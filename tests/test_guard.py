"""Garde-fou : les ordres publiés, rejoués comme le programmateur du jeu, ne touchent ni terre ni zone interdite."""
from routeur.roadmap import guard_orders, iso, replay_orders
from routeur.wind import WindField

from .conftest import open_sea

T0 = 1_800_000_000.0
H = 3600.0


def wp(n, lat, lon, t, heading, mode="cap", value=None):
    return {"n": n, "lat": lat, "lon": lon, "t": iso(T0 + t), "heading": heading,
            "order": {"mode": mode, "value": heading if value is None else value}}


def doc(*wps):
    return {"waypoints": list(wps)}


# Vent du nord, 15 kt : TWA +90 (tribord) = cap 270, TWA +60 = cap 300.
WIND = WindField.uniform(0.0, 15.0, T0, hours=100)
# Zone interdite au nord-ouest du départ (45° N, 20° W), la route plein ouest passe dessous.
NW_BLOCK = (45.2, 46.5, -21.5, -20.3)


def test_twa_into_zone_becomes_cap(polar):
    mask = open_sea(blocks=[NW_BLOCK])
    d = doc(wp(0, 45.0, -20.0, 0, 270.0, "twa", 60), wp(1, 45.0, -22.0, 4 * H, 270.0), wp(2, 45.0, -23.0, 6 * H, 270.0))
    g = guard_orders(d, WIND, polar, mask)
    assert g["ok"] and g["twa_to_cap"] == [0]
    assert d["waypoints"][0]["order"] == {"mode": "cap", "value": 270, "guard": "twa"}


def test_cap_into_zone_is_flagged(polar):
    mask = open_sea(blocks=[NW_BLOCK])
    d = doc(wp(0, 45.0, -20.0, 0, 300.0), wp(1, 45.6, -21.6, 4 * H, 270.0), wp(2, 45.6, -23.0, 6 * H, 270.0))
    g = guard_orders(d, WIND, polar, mask)
    assert not g["ok"] and g["hit"]["n"] == 0 and d["waypoints"][0]["order"]["unsafe"]


def test_clear_route_passes(polar):
    mask = open_sea(blocks=[NW_BLOCK])
    d = doc(wp(0, 45.0, -20.0, 0, 270.0, "twa", 90), wp(1, 45.0, -22.0, 3 * H, 270.0), wp(2, 45.0, -23.0, 5 * H, 270.0))
    g = guard_orders(d, WIND, polar, mask)
    assert g["ok"] and g["twa_to_cap"] == [] and d["waypoints"][0]["order"]["mode"] == "twa"


def test_zone_beyond_horizon_is_ignored(polar):
    # cap 300 pendant 30 h : la zone n'est atteinte qu'après l'horizon de contrôle
    mask = open_sea(blocks=[(52.0, 53.0, -40.0, -30.0)])
    d = doc(wp(0, 45.0, -20.0, 0, 300.0), wp(1, 50.0, -40.0, 30 * H, 300.0))
    assert replay_orders(d["waypoints"], WIND, polar, mask, horizon_h=2)["hit"] is None
