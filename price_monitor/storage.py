"""Histórico en CSV formato largo (timestamp, asset, price).

El formato largo permite agregar o quitar activos sin romper el archivo.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

COLUMNS = ["timestamp", "asset", "price"]


def load(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=COLUMNS).astype({"price": float})
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    return df


def append(df: pd.DataFrame, rows: list[tuple[datetime, str, float]]) -> pd.DataFrame:
    new = pd.DataFrame(rows, columns=COLUMNS)
    new["timestamp"] = pd.to_datetime(new["timestamp"], utc=True)
    frames = [f for f in (df, new) if not f.empty]
    out = pd.concat(frames, ignore_index=True) if frames else new
    # dedupe por hora: un punto por activo por hora
    out["_h"] = out["timestamp"].dt.floor("h")
    out = (out.sort_values("timestamp")
              .drop_duplicates(["_h", "asset"], keep="last")
              .drop(columns="_h")
              .reset_index(drop=True))
    return out


def save(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    out["timestamp"] = out["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    out.to_csv(path, index=False, float_format="%.8g")


def assets_without_history(df: pd.DataFrame, symbols: list[str]) -> list[str]:
    have = set(df["asset"].unique()) if not df.empty else set()
    return [s for s in symbols if s not in have]
