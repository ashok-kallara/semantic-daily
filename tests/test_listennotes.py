"""Tests for ListenNotes podcast collector."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.collectors.listennotes import ListenNotesCollector
from src.models.article import MediaType, Source


class TestListenNotesCollector:
    def _make_collector(self, **overrides):
        config = {
            "enabled": True,
            "api_key": "test-key",
            "queries": ["artificial intelligence"],
            "max_results": 5,
            **overrides,
        }
        return ListenNotesCollector(config)

    def test_disabled_returns_empty(self):
        c = self._make_collector(enabled=False)
        result = asyncio.run(c.collect())
        assert result == []

    def test_no_api_key_returns_empty(self):
        c = self._make_collector(api_key="")
        result = asyncio.run(c.collect())
        assert result == []

    @patch("src.collectors.listennotes.aiohttp.ClientSession")
    def test_collects_episodes(self, MockSession):
        api_response = {
            "results": [
                {
                    "title_original": "The Future of AI Agents",
                    "podcast": {
                        "title_original": "AI Today Podcast",
                        "listen_score": 75,
                    },
                    "link": "https://podcast.example.com/ep1",
                    "audio": "https://audio.example.com/ep1.mp3",
                    "listennotes_url": "https://listennotes.com/ep1",
                    "description_original": "Exploring the future of AI agents...",
                    "pub_date_ms": 1744300000000,
                    "audio_length_sec": 2400,
                }
            ]
        }

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=api_response)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        MockSession.return_value = mock_session

        c = self._make_collector()
        result = asyncio.run(c.collect())

        assert len(result) == 1
        assert result[0].title == "The Future of AI Agents"
        assert result[0].source == Source.PODCAST
        assert result[0].media_type == MediaType.PODCAST
        assert result[0].listen_score == 75
        assert result[0].duration_seconds == 2400
        assert result[0].author == "AI Today Podcast"

    @patch("src.collectors.listennotes.aiohttp.ClientSession")
    def test_handles_rate_limit(self, MockSession):
        mock_resp = AsyncMock()
        mock_resp.status = 429
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        MockSession.return_value = mock_session

        c = self._make_collector()
        result = asyncio.run(c.collect())
        assert result == []
