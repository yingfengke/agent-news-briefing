"""rerun.py 单测：同日重跑判断 + 去重库清空。

仅依赖 config / logger（纯 Python），可在缺 jinja2/tiktoken 的环境运行。
"""
import os
import json

import pytest

from src import config
from src.core import rerun
from src.core.models import NewsItem
from src.core.rerun import (
    is_rerun, clear_dedup_for_rerun, _html_published_today,
    save_clean_items, load_cached_clean_items,
)


def _write_tmp_html(tmp_path, date_y, date_m, date_d, with_news=True):
    p = tmp_path / "tech-briefing.html"
    news = '[ {"title":"旧新闻A"},{"title":"旧新闻B"} ];' if with_news else '[];'
    p.write_text(
        '<!DOCTYPE html><html><body>\n'
        f'  <p id="today-date">{date_y}年{date_m}月{date_d}日</p>\n'
        '  <div class="timestamp visible" id="timestamp">'
        f'{date_y}-{date_m}-{date_d} 17:30（北京时间）</div>\n'
        f'  const __NEWS_DATA__ = {news};\n'
        '</body></html>\n',
        encoding="utf-8",
    )
    return p


def test_html_published_today_true(tmp_path, monkeypatch):
    today = config.now_bjt()
    p = _write_tmp_html(tmp_path, today.strftime("%Y"), today.strftime("%m"), today.strftime("%d"))
    monkeypatch.setattr(config, "HTML_FILE", str(p))
    assert _html_published_today() is True


def test_html_published_today_false_yesterday(tmp_path, monkeypatch):
    from datetime import timedelta
    y = config.now_bjt() - timedelta(days=1)
    p = _write_tmp_html(tmp_path, y.strftime("%Y"), y.strftime("%m"), y.strftime("%d"))
    monkeypatch.setattr(config, "HTML_FILE", str(p))
    assert _html_published_today() is False


def test_html_published_today_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HTML_FILE", str(tmp_path / "nope.html"))
    assert _html_published_today() is False


def test_is_rerun_env_flag(tmp_path, monkeypatch):
    p = _write_tmp_html(tmp_path, "2020", "01", "01")  # 非今天
    monkeypatch.setattr(config, "HTML_FILE", str(p))
    monkeypatch.setenv("BRIEFING_RERUN", "1")
    monkeypatch.delenv("GITHUB_RUN_ATTEMPT", raising=False)
    assert is_rerun() is True


def test_is_rerun_github_attempt(tmp_path, monkeypatch):
    p = _write_tmp_html(tmp_path, "2020", "01", "01")
    monkeypatch.setattr(config, "HTML_FILE", str(p))
    monkeypatch.delenv("BRIEFING_RERUN", raising=False)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    assert is_rerun() is True


def test_is_rerun_date_based(tmp_path, monkeypatch):
    today = config.now_bjt()
    p = _write_tmp_html(tmp_path, today.strftime("%Y"), today.strftime("%m"), today.strftime("%d"))
    monkeypatch.setattr(config, "HTML_FILE", str(p))
    monkeypatch.delenv("BRIEFING_RERUN", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ATTEMPT", raising=False)
    assert is_rerun() is True


def test_is_rerun_false_when_fresh(tmp_path, monkeypatch):
    from datetime import timedelta
    y = config.now_bjt() - timedelta(days=1)
    p = _write_tmp_html(tmp_path, y.strftime("%Y"), y.strftime("%m"), y.strftime("%d"))
    monkeypatch.setattr(config, "HTML_FILE", str(p))
    monkeypatch.delenv("BRIEFING_RERUN", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ATTEMPT", raising=False)
    assert is_rerun() is False


def test_clear_dedup_removes_url_db_and_resets_html(tmp_path, monkeypatch):
    today = config.now_bjt()
    html_p = _write_tmp_html(tmp_path, today.strftime("%Y"), today.strftime("%m"), today.strftime("%d"))
    monkeypatch.setattr(config, "HTML_FILE", str(html_p))

    db_p = tmp_path / ".url_dedup_db.json"
    db_p.write_text(json.dumps({"urls": ["deadbeef"], "updated": "x"}), encoding="utf-8")
    monkeypatch.setattr(config, "URL_DB_FILE", str(db_p))

    clear_dedup_for_rerun()

    # URL 库已删除
    assert not db_p.exists()
    # HTML 的 __NEWS_DATA__ 已重置为 []
    content = html_p.read_text(encoding="utf-8")
    import re
    m = re.search(r'const\s+__NEWS_DATA__\s*=\s*(\[[\s\S]*?\])\s*;', content)
    assert m, "未找到 __NEWS_DATA__"
    assert json.loads(m.group(1)) == []


def test_clear_dedup_idempotent_on_empty(tmp_path, monkeypatch):
    today = config.now_bjt()
    html_p = _write_tmp_html(tmp_path, today.strftime("%Y"), today.strftime("%m"), today.strftime("%d"),
                              with_news=False)  # 已经是 []
    monkeypatch.setattr(config, "HTML_FILE", str(html_p))
    monkeypatch.setattr(config, "URL_DB_FILE", str(tmp_path / "missing_db.json"))  # 不存在

    # 不应抛异常
    clear_dedup_for_rerun()
    content = html_p.read_text(encoding="utf-8")
    assert "__NEWS_DATA__" in content


def _make_items():
    return [
        NewsItem(id="a1", title="T1", content="C1", url="http://x/1",
                  source="S1", lang="zh", source_type="rss",
                  crawled_at="2026-07-22T10:00:00", published_at="2026-07-22T09:00:00",
                  tags=["Agent"], summary="s1"),
        NewsItem(id="a2", title="T2", content="C2", url="http://x/2",
                  source="S2", lang="en", source_type="rss",
                  crawled_at="2026-07-22T10:01:00"),  # tags/summary 走默认
    ]


def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    cache = tmp_path / ".raw_pool_cache.json"
    monkeypatch.setattr(config, "RAW_CACHE_FILE", str(cache))
    assert load_cached_clean_items() is None  # 初始无缓存

    items = _make_items()
    save_clean_items(items)

    loaded = load_cached_clean_items()
    assert loaded is not None and len(loaded) == 2
    assert isinstance(loaded[0], NewsItem)
    assert loaded[0].title == "T1" and loaded[0].tags == ["Agent"]
    # 默认值分支应保留
    assert loaded[1].summary == "" and loaded[1].tags == []


def test_load_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RAW_CACHE_FILE", str(tmp_path / "nope.json"))
    assert load_cached_clean_items() is None


def test_load_returns_none_when_corrupt(tmp_path, monkeypatch):
    cache = tmp_path / ".raw_pool_cache.json"
    cache.write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setattr(config, "RAW_CACHE_FILE", str(cache))
    assert load_cached_clean_items() is None
