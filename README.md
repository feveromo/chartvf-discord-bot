# Economic Calendar Discord Bot

A Discord bot that sends notifications for important economic events like Fed announcements, economic data releases, and more. Also provides stock charts from Finviz.

## Features

- Daily economic event listings and notifications
- 15-minute advance notifications for upcoming events
- Support for multiple announcement channels
- Easy channel management with admin commands
- Stock charts from Finviz
- Timezone-aware scheduling

## Commands

### Stock Charts
- `;ticker timeframe` - Get stock chart (e.g., `;aapl d`, `;msft w`, `;tsla m`)
  - Timeframes: `d` (daily), `w` (weekly), `m` (monthly)

### Economic Events
- `;setchannel` - Set current channel for economic event announcements
- `;removechannel` - Remove current channel from announcements
- `;events` - List all upcoming economic events

## Setup

1. Install requirements:
    ```bash
    pip install -r requirements.txt
    ```

2. Configure the bot:
   - Add your Discord bot token in main.py
   - Add your FRED API key in main.py (get one from https://fred.stlouisfed.org/docs/api/api_key.html)

3. Run the bot:
    ```bash
    python main.py
    ```

## Usage

1. Invite the bot to your server
2. Use `;setchannel` in channels where you want to receive economic announcements
3. The bot will automatically:
   - Send stock charts when requested
   - Provide daily economic event listings
   - Send 15-minute advance notifications for upcoming events

## Economic Indicators Tracked

- Gross Domestic Product (GDP)
- Unemployment Rate (UNRATE)
- Consumer Price Index (CPIAUCSL)
- Federal Funds Rate (FEDFUNDS)
- Industrial Production Index (INDPRO)
- Housing Starts (HOUST)
- Retail Sales (RSXFS)
- Nonfarm Payroll (PAYEMS)
