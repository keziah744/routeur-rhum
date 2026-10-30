"""Champ de vent interpolé dans l'espace (bilinéaire) et le temps (linéaire)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

MS_TO_KT = 1.0 / 0.514444


@dataclass
class WindField:
    valid: np.ndarray   # (T,) secondes epoch UTC, croissantes
    lats: np.ndarray    # (J,) croissantes
    lons: np.ndarray    # (I,) croissantes
    u: np.ndarray       # (T, J, I) m/s
    v: np.ndarray
    run: float = 0.0    # epoch du cycle (0 pour un vent synthétique)
    label: str = ""

    @classmethod
    def load(cls, path: str | Path, label: str = "") -> "WindField":
        d = np.load(path)
        return cls(d["valid"], d["lats"], d["lons"], d["u"], d["v"], float(d["run"]), label)

    @classmethod
    def uniform(cls, twd_deg: float, tws_kt: float, t0: float, hours: float = 1000,
                lat=(0.0, 70.0), lon=(-100.0, 20.0)) -> "WindField":
        """Vent constant (direction d'où il vient, vitesse en nœuds), pour les tests."""
        ms = tws_kt / MS_TO_KT
        u = -ms * np.sin(np.radians(twd_deg))
        v = -ms * np.cos(np.radians(twd_deg))
        lats = np.array(lat, float)
        lons = np.array(lon, float)
        valid = np.array([t0, t0 + hours * 3600])
        shape = (2, 2, 2)
        return cls(valid, lats, lons, np.full(shape, u, np.float32), np.full(shape, v, np.float32), 0.0, "synthétique")

    @property
    def start(self) -> float:
        return float(self.valid[0])

    @property
    def end(self) -> float:
        return float(self.valid[-1])

    def uv(self, lat, lon, t):
        """Composantes U, V (m/s) aux positions données (tableaux) à l'instant t (scalaire ou tableau).

        Hors de la grille, la valeur du bord est utilisée ; après la dernière échéance, la dernière
        prévision est maintenue (le routeur le signale via `beyond_forecast`).
        """
        lat = np.asarray(lat, float)
        lon = np.asarray(lon, float)
        t = np.broadcast_to(np.asarray(t, float), lat.shape)
        fj = np.clip(np.interp(lat, self.lats, np.arange(self.lats.size)), 0, self.lats.size - 1)
        fi = np.clip(np.interp(lon, self.lons, np.arange(self.lons.size)), 0, self.lons.size - 1)
        ft = np.clip(np.interp(t, self.valid, np.arange(self.valid.size)), 0, self.valid.size - 1)
        j0 = np.minimum(fj.astype(int), self.lats.size - 2) if self.lats.size > 1 else np.zeros_like(fj, int)
        i0 = np.minimum(fi.astype(int), self.lons.size - 2) if self.lons.size > 1 else np.zeros_like(fi, int)
        k0 = np.minimum(ft.astype(int), self.valid.size - 2) if self.valid.size > 1 else np.zeros_like(ft, int)
        wj, wi, wk = fj - j0, fi - i0, ft - k0
        out = []
        for f in (self.u, self.v):
            acc = 0.0
            for dk, wk_ in ((0, 1 - wk), (1, wk)):
                for dj, wj_ in ((0, 1 - wj), (1, wj)):
                    for di, wi_ in ((0, 1 - wi), (1, wi)):
                        acc = acc + wk_ * wj_ * wi_ * f[k0 + dk, j0 + dj, i0 + di]
            out.append(acc)
        return out[0], out[1]

    def wind(self, lat, lon, t):
        """Direction d'où vient le vent (degrés vrais) et vitesse (nœuds)."""
        u, v = self.uv(lat, lon, t)
        tws = np.hypot(u, v) * MS_TO_KT
        twd = (np.degrees(np.arctan2(-u, -v)) + 360.0) % 360.0
        return twd, tws

    def beyond_forecast(self, t: float) -> bool:
        return bool(t > self.end)
