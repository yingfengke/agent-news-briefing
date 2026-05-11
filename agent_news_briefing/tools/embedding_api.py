"""
embedding_api.py — Embedding API Tool (for semantic dedup + RAG)
"""

from agent_news_briefing.core.tool import BaseTool, ToolResult
from agent_news_briefing import config


class EmbeddingApiTool(BaseTool):
    """Get text embeddings via SiliconFlow API."""

    name = "embedding_api"
    description = "Get vector embeddings for text"

    def run(self, texts: list[str], **kwargs) -> ToolResult:
        try:
            import json
            from urllib.request import Request, urlopen

            api_url = f"{config.API_BASE_URL.rstrip('/')}/v1/embeddings"
            headers = {
                "Authorization": f"Bearer {config.API_KEY}",
                "Content-Type": "application/json",
            }

            results = []
            for text in texts:
                payload = json.dumps({
                    "model": config.RAG_EMBEDDING_MODEL,
                    "input": text[:512],
                }).encode()
                req = Request(api_url, data=payload, headers=headers)
                with urlopen(req, timeout=config.TOOL_EMBEDDING_TIMEOUT) as resp:
                    data = json.loads(resp.read())
                    results.append(data["data"][0]["embedding"])

            return ToolResult(True, data=results)
        except Exception as e:
            return ToolResult(False, error=f"Embedding API failed: {e}")
