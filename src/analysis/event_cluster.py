"""event_cluster.py - 事件级判定：语义筛候选 + cross-encoder 精判。

分工：
  embedding  只负责捞候选（同主题、措辞可能完全不同），阈值放宽到 0.65；
  reranker   负责判「是不是同一件事」（实测同事件 >= 0.72，不同事件 <= 0.10）。

为什么不能只靠 embedding：同一厂商的两条不同新闻，embedding 余弦可达 0.75，
与真正的同事件（0.76）几乎无法区分；cross-encoder 能把它压到 0.01 以下。

对外两个能力：
  annotate_progress()  跨天同事件且带新事实 -> 标题前加「进展：」
  apply_event_quota()  批内同事件成簇，正文每簇最多 N 条，其余转入简讯
两者失败都静默降级，不阻断主流程。
"""
import json
from urllib.request import Request, urlopen

import numpy as np

from src import config
from src.core.logger import get_logger
from src.core.http_utils import http_error_detail

log = get_logger("analysis.events")

EMBED_CANDIDATE_THRESHOLD = 0.65   # 候选门槛（低于此值几乎不可能是同一事件）
SAME_EVENT_THRESHOLD = 0.45        # reranker 双向 max 判定门槛（实测同事件 >=0.65，不同事件 <=0.06）
MAX_CANDIDATE_PAIRS = 12           # 单次最多精判对数，控制耗时
MAX_PER_EVENT_IN_BODY = 2          # 正文中同一事件最多保留条数
PROGRESS_PREFIX = "进展："
_RERANK_MODEL = "BAAI/bge-reranker-v2-m3"


def _post(url: str, payload: dict, timeout: int = 60) -> dict:
    req = Request(url, data=json.dumps(payload).encode("utf-8"), headers={
        "Authorization": f"Bearer {config.API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; BriefingBot/2.0)",
    })
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _text(item) -> str:
    """向量筛选用：标题 + 摘要，召回更宽。"""
    if isinstance(item, dict):
        return f"{item.get('title', '')}。{(item.get('summary') or '')[:200]}"
    title, summary = item
    return f"{title}。{(summary or '')[:200]}"


def _judge(item) -> str:
    """reranker 判定用：只用标题。

    拼上摘要后模型会退化成「主题是否相关」：实测把「Anthropic 营收」与
    「Anthropic 捐股份」打到 0.999，而纯标题只有 0.006。标题短、信息聚焦，
    才判得准「是不是同一件事」。
    """
    if isinstance(item, dict):
        return item.get("title", "") or ""
    return item[0] or ""


