#!/usr/bin/env python3
"""
models.py — 统一数据结构定义

所有模块（collector / deduplicator / generate_briefing）均引用此文件。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class NewsItem:
    """
    统一新闻数据项。

    字段说明：
      id          — SHA256(url)[:16]，全局唯一
      title       — 新闻标题（原始语言）
      content     — RSS源：摘要（若源提供）；爬虫源：正文前300字
      url         — 原文链接
      source      — 来源名称（如 "机器之心"、"量子位爬虫"）
      lang        — "zh" | "en"
      source_type — "rss" | "crawler"
      crawled_at  — 采集时间 ISO 格式
      published_at— 发布时间 ISO 格式（可选）
      tags        — 技术方向标签，如 ["Agent", "LangChain"]（可选）
      region      — 分组信息，由 AI 分析阶段填充："international" | "china"
      summary     — AI 生成的摘要，由 AI 分析阶段填充
    """
    id: str
    title: str
    content: str
    url: str
    source: str
    lang: str
    source_type: str
    crawled_at: str
    published_at: str = ""
    tags: list[str] = field(default_factory=list)
    region: str = ""
    summary: str = ""


@dataclass
class FilterReport:
    """
    过滤层执行报告，记录各阶段去重数量。
    """
    total_input: int = 0
    url_removed: int = 0
    minhash_removed: int = 0
    semantic_removed: int = 0
    credibility_removed: int = 0
    total_output: int = 0
    remaining_items: list[NewsItem] = field(default_factory=list)

    @property
    def total_removed(self) -> int:
        return self.url_removed + self.minhash_removed + self.semantic_removed + self.credibility_removed

    def print_report(self) -> None:
        print(f"\n  ── 过滤报告 ──")
        print(f"  输入: {self.total_input} 条")
        print(f"  ├─ URL去重:    -{self.url_removed} 条")
        print(f"  ├─ MinHash去重: -{self.minhash_removed} 条")
        print(f"  ├─ 语义去重:   -{self.semantic_removed} 条")
        print(f"  ├─ 可信度过滤: -{self.credibility_removed} 条")
        print(f"  └─ 输出:       {self.total_output} 条")

    def to_email_html(self) -> str:
        """生成用于邮件末尾的过滤摘要 HTML"""
        pct = f"({self.total_output/self.total_input*100:.0f}%)" if self.total_input else ""
        return f"""
        <tr>
          <td style="padding:16px 20px;background:#f8f8f6;border-radius:10px;margin-top:16px;">
            <div style="font-size:11px;color:#888;letter-spacing:1px;margin-bottom:8px;">📋 今日过滤摘要</div>
            <table width="100%" cellpadding="0" cellspacing="0" style="font-size:12px;color:#666;">
              <tr>
                <td style="padding:2px 0;">采集</td>
                <td style="text-align:right;font-weight:600;color:#333;">{self.total_input} 条</td>
              </tr>
              <tr>
                <td style="padding:2px 0;">URL去重</td>
                <td style="text-align:right;color:#c0392b;">-{self.url_removed} 条</td>
              </tr>
              <tr>
                <td style="padding:2px 0;">内容指纹去重</td>
                <td style="text-align:right;color:#c0392b;">-{self.minhash_removed} 条</td>
              </tr>
              <tr>
                <td style="padding:2px 0;">语义去重</td>
                <td style="text-align:right;color:#c0392b;">-{self.semantic_removed} 条</td>
              </tr>
              <tr>
                <td style="padding:2px 0;">可信度过滤</td>
                <td style="text-align:right;color:#c0392b;">-{self.credibility_removed} 条</td>
              </tr>
              <tr style="border-top:1px solid #ddd;">
                <td style="padding:4px 0;font-weight:700;color:#333;">最终输出 {pct}</td>
                <td style="text-align:right;font-weight:700;color:#27ae60;">{self.total_output} 条</td>
              </tr>
            </table>
          </td>
        </tr>"""
