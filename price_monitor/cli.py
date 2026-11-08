"""Punto de entrada: python -m price_monitor [--config config.yaml]"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from . import alerts, analytics, dashboard, storage
from .config import load_config
from .sources import CoinGecko, SourceError

log = logging.getLogger("price_monitor")


def run(config_path: str, source: CoinGecko | None = None, skip_fetch: bool = False) -> int:
    cfg = load_config(config_path)
    src = source or CoinGecko()
    now = alerts.utcnow()
    by_id = {a.id: a for a in cfg.assets}

    df = storage.load(cfg.history_csv)

    if not skip_fetch:
        # 1) Backfill de activos sin historia (primer run o activo nuevo)
        missing = storage.assets_without_history(df, [a.symbol for a in cfg.assets])
        for a in cfg.assets:
            if a.symbol in missing and cfg.backfill_days > 0:
                try:
                    hist = src.history(a.id, cfg.vs_currency, cfg.backfill_days)
                    df = storage.append(df, [(t, a.symbol, p) for t, p in hist])
                    log.info("Backfill %s: %d puntos", a.symbol, len(hist))
                except SourceError as e:
                    log.warning("Backfill %s falló: %s", a.symbol, e)

        # 2) Precio actual
        try:
            prices = src.current_prices(list(by_id), cfg.vs_currency)
        except SourceError as e:
            log.error("%s", e)
            prices = {}
        if prices:
            df = storage.append(df, [(now, by_id[i].symbol, p) for i, p in prices.items()])
            storage.save(df, cfg.history_csv)
        elif df.empty:
            log.error("Sin datos: ni histórico ni precio actual.")
            return 1

    w = analytics.wide(df)
    summary = analytics.summarize(w)

    state = {"history": []}
    if cfg.alerts_enabled:
        triggered = alerts.evaluate(cfg.assets, summary, now)
        fresh, state = alerts.filter_cooldown(triggered, cfg.alert_state, now, cfg.cooldown_hours)
        for al in fresh:
            log.info("ALERTA %s", al.message)
        alerts.send_telegram(fresh)
        alerts.save_state(state, cfg.alert_state)
    elif cfg.alert_state.exists():
        state = json.loads(cfg.alert_state.read_text())

    payload = dashboard.build_payload(w, cfg, state.get("history", []), now)
    dashboard.write(payload, cfg.data_json)

    for sym, m in summary.items():
        ch = m["change_24h"]
        log.info("%-4s $%s  24h %s", sym, f"{m['price']:,.2f}",
                 "n/a" if ch is None else f"{ch:+.2f}%")
    return 0


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Monitor de precios cripto")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--skip-fetch", action="store_true",
                    help="Solo regenera el dashboard con el histórico existente")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(message)s")
    sys.exit(run(args.config, skip_fetch=args.skip_fetch))
