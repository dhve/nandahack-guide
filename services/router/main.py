"""
Cheapest LLM Router, a NANDA Town demo service.

Given a prompt and a minimum quality tier, this service picks the cheapest
LLM that meets the bar and can also run the completion. Designed to be
callable by an AI agent from its SkillMD alone.
"""

import hashlib
import json
import math
import pathlib
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

ROOT = pathlib.Path(__file__).parent
MODELS = json.loads((ROOT / "models.json").read_text())
QUALITY_ORDER = {"basic": 1, "standard": 2, "high": 3, "frontier": 4}

app = FastAPI(
    title="Cheapest LLM Router",
    version="0.1.0",
    description="Picks the cheapest LLM that meets a quality bar. NandaHack demo.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class RouteRequest(BaseModel):
    prompt: str = Field(..., description="The prompt you want to send to an LLM.")
    min_quality: str = Field("basic", description="basic | standard | high | frontier")
    max_output_tokens: int = Field(512, ge=1, le=8192)


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def choose_model(prompt: str, min_quality: str, max_output_tokens: int):
    q = QUALITY_ORDER.get(min_quality)
    if q is None:
        raise HTTPException(400, f"Unknown min_quality '{min_quality}'. Use one of {list(QUALITY_ORDER)}.")
    eligible = [m for m in MODELS if QUALITY_ORDER[m["quality"]] >= q]
    if not eligible:
        raise HTTPException(400, f"No models meet min_quality={min_quality}")
    in_toks = estimate_tokens(prompt)
    def cost(m):
        return (in_toks * m["price_per_1k_input"] + max_output_tokens * m["price_per_1k_output"]) / 1000
    winner = min(eligible, key=cost)
    return winner, cost(winner), in_toks


@app.get("/")
def root():
    return {
        "service": "cheapest-llm-router",
        "docs": "/docs",
        "skill_md": "/skill.md",
        "endpoints": ["/models", "/route", "/complete"],
    }


@app.get("/models")
def list_models():
    return {"count": len(MODELS), "models": MODELS}


@app.post("/route")
def route(req: RouteRequest):
    m, c, in_toks = choose_model(req.prompt, req.min_quality, req.max_output_tokens)
    return {
        "chosen_model": m["id"],
        "provider": m["provider"],
        "quality": m["quality"],
        "estimated_cost_cents": round(c * 100, 6),
        "estimated_input_tokens": in_toks,
        "why": (
            f"Cheapest model meeting min_quality={req.min_quality}. "
            f"Priced at ${m['price_per_1k_input']}/1k in, ${m['price_per_1k_output']}/1k out."
        ),
    }


@app.post("/complete")
def complete(req: RouteRequest):
    m, c, in_toks = choose_model(req.prompt, req.min_quality, req.max_output_tokens)
    # Deterministic mock completion so the demo always works with no API keys.
    seed = hashlib.sha256((m["id"] + req.prompt).encode()).hexdigest()[:10]
    reply = (
        f"[{m['id']} · demo mode] I would answer: {req.prompt.strip()[:80]}"
        + (" ..." if len(req.prompt) > 80 else "")
        + f" (response id {seed})"
    )
    return {
        "model": m["id"],
        "provider": m["provider"],
        "response": reply,
        "cost_cents": round(c * 100, 6),
        "input_tokens": in_toks,
        "output_tokens_max": req.max_output_tokens,
    }


@app.get("/skill.md", response_class=PlainTextResponse)
def skill_md():
    return (ROOT / "skill.md").read_text()


# ---------------------------------------------------------------------------
# NANDA Town submission proxy.
#
# The onboarding pages at dhve.github.io let contributors submit code,
# video, live-link, and write-up contributions to the NANDA Town registry.
# The registry API (nandatown.projectnanda.org/api/skills) does not send
# CORS headers, so browsers block direct cross-origin POSTs. This endpoint
# forwards the submission server-side. It only relays to the one fixed URL.
# ---------------------------------------------------------------------------

TOWN_API = "https://nandatown.projectnanda.org/api/skills"
VALID_SOURCE_TYPES = {"url", "github", "content"}


class TownSubmission(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    author: str = Field(..., min_length=2, max_length=200)
    description: str = Field(..., min_length=10, max_length=2000)
    source_type: str = Field(..., description="url | github | content")
    source_url: Optional[str] = Field(None, max_length=1000)
    content: Optional[str] = Field(None, max_length=100_000)
    endpoints: Optional[str] = Field(None, max_length=10_000)
    tags: Optional[str] = Field(None, max_length=500)
    dry_run: bool = Field(False, description="Validate only, do not forward.")


@app.post("/town/submit")
def town_submit(sub: TownSubmission):
    if sub.source_type not in VALID_SOURCE_TYPES:
        raise HTTPException(400, f"source_type must be one of {sorted(VALID_SOURCE_TYPES)}")
    if sub.source_type in ("url", "github") and not (sub.source_url or "").startswith("http"):
        raise HTTPException(400, "source_url must be a full http(s) URL for this source_type")
    if sub.source_type == "content" and not (sub.content or "").strip():
        raise HTTPException(400, "content is required when source_type is 'content'")

    payload = {
        "name": sub.name,
        "author": sub.author,
        "description": sub.description,
        "source_type": sub.source_type,
        "source_url": sub.source_url,
        "content": sub.content,
        "endpoints": sub.endpoints,
        "tags": sub.tags,
    }
    if sub.dry_run:
        return {"ok": True, "dry_run": True, "payload": payload}

    try:
        r = httpx.post(TOWN_API, json=payload, timeout=30)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Could not reach NANDA Town: {e}")
    if r.status_code >= 400:
        raise HTTPException(r.status_code, f"NANDA Town rejected the submission: {r.text[:500]}")
    return {"ok": True, "town_response": r.json()}
