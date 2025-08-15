import argparse
import datetime as dt
from pathlib import Path
import csv

import numpy as np
import pandas as pd
import requests
import yaml
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def load_config(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def fetch_prices(assets, url, vs_currency):
    ids = ",".join(a["id"] for a in assets)
    params = {"ids": ids, "vs_currencies": vs_currency}
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    prices = {}
    for a in assets:
        aid = a["id"]
        if aid in data and vs_currency in data[aid]:
            prices[a["name"]] = float(data[aid][vs_currency])
    return prices


def append_history(csv_path, timestamp, prices):
    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    file_exists = Path(csv_path).exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not file_exists:
            w.writerow(["timestamp"] + list(prices.keys()))
        w.writerow([timestamp.isoformat()] + [prices[k] for k in prices.keys()])


def load_history(csv_path):
    if not Path(csv_path).exists():
        return None
    df = pd.read_csv(csv_path, parse_dates=["timestamp"])
    df = df.sort_values("timestamp")
    return df


def enrich_with_changes(df: pd.DataFrame):
    """Agrega % cambio vs. punto anterior y rellena NaN con 0 para funcionar en el primer run."""
    result = df.copy()
    for col in df.columns:
        if col == "timestamp":
            continue
        result[f"{col}_pct"] = result[col].pct_change() * 100.0
    return result.fillna(0.0)


def build_dashboard(df: pd.DataFrame, cfg: dict):
    colors = {a["name"]: a.get("color") for a in cfg["assets"]}
    bg = cfg["chart"].get("theme_bg", "#0f1220")
    fg = cfg["chart"].get("theme_fg", "#e8ecf5")
    ma_windows = cfg["chart"].get("ma_windows", [5, 20])

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Series y medias móviles (si hay muy pocos puntos, Plotly igual pinta)
    for col in df.columns:
        if col == "timestamp" or col.endswith("_pct"):
            continue
        fig.add_trace(
            go.Scatter(
                x=df["timestamp"], y=df[col], name=col,
                mode="lines+markers" if len(df) <= 3 else "lines",
                line=dict(width=2, color=colors.get(col))
            ),
            secondary_y=False
        )
        for w in ma_windows:
            ma = df[col].rolling(w).mean()
            fig.add_trace(
                go.Scatter(
                    x=df["timestamp"], y=ma, name=f"{col} MA{w}",
                    mode="lines", line=dict(width=1, dash="dot")
                ),
                secondary_y=False
            )

    # Δ% promedio como barras (rellenado con 0s en primeros puntos)
    vol_cols = [c for c in df.columns if c.endswith("_pct")]
    if vol_cols:
        vol = df[vol_cols].mean(axis=1).fillna(0.0)
        fig.add_trace(
            go.Bar(x=df["timestamp"], y=vol, name="Δ% promedio", opacity=0.25),
            secondary_y=True
        )

    fig.update_layout(
        title="Histórico de precios (MA y Δ% promedio)",
        template="plotly_dark",
        plot_bgcolor=bg, paper_bgcolor=bg,
        font=dict(color=fg),
        legend=dict(orientation="h", y=-0.2),
        margin=dict(l=40, r=20, t=60, b=100),
        height=580,
    )
    fig.update_yaxes(title_text="Precio (USD)", secondary_y=False, gridcolor="rgba(255,255,255,0.06)")
    fig.update_yaxes(title_text="Δ% (barra)", secondary_y=True, gridcolor="rgba(255,255,255,0.06)")

    # Tabla de últimos valores
    last_row = df.iloc[-1]
    latest = []
    for col in df.columns:
        if col == "timestamp" or col.endswith("_pct"):
            continue
        pct_col = f"{col}_pct"
        latest.append([col, f"${last_row[col]:,.2f}", f"{last_row.get(pct_col, 0.0):+.2f}%"])
    table = go.Figure(
        data=[go.Table(
            header=dict(values=["Activo", "Último precio", "Δ% vs. anterior"]),
            cells=dict(values=list(zip(*latest)))
        )]
    )
    table.update_layout(
        template="plotly_dark", plot_bgcolor=bg, paper_bgcolor=bg,
        font=dict(color=fg), margin=dict(l=0, r=0, t=10, b=0), height=220
    )

    return fig, table


def check_alerts(prices, assets):
    alerts = []
    for a in assets:
        name = a["name"]
        p = prices.get(name)
        if p is None:
            continue
        if "upper" in a and p >= a["upper"]:
            alerts.append(f"ALERTA: {name} ≥ {a['upper']} → {p:.2f} USD")
        if "lower" in a and p <= a["lower"]:
            alerts.append(f"ALERTA: {name} ≤ {a['lower']} → {p:.2f} USD")
    return alerts


def notify_telegram(text, cfg):
    token = cfg.get("telegram", {}).get("bot_token") or ""
    chat_id = cfg.get("telegram", {}).get("chat_id") or ""
    if not token or not chat_id:
        return False
    try:
        import requests as rq
        rq.post(f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text}, timeout=15)
        return True
    except Exception:
        return False


def write_dashboard_html(fig, table, out_html):
    from plotly.io import to_html
    Path(out_html).parent.mkdir(parents=True, exist_ok=True)
    body = f"""
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dashboard de precios</title>
<style>
  body{{margin:0;background:#0f1220;color:#e8ecf5;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif}}
  .wrap{{max-width:1100px;margin:24px auto;padding:0 16px}}
  .card{{background:#15192b;border:1px solid #26304a;border-radius:14px;padding:14px;box-shadow:0 10px 24px rgba(0,0,0,.25)}}
  h1{{font-size:1.4rem;margin:0 0 12px}}
  footer{{opacity:.7;margin:18px 0}}
</style>
</head>
<body>
  <div class="wrap">
    <h1>Dashboard de precios</h1>
    <div class="card">
      {to_html(fig, include_plotlyjs="cdn", full_html=False)}
    </div>
    <div class="card" style="margin-top:14px">
      {to_html(table, include_plotlyjs=False, full_html=False)}
    </div>
    <footer>Generado automáticamente por GitHub Actions.</footer>
  </div>
</body>
</html>
"""
    Path(out_html).write_text(body, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="src/config.yaml")
    args = ap.parse_args()

    cfg = load_config(args.config)
    assets = cfg["assets"]
    url = cfg["source"]["url"]
    vs = cfg["source"]["vs_currency"]
    csv_path = cfg["output"]["history_csv"]
    out_html = cfg["output"]["dashboard_html"]

    now = dt.datetime.utcnow()
    prices = fetch_prices(assets, url, vs)
    append_history(csv_path, now, prices)

    df = load_history(csv_path)
    if df is None or df.empty:
        # Caso muy raro: no se pudo crear el CSV; salimos con info.
        print("No hay histórico aún; vuelve a ejecutar.")
        return

    df = enrich_with_changes(df)
    fig, table = build_dashboard(df, cfg)
    write_dashboard_html(fig, table, out_html)

    alerts = check_alerts(prices, assets)
    if cfg.get("alerts", {}).get("enabled", False) and alerts:
        msg = " | ".join(alerts)
        print(msg)
        if cfg.get("telegram"):
            notify_telegram(msg, cfg)

    print(f"[{now.isoformat()}Z] " + ", ".join([f"{k}: ${v}" for k, v in prices.items()]))
    if alerts:
        print("ALERTAS:")
        for a in alerts:
            print(" - " + a)


if __name__ == "__main__":
    main()
