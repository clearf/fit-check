"""
Main entrypoint: starts Telegram bot + APScheduler in one process.

FastAPI runs separately under uvicorn (for the webhook endpoint).

Usage:
    python -m fitness           # starts bot + scheduler
    uvicorn fitness.api.main:app --host 0.0.0.0 --port 8000  # starts API
"""
import asyncio
import logging

from fitness.ai.claude_client import ClaudeClient
from fitness.ai.whisper_client import WhisperClient
from fitness.bot.app import build_bot_app
from fitness.config import get_settings
from fitness.db.engine import get_engine
from fitness.scheduler.jobs import build_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    engine = get_engine()

    # AI clients
    claude = ClaudeClient(api_key=settings.anthropic_api_key)
    whisper = (
        WhisperClient(api_key=settings.openai_api_key)
        if settings.openai_api_key
        else None
    )

    # Scheduler
    scheduler = build_scheduler(engine)
    scheduler.start()
    logger.info("Scheduler started (nightly sync at %02d:00 UTC)", settings.garmin_sync_hour)

    # Bot
    app = build_bot_app(
        token=settings.telegram_bot_token,
        engine=engine,
        claude=claude,
        whisper=whisper,
    )

    logger.info("Starting Telegram bot...")
    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("Bot is running. Press Ctrl+C to stop.")

        try:
            # Keep running until interrupted
            await asyncio.Event().wait()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutting down...")
        finally:
            await app.updater.stop()
            await app.stop()
            scheduler.shutdown()
            logger.info("Goodbye.")


if __name__ == "__main__":
    asyncio.run(main())
