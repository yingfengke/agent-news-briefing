"""测试 AI 分析层核心函数"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.ai_analyzer import (
    _estimate_tokens, _safe_parse_json, get_parse_stats, reset_parse_stats,
    _balance_sources, _filter_history_duplicates, _truncate_context,
)
from src.models import NewsItem


def test_estimate_tokens_empty():
    assert _estimate_tokens("") == 0
    assert _estimate_tokens(None) == 0


def test_estimate_tokens_basic():
    tok = _estimate_tokens("hello world")
    assert tok > 0, f"Expected positive token count, got {tok}"


def test_estimate_tokens_chinese():
    tok = _estimate_tokens("深度学习框架 PyTorch 发布了")
    assert tok > 0
    # tiktoken cl100k_base: Chinese ~1.5-2 chars/token, safety 0.9
    # So should be reasonable
    assert tok < 100


def test_safe_parse_json_direct():
    result = _safe_parse_json('{"a": 1, "b": "hello"}')
    assert result == {"a": 1, "b": "hello"}


def test_safe_parse_json_markdown_block():
    result = _safe_parse_json('```json\n{"a": 1}\n```')
    assert result == {"a": 1}


def test_safe_parse_json_trailing_comma():
    result = _safe_parse_json('{"a": 1, "b": 2,}')
    assert result == {"a": 1, "b": 2}


def test_safe_parse_json_single_quotes():
    result = _safe_parse_json("{'a': 1, 'b': 'hello'}")
    assert result == {"a": 1, "b": "hello"}


def test_safe_parse_json_empty():
    assert _safe_parse_json("") == {}
    assert _safe_parse_json("   ") == {}


def test_safe_parse_json_extra_text():
    result = _safe_parse_json('Here is the result: {"a": 1}')
    assert result == {"a": 1}


def test_parse_stats():
    reset_parse_stats()
    stats = get_parse_stats()
    assert stats["total"] == 0
    assert stats["direct_ok"] == 0

    _safe_parse_json('{"ok": 1}')
    stats = get_parse_stats()
    assert stats["total"] == 1
    assert stats["direct_ok"] == 1

    reset_parse_stats()
    stats = get_parse_stats()
    assert stats["total"] == 0


def test_balance_sources():
    items = [
        NewsItem(id="1", title="A1", content="", url="", source="SrcA", lang="zh", source_type="rss", crawled_at=""),
        NewsItem(id="2", title="A2", content="", url="", source="SrcA", lang="zh", source_type="rss", crawled_at=""),
        NewsItem(id="3", title="A3", content="", url="", source="SrcA", lang="zh", source_type="rss", crawled_at=""),
        NewsItem(id="4", title="B1", content="", url="", source="SrcB", lang="en", source_type="rss", crawled_at=""),
        NewsItem(id="5", title="C1", content="", url="", source="SrcC", lang="en", source_type="rss", crawled_at=""),
    ]
    balanced = _balance_sources(items, max_total=5, min_per_source=1, min_sources=3)
    assert len(balanced) <= 5
    sources = set(it.source for it in balanced)
    assert len(sources) >= 3  # should cover at least 3 sources


def test_filter_history_duplicates_no_history():
    """When there's no history file, should return all items unchanged."""
    items = [
        NewsItem(id="1", title="ZZZZ_UNIQUE_TEST_TITLE_12345", content="", url="", source="SrcA", lang="en", source_type="rss", crawled_at=""),
        NewsItem(id="2", title="YYYY_ANOTHER_UNIQUE_TEST_67890", content="", url="", source="SrcB", lang="en", source_type="rss", crawled_at=""),
    ]
    # Mock that HTML_FILE doesn't exist or is empty
    result = _filter_history_duplicates(items)
    assert len(result) == 2


def test_truncate_context_converges_within_budget():
    """_truncate_context 必须真正收敛在 token 预算内，不再发超长上下文（P3-3）。"""
    items = [
        NewsItem(
            id=f"id{i:02d}",
            title=f"这是一条非常长的测试新闻标题编号{i:02d}关于大模型的重大发布",
            content="内容" * 200,
            url=f"https://example.com/{i}",
            source="测试源", lang="zh", source_type="rss",
            crawled_at="2026-07-07T00:00:00+00:00",
            published_at="2026-07-07T00:00:00+00:00",
        )
        for i in range(40)
    ]
    system_prompt = "你是一个测试 system prompt " * 50
    max_context, max_output, safety = 4000, 1024, 200
    ctx = _truncate_context(items, system_prompt, max_context=max_context,
                            max_output=max_output, safety_margin=safety)
    budget = max_context - max_output - safety
    assert ctx["total_tokens"] <= budget, f"仍超预算: {ctx['total_tokens']} > {budget}"
    assert ctx["content_limit"] <= 30, f"content 未收敛: {ctx['content_limit']}"


if __name__ == "__main__":
    test_estimate_tokens_empty()
    test_estimate_tokens_basic()
    test_estimate_tokens_chinese()
    test_safe_parse_json_direct()
    test_safe_parse_json_markdown_block()
    test_safe_parse_json_trailing_comma()
    test_safe_parse_json_single_quotes()
    test_safe_parse_json_empty()
    test_safe_parse_json_extra_text()
    test_parse_stats()
    test_balance_sources()
    test_filter_history_duplicates_no_history()
    test_truncate_context_converges_within_budget()
    print("All ai_analyzer tests passed!")
