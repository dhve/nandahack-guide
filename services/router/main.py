"""
Cheapest LLM Router, a NANDA Town demo service.

Given a prompt and a minimum quality tier, this service picks the cheapest
LLM that meets the bar and can also run the completion. Designed to be
callable by an AI agent from its SkillMD alone.
"""

import base64
import hashlib
import json
import math
import os
import pathlib
import secrets
import uuid
from datetime import datetime, timezone
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


# ---------------------------------------------------------------------------
# Showcase with moderation.
#
# Contributions submitted on the onboarding pages are stored as JSON files
# in the public GitHub repo (SHOWCASE_REPO), so the whole gallery is durable
# and world-readable. Flow:
#   POST /showcase/submit          -> writes showcase/data/pending/<id>.json
#   GET  /showcase/pending         -> admin: list the review queue
#   POST /showcase/approve         -> admin: move entry into approved.json,
#                                     optionally register it in the NANDA
#                                     Town registry. The commit triggers a
#                                     GitHub Pages rebuild, so the public
#                                     showcase page updates automatically.
#   POST /showcase/reject          -> admin: delete the pending entry
#   GET  /showcase/approved        -> public: freshest approved list
#
# Requires env vars on the host:
#   GITHUB_TOKEN  fine-grained PAT with contents read/write on SHOWCASE_REPO
#   ADMIN_KEY     shared secret for the admin review page
# ---------------------------------------------------------------------------

SHOWCASE_REPO = os.environ.get("SHOWCASE_REPO", "dhve/nandahack-guide")
GH_API = "https://api.github.com"
PENDING_DIR = "showcase/data/pending"
APPROVED_PATH = "showcase/data/approved.json"
SUBMISSION_TYPES = {"code", "live", "video", "writeup"}
SUBMITTER_PATHS = {"individual", "startup", "corporate"}


def _gh_headers():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise HTTPException(503, "Showcase storage is not configured yet (missing GITHUB_TOKEN).")
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def _gh_get(path: str):
    r = httpx.get(f"{GH_API}/repos/{SHOWCASE_REPO}/contents/{path}", headers=_gh_headers(), timeout=30)
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        raise HTTPException(502, f"GitHub read failed ({r.status_code}): {r.text[:300]}")
    return r.json()


def _gh_put(path: str, data, message: str, sha: Optional[str] = None):
    body = {
        "message": message,
        "content": base64.b64encode(json.dumps(data, indent=2).encode()).decode(),
    }
    if sha:
        body["sha"] = sha
    r = httpx.put(f"{GH_API}/repos/{SHOWCASE_REPO}/contents/{path}", headers=_gh_headers(), json=body, timeout=30)
    if r.status_code >= 400:
        raise HTTPException(502, f"GitHub write failed ({r.status_code}): {r.text[:300]}")
    return r.json()


def _gh_delete(path: str, sha: str, message: str):
    r = httpx.request(
        "DELETE",
        f"{GH_API}/repos/{SHOWCASE_REPO}/contents/{path}",
        headers=_gh_headers(),
        json={"message": message, "sha": sha},
        timeout=30,
    )
    if r.status_code >= 400:
        raise HTTPException(502, f"GitHub delete failed ({r.status_code}): {r.text[:300]}")


def _decode_file(obj) -> dict:
    return json.loads(base64.b64decode(obj["content"]).decode())


def _require_admin(key: Optional[str]):
    expected = os.environ.get("ADMIN_KEY")
    if not expected:
        raise HTTPException(503, "Admin review is not configured yet (missing ADMIN_KEY).")
    if not key or not secrets.compare_digest(key, expected):
        raise HTTPException(401, "Invalid admin key.")


