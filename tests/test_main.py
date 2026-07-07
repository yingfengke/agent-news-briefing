"""测试 main.py 的 AI 输出解析与 final_item 构造辅助函数"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.main import _resolve_category, _append_parsed_items
from src.config.sources import CATEGORY_ORDER


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


def test_append_parsed_items_builds_final_item():
    """_append_parsed_items 正确构造 final_item（含 category/score/link/tags）（P3-2）。"""
    parsed_list = [
        {"title": "GPT-5 发布", "summary": "x", "url": "https://openai.com/1",
         "score": 4.5, "tags": ["大模型"]},
        {"title": "无效条目缺字段", "summary": "", "url": "", "score": "bad"},
        {"title": "LangGraph 更新", "summary": "y", "url": "https://github.com/2",
         "score": 3.2, "tags": ["Agent框架"]},
    ]
    final = []
    ok, skip = _append_parsed_items(parsed_list, final, {}, {}, [])
    assert ok == 3 and skip == 0 and len(final) == 3
    for it in final:
        assert it["category"] in CATEGORY_ORDER
        assert isinstance(it["score"], (int, float))
        assert "link" in it and "source" in it and "tags" in it


if __name__ == "__main__":
    test_resolve_category_valid_tag_passthrough()
    test_resolve_category_invalid_tag_falls_back_to_title()
    test_resolve_category_no_summary_scan()
    test_resolve_category_default_other()
    test_append_parsed_items_builds_final_item()
    print("All main tests passed!")
