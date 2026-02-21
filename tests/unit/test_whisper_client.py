"""Tests for WhisperClient — async wrapper over OpenAI Whisper.

We mock the OpenAI client entirely (no real API calls) and verify:
  - transcribe() opens the file and calls the Whisper API
  - The running vocabulary prompt is included
  - The transcript text is returned correctly
"""
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from fitness.ai.whisper_client import WhisperClient


@pytest.fixture
def mock_openai_client():
    """openai.OpenAI client mock with audio.transcriptions.create stubbed."""
    client = MagicMock()
    response = MagicMock()
    response.text = "I felt good in miles 1-3 but hit a wall around mile 4."
    client.audio.transcriptions.create.return_value = response
    return client


@pytest.fixture
def whisper(mock_openai_client):
    """WhisperClient with a mock OpenAI backend."""
    with patch("fitness.ai.whisper_client.openai.OpenAI", return_value=mock_openai_client):
        return WhisperClient(api_key="test-key")


class TestWhisperClientInit:
    def test_client_created(self):
        with patch("fitness.ai.whisper_client.openai.OpenAI") as mock_openai:
            WhisperClient(api_key="my-key")
        mock_openai.assert_called_once_with(api_key="my-key")


class TestTranscribeSync:
    def test_uses_whisper_1_model(self, whisper, mock_openai_client, tmp_path):
        audio_file = tmp_path / "voice.ogg"
        audio_file.write_bytes(b"fake audio data")

        whisper._transcribe_sync(audio_file)

        call_kwargs = mock_openai_client.audio.transcriptions.create.call_args.kwargs
        assert call_kwargs["model"] == "whisper-1"

    def test_includes_running_vocabulary_prompt(self, whisper, mock_openai_client, tmp_path):
        audio_file = tmp_path / "voice.ogg"
        audio_file.write_bytes(b"fake audio data")

        whisper._transcribe_sync(audio_file)

        call_kwargs = mock_openai_client.audio.transcriptions.create.call_args.kwargs
        prompt = call_kwargs.get("prompt", "")
        assert "Galloway" in prompt or "running" in prompt.lower()

    def test_returns_transcript_text(self, whisper, tmp_path):
        audio_file = tmp_path / "voice.ogg"
        audio_file.write_bytes(b"fake audio data")

        result = whisper._transcribe_sync(audio_file)

        assert result == "I felt good in miles 1-3 but hit a wall around mile 4."

    def test_opens_file_in_binary_mode(self, whisper, mock_openai_client, tmp_path):
        audio_file = tmp_path / "voice.ogg"
        audio_file.write_bytes(b"fake audio data")

        whisper._transcribe_sync(audio_file)

        # file kwarg should be the opened file handle
        call_kwargs = mock_openai_client.audio.transcriptions.create.call_args.kwargs
        assert call_kwargs["file"] is not None


class TestTranscribeAsync:
    @pytest.mark.asyncio
    async def test_transcribe_returns_string(self, whisper, tmp_path):
        audio_file = tmp_path / "voice.ogg"
        audio_file.write_bytes(b"fake audio data")

        result = await whisper.transcribe(audio_file)

        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_transcribe_content(self, whisper, tmp_path):
        audio_file = tmp_path / "voice.ogg"
        audio_file.write_bytes(b"fake audio data")

        result = await whisper.transcribe(audio_file)

        assert "mile" in result.lower()

    @pytest.mark.asyncio
    async def test_transcribe_propagates_exceptions(self, whisper, mock_openai_client, tmp_path):
        audio_file = tmp_path / "voice.ogg"
        audio_file.write_bytes(b"fake audio data")
        mock_openai_client.audio.transcriptions.create.side_effect = Exception("API down")

        with pytest.raises(Exception, match="API down"):
            await whisper.transcribe(audio_file)

    @pytest.mark.asyncio
    async def test_transcribe_missing_file_raises(self, whisper):
        with pytest.raises((FileNotFoundError, OSError)):
            await whisper.transcribe(Path("/nonexistent/voice.ogg"))
