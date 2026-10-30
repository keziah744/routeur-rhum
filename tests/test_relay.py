import json

import pytest

from routeur import relay as R
from routeur import service as S

CFG = {"boats": [{"id": "keziah", "name": "Keziah"}, {"id": "papa", "name": "Papa"}],
       "relay": {"ntfy_topic": "rr-test"}}
SAILS = ["Jib", "Spi", "Staysail", "LightJib", "Code0", "HeavyGnk", "LightGnk"]
CODES = {"keziah": "voile42", "papa": "ultim77"}


def ntfy(body: dict, code: str, t_recv: float, mid: str = "m1") -> dict:
    data = json.dumps(body)
    return {"id": mid, "event": "message", "time": t_recv,
            "message": json.dumps({"data": data, "sig": R.sign(code, data)})}


def test_signed_message_accepted():
    pos = R.parse_message(ntfy({"bateau": "papa", "lat": "46°12'30\" N", "lon": "23°40,1 W", "voile": "Code 0",
                                "porte": 2, "twa": "-125", "t": 1000.0}, "ultim77", 1010.0), CFG, CODES, SAILS)
    assert pos["boat"] == "papa" and pos["gate"] == 2 and pos["sail"] == SAILS.index("Code0")
    assert pos["lat"] == pytest.approx(46.2083, abs=1e-4) and pos["lon"] == pytest.approx(-23.6683, abs=1e-4)
    assert pos["twa"] == -125 and pos["time"] == 1000.0


@pytest.mark.parametrize("code, t_sent, boat", [
    ("voile42", 1000.0, "papa"),      # code d'un autre bateau
    ("ultim77", 1000.0 - 3600, "papa"),  # vieux message rejoué
    ("ultim77", 1000.0, "inconnu"),
])
def test_bad_messages_rejected(code, t_sent, boat):
    msg = ntfy({"bateau": boat, "lat": 46.2, "lon": -23.6, "t": t_sent}, code, 1000.0)
    assert R.parse_message(msg, CFG, CODES, SAILS) is None


def test_tampered_data_rejected():
    msg = ntfy({"bateau": "papa", "lat": 46.2, "lon": -23.6, "t": 1000.0}, "ultim77", 1000.0)
    outer = json.loads(msg["message"])
    outer["data"] = outer["data"].replace("46.2", "12.0")
    msg["message"] = json.dumps(outer)
    assert R.parse_message(msg, CFG, CODES, SAILS) is None


def test_codes_from_env_normalised(monkeypatch):
    monkeypatch.setenv("ROUTEUR_CODES", json.dumps({"keziah": "Voile 42"}))
    monkeypatch.setenv("ROUTEUR_CODE_PAPA", " Ultim77 ")
    assert R.codes_from_env(CFG) == {"keziah": "voile42", "papa": "ultim77"}
    pub = R.boats_public(CFG)
    assert pub["ntfy_topic"] == "rr-test"
    assert pub["boats"][1] == {"id": "papa", "name": "Papa", "check": R.check_value("ultim77", "papa")}


def test_relay_keeps_latest_position_per_boat(tmp_path, monkeypatch):
    root = lambda rel: tmp_path / rel  # noqa: E731
    monkeypatch.setattr(R, "resolve", root)
    monkeypatch.setattr(S, "resolve", root)
    monkeypatch.setenv("ROUTEUR_CODES", json.dumps(CODES))
    msgs = [ntfy({"bateau": "papa", "lat": 40, "lon": -30, "t": 100.0}, "ultim77", 100.0, "a"),
            ntfy({"bateau": "papa", "lat": 41, "lon": -31, "t": 200.0}, "ultim77", 200.0, "b"),
            ntfy({"bateau": "keziah", "lat": 42, "lon": -32, "t": 150.0}, "faux", 150.0, "c")]
    seen = []

    def get(url):
        seen.append(url)
        return "\n".join(json.dumps(m) for m in msgs) + "\n" + json.dumps({"event": "keepalive"})

    assert R.relay(CFG, SAILS, get) == ["papa"]
    assert json.loads((tmp_path / "data/positions/papa.json").read_text())["lat"] == 41
    assert not (tmp_path / "data/positions/keziah.json").exists()
    assert "since=12h" in seen[0]
    R.relay(CFG, SAILS, get)
    assert "since=c" in seen[1]  # reprend après le dernier message lu


def test_recalc_request_without_position(tmp_path, monkeypatch):
    root = lambda rel: tmp_path / rel  # noqa: E731
    monkeypatch.setattr(R, "resolve", root)
    monkeypatch.setattr(S, "resolve", root)
    monkeypatch.setenv("ROUTEUR_CODES", json.dumps(CODES))
    msgs = [ntfy({"bateau": "keziah", "action": "recalcul", "t": 100.0}, "voile42", 100.0, "r1"),
            ntfy({"bateau": "papa", "action": "recalcul", "t": 100.0}, "faux", 100.0, "r2")]
    assert R.relay(CFG, SAILS, lambda url: "\n".join(json.dumps(m) for m in msgs)) == ["keziah"]
    assert not (tmp_path / "data/positions").exists()
