"""
Main entrypoint: starts Telegram bot + APScheduler in one process.

FastAPI runs separately under uvicorn (for the webhook endpoint).

Usage:
    python -m fitness setup         # one-time Garmin auth setup
    python -m fitness               # starts bot + scheduler
    uvicorn fitness.api.main:app --host 0.0.0.0 --port 8000  # starts API
"""
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def _run_setup() -> None:
    from fitness.scripts.setup import run_setup
    run_setup()


async def _run_bot() -> None:
    from fitness.ai.claude_client import ClaudeClient
    from fitness.ai.whisper_client import WhisperClient
    from fitness.bot.app import build_bot_app
    from fitness.config import get_settings
    from fitness.db.engine import get_engine
    from fitness.garmin.auth import GarminAuth, NoSessionError, SessionExpiredError
    from fitness.scheduler.jobs import build_scheduler

    settings = get_settings()
    engine = get_engine()

    # Check Garmin session before starting
    auth = GarminAuth()
    if not auth.has_session():
        logger.error(
            "No Garmin session found. Run `python -m fitness setup` first."
        )
        sys.exit(1)

    # AI clients
    claude = ClaudeClient(api_key=settings.anthropic_api_key)
    whisper = (
        WhisperClient(api_key=settings.openai_api_key)
        if settings.openai_api_key
        else None
    )
    if not whisper:
        logger.info("OPENAI_API_KEY not set — voice messages disabled.")

    # Scheduler
    scheduler = build_scheduler(engine)
    scheduler.start()
    logger.info(
        "Scheduler started (nightly sync at %02d:00 UTC)",
        settings.garmin_sync_hour,
    )

    # Bot
    app = build_bot_app(
        token=settings.telegram_bot_token,
        engine=engine,
        claude=claude,
        whisper=whisper,
        owner_chat_id=settings.telegram_allowed_user_id,
    )

    logger.info("Starting Telegram bot...")
    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("Bot is running. Press Ctrl+C to stop.")

        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutting down...")
        finally:
            await app.updater.stop()
            await app.stop()
            scheduler.shutdown()
            logger.info("Goodbye.")


if __name__ == "__main__":
    # Dispatch on first argument: `python -m fitness setup` or just `python -m fitness`
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        _run_setup()
    else:
        asyncio.run(_run_bot())
