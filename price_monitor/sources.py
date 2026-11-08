"""Cliente de CoinGecko con reintentos y backoff exponencial."""
from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://api.coingecko.com/api/v3"


class SourceError(RuntimeError):
    pass


class CoinGecko:
    def __init__(self, session: requests.Session | None = None,
                 retries: int = 4, backoff: float = 2.0, timeout: float = 20):
        self.s = session or requests.Session()
        self.s.headers["User-Agent"] = "price-monitor/2.0"
        # API key demo opcional (gratis) para más cuota
        if key := os.getenv("COINGECKO_API_KEY"):
            self.s.headers["x-cg-demo-api-key"] = key
        self.retries, self.backoff, self.timeout = retries, backoff, timeout

    def _get(self, path: str, params: dict) -> dict:
        last_err: Exception | None = None
        for attempt in range(self.retries):
            try:
                r = self.s.get(f"{BASE_URL}{path}", params=params, timeout=self.timeout)
                if r.status_code == 429 or r.status_code >= 500:
                    raise SourceError(f"HTTP {r.status_code}")
                r.raise_for_status()
                return r.json()
            except (requests.RequestException, SourceError) as e:
                last_err = e
                wait = self.backoff * (2 ** attempt)
                log.warning("CoinGecko %s falló (%s); reintento en %.0fs", path, e, wait)
                if attempt < self.retries - 1:
                    time.sleep(wait)
        raise SourceError(f"CoinGecko {path} falló tras {self.retries} intentos: {last_err}")

    def current_prices(self, ids: list[str], vs: str) -> dict[str, float]:
        data = self._get("/simple/price", {"ids": ",".join(ids), "vs_currencies": vs})
        out = {}
        for i in ids:
            if i in data and vs in data[i]:
                out[i] = float(data[i][vs])
            else:
                log.warning("Sin precio para %s", i)
        return out

    def history(self, coin_id: str, vs: str, days: int) -> list[tuple[datetime, float]]:
        """Serie histórica (granularidad horaria para days<=90)."""
        data = self._get(f"/coins/{coin_id}/market_chart",
                         {"vs_currency": vs, "days": days})
        return [(datetime.fromtimestamp(ms / 1000, tz=UTC), float(p))
                for ms, p in data.get("prices", [])]
