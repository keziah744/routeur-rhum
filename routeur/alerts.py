"""Alertes sur le téléphone par ntfy.sh : route qui change vraiment, position à renvoyer.

On s'abonne au sujet <ntfy_topic>-<bateau> dans l'application ntfy (gratuite, sans compte). Les alertes ne
partent que si ROUTEUR_ALERTES=1 (GitHub Actions) : le PC calcule aussi des routes, il ne doit pas doubler les
messages avec des routes différentes.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import numpy as np

from .config import resolve
from .geo import haversine_nm

log = logging.getLogger("routeur.alertes")

NTFY = "https://ntfy.sh"
ETA_ALERT_H = 1.0          # écart d'arrivée qui mérite une alerte
DEVIATION_ALERT_NM = 15.0  # écart de trajectoire sur les 24 h à venir qui mérite une alerte
REMIND_AFTER_H = 6.0       # position plus vieille que ça : rappel (puis toutes les 6 h)
SAIL_FR = {"Jib": "Foc", "Spi": "Spi", "Staysail": "Trinquette", "LightJib": "Foc léger", "Code0": "Code 0",
           "HeavyGnk": "Gennaker lourd", "LightGnk": "Gennaker léger"}


def _paris():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Paris")
    except Exception:  # Windows sans tzdata : heure d'hiver, valable toute la course (novembre)
        return timezone(timedelta(hours=1))


PARIS = _paris()
DAYS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]


def ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def fmt(t: float) -> str:
    d = datetime.fromtimestamp(t, PARIS)
    return f"{DAYS[d.weekday()]} {d:%d/%m %H:%M}"


def enabled() -> bool:
    return os.environ.get("ROUTEUR_ALERTES") == "1"


def topic(cfg: dict, boat: str) -> str | None:
    base = (cfg.get("relay") or {}).get("ntfy_topic")
    return f"{base}-{boat}" if base else None


def page_url(cfg: dict, boat: str) -> str | None:
    url = (cfg.get("relay") or {}).get("page_url")
    return f"{url}?bateau={boat}" if url else None


def http_post(payload: dict, timeout: float = 20) -> None:
    """Publication JSON (titre et texte accentués sans souci d'en-têtes HTTP)."""
    req = urllib.request.Request(NTFY, data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"User-Agent": "routeur-rhum/0.1", "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=timeout).close()


def send(cfg: dict, boat: str, title: str, message: str, tag: str = "sailboat", post=http_post) -> bool:
    t = topic(cfg, boat)
    if not (enabled() and t):
        return False
    payload = {"topic": t, "title": title, "message": message, "tags": [tag]}
    url = page_url(cfg, boat)
    if url:
        payload["click"] = url
    try:
        post(payload)
        log.info("[%s] alerte envoyée : %s", boat, title)
        return True
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.warning("[%s] alerte non envoyée : %s", boat, exc)
        return False


def deviation_next_24h(prev: dict, doc: dict, now: float) -> float:
    """Écart maximal (milles) entre l'ancienne et la nouvelle route sur les 24 h à venir."""
    def series(d):
        tr = d.get("track") or []
        return (np.array([ts(p[2]) for p in tr]), np.array([p[0] for p in tr]), np.array([p[1] for p in tr]))

    (pt, pla, plo), (ct, cla, clo) = series(prev), series(doc)
    if not pt.size or not ct.size:
        return 0.0
    t0 = max(now, pt[0], ct[0])
    t1 = min(t0 + 24 * 3600, pt[-1], ct[-1])
    if t1 <= t0:
        return 0.0
    tt = np.linspace(t0, t1, 25)
    d = haversine_nm(np.interp(tt, pt, pla), np.interp(tt, pt, plo), np.interp(tt, ct, cla), np.interp(tt, ct, clo))
    return float(np.max(d))


def route_change_message(prev: dict | None, doc: dict, now: float | None = None) -> str | None:
    """Texte de l'alerte si la nouvelle route change vraiment quelque chose, sinon None."""
    if not prev or not doc.get("track") or not prev.get("track"):
        return None
    now = now or time.time()
    eta_d = (ts(doc["eta"]) - ts(prev["eta"])) / 3600 if doc.get("eta") and prev.get("eta") else 0.0
    dev = deviation_next_24h(prev, doc, now)
    if abs(eta_d) < ETA_ALERT_H and dev < DEVIATION_ALERT_NM:
        return None
    lines = [f"Arrivée {fmt(ts(doc['eta']))} ({'+' if eta_d > 0 else '−'}{abs(eta_d):.1f} h)."
             if doc.get("eta") else "Arrivée hors de la durée de calcul."]
    if dev >= DEVIATION_ALERT_NM:
        lines.append(f"La route des 24 prochaines heures bouge (jusqu'à {dev:.0f} milles) : reprogramme le jeu.")
    wp = next((w for w in doc.get("waypoints", []) if ts(w["t"]) > now), None)
    if wp:
        lines.append(f"Prochain waypoint WP{wp['n']:02d} à {fmt(ts(wp['t']))} : cap {round(wp['heading']) % 360:03d}°, "
                     f"{SAIL_FR.get(wp['sail'], wp['sail'])}.")
    return "\n".join(lines)


def remind_positions(cfg: dict, boats: list[dict], last_positions: dict[str, float | None], race_start: float,
                     now: float | None = None, post=http_post) -> list[str]:
    """Rappel « envoie ta position » quand la dernière date de plus de 6 h (au plus une fois toutes les 6 h)."""
    from .service import read_json, write_json
    now = now or time.time()
    if not enabled() or now < race_start + 3600:
        return []
    state_p = resolve("data/alerts-state.json")
    state = read_json(state_p) or {}
    sent = []
    for b in boats:
        last = last_positions.get(b["id"])
        age_h = (now - (last or race_start)) / 3600
        reminded = state.get(f"rappel-{b['id']}", 0)
        if age_h >= REMIND_AFTER_H and (now - reminded) / 3600 >= REMIND_AFTER_H:
            msg = (f"Ta dernière position date de {age_h:.0f} h. La route suppose que tu as suivi ses waypoints : "
                   "envoie ta position depuis l'onglet Météo." if last else
                   "Aucune position envoyée depuis le départ : envoie ta position depuis l'onglet Météo.")
            if send(cfg, b["id"], f"Position à envoyer · {b.get('name', b['id'])}", msg, "round_pushpin", post):
                state[f"rappel-{b['id']}"] = now
                sent.append(b["id"])
    if sent:
        write_json(state_p, state)
    return sent
