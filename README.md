# Discord Finviz Chart Bot

A tiny Discord bot that posts Finviz stock charts. Nothing else.

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
;AAPL                daily candle chart
;AAPL w              weekly candle chart
;AAPL m line         monthly line chart
;AAPL light log      light theme, log scale
;AAPL percent        percent scale
;AAPL 1y             1-year chart
;AAPL w 5y           5-year weekly chart
;help                show help
```

Timeframes: `d`, `w`, `m`.
Chart types: `candle`, `line`.
Ranges: `1m`, `3m`, `6m`, `ytd`, `1y`, `2y`, `5y`, `max`.
Themes: `dark`, `light`.
Scales: `linear`, `log`, `percent`.

Intraday Finviz chart params are not included because Finviz silently downgrades them to daily charts.
