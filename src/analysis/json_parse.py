#!/usr/bin/env python3
"""
json_parse.py — AI 返回的 JSON 健壮解析与截断抢救
"""

import json
import re

from src.core.logger import get_logger

log = get_logger("ai.parse")

# JSON 解析质量监控
_json_parse_stats = {"total": 0, "direct_ok": 0, "fallback_comma": 0,
                     "fallback_quotes": 0, "fallback_salvage": 0, "failed": 0}


def _salvage_truncated_json(text: str) -> dict:
    """
    从格式不完整/结构残缺的 JSON 中抢救出完整的新闻条目。

    当模型输出的 JSON 尾部残缺（缺 } 或 ]）、或夹杂非结构化文本导致
    整体 json.loads 失败时，定位 news / items 数组起点，
    用括号平衡扫描逐条抽取【已完整闭合】的对象，丢弃末尾残缺的一条，
    最大限度救回已生成的内容，避免整期简报因输出格式问题而全盘降级。

    返回 {"news": [...]}（键名与调用方一致），无可救则返回 {}。
    """
    # 定位数组键：优先 news，其次 items；再兜底任何顶层数组（模型偶发换键名）
    key = None
    arr_start = -1
    for k in ("news", "items"):
        m = re.search(r'"' + k + r'"\s*:\s*\[', text)
        if m:
            key = k
            arr_start = m.end()  # 指向 [ 之后第一个字符
            break
    if key is None:
        m = re.search(r'"[A-Za-z_][A-Za-z0-9_]*"\s*:\s*\[', text)
        if m:
            arr_start = m.end()
        else:
            return {}

    objects = []
    i = arr_start
    n = len(text)
    while i < n:
        # 跳到下一个对象起点
        while i < n and text[i] != "{":
            if text[i] == "]":  # 数组正常结束
                i = n
                break
            i += 1
        if i >= n:
            break
        # 括号平衡扫描单个对象（考虑字符串内的括号与转义）
        depth = 0
        in_str = False
        esc = False
        obj_start = i
        while i < n:
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[obj_start:i + 1]
                        try:
                            objects.append(json.loads(candidate))
                        except json.JSONDecodeError:
                            pass
                        i += 1
                        break
            i += 1
        else:
            # 扫到结尾仍未闭合 → 末尾残缺对象，丢弃
            break

    if objects:
        return {"news": objects}
    return {}


def _safe_parse_json(text: str) -> dict:
    """
    健壮的 JSON 解析，兜底处理 AI 输出的各种不规范格式。

    兜底顺序：直接解析 → 去尾逗号 → 单引号转双引号 → 截断抢救。
    """
    _json_parse_stats["total"] += 1
    text = text.strip()
    if not text:
        _json_parse_stats["failed"] += 1
        return {}

    if text.startswith("```"):
        end_md = text.find("```", 3)
        if end_md != -1:
            text = text[3:end_md]
        else:
            text = text[3:]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()

    # 保留清洗后的原文，供截断抢救使用（抽 {} 会丢掉截断场景的有效内容）
    cleaned = text
    m = re.search(r"(\{[\s\S]*\})", text)
    if m:
        text = m.group(1)

    try:
        result = json.loads(text)
        _json_parse_stats["direct_ok"] += 1
        return result
    except json.JSONDecodeError:
        pass

    text = re.sub(r",\s*}", "}", text)
    text = re.sub(r",\s*]", "]", text)

    try:
        result = json.loads(text)
        _json_parse_stats["fallback_comma"] += 1
        return result
    except json.JSONDecodeError:
        pass

    text = re.sub(r"'([^']+)'(\s*[:,\]}])", lambda m: chr(34) + m.group(1) + chr(34) + m.group(2), text)

    try:
        result = json.loads(text)
        _json_parse_stats["fallback_quotes"] += 1
        return result
    except json.JSONDecodeError:
        pass

    # 第 5 层：残缺解析兜底（JSON 尾部残缺或夹杂非结构化文本时逐条抽取）
    salvaged = _salvage_truncated_json(cleaned)
    if salvaged:
        _json_parse_stats["fallback_salvage"] += 1
        log.warning("  JSON 残缺解析: 从非完整输出中救回 %d 条完整条目",
                    len(salvaged.get("news") or salvaged.get("items") or []))
        return salvaged

    _json_parse_stats["failed"] += 1
    return {}


def get_parse_stats():
    """返回 JSON 解析质量统计数据"""
    return dict(_json_parse_stats)


def reset_parse_stats():
    """重置 JSON 解析质量计数器"""
    _json_parse_stats["total"] = 0
    _json_parse_stats["direct_ok"] = 0
    _json_parse_stats["fallback_comma"] = 0
    _json_parse_stats["fallback_quotes"] = 0
    _json_parse_stats["fallback_salvage"] = 0
    _json_parse_stats["failed"] = 0
