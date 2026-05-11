"""
llm_api.py — LLM Completion Tool

Wraps the AI analysis call from original generate_briefing.py.
"""

from agent_news_briefing.core.tool import BaseTool, ToolResult
from agent_news_briefing import config


class LlmCompletionTool(BaseTool):
    """Call the LLM (DeepSeek via SiliconFlow) for text generation."""

    name = "llm_api"
    description = "Call LLM for analysis and summarization"

    def run(self, system_prompt: str = "", user_content: str = "", **kwargs) -> ToolResult:
        try:
            import json
            from urllib.request import Request, urlopen

            if not config.API_KEY:
                return ToolResult(False, error="No API key configured")

            url = f"{config.API_BASE_URL.rstrip('/')}/v1/chat/completions"
            payload = json.dumps({
                "model": config.ANALYST_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "temperature": config.ANALYST_TEMPERATURE,
                "max_tokens": config.ANALYST_MAX_TOKENS,
            }).encode()

            req = Request(url, data=payload, headers={
                "Authorization": f"Bearer {config.API_KEY}",
                "Content-Type": "application/json",
            })

            with urlopen(req, timeout=config.TOOL_LLM_TIMEOUT) as resp:
                body = resp.read().decode()
                result = json.loads(body)

            content = result["choices"][0]["message"]["content"]
            return ToolResult(True, data=content)

        except Exception as e:
            return ToolResult(False, error=f"LLM call failed: {e}")
