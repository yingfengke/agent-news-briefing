#!/usr/bin/env python3
"""
translate.py — 纯英文标题翻译兜底
"""

import json

from src import config
from src.core.logger import get_logger
from urllib.request import Request, urlopen

log = get_logger("ai.translate")


def _translate_english_titles(items: list[dict]) -> list[dict]:
    """
    兜底：将纯英文标题翻译成中文（保留技术术语原文）。
    """
    need = []
    for i, it in enumerate(items):
        title = it.get("title", "")
        if not title:
            continue
        cn = sum(1 for c in title if '\u4e00' <= c <= '\u9fff')
        if cn == 0:
            need.append((i, title))
    if not need:
        return items
    log.info("")
    log.info("  翻译兜底: %d 条纯英文标题，正在翻译...", len(need))
    lines = "\n".join(f"{j+1}. {t}" for j, (_, t) in enumerate(need))
    prompt = f"将以下英文标题翻译成自然中文，技术名词（GPT-5O、Agent、RAG、MoE等）保留英文：\n{lines}"
    payload = json.dumps({"model": config.MODEL_NAME, "messages": [
        {"role": "system", "content": "你专业翻译技术标题。"},
        {"role": "user", "content": prompt},
    ], "temperature": 0.1}).encode("utf-8")
    try:
        url = f"{config.API_BASE_URL.rstrip('/')}/v1/chat/completions"
        req = Request(url, data=payload, headers={
            "Authorization": f"Bearer {config.API_KEY}",
            "Content-Type": "application/json",
        })
        with urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
            result = json.loads(body)
        text = result["choices"][0]["message"]["content"]
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line or not line[0].isdigit():
                continue
            parts = line.split(".", 1)
            if len(parts) != 2:
                continue
            try:
                idx = int(parts[0].strip()) - 1
                translated = parts[1].strip()
                if 0 <= idx < len(need):
                    oi = need[idx][0]
                    old = items[oi]["title"]
                    items[oi]["title"] = translated
                    log.info("    %s... -> %s", old[:35], translated[:35])
            except (ValueError, IndexError):
                continue
        log.info("  翻译兜底完成 %d 条", len(need))
    except Exception as e:
        log.warning("  翻译兜底失败: %s", str(e)[:60])
    return items
