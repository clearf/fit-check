"""Async OpenAI Whisper wrapper for voice transcription."""
import asyncio
from pathlib import Path

import openai

from fitness.prompts.voice import build_whisper_prompt


class WhisperClient:
    """Transcribes voice messages via OpenAI Whisper."""

    def __init__(self, api_key: str):
        self._client = openai.OpenAI(api_key=api_key)

    async def transcribe(self, audio_path: Path) -> str:
        """
        Transcribe an audio file. Returns the transcript string.
        Runs the sync OpenAI call in a thread pool executor.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._transcribe_sync(audio_path),
        )

    def _transcribe_sync(self, audio_path: Path) -> str:
        with open(audio_path, "rb") as f:
            response = self._client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                prompt=build_whisper_prompt(),
            )
        return response.text
