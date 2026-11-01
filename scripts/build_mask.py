"""Construit le masque terre + zones interdites (data/geo/mask.npz) et les côtes d'affichage.

Usage : .venv\\Scripts\\python.exe scripts\\build_mask.py
À relancer si la marge de sécurité, la zone ou les zones interdites changent.
"""
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from routeur.config import load_config, resolve  # noqa: E402
from routeur.course import Course  # noqa: E402
from routeur.geo import LandMask, coastline_geojson  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
cfg = load_config()
course = Course.load(resolve(cfg["course"]["file"]))
bbox = {k: cfg["gfs"][k] for k in ("lat_min", "lat_max", "lon_min", "lon_max")}
gshhg = resolve("data/geo/sources/gshhg-bin-2.3.7.zip")
t = time.time()
mask = LandMask.build(gshhg, resolve(course.forbidden_geojson), bbox, cfg["geo"]["mask_resolution"],
                      cfg["geo"]["safety_margin_nm"], course.fine_tiles, cfg["geo"]["fine_resolution"],
                      cfg["geo"].get("zone_margin_nm", 0.0))
out = resolve("data/geo/mask.npz")
mask.save(out)
LandMask.split(out)  # morceaux versionnés dans le dépôt (voir LandMask.load)
print(f"masque: {out} ({out.stat().st_size / 1e6:.1f} Mo) en {time.time() - t:.0f} s")
for tile in mask.tiles:
    print(f"  tuile {tile.lat0:.2f}..{tile.lat1:.2f} / {tile.lon0:.2f}..{tile.lon1:.2f} à {tile.res}° :"
          f" {tile.mask.mean() * 100:.1f} % non navigable")
web = resolve(cfg["service"]["output_dir"])
web.mkdir(parents=True, exist_ok=True)
coast = coastline_geojson(gshhg, bbox, "gshhs_l.b", clip=True, decimals=3)
(web / "coast.geojson").write_text(json.dumps(coast, separators=(",", ":")), encoding="utf-8")
print(f"côtes d'affichage: {len(coast['features'])} polygones, {(web / 'coast.geojson').stat().st_size / 1e6:.1f} Mo")
# Détail pleine résolution (celle du masque) autour du départ et de l'arrivée.
detail = {"type": "FeatureCollection", "features": []}
for ft in course.fine_tiles:
    detail["features"] += coastline_geojson(gshhg, ft, "gshhs_f.b", clip=True, decimals=4)["features"]
(web / "coast-detail.geojson").write_text(json.dumps(detail, separators=(",", ":")), encoding="utf-8")
print(f"côtes détaillées: {len(detail['features'])} polygones, {(web / 'coast-detail.geojson').stat().st_size / 1e6:.2f} Mo")
