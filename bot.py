import os
import sqlite3
from datetime import datetime
import pytz
import discord
from discord import app_commands
from discord.ext import commands, tasks

# --- CONFIGURATION ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
MASTER_PASSWORD = os.getenv("MASTER_PASSWORD", "Pubstomped")

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

def get_db():
    return sqlite3.connect("data.db")

# --- BOT SETUP ---
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# Active session authentication storage
authenticated_users = set()

# Helper to format status display
STATUS_CONFIG = {
    "online": {
        "text": "Online: Undetected ✅",
        "color": discord.Color.green(),
        "desc": "The tool is safe and operational."
    },
    "offline": {
        "text": "Offline: Maintenance 🔧",
        "color": discord.Color.orange(),
        "desc": "The tool is currently undergoing scheduled maintenance."
    },
    "detected": {
        "text": "Detected: Updating 🚫",
        "color": discord.Color.red(),
        "desc": "The tool is unsafe/detected. Updates are in progress."
    }
}

# --- HELPER FUNCTIONS ---
def check_auth(interaction: discord.Interaction) -> bool:
    return interaction.user.id in authenticated_users

def get_config_val(key: str) -> str:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def set_config_val(key: str, value: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def create_status_embed(status_key: str):
    info = STATUS_CONFIG.get(status_key, STATUS_CONFIG["online"])
    embed = discord.Embed(
        title="🛠️ Tool Status Update",
        color=info["color"],
        timestamp=datetime.now(pytz.utc)
    )
    embed.add_field(name="Current Status", value=f"### {info['text']}", inline=False)
    embed.add_field(name="Details", value=info["desc"], inline=False)
    embed.set_footer(
        text="PubsTracker - Real-Time Status Manager",
        icon_url="https://cdn-icons-png.flaticon.com/512/1063/1063376.png"
    )
    return embed

# --- COMMANDS ---

@bot.tree.command(name="master_auth", description="Authenticate to manage tool status and announcements.")
@app_commands.describe(password="Master password")
async def master_auth(interaction: discord.Interaction, password: str):
    if password == MASTER_PASSWORD:
        authenticated_users.add(interaction.user.id)
        await interaction.response.send_message("✅ Authenticated successfully! You have administrative access.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Incorrect password. Access denied.", ephemeral=True)

@bot.tree.command(name="set_channel", description="Set the Discord channel for status updates and announcements.")
@app_commands.describe(target_channel="Discord Text Channel")
async def set_channel(interaction: discord.Interaction, target_channel: discord.TextChannel):
    if not check_auth(interaction):
        return await interaction.response.send_message("🔒 Unauthorized! Run `/master_auth` first.", ephemeral=True)

    set_config_val("announcement_channel", str(target_channel.id))
    await interaction.response.send_message(f"📢 Target channel set to {target_channel.mention}.", ephemeral=True)

@bot.tree.command(name="status", description="Update tool status and send update immediately.")
@app_commands.describe(status="Select the current tool status")
@app_commands.choices(status=[
    app_commands.Choice(name="Online: Undetected ✅", value="online"),
    app_commands.Choice(name="Offline: Maintenance 🔧", value="offline"),
    app_commands.Choice(name="Detected: Updating 🚫", value="detected")
])
async def status(interaction: discord.Interaction, status: app_commands.Choice[str]):
    if not check_auth(interaction):
        return await interaction.response.send_message("🔒 Unauthorized! Run `/master_auth` first.", ephemeral=True)

    # Save active status to DB
    set_config_val("current_status", status.value)
    
    channel_id = get_config_val("announcement_channel")
    if not channel_id:
        return await interaction.response.send_message("⚠️ Target channel not set. Run `/set_channel` first.", ephemeral=True)

    channel = bot.get_channel(int(channel_id))
    if not channel:
        return await interaction.response.send_message("❌ Configured channel could not be found.", ephemeral=True)

    embed = create_status_embed(status.value)
    await channel.send(embed=embed)
    await interaction.response.send_message(f"✅ Status updated to **{status.name}** and posted to {channel.mention}.", ephemeral=True)

@bot.tree.command(name="announcement", description="Post a custom announcement immediately.")
@app_commands.describe(message="Announcement text")
async def announcement(interaction: discord.Interaction, message: str):
    if not check_auth(interaction):
        return await interaction.response.send_message("🔒 Unauthorized! Run `/master_auth` first.", ephemeral=True)

    channel_id = get_config_val("announcement_channel")
    if not channel_id:
        return await interaction.response.send_message("⚠️ Target channel not set. Run `/set_channel` first.", ephemeral=True)

    channel = bot.get_channel(int(channel_id))
    if not channel:
        return await interaction.response.send_message("❌ Configured channel could not be found.", ephemeral=True)

    embed = discord.Embed(
        title="📢 Tool Announcement",
        description=message,
        color=discord.Color.blue(),
        timestamp=datetime.now(pytz.utc)
    )
    embed.set_footer(
        text="PubsTracker - Official Update",
        icon_url="https://cdn-icons-png.flaticon.com/512/1063/1063376.png"
    )

    await channel.send(embed=embed)
    await interaction.response.send_message(f"✅ Announcement posted successfully to {channel.mention}.", ephemeral=True)

# --- DAILY midnight UK UPDATE TASK ---
@tasks.loop(minutes=1)
async def daily_status_task():
    uk_tz = pytz.timezone("Europe/London")
    now_uk = datetime.now(uk_tz)

    # Check if current time in UK is 00:00 (Midnight)
    if now_uk.hour == 0 and now_uk.minute == 0:
        channel_id = get_config_val("announcement_channel")
        status_key = get_config_val("current_status") or "online"

        if channel_id:
            channel = bot.get_channel(int(channel_id))
            if channel:
                embed = create_status_embed(status_key)
                await channel.send(content="⏰ **Daily Midnight Tool Status Check**", embed=embed)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    await bot.tree.sync()
    if not daily_status_task.is_running():
        daily_status_task.start()

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
