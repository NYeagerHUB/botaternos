"""
Cog: Music — Nghe nhạc từ YouTube
/play /skip /stop /queue /pause /resume /nowplaying
"""

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("bot.music")

# ── YT-DLP options ────────────────────────────────────────────────────────────
YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "cookiefile": None,
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn -filter:a 'volume=0.5'",
}


@dataclass
class Track:
    title: str
    url: str          # stream URL
    webpage_url: str  # YouTube link
    duration: int     # giây
    thumbnail: str
    requester: discord.Member


def _format_duration(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


async def _fetch_track(query: str, requester: discord.Member) -> Optional[Track]:
    """Tìm kiếm và lấy thông tin bài hát từ YouTube."""
    import yt_dlp

    loop = asyncio.get_event_loop()

    def _search():
        with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
            # Nếu là URL thì dùng thẳng, không thì search
            if query.startswith("http"):
                info = ydl.extract_info(query, download=False)
            else:
                info = ydl.extract_info(f"ytsearch:{query}", download=False)
                if "entries" in info:
                    info = info["entries"][0]
            return info

    try:
        info = await loop.run_in_executor(None, _search)
        return Track(
            title=info.get("title", "Unknown"),
            url=info["url"],
            webpage_url=info.get("webpage_url", query),
            duration=info.get("duration", 0),
            thumbnail=info.get("thumbnail", ""),
            requester=requester,
        )
    except Exception as e:
        logger.error(f"yt-dlp error: {e}")
        return None


class GuildPlayer:
    """Quản lý nhạc cho từng guild."""

    def __init__(self):
        self.queue: deque[Track] = deque()
        self.current: Optional[Track] = None
        self.voice_client: Optional[discord.VoiceClient] = None
        self.text_channel: Optional[discord.TextChannel] = None
        self._volume: float = 0.5

    def is_playing(self) -> bool:
        return self.voice_client is not None and self.voice_client.is_playing()

    def is_paused(self) -> bool:
        return self.voice_client is not None and self.voice_client.is_paused()


class MusicCog(commands.Cog, name="Music"):
    """Bot nhạc YouTube."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._players: dict[int, GuildPlayer] = {}

    def _get_player(self, guild_id: int) -> GuildPlayer:
        if guild_id not in self._players:
            self._players[guild_id] = GuildPlayer()
        return self._players[guild_id]

    async def _play_next(self, guild_id: int):
        player = self._get_player(guild_id)
        if not player.queue:
            player.current = None
            if player.text_channel:
                await player.text_channel.send(
                    embed=discord.Embed(
                        description="✅ Hết hàng chờ. Bot rời kênh sau 30 giây.",
                        color=0x3498DB,
                    )
                )
            await asyncio.sleep(30)
            if player.voice_client and not player.is_playing():
                await player.voice_client.disconnect()
                self._players.pop(guild_id, None)
            return

        track = player.queue.popleft()
        player.current = track

        source = discord.FFmpegPCMAudio(track.url, **FFMPEG_OPTIONS)
        source = discord.PCMVolumeTransformer(source, volume=player._volume)

        def after_play(error):
            if error:
                logger.error(f"Lỗi phát nhạc: {error}")
            asyncio.run_coroutine_threadsafe(
                self._play_next(guild_id), self.bot.loop
            )

        player.voice_client.play(source, after=after_play)

        if player.text_channel:
            embed = self._now_playing_embed(track)
            await player.text_channel.send(embed=embed)

    def _now_playing_embed(self, track: Track) -> discord.Embed:
        embed = discord.Embed(
            title="🎵 Đang phát",
            description=f"**[{track.title}]({track.webpage_url})**",
            color=0x1DB954,
        )
        embed.add_field(name="⏱ Thời lượng", value=_format_duration(track.duration), inline=True)
        embed.add_field(name="👤 Yêu cầu bởi", value=track.requester.mention, inline=True)
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        return embed

    # ── /play ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="play", description="🎵 Phát nhạc từ YouTube")
    @app_commands.describe(query="Tên bài hát hoặc link YouTube")
    @app_commands.guild_only()
    async def play(self, interaction: discord.Interaction, query: str):
        # Kiểm tra người dùng có trong voice channel không
        if not interaction.user.voice:
            await interaction.response.send_message(
                "⚠️ Bạn cần vào kênh voice trước!", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)

        player = self._get_player(interaction.guild_id)
        player.text_channel = interaction.channel

        # Kết nối voice nếu chưa
        if not player.voice_client or not player.voice_client.is_connected():
            try:
                player.voice_client = await interaction.user.voice.channel.connect()
            except Exception as e:
                await interaction.followup.send(f"❌ Không thể vào kênh voice: {e}")
                return
        elif player.voice_client.channel != interaction.user.voice.channel:
            await player.voice_client.move_to(interaction.user.voice.channel)

        # Tìm bài hát
        track = await _fetch_track(query, interaction.user)
        if not track:
            await interaction.followup.send(
                embed=discord.Embed(
                    description=f"❌ Không tìm thấy: **{query}**",
                    color=0xE74C3C,
                )
            )
            return

        player.queue.append(track)

        if player.is_playing() or player.is_paused():
            embed = discord.Embed(
                title="➕ Thêm vào hàng chờ",
                description=f"**[{track.title}]({track.webpage_url})**",
                color=0x3498DB,
            )
            embed.add_field(name="⏱ Thời lượng", value=_format_duration(track.duration), inline=True)
            embed.add_field(name="📋 Vị trí", value=f"`#{len(player.queue)}`", inline=True)
            if track.thumbnail:
                embed.set_thumbnail(url=track.thumbnail)
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send(
                embed=discord.Embed(description="🔍 Đang tải bài hát...", color=0xFEE75C)
            )
            await self._play_next(interaction.guild_id)

    # ── /skip ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="skip", description="⏭ Bỏ qua bài hiện tại")
    @app_commands.guild_only()
    async def skip(self, interaction: discord.Interaction):
        player = self._get_player(interaction.guild_id)
        if not player.is_playing() and not player.is_paused():
            await interaction.response.send_message("⚠️ Không có bài nào đang phát!", ephemeral=True)
            return
        player.voice_client.stop()
        await interaction.response.send_message(
            embed=discord.Embed(description="⏭ Đã skip!", color=0x3498DB)
        )

    # ── /stop ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="stop", description="⏹ Dừng nhạc và rời kênh")
    @app_commands.guild_only()
    async def stop(self, interaction: discord.Interaction):
        player = self._get_player(interaction.guild_id)
        if player.voice_client:
            player.queue.clear()
            player.current = None
            await player.voice_client.disconnect()
            self._players.pop(interaction.guild_id, None)
        await interaction.response.send_message(
            embed=discord.Embed(description="⏹ Đã dừng và rời kênh!", color=0xE74C3C)
        )

    # ── /pause ────────────────────────────────────────────────────────────────
    @app_commands.command(name="pause", description="⏸ Tạm dừng nhạc")
    @app_commands.guild_only()
    async def pause(self, interaction: discord.Interaction):
        player = self._get_player(interaction.guild_id)
        if player.is_playing():
            player.voice_client.pause()
            await interaction.response.send_message(
                embed=discord.Embed(description="⏸ Đã tạm dừng!", color=0xF39C12)
            )
        else:
            await interaction.response.send_message("⚠️ Không có gì đang phát!", ephemeral=True)

    # ── /resume ───────────────────────────────────────────────────────────────
    @app_commands.command(name="resume", description="▶️ Tiếp tục phát nhạc")
    @app_commands.guild_only()
    async def resume(self, interaction: discord.Interaction):
        player = self._get_player(interaction.guild_id)
        if player.is_paused():
            player.voice_client.resume()
            await interaction.response.send_message(
                embed=discord.Embed(description="▶️ Tiếp tục phát!", color=0x2ECC71)
            )
        else:
            await interaction.response.send_message("⚠️ Nhạc không bị tạm dừng!", ephemeral=True)

    # ── /queue ────────────────────────────────────────────────────────────────
    @app_commands.command(name="queue", description="📋 Xem hàng chờ nhạc")
    @app_commands.guild_only()
    async def queue(self, interaction: discord.Interaction):
        player = self._get_player(interaction.guild_id)
        embed = discord.Embed(title="📋 Hàng chờ nhạc", color=0x3498DB)

        if player.current:
            embed.add_field(
                name="🎵 Đang phát",
                value=f"**[{player.current.title}]({player.current.webpage_url})** `{_format_duration(player.current.duration)}`",
                inline=False,
            )

        if player.queue:
            queue_list = []
            for i, track in enumerate(list(player.queue)[:10], 1):
                queue_list.append(
                    f"`{i}.` [{track.title}]({track.webpage_url}) `{_format_duration(track.duration)}`"
                )
            embed.add_field(
                name=f"⏭ Tiếp theo ({len(player.queue)} bài)",
                value="\n".join(queue_list),
                inline=False,
            )
        else:
            embed.add_field(name="⏭ Hàng chờ", value="_Trống_", inline=False)

        await interaction.response.send_message(embed=embed)

    # ── /nowplaying ───────────────────────────────────────────────────────────
    @app_commands.command(name="nowplaying", description="🎵 Xem bài đang phát")
    @app_commands.guild_only()
    async def nowplaying(self, interaction: discord.Interaction):
        player = self._get_player(interaction.guild_id)
        if not player.current:
            await interaction.response.send_message("⚠️ Không có bài nào đang phát!", ephemeral=True)
            return
        await interaction.response.send_message(embed=self._now_playing_embed(player.current))

    # ── /volume ───────────────────────────────────────────────────────────────
    @app_commands.command(name="volume", description="🔊 Chỉnh âm lượng (0-100)")
    @app_commands.describe(level="Âm lượng từ 0 đến 100")
    @app_commands.guild_only()
    async def volume(self, interaction: discord.Interaction, level: int):
        if not 0 <= level <= 100:
            await interaction.response.send_message("⚠️ Âm lượng phải từ 0-100!", ephemeral=True)
            return
        player = self._get_player(interaction.guild_id)
        player._volume = level / 100
        if player.voice_client and player.voice_client.source:
            player.voice_client.source.volume = level / 100
        await interaction.response.send_message(
            embed=discord.Embed(description=f"🔊 Âm lượng: **{level}%**", color=0x2ECC71)
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCog(bot))
