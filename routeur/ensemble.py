"""Scénarios météo (ensemble GEFS) : une route optimale par scénario, puis la route la plus sûre.

1. Télécharge les 31 membres GEFS 0,5° (contrôle gec00 + gep01..gep30).
2. Calcule la route optimale dans chaque scénario (moteur d'isochrones, réglages plus grossiers).
3. Teste chaque route candidate (route GFS + routes des scénarios) dans les 31 scénarios avec un
   simulateur qui suit les waypoints en louvoyant / empannant si besoin (pénalités et énergie comprises).
4. Route conseillée = meilleure arrivée médiane sur les scénarios (puis la moins risquée, P90).
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .config import resolve
from .gfs import Cycle, FetchError, GfsStore, gefs_member, listing, recent_cycles, with_retries
from .isochrones import Router, RoutingParams
from .roadmap import build_roadmap, iso, route_document
from .course import Course
from .geo import haversine_nm, rhumb_bearing_distance, rhumb_destination
from .polar import Polar
from .wind import MS_TO_KT, SwitchedWind, WindField

log = logging.getLogger("routeur.ensemble")


def member_names(n: int) -> list[str]:
    return ["gec00"] + [f"gep{k:02d}" for k in range(1, n)]


def write_json(path: Path, data, compact: bool = True) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":") if compact else None,
                              indent=None if compact else 1), encoding="utf-8")
    os.replace(tmp, path)


# --- téléchargement ---------------------------------------------------------------------------

class EnsembleStore:
    def __init__(self, cfg: dict, status_path: Path):
        self.cfg = cfg
        self.ecfg = {**cfg["gfs"], **cfg["ensemble"]}
        self.root = resolve("data/gefs")
        self.root.mkdir(parents=True, exist_ok=True)
        self.status_path = status_path
        self.members = member_names(self.ecfg["members"])

    def status(self, **st) -> None:
        st["updated_at"] = iso(time.time())
        write_json(self.status_path, st, compact=False)

    def current(self) -> dict | None:
        p = self.root / "current.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def member_store(self, m: str) -> GfsStore:
        return GfsStore(self.cfg, root=self.root / m, status_path=self.root / m / "status.json",
                        product=gefs_member(m), section="ensemble")

    def find_latest(self, now: datetime) -> tuple[Cycle, dict[str, list[int]]] | None:
        """Cycle le plus récent où tous les membres sont publiés jusqu'à min_usable_hour."""
        for cycle in recent_cycles(now):
            html = with_retries(lambda c=cycle: listing(c, self.ecfg["timeout_s"], gefs_member("gec00")),
                                self.ecfg["retries"], f"liste GEFS {cycle}")
            hours = {m: gefs_member(m).hours_in(html, cycle) for m in self.members}
            if all(h and max(h) >= self.ecfg["min_usable_hour"] for h in hours.values()):
                return cycle, hours
            time.sleep(self.ecfg["request_pause_s"])
        return None

    def update(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        cur = self.current()
        found = self.find_latest(now)
        if found is None:
            self.status(state="à jour" if cur else "attente", message="Pas de nouveau cycle GEFS complet")
            if cur:
                return {"changed": False, **cur}
            raise FetchError("aucun cycle GEFS complet disponible")
        cycle, hours = found
        if cur and cur["cycle"] == cycle.key:
            return {"changed": False, **cur}
        paths = {}
        for k, m in enumerate(self.members):
            self.status(state="téléchargement", cycle=cycle.key, done=k, total=len(self.members),
                        message=f"Scénario {k + 1}/{len(self.members)} ({m})")
            st = self.member_store(m)
            cdir = st.download(cycle, hours[m])
            paths[m] = str(st.build_forecast(cdir))
            st.set_current({"cycle": cycle.key, "path": paths[m]})
            st.prune()
        info = {"cycle": cycle.key, "run": cycle.run.isoformat(), "members": paths, "updated_at": iso(time.time())}
        tmp = self.root / "current.json.tmp"
        tmp.write_text(json.dumps(info, indent=1), encoding="utf-8")
        os.replace(tmp, self.root / "current.json")
        self.status(state="ok", cycle=cycle.key, done=len(self.members), total=len(self.members),
                    message=f"{len(self.members)} scénarios GEFS {cycle.date[6:]}/{cycle.date[4:6]} {cycle.hh}z prêts")
        return {"changed": True, **info}


# --- vent de tous les scénarios à la fois -----------------------------------------------------

@dataclass
class StackedWind:
    """Les S scénarios sur une même grille : interpolation vectorisée, un bateau par scénario."""
    valid: np.ndarray
    lats: np.ndarray
    lons: np.ndarray
    u: np.ndarray  # (S, T, J, I) float16
    v: np.ndarray

    @classmethod
    def load(cls, paths: list[str]) -> "StackedWind":
        ws = [WindField.load(p) for p in paths]
        t = min(w.valid.size for w in ws)
        return cls(ws[0].valid[:t], ws[0].lats, ws[0].lons,
                   np.stack([w.u[:t] for w in ws]).astype(np.float16),
                   np.stack([w.v[:t] for w in ws]).astype(np.float16))

    def wind(self, lat, lon, t, s=None):
        """Vent du scénario s[i] au point i, à l'instant t[i] (tableaux de même taille)."""
        s = np.arange(lat.size) if s is None else s
        fj = np.clip(np.interp(lat, self.lats, np.arange(self.lats.size)), 0, self.lats.size - 1)
        fi = np.clip(np.interp(lon, self.lons, np.arange(self.lons.size)), 0, self.lons.size - 1)
        ft = np.clip(np.interp(np.broadcast_to(t, lat.shape), self.valid, np.arange(self.valid.size)),
                     0, self.valid.size - 1)
        j0 = np.minimum(fj.astype(int), self.lats.size - 2)
        i0 = np.minimum(fi.astype(int), self.lons.size - 2)
        k0 = np.minimum(ft.astype(int), self.valid.size - 2)
        wj, wi, wk = fj - j0, fi - i0, ft - k0
        out = []
        for f in (self.u, self.v):
            acc = 0.0
            for dk, a in ((0, 1 - wk), (1, wk)):
                for dj, b in ((0, 1 - wj), (1, wj)):
                    for di, c in ((0, 1 - wi), (1, wi)):
                        acc = acc + a * b * c * f[s, k0 + dk, j0 + dj, i0 + di].astype(np.float32)
            out.append(acc)
        u, v = out
        return (np.degrees(np.arctan2(-u, -v)) + 360) % 360, np.hypot(u, v) * MS_TO_KT


# --- simulateur : suivre des waypoints dans chaque scénario ------------------------------------

class Follower:
    """Bateau VR qui vise le waypoint suivant ; louvoie / empanne aux angles de VMG si la route directe
    est dans la zone morte (près ou vent arrière). Pénalités, voile auto et énergie comme le moteur.
    Chaque bateau a sa propre horloge : en atteignant un waypoint, le reste du pas sert au leg suivant."""

    def __init__(self, polar: Polar, margin_deg: float = 12.0, dt_s: float = 600.0):
        self.p, self.margin, self.dt = polar, margin_deg, dt_s
        g = np.arange(0, 70.5, 0.5)
        a = np.arange(25.0, 180.1, 1.0)
        A, G = np.meshgrid(a, g, indexing="ij")
        best = polar.best(A.ravel(), G.ravel())[0].reshape(A.shape)
        self.g = g
        self.up = a[np.argmax(best * np.cos(np.radians(A)), axis=0)]
        self.down = a[np.argmax(-best * np.cos(np.radians(A)), axis=0)]

    def run(self, wps: np.ndarray, wind: StackedWind, t0: float, max_h: float) -> np.ndarray:
        """wps : (N, 2) lat/lon, le premier = départ. Renvoie l'heure d'arrivée par scénario (inf si non arrivé)."""
        return self.simulate(wps, wind, t0, max_h)[0]

    def simulate(self, wps: np.ndarray, wind: StackedWind, t0: float, max_h: float):
        """(arrivée, lat, lon, heure) par scénario : arrêt à l'arrivée ou après max_h heures."""
        p, S = self.p, wind.u.shape[0]
        lat = np.full(S, float(wps[0, 0]))
        lon = np.full(S, float(wps[0, 1]))
        tb = np.full(S, float(t0))          # horloge de chaque bateau
        k = np.ones(S, int)
        sail = np.full(S, -1)
        tack = np.zeros(S)
        energy = np.full(S, 100.0)
        eta = np.full(S, np.inf)
        live = np.ones(S, bool)
        thr = max(p.auto_tolerance, 1.01)
        limit = t0 + max_h * 3600
        for _ in range(200000):
            act = np.flatnonzero(live & (tb < limit))
            if act.size == 0:
                break
            n = act.size
            la, lo, kk = lat[act], lon[act], k[act]
            tl, tn = wps[kk, 0], wps[kk, 1]
            brg, dist = rhumb_bearing_distance(la, lo, tl, tn)
            twd, tws = wind.wind(la, lo, tb[act], act)
            direct = (twd - brg + 180) % 360 - 180          # TWA de la route directe (+ tribord)
            up = np.interp(tws, self.g, self.up)
            down = np.interp(tws, self.g, self.down)
            tk = tack[act]
            side = np.where(tk == 0, np.where(direct >= 0, 1.0, -1.0), tk)
            beat = np.abs(direct) < up
            run_ = np.abs(direct) > down
            # Changement d'amure seulement quand le waypoint passe nettement de l'autre côté du vent.
            flip_side = ((beat & (np.abs(direct) > self.margin)) | (run_ & (np.abs(direct) < 180 - self.margin))) \
                & (np.sign(direct) == -side)
            side = np.where(flip_side, -side, side)
            twa = np.where(beat, side * up, np.where(run_, side * down, direct))
            heading = (twd - twa) % 360
            best, bidx, allsp = p.best(np.abs(twa), tws)
            sl = sail[act]
            cur = np.where(sl >= 0, allsp[np.maximum(sl, 0), np.arange(n)], 0.0)
            change = (sl >= 0) & (bidx != sl) & (best > cur * thr)
            keep = (sl >= 0) & ~change & (cur > 0)
            speed = np.maximum(np.where(keep, cur, best), 0.05)
            sail[act] = np.where(keep, sl, bidx)
            flip = (tk != 0) & (np.sign(twa) != tk)
            lost = np.zeros(n)
            en = energy[act]
            for kind, sel in (("tack", flip & (np.abs(twa) < 90)), ("gybe", flip & (np.abs(twa) >= 90)),
                              ("sailChange", change)):
                if sel.any():
                    timer, ratio = p.penalty(kind, tws[sel])
                    lost[sel] += timer * p.stamina_multiplier(en[sel]) * (1 - ratio)
                    en[sel] -= p.stamina_cost(kind, tws[sel])
            tack[act] = np.sign(twa)
            need = dist / speed * 3600 + lost               # temps pour atteindre le waypoint
            reach = need <= self.dt
            used = np.where(reach, need, self.dt)
            energy[act] = np.clip(en + p.stamina_recovery(tws, used), 0, 100)
            tb[act] += used
            # Atteint : on se pose sur le waypoint, la suite du pas servira au leg suivant.
            r = act[reach]
            lat[r], lon[r] = wps[k[r], 0], wps[k[r], 1]
            last = r[k[r] == len(wps) - 1]
            eta[last] = tb[last]
            live[last] = False
            k[r] = np.minimum(k[r] + 1, len(wps) - 1)
            m = act[~reach]
            step = speed[~reach] * np.maximum(self.dt - lost[~reach], 0) / 3600
            lat[m], lon[m] = rhumb_destination(la[~reach], lo[~reach], heading[~reach], step)
        return eta, lat, lon, tb


# --- orchestration ----------------------------------------------------------------------------

def coarse_params(cfg: dict) -> RoutingParams:
    p = RoutingParams.from_config(cfg)
    e = cfg["ensemble"]
    p.time_steps = e.get("time_steps", [[24, 1.0], [400, 2.0]])
    p.twa_step_deg = e.get("twa_step_deg", 5)
    p.sector_nm = e.get("sector_nm", 8.0)
    p.iso_every_h = 1e9
    return p


def thin(track, keep: int = 160) -> list:
    step = max(1, len(track) // keep)
    return [[round(a, 3), round(b, 3)] for a, b in track[::step]] + [[round(track[-1][0], 3), round(track[-1][1], 3)]]


def run_ensemble(svc, members: dict[str, str], gefs_cycle: str, progress=None) -> dict:
    """Routes par scénario + évaluation croisée. svc = Service (polaire, masque, parcours, sorties).

    Les scénarios comparent la traversée jusqu'à la porte stratégique (Tête à l'Anglais, index 1) : c'est là
    que les choix diffèrent. Le tour de la Guadeloupe qui suit est repris de la route GFS (grille 0,25°).
    """
    cfg, polar, mask, course = svc.cfg, svc.polar, svc.mask, svc.course
    main = json.loads((svc.bout / "route.json").read_text(encoding="utf-8"))
    t0 = datetime.fromisoformat(main["start_time"].replace("Z", "+00:00")).timestamp()
    start = (main["start"]["lat"], main["start"]["lon"])
    gate0 = int(main.get("start_gate", 0))
    # Porte où s'arrête la comparaison : Tête à l'Anglais (la première porte de Guadeloupe).
    cut = next((k for k, g in enumerate(course.gates) if "Anglais" in g.name), 1)
    if gate0 > cut:
        raise RuntimeError("fin de course : la porte stratégique est passée, scénarios inutiles")
    cut_name = f"Porte : {course.gates[cut].name}"
    i_cut = next((i for i, w in enumerate(main["waypoints"]) if w["reason"] == cut_name), None)
    if i_cut is None:
        raise RuntimeError("la route GFS ne passe pas par la porte stratégique")
    ts = lambda x: datetime.fromisoformat(x.replace("Z", "+00:00")).timestamp()  # noqa: E731
    t_cut_main = ts(main["waypoints"][i_cut]["t"])
    tour_s = ts(main["eta"]) - t_cut_main       # durée du tour de la Guadeloupe, prise sur la route GFS
    leg = Course(course.name, course.start_lat, course.start_lon, course.start_time, course.gates[:cut + 1],
                 course.forbidden_geojson, course.fine_tiles, course.raw)
    params = coarse_params(cfg)
    fine = RoutingParams.from_config(cfg)
    fine.iso_every_h = 1e9
    names = sorted(members)
    cands, results = [], {}
    clock = time.time()
    # Les premières heures, le jeu navigue dans le GFS (connu) : chaque scénario ne prend la main qu'ensuite.
    # Sinon la route conseillée donne des caps et des TWA calculés dans un vent que le bateau n'a pas (01/11 :
    # cap 272 à TWA 134 au lieu de 125, TWA verrouillée qui menait à la côte avant Fréhel).
    cur = svc.store.current()
    gfs = None
    if cur:
        gfs, _ = svc.game_wind(WindField.load(cur["path"]), cur)
    near_s = float(cfg["ensemble"].get("gfs_first_h", 6.0)) * 3600
    switch_t = max(t0, time.time()) + near_s
    for n, m in enumerate(names):
        if progress:
            progress(f"Route du scénario {n + 1}/{len(names)}", n, len(names))
        w = WindField.load(members[m])
        if gfs is not None and near_s > 0:
            w = SwitchedWind(gfs, w, switch_t)
        res = None
        # Réglages grossiers d'abord ; si le front se bloque, second essai avec les réglages fins de la route GFS.
        for attempt, prm in enumerate((params, fine)):
            try:
                res = Router(w, polar, mask, leg, prm).run(start_time=t0, start=start, start_gate=gate0)
                break
            except RuntimeError as exc:
                log.warning("scénario %s, essai %d : pas de route (%s)", m, attempt + 1, exc)
        if res is None:
            continue
        if not res.arrived:
            continue
        rm = build_roadmap(res, polar, mask, [g.name for g in leg.gates], cfg["routing"]["simplify_tolerance_nm"])
        wps = np.array([[x.lat, x.lon] for x in rm["waypoints"]])
        results[m] = (res, rm)
        cands.append({"id": m, "label": f"Scénario {m[3:]}", "own_eta": res.eta + tour_s, "wps": wps,
                      "track": thin([[p.lat, p.lon] for p in res.points])})
    main_wps = np.array([[x["lat"], x["lon"]] for x in main["waypoints"][:i_cut + 1]])
    cands.insert(0, {"id": "gfs", "label": "Route GFS", "own_eta": None, "wps": main_wps,
                     "track": thin([[p[0], p[1]] for p in main["track"]])})
    if progress:
        progress("Test de chaque route dans tous les scénarios", len(names), len(names))
    # Seuls les scénarios où une route optimale existe servent d'arbitres.
    judges = [m for m in names if m in results]
    wind = StackedWind.load([members[m] for m in judges])
    fol = Follower(polar)
    commit_h = cfg["ensemble"].get("commit_h", 48.0)
    ref = [results[m][0] for m in judges]
    r_lat = [np.array([q.lat for q in r.points]) for r in ref]
    r_lon = [np.array([q.lon for q in r.points]) for r in ref]
    r_t = [np.array([q.t for q in r.points]) for r in ref]
    r_v = [max(r.distance_nm / max((r.eta - t0) / 3600, 1e-6), 1.0) for r in ref]

    def total_eta(c):
        """Arrivée estimée par scénario si l'on suit c pendant commit_h puis qu'on recalcule."""
        eta, la, lo, tb = fol.simulate(c["wps"], wind, t0, commit_h)
        out = np.empty(len(judges))
        for j in range(len(judges)):
            if np.isfinite(eta[j]):
                out[j] = eta[j]
                continue
            d = haversine_nm(la[j], lo[j], r_lat[j], r_lon[j])
            k = int(np.argmin(d))
            out[j] = tb[j] + (ref[j].eta - r_t[j][k]) + d[k] / r_v[j] * 3600
        return out

    etas = np.array([total_eta(c) for c in cands]) + tour_s   # (candidats, scénarios arbitres)
    fastest = np.argmin(etas, axis=0)
    out_c = []
    for i, c in enumerate(cands):
        e = etas[i][np.isfinite(etas[i])]
        out_c.append({"id": c["id"], "label": c["label"], "own_eta": iso(c["own_eta"]) if c["own_eta"] else None,
                      "arrived_in": int(e.size), "median_eta": iso(float(np.median(e))) if e.size else None,
                      "p10_eta": iso(float(np.percentile(e, 10))) if e.size else None,
                      "p90_eta": iso(float(np.percentile(e, 90))) if e.size else None,
                      "etas": [iso(float(x)) for x in np.sort(e)],   # une arrivée par scénario (frise de la page)
                      "_median": float(np.median(e)) if e.size else np.inf,
                      "_p90": float(np.percentile(e, 90)) if e.size else np.inf,
                      "wins": int((fastest == i).sum()), "beats_gfs": int((etas[i] < etas[0] - 60).sum()),
                      "track": c["track"]})
    # Une route qui n'arrive pas dans tous les scénarios est écartée si une autre y arrive.
    full = [c for c in out_c if c["arrived_in"] == len(judges)] or out_c
    rec = min(full, key=lambda c: (c["_median"], c["_p90"]))
    gfs = out_c[0]
    own = np.array([c["own_eta"] for c in cands[1:]])
    spread_h = float((np.percentile(own, 90) - np.percentile(own, 10)) / 3600) if own.size > 2 else None
    gain_h = (gfs["_median"] - rec["_median"]) / 3600 if np.isfinite(gfs["_median"]) else None
    doc = {"format": "routeur-rhum/ensemble@1", "computed_at": iso(time.time()), "gefs_cycle": gefs_cycle,
           "gfs_cycle": main.get("gfs_cycle"), "scenarios": len(names), "routes_found": len(cands) - 1,
           "compared_until": course.gates[cut].name, "guadeloupe_tour_h": round(tour_s / 3600, 1),
           "judges": len(judges), "commit_h": commit_h,
           "start_time": main["start_time"], "start": main["start"], "recommended": rec["id"],
           "recommended_label": rec["label"], "gain_vs_gfs_h": round(gain_h, 2) if gain_h is not None else None,
           "spread_h": round(spread_h, 1) if spread_h is not None else None,
           "best_possible_median": iso(float(np.median(own))) if own.size else None,
           "compute_s": round(time.time() - clock, 1),
           "candidates": [{k: v for k, v in c.items() if not k.startswith("_")} for c in out_c]}
    safe = svc.bout / "route-safe.json"
    if rec["id"] != "gfs":
        write_json(safe, safe_document(main, results[rec["id"]], i_cut, rec["id"], gefs_cycle, members[rec["id"]]))
    elif safe.exists():
        safe.unlink()
    write_json(svc.bout / "ensemble.json", doc)
    log.info("scénarios : %d routes, conseillée %s (médiane %s), dispersion %s h, %.0f s",
             len(cands) - 1, rec["label"], rec["median_eta"], doc["spread_h"], doc["compute_s"])
    return doc


def safe_document(main: dict, member: tuple, i_cut: int, variant: str, gefs_cycle: str, wind_file: str) -> dict:
    """Route conseillée = traversée du scénario retenu + tour de la Guadeloupe de la route GFS (décalé)."""
    res, rm = member
    ts = lambda x: datetime.fromisoformat(x.replace("Z", "+00:00")).timestamp()  # noqa: E731
    meta = {k: main[k] for k in ("race", "boat", "polar_file", "options", "sail_names", "gates", "start_source",
                                  "start", "start_gate") if k in main}
    meta.update({"gfs_cycle": main.get("gfs_cycle"), "gefs_cycle": gefs_cycle, "variant": variant,
                 "wind_file": wind_file})
    doc = route_document(res, rm, meta, None)
    shift = res.eta - ts(main["waypoints"][i_cut]["t"])
    move = lambda x: iso(ts(x) + shift)  # noqa: E731
    t_cut = ts(main["waypoints"][i_cut]["t"])
    tail_w = [{**w, "t": move(w["t"])} for w in main["waypoints"][i_cut + 1:]]
    n0 = len(doc["waypoints"])
    for k, w in enumerate(tail_w):
        w["n"] = n0 + k
    doc["waypoints"] += tail_w
    doc["sail_changes"] += [{**c, "t": move(c["t"])} for c in main["sail_changes"] if ts(c["t"]) > t_cut]
    tail_t = [p for p in main["track"] if ts(p[2]) > t_cut]
    doc["track"] += [[p[0], p[1], move(p[2]), *p[3:]] for p in tail_t]
    doc["gates_passed_track"] = [p.gate for p in res.points] + main["gates_passed_track"][-len(tail_t):] if tail_t else [p.gate for p in res.points]
    doc["eta"] = move(main["eta"])
    doc["arrived"] = True
    doc["duration_h"] = round((ts(doc["eta"]) - ts(doc["start_time"])) / 3600, 2)
    doc["distance_nm"] = round(doc["distance_nm"] + sum(
        float(haversine_nm(a[0], a[1], b[0], b[1])) for a, b in zip(tail_t, tail_t[1:])), 1)
    doc["comparison"] = main.get("comparison")
    return doc
