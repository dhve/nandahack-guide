# Polite Email Rewriter

Turn a blunt draft email into a polite version in the tone you want. This service is built on top of the Cheapest LLM Router: it picks a model tier based on the email's priority, so quick notes stay cheap and important messages get a stronger model.

## Base URL

http://localhost:8001

## Endpoints

### POST /rewrite
Rewrite a draft email.

Body:
```
{"draft": "you never replied. send it today.",
 "tone": "professional",
 "priority": "normal"}
```
- `draft` (required): the blunt draft to soften.
- `tone` (optional, default `professional`): `professional | warm | apologetic`.
- `priority` (optional, default `normal`): `normal` uses a basic model, `important` upgrades to standard.

Example reply:
```
{"rewritten": "Hi, following up on my previous message...",
 "via_model": "gpt-oss-20b",
 "via_provider": "local-ollama",
 "cost_cents": 0.0,
 "note": "Composed the 'professional' tone at min_quality=basic through cheapest-llm-router."}
```

## How the agent should use this

1. Ask the user what tone they want if the request isn't clear.
2. Call `POST /rewrite` with `draft` and `tone`.
3. If the user says the message is urgent, important, to a customer, or to a boss, pass `priority: "important"`.
4. Return `rewritten` to the user, and mention `via_model` + `cost_cents` if they want to know how it was produced.

## Notes for judges
- This service COMPOSES the Cheapest LLM Router. That is the point: NANDA Town skills can layer on each other. Two agent-facing services, connected end to end.
- No API key required.
