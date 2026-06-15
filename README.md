# Discord Finviz Chart Bot

A tiny Discord bot that posts Finviz stock and futures charts. Nothing else.

## Setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
printf 'DISCORD_TOKEN=your_discord_bot_token\n' > .env
python main.py
```

Enable **Message Content Intent** for the bot in the Discord Developer Portal.

## Commands

```text
;TICKER [timeframe] [type] [range] [theme] [scale]      stocks
;fut ROOT [timeframe] [type] [range] [theme] [scale]    futures

;AAPL                daily candle chart
;AAPL w              weekly candle chart
;AAPL m line         monthly line chart
;AAPL light log      light theme, log scale
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

Timeframes: `d`, `w`, `m`. Futures also support `1`, `5`, `15`, `30`, `60`, `2h`, `4h`.
Chart types: `candle`, `line`.
Ranges: `1m`, `3m`, `6m`, `ytd`, `1y`, `2y`, `5y`, `max`.
Themes: `dark`, `light`.
Scales: `linear`, `log`, `percent`.

Stock intraday image params are not included because Finviz silently downgrades them to daily charts. Futures intraday works through the quote API. Discord also caps inline image previews, so there is no `big` mode.

## Futures

Futures use `;fut`/`;future`/`;futures`; `;f` remains Ford (`F`). Futures are
rendered locally from Finviz's futures quote API (`instrument=futures`) because
Finviz's image renderer collides with stock tickers for roots like `ES` and `CL`.
This means roots like `ES`, `NQ`, `GC`, `CL`, `6E`, and `VX` work when Finviz has
quote data for them.

## Checks

```bash
python main.py --self-test
python -m py_compile main.py
pyright --pythonpath .venv/bin/python main.py  # optional
```
