"""测试 AI 分析层核心函数"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch
from src.analysis import (
    _estimate_tokens, _safe_parse_json, get_parse_stats, reset_parse_stats,
    _balance_sources, _filter_history_duplicates, _truncate_context,
    call_ai_analysis,
)
from src.core.models import NewsItem
import src.config as config


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
    # 隔离历史加载：本单测只验证去重逻辑，不依赖外部 html 状态
    with patch("src.analysis.context.load_history_titles", return_value=[]):
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
    # 隔离历史加载：本单测只验证截断收敛，不依赖外部 html 历史条数
    with patch("src.analysis.context.load_history_titles", return_value=[]):
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


_VALID = {"choices": [{"message": {"content": '{"news":[{"title":"T1","summary":"S1","score":3,"category":"其他动态","tags":[]}]}'}}]}


class _FakeResp:
    def __init__(self, obj):
        self._b = json.dumps(obj).encode("utf-8")
    def read(self):
        return self._b
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def _mk_items(n=2):
    return [
        NewsItem(id=f"i{i}", title=f"新闻{i} 发布", content="这是一条足够长的新闻摘要内容",
                  url=f"https://e.com/{i}", source="量子位", lang="zh",
                  source_type="rss", crawled_at="2026-07-13T00:00:00Z")
        for i in range(n)
    ]


def test_call_ai_fallback_to_second_model():
    # 主模型失败，兜底模型成功 -> 返回解析结果（非 None），且两个模型都被调用
    calls = []
    def fake_urlopen(req, timeout=180):
        model = json.loads(req.data.decode())["model"]
        calls.append(model)
        if model == "primary/fail":
            raise TimeoutError("read operation timed out")
        return _FakeResp(_VALID)
    with patch("src.analysis.invoke.urlopen", fake_urlopen), \
         patch.object(config, "API_KEY", "x"), \
         patch.object(config, "MODEL_NAME", "primary/fail"), \
         patch.object(config, "FALLBACK_MODEL_NAME", "fallback/ok"):
        style, parsed = call_ai_analysis(_mk_items(), max_retries=1)
    assert parsed is not None
    assert parsed["news"][0]["title"] == "T1"
    assert "primary/fail" in calls and "fallback/ok" in calls


def test_call_ai_both_fail_returns_none():
    # 主模型与兜底模型都失败 -> 返回 (style, None)
    def fake_urlopen(req, timeout=180):
        raise TimeoutError("read operation timed out")
    with patch("src.analysis.invoke.urlopen", fake_urlopen), \
         patch.object(config, "API_KEY", "x"), \
         patch.object(config, "MODEL_NAME", "primary/fail"), \
         patch.object(config, "FALLBACK_MODEL_NAME", "fallback/ok"):
        style, parsed = call_ai_analysis(_mk_items(), max_retries=1)
    assert parsed is None


def test_filter_history_duplicates_catches_same_product_entity():
    """跨源报道同一产品：措辞与关键词都不同，靠稀有实体命中判定为已报道。"""
    items = [
        NewsItem(id="1", title="Z.ai 发布 GLM-Legal 法律模型，在 Harvey LAB 上超越 Claude",
                 content="", url="https://a.example/1", source="MarkTechPost",
                 lang="zh", source_type="rss", crawled_at=""),
    ]
    history = ["智谱 AI 推出 GLM-Legal：面向合同审查与合规的专用法律模型"]
    records = tuple((t, "") for t in history)
    with patch("src.analysis.context.load_history_records", return_value=records):
        result = _filter_history_duplicates(items)
    assert result == []


def test_filter_history_duplicates_keeps_different_event_of_same_vendor():
    """同一厂商的不同事件不算重复（共享厂商名不放行）。"""
    items = [
        NewsItem(id="1", title="OpenAI 调整 API 定价，企业版下调 20%",
                 content="", url="https://a.example/1", source="SrcA",
                 lang="zh", source_type="rss", crawled_at=""),
    ]
    history = ["OpenAI 发布新版语音模型，延迟降低一半"]
    records = tuple((t, "") for t in history)
    with patch("src.analysis.context.load_history_records", return_value=records):
        result = _filter_history_duplicates(items)
    assert len(result) == 1


def test_extract_entities_filters_generic_tokens():
    from src.analysis.context import _extract_entities
    assert "glm-legal" in _extract_entities("智谱推出 GLM-Legal 法律模型")
    assert "llama-4" in _extract_entities("Llama-4 用 MoE 架构降本")
    # 厂商名与短数字不参与
    assert _extract_entities("OpenAI 与 Google 合作") == set()
    assert _extract_entities("GPT-5") == set()


def test_filter_history_duplicates_catches_content_level_duplicate():
    """无可识别产品名时，靠摘要内容重合兜住跨源改写报道的同一事件。"""
    items = [
        NewsItem(id="1", title="AI 模型上线须先完成备案",
                 content="监管要求大模型上线前完成备案，涉及训练数据来源、内容安全评估与算法说明等材料",
                 url="https://a.example/2", source="SrcB", lang="zh",
                 source_type="rss", crawled_at=""),
    ]
    records = ((
        "某地发布大模型备案新规",
        "监管要求所有大模型上线前完成备案，涉及训练数据来源、内容安全评估与算法说明",
    ),)
    with patch("src.analysis.context.load_history_records", return_value=records):
        result = _filter_history_duplicates(items)
    assert result == []


def test_filter_history_duplicates_keeps_unrelated_content():
    """内容不重合的条目即使同为主题也不误杀。"""
    items = [
        NewsItem(id="1", title="OpenAI 发布新语音模型",
                 content="延迟降低一半，支持多语种实时转写，定价同步下调",
                 url="https://a.example/3", source="SrcA", lang="zh",
                 source_type="rss", crawled_at=""),
    ]
    records = ((
        "某地发布大模型备案新规",
        "监管要求所有大模型上线前完成备案，涉及训练数据来源、内容安全评估与算法说明",
    ),)
    with patch("src.analysis.context.load_history_records", return_value=records):
        result = _filter_history_duplicates(items)
    assert len(result) == 1


def test_content_token_similarity_requires_enough_shared_tokens():
    from src.analysis.context import _content_tokens, _content_duplicate
    a = _content_tokens("监管要求大模型上线前完成备案，涉及训练数据来源与内容安全评估")
    b = _content_tokens("大模型上线前须完成备案，训练数据来源和内容安全评估必不可少")
    c = _content_tokens("半导体设备出货量同比增长，带动上游材料涨价")
    assert _content_duplicate(a, b) is True
    assert _content_duplicate(a, c) is False
