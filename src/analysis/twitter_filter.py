#!/usr/bin/env python3
"""
twitter_filter.py — 用免费模型精选 Twitter 内容
"""

import json
import re

from src import config
from src.core.models import NewsItem
from src.core.logger import get_logger
from urllib.request import Request, urlopen

log = get_logger("ai.twitter")


def _filter_twitter_items(twitter_items: list[NewsItem], model: str = "THUDM/GLM-Z1-9B-0414",
                          max_chars: int = 10000) -> list[NewsItem]:
    """
    用免费模型筛选 Twitter 内容，精选最有价值的 3-5 条。

    如果推文总字数超过 max_chars，自动拆分为两次请求，
    防止免费模型 context window 超限。
    """
    if not twitter_items or not config.API_KEY:
        return twitter_items[:3]

    lines = []
    for i, it in enumerate(twitter_items, 1):
        lines.append(f"{i}. [{it.source}] {it.title}\n   简介: {(it.content or '无描述')[:150]}")

    # 精选前：打印原始待筛推特清单，便于回溯智谱模型的取舍
    log.info("  -> Twitter 原始 %d 条待精选（%s 筛选）:", len(twitter_items), model)
    for i, it in enumerate(twitter_items, 1):
        log.info("       %2d. [%s] %s", i, it.source, (it.title or "")[:50])

    prompt_template = (
        "从以下 AI 推文中选出最有价值的 3-5 条。\n"
        "【优先保留】模型发布、技术突破、工具推荐、论文解读\n"
        "【过滤】纯个人观点、转发无评论、营销内容、无信息量的日常动态\n"
        "【去重】同一话题只保留信息量最丰富的一条\n"
        "只输出编号，用逗号分隔，如：1,3,5\n\n"
    )

    def _call_model(prompt_text: str, offset: int = 0) -> list[int]:
        """调用免费模型，返回选中编号（相对 offset 的原始索引）"""
        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": "你是一个 AI 资讯筛选助手，从推文中选出最有价值的几条。"},
                {"role": "user", "content": prompt_text},
            ],
            "temperature": 0.1,
            "max_tokens": 128,
        }).encode("utf-8")

        url = f"{config.API_BASE_URL.rstrip('/')}/v1/chat/completions"
        req = Request(url, data=payload, headers={
            "Authorization": f"Bearer {config.API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; BriefingBot/2.0)",
        })

        with urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        raw = result["choices"][0]["message"]["content"]
        log.info("       模型返回编号: %s", raw.strip()[:80] or "(空)")
        nums = [int(n.strip()) for n in re.split(r'[,，\s]+', raw) if n.strip().isdigit()]
        return [offset + n - 1 for n in nums if 1 <= n <= len(twitter_items[offset:])]

    # 估算输入总字符数，超限则分批
    total_chars = len(prompt_template) + sum(len(l) for l in lines)
    all_selected_indices = []

    try:
        if total_chars <= max_chars:
            prompt = prompt_template + "\n".join(lines)
            all_selected_indices = _call_model(prompt)
        else:
            # 分批：每批最大字符数为 max_chars 的一半（留余量）
            batch_size = max_chars // 2
            batches = []
            current_batch = []
            current_size = 0
            for l in lines:
                if current_size + len(l) > batch_size and current_batch:
                    batches.append(current_batch)
                    current_batch = []
                    current_size = 0
                current_batch.append(l)
                current_size += len(l)
            if current_batch:
                batches.append(current_batch)

            log.info("  -> Twitter 推文 %d 条 (%d 字符)，拆为 %d 批筛选",
                     len(twitter_items), total_chars, len(batches))

            offset = 0
            for batch_lines in batches:
                prompt = prompt_template + "\n".join(batch_lines)
                indices = _call_model(prompt, offset)
                all_selected_indices.extend(indices)
                offset += len(batch_lines)

        selected = [twitter_items[i] for i in all_selected_indices if 0 <= i < len(twitter_items)]
        if not selected:
            log.warning("  -> Twitter 精选: 模型未返回有效编号，回退保留前 3 条")
            selected = twitter_items[:3]
        log.info("  -> Twitter 精选: %d 条 -> %d 条 (%s)", len(twitter_items), len(selected), model)
        for it in selected:
            log.info("       选中 [%s] %s", it.source, (it.title or "")[:50])
        return selected
    except Exception as e:
        log.warning("Twitter 精选失败 (%s)，回退保留前 3 条", str(e)[:50])
        return twitter_items[:3]
