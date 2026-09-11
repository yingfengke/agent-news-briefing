"""可观测性测试：Timeline 阶段计时、质量异常判定、当日摘要、Trending 隔离。"""
import json
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import src.main as M
from src.core.logger import Timeline
from src.core.models import NewsItem


# ---------- Timeline ----------

def test_timeline_mark_and_rows():
    tl = Timeline()
    tl.mark("采集", "rss_fetch", "ok", "36 源 128 条")
    tl.mark("分析", "ai_analysis", "ok", "18 条")
    rows = tl.summary()
    assert len(rows) == 2
    assert rows[0]["stage"] == "采集"
    assert rows[0]["cost_s"] >= 0
    assert rows[1]["action"] == "ai_analysis"
    assert tl.elapsed() >= 0


def test_timeline_failures_detects_degraded_and_failed():
    """只有 ok/skipped 不算异常；failed 与 degraded 都要被识别。"""
    tl = Timeline()
    tl.mark("采集", "rss_fetch", "ok")
    tl.mark("采集", "trending", "skipped")
    tl.mark("分析", "ai_analysis", "degraded")
    tl.mark("生成", "html_render", "failed")
    assert {m["action"] for m in tl.failures()} == {"ai_analysis", "html_render"}


def test_timeline_to_dict_serializable():
    tl = Timeline()
    tl.mark("采集", "rss_fetch", "ok", "10 条")
    data = tl.to_dict()
    json.dumps(data, ensure_ascii=False)  # 必须可 JSON 序列化
    assert data["stages"][0]["cost_s"] >= 0
    assert data["failed_stages"] == []


def test_timeline_summary_writes_to_logger():
    calls = []

    class _FakeLogger:
        def info(self, msg):
            calls.append(msg)

    tl = Timeline()
    tl.mark("采集", "rss_fetch", "ok", "10 条")
    tl.summary(_FakeLogger())
    assert len(calls) == 1
    assert "Pipeline Timeline" in calls[0]
    assert "rss_fetch" in calls[0]


# ---------- 质量异常判定 ----------

def _fake_report(total_input=50, total_output=20):
    class _R:
        def __init__(self):
            self.total_input = total_input
            self.total_output = total_output
    return _R()


def test_quality_issues_clean_run_returns_empty():
    items = [{"title": f"n{i}"} for i in range(12)]
    issues = M._collect_quality_issues(items, _fake_report(), False)
    assert issues == []


def test_quality_issues_flags_ai_degraded():
    items = [{"title": f"n{i}"} for i in range(12)]
    issues = M._collect_quality_issues(items, _fake_report(), True)
    assert any("AI 分析失败" in it for it in issues)


def test_quality_issues_flags_low_news_count():
    items = [{"title": "only"}]
    issues = M._collect_quality_issues(items, _fake_report(), False)
    assert any("最终新闻仅 1 条" in it for it in issues)


def test_quality_issues_flags_low_input():
    items = [{"title": f"n{i}"} for i in range(12)]
    issues = M._collect_quality_issues(items, _fake_report(total_input=3), False)
    assert any("进入 AI 分析" in it for it in issues)


def test_quality_issues_ignores_missing_trending():
    """Trending 为空不触发提醒（推荐偶尔为空属正常，仅记入 timeline/摘要）。"""
    items = [{"title": f"n{i}"} for i in range(12)]
    issues = M._collect_quality_issues(items, _fake_report(), False)
    assert issues == []


def test_quality_issues_skips_input_check_when_ai_failed():
    """AI 失败时不再重复报「输入过少」，避免同一根因刷两条。"""
    items = [{"title": "only"}]
    issues = M._collect_quality_issues(items, _fake_report(total_input=0), True)
    assert not any("进入 AI 分析" in it for it in issues)


# ---------- 当日摘要 ----------

