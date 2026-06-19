"""
Cog: Aternos — /startserver
Điều khiển Aternos qua session cookie + aiohttp (không dùng python-aternos)
"""

import asyncio
import logging
import os
import aiohttp
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils import config, embeds

logger = logging.getLogger("bot.aternos")

POLL_INTERVAL = 15
MAX_WAIT_TIME = 600

# Aternos API endpoints
BASE_URL = "https://aternos.org"
API_URL  = "https://aternos.org/panel/ajax"


class AternosCog(commands.Cog, name="Aternos"):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._starting = False

    def _get_session_cookie(self) -> str:
        cookie = os.getenv("ATERNOS_SESSION")
        if not cookie:
            raise ValueError("Thiếu ATERNOS_SESSION trong biến môi trường!")
        return cookie

    def _get_headers(self, cookie: str) -> dict:
        return {
            "Cookie": f"ATERNOS_SESSION={cookie}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://aternos.org/server/",
        }

    async def _get_server_info(self, session: aiohttp.ClientSession, cookie: str) -> dict:
        """Lấy thông tin server hiện tại."""
        headers = self._get_headers(cookie)
        async with session.get(
            f"{API_URL}/status",
            headers=headers,
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Lỗi API Aternos: HTTP {resp.status}")
            data = await resp.json(content_type=None)
            return data

    async def _start_server(self, session: aiohttp.ClientSession, cookie: str) -> bool:
        """Gửi lệnh start server."""
        headers = self._get_headers(cookie)
        # Lấy ATERNOS_SERVER token từ trang
        async with session.get(
            f"{BASE_URL}/server/",
            headers=headers,
        ) as resp:
            text = await resp.text()
            # Tìm server token trong HTML
            server_token = None
            for line in text.split("\n"):
                if "window.headless" in line or "ATERNOS_SERVER" in line:
                    logger.debug(f"Found line: {line[:100]}")
                if 'let lastStatus' in line or '"server"' in line:
                    pass

        # Gửi lệnh start
        async with session.get(
            f"{API_URL}/start",
            headers=headers,
            params={"headless": "true"},
        ) as resp:
            data = await resp.json(content_type=None)
            logger.info(f"Start response: {data}")
            success = data.get("success", False)
            return success

    # ── /startserver ──────────────────────────────────────────────────────────
    @app_commands.command(
        name="startserver",
        description="🚀 Khởi động Minecraft server Aternos",
    )
    @app_commands.guild_only()
    async def startserver(self, interaction: discord.Interaction):
        if self._starting:
            await interaction.response.send_message(
                "⚠️ Server đang trong quá trình khởi động, vui lòng chờ!",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)

        try:
            self._starting = True
            cookie = self._get_session_cookie()
        except ValueError as e:
            embed = embeds.base_embed(
                title="❌ Lỗi cấu hình",
                description=str(e),
                color_key="error",
            )
            await interaction.followup.send(embed=embed)
            self._starting = False
            return

        try:
            await self._start_and_monitor(interaction, cookie)
        except Exception as e:
            logger.error(f"startserver error: {e}", exc_info=True)
            embed = embeds.base_embed(
                title="❌ Lỗi khởi động server",
                description=f"```{e}```",
                color_key="error",
            )
            try:
                await interaction.followup.send(embed=embed)
            except Exception:
                pass
        finally:
            self._starting = False

    async def _start_and_monitor(self, interaction: discord.Interaction, cookie: str):
        ip = config.get("minecraft_server_ip", "coctackeegg.aternos.me")

        async with aiohttp.ClientSession() as session:
            # Bước 1: Kiểm tra trạng thái hiện tại
            try:
                info = await self._get_server_info(session, cookie)
                current_status = info.get("class", info.get("status", "unknown"))
                logger.info(f"Trạng thái hiện tại: {current_status} | raw: {info}")
            except Exception as e:
                logger.warning(f"Không lấy được status: {e}")
                current_status = "unknown"

            if current_status in ("online",):
                embed = embeds.aternos_status_embed("online", ip)
                embed.description = f"✅ Server đã online rồi! Kết nối: **`{ip}`**"
                await interaction.followup.send(embed=embed)
                return

            # Bước 2: Start server
            if current_status not in ("starting", "loading", "waiting", "preparing"):
                try:
                    success = await self._start_server(session, cookie)
                    if not success:
                        raise RuntimeError("Aternos từ chối lệnh start")
                    logger.info("Đã gửi lệnh start thành công")
                except Exception as e:
                    embed = embeds.base_embed(
                        title="❌ Không thể start server",
                        description=(
                            f"```{e}```\n\n"
                            "**Thử thủ công:**\n"
                            f"Vào [aternos.org/server/](https://aternos.org/server/) và bấm START"
                        ),
                        color_key="error",
                    )
                    await interaction.followup.send(embed=embed)
                    return

            embed = embeds.aternos_status_embed("starting", ip)
            msg = await interaction.followup.send(embed=embed)

            # Bước 3: Poll trạng thái
            elapsed = 0
            last_status = ""

            while elapsed < MAX_WAIT_TIME:
                await asyncio.sleep(POLL_INTERVAL)
                elapsed += POLL_INTERVAL

                try:
                    info = await self._get_server_info(session, cookie)
                    raw_status = info.get("class", info.get("status", "unknown")).lower()
                except Exception as e:
                    logger.warning(f"Poll error: {e}")
                    continue

                if raw_status == last_status:
                    continue

                last_status = raw_status
                logger.info(f"Aternos status: {raw_status}")

                updated_embed = embeds.aternos_status_embed(raw_status, ip)
                try:
                    await msg.edit(embed=updated_embed)
                except discord.HTTPException:
                    pass

                if raw_status == "online":
                    channel_id = config.get("discord_announce_channel_id", 0)
                    if channel_id:
                        channel = self.bot.get_channel(int(channel_id))
                        if channel:
                            announce = embeds.base_embed(
                                title="🟢 Server Minecraft đã ONLINE!",
                                description=f"✅ Kết nối: **`{ip}`**\nGõ `/online` để xem ai đang chơi!",
                                color_key="online",
                            )
                            await channel.send(embed=announce)
                    return

                if raw_status in ("offline", "error", "stopping"):
                    return

            # Timeout
            timeout_embed = embeds.base_embed(
                title="⏰ Hết thời gian chờ",
                description=f"Server chưa online sau {MAX_WAIT_TIME // 60} phút. Kiểm tra Aternos thủ công.",
                color_key="warning",
            )
            try:
                await msg.edit(embed=timeout_embed)
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(AternosCog(bot))
