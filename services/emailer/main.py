"""
Polite Email Rewriter — a second NandaHack submission that COMPOSES
the Cheapest LLM Router. Demonstrates two agent-facing services connected
end to end: a caller service reaches an underlying model via the router.
"""

import os
import pathlib
import time
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

ROOT = pathlib.Path(__file__).parent
ROUTER_URL = os.environ.get("ROUTER_URL", "http://localhost:8000")

app = FastAPI(title="Polite Email Rewriter", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class RewriteRequest(BaseModel):
    draft: str = Field(..., description="A blunt draft email to soften.")
    tone: str = Field("professional", description="professional | warm | apologetic")
    priority: str = Field("normal", description="normal | important -> influences model tier")


TONE_HINT = {
    "professional": "Rewrite this so it is polite, direct, and businesslike.",
    "warm": "Rewrite this so it is friendly and warm without losing clarity.",
    "apologetic": "Rewrite this in an apologetic register while keeping the request clear.",
}

PRIORITY_TO_QUALITY = {"normal": "basic", "important": "standard"}


@app.get("/")
def root():
    return {
        "service": "polite-email-rewriter",
        "depends_on": ROUTER_URL,
        "skill_md": "/skill.md",
        "endpoints": ["/rewrite"],
    }


@app.post("/rewrite")
def rewrite(req: RewriteRequest):
    hint = TONE_HINT.get(req.tone)
    if hint is None:
        raise HTTPException(400, f"Unknown tone '{req.tone}'. Use professional | warm | apologetic.")
    quality = PRIORITY_TO_QUALITY.get(req.priority, "basic")
    prompt = f"{hint}\n\nDraft:\n{req.draft}\n\nReturn only the rewritten email."
    # Retry against Render's free-tier edge, which occasionally 404s a request
    # while the router container is still spinning up.
    last_err = None
    r = None
    for attempt in range(4):
        try:
            r = httpx.post(
                f"{ROUTER_URL}/complete",
                json={"prompt": prompt, "min_quality": quality, "max_output_tokens": 400},
                timeout=65,
            )
            if r.status_code < 400:
                break
            last_err = f"HTTP {r.status_code}"
        except httpx.HTTPError as e:
            last_err = str(e)
        time.sleep(1.5 * (attempt + 1))
    if r is None or r.status_code >= 400:
        raise HTTPException(502, f"Router unavailable at {ROUTER_URL} after retries: {last_err}")
    data = r.json()
    return {
        "rewritten": data["response"],
        "via_model": data["model"],
        "via_provider": data["provider"],
        "cost_cents": data["cost_cents"],
        "note": f"Composed the '{req.tone}' tone at min_quality={quality} through cheapest-llm-router.",
    }


@app.get("/skill.md", response_class=PlainTextResponse)
def skill_md():
    return (ROOT / "skill.md").read_text()
