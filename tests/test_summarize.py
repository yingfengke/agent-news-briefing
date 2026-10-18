"""正文/简讯拆分与简讯压缩测试。"""
import json
from unittest.mock import patch

import pytest

from src import config
from src.analysis import summarize as S


def _item(title, score, category="行业动态"):
    return {"title": title, "score": score, "category": category,
            "summary": f"{title}的摘要内容。第二句。", "link": f"https://e.com/{title}"}


def test_split_prefers_other_category_when_over_limit():
    """正文满额后，「其他动态」优先让出名额给待展示区的非其他动态条目。"""
    items = [_item(f"热点{i}", 4.0 - i * 0.1) for i in range(18)]
    items.append(_item("杂项A", 4.5, "其他动态"))
    items.append(_item("杂项B", 4.4, "其他动态"))
    items.append(_item("备选C", 2.0))
    items.append(_item("备选D", 1.9))

    display, rest = S.split_display_items(items, limit=18)
    assert len(display) == 18
    titles = [it["title"] for it in display]
    # 两个「其他动态」被挤出正文，名额由待展示区里分数最高的非其他动态条目补上
    assert "杂项A" not in titles and "杂项B" not in titles
    assert all(it["category"] != "其他动态" for it in display)
    assert {it["title"] for it in rest} >= {"杂项A", "杂项B"}


def test_split_keeps_other_category_when_no_replacement():
    """待展示区没有非其他动态可替补时，保留原有条目而不是硬挤出。"""
    items = [_item(f"热点{i}", 4.0 - i * 0.1) for i in range(18)]
    items.append(_item("杂项", 1.0, "其他动态"))
    display, rest = S.split_display_items(items, limit=18)
    assert len(display) == 18 and len(rest) == 1
    assert "杂项" in [it["title"] for it in rest]


def test_split_orders_by_score():
    items = [_item("低", 1.0), _item("高", 4.8), _item("中", 3.0)]
    display, rest = S.split_display_items(items, limit=2)
    assert [it["title"] for it in display] == ["高", "中"]
    assert [it["title"] for it in rest] == ["低"]


def test_build_briefs_falls_back_when_model_fails():
    items = [_item("甲", 1.0), _item("乙", 0.9)]
    with patch.object(S, "_call_model", side_effect=TimeoutError("timeout")):
        briefs = S.build_briefs(items, model="x")
    assert len(briefs) == 2
    # 本地兜底：摘要首句
    assert briefs[0]["brief"].startswith("甲的摘要内容")
    assert briefs[0]["link"] == "https://e.com/甲"


def test_build_briefs_falls_back_to_main_model():
    """轻量模型不可用时改用主模型，避免整批退化成 60 字截断。"""
    items = [_item("甲", 1.0)]
    calls = []

    def _fake(prompt, model):
        calls.append(model)
        if model == config.MODEL_NAME:
            return ["主模型简讯"]
        raise TimeoutError("free model down")

    with patch.object(S, "_call_model", side_effect=_fake):
        briefs = S.build_briefs(items, model="free-model")
    assert calls == ["free-model", config.MODEL_NAME]
    assert briefs[0]["brief"] == "主模型简讯"


def test_build_briefs_uses_local_fallback_when_all_models_fail():
    items = [_item("甲", 1.0)]
    with patch.object(S, "_call_model", side_effect=TimeoutError("down")):
        briefs = S.build_briefs(items, model="free-model")
    assert briefs[0]["brief"].startswith("甲的摘要内容")


def test_build_briefs_treats_empty_output_as_failure():
    """模型返回空字符串同样视为失败，继续下一档模型。"""
    items = [_item("甲", 1.0)]
    calls = []

    def _fake(prompt, model):
        calls.append(model)
        return [""] if model != config.MODEL_NAME else ["兜底简讯"]

    with patch.object(S, "_call_model", side_effect=_fake):
        briefs = S.build_briefs(items, model="free-model")
    assert calls == ["free-model", config.MODEL_NAME]
    assert briefs[0]["brief"] == "兜底简讯"


def test_build_briefs_uses_model_output():
    items = [_item("甲", 1.0)]
    with patch.object(S, "_call_model", return_value=["一句话简讯"]):
        briefs = S.build_briefs(items, model="x")
    assert briefs[0]["brief"] == "一句话简讯"


def test_build_briefs_without_api_key_skips_model():
    items = [_item("甲", 1.0)]
    with patch.object(config, "API_KEY", ""):
        briefs = S.build_briefs(items)
    assert briefs[0]["brief"].startswith("甲的摘要内容")


def test_build_briefs_caps_item_count():
    items = [_item(f"n{i}", 1.0) for i in range(40)]
    briefs = S.build_briefs(items, max_items=24)
    assert len(briefs) == 24


def test_build_briefs_empty_input():
    assert S.build_briefs([]) == []


def test_call_model_parses_json_array():
    payload = {"choices": [{"message": {"content": '```json\n[{"i":1,"b":"简讯一"},{"i":2,"b":"简讯二"}]\n```'}}]}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    with patch.object(S, "urlopen", lambda *a, **k: _Resp()):
        out = S._call_model("prompt", "m")
    assert out[0] == "简讯一" and out[1] == "简讯二"


def test_call_model_rejects_non_json():
    payload = {"choices": [{"message": {"content": "抱歉，我无法完成"}}]}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    with patch.object(S, "urlopen", lambda *a, **k: _Resp()):
        with pytest.raises(ValueError):
            S._call_model("prompt", "m")