def test_write_daily_summary_creates_json(tmp_path, monkeypatch):
    monkeypatch.setattr(M.config, "BASE_DIR", str(tmp_path))
    tl = Timeline()
    tl.mark("采集", "rss_fetch", "ok", "10 条")
    path = M._write_daily_summary(tl.to_dict(), news_count=3, ai_failed=False)
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["metrics"]["news_count"] == 3
    assert data["timeline"]["stages"][0]["action"] == "rss_fetch"


# ---------- Trending 局部隔离 ----------

def _stub_pipeline(monkeypatch, tmp_path, trending_fn):
    """把 _run_main 的外部依赖全部替换为桩，仅保留待测逻辑。"""
    item = NewsItem(id="1", title="GPT-5 发布", content="x", url="https://x.com/1",
                    source="OpenAI", lang="en", source_type="rss", crawled_at="")

    class _Report:
        total_input = 50
        total_output = 1
        remaining_items = [item]

        def print_report(self):
            pass

    monkeypatch.setattr(M, "is_rerun", lambda: False)
    monkeypatch.setattr(M, "collect_all", lambda: [item])
    monkeypatch.setattr(M, "run_pipeline", lambda raw: _Report())
    monkeypatch.setattr(M, "save_clean_items", lambda items: None)
    monkeypatch.setattr(M, "call_ai_analysis", lambda items: (
        "极简资讯",
        {"news": [{"title": "GPT-5 发布", "summary": "s", "url": "https://x.com/1",
                   "score": 4.0, "tags": ["大模型"]}], "daily_analysis": "分析"},
    ))
    monkeypatch.setattr(M, "_translate_english_titles", lambda items: items)
    monkeypatch.setattr(M, "_attach_published_at", lambda *a, **k: None)
    monkeypatch.setattr(M, "write_html", lambda *a, **k: None)
    monkeypatch.setattr(M, "make_email_with_categories", lambda *a, **k: None)
    monkeypatch.setattr(M, "generate_rss_feed", lambda *a, **k: None)
    monkeypatch.setattr(M, "_write_daily_summary",
                        lambda *a, **k: str(tmp_path / "summary.json"))
    monkeypatch.setattr(M, "fetch_github_trending", trending_fn)
    # 默认屏蔽真实告警发送（避免测试触达 SMTP），个别用例再覆盖此桩
    monkeypatch.setattr("src.delivery.send_email.send_quality_alert",
                        lambda issues, summary="": True)


def test_run_main_survives_trending_exception(monkeypatch, tmp_path):
    """Trending 抓取抛异常时，主流程不得中断（AI 有降级，Trending 也应隔离）。"""
    def _boom():
        raise RuntimeError("trending down")

    _stub_pipeline(monkeypatch, tmp_path, _boom)
    M._run_main()  # 不抛异常即通过


def test_run_main_alerts_on_quality_issues(monkeypatch, tmp_path):
    """Trending 失败 + 新闻仅 1 条 -> 触发质量提醒（且不影响主流程）。"""
    sent = {}

    def _boom():
        raise RuntimeError("trending down")

    _stub_pipeline(monkeypatch, tmp_path, _boom)
    monkeypatch.setattr("src.delivery.send_email.send_quality_alert",
                        lambda issues, summary="": sent.update(issues=issues, summary=summary))
    M._run_main()
    assert sent.get("issues"), "应触发质量提醒"
    assert any("最终新闻仅 1 条" in it for it in sent["issues"])


def test_run_main_quality_check_survives_alert_failure(monkeypatch, tmp_path):
    """告警发送自身抛异常时不得影响主流程。"""
    def _boom():
        raise RuntimeError("trending down")

    def _alert_boom(issues, summary=""):
        raise RuntimeError("smtp down")

    _stub_pipeline(monkeypatch, tmp_path, _boom)
    monkeypatch.setattr("src.delivery.send_email.send_quality_alert", _alert_boom)
    M._run_main()  # 不抛异常即通过
