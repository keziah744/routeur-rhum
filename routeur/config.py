"""Chargement de la configuration centrale (config.toml)."""
from __future__ import annotations

import logging
import logging.handlers
import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | Path | None = None) -> dict:
    path = Path(path) if path else ROOT / "config.toml"
    with open(path, "rb") as fh:
        cfg = tomllib.load(fh)
    # Dans le cloud (GitHub Actions), le miroir AWS est plus fiable que NOMADS pour les gros volumes.
    if os.environ.get("ROUTEUR_PREFER_S3") == "1":
        cfg["gfs"]["prefer_s3"] = True
        cfg.setdefault("ensemble", {})["prefer_s3"] = True
    return cfg


def resolve(rel: str | Path) -> Path:
    """Chemin absolu à partir d'un chemin relatif au projet."""
    p = Path(rel)
    return p if p.is_absolute() else ROOT / p


def setup_logging(cfg: dict, verbose: bool = False) -> None:
    log_file = resolve(cfg["service"]["log_file"])
    log_file.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%dT%H:%M:%S%z")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        fh = logging.handlers.RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)
