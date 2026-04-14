"""Tests for YouTube collector."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.collectors.youtube import YouTubeCollector
from src.models.article import MediaType, Source


class TestYouTubeCollector:
    def _make_collector(self, **overrides):
        config = {
            "enabled": True,
            "api_key": "test-key",
            "queries": ["AI news"],
            "max_results": 5,
            "published_after_hours": 48,
            "order": "viewCount",
            "min_views": 100,
            **overrides,
        }
        return YouTubeCollector(config)

    def test_disabled_returns_empty(self):
        c = self._make_collector(enabled=False)
        result = asyncio.run(c.collect())
        assert result == []

    def test_no_api_key_returns_empty(self):
        c = self._make_collector(api_key="")
        result = asyncio.run(c.collect())
        assert result == []

    @patch("src.collectors.youtube.aiohttp.ClientSession")
    def test_collects_videos(self, MockSession):
        search_response = {
            "items": [
                {
                    "id": {"videoId": "abc123"},
                    "snippet": {
                        "title": "GPT-5 Explained",
                        "channelTitle": "Two Minute Papers",
                        "publishedAt": "2026-04-10T12:00:00Z",
                        "description": "In this video we look at GPT-5...",
                    },
                }
            ]
        }

        stats_response = {
            "items": [
                {
                    "id": "abc123",
                    "statistics": {
                        "viewCount": "150000",
                        "likeCount": "5000",
                        "commentCount": "200",
                    },
                    "contentDetails": {
                        "duration": "PT12M30S",
                    },
                }
            ]
        }

        call_count = 0

        async def mock_get_cm(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_resp = AsyncMock()
            mock_resp.status = 200
            if call_count == 1:
                mock_resp.json = AsyncMock(return_value=search_response)
            else:
                mock_resp.json = AsyncMock(return_value=stats_response)
            return mock_resp

        mock_get = MagicMock()
        mock_get.__aenter__ = mock_get_cm
        mock_get.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_get)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        MockSession.return_value = mock_session

        c = self._make_collector()
        result = asyncio.run(c.collect())

        assert len(result) == 1
        assert result[0].title == "GPT-5 Explained"
        assert result[0].source == Source.YOUTUBE
        assert result[0].media_type == MediaType.VIDEO
        assert result[0].view_count == 150000
        assert result[0].like_count == 5000
        assert result[0].duration_seconds == 750  # 12m30s

    def test_parse_iso_duration(self):
        assert YouTubeCollector._parse_iso_duration("PT1H2M30S") == 3750
        assert YouTubeCollector._parse_iso_duration("PT12M30S") == 750
        assert YouTubeCollector._parse_iso_duration("PT45S") == 45
        assert YouTubeCollector._parse_iso_duration("PT1H") == 3600
        assert YouTubeCollector._parse_iso_duration("") is None
        assert YouTubeCollector._parse_iso_duration("invalid") is None
