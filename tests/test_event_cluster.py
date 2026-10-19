"""事件级判定测试：跨天「进展」标注 + 批内事件簇配额。

网络调用全部 mock：embedding 用二维向量控制相似度，reranker 返回预设分数。
"""
import pytest

from src import config
from src.analysis import event_cluster as E


def _vec(text: str):
    """按标题构造正交向量：同事件共用一个轴，其他条目各占一轴。"""
    if "同事件" in text or "续报" in text:
        return [1.0, 0.0, 0.0, 0.0]
    if "B1" in text:
        return [0.0, 1.0, 0.0, 0.0]
    if "B2" in text:
        return [0.0, 0.0, 1.0, 0.0]
    return [0.0, 0.0, 0.0, 1.0]


def _fake_post_factory(rerank_score):
    def _fake_post(url, payload, timeout=60):
        if url.endswith("/embeddings"):
            return {"data": [{"embedding": _vec(t)} for t in payload["input"]]}
        if url.endswith("/rerank"):
            return {"results": [{"relevance_score": rerank_score}]}
        raise AssertionError(url)
    return _fake_post


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "sk-test")
    monkeypatch.setattr(config, "API_BASE_URL", "https://api.example")


def test_annotate_marks_same_event(monkeypatch):
    monkeypatch.setattr(E, "_post", _fake_post_factory(0.80))
    items = [{"title": "同事件 智谱新模型法律领域登顶", "summary": ""}]
    out = E.annotate_progress(items, [("同事件 智谱推出法律模型", "摘要")])
    assert out[0]["title"] == E.PROGRESS_PREFIX + "同事件 智谱新模型法律领域登顶"


def test_annotate_skips_different_event(monkeypatch):
    monkeypatch.setattr(E, "_post", _fake_post_factory(0.05))
    items = [{"title": "同事件 智谱新模型法律领域登顶", "summary": ""}]
    out = E.annotate_progress(items, [("同事件 智谱推出法律模型", "摘要")])
    assert out[0]["title"] == "同事件 智谱新模型法律领域登顶"


def test_annotate_does_not_double_prefix(monkeypatch):
    monkeypatch.setattr(E, "_post", _fake_post_factory(0.80))
    items = [{"title": E.PROGRESS_PREFIX + "同事件 已有前缀", "summary": ""}]
    out = E.annotate_progress(items, [("同事件 历史", "")])
    assert out[0]["title"].count(E.PROGRESS_PREFIX) == 1


def test_annotate_degrades_on_api_error(monkeypatch):
    def _boom(*a, **k):
        raise TimeoutError("down")
    monkeypatch.setattr(E, "_post", _boom)
    items = [{"title": "同事件 原标题", "summary": ""}]
    out = E.annotate_progress(items, [("同事件 历史", "")])
    assert out[0]["title"] == "同事件 原标题"


def test_event_quota_moves_excess_and_backfills(monkeypatch):
    monkeypatch.setattr(E, "_post", _fake_post_factory(0.80))
    display = [
        {"title": "同事件 A1", "score": 4.0, "summary": ""},
        {"title": "同事件 A2", "score": 3.9, "summary": ""},
        {"title": "同事件 A3", "score": 3.8, "summary": ""},
        {"title": "其他 B1", "score": 3.0, "summary": ""},
        {"title": "其他 B2", "score": 2.9, "summary": ""},
    ]
    rest = [{"title": "其他 B3", "score": 2.0, "summary": ""}]

    kept, overflow = E.apply_event_quota(display, rest, limit=2)

    assert len(kept) == len(display)
    same = [x for x in kept if x["title"].startswith("同事件")]
    assert len(same) == 2
    assert "同事件 A3" in [x["title"] for x in overflow]
    assert "其他 B3" in [x["title"] for x in kept]


def test_event_quota_keeps_unrelated_pairs(monkeypatch):
    """embedding 相似度低于候选门槛时不做任何调整。"""
    monkeypatch.setattr(E, "_post", _fake_post_factory(0.80))
    display = [{"title": f"其他 B{i}", "score": 4.0 - i * 0.1, "summary": ""} for i in (1, 2, 3)]
    kept, overflow = E.apply_event_quota(display, [], limit=1)
    assert kept == display and overflow == []


def test_event_quota_degrades_on_api_error(monkeypatch):
    def _boom(*a, **k):
        raise TimeoutError("down")
    monkeypatch.setattr(E, "_post", _boom)
    display = [{"title": "同事件 A1", "score": 4.0}, {"title": "同事件 A2", "score": 3.9}]
    kept, overflow = E.apply_event_quota(display, [], limit=1)
    assert kept == display and overflow == []
