"""Async Claude API wrapper."""
import asyncio
from typing import Optional

import anthropic


class ClaudeClient:
    """Thin async wrapper over the Anthropic SDK."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-5"):
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    async def complete(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1500,
    ) -> str:
        """
        Send a message to Claude and return the response text.
        Runs the sync SDK call in a thread pool executor.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._complete_sync(user_prompt, system_prompt, max_tokens),
        )

    async def complete_with_history(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        max_tokens: int = 1500,
    ) -> str:
        """
        Send a multi-turn conversation to Claude and return the response text.
        messages is a list of {"role": "user"|"assistant", "content": "..."} dicts.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._complete_with_history_sync(messages, system_prompt, max_tokens),
        )

    def _complete_sync(
        self,
        user_prompt: str,
        system_prompt: Optional[str],
        max_tokens: int,
    ) -> str:
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        response = self._client.messages.create(**kwargs)
        return response.content[0].text

    def _complete_with_history_sync(
        self,
        messages: list[dict],
        system_prompt: Optional[str],
        max_tokens: int,
    ) -> str:
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        response = self._client.messages.create(**kwargs)
        return response.content[0].text
