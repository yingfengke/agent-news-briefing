"""timefmt.py - 发布时间格式化（UTC -> 北京时间显示串）。
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src.core.models import NewsItem

def _fmt_published(iso: str) -> str:
    """把采集层抓到的 UTC ISO 发布时间转换为北京时间显示串（月-日 或 月-日 时:分）。"""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso)
    except Exception:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    bjt = dt.astimezone(ZoneInfo("Asia/Shanghai"))
    if bjt.hour == 0 and bjt.minute == 0:
        return f"{bjt.month:02d}-{bjt.day:02d}"
    return f"{bjt.month:02d}-{bjt.day:02d} {bjt.hour:02d}:{bjt.minute:02d}"


def _attach_published_at(final_items: list[dict], clean_items: list[NewsItem]) -> None:
    """
    采集层已抓取每条新闻的发布时间（NewsItem.published_at，UTC ISO），
    但 AI 输出 JSON 不含该字段，这里按 URL / 标题回关联到最终新闻条目，
    供网页卡片与邮件卡片展示"发布于 …"。
    """
    url_pub: dict[str, str] = {}
    title_pub: dict[str, str] = {}
    for ci in clean_items:
        if not ci.published_at:
            continue
        if ci.url:
            u = ci.url.strip()
            url_pub[u] = ci.published_at
            url_pub[u.rstrip("/").lower()] = ci.published_at
        title_pub[ci.title.strip()[:50].lower()] = ci.published_at

    for it in final_items:
        iso = ""
        u = (it.get("link") or "").strip()
        if u:
            iso = url_pub.get(u) or url_pub.get(u.rstrip("/").lower())
        if not iso:
            iso = title_pub.get((it.get("title") or "").strip()[:50].lower())
        if iso:
            it["published_at"] = iso
            it["published_at_disp"] = _fmt_published(iso)


# ============================================================
# 主流程
# ============================================================
