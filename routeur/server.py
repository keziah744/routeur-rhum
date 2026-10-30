"""Serveur local : sert l'interface (web/) et une petite API pour le téléphone.

  GET  /api/ping       présence de l'API (l'interface masque les boutons sans elle, ex. GitHub Pages)
  GET  /api/job        état du calcul lancé depuis l'interface
  POST /api/position   {"lat": .., "lon": .., "sail": "Code0"?, "twa": ..?} puis recalcul de la route
  POST /api/recalcul   recalcul de la route avec la météo courante
"""
from __future__ import annotations

import json
import logging
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from .config import resolve
from .roadmap import iso
from .service import Busy, Service, write_json

log = logging.getLogger("routeur.server")


class Jobs:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.lock = threading.Lock()
        self.state = {"state": "inactif"}

    def start(self, label: str, fn) -> bool:
        with self.lock:
            if self.state.get("state") == "en cours":
                return False
            self.state = {"state": "en cours", "label": label, "started_at": iso(time.time())}

        def run():
            try:
                fn()
                result = {"state": "terminé"}
            except Busy:
                result = {"state": "occupé", "message": "Un calcul planifié est déjà en cours."}
            except Exception as exc:  # message lisible pour l'interface
                log.exception("tâche « %s » échouée", label)
                result = {"state": "erreur", "message": str(exc)}
            with self.lock:
                self.state = {**self.state, **result, "finished_at": iso(time.time())}

        threading.Thread(target=run, daemon=True).start()
        return True


def make_handler(cfg: dict, jobs: Jobs):
    web = resolve("web")

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, fmt, *args):
            log.debug("%s %s", self.address_string(), fmt % args)

        def end_headers(self):
            # Données : jamais en cache ; interface : revalidée à chaque chargement (mises à jour visibles).
            data = self.path.startswith("/data/") or self.path.startswith("/api/")
            self.send_header("Cache-Control", "no-store" if data else "no-cache")
            super().end_headers()

        def _json(self, code: int, body: dict):
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/api/ping":
                return self._json(200, {"ok": True})
            if self.path == "/api/job":
                return self._json(200, jobs.state)
            return super().do_GET()

        def do_POST(self):
            length = min(int(self.headers.get("Content-Length") or 0), 10_000)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._json(400, {"error": "JSON invalide"})
            svc = Service(cfg)
            if self.path == "/api/position":
                try:
                    lat, lon = float(body["lat"]), float(body["lon"])
                    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                        raise ValueError
                except (KeyError, TypeError, ValueError):
                    return self._json(400, {"error": "latitude / longitude invalides"})
                pos = {"time": time.time(), "lat": lat, "lon": lon, "gate": int(body.get("gate", 1))}
                if body.get("sail") in svc.polar.sail_names:
                    pos["sail"] = svc.polar.sail_names.index(body["sail"])
                if body.get("twa") not in (None, ""):
                    pos["twa"] = float(body["twa"])
                write_json(resolve("data/position.json"), pos)
                ok = jobs.start("recalcul depuis la position saisie", lambda: svc.cycle(force_route=True))
                return self._json(202 if ok else 409, {"accepted": ok, **jobs.state})
            if self.path == "/api/recalcul":
                ok = jobs.start("recalcul de la route", lambda: svc.cycle(force_route=True))
                return self._json(202 if ok else 409, {"accepted": ok, **jobs.state})
            return self._json(404, {"error": "inconnu"})

    return partial(Handler, directory=str(web))


def serve(cfg: dict, host: str, port: int) -> None:
    httpd = ThreadingHTTPServer((host, port), make_handler(cfg, Jobs(cfg)))
    log.info("interface : http://%s:%d/ (Ctrl+C pour arrêter)", "localhost" if host == "0.0.0.0" else host, port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
