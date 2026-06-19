"""
Discord Bot - Minecraft Server Manager
Entry point chính của bot
"""

import discord
from discord.ext import commands
import asyncio
import logging
import os
import sys
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
load_dotenv()

# ── Logging setup ──────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("bot")

# ── Bot setup ──────────────────────────────────────────────────────────────────
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")

if not DISCORD_TOKEN:
    logger.critical("DISCORD_TOKEN không được tìm thấy trong .env!")
    sys.exit(1)


class MinecraftBot(commands.Bot):
    """Custom Bot class với auto-reconnect và cog loading."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True          # Cần để lấy danh sách member
        intents.message_content = True

        super().__init__(
            command_prefix="!",         # prefix fallback (không dùng chính)
            intents=intents,
            help_command=None,
        )

    async def setup_hook(self):
        """Chạy khi bot khởi động - load tất cả cogs."""
        cogs = [
            "cogs.status",
            "cogs.reminder",
            "cogs.monitor",
        ]
        for cog in cogs:
            try:
                await self.load_extension(cog)
                logger.info(f"✅ Loaded cog: {cog}")
            except Exception as e:
                logger.error(f"❌ Không thể load cog {cog}: {e}", exc_info=True)

        # Sync slash commands cho tất cả guild trong GUILD_IDS
        guild_ids_env = os.getenv("GUILD_IDS", os.getenv("GUILD_ID", ""))
        guild_ids = [gid.strip() for gid in guild_ids_env.split(",") if gid.strip()]

        if guild_ids:
            for gid in guild_ids:
                guild_obj = discord.Object(id=int(gid))
                self.tree.copy_global_to(guild=guild_obj)
                synced = await self.tree.sync(guild=guild_obj)
                logger.info(f"🔄 Synced {len(synced)} slash commands (guild {gid})")
        else:
            synced = await self.tree.sync()
            logger.info(f"🔄 Synced {len(synced)} slash commands (global)")

    async def on_ready(self):
        logger.info(f"🤖 Bot đã sẵn sàng: {self.user} (ID: {self.user.id})")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Minecraft Server 🎮",
            )
        )

    async def on_disconnect(self):
        logger.warning("⚠️  Bot bị ngắt kết nối. Đang thử kết nối lại...")

    async def on_resumed(self):
        logger.info("✅ Bot đã kết nối lại thành công.")

    async def on_error(self, event: str, *args, **kwargs):
        logger.error(f"Lỗi trong event {event}", exc_info=True)

    async def on_command_error(self, ctx, error):
        logger.error(f"Command error: {error}", exc_info=True)


# ── Main runner với reconnect logic ───────────────────────────────────────────
async def main():
    reconnect_delay = 5  # giây

    while True:
        bot = MinecraftBot()  # tạo bot mới mỗi lần reconnect
        try:
            logger.info("🚀 Đang khởi động bot...")
            async with bot:
                await bot.start(DISCORD_TOKEN)
        except discord.LoginFailure:
            logger.critical("❌ Token không hợp lệ. Dừng bot.")
            break
        except discord.HTTPException as e:
            logger.error(f"HTTP error: {e}. Thử lại sau {reconnect_delay}s...")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60)
        except KeyboardInterrupt:
            logger.info("🛑 Bot dừng theo yêu cầu người dùng.")
            break
        except Exception as e:
            logger.error(f"Lỗi không xác định: {e}. Thử lại sau {reconnect_delay}s...", exc_info=True)
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60)


if __name__ == "__main__":
    asyncio.run(main())
