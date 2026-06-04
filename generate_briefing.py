#!/usr/bin/env python3
"""
generate_briefing.py — AI & Agent 开发者晨报 主流程编排器

职责：
  1. 调用采集层 → 获取原始新闻数据池
  2. 调用过滤层 → 去重/评分得到干净数据
  3. AI 智能筛选与摘要生成
  4. 写入 HTML + 生成邮件 + 发送

架构：
  collector.py (采集层)
    → deduplicator.py (过滤层)
      → 本文件 (AI分析 + HTML生成 + 邮件发送)

三层架构，每层独立模块，协同工作。
"""

import json
import os
import re
import sys
from datetime import datetime
from urllib.request import Request, urlopen

import config
from config import get_random_style, get_random_trivia
from models import NewsItem, FilterReport
from collector import collect_all
from deduplicator import run_pipeline


# ============================================================
# Markdown 链接清洗（用于邮件安全嵌入）
# ============================================================

def clean_links(text: str) -> str:
    """
    将 Markdown 格式的链接和裸 URL 转换为 HTML <a> 标签。
    包含清洗自检（发现遗留的 Markdown 链接会告警）。

    转换规则：
      - [文字](url) → <a href="url" target="_blank">文字</a>
      - 裸 URL (http/https) → <a href="url" target="_blank">url</a>
    """
    if not text:
        return text

    # 1. 转换 Markdown 内联链接
    cleaned = re.sub(
        r'\[([^\]]+)\]\(([^)]+)\)',
        r'<a href="\2" target="_blank">\1</a>',
        text,
    )

    # 2. 转换裸 URL（排除已包裹在 <a> 标签内的）
    #    用 (?![^<]*</a>) 确保不会重复包装已有 <a> 的 URL
    cleaned = re.sub(
        r'(https?://[^\s<>)\]】、，,]+)(?![^<]*</a>)',
        r'<a href="\1" target="_blank">\1</a>',
        cleaned,
    )

    # 3. 自检：是否还有未转换的 Markdown 链接
    remaining = re.findall(r'\[([^\]]+)\]\(', cleaned)
    if remaining:
        print(f"  [LINK-CHECK] ⚠ 发现 {len(remaining)} 个未转换的 Markdown 链接: {remaining}")

    return cleaned


# ============================================================
# AI 分析
# ============================================================

