"""Tests du moteur d'isochrones sur des vents synthétiques simples, avec résultat attendu calculable."""
import numpy as np
import pytest

from routeur.geo import haversine_nm
from routeur.isochrones import MANEUVER_GYBE, MANEUVER_TACK, Router, RoutingParams
from routeur.wind import WindField

from .conftest import open_sea, simple_course

T0 = 1_800_000_000.0
PARAMS = RoutingParams(time_steps=[[1000, 0.5]], twa_step_deg=2, sector_deg=1.0, max_duration_h=60)


def run(polar, wind, course, mask=None, params=PARAMS):
    return Router(wind, polar, mask or open_sea(), course, params).run()


def test_beam_reach_goes_straight_at_polar_speed(polar):
    # Vent du nord 20 kt, arrivée courte 120 milles plein ouest : route directe à TWA 90.
    course = simple_course((45.0, -20.0), (44.97, -22.828), (45.03, -22.828))
    res = run(polar, WindField.uniform(0, 20, T0), course)
    assert res.arrived
    expected_speed = float(polar.best([90], [20])[0][0])
    dist = haversine_nm(45.0, -20.0, 45.0, -22.828)
    hours = (res.eta - T0) / 3600
    assert hours == pytest.approx(dist / expected_speed, rel=0.03)
    lats = np.array([p.lat for p in res.points])
    assert np.abs(lats - 45.0).max() < 0.15  # pas de zigzag


def test_upwind_tacks_and_matches_vmg(polar):
    # Vent du nord 16 kt, arrivée 60 milles au nord : il faut tirer des bords.
    course = simple_course((45.0, -20.0), (46.0, -20.5), (46.0, -19.5), cross="north")
    res = run(polar, WindField.uniform(0, 16, T0), course)
    assert res.arrived
    twa = np.arange(30, 90.1, 0.5)
    vmg = (polar.best(twa, np.full(twa.size, 16.0))[0] * np.cos(np.radians(twa))).max()
    hours = (res.eta - T0) / 3600
    assert hours >= 60 / vmg * 0.98                    # impossible de faire mieux que la VMG
    assert hours <= 60 / vmg * 1.10                    # mais pas loin, pénalités comprises
    assert any(p.maneuver & MANEUVER_TACK for p in res.points)
    assert all(abs(p.twa) < 90 for p in res.points[:-1])


def test_downwind_gybes_and_beats_dead_run(polar):
    # Vent du nord 14 kt, arrivée 80 milles au sud : le vent arrière pur est lent, on empanne.
    course = simple_course((45.0, -20.0), (43.667, -21.0), (43.667, -19.0), cross="south")
    res = run(polar, WindField.uniform(0, 14, T0), course)
    assert res.arrived
    dead_run = float(polar.best([180], [14])[0][0])
    hours = (res.eta - T0) / 3600
    assert hours < 80 / dead_run
    assert any(p.maneuver & MANEUVER_GYBE for p in res.points)


def test_route_avoids_island(polar):
    # Une île bloque la route directe : la route la contourne et reste hors de la terre.
    island = (44.7, 45.3, -21.6, -21.2)
    mask = open_sea(blocks=[island])
    course = simple_course((45.0, -20.0), (44.0, -22.828), (46.0, -22.828))
    res = run(polar, WindField.uniform(0, 20, T0), course, mask=mask)
    assert res.arrived
    lat = np.array([p.lat for p in res.points])
    lon = np.array([p.lon for p in res.points])
    inside = (lat > island[0]) & (lat < island[1]) & (lon > island[2]) & (lon < island[3])
    assert not inside.any()
    for a, b in zip(res.points, res.points[1:]):
        assert mask.segments_clear(a.lat, a.lon, b.lat, b.lon)
    free = run(polar, WindField.uniform(0, 20, T0), course)
    assert res.eta > free.eta


def test_penalties_cost_time(polar):
    from routeur.polar import Polar
    no_pen = Polar(polar.label, polar.twa, polar.tws, polar.speed, polar.sail_ids, polar.sail_names, polar.foil,
                   polar.hull_ratio, polar.global_ratio, polar.auto_tolerance,
                   {k: ({"std": {"lw": {"ratio": 1, "timer": 0}, "hw": {"ratio": 1, "timer": 0}},
                         "pro": {"lw": {"ratio": 1, "timer": 0}, "hw": {"ratio": 1, "timer": 0}}}
                        if isinstance(v, dict) else v) for k, v in polar.winch.items()},
                   polar.options)
    course = simple_course((45.0, -20.0), (46.0, -20.5), (46.0, -19.5), cross="north")
    wind = WindField.uniform(0, 16, T0)
    with_pen = run(polar, wind, course)
    without = run(no_pen, wind, course)
    assert with_pen.eta > without.eta


def test_wind_shift_is_exploited(polar):
    # Le vent tourne de 30° en 6 h : la route doit différer de celle d'un vent fixe.
    lats, lons = np.array([30.0, 60.0]), np.array([-60.0, 0.0])
    valid = np.array([T0, T0 + 6 * 3600, T0 + 100 * 3600])
    def comp(twd, tws=16):
        ms = tws * 0.514444
        return -ms * np.sin(np.radians(twd)), -ms * np.cos(np.radians(twd))
    u = np.zeros((3, 2, 2), np.float32)
    v = np.zeros_like(u)
    for k, twd in enumerate([0, 30, 30]):
        u[k], v[k] = comp(twd)
    shifting = WindField(valid, lats, lons, u, v)
    course = simple_course((45.0, -20.0), (46.0, -20.5), (46.0, -19.5), cross="north")
    res_shift = run(polar, shifting, course)
    res_fixed = run(polar, WindField.uniform(0, 16, T0), course)
    assert res_shift.arrived and res_fixed.arrived
    assert res_shift.eta != pytest.approx(res_fixed.eta, abs=60)
