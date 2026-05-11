"""
config.py — multi-agent system configuration

Reuses the existing project config, overrides where needed.
"""

import os
import sys

# Add parent directory so we can import the existing config
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Reuse existing config as base
import config as base_config

# --- Agent-specific config ---

# How many retries before an agent gives up
AGENT_MAX_RETRIES = 3
AGENT_RETRY_DELAY = 5  # seconds

# Orchestrator
ORCHESTRATOR_TIMEOUT = 600  # total pipeline timeout (seconds)

# Scout agent
SCOUT_PARALLEL = True  # fetch sources in parallel
SCOUT_MAX_WORKERS = 5  # concurrent fetch workers

# Filter agent
FILTER_ENABLE_URL = True
FILTER_ENABLE_MINHASH = True
FILTER_ENABLE_SEMANTIC = True
FILTER_ENABLE_CREDIBILITY = True

# Analyst agent
ANALYST_MODEL = base_config.MODEL_NAME
ANALYST_MAX_TOKENS = 4096
ANALYST_TEMPERATURE = 0.3

# Generator agent
GENERATOR_TEMPLATE = base_config.EMAIL_TEMPLATE
GENERATOR_OUTPUT = base_config.EMAIL_OUTPUT
GENERATOR_HTML_FILE = base_config.HTML_FILE

# RAG
RAG_EMBEDDING_MODEL = base_config.EMBEDDING_MODEL
RAG_TOP_K = 5  # max similar items to retrieve
RAG_DB_PATH = os.path.join(_project_root, ".rag_store.json")

# Tool timeouts
TOOL_RSS_TIMEOUT = 15
TOOL_CRAWLER_TIMEOUT = 30
TOOL_LLM_TIMEOUT = 180
TOOL_EMBEDDING_TIMEOUT = 30

# Re-export base config values for convenience
RSS_SOURCES = base_config.RSS_SOURCES
CRAWLER_TARGETS = base_config.CRAWLER_TARGETS
MAX_PER_SOURCE = base_config.MAX_PER_SOURCE
RSS_FALLBACKS = getattr(base_config, "RSS_FALLBACKS", {})
CRAWLER_SITE_SELECTORS = getattr(base_config, "CRAWLER_SITE_SELECTORS", {})
CHINESE_SOURCE_NAMES = base_config.CHINESE_SOURCE_NAMES
DEDUP_MINHASH_THRESHOLD = base_config.DEDUP_MINHASH_THRESHOLD
DEDUP_SEMANTIC_THRESHOLD = base_config.DEDUP_SEMANTIC_THRESHOLD
CREDIBILITY_WHITELIST = base_config.CREDIBILITY_WHITELIST
CREDIBILITY_BLACKLIST = base_config.CREDIBILITY_BLACKLIST