def load_history_titles():
    """
    从 tech-briefing.html 中读取 __NEWS_DATA__ 数组并提取标题，
    用于 AI 排重（避免每日重复报道相似内容）。
    """
    try:
        with open(config.HTML_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        m = re.search(r'const\s+__NEWS_DATA__\s*=\s*(\[[\s\S]*?\])\s*;', content)
        if not m:
            return []
        data = json.loads(m.group(1))
        titles = [item.get("title", "") for item in data if item.get("title")]
        return titles
    except Exception as e:
        print(f"  [警告] 读取历史简报用于排重时出错: {e}")
        return []


def _balance_sources(items: list, max_total: int = 30, min_per_source: int = 2, min_sources: int = 5) -> list:
    """
    来源配额制：先按来源分桶，每源保底 2 条，
    再从剩余池中补满到 max_total 条，确保覆盖至少 min_sources 个源。
    """
    from collections import defaultdict
    buckets = defaultdict(list)
    for it in items:
        buckets[it.source].append(it)

    # 每源保底
    selected = []
    remaining = []
    for source, src_items in buckets.items():
        selected.extend(src_items[:min_per_source])
        remaining.extend(src_items[min_per_source:])

    # 按内容长度降序排列（内容越丰富优先级越高）
    remaining.sort(key=lambda x: len(x.content or ""), reverse=True)

    # 补满到 max_total
    needed = max_total - len(selected)
    if needed > 0 and remaining:
        selected.extend(remaining[:needed])

    source_count = len(set(it.source for it in selected))
    print(f"  → 配额后: {len(selected)} 条（覆盖 {source_count} 个来源）")
    return selected


# ============================================================
# Token 估算 & 上下文截断
# ============================================================

def _estimate_tokens(text: str) -> int:
    """
    保守估算文本的 token 数，用于上下文截断判断。
    中文字符按 2 tokens，其余按 0.3 tokens 估算。
    优先高估，避免 API 返回 400 错误。
    """
    if not text:
        return 0
    chinese = len(re.findall(r'[\u4e00-\u9fff]', text))
    rest = len(text) - chinese
    return int(chinese * 2.0 + rest * 0.3)


def _filter_history_duplicates(items: list[NewsItem]) -> list[NewsItem]:
    """
    基于历史简报标题，过滤掉内容高度重复的新闻。
    可跨天，解决同源"顽固新闻"反复出现的问题。

    使用双重检测：
      A) SequenceMatcher（字符级，能抵抗 AI 改写标点和虚词）
      B) 关键词重叠率（覆盖完全重写但核心词不变的情况）
    """
    from difflib import SequenceMatcher

    history_titles = load_history_titles()
    if not history_titles:
        return items

    def _normalize(title: str) -> str:
        """去标点 + 小写，用于字符级比较"""
        return re.sub(r'[\s：:，,、()（）\[\]【】|/／\-—\'\"「」『』]', '', title).lower()

    def _keywords(title: str) -> set:
        """按分隔符提取关键词"""
        parts = re.split(r'[\s：:，,、()（）\[\]【】|/／\-—\'\"「」『』]', title.lower())
        return set(w.strip() for w in parts if len(w.strip()) > 2)

    norm_history = [_normalize(t) for t in history_titles[:30]]
    kw_history = [_keywords(t) for t in history_titles[:30]]

    kept = []
    removed = 0
    for it in items:
        norm_current = _normalize(it.title)
        kw_current = _keywords(it.title)

        is_dup = False
        for i in range(len(norm_history)):
            # A) 字符级相似度（抗标点/虚词差异）
            if len(norm_history[i]) > 5 and len(norm_current) > 5:
                ratio = SequenceMatcher(None, norm_history[i], norm_current).ratio()
                if ratio > 0.50:
                    is_dup = True
                    break

            # B) 关键词重叠率（抗完全重写）
            if kw_history[i] and kw_current:
                overlap = len(kw_current & kw_history[i])
                min_size = min(len(kw_current), len(kw_history[i]))
                # 精确重叠
                if min_size > 0 and overlap / min_size > 0.5:
                    is_dup = True
                    break
                # 子串重叠：当前关键词作为历史关键词的子串（例如 "goose" in "goose免费提供"）
                for ck in kw_current:
                    for hk in kw_history[i]:
                        if len(ck) > 3 and len(hk) > 3 and (ck in hk or hk in ck):
                            is_dup = True
                            break
                    if is_dup:
                        break

        if is_dup:
            removed += 1
        else:
            kept.append(it)

    if removed:
        print(f"  → 历史排重: 过滤 {removed} 条已报道过的新闻")
    return kept


def _build_context(items_for_ai: list[NewsItem], system_prompt: str,
                   content_limit: int = 80, max_items: int | None = None):
    """
    构建完整的 user 消息（含前文 + 新闻列表 + 历史排重），
    同时返回各部分的 token 估算值。
    """
    # 固定前文
    preamble_lines = [
        "以下是今日抓取的科技新闻，请按你的系统指令处理：\n",
        "【摘要要求】每条摘要字数控制在 80-150 字之间，不要过短或过长。"
        "摘要中只写新闻内容本身，不要包含任何链接或URL。\n",
        "【链接要求】请在每条新闻的 JSON 输出中保留 url 字段，"
        "值为原文链接。\n",
        "【来源多样性要求】在筛选过程中，如果某条新闻不值得单独成条，"
        "可以合并到相关新闻的摘要中提及，确保最终简报覆盖尽可能多的来源和话题。\n",
    ]
    preamble_text = "".join(preamble_lines)
    preamble_tokens = _estimate_tokens(preamble_text)

    # 新闻列表
    max_items = max_items or len(items_for_ai)
    item_lines = []
    for i, item in enumerate(items_for_ai[:max_items], 1):
        content_short = (item.content or "无描述")[:content_limit]
        time_info = f" ({item.published_at[:10]})" if item.published_at else ""
        item_lines.append(f"{i}. [{item.source}]{time_info} {item.title}")
        item_lines.append(f"   简介: {content_short}")
        item_lines.append(f"   链接: {item.url}\n")
    items_text = "\n".join(item_lines)
    items_tokens = _estimate_tokens(items_text)
    actual_items = min(max_items, len(items_for_ai))

    # 历史排重
    history_titles = load_history_titles()
    history_text = ""
    if history_titles:
        history_text = ("\n---\n【已报道历史】过去几天已推送过的新闻标题"
                        "（遇到核心主题相似的请跳过）：\n" +
                        "\n".join(f"- {t}" for t in history_titles))
    history_tokens = _estimate_tokens(history_text)

    # 系统 prompt
    system_tokens = _estimate_tokens(system_prompt)

    user_content = preamble_text + items_text + history_text

    total_tokens = system_tokens + preamble_tokens + items_tokens + history_tokens

    return {
        "user_content": user_content,
        "total_tokens": total_tokens,
        "system_tokens": system_tokens,
        "item_count": actual_items,
        "content_limit": content_limit,
    }


def _truncate_context(items_for_ai: list[NewsItem], system_prompt: str,
                      max_context: int = 32000,
                      max_output: int = 4096,
                      safety_margin: int = 800):
    """
    渐进式截断流程：
      1. content_short 从 80 字缩到 50 字
      2. max_items 从当前值缩到 25 → 20
    保留配额制核心（每源保底 2 条、至少 5 个源）不变。
    """
    token_budget = max_context - max_output - safety_margin

    content_limit = 80
    max_items = len(items_for_ai)

    for step in range(10):  # 最多 10 轮降级
        ctx = _build_context(items_for_ai, system_prompt,
                             content_limit=content_limit, max_items=max_items)
        if ctx["total_tokens"] <= token_budget:
            return ctx

        # 降级策略
        if content_limit > 50:
            old = content_limit
            content_limit = 50
            print(f"  → 上下文超限 ({ctx['total_tokens']} > {token_budget})，"
                  f"content 缩短 {old}→{content_limit} 字")
            continue
        if max_items > 25:
            max_items = 25
            print(f"  → 上下文仍超限，总条数缩至 {max_items}")
            continue
        if max_items > 20:
            max_items = 20
            print(f"  → 上下文仍超限，总条数缩至 {max_items}")
            continue

        print(f"  ⚠ 已达最大截断仍超限 ({ctx['total_tokens']} > {token_budget})，继续发送")
        break

    return _build_context(items_for_ai, system_prompt,
                          content_limit=content_limit, max_items=max_items)


def call_ai_analysis(items: list[NewsItem], max_retries: int = 3):
    """
    将过滤后的干净新闻发给大模型。

    特性：
      - 每天随机一种语气（极简/毒舌/深度）
      - 失败自动重试，最多 3 次，间隔 5 秒
      - 解析新 JSON 格式（含 news 字段）

    返回:
      (style_name, parsed_json)  成功
      (style_name, None)          全部失败
    """
    if not config.API_KEY:
        print("[警告] 未配置 API_KEY，跳过 AI 分析")
        return ("", None)

    # 随机选择语气
    style_name, system_prompt = get_random_style()
    print(f"\n  → 今日风格: [{style_name}]")

    # 来源配额制：每源保底 → 补满到 30 条 → 全量喂给 AI
    balanced = _balance_sources(items)
    zh_items = [it for it in balanced if it.lang == "zh"]
    en_items = [it for it in balanced if it.lang == "en"]
    items_for_ai = en_items + zh_items
    print(f"  → 喂给 AI: 英文 {len(en_items)} 条 + 中文 {len(zh_items)} 条 = {len(items_for_ai)} 条")

    # 跨天历史排重：过滤已报道过的同源新闻
    items_for_ai = _filter_history_duplicates(items_for_ai)
    if not items_for_ai:
        print("  [警告] 所有新闻均已被历史报道过滤，将继续使用 AI 判断")

    # 渐进截断：先缩 content（80→50），再缩总量（→25→20）
    ctx = _truncate_context(items_for_ai, system_prompt)
    user_content = ctx["user_content"]
    print(f"  → 最终输入: {ctx['content_limit']}字摘要 × {ctx['item_count']}条 "
          f"(预估 {ctx['total_tokens']} tokens, 系统 {ctx['system_tokens']} tokens)")

    url = f"{config.API_BASE_URL.rstrip('/')}/v1/chat/completions"

    # 重试循环
    for attempt in range(1, max_retries + 1):
        print(f"\n  → 调用 AI 分析 ({config.MODEL_NAME}) ... ", end="", flush=True)

        payload = json.dumps({
            "model": config.MODEL_NAME,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_content},
            ],
            "temperature": 0.3,
            "max_tokens": 4096,
        }).encode("utf-8")

        req = Request(url, data=payload, headers={
            "Authorization": f"Bearer {config.API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; BriefingBot/2.0)",
        })

        try:
            with urlopen(req, timeout=180) as resp:
                body = resp.read().decode("utf-8")
                result = json.loads(body)
            if "choices" not in result or len(result["choices"]) == 0:
                raise ValueError(f"API 返回异常: {str(result)[:200]}")

            content = result["choices"][0]["message"]["content"]
            print(f"✔ 成功 ({len(content)} 字符)")

            # 解析 JSON
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                m = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
                if m:
                    parsed = json.loads(m.group(1).strip())
                else:
                    start = content.find("{")
                    end = content.rfind("}")
                    if start != -1 and end > start:
                        parsed = json.loads(content[start:end+1])
                    else:
                        raise

            print(f"  → AI 筛选: 国外 {intl} 条 + 国内 {cn} 条")
            return (style_name, parsed)

        except Exception as e:
            if attempt < max_retries:
                print(f"✘ 第{attempt}次失败 ({str(e)[:60]})，5秒后重试...")
                import time
                time.sleep(5)
            else:
                print(f"✘ 全部 {max_retries} 次重试均失败: {str(e)[:80]}")
                return (style_name, None)


