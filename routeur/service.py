"""Orchestration : météo → route → fichiers publiés pour l'interface (web/data/).

Un verrou de fichier empêche deux calculs simultanés (tâche planifiée + bouton « recalculer »).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .config import resolve
from .course import Course
from .geo import LandMask
from .gfs import GfsStore
from .isochrones import Router, RoutingParams
from .polar import Polar
from .roadmap import build_roadmap, check_legs, compare, iso, route_document, to_csv, to_gpx
from .wind import WindField

log = logging.getLogger("routeur.service")

STALE_AFTER_H = 9.0   # un cycle GFS sort toutes les 6 h ; au-delà de 9 h on prévient


class Busy(RuntimeError):
    pass


@contextmanager
def file_lock(path: Path):
    """Verrou exclusif non bloquant, libéré automatiquement si le processus meurt."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+")
    try:
        if sys.platform == "win32":
            import msvcrt
            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise Busy("un calcul est déjà en cours") from exc
        else:
            import fcntl
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise Busy("un calcul est déjà en cours") from exc
        yield
    finally:
        if sys.platform == "win32":
            try:
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        fh.close()


def write_json(path: Path, data, compact=False) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":") if compact else None,
                              indent=None if compact else 1), encoding="utf-8")
    os.replace(tmp, path)


