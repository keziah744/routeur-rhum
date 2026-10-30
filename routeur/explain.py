"""Explication de la route en français par Claude (clé API Anthropic de l'utilisateur).

N'influence pas le calcul : Claude lit les résultats du routeur (route, changements, scénarios) et
les raconte simplement. Sans clé (variable d'environnement ANTHROPIC_API_KEY), rien n'est appelé.
"""
from __future__ import annotations

import json
import logging
import os
import time

import anthropic

from .roadmap import iso

log = logging.getLogger("routeur.explain")

# Changer ce numéro quand le format change : les explications existantes sont alors refaites.
PROMPT_VERSION = 3

SYSTEM = """Tu es l'équipier d'un joueur de Virtual Regatta (Route du Rhum, Ultim). Un moteur de routage a déjà
calculé la route : tu ne recalcules rien, tu la résumes pour qu'il comprenne d'un coup d'œil sur son téléphone.

Écris 3 à 5 lignes, chacune commençant par un de ces intitulés, dans cet ordre, sans rien avant ni après :
Le plan : <par où passe la route et pourquoi>
À faire : <la prochaine action dans le jeu : jour, heure, cap, voile>
Ce qui a changé : <seulement si la route a nettement bougé depuis le calcul précédent>
Fiabilité : <ce que disent les scénarios météo, en mots simples>
Attention : <le principal risque>

Règles :
- Une ou deux phrases courtes par ligne, 30 mots au plus. Mots de tous les jours, pas de coordonnées,
  le moins de chiffres possible.
- Uniquement d'après les données fournies. Un système météo (alizés, front…) se présente comme une hypothèse :
  « on dirait un front », jamais comme une certitude.
- Heures de Paris, jours en toutes lettres : « dimanche à 13 h ». Pas de markdown.
- Ne promets jamais une arrivée certaine."""


def _facts(route: dict, ens: dict | None) -> dict:
    """Résumé compact des résultats envoyé à Claude (pas la trace complète)."""
    wps = route["waypoints"]
    step = max(1, len(wps) // 40)
    keep = wps[::step] + ([wps[-1]] if wps[-1] not in wps[::step] else [])
    c = route.get("comparison") or {}
    facts = {
        "course": route.get("race"), "bateau": route.get("boat"),
        "depart": route["start_time"], "depart_depuis": route.get("start_source"),
        "arrivee_estimee": route.get("eta"), "duree_h": route.get("duration_h"),
        "distance_milles": route.get("distance_nm"), "meteo": route.get("gfs_cycle"),
        "variante": route.get("variant", "route GFS"),
        "waypoints": [{k: w[k] for k in ("n", "t", "lat", "lon", "heading", "twa", "tws", "twd", "sail", "reason")}
                      for w in keep],
        "changements_de_voile": [{k: s[k] for k in ("t", "sail_from", "sail_to", "gain_pct", "tws")}
                                 for s in route.get("sail_changes", [])[:30]],
        "par_rapport_au_calcul_precedent": {k: c.get(k) for k in ("previous_cycle", "eta_delta_h", "max_deviation_nm",
                                                                    "mean_deviation_nm", "mean_lat_shift_deg")} if c else None,
        "maintenant_utc": iso(time.time()),
    }
    if ens:
        rec = next(x for x in ens["candidates"] if x["id"] == ens["recommended"])
        facts["scenarios_meteo"] = {
            "scenarios_testes": ens.get("judges", ens["scenarios"]), "route_conseillee": ens["recommended_label"],
            "arrivee_mediane": rec["median_eta"], "arrivee_10pct": rec["p10_eta"], "arrivee_90pct": rec["p90_eta"],
            "fait_mieux_que_la_route_gfs_dans_n_scenarios": rec.get("beats_gfs"),
            "gain_median_vs_route_gfs_h": ens["gain_vs_gfs_h"], "dispersion_arrivees_h": ens["spread_h"],
            "methode": f"chaque route suivie {ens.get('commit_h', 48)} h dans chaque scénario, puis recalcul supposé"}
    return facts


def has_credentials() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def explain(route: dict, ens: dict | None, cfg: dict) -> dict:
    """Renvoie {"state", "text", ...} ; ne lève pas d'exception (l'explication est un bonus)."""
    e = cfg.get("explain", {})
    base = {"for_route": route.get("computed_at"), "computed_at": iso(time.time()), "model": e.get("model"),
            "prompt": PROMPT_VERSION}
    if not e.get("enabled", True):
        return {**base, "state": "désactivé", "text": None}
    if not has_credentials():
        return {**base, "state": "pas de clé", "text": None}
    client = anthropic.Anthropic(timeout=120.0, max_retries=2)
    try:
        resp = client.beta.messages.create(
            model=e.get("model", "claude-opus-5-5"),
            max_tokens=4000,
            system=SYSTEM,
            output_config={"effort": e.get("effort", "medium")},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": "Résultats du routeur (JSON) :\n"
                       + json.dumps(_facts(route, ens), ensure_ascii=False)}],
        )
    except anthropic.AuthenticationError:
        return {**base, "state": "clé refusée", "text": None}
    except anthropic.RateLimitError:
        return {**base, "state": "limite atteinte", "text": None}
    except anthropic.APIStatusError as exc:
        log.warning("explication : erreur API %s", exc.status_code)
        return {**base, "state": f"erreur API {exc.status_code}", "text": None}
    except anthropic.APIConnectionError:
        return {**base, "state": "pas de réseau", "text": None}
    if resp.stop_reason == "refusal":
        return {**base, "state": "refusé", "text": None}
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    log.info("explication rédigée (%d caractères, %s jetons en sortie)", len(text), resp.usage.output_tokens)
    return {**base, "state": "ok", "text": text, "served_by": resp.model}
