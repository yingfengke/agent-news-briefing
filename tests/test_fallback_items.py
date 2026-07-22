"""AI 失败降级兜底测试：_build_fallback_items / _fallback_category。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.models import NewsItem
from src.analysis.postprocess import _build_fallback_items, _fallback_category


def _mk(title, tags=None, content="摘要内容", source="量子位",
         url="https://example.com/1", source_type="rss"):
    return NewsItem(
        id="1", title=title, content=content, url=url, source=source,
        lang="zh", source_type=source_type, crawled_at="2026-07-13T00:00:00Z",
        tags=tags or [],
    )


def test_build_fallback_items_schema():
    items = [
        _mk("OpenAI 发布新模型", tags=["发布"]),
        _mk("某 Agent 框架开源", tags=["agent"]),
    ]
    out = _build_fallback_items(items)
    assert len(out) == 2
    keys = {"title", "summary", "link", "source", "score", "tags", "category"}
    for it in out:
        assert keys.issubset(it.keys())
        assert it["score"] == 0
        assert it["link"].startswith("https://")
        assert it["category"] in (
            "大模型", "Agent框架", "产品与发布",
            "论文与研究", "行业动态", "其他动态",
        )


def test_build_fallback_truncates_long_content():
    long = "字" * 500
    out = _build_fallback_items([_mk("长内容新闻", content=long)])
    assert len(out[0]["summary"]) <= 201
    assert out[0]["summary"].endswith("…")


def test_fallback_category_mapping():
    assert _fallback_category(_mk("Agent 框架发布", tags=["agent"])) == "Agent框架"
    assert _fallback_category(_mk("论文研究新进展", tags=["论文"])) == "论文与研究"
    assert _fallback_category(_mk("某公司发布开源模型", tags=["发布", "开源"])) == "产品与发布"
    assert _fallback_category(_mk("行业融资动态", tags=["融资"])) == "行业动态"
    assert _fallback_category(_mk("杂项新闻", tags=[])) == "其他动态"


def test_empty_clean_items_returns_empty():
    assert _build_fallback_items([]) == []
