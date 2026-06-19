"""
Utility: Tạo Discord Embeds đẹp mắt dùng chung
"""

import discord
from datetime import datetime


COLORS = {
    "success":  0x2ECC71,   # xanh lá
    "error":    0xE74C3C,   # đỏ
    "warning":  0xF39C12,   # vàng
    "info":     0x3498DB,   # xanh dương
    "online":   0x57F287,   # xanh Discord online
    "offline":  0xED4245,   # đỏ Discord offline
    "loading":  0xFEE75C,   # vàng Discord
}


def base_embed(
    title: str,
    description: str = "",
    color_key: str = "info",
) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=COLORS.get(color_key, COLORS["info"]),
        timestamp=datetime.utcnow(),
    )
    embed.set_footer(text="Minecraft Bot • by YourName")
    return embed


def server_status_embed(
    ip: str,
    port: int,
    online: bool,
    player_count: int = 0,
    max_players: int = 0,
    player_list: list[str] | None = None,
    latency: float | None = None,
    motd: str = "",
) -> discord.Embed:
    if online:
        embed = base_embed(
            title="🟢 Server Minecraft — ONLINE",
            color_key="online",
        )
        embed.add_field(name="🌐 Địa chỉ", value=f"`{ip}:{port}`", inline=True)
        embed.add_field(
            name="👥 Người chơi",
            value=f"`{player_count}/{max_players}`",
            inline=True,
        )
        if latency is not None:
            embed.add_field(name="📶 Ping", value=f"`{latency:.1f} ms`", inline=True)
        if motd:
            embed.add_field(name="📋 MOTD", value=f"```{motd}```", inline=False)
        if player_list:
            names = "\n".join(f"• `{p}`" for p in player_list)
            embed.add_field(
                name=f"🎮 Đang chơi ({len(player_list)})",
                value=names or "_Không có_",
                inline=False,
            )
        else:
            embed.add_field(name="🎮 Đang chơi", value="_Không có ai_", inline=False)
    else:
        embed = base_embed(
            title="🔴 Server Minecraft — OFFLINE",
            description=f"Server `{ip}:{port}` hiện không hoạt động.",
            color_key="offline",
        )

    return embed


def ruchoi_embed(
    online_players: list[str],
    members_not_in: list[discord.Member],
) -> discord.Embed:
    embed = base_embed(
        title="🎮 Ai đang chơi Minecraft?",
        color_key="info",
    )

    if online_players:
        names = "\n".join(f"• `{p}`" for p in online_players)
        embed.add_field(
            name=f"✅ Đang online ({len(online_players)})",
            value=names,
            inline=False,
        )
    else:
        embed.add_field(
            name="✅ Đang online",
            value="_Chưa có ai vào chơi_",
            inline=False,
        )

    if members_not_in:
        mentions = " ".join(m.mention for m in members_not_in)
        embed.add_field(
            name=f"📢 Chưa vào ({len(members_not_in)})",
            value=mentions,
            inline=False,
        )
        embed.description = "Vào chơi Minecraft đi anh em! 👇"

    embed.color = COLORS["online"] if online_players else COLORS["warning"]
    return embed


def aternos_status_embed(status: str, server_ip: str = "") -> discord.Embed:
    status_map = {
        "starting":  ("🟡 Server đang khởi động...", "loading", "⏳ Đang khởi động"),
        "loading":   ("🟡 Server đang tải...",        "loading", "⏳ Đang tải"),
        "waiting":   ("⏳ Đang chờ trong hàng đợi",  "warning", "🕐 Hàng đợi"),
        "online":    ("🟢 Server đã ONLINE!",         "online",  "✅ Online"),
        "offline":   ("🔴 Server OFFLINE",            "offline", "❌ Offline"),
        "stopping":  ("🟠 Server đang tắt...",        "warning", "⏹️ Đang tắt"),
        "error":     ("❌ Lỗi server",                "error",   "❌ Lỗi"),
    }
    title, color_key, status_text = status_map.get(
        status.lower(),
        (f"ℹ️ Trạng thái: {status}", "info", status),
    )

    embed = base_embed(title=title, color_key=color_key)
    embed.add_field(name="📊 Trạng thái", value=f"`{status_text}`", inline=True)
    if server_ip and status.lower() == "online":
        embed.add_field(name="🌐 IP Server", value=f"`{server_ip}`", inline=True)
        embed.description = f"Kết nối: **`{server_ip}`**"

    return embed