# ============================================================
# 新闻评分系统（独立 API 调用，不占用主分析上下文）
# ============================================================

def _rate_news_items(items: list[dict]) -> list[dict]:
    """
    对 AI 已生成的新闻条目进行评分（1-5星）和标签分类。
    在 main() 中调用，结果合并回 items。
    """
    if not items:
        return items

    import json as _json

    # 构造评分输入
    lines = []
    for i, it in enumerate(items, 1):
        t = (it.get("title") or "")[:80]
        s = (it.get("summary") or "")[:120]
        lines.append(f'{i}. 标题: {t} | 摘要: {s}')
    input_text = "\n".join(lines)

    prompt = f"""请对以下 {len(items)} 条 AI/Agent 开发者新闻逐一评分和分类。

评分标准（1-5星）：
  5 - 对开发者非常有价值（核心技术突破、新框架发布）
  4 - 比较有用（新工具、重要更新、好文章）
  3 - 一般（普通行业新闻、常规发布）
  2 - 参考价值低（营销稿、八卦）
  1 - 无关内容

标签分类（每篇选一个最合适的）：
  【前沿研究】论文、技术突破、新架构、理论分析
  【开发工具】新框架、新模型、新 API、新平台
  【行业动态】融资、收购、公司战略、市场变化、政策
  【工程实践】性能优化、踩坑经验、部署方案、代码技巧
  【开源推荐】值得关注的开源项目、工具库

请严格按照以下 JSON 格式输出，不要 markdown 代码块标记：
[
  {{"score": 4, "tag": "开发工具"}},
  {{"score": 3, "tag": "行业动态"}}
]

新闻列表：
{input_text}"""

    url = f"{config.API_BASE_URL.rstrip('/')}/v1/chat/completions"
    payload = _json.dumps({
        "model": config.MODEL_NAME,
        "messages": [
            {"role": "system", "content": "你是一个专业的 AI 开发者新闻评分助手。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 2048,
    }).encode("utf-8")

    req = Request(url, data=payload, headers={
        "Authorization": f"Bearer {config.API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; BriefingBot/2.0)",
    })

    try:
        with urlopen(req, timeout=60) as resp:
            result = _json.loads(resp.read().decode("utf-8"))
        raw = result["choices"][0]["message"]["content"].strip()
        # 清理可能的 markdown 代码块
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()
        ratings = _json.loads(raw)
        print(f"\n  ── 新闻评分 ──")
        for i, it in enumerate(items):
            if i < len(ratings) and isinstance(ratings[i], dict):
                score = ratings[i].get("score", 3)
                tag = ratings[i].get("tag", "")
                it["score"] = max(1, min(5, score))  # 钳制到 1-5
                it["tag"] = tag
                tag_display = f' [{tag}]' if tag else ''
                stars = "⭐" * it["score"]
                print(f"    No.{i+1:02d} {stars}{tag_display}")
            else:
                it["score"] = 3
                it["tag"] = ""
        scored = sum(1 for it in items if it.get("score"))
        print(f"  → 已评分 {scored}/{len(items)} 条")
    except Exception as e:
        print(f"  [评分] API 调用失败: {str(e)[:80]}")
        # 降级：全部给默认分
        for it in items:
            it["score"] = 3
            it["tag"] = ""

    return items


# ============================================================
# GitHub Trending（独立数据源，不经过过滤层和 AI）
# ============================================================

def fetch_github_trending():
    """
    直接爬取 github.com/trending 官方页面，解析热门项目。
    不依赖任何第三方 API。
    返回: [{"name","desc","stars","link","tag"}, ...]
    """
    TAG_MAP = config.TRENDING_TAG_MAP if hasattr(config, 'TRENDING_TAG_MAP') else {}

    urls = [
        "https://github.com/trending?since=daily",
        "https://github.com/trending?since=weekly",
    ]
    projects = []

    for url in urls:
        try:
            print(f"\n  → 抓取 GitHub Trending 官方页面 ({url.split('=')[-1]}) ... ", end="", flush=True)
            req = Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            })
            with urlopen(req, timeout=20) as resp:
                html = resp.read().decode("utf-8", "ignore")

            repo_blocks = re.findall(
                r'<article[^>]*class="[^"]*Box-row[^"]*"[^>]*>([\s\S]*?)</article>',
                html, re.I
            )
            print(f"找到 {len(repo_blocks)} 个项目块 ... ", end="", flush=True)

            for block in repo_blocks:
                href_m = re.search(r'href="/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)"', block)
                if not href_m:
                    continue
                full_name = href_m.group(1).strip()
                if "/" in full_name.replace("/", "", 1):
                    continue

                desc_m = re.search(r'<p[^>]*class="[^"]*col-9[^"]*"[^>]*>\s*([\s\S]*?)\s*</p>', block)
                if not desc_m:
                    desc_m = re.search(r'<p[^>]*>\s*([^<]{10,200})\s*</p>', block)
                desc = re.sub(r'\s+', ' ', desc_m.group(1).strip()) if desc_m else ""
                desc = re.sub(r'<[^>]+>', '', desc).strip()

                stars_today_m = re.search(r'([\d,]+)\s*stars?\s*today', block, re.I)
                if stars_today_m:
                    stars_n = int(stars_today_m.group(1).replace(",", ""))
                    stars_str = f"⭐+{stars_n} today"
                else:
                    stars_str = "⭐N/A"
                    stars_n = 0

                # 关键词匹配
                text = f"{full_name} {desc}".lower()
                matched_tag = ""
                for kw, tag in TAG_MAP.items():
                    if kw in text:
                        matched_tag = tag
                        break

                if matched_tag and len(desc) > 5 and full_name not in [p["name"] for p in projects]:
                    projects.append({
                        "name": full_name, "desc": desc[:100],
                        "stars": stars_str, "stars_n": stars_n,
                        "link": f"https://github.com/{full_name}", "tag": matched_tag,
                    })

            print(f"✔ 筛出 {len(projects)} 个")
            if projects:
                break
        except Exception as e:
            print(f"✘ {e}")
            continue

    # 备用：GitHub Search API
    if not projects:
        print(f"\n  → 备用：GitHub Search API ... ", end="", flush=True)
        try:
            from datetime import timedelta
            week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            search_url = (f"https://api.github.com/search/repositories"
                          f"?q=topic:llm+topic:agent+created:>{week_ago}"
                          f"&sort=stars&order=desc&per_page=10")
            req2 = Request(search_url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; BriefingBot/2.0)",
                "Accept": "application/vnd.github+json",
            })
            with urlopen(req2, timeout=15) as r2:
                sdata = json.loads(r2.read().decode("utf-8"))
            for repo in sdata.get("items") or []:
                fn = repo.get("full_name", "")
                desc = repo.get("description", "") or ""
                sn = repo.get("stargazers_count", 0)
                text = f"{fn} {desc}".lower()
                mt = ""
                for kw, tag in TAG_MAP.items():
                    if kw in text:
                        mt = tag
                        break
                if not mt:
                    mt = "Agent 框架"
                if fn and len(desc) > 5:
                    projects.append({
                        "name": fn, "desc": desc[:100],
                        "stars": f"⭐{sn:,}", "link": f"https://github.com/{fn}", "tag": mt,
                    })
                if len(projects) >= 3:
                    break
            print(f"✔ 备用找到 {len(projects)} 个")
        except Exception as e2:
            print(f"✘ {e2}")

    projects.sort(key=lambda x: x.get("stars_n", 0), reverse=True)
    for p in projects:
        p.pop("stars_n", None)
    return projects[:3]


