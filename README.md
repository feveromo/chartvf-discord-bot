# ChartVF

A tiny Discord chart bot for stocks and futures. It renders local PNGs from market chart data. Nothing else.

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

## Commands

```text
;TICKER [timeframe] [type] [range] [theme] [scale]      stocks
;fut ROOT [timeframe] [type] [range] [theme] [scale]    futures

;AAPL                latest 5-minute candle chart
;AAPL d              daily candle chart
;AMD 1               AMD 1-minute intraday chart
;AAPL w              weekly candle chart
;AAPL m line         monthly line chart
;AAPL dark log       dark theme, log scale
;AAPL percent        percent scale
;AAPL 1y             1-year chart
;AAPL w 5y           5-year weekly chart
;fut ES              E-mini S&P daily candle
;fut ES 15           E-mini S&P 15-minute chart
;fut CL w line       crude oil weekly line
;futures GC 1y       gold 1-year chart
;help                show help
```

Options can be in any order after the ticker.

Timeframes: stocks support `d`, `w`, `m`, plus intraday `1`, `2`, `5`, `15`, `30`, `60`, `4h`. Futures also support `3`, `10`, `2h`.
Chart types: `candle`, `line`.
Ranges: `1m`, `3m`, `6m`, `ytd`, `1y`, `2y`, `5y`, `max`.
Themes: `dark`, `light`.
Scales: `linear`, `log`, `percent`.

Bare stock commands default to the latest 5-minute chart. All chart images are rendered locally from market chart data. Discord also caps inline image previews, so there is no `big` mode.

## Futures

Futures use `;fut`/`;future`/`;futures`; `;f` remains Ford (`F`). Futures roots
are mapped to market symbols such as `ES=F`, `NQ=F`, `GC=F`, `CL=F`, and `6E=F`
for chart data, then rendered locally by the bot.

## Checks

```bash
python main.py --self-test
python -m py_compile main.py charting.py
pyright --pythonpath .venv/bin/python main.py charting.py  # optional
```
