from typing import Optional
import httpx
from app.config import settings


class LLMClient:
    async def generate(self, prompt: str) -> str:
        if settings.LLM_PROVIDER.lower() == "ollama":
            return await self._ollama(prompt)
        return ""  # none

    async def _ollama(self, prompt: str) -> str:
        url = f"{settings.OLLAMA_BASE_URL}/api/generate"
        payload = {
            "model": settings.OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.2,
            },
        }
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
            return data.get("response", "").strip()


llm_client = LLMClient()
