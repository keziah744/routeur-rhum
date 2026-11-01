"""Relais sans compte : la page publie sur ntfy.sh, le routeur relève et recalcule.

Chaque message ntfy est un JSON {"data": "<json>"}. `data` contient {"bateau", "t"} et, selon le cas :
une position {"lat", "lon", "voile"?, "porte"?, "twa"?}, {"action": "recalcul"} ou {"action": "options",
"options": {foils, hull, …}}. Pas de code : le sujet ntfy est public (il est dans la page), n'importe qui le
lisant pourrait donc envoyer une position (choix de Keziah, 01/11/2026). `t` (heure d'envoi) écarte les vieux
messages rejoués ; une ancienne signature `sig` éventuelle est ignorée.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request

from .config import resolve
from .service import OPTION_KEYS, boat_options, boats_of, options_file, position_file, read_json, write_json

log = logging.getLogger("routeur.relais")

NTFY = "https://ntfy.sh"
MAX_SKEW_S = 900   # écart toléré entre l'heure d'envoi écrite par la page et l'heure de réception ntfy
SAIL_FR = {"foc": "Jib", "spi": "Spi", "trinquette": "Staysail", "foc léger": "LightJib", "code 0": "Code0",
           "gennaker lourd": "HeavyGnk", "gennaker léger": "LightGnk"}


def parse_coord(txt, is_lat: bool) -> float:
    """« 46.2083 », « -23.668 », « 46°12,5 N », « 46 12.5 N », « 46°12'30\" N » -> degrés décimaux."""
    if isinstance(txt, (int, float)):
        v = float(txt)
    else:
        s = str(txt).strip().upper().replace(",", ".")
        nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", s)]
        if not nums:
            raise ValueError(f"coordonnée illisible : {txt!r}")
        v = nums[0] + (nums[1] / 60 if len(nums) > 1 else 0) + (nums[2] / 3600 if len(nums) > 2 else 0)
        if re.search(r"[SWO]", s) or s.startswith("-"):
            v = -v
    if abs(v) > (90 if is_lat else 180):
        raise ValueError(f"coordonnée hors limites : {txt!r}")
    return v


def sail_index(name: str, sail_names: list[str]) -> int | None:
    name = (name or "").strip()
    name = SAIL_FR.get(name.lower(), name)
    return sail_names.index(name) if name in sail_names else None


