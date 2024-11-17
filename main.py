import discord
from discord.ext import commands, tasks
from finvizfinance.quote import finvizfinance
from datetime import datetime, timedelta
import pytz
from fredapi import Fred
import pandas as pd
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up Discord bot with necessary intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=';', intents=intents)

# Initialize APIs with environment variables
fred = Fred(api_key=os.getenv('FRED_API_KEY'))

# Store channel IDs where the bot should send updates
ANNOUNCEMENT_CHANNELS = set()

# Economic events cache
daily_events = []

# Important economic indicators and market data to track
ECONOMIC_INDICATORS = {
    # High Impact Events
    'CPIAUCSL': 'Consumer Price Index (CPI)',
    'CPILFESL': 'Core CPI (excluding Food & Energy)',
    'PAYEMS': 'Nonfarm Payroll',
    'UNRATE': 'Unemployment Rate',
    'GDP': 'Gross Domestic Product',
    'FEDFUNDS': 'Federal Funds Rate',
    
    # Production & Sales
    'INDPRO': 'Industrial Production Index',
    'RSXFS': 'Retail Sales',
    'RRSFS': 'Real Retail Sales',
    
    # Market Indicators
    'VIXCLS': 'VIX Volatility Index',
    'DTWEXB': 'US Dollar Index',
    'DCOILWTICO': 'Crude Oil WTI',
    'WPU10210301': 'Gold Price',
    
    # Interest Rates & Spreads
    'DGS2': '2-Year Treasury Rate',
    'DGS10': '10-Year Treasury Rate',
    'T10Y2Y': '10Y-2Y Treasury Spread',
    
    # Fed Related
    'WALCL': 'Fed Balance Sheet Total Assets',
    'M2V': 'Velocity of M2 Money Stock',
    'BOGMBASE': 'Monetary Base',
    
    # Additional Important Data
    'ICSA': 'Initial Jobless Claims',
    'PCE': 'Personal Consumption Expenditures',
    'HOUST': 'Housing Starts'
}

# Add Fed calendar events (these won't come from FRED API)
FED_EVENTS = {
    'FOMC': 'Federal Open Market Committee Meeting',
    'BEIGE': 'Beige Book Release',
    'MINUTES': 'FOMC Minutes Release',
    'TESTIMONY': 'Fed Chair Congressional Testimony',
    'SPEECH': 'Fed Chair Speech'
}

async def fetch_economic_events():
    """Fetch upcoming economic releases from FRED"""
    events = []
    
    # Get current time in ET (US Eastern Time)
    et_tz = pytz.timezone('US/Eastern')
    now = datetime.now(et_tz)
    
    # If it's after 4:30 PM ET, show events for next business day
    if now.hour >= 16 and now.minute >= 30:
        next_day = now + timedelta(days=1)
    else:
        next_day = now
        
    # Skip to Monday if it's weekend
    while next_day.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        next_day += timedelta(days=1)
    
    # Set release time to 8:30 AM ET for next business day
    next_release = next_day.replace(hour=8, minute=30, second=0, microsecond=0)
    
    try:
        for series_id, description in ECONOMIC_INDICATORS.items():
            try:
                # Get series info and latest value
                info = fred.get_series_info(series_id)
                
                # Get recent data (last 30 days)
                end_date = now
                start_date = end_date - timedelta(days=30)
                series = fred.get_series(
                    series_id,
                    observation_start=start_date.strftime('%Y-%m-%d'),
                    observation_end=end_date.strftime('%Y-%m-%d')
                )
                
                if series.empty:
                    # If no recent data, get the last value
                    series = fred.get_series(series_id, limit=1)
                
                # Get the most recent non-null value
                previous_value = None
                for val in series:
                    if pd.notna(val):
                        previous_value = val
                        break
                
                # Format the value based on units and series type
                if previous_value is not None and not pd.isna(previous_value):
                    if series_id in ['UNRATE', 'FEDFUNDS', 'DGS2', 'DGS10', 'T10Y2Y']:
                        formatted_value = f"{previous_value:.2f}%"
                    elif series_id == 'DCOILWTICO':  # Oil price
                        formatted_value = f"${previous_value:.2f}/bbl"
                    elif series_id == 'WPU10210301':  # Gold price
                        formatted_value = f"${previous_value:.2f}/oz"
                    elif 'Billions of Dollars' in info.get('units', ''):
                        formatted_value = f"${previous_value:,.2f}B"
                    elif 'Millions of Dollars' in info.get('units', ''):
                        formatted_value = f"${previous_value:,.2f}M"
                    elif series_id == 'ICSA':
                        formatted_value = f"{previous_value:,.0f}"
                    elif series_id == 'VIXCLS':
                        formatted_value = f"{previous_value:.2f}"
                    else:
                        formatted_value = f"{previous_value:,.2f}"
                else:
                    formatted_value = 'N/A'
                
                events.append({
                    'time': next_release.isoformat(),
                    'title': f"{description}",
                    'series_id': series_id,
                    'impact': 'High' if series_id in ['CPIAUCSL', 'PAYEMS', 'GDP', 'FEDFUNDS'] else 'Medium',
                    'previous': formatted_value
                })
            except Exception as e:
                print(f"Error fetching {series_id}: {e}")
                continue
        
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
                    embed.add_field(name="Impact", value=event['impact'])
                    embed.add_field(name="Previous Value", value=event['previous'])
                    await channel.send(embed=embed)

