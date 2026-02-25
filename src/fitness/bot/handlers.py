"""
Telegram bot command and message handlers.

All handlers receive (update, context) from python-telegram-bot.
Bot data keys (set in build_bot_app):
  context.bot_data["engine"]   — SQLAlchemy engine
  context.bot_data["claude"]   — ClaudeClient instance
  context.bot_data["whisper"]  — WhisperClient instance (None if no OPENAI_API_KEY)

Chat data keys (persisted per-chat via PicklePersistence):
  context.chat_data["run_histories"]       — dict mapping activity_id → messages list
  context.chat_data["current_activity_id"] — int, the run currently being discussed
"""
import asyncio
import io
import logging
import traceback
from typing import Optional

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes
from sqlmodel import Session, select

logger = logging.getLogger(__name__)

from fitness.analysis.run_report import RunReport, build_run_report
from fitness.models.activity import Activity
from fitness.prompts.debrief import build_debrief_prompt, build_debrief_system_prompt
from fitness.prompts.trends import build_trends_prompt
from fitness.prompts.voice import build_voice_query_prompt
from fitness.prompts.charts import make_run_overview_chart


_TELEGRAM_MAX_LEN = 4096


def _get_run_histories(context: ContextTypes.DEFAULT_TYPE) -> dict:
    """Return the run_histories dict from chat_data, creating it if absent."""
    if "run_histories" not in context.chat_data:
        context.chat_data["run_histories"] = {}
    return context.chat_data["run_histories"]


async def _reply_long(update: Update, text: str) -> None:
    """Send text, splitting into ≤4096-char chunks if needed."""
    for i in range(0, len(text), _TELEGRAM_MAX_LEN):
        await update.message.reply_text(text[i : i + _TELEGRAM_MAX_LEN])


