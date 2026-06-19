"""
Cog: Reminder — Auto reminder hàng ngày
Kiểm tra số người online, tag role nếu ít hơn ngưỡng cấu hình.
"""

import asyncio
import logging
from datetime import datetime, time, timezone, timedelta
from typing import Optional

import discord
from discord.ext import commands, tasks

from utils import config, embeds

logger = logging.getLogger("bot.reminder")


def _parse_time(time_str: str) -> time:
    """Parse "HH:MM" thành datetime.time (local)."""
    try:
        h, m = map(int, time_str.strip().split(":"))
        return time(hour=h, minute=m)
    except Exception:
        logger.warning(f"Không parse được reminder_time '{time_str}', dùng 19:00")
        return time(hour=19, minute=0)


def _query_server(ip: str, port: int):
    from mcstatus import JavaServer
    server = JavaServer(ip, port, timeout=5)
    return server.status()


class ReminderCog(commands.Cog, name="Reminder"):
    """Auto reminder gửi lời mời vào Minecraft mỗi ngày."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._task_started = False
        self._daily_task: Optional[tasks.Loop] = None
        self._last_triggered_date: Optional[str] = None

    async def cog_load(self):
        """Khởi động task khi cog được load."""
        self._schedule_task()

    def cog_unload(self):
        """Dừng task khi cog unload."""
        if self._daily_task and self._daily_task.is_running():
            self._daily_task.cancel()

    def _schedule_task(self):
        """Tạo và start background loop."""
        if self._daily_task and self._daily_task.is_running():
            self._daily_task.cancel()

        # Đọc thời gian từ config
        time_str = config.get("reminder_time", "19:00")
        reminder_time = _parse_time(time_str)
        logger.info(f"Reminder được lên lịch lúc {reminder_time.strftime('%H:%M')} mỗi ngày.")

        @tasks.loop(hours=24)
        async def daily_reminder():
            await self._send_reminder()

        @daily_reminder.before_loop
        async def before_reminder():
            await self.bot.wait_until_ready()
            # Tính thời gian chờ đến lần chạy đầu tiên
            now = datetime.now()
            target = now.replace(
                hour=reminder_time.hour,
                minute=reminder_time.minute,
                second=0,
                microsecond=0,
            )
            if target <= now:
                # Đã qua giờ hôm nay → chờ đến ngày mai
                target += timedelta(days=1)
            wait_seconds = (target - now).total_seconds()
            logger.info(
                f"Reminder sẽ chạy lần đầu sau {wait_seconds / 60:.1f} phút "
                f"(lúc {target.strftime('%H:%M %d/%m/%Y')})"
            )
            await asyncio.sleep(wait_seconds)

        self._daily_task = daily_reminder
        daily_reminder.start()

    # ── Logic gửi reminder ────────────────────────────────────────────────────
    async def _send_reminder(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self._last_triggered_date == today:
            return  # đã gửi hôm nay rồi
        self._last_triggered_date = today

        cfg = config.load_config()
        channel_id = cfg.get("discord_announce_channel_id", 0)
        role_id = cfg.get("discord_minecraft_role_id", 0)
        min_players = int(cfg.get("reminder_min_players", 2))
        ip = cfg.get("minecraft_server_ip", "localhost")
        port = int(cfg.get("minecraft_server_port", 25565))

        if not channel_id or not role_id:
            logger.warning(
                "Reminder: chưa cấu hình discord_announce_channel_id hoặc "
                "discord_minecraft_role_id trong config.json"
            )
            return

        channel = self.bot.get_channel(int(channel_id))
        if not channel:
            logger.warning(f"Reminder: không tìm thấy channel ID {channel_id}")
            return

        # Kiểm tra số người online
        loop = asyncio.get_event_loop()
        try:
            status = await loop.run_in_executor(None, _query_server, ip, port)
            player_count = status.players.online
            player_list = [p.name for p in (status.players.sample or [])]
            server_online = True
        except Exception as e:
            logger.warning(f"Reminder: không query được server — {e}")
            player_count = 0
            player_list = []
            server_online = False

        logger.info(
            f"Reminder check: server_online={server_online}, "
            f"players={player_count}, min={min_players}"
        )

        if player_count >= min_players:
            logger.info("Reminder: đủ người rồi, không gửi.")
            return

        # Lấy guild từ channel
        guild = channel.guild
        role = guild.get_role(int(role_id))
        if not role:
            logger.warning(f"Reminder: không tìm thấy role ID {role_id}")
            return

        # Tạo embed
        time_str = cfg.get("reminder_time", "19:00")
        embed = embeds.base_embed(
            title="⏰ Nhắc nhở Minecraft hàng ngày",
            color_key="info" if not server_online else "warning",
        )

        if server_online:
            embed.description = (
                f"🎮 Server đang online nhưng mới có **{player_count}** người chơi!\n"
                f"Kết nối: **`{ip}:{port}`**"
            )
            if player_list:
                embed.add_field(
                    name="✅ Đang chơi",
                    value="\n".join(f"• `{p}`" for p in player_list),
                    inline=False,
                )
        else:
            embed.description = (
                f"🌙 Đã {time_str} rồi mà chưa ai vào Minecraft!\n"
                "Dùng `/startserver` để khởi động server nhé."
            )

        embed.add_field(
            name="📢 Được nhắc nhở",
            value=role.mention,
            inline=False,
        )

        # Gửi mention + embed
        await channel.send(
            content=f"Hey {role.mention}! Vào chơi Minecraft đi anh em! 🎮",
            embed=embed,
        )
        logger.info(f"Đã gửi reminder vào channel {channel.name}")

    # ── Reload task khi config thay đổi ──────────────────────────────────────
    @commands.command(name="reload_reminder", hidden=True)
    @commands.is_owner()
    async def reload_reminder(self, ctx):
        """Owner: reload lại reminder task (khi đổi giờ trong config)."""
        self._schedule_task()
        await ctx.send("✅ Đã reload reminder task.")


async def setup(bot: commands.Bot):
    await bot.add_cog(ReminderCog(bot))
