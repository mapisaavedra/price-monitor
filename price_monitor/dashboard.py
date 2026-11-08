"""Exporta docs/data.json, que consume el dashboard estático (docs/index.html)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from .analytics import correlation, summarize
from .config import Config


def build_payload(w: pd.DataFrame, cfg: Config, alert_history: list[dict],
                  generated: datetime) -> dict:
    series = {}
    for sym in w.columns:
        s = w[sym].dropna()
        entry = {
            "t": [t.strftime("%Y-%m-%dT%H:%MZ") for t in s.index],
            "p": [round(float(v), 6) for v in s.values],
            "ma": {},
        }
        for win in cfg.ma_windows:
            ma = s.rolling(win, min_periods=win).mean()
            entry["ma"][str(win)] = [None if pd.isna(v) else round(float(v), 6) for v in ma.values]
        series[sym] = entry

    return {
        "generated": generated.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "vs_currency": cfg.vs_currency,
        "ma_windows": cfg.ma_windows,
        "assets": [
            {"id": a.id, "symbol": a.symbol, "name": a.name, "color": a.color,
             "alerts": {k: v for k, v in vars(a.alerts).items() if v is not None}}
            for a in cfg.assets if a.symbol in series
        ],
        "summary": summarize(w),
        "series": series,
        "correlation": correlation(w),
        "alerts": list(reversed(alert_history))[:20],
    }


def write(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
