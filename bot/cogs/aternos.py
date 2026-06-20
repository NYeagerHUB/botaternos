"""
Cog: Aternos - /startserver
Controls Aternos through a real Chromium browser using Playwright.
"""

import asyncio
import logging
import os
import re

import discord
from discord import app_commands
from discord.ext import commands
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from utils import config, embeds

logger = logging.getLogger("bot.aternos")

POLL_INTERVAL = 15
MAX_WAIT_TIME = 600

ATERNOS_ORIGIN = "https://aternos.org"
ATERNOS_SERVER_URL = f"{ATERNOS_ORIGIN}/server/"
ATERNOS_LOGIN_URL = f"{ATERNOS_ORIGIN}/go/"

STATUS_ALIASES = {
    "online": ("online", "running"),
    "offline": ("offline", "stopped"),
    "starting": ("starting", "starting..."),
    "loading": ("loading", "preparing", "saving", "loading..."),
    "waiting": ("waiting", "queue", "queued"),
    "stopping": ("stopping", "stopping..."),
    "error": ("error", "crashed"),
}


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


class AternosBrowser:
    """Small Playwright wrapper for Aternos UI actions."""

    def __init__(self):
        self.username = _env("ATERNOS_USERNAME")
        self.password = _env("ATERNOS_PASSWORD")
        self.session_cookie = _env("ATERNOS_SESSION")
        self.server_name = _env("ATERNOS_SERVER") or config.get("aternos_server_name", "")
        self.headless = _env("ATERNOS_HEADLESS").lower() not in ("0", "false", "no")
        self.slow_mo = int(_env("ATERNOS_SLOW_MO") or "0")

        if not self.session_cookie and not (self.username and self.password):
            raise ValueError(
                "Missing Aternos login. Set ATERNOS_USERNAME + ATERNOS_PASSWORD, "
                "or ATERNOS_SESSION."
            )

        self._playwright = None
        self._browser = None
        self._context = None
        self.page = None

    async def __aenter__(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            slow_mo=self.slow_mo,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        self._context = await self._browser.new_context(
            locale="en-US",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
        )

        if self.session_cookie:
            await self._context.add_cookies([
                {
                    "name": "ATERNOS_SESSION",
                    "value": self.session_cookie,
                    "domain": ".aternos.org",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                    "sameSite": "Lax",
                }
            ])

        self.page = await self._context.new_page()
        self.page.set_default_timeout(20000)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def open_server(self) -> None:
        await self.page.goto(ATERNOS_SERVER_URL, wait_until="domcontentloaded")
        await self._dismiss_popups()

        if await self._is_login_page():
            await self._login()
            await self.page.goto(ATERNOS_SERVER_URL, wait_until="domcontentloaded")
            await self._dismiss_popups()

        await self._select_server_if_needed()
        await self._wait_for_server_panel()

    async def status(self) -> str:
        await self._dismiss_popups()

        for selector in (
            ".statuslabel-label",
            ".statuslabel",
            ".server-status",
            "[class*='status']",
        ):
            locator = self.page.locator(selector).first
            try:
                if await locator.count() and await locator.is_visible(timeout=1500):
                    text = await locator.inner_text(timeout=1500)
                    parsed = self._parse_status(text)
                    if parsed != "unknown":
                        return parsed
            except PlaywrightTimeoutError:
                continue

        text = await self.page.locator("body").inner_text(timeout=5000)
        return self._parse_status(text)

    async def start(self) -> None:
        await self._dismiss_popups()

        start_selectors = (
            "#start",
            ".server-start",
            "[data-action='start']",
            "button:has-text('Start')",
            "a:has-text('Start')",
            "div:has-text('Start')",
        )

        for selector in start_selectors:
            locator = self.page.locator(selector).first
            try:
                if await locator.count() and await locator.is_visible(timeout=2000):
                    await locator.click(timeout=5000)
                    await self._confirm_start_if_needed()
                    return
            except PlaywrightTimeoutError:
                continue

        raise RuntimeError("Could not find the Aternos Start button in the browser UI.")

    async def _login(self) -> None:
        if not (self.username and self.password):
            raise RuntimeError("Aternos session expired. Set ATERNOS_USERNAME and ATERNOS_PASSWORD.")

        await self.page.goto(ATERNOS_LOGIN_URL, wait_until="domcontentloaded")
        await self._dismiss_popups()

        user_input = self.page.locator(
            "input[name='user'], input[name='username'], input[type='text']"
        ).first
        password_input = self.page.locator("input[name='password'], input[type='password']").first

        await user_input.fill(self.username)
        await password_input.fill(self.password)

        submit = self.page.locator(
            "button[type='submit'], button:has-text('Login'), button:has-text('Log in')"
        ).first
        await submit.click()

        try:
            await self.page.wait_for_url(re.compile(r".*/(server|servers|panel)/?.*"), timeout=30000)
        except PlaywrightTimeoutError:
            if await self._is_login_page():
                raise RuntimeError(
                    "Could not log in to Aternos. Check credentials or solve any captcha manually."
                )

    async def _is_login_page(self) -> bool:
        if "login" in self.page.url or "/go" in self.page.url:
            password_inputs = await self.page.locator("input[type='password']").count()
            return password_inputs > 0
        return await self.page.locator("input[type='password']").count() > 0

    async def _select_server_if_needed(self) -> None:
        if not self.server_name:
            return

        body_text = await self.page.locator("body").inner_text(timeout=5000)
        if self.server_name in body_text and "/server/" not in self.page.url.rstrip("/"):
            server_link = self.page.locator(f"text={self.server_name}").first
            try:
                if await server_link.count() and await server_link.is_visible(timeout=2000):
                    await server_link.click(timeout=5000)
                    await self.page.wait_for_load_state("domcontentloaded")
            except PlaywrightTimeoutError:
                logger.debug("Server list item was present but not clickable.")

    async def _wait_for_server_panel(self) -> None:
        try:
            await self.page.wait_for_selector(
                "#start, .server-start, .statuslabel, [class*='status']",
                timeout=30000,
            )
        except PlaywrightTimeoutError as exc:
            raise RuntimeError("Aternos server panel did not load in the browser.") from exc

    async def _confirm_start_if_needed(self) -> None:
        await asyncio.sleep(1)
        for selector in (
            "button:has-text('Confirm')",
            "button:has-text('Yes')",
            "button:has-text('Continue')",
            ".btn-success:visible",
        ):
            locator = self.page.locator(selector).first
            try:
                if await locator.count() and await locator.is_visible(timeout=1000):
                    await locator.click(timeout=3000)
                    break
            except PlaywrightTimeoutError:
                continue

    async def _dismiss_popups(self) -> None:
        for selector in (
            "button:has-text('Accept')",
            "button:has-text('Agree')",
            "button:has-text('OK')",
            ".fc-cta-consent",
            ".cookie-button",
        ):
            locator = self.page.locator(selector).first
            try:
                if await locator.count() and await locator.is_visible(timeout=800):
                    await locator.click(timeout=2000)
            except PlaywrightTimeoutError:
                continue

    @staticmethod
    def _parse_status(text: str) -> str:
        normalized = " ".join(text.lower().split())
        for status, aliases in STATUS_ALIASES.items():
            if any(alias in normalized for alias in aliases):
                return status
        return "unknown"


class AternosCog(commands.Cog, name="Aternos"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._starting = False

    @app_commands.command(
        name="startserver",
        description="Start the Minecraft Aternos server",
    )
    @app_commands.guild_only()
    async def startserver(self, interaction: discord.Interaction):
        if self._starting:
            await interaction.response.send_message(
                "Server is already starting. Please wait.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)
        self._starting = True

        try:
            await self._start_and_monitor(interaction)
        except Exception as e:
            logger.error("startserver error: %s", e, exc_info=True)
            try:
                await interaction.followup.send(embed=embeds.base_embed(
                    title="Could not start server",
                    description=f"```{e}```",
                    color_key="error",
                ))
            except Exception:
                pass
        finally:
            self._starting = False

    async def _start_and_monitor(self, interaction: discord.Interaction):
        ip = config.get("minecraft_server_ip", "coctackeegg.aternos.me")

        async with AternosBrowser() as aternos:
            await aternos.open_server()

            current_status = await aternos.status()
            logger.info("Aternos browser status: %s", current_status)

            if current_status == "online":
                embed = embeds.aternos_status_embed("online", ip)
                embed.description = f"Server is online. Connect: **`{ip}`**"
                await interaction.followup.send(embed=embed)
                return

            if current_status not in ("starting", "loading", "waiting"):
                await aternos.start()
                logger.info("Clicked Aternos Start in browser")

            msg = await interaction.followup.send(
                embed=embeds.aternos_status_embed("starting", ip)
            )

            elapsed = 0
            last_status = ""

            while elapsed < MAX_WAIT_TIME:
                await asyncio.sleep(POLL_INTERVAL)
                elapsed += POLL_INTERVAL

                try:
                    raw_status = await aternos.status()
                except Exception as e:
                    logger.warning("Browser poll error: %s", e)
                    continue

                if raw_status == last_status:
                    continue

                last_status = raw_status
                logger.info("Aternos browser poll status: %s", raw_status)

                try:
                    await msg.edit(embed=embeds.aternos_status_embed(raw_status, ip))
                except discord.HTTPException:
                    pass

                if raw_status == "online":
                    await self._announce_online(ip)
                    return

                if raw_status in ("offline", "error", "stopping"):
                    return

            try:
                await msg.edit(embed=embeds.base_embed(
                    title="Start timed out",
                    description=f"Server did not come online after {MAX_WAIT_TIME // 60} minutes.",
                    color_key="warning",
                ))
            except discord.HTTPException:
                pass

    async def _announce_online(self, ip: str) -> None:
        channel_id = config.get("discord_announce_channel_id", 0)
        if not channel_id:
            return

        ch = self.bot.get_channel(int(channel_id))
        if ch:
            await ch.send(embed=embeds.base_embed(
                title="Minecraft server is ONLINE",
                description=f"Connect: **`{ip}`** - use `/online` to see who is playing.",
                color_key="online",
            ))


async def setup(bot: commands.Bot):
    await bot.add_cog(AternosCog(bot))
