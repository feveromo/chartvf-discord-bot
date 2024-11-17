# Economic Calendar & Stock Chart Discord Bot

A Discord bot that helps traders and investors track market-moving economic events and analyze stocks. Get stock charts, economic data, and automated notifications for important market events.

## 🚀 Quick Start

1. **Create a Discord Bot**
   - Go to [Discord Developer Portal](https://discord.com/developers/applications)
   - Click "New Application" and give it a name
   - Go to "Bot" section and click "Add Bot"
   - Copy your bot token (you'll need this later)

2. **Get a FRED API Key**
   - Visit [FRED API](https://fred.stlouisfed.org/docs/api/api_key.html)
   - Create an account and request an API key
   - Copy your API key (you'll need this too)

3. **Set Up the Bot**
   ```bash
   # Clone the repository
   git clone https://github.com/feveromo/discord-finviz-bot
   cd discord-finviz-bot

   # Install dependencies
   pip install -r requirements.txt

   # Create .env file and add your tokens
   echo "DISCORD_TOKEN=your_discord_token_here" > .env
   echo "FRED_API_KEY=your_fred_api_key_here" >> .env
   ```

4. **Run the Bot**
   ```bash
   python main.py
   ```

5. **Invite Bot to Your Server**
   - Go back to Discord Developer Portal
   - Select your application → OAuth2 → URL Generator
   - Select scopes: `bot`
   - Select permissions: `Send Messages`, `Embed Links`, `Read Message History`
   - Copy and open the generated URL to invite the bot

## 📊 Features

### Stock Charts
Get Finviz charts for any stock with simple commands:
```
;aapl d    → Daily AAPL chart
;msft w    → Weekly MSFT chart
;tsla m    → Monthly TSLA chart
```

### Economic Data
Track important economic indicators:
```
;events           → List upcoming economic releases
;getdata CPIAUCSL → Get latest CPI data
;search gdp      → Search for GDP-related indicators
```

### Analysis Tools
```
;correlation VIXCLS DCOILWTICO 30  → Compare VIX and Oil prices over 30 days
```

## 📈 Tracked Economic Indicators

### High Impact Events
- Consumer Price Index (CPI)
- Core CPI (excluding Food & Energy)
- Nonfarm Payroll
- Unemployment Rate
- GDP
- Federal Funds Rate

### Production & Sales
- Industrial Production Index
- Retail Sales
- Real Retail Sales

### Market Indicators
- VIX Volatility Index
- US Dollar Index
- Crude Oil WTI
- Gold Price

### Interest Rates & Spreads
- 2-Year Treasury Rate
- 10-Year Treasury Rate
- 10Y-2Y Treasury Spread

### Fed Related Data
- Fed Balance Sheet Total Assets
- Velocity of M2 Money Stock
- Monetary Base

### Additional Indicators
- Initial Jobless Claims
- Personal Consumption Expenditures
- Housing Starts

### Series IDs Reference
For direct data queries using `;getdata`, use these series IDs:
```
CPIAUCSL    → Consumer Price Index
CPILFESL    → Core CPI
PAYEMS      → Nonfarm Payroll
UNRATE      → Unemployment Rate
GDP         → Gross Domestic Product
FEDFUNDS    → Federal Funds Rate
INDPRO      → Industrial Production
RSXFS       → Retail Sales
RRSFS       → Real Retail Sales
VIXCLS      → VIX Index
DTWEXB      → US Dollar Index
DCOILWTICO  → Crude Oil WTI
WPU10210301 → Gold Price
DGS2        → 2Y Treasury Rate
DGS10       → 10Y Treasury Rate
T10Y2Y      → 10Y-2Y Spread
WALCL       → Fed Balance Sheet
M2V         → M2 Velocity
BOGMBASE    → Monetary Base
ICSA        → Initial Claims
PCE         → Personal Consumption
HOUST       → Housing Starts
```

## ⚙️ Channel Setup

1. Invite the bot to your server
2. In any channel where you want economic updates:
   ```
   ;setchannel
   ```
3. To stop updates in a channel:
   ```
   ;removechannel
   ```

## 🔔 Notifications

The bot automatically:
- Sends 15-minute advance notices for economic releases
- Provides real-time data updates
- Tracks high-impact economic events

## 🛠️ Troubleshooting

- Make sure both API keys are correctly set in your .env file
- Bot needs permission to send messages and embeds
- For chart issues, check if the ticker symbol is correct
- Economic data is sourced from FRED, which may have delays

## 📝 Notes

- Stock charts are provided by Finviz
- Economic data is sourced from FRED (Federal Reserve Economic Data)
- All times are in US Eastern Time (ET)
- Some economic data may have reporting delays

## 🤝 Contributing

Feel free to:
- Open issues for bugs or suggestions
- Submit pull requests
- Share feature ideas

## 📄 License

This project is open source and available under the MIT License.
