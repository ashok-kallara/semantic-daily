"""Tests for Apify X.com + Reddit collector."""

import asyncio
import sys
from unittest.mock import MagicMock, patch

from src.collectors.apify import ApifyCollector
from src.models.article import Source


class TestApifyCollector:
    def _make_collector(self, **overrides):
        config = {
            "enabled": True,
            "api_token": "test-token",
            "twitter_enabled": True,
            "twitter_keywords": ["AI", "LLM"],
            "twitter_max_tweets": 10,
            "twitter_min_likes": 5,
            "reddit_enabled": False,
            **overrides,
        }
        return ApifyCollector(config)

    def test_disabled_returns_empty(self):
        c = self._make_collector(enabled=False)
        result = asyncio.run(c.collect())
        assert result == []

    def test_no_api_token_returns_empty(self):
        c = self._make_collector(api_token="")
        result = asyncio.run(c.collect())
        assert result == []

    def test_collects_tweets(self):
        tweet_data = {
            "full_text": "Exciting AI breakthrough in reasoning!",
            "favorite_count": 500,
            "retweet_count": 100,
            "reply_count": 25,
            "views_count": 50000,
            "user": {"screen_name": "ai_researcher"},
            "id_str": "123456789",
            "created_at": "Thu Apr 10 12:00:00 +0000 2026",
        }

        mock_dataset = MagicMock()
        mock_dataset.iterate_items.return_value = [tweet_data]

        mock_run = {"defaultDatasetId": "dataset-123"}
        mock_actor = MagicMock()
        mock_actor.call.return_value = mock_run

        mock_client = MagicMock()
        mock_client.actor.return_value = mock_actor
        mock_client.dataset.return_value = mock_dataset

        mock_apify_module = MagicMock()
        mock_apify_module.ApifyClient.return_value = mock_client

        with patch.dict(sys.modules, {"apify_client": mock_apify_module}):
            c = self._make_collector()
            result = asyncio.run(c.collect())

        assert len(result) == 1
        assert result[0].source == Source.APIFY_X
        assert result[0].like_count == 500
        assert result[0].retweet_count == 100
        assert result[0].view_count == 50000
        assert "@ai_researcher" in result[0].author

    def test_filters_low_likes(self):
        tweet_data = {
            "full_text": "Low engagement tweet",
            "favorite_count": 2,  # Below min_likes of 5
            "retweet_count": 0,
            "user": {"screen_name": "nobody"},
            "id_str": "999",
        }

        mock_dataset = MagicMock()
        mock_dataset.iterate_items.return_value = [tweet_data]

        mock_actor = MagicMock()
        mock_actor.call.return_value = {"defaultDatasetId": "ds-1"}

        mock_client = MagicMock()
        mock_client.actor.return_value = mock_actor
        mock_client.dataset.return_value = mock_dataset

        mock_apify_module = MagicMock()
        mock_apify_module.ApifyClient.return_value = mock_client

        with patch.dict(sys.modules, {"apify_client": mock_apify_module}):
            c = self._make_collector()
            result = asyncio.run(c.collect())
        assert len(result) == 0

    def test_handles_actor_error(self):
        mock_actor = MagicMock()
        mock_actor.call.side_effect = Exception("Actor failed")

        mock_client = MagicMock()
        mock_client.actor.return_value = mock_actor

        mock_apify_module = MagicMock()
        mock_apify_module.ApifyClient.return_value = mock_client

        with patch.dict(sys.modules, {"apify_client": mock_apify_module}):
            c = self._make_collector()
            result = asyncio.run(c.collect())
        assert result == []

    def test_twitter_disabled_returns_empty(self):
        c = self._make_collector(twitter_enabled=False)
        result = asyncio.run(c.collect())
        assert result == []

    # ── Reddit tests ──

    def test_collects_reddit_posts(self):
        post_data = {
            "title": "New open source LLM beats GPT-4",
            "score": 1500,
            "numberOfComments": 230,
            "url": "https://www.reddit.com/r/LocalLLaMA/comments/abc123",
            "subreddit": "LocalLLaMA",
            "author": "ai_fan",
            "createdAt": "2026-04-10T12:00:00Z",
            "body": "Check out this new model...",
        }

        mock_dataset = MagicMock()
        mock_dataset.iterate_items.return_value = [post_data]

        mock_run = {"defaultDatasetId": "dataset-reddit"}
        mock_actor = MagicMock()
        mock_actor.call.return_value = mock_run

        mock_client = MagicMock()
        mock_client.actor.return_value = mock_actor
        mock_client.dataset.return_value = mock_dataset

        mock_apify_module = MagicMock()
        mock_apify_module.ApifyClient.return_value = mock_client

        with patch.dict(sys.modules, {"apify_client": mock_apify_module}):
            c = self._make_collector(
                twitter_enabled=False,
                reddit_enabled=True,
                reddit_subreddits=["LocalLLaMA"],
                reddit_min_score=50,
            )
            result = asyncio.run(c.collect())

        assert len(result) == 1
        assert result[0].source == Source.APIFY_REDDIT
        assert result[0].title == "New open source LLM beats GPT-4"
        assert result[0].score == 1500
        assert result[0].comment_count == 230
        assert "r/LocalLLaMA" in result[0].source_detail

    def test_filters_low_score_reddit(self):
        post_data = {
            "title": "Low score post",
            "score": 5,  # Below min_score of 50
            "url": "https://www.reddit.com/r/test/comments/xyz",
            "subreddit": "test",
        }

        mock_dataset = MagicMock()
        mock_dataset.iterate_items.return_value = [post_data]

        mock_actor = MagicMock()
        mock_actor.call.return_value = {"defaultDatasetId": "ds-reddit"}

        mock_client = MagicMock()
        mock_client.actor.return_value = mock_actor
        mock_client.dataset.return_value = mock_dataset

        mock_apify_module = MagicMock()
        mock_apify_module.ApifyClient.return_value = mock_client

        with patch.dict(sys.modules, {"apify_client": mock_apify_module}):
            c = self._make_collector(
                twitter_enabled=False,
                reddit_enabled=True,
                reddit_min_score=50,
            )
            result = asyncio.run(c.collect())
        assert len(result) == 0
