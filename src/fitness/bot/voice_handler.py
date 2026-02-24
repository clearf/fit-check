"""
Telegram voice message handler.

Flow:
  1. Download voice OGG from Telegram
  2. Save to temp file
  3. Transcribe via Whisper
  4. Build prompt with transcript + most recent run report
  5. Send to Claude → reply with debrief
  6. Delete temp file
"""
import io
import tempfile
from pathlib import Path
from typing import Optional

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes
from sqlmodel import Session, select

from fitness.analysis.run_report import RunReport, build_run_report
from fitness.models.activity import Activity
from fitness.prompts.debrief import build_debrief_system_prompt
from fitness.prompts.voice import build_voice_query_prompt
from fitness.prompts.charts import make_run_overview_chart


async def save_voice_to_temp(update: Update) -> Path:
    """Download voice message OGG bytes to a temp file and return the path."""
    voice = update.message.voice
    voice_file = await voice.get_file()
    audio_bytes = await voice_file.download_as_bytearray()

    tmp = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
    tmp.write(bytes(audio_bytes))
    tmp.close()
    return Path(tmp.name)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle an incoming voice message."""
    whisper = context.bot_data.get("whisper")
    if whisper is None:
        await update.message.reply_text(
            "Voice messages require a Whisper API key (OPENAI_API_KEY). "
            "Not configured on this instance."
        )
        return

    engine = context.bot_data["engine"]
    claude = context.bot_data["claude"]

    await update.message.reply_chat_action(ChatAction.TYPING)

    # Transcribe
    tmp_path = await save_voice_to_temp(update)
    try:
        transcript = await whisper.transcribe(tmp_path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass

    # Build run context
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

    # Send chart if we have a run to contextualise
    if report:
        try:
            png_bytes, caption = make_run_overview_chart(report)
            await update.message.reply_photo(
                photo=io.BytesIO(png_bytes),
                caption=f"Run context for: \"{transcript[:80]}\"",
            )
        except Exception:
            pass

    prompt = build_voice_query_prompt(transcript, report)
    system = build_debrief_system_prompt()

    activity_id = context.chat_data.get("current_activity_id")
    if activity_id is not None:
        from fitness.bot.handlers import _get_run_histories
        run_histories = _get_run_histories(context)
        history = run_histories.setdefault(activity_id, [])
        history.append({"role": "user", "content": prompt})
        response = await claude.complete_with_history(history, system_prompt=system, max_tokens=1500)
        history.append({"role": "assistant", "content": response})
    else:
        response = await claude.complete(prompt, system_prompt=system, max_tokens=1500)

    await update.message.reply_text(response)
