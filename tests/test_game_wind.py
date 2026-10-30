"""Météo du jeu : l'ancien GFS jusqu'à l'heure où le jeu charge le nouveau."""
import numpy as np
import pytest

from routeur.wind import SwitchedWind, WindField

T0 = 1_800_000_000.0


@pytest.fixture
def sw():
    old = WindField.uniform(90, 10, T0 - 6 * 3600)   # vent d'est, 10 kt
    new = WindField.uniform(270, 20, T0 - 6 * 3600)  # vent d'ouest, 20 kt
    new.run = T0
    return SwitchedWind(old, new, T0 + 3600)


def test_before_and_after_switch(sw):
    twd, tws = sw.wind(np.array([46.0]), np.array([-20.0]), T0)
    assert twd[0] == pytest.approx(90) and tws[0] == pytest.approx(10)
    twd, tws = sw.wind(np.array([46.0]), np.array([-20.0]), T0 + 2 * 3600)
    assert twd[0] == pytest.approx(270) and tws[0] == pytest.approx(20)


def test_mixed_times(sw):
    _, tws = sw.wind(np.array([46.0, 46.0]), np.array([-20.0, -20.0]), np.array([T0, T0 + 7200]))
    assert tws == pytest.approx([10, 20])


def test_metadata_from_new_cycle(sw):
    assert sw.run == T0 and sw.end == sw.after.end and not sw.beyond_forecast(T0)
