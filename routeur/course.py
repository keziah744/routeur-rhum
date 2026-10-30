"""Parcours : départ, portes à franchir dans l'ordre et dans un sens imposé, ligne d'arrivée."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

# Sens de franchissement -> composante du déplacement qui doit être positive.
_DIRS = {"north": (1, 0), "south": (-1, 0), "east": (0, 1), "west": (0, -1)}


@dataclass
class Gate:
    name: str
    a: tuple[float, float]  # (lat, lon)
    b: tuple[float, float]
    cross: str              # north | south | east | west | any

    @property
    def mid(self) -> tuple[float, float]:
        return ((self.a[0] + self.b[0]) / 2, (self.a[1] + self.b[1]) / 2)

    def crossing(self, lat1, lon1, lat2, lon2):
        """Fraction (0..1) du segment où la porte est franchie dans le bon sens, NaN sinon."""
        lat1, lon1, lat2, lon2 = (np.asarray(x, float) for x in (lat1, lon1, lat2, lon2))
        k = np.cos(np.radians(self.mid[0]))  # plan local : longitudes ramenées en milles
        px, py = lon1 * k, lat1
        rx, ry = (lon2 - lon1) * k, lat2 - lat1
        qx, qy = self.a[1] * k, self.a[0]
        sx, sy = (self.b[1] - self.a[1]) * k, self.b[0] - self.a[0]
        den = rx * sy - ry * sx
        with np.errstate(divide="ignore", invalid="ignore"):
            t = ((qx - px) * sy - (qy - py) * sx) / den
            u = ((qx - px) * ry - (qy - py) * rx) / den
        ok = (np.abs(den) > 1e-15) & (t >= 0) & (t <= 1) & (u >= 0) & (u <= 1)
        if self.cross != "any":
            dy, dx = _DIRS[self.cross]
            ok &= (ry * dy + rx * dx / k) > 0
        return np.where(ok, t, np.nan)


@dataclass
class Course:
    name: str
    start_lat: float
    start_lon: float
    start_time: float  # epoch UTC
    gates: list[Gate]  # portes intermédiaires puis arrivée (dernière)
    forbidden_geojson: str | None
    fine_tiles: list[dict]
    raw: dict

    @classmethod
    def load(cls, path: str | Path) -> "Course":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        gates = [Gate(g["name"], tuple(g["a"]), tuple(g["b"]), g.get("cross", "any")) for g in d.get("gates", [])]
        f = d["finish"]
        gates.append(Gate(f.get("name", "Arrivée"), tuple(f["a"]), tuple(f["b"]), f.get("cross", "any")))
        t = datetime.fromisoformat(d["start"]["time_utc"].replace("Z", "+00:00")).timestamp()
        return cls(d["name"], d["start"]["lat"], d["start"]["lon"], t, gates,
                   d.get("forbidden_geojson"), d.get("fine_tiles", []), d)

    @property
    def finish(self) -> Gate:
        return self.gates[-1]

    def leg_origin(self, gate_idx: int) -> tuple[float, float]:
        """Point d'où l'on mesure la progression vers la porte gate_idx."""
        return (self.start_lat, self.start_lon) if gate_idx == 0 else self.gates[gate_idx - 1].mid
