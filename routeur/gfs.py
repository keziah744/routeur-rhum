"""Récupération des prévisions GFS 0,25° (vent à 10 m) et mise en cache.

Source principale : filtre NOMADS (sous-zone + variables, ~260 Ko par échéance).
Secours : miroir NOAA sur AWS S3 (index .idx + lecture par plages d'octets, globe entier, recadré ici).

Organisation sur disque (data/gfs/) :
  <AAAAMMJJHH>/fFFF.grb2   fichiers bruts validés
  <AAAAMMJJHH>/manifest.json  provenance de chaque fichier
  <AAAAMMJJHH>/forecast.npz   grille empilée prête pour le routeur
  current.json              pointe vers le dernier cycle valide
  status.json               progression de la dernière mise à jour
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from .config import resolve
from .grib import GribError, WindMessage, decode_wind_file

log = logging.getLogger("routeur.gfs")

NOMADS = "https://nomads.ncep.noaa.gov"
S3 = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
UA = "routeur-rhum/0.1 (routage perso Virtual Regatta)"


class FetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class Cycle:
    run: datetime  # UTC

    @property
    def date(self) -> str:
        return self.run.strftime("%Y%m%d")

    @property
    def hh(self) -> str:
        return self.run.strftime("%H")

    @property
    def key(self) -> str:
        return self.run.strftime("%Y%m%d%H")

    @classmethod
    def from_key(cls, key: str) -> "Cycle":
        return cls(datetime.strptime(key, "%Y%m%d%H").replace(tzinfo=timezone.utc))

    def __str__(self) -> str:
        return f"GFS {self.date} {self.hh}z"


def recent_cycles(now: datetime, count: int = 6) -> list[Cycle]:
    """Cycles 00/06/12/18 z les plus récents, du plus récent au plus ancien."""
    base = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    base = base.replace(hour=base.hour - base.hour % 6)
    return [Cycle(base - timedelta(hours=6 * i)) for i in range(count)]


# --- accès réseau -----------------------------------------------------------------------------

def http_get(url: str, timeout: float, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def with_retries(fn, retries: int, what: str):
    delay = 5.0
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except (urllib.error.URLError, TimeoutError, ConnectionError, GribError, FetchError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 404:
                raise FetchError(f"{what}: absent (404)") from exc
            log.warning("%s: tentative %d/%d échouée (%s)", what, attempt, retries, exc)
            if attempt == retries:
                raise FetchError(f"{what}: {exc}") from exc
            time.sleep(delay)
            delay = min(delay * 2, 60)


@dataclass(frozen=True)
class Product:
    """Un jeu de fichiers NOAA : GFS déterministe ou un membre de l'ensemble GEFS."""
    name: str
    listing_base: str     # racine NOMADS des dossiers de cycles
    cycle_dir: str        # dossier d'un cycle ({date}, {hh})
    file: str             # nom de fichier ({hh}, {fh})
    filter_script: str    # script de filtre NOMADS
    s3: str               # miroir AWS

    def filename(self, cycle: Cycle, fh: int) -> str:
        return self.file.format(hh=cycle.hh, fh=fh)

    def path(self, cycle: Cycle) -> str:
        return self.cycle_dir.format(date=cycle.date, hh=cycle.hh)

    def hours_in(self, text: str, cycle: Cycle) -> list[int]:
        prefix = re.escape(self.file.split("{fh")[0].format(hh=cycle.hh))
        return sorted({int(m) for m in re.findall(prefix + r"(\d{3})\.idx", text)})


GFS = Product("NCEP GFS 0.25°", "/pub/data/nccf/com/gfs/prod", "/gfs.{date}/{hh}/atmos",
              "gfs.t{hh}z.pgrb2.0p25.f{fh:03d}", "filter_gfs_0p25.pl", S3)


def gefs_member(member: str) -> Product:
    """member : gec00 (contrôle) ou gep01 … gep30."""
    return Product(f"NCEP GEFS 0.5° {member}", "/pub/data/nccf/com/gens/prod", "/gefs.{date}/{hh}/atmos/pgrb2ap5",
                   member + ".t{hh}z.pgrb2a.0p50.f{fh:03d}", "filter_gefs_atmos_0p50a.pl",
                   "https://noaa-gefs-pds.s3.amazonaws.com")