@tasks.loop(hours=24)
async def update_daily_events():
    """Update the cache of daily events"""
    global daily_events
    daily_events = await fetch_economic_events()

@bot.event
async def on_ready():
    """Bot initialization"""
    print(f'{bot.user} has connected to Discord!')
    update_daily_events.start()
    check_events.start()

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if message.content.startswith(';'):
        # Process help commands first
        if message.content.startswith(';help'):
            await bot.process_commands(message)
            return
            
        # Process other bot commands
        if message.content.startswith((';setchannel', ';removechannel', ';events', 
                                     ';getdata', ';search', ';correlation')):
            await bot.process_commands(message)
            return
            
        # Handle chart commands
        parts = message.content[1:].split()
        if len(parts) == 2:
            ticker, timeframe = parts
            await send_chart(message.channel, ticker, timeframe)
        else:
            await message.channel.send("Invalid command. Use format: ;ticker timeframe (e.g., ;aapl d, ;aapl w, ;aapl m)")
    
    # Process other commands
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
    """Set current channel for economic event announcements
    
    Configures the current channel to receive economic event notifications.
    Requires administrator permissions.
    
    Usage:
        ;setchannel
    """
    ANNOUNCEMENT_CHANNELS.add(ctx.channel.id)
    await ctx.send(f"✅ This channel will now receive economic event notifications!")

@bot.command(name='removechannel')
@commands.has_permissions(administrator=True)
async def remove_channel(ctx):
    """Remove current channel from economic event announcements
    
    Stops economic event notifications in the current channel.
    Requires administrator permissions.
    
    Usage:
        ;removechannel
    """
    ANNOUNCEMENT_CHANNELS.discard(ctx.channel.id)
    await ctx.send(f"❌ This channel will no longer receive economic event notifications!")

@bot.command(name='events')
async def list_events(ctx):
    """Lists upcoming economic releases and events
    
    Shows both high-impact and other economic events with their scheduled times and previous values.
    Events are grouped by date and impact level for easy reading.
    
    Usage:
        ;events
    """
    if not daily_events:
        await ctx.send("No economic events scheduled.")
        return

    # Group events by date and impact
    high_impact_events = []
    other_events = []
    
    for event in daily_events:
        if event['impact'] == 'High':
            high_impact_events.append(event)
        else:
            other_events.append(event)

    # Create embed for high impact events
    high_impact_embed = discord.Embed(
        title="🔴 High Impact Economic Releases",
        color=0xFF0000
    )

    # Format high impact events
    for event in high_impact_events:
        event_time = datetime.fromisoformat(event['time'])
        time_str = event_time.strftime('%I:%M %p')
        date_str = event_time.strftime('%a, %b %d')  # e.g., "Mon, Nov 16"
        
        high_impact_embed.add_field(
            name=f"{date_str} • {time_str}",
            value=f"**{event['title']}**\n└ Previous: {event['previous']}",
            inline=False
        )

    # Create embed for other events
    other_embed = discord.Embed(
        title="🟡 Other Economic Releases",
        color=0xFFD700
    )

    # Format other events more compactly
    current_date = None
    current_text = ""
    
    for event in other_events:
        event_time = datetime.fromisoformat(event['time'])
        date_str = event_time.strftime('%a, %b %d')
        time_str = event_time.strftime('%I:%M %p')
        
        if date_str != current_date:
            if current_text:
                other_embed.add_field(name=current_date, value=current_text, inline=False)
                current_text = ""
            current_date = date_str
            
        current_text += f"`{time_str}` **{event['title']}** ({event['previous']})\n"
    
    if current_text:
        other_embed.add_field(name=current_date, value=current_text, inline=False)

    # Send embeds
    await ctx.send(embed=high_impact_embed)
    await ctx.send(embed=other_embed)

