#!/usr/bin/env python3
"""
twitter_filter.py — 用免费模型精选 Twitter 内容
"""

import json
import re

from src import config
from src.core.models import NewsItem
from src.core.logger import get_logger
from src.core.http_utils import http_error_detail
from urllib.request import Request, urlopen

log = get_logger("ai.twitter")

_PROMPT_TEMPLATE = (
    "从以下 AI 推文中选出最有价值的 3-5 条。\n"
    "【优先保留】模型发布、技术突破、工具推荐、论文解读\n"
    "【过滤】纯个人观点、转发无评论、营销内容、无信息量的日常动态\n"
    "【去重】同一话题只保留信息量最丰富的一条\n"
    "只输出编号，用逗号分隔，如：1,3,5\n\n"
)


def _filter_twitter_items(twitter_items: list[NewsItem], model: str | None = None,
                          max_chars: int = 10000) -> list[NewsItem]:
    """
    用免费模型筛选 Twitter 内容，精选最有价值的 3-5 条。

    如果推文总字数超过 max_chars，自动拆分为两次请求，
    防止免费模型 context window 超限。

    轻量模型失败时改用主模型重试一次：免费模型额度受限时整批会失败，
    直接回退前 3 条会把筛选完全退化成按顺序取数。
    """
    model = model or config.TWITTER_FILTER_MODEL_NAME
    if not twitter_items:
        log.info("  -> 无 Twitter 条目，跳过精选（未发起模型调用）")
        return []
    if not config.API_KEY:
        log.warning("  -> 未配置 API_KEY，跳过 Twitter 精选（未发起模型调用），保留前 3 条")
        return twitter_items[:3]

    lines = []
    for i, it in enumerate(twitter_items, 1):
        lines.append(f"{i}. [{it.source}] {it.title}\n   简介: {(it.content or '无描述')[:150]}")

    # 精选前：打印原始待筛推特清单，便于回溯模型的取舍
    log.info("  -> Twitter 原始 %d 条待精选:", len(twitter_items))
    for i, it in enumerate(twitter_items, 1):
        log.info("       %2d. [%s] %s", i, it.source, (it.title or "")[:50])

    def _run(mdl: str) -> list[NewsItem]:
        """按指定模型跑一次完整筛选流程。"""
        def _call_model(prompt_text: str, offset: int = 0) -> list[int]:
            """调用模型，返回选中编号（相对 offset 的原始索引）"""
            payload = json.dumps({
                "model": mdl,
                "messages": [
                    {"role": "system",
                     "content": "你是一个 AI 资讯筛选助手，从推文中选出最有价值的几条。"},
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
            log.info("       模型返回编号 [%s]: %s", mdl, raw.strip()[:80] or "(空)")
            nums = [int(n.strip()) for n in re.split(r'[,，\s]+', raw) if n.strip().isdigit()]
            return [offset + n - 1 for n in nums if 1 <= n <= len(twitter_items[offset:])]

        total_chars = len(_PROMPT_TEMPLATE) + sum(len(l) for l in lines)
        all_selected_indices = []

        if total_chars <= max_chars:
            all_selected_indices = _call_model(_PROMPT_TEMPLATE + "\n".join(lines))
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
                prompt = _PROMPT_TEMPLATE + "\n".join(batch_lines)
                indices = _call_model(prompt, offset)
                all_selected_indices.extend(indices)
                offset += len(batch_lines)

        selected = [twitter_items[i] for i in all_selected_indices
                    if 0 <= i < len(twitter_items)]
        if not selected:
            log.warning("  -> [%s] 未返回有效编号，回退保留前 3 条", mdl)
            return twitter_items[:3]
        return selected

    try:
        selected = _run(model)
        log.info("  -> Twitter 精选: %d 条 -> %d 条 (%s)",
                 len(twitter_items), len(selected), model)
        for it in selected:
            log.info("       选中 [%s] %s", it.source, (it.title or "")[:50])
        return selected
    except Exception as e:
        log.warning("Twitter 精选失败 (%s) [%s]", http_error_detail(e), model)
        if config.MODEL_NAME and config.MODEL_NAME != model:
            try:
                selected = _run(config.MODEL_NAME)
                log.info("  -> Twitter 精选(主模型兜底): %d 条 -> %d 条 (%s)",
                         len(twitter_items), len(selected), config.MODEL_NAME)
                for it in selected:
                    log.info("       选中 [%s] %s", it.source, (it.title or "")[:50])
                return selected
            except Exception as e2:
                log.warning("Twitter 精选主模型兜底也失败 (%s)", http_error_detail(e2))
        return twitter_items[:3]
