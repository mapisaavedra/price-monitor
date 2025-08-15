# Price Monitor — Interactivo (Plotly + GitHub Actions)

Proyecto de automatización para portafolio: consulta precios de CoinGecko (sin API key), guarda histórico en CSV y genera un **dashboard interactivo** con Plotly en `docs/dashboard.html` (publicado con GitHub Pages).

## Stack
- Python 3.11
- requests · pandas · numpy · pyyaml · plotly
- GitHub Actions (cron)

## Cómo usar
```bash
python -m venv .venv && source .venv/bin/activate      # Win: .venv\Scripts\activate
pip install -r requirements.txt
python src/monitor_plotly.py --config src/config.yaml
