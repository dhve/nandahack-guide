# Polite Email Rewriter

Turn a blunt draft email into a polite version in the tone you want. This service is built on top of the Cheapest LLM Router: it picks a model tier based on the email's priority, so quick notes stay cheap and important messages get a stronger model.

## Base URL

https://polite-email-rewriter.onrender.com

## Authentication

None. No API key, no token, no signup. Just call the endpoints.

## Composes

This service internally calls https://cheapest-llm-router.onrender.com/complete on every `/rewrite`. That upstream service is a separate NandaHack submission — see its own SkillMD at https://cheapest-llm-router.onrender.com/skill.md.

## Endpoints

### POST /rewrite
Rewrite a draft email.

Example call:
```
curl -s -X POST https://polite-email-rewriter.onrender.com/rewrite \
  -H "Content-Type: application/json" \
  -d '{"draft": "you never replied. send it today.",
       "tone": "professional",
       "priority": "normal"}'
```

Body:
- `draft` (required): the blunt draft to soften.
- `tone` (optional, default `professional`): `professional | warm | apologetic`.
- `priority` (optional, default `normal`): `normal` uses a basic model, `important` upgrades to standard.

Example reply:
```
{
  "rewritten": "Hi, following up on my previous message...",
  "via_model": "gpt-oss-20b",
  "via_provider": "local-ollama",
  "cost_cents": 0.0,
  "note": "Composed the 'professional' tone at min_quality=basic through cheapest-llm-router."
}
```

## How the agent should use this

1. Ask the user what tone they want if the request isn't clear.
2. Call `POST /rewrite` with `draft` and `tone`.
3. If the user says the message is urgent, important, to a customer, or to a boss, pass `priority: "important"`.
4. Return `rewritten` to the user, and mention `via_model` + `cost_cents` if they want to know how it was produced.
5. On the first request of the day the service may take 30 to 60 seconds because both this service and the upstream router are Render free-tier containers waking from sleep. Retry once if you get a 502 or timeout — the emailer already retries against the router internally.

## Notes for judges
- Deployed on Render, source at https://github.com/dhve/nandahack-guide/tree/main/services/emailer.
- This service COMPOSES the Cheapest LLM Router at https://cheapest-llm-router.onrender.com. Two agent-facing NandaHack submissions, connected end to end.
- No API key required.
- Interactive OpenAPI docs at https://polite-email-rewriter.onrender.com/docs.
