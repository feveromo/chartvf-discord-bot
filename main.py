import discord
from discord.ext import commands, tasks
from finvizfinance.quote import finvizfinance
from datetime import datetime, timedelta
import pytz
from fredapi import Fred
import pandas as pd

# Set up Discord bot with necessary intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=';', intents=intents)

# Initialize FRED API
fred = Fred(api_key='YOUR_FRED_API_KEY')

# Store channel IDs where the bot should send updates
ANNOUNCEMENT_CHANNELS = set()

# Economic events cache
daily_events = []

# Important economic indicators to track
ECONOMIC_INDICATORS = {
    'GDP': 'Gross Domestic Product',
    'UNRATE': 'Unemployment Rate',
    'CPIAUCSL': 'Consumer Price Index',
    'FEDFUNDS': 'Federal Funds Rate',
    'INDPRO': 'Industrial Production Index',
    'HOUST': 'Housing Starts',
    'RSXFS': 'Retail Sales',
    'PAYEMS': 'Nonfarm Payroll'
}

async def fetch_economic_events():
    """Fetch upcoming economic releases from FRED"""
    events = []
    today = datetime.now(pytz.UTC)
    
    try:
        for series_id, description in ECONOMIC_INDICATORS.items():
            series_info = fred.get_series_info(series_id)
            if 'release_dates' in series_info:
                next_release = pd.to_datetime(series_info['release_dates'][0])
                if next_release.date() >= today.date():
                    events.append({
                        'time': next_release.isoformat(),
                        'title': f"{description} Release",
                        'series_id': series_id,
                        'impact': 'High',
                        'previous': str(fred.get_series(series_id)[-1]),
                        'forecast': 'N/A'
                    })
        return sorted(events, key=lambda x: x['time'])
    except Exception as e:
        print(f"Error fetching economic events: {e}")
        return []

@tasks.loop(minutes=1)
async def check_events():
    """Check for upcoming economic events and send notifications"""
    now = datetime.now(pytz.UTC)
    
    for event in daily_events:
        event_time = datetime.fromisoformat(event['time'])
        time_until_event = event_time - now
        
        if timedelta(minutes=14) <= time_until_event <= timedelta(minutes=15):
            for channel_id in ANNOUNCEMENT_CHANNELS:
                channel = bot.get_channel(channel_id)
                if channel:
                    embed = discord.Embed(
                        title="🔔 Upcoming Economic Release",
                        description=f"**{event['title']}**",
                        color=0x00ff00
                    )
                    embed.add_field(name="Time", value=event_time.strftime("%H:%M UTC"))
                    embed.add_field(name="Previous Value", value=event['previous'])
                    await channel.send(embed=embed)

@tasks.loop(hours=24)
async def update_daily_events():
    """Update the cache of daily events"""
    global daily_events
    daily_events = await fetch_economic_events()

@bot.event
async def on_ready():
    """
    Event handler that runs when the bot successfully connects to Discord.
    Starts the economic event tasks.
    """
    print(f'{bot.user} has connected to Discord!')
    update_daily_events.start()
    check_events.start()

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if message.content.startswith(';'):
        parts = message.content[1:].split()
        if len(parts) == 2:
            ticker, timeframe = parts
            await send_chart(message.channel, ticker, timeframe)
        else:
            await message.channel.send("Invalid command. Use format: ;ticker timeframe (e.g., ;aapl d, ;aapl w, ;aapl m)")
    
    # This line is important to process commands
    await bot.process_commands(message)

async def send_chart(channel, ticker: str, timeframe: str):
    """Original chart functionality"""
    timeframe = timeframe.lower()
    valid_timeframes = {
        'd': 'daily', 'w': 'weekly', 'm': 'monthly'
    }
    
    if timeframe in ['3', '5', '15']:
        await channel.send("Intraday charts are only available for FINVIZ*Elite users.")
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

@bot.command(name='setchannel')
@commands.has_permissions(administrator=True)
async def set_channel(ctx):
    """Set the current channel for economic event announcements"""
    ANNOUNCEMENT_CHANNELS.add(ctx.channel.id)
    await ctx.send(f"✅ This channel will now receive economic event notifications!")

@bot.command(name='removechannel')
@commands.has_permissions(administrator=True)
async def remove_channel(ctx):
    """Remove the current channel from economic event announcements"""
    ANNOUNCEMENT_CHANNELS.discard(ctx.channel.id)
    await ctx.send(f"❌ This channel will no longer receive economic event notifications!")

@bot.command(name='events')
async def list_events(ctx):
    """List upcoming economic events"""
    if not daily_events:
        await ctx.send("No economic events scheduled.")
        return

    embed = discord.Embed(
        title="📅 Upcoming Economic Releases",
        color=0x00ff00
    )

    for event in daily_events:
        event_time = datetime.fromisoformat(event['time'])
        embed.add_field(
            name=f"{event_time.strftime('%Y-%m-%d %H:%M UTC')} - {event['title']}",
            value=f"Previous: {event['previous']}",
            inline=False
        )

    await ctx.send(embed=embed)

bot.run('YOUR_DISCORD_BOT_TOKEN')