# ChartVF

A tiny Discord chart bot for stocks and futures. It renders local PNG charts from market data:
candles, volume, SMA20/50/200, regular/extended sessions where they make sense, and simple line charts.
Nothing else.

<img width="1280" height="478" alt="AAPL_d_1781687477" src="https://github.com/user-attachments/assets/aa7b1a92-bbdf-4c92-b647-bee0e654b45b" />


## Commands

```text
;TICKER [timeframe] [type] [range] [theme] [scale]      stocks
;fut ROOT [timeframe] [type] [range] [theme] [scale]    futures
```

Options can be in any order after the ticker.

| Command | What it shows |
| --- | --- |
| `;AAPL` | latest 5-minute stock candles |
| `;AAPL d` | daily candles |
| `;AMD 1` | 1-minute intraday candles |
| `;AAPL w` | weekly candles |
| `;AAPL m line` | monthly line chart |
| `;AAPL 1y` | 1-year daily chart |
| `;AAPL w 5y` | 5-year weekly chart |
| `;AAPL dark log` | dark theme, log scale |
| `;AAPL percent` | percent scale |
| `;fut ES` | E-mini S&P futures |
| `;fut ES 15` | 15-minute futures |
| `;fut CL w line` | crude oil weekly line chart |
| `;futures GC 1y` | 1-year gold futures |
| `;help` | command help |

<img width="1280" height="478" alt="ES_i15_1781687948" src="https://github.com/user-attachments/assets/d98b2db3-8256-4c99-82cc-2519e2efda7a" />


## Options

| Option | Values |
| --- | --- |
| Timeframes | stocks: `d`, `w`, `m`, `1`, `2`, `5`, `15`, `30`, `60`, `4h`; futures also: `3`, `10`, `2h` |
| Chart types | `candle`, `line` |
| Ranges | `1m`, `3m`, `6m`, `ytd`, `1y`, `2y`, `5y`, `max` |
| Themes | `light`, `dark` |
| Scales | `linear`, `log`, `percent` |

Bare stock commands default to the latest 5-minute chart.

## Futures

Futures use `;fut`/`;future`/`;futures`; `;f` remains Ford (`F`). Futures roots
are mapped to market symbols such as `ES=F`, `NQ=F`, `GC=F`, `CL=F`, and `6E=F`
for chart data, then rendered locally by the bot.

## Setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
printf 'DISCORD_TOKEN=your_discord_bot_token\n' > .env
python main.py
```

Enable **Message Content Intent** for the bot in the Discord Developer Portal.

## Railway

1. Push this repo to GitHub.
2. In Railway, create a new project from the GitHub repo.
3. Add a Railway variable named `DISCORD_TOKEN` with your Discord bot token.
4. Confirm **Message Content Intent** is enabled for the bot in the Discord Developer Portal.
5. Deploy the service. The repo's `railway.toml` sets the start command to `python main.py`.

This bot is a long-running Discord worker, not an HTTP web service, so it does not need a
`PORT` binding or Railway healthcheck path.

## Checks

```bash
python main.py --self-test
python -m py_compile main.py charting.py
pyright --pythonpath .venv/bin/python main.py charting.py  # optional
```
