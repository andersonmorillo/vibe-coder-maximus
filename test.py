"""Smoke the same OpenRouter chat call talk uses. Key comes from .env, not this file."""
import json

import requests

from voice_cursor.envfile import load_talk_env, talk_llm

load_talk_env(".")
spec = talk_llm()
if not spec["api_key"]:
    raise SystemExit("no OPENROUTER_API_KEY in .env")

response = requests.post(
    url=f"{spec['base_url']}/chat/completions",
    headers={
        "Authorization": f"Bearer {spec['api_key']}",
        "Content-Type": "application/json",
    },
    data=json.dumps(
        {
            "model": spec["model"],
            "messages": [
                {
                    "role": "user",
                    "content": "How many r's are in the word 'strawberry'?",
                }
            ],
            "reasoning": {"enabled": True},
        }
    ),
    timeout=60,
)
response.raise_for_status()
print(response.json()["choices"][0]["message"])
