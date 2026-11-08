"""Carga y validación de configuración."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class AlertRules:
    above: float | None = None
    below: float | None = None
    move_pct_24h: float | None = None


@dataclass(frozen=True)
class Asset:
    id: str
    symbol: str
    name: str
    color: str = "#94a3b8"
    alerts: AlertRules = field(default_factory=AlertRules)


@dataclass(frozen=True)
class Config:
    assets: list[Asset]
    vs_currency: str
    history_csv: Path
    alert_state: Path
    backfill_days: int
    data_json: Path
    ma_windows: list[int]
    alerts_enabled: bool
    cooldown_hours: float


class ConfigError(ValueError):
    pass


def load_config(path: str | Path) -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    assets_raw = raw.get("assets") or []
    if not assets_raw:
        raise ConfigError("config: 'assets' no puede estar vacío")

    assets, seen = [], set()
    for a in assets_raw:
        if "id" not in a or "symbol" not in a:
            raise ConfigError(f"config: cada asset necesita 'id' y 'symbol': {a}")
        if a["symbol"] in seen:
            raise ConfigError(f"config: símbolo duplicado {a['symbol']}")
        seen.add(a["symbol"])
        rules = AlertRules(**(a.get("alerts") or {}))
        assets.append(Asset(
            id=a["id"], symbol=a["symbol"], name=a.get("name", a["symbol"]),
            color=a.get("color", "#94a3b8"), alerts=rules,
        ))

    storage = raw.get("storage", {})
    dash = raw.get("dashboard", {})
    alerts = raw.get("alerts", {})
    return Config(
        assets=assets,
        vs_currency=raw.get("vs_currency", "usd"),
        history_csv=Path(storage.get("history_csv", "data/prices.csv")),
        alert_state=Path(storage.get("alert_state", "data/alert_state.json")),
        backfill_days=int(storage.get("backfill_days", 90)),
        data_json=Path(dash.get("data_json", "docs/data.json")),
        ma_windows=list(dash.get("ma_windows", [24, 168])),
        alerts_enabled=bool(alerts.get("enabled", True)),
        cooldown_hours=float(alerts.get("cooldown_hours", 6)),
    )
