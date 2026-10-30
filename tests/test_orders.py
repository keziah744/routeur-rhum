"""Ordre conseillé pour le programmateur du jeu : cap fixe ou TWA fixe sur chaque segment."""
from types import SimpleNamespace

from routeur.roadmap import order_advice


def pts(twas, heads):
    return [SimpleNamespace(t=float(k), twa=a, heading=h) for k, (a, h) in enumerate(zip(twas, heads))]


def test_wind_shift_gives_twa_order():
    # le vent tourne de 30° : la route garde ~-125° de TWA, le cap tourne avec
    o = order_advice(pts([-124, -125, -126, -125], [240, 250, 260, 270]), 0, 4, 255)
    assert o["mode"] == "twa" and o["value"] == -125 and o["spread_cap"] == 30


def test_steady_heading_gives_cap_order():
    o = order_advice(pts([-110, -120, -130, -140], [245, 245, 246, 245]), 0, 4, 245.4)
    assert o == {"mode": "cap", "value": 245, "spread_cap": 1, "spread_twa": 30}


def test_close_call_keeps_cap():
    o = order_advice(pts([135, 136, 138], [240, 242, 244]), 0, 3, 242)
    assert o["mode"] == "cap"


def test_tack_inside_segment_forces_cap():
    o = order_advice(pts([-45, -44, 44, 45], [10, 12, 100, 101]), 0, 4, 55)
    assert o["mode"] == "cap"


def test_heading_wraps_around_north():
    o = order_advice(pts([100, 130, 160], [355, 0, 5]), 0, 3, 0)
    assert o["mode"] == "cap" and o["spread_cap"] == 10
