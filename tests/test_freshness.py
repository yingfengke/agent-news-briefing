"""时效过滤测试：旧闻丢弃、无法判定时间的条目放行、内容不足时窗口放宽。"""
from datetime import datetime, timedelta, timezone

from src.core.models import NewsItem
from src.dedupe.freshness import filter_stale, _parse_published


def _item(title: str, hours_ago: float | None, source: str = "Test") -> NewsItem:
    published = ""
    if hours_ago is not None:
        dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        published = dt.isoformat()
    return NewsItem(id=title, title=title, content="正文内容足够长用于测试",
                    url=f"https://e.com/{title}", source=source,
                    lang="zh", source_type="rss", crawled_at="",
                    published_at=published)


def test_parse_published_handles_naive_and_bad_input():
    assert _parse_published("") is None
    assert _parse_published("not-a-date") is None
    # 无时区信息按 UTC 处理
    dt = _parse_published("2026-10-13T08:19:54")
    assert dt is not None and dt.tzinfo is not None


def test_stale_news_is_dropped():
    now = datetime.now(timezone.utc)
    items = [_item("新鲜", 2), _item("旧闻", 96)]
    kept = filter_stale(items, max_age_hours=72, min_keep=0, now=now)
    titles = [it.title for it in kept]
    assert "新鲜" in titles
    assert "旧闻" not in titles


def test_items_without_published_time_are_kept():
    now = datetime.now(timezone.utc)
    items = [_item("无时间", None), _item("解析失败", None)]
    items[1].published_at = "garbage"
    kept = filter_stale(items, max_age_hours=72, min_keep=0, now=now)
    assert len(kept) == 2


def test_future_timestamp_is_kept():
    """源站时区标注错误会产生未来时间，不做时效判定。"""
    now = datetime.now(timezone.utc)
    item = _item("未来时间", -10)
    kept = filter_stale([item], max_age_hours=72, min_keep=0, now=now)
    assert kept == [item]


def test_window_relaxes_when_content_too_low():
    """过滤后条数低于保护下限时窗口翻倍，避免简报被清空。"""
    now = datetime.now(timezone.utc)
    items = [_item("新鲜", 2), _item("三天前", 80), _item("三天前2", 85)]
    strict = filter_stale(items, max_age_hours=72, min_keep=0, now=now)
    assert len(strict) == 1
    relaxed = filter_stale(items, max_age_hours=72, min_keep=12, now=now)
    assert len(relaxed) == 3


def test_empty_input_passthrough():
    assert filter_stale([]) == []
