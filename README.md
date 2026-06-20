# 🎮 Minecraft Discord Bot

Bot Discord quản lý Minecraft server trên **Aternos** với slash commands, auto reminder và hiển thị trạng thái real-time.

---

## ✨ Tính năng

| Lệnh | Mô tả |
|------|-------|
| `/startserver` | Kết nối Aternos, khởi động server, theo dõi trạng thái đến khi online |
| `/stopserver` / `/offserver` | Kết nối Aternos bằng browser thật, tắt server và theo dõi đến khi offline |
| `/status` | Kiểm tra trạng thái server (online/offline, số người, ping, MOTD) |
| `/online` | Danh sách người đang chơi (embed đẹp) |
| `/ruchoi` | So sánh role Discord vs người chơi MC, tag người chưa vào |
| `/play` | Nghe nhạc từ YouTube bằng tên bài, link video hoặc playlist |
| Auto Reminder | Mỗi ngày lúc 19:00, tự động tag role nếu ít hơn 2 người online |

---

## 📁 Cấu trúc dự án

```
BOTDISCORD/
├── bot/
│   ├── main.py              # Entry point, bot setup, auto-reconnect
│   ├── cogs/
│   │   ├── aternos.py       # /startserver — Aternos integration
│   │   ├── status.py        # /status, /online, /ruchoi
│   │   └── reminder.py      # Auto reminder hàng ngày
│   ├── utils/
│   │   ├── config.py        # Đọc/ghi config.json
│   │   └── embeds.py        # Discord embed templates
│   ├── config.json          # Cấu hình có thể chỉnh không cần restart
│   ├── .env                 # Token & secrets (KHÔNG commit)
│   └── requirements.txt
├── Procfile                 # Railway / Heroku process
├── railway.toml             # Railway config
├── runtime.txt              # Python version
├── .gitignore
└── README.md
```

---

## ⚙️ Cài đặt local

### 1. Clone repo

```bash
git clone https://github.com/yourname/minecraft-discord-bot.git
cd minecraft-discord-bot
```

### 2. Tạo virtual environment

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
```

### 3. Cài dependencies

```bash
pip install -r bot/requirements.txt
```

### 4. Cấu hình `.env`

Copy file mẫu và điền thông tin:

```bash
cp bot/.env.example bot/.env
```

Mở `bot/.env` và điền:

```env
DISCORD_TOKEN=your_discord_bot_token_here
GUILD_ID=your_guild_id_here
ATERNOS_USERNAME=your_aternos_username
ATERNOS_PASSWORD=your_aternos_password
ATERNOS_SERVER=yourserver.aternos.me
LOG_LEVEL=INFO
```

### 5. Cấu hình `config.json`

Mở `bot/config.json` và điền:

```json
{
  "minecraft_server_ip": "yourserver.aternos.me",
  "minecraft_server_port": 25565,
  "discord_minecraft_role_id": 123456789012345678,
  "discord_announce_channel_id": 123456789012345678,
  "reminder_time": "19:00",
  "reminder_min_players": 2
}
```

> **Lấy ID Discord:** Bật Developer Mode (Settings → Advanced → Developer Mode), chuột phải vào role/channel → Copy ID.

### 6. Chạy bot

```bash
python bot/main.py
```

---

## 🔑 Tạo Discord Bot

1. Vào [Discord Developer Portal](https://discord.com/developers/applications)
2. **New Application** → đặt tên
3. Tab **Bot** → **Reset Token** → copy token vào `.env`
4. Bật **Privileged Gateway Intents**:
   - ✅ Server Members Intent
   - ✅ Message Content Intent
5. Tab **OAuth2 → URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Permissions: `Send Messages`, `Embed Links`, `Mention Everyone`, `Read Message History`
6. Copy link → mở trình duyệt → mời bot vào server

---

## 🚀 Deploy lên Railway (miễn phí)

### Bước 1: Chuẩn bị

- Tạo tài khoản [Railway](https://railway.app) (đăng nhập bằng GitHub)
- Push code lên GitHub (đừng commit file `.env`!)

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/yourname/minecraft-discord-bot.git
git push -u origin main
```

