"""pipeline.py - 四阶段过滤管道编排。
"""
import json
import os

from src import config
from src.core.models import NewsItem, FilterReport
from src.core.logger import get_logger
from src.dedupe.url_dedup import UrlDeduper
from src.dedupe.minhash_dedup import MinhashDeduper
from src.dedupe.semantic_dedup import SemanticDeduper
from src.dedupe.credibility import CredibilityFilter

log = get_logger("dedup.pipeline")
def run_pipeline(items: list[NewsItem]) -> FilterReport:
    """
    四层过滤管道。

    参数:
      items — 原始新闻列表

    返回:
      FilterReport — 各阶段统计 + 干净数据
    """
    report = FilterReport(total_input=len(items))
    if not items:
        return report

    # ---- A: URL 去重 ----
    # 跨天持久化策略：
    #   1. 从已有 DB 加载历史 URL 哈希（跨天去重）
    #   2. 清空当前 DB 文件（避免重试时被第一轮的哈希污染）
    #   3. 创建 UrlDeduper 时带上跨天哈希
    #   4. 运行结束后，flush() 写入新 DB，由 github_api_push.py 提交到 repo
    cross_day_hashes: set[str] = set()
    try:
        if os.path.exists(config.URL_DB_FILE):
            with open(config.URL_DB_FILE, "r") as f:
                data = json.load(f)
            cross_day_hashes = set(data.get("urls", []))
            log.info("  -> 加载跨天 URL 去重库: %d 条历史哈希", len(cross_day_hashes))
    except Exception as e:
        log.warning("加载跨天 URL 去重库失败: %s", e)

    # 清空 session DB（避免重试污染）
    try:
        if os.path.exists(config.URL_DB_FILE):
            os.remove(config.URL_DB_FILE)
    except Exception:
        pass

    log.info("")
    log.info("  -- A. URL 去重 --")
    url_deduper = UrlDeduper(initial_set=cross_day_hashes)
    after_a = []
    for it in items:
        if not url_deduper.is_duplicate(it):
            after_a.append(it)
        else:
            report.url_removed += 1
    url_deduper.flush()
    log.info("  %d -> %d (去重 %d 条)", len(items), len(after_a), report.url_removed)

    # B/C/D 阶段用 guard 包裹：某阶段结果为空时不提前返回，
    # 始终走到函数末尾统一填充 report 并返回（避免提前 return 跳过后续统计）。
    after_b = after_a
    if after_a:
        log.info("")
        log.info("  -- B. 内容指纹去重 (MinHash+LSH) --")
        mh_deduper = MinhashDeduper()
        after_b = []
        for it in after_a:
            if not mh_deduper.is_duplicate(it):
                after_b.append(it)
            else:
                report.minhash_removed += 1
        log.info("  %d -> %d (去重 %d 条)", len(after_a), len(after_b), report.minhash_removed)

    after_c = after_b
    if after_b:
        log.info("")
        log.info("  -- C. 语义去重 (Embedding+聚类) --")
        semanticer = SemanticDeduper()
        after_c = semanticer.deduplicate(after_b)
        report.semantic_removed = len(after_b) - len(after_c)
        log.info("  %d -> %d (去重 %d 条，含聚类标注)", len(after_b), len(after_c), report.semantic_removed)

    after_d = after_c
    if after_c:
        log.info("")
        log.info("  -- D. 来源可信度过滤 --")
        filter_d = CredibilityFilter()
        after_d = [it for it in after_c if not filter_d.should_filter(it)]
        report.credibility_removed = len(after_c) - len(after_d)
        log.info("  %d -> %d (过滤 %d 条)", len(after_c), len(after_d), report.credibility_removed)

    report.total_output = len(after_d)
    report.remaining_items = after_d
    return report


# ============================================================
# 独立测试
# ============================================================

if __name__ == "__main__":
    from src.collect.collector import collect_all
    raw = collect_all()
    report = run_pipeline(raw)
    report.print_report()
    print(f"\n  前 5 条保留新闻:")
    for it in report.remaining_items[:5]:
        tags = f" [{', '.join(it.tags)}]" if it.tags else ""
        print(f"  [{it.source}]{tags} {it.title[:60]}")
        if "多家来源报道" in it.content:
            print(f"     {it.content[-30:]}")
