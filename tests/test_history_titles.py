"""跨天标题库测试：读写、窗口裁剪、同日覆盖、重跑清除。"""
import json
from datetime import datetime, timedelta

import pytest

from src import config
from src.core import history_titles as ht


@pytest.fixture()
def store(tmp_path, monkeypatch):
    path = tmp_path / ".recent_titles.json"
    monkeypatch.setattr(config, "RECENT_TITLES_FILE", str(path))
    return path


def _write(path, entries):
    path.write_text(json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")


def test_record_and_load_roundtrip(store):
    assert ht.record_titles([{"title": "新闻A"}, {"title": "新闻B"}], "2026-10-15")
    titles = ht.load_recent_titles(days=7)
    assert titles == ["新闻A", "新闻B"]


def test_record_overwrites_same_date(store):
    ht.record_titles([{"title": "旧标题"}], "2026-10-15")
    ht.record_titles([{"title": "新标题"}], "2026-10-15")
    assert ht.load_recent_titles(days=7) == ["新标题"]


def test_load_skips_entries_beyond_window(store):
    old = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    new = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    _write(store, [
        {"date": old, "titles": ["十天前"]},
        {"date": new, "titles": ["昨天"]},
    ])
    assert ht.load_recent_titles(days=7) == ["昨天"]


def test_load_is_latest_first_and_deduped(store):
    d1 = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    d2 = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    _write(store, [
        {"date": d1, "titles": ["重复标题", "前天标题"]},
        {"date": d2, "titles": ["重复标题", "昨天标题"]},
    ])
    assert ht.load_recent_titles(days=7) == ["重复标题", "昨天标题", "前天标题"]


def test_clear_today_removes_only_today(store):
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    _write(store, [
        {"date": yesterday, "titles": ["昨天"]},
        {"date": today, "titles": ["今天"]},
    ])
    assert ht.clear_today_titles() is True
    assert ht.load_recent_titles(days=7) == ["昨天"]


def test_missing_file_and_corrupted_file_are_safe(store):
    assert ht.load_recent_titles() == []
    store.write_text("{not json", encoding="utf-8")
    assert ht.load_recent_titles() == []


def test_record_ignores_empty_titles(store):
    assert ht.record_titles([{"title": ""}, {"title": "有效"}]) is True
    assert ht.load_recent_titles(days=7) == ["有效"]


def test_record_stores_summary(store):
    """库里同时保存摘要，供内容级跨天比对使用。"""
    ht.record_titles([{"title": "标题A", "summary": "这是摘要内容"}], "2026-10-16")
    items = ht.load_recent_items(days=7)
    assert items[0]["t"] == "标题A"
    assert items[0]["s"] == "这是摘要内容"


def test_load_compatible_with_legacy_titles_format(store):
    """旧格式（只存 titles 数组）仍可读取，摘要为空。"""
    date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    _write(store, [{"date": date, "titles": ["旧格式标题"]}])
    assert ht.load_recent_titles(days=7) == ["旧格式标题"]
    assert ht.load_recent_items(days=7)[0]["s"] == ""


def test_write_prunes_entries_beyond_retention(store):
    """写入时丢弃超出保留期的条目，避免状态文件无限增长。"""
    old = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    _write(store, [{"date": old, "titles": ["很久以前"]}])
    ht.record_titles([{"title": "今天"}])
    dates = [e["date"] for e in json.loads(store.read_text(encoding="utf-8"))["entries"]]
    assert old not in dates


def test_retention_window_is_fourteen_days():
    assert config.RECENT_TITLES_DAYS == 14
