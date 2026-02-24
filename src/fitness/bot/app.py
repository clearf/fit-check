"""
Telegram bot application factory.

Builds and configures the python-telegram-bot Application with all
handlers registered.
"""
from pathlib import Path

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    PicklePersistence,
    filters,
)

from fitness.bot.handlers import (
    handle_lastrun,
    handle_debrief,
    handle_trends,
    handle_sync,
    handle_clear,
    handle_clearall,
    handle_text_message,
    error_handler,
)
from fitness.bot.voice_handler import handle_voice


def build_bot_app(
    token: str,
    engine,
    claude,
    whisper=None,
    owner_chat_id: int = None,
) -> Application:
    """
    Build and return the PTB Application.

    Args:
        token: Telegram bot token.
        engine: SQLAlchemy engine (SQLModel).
        claude: ClaudeClient instance.
        whisper: WhisperClient instance (optional — voice disabled if None).
        owner_chat_id: Telegram chat ID to send error notifications to.

    Returns:
        Configured Application (not yet started).
    """
    persistence_path = Path.home() / ".fitness" / "chat_persistence.pickle"
    persistence_path.parent.mkdir(parents=True, exist_ok=True)
    persistence = PicklePersistence(
        filepath=persistence_path,
        store_bot_data=False,
        store_user_data=False,
    )

    app = Application.builder().token(token).persistence(persistence).build()

    # Store shared resources in bot_data so handlers can access them
    app.bot_data["engine"] = engine
    app.bot_data["claude"] = claude
    app.bot_data["whisper"] = whisper
    app.bot_data["owner_chat_id"] = owner_chat_id

    # Command handlers
    app.add_handler(CommandHandler("lastrun", handle_lastrun))
    app.add_handler(CommandHandler("debrief", handle_debrief))
    app.add_handler(CommandHandler("trends", handle_trends))
    app.add_handler(CommandHandler("sync", handle_sync))
    app.add_handler(CommandHandler("clear", handle_clear))
    app.add_handler(CommandHandler("clearall", handle_clearall))

    # Voice messages
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    # Free-text messages (reflections / questions)
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
    )

    # Global error handler — sends tracebacks to owner via Telegram
    app.add_error_handler(error_handler)

    return app
