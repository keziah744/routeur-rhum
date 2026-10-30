import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from routeur.course import Course, Gate  # noqa: E402
from routeur.geo import LandMask, Tile  # noqa: E402
from routeur.polar import Polar  # noqa: E402

FULL_PACK = dict(foils=True, hull=True, winch_pro=True, auto_sail=True,
                 light_sails=True, heavy_sails=True, reach_sail=True)


@pytest.fixture(scope="session")
def polar():
    return Polar.load(ROOT / "data/polar/ultim-bp-xi.json", FULL_PACK, ROOT / "data/polar/stamina-ityc.json", 1.5)


def open_sea(lat=(30.0, 60.0), lon=(-60.0, 0.0), res=0.05, blocks=()):
    """Masque sans terre, avec des rectangles bloqués optionnels (lat0, lat1, lon0, lon1)."""
    h, w = int((lat[1] - lat[0]) / res), int((lon[1] - lon[0]) / res)
    m = np.zeros((h, w), bool)
    for la0, la1, lo0, lo1 in blocks:
        m[int((la0 - lat[0]) / res):int((la1 - lat[0]) / res), int((lo0 - lon[0]) / res):int((lo1 - lon[0]) / res)] = True
    return LandMask([Tile(lat[0], lon[0], res, m)])


def simple_course(start, finish_a, finish_b, cross="any", t0=1_800_000_000.0, gates=()):
    return Course("test", start[0], start[1], t0, [*gates, Gate("arrivée", finish_a, finish_b, cross)], None, [], {})
