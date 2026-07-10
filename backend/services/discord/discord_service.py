"""Discord bot service for Strategy Lab notifications and commands."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from .commands import DiscordCommandHandlers
from .notification_hooks import DiscordNotificationHooks
from .quant_commands import QuantCommandHandlers

if TYPE_CHECKING:
    from ..settings_store import SettingsStore

logger = logging.getLogger(__name__)


class DiscordBotService:
    """Discord bot service for notifications and commands."""

    def __init__(
        self,
        settings_store: SettingsStore,
    ) -> None:
        """Initialize Discord bot service.

        Args:
            settings_store: Settings store for loading Discord configuration
        """
        self.settings_store = settings_store
        self.client: discord.Client | None = None
        self.tree: app_commands.CommandTree | None = None
        self._ready_event = asyncio.Event()
        self._task: asyncio.Task | None = None
        
        # Initialize command handlers and notification hooks
        self.command_handlers = DiscordCommandHandlers(self)
        self.notification_hooks = DiscordNotificationHooks(self)
        self.quant_command_handlers = QuantCommandHandlers(self)

    async def start(self) -> None:
        """Start the Discord bot."""
        settings = self.settings_store.load()

        if not settings.discord_enabled or not settings.discord_bot_token:
            logger.info("Discord integration is disabled or token not configured")
            return

        try:
            # Define intents
            intents = discord.Intents.default()
            intents.message_content = True
            intents.guilds = True

            # Create client
            self.client = discord.Client(intents=intents)

            # Create command tree
            self.tree = app_commands.CommandTree(self.client)

            # Setup event handlers
            self.client.event(self._on_ready)
            self.client.event(self._on_message)

            # Start bot in background task
            self._task = asyncio.create_task(self._run_bot(settings.discord_bot_token))

            # Wait for bot to be ready
            try:
                await asyncio.wait_for(self._ready_event.wait(), timeout=30.0)
                logger.info("Discord bot connected successfully")
            except asyncio.TimeoutError:
                logger.warning("Discord bot connection timed out after 30 seconds")

        except Exception as e:
            logger.exception(f"Failed to start Discord bot: {e}")

    async def _run_bot(self, token: str) -> None:
        """Run the Discord bot."""
        try:
            await self.client.start(token)
        except Exception as e:
            logger.exception(f"Discord bot error: {e}")
            self._ready_event.set()  # Unblock even on failure

    async def _on_ready(self) -> None:
        """Handle bot ready event."""
        logger.info(f"Discord bot logged in as {self.client.user}")
        self._ready_event.set()

        # Sync commands with Discord
        try:
            settings = self.settings_store.load()
            if settings.discord_server_id:
                guild = discord.Object(id=int(settings.discord_server_id))
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                logger.info(f"Synced commands to server {settings.discord_server_id}")
            else:
                await self.tree.sync()
                logger.info("Synced global commands")
        except Exception as e:
            logger.exception(f"Failed to sync Discord commands: {e}")

    async def _on_message(self, message: discord.Message) -> None:
        """Handle incoming messages."""

        # Log messages for debugging
        logger.debug(f"Received message from {message.author}: {message.content[:100]}")

    async def stop(self) -> None:
        """Stop the Discord bot."""
        if self.client:
            try:
                await self.client.close()
                logger.info("Discord bot stopped")
            except Exception as e:
                logger.exception(f"Error stopping Discord bot: {e}")

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def send_message(
        self,
        content: str,
        channel_id: str | None = None,
        embed: discord.Embed | None = None,
    ) -> bool:
        """Send a message to a Discord channel.

        Args:
            content: Message content
            channel_id: Channel ID (uses configured notification channel if None)
            embed: Discord embed object

        Returns:
            True if message sent successfully, False otherwise
        """
        if not self.client or not self.client.is_ready():
            logger.warning("Discord bot not ready, cannot send message")
            return False

        settings = self.settings_store.load()
        target_channel_id = channel_id or settings.discord_notification_channel_id

        if not target_channel_id:
            logger.warning("No Discord channel configured for notifications")
            return False

        try:
            channel = self.client.get_channel(int(target_channel_id))
            if not channel:
                logger.error(f"Could not find Discord channel {target_channel_id}")
                return False

            if embed:
                await channel.send(content=content, embed=embed)
            else:
                await channel.send(content=content)

            logger.debug(f"Sent message to Discord channel {target_channel_id}")
            return True

        except Exception as e:
            logger.exception(f"Failed to send Discord message: {e}")
            return False

    async def send_embed(
        self,
        title: str,
        description: str,
        color: int = 0x00FF00,
        fields: list[tuple[str, str, bool]] | None = None,
        channel_id: str | None = None,
    ) -> bool:
        """Send an embedded message to Discord.

        Args:
            title: Embed title
            description: Embed description
            color: Embed color (hex)
            fields: List of (name, value, inline) tuples
            channel_id: Channel ID (uses configured notification channel if None)

        Returns:
            True if message sent successfully, False otherwise
        """
        embed = discord.Embed(title=title, description=description, color=color)

        if fields:
            for name, value, inline in fields:
                embed.add_field(name=name, value=value, inline=inline)

        return await self.send_message(channel_id=channel_id, embed=embed)

    def is_ready(self) -> bool:
        """Check if the bot is ready."""
        return self.client is not None and self.client.is_ready()

    def get_user_permission(self, user_id: int) -> bool:
        """Check if a user has admin permissions.

        Args:
            user_id: Discord user ID

        Returns:
            True if user is authorized, False otherwise
        """
        settings = self.settings_store.load()
        return str(user_id) == settings.discord_user_id

    async def create_text_channel(self, name: str) -> dict | None:
        """Create a text channel in the Discord server.

        Args:
            name: Channel name

        Returns:
            Dict with channel info (id, name, guild_id) or None if failed
        """
        if not self.client or not self.client.is_ready():
            logger.error("Discord bot not ready, cannot create channel")
            return None

        settings = self.settings_store.load()
        if not settings.discord_server_id:
            logger.error("No Discord server ID configured")
            return None

        try:
            guild = self.client.get_guild(int(settings.discord_server_id))
            if not guild:
                logger.error(f"Could not find guild with ID {settings.discord_server_id}")
                return None

            # Check bot permissions
            bot_member = guild.me
            if not bot_member.guild_permissions.manage_channels:
                logger.error("Bot does not have manage_channels permission")
                return None

            # Create channel
            channel = await guild.create_text_channel(name)
            logger.info(f"Created channel {name} with ID {channel.id}")

            return {
                "id": str(channel.id),
                "name": channel.name,
                "guild_id": str(guild.id),
            }

        except Exception as e:
            logger.exception(f"Failed to create channel {name}: {e}")
            return None

    async def delete_channel(self, channel_id: str) -> bool:
        """Delete a Discord channel.

        Args:
            channel_id: Channel ID to delete

        Returns:
            True if deleted successfully, False otherwise
        """
        if not self.client or not self.client.is_ready():
            logger.error("Discord bot not ready, cannot delete channel")
            return False

        try:
            channel = self.client.get_channel(int(channel_id))
            if not channel:
                logger.error(f"Could not find channel with ID {channel_id}")
                return False

            await channel.delete()
            logger.info(f"Deleted channel {channel_id}")
            return True

        except Exception as e:
            logger.exception(f"Failed to delete channel {channel_id}: {e}")
            return False
