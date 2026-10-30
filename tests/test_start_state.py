"""Point de départ du calcul pendant la course : position du jeu, ou estimation le long de la route suivie."""
from types import SimpleNamespace

import pytest

from routeur import service as S
from routeur.roadmap import iso

T0 = 1_800_000_000.0  # coup de canon
H = 3600.0


def route(start_t, lat0=46.0, lon0=-20.0, hours=10, sail=2, start_lat=None):
    """Route en ligne droite vers l'ouest, un point par heure (1° de longitude par heure)."""
    track = [[lat0, lon0 - k, iso(start_t + k * H), sail, 15.0, -120.0, 20.0] for k in range(hours + 1)]
    return {"start_time": iso(start_t), "start": {"lat": start_lat or lat0, "lon": lon0}, "track": track,
            "gates_passed_track": [1] * (hours + 1), "start_gate": 1}


@pytest.fixture
def svc(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "resolve", lambda rel: tmp_path / rel)
    s = S.Service.__new__(S.Service)
    s.boat, s.bout = "papa", tmp_path / "web/data/bateaux/papa"
    s.bout.mkdir(parents=True)
    s.course = SimpleNamespace(start_time=T0, start_lat=48.7, start_lon=-1.9)
    return s


def put_pos(t, lat=45.0, lon=-30.0):
    S.write_json(S.position_file("papa"), {"time": t, "lat": lat, "lon": lon, "gate": 1})


def test_before_start_uses_line(svc):
    put_pos(T0 - H)
    assert svc.start_state(now=T0 - 60)["source"] == "ligne de départ"


def test_fresh_position_used_as_is(svc):
    S.write_json(svc.bout / "route.json", route(T0 + 5 * H))
    put_pos(T0 + 9 * H)
    st = svc.start_state(now=T0 + 9 * H + 600)
    assert (st["lat"], st["lon"], st["time"]) == (45.0, -30.0, T0 + 9 * H)
    assert "il y a 10 min" in st["source"]


def test_old_position_keeps_its_real_time(svc):
    """Une position de 2 h n'est plus rajeunie à « il y a 30 min » : le bateau a avancé depuis."""
    S.write_json(svc.bout / "route.json", route(T0 + 5 * H))
    put_pos(T0 + 7 * H)
    st = svc.start_state(now=T0 + 9 * H)
    assert st["time"] == T0 + 7 * H and "position saisie (il y a 2.0 h)" == st["source"]


def test_position_already_used_is_advanced_along_route(svc):
    S.write_json(svc.bout / "route.json", route(T0 + 5 * H, lat0=45.0, lon0=-30.0, sail=4))
    put_pos(T0 + 5 * H)  # la route en cours part déjà de cette position
    st = svc.start_state(now=T0 + 10.5 * H)
    assert st["time"] == T0 + 10.5 * H
    assert st["lon"] == pytest.approx(-35.5) and st["sail"] == 4 and st["gate"] == 1
    assert "dernière position il y a 5.5 h" in st["source"]


def test_safe_route_preferred_when_same_start(svc):
    S.write_json(svc.bout / "route.json", route(T0 + 5 * H, lat0=45.0))
    S.write_json(svc.bout / "route-safe.json", {**route(T0 + 5 * H, lat0=40.0, start_lat=45.0)})
    st = svc.start_state(now=T0 + 6 * H)
    assert st["lat"] == pytest.approx(40.0) and "aucune position saisie" in st["source"]


def test_boats_with_other_options_never_share_a_route(svc):
    """Même ligne de départ, mais pas les mêmes options VR : chacun son calcul."""
    svc.options = {"foils": True, "winch_pro": True}
    other = S.Service.__new__(S.Service)
    other.boat, other.bout, other.course = "keziah", svc.bout, svc.course
    other.options = {"foils": True, "winch_pro": False}
    a, b = svc.start_signature(), other.start_signature()
    assert a[:5] == b[:5] and a != b


def test_stale_safe_route_ignored(svc):
    S.write_json(svc.bout / "route.json", route(T0 + 5 * H, lat0=45.0))
    S.write_json(svc.bout / "route-safe.json", route(T0 + 2 * H, lat0=40.0))  # d'une ancienne route GFS
    assert svc.start_state(now=T0 + 6 * H)["lat"] == pytest.approx(45.0)