class Service:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.out = resolve(cfg["service"]["output_dir"])
        self.out.mkdir(parents=True, exist_ok=True)
        self.store = GfsStore(cfg, status_path=self.out / "weather-status.json")
        self.course = Course.load(resolve(cfg["course"]["file"]))
        self._polar = self._mask = None
        src = resolve(self.course.forbidden_geojson) if self.course.forbidden_geojson else None
        dst = self.out / "course.geojson"
        if src and src.exists() and (not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime):
            shutil.copyfile(src, dst)

    @property
    def polar(self) -> Polar:
        if self._polar is None:
            pc = self.cfg["polar"]
            self._polar = Polar.load(resolve(pc["file"]), self.cfg["boat"],
                                     resolve(pc["stamina_file"]) if pc.get("stamina_file") else None,
                                     pc.get("stamina_boat_factor", 1.0))
        return self._polar

    @property
    def mask(self) -> LandMask:
        if self._mask is None:
            path = resolve("data/geo/mask.npz")
            if not path.exists():
                raise FileNotFoundError("masque absent : lancer « python -m routeur masque »")
            self._mask = LandMask.load(path)
        return self._mask

    # --- état publié ---------------------------------------------------------------------------

    def status(self, **route) -> dict:
        p = self.out / "status.json"
        st = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        cur = self.store.current()
        if cur:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(cur["run"])).total_seconds() / 3600
            st["weather"] = {"cycle": cur["cycle"], "run": cur["run"], "max_hour": cur["max_hour"],
                             "fetched_at": cur["updated_at"], "age_h": round(age, 1),
                             "stale": age > STALE_AFTER_H,
                             "incomplete": cur["max_hour"] < self.cfg["gfs"]["max_hour"]}
        if route:
            st["route"] = {**st.get("route", {}), **route}
        st["race"] = {"name": self.course.name, "start_time": iso(self.course.start_time)}
        st["updated_at"] = iso(time.time())
        write_json(p, st)
        return st

    # --- météo -------------------------------------------------------------------------------

    def update_weather(self) -> dict:
        res = self.store.update()
        if res.get("path") and (res.get("changed") or not (self.out / "wind.json").exists()):
            self.export_wind(WindField.load(res["path"]))
        self.status()
        return res

    def export_wind(self, wind: WindField, step_deg: float = 1.0, every_h: int = 6) -> None:
        """Champ de vent allégé pour la carte : grille 1°, toutes les 6 h, U/V en int8 (0,5 m/s)."""
        lats = np.arange(np.ceil(wind.lats[0]), wind.lats[-1] + 1e-6, step_deg)
        lons = np.arange(np.ceil(wind.lons[0]), wind.lons[-1] + 1e-6, step_deg)
        times = np.arange(wind.start, wind.end + 1, every_h * 3600)
        glat, glon = np.meshgrid(lats, lons, indexing="ij")
        frames = []
        for t in times:
            u, v = wind.uv(glat.ravel(), glon.ravel(), t)
            q = np.clip(np.round(np.stack([u, v]) * 2), -127, 127).astype(np.int8)
            frames.append({"t": iso(t), "uv": base64.b64encode(q.tobytes()).decode()})
        write_json(self.out / "wind.json", {"format": "routeur-rhum/wind@1", "lat0": float(lats[0]),
                                            "lon0": float(lons[0]), "step": step_deg, "nlat": int(lats.size),
                                            "nlon": int(lons.size), "scale_ms": 0.5,
                                            "run": iso(wind.run), "frames": frames}, compact=True)

    # --- route -------------------------------------------------------------------------------

    def start_state(self, now: float | None = None, override: dict | None = None) -> dict:
        """Point de départ : ligne de départ avant le coup de canon, sinon position du bateau."""
        now = now or time.time()
        if override:
            return override
        pos_file = resolve("data/position.json")
        if now < self.course.start_time:
            return {"time": self.course.start_time, "lat": self.course.start_lat, "lon": self.course.start_lon,
                    "gate": 0, "source": "ligne de départ"}
        if pos_file.exists():
            pos = json.loads(pos_file.read_text(encoding="utf-8"))
            age_h = (now - pos["time"]) / 3600
            if age_h < 12:
                return {**pos, "time": max(pos["time"], now - 1800), "source": f"position saisie ({age_h:.1f} h)"}
        prev = self.out / "route.json"
        if prev.exists():  # estimation : on suppose que le bateau suit la route précédente
            doc = json.loads(prev.read_text(encoding="utf-8"))
            ts = np.array([datetime.fromisoformat(p[2].replace("Z", "+00:00")).timestamp() for p in doc["track"]])
            if ts[0] <= now <= ts[-1]:
                k = int(np.searchsorted(ts, now))
                return {"time": now, "lat": float(np.interp(now, ts, [p[0] for p in doc["track"]])),
                        "lon": float(np.interp(now, ts, [p[1] for p in doc["track"]])),
                        "gate": int(doc.get("gates_passed_track", [0] * len(ts))[min(k, len(ts) - 1)]),
                        "source": "estimée sur la route précédente (saisir la position réelle !)"}
        return {"time": now, "lat": self.course.start_lat, "lon": self.course.start_lon, "gate": 0,
                "source": "ligne de départ (aucune position connue)"}

    def compute_route(self, wind_path: str | Path | None = None, start: dict | None = None,
                      progress=None) -> dict:
        cur = self.store.current()
        wind_path = wind_path or (cur and cur["path"])
        if not wind_path:
            raise FileNotFoundError("aucune prévision GFS disponible : lancer « python -m routeur meteo »")
        wind = WindField.load(wind_path)
        st = self.start_state(override=start)
        params = RoutingParams.from_config(self.cfg)
        self.status(state="calcul", message=f"Calcul depuis {st['source']}", started_at=iso(time.time()))
        router = Router(wind, self.polar, self.mask, self.course, params)
        res = router.run(start_time=st["time"], start=(st["lat"], st["lon"]), start_gate=st.get("gate", 0),
                         start_sail=st.get("sail", -1), start_twa=st.get("twa", 0.0), progress=progress)
        gate_names = [g.name for g in self.course.gates]
        rm = build_roadmap(res, self.polar, self.mask, gate_names, self.cfg["routing"]["simplify_tolerance_nm"],
                           wind=wind)
        check = check_legs(rm["waypoints"], wind, self.polar)
        meta = {"race": self.course.name, "boat": self.polar.label, "polar_file": self.polar.source,
                "gfs_cycle": (cur or {}).get("cycle") if not start or wind_path == (cur or {}).get("path") else None,
                "gfs_run": iso(wind.run) if wind.run else None, "wind_file": str(wind_path),
                "start_source": st["source"], "start": {"lat": st["lat"], "lon": st["lon"]},
                "start_gate": int(st.get("gate", 0)),
                "options": self.cfg["boat"], "sail_names": self.polar.sail_names,
                "gates": [{"name": g.name, "a": g.a, "b": g.b, "cross": g.cross} for g in self.course.gates]}
        doc = route_document(res, rm, meta, check)
        doc["gates_passed_track"] = [p.gate for p in res.points]
        out_route = self.out / "route.json"
        prev = json.loads(out_route.read_text(encoding="utf-8")) if out_route.exists() else None
        doc["comparison"] = compare(prev, doc)
        if prev:
            shutil.copyfile(out_route, self.out / "route-prev.json")
        write_json(out_route, doc, compact=True)
        (self.out / "feuille-de-route.csv").write_text(to_csv(doc), encoding="utf-8-sig")
        (self.out / "feuille-de-route.gpx").write_text(to_gpx(doc), encoding="utf-8")
        msg = (f"Arrivée estimée {doc['eta']} ({doc['duration_h']:.1f} h)" if res.arrived
               else "Arrivée non atteinte dans la durée maximale de calcul")
        self.status(state="ok" if res.arrived else "incomplet", message=msg, computed_at=doc["computed_at"],
                    gfs_cycle=doc["gfs_cycle"], compute_s=res.stats["compute_s"], eta=doc["eta"])
        log.info("route calculée : %s, %d waypoints, %d changements de voile, %.0f s", msg,
                 len(doc["waypoints"]), len(doc["sail_changes"]), res.stats["compute_s"])
        return doc

    def explanation_stale(self) -> bool:
        """Vrai si l'explication manque, a échoué, ou décrit une autre route que celle affichée."""
        from .explain import PROMPT_VERSION, has_credentials
        if not has_credentials():
            return False
        p = self.out / "explain.json"
        if not p.exists():
            return True
        x = json.loads(p.read_text(encoding="utf-8"))
        src = self.out / ("route-safe.json" if (self.out / "route-safe.json").exists() else "route.json")
        shown = json.loads(src.read_text(encoding="utf-8")).get("computed_at") if src.exists() else None
        return x.get("state") != "ok" or x.get("for_route") != shown or x.get("prompt") != PROMPT_VERSION

    def write_explanation(self) -> dict:
        """Explication par Claude de la route affichée par défaut (conseillée si elle existe)."""
        from .explain import explain
        safe, main = self.out / "route-safe.json", self.out / "route.json"
        src = safe if safe.exists() else main
        if not src.exists():
            return {"state": "pas de route"}
        route = json.loads(src.read_text(encoding="utf-8"))
        ens_p = self.out / "ensemble.json"
        ens = json.loads(ens_p.read_text(encoding="utf-8")) if ens_p.exists() else None
        res = explain(route, ens, self.cfg)
        write_json(self.out / "explain.json", res)
        return res

    def ensemble_cycle(self, force: bool = False) -> dict:
        """Tâche planifiée n° 2 : scénarios GEFS, recalculés si nouveau cycle GEFS ou nouvelle route GFS."""
        from .ensemble import EnsembleStore, run_ensemble
        with file_lock(resolve("data/.ensemble.lock")):
            store = EnsembleStore(self.cfg, self.out / "ensemble-status.json")
            upd = store.update()
            ens, route = self.out / "ensemble.json", self.out / "route.json"
            if not route.exists():
                return {"ensemble": "pas encore de route GFS"}
            stale = not ens.exists() or ens.stat().st_mtime < route.stat().st_mtime
            if not (force or upd.get("changed") or stale):
                log.info("scénarios inchangés (GEFS %s)", upd.get("cycle"))
                return {"ensemble": "inchangé", "gefs": upd.get("cycle")}

            def progress(msg, done, total):
                store.status(state="calcul", cycle=upd["cycle"], done=done, total=total, message=msg)

            doc = run_ensemble(self, upd["members"], upd["cycle"], progress)
            store.status(state="ok", cycle=upd["cycle"], done=doc["scenarios"], total=doc["scenarios"],
                         message=f"{doc['routes_found']} routes calculées, conseillée : {doc['recommended_label']}")
            self.write_explanation()
            return {"ensemble": doc["recommended"], "gain_h": doc["gain_vs_gfs_h"], "spread_h": doc["spread_h"]}

    def cycle(self, force_route: bool = False) -> dict:
        """Tâche planifiée : nouvelle météo ? → nouvelle route. Sans effet si rien n'a changé."""
        with file_lock(resolve(self.cfg["service"]["lock_file"])):
            w = self.update_weather()
            route_file = self.out / "route.json"
            pos_file = resolve("data/position.json")
            pos_newer = pos_file.exists() and route_file.exists() and pos_file.stat().st_mtime > route_file.stat().st_mtime
            need = force_route or w.get("changed") or not route_file.exists() or pos_newer
            if not need:
                log.info("météo inchangée (%s) : route conservée", w.get("cycle"))
                self.status()
                if self.explanation_stale():
                    self.write_explanation()
                return {"weather": w, "route": "inchangée"}
            try:
                doc = self.compute_route()
            except Exception as exc:
                log.exception("calcul de route échoué")
                self.status(state="erreur", message=f"Calcul de route échoué : {exc}")
                raise
            self.write_explanation()
            return {"weather": w, "route": {"eta": doc["eta"], "waypoints": len(doc["waypoints"])}}
