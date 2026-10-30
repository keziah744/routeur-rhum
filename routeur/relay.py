"""Relais des positions sans compte : la page publie sur ntfy.sh, le routeur relève et recalcule.

Chaque message ntfy est un JSON {"data": "<json>", "sig": "<hex>"}. `data` contient {"bateau", "lat", "lon",
"voile"?, "porte"?, "twa"?, "t"} et `sig` = HMAC-SHA256(code du bateau, data). Le code ne circule donc jamais :
le sujet ntfy est public (il est dans la page), seul le code protège l'envoi. `t` (heure d'envoi) empêche de
rejouer un ancien message. Codes : secrets GitHub ROUTEUR_CODE_<BATEAU> (ex. ROUTEUR_CODE_PAPA) ou ROUTEUR_CODES
= {"keziah": "...", "papa": "..."}.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import urllib.error
import urllib.request

from .config import resolve
from .service import boats_of, position_file, read_json, write_json

log = logging.getLogger("routeur.relais")

NTFY = "https://ntfy.sh"
MAX_SKEW_S = 900   # écart toléré entre l'heure d'envoi signée et l'heure de réception ntfy
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


def norm_code(code) -> str:
    """Code tel que signé : sans espaces, en minuscules (saisie au téléphone, majuscule automatique)."""
    return "".join(str(code or "").split()).lower()


def codes_from_env(cfg: dict) -> dict[str, str]:
    codes = json.loads(os.environ.get("ROUTEUR_CODES") or "{}")
    for b in boats_of(cfg):
        v = os.environ.get(f"ROUTEUR_CODE_{b['id'].upper()}", "")
        if v.strip():
            codes[b["id"]] = v
    return {k: norm_code(v) for k, v in codes.items() if norm_code(v)}


def sign(code: str, text: str) -> str:
    return hmac.new(code.encode("utf-8"), text.encode("utf-8"), hashlib.sha256).hexdigest()


def check_value(code: str, boat: str) -> str:
    """Empreinte courte publiée dans boats.json : la page vérifie le code tapé avant d'envoyer."""
    return sign(code, f"routeur-rhum:{boat}")[:8]


def boats_public(cfg: dict) -> dict:
    """Contenu de web/data/boats.json : bateaux, sujet du relais, empreinte des codes connus."""
    codes = codes_from_env(cfg)
    boats = [{"id": b["id"], "name": b.get("name", b["id"]),
              **({"check": check_value(codes[b["id"]], b["id"])} if b["id"] in codes else {})}
             for b in boats_of(cfg)]
    return {"boats": boats, "ntfy_topic": (cfg.get("relay") or {}).get("ntfy_topic")}


def parse_message(msg: dict, cfg: dict, codes: dict, sail_names: list[str]) -> dict | None:
    """Position validée, ou None (message illisible, bateau inconnu, mauvaise signature, trop ancien)."""
    try:
        outer = json.loads(msg.get("message", ""))
        data, sig = str(outer["data"]), str(outer["sig"])
        body = json.loads(data)
        boat = str(body["bateau"])
    except (ValueError, KeyError, TypeError):
        log.warning("message %s illisible, ignoré", msg.get("id"))
        return None
    if boat not in {b["id"] for b in boats_of(cfg)}:
        log.warning("message %s : bateau inconnu, ignoré", msg.get("id"))
        return None
    code = codes.get(boat, "")
    if not code or not hmac.compare_digest(sig.strip().lower(), sign(code, data)):
        log.warning("message %s : mauvais code pour %s, ignoré", msg.get("id"), boat)
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
    try:
        pos = {"boat": boat, "time": min(sent, received), "lat": parse_coord(body["lat"], True),
               "lon": parse_coord(body["lon"], False), "gate": int(body.get("porte", 1))}
    except (ValueError, KeyError, TypeError) as exc:
        log.warning("message %s : position invalide (%s), ignoré", msg.get("id"), exc)
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
    """Relève les nouvelles positions, écrit data/positions/<bateau>.json. Renvoie les bateaux mis à jour."""
    topic = (cfg.get("relay") or {}).get("ntfy_topic")
    if not topic:
        return []
    codes = codes_from_env(cfg)
    if not codes:
        log.warning("aucun code de bateau (secrets ROUTEUR_CODE_…) : positions ignorées")
    state_p = resolve("data/relay-state.json")
    state = read_json(state_p) or {}
    try:
        msgs = fetch_messages(topic, state.get("last_id") or "12h", get)
    except (urllib.error.URLError, TimeoutError) as exc:
        log.warning("relais ntfy injoignable : %s", exc)
        return []
    latest: dict[str, dict] = {}
    recalc: set[str] = set()
    for m in msgs:
        pos = parse_message(m, cfg, codes, sail_names)
        if pos and pos.get("recalc"):
            recalc.add(pos["boat"])
            log.info("[%s] recalcul demandé depuis la page", pos["boat"])
        elif pos and (pos["boat"] not in latest or pos["time"] >= latest[pos["boat"]]["time"]):
            latest[pos["boat"]] = pos
    for boat, pos in latest.items():
        write_json(position_file(boat), {k: v for k, v in pos.items() if k != "boat"})
        log.info("[%s] nouvelle position reçue : %.4f, %.4f", boat, pos["lat"], pos["lon"])
    if msgs:
        write_json(state_p, {"last_id": msgs[-1]["id"], "last_time": msgs[-1].get("time")})
    return sorted(set(latest) | recalc)
