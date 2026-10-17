"""history_titles.py - 跨天已推标题库。

只从 web/tech-briefing.html 取历史只能拿到上一期（页面每天被覆盖），跨天
事件级去重会漏掉「隔两三天又被另一源转载」的情况。这里把每期标题落到独立
文件并按天轮转，次日运行即可比对近 N 天的已推内容。

状态文件位于 web/.recent_titles.json，被 .gitignore 的 *.json 规则排除，
由 CI 的 Actions Cache 持久化（与 URL 去重库同机制）。

容错口径：文件缺失、损坏、写入失败一律不阻断主流程。
"""
import json
import os
from datetime import datetime, timedelta

from src import config
from src.core.logger import get_logger

log = get_logger("core.history_titles")

_MAX_TITLES_PER_DAY = 40


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


def load_recent_titles(days: int | None = None) -> list[str]:
    """返回近 N 天已推标题（最新在前，去重保序）。"""
    window = config.RECENT_TITLES_DAYS if days is None else days
    cutoff = (datetime.now() - timedelta(days=window)).strftime("%Y-%m-%d")

    titles: list[str] = []
    seen: set[str] = set()
    # 条目按日期升序保存，倒序遍历即最新在前
    for entry in reversed(_load_raw()):
        date = str(entry.get("date", ""))
        if date and date < cutoff:
            continue
        for t in entry.get("titles") or []:
            key = (t or "").strip()
            if key and key not in seen:
                seen.add(key)
                titles.append(key)
    return titles


def clear_today_titles(date_str: str = "") -> bool:
    """删除当日记录（同日重跑时调用，避免把上次运行推送的标题当成历史吃掉）。"""
    date = date_str or datetime.now().strftime("%Y-%m-%d")
    entries = _load_raw()
    kept = [e for e in entries if str(e.get("date", "")) != date]
    if len(kept) == len(entries):
        return False
    try:
        os.makedirs(os.path.dirname(config.RECENT_TITLES_FILE), exist_ok=True)
        with open(config.RECENT_TITLES_FILE, "w", encoding="utf-8") as f:
            json.dump({"entries": kept}, f, ensure_ascii=False, indent=1)
        log.info("  -> 同日重跑：已清除当日历史标题记录")
        return True
    except Exception as e:
        log.warning("清除当日历史标题失败: %s", e)
        return False


def record_titles(items, date_str: str = "") -> bool:
    """记录当日已推标题；同日重复写入时覆盖旧记录。返回是否写入成功。"""
    titles = []
    for it in items or []:
        title = ""
        if isinstance(it, dict):
            title = (it.get("title") or "").strip()
        else:
            title = (getattr(it, "title", "") or "").strip()
        if title:
            titles.append(title)
    if not titles:
        return False

    date = date_str or datetime.now().strftime("%Y-%m-%d")
    entries = [e for e in _load_raw() if str(e.get("date", "")) != date]
    entries.append({"date": date, "titles": titles[:_MAX_TITLES_PER_DAY]})
    entries.sort(key=lambda e: str(e.get("date", "")))

    try:
        os.makedirs(os.path.dirname(config.RECENT_TITLES_FILE), exist_ok=True)
        with open(config.RECENT_TITLES_FILE, "w", encoding="utf-8") as f:
            json.dump({"entries": entries}, f, ensure_ascii=False, indent=1)
        log.info("  -> 已记录当日 %d 条标题至历史库", len(titles))
        return True
    except Exception as e:
        log.warning("写入历史标题库失败: %s", e)
        return False
