"""
Cog: Aternos — /startserver
Kết nối Aternos, khởi động server, theo dõi trạng thái và thông báo khi online.
"""

import asyncio
import logging
import os
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils import config, embeds

logger = logging.getLogger("bot.aternos")

# Khoảng thời gian poll trạng thái (giây)
POLL_INTERVAL = 15
# Timeout tối đa chờ server online (giây) — 10 phút
MAX_WAIT_TIME = 600


class AternosCog(commands.Cog, name="Aternos"):
    """Quản lý Aternos server."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._starting: bool = False   # lock để tránh double start

    # ── Helper: lấy Aternos client ────────────────────────────────────────────
    def _get_aternos_client(self):
        """
        Khởi tạo python-aternos client.
        Trả về (client, server) hoặc raise Exception.
        """
        try:
            from python_aternos import Client, AternosServer  # noqa: F401
        except ImportError:
            raise RuntimeError(
                "Thư viện python-aternos chưa được cài đặt. "
                "Chạy: pip install python-aternos"
            )

        username = os.getenv("ATERNOS_USERNAME") or config.get("aternos_username")
        password = os.getenv("ATERNOS_PASSWORD")
        server_name = os.getenv("ATERNOS_SERVER") or config.get("aternos_server_name")

        if not username or not password:
            raise ValueError(
                "Thiếu ATERNOS_USERNAME hoặc ATERNOS_PASSWORD trong .env"
            )

        from python_aternos import Client
        client = Client.from_credentials(username, password)
        servers = client.list_servers()

        if not servers:
            raise RuntimeError("Không tìm thấy server nào trong tài khoản Aternos.")

        # Chọn server theo tên hoặc lấy server đầu tiên
        server = None
        if server_name:
            for s in servers:
                if server_name.lower() in s.domain.lower():
                    server = s
                    break
        if server is None:
            server = servers[0]

        return client, server

    # ── /startserver ──────────────────────────────────────────────────────────
    @app_commands.command(
        name="startserver",
        description="🚀 Khởi động Minecraft server trên Aternos",
    )
    @app_commands.guild_only()
    async def startserver(self, interaction: discord.Interaction):
        if self._starting:
            await interaction.response.send_message(
                "⚠️ Server đang trong quá trình khởi động. Vui lòng chờ!",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)

        try:
            self._starting = True
            await self._start_and_monitor(interaction)
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

    async def _start_and_monitor(self, interaction: discord.Interaction):
        """Chạy trong background: start server rồi poll đến khi online."""
        loop = asyncio.get_event_loop()

        # ── Bước 1: Kết nối Aternos (blocking → thread pool) ──────────────
        try:
            client, server = await loop.run_in_executor(
                None, self._get_aternos_client
            )
        except Exception as e:
            embed = embeds.base_embed(
                title="❌ Không thể kết nối Aternos",
                description=str(e),
                color_key="error",
            )
            await interaction.followup.send(embed=embed)
            return

        server_domain = getattr(server, "domain", "unknown")
        logger.info(f"Đã kết nối Aternos — server: {server_domain}")

        # ── Bước 2: Kiểm tra trạng thái hiện tại ──────────────────────────
        current_status = await loop.run_in_executor(
            None, lambda: getattr(server, "status", "unknown")
        )
        logger.info(f"Trạng thái hiện tại: {current_status}")

        if str(current_status).lower() in ("online", "starting", "loading", "waiting"):
            embed = embeds.aternos_status_embed(str(current_status), server_domain)
            embed.description = (
                embed.description or ""
            ) + "\n\n_(Server đã đang chạy, không cần start lại)_"
            msg = await interaction.followup.send(embed=embed)
        else:
            # ── Bước 3: Gửi lệnh start ────────────────────────────────────
            try:
                await loop.run_in_executor(None, server.start)
                logger.info("Đã gửi lệnh start tới Aternos.")
            except Exception as e:
                embed = embeds.base_embed(
                    title="❌ Không thể gửi lệnh start",
                    description=str(e),
                    color_key="error",
                )
                await interaction.followup.send(embed=embed)
                return

            embed = embeds.aternos_status_embed("starting", server_domain)
            msg = await interaction.followup.send(embed=embed)

        # ── Bước 4: Poll trạng thái cho đến khi online ────────────────────
        elapsed = 0
        last_status = ""

        while elapsed < MAX_WAIT_TIME:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL

            try:
                # Refresh server object
                client2, server = await loop.run_in_executor(
                    None, self._get_aternos_client
                )
                raw_status = await loop.run_in_executor(
                    None, lambda: str(getattr(server, "status", "unknown")).lower()
                )
            except Exception as e:
                logger.warning(f"Poll error: {e}")
                continue

            if raw_status == last_status:
                continue  # không đổi → không update embed

            last_status = raw_status
            logger.info(f"Aternos status: {raw_status}")

            ip = config.get("minecraft_server_ip", server_domain)
            updated_embed = embeds.aternos_status_embed(raw_status, ip)

            try:
                await msg.edit(embed=updated_embed)
            except discord.HTTPException:
                pass

            if raw_status == "online":
                # Gửi thêm thông báo vào channel
                channel_id = config.get("discord_announce_channel_id", 0)
                if channel_id:
                    channel = self.bot.get_channel(int(channel_id))
                    if channel:
                        announce_embed = embeds.base_embed(
                            title="🟢 Server Minecraft đã ONLINE!",
                            description=(
                                f"✅ Kết nối ngay: **`{ip}`**\n\n"
                                "Gõ `/online` để xem ai đang chơi nhé!"
                            ),
                            color_key="online",
                        )
                        await channel.send(embed=announce_embed)
                return

            if raw_status in ("offline", "error", "stopping"):
                logger.warning(f"Server về trạng thái bất thường: {raw_status}")
                return

        # Timeout
        timeout_embed = embeds.base_embed(
            title="⏰ Hết thời gian chờ",
            description=(
                f"Server chưa online sau {MAX_WAIT_TIME // 60} phút. "
                "Vui lòng kiểm tra Aternos thủ công."
            ),
            color_key="warning",
        )
        try:
            await msg.edit(embed=timeout_embed)
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(AternosCog(bot))
