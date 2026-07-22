#!/usr/bin/env python3
"""
orchestrator.py - 分析编排 facade

上下文预组装（context）+ 模型调用与重试（invoke）已拆为同包子模块，
本文件仅做编排入口并重新导出公共符号，使调用方从 src.analysis 导入即可。
"""

from src.analysis.context import (
    load_history_titles,
    _prescreen_items,
    _balance_sources,
    _estimate_tokens,
    _filter_history_duplicates,
    _build_context,
    _truncate_context,
    _MAX_OUTPUT_TOKENS,
)
from src.analysis.invoke import call_ai_analysis, _try_model

__all__ = [
    "call_ai_analysis",
    "load_history_titles",
    "_prescreen_items",
    "_balance_sources",
    "_estimate_tokens",
    "_filter_history_duplicates",
    "_build_context",
    "_truncate_context",
    "_try_model",
    "_MAX_OUTPUT_TOKENS",
]