def http_get(url: str, timeout: float = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "routeur-rhum/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def fetch_messages(topic: str, since: str, get=http_get) -> list[dict]:
    """Messages ntfy publiés depuis `since` (identifiant de message ou durée, ex. « 12h »)."""
    text = get(f"{NTFY}/{topic}/json?poll=1&since={since}")
    msgs = []
    for line in text.splitlines():
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if m.get("event") == "message":
            msgs.append(m)
    return msgs


def boats_public(cfg: dict) -> dict:
    """Contenu de web/data/boats.json : bateaux, leurs options VR (et si elles ont été choisies), sujet du relais."""
    boats = []
    for b in boats_of(cfg):
        opts, chosen = boat_options(cfg, b["id"])
        boats.append({"id": b["id"], "name": b.get("name", b["id"]), "options": opts, "options_set": chosen})
    return {"boats": boats, "ntfy_topic": (cfg.get("relay") or {}).get("ntfy_topic")}


def parse_message(msg: dict, cfg: dict, sail_names: list[str]) -> dict | None:
    """Position, options ou recalcul validés, ou None (message illisible, bateau inconnu, trop ancien)."""
    try:
        outer = json.loads(msg.get("message", ""))
        body = json.loads(outer["data"]) if isinstance(outer, dict) and "data" in outer else outer
        boat = str(body["bateau"])
    except (ValueError, KeyError, TypeError):
        log.warning("message %s illisible, ignoré", msg.get("id"))
        return None
    if boat not in {b["id"] for b in boats_of(cfg)}:
        log.warning("message %s : bateau inconnu, ignoré", msg.get("id"))
        return None
    try:
        sent, received = float(body["t"]), float(msg["time"])
    except (ValueError, KeyError, TypeError):
        log.warning("message %s : heure d'envoi absente, ignoré", msg.get("id"))
        return None
    if abs(received - sent) > MAX_SKEW_S:
        log.warning("message %s : heure d'envoi incohérente (rejeu ?), ignoré", msg.get("id"))
        return None
    if body.get("action") == "recalcul":  # bouton « Recalculer » : pas de position, juste un nouveau calcul
        return {"boat": boat, "time": min(sent, received), "recalc": True}
    if body.get("action") == "options":  # écran « Tes options » : les sept cases, vraies ou fausses
        opts = body.get("options")
        if not isinstance(opts, dict) or not all(isinstance(opts.get(k), bool) for k in OPTION_KEYS):
            log.warning("message %s : options incomplètes, ignoré", msg.get("id"))
            return None
        return {"boat": boat, "time": min(sent, received), "options": {k: opts[k] for k in OPTION_KEYS}}
    try:
        pos = {"boat": boat, "time": min(sent, received), "lat": parse_coord(body["lat"], True),
               "lon": parse_coord(body["lon"], False), "gate": int(body.get("porte", 1))}
    except (ValueError, KeyError, TypeError) as exc:
        log.warning("message %s : position invalide (%s), ignoré", msg.get("id"), exc)
        return None
    g = cfg.get("gfs") or {}
    if not (g.get("lat_min", -90) <= pos["lat"] <= g.get("lat_max", 90)
            and g.get("lon_min", -180) <= pos["lon"] <= g.get("lon_max", 180)):
        log.warning("message %s : position hors de la zone météo, ignoré", msg.get("id"))
        return None
    sail = sail_index(body.get("voile", ""), sail_names)
    if sail is not None:
        pos["sail"] = sail
    if str(body.get("twa", "")).strip():
        try:
            pos["twa"] = float(str(body["twa"]).replace(",", "."))
        except ValueError:
            pass
    return pos


def relay(cfg: dict, sail_names: list[str], get=http_get) -> list[str]:
    """Relève les messages : data/positions/<bateau>.json (position) et <bateau>.options.json (options).
    Renvoie les bateaux à recalculer."""
    topic = (cfg.get("relay") or {}).get("ntfy_topic")
    if not topic:
        return []
    state_p = resolve("data/relay-state.json")
    state = read_json(state_p) or {}
    try:
        msgs = fetch_messages(topic, state.get("last_id") or "12h", get)
    except (urllib.error.URLError, TimeoutError) as exc:
        log.warning("relais ntfy injoignable : %s", exc)
        return []
    latest: dict[str, dict] = {}
    recalc: set[str] = set()
    options: dict[str, dict] = {}
    for m in msgs:
        pos = parse_message(m, cfg, sail_names)
        if pos and "options" in pos:
            if pos["boat"] not in options or pos["time"] >= options[pos["boat"]]["time"]:
                options[pos["boat"]] = pos
        elif pos and pos.get("recalc"):
            recalc.add(pos["boat"])
            log.info("[%s] recalcul demandé depuis la page", pos["boat"])
        elif pos and (pos["boat"] not in latest or pos["time"] >= latest[pos["boat"]]["time"]):
            latest[pos["boat"]] = pos
    for boat, pos in latest.items():
        write_json(position_file(boat), {k: v for k, v in pos.items() if k != "boat"})
        log.info("[%s] nouvelle position reçue : %.4f, %.4f", boat, pos["lat"], pos["lon"])
    for boat, o in options.items():
        write_json(options_file(boat), {"time": o["time"], "options": o["options"]})
        log.info("[%s] options reçues : %s", boat, ", ".join(k for k, v in o["options"].items() if v) or "aucune")
    if msgs:
        write_json(state_p, {"last_id": msgs[-1]["id"], "last_time": msgs[-1].get("time")})
    return sorted(set(latest) | recalc | set(options))
