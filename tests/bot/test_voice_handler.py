"""Tests for Telegram voice message handler."""
import io
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from fitness.models.activity import Activity, ActivityDatapoint
from fitness.bot.voice_handler import handle_voice


@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(name="seeded_engine")
def seeded_engine_fixture(engine):
    with Session(engine) as s:
        act = Activity(
            garmin_activity_id="77777",
            name="Morning Run",
            activity_type="running",
            start_time_utc=datetime(2025, 1, 15, 7, 30),
            duration_seconds=3600.0,
            distance_meters=8046.72,
            avg_hr=148.0,
        )
        s.add(act)
        s.commit()
        s.refresh(act)
        speed = 1000.0 / 450.0
        for i in range(200):
            t = i * 5
            s.add(ActivityDatapoint(
                activity_id=act.id,
                user_id=1,
                elapsed_seconds=t,
                heart_rate=148,
                speed_ms=speed,
                pace_seconds_per_km=450.0,
                elevation_meters=100.0,
                cadence_spm=162,
                distance_meters=float(t) * speed,
            ))
        s.commit()
    return engine


def make_voice_update(audio_bytes: bytes = b"fake_audio") -> MagicMock:
    update = MagicMock()
    update.effective_user.id = 1
    update.message.reply_text = AsyncMock()
    update.message.reply_chat_action = AsyncMock()

    # Mock voice attachment
    voice = MagicMock()
    voice_file = AsyncMock()
    voice_file.download_as_bytearray = AsyncMock(return_value=bytearray(audio_bytes))
    voice.get_file = AsyncMock(return_value=voice_file)
    update.message.voice = voice
    update.message.text = None
    return update


def make_context(engine=None, claude=None, whisper=None):
    ctx = MagicMock()
    ctx.chat_data = {}
    ctx.bot_data = {
        "engine": engine,
        "claude": claude or MagicMock(
            complete=AsyncMock(return_value="Sounds like a great run!"),
            complete_with_history=AsyncMock(return_value="Sounds like a great run!"),
        ),
        "whisper": whisper or AsyncMock(transcribe=AsyncMock(return_value="I felt great on that run")),
    }
    return ctx


class TestHandleVoice:
    @pytest.mark.asyncio
    async def test_transcribes_audio(self, seeded_engine):
        update = make_voice_update()
        whisper = AsyncMock(transcribe=AsyncMock(return_value="Felt strong today"))
        ctx = make_context(engine=seeded_engine, whisper=whisper)

        with patch("fitness.bot.voice_handler.save_voice_to_temp", new=AsyncMock(return_value=Path("/tmp/fake.ogg"))):
            with patch("pathlib.Path.unlink"):
                await handle_voice(update, ctx)

        whisper.transcribe.assert_called_once()

    @pytest.mark.asyncio
    async def test_calls_claude_with_transcript(self, seeded_engine):
        update = make_voice_update()
        claude = MagicMock(
            complete=AsyncMock(return_value="Great effort!"),
            complete_with_history=AsyncMock(return_value="Great effort!"),
        )
        whisper = AsyncMock(transcribe=AsyncMock(return_value="Legs felt heavy"))
        ctx = make_context(engine=seeded_engine, claude=claude, whisper=whisper)

        with patch("fitness.bot.voice_handler.save_voice_to_temp", new=AsyncMock(return_value=Path("/tmp/fake.ogg"))):
            with patch("pathlib.Path.unlink"):
                await handle_voice(update, ctx)

        # Claude must receive a prompt that includes the transcript
        prompt_arg = claude.complete.call_args[0][0]
        assert "heavy" in prompt_arg or "Legs" in prompt_arg

    @pytest.mark.asyncio
    async def test_replies_with_claude_response(self, seeded_engine):
        update = make_voice_update()
        ctx = make_context(engine=seeded_engine)

        with patch("fitness.bot.voice_handler.save_voice_to_temp", new=AsyncMock(return_value=Path("/tmp/fake.ogg"))):
            with patch("pathlib.Path.unlink"):
                await handle_voice(update, ctx)

        update.message.reply_text.assert_called()

    @pytest.mark.asyncio
    async def test_no_whisper_client_replies_error(self, engine):
        update = make_voice_update()
        ctx = make_context(engine=engine, whisper=None)
        ctx.bot_data["whisper"] = None

        await handle_voice(update, ctx)
        text = update.message.reply_text.call_args[0][0]
        assert "voice" in text.lower() or "whisper" in text.lower() or "not" in text.lower()
