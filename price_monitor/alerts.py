"""Reglas de alerta con cooldown persistente y envío a Telegram."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests

from .config import Asset

log = logging.getLogger(__name__)


@dataclass
class Alert:
    key: str          # p.ej. "BTC:above"
    asset: str
    message: str
    at: str


def evaluate(assets: list[Asset], summary: dict[str, dict], now: datetime) -> list[Alert]:
    alerts = []
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    for a in assets:
        m = summary.get(a.symbol)
        if not m:
            continue
        p, r = m["price"], a.alerts
        if r.above is not None and p >= r.above:
            alerts.append(Alert(f"{a.symbol}:above", a.symbol,
                                f"🚀 {a.symbol} superó {r.above:,.0f} → ${p:,.2f}", stamp))
        if r.below is not None and p <= r.below:
            alerts.append(Alert(f"{a.symbol}:below", a.symbol,
                                f"🔻 {a.symbol} cayó bajo {r.below:,.0f} → ${p:,.2f}", stamp))
        ch = m.get("change_24h")
        if r.move_pct_24h is not None and ch is not None and abs(ch) >= r.move_pct_24h:
            alerts.append(Alert(f"{a.symbol}:move24h", a.symbol,
                                f"⚡ {a.symbol} {ch:+.2f}% en 24h → ${p:,.2f}", stamp))
    return alerts


def filter_cooldown(alerts: list[Alert], state_path: Path, now: datetime,
                    cooldown_hours: float) -> tuple[list[Alert], dict]:
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except json.JSONDecodeError:
            state = {}
    fresh = []
    for al in alerts:
        last = state.get("last_sent", {}).get(al.key)
        if last and now - datetime.fromisoformat(last) < timedelta(hours=cooldown_hours):
            continue
        fresh.append(al)
        state.setdefault("last_sent", {})[al.key] = al.at
    history = state.get("history", []) + [asdict(a) for a in fresh]
    state["history"] = history[-50:]
    return fresh, state


def save_state(state: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def send_telegram(alerts: list[Alert]) -> bool:
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not alerts or not token or not chat:
        return False
    text = "📈 *Price Monitor*\n" + "\n".join(a.message for a in alerts)
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": text, "parse_mode": "Markdown"},
                          timeout=15)
        r.raise_for_status()
        return True
    except requests.RequestException as e:
        log.error("Telegram falló: %s", e)
        return False


def utcnow() -> datetime:
    return datetime.now(UTC)