def listing(cycle: Cycle, timeout: float = 30, product: Product = GFS) -> str:
    """Page NOMADS du dossier d'un cycle ; "" si le cycle n'existe pas ou est en cours de création."""
    url = f"{NOMADS}{product.listing_base}{product.path(cycle)}/"
    try:
        return http_get(url, timeout).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        # NOMADS répond 403 sur un dossier de cycle encore en cours de création, 404 s'il n'existe pas.
        if exc.code in (403, 404):
            return ""
        raise


def available_hours(cycle: Cycle, timeout: float = 30, product: Product = GFS) -> list[int]:
    """Échéances publiées et complètes (index .idx présent) d'un cycle sur NOMADS."""
    return product.hours_in(listing(cycle, timeout, product), cycle)


def available_hours_s3(cycle: Cycle, timeout: float = 30, product: Product = GFS) -> list[int]:
    """Même information depuis le miroir AWS (secours si NOMADS ne répond pas)."""
    prefix = product.path(cycle).lstrip("/") + "/" + product.file.split("{fh")[0].format(hh=cycle.hh)
    xml = http_get(f"{product.s3}/?list-type=2&prefix={prefix}", timeout).decode("utf-8", "replace")
    return product.hours_in(xml.replace("</Key>", ""), cycle)


def nomads_url(cycle: Cycle, fh: int, bbox: dict, product: Product = GFS) -> str:
    d = product.path(cycle).replace("/", "%2F")
    return (f"{NOMADS}/cgi-bin/{product.filter_script}?dir={d}"
            f"&file={product.filename(cycle, fh)}&var_UGRD=on&var_VGRD=on"
            f"&lev_10_m_above_ground=on&subregion=&toplat={bbox['lat_max']}&bottomlat={bbox['lat_min']}"
            f"&leftlon={bbox['lon_min']}&rightlon={bbox['lon_max']}")


def s3_key(cycle: Cycle, fh: int, product: Product = GFS) -> str:
    return product.path(cycle).lstrip("/") + "/" + product.filename(cycle, fh)


def s3_wind_bytes(cycle: Cycle, fh: int, timeout: float, product: Product = GFS) -> bytes:
    """Lit uniquement les messages UGRD/VGRD 10 m du fichier global sur S3."""
    base = f"{product.s3}/{s3_key(cycle, fh, product)}"
    idx = http_get(base + ".idx", timeout).decode()
    lines = [l.split(":") for l in idx.splitlines() if l]
    out = b""
    for var in ("UGRD", "VGRD"):
        for i, parts in enumerate(lines):
            if parts[3] == var and parts[4] == "10 m above ground":
                start = int(parts[1])
                end = int(lines[i + 1][1]) - 1 if i + 1 < len(lines) else ""
                out += http_get(base, timeout, {"Range": f"bytes={start}-{end}"})
                break
        else:
            raise FetchError(f"{var} 10 m absent de l'index S3")
    return out


def crop(msg: WindMessage, bbox: dict) -> WindMessage:
    j = (msg.lats >= bbox["lat_min"] - 1e-6) & (msg.lats <= bbox["lat_max"] + 1e-6)
    i = (msg.lons >= bbox["lon_min"] - 1e-6) & (msg.lons <= bbox["lon_max"] + 1e-6)
    return WindMessage(msg.run, msg.forecast_hour, msg.lats[j], msg.lons[i],
                       msg.u[np.ix_(j, i)], msg.v[np.ix_(j, i)])


# --- cache et cycle courant -------------------------------------------------------------------