### Bước 2: Tạo project Railway

1. Vào [railway.app/new](https://railway.app/new)
2. Chọn **Deploy from GitHub repo**
3. Chọn repo của bạn

### Bước 3: Cấu hình Environment Variables

Trong Railway dashboard → tab **Variables** → thêm từng biến:

| Key | Value |
|-----|-------|
| `DISCORD_TOKEN` | Token bot Discord |
| `GUILD_ID` | ID server Discord |
| `ATERNOS_USERNAME` | Tên đăng nhập Aternos |
| `ATERNOS_PASSWORD` | Mật khẩu Aternos |
| `ATERNOS_SERVER` | Domain server Aternos |
| `LOG_LEVEL` | `INFO` |

### Bước 4: Deploy

Railway tự động detect `Procfile` và deploy. Xem logs trong tab **Deployments**.

> ⚠️ **Lưu ý Railway Free Tier:** Railway miễn phí giới hạn ~500 giờ/tháng. Đủ để chạy 1 bot 24/7.

---

## 🚀 Deploy lên Koyeb (miễn phí)

### Bước 1: Tạo tài khoản [Koyeb](https://app.koyeb.com)

### Bước 2: Tạo App mới

1. **Create App** → **GitHub**
2. Chọn repo → branch `main`
3. **Build command:** `pip install -r bot/requirements.txt`
4. **Run command:** `python bot/main.py`
5. **Instance type:** Free (Eco)

### Bước 3: Environment Variables

Thêm tất cả biến như bảng ở trên.

### Bước 4: Deploy

Click **Deploy** và chờ build xong.

---

## 📝 Dashboard Config (config.json)

Có thể chỉnh file `bot/config.json` trực tiếp mà **không cần restart bot**:

| Key | Mô tả | Ví dụ |
|-----|-------|-------|
| `minecraft_server_ip` | IP/domain Minecraft server | `"play.aternos.me"` |
| `minecraft_server_port` | Port server | `25565` |
| `discord_minecraft_role_id` | ID role Minecraft trên Discord | `123456789` |
| `discord_announce_channel_id` | ID channel thông báo | `123456789` |
| `reminder_time` | Giờ nhắc nhở (24h format) | `"19:00"` |
| `reminder_min_players` | Số người tối thiểu để bỏ qua reminder | `2` |

---

## 🛠️ Xử lý sự cố

### Bot không phản hồi slash commands
- Đảm bảo đã điền đúng `GUILD_ID` trong `.env`
- Đợi ~1 phút sau khi bot start để sync commands
- Nếu dùng global sync (không có GUILD_ID), đợi tối đa 1 giờ

### `/startserver` báo lỗi Aternos
- Kiểm tra username/password Aternos trong `.env`
- Cài Playwright browser: `python -m playwright install chromium`
- Nếu deploy Linux/Railway, dùng build step: `python -m playwright install --with-deps chromium`
- Nếu Aternos hiện captcha/verify, đăng nhập thủ công một lần rồi dùng lại session/cookie hợp lệ

### Reminder không gửi
- Kiểm tra `discord_announce_channel_id` và `discord_minecraft_role_id` trong `config.json`
- Bot cần quyền `Send Messages` và `Mention Roles` trong channel đó
- Restart bot sau khi thay đổi `reminder_time`

---

## 📦 Dependencies

| Package | Version | Dùng để |
|---------|---------|---------|
| `discord.py` | 2.3.2 | Discord API, slash commands |
| `mcstatus` | 11.1.1 | Query Minecraft server status |
| `yt-dlp` | 2024.4.9 | Lấy stream nhạc từ YouTube |
| `playwright` | 1.60.0 | Điều khiển browser thật để thao tác Aternos |
| `aiohttp` | 3.9.5 | Async HTTP (dependency) |
| `python-dotenv` | 1.0.1 | Load file .env |

---

## 📄 License

MIT License — Sử dụng tự do, vui lòng giữ credit.
