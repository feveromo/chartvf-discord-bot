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
;AAPL          daily candle chart
;AAPL w        weekly candle chart
;AAPL m line   monthly line chart
;help          show help
```

Timeframes: `d`, `w`, `m`.
Chart types: `candle`, `line`.

Intraday Finviz charts are not included because they are Elite-gated.
