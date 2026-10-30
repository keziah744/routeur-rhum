"""Décodage GRIB2 (vent U/V à 10 m) avec ecCodes.

Un fichier téléchargé contient deux messages (10u et 10v) pour une échéance.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import eccodes
import numpy as np


class GribError(ValueError):
    pass


@dataclass
class WindMessage:
    run: datetime          # date de génération (analyse) du cycle, UTC
    forecast_hour: int
    lats: np.ndarray       # croissantes (sud -> nord)
    lons: np.ndarray       # croissantes, en -180..180
    u: np.ndarray          # m/s, forme (nlat, nlon)
    v: np.ndarray


def _grid(h) -> tuple[np.ndarray, np.ndarray, int, int]:
    ni = eccodes.codes_get(h, "Ni")
    nj = eccodes.codes_get(h, "Nj")
    la1 = eccodes.codes_get(h, "latitudeOfFirstGridPointInDegrees")
    lo1 = eccodes.codes_get(h, "longitudeOfFirstGridPointInDegrees")
    di = eccodes.codes_get(h, "iDirectionIncrementInDegrees")
    dj = eccodes.codes_get(h, "jDirectionIncrementInDegrees")
    south_to_north = eccodes.codes_get(h, "jScansPositively") == 1
    lats = la1 + np.arange(nj) * (dj if south_to_north else -dj)
    lons = lo1 + np.arange(ni) * di
    lons = ((lons + 180.0) % 360.0) - 180.0
    return lats, lons, ni, nj


def decode_wind_file(path: str | Path) -> WindMessage:
    """Lit un fichier GRIB2 contenant 10u et 10v et renvoie une grille régulière."""
    fields: dict[str, np.ndarray] = {}
    meta = None
    with open(path, "rb") as fh:
        while True:
            h = eccodes.codes_grib_new_from_file(fh)
            if h is None:
                break
            try:
                name = eccodes.codes_get(h, "shortName")
                if name not in ("10u", "10v"):
                    continue
                lats, lons, ni, nj = _grid(h)
                vals = eccodes.codes_get_values(h).reshape(nj, ni)
                step = eccodes.codes_get(h, "forecastTime")
                if eccodes.codes_get(h, "stepUnits") != 1:
                    raise GribError(f"unité d'échéance inattendue dans {path}")
                d = str(eccodes.codes_get(h, "dataDate"))
                t = int(eccodes.codes_get(h, "dataTime"))
                run = datetime(int(d[:4]), int(d[4:6]), int(d[6:8]), t // 100, tzinfo=timezone.utc)
                cur = (run, step, lats.tobytes(), lons.tobytes())
                if meta is None:
                    meta = (run, step, lats, lons)
                elif cur[:2] != meta[:2] or not (np.array_equal(lats, meta[2]) and np.array_equal(lons, meta[3])):
                    raise GribError(f"messages U/V incohérents dans {path}")
                fields[name] = vals
            finally:
                eccodes.codes_release(h)
    if meta is None or set(fields) != {"10u", "10v"}:
        raise GribError(f"{path}: 10u/10v manquants (trouvé {sorted(fields)})")
    run, step, lats, lons = meta
    u, v = fields["10u"], fields["10v"]
    if lats[0] > lats[-1]:
        lats, u, v = lats[::-1], u[::-1], v[::-1]
    # La zone peut traverser le méridien 0 : on remet les longitudes dans l'ordre croissant.
    order = np.argsort(lons, kind="stable")
    lons, u, v = lons[order], u[:, order], v[:, order]
    for name, arr in (("10u", u), ("10v", v)):
        if not np.all(np.isfinite(arr)):
            raise GribError(f"{path}: valeurs non finies dans {name}")
        if np.abs(arr).max() > 100:
            raise GribError(f"{path}: vent > 100 m/s dans {name}, fichier suspect")
    return WindMessage(run=run, forecast_hour=int(step), lats=lats, lons=lons,
                       u=u.astype(np.float32), v=v.astype(np.float32))
