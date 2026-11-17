"""Application entry point for PS99 Clan Wars Monitor."""

import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from ps99_bot.config import Config
from ps99_bot.database import Database
from ps99_bot.monitor import WarMonitor
from ps99_bot.roblox import RobloxClient


class ClanWarsBot(commands.Bot):
    def __init__(self, config: Config):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.config = config
        self.database = Database(config.database_path)
        self.http_session = None
        self.roblox = None
        self.monitor = None

    async def setup_hook(self):
        timeout = aiohttp.ClientTimeout(total=15)
        self.http_session = aiohttp.ClientSession(timeout=timeout,
                                                  headers={"User-Agent": "PS99ClanWarsMonitor/1.0"})
        self.roblox = RobloxClient(self.http_session, self.config.presence_batch_size)
        self.monitor = WarMonitor(self.database, self.roblox, self.config.ps99_universe_id,
                                  self.config.poll_interval_seconds,
                                  self.config.disconnect_confirmation_checks,
                                  self.send_presence_notification)
        # Global sync makes commands available in every server the bot is installed in.
        await self.tree.sync()
        if self.database.is_war_active():
            logging.info("Resuming persisted active war after restart")
            self.monitor.start()

    async def close(self):
        if self.monitor:
            self.monitor.stop()
        if self.http_session:
            await self.http_session.close()
        self.database.close()
        await super().close()

    async def send_presence_notification(self, discord_user_id: int, reconnected: bool, username: str):
        channel = self.get_channel(self.config.notification_channel_id)
        if channel is None:
            channel = await self.fetch_channel(self.config.notification_channel_id)
        if reconnected:
            message = "✅ <@%s> (**%s**) is back in Pet Simulator 99." % (discord_user_id, username)
        else:
            message = "⚠️ <@%s> (**%s**) appears to have left Pet Simulator 99." % (discord_user_id, username)
        await channel.send(message, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))


def guild_only(interaction: discord.Interaction) -> bool:
    return interaction.guild is not None


def create_bot(config: Config) -> ClanWarsBot:
    bot = ClanWarsBot(config)

    @bot.tree.command(name="register", description="Link your Discord account to your Roblox username")
    @app_commands.describe(roblox_username="Your Roblox account username (not display name)")
    async def register(interaction: discord.Interaction, roblox_username: str):
        if not guild_only(interaction):
            await interaction.response.send_message("Use this command in your clan server.", ephemeral=True)
            return
        username = roblox_username.strip()
        if not 3 <= len(username) <= 20:
            await interaction.response.send_message("Enter a Roblox username between 3 and 20 characters.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            account = await bot.roblox.resolve_username(username)
            bot.database.register_player(interaction.user.id, int(account["id"]), account["name"])
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except Exception:
            logging.exception("Could not register Roblox account")
            await interaction.followup.send("Roblox could not be reached or registration failed. Please try again later.", ephemeral=True)
            return
        await interaction.followup.send("Registered **%s**. Your Roblox user ID is stored for war checks." % account["name"], ephemeral=True)

    @bot.tree.command(name="startwar", description="Start monitoring registered clan members")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def startwar(interaction: discord.Interaction):
        if not guild_only(interaction):
            await interaction.response.send_message("Use this command in your clan server.", ephemeral=True)
            return
        if bot.database.is_war_active():
            await interaction.response.send_message("War monitoring is already active.", ephemeral=True)
            return
        bot.database.set_war_active(True)
        bot.monitor.start()
        await interaction.response.send_message("War monitoring started for %d registered member(s)." % len(bot.database.list_players()))

    @bot.tree.command(name="endwar", description="Stop monitoring registered clan members")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def endwar(interaction: discord.Interaction):
        if not guild_only(interaction):
            await interaction.response.send_message("Use this command in your clan server.", ephemeral=True)
            return
        if not bot.database.is_war_active():
            await interaction.response.send_message("War monitoring is not active.", ephemeral=True)
            return
        bot.database.set_war_active(False)
        bot.monitor.stop()
        await interaction.response.send_message("War monitoring stopped.")

    @bot.tree.command(name="status", description="Show registered members and their detected status")
    async def status(interaction: discord.Interaction):
        if not guild_only(interaction):
            await interaction.response.send_message("Use this command in your clan server.", ephemeral=True)
            return
        players = bot.database.list_players()
        if not players:
            await interaction.response.send_message("No members are registered yet.", ephemeral=True)
            return
        labels = {"ps99": "In Pet Simulator 99", "other": "Online elsewhere", "offline": "Offline", "unknown": "Unknown / awaiting check"}
        lines = ["**%s** — %s" % (p["roblox_username"], labels.get(p["status"], "Unknown")) for p in players]
        content = "War monitoring: **%s**\n%s" % ("active" if bot.database.is_war_active() else "stopped", "\n".join(lines))
        # Discord message limit is 2000 characters; keep the command useful for large clans.
        if len(content) > 1900:
            content = content[:1850] + "\n… (member list truncated)"
        await interaction.response.send_message(content, ephemeral=True)

    @bot.tree.error
    async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            message = "Only server administrators can use this command."
        else:
            logging.error("Slash command failed", exc_info=(type(error), error, error.__traceback__))
            message = "The command failed. Check the bot logs and try again."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    return bot


def main():
    config = Config.from_env()
    logging.basicConfig(level=getattr(logging, config.log_level, logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    bot = create_bot(config)
    bot.run(config.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
