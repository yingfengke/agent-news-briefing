"""dedupe 子包：四阶段智能过滤与去重。"""
from src.core.models import FilterReport
from src.dedupe.url_dedup import UrlDeduper
from src.dedupe.minhash_dedup import MinhashDeduper
from src.dedupe.semantic_dedup import SemanticDeduper
from src.dedupe.credibility import CredibilityFilter
from src.dedupe.pipeline import run_pipeline

__all__ = ["UrlDeduper", "MinhashDeduper", "SemanticDeduper",
            "CredibilityFilter", "run_pipeline", "FilterReport"]
