"""freshness.py - 阶段 A0: 时效过滤（丢弃超出时效窗口的旧闻）。

背景：RSS 的 published 是文章原始发布时间。某事件发布数日后，另有源转载或
二次上架，仍会作为新条目进入采集池，与「去重」是两回事——标题、链接、正文
都不同，URL / 指纹 / 语义三层去重均无法识别，只有按发布时间卡窗口才能阻断。

判定口径：
  - 有 published_at 且可解析 → 早于「现在 - 窗口」即丢弃
  - 无 published_at / 解析失败 / 时间在未来（时钟偏差）→ 一律保留
    （无法判断时效时不误杀，交由后续层级处理）
"""
from datetime import datetime, timedelta, timezone

from src import config
from src.core.models import NewsItem
from src.core.logger import get_logger

log = get_logger("dedup.freshness")


def _parse_published(iso: str):
    """解析 ISO 发布时间为带时区的 datetime；无法解析返回 None。"""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def filter_stale(items: list[NewsItem], max_age_hours: int | None = None,
                 min_keep: int | None = None, now: datetime | None = None) -> list[NewsItem]:
    """按时效窗口过滤旧闻。

    参数:
      items          — 待过滤条目
      max_age_hours  — 时效窗口（小时），默认取 config.NEWS_MAX_AGE_HOURS
      min_keep       — 内容量保护下限，默认 config.MIN_NEWS_ITEMS；
                       过滤后不足该条数时窗口翻倍重试一次，避免内容枯竭
      now            — 参照时刻（测试注入用），默认当前 UTC

    返回:
      过滤后的列表（顺序保持不变）
    """
    if not items:
        return items

    window = config.NEWS_MAX_AGE_HOURS if max_age_hours is None else max_age_hours
    floor = config.MIN_NEWS_ITEMS if min_keep is None else min_keep
    ref = now or datetime.now(timezone.utc)

    kept = _apply_window(items, window, ref)
    removed = len(items) - len(kept)
    if removed:
        log.info("  %d -> %d (时效过滤 %d 条，窗口 %d 小时)",
                 len(items), len(kept), removed, window)

    # 内容保护：窗口过紧导致条数不足时放宽一倍，宁可保留旧闻也不让简报空掉
    if kept and len(kept) < floor:
        wider = window * 2
        relaxed = _apply_window(items, wider, ref)
        if len(relaxed) > len(kept):
            log.warning("  -> 时效过滤后仅 %d 条（低于 %d），窗口放宽至 %d 小时，恢复 %d 条",
                        len(kept), floor, wider, len(relaxed) - len(kept))
            return relaxed

    return kept


def _apply_window(items: list[NewsItem], hours: int, ref: datetime) -> list[NewsItem]:
    """按给定窗口筛选：超出窗口的丢弃，其余（含无法判定时间的）保留。"""
    deadline = ref - timedelta(hours=hours)
    kept = []
    for it in items:
        published = _parse_published(getattr(it, "published_at", "") or "")
        if published is None:
            kept.append(it)
            continue
        # 时间在未来：源站时区标注错误或时钟偏差，不做时效判定
        if published > ref + timedelta(hours=1):
            kept.append(it)
            continue
        if published >= deadline:
            kept.append(it)
    return kept