# ============================================================
# 写入 HTML
# ============================================================

def _replace_array_var(content: str, var_name: str, new_json_str: str) -> str:
    """
    替换 HTML 中 JavaScript 数组变量的内容。
    使用位置定位替代 regex，避免数据中含 `]` 导致匹配失败。
    支持变量名与 `[` 之间任意长度空格。
    """
    key = f"const {var_name} ="
    start = content.find(key)
    if start < 0:
        print(f"  [警告] 未找到 {key}")
        return content

    # 从 key 末尾向后找第一个 `[`
    search_from = start + len(key)
    bracket_pos = content.find("[", search_from)
    if bracket_pos < 0:
        print(f"  [警告] 未找到 [")
        return content

    # 找到第一个 `];`（数组结束标志）
    array_end = content.find("];", bracket_pos)
    if array_end < 0:
        print(f"  [警告] 未找到数组结束 ];")
        return content

    # 替换数组内容（保留 [ 和 ];）
    # new_json_str 已包含完整的 JSON 数组字符串（以 [ 开头，以 ] 结尾）
    # 需要补上 ; 以闭合 JS 语句
    return content[:bracket_pos] + new_json_str + ";" + content[array_end + 2:]


def write_html(news_items, daily_analysis="", projects=None):
    if not projects:
        projects = []
    if not os.path.exists(config.HTML_FILE):
        print(f"[错误] HTML 文件不存在: {config.HTML_FILE}")
        return False

    with open(config.HTML_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    json_str = json.dumps(news_items, ensure_ascii=False, indent=4)
    lines = json_str.split("\n")
    indented = "\n".join("        " + line if line.strip() else line for line in lines)
    content = _replace_array_var(content, "__NEWS_DATA__", indented)

    if daily_analysis:
        escaped = json.dumps(daily_analysis, ensure_ascii=False)
        key = 'const __DAILY_ANALYSIS__ = "'
        da_start = content.find(key)
        if da_start >= 0:
            val_start = da_start + len(key)
            val_end = content.find('"', val_start)
            if val_end > val_start:
                content = content[:val_start] + escaped.strip('"') + content[val_end:]

    projects_json = json.dumps(projects, ensure_ascii=False, indent=4)
    plines = projects_json.split("\n")
    pindented = "\n".join("        " + line if line.strip() else line for line in plines)
    content = _replace_array_var(content, "__PROJECTS__", pindented)

    with open(config.HTML_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[成功] 已更新 {len(news_items)} 条新闻 + {len(projects)} 个项目到 HTML")

    # 同步更新 index.html（GitHub Pages 默认入口）
    index_path = os.path.join(config.BASE_DIR, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[成功] 已同步更新 index.html")

    # ---- Pages 验证日志：确认 index.html 内容已刷新 ----
    import json as _json
    _find = content.find("__NEWS_DATA__")
    if _find >= 0:
        _b = content.find("[", _find)
        _e = content.find("];", _b)
        if _e > _b:
            try:
                _data = _json.loads(content[_b:_e + 1])
                print(f"  [Pages验证] index.html 已更新，新闻条数: {len(_data)} 条")
                if _data:
                    print(f"    第一条: {_data[0].get('title','')[:50]}")
            except Exception as e:
                print(f"  [Pages验证] JSON 解析失败: {e}")

    return True


# ============================================================
# 邮件 HTML 生成
# ============================================================

def generate_email_html(news_items, daily_analysis="", projects=None,
                        filter_report=None, style_name="", trivia=""):
    if not projects:
        projects = []
    if not os.path.exists(config.EMAIL_TEMPLATE):
        print(f"[警告] 邮件模板不存在: {config.EMAIL_TEMPLATE}")
        return False

    with open(config.EMAIL_TEMPLATE, "r", encoding="utf-8") as f:
        template = f.read()

    # 顶部过滤统计（供模板使用）
    total_input = filter_report.total_input if filter_report else 0
    total_output = filter_report.total_output if filter_report else len(news_items)
    filter_tagline = f"今日从 {total_input} 条新闻中精选 {total_output} 条"

    def make_card_html(items_list, start_no=1):
        html = []
        for i, item in enumerate(items_list, start_no):
            source_tag = (f'<span style="font-size:10px;color:#888;background:#f0f0ee;'
                          f'padding:2px 10px;border-radius:20px;">{item["source"]}</span>'
                          ) if item.get("source") else ""
            score = item.get("score", 0)
            tag = item.get("tag", "")
            stars = "⭐" * score if score else ""
            tag_html = f'<span style="font-size:10px;color:#555;background:#f0f0ee;padding:2px 10px;border-radius:20px;margin-left:4px;">{tag}</span>' if tag else ''
            score_html = f'<span style="font-size:10px;color:#e67e22;margin-left:4px;">{stars}</span>' if stars else ''
            html.append(f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid #e5e5e5;border-radius:12px;margin-bottom:16px;">
          <tr>
            <td style="padding:20px 24px;">
              <div style="margin-bottom:10px;">
                <span style="font-size:11px;font-weight:700;color:#ccc;letter-spacing:1px;">No.{i:02d}</span>
                {' ' + source_tag if source_tag else ''}{tag_html}{score_html}
              </div>
              <h2 style="font-size:15px;font-weight:700;color:#111;margin:0 0 10px 0;line-height:1.5;">{item["title"]}</h2>
              <p style="font-size:13px;color:#555;margin:0 0 14px 0;line-height:1.7;">{clean_links(item["summary"])}</p>
            </td>
          </tr>
        </table>""")
        return "\n".join(html)

    # 统一渲染所有新闻（不区分国内外）
    news_items_html = make_card_html(news_items)
    news_sections = news_items_html

    analysis_section = ""
    if daily_analysis:
        analysis_section = f"""
        <tr>
          <td style="padding:24px 24px;background:#1a1a1a;border-radius:12px;">
            <div style="font-size:11px;color:#888;letter-spacing:1.2px;margin-bottom:12px;">📊 今日深度分析</div>
            <p style="font-size:13px;color:#ccc;line-height:1.8;margin:0;">{clean_links(daily_analysis)}</p>
          </td>
        </tr>"""

    projects_section = ""
    if projects:
        proj_cards = []
        for p in projects:
            proj_cards.append(f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid #e0e0e0;border-radius:10px;margin-bottom:14px;">
          <tr>
            <td style="padding:16px 20px;">
              <div style="font-size:14px;font-weight:700;color:#111;margin-bottom:4px;">
                📌 <a href="{p.get("link","#")}" target="_blank" style="color:#1a1a1a;text-decoration:none;">{p.get("name","")}</a>
                <span style="font-size:12px;color:#888;margin-left:8px;">{p.get("stars","")}</span>
              </div>
              <p style="font-size:13px;color:#555;margin:4px 0 0 0;line-height:1.6;">{p.get("desc","")}</p>
              <span style="font-size:11px;color:#888;background:#f0f0ee;padding:2px 10px;border-radius:20px;display:inline-block;margin-top:8px;">🏷️ {p.get("tag","")}</span>
            </td>
          </tr>
        </table>""")
        projects_section = f"""
        <tr>
          <td style="padding-top:24px;border-top:2px dashed #ddd;">
            <div style="font-size:13px;font-weight:700;color:#1a1a1a;margin-bottom:14px;">📚 本周热门学习项目</div>
            {''.join(proj_cards)}
          </td>
        </tr>"""
    else:
        projects_section = f"""
        <tr>
          <td style="padding-top:24px;border-top:2px dashed #ddd;">
            <div style="font-size:13px;color:#888;text-align:center;padding:20px 0;">📚 今日暂无推荐学习项目</div>
          </td>
        </tr>"""

    filter_report_section = ""
    if filter_report:
        filter_report_section = filter_report.to_email_html()

    # ---- 彩蛋角落 ----
    trivia_section = ""
    if trivia:
        trivia_section = f"""
        <tr>
          <td style="padding:16px 20px;background:#f8f8f6;border:1px solid #e5e5e5;border-radius:10px;margin-bottom:0;">
            <div style="font-size:11px;color:#888;letter-spacing:1px;margin-bottom:6px;">🎲 彩蛋角落</div>
            <p style="font-size:12px;color:#666;line-height:1.7;margin:0;font-style:italic;">{clean_links(trivia)}</p>
          </td>
        </tr>"""

    # ---- 网页版入口（正文不含任何链接，引导访问网页版） ----
    web_link_section = ""
    web_link_section = f"""
        <tr>
          <td style="padding:24px 20px;border-top:2px dashed #ddd;border-bottom:2px dashed #ddd;">
            <div style="font-size:12px;color:#888;line-height:1.8;text-align:center;">
              <span style="font-size:14px;font-weight:700;color:#555;">📖 查看原文链接</span><br/>
              请在浏览器中打开网页版查看所有新闻原文链接及项目详情<br/>
              <span style="color:#999;font-size:11px;">yingfengke.github.io/agent-news-briefing</span>
            </div>
          </td>
        </tr>"""

    today = datetime.now()
    date_str = f"{today.year}年{today.month:02d}月{today.day:02d}日"

    html = template.replace("{{date}}", date_str)
    html = html.replace("{{filter_tagline}}", filter_tagline)
    html = html.replace("{{news_items}}", news_sections)
    html = html.replace("{{daily_analysis_section}}", analysis_section)
    html = html.replace("{{projects_section}}", projects_section)
    html = html.replace("{{filter_report_section}}", filter_report_section)
    html = html.replace("{{trivia_section}}", trivia_section)
    html = html.replace("{{link_list_section}}", web_link_section)
    # 底部免责声明 — 纯文字，不含任何可点击链接
    html = html.replace('href="{{repo_url}}"', 'style="color:#888;text-decoration:none;"')
    html = html.replace("{{repo_url}}", "GitHub: yingfengke/agent-news-briefing")
    if style_name:
        html = html.replace("{{style_tag}}", f" · 今日风格：{style_name}")
    else:
        html = html.replace("{{style_tag}}", "")

    with open(config.EMAIL_OUTPUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[成功] 已生成邮件 HTML ({len(news_items)} 条)")

    # ---- 自检：扫描邮件 HTML 中是否还有未包裹的链接 ----
    # 排除 <style> 内的内容（纯文本网站域名不算）
    body_only = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
    loose_urls = re.findall(r'https?://[^\s<>"\'\]】、，,]+', body_only)
    if loose_urls:
        for url in loose_urls[:5]:
            print(f"  [LINK-CHECK] ⚠ 发现未清理的链接: {url[:80]}")
        if len(loose_urls) > 5:
            print(f"  [LINK-CHECK] ⚠ ... 还有 {len(loose_urls)-5} 个")
    else:
        print(f"  [LINK-CHECK] ✅ 邮件中无任何链接，通过")
    return True


# ============================================================
# 主流程
# ============================================================

def main():
    print("=" * 60)
    print("  AI & Agent 开发者晨报 — 三层架构 v2.0")
    print(f"  采集: {len(config.RSS_SOURCES)} 个 RSS 源")
    print(f"  模型: {config.MODEL_NAME}")
    print("=" * 60)

    # ---- 1. 采集层 ----
    print(f"\n{'=' * 40}")
    print("  第 1 层：多模态数据采集")
    print(f"{'=' * 40}")
    raw_pool = collect_all()

    # ---- 2. 过滤层 ----
    print(f"\n{'=' * 40}")
    print("  第 2 层：智能过滤与去重")
    print(f"{'=' * 40}")
    if raw_pool:
        report = run_pipeline(raw_pool)
    else:
        report = FilterReport(total_input=0)
    report.print_report()
    clean_items = report.remaining_items

    # ---- 3. AI 分析层 ----
    print(f"\n{'=' * 40}")
    print("  第 3 层：AI 分析与简报生成")
    print(f"{'=' * 40}")

    # 随机彩蛋
    trivia = get_random_trivia()
    print(f"  🎲 今日彩蛋: {trivia}")

    final_items = []
    daily_analysis = ""
    ai_failed = False

    if not clean_items:
        print("  [信息] 过滤后无可用数据，发送空报告邮件")
        ai_failed = True
    else:
        style_name, ai_result = call_ai_analysis(clean_items)
        if ai_result:
            daily_analysis = ai_result.get("daily_analysis", "")

            # 从原始数据构建多级链接索引（用于 AI 输出的链接兜底）
            # level 1: 精确标题匹配
            title_exact_map = {}
            # level 2: 来源+标题关键词匹配
            source_title_map: dict[str, list[tuple[str, str]]] = {}
            for ci in clean_items:
                key = ci.title.strip()[:50].lower()
                if ci.url:
                    title_exact_map[key] = ci.url
                    src = (ci.source or "").lower()
                    source_title_map.setdefault(src, []).append((key, ci.url))
                    # 也索引原文前60字（AI 可能截断）
                    key_short = key[:30]
                    if key_short not in title_exact_map:
                        title_exact_map[key_short] = ci.url

            def _extract_link(it: dict, summary: str = "") -> str:
                """从 AI 返回的条目中提取链接。
                优先顺序：link → url → summary 正则提取 → 标题匹配原始数据（精确→模糊）。
                """
                link = it.get("link") or it.get("url") or ""
                if not link and summary:
                    m = re.search(r'https?://[^\s<>)\]】、，,]+', summary)
                    if m:
                        link = m.group(0)
                        print(f"    [链接兜底-摘要] {link[:60]}")

                if not link:
                    title = (it.get("title", "") or "").lower().strip()
                    ai_source = (it.get("source", "") or "").lower().strip()

                    # ① 精确匹配（保留原有逻辑）
                    if title[:50] in title_exact_map:
                        link = title_exact_map[title[:50]]
                        print(f"    [链接兜底-精确匹配] {link[:60]}")

                if not link:
                    # ② 模糊匹配：按来源缩小范围后，检查子串包含关系
                    title = (it.get("title", "") or "").lower().strip()
                    ai_source = (it.get("source", "") or "").lower().strip()
                    candidates = []
                    # 先按来源找候选
                    for src_key, entries in source_title_map.items():
                        if ai_source and (ai_source in src_key or src_key in ai_source):
                            candidates.extend(entries)
                    # 没匹配到来源就用全部
                    if not candidates:
                        for entries in source_title_map.values():
                            candidates.extend(entries)

                    # 子串匹配：AI 标题包含原始标题 或 原始标题包含 AI 标题
                    title_words = set(w for w in re.split(r'[\s：:，,、()（）\[\]【】]', title) if len(w) > 1)
                    best_match = ""
                    best_score = 0
                    for orig_title, orig_url in candidates:
                        orig_words = set(w for w in re.split(r'[\s：:，,、()（）\[\]【】]', orig_title) if len(w) > 1)
                        if not title_words or not orig_words:
                            continue
                        overlap = len(title_words & orig_words)
                        score = overlap / min(len(title_words), len(orig_words))
                        if score > best_score:
                            best_score = score
                            best_match = orig_url

                    if best_score >= 0.4 and best_match:
                        link = best_match
                        print(f"    [链接兜底-模糊匹配] {link[:60]} (相似度{best_score:.2f})")

                return link

            def _try_parse_item(it):
                """
                尝试将 AI 返回的条目解析为 dict。
                支持 dict 直接使用、字符串 JSON 反序列化。
                返回 (parsed_dict, success_bool)。
                """
                import json as _json
                if isinstance(it, dict):
                    return it, True
                if isinstance(it, str):
                    stripped = it.strip()
                    # 尝试去掉可能的 markdown 代码块标记
                    if stripped.startswith("```"):
                        stripped = stripped.strip("`").strip()
                        if stripped.startswith("json"):
                            stripped = stripped[4:].strip()
                    try:
                        parsed = _json.loads(stripped)
                        if isinstance(parsed, dict):
                            return parsed, True
                        # 如果是 JSON 数组，取第一个元素
                        if isinstance(parsed, list) and len(parsed) > 0 and isinstance(parsed[0], dict):
                            print(f"    [抢救] 字符串 JSON 数组 → 取首元素")
                            return parsed[0], True
                    except _json.JSONDecodeError:
                        pass
                print(f"    [警告] 无法解析的条目: {str(it)[:80]}")
                return None, False

            ok_count = skip_count = 0

            if "news" in ai_result:
                for it in ai_result.get("news", []):
                    parsed, ok = _try_parse_item(it)
                    if not ok:
                        skip_count += 1
                        continue
                    ok_count += 1
                    summary = parsed.get("summary", "")
                    final_items.append({
                        "title": parsed.get("title", ""),
                        "summary": summary,
                        "link": _extract_link(parsed, summary),
                        "source": parsed.get("source", "AI"),
                    })
                detail = ""
                if skip_count:
                    detail = f" (跳过 {skip_count} 条无法解析)"
                print(f"\n  AI 筛选后: {ok_count} 条{detail}")
            elif "items" in ai_result:
                items_ok = items_skip = 0
                for it in ai_result["items"]:
                    parsed, ok = _try_parse_item(it)
                    if not ok:
                        items_skip += 1
                        continue
                    items_ok += 1
                    summary = parsed.get("summary", "")
                    final_items.append({
                        "title": parsed.get("title", ""),
                        "summary": summary,
                        "link": _extract_link(parsed, summary),
                        "source": parsed.get("source", "AI"),
                    })
                detail = ""
                if items_skip:
                    detail = f" (跳过 {items_skip} 条无法解析)"
                print(f"\n  AI 筛选后: {items_ok} 条{detail}")
        else:
            # 降级：兼容旧格式 international/china
            if "international" in ai_result or "china" in ai_result:
                fallback_items = []
                for key in ("international", "china"):
                    for it in ai_result.get(key, []):
                        parsed, ok = _try_parse_item(it)
                        if not ok:
                            continue
                        summary = parsed.get("summary", "")
                        fallback_items.append({
                            "title": parsed.get("title", ""),
                            "summary": summary,
                            "link": _extract_link(parsed, summary),
                            "source": parsed.get("source", "AI"),
                        })
                if fallback_items:
                    print(f"  [降级] 使用旧格式 international/china，解析 {len(fallback_items)} 条")
                    final_items = fallback_items
                else:
                    ai_failed = True
            else:
                ai_failed = True

    # ---- 新闻评分（独立 API 调用，不影响主体分析） ----
    if final_items and not ai_failed:
        print(f"\n{'=' * 40}")
        print("  新闻评分与标签标注")
        print(f"{'=' * 40}")
        final_items = _rate_news_items(final_items)
    # ---- 5. 按评分排序（高→低） ----
    print(f"\n  ── 按评分排序（高→低） ──")
    final_items.sort(key=lambda x: x.get("score", 0) or 0, reverse=True)
    scored = sum(1 for it in final_items if it.get("score", 0) > 0)
    print(f"  评分分布: {scored}/{len(final_items)} 条有评分")

    # ---- 4. GitHub Trending 项目 ----
    print(f"\n  ── 抓取 GitHub Trending 项目 ──")
    trending_projects = fetch_github_trending()
    if trending_projects:
        print(f"  📚 本周热门学习项目: {len(trending_projects)} 个")
        for p in trending_projects:
            print(f"     📌 {p['name']} ({p['tag']})")
    else:
        print("  [信息] 今日暂无合适的 Trending 项目推荐")

    # ---- 5. 写入网页 HTML ----
    print(f"\n  ── 写入网页 HTML ──")
    write_html(final_items, daily_analysis, trending_projects)

    # ---- 6. 生成邮件 HTML ----
    print(f"\n  ── 生成邮件 HTML ──")
    if ai_failed and not final_items:
        # AI 失败且无降级数据 → 空报告
        generate_email_html(
            [], f"今日无可用新闻。过滤报告：采集 {report.total_input} 条 → "
                f"过滤后 {report.total_output} 条。",
            trending_projects, filter_report=report,
            style_name="", trivia=trivia,
        )
    else:
        generate_email_html(
            final_items, daily_analysis, trending_projects,
            filter_report=report,
            style_name=style_name if not ai_failed else "降级",
            trivia=trivia,
        )

    # ---- 7. 发送邮件（由 workflow 的 Step ② 独立执行，此处不再重复调用） ----
    print(f"\n  ── 邮件已生成，由 workflow 步骤发送 ──")

    if daily_analysis:
        print(f"\n  📊 今日深度分析:")
        print(f"     {daily_analysis[:200]}...")

    print(f"\n  ✅ 简报生成完毕 | {len(final_items)} 条新闻 | {len(trending_projects)} 个项目")
    print(f"     邮件: {config.EMAIL_OUTPUT}")
    print(f"     过滤前: {report.total_input} 条 → 过滤后: {report.total_output} 条")


if __name__ == "__main__":
    main()
