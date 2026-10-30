"""Simulateur de suivi de waypoints (scénarios) sur vents synthétiques."""
import numpy as np
import pytest

from routeur.ensemble import Follower, StackedWind
from routeur.geo import haversine_nm
from routeur.wind import WindField

T0 = 1_800_000_000.0


def stacked(*winds):
    """Plusieurs vents uniformes (direction, vitesse) = plusieurs scénarios."""
    ws = [WindField.uniform(d, s, T0) for d, s in winds]
    return StackedWind(ws[0].valid, ws[0].lats, ws[0].lons,
                       np.stack([w.u for w in ws]).astype(np.float16), np.stack([w.v for w in ws]).astype(np.float16))


def test_reach_matches_polar_speed(polar):
    wps = np.array([[45.0, -20.0], [45.0, -22.0]])
    eta = Follower(polar).run(wps, stacked((0, 20)), T0, 48)
    dist = haversine_nm(45, -20, 45, -22)
    assert (eta[0] - T0) / 3600 == pytest.approx(dist / float(polar.best([90], [20])[0][0]), rel=0.03)


def test_upwind_waypoint_is_reached_by_tacking(polar):
    # Waypoint plein vent debout : la route directe est impossible, le simulateur doit louvoyer.
    wps = np.array([[45.0, -20.0], [46.0, -20.0]])
    eta = Follower(polar).run(wps, stacked((0, 16)), T0, 48)
    twa = np.arange(30, 90.1, 0.5)
    vmg = (polar.best(twa, np.full(twa.size, 16.0))[0] * np.cos(np.radians(twa))).max()
    hours = (eta[0] - T0) / 3600
    assert np.isfinite(eta[0])
    assert 60 / vmg * 0.97 <= hours <= 60 / vmg * 1.25


def test_dead_downwind_waypoint_gybes(polar):
    wps = np.array([[45.0, -20.0], [44.0, -20.0]])
    eta = Follower(polar).run(wps, stacked((0, 14)), T0, 48)
    assert np.isfinite(eta[0]) and (eta[0] - T0) / 3600 < 60 / float(polar.best([180], [14])[0][0])


def test_simulate_stops_at_commit_horizon(polar):
    # Suivi limité à 2 h : le bateau s'arrête en route, à la bonne distance, sans arriver.
    wps = np.array([[45.0, -20.0], [45.0, -25.0]])
    eta, lat, lon, tb = Follower(polar).simulate(wps, stacked((0, 20)), T0, 2.0)
    v = float(polar.best([90], [20])[0][0])
    assert not np.isfinite(eta[0])
    assert haversine_nm(45, -20, lat[0], lon[0]) == pytest.approx(v * (tb[0] - T0) / 3600, rel=0.03)
    assert 2 * 3600 <= tb[0] - T0 <= 2 * 3600 + 600


def test_waypoint_remainder_is_not_wasted(polar):
    # Dix waypoints rapprochés sur une ligne droite : même temps qu'un seul leg (le reste du pas est réutilisé).
    lons = np.linspace(-20.0, -22.0, 11)
    dense = np.column_stack([np.full(11, 45.0), lons])
    one = np.array([[45.0, -20.0], [45.0, -22.0]])
    f = Follower(polar)
    w = stacked((0, 20))
    assert f.run(dense, w, T0, 48)[0] == pytest.approx(f.run(one, w, T0, 48)[0], abs=120)


def test_scenarios_are_independent(polar):
    # Même route, trois vents : travers rapide, près, vent faible. Les ETA doivent être ordonnées.
    wps = np.array([[45.0, -20.0], [45.0, -21.5]])
    eta = Follower(polar).run(wps, stacked((0, 20), (270, 16), (0, 6)), T0, 200)
    assert eta[0] < eta[1] and eta[0] < eta[2]
