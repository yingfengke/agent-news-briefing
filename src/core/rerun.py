"""rerun.py - 同日重跑判断与原始数据复用。

问题背景（2026-07-22 实战）：
  主模型连续超时 -> 兜底模型 LongCat-2.0 回垃圾 -> 触发内容降级
  _build_fallback_items 产出 67 条「降级版」简报并正常落库。
  同日重新触发 workflow 时，去重双库仍保留这 67 条：
    - web/tech-briefing.html 的 __NEWS_DATA__（历史标题排重数据源）
    - .url_dedup_db.json（URL 跨天去重库，无逐条时间戳，只能整体清空）
  导致新抓取的同日新闻相似度≈1.0 被历史排重 / URL 去重全部吃掉，
  重跑反而比首跑更空。

修复策略（复用优先、清空仅兜底）：每次正常跑把「已去重、未过 AI」的
clean_items 落盘到 RAW_CACHE_FILE；同日重跑时若有缓存则直接加载、
跳过采集+去重（仅重置历史标题排重），无缓存才退回清空去重库后重抓。
"""
import json
import os
import re
import tempfile

from src import config
from src.core.logger import get_logger
from src.core.models import NewsItem

log = get_logger("rerun")

# const __NEWS_DATA__ = [ ... ];  ->  const __NEWS_DATA__ = [];
_NEWS_DATA_RE = re.compile(r'(const\s+__NEWS_DATA__\s*=\s*)\[[\s\S]*?\]\s*;')


def _html_published_today() -> bool:
    """已提交的 tech-briefing.html 是否标记为今天（北京时间）。"""
    try:
        with open(config.HTML_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return False
    # 精确取生成日期：<p id="today-date">2026年07月22日</p>
    m = re.search(r'id="today-date">(\d{4})年(\d{2})月(\d{2})日', content)
    if not m:
        return False
    html_date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    today = config.now_bjt().strftime("%Y-%m-%d")
    return html_date == today


def is_rerun() -> bool:
    """
    判断本次是否为「同日重跑」。任一信号命中即视为重跑：
      1. GitHub Actions 对同一 workflow run 的「Re-run jobs」：
         GITHUB_RUN_ATTEMPT > 1
      2. 显式开关：环境变量 BRIEFING_RERUN=1/true/yes
         （本地调试，或手动重跑且首跑未落 HTML 时使用）
      3. 已提交网页的生成日期是今天（今天已成功跑过一次）
    """
    reasons = []

    attempt = os.getenv("GITHUB_RUN_ATTEMPT")
    if attempt and attempt.isdigit() and int(attempt) > 1:
        reasons.append(f"GITHUB_RUN_ATTEMPT={attempt}")

    if os.getenv("BRIEFING_RERUN", "").lower() in ("1", "true", "yes"):
        reasons.append("BRIEFING_RERUN 已置位")

    if _html_published_today():
        reasons.append("已提交网页生成日期为今天（今天已跑过）")

    if reasons:
        log.warning("检测到同日重跑，将清空去重库以重新抓取：%s", "；".join(reasons))
        return True
    return False


def _reset_html_news_data() -> None:
    """把已提交网页里的 __NEWS_DATA__ 重置为 []，使历史标题排重失效。"""
    try:
        with open(config.HTML_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return
    if "__NEWS_DATA__" not in content:
        return
    new_content = _NEWS_DATA_RE.sub(r"\1[];", content)
    if new_content != content:
        with open(config.HTML_FILE, "w", encoding="utf-8") as f:
            f.write(new_content)
        log.info("  已重置 %s 的 __NEWS_DATA__ 为空（历史排重将跳过）",
                 os.path.basename(config.HTML_FILE))


def clear_dedup_for_rerun() -> None:
    """
    同日重跑「无复用缓存」时的兜底：清空两个去重库，改走正常重新抓取。
    （有缓存时走 load_cached_clean_items 复用路径，不会调用本函数）
      1. .url_dedup_db.json：URL 跨天去重，无逐条时间戳，整体删除
      2. web/tech-briefing.html 的 __NEWS_DATA__：历史标题排重数据源，重置为 []
    """
    # 1) URL 去重库
    if os.path.exists(config.URL_DB_FILE):
        try:
            os.remove(config.URL_DB_FILE)
            log.info("  已删除 URL 去重库 %s", os.path.basename(config.URL_DB_FILE))
        except OSError as e:
            log.warning("  删除 URL 去重库失败（继续）: %s", e)

    # 2) 历史标题排重数据源
    _reset_html_news_data()


def save_clean_items(items: list[NewsItem]) -> None:
    """把「已去重、未过 AI」的 clean_items 落盘，供同日重跑复用（跳过采集+去重）。"""
    try:
        data = [vars(it) for it in items]
        dir_name = os.path.dirname(config.RAW_CACHE_FILE) or "."
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp_path, config.RAW_CACHE_FILE)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
        log.info("  已缓存 %d 条去重后原始数据到 %s（供同日重跑复用）",
                 len(items), os.path.basename(config.RAW_CACHE_FILE))
    except Exception as e:
        log.warning("  缓存原始数据失败（继续）: %s", e)


def load_cached_clean_items():
    """同日重跑时加载上次落盘的去重后原始数据；无缓存或损坏则返回 None（调用方改走正常采集）。"""
    try:
        if not os.path.exists(config.RAW_CACHE_FILE):
            return None
        with open(config.RAW_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list) or not data:
            return None
        items = [NewsItem(**d) for d in data]
        log.info("  已加载缓存的原始数据 %d 条（跳过采集与去重）", len(items))
        return items
    except Exception as e:
        log.warning("  加载缓存原始数据失败（改用重新采集）: %s", e)
        return None