# Add a new command to get current value of an indicator
@bot.command(name='getdata')
async def get_current_data(ctx, series_id: str):
    """Get current value for an economic indicator
    
    Retrieves the latest value and information for a specific economic data series.
    
    Usage:
        ;getdata [series_id]
    
    Example:
        ;getdata VIXCLS
        ;getdata CPIAUCSL
    """
    try:
        # Get series info and data
        info = fred.get_series_info(series_id)
        series = fred.get_series(series_id, limit=1)
        
        embed = discord.Embed(
            title=f"📊 {info['title']}",
            color=0x00ff00
        )
        embed.add_field(name="Latest Value", value=f"{series.iloc[-1]:,.2f}")
        embed.add_field(name="Last Updated", value=series.index[-1].strftime('%Y-%m-%d'))
        embed.add_field(name="Units", value=info.get('units', 'N/A'))
        
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"Error fetching data: {str(e)}")

# Add a new command to search for series
@bot.command(name='search')
async def search_series(ctx, *search_terms):
    """Search for economic data series by keywords
    
    Searches FRED database for economic data series matching your keywords.
    Shows series ID, frequency, and units for each result.
    
    Usage:
        ;search [keywords]
    
    Example:
        ;search oil
        ;search treasury yield
        ;search gdp quarterly
    """
    try:
        search_text = ' '.join(search_terms)
        results = fred.search(search_text, limit=5)
        
        embed = discord.Embed(
            title=f"🔍 Search Results for '{search_text}'",
            color=0x00ff00
        )
        
        for idx, row in results.iterrows():
            # Format frequency to be more readable
            freq = row['frequency'].replace(', Ending Friday', '')
            freq = freq.replace(', Close', '')
            
            # Format title to be more concise
            title = row['title']
            if len(title) > 50:
                title = title[:47] + "..."
            
            # Format units more cleanly
            units = row['units']
            if 'Index' in units:
                if '=' in units:  # If it has a base year
                    base_year = units.split('=')[1].strip()
                    units = f"Index (Base: {base_year})"
                else:
                    units = "Index"
            elif 'Dollars per' in units:
                units = f"${units.replace('Dollars per', 'per')}"
            elif 'Billions of Dollars' in units:
                units = "$B"
            elif 'Millions of Dollars' in units:
                units = "$M"
            
            value_text = (
                f"**Series ID:** `{idx}`\n"
                f"**Frequency:** {freq}\n"
                f"**Units:** {units}"
            )
            
            embed.add_field(
                name=f"📊 {title}",
                value=value_text,
                inline=False
            )
        
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"Error searching: {str(e)}")

# Add a command to get correlation between two series
@bot.command(name='correlation')
async def get_correlation(ctx, series1: str, series2: str, days: int = 90):
    """Calculate correlation between two economic indicators
    
    Calculates the correlation coefficient between two data series over a specified time period.
    
    Usage:
        ;correlation [series1] [series2] [days]
    
    Arguments:
        series1: First series ID (e.g., VIXCLS)
        series2: Second series ID (e.g., DCOILWTICO)
        days: Number of days to analyze (default: 90)
    
    Example:
        ;correlation VIXCLS DCOILWTICO 30
    """
    try:
        # Get data for both series
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        data1 = fred.get_series(series1, observation_start=start_date)
        data2 = fred.get_series(series2, observation_start=start_date)
        
        # Calculate correlation
        correlation = data1.corr(data2)
        
        embed = discord.Embed(
            title=f"📊 Correlation Analysis ({days} days)",
            description=f"Correlation between {series1} and {series2}",
            color=0x00ff00
        )
        embed.add_field(name="Correlation Coefficient", value=f"{correlation:.2f}")
        
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"Error calculating correlation: {str(e)}")

bot.run(os.getenv('DISCORD_TOKEN'))