"""Orchestration : météo → route(s) → fichiers publiés pour l'interface (web/data/).

Plusieurs bateaux (config [[boats]]) : météo et scénarios GEFS partagés, une position, une route, une feuille
de route et une explication par bateau dans web/data/bateaux/<id>/. Deux bateaux qui partent du même point
(avant le départ, typiquement) ne sont calculés qu'une fois.
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
from .wind import SwitchedWind, WindField

log = logging.getLogger("routeur.service")

# Un run GFS sort toutes les 6 h et n'est complet (+240 h) que ~5 h après : en temps normal la météo utilisée a
# jusqu'à ~12 h (6 + 5 + 1 h entre deux calculs). Au-delà de 13 h, un run a vraiment été manqué.
STALE_AFTER_H = 13.0
DEFAULT_BOATS = [{"id": "keziah", "name": "Keziah"}]
# Fichiers propres à chaque bateau (les autres de web/data/ sont partagés).
BOAT_FILES = ("route.json", "route-prev.json", "route-safe.json", "ensemble.json", "explain.json", "status.json",
              "feuille-de-route.csv", "feuille-de-route.gpx")


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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":") if compact else None,
                              indent=None if compact else 1), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def boats_of(cfg: dict) -> list[dict]:
    return cfg.get("boats") or DEFAULT_BOATS


def position_file(boat: str) -> Path:
    return resolve(f"data/positions/{boat}.json")


# Options VR (clés de [boat] dans config.toml), dans l'ordre de la page.
OPTION_KEYS = ("foils", "hull", "winch_pro", "auto_sail", "light_sails", "heavy_sails", "reach_sail")


def options_file(boat: str) -> Path:
    return resolve(f"data/positions/{boat}.options.json")


def prog_file(boat: str) -> Path:
    """Fin des ordres programmés dans le jeu ({"time", "until"}), indiquée depuis l'onglet Ordres."""
    return resolve(f"data/positions/{boat}.prog.json")


def boat_options(cfg: dict, boat: str) -> tuple[dict, bool]:
    """Options VR du bateau et si elles ont été choisies : celles cochées dans la page, sinon [boats.options],
    sinon [boat] par défaut (non choisies : la page demande de les cocher avant tout le reste)."""
    entry = next((b for b in boats_of(cfg) if b["id"] == boat), {})
    opts = {**(cfg.get("boat") or {}), **(entry.get("options") or {})}
    chosen = bool(entry.get("options"))
    sent = read_json(options_file(boat))
    if sent and isinstance(sent.get("options"), dict):
        opts.update({k: bool(v) for k, v in sent["options"].items() if k in OPTION_KEYS})
        chosen = True
    return {k: bool(opts.get(k, False)) for k in OPTION_KEYS}, chosen


class Service:
    def __init__(self, cfg: dict, boat: str | None = None):
        self.cfg = cfg
        self.boats = boats_of(cfg)
        self.boat = boat or self.boats[0]["id"]
        if self.boat not in {b["id"] for b in self.boats}:
            raise ValueError(f"bateau inconnu : {self.boat}")
        # Options VR : celles cochées dans la page, sinon [boats.options], sinon [boat].
        self.options, _ = boat_options(cfg, self.boat)
        self.out = resolve(cfg["service"]["output_dir"])
        self.bout = self.out / "bateaux" / self.boat
        self.bout.mkdir(parents=True, exist_ok=True)
        self._migrate()
        self.store = GfsStore(cfg, status_path=self.out / "weather-status.json")
        self.course = Course.load(resolve(cfg["course"]["file"]))
        self._polar = self._mask = None
        src = resolve(self.course.forbidden_geojson) if self.course.forbidden_geojson else None
        dst = self.out / "course.geojson"
        if src and src.exists() and (not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime):
            shutil.copyfile(src, dst)
        from .relay import boats_public
        pub = boats_public(cfg)
        if read_json(self.out / "boats.json") != pub:
            write_json(self.out / "boats.json", pub)

    def _migrate(self) -> None:
        """Ancienne version à un seul bateau : ses fichiers passent au premier bateau."""
        if self.boat != self.boats[0]["id"]:
            return
        for name in BOAT_FILES:
            old = self.out / name
            if old.exists() and not (self.bout / name).exists() and name != "status.json":
                shutil.move(str(old), self.bout / name)
        old_pos = resolve("data/position.json")
        if old_pos.exists() and not position_file(self.boat).exists():
            position_file(self.boat).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_pos), position_file(self.boat))

    @property
    def polar(self) -> Polar:
        if self._polar is None:
            pc = self.cfg["polar"]
            self._polar = Polar.load(resolve(pc["file"]), self.options,
                                     resolve(pc["stamina_file"]) if pc.get("stamina_file") else None,
                                     pc.get("stamina_boat_factor", 1.0))
        return self._polar

    @property
    def mask(self) -> LandMask:
        if self._mask is None:
            try:  # mask.npz entier (PC) ou en morceaux mask.npz.part* (dépôt publié)
                self._mask = LandMask.load(resolve("data/geo/mask.npz"))
            except FileNotFoundError as exc:
                raise FileNotFoundError("masque absent : lancer « python -m routeur masque »") from exc
        return self._mask

    # --- état publié ---------------------------------------------------------------------------

    def status(self) -> dict:
        """État partagé : météo et course (web/data/status.json)."""
        p = self.out / "status.json"
        st = read_json(p) or {}
        st.pop("route", None)
        cur = self.store.current()
        if cur:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(cur["run"])).total_seconds() / 3600
            st["weather"] = {"cycle": cur["cycle"], "run": cur["run"], "max_hour": cur["max_hour"],
                             "fetched_at": cur["updated_at"], "age_h": round(age, 1),
                             "stale": age > STALE_AFTER_H,
                             "incomplete": cur["max_hour"] < self.cfg["gfs"]["max_hour"]}
        st["race"] = {"name": self.course.name, "start_time": iso(self.course.start_time)}
        st["updated_at"] = iso(time.time())
        write_json(p, st)
        return st

    def route_status(self, **route) -> dict:
        """État du calcul de route de ce bateau (web/data/bateaux/<id>/status.json)."""
        p = self.bout / "status.json"
        st = {**(read_json(p) or {}), **route, "updated_at": iso(time.time())}
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

    def followed_route(self) -> dict | None:
        """Route que le bateau est censé suivre : celle que la page affiche par défaut (la conseillée si elle part
        du même point que la route GFS, sinon la route GFS)."""
        main = read_json(self.bout / "route.json")
        safe = read_json(self.bout / "route-safe.json")
        if main and safe and (safe.get("start_time"), safe.get("start")) == (main.get("start_time"), main.get("start")):
            return safe
        return main

    @staticmethod
    def along(doc: dict, t: float) -> dict | None:
        """Position, porte, voile et TWA prévues sur la route à l'instant t (None hors de la route)."""
        tr = doc.get("track") or []
        if not tr:
            return None
        ts = np.array([datetime.fromisoformat(p[2].replace("Z", "+00:00")).timestamp() for p in tr])
        if not ts[0] <= t <= ts[-1]:
            return None
        k = max(0, min(int(np.searchsorted(ts, t, side="right")) - 1, len(tr) - 1))  # dernier point déjà passé
        gates = doc.get("gates_passed_track") or []
        return {"time": t, "lat": float(np.interp(t, ts, [p[0] for p in tr])),
                "lon": float(np.interp(t, ts, [p[1] for p in tr])),
                "gate": int(gates[k]) if k < len(gates) else int(doc.get("start_gate", 0)),
                "sail": int(tr[k][3]), "twa": float(tr[k][5])}

    def start_state(self, now: float | None = None, override: dict | None = None) -> dict:
        """Point de départ du calcul.

        Avant le coup de canon : la ligne de départ. Ensuite, la position du jeu si la route en cours ne la connaît
        pas encore (à son heure réelle : le bateau a avancé depuis). Sinon, on suppose que le bateau a suivi la route
        calculée depuis sa dernière position et on l'avance le long de cette route jusqu'à maintenant.
        """
        now = now or time.time()
        if override:
            return override
        if now < self.course.start_time:
            return {"time": self.course.start_time, "lat": self.course.start_lat, "lon": self.course.start_lon,
                    "gate": 0, "source": "ligne de départ"}
        pos = read_json(position_file(self.boat))
        route = self.followed_route()
        r_start = datetime.fromisoformat(route["start_time"].replace("Z", "+00:00")).timestamp() if route else None
        if pos and (r_start is None or pos["time"] > r_start + 60):
            age_min = (now - pos["time"]) / 60
            when = f"il y a {age_min:.0f} min" if age_min < 90 else f"il y a {age_min / 60:.1f} h"
            return {**pos, "time": max(pos["time"], now - 1800) if age_min <= 30 else pos["time"],
                    "source": f"position saisie ({when})"}
        est = self.along(route, now) if route else None
        if est:
            last = (f"dernière position il y a {(now - pos['time']) / 3600:.1f} h" if pos
                    else "aucune position saisie")
            return {**est, "source": f"estimée sur la route suivie ({last})"}
        if pos:
            return {**pos, "source": "position saisie (route précédente terminée)"}
        return {"time": now, "lat": self.course.start_lat, "lon": self.course.start_lon, "gate": 0,
                "source": "ligne de départ (aucune position connue)"}

    def compute_route(self, wind_path: str | Path | None = None, start: dict | None = None,
                      progress=None) -> dict:
        cur = self.store.current()
        given = wind_path
        wind_path = wind_path or (cur and cur["path"])
        if not wind_path:
            raise FileNotFoundError("aucune prévision GFS disponible : lancer « python -m routeur meteo »")
        wind = WindField.load(wind_path)
        switch = None
        if not given:
            wind, switch = self.game_wind(wind, cur)
        st = self.start_state(override=start)
        params = RoutingParams.from_config(self.cfg)
        self.route_status(state="calcul", message=f"Calcul depuis {st['source']}", started_at=iso(time.time()))
        router = Router(wind, self.polar, self.mask, self.course, params)
        res = router.run(start_time=st["time"], start=(st["lat"], st["lon"]), start_gate=st.get("gate", 0),
                         start_sail=st.get("sail", -1), start_twa=st.get("twa", 0.0), progress=progress)
        gate_names = [g.name for g in self.course.gates]
        rm = build_roadmap(res, self.polar, self.mask, gate_names, self.cfg["routing"]["simplify_tolerance_nm"],
                           wind=wind)
        check = check_legs(rm["waypoints"], wind, self.polar)
        meta = {"race": self.course.name, "boat": self.polar.label, "polar_file": self.polar.source,
                "skipper": self.boat,
                "gfs_cycle": (cur or {}).get("cycle") if not start or wind_path == (cur or {}).get("path") else None,
                "gfs_run": iso(wind.run) if wind.run else None, "wind_file": str(wind_path),
                "start_source": st["source"], "start": {"lat": st["lat"], "lon": st["lon"]},
                "start_gate": int(st.get("gate", 0)), "game_switch": switch,
                "options": self.options, "sail_names": self.polar.sail_names,
                "gates": [{"name": g.name, "a": g.a, "b": g.b, "cross": g.cross} for g in self.course.gates]}
        doc = route_document(res, rm, meta, check)
        doc["gates_passed_track"] = [p.gate for p in res.points]
        self.publish_route(doc)
        log.info("[%s] route calculée : arrivée %s, %d waypoints, %d changements de voile, %.0f s", self.boat,
                 doc["eta"], len(doc["waypoints"]), len(doc["sail_changes"]), res.stats["compute_s"])
        return doc

    def game_wind(self, wind: WindField, cur: dict | None, now: float | None = None):
        """Avant l'heure où le jeu charge le nouveau GFS, le bateau navigue encore dans l'ancien."""
        delay = self.cfg["gfs"].get("game_switch_after_run_h")
        now = now or time.time()
        if not delay or not cur or not wind.run or now >= wind.run + delay * 3600:
            return wind, None
        prev = self.store.previous_path(cur["cycle"])
        if not prev:
            return wind, None
        at = wind.run + delay * 3600
        log.info("[%s] jeu encore sur le GFS %s jusqu'à %s", self.boat, prev[0], iso(at))
        return SwitchedWind(WindField.load(prev[1]), wind, at), {"at": iso(at), "before_cycle": prev[0]}

    def publish_route(self, doc: dict) -> None:
        """Écrit la route de ce bateau (avec la comparaison à sa route précédente)."""
        pos = read_json(position_file(self.boat))
        doc = {**doc, "skipper": self.boat, "published_at": iso(time.time()),  # ≠ computed_at si route reprise
               "last_position": {"time": iso(pos["time"]), "lat": pos["lat"], "lon": pos["lon"]} if pos else None}
        out_route = self.bout / "route.json"
        prev = read_json(out_route)
        doc["comparison"] = compare(prev, doc)
        if prev:
            shutil.copyfile(out_route, self.bout / "route-prev.json")
        write_json(out_route, doc, compact=True)
        from . import alerts
        msg = alerts.route_change_message(prev, doc) if alerts.enabled() else None
        if msg:
            name = next(b.get("name", b["id"]) for b in self.boats if b["id"] == self.boat)
            alerts.send(self.cfg, self.boat, f"Nouvelle route · {name}", msg)
        (self.bout / "feuille-de-route.csv").write_text(to_csv(doc), encoding="utf-8-sig")
        (self.bout / "feuille-de-route.gpx").write_text(to_gpx(doc), encoding="utf-8")
        msg = (f"Arrivée estimée {doc['eta']} ({doc['duration_h']:.1f} h)" if doc.get("arrived")
               else "Arrivée non atteinte dans la durée maximale de calcul")
        self.route_status(state="ok" if doc.get("arrived") else "incomplet", message=msg,
                          computed_at=doc["computed_at"], gfs_cycle=doc.get("gfs_cycle"),
                          compute_s=(doc.get("stats") or {}).get("compute_s"), eta=doc.get("eta"),
                          start_source=doc.get("start_source"))

    def start_signature(self) -> tuple:
        """Deux bateaux de même signature partent du même point au même moment : un seul calcul suffit."""
        st = self.start_state()
        return (round(st["lat"], 3), round(st["lon"], 3), int(st["time"] // 600), int(st.get("gate", 0)),
                st.get("sail", -1), tuple(sorted(self.options.items())))

    def explanation_stale(self) -> bool:
        """Vrai si l'explication manque, a échoué, ou décrit une autre route que celle affichée."""
        from .explain import PROMPT_VERSION, has_credentials
        if not has_credentials():
            return False
        x = read_json(self.bout / "explain.json")
        if not x:
            return True
        src = self.bout / ("route-safe.json" if (self.bout / "route-safe.json").exists() else "route.json")
        shown = (read_json(src) or {}).get("computed_at")
        return x.get("state") != "ok" or x.get("for_route") != shown or x.get("prompt") != PROMPT_VERSION

    def write_explanation(self) -> dict:
        """Explication par Claude de la route affichée par défaut (conseillée si elle existe)."""
        from .explain import explain
        safe, main = self.bout / "route-safe.json", self.bout / "route.json"
        src = safe if safe.exists() else main
        if not src.exists():
            return {"state": "pas de route"}
        res = explain(read_json(src), read_json(self.bout / "ensemble.json"), self.cfg)
        write_json(self.bout / "explain.json", res)
        return res

    def copy_from(self, other: "Service", names=("route.json", "route-safe.json", "ensemble.json",
                                                    "explain.json")) -> None:
        """Reprend les résultats d'un bateau parti du même point (avant le départ, typiquement)."""
        for name in names:
            src = other.bout / name
            if name == "route.json" and src.exists():
                self.publish_route(read_json(src))
            elif src.exists():
                shutil.copyfile(src, self.bout / name)
            elif (self.bout / name).exists() and name != "route.json":
                (self.bout / name).unlink()

    # --- tâches planifiées -------------------------------------------------------------------

    def cycle(self, force_route: bool = False, boats: list[str] | None = None) -> dict:
        """Nouvelle météo ? → nouvelles routes. Sans effet si rien n'a changé.

        boats : bateaux que force_route concerne (tous par défaut). Les autres sont quand même recalculés si la
        météo a changé ou si leur position est plus récente que leur route.
        """
        with file_lock(resolve(self.cfg["service"]["lock_file"])):
            w = self.update_weather()
            forced = set(boats or [b["id"] for b in self.boats]) if force_route else set()
            done: dict[tuple, Service] = {}
            report = {}
            for bid in [b["id"] for b in self.boats]:
                svc = self if bid == self.boat else Service(self.cfg, bid)
                route_file = svc.bout / "route.json"
                pos = position_file(bid)
                pos_newer = pos.exists() and route_file.exists() and pos.stat().st_mtime > route_file.stat().st_mtime
                need = bid in forced or w.get("changed") or not route_file.exists() or pos_newer
                sig = svc.start_signature()
                if not need:
                    if svc.explanation_stale():
                        svc.write_explanation()
                    done.setdefault(sig, svc)  # route à jour : peut servir de modèle aux bateaux suivants
                    report[bid] = "inchangée"
                    continue
                try:
                    if sig in done:
                        svc.copy_from(done[sig], names=("route.json", "explain.json"))
                        log.info("[%s] même point de départ que %s : route reprise", bid, done[sig].boat)
                    else:
                        svc.compute_route()
                        svc.write_explanation()
                        done[sig] = svc
                except Exception as exc:
                    log.exception("[%s] calcul de route échoué", bid)
                    svc.route_status(state="erreur", message=f"Calcul de route échoué : {exc}")
                    report[bid] = f"erreur : {exc}"
                    continue
                report[bid] = (read_json(route_file) or {}).get("eta")
            if not any(v not in ("inchangée",) for v in report.values()):
                log.info("météo inchangée (%s) : routes conservées", w.get("cycle"))
            from . import alerts
            last = {b["id"]: (read_json(position_file(b["id"])) or {}).get("time") for b in self.boats}
            alerts.remind_positions(self.cfg, self.boats, last, self.course.start_time)
            alerts.remind_return(self.cfg, self.boats)
            return {"weather": {k: w.get(k) for k in ("cycle", "changed", "max_hour")}, "routes": report}

    def ensemble_cycle(self, force: bool = False) -> dict:
        """Scénarios GEFS (partagés), recalculés par bateau si nouveau cycle GEFS ou nouvelle route."""
        from .ensemble import EnsembleStore, run_ensemble
        with file_lock(resolve("data/.ensemble.lock")):
            store = EnsembleStore(self.cfg, self.out / "ensemble-status.json")
            upd = store.update()
            done: dict[tuple, Service] = {}
            report = {}
            for b in self.boats:
                svc = self if b["id"] == self.boat else Service(self.cfg, b["id"])
                ens, route = svc.bout / "ensemble.json", svc.bout / "route.json"
                if not route.exists():
                    report[b["id"]] = "pas encore de route GFS"
                    continue
                stale = not ens.exists() or ens.stat().st_mtime < route.stat().st_mtime
                if not (force or upd.get("changed") or stale):
                    report[b["id"]] = "inchangé"
                    continue
                doc_route = read_json(route)
                sig = (doc_route["start_time"], round(doc_route["start"]["lat"], 3),
                       round(doc_route["start"]["lon"], 3), doc_route.get("gfs_cycle"),
                       json.dumps(doc_route.get("options"), sort_keys=True))
                if sig in done:
                    svc.copy_from(done[sig], names=("route-safe.json", "ensemble.json"))
                    svc.write_explanation()
                    report[b["id"]] = f"repris de {done[sig].boat}"
                    continue

                def progress(msg, d, total, name=b["name"]):
                    store.status(state="calcul", cycle=upd["cycle"], done=d, total=total, message=f"{name} : {msg}")

                doc = run_ensemble(svc, upd["members"], upd["cycle"], progress)
                svc.write_explanation()
                done[sig] = svc
                report[b["id"]] = {"conseillée": doc["recommended"], "gain_h": doc["gain_vs_gfs_h"]}
            store.status(state="ok", cycle=upd["cycle"], done=1, total=1,
                         message=f"Scénarios GEFS {upd['cycle'][6:8]}/{upd['cycle'][4:6]} {upd['cycle'][8:]}z à jour")
            return {"gefs": upd.get("cycle"), "bateaux": report}
