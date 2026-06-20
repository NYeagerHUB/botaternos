"""
Cog: Music — Nghe nhạc từ YouTube
Port từ MusicBot-main (Node.js) sang Python/discord.py
Tính năng: play, skip, stop, pause, resume, queue, loop, shuffle, volume, nowplaying
Button controls, preload, auto-reconnect
"""

import asyncio
import logging
import random
import concurrent.futures
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Literal
from enum import Enum

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("bot.music")

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": False,
    "quiet": True,
    "no_warnings": True,
    "socket_timeout": 30,
    "retries": 3,
    "extract_flat": False,
    "extractor_args": {"youtube": {"player_client": ["ios"]}},
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)


class LoopMode(Enum):
    OFF = "off"
    TRACK = "track"
    QUEUE = "queue"


@dataclass
class Track:
    title: str
    url: str
    webpage_url: str
    duration: int
    thumbnail: str
    artist: str
    platform: str
    requester: discord.Member

    def duration_str(self) -> str:
        s = self.duration
        if not s:
            return "Live"
        h, rem = divmod(int(s), 3600)
        m, sec = divmod(rem, 60)
        return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _do_search(query: str) -> dict:
    import yt_dlp
    opts = dict(YTDL_OPTIONS)
    with yt_dlp.YoutubeDL(opts) as ydl:
        if query.startswith("http"):
            info = ydl.extract_info(query, download=False)
        else:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
            if "entries" in info and info["entries"]:
                info = info["entries"][0]
            elif "entries" in info:
                raise ValueError("Không tìm thấy bài hát")
    return info


def _do_playlist(url: str) -> dict:
    import yt_dlp
    opts = {**YTDL_OPTIONS, "extract_flat": True, "noplaylist": False}
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


async def fetch_track(query: str, requester: discord.Member) -> Optional[Track]:
    loop = asyncio.get_event_loop()
    try:
        info = await asyncio.wait_for(
            loop.run_in_executor(_executor, _do_search, query),
            timeout=45,
        )
        return Track(
            title=info.get("title", "Unknown"),
            url=info.get("url", info.get("webpage_url", query)),
            webpage_url=info.get("webpage_url", query),
            duration=info.get("duration", 0),
            thumbnail=info.get("thumbnail", ""),
            artist=info.get("uploader", info.get("channel", "Unknown")),
            platform="youtube",
            requester=requester,
        )
    except asyncio.TimeoutError:
        logger.error("yt-dlp timeout")
        return None
    except Exception as e:
        logger.error(f"fetch_track error: {e}")
        return None


async def fetch_playlist(url: str, requester: discord.Member) -> list[Track]:
    loop = asyncio.get_event_loop()
    try:
        info = await asyncio.wait_for(
            loop.run_in_executor(_executor, _do_playlist, url),
            timeout=60,
        )
        tracks = []
        entries = info.get("entries", [])
        for e in entries[:50]:
            if not e:
                continue
            tracks.append(Track(
                title=e.get("title", "Unknown"),
                url=e.get("url", e.get("webpage_url", "")),
                webpage_url=e.get("webpage_url", e.get("url", "")),
                duration=e.get("duration", 0),
                thumbnail=e.get("thumbnail", ""),
                artist=e.get("uploader", "Unknown"),
                platform="youtube",
                requester=requester,
            ))
        return tracks
    except Exception as e:
        logger.error(f"fetch_playlist error: {e}")
        return []


