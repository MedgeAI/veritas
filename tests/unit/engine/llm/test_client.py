"""Unit tests for VeritasLLMClient."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestVeritasLLMClient:
    """Tests for engine.llm.client.VeritasLLMClient."""

    def test_chat_success(self):
        """Test chat() returns text response from OpenAI client."""
        from engine.llm.client import VeritasLLMClient

        with patch("engine.env.get_env", return_value="test-api-key"):
            with patch("openai.OpenAI") as mock_openai_cls:
                mock_client = MagicMock()
                mock_openai_cls.return_value = mock_client

                mock_response = MagicMock()
                mock_response.choices = [MagicMock()]
                mock_response.choices[0].message.content = "Hello, world!"
                mock_client.chat.completions.create.return_value = mock_response

                client = VeritasLLMClient()
                result = client.chat("test prompt")

                assert result == "Hello, world!"
                mock_client.chat.completions.create.assert_called_once_with(
                    model="qwen3.7-plus",
                    messages=[{"role": "user", "content": "test prompt"}],
                    temperature=0.0,
                    max_tokens=1024,
                )

    def test_chat_json_success(self):
        """Test chat_json() parses valid JSON response."""
        from engine.llm.client import VeritasLLMClient

        with patch("engine.env.get_env", return_value="test-api-key"):
            with patch("openai.OpenAI") as mock_openai_cls:
                mock_client = MagicMock()
                mock_openai_cls.return_value = mock_client

                mock_response = MagicMock()
                mock_response.choices = [MagicMock()]
                mock_response.choices[0].message.content = '{"key": "value", "num": 42}'
                mock_client.chat.completions.create.return_value = mock_response

                client = VeritasLLMClient()
                result = client.chat_json("test prompt")

                assert result == {"key": "value", "num": 42}

    def test_chat_json_parse_error(self):
        """Test chat_json() raises VeritasLLMParseError on invalid JSON."""
        from engine.llm.client import VeritasLLMClient, VeritasLLMParseError

        with patch("engine.env.get_env", return_value="test-api-key"):
            with patch("openai.OpenAI") as mock_openai_cls:
                mock_client = MagicMock()
                mock_openai_cls.return_value = mock_client

                mock_response = MagicMock()
                mock_response.choices = [MagicMock()]
                mock_response.choices[0].message.content = "not valid json"
                mock_client.chat.completions.create.return_value = mock_response

                client = VeritasLLMClient()

                with pytest.raises(VeritasLLMParseError) as exc_info:
                    client.chat_json("test prompt")

                assert "Failed to parse JSON" in str(exc_info.value)
                assert "not valid json" in str(exc_info.value)

    def test_missing_api_key_fail_loud(self):
        """Test that missing DASHSCOPE_API_KEY raises RuntimeError (fail-loud)."""
        from engine.llm.client import VeritasLLMClient

        with patch("engine.env.get_env", side_effect=RuntimeError("Required environment variable 'DASHSCOPE_API_KEY' is not set")):
            with pytest.raises(RuntimeError) as exc_info:
                VeritasLLMClient()

            assert "DASHSCOPE_API_KEY" in str(exc_info.value)

    def test_chat_with_custom_params(self):
        """Test chat() passes custom model/temperature/max_tokens."""
        from engine.llm.client import VeritasLLMClient

        with patch("engine.env.get_env", return_value="test-api-key"):
            with patch("openai.OpenAI") as mock_openai_cls:
                mock_client = MagicMock()
                mock_openai_cls.return_value = mock_client

                mock_response = MagicMock()
                mock_response.choices = [MagicMock()]
                mock_response.choices[0].message.content = "response"
                mock_client.chat.completions.create.return_value = mock_response

                client = VeritasLLMClient()
                result = client.chat(
                    "prompt",
                    model="qwen-turbo",
                    temperature=0.7,
                    max_tokens=512,
                )

                assert result == "response"
                mock_client.chat.completions.create.assert_called_once_with(
                    model="qwen-turbo",
                    messages=[{"role": "user", "content": "prompt"}],
                    temperature=0.7,
                    max_tokens=512,
                )

    def test_openai_import_error(self):
        """Test that missing openai package raises RuntimeError with install hint."""
        with patch("engine.env.get_env", return_value="test-api-key"):
            with patch.dict("sys.modules", {"openai": None}):
                from engine.llm.client import VeritasLLMClient

                with pytest.raises(RuntimeError) as exc_info:
                    VeritasLLMClient()

                assert "openai package not installed" in str(exc_info.value)
