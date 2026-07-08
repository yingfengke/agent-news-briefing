"""测试 main.py 的 AI 输出解析与 final_item 构造辅助函数"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.main import (
    _resolve_category, _resolve_source, _sanitize_tags, _append_parsed_items,
)
from src.config.sources import CATEGORY_ORDER
from src.models import NewsItem


def test_resolve_category_valid_tag_passthrough():
    """AI 返回合法枚举标签时直接采用（D1）。"""
    assert _resolve_category({"tags": ["大模型"]}) == "大模型"
    assert _resolve_category({"tags": ["行业动态"]}) == "行业动态"


def test_resolve_category_invalid_tag_falls_back_to_title():
    """AI 返回非法标签时回退到标题关键词（D1）。"""
    assert _resolve_category({"tags": ["乱码"], "title": "GPT-5 发布"}) == "大模型"
    assert _resolve_category({"tags": ["坏标签"], "title": "arxiv 新论文"}) == "论文与研究"


def test_resolve_category_no_summary_scan():
    """标题不命中、摘要命中时仍归「其他动态」，不扫摘要（D1 根因）。"""
    assert _resolve_category({"tags": [], "title": "随便聊聊", "summary": "关于 llama 的论文"}) == "其他动态"


def test_resolve_category_default_other():
    """无任何标签、标题无命中时兜底「其他动态」。"""
    assert _resolve_category({"tags": [], "title": "今日杂谈"}) == "其他动态"


def test_resolve_category_scans_all_tags_not_just_first():
    """扫描全部 tags 取首个合法枚举，AI 误放在前面也不影响（标签清洗配套修复）。"""
    assert _resolve_category({"tags": ["AI", "大模型"], "title": "某新闻"}) == "大模型"
    assert _resolve_category({"tags": ["", "论文与研究"], "title": "某论文"}) == "论文与研究"


def test_sanitize_tags_drops_ai_and_noise():
    """_sanitize_tags 去掉 'AI'、空值、无意义词与重复项。"""
    assert _sanitize_tags(["AI", "大模型", "", "ai", "开源", "开源"]) == ["大模型", "开源"]
    assert _sanitize_tags(["ai"]) == []
    assert _sanitize_tags(["其他动态", "无", "null"]) == []
    assert _sanitize_tags("not-a-list") == []


def test_resolve_source_by_title_fallback():
    """AI 返回 source='AI' 时按标题模糊匹配回溯真实源（9bf1689）。"""
    clean = [NewsItem(id="1", title="DeepSeek 发布全新 V4 大模型", content="", url="https://arxiv.org/1",
                      source="ArXiv", lang="en", source_type="rss", crawled_at="")]
    assert _resolve_source({"source": "AI", "title": "DeepSeek 发布全新 V4 大模型引发关注"}, clean) == "ArXiv"


def test_resolve_source_by_domain_fallback():
    """标题被改写导致匹配失败时，按 URL 域名反查源（抗 LLM 改写标题）。"""
    clean = [NewsItem(id="1", title="DeepSeek 发布新模型", content="", url="https://arxiv.org/abs/2401.1",
                      source="ArXiv", lang="en", source_type="rss", crawled_at=""),
             NewsItem(id="2", title="Foo", content="", url="https://techcrunch.com/x",
                      source="TechCrunch", lang="en", source_type="rss", crawled_at="")]
    assert _resolve_source({"source": "AI", "title": "完全无关的改写标题 xyz",
                            "url": "https://arxiv.org/abs/9999"}, clean) == "ArXiv"


def test_append_parsed_items_sanitizes_tags():
    """_append_parsed_items 写入的 tags 已被清洗（'AI' 不会进入前端 chip）（标签清洗修复）。"""
    parsed_list = [
        {"title": "GPT-5 发布", "summary": "x", "url": "https://openai.com/1",
         "score": 4.5, "tags": ["AI", "大模型"]},
        {"title": "LangGraph 更新", "summary": "y", "url": "https://github.com/2",
         "score": 3.2, "tags": ["Agent框架", "开源"]},
    ]
    final = []
    ok, skip = _append_parsed_items(parsed_list, final, {}, {}, [])
    assert ok == 2 and len(final) == 2
    assert final[0]["tags"] == ["大模型"]
    assert final[1]["tags"] == ["Agent框架", "开源"]
    for it in final:
        assert it["category"] in CATEGORY_ORDER
        assert "link" in it and "source" in it


if __name__ == "__main__":
    test_resolve_category_valid_tag_passthrough()
    test_resolve_category_invalid_tag_falls_back_to_title()
    test_resolve_category_no_summary_scan()
    test_resolve_category_default_other()
    test_resolve_category_scans_all_tags_not_just_first()
    test_sanitize_tags_drops_ai_and_noise()
    test_resolve_source_by_title_fallback()
    test_resolve_source_by_domain_fallback()
    test_append_parsed_items_sanitizes_tags()
    print("All main tests passed!")