class MusicControlView(discord.ui.View):
    """Button controls cho now-playing embed."""

    def __init__(self, player: "GuildPlayer"):
        super().__init__(timeout=None)
        self.player = player
        self._update_buttons()

    def _update_buttons(self):
        self.clear_items()
        p = self.player

        # Pause/Resume
        pause_btn = discord.ui.Button(
            label="Resume" if p.paused else "Pause",
            emoji="▶️" if p.paused else "⏸️",
            style=discord.ButtonStyle.secondary,
            custom_id="music_pause",
        )
        pause_btn.callback = self._pause_callback
        self.add_item(pause_btn)

        # Skip
        skip_btn = discord.ui.Button(
            label="Skip", emoji="⏭️",
            style=discord.ButtonStyle.secondary,
            custom_id="music_skip",
            disabled=len(p.queue) == 0 and p.loop == LoopMode.OFF,
        )
        skip_btn.callback = self._skip_callback
        self.add_item(skip_btn)

        # Stop
        stop_btn = discord.ui.Button(
            label="Stop", emoji="⏹️",
            style=discord.ButtonStyle.danger,
            custom_id="music_stop",
        )
        stop_btn.callback = self._stop_callback
        self.add_item(stop_btn)

        # Queue
        queue_btn = discord.ui.Button(
            label="Queue", emoji="📋",
            style=discord.ButtonStyle.primary,
            custom_id="music_queue",
        )
        queue_btn.callback = self._queue_callback
        self.add_item(queue_btn)

        # Shuffle
        shuffle_btn = discord.ui.Button(
            label="Shuffle", emoji="🔀",
            style=discord.ButtonStyle.success if p.shuffle else discord.ButtonStyle.secondary,
            custom_id="music_shuffle",
        )
        shuffle_btn.callback = self._shuffle_callback
        self.add_item(shuffle_btn)

        # Loop
        loop_labels = {LoopMode.OFF: ("Loop", "➡️"), LoopMode.TRACK: ("Loop Track", "🔂"), LoopMode.QUEUE: ("Loop Queue", "🔁")}
        ll, le = loop_labels[p.loop]
        loop_btn = discord.ui.Button(
            label=ll, emoji=le,
            style=discord.ButtonStyle.success if p.loop != LoopMode.OFF else discord.ButtonStyle.secondary,
            custom_id="music_loop",
        )
        loop_btn.callback = self._loop_callback
        self.add_item(loop_btn)

    async def _pause_callback(self, interaction: discord.Interaction):
        p = self.player
        if p.is_paused():
            p.voice_client.resume()
            p.paused = False
        elif p.is_playing():
            p.voice_client.pause()
            p.paused = True
        await interaction.response.defer()
        await p.update_embed()

    async def _skip_callback(self, interaction: discord.Interaction):
        p = self.player
        if p.voice_client:
            p.voice_client.stop()
        await interaction.response.defer()

    async def _stop_callback(self, interaction: discord.Interaction):
        p = self.player
        p.queue.clear()
        p.loop = LoopMode.OFF
        if p.voice_client:
            p.voice_client.stop()
            await p.voice_client.disconnect()
        p.voice_client = None
        p.current = None
        await interaction.response.send_message("Đã dừng và rời kênh!", ephemeral=True)

    async def _queue_callback(self, interaction: discord.Interaction):
        p = self.player
        embed = discord.Embed(title="Hàng chờ nhạc", color=0x3498DB)
        if p.current:
            embed.add_field(
                name="Đang phát",
                value=f"**[{p.current.title}]({p.current.webpage_url})** `{p.current.duration_str()}`",
                inline=False,
            )
        if p.queue:
            items = [f"`{i}.` [{t.title}]({t.webpage_url}) `{t.duration_str()}`"
                     for i, t in enumerate(list(p.queue)[:10], 1)]
            embed.add_field(name=f"Tiếp theo ({len(p.queue)})", value="\n".join(items), inline=False)
        else:
            embed.add_field(name="Tiếp theo", value="_Trống_", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _shuffle_callback(self, interaction: discord.Interaction):
        p = self.player
        p.shuffle = not p.shuffle
        if p.shuffle and p.queue:
            q = list(p.queue)
            random.shuffle(q)
            p.queue = deque(q)
        await interaction.response.defer()
        await p.update_embed()

    async def _loop_callback(self, interaction: discord.Interaction):
        p = self.player
        modes = [LoopMode.OFF, LoopMode.TRACK, LoopMode.QUEUE]
        p.loop = modes[(modes.index(p.loop) + 1) % len(modes)]
        await interaction.response.defer()
        await p.update_embed()


class GuildPlayer:
    """Quản lý nhạc cho 1 guild."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queue: deque[Track] = deque()
        self.current: Optional[Track] = None
        self.voice_client: Optional[discord.VoiceClient] = None
        self.text_channel: Optional[discord.abc.Messageable] = None
        self.now_playing_msg: Optional[discord.Message] = None
        self.volume: float = 0.5
        self.loop: LoopMode = LoopMode.OFF
        self.shuffle: bool = False
        self.paused: bool = False

    def is_playing(self) -> bool:
        return self.voice_client is not None and self.voice_client.is_playing()

    def is_paused(self) -> bool:
        return self.voice_client is not None and self.voice_client.is_paused()

    def now_playing_embed(self) -> discord.Embed:
        t = self.current
        embed = discord.Embed(
            title="Đang phát",
            description=f"**[{t.title}]({t.webpage_url})**",
            color=0x1DB954,
        )
        embed.add_field(name="Nghệ sĩ", value=t.artist or "Unknown", inline=True)
        embed.add_field(name="Thời lượng", value=t.duration_str(), inline=True)
        embed.add_field(name="Yêu cầu bởi", value=t.requester.mention, inline=True)

        loop_map = {LoopMode.OFF: "Tắt", LoopMode.TRACK: "Bài này", LoopMode.QUEUE: "Cả hàng"}
        embed.add_field(name="Lặp", value=loop_map[self.loop], inline=True)
        embed.add_field(name="Shuffle", value="Bật" if self.shuffle else "Tắt", inline=True)
        embed.add_field(name="Hàng chờ", value=f"{len(self.queue)} bài", inline=True)

        if t.thumbnail:
            embed.set_thumbnail(url=t.thumbnail)
        embed.set_footer(text="Dùng các nút bên dưới để điều khiển")
        return embed

    async def update_embed(self):
        if not self.now_playing_msg or not self.current:
            return
        try:
            view = MusicControlView(self)
            await self.now_playing_msg.edit(embed=self.now_playing_embed(), view=view)
        except discord.HTTPException:
            pass

    async def play_next(self):
        if self.loop == LoopMode.TRACK and self.current:
            pass  # giữ nguyên current
        elif self.loop == LoopMode.QUEUE and self.current:
            self.queue.append(self.current)
            self.current = self.queue.popleft() if self.queue else None
        else:
            self.current = self.queue.popleft() if self.queue else None

        if not self.current:
            await self._on_queue_empty()
            return

        await self._start_playback()

    async def _start_playback(self):
        if not self.voice_client or not self.voice_client.is_connected():
            return

        loop = asyncio.get_event_loop()
        try:
            # Lấy stream URL mới (URL stream có TTL ngắn)
            info = await asyncio.wait_for(
                loop.run_in_executor(_executor, _do_search, self.current.webpage_url),
                timeout=45,
            )
            stream_url = info.get("url", self.current.url)
        except Exception as e:
            logger.error(f"Không lấy được stream URL: {e}")
            # Thử bài tiếp theo
            self.current = self.queue.popleft() if self.queue else None
            if self.current:
                await self._start_playback()
            return

        source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
        source = discord.PCMVolumeTransformer(source, volume=self.volume)

        def after(error):
            if error:
                logger.error(f"Playback error: {error}")
            asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)

        self.voice_client.play(source, after=after)
        self.paused = False

        # Gửi/cập nhật now playing embed
        view = MusicControlView(self)
        embed = self.now_playing_embed()
        try:
            if self.now_playing_msg:
                await self.now_playing_msg.edit(embed=embed, view=view)
            elif self.text_channel:
                self.now_playing_msg = await self.text_channel.send(embed=embed, view=view)
        except discord.HTTPException:
            pass

    async def _on_queue_empty(self):
        self.current = None
        if self.now_playing_msg:
            try:
                embed = discord.Embed(
                    description="Hết hàng chờ. Bot rời kênh sau 60 giây.",
                    color=0x3498DB,
                )
                await self.now_playing_msg.edit(embed=embed, view=None)
            except discord.HTTPException:
                pass
        await asyncio.sleep(60)
        if self.voice_client and not self.is_playing() and not self.is_paused():
            try:
                await self.voice_client.disconnect()
            except Exception:
                pass


class MusicCog(commands.Cog, name="Music"):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._players: dict[int, GuildPlayer] = {}

    def _get_player(self, guild_id: int) -> GuildPlayer:
        if guild_id not in self._players:
            self._players[guild_id] = GuildPlayer(self.bot)
        return self._players[guild_id]

    async def _ensure_voice(self, interaction: discord.Interaction) -> Optional[GuildPlayer]:
        if not interaction.user.voice:
            await interaction.followup.send("Bạn cần vào kênh voice trước!", ephemeral=True)
            return None
        player = self._get_player(interaction.guild_id)
        player.text_channel = interaction.channel
        if not player.voice_client or not player.voice_client.is_connected():
            try:
                player.voice_client = await interaction.user.voice.channel.connect()
            except Exception as e:
                await interaction.followup.send(f"Không vào được kênh voice: {e}", ephemeral=True)
                return None
        elif player.voice_client.channel != interaction.user.voice.channel:
            await player.voice_client.move_to(interaction.user.voice.channel)
        return player

    # ── /play ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="play", description="Phát nhạc từ YouTube (tên bài, link video hoặc playlist)")
    @app_commands.describe(query="Tên bài hát hoặc link YouTube")
    @app_commands.guild_only()
    async def play(self, interaction: discord.Interaction, query: str):
        if not interaction.user.voice:
            await interaction.response.send_message("Bạn cần vào kênh voice trước!", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)

        player = await self._ensure_voice(interaction)
        if not player:
            return

        await interaction.followup.send(
            embed=discord.Embed(description=f"Đang tìm: **{query}**...", color=0xFEE75C)
        )

        # Kiểm tra playlist
        is_playlist = "list=" in query and ("youtube.com" in query or "youtu.be" in query)
        if is_playlist:
            tracks = await fetch_playlist(query, interaction.user)
            if not tracks:
                await interaction.channel.send(
                    embed=discord.Embed(description=f"Không tải được playlist: **{query}**", color=0xE74C3C)
                )
                return

            was_idle = player.current is None
            for t in tracks:
                if player.current is None and was_idle:
                    player.current = t
                    was_idle = False
                else:
                    player.queue.append(t)

            await interaction.channel.send(
                embed=discord.Embed(
                    description=f"Đã thêm **{len(tracks)} bài** từ playlist vào hàng chờ.",
                    color=0x2ECC71,
                )
            )
            if player.current and not player.is_playing() and not player.is_paused():
                await player._start_playback()
        else:
            track = await fetch_track(query, interaction.user)
            if not track:
                await interaction.channel.send(
                    embed=discord.Embed(
                        description=f"Không tìm thấy: **{query}**",
                        color=0xE74C3C,
                    )
                )
                return

            if player.is_playing() or player.is_paused():
                if player.shuffle:
                    pos = random.randint(0, len(player.queue))
                    q = list(player.queue)
                    q.insert(pos, track)
                    player.queue = deque(q)
                else:
                    player.queue.append(track)
                embed = discord.Embed(
                    title="Thêm vào hàng chờ",
                    description=f"**[{track.title}]({track.webpage_url})**",
                    color=0x3498DB,
                )
                embed.add_field(name="Thời lượng", value=track.duration_str(), inline=True)
                embed.add_field(name="Vị trí", value=f"`#{len(player.queue)}`", inline=True)
                if track.thumbnail:
                    embed.set_thumbnail(url=track.thumbnail)
                await interaction.channel.send(embed=embed)
                await player.update_embed()
            else:
                player.current = track
                await player._start_playback()

    # ── /skip ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="skip", description="Bỏ qua bài hiện tại")
    @app_commands.guild_only()
    async def skip(self, interaction: discord.Interaction):
        player = self._get_player(interaction.guild_id)
        if not player.is_playing() and not player.is_paused():
            await interaction.response.send_message("Không có bài nào đang phát!", ephemeral=True)
            return
        player.voice_client.stop()
        await interaction.response.send_message(
            embed=discord.Embed(description="Đã skip!", color=0x3498DB)
        )

    # ── /stop ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="stop", description="Dừng nhạc và rời kênh voice")
    @app_commands.guild_only()
    async def stop(self, interaction: discord.Interaction):
        player = self._get_player(interaction.guild_id)
        player.queue.clear()
        player.loop = LoopMode.OFF
        player.current = None
        if player.voice_client:
            try:
                await player.voice_client.disconnect()
            except Exception:
                pass
        self._players.pop(interaction.guild_id, None)
        await interaction.response.send_message(
            embed=discord.Embed(description="Đã dừng và rời kênh!", color=0xE74C3C)
        )

    # ── /pause ────────────────────────────────────────────────────────────────
    @app_commands.command(name="pause", description="Tạm dừng nhạc")
    @app_commands.guild_only()
    async def pause(self, interaction: discord.Interaction):
        player = self._get_player(interaction.guild_id)
        if player.is_playing():
            player.voice_client.pause()
            player.paused = True
            await interaction.response.send_message(
                embed=discord.Embed(description="Đã tạm dừng!", color=0xF39C12)
            )
            await player.update_embed()
        else:
            await interaction.response.send_message("Không có gì đang phát!", ephemeral=True)

    # ── /resume ───────────────────────────────────────────────────────────────
    @app_commands.command(name="resume", description="Tiếp tục phát nhạc")
    @app_commands.guild_only()
    async def resume(self, interaction: discord.Interaction):
        player = self._get_player(interaction.guild_id)
        if player.is_paused():
            player.voice_client.resume()
            player.paused = False
            await interaction.response.send_message(
                embed=discord.Embed(description="Tiếp tục phát!", color=0x2ECC71)
            )
            await player.update_embed()
        else:
            await interaction.response.send_message("Nhạc không bị tạm dừng!", ephemeral=True)

    # ── /queue ────────────────────────────────────────────────────────────────
    @app_commands.command(name="queue", description="Xem hàng chờ nhạc")
    @app_commands.guild_only()
    async def queue_cmd(self, interaction: discord.Interaction):
        player = self._get_player(interaction.guild_id)
        embed = discord.Embed(title="Hàng chờ nhạc", color=0x3498DB)
        if player.current:
            embed.add_field(
                name="Đang phát",
                value=f"**[{player.current.title}]({player.current.webpage_url})** `{player.current.duration_str()}`",
                inline=False,
            )
        if player.queue:
            items = [f"`{i}.` [{t.title}]({t.webpage_url}) `{t.duration_str()}`"
                     for i, t in enumerate(list(player.queue)[:10], 1)]
            embed.add_field(name=f"Tiếp theo ({len(player.queue)} bài)", value="\n".join(items), inline=False)
        else:
            embed.add_field(name="Tiếp theo", value="_Trống_", inline=False)
        await interaction.response.send_message(embed=embed)

    # ── /nowplaying ───────────────────────────────────────────────────────────
    @app_commands.command(name="nowplaying", description="Xem bài đang phát")
    @app_commands.guild_only()
    async def nowplaying(self, interaction: discord.Interaction):
        player = self._get_player(interaction.guild_id)
        if not player.current:
            await interaction.response.send_message("Không có bài nào đang phát!", ephemeral=True)
            return
        view = MusicControlView(player)
        await interaction.response.send_message(embed=player.now_playing_embed(), view=view)

    # ── /volume ───────────────────────────────────────────────────────────────
    @app_commands.command(name="volume", description="Chỉnh âm lượng (0-100)")
    @app_commands.describe(level="Âm lượng từ 0 đến 100")
    @app_commands.guild_only()
    async def volume(self, interaction: discord.Interaction, level: int):
        if not 0 <= level <= 100:
            await interaction.response.send_message("Âm lượng phải từ 0-100!", ephemeral=True)
            return
        player = self._get_player(interaction.guild_id)
        player.volume = level / 100
        if player.voice_client and player.voice_client.source:
            player.voice_client.source.volume = level / 100
        await interaction.response.send_message(
            embed=discord.Embed(description=f"Âm lượng: **{level}%**", color=0x2ECC71)
        )

    # ── /shuffle ──────────────────────────────────────────────────────────────
    @app_commands.command(name="shuffle", description="Bật/tắt phát ngẫu nhiên")
    @app_commands.guild_only()
    async def shuffle_cmd(self, interaction: discord.Interaction):
        player = self._get_player(interaction.guild_id)
        player.shuffle = not player.shuffle
        if player.shuffle and player.queue:
            q = list(player.queue)
            random.shuffle(q)
            player.queue = deque(q)
        status = "Bật" if player.shuffle else "Tắt"
        await interaction.response.send_message(
            embed=discord.Embed(description=f"Shuffle: **{status}**", color=0x2ECC71)
        )
        await player.update_embed()

    # ── /loop ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="loop", description="Chọn chế độ lặp")
    @app_commands.describe(mode="off = tắt, track = lặp bài này, queue = lặp cả hàng")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Tắt", value="off"),
        app_commands.Choice(name="Lặp bài này", value="track"),
        app_commands.Choice(name="Lặp cả hàng", value="queue"),
    ])
    @app_commands.guild_only()
    async def loop_cmd(self, interaction: discord.Interaction, mode: str):
        player = self._get_player(interaction.guild_id)
        player.loop = LoopMode(mode)
        labels = {"off": "Tắt", "track": "Lặp bài này", "queue": "Lặp cả hàng"}
        await interaction.response.send_message(
            embed=discord.Embed(description=f"Chế độ lặp: **{labels[mode]}**", color=0x2ECC71)
        )
        await player.update_embed()

    # ── /clear ────────────────────────────────────────────────────────────────
    @app_commands.command(name="clear", description="Xóa toàn bộ hàng chờ nhạc")
    @app_commands.guild_only()
    async def clear(self, interaction: discord.Interaction):
        player = self._get_player(interaction.guild_id)
        count = len(player.queue)
        player.queue.clear()
        await interaction.response.send_message(
            embed=discord.Embed(description=f"Đã xóa **{count}** bài khỏi hàng chờ.", color=0xE74C3C)
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCog(bot))