def embed_texts(texts: list[str]) -> np.ndarray:
    """批量取向量并归一化；失败抛异常由调用方降级。"""
    vectors = []
    batch = 32
    for i in range(0, len(texts), batch):
        data = _post(f"{config.API_BASE_URL.rstrip('/')}/v1/embeddings", {
            "model": config.EMBEDDING_MODEL,
            "input": texts[i:i + batch],
        })
        vectors.extend(row["embedding"] for row in data["data"])
    arr = np.array(vectors, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return arr / norms


def rerank_pair(a: str, b: str) -> float:
    """双向各打一次分取 max：单向会漏掉措辞差异大的同事件（实测 0.17 vs 0.76）。"""
    def _one(query: str, doc: str) -> float:
        data = _post(f"{config.API_BASE_URL.rstrip('/')}/v1/rerank", {
            "model": _RERANK_MODEL,
            "query": query,
            "documents": [doc],
            "top_n": 1,
            "return_documents": False,
        })
        return float(data["results"][0]["relevance_score"])

    return max(_one(a, b), _one(b, a))


def _candidate_pairs(vectors: np.ndarray, indices: list[int]) -> list[tuple[float, int, int]]:
    """返回按相似度降序、且超过候选门槛的下标对。"""
    pairs = []
    for pos_i in range(len(indices)):
        for pos_j in range(pos_i + 1, len(indices)):
            sim = float(vectors[indices[pos_i]] @ vectors[indices[pos_j]])
            if sim >= EMBED_CANDIDATE_THRESHOLD:
                pairs.append((sim, indices[pos_i], indices[pos_j]))
    pairs.sort(reverse=True)
    return pairs


def annotate_progress(items: list[dict], history_records) -> list[dict]:
    """给「跨天同事件、本期为续报」的条目标题加「进展：」前缀。

    history_records 为 (标题, 摘要) 元组序列。向量筛选用标题+摘要（召回宽），
    reranker 判定两侧都只用标题（否则会退化成主题相关性）。

    只判定不删除：纯重复已在 AI 前的文本规则里被过滤，
    这里命中的都属于「同一事件但有新事实」，保留并让读者看出不是重复内容。
    """
    if not items or not history_records or not config.API_KEY:
        return items

    try:
        records = [(t, s or "") for t, s in history_records if t][:400]
        if not records:
            return items

        item_texts = [_text(it) for it in items]
        item_judge = [_judge(it) for it in items]
        hist_texts = [f"{t}。{s[:200]}" for t, s in records]
        hist_judge = [t for t, _ in records]
        vectors = embed_texts(item_texts + hist_texts)
        hist_indices = list(range(len(item_texts), len(item_texts) + len(hist_texts)))

        pairs = _candidate_pairs(vectors, hist_indices + list(range(len(item_texts))))
        # 只保留「一条当期 + 一条历史」的组合，并按分数排序截断
        cross = [(s, i, j) for s, i, j in pairs
                 if (i < len(item_texts)) != (j < len(item_texts))]
        cross.sort(reverse=True)

        marked = set()
        for sim, i, j in cross[:MAX_CANDIDATE_PAIRS]:
            cur = i if i < len(item_texts) else j
            hist = j if cur == i else i
            if cur in marked:
                continue
            score = rerank_pair(item_judge[cur], hist_judge[hist - len(item_texts)])
            log.info("    事件判定 %.3f | %s <-> %s",
                     score, item_judge[cur][:28], hist_judge[hist - len(item_texts)][:28])
            if score >= SAME_EVENT_THRESHOLD:
                marked.add(cur)

        for idx in marked:
            title = items[idx].get("title") or ""
            if title and not title.startswith(PROGRESS_PREFIX):
                items[idx]["title"] = PROGRESS_PREFIX + title
        if marked:
            log.info("  跨天续报标注: %d 条（已加「%s」前缀）", len(marked), PROGRESS_PREFIX)
        return items
    except Exception as e:
        log.warning("  事件续报标注跳过（%s）", http_error_detail(e))
        return items


def apply_event_quota(display: list[dict], rest: list[dict],
                      limit: int = MAX_PER_EVENT_IN_BODY):
    """同一事件在正文最多保留 limit 条，其余下移到简讯（不删除内容）。

    用 embedding 找候选、reranker 确认同一事件，按簇分配正文名额。
    任一步失败都退回原样，不影响原有配额逻辑。
    """
    pool = list(display) + list(rest)
    if len(pool) <= limit or not config.API_KEY:
        return display, rest

    try:
        vectors = embed_texts([_text(it) for it in pool])
        pairs = _candidate_pairs(vectors, list(range(len(pool))))

        # union-find 建簇（先做候选筛选，再逐对精判）
        parent = list(range(len(pool)))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[ry] = rx

        judged = 0
        for sim, i, j in pairs:
            if judged >= MAX_CANDIDATE_PAIRS:
                break
            if find(i) == find(j):
                continue
            judged += 1
            try:
                if rerank_pair(_judge(pool[i]), _judge(pool[j])) >= SAME_EVENT_THRESHOLD:
                    union(i, j)
            except Exception:
                pass

        if judged == 0:
            return display, rest

        # 按簇分配正文名额：同簇按分数降序，超出 limit 的移入简讯
        # pool = display + rest，索引与位置一一对应，避免按值查找
        cluster_count: dict[int, int] = {}
        kept, overflow = [], []
        for pos, item in enumerate(display):
            root = find(pos)
            if cluster_count.get(root, 0) >= limit:
                overflow.append(item)
                continue
            cluster_count[root] = cluster_count.get(root, 0) + 1
            kept.append(item)
        if not overflow:
            return display, rest

        # 用待展示区补位（补位后仍受簇配额约束）
        target = len(display)
        remaining = []
        for pos, item in enumerate(rest, start=len(display)):
            root = find(pos)
            if len(kept) < target and cluster_count.get(root, 0) < limit:
                cluster_count[root] = cluster_count.get(root, 0) + 1
                kept.append(item)
            else:
                remaining.append(item)

        kept.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
        overflow.extend(remaining)
        overflow.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
        log.info("  事件簇配额: %d 条移出正文，%d 簇受影响", len(overflow),
                 sum(1 for v in cluster_count.values() if v >= limit))
        return kept, overflow
    except Exception as e:
        log.warning("  事件簇配额跳过（%s）", http_error_detail(e))
        return display, rest
