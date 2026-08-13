"""splitter.py 单测：分割、围栏剥离、熔断区分、失败恢复、字段注入。

依赖 stub：dotenv（配置加载）、tiktoken（src.analysis 包链式导入 context 需要）。
本机无这些包时 setdefault 注入假模块；CI 有真实包则不受影响。
"""
import sys
import types

import pytest

# --- 依赖 stub ---
_dotenv = types.ModuleType("dotenv")
_dotenv.load_dotenv = lambda *a, **k: None
sys.modules.setdefault("dotenv", _dotenv)

_tk = types.ModuleType("tiktoken")
_tk.get_encoding = lambda name: types.SimpleNamespace(encode=lambda s: [0] * len(s))
sys.modules.setdefault("tiktoken", _tk)

from src.analysis.splitter import (  # noqa: E402
    SPLIT_STYLES, _SPLIT_MODEL, split_analysis, split_items,
)


class TestSplitAnalysis:
    def test_normal_split(self, monkeypatch):
        monkeypatch.setattr(
            "src.analysis.splitter._call_model",
            lambda text: {"summary": "某模型发布。", "analysis": "该方案性能提升明显。"},
        )
        head, tail, ok = split_analysis("某模型发布。该方案性能提升明显。")
        assert head == "某模型发布。"
        assert tail == "该方案性能提升明显。"
        assert ok is True

    def test_api_exception_returns_original(self, monkeypatch):
        def boom(text):
            raise Exception("timeout")

        monkeypatch.setattr("src.analysis.splitter._call_model", boom)
        head, tail, ok = split_analysis("某模型发布。")
        assert head == "某模型发布。" and tail == "" and ok is False

    def test_empty_input(self, monkeypatch):
        def should_not_call(text):
            raise AssertionError("不应调用模型")

        monkeypatch.setattr("src.analysis.splitter._call_model", should_not_call)
        head, tail, ok = split_analysis("")
        assert head == "" and tail == "" and ok is True

    def test_empty_head_falls_back(self, monkeypatch):
        # 模型把全部内容当分析（summary 为空）→ 回退原样
        monkeypatch.setattr(
            "src.analysis.splitter._call_model",
            lambda text: {"summary": "", "analysis": "全部是分析。"},
        )
        head, tail, ok = split_analysis("原文内容。")
        assert head == "原文内容。" and tail == "" and ok is False

    def test_code_fence_stripped(self, monkeypatch):
        # 模型返回 ```json 围栏：真实 _call_model 解析路径应剥掉围栏
        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def read(self):
                # JSON 字符串里用 \n（真实换行转义），与模型实际输出一致
                s = ('{"choices":[{"message":{"content":"```json\\n'
                     '{\\"summary\\": \\"某模型发布。\\", \\"analysis\\": \\"该方案性能提升明显。\\"}'
                     '\\n```"}}]}')
                return s.encode("utf-8")

        monkeypatch.setattr(
            "src.analysis.splitter.urlopen", lambda req, timeout=30: FakeResp()
        )
        head, tail, ok = split_analysis("某模型发布。该方案性能提升明显。")
        assert head == "某模型发布。" and tail == "该方案性能提升明显。" and ok is True


class TestSplitItems:
    def test_inject_analysis_and_shrink_summary(self, monkeypatch):
        monkeypatch.setattr(
            "src.analysis.splitter._call_model",
            lambda text: {"summary": "事实。", "analysis": "分析。"},
        )
        items = [{"summary": "事实。分析。"}]
        split_items(items)
        assert items[0]["summary"] == "事实。"
        assert items[0]["analysis"] == "分析。"

    def test_legit_empty_analysis_not_counted_as_fail(self, monkeypatch):
        # 纯事实条目合法空分析：连续多条不触发熔断
        monkeypatch.setattr(
            "src.analysis.splitter._call_model",
            lambda text: {"summary": text, "analysis": ""},
        )
        items = [{"summary": f"纯事实{i}。"} for i in range(5)]
        split_items(items)
        assert all("analysis" not in it for it in items)

    def test_api_failures_trigger_circuit_break(self, monkeypatch):
        def boom(text):
            raise Exception("timeout")

        monkeypatch.setattr("src.analysis.splitter._call_model", boom)
        items = [{"summary": f"新闻{i}"} for i in range(5)]
        split_items(items)
        assert all("analysis" not in it for it in items)

    def test_recovery_after_failures(self, monkeypatch):
        calls = {"n": 0}

        def flaky(text):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise Exception("flaky")
            return {"summary": "事实。", "analysis": "分析。"}

        monkeypatch.setattr("src.analysis.splitter._call_model", flaky)
        items = [{"summary": "a1"}, {"summary": "a2"},
                 {"summary": "a3"}, {"summary": "a4"}]
        split_items(items)
        analyzed = [it for it in items if it.get("analysis")]
        assert len(analyzed) == 2  # 前 2 条失败，第 3 条起恢复

    def test_empty_summary_skipped(self, monkeypatch):
        def should_not_call(text):
            raise AssertionError("不应调用模型")

        monkeypatch.setattr("src.analysis.splitter._call_model", should_not_call)
        items = [{"summary": ""}]
        split_items(items)
        assert "analysis" not in items[0]


class TestMeta:
    def test_split_styles_contains_paragraph_styles(self):
        assert SPLIT_STYLES == {"深度解读", "极客观点"}

    def test_model_is_free_glm(self):
        assert _SPLIT_MODEL == "THUDM/GLM-Z1-9B-0414"
