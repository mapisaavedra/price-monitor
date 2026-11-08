"""Métricas: variaciones, volatilidad, drawdown, medias móviles."""
from __future__ import annotations

import math

import pandas as pd


def wide(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot a una columna por activo, índice horario."""
    if df.empty:
        return pd.DataFrame()
    w = (df.assign(ts=df["timestamp"].dt.floor("h"))
           .pivot_table(index="ts", columns="asset", values="price", aggfunc="last")
           .sort_index())
    return w


def pct_change_over(series: pd.Series, hours: int) -> float | None:
    s = series.dropna()
    if len(s) < 2:
        return None
    last_t = s.index[-1]
    past = s[s.index <= last_t - pd.Timedelta(hours=hours)]
    if past.empty:
        return None
    return (s.iloc[-1] / past.iloc[-1] - 1) * 100


def volatility_annualized(series: pd.Series, hours: int = 24 * 30) -> float | None:
    s = series.dropna()
    s = s[s.index >= s.index[-1] - pd.Timedelta(hours=hours)] if len(s) else s
    r = s.pct_change().dropna()
    if len(r) < 10:
        return None
    return float(r.std() * math.sqrt(24 * 365) * 100)


def max_drawdown(series: pd.Series) -> float | None:
    s = series.dropna()
    if len(s) < 2:
        return None
    dd = s / s.cummax() - 1
    return float(dd.min() * 100)


def summarize(w: pd.DataFrame) -> dict[str, dict]:
    out = {}
    for sym in w.columns:
        s = w[sym].dropna()
        if s.empty:
            continue
        out[sym] = {
            "price": float(s.iloc[-1]),
            "updated": s.index[-1].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "change_24h": pct_change_over(s, 24),
            "change_7d": pct_change_over(s, 24 * 7),
            "change_30d": pct_change_over(s, 24 * 30),
            "high_30d": float(s[s.index >= s.index[-1] - pd.Timedelta(days=30)].max()),
            "low_30d": float(s[s.index >= s.index[-1] - pd.Timedelta(days=30)].min()),
            "volatility_30d": volatility_annualized(s),
            "max_drawdown": max_drawdown(s),
        }
    return out


def correlation(w: pd.DataFrame) -> dict:
    r = w.pct_change().dropna(how="all")
    if len(r) < 10 or w.shape[1] < 2:
        return {"assets": list(w.columns), "matrix": []}
    c = r.corr().round(3)
    return {"assets": list(c.columns), "matrix": c.values.tolist()}
