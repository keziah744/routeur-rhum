"""Chaîne météo hors ligne : décodage GRIB réel, sélection du cycle, secours, conservation du dernier valide.

Le réseau est simulé (monkeypatch de http_get) avec deux vrais fichiers GRIB (cycle 25/10 12z, +6 h et +9 h).
"""
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from routeur import gfs
from routeur.config import load_config
from routeur.grib import GribError, decode_wind_file
from routeur.service import Busy, file_lock
from routeur.wind import WindField

FIX = Path(__file__).parent / "fixtures"
F6, F9 = (FIX / "gfs.t12z.f006.grb2").read_bytes(), (FIX / "gfs.t12z.f009.grb2").read_bytes()
NOW = datetime(2026, 10, 25, 18, 30, tzinfo=timezone.utc)


def test_decode_real_grib():
    m = decode_wind_file(FIX / "gfs.t12z.f006.grb2")
    assert m.run == datetime(2026, 10, 25, 12, tzinfo=timezone.utc) and m.forecast_hour == 6
    assert m.u.shape == (221, 361) and m.lats[0] == 5.0 and m.lats[-1] == 60.0
    assert m.lons[0] == -85.0 and m.lons[-1] == 5.0 and np.all(np.diff(m.lons) > 0)
    assert np.abs(m.u).max() < 60 and np.abs(m.v).max() < 60


def test_decode_rejects_html(tmp_path):
    bad = tmp_path / "x.grb2"
    bad.write_bytes(b"<html>Over Rate Limit</html>")
    with pytest.raises(GribError):
        decode_wind_file(bad)


def test_recent_cycles():
    keys = [c.key for c in gfs.recent_cycles(NOW, 3)]
    assert keys == ["2026102518", "2026102512", "2026102506"]


def fake_network(publish: dict, fail_nomads=False, calls=None):
    """publish = {clé de cycle: liste d'échéances publiées}; renvoie un http_get simulé."""
    def http_get(url, timeout, headers=None):
        if calls is not None:
            calls.append(url)
        if "nomads" in url and fail_nomads:
            raise urllib.error.URLError("hors ligne")
        if "/pub/data/" in url:
            date, hh = url.split("gfs.")[1][:8], url.split("/atmos")[0][-2:]
            hours = publish.get(date + hh)
            if hours is None:
                raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)  # cycle en cours de création
            return "".join(f'<a href="gfs.t{hh}z.pgrb2.0p25.f{h:03d}.idx">x</a>' for h in hours).encode()
        if "list-type=2" in url:
            pre = url.split("prefix=gfs.")[1]
            key = pre[:8] + pre[9:11]
            return "".join(f"<Key>a/gfs.t{pre[9:11]}z.pgrb2.0p25.f{h:03d}.idx</Key>" for h in publish.get(key, [])).encode()
        if "filter_gfs" in url:
            fh = int(url.split(".f")[1][:3])
            return {6: F6, 9: F9}[fh]
        raise AssertionError(f"URL inattendue {url}")
    return http_get


@pytest.fixture
def store(tmp_path):
    cfg = load_config()
    cfg["gfs"].update(step_hours=3, max_hour=9, min_usable_hour=9, request_pause_s=0, retries=1)
    s = gfs.GfsStore(cfg, root=tmp_path / "gfs")
    s.wanted_hours = lambda published: [h for h in (6, 9) if h in published]  # seules échéances en fixture
    return s


def test_update_picks_latest_usable_cycle(store, monkeypatch):
    monkeypatch.setattr(gfs, "http_get", fake_network({"2026102512": [0, 3, 6, 9]}))
    monkeypatch.setattr(gfs.time, "sleep", lambda s: None)
    res = store.update(NOW)  # 18z en cours (403) -> 12z
    assert res["changed"] and res["cycle"] == "2026102512"
    w = WindField.load(res["path"])
    assert w.u.shape == (2, 221, 361) and w.valid[1] - w.valid[0] == 3 * 3600
    man = (store.root / "2026102512" / "manifest.json").read_text(encoding="utf-8")
    assert "nomads-filter" in man and "sha256" in man


def test_second_update_downloads_nothing(store, monkeypatch):
    calls = []
    monkeypatch.setattr(gfs, "http_get", fake_network({"2026102512": [0, 3, 6, 9]}, calls=calls))
    monkeypatch.setattr(gfs.time, "sleep", lambda s: None)
    store.update(NOW)
    calls.clear()
    res = store.update(NOW)
    assert not res["changed"]
    assert not any("filter_gfs" in c for c in calls)


def test_failure_keeps_last_valid_forecast(store, monkeypatch):
    monkeypatch.setattr(gfs, "http_get", fake_network({"2026102512": [0, 3, 6, 9]}))
    monkeypatch.setattr(gfs.time, "sleep", lambda s: None)
    first = store.update(NOW)

    def broken(url, timeout, headers=None):
        raise urllib.error.URLError("réseau coupé")
    monkeypatch.setattr(gfs, "http_get", broken)
    res = store.update(datetime(2026, 10, 26, 2, tzinfo=timezone.utc))
    assert res["error"] and res["cycle"] == first["cycle"] and not res["changed"]
    assert Path(res["path"]).exists()
    assert "Dernière prévision valide conservée" in store.status_path.read_text(encoding="utf-8")


def test_listing_falls_back_to_s3(store, monkeypatch):
    monkeypatch.setattr(gfs, "http_get", fake_network({"2026102518": [0, 3, 6, 9]}, fail_nomads=True))
    monkeypatch.setattr(gfs.time, "sleep", lambda s: None)
    found = store.find_latest_cycle(NOW)
    assert found and found[0].key == "2026102518"


def test_incomplete_cycle_is_skipped(store, monkeypatch):
    # 18z publié seulement jusqu'à +3 h : on garde 12z complet.
    monkeypatch.setattr(gfs, "http_get", fake_network({"2026102518": [0, 3], "2026102512": [0, 3, 6, 9]}))
    monkeypatch.setattr(gfs.time, "sleep", lambda s: None)
    assert store.find_latest_cycle(NOW)[0].key == "2026102512"


def test_lock_prevents_parallel_runs(tmp_path):
    lock = tmp_path / "x.lock"
    with file_lock(lock):
        with pytest.raises(Busy):
            with file_lock(lock):
                pass
    with file_lock(lock):  # libéré après usage
        pass
