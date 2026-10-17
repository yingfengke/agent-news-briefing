"""history_titles.py - 跨天已推内容库（标题 + 摘要）。

只从 web/tech-briefing.html 取历史只能拿到上一期（页面每天被覆盖），跨天
事件级去重会漏掉「隔两三天又被另一源转载」的情况。这里把每期标题与摘要
落到独立文件并按天轮转，次日即可比对近期已推内容。

为什么存摘要：同一事件在不同源往往换了措辞，标题层面可能毫无交集
（「Z.ai 发布 GLM-Legal」 vs「智谱推出 GLM-Legal」），但摘要里的实体、
场景词高度重合，内容级比对才能命中。

状态文件位于 web/.recent_titles.json，被 .gitignore 的 *.json 规则排除，
由 CI 的 Actions Cache 持久化（与 URL 去重库同机制）。写入时裁剪超过
保留天数的条目，控制文件体积。

容错口径：文件缺失、损坏、写入失败一律不阻断主流程。
"""
import json
import os
from datetime import datetime, timedelta

from src import config
from src.core.logger import get_logger

log = get_logger("core.history_titles")

_MAX_ITEMS_PER_DAY = 40
# 字段名压缩以控制体积：t=标题，s=摘要
_TITLE_KEY = "t"
_SUMMARY_KEY = "s"


def _load_raw() -> list[dict]:
    """读取历史条目（结构损坏时返回空列表）。"""
    path = config.RECENT_TITLES_FILE
    try:
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        entries = data.get("entries")
        return entries if isinstance(entries, list) else []
    except Exception as e:
        log.warning("读取历史标题库失败: %s", e)
        return []


def _entry_items(entry: dict) -> list[dict]:
    """统一取出某天的条目；兼容早期只存标题数组的格式。"""
    items = entry.get("items")
    if isinstance(items, list):
        return [it for it in items if isinstance(it, dict)]
    legacy = entry.get("titles")
    if isinstance(legacy, list):
        return [{_TITLE_KEY: t, _SUMMARY_KEY: ""} for t in legacy if t]
    return []


def _cutoff(days: int) -> str:
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")


def load_recent_items(days: int | None = None) -> list[dict]:
    """返回近 N 天的已推条目（最新在前），元素形如 {"t": 标题, "s": 摘要}。"""
    window = config.RECENT_TITLES_DAYS if days is None else days
    cutoff = _cutoff(window)

    items: list[dict] = []
    seen: set[str] = set()
    # 条目按日期升序保存，倒序遍历即最新在前
    for entry in reversed(_load_raw()):
        date = str(entry.get("date", ""))
        if date and date < cutoff:
            continue
        for it in _entry_items(entry):
            title = (it.get(_TITLE_KEY) or "").strip()
            if not title or title in seen:
                continue
            seen.add(title)
            items.append({_TITLE_KEY: title, _SUMMARY_KEY: (it.get(_SUMMARY_KEY) or "").strip()})
    return items


def load_recent_titles(days: int | None = None) -> list[str]:
    """返回近 N 天已推标题（最新在前，去重保序）。"""
    return [it[_TITLE_KEY] for it in load_recent_items(days)]


def _prune(entries: list[dict], days: int) -> list[dict]:
    """丢弃超出保留期的日期条目，避免状态文件无限增长。"""
    cutoff = _cutoff(days)
    return [e for e in entries if str(e.get("date", "")) >= cutoff]


def clear_today_titles(date_str: str = "") -> bool:
    """删除当日记录（同日重跑时调用，避免把上次运行推送的标题当成历史吃掉）。"""
    date = date_str or datetime.now().strftime("%Y-%m-%d")
    entries = _load_raw()
    kept = [e for e in entries if str(e.get("date", "")) != date]
    if len(kept) == len(entries):
        return False
    return _write(kept, "已清除当日历史记录")


def record_titles(items, date_str: str = "") -> bool:
    """记录当日已推内容（标题 + 摘要）；同日重复写入时覆盖旧记录。"""
    records = []
    for it in items or []:
        if isinstance(it, dict):
            title = (it.get("title") or "").strip()
            summary = (it.get("summary") or "").strip()
        else:
            title = (getattr(it, "title", "") or "").strip()
            summary = (getattr(it, "content", "") or "").strip()
        if title:
            records.append({_TITLE_KEY: title, _SUMMARY_KEY: summary[:300]})
    if not records:
        return False

    date = date_str or datetime.now().strftime("%Y-%m-%d")
    entries = [e for e in _load_raw() if str(e.get("date", "")) != date]
    entries.append({"date": date, "items": records[:_MAX_ITEMS_PER_DAY]})
    entries.sort(key=lambda e: str(e.get("date", "")))
    entries = _prune(entries, config.RECENT_TITLES_DAYS)
    return _write(entries, f"已记录当日 {len(records)} 条内容")


def _write(entries: list[dict], log_msg: str) -> bool:
    try:
        os.makedirs(os.path.dirname(config.RECENT_TITLES_FILE), exist_ok=True)
        with open(config.RECENT_TITLES_FILE, "w", encoding="utf-8") as f:
            json.dump({"entries": entries}, f, ensure_ascii=False, indent=1)
        log.info("  -> %s", log_msg)
        return True
    except Exception as e:
        log.warning("写入历史内容库失败: %s", e)
        return False
