import json

import pytest

from routeur import relay as R
from routeur import service as S

CFG = {"boats": [{"id": "keziah", "name": "Keziah", "options": {"foils": True}}, {"id": "papa", "name": "Papa"}],
       "boat": {"foils": True, "hull": True, "winch_pro": True, "auto_sail": True, "light_sails": True,
                "heavy_sails": True, "reach_sail": True},
       "gfs": {"lat_min": 5.0, "lat_max": 60.0, "lon_min": -85.0, "lon_max": 5.0},
       "relay": {"ntfy_topic": "rr-test"}}
SAILS = ["Jib", "Spi", "Staysail", "LightJib", "Code0", "HeavyGnk", "LightGnk"]
PAPA = {"foils": True, "hull": False, "winch_pro": True, "auto_sail": False, "light_sails": True,
        "heavy_sails": False, "reach_sail": True}


def ntfy(body: dict, t_recv: float, mid: str = "m1", sig: str | None = None) -> dict:
    outer = {"data": json.dumps(body), **({"sig": sig} if sig else {})}
    return {"id": mid, "event": "message", "time": t_recv, "message": json.dumps(outer)}


@pytest.fixture
def tmp_root(tmp_path, monkeypatch):
    root = lambda rel: tmp_path / rel  # noqa: E731
    monkeypatch.setattr(R, "resolve", root)
    monkeypatch.setattr(S, "resolve", root)
    return tmp_path


def test_position_accepted_without_code():
    pos = R.parse_message(ntfy({"bateau": "papa", "lat": "46°12'30\" N", "lon": "23°40,1 W", "voile": "Code 0",
                                "porte": 2, "twa": "-125", "t": 1000.0}, 1010.0), CFG, SAILS)
    assert pos["boat"] == "papa" and pos["gate"] == 2 and pos["sail"] == SAILS.index("Code0")
    assert pos["lat"] == pytest.approx(46.2083, abs=1e-4) and pos["lon"] == pytest.approx(-23.6683, abs=1e-4)
    assert pos["twa"] == -125 and pos["time"] == 1000.0


def test_old_signed_message_still_read():
    pos = R.parse_message(ntfy({"bateau": "papa", "lat": 46.2, "lon": -23.6, "t": 1000.0}, 1000.0, sig="ab12"),
                          CFG, SAILS)
    assert pos["lat"] == 46.2


@pytest.mark.parametrize("body", [
    {"bateau": "papa", "lat": 46.2, "lon": -23.6, "t": 1000.0 - 3600},  # vieux message rejoué
    {"bateau": "inconnu", "lat": 46.2, "lon": -23.6, "t": 1000.0},
    {"bateau": "papa", "lat": -46.2, "lon": -23.6, "t": 1000.0},        # hors de la zone météo
    {"bateau": "papa", "action": "options", "options": {"foils": True}, "t": 1000.0},  # options incomplètes
    {"bateau": "papa", "action": "options", "options": {**PAPA, "hull": "non"}, "t": 1000.0},
])
def test_bad_messages_rejected(body):
    assert R.parse_message(ntfy(body, 1000.0), CFG, SAILS) is None


def test_boats_public_options(tmp_root):
    pub = R.boats_public(CFG)
    assert pub["ntfy_topic"] == "rr-test"
    kez, papa = pub["boats"]
    assert kez["options_set"] is True and all(kez["options"].values())
    assert papa == {"id": "papa", "name": "Papa", "options": CFG["boat"], "options_set": False}


def test_options_from_page_override_config(tmp_root):
    msgs = [ntfy({"bateau": "papa", "action": "options", "options": {**PAPA, "hull": True}, "t": 100.0}, 100.0, "o1"),
            ntfy({"bateau": "papa", "action": "options", "options": PAPA, "t": 200.0}, 200.0, "o2")]
    assert R.relay(CFG, SAILS, lambda url: "\n".join(json.dumps(m) for m in msgs)) == ["papa"]
    assert S.boat_options(CFG, "papa") == (PAPA, True)
    papa = R.boats_public(CFG)["boats"][1]
    assert papa["options"] == PAPA and papa["options_set"] is True
    assert not (tmp_root / "data/positions/papa.json").exists()  # des options ne sont pas une position


def test_relay_keeps_latest_position_per_boat(tmp_root):
    msgs = [ntfy({"bateau": "papa", "lat": 40, "lon": -30, "t": 100.0}, 100.0, "a"),
            ntfy({"bateau": "papa", "lat": 41, "lon": -31, "t": 200.0}, 200.0, "b"),
            ntfy({"bateau": "keziah", "lat": 42, "lon": -32, "t": 150.0}, 150.0 + 3600, "c")]
    seen = []

    def get(url):
        seen.append(url)
        return "\n".join(json.dumps(m) for m in msgs) + "\n" + json.dumps({"event": "keepalive"})

    assert R.relay(CFG, SAILS, get) == ["papa"]
    assert json.loads((tmp_root / "data/positions/papa.json").read_text())["lat"] == 41
    assert not (tmp_root / "data/positions/keziah.json").exists()
    assert "since=12h" in seen[0]
    R.relay(CFG, SAILS, get)
    assert "since=c" in seen[1]  # reprend après le dernier message lu


def test_recalc_request_without_position(tmp_root):
    msgs = [ntfy({"bateau": "keziah", "action": "recalcul", "t": 100.0}, 100.0, "r1")]
    assert R.relay(CFG, SAILS, lambda url: "\n".join(json.dumps(m) for m in msgs)) == ["keziah"]
    assert not (tmp_root / "data/positions").exists()
