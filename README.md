# Discord Finviz Bot

This Discord bot allows users to fetch and display stock charts from Finviz directly in Discord channels. It supports daily, weekly, and monthly charts for various stock tickers.

## Features

- Fetch stock charts from Finviz
- Support for daily, weekly, and monthly timeframes
- Easy-to-use command structure

## Requirements

- Python 3.7+
- discord.py library
- finvizfinance library

## Setup

1. Clone this repository or download the `discord_finviz_bot.py` file.

2. Install the required dependencies:
   ```
   pip install discord.py finvizfinance
   ```

3. Create a Discord bot and get your bot token:
   - Go to the [Discord Developer Portal](https://discord.com/developers/applications)
   - Click "New Application" and give it a name
   - Go to the "Bot" tab and click "Add Bot"
   - Under the bot's username, click "Copy" to copy your bot token

4. Replace the placeholder token in `discord_finviz_bot.py`:
   
   Find this line at the bottom of the file:
   ```python
   bot.run('YOUR_BOT_TOKEN_HERE')
   ```
   Replace `'YOUR_BOT_TOKEN_HERE'` with your actual bot token.

5. Invite the bot to your Discord server:
   - In the Discord Developer Portal, go to the "OAuth2" tab
   - In the "Scopes" section, select "bot"
   - In the "Bot Permissions" section, select the permissions your bot needs (at minimum: "Send Messages", "Embed Links", and "Attach Files")
   - Copy the generated URL and open it in a new tab to invite the bot to your server

## Running the Bot

To run the bot, simply execute the Python script:

## Usage

To use the bot, send a message in any channel the bot has access to with the following format:

`;TICKER TIMEFRAME`

Where:

- `TICKER` is the stock ticker symbol (e.g., AAPL for Apple Inc.)
- `TIMEFRAME` is either `d` for daily, `w` for weekly, or `m` for monthly

Examples:

- `;AAPL d` - Fetch the daily chart for Apple Inc.
- `;MSFT w` - Fetch the weekly chart for Microsoft Corporation
- `;TSLA m` - Fetch the monthly chart for Tesla, Inc.

## Note

This bot uses the free version of Finviz, which does not support intraday charts. Requests for 3, 5, or 15-minute charts will result in an error message.

## License

This project is licensed under the BSD 3-Clause License.

## Disclaimer

This bot is for educational and informational purposes only. It is not intended to provide investment advice. Always do your own research before making any investment decisions.
