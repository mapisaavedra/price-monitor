import json
import math
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
import responses

from price_monitor import alerts, analytics, storage
from price_monitor.cli import run
from price_monitor.config import AlertRules, Asset, ConfigError, load_config
from price_monitor.sources import BASE_URL, CoinGecko, SourceError

NOW = datetime(2026, 11, 8, 12, tzinfo=UTC)


class FakeSource:
    """Serie sintética determinista: 90 días horarios."""
    def __init__(self):
        self.calls = {"history": 0, "current": 0}

    def history(self, coin_id, vs, days):
        self.calls["history"] += 1
        base = {"bitcoin": 100_000, "ethereum": 3_000}[coin_id]
        start = NOW - timedelta(days=days)
        return [(start + timedelta(hours=h), base * (1 + 0.05 * math.sin(h / 20)))
                for h in range(days * 24)]

    def current_prices(self, ids, vs):
        self.calls["current"] += 1
        return {"bitcoin": 130_000.0, "ethereum": 3_100.0}


@pytest.fixture
def cfg_file(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(f"""
assets:
  - {{id: bitcoin, symbol: BTC, alerts: {{above: 120000}}}}
  - {{id: ethereum, symbol: ETH}}
storage:
  history_csv: {tmp_path}/data/prices.csv
  alert_state: {tmp_path}/data/state.json
  backfill_days: 30
dashboard:
  data_json: {tmp_path}/docs/data.json
  ma_windows: [24]
""")
    return p


def test_end_to_end_backfill_then_incremental(cfg_file, tmp_path):
    src = FakeSource()
    assert run(str(cfg_file), source=src) == 0
    assert src.calls["history"] == 2

    data = json.loads((tmp_path / "docs/data.json").read_text())
    assert {a["symbol"] for a in data["assets"]} == {"BTC", "ETH"}
    assert len(data["series"]["BTC"]["p"]) > 700
    assert data["summary"]["BTC"]["price"] == 130_000.0
    assert data["alerts"][0]["key"] == "BTC:above"

    # segundo run: no repite backfill y la alerta queda en cooldown
    run(str(cfg_file), source=src)
    assert src.calls["history"] == 2
    state = json.loads((tmp_path / "data/state.json").read_text())
    assert len(state["history"]) == 1


def test_storage_dedupes_by_hour(tmp_path):
    t = datetime(2026, 1, 1, 10, 5, tzinfo=UTC)
    df = storage.append(storage.load(tmp_path / "x.csv"),
                        [(t, "BTC", 1.0), (t + timedelta(minutes=30), "BTC", 2.0)])
    assert len(df) == 1 and df.price.iloc[0] == 2.0
    storage.save(df, tmp_path / "x.csv")
    assert storage.load(tmp_path / "x.csv").price.iloc[0] == 2.0


def test_analytics_metrics():
    idx = pd.date_range("2026-01-01", periods=48, freq="h", tz="UTC")
    s = pd.Series([100.0] * 24 + [110.0] * 23 + [99.0], index=idx)
    assert analytics.pct_change_over(s, 24) == pytest.approx(-1.0)
    assert analytics.max_drawdown(s) == pytest.approx(-10.0)


def test_alert_rules_and_cooldown(tmp_path):
    a = Asset("bitcoin", "BTC", "Bitcoin", alerts=AlertRules(below=50, move_pct_24h=5))
    found = alerts.evaluate([a], {"BTC": {"price": 40, "change_24h": -8}}, NOW)
    assert {x.key for x in found} == {"BTC:below", "BTC:move24h"}

    fresh, state = alerts.filter_cooldown(found, tmp_path / "s.json", NOW, 6)
    alerts.save_state(state, tmp_path / "s.json")
    again, _ = alerts.filter_cooldown(found, tmp_path / "s.json", NOW + timedelta(hours=1), 6)
    later, _ = alerts.filter_cooldown(found, tmp_path / "s.json", NOW + timedelta(hours=7), 6)
    assert len(fresh) == 2 and again == [] and len(later) == 2


def test_config_validation(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("assets: []")
    with pytest.raises(ConfigError):
        load_config(p)


@responses.activate
def test_coingecko_retries_then_succeeds():
    url = f"{BASE_URL}/simple/price"
    responses.add(responses.GET, url, status=429)
    responses.add(responses.GET, url, json={"bitcoin": {"usd": 1.5}})
    assert CoinGecko(backoff=0).current_prices(["bitcoin"], "usd") == {"bitcoin": 1.5}


@responses.activate
def test_coingecko_gives_up():
    responses.add(responses.GET, f"{BASE_URL}/simple/price", status=503)
    with pytest.raises(SourceError):
        CoinGecko(retries=2, backoff=0).current_prices(["bitcoin"], "usd")
