import discord
from discord.ext import commands
from finvizfinance.quote import finvizfinance

# Set up Discord bot with necessary intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=';', intents=intents)

@bot.event
async def on_ready():
    """
    Event handler that runs when the bot successfully connects to Discord.
    Prints a confirmation message to the console.
    """
    print(f'{bot.user} has connected to Discord!')

@bot.event
async def on_message(message):
    """
    Event handler for incoming messages.
    Ignores messages from the bot itself and processes commands starting with ';'.
    
    Args:
        message (discord.Message): The incoming message object.
    """
    # Ignore messages from the bot itself
    if message.author == bot.user:
        return

    # Check if the message is a command (starts with ';')
    if message.content.startswith(';'):
        parts = message.content[1:].split()
        if len(parts) == 2:
            ticker, timeframe = parts
            await send_chart(message.channel, ticker, timeframe)
        else:
            await message.channel.send("Invalid command. Use format: ;ticker timeframe (e.g., ;aapl d, ;aapl w, ;aapl m)")

async def send_chart(channel, ticker: str, timeframe: str):
    """
    Fetches and sends a stock chart for the given ticker and timeframe.
    
    Args:
        channel (discord.TextChannel): The channel to send the chart to.
        ticker (str): The stock ticker symbol.
        timeframe (str): The chart timeframe ('d', 'w', or 'm').
    """
    timeframe = timeframe.lower()
    valid_timeframes = {
        'd': 'daily', 'w': 'weekly', 'm': 'monthly'
    }
    
    if timeframe in ['3', '5', '15']:
        await channel.send("Intraday charts (3, 5, 15 minutes) are only available for FINVIZ*Elite users. Please use 'd' for daily, 'w' for weekly, or 'm' for monthly charts.")
        return
    
    if timeframe not in valid_timeframes:
        await channel.send("Invalid timeframe. Use 'd' for daily, 'w' for weekly, or 'm' for monthly.")
        return

    try:
        stock = finvizfinance(ticker)
        chart_url = stock.ticker_charts(timeframe=valid_timeframes[timeframe])
        
        embed = discord.Embed(title=f"{ticker.upper()} {valid_timeframes[timeframe]} Chart", color=0x00ff00)
        embed.set_image(url=chart_url)
        await channel.send(embed=embed)
    except Exception as e:
        await channel.send(f"An error occurred: {str(e)}")

# Start the bot with the provided token
bot.run('YOUR_BOT_TOKEN_HERE')