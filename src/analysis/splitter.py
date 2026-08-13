#!/usr/bin/env python3
"""
splitter.py — 用免费小模型把混排的新闻文本分割为「事实摘要 + 分析点评」两部分。

仅深度解读 / 极客观点两种段落式风格使用：它们的摘要与分析混在同一段里、
没有冒号前缀，正则无法可靠区分边界。分割在主模型提示词之外独立进行——
主模型零改动，不要求它输出额外字段；由免费模型 THUDM/GLM-Z1-9B-0414
（与 twitter_filter 精选同一个模型，不占用主模型配额）完成切分。

失败时安全回退：该条 analysis 留空、summary 保持原样，不阻塞流水线；
连续失败超过阈值则整体放弃本次分割，避免逐条超时拖垮 CI。
"""

import json

from urllib.request import Request, urlopen

from src import config
from src.core.logger import get_logger

log = get_logger("ai.split")

# 需要分割的段落式风格（其余风格的分析结构有冒号前缀，正则即可处理）
SPLIT_STYLES = {"深度解读", "极客观点"}

# 与 twitter_filter 共用的免费模型
_SPLIT_MODEL = "THUDM/GLM-Z1-9B-0414"

# 单条超时与连续失败熔断阈值
_TIMEOUT = 30
_MAX_CONSECUTIVE_FAIL = 3

_PROMPT_TEMPLATE = (
    "你是新闻文本分割助手。把下面这条 AI 生成的新闻文本分割为两部分：\n"
    "1. 事实摘要：客观陈述事件本身的句子（谁发布了什么、发生了什么），不含任何点评。\n"
    "2. 分析点评：其余全部内容（技术原理、架构变化、工程启示、性能数据、主观点评等），保持原文措辞，尽量完整。\n"
    "要求：\n"
    "- 事实摘要必须包含原文里陈述事件的那部分文字\n"
    "- 如果整段都是客观陈述、没有分析内容，analysis 输出空字符串\n"
    "- 只输出 JSON：{{\"summary\": \"...\", \"analysis\": \"...\"}}，不要多余文字或解释\n\n"
    "文本：\n{text}"
)


def _call_model(text: str) -> dict:
    """调用免费模型分割单条文本，返回 {summary, analysis}。异常向上抛。"""
    payload = json.dumps({
        "model": _SPLIT_MODEL,
        "messages": [
            {"role": "system", "content": "你是一个新闻文本分割助手，把摘要与分析分开。"},
            {"role": "user", "content": _PROMPT_TEMPLATE.format(text=text[:2000])},
        ],
        "temperature": 0.1,
        "max_tokens": 512,
    }).encode("utf-8")

    url = f"{config.API_BASE_URL.rstrip('/')}/v1/chat/completions"
    req = Request(url, data=payload, headers={
        "Authorization": f"Bearer {config.API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; BriefingBot/2.0)",
    })

    with urlopen(req, timeout=_TIMEOUT) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    raw = result["choices"][0]["message"]["content"]
    parsed = json.loads(raw.strip())
    return {"summary": (parsed.get("summary") or "").strip(),
            "analysis": (parsed.get("analysis") or "").strip()}


def split_analysis(summary: str) -> tuple[str, str]:
    """把一条混排文本分割为 (摘要, 分析)。失败时返回 (原样, "")。"""
    if not summary:
        return summary, ""
    try:
        parts = _call_model(summary)
    except Exception as e:
        log.warning("分割失败（该条跳过）: %s | %s", str(e)[:100], summary[:50])
        return summary, ""
    head, tail = parts.get("summary"), parts.get("analysis")
    if not head:  # 模型把全部内容当分析 → 回退原样
        return summary, ""
    return head, tail


def split_items(items: list[dict]) -> None:
    """为每条 item 增加 analysis 字段（分割自 summary），summary 同步缩减。

    连续失败超过阈值整体放弃（避免逐条超时拖垮 CI），不抛异常。
    """
    consecutive_fail = 0
    for it in items:
        s = it.get("summary") or ""
        if not s:
            continue
        head, tail = split_analysis(s)
        if tail:
            it["analysis"] = tail
            it["summary"] = head
            consecutive_fail = 0
        else:
            consecutive_fail += 1
            if consecutive_fail >= _MAX_CONSECUTIVE_FAIL:
                log.warning("分割器连续失败 %d 次，放弃本次分割", consecutive_fail)
                return
