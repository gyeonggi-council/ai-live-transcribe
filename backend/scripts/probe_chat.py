"""chat/completions 400 원인 진단 — 실제 OpenAI 에러 본문 출력."""
import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from app.core.config import settings

print("openai_model =", repr(settings.openai_model))


async def try_call(payload, label):
    async with httpx.AsyncClient(timeout=60.0) as c:
        r = await c.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"},
            json=payload,
        )
    print(f"\n[{label}] HTTP {r.status_code}")
    if r.status_code != 200:
        print("  body:", r.text[:500])
    else:
        print("  ok:", r.json()["choices"][0]["message"]["content"][:80])


msgs = [{"role": "user", "content": "안녕? 한 단어로 답해."}]
asyncio.run(try_call(
    {"model": settings.openai_model, "messages": msgs, "temperature": 0.3, "max_tokens": 50},
    "current(max_tokens+temp0.3)"))
asyncio.run(try_call(
    {"model": settings.openai_model, "messages": msgs, "max_completion_tokens": 50},
    "max_completion_tokens, default temp"))
asyncio.run(try_call(
    {"model": "gpt-4o-mini", "messages": msgs, "temperature": 0.3, "max_tokens": 50},
    "gpt-4o-mini fallback"))
