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
