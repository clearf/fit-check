"""Tests for ClaudeClient — async wrapper over the Anthropic SDK.

We mock the Anthropic client entirely (no real API calls) and verify:
  - _complete_sync builds the correct payload
  - system_prompt is only included when provided
  - complete() delegates to the thread executor and returns text
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fitness.ai.claude_client import ClaudeClient


@pytest.fixture
def mock_anthropic_client():
    """Anthropic.Anthropic client mock with messages.create stubbed."""
    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(text="Great run! Your HR drift was minimal.")]
    client.messages.create.return_value = response
    return client


@pytest.fixture
def claude(mock_anthropic_client):
    """ClaudeClient with a mock Anthropic backend."""
    with patch("fitness.ai.claude_client.anthropic.Anthropic", return_value=mock_anthropic_client):
        return ClaudeClient(api_key="test-key", model="claude-sonnet-4-5")


class TestClaudeClientInit:
    def test_model_stored(self, claude):
        assert claude.model == "claude-sonnet-4-5"

    def test_default_model_is_sonnet(self):
        with patch("fitness.ai.claude_client.anthropic.Anthropic"):
            c = ClaudeClient(api_key="k")
        assert "sonnet" in c.model.lower()


class TestCompleteSyncPayload:
    def test_user_message_included(self, claude, mock_anthropic_client):
        claude._complete_sync("Analyse my run", system_prompt=None, max_tokens=500)
        call_kwargs = mock_anthropic_client.messages.create.call_args.kwargs
        assert call_kwargs["messages"] == [{"role": "user", "content": "Analyse my run"}]

    def test_system_prompt_included_when_provided(self, claude, mock_anthropic_client):
        claude._complete_sync("q", system_prompt="Be a coach", max_tokens=100)
        call_kwargs = mock_anthropic_client.messages.create.call_args.kwargs
        assert call_kwargs.get("system") == "Be a coach"

    def test_system_prompt_omitted_when_none(self, claude, mock_anthropic_client):
        claude._complete_sync("q", system_prompt=None, max_tokens=100)
        call_kwargs = mock_anthropic_client.messages.create.call_args.kwargs
        assert "system" not in call_kwargs

    def test_model_passed_through(self, claude, mock_anthropic_client):
        claude._complete_sync("q", system_prompt=None, max_tokens=100)
        call_kwargs = mock_anthropic_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-5"

    def test_max_tokens_passed_through(self, claude, mock_anthropic_client):
        claude._complete_sync("q", system_prompt=None, max_tokens=999)
        call_kwargs = mock_anthropic_client.messages.create.call_args.kwargs
        assert call_kwargs["max_tokens"] == 999

    def test_returns_text_from_response(self, claude):
        result = claude._complete_sync("q", system_prompt=None, max_tokens=100)
        assert result == "Great run! Your HR drift was minimal."


class TestCompleteAsync:
    @pytest.mark.asyncio
    async def test_complete_returns_string(self, claude):
        result = await claude.complete("Analyse my run")
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_complete_with_system_prompt(self, claude, mock_anthropic_client):
        result = await claude.complete("q", system_prompt="You are a coach")
        call_kwargs = mock_anthropic_client.messages.create.call_args.kwargs
        assert call_kwargs.get("system") == "You are a coach"

    @pytest.mark.asyncio
    async def test_complete_default_max_tokens(self, claude, mock_anthropic_client):
        await claude.complete("q")
        call_kwargs = mock_anthropic_client.messages.create.call_args.kwargs
        assert call_kwargs["max_tokens"] == 1500

    @pytest.mark.asyncio
    async def test_complete_propagates_exceptions(self, claude, mock_anthropic_client):
        mock_anthropic_client.messages.create.side_effect = Exception("API error")
        with pytest.raises(Exception, match="API error"):
            await claude.complete("q")
