"""Polaire Virtual Regatta (format JSON VR) : vitesse, foils, coque, choix de voile, pénalités.

Le moteur ne connaît que la classe `Polar` : changer de bateau = changer de fichier JSON.

Hypothèses (documentées dans docs/HYPOTHESES.md) :
- vitesse = interpolation bilinéaire du tableau (TWA, TWS) de chaque voile ;
- foils : facteur speedRatio plein dans [twaMin, twaMax] × [twsMin, twsMax], rampe linéaire sur
  twaMerge / twsMerge (méthode des outils communautaires VR Dashboard / ITYC) ;
- durée de pénalité interpolée linéairement entre lws et hws (VR ne publie pas la courbe) ;
- énergie : modèle ITYC (non officiel).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

SAIL_OPTION = {3: "heavy_sails", 6: "heavy_sails", 4: "light_sails", 7: "light_sails", 5: "reach_sail"}



@dataclass
class Polar:
    label: str
    twa: np.ndarray            # (A,) degrés
    tws: np.ndarray            # (W,) nœuds
    speed: np.ndarray          # (S, A, W) nœuds
    sail_ids: list[int]
    sail_names: list[str]
    foil: dict
    hull_ratio: float
    global_ratio: float
    auto_tolerance: float
    winch: dict
    options: dict
    stamina: dict | None = None
    stamina_boat_factor: float = 1.0
    source: str = ""
    allowed: np.ndarray = field(init=False)

    def __post_init__(self):
        self.allowed = np.array([self.options.get(SAIL_OPTION[i], True) if i in SAIL_OPTION else True
                                 for i in self.sail_ids])

    @classmethod
    def load(cls, path: str | Path, options: dict, stamina_path: str | Path | None = None,
             stamina_boat_factor: float = 1.0) -> "Polar":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(d, list):
            d = d[0]
        twa = np.array(d["twa"], float)
        tws = np.array(d["tws"], float)
        speed = np.array([s["speed"] for s in d["sail"]], float)
        if speed.shape[1:] != (twa.size, tws.size):
            raise ValueError(f"polaire {path}: tableau {speed.shape[1:]} ≠ (twa {twa.size}, tws {tws.size})")
        if np.any(np.diff(twa) <= 0) or np.any(np.diff(tws) <= 0):
            raise ValueError(f"polaire {path}: axes TWA/TWS non croissants")
        stamina = json.loads(Path(stamina_path).read_text(encoding="utf-8")) if stamina_path else None
        return cls(label=d.get("label", Path(path).stem), twa=twa, tws=tws, speed=speed,
                   sail_ids=[s["id"] for s in d["sail"]], sail_names=[s["name"] for s in d["sail"]],
                   foil=d.get("foil") or {}, hull_ratio=float((d.get("hull") or {}).get("speedRatio", 1.0)),
                   global_ratio=float(d.get("globalSpeedRatio", 1.0)),
                   auto_tolerance=float(d.get("autoSailChangeTolerance", 1.0)),
                   winch=d["winch"], options=options, stamina=stamina,
                   stamina_boat_factor=stamina_boat_factor, source=str(path))

    # --- vitesse ---------------------------------------------------------------------------------

    def sail_speeds(self, twa, tws) -> np.ndarray:
        """Vitesse de chaque voile (S, N) pour des TWA (0-180, valeur absolue) et TWS (nœuds), sans bonus."""
        twa = np.abs(np.asarray(twa, float))
        tws = np.asarray(tws, float)
        fa = np.interp(twa, self.twa, np.arange(self.twa.size))
        fw = np.interp(tws, self.tws, np.arange(self.tws.size))
        a0 = np.minimum(fa.astype(int), self.twa.size - 2)
        w0 = np.minimum(fw.astype(int), self.tws.size - 2)
        ta, tw = fa - a0, fw - w0
        s = self.speed
        return ((1 - ta) * (1 - tw) * s[:, a0, w0] + (1 - ta) * tw * s[:, a0, w0 + 1]
                + ta * (1 - tw) * s[:, a0 + 1, w0] + ta * tw * s[:, a0 + 1, w0 + 1])

    def foil_factor(self, twa, tws) -> np.ndarray:
        twa = np.abs(np.asarray(twa, float))
        tws = np.asarray(tws, float)
        f = self.foil
        if not f or not self.options.get("foils", False):
            return np.ones(np.broadcast(twa, tws).shape)

        def ramp(x, lo, hi, merge):
            return np.clip(np.minimum((x - (lo - merge)) / merge, ((hi + merge) - x) / merge), 0.0, 1.0)

        k = ramp(twa, f["twaMin"], f["twaMax"], f["twaMerge"]) * ramp(tws, f["twsMin"], f["twsMax"], f["twsMerge"])
        return 1.0 + (f["speedRatio"] - 1.0) * k

    def bonus(self, twa, tws) -> np.ndarray:
        hull = self.hull_ratio if self.options.get("hull", False) else 1.0
        return self.global_ratio * hull * self.foil_factor(twa, tws)

    def best(self, twa, tws):
        """Meilleure voile autorisée : (vitesse avec bonus, index de voile, vitesses de toutes les voiles)."""
        sp = self.sail_speeds(twa, tws)
        sp_allowed = np.where(self.allowed[:, None], sp, -1.0)
        idx = np.argmax(sp_allowed, axis=0)
        b = self.bonus(twa, tws)
        return sp_allowed[idx, np.arange(idx.size)] * b, idx, sp * b

    def speed_with_sail(self, twa, tws, sail_idx) -> np.ndarray:
        sp = self.sail_speeds(twa, tws)
        sail_idx = np.asarray(sail_idx)
        return sp[sail_idx, np.arange(sail_idx.size)] * self.bonus(twa, tws)

    # --- pénalités et énergie ------------------------------------------------------------------

    def penalty(self, kind: str, tws) -> tuple[np.ndarray, float]:
        """(durée en s, ratio de vitesse) d'une manœuvre : kind = tack | gybe | sailChange."""
        w = self.winch
        spec = w[kind]["pro" if self.options.get("winch_pro", False) else "std"]
        frac = np.clip((np.asarray(tws, float) - w["lws"]) / (w["hws"] - w["lws"]), 0.0, 1.0)
        timer = spec["lw"]["timer"] + (spec["hw"]["timer"] - spec["lw"]["timer"]) * frac
        return timer, float(spec["lw"]["ratio"])

    def stamina_multiplier(self, energy) -> np.ndarray:
        if not self.stamina:
            return np.ones_like(np.asarray(energy, float))
        imp = self.stamina["impact"]
        return np.interp(energy, sorted(float(k) for k in imp), [imp[k] for k in sorted(imp, key=float)])

    def stamina_cost(self, kind: str, tws) -> np.ndarray:
        if not self.stamina:
            return np.zeros_like(np.asarray(tws, float))
        c = self.stamina["consumption"]
        pts = c["points"]["sail" if kind == "sailChange" else kind]
        winds = c["winds"]
        wf = np.interp(tws, sorted(float(k) for k in winds), [winds[k] for k in sorted(winds, key=float)])
        return pts * wf * self.stamina_boat_factor

    def stamina_recovery(self, tws, dt_s) -> np.ndarray:
        """Points regagnés en dt_s secondes (1 point toutes les loTime..hiTime minutes selon le vent)."""
        if not self.stamina:
            return np.zeros_like(np.asarray(tws, float))
        r = self.stamina["recovery"]
        x = np.clip((np.asarray(tws, float) - r["loWind"]) / (r["hiWind"] - r["loWind"]), 0, 1)
        # Courbe en cosinus entre loTime et hiTime (implémentation ITYC, SUPPOSÉ).
        minutes = r["loTime"] + (r["hiTime"] - r["loTime"]) * (1 - np.cos(np.pi * x)) / 2
        return r["points"] * dt_s / (minutes * 60.0)
