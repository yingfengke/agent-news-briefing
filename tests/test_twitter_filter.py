"""Twitter 精选的模型兜底测试。"""
import json
from unittest.mock import patch

from src import config
from src.analysis import twitter_filter as T
from src.core.models import NewsItem


def _item(i: int) -> NewsItem:
    return NewsItem(id=str(i), title=f"推文{i}", content="内容", url=f"https://x.com/{i}",
                    source="Twitter", lang="zh", source_type="twitter", crawled_at="")


def _resp(content: str):
    class _R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")

    return _R()


def test_twitter_falls_back_to_main_model():
    """免费模型失败时改用主模型重试，而不是直接按顺序取前三条。"""
    items = [_item(i) for i in range(1, 6)]
    calls = []

    def _fake_urlopen(req, timeout=0):
        body = json.loads(req.data.decode("utf-8"))
        calls.append(body["model"])
        if body["model"] == config.MODEL_NAME:
            return _resp("2")
        raise TimeoutError("free model down")

    with patch.object(T, "urlopen", _fake_urlopen):
        out = T._filter_twitter_items(items, model="free-model")

    assert calls == ["free-model", config.MODEL_NAME]
    assert [it.title for it in out] == ["推文2"]


def test_twitter_returns_first_three_when_all_models_fail():
    items = [_item(i) for i in range(1, 6)]
    with patch.object(T, "urlopen", side_effect=TimeoutError("down")):
        out = T._filter_twitter_items(items, model="free-model")
    assert [it.title for it in out] == ["推文1", "推文2", "推文3"]


def test_twitter_empty_selection_falls_back_to_first_three():
    items = [_item(i) for i in range(1, 6)]
    with patch.object(T, "urlopen", lambda req, timeout=0: _resp("无法判断")):
        out = T._filter_twitter_items(items, model="m")
    assert [it.title for it in out] == ["推文1", "推文2", "推文3"]
