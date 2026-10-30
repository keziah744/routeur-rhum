"""Moteur de routage par isochrones.

À chaque pas de temps, chaque point du front est propagé selon un éventail de TWA (deux amures).
La vitesse vient de la polaire (meilleure voile, foils, coque), diminuée des pénalités de virement,
d'empannage et de changement de voile (durée × facteur d'énergie). Les candidats qui finissent dans
un obstacle ou dont le segment traverse un obstacle sont éliminés. Le pruning garde, dans chaque
secteur angulaire vu de l'origine de la branche en cours, le point le plus éloigné.

Convention : TWA signée, positive = vent de tribord (tribord amures) ; cap = TWD − TWA.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import numpy as np

from .course import Course
from .geo import LandMask, bearing_deg, haversine_nm, rhumb_destination
from .polar import Polar
from .wind import WindField

log = logging.getLogger("routeur.iso")

MANEUVER_TACK, MANEUVER_GYBE, MANEUVER_SAIL = 1, 2, 4


@dataclass
class RoutingParams:
    time_steps: list = field(default_factory=lambda: [[6, 0.25], [24, 0.5], [72, 1.0], [400, 2.0]])
    twa_step_deg: float = 3.0
    twa_min_deg: float = 30.0
    sector_deg: float = 0.5          # largeur max d'un secteur (près de l'origine)
    sector_nm: float = 4.0           # largeur visée en milles : le secteur rétrécit quand le front s'éloigne
    sector_min_deg: float = 0.02
    stall_h: float = 36.0            # sans progrès vers la porte pendant cette durée : abandon
    funnel_nm: float = 250.0         # un point plus loin de la porte que le meilleur + max(funnel, 2 × meilleur) est abandonné
    max_duration_h: float = 400.0
    gate_grace_h: float = 3.0
    stamina_start_pct: float = 100.0
    iso_every_h: float = 6.0
    sail_change_min_gain_pct: float = 1.0
    near_gate_nm: float = 80.0       # en deçà, pas de temps fin (marques rapprochées, côtes)
    near_gate_step_h: float = 1 / 6
    close_gate_nm: float = 6.0       # tout près d'une marque : pas très fin
    close_gate_step_h: float = 1 / 30

    @classmethod
    def from_config(cls, cfg: dict) -> "RoutingParams":
        r = cfg["routing"]
        return cls(time_steps=r["time_steps"], twa_step_deg=r["twa_step_deg"], twa_min_deg=r["twa_min_deg"],
                   sector_deg=r["sector_deg"], max_duration_h=r["max_duration_h"],
                   sector_nm=r.get("sector_nm", 4.0),
                   sail_change_min_gain_pct=r.get("sail_change_min_gain_pct", 1.0),
                   near_gate_nm=r.get("near_gate_nm", 80.0), near_gate_step_h=r.get("near_gate_step_h", 1 / 6),
                   stamina_start_pct=cfg["polar"].get("stamina_start_pct", 100.0))

    def step_h(self, elapsed_h: float) -> float:
        for until, dt in self.time_steps:
            if elapsed_h < until:
                return float(dt)
        return float(self.time_steps[-1][1])


@dataclass
class RoutePoint:
    t: float
    lat: float
    lon: float
    heading: float   # cap suivi depuis ce point jusqu'au suivant
    twa: float
    twd: float
    tws: float
    sail: int        # index de voile dans la polaire
    speed: float     # vitesse moyenne sur le segment (pénalités incluses), nœuds
    energy: float
    maneuver: int    # bits MANEUVER_* effectués au début du segment
    gate: int        # porte visée
    beyond_forecast: bool


@dataclass
class RouteResult:
    points: list[RoutePoint]
    arrived: bool
    eta: float | None
    start_time: float
    distance_nm: float
    isochrones: list[dict]
    stats: dict


class Router:
    def __init__(self, wind: WindField, polar: Polar, mask: LandMask, course: Course, params: RoutingParams):
        self.wind, self.polar, self.mask, self.course, self.p = wind, polar, mask, course, params
        a = np.arange(params.twa_min_deg, 180.0 + 1e-9, params.twa_step_deg)
        if a[-1] < 180.0:
            a = np.append(a, 180.0)
        self.twas = np.concatenate([a, -a])

    def run(self, start_time: float | None = None, start: tuple[float, float] | None = None,
            start_gate: int = 0, start_sail: int = -1, start_twa: float = 0.0, progress=None) -> RouteResult:
        p, pol, gates = self.p, self.polar, self.course.gates
        t0 = float(start_time if start_time is not None else self.course.start_time)
        lat0, lon0 = start if start else (self.course.start_lat, self.course.start_lon)
        if self.mask.blocked(np.array([lat0]), np.array([lon0]))[0]:
            raise ValueError(f"le point de départ {lat0:.4f}, {lon0:.4f} est dans un obstacle")
        clock = time.time()
        # Front courant (tableaux alignés).
        f = dict(lat=np.array([lat0]), lon=np.array([lon0]), sail=np.array([start_sail]),
                 twa=np.array([start_twa]), energy=np.array([p.stamina_start_pct]),
                 gate=np.array([start_gate]), parent=np.array([-1]))
        history = []   # par pas : dict de tableaux (positions de fin de segment + paramètres du segment)
        isochrones = []
        gate_reached_at = {start_gate: t0}
        t = t0
        n_cand = 0
        arrival = None
        last_iso = t0
        best_progress = (start_gate, np.inf, 0.0, t0)   # (porte, mini vers la porte, maxi depuis l'origine, heure)
        while t - t0 < p.max_duration_h * 3600:
            dt_h = p.step_h((t - t0) / 3600)
            near = self._near_gate(f)
            top_gate = int(f["gate"].max())
            o = self.course.leg_origin(min(top_gate, len(gates) - 1))
            reach = float(haversine_nm(f["lat"], f["lon"], *o).max())
            if top_gate > best_progress[0]:
                best_progress = (top_gate, near, reach, t)
            elif near < best_progress[1] - 1.0 or reach > best_progress[2] + 1.0:
                best_progress = (top_gate, min(near, best_progress[1]), max(reach, best_progress[2]), t)
            elif t - best_progress[3] > p.stall_h * 3600:
                raise RuntimeError(f"route bloquée : aucun progrès vers « {gates[top_gate].name} » depuis "
                                   f"{p.stall_h:.0f} h (front coincé à {near:.0f} milles de la porte)")
            if near < p.close_gate_nm:
                dt_h = min(dt_h, p.close_gate_step_h)
            elif near < p.near_gate_nm:
                dt_h = min(dt_h, p.near_gate_step_h)
            dt = dt_h * 3600
            n = f["lat"].size
            twd, tws = self.wind.wind(f["lat"], f["lon"], t)
            # Éventail : n nœuds × m TWA.
            m = self.twas.size
            idx = np.repeat(np.arange(n), m)
            twa = np.tile(self.twas, n)
            c_twd, c_tws = twd[idx], tws[idx]
            heading = (c_twd - twa) % 360
            best_speed, best_sail, all_speeds = pol.best(np.abs(twa), c_tws)
            cur_sail = f["sail"][idx]
            has_sail = cur_sail >= 0
            cur_speed = np.where(has_sail, all_speeds[np.maximum(cur_sail, 0), np.arange(idx.size)], 0.0)
            # Changement de voile seulement si le gain dépasse autoSailChangeTolerance (VR) et le seuil config.
            threshold = max(pol.auto_tolerance, 1.0 + p.sail_change_min_gain_pct / 100.0)
            change = has_sail & (best_sail != cur_sail) & (best_speed > cur_speed * threshold)
            sail = np.where(has_sail & ~change, cur_sail, best_sail)
            speed = np.where(has_sail & ~change, cur_speed, best_speed)
            prev_twa = f["twa"][idx]
            flip = (prev_twa != 0) & (np.sign(prev_twa) != np.sign(twa))
            is_tack = flip & ((np.abs(prev_twa) + np.abs(twa)) / 2 < 90)
            is_gybe = flip & ~is_tack
            energy = f["energy"][idx].copy()
            lost_s = np.zeros(idx.size)
            ratio_loss = np.zeros(idx.size)
            maneuver = np.zeros(idx.size, np.int8)
            for kind, sel, bit in (("tack", is_tack, MANEUVER_TACK), ("gybe", is_gybe, MANEUVER_GYBE),
                                   ("sailChange", change, MANEUVER_SAIL)):
                if not sel.any():
                    continue
                timer, ratio = pol.penalty(kind, c_tws[sel])
                dur = timer * pol.stamina_multiplier(energy[sel])
                lost_s[sel] += dur
                ratio_loss[sel] = 1.0 - ratio
                energy[sel] = energy[sel] - pol.stamina_cost(kind, c_tws[sel])
                maneuver[sel] |= bit
            energy = np.clip(energy + pol.stamina_recovery(c_tws, dt), 0.0, 100.0)
            lost_s = np.minimum(lost_s, dt)
            slat, slon = f["lat"][idx], f["lon"][idx]
            # Point milieu (RK2) : vitesse recalculée avec le vent au milieu du segment, cap inchangé.
            mlat, mlon = rhumb_destination(slat, slon, heading, speed * dt_h / 2)
            m_twd, m_tws = self.wind.wind(mlat, mlon, t + dt / 2)
            m_twa = np.abs((m_twd - heading + 180.0) % 360.0 - 180.0)
            speed = pol.speed_with_sail(m_twa, m_tws, sail)
            dist = speed * dt_h - speed * ratio_loss * lost_s / 3600.0
            nlat, nlon = rhumb_destination(slat, slon, heading, dist)
            # Portes : franchissements successifs possibles dans le même segment.
            gate = f["gate"][idx].copy()
            frac_finish = np.full(idx.size, np.nan)
            for _ in range(3):
                moved = np.zeros(idx.size, bool)
                for g in np.unique(gate):
                    if g >= len(gates):
                        continue
                    sel = gate == g
                    fr = gates[g].crossing(slat[sel], slon[sel], nlat[sel], nlon[sel])
                    hit = ~np.isnan(fr)
                    if hit.any():
                        w = np.flatnonzero(sel)[hit]
                        gate[w] += 1
                        moved[w] = True
                        if g == len(gates) - 1:
                            frac_finish[w] = fr[hit]
                if not moved.any():
                    break
            ok = ~self.mask.blocked(nlat, nlon) | ~np.isnan(frac_finish)
            n_cand += idx.size
            # Les branches en retard d'une porte sont gardées quelques heures puis abandonnées.
            top = gate.max()
            if top not in gate_reached_at:
                gate_reached_at[top] = t + dt
            keep_gate = gate >= top - (1 if (t + dt - gate_reached_at[top]) < p.gate_grace_h * 3600 else 0)
            ok &= keep_gate
            cand = np.flatnonzero(ok)
            # Arrivée : on contrôle d'abord la navigabilité des segments arrivés.
            fin = cand[~np.isnan(frac_finish[cand])]
            if fin.size:
                fr = frac_finish[fin]
                clat, clon = slat[fin] + (nlat[fin] - slat[fin]) * fr, slon[fin] + (nlon[fin] - slon[fin]) * fr
                fin = fin[self.mask.segments_clear(slat[fin], slon[fin], clat, clon)]
                if fin.size:
                    k = fin[np.argmin(frac_finish[fin])]
                    fr = frac_finish[k]
                    arrival = (k, float(t + fr * dt))
                    # Le bateau s'arrête sur la ligne : position = point de franchissement.
                    nlat[k] = slat[k] + (nlat[k] - slat[k]) * fr
                    nlon[k] = slon[k] + (nlon[k] - slon[k]) * fr
            sel = self._prune(cand, idx, nlat, nlon, gate, slat, slon) if arrival is None else np.array([arrival[0]])
            step = dict(t=t, dt=dt, parent=idx[sel], lat=nlat[sel], lon=nlon[sel], heading=heading[sel],
                        twa=twa[sel], twd=c_twd[sel], tws=c_tws[sel], sail=sail[sel], speed=dist[sel] / dt_h,
                        energy=energy[sel], maneuver=maneuver[sel], gate=gate[sel])
            history.append(step)
            f = dict(lat=step["lat"], lon=step["lon"], sail=step["sail"], twa=step["twa"],
                     energy=step["energy"], gate=step["gate"], parent=np.arange(sel.size))
            t += dt
            if t - last_iso >= p.iso_every_h * 3600 - 1:
                isochrones.append(self._iso_line(f, t))
                last_iso = t
            if arrival is not None:
                break
            if f["lat"].size == 0:
                raise RuntimeError(f"front vide à t+{(t - t0) / 3600:.1f} h (porte visée : "
                                   f"{gates[int(history[-2]['gate'].max())].name if len(history) > 1 else '?'}) : "
                                   "toutes les branches sont bloquées par la terre ou une zone interdite")
            if progress:
                progress((t - t0) / 3600, int(f["gate"].max()), f["lat"].size, near)
        return self._backtrack(history, t0, lat0, lon0, arrival, isochrones,
                               stats={"steps": len(history), "candidates": n_cand,
                                      "compute_s": round(time.time() - clock, 1)})

    def _iso_line(self, f, t, max_points: int = 300) -> dict:
        """Isochrone allégée pour l'affichage : points triés par relèvement depuis l'origine."""
        g = int(f["gate"].max())
        sel = f["gate"] == g
        o = self.course.leg_origin(min(g, len(self.course.gates) - 1))
        lat, lon = f["lat"][sel], f["lon"][sel]
        order = np.argsort(bearing_deg(o[0], o[1], lat, lon))
        step = max(1, order.size // max_points)
        k = order[::step]
        return {"t": float(t), "lat": np.round(lat[k], 3).tolist(), "lon": np.round(lon[k], 3).tolist()}

    def _gate_distance(self, lat, lon, g) -> np.ndarray:
        """Distance (nm) de chaque point au segment de la porte qu'il vise (échantillonné en 5 points)."""
        out = np.full(lat.size, np.inf)
        for gi in np.unique(g):
            if gi >= len(self.course.gates):
                out[g == gi] = 0.0
                continue
            gate = self.course.gates[int(gi)]
            sel = g == gi
            for frac in np.linspace(0, 1, 5):
                la = gate.a[0] + (gate.b[0] - gate.a[0]) * frac
                lo = gate.a[1] + (gate.b[1] - gate.a[1]) * frac
                out[sel] = np.minimum(out[sel], haversine_nm(lat[sel], lon[sel], la, lo))
        return out

    def _near_gate(self, f) -> float:
        """Distance minimale (nm) entre le front et le segment de la porte que chaque point vise."""
        best = np.inf
        for g in np.unique(f["gate"]):
            if g >= len(self.course.gates):
                continue
            gate = self.course.gates[int(g)]
            sel = f["gate"] == g
            for frac in (0.0, 0.5, 1.0):
                la = gate.a[0] + (gate.b[0] - gate.a[0]) * frac
                lo = gate.a[1] + (gate.b[1] - gate.a[1]) * frac
                best = min(best, float(haversine_nm(f["lat"][sel], f["lon"][sel], la, lo).min()))
        return best

    def _prune(self, cand, idx, nlat, nlon, gate, slat, slon):
        """Un point par (porte visée, secteur vu de l'origine de branche) : le plus éloigné, segment libre."""
        if cand.size == 0:
            return cand
        g = gate[cand]
        # Entonnoir : on abandonne les points sans espoir, beaucoup plus loin de leur porte que le meilleur.
        dg = self._gate_distance(nlat[cand], nlon[cand], g)
        keep = np.ones(cand.size, bool)
        for gi in np.unique(g):
            sel = g == gi
            best = float(dg[sel].min())
            keep[sel] = dg[sel] <= best + max(self.p.funnel_nm, 2.0 * best)
        cand, g = cand[keep], g[keep]
        olat = np.empty(cand.size)
        olon = np.empty(cand.size)
        for gi in np.unique(g):
            o = self.course.leg_origin(min(int(gi), len(self.course.gates) - 1))
            olat[g == gi], olon[g == gi] = o
        brg = bearing_deg(olat, olon, nlat[cand], nlon[cand])
        dist = haversine_nm(olat, olon, nlat[cand], nlon[cand])
        # Largeur angulaire par groupe de porte : ~sector_nm milles au rayon le plus lointain du front.
        width = np.empty(cand.size)
        for gi in np.unique(g):
            sel = g == gi
            r = max(float(dist[sel].max()), 1.0)
            width[sel] = np.clip(np.degrees(self.p.sector_nm / r), self.p.sector_min_deg, self.p.sector_deg)
        key = g.astype(np.int64) * 10_000_000 + (brg // width).astype(np.int64)
        order = np.lexsort((-dist, key))
        cand, key = cand[order], key[order]
        alive = np.ones(cand.size, bool)

        def first_per_key():
            pos = np.flatnonzero(alive)
            if pos.size == 0:
                return pos
            k = key[pos]
            return pos[np.r_[True, k[1:] != k[:-1]]]

        # Le meilleur de chaque secteur dont le segment touche un obstacle cède la place au suivant.
        for _ in range(6):
            first = first_per_key()
            pick = cand[first]
            clear = self.mask.segments_clear(slat[pick], slon[pick], nlat[pick], nlon[pick])
            if clear.all():
                return pick
            alive[first[~clear]] = False
        pick = cand[first_per_key()]
        clear = self.mask.segments_clear(slat[pick], slon[pick], nlat[pick], nlon[pick])
        return pick[clear]

    def _backtrack(self, history, t0, lat0, lon0, arrival, isochrones, stats) -> RouteResult:
        if not history:
            raise RuntimeError("aucun pas calculé")
        if arrival is not None:
            k_last, eta = 0, arrival[1]  # le dernier pas ne contient que le nœud arrivé
        else:
            # Pas d'arrivée : on garde le point le plus avancé (porte la plus haute, puis le plus proche).
            last = history[-1]
            gmax = last["gate"].max()
            target = self.course.gates[min(gmax, len(self.course.gates) - 1)].mid
            d = haversine_nm(last["lat"], last["lon"], *target)
            d = np.where(last["gate"] == gmax, d, np.inf)
            k_last, eta = int(np.argmin(d)), None
        chain = []
        k = k_last
        for step in reversed(history):
            chain.append((step, k))
            k = step["parent"][k]
        chain.reverse()
        pts = []
        prev_lat, prev_lon = lat0, lon0
        for step, k in chain:
            pts.append(RoutePoint(t=step["t"], lat=prev_lat, lon=prev_lon, heading=float(step["heading"][k]),
                                  twa=float(step["twa"][k]), twd=float(step["twd"][k]), tws=float(step["tws"][k]),
                                  sail=int(step["sail"][k]), speed=float(step["speed"][k]),
                                  energy=float(step["energy"][k]), maneuver=int(step["maneuver"][k]),
                                  gate=int(step["gate"][k]),
                                  beyond_forecast=self.wind.beyond_forecast(step["t"])))
            prev_lat, prev_lon = float(step["lat"][k]), float(step["lon"][k])
        end_t = eta if eta is not None else chain[-1][0]["t"] + chain[-1][0]["dt"]
        last = pts[-1]
        pts.append(RoutePoint(t=end_t, lat=prev_lat, lon=prev_lon, heading=last.heading, twa=last.twa, twd=last.twd,
                              tws=last.tws, sail=last.sail, speed=last.speed, energy=last.energy, maneuver=0,
                              gate=len(self.course.gates) if eta is not None else last.gate,
                              beyond_forecast=self.wind.beyond_forecast(end_t)))
        dist = float(sum(haversine_nm(a.lat, a.lon, b.lat, b.lon) for a, b in zip(pts, pts[1:])))
        return RouteResult(points=pts, arrived=eta is not None, eta=eta, start_time=t0, distance_nm=dist,
                           isochrones=isochrones, stats=stats)
