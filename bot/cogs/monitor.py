"""
Cog: Monitor — Auto detect server online/offline
Tự động poll Minecraft server, thông báo khi online/offline và ping mọi người.
"""

import asyncio
import logging
from datetime import datetime

import discord
from discord.ext import commands, tasks

from utils import config, embeds

logger = logging.getLogger("bot.monitor")


def _query_server(ip: str, port: int):
    from mcstatus import JavaServer
    if port == 25565:
        server = JavaServer.lookup(ip, timeout=8)
    else:
        server = JavaServer.lookup(f"{ip}:{port}", timeout=8)
    return server.status()


class MonitorCog(commands.Cog, name="Monitor"):
    """Auto monitor Minecraft server và thông báo Discord."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_state: str = "unknown"   # "online" | "offline" | "unknown"
        self._last_players: set[str] = set()
        self._monitor_task: tasks.Loop | None = None

    async def cog_load(self):
        self._start_monitor()

    def cog_unload(self):
        if self._monitor_task and self._monitor_task.is_running():
            self._monitor_task.cancel()

    def _start_monitor(self):
        if self._monitor_task and self._monitor_task.is_running():
            self._monitor_task.cancel()

        interval = int(config.get("monitor_interval", 30))

        @tasks.loop(seconds=interval)
        async def monitor_loop():
            await self._check_server()

        @monitor_loop.before_loop
        async def before():
            await self.bot.wait_until_ready()
            await asyncio.sleep(5)

        @monitor_loop.error
        async def on_error(error):
            logger.error(f"Monitor loop error: {error}", exc_info=True)

        self._monitor_task = monitor_loop
        monitor_loop.start()
        logger.info(f"Monitor loop started — interval {interval}s")

    async def _check_server(self):
        ip = config.get("minecraft_server_ip", "localhost")
        port = int(config.get("minecraft_server_port", 25565))

        loop = asyncio.get_event_loop()
        try:
            status = await loop.run_in_executor(None, _query_server, ip, port)
            current_state = "online"
            player_count = status.players.online
            player_list = [p.name for p in (status.players.sample or [])]
            latency = status.latency
        except Exception:
            current_state = "offline"
            player_count = 0
            player_list = []
            latency = None

        # ── Xử lý thay đổi trạng thái ────────────────────────────────────────
        if current_state == "online" and self._last_state != "online":
            logger.info(f"Server ONLINE — {player_count} người chơi")
            await self._notify_online(ip, port, player_count, player_list, latency)

        elif current_state == "offline" and self._last_state == "online":
            logger.info("Server OFFLINE")
            await self._notify_offline(ip)

        elif current_state == "online":
            # Server vẫn online — kiểm tra có người mới vào không
            current_set = set(player_list)
            new_players = current_set - self._last_players
            if new_players:
                logger.info(f"Người chơi mới: {new_players}")

        self._last_state = current_state
        self._last_players = set(player_list)

    async def _notify_online(
        self,
        ip: str,
        port: int,
        player_count: int,
        player_list: list[str],
        latency: float | None,
    ):
        """Gửi thông báo server online đến tất cả guild."""
        cfg = config.load_config()
        guilds_cfg = cfg.get("guilds", [])

        embed = embeds.base_embed(
            title="🟢 Server Minecraft đã ONLINE!",
            description=f"Kết nối ngay: **`{ip}`**",
            color_key="online",
        )
        embed.add_field(name="👥 Người chơi", value=f"`{player_count}`", inline=True)
        if latency:
            embed.add_field(name="📶 Ping", value=f"`{latency:.0f}ms`", inline=True)
        if player_list:
            embed.add_field(
                name="🎮 Đang chơi",
                value="\n".join(f"• `{p}`" for p in player_list),
                inline=False,
            )

        for g in guilds_cfg:
            channel_id = g.get("announce_channel_id", 0)
            if not channel_id:
                continue
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                continue

            ping_everyone = g.get("ping_everyone", False)
            role_id = g.get("minecraft_role_id", 0)

            if ping_everyone:
                content = "@everyone 🎮 Server Minecraft đã mở! Vào chơi đi anh em!"
            elif role_id:
                role = channel.guild.get_role(int(role_id))
                content = f"{role.mention} 🎮 Server Minecraft đã mở! Vào chơi đi anh em!" if role else ""
            else:
                content = "🎮 Server Minecraft đã mở! Vào chơi đi anh em!"

            try:
                await channel.send(content=content, embed=embed)
                logger.info(f"Đã gửi thông báo online → channel {channel_id}")
            except Exception as e:
                logger.error(f"Không gửi được thông báo online → {channel_id}: {e}")

    async def _notify_offline(self, ip: str):
        """Gửi thông báo server offline đến tất cả guild."""
        cfg = config.load_config()
        guilds_cfg = cfg.get("guilds", [])

        embed = embeds.base_embed(
            title="🔴 Server Minecraft đã OFFLINE",
            description=f"Server `{ip}` đã đóng.",
            color_key="offline",
        )

        for g in guilds_cfg:
            channel_id = g.get("announce_channel_id", 0)
            if not channel_id:
                continue
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                continue

            ping_everyone = g.get("ping_everyone", False)
            role_id = g.get("minecraft_role_id", 0)

            if ping_everyone:
                content = "@everyone 😴 Server Minecraft đã đóng rồi nhé!"
            elif role_id:
                role = channel.guild.get_role(int(role_id))
                content = f"{role.mention} 😴 Server Minecraft đã đóng rồi nhé!" if role else ""
            else:
                content = "😴 Server Minecraft đã đóng rồi nhé!"

            try:
                await channel.send(content=content, embed=embed)
                logger.info(f"Đã gửi thông báo offline → channel {channel_id}")
            except Exception as e:
                logger.error(f"Không gửi được thông báo offline → {channel_id}: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(MonitorCog(bot))