async def handle_lastrun(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /lastrun — fetch the most recent activity, run full analysis, send debrief + charts.
    """
    engine = context.bot_data["engine"]

    await update.message.reply_chat_action(ChatAction.TYPING)

    with Session(engine) as s:
        activity = s.exec(
            select(Activity).order_by(Activity.start_time_utc.desc())
        ).first()

    if not activity:
        await update.message.reply_text(
            "No activities found. Run /sync to pull your latest run from Garmin."
        )
        return

    await _send_run_debrief(update, context, activity.id, reflection=None)


async def handle_debrief(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /debrief [id] — debrief a specific activity by ID, or latest if no ID given.
    """
    engine = context.bot_data["engine"]
    text = update.message.text or ""
    parts = text.strip().split()

    activity_id: Optional[int] = None
    if len(parts) >= 2:
        try:
            activity_id = int(parts[1])
        except ValueError:
            await update.message.reply_text("Usage: /debrief [activity_id]")
            return

    if activity_id is None:
        # Use latest
        with Session(engine) as s:
            activity = s.exec(
                select(Activity).order_by(Activity.start_time_utc.desc())
            ).first()
        if not activity:
            await update.message.reply_text(
                "No activities found. Run /sync first."
            )
            return
        activity_id = activity.id

    try:
        await _send_run_debrief(update, context, activity_id, reflection=None)
    except ValueError as e:
        await update.message.reply_text(f"Activity not found: {e}")


async def handle_trends(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /trends — 30-day training summary via Claude.
    """
    engine = context.bot_data["engine"]
    claude = context.bot_data["claude"]

    await update.message.reply_chat_action(ChatAction.TYPING)

    with Session(engine) as s:
        activities = s.exec(
            select(Activity)
            .order_by(Activity.start_time_utc.desc())
            .limit(20)
        ).all()

    if not activities:
        await update.message.reply_text(
            "No data yet. Run /sync to pull your Garmin activities."
        )
        return

    prompt = build_trends_prompt(list(activities))
    response = await claude.complete(prompt)
    await _reply_long(update, response)


async def handle_sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /sync — trigger an on-demand Garmin sync in the background.
    """
    await update.message.reply_text(
        "Syncing your latest run from Garmin... I'll let you know when it's ready. "
        "This usually takes 1-2 minutes."
    )
    asyncio.create_task(_trigger_sync_background(context))


async def handle_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /clear — clear conversation history for the current run only.
    """
    activity_id = context.chat_data.get("current_activity_id")
    if activity_id is not None:
        run_histories = _get_run_histories(context)
        run_histories.pop(activity_id, None)
    await update.message.reply_text("Conversation for this run cleared.")


async def handle_clearall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /clearall — clear all run conversation histories.
    """
    context.chat_data["run_histories"] = {}
    await update.message.reply_text("All run conversation histories cleared.")


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Free-text messages — appended to current run's conversation history if one is active,
    otherwise falls back to single-turn with the most recent run report.
    """
    claude = context.bot_data["claude"]
    text = update.message.text or ""

    await update.message.reply_chat_action(ChatAction.TYPING)

    activity_id = context.chat_data.get("current_activity_id")
    system = build_debrief_system_prompt()

    if activity_id is not None:
        run_histories = _get_run_histories(context)
        history = run_histories.setdefault(activity_id, [])
        history.append({"role": "user", "content": text})
        response = await claude.complete_with_history(history, system_prompt=system)
        history.append({"role": "assistant", "content": response})
    else:
        # No active run — fall back to single-turn with most recent run context
        engine = context.bot_data["engine"]
        report: Optional[RunReport] = None
        with Session(engine) as s:
            activity = s.exec(
                select(Activity).order_by(Activity.start_time_utc.desc())
            ).first()
        if activity:
            try:
                report = build_run_report(activity.id, engine)
            except Exception:
                pass

        prompt = build_voice_query_prompt(text, report)
        response = await claude.complete(prompt, system_prompt=system)

    await _reply_long(update, response)


# ─── Internal helpers ─────────────────────────────────────────────────────────

async def _send_run_debrief(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    activity_id: int,
    reflection: Optional[str],
) -> None:
    """Build RunReport, send chart photo(s), then send Claude debrief text.

    Sets current_activity_id and manages per-run conversation history.
    If history already exists for this activity, appends to it (continues
    the prior conversation). Otherwise initializes from the debrief prompt.
    """
    engine = context.bot_data["engine"]
    claude = context.bot_data["claude"]

    await update.message.reply_chat_action(ChatAction.TYPING)

    report = build_run_report(activity_id, engine)

    # Send overview chart
    try:
        png_bytes, caption = make_run_overview_chart(report)
        await update.message.reply_photo(
            photo=io.BytesIO(png_bytes),
            caption=caption[:1024],  # Telegram caption limit
        )
    except Exception:
        pass  # Charts are best-effort; don't block the debrief

    # Set current run context
    context.chat_data["current_activity_id"] = activity_id
    run_histories = _get_run_histories(context)
    system = build_debrief_system_prompt()

    if activity_id in run_histories:
        # Continuing an existing conversation — send a fresh debrief prompt appended to history
        history = run_histories[activity_id]
        prompt = build_debrief_prompt(report, reflection=reflection)
        history.append({"role": "user", "content": prompt})
        response = await claude.complete_with_history(history, system_prompt=system, max_tokens=1500)
        history.append({"role": "assistant", "content": response})
    else:
        # First time debriefing this run — initialize history
        prompt = build_debrief_prompt(report, reflection=reflection)
        history = [{"role": "user", "content": prompt}]
        response = await claude.complete_with_history(history, system_prompt=system, max_tokens=1500)
        history.append({"role": "assistant", "content": response})
        run_histories[activity_id] = history

    await _reply_long(update, response)


async def _trigger_sync_background(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Background coroutine to sync Garmin — called from /sync handler."""
    from fitness.garmin.client import GarminClient
    from fitness.garmin.sync_service import GarminSyncService

    engine = context.bot_data["engine"]
    chat_id = context.bot_data.get("owner_chat_id")

    try:
        client = GarminClient()  # loads session from ~/.fitness/garmin_session/
        await client.connect()
        service = GarminSyncService(client=client, engine=engine)

        activities = await client.get_activities(start=0, limit=1)
        if activities:
            gid = str(activities[0].get("activityId", ""))
            await service.sync_activity(gid)
            if chat_id:
                await context.bot.send_message(chat_id=chat_id, text="✅ Sync complete!")
        else:
            if chat_id:
                await context.bot.send_message(chat_id=chat_id, text="No new activities found on Garmin.")
    except Exception as exc:
        logger.exception("Garmin sync failed")
        if chat_id:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Sync failed: {exc}",
            )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global PTB error handler — logs the exception and notifies the owner."""
    logger.exception("Unhandled exception", exc_info=context.error)

    chat_id = context.bot_data.get("owner_chat_id")
    if not chat_id:
        return

    tb = "".join(traceback.format_exception(type(context.error), context.error, context.error.__traceback__))
    # Telegram message limit is 4096 chars
    short_tb = tb[-3000:] if len(tb) > 3000 else tb
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"⚠️ Unhandled error:\n<pre>{short_tb}</pre>",
        parse_mode="HTML",
    )
