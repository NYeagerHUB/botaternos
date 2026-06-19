"""
Cog: Status — /status, /online, /ruchoi
Kiểm tra trạng thái server Minecraft và danh sách người chơi.
"""

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils import config, embeds

logger = logging.getLogger("bot.status")


def _query_server(ip: str, port: int):
    """
    Blocking call — chạy trong executor.
    Dùng JavaServer.lookup() để tự resolve SRV record của Aternos
    (port Aternos thay đổi mỗi lần, SRV record luôn đúng).
    """
    from mcstatus import JavaServer
    # Nếu port là 25565 (default) thì dùng SRV lookup
    # Nếu có port cụ thể thì dùng luôn
    if port == 25565:
        server = JavaServer.lookup(ip, timeout=8)
    else:
        server = JavaServer.lookup(f"{ip}:{port}", timeout=8)
    return server.status()


class StatusCog(commands.Cog, name="Status"):
    """Lệnh kiểm tra trạng thái server Minecraft."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _fetch_status(self):
        import asyncio
        ip = config.get("minecraft_server_ip", "localhost")
        port = int(config.get("minecraft_server_port", 25565))

        loop = asyncio.get_event_loop()
        try:
            status = await loop.run_in_executor(None, _query_server, ip, port)
            players_sample = status.players.sample or []
            player_names = [p.name for p in players_sample]

            return {
                "online": True,
                "ip": ip,
                "port": port,
                "player_count": status.players.online,
                "max_players": status.players.max,
                "player_list": player_names,
                "latency": status.latency,
                "motd": str(status.motd).strip() if status.motd else "",
            }
        except Exception as e:
            logger.warning(f"Không thể kết nối server {ip}:{port} — {e}")
            return {
                "online": False,
                "ip": ip,
                "port": port,
                "player_count": 0,
                "max_players": 0,
                "player_list": [],
                "latency": None,
                "motd": "",
            }

    # ── /status ───────────────────────────────────────────────────────────────
    @app_commands.command(
        name="status",
        description="📊 Xem trạng thái server Minecraft",
    )
    @app_commands.guild_only()
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        info = await self._fetch_status()
        embed = embeds.server_status_embed(
            ip=info["ip"],
            port=info["port"],
            online=info["online"],
            player_count=info["player_count"],
            max_players=info["max_players"],
            player_list=info["player_list"],
            latency=info["latency"],
            motd=info["motd"],
        )
        await interaction.followup.send(embed=embed)

    # ── /online ───────────────────────────────────────────────────────────────
    @app_commands.command(
        name="online",
        description="🎮 Xem danh sách người đang chơi Minecraft",
    )
    @app_commands.guild_only()
    async def online(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        info = await self._fetch_status()

        if not info["online"]:
            embed = embeds.base_embed(
                title="🔴 Server đang offline",
                description="Không thể lấy danh sách người chơi.",
                color_key="offline",
            )
            await interaction.followup.send(embed=embed)
            return

        ip = info["ip"]
        port = info["port"]
        players = info["player_list"]

        embed = embeds.base_embed(
            title="🎮 Danh sách người chơi Minecraft",
            color_key="online" if players else "info",
        )
        embed.add_field(name="🌐 Server", value=f"`{ip}`", inline=True)
        embed.add_field(name="👥 Số người", value=f"`{info['player_count']}/{info['max_players']}`", inline=True)
        embed.add_field(
            name="📶 Ping",
            value=f"`{info['latency']:.1f} ms`" if info["latency"] else "`N/A`",
            inline=True,
        )

        if players:
            embed.add_field(
                name=f"🟢 Đang online ({len(players)})",
                value="\n".join(f"• `{p}`" for p in players),
                inline=False,
            )
        else:
            embed.add_field(
                name="🟡 Đang online",
                value="_Server trống, không có ai đang chơi_",
                inline=False,
            )

        await interaction.followup.send(embed=embed)

    # ── /ruchoi ───────────────────────────────────────────────────────────────
    @app_commands.command(
        name="ruchoi",
        description="📢 Tag những người chưa vào Minecraft",
    )
    @app_commands.guild_only()
    async def ruchoi(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        role_id = config.get("discord_minecraft_role_id", 0)
        if not role_id:
            await interaction.followup.send(
                "⚠️ Chưa cấu hình `discord_minecraft_role_id` trong config.json!",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        role = guild.get_role(int(role_id))
        if not role:
            await interaction.followup.send(
                f"⚠️ Không tìm thấy role ID `{role_id}`.",
                ephemeral=True,
            )
            return

        role_members = [m for m in role.members if not m.bot]
        if not role_members:
            await interaction.followup.send(
                f"⚠️ Role **{role.name}** không có thành viên nào.",
                ephemeral=True,
            )
            return

        info = await self._fetch_status()
        mc_players_lower = [p.lower() for p in info["player_list"]]

        def is_playing(member: discord.Member) -> bool:
            return any(
                n in mc_players_lower
                for n in [member.display_name.lower(), member.name.lower()]
            )

        not_playing = [m for m in role_members if not is_playing(m)]

        embed = embeds.ruchoi_embed(
            online_players=info["player_list"],
            members_not_in=not_playing,
        )

        mention_str = None
        if not_playing:
            mention_str = (
                " ".join(m.mention for m in not_playing)
                + "\n**Vào chơi Minecraft đi anh em!** 🎮"
            )

        await interaction.followup.send(
            content=mention_str,
            embed=embed,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(StatusCog(bot))