class ShowcaseSubmission(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    author: str = Field(..., min_length=2, max_length=200)
    description: str = Field(..., min_length=10, max_length=2000)
    submission_type: str = Field(..., description="code | live | video | writeup")
    contributor_path: str = Field("individual", description="individual | startup | corporate")
    url: Optional[str] = Field(None, max_length=1000)
    content: Optional[str] = Field(None, max_length=100_000)
    endpoints: Optional[str] = Field(None, max_length=10_000)
    tags: Optional[str] = Field(None, max_length=500)


class ModerationAction(BaseModel):
    id: str = Field(..., min_length=8, max_length=64)
    admin_key: str
    register_in_town: bool = Field(True, description="Also register approved entry in the NANDA Town registry.")


@app.post("/showcase/submit")
def showcase_submit(sub: ShowcaseSubmission):
    if sub.submission_type not in SUBMISSION_TYPES:
        raise HTTPException(400, f"submission_type must be one of {sorted(SUBMISSION_TYPES)}")
    if sub.contributor_path not in SUBMITTER_PATHS:
        raise HTTPException(400, f"contributor_path must be one of {sorted(SUBMITTER_PATHS)}")
    if sub.submission_type in ("code", "live", "video") and not (sub.url or "").startswith("http"):
        raise HTTPException(400, "A full http(s) URL is required for this submission type.")
    if sub.submission_type == "writeup" and len((sub.content or "").strip()) < 50:
        raise HTTPException(400, "The written case needs some substance.")

    entry_id = uuid.uuid4().hex[:12]
    record = {
        "id": entry_id,
        "status": "pending",
        "submitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "name": sub.name,
        "author": sub.author,
        "description": sub.description,
        "submission_type": sub.submission_type,
        "contributor_path": sub.contributor_path,
        "url": sub.url,
        "content": sub.content,
        "endpoints": sub.endpoints,
        "tags": sub.tags,
    }
    _gh_put(f"{PENDING_DIR}/{entry_id}.json", record, f"Showcase submission: {sub.name} ({entry_id})")
    return {"ok": True, "id": entry_id, "status": "pending",
            "note": "Submitted for review. It appears on the public showcase once approved."}


@app.get("/showcase/pending")
def showcase_pending(admin_key: str):
    _require_admin(admin_key)
    listing = _gh_get(PENDING_DIR)
    if listing is None:
        return {"count": 0, "pending": []}
    entries = []
    for f in listing:
        if f.get("name", "").endswith(".json"):
            obj = _gh_get(f["path"])
            if obj:
                entries.append(_decode_file(obj))
    entries.sort(key=lambda e: e.get("submitted_at", ""), reverse=True)
    return {"count": len(entries), "pending": entries}


@app.get("/showcase/approved")
def showcase_approved():
    obj = _gh_get(APPROVED_PATH)
    entries = _decode_file(obj) if obj else []
    return {"count": len(entries), "approved": entries}


@app.post("/showcase/approve")
def showcase_approve(action: ModerationAction):
    _require_admin(action.admin_key)
    pending_path = f"{PENDING_DIR}/{action.id}.json"
    obj = _gh_get(pending_path)
    if obj is None:
        raise HTTPException(404, f"No pending submission with id {action.id}")
    record = _decode_file(obj)
    record["status"] = "approved"
    record["approved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    town_result = None
    if action.register_in_town:
        try:
            if record["submission_type"] == "writeup":
                payload = {"source_type": "content", "source_url": None, "content": record["content"]}
            elif record["submission_type"] == "code":
                payload = {"source_type": "github", "source_url": record["url"], "content": None}
            else:
                payload = {"source_type": "url", "source_url": record["url"], "content": None}
            payload.update({
                "name": record["name"], "author": record["author"],
                "description": record["description"], "endpoints": record["endpoints"],
                "tags": record["tags"],
            })
            r = httpx.post(TOWN_API, json=payload, timeout=30)
            town_result = {"status": r.status_code}
            if r.status_code < 400:
                data = r.json()
                record["town_registry_id"] = data.get("id") or (data.get("skill") or {}).get("id")
        except httpx.HTTPError as e:
            town_result = {"error": str(e)[:200]}

    approved_obj = _gh_get(APPROVED_PATH)
    approved = _decode_file(approved_obj) if approved_obj else []
    approved = [e for e in approved if e.get("id") != record["id"]]
    approved.insert(0, record)
    _gh_put(APPROVED_PATH, approved, f"Approve showcase entry: {record['name']} ({record['id']})",
            sha=approved_obj["sha"] if approved_obj else None)
    _gh_delete(pending_path, obj["sha"], f"Remove pending entry {record['id']} after approval")
    return {"ok": True, "id": record["id"], "status": "approved", "town_registry": town_result,
            "note": "The showcase page updates automatically after the GitHub Pages rebuild (about a minute)."}


@app.post("/showcase/reject")
def showcase_reject(action: ModerationAction):
    _require_admin(action.admin_key)
    pending_path = f"{PENDING_DIR}/{action.id}.json"
    obj = _gh_get(pending_path)
    if obj is None:
        raise HTTPException(404, f"No pending submission with id {action.id}")
    _gh_delete(pending_path, obj["sha"], f"Reject showcase entry {action.id}")
    return {"ok": True, "id": action.id, "status": "rejected"}
