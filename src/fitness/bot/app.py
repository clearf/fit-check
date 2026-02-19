"""
Telegram bot application factory.

Builds and configures the python-telegram-bot Application with all
handlers registered.
"""
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from fitness.bot.handlers import (
    handle_lastrun,
    handle_debrief,
    handle_trends,
    handle_sync,
    handle_text_message,
)
from fitness.bot.voice_handler import handle_voice


def build_bot_app(
    token: str,
    engine,
    claude,
    whisper=None,
) -> Application:
    """
    Build and return the PTB Application.

    Args:
        token: Telegram bot token.
        engine: SQLAlchemy engine (SQLModel).
        claude: ClaudeClient instance.
        whisper: WhisperClient instance (optional — voice disabled if None).

    Returns:
        Configured Application (not yet started).
    """
    app = Application.builder().token(token).build()

    # Store shared resources in bot_data so handlers can access them
    app.bot_data["engine"] = engine
    app.bot_data["claude"] = claude
    app.bot_data["whisper"] = whisper

    # Command handlers
    app.add_handler(CommandHandler("lastrun", handle_lastrun))
    app.add_handler(CommandHandler("debrief", handle_debrief))
    app.add_handler(CommandHandler("trends", handle_trends))
    app.add_handler(CommandHandler("sync", handle_sync))

    # Voice messages
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    # Free-text messages (reflections / questions)
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
    )

    return app
