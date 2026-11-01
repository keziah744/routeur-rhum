"""Feuille de route : waypoints simplifiés, changements de voile, vérification et exports.

Format de sortie (route.json) documenté dans docs/FORMAT.md.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import numpy as np

from .geo import LandMask, haversine_nm, rhumb_bearing_distance, rhumb_destination
from .isochrones import MANEUVER_GYBE, MANEUVER_SAIL, MANEUVER_TACK, RouteResult
from .polar import Polar
from .wind import WindField

# Noms des voiles tels qu'affichés dans le jeu (identiques en version française).
SAIL_LABEL = {"Jib": "Jib", "Spi": "Spi", "Staysail": "Staysail", "LightJib": "Light Jib", "Code0": "Code 0",
              "HeavyGnk": "Heavy Gnk", "LightGnk": "Light Gnk"}


def sail_label(name: str) -> str:
    return SAIL_LABEL.get(name, name)


@dataclass
class Waypoint:
    n: int
    lat: float
    lon: float
    t: float
    heading: float      # cap loxodromique vers le waypoint suivant
    twa: float          # TWA prévue au départ du segment
    tws: float
    twd: float
    sail: str           # voile à utiliser sur le segment suivant
    speed: float
    reason: str
    beyond_forecast: bool


@dataclass
class SailChange:
    t: float
    lat: float
    lon: float
    sail_from: str
    sail_to: str
    gain_pct: float
    twa: float
    tws: float


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="minutes").replace("+00:00", "Z")


def _local_xy(lat, lon, lat0):
    return np.column_stack([np.asarray(lon) * 60 * np.cos(np.radians(lat0)), np.asarray(lat) * 60])


def douglas_peucker(lat, lon, tol_nm, keep: set[int]) -> list[int]:
    """Indices conservés (toujours les extrémités et `keep`), écart latéral max tol_nm."""
    xy = _local_xy(lat, lon, float(np.mean(lat)))
    anchors = sorted({0, len(lat) - 1, *keep})
    out = set(anchors)

    def rec(i, j):
        if j <= i + 1:
            return
        a, b = xy[i], xy[j]
        ab = b - a
        L = np.hypot(*ab)
        pts = xy[i + 1:j]
        if L < 1e-9:
            d = np.hypot(*(pts - a).T)
        else:
            d = np.abs(ab[0] * (pts[:, 1] - a[1]) - ab[1] * (pts[:, 0] - a[0])) / L
        k = int(np.argmax(d))
        if d[k] > tol_nm:
            m = i + 1 + k
            out.add(m)
            rec(i, m)
            rec(m, j)

    for i, j in zip(anchors, anchors[1:]):
        rec(i, j)
    return sorted(out)


def build_roadmap(res: RouteResult, polar: Polar, mask: LandMask, gate_names: list[str],
                  tol_nm: float = 3.0, wind: WindField | None = None, max_loss_pct: float = 2.0,
                  max_loss_s: float = 120.0) -> dict:
    pts = res.points
    lat = np.array([p.lat for p in pts])
    lon = np.array([p.lon for p in pts])
    names = polar.sail_names

    # Points imposés : manœuvres de virement/empannage, franchissement de porte.
    reasons: dict[int, str] = {0: "Départ", len(pts) - 1: "Arrivée" if res.arrived else "Fin du calcul"}
    for k in range(1, len(pts) - 1):
        p = pts[k]
        if p.maneuver & MANEUVER_TACK:
            reasons.setdefault(k, "Virement de bord")
        elif p.maneuver & MANEUVER_GYBE:
            reasons.setdefault(k, "Empannage")
        if pts[k].gate != pts[k - 1].gate and pts[k - 1].gate < len(gate_names):
            reasons[k] = f"Porte : {gate_names[pts[k - 1].gate]}"
    keep = douglas_peucker(lat, lon, tol_nm, set(reasons))
    # Évitement des terres : un segment simplifié qui touche un obstacle est recoupé.
    changed = True
    while changed:
        changed = False
        for a, b in zip(keep, keep[1:]):
            if b > a + 1 and not mask.segments_clear(lat[a], lon[a], lat[b], lon[b]):
                xy = _local_xy(lat[a:b + 1], lon[a:b + 1], float(lat[a]))
                ab = xy[-1] - xy[0]
                L = max(np.hypot(*ab), 1e-9)
                d = np.abs(ab[0] * (xy[1:-1, 1] - xy[0, 1]) - ab[1] * (xy[1:-1, 0] - xy[0, 0])) / L
                m = a + 1 + int(np.argmax(d))
                keep = sorted({*keep, m})
                reasons.setdefault(m, "Évitement des terres / zone interdite")
                changed = True
                break

    # Performance : un leg simplifié resimulé ne doit pas perdre plus de max_loss (sinon on le recoupe).
    if wind is not None:
        changed = True
        while changed:
            changed = False
            for a, b in zip(keep, keep[1:]):
                if b <= a + 1:
                    continue
                pa, pb = pts[a], pts[b]
                wa = Waypoint(0, pa.lat, pa.lon, pa.t, 0, 0, 0, 0, "", 0, "", False)
                wb = Waypoint(1, pb.lat, pb.lon, pb.t, 0, 0, 0, 0, "", 0, "", False)
                t_sim = simulate_waypoints([wa, wb], wind, polar, pa.t, dt_s=300)
                planned = pb.t - pa.t
                if t_sim is None or t_sim - pb.t > max(planned * max_loss_pct / 100, max_loss_s):
                    m = (a + b) // 2
                    keep = sorted({*keep, m})
                    reasons.setdefault(m, None)
                    changed = True
                    break
        reasons = {k: v for k, v in reasons.items() if v is not None}

    wps = []
    for n, k in enumerate(keep):
        p = pts[k]
        if n + 1 < len(keep):
            brg, _ = rhumb_bearing_distance(p.lat, p.lon, lat[keep[n + 1]], lon[keep[n + 1]])
            brg = float(brg)
        else:
            brg = p.heading
        reason = reasons.get(k)
        if reason is None:
            prev_h = pts[keep[n - 1]].heading
            dh = abs((p.heading - prev_h + 180) % 360 - 180)
            dtwa = abs(abs(p.twa) - abs(pts[keep[n - 1]].twa))
            reason = ("Stratégie météo : suivre la bascule du vent" if dh > 8 and dtwa < 8
                      else "Changement de cap")
        wps.append(Waypoint(n=n, lat=round(p.lat, 5), lon=round(p.lon, 5), t=p.t, heading=round(brg, 1),
                            twa=round(p.twa, 1), tws=round(p.tws, 1), twd=round(p.twd, 1),
                            sail=names[p.sail], speed=round(p.speed, 2), reason=reason,
                            beyond_forecast=p.beyond_forecast))

    # Changements de voile : le moteur ne change que si le gain dépasse le seuil (tolérance VR / config).
    changes = []
    for k in range(1, len(pts) - 1):
        a, b = pts[k - 1], pts[k]
        if b.sail != a.sail:
            sp = polar.sail_speeds([abs(b.twa)], [b.tws])[:, 0]
            gain = (sp[b.sail] / max(sp[a.sail], 1e-6) - 1) * 100
            changes.append(SailChange(t=b.t, lat=round(b.lat, 4), lon=round(b.lon, 4), sail_from=names[a.sail],
                                      sail_to=names[b.sail], gain_pct=round(float(gain), 1),
                                      twa=round(b.twa, 1), tws=round(b.tws, 1)))
    return {"waypoints": wps, "sail_changes": changes}


def simulate_waypoints(wps: list[Waypoint], wind: WindField, polar: Polar, t0: float, dt_s: float = 600) -> float | None:
    """Temps d'arrivée en suivant les waypoints (cap direct, meilleure voile, pénalités) : contrôle de la
    simplification. Renvoie l'heure d'arrivée au dernier waypoint, None si non atteint."""
    lat, lon, t = wps[0].lat, wps[0].lon, t0
    prev_twa, sail = 0.0, -1
    tired = float(polar.stamina_multiplier(100.0))  # énergie supposée pleine pour ce contrôle
    for wp in wps[1:]:
        for _ in range(100000):
            brg, dist = rhumb_bearing_distance(lat, lon, wp.lat, wp.lon)
            if dist < 0.05:
                break
            twd, tws = wind.wind(np.array([lat]), np.array([lon]), t)
            twa = float((twd[0] - brg + 180) % 360 - 180)
            speed, best, allsp = polar.best([abs(twa)], tws)
            v = float(speed[0])
            loss = 0.0
            if sail >= 0 and best[0] != sail and allsp[best[0], 0] > allsp[sail, 0] * polar.auto_tolerance:
                tm, r = polar.penalty("sailChange", tws)
                loss += float(tm[0]) * tired * (1 - r)
                sail = int(best[0])
            elif sail < 0:
                sail = int(best[0])
            else:
                v = float(allsp[sail, 0])
            if prev_twa and np.sign(prev_twa) != np.sign(twa):
                kind = "tack" if abs(twa) < 90 else "gybe"
                tm, r = polar.penalty(kind, tws)
                loss += float(tm[0]) * tired * (1 - r)
            prev_twa = twa
            step_nm = v * dt_s / 3600 - v * loss / 3600
            if v <= 0.01:
                return None
            if step_nm >= dist:
                t += dist / v * 3600
                lat, lon = wp.lat, wp.lon
                break
            lat, lon = (float(x) for x in rhumb_destination(lat, lon, float(brg), step_nm))
            t += dt_s
    return t


def check_legs(wps: list[Waypoint], wind: WindField, polar: Polar) -> dict:
    """Contrôle de la feuille de route : chaque leg est resimulé (pas de 5 min) depuis son heure prévue.

    Mesure la perte due à la simplification et au pas du moteur, sans l'effet cumulé d'un retard
    (qui change la météo rencontrée : la route est de toute façon recalculée à chaque cycle).
    """
    planned = simulated = 0.0
    worst = []
    for a, b in zip(wps, wps[1:]):
        t = simulate_waypoints([a, b], wind, polar, a.t, dt_s=300)
        dt_plan = b.t - a.t
        dt_sim = (t - a.t) if t else dt_plan * 3
        planned += dt_plan
        simulated += dt_sim
        worst.append((dt_sim - dt_plan, a.n))
    worst.sort(reverse=True)
    return {"planned_h": round(planned / 3600, 2), "simulated_h": round(simulated / 3600, 2),
            "loss_pct": round((simulated / planned - 1) * 100, 1) if planned else None,
            "worst_legs": [{"from_wp": n, "extra_min": round(x / 60)} for x, n in worst[:3] if x > 60]}


def order_advice(points, t0: float, t1: float, heading: float) -> dict:
    """Ordre à donner dans le programmateur du jeu pour le segment [t0, t1[ : cap fixe ou TWA fixe.

    On garde ce qui varie le moins le long de la route : si le vent tourne, la route suit un angle au vent
    constant (TWA) plutôt qu'un cap. Un virement ou un empannage dans le segment impose le cap ; à 3° près, on
    garde aussi le cap, plus simple à programmer.
    """
    seg = [p for p in points if t0 <= p.t < t1] or [min(points, key=lambda p: abs(p.t - t0))]
    twas = np.array([p.twa for p in seg])
    heads = np.array([p.heading for p in seg])
    d_head = (heads - heads[0] + 180) % 360 - 180
    spread_cap = float(d_head.max() - d_head.min())
    spread_twa = float(twas.max() - twas.min())
    same_tack = bool(np.all(twas > 0) or np.all(twas < 0))
    if same_tack and spread_twa + 3 <= spread_cap:
        return {"mode": "twa", "value": round(float(np.median(twas))), "spread_cap": round(spread_cap),
                "spread_twa": round(spread_twa)}
    return {"mode": "cap", "value": round(heading) % 360, "spread_cap": round(spread_cap),
            "spread_twa": round(spread_twa)}


def route_document(res: RouteResult, roadmap: dict, meta: dict, check: dict | None) -> dict:
    """Document JSON publié pour l'interface et l'export."""
    pts = res.points
    wps = roadmap["waypoints"]
    ends = [w.t for w in wps[1:]] + [(res.eta or pts[-1].t) + 1]
    return {
        "format": "routeur-rhum/route@1",
        "computed_at": iso(datetime.now(timezone.utc).timestamp()),
        **meta,
        "start_time": iso(res.start_time),
        "arrived": res.arrived,
        "eta": iso(res.eta) if res.eta else None,
        "duration_h": round(((res.eta or pts[-1].t) - res.start_time) / 3600, 2),
        "distance_nm": round(res.distance_nm, 1),
        "check_waypoints": check,
        "beyond_forecast_from": next((iso(p.t) for p in pts if p.beyond_forecast), None),
        "stats": res.stats,
        "waypoints": [{**asdict(w), "t": iso(w.t), "order": order_advice(pts, w.t, t1, w.heading)}
                      for w, t1 in zip(wps, ends)],
        "sail_changes": [{**asdict(c), "t": iso(c.t)} for c in roadmap["sail_changes"]],
        "track": [[round(p.lat, 4), round(p.lon, 4), iso(p.t), p.sail, round(p.tws, 1), round(p.twa, 1),
                   round(p.speed, 1)] for p in pts],
        "isochrones": res.isochrones,
    }


def compare(prev: dict | None, cur: dict) -> dict | None:
    """Écarts entre l'ancienne et la nouvelle route (ETA, écart latéral, voiles)."""
    if not prev or not prev.get("track"):
        return None

    def ts(s):
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()

    pt = np.array([ts(p[2]) for p in prev["track"]])
    plat = np.array([p[0] for p in prev["track"]])
    plon = np.array([p[1] for p in prev["track"]])
    dev, dlat = [], []
    for la, lo, tt, *_ in cur["track"]:
        t = ts(tt)
        if pt[0] <= t <= pt[-1]:
            pla = np.interp(t, pt, plat)
            dev.append(float(haversine_nm(la, lo, pla, np.interp(t, pt, plon))))
            dlat.append(la - pla)
    eta_delta = ((ts(cur["eta"]) - ts(prev["eta"])) / 3600) if cur.get("eta") and prev.get("eta") else None
    return {"previous_cycle": prev.get("gfs_cycle"), "previous_computed_at": prev.get("computed_at"),
            "eta_delta_h": round(eta_delta, 2) if eta_delta is not None else None,
            "max_deviation_nm": round(max(dev), 1) if dev else None,
            "mean_deviation_nm": round(float(np.mean(dev)), 1) if dev else None,
            "mean_lat_shift_deg": round(float(np.mean(dlat)), 2) if dlat else None,
            "previous_track": [[p[0], p[1]] for p in prev["track"]],
            "previous_waypoints": [[w["lat"], w["lon"]] for w in prev.get("waypoints", [])]}


def to_csv(doc: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["n", "heure_utc", "latitude", "longitude", "cap", "twa", "tws_kt", "twd", "voile", "vitesse_kt",
                "ordre", "valeur_ordre", "motif"])
    for p in doc["waypoints"]:
        o = p.get("order") or {}
        w.writerow([p["n"], p["t"], p["lat"], p["lon"], p["heading"], p["twa"], p["tws"], p["twd"], sail_label(p["sail"]),
                    p["speed"], o.get("mode", ""), o.get("value", ""), p["reason"]])
    return buf.getvalue()


def to_gpx(doc: dict) -> str:
    rows = "\n".join(f'    <rtept lat="{p["lat"]}" lon="{p["lon"]}"><name>WP{p["n"]:02d}</name><time>{p["t"]}</time>'
                     f'<desc>{sail_label(p["sail"])} · cap {p["heading"]}° · {p["reason"]}</desc></rtept>' for p in doc["waypoints"])
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="routeur-rhum" '
            'xmlns="http://www.topografix.com/GPX/1/1">\n  <rte><name>Route du Rhum - Ultim</name>\n'
            f'{rows}\n  </rte>\n</gpx>\n')
