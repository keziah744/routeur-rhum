import pytest

from routeur import alerts as A
from routeur import service as S
from routeur.roadmap import iso

H = 3600.0
T0 = 1_800_000_000.0
CFG = {"relay": {"ntfy_topic": "rr-test", "page_url": "https://exemple.github.io/routeur/"}}
BOATS = [{"id": "keziah", "name": "Keziah"}, {"id": "papa", "name": "Papa"}]


def route(eta_h, lat_shift=0.0):
    track = [[46.0 + lat_shift * min(k, 5) / 5, -20.0 - k, iso(T0 + k * H), 4, 15.0, -120.0, 20.0] for k in range(30)]
    wps = [{"n": 3, "t": iso(T0 + 2 * H), "heading": 245.4, "sail": "Code0", "lat": 46.0, "lon": -22.0}]
    return {"track": track, "eta": iso(T0 + eta_h * H), "waypoints": wps}


def test_small_change_is_silent():
    assert A.route_change_message(route(100), route(100.4), now=T0) is None


def test_eta_change_alerts_with_next_waypoint():
    msg = A.route_change_message(route(100), route(98.5), now=T0)
    assert "−1.5 h" in msg and "WP03" in msg and "cap 245°" in msg and "Code 0" in msg


def test_track_change_in_next_24h_alerts():
    msg = A.route_change_message(route(100), route(100, lat_shift=0.5), now=T0)  # 30 milles plus au nord
    assert msg and "reprogramme" in msg


def test_nothing_sent_without_switch(monkeypatch):
    monkeypatch.delenv("ROUTEUR_ALERTES", raising=False)
    sent = []
    assert not A.send(CFG, "papa", "t", "m", post=sent.append) and not sent


def test_send_payload(monkeypatch):
    monkeypatch.setenv("ROUTEUR_ALERTES", "1")
    sent = []
    assert A.send(CFG, "papa", "Nouvelle route · Papa", "texte", post=sent.append)
    assert sent == [{"topic": "rr-test-papa", "title": "Nouvelle route · Papa", "message": "texte",
                     "tags": ["sailboat"], "click": "https://exemple.github.io/routeur/?bateau=papa"}]


def test_position_reminder_every_6h(tmp_path, monkeypatch):
    monkeypatch.setenv("ROUTEUR_ALERTES", "1")
    monkeypatch.setattr(A, "resolve", lambda rel: tmp_path / rel)
    monkeypatch.setattr(S, "resolve", lambda rel: tmp_path / rel)
    sent = []
    last = {"keziah": T0 + 9 * H, "papa": None}  # Keziah : position de 1 h ; Papa : aucune
    assert A.remind_positions(CFG, BOATS, last, T0, now=T0 + 10 * H, post=sent.append) == ["papa"]
    assert "Aucune position" in sent[0]["message"]
    assert A.remind_positions(CFG, BOATS, last, T0, now=T0 + 12 * H, post=sent.append) == []  # déjà rappelé
    assert A.remind_positions(CFG, BOATS, last, T0, now=T0 + 16.5 * H, post=sent.append) == ["keziah", "papa"]


def test_no_reminder_before_start(monkeypatch):
    monkeypatch.setenv("ROUTEUR_ALERTES", "1")
    assert A.remind_positions(CFG, BOATS, {}, T0, now=T0 - H, post=pytest.fail) == []
