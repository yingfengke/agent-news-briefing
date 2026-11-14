"""event_cooldown.py - 跨期事件冷却：同一事件不重复占正文。

与批内配额的分工：
  apply_entity_quota / apply_event_quota 管「同一期里别堆同一个事件」；
  本模块管「跨期别让同一个事件反复上正文」。

判定有两条路径：
  1. 标题带「进展：」前缀，即跨天续报标注已判为同一事件（覆盖无型号标题）；
  2. 标题里的产品/型号标识命中近 N 天历史。

复用已有标注结果，不新增网络调用，也不往条目里写内部字段。
失败面只有历史库读取，读不到时仍可按路径 1 判定。

两个例外允许留在正文：
  1. 来源属于厂商/平台一手博客，且该条不是教程/观点类（视为当事方新动作）；
  2. 该条被至少 4 个不同来源报道，视为有足够信息增量。

来源数由调用方传入去重阶段的真实统计；查不到时才退回文本标注解析。
"""
import re

from src import config
from src.analysis.event_cluster import PROGRESS_PREFIX
from src.config.sources import OFFICIAL_SOURCE_NAMES
from src.core.entities import primary_key
from src.core.history_titles import load_recent_items
from src.core.logger import get_logger

log = get_logger("analysis.cooldown")

# 只用于收窄「官方一手来源」这个放行例外，不删除任何内容。
_COMMENTARY_RE = re.compile(
    r"教程|指南|如何|上手|入门|点评|观点|解读|实测|评测|分析|访谈|看法|盘点|综述|最佳实践")
_MULTI_SOURCE_COUNT_RE = re.compile(r"被\s*(\d+)\s*家(?:来源)?(?:报道|转载)")
_MULTI_SOURCE_LIST_RE = re.compile(r"来源报道[：:]\s*([^）)\]]+)")
_LOG_LIMIT = 10


def _score(item: dict) -> float:
    try:
        return float(item.get("score") or 0)
    except (TypeError, ValueError):
        return 0.0


def _source_count(item: dict, source_counts: dict | None = None) -> int:
    """优先取去重阶段的真实来源数；查不到时解析文本标注。"""
    structured = 0
    if source_counts:
        link = (item.get("link") or "").strip()
        title_key = (item.get("title") or "").strip()[:50].lower()
        try:
            structured = int(source_counts.get(link) or source_counts.get(title_key) or 0)
        except (TypeError, ValueError):
            structured = 0

    # 注记可能被后处理剥离到 footnote，四个字段一起看
    text = " ".join(str(item.get(k) or "")
                    for k in ("title", "summary", "content", "footnote"))
    parsed = 0
    m = _MULTI_SOURCE_COUNT_RE.search(text)
    if m:
        parsed = int(m.group(1))
    m = _MULTI_SOURCE_LIST_RE.search(text)
    if m:
        names = [x.strip() for x in re.split(r"[、,，;；]", m.group(1)) if x.strip()]
        parsed = max(parsed, len(names))
    return max(structured, parsed)


def _is_commentary(title: str) -> bool:
    return bool(_COMMENTARY_RE.search(title or ""))


def _is_progress(item: dict) -> bool:
    """跨天续报标注已判定为同一事件（标题带「进展：」前缀）。"""
    return (item.get("title") or "").startswith(PROGRESS_PREFIX)


def _is_exempt(item: dict, source_counts: dict | None = None) -> bool:
    """两个例外：当事方一手新动作，或被多家来源报道。"""
    if ((item.get("source") or "").strip() in OFFICIAL_SOURCE_NAMES
            and not _is_commentary(item.get("title") or "")):
        return True
    return _source_count(item, source_counts) >= config.EVENT_PROGRESS_MIN_SOURCES


def _history_keys(history_items) -> set[str]:
    keys = set()
    for it in history_items or []:
        key = primary_key(it.get("t") or it.get("title") or "")
        if key:
            keys.add(key)
    return keys


def build_source_counts(clean_items) -> dict:
    """按链接与标题建立去重阶段统计的来源数索引，避免污染最终条目字段。"""
    index: dict[str, int] = {}
    for ci in clean_items or []:
        try:
            n = int(getattr(ci, "source_count", 1) or 1)
        except (TypeError, ValueError):
            n = 1
        keys = []
        url = (getattr(ci, "url", "") or "").strip()
        if url:
            keys.append(url)
        title = (getattr(ci, "title", "") or "").strip()[:50].lower()
        if title:
            keys.append(title)
        for k in keys:
            index[k] = max(index.get(k, 1), n)
    return index


def apply_event_cooldown(display: list[dict], rest: list[dict],
                         history_items=None, days: int | None = None,
                         source_counts: dict | None = None):
    """近 N 天报过的事件键默认转入简讯，空出名额由待展示区补入。

    返回 (display, rest)。只调整展示位置，不删除任何条目。
    """
    window = config.EVENT_COOLDOWN_DAYS if days is None else days
    if history_items is None:
        try:
            history_items = load_recent_items(days=window)
        except Exception as e:
            log.warning("  事件冷却: 历史库读取失败 (%s)，仅依据续报标注判定", e)
            history_items = []

    seen = _history_keys(history_items)
    has_progress = any(_is_progress(it) for it in list(display) + list(rest))
    if not seen and not has_progress:
        return display, rest

    def cooled(item: dict) -> bool:
        if _is_exempt(item, source_counts):
            return False
        if _is_progress(item):
            return True
        key = primary_key(item.get("title") or "")
        return bool(key and key in seen)

    kept, demoted = [], []
    for item in display:
        (demoted if cooled(item) else kept).append(item)

    if not demoted:
        return display, rest

    target = len(display)
    remaining = []
    for item in rest:
        if len(kept) < target and not cooled(item):
            kept.append(item)
        else:
            remaining.append(item)

    for item in demoted[:_LOG_LIMIT]:
        title = item.get("title") or ""
        reason = "续报标注" if _is_progress(item) else "键 " + primary_key(title)
        log.info("  事件冷却: %s -> 简讯 (%s)", title[:40], reason)
    log.info("  事件冷却: %d 条同事件内容转入简讯，补入 %d 条（型号键窗口 %d 天）",
             len(demoted), len(kept) - (len(display) - len(demoted)), window)

    kept.sort(key=_score, reverse=True)
    demoted.extend(remaining)
    demoted.sort(key=_score, reverse=True)
    return kept, demoted
