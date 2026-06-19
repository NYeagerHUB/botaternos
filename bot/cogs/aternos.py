"""
Cog: Aternos — /startserver
Điều khiển Aternos qua session cookie + aiohttp
"""

import asyncio
import logging
import os
import aiohttp
from yarl import URL

import discord
from discord import app_commands
from discord.ext import commands

from utils import config, embeds

logger = logging.getLogger("bot.aternos")

POLL_INTERVAL = 15
MAX_WAIT_TIME = 600

ATERNOS_ORIGIN = "https://aternos.org"


def _make_session(cookie: str) -> aiohttp.ClientSession:
    """Tạo aiohttp session với cookie Aternos."""
    # Dùng CookieJar unsafe để tránh lỗi header injection
    jar = aiohttp.CookieJar(unsafe=True)
    jar.update_cookies(
        {"ATERNOS_SESSION": cookie.strip()},
        URL(ATERNOS_ORIGIN),
    )
    return aiohttp.ClientSession(
        cookie_jar=jar,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{ATERNOS_ORIGIN}/server/",
        },
    )


class AternosCog(commands.Cog, name="Aternos"):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._starting = False

    def _get_session_cookie(self) -> str:
        cookie = os.getenv("ATERNOS_SESSION", "").strip()
        if not cookie:
            raise ValueError("Thiếu ATERNOS_SESSION trong biến môi trường!")
        return cookie

    async def _get_status(self, session: aiohttp.ClientSession) -> dict:
        async with session.get(f"{ATERNOS_ORIGIN}/panel/ajax/status") as resp:
            if resp.status == 403:
                raise RuntimeError("Session cookie hết hạn hoặc không hợp lệ (403)")
            data = await resp.json(content_type=None)
            return data

    async def _do_start(self, session: aiohttp.ClientSession) -> None:
        async with session.get(f"{ATERNOS_ORIGIN}/panel/ajax/start") as resp:
            data = await resp.json(content_type=None)
            logger.info(f"Start response: {data}")
            if not data.get("success", False):
                error = data.get("error", "unknown")
                raise RuntimeError(f"Aternos từ chối: {error}")

    # ── /startserver ──────────────────────────────────────────────────────────
    @app_commands.command(
        name="startserver",
        description="🚀 Khởi động Minecraft server Aternos",
    )
    @app_commands.guild_only()
    async def startserver(self, interaction: discord.Interaction):
        if self._starting:
            await interaction.response.send_message(
                "⚠️ Server đang khởi động, vui lòng chờ!",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)
        self._starting = True

        try:
            cookie = self._get_session_cookie()
        except ValueError as e:
            await interaction.followup.send(embed=embeds.base_embed(
                title="❌ Lỗi cấu hình",
                description=str(e),
                color_key="error",
            ))
            self._starting = False
            return

        try:
            await self._start_and_monitor(interaction, cookie)
        except Exception as e:
            logger.error(f"startserver error: {e}", exc_info=True)
            try:
                await interaction.followup.send(embed=embeds.base_embed(
                    title="❌ Lỗi khởi động server",
                    description=f"```{e}```",
                    color_key="error",
                ))
            except Exception:
                pass
        finally:
            self._starting = False

    async def _start_and_monitor(self, interaction: discord.Interaction, cookie: str):
        ip = config.get("minecraft_server_ip", "coctackeegg.aternos.me")

        async with _make_session(cookie) as session:
            # Bước 1: Kiểm tra trạng thái
            try:
                info = await self._get_status(session)
                current_status = str(info.get("class", info.get("status", "offline"))).lower()
                logger.info(f"Trạng thái: {current_status} | raw: {info}")
            except Exception as e:
                logger.warning(f"Không lấy được status: {e}")
                current_status = "offline"

            if current_status == "online":
                embed = embeds.aternos_status_embed("online", ip)
                embed.description = f"✅ Server đã online! Kết nối: **`{ip}`**"
                await interaction.followup.send(embed=embed)
                return

            # Bước 2: Gửi lệnh start nếu chưa khởi động
            if current_status not in ("starting", "loading", "waiting", "preparing"):
                try:
                    await self._do_start(session)
                    logger.info("Đã gửi lệnh start")
                except Exception as e:
                    await interaction.followup.send(embed=embeds.base_embed(
                        title="❌ Không thể start server",
                        description=(
                            f"```{e}```\n\n"
                            "Thử thủ công: [aternos.org/server/](https://aternos.org/server/)"
                        ),
                        color_key="error",
                    ))
                    return

            msg = await interaction.followup.send(
                embed=embeds.aternos_status_embed("starting", ip)
            )

            # Bước 3: Poll cho đến khi online
            elapsed = 0
            last_status = ""

            while elapsed < MAX_WAIT_TIME:
                await asyncio.sleep(POLL_INTERVAL)
                elapsed += POLL_INTERVAL

                try:
                    info = await self._get_status(session)
                    raw_status = str(info.get("class", info.get("status", "unknown"))).lower()
                except Exception as e:
                    logger.warning(f"Poll error: {e}")
                    continue

                if raw_status == last_status:
                    continue
                last_status = raw_status
                logger.info(f"Poll status: {raw_status}")

                try:
                    await msg.edit(embed=embeds.aternos_status_embed(raw_status, ip))
                except discord.HTTPException:
                    pass

                if raw_status == "online":
                    channel_id = config.get("discord_announce_channel_id", 0)
                    if channel_id:
                        ch = self.bot.get_channel(int(channel_id))
                        if ch:
                            await ch.send(embed=embeds.base_embed(
                                title="🟢 Server Minecraft ONLINE!",
                                description=f"Kết nối: **`{ip}`** — Gõ `/online` để xem ai đang chơi!",
                                color_key="online",
                            ))
                    return

                if raw_status in ("offline", "error", "stopping"):
                    return

            # Timeout
            try:
                await msg.edit(embed=embeds.base_embed(
                    title="⏰ Hết thời gian chờ",
                    description=f"Server chưa online sau {MAX_WAIT_TIME // 60} phút.",
                    color_key="warning",
                ))
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(AternosCog(bot))
