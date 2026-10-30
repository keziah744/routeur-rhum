"""Tests unitaires : polaire, vent, géodésie, portes."""
import numpy as np
import pytest

from routeur.course import Gate
from routeur.geo import EARTH_NM, haversine_nm, rhumb_bearing_distance, rhumb_destination
from routeur.wind import WindField


def test_polar_nodes_match_table(polar):
    # Aux nœuds du tableau, l'interpolation rend la valeur brute de la polaire VR.
    a, w = list(polar.twa).index(45), list(polar.tws).index(16)
    jib = polar.sail_names.index("Jib")
    assert polar.sail_speeds([45], [16])[jib, 0] == pytest.approx(polar.speed[jib, a, w])


def test_polar_interpolates_between_nodes(polar):
    s = polar.sail_speeds([90, 100, 95], [20, 20, 20])
    assert s[:, 2] == pytest.approx((s[:, 0] + s[:, 1]) / 2)


def test_foil_factor_ramps(polar):
    f = polar.foil
    assert polar.foil_factor([120], [25])[0] == pytest.approx(f["speedRatio"])
    assert polar.foil_factor([40], [25])[0] == pytest.approx(1.0)            # hors plage TWA
    assert polar.foil_factor([120], [5])[0] == pytest.approx(1.0)            # hors plage TWS
    mid = polar.foil_factor([f["twaMin"] - f["twaMerge"] / 2], [25])[0]      # milieu de rampe
    assert mid == pytest.approx(1 + (f["speedRatio"] - 1) / 2)


def test_best_sail_is_max_of_allowed(polar):
    speed, idx, allsp = polar.best([60, 150], [12, 25])
    assert np.allclose(speed, allsp.max(axis=0))


def test_sail_options_restrict_choice(polar):
    from routeur.polar import Polar
    basic = Polar(polar.label, polar.twa, polar.tws, polar.speed, polar.sail_ids, polar.sail_names, polar.foil,
                  polar.hull_ratio, polar.global_ratio, polar.auto_tolerance, polar.winch,
                  dict(light_sails=False, heavy_sails=False, reach_sail=False))
    _, idx, _ = basic.best(np.arange(30, 181, 5), np.full(31, 14.0))
    assert set(np.array(basic.sail_names)[idx]) <= {"Jib", "Spi"}


def test_penalty_interpolation(polar):
    t_lo, r = polar.penalty("tack", [5])
    t_hi, _ = polar.penalty("tack", [40])
    t_mid, _ = polar.penalty("tack", [20])
    assert t_lo[0] == 180 and t_hi[0] == 300 and t_mid[0] == pytest.approx(240)
    assert r == pytest.approx(0.7)  # winch pro


def test_stamina_multiplier(polar):
    assert polar.stamina_multiplier([100, 0, 50]) == pytest.approx([0.5, 2.0, 1.25])


def test_uniform_wind_direction():
    w = WindField.uniform(twd_deg=270, tws_kt=15, t0=0)
    twd, tws = w.wind(np.array([45.0]), np.array([-20.0]), 100.0)
    assert twd[0] == pytest.approx(270) and tws[0] == pytest.approx(15)


def test_wind_bilinear_and_time_interp():
    lats, lons = np.array([0.0, 1.0]), np.array([0.0, 1.0])
    u = np.zeros((2, 2, 2), np.float32)
    u[0] = [[0, 2], [0, 2]]      # U croît vers l'est au premier instant
    u[1] = u[0] + 4              # +4 m/s au second instant
    w = WindField(np.array([0.0, 3600.0]), lats, lons, u, np.zeros_like(u))
    uu, _ = w.uv(np.array([0.5]), np.array([0.25]), 1800.0)
    assert uu[0] == pytest.approx(0.5 + 2.0)


def test_rhumb_destination_and_distance():
    one_deg = EARTH_NM * np.pi / 180  # ≈ 60,04 milles sur la sphère utilisée
    lat, lon = rhumb_destination(45.0, -10.0, 0.0, one_deg)
    assert lat == pytest.approx(46.0, abs=1e-6) and lon == pytest.approx(-10.0)
    lat, lon = rhumb_destination(0.0, 0.0, 90.0, one_deg)
    assert lon == pytest.approx(1.0, abs=1e-6)
    brg, d = rhumb_bearing_distance(45.0, -10.0, 45.0, -11.0)
    assert brg == pytest.approx(270) and d == pytest.approx(one_deg * np.cos(np.radians(45)), rel=1e-6)
    assert haversine_nm(0, 0, 1, 0) == pytest.approx(one_deg)
    # Aller-retour : destination puis cap/distance redonnent les mêmes valeurs.
    lat, lon = rhumb_destination(48.7, -2.0, 237.0, 1500.0)
    brg, d = rhumb_bearing_distance(48.7, -2.0, lat, lon)
    assert brg == pytest.approx(237.0) and d == pytest.approx(1500.0)


def test_gate_direction():
    g = Gate("porte", (48.0, -2.0), (49.0, -2.0), "west")
    assert not np.isnan(g.crossing(48.5, -1.9, 48.5, -2.1))     # vers l'ouest : franchie
    assert np.isnan(g.crossing(48.5, -2.1, 48.5, -1.9))         # vers l'est : refusée
    assert np.isnan(g.crossing(47.5, -1.9, 47.5, -2.1))         # à côté de la porte
    assert g.crossing(48.5, -1.9, 48.5, -2.1) == pytest.approx(0.5)


def test_parse_coord_game_formats():
    from routeur.__main__ import parse_coord
    assert parse_coord("46°12,5 N", True) == pytest.approx(46 + 12.5 / 60)
    assert parse_coord("23°40,1 W", False) == pytest.approx(-(23 + 40.1 / 60))
    assert parse_coord("46°12'30\" N", True) == pytest.approx(46 + 12 / 60 + 30 / 3600)
    assert parse_coord("-23.668", False) == pytest.approx(-23.668)
    with pytest.raises(ValueError):
        parse_coord("abc", True)
    with pytest.raises(ValueError):
        parse_coord("95 N", True)


def test_prefer_s3_from_environment(monkeypatch):
    from routeur.config import load_config
    monkeypatch.setenv("ROUTEUR_PREFER_S3", "1")
    cfg = load_config()
    assert cfg["gfs"]["prefer_s3"] and cfg["ensemble"]["prefer_s3"]
