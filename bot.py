import csv
import os
import re

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.environ["DISCORD_TOKEN"]
OUTPUT_FILE = "codes.csv"
FIELDS = ["code", "game", "channel", "author", "date", "link"]

# Any text channel whose name contains this is treated as a codes channel
# (e.g. "codes", "promo-codes", "codes-news", "redeem-codes").
CHANNEL_KEYWORD = os.getenv("CHANNEL_KEYWORD", "code").lower()

# Adjust to match your games' code format.
# Default: groups like ABCD-EFGH-IJKL, or a single 8-16 char uppercase/digit code.
CODE_PATTERN = re.compile(
    os.getenv(
        "CODE_REGEX",
        r"\b(?:[A-Z0-9]{4,6}(?:-[A-Z0-9]{4,6}){1,4}|[A-Z0-9]{8,16})\b",
    )
)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


def is_codes_channel(channel) -> bool:
    return isinstance(channel, discord.TextChannel) and CHANNEL_KEYWORD in channel.name.lower()


def find_codes(text: str) -> list[str]:
    # Require a digit so plain words like "ANNOUNCEMENT" don't match
    found = [c for c in CODE_PATTERN.findall(text) if any(ch.isdigit() for ch in c)]
    return list(dict.fromkeys(found))


def message_text(msg: discord.Message) -> str:
    parts = [msg.content]
    for e in msg.embeds:
        parts += [e.title or "", e.description or ""]
        parts += [f"{f.name} {f.value}" for f in e.fields]
    return " ".join(parts)


def load_seen() -> set[tuple[str, str]]:
    if not os.path.exists(OUTPUT_FILE):
        return set()
    with open(OUTPUT_FILE, newline="", encoding="utf-8") as f:
        return {(r["code"], r["game"]) for r in csv.DictReader(f)}


def save_rows(rows: list[dict]) -> None:
    new_file = not os.path.exists(OUTPUT_FILE)
    with open(OUTPUT_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def row_for(code: str, msg: discord.Message) -> dict:
    return {
        "code": code,
        "game": msg.guild.name,
        "channel": msg.channel.name,
        "author": str(msg.author),
        "date": msg.created_at.isoformat(),
        "link": msg.jump_url,
    }


async def scan_guild(guild: discord.Guild, limit: int, seen: set) -> dict[str, int]:
    """Scan every readable codes channel in a server. Returns {channel: new_code_count}."""
    results = {}
    for channel in guild.text_channels:
        if not is_codes_channel(channel):
            continue
        perms = channel.permissions_for(guild.me)
        if not (perms.view_channel and perms.read_message_history):
            continue
        rows = []
        async for msg in channel.history(limit=limit):
            if msg.author.bot and not msg.embeds:
                continue
            for code in find_codes(message_text(msg)):
                key = (code, guild.name)
                if key not in seen:
                    seen.add(key)
                    rows.append(row_for(code, msg))
        if rows:
            save_rows(rows)
        results[f"{guild.name} / #{channel.name}"] = len(rows)
    return results


def summarize(results: dict[str, int]) -> str:
    if not results:
        return "No channels with a matching name were found (or I can't read them)."
    lines = [f"{name}: {n} new" for name, n in results.items()]
    text = "\n".join(lines)
    return f"```\n{text[:1800]}\n```"


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} in {len(bot.guilds)} server(s)")


@bot.command()
@commands.has_permissions(manage_messages=True)
async def extract(ctx: commands.Context, limit: int = 500):
    """!extract [limit] - scan this server's codes channels."""
    results = await scan_guild(ctx.guild, limit, load_seen())
    await ctx.send(summarize(results))


@bot.command()
@commands.is_owner()
async def extractall(ctx: commands.Context, limit: int = 500):
    """!extractall [limit] - scan codes channels in every server the bot is in."""
    seen = load_seen()
    results = {}
    for guild in bot.guilds:
        results.update(await scan_guild(guild, limit, seen))
    await ctx.send(summarize(results))


@bot.event
async def on_message(message: discord.Message):
    # Live capture: any new message in a codes channel gets saved automatically
    if message.guild and is_codes_channel(message.channel) and (
        not message.author.bot or message.embeds
    ):
        seen = load_seen()
        rows = [
            row_for(c, message)
            for c in find_codes(message_text(message))
            if (c, message.guild.name) not in seen
        ]
        if rows:
            save_rows(rows)
    await bot.process_commands(message)


bot.run(TOKEN)
