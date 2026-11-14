"""语义去重：低阈值召回 + 重排精判的行为测试。"""
import math

from src import config
from src.core.models import NewsItem
from src.dedupe import semantic_dedup as SD


def _item(title, source, published="2026-11-12T08:00:00"):
    return NewsItem(
        id=title, title=title, content="正文内容若干", url="https://e.com/" + title,
        source=source, lang="en", source_type="rss",
        crawled_at=published, published_at=published,
    )


def _vec(angle):
    return [math.cos(angle), math.sin(angle)]


def _setup(tmp_path, monkeypatch, vectors, score_fn):
    monkeypatch.setattr(config, "EMBEDDING_CACHE_FILE", str(tmp_path / "cache.json"))
    deduper = SD.SemanticDeduper()
    monkeypatch.setattr(deduper, "_get_embeddings_batch", lambda items: vectors)
    calls = []

    def _fake(a, b):
        calls.append((a, b))
        return score_fn(a, b)

    monkeypatch.setattr(SD, "rerank_pair", _fake)
    return deduper, calls


def test_thresholds_are_recall_and_judgement():
    assert config.DEDUP_SEMANTIC_THRESHOLD == 0.65
    assert config.DEDUP_RERANK_MAX_PAIRS == 24
    assert SD.SAME_EVENT_THRESHOLD == 0.45


def test_same_event_merges_and_writes_source_count(tmp_path, monkeypatch):
    items = [_item("Gemini Decisions API", "Google AI"),
             _item("Google Launches Gemini Decisions", "The Verge AI")]
    deduper, calls = _setup(tmp_path, monkeypatch,
                            [_vec(0.0), _vec(0.20)], lambda a, b: 0.94)

    out = deduper.deduplicate(items)

    assert len(out) == 1
    assert out[0].source_count == 2
    assert "2 家来源报道" in out[0].content
    assert len(calls) == 1


def test_same_topic_different_event_not_merged(tmp_path, monkeypatch):
    items = [_item("datasette-cluster-map 0.19", "Simon Willison"),
             _item("datasette-leaflet 0.3", "Simon Willison")]
    deduper, calls = _setup(tmp_path, monkeypatch,
                            [_vec(0.0), _vec(0.20)], lambda a, b: 0.02)

    out = deduper.deduplicate(items)

    assert len(out) == 2
    assert all(x.source_count == 1 for x in out)
    assert len(calls) == 1


def test_below_recall_threshold_never_calls_reranker(tmp_path, monkeypatch):
    items = [_item("标题A", "S1"), _item("标题B", "S2")]
    deduper, calls = _setup(tmp_path, monkeypatch,
                            [_vec(0.0), _vec(1.40)], lambda a, b: 0.99)

    out = deduper.deduplicate(items)

    assert len(out) == 2
    assert calls == []


def test_rerank_receives_titles_only(tmp_path, monkeypatch):
    items = [_item("标题A", "S1"), _item("标题B", "S2")]
    deduper, calls = _setup(tmp_path, monkeypatch,
                            [_vec(0.0), _vec(0.20)], lambda a, b: 0.90)

    deduper.deduplicate(items)

    assert calls == [("标题A", "标题B")]


def test_three_items_one_cluster_counts_three_sources(tmp_path, monkeypatch):
    items = [_item(f"同一事件 {i}", f"S{i}") for i in range(3)]
    deduper, calls = _setup(tmp_path, monkeypatch,
                            [_vec(0.0), _vec(0.05), _vec(0.10)],
                            lambda a, b: 0.90)

    out = deduper.deduplicate(items)

    assert len(out) == 1
    assert out[0].source_count == 3
    assert "3 家来源报道" in out[0].content
    # 已连通的第三对跳过，不浪费精判次数
    assert len(calls) == 2


def test_rerank_failure_rolls_back_to_zero_merge(tmp_path, monkeypatch):
    items = [_item(f"同一事件 {i}", f"S{i}") for i in range(3)]
    monkeypatch.setattr(config, "EMBEDDING_CACHE_FILE", str(tmp_path / "cache.json"))
    deduper = SD.SemanticDeduper()
    monkeypatch.setattr(deduper, "_get_embeddings_batch",
                        lambda xs: [_vec(0.0), _vec(0.05), _vec(0.10)])
    state = {"n": 0}

    def _flaky(a, b):
        state["n"] += 1
        if state["n"] >= 2:
            raise TimeoutError("down")
        return 0.90

    monkeypatch.setattr(SD, "rerank_pair", _flaky)

    out = deduper.deduplicate(items)

    assert len(out) == 3
    assert all(x.source_count == 1 for x in out)


def test_max_pairs_cap_limits_calls(tmp_path, monkeypatch):
    items = [_item(f"条目 {i}", f"S{i}") for i in range(4)]
    monkeypatch.setattr(config, "DEDUP_RERANK_MAX_PAIRS", 2)
    deduper, calls = _setup(tmp_path, monkeypatch,
                            [_vec(0.0), _vec(0.05), _vec(0.10), _vec(0.15)],
                            lambda a, b: 0.90)

    deduper.deduplicate(items)

    assert len(calls) == 2
