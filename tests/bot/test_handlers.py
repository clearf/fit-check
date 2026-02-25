"""Tests for Telegram bot command handlers."""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from fitness.models.activity import Activity, ActivityDatapoint
from fitness.bot.handlers import (
    handle_lastrun,
    handle_debrief,
    handle_trends,
    handle_sync,
    handle_text_message,
)


# ─── In-memory DB ─────────────────────────────────────────────────────────────

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
    """Engine with one activity and 200 datapoints."""
    with Session(engine) as s:
        act = Activity(
            garmin_activity_id="55555",
            name="Morning Run",
            activity_type="running",
            start_time_utc=datetime(2025, 1, 15, 7, 30),
            duration_seconds=3600.0,
            distance_meters=8046.72,
            avg_hr=148.0,
            max_hr=172.0,
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


# ─── PTB Update mock helper ───────────────────────────────────────────────────

def make_update(text: str = "", user_id: int = 1) -> MagicMock:
    """Build a minimal python-telegram-bot Update mock."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.message.reply_photo = AsyncMock()
    update.message.reply_chat_action = AsyncMock()
    update.message.voice = None
    return update


def make_context(engine=None, claude=None, whisper=None) -> MagicMock:
    """Build a minimal PTB context mock with our custom bot_data."""
    ctx = MagicMock()
    ctx.chat_data = {}
    ctx.bot_data = {
        "engine": engine,
        "claude": claude or MagicMock(
            complete=AsyncMock(return_value="Great run!"),
            complete_with_history=AsyncMock(return_value="Great run!"),
        ),
        "whisper": whisper,
    }
    return ctx


# ─── Tests ───────────────────────────────────────────────────────────────────

class TestHandleLastRun:
    @pytest.mark.asyncio
    async def test_replies_when_activity_exists(self, seeded_engine):
        update = make_update()
        ctx = make_context(engine=seeded_engine)
        await handle_lastrun(update, ctx)
        update.message.reply_text.assert_called()

    @pytest.mark.asyncio
    async def test_replies_no_activity_when_empty(self, engine):
        update = make_update()
        ctx = make_context(engine=engine)
        await handle_lastrun(update, ctx)
        call_args = update.message.reply_text.call_args[0][0]
        assert "no" in call_args.lower() or "sync" in call_args.lower()

    @pytest.mark.asyncio
    async def test_sends_chart_photo(self, seeded_engine):
        update = make_update()
        ctx = make_context(engine=seeded_engine)
        await handle_lastrun(update, ctx)
        # Chart should be sent as photo
        update.message.reply_photo.assert_called()

    @pytest.mark.asyncio
    async def test_claude_is_called(self, seeded_engine):
        update = make_update()
        claude = MagicMock(
            complete=AsyncMock(return_value="Nice run!"),
            complete_with_history=AsyncMock(return_value="Nice run!"),
        )
        ctx = make_context(engine=seeded_engine, claude=claude)
        await handle_lastrun(update, ctx)
        claude.complete_with_history.assert_called_once()


class TestHandleDebrief:
    @pytest.mark.asyncio
    async def test_debrief_with_valid_id(self, seeded_engine):
        # Get the activity id
        with Session(seeded_engine) as s:
            act = s.exec(__import__("sqlmodel").select(Activity)).first()

        update = make_update(text=f"/debrief {act.id}")
        ctx = make_context(engine=seeded_engine)
        await handle_debrief(update, ctx)
        update.message.reply_text.assert_called()

    @pytest.mark.asyncio
    async def test_debrief_invalid_id_replies_error(self, engine):
        update = make_update(text="/debrief 99999")
        ctx = make_context(engine=engine)
        await handle_debrief(update, ctx)
        call_args = update.message.reply_text.call_args[0][0]
        assert "not found" in call_args.lower() or "error" in call_args.lower()

    @pytest.mark.asyncio
    async def test_debrief_no_id_uses_latest(self, seeded_engine):
        update = make_update(text="/debrief")
        ctx = make_context(engine=seeded_engine)
        await handle_debrief(update, ctx)
        update.message.reply_text.assert_called()


class TestHandleTrends:
    @pytest.mark.asyncio
    async def test_trends_replies(self, seeded_engine):
        update = make_update()
        claude = AsyncMock(complete=AsyncMock(return_value="Good training week!"))
        ctx = make_context(engine=seeded_engine, claude=claude)
        await handle_trends(update, ctx)
        update.message.reply_text.assert_called()
        claude.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_trends_no_data_message(self, engine):
        update = make_update()
        ctx = make_context(engine=engine)
        await handle_trends(update, ctx)
        call_args = update.message.reply_text.call_args[0][0]
        assert "no" in call_args.lower() or "data" in call_args.lower() or "sync" in call_args.lower()


class TestHandleSync:
    @pytest.mark.asyncio
    async def test_sync_acknowledges(self):
        update = make_update()
        ctx = make_context()
        with patch("fitness.bot.handlers._trigger_sync_background", new=AsyncMock()):
            await handle_sync(update, ctx)
        update.message.reply_text.assert_called()

    @pytest.mark.asyncio
    async def test_sync_reply_contains_status_info(self):
        update = make_update()
        ctx = make_context()
        with patch("fitness.bot.handlers._trigger_sync_background", new=AsyncMock()):
            await handle_sync(update, ctx)
        text = update.message.reply_text.call_args[0][0]
        assert len(text) > 0


class TestHandleTextMessage:
    @pytest.mark.asyncio
    async def test_text_message_gets_claude_reply(self, seeded_engine):
        update = make_update(text="How was my run today?")
        claude = AsyncMock(complete=AsyncMock(return_value="Your run was great!"))
        ctx = make_context(engine=seeded_engine, claude=claude)
        await handle_text_message(update, ctx)
        update.message.reply_text.assert_called()
        claude.complete.assert_called_once()