class GfsStore:
    def __init__(self, cfg: dict, root: Path | None = None, status_path: Path | None = None,
                 product: Product = GFS, section: str = "gfs"):
        self.cfg = {**cfg["gfs"], **cfg.get(section, {})}
        self.product = product
        self.root = root or resolve("data/gfs")
        self.root.mkdir(parents=True, exist_ok=True)
        self.status_path = status_path or self.root / "status.json"
        self.bbox = {k: self.cfg[k] for k in ("lat_min", "lat_max", "lon_min", "lon_max")}

    # état visible par l'interface
    def write_status(self, **status) -> None:
        status["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        tmp = self.status_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.status_path)

    def current(self) -> dict | None:
        p = self.root / "current.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def set_current(self, info: dict) -> None:
        tmp = self.root / "current.json.tmp"
        tmp.write_text(json.dumps(info, indent=1), encoding="utf-8")
        os.replace(tmp, self.root / "current.json")

    def wanted_hours(self, published: list[int]) -> list[int]:
        step, mx = self.cfg["step_hours"], self.cfg["max_hour"]
        pub = set(published)
        return [h for h in range(0, mx + 1, step) if h in pub]

    def find_latest_cycle(self, now: datetime) -> tuple[Cycle, list[int]] | None:
        """Cycle le plus récent dont la publication atteint min_usable_hour."""
        for cycle in recent_cycles(now):
            try:
                hours = with_retries(lambda c=cycle: available_hours(c, self.cfg["timeout_s"], self.product),
                                     self.cfg["retries"], f"liste NOMADS {cycle}")
            except FetchError as exc:
                log.warning("NOMADS indisponible (%s) : liste lue sur le miroir AWS", exc)
                hours = with_retries(lambda c=cycle: available_hours_s3(c, self.cfg["timeout_s"], self.product),
                                     self.cfg["retries"], f"liste AWS {cycle}")
            time.sleep(self.cfg["request_pause_s"])
            if hours and max(hours) >= self.cfg["min_usable_hour"]:
                return cycle, hours
            log.info("%s: %s", cycle, f"publié jusqu'à +{max(hours)} h" if hours else "pas encore publié")
        return None

    def fetch_hour(self, cycle: Cycle, fh: int, dest: Path) -> dict:
        """Télécharge et valide une échéance. Renvoie l'entrée de manifeste."""
        timeout, retries = self.cfg["timeout_s"], self.cfg["retries"]
        url = nomads_url(cycle, fh, self.bbox, self.product)

        def from_nomads():
            data = http_get(url, timeout)
            if not data.startswith(b"GRIB"):
                raise FetchError("réponse NOMADS non GRIB (page d'erreur ou limite de requêtes)")
            return data, "nomads-filter", url

        def from_s3():
            return (s3_wind_bytes(cycle, fh, timeout, self.product), "aws-s3-range",
                    f"{self.product.s3}/{s3_key(cycle, fh, self.product)}")

        last_exc = None
        order = (from_s3, from_nomads) if self.cfg.get("prefer_s3") else (from_nomads, from_s3)
        for source in order:
            try:
                data, kind, src = with_retries(source, retries, f"{cycle} f{fh:03d} ({source.__name__})")
                tmp = dest.with_suffix(".part")
                tmp.write_bytes(data)
                msg = decode_wind_file(tmp)
                if msg.forecast_hour != fh or msg.run != cycle.run:
                    raise GribError(f"fichier reçu pour {msg.run} +{msg.forecast_hour} h au lieu de {cycle} +{fh} h")
                if kind == "aws-s3-range":
                    msg = crop(msg, self.bbox)
                    np.savez_compressed(dest.with_suffix(".npz"), lats=msg.lats, lons=msg.lons, u=msg.u, v=msg.v)
                os.replace(tmp, dest)
                return {"hour": fh, "source": kind, "url": src, "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            except (FetchError, GribError) as exc:
                last_exc = exc
                log.warning("%s f%03d: %s", cycle, fh, exc)
        raise FetchError(f"{cycle} f{fh:03d} introuvable sur NOMADS et S3: {last_exc}")

    def load_hour(self, path: Path) -> WindMessage:
        npz = path.with_suffix(".npz")
        if npz.exists():  # fichier global S3 déjà recadré
            d = np.load(npz)
            msg = decode_wind_file(path)
            return WindMessage(msg.run, msg.forecast_hour, d["lats"], d["lons"], d["u"], d["v"])
        return decode_wind_file(path)

    def download(self, cycle: Cycle, published: list[int]) -> Path:
        cdir = self.root / cycle.key
        cdir.mkdir(exist_ok=True)
        man_path = cdir / "manifest.json"
        manifest = json.loads(man_path.read_text(encoding="utf-8")) if man_path.exists() else {"files": {}}
        manifest.update({"cycle": cycle.key, "run": cycle.run.isoformat(), "model": self.product.name,
                         "variables": "UGRD,VGRD 10 m above ground", "bbox": self.bbox})
        hours = self.wanted_hours(published)
        for n, fh in enumerate(hours):
            dest = cdir / f"f{fh:03d}.grb2"
            if dest.exists() and str(fh) in manifest["files"]:
                continue
            self.write_status(state="téléchargement", cycle=cycle.key, done=n, total=len(hours),
                              message=f"{cycle} échéance +{fh} h")
            manifest["files"][str(fh)] = self.fetch_hour(cycle, fh, dest)
            man_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
            time.sleep(self.cfg["request_pause_s"])
        manifest["complete_until_hour"] = max(hours)
        man_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        return cdir

    def build_forecast(self, cdir: Path) -> Path:
        """Empile toutes les échéances d'un cycle dans forecast.npz (heures valides croissantes)."""
        manifest = json.loads((cdir / "manifest.json").read_text(encoding="utf-8"))
        hours = sorted(int(h) for h in manifest["files"])
        msgs = [self.load_hour(cdir / f"f{h:03d}.grb2") for h in hours]
        lats, lons = msgs[0].lats, msgs[0].lons
        for m in msgs:
            if m.u.shape != (lats.size, lons.size):
                raise GribError(f"grille différente à +{m.forecast_hour} h")
        # Contrôle de continuité : pas de trou dans les échéances.
        gaps = [b - a for a, b in zip(hours, hours[1:]) if b - a > self.cfg["step_hours"]]
        if gaps:
            raise GribError(f"échéances manquantes (écart max {max(gaps)} h)")
        run = msgs[0].run
        valid = np.array([(run + timedelta(hours=h)).timestamp() for h in hours])
        out = cdir / "forecast.npz"
        tmp = cdir / "forecast.tmp.npz"
        np.savez(tmp, run=run.timestamp(), hours=np.array(hours), valid=valid, lats=lats, lons=lons,
                 u=np.stack([m.u for m in msgs]), v=np.stack([m.v for m in msgs]))
        os.replace(tmp, out)
        return out

    def prune(self) -> None:
        cur = (self.current() or {}).get("cycle")
        dirs = sorted(d for d in self.root.iterdir() if d.is_dir() and re.fullmatch(r"\d{10}", d.name))
        for d in dirs[:-self.cfg["keep_cycles"]]:
            if d.name != cur:
                shutil.rmtree(d, ignore_errors=True)
                log.info("ancien cycle supprimé du cache: %s", d.name)

    def update(self, now: datetime | None = None) -> dict:
        """Récupère le dernier cycle utilisable. Garde le précédent en cas d'échec.

        Renvoie {"changed": bool, "cycle": key, ...}.
        """
        now = now or datetime.now(timezone.utc)
        cur = self.current()
        try:
            found = self.find_latest_cycle(now)
            if found is None:
                raise FetchError("aucun cycle récent assez publié (retard NOAA ?)")
            cycle, published = found
            target_max = max(self.wanted_hours(published))
            if cur and cur["cycle"] == cycle.key and cur["max_hour"] >= min(target_max, self.cfg["max_hour"]):
                self.write_status(state="à jour", cycle=cycle.key, done=1, total=1,
                                  message=f"{cycle} déjà en cache")
                return {"changed": False, **cur}
            log.info("nouveau cycle: %s (publié jusqu'à +%d h)", cycle, max(published))
            cdir = self.download(cycle, published)
            self.build_forecast(cdir)
            info = {"cycle": cycle.key, "run": cycle.run.isoformat(), "max_hour": target_max,
                    "path": str(cdir / "forecast.npz"),
                    "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            changed = not cur or cur["cycle"] != cycle.key or cur["max_hour"] != target_max
            self.set_current(info)
            self.write_status(state="ok", cycle=cycle.key, done=1, total=1, message=f"{cycle} prêt")
            self.prune()
            return {"changed": changed, **info}
        except Exception as exc:
            log.error("mise à jour GFS échouée: %s", exc)
            self.write_status(state="erreur", cycle=(cur or {}).get("cycle"), done=0, total=0,
                              message=f"Échec de la mise à jour : {exc}. Dernière prévision valide conservée.")
            if cur is None:
                raise
            return {"changed": False, "error": str(exc), **cur}
