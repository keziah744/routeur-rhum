"""Ligne de commande : python -m routeur <commande>.

  meteo                 récupère le dernier cycle GFS (sans recalculer la route)
  route                 calcule la route avec la prévision courante (ou --gfs fichier)
  cycle                 tâche planifiée : météo, puis route si la prévision a changé
  ensemble              31 scénarios GEFS : route la plus sûre (tâche planifiée n° 2)
  expliquer             explication de la route en français par Claude (clé ANTHROPIC_API_KEY)
  position              enregistre la position d'un bateau (--bateau) puis recalcule sa route
  relais                relève les positions envoyées depuis la page (ntfy.sh) et recalcule
  masque                reconstruit le masque terre + zones interdites
  serveur               interface web locale (téléphone sur le même réseau)
  planifier / deplanifier   installe / retire la tâche planifiée Windows (toutes les heures)
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone

from .config import ROOT, load_config, setup_logging

log = logging.getLogger("routeur")
TASK_NAME = "RouteurRhum-cycle"


from .relay import parse_coord, sail_index  # noqa: E402,F401  (réexporté pour les tests)


def parse_start(args, svc) -> dict | None:
    if not (args.depart or args.position):
        return None
    if args.depart == "maintenant":
        t = datetime.now(timezone.utc).timestamp()
    elif args.depart in (None, "course"):
        t = svc.course.start_time
    else:
        t = datetime.fromisoformat(args.depart.replace("Z", "+00:00")).timestamp()
    if args.position:
        lat, lon = (float(x) for x in args.position.split(","))
    else:
        lat, lon = svc.course.start_lat, svc.course.start_lon
    return {"time": t, "lat": lat, "lon": lon, "gate": args.porte, "source": "ligne de commande"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m routeur", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="fichier de configuration (défaut : config.toml)")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--bateau", help="identifiant du bateau (défaut : le premier de config.toml)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("meteo")
    r = sub.add_parser("route")
    r.add_argument("--gfs", help="forecast.npz déjà téléchargé (mode test hors ligne)")
    r.add_argument("--depart", help="« course » (défaut), « maintenant » ou heure ISO UTC")
    r.add_argument("--position", help="LAT,LON de départ (degrés décimaux, ouest négatif)")
    r.add_argument("--porte", type=int, default=0, help="index de la prochaine porte à franchir")
    po = sub.add_parser("position", help="enregistre la position lue dans le jeu puis recalcule")
    po.add_argument("--lat", required=True, help="ex. « 46°12,5 N » ou 46.2083")
    po.add_argument("--lon", required=True, help="ex. « 23°40,1 W » ou -23.668")
    po.add_argument("--voile", default="", help="voile actuelle (Jib, Spi, Code0…), facultatif")
    po.add_argument("--porte", type=int, default=1, help="prochaine marque (1 = Tête à l'Anglais)")
    sub.add_parser("expliquer")
    sub.add_parser("relais")
    e = sub.add_parser("ensemble")
    e.add_argument("--force", action="store_true", help="recalcule les scénarios même sans nouveau cycle")
    c = sub.add_parser("cycle")
    c.add_argument("--force", action="store_true", help="recalcule la route même sans nouvelle météo")
    sub.add_parser("masque")
    s = sub.add_parser("serveur")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--hote", default="0.0.0.0", help="0.0.0.0 = accessible depuis le téléphone sur le Wi-Fi")
    sub.add_parser("planifier")
    sub.add_parser("deplanifier")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    setup_logging(cfg, args.verbose)
    from .service import Busy, Service

    if args.cmd == "masque":
        return subprocess.call([sys.executable, str(ROOT / "scripts" / "build_mask.py")])
    if args.cmd == "serveur":
        from .server import serve
        serve(cfg, args.hote, args.port)
        return 0
    if args.cmd == "planifier":
        return schedule(install=True)
    if args.cmd == "deplanifier":
        return schedule(install=False)

    svc = Service(cfg, args.bateau)
    try:
        if args.cmd == "meteo":
            print(json.dumps(svc.update_weather(), indent=1, ensure_ascii=False))
        elif args.cmd == "route":
            last = [0.0]

            def progress(h, gate, n, near=float("nan")):
                if h - last[0] >= 12:
                    last[0] = h
                    log.info("t+%.0f h, porte %d, %d points dans le front, %.0f milles de la porte", h, gate, n, near)

            from .config import resolve
            from .service import file_lock
            with file_lock(resolve(cfg["service"]["lock_file"])):
                doc = svc.compute_route(wind_path=args.gfs, start=parse_start(args, svc), progress=progress)
            print(f"ETA {doc['eta']}  durée {doc['duration_h']} h  distance {doc['distance_nm']} nm  "
                  f"{len(doc['waypoints'])} waypoints  {len(doc['sail_changes'])} changements de voile  "
                  f"contrôle waypoints {doc['check_waypoints']}")
        elif args.cmd == "cycle":
            print(json.dumps(svc.cycle(force_route=args.force), indent=1, ensure_ascii=False))
        elif args.cmd == "relais":
            from .config import resolve
            from .relay import relay
            flag = resolve("data/.relais-nouveau")
            flag.unlink(missing_ok=True)
            updated = relay(cfg, svc.polar.sail_names)
            if updated:
                flag.write_text(",".join(updated), encoding="utf-8")  # signal pour GitHub Actions : publier
                print(json.dumps(svc.cycle(force_route=True, boats=updated), indent=1, ensure_ascii=False))
            else:
                print("aucune nouvelle position")
        elif args.cmd == "position":
            import time as _time
            from .config import resolve
            from .service import write_json
            pos = {"time": _time.time(), "lat": parse_coord(args.lat, True), "lon": parse_coord(args.lon, False),
                   "gate": args.porte}
            from .service import position_file
            sail = sail_index(args.voile, svc.polar.sail_names)
            if sail is not None:
                pos["sail"] = sail
            write_json(position_file(svc.boat), pos)
            log.info("[%s] position enregistrée : %.4f, %.4f", svc.boat, pos["lat"], pos["lon"])
            print(json.dumps(svc.cycle(force_route=True, boats=[svc.boat]), indent=1, ensure_ascii=False))
        elif args.cmd == "expliquer":
            print(json.dumps(svc.write_explanation(), indent=1, ensure_ascii=False))
        elif args.cmd == "ensemble":
            print(json.dumps(svc.ensemble_cycle(force=args.force), indent=1, ensure_ascii=False))
    except Busy as exc:
        log.warning("%s : rien à faire", exc)
        return 0
    return 0


# (nom, script, minute de départ, durée max en heures) : sans effet tant que rien de neuf n'est publié.
TASKS = [(TASK_NAME, "cycle.py", "00:05", 1), ("RouteurRhum-ensemble", "ensemble.py", "00:35", 3)]


def schedule(install: bool) -> int:
    """Tâches Windows : route GFS (cycle) et scénarios GEFS (ensemble), toutes les heures."""
    if not install:
        return max(subprocess.call(["schtasks", "/Delete", "/TN", name, "/F"]) for name, *_ in TASKS)
    # pythonw : pas de fenêtre console à chaque exécution.
    py = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    for name, script, start, hours in TASKS:
        tr = f'"{py}" "{ROOT / "scripts" / script}"'
        code = subprocess.call(["schtasks", "/Create", "/TN", name, "/TR", tr, "/SC", "HOURLY",
                                "/MO", "1", "/ST", start, "/F"])
        if code:
            return code
        # Par défaut, Windows ne lance pas la tâche sur batterie et ne rattrape pas les heures manquées (veille).
        ps = (f"$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
              f"-StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours {hours}) -MultipleInstances IgnoreNew; "
              f"Set-ScheduledTask -TaskName '{name}' -Settings $s | Out-Null")
        code = subprocess.call(["powershell", "-NoProfile", "-Command", ps])
        if code:
            return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
