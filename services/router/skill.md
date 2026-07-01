# Cheapest LLM Router

Given a prompt and an optional minimum quality tier, this service picks the cheapest LLM that meets the bar, tells you the estimated cost, and can also run the completion. Use it as a routing layer in front of any multi-model workflow when you care about cost.

## Base URL

http://localhost:8000

(Replace with your public URL after you deploy, for example `https://cheapest-router.demo.nandahack.example`.)

## Endpoints

### GET /models
Return every model the router knows about, with price per 1k tokens and a quality tier.

Example call:
```
curl -s https://your-router/models
```

Example reply:
```
{
  "count": 6,
  "models": [
    {"id": "llama-3.1-8b", "provider": "groq", "quality": "basic",
     "price_per_1k_input": 0.00005, "price_per_1k_output": 0.00008},
    {"id": "haiku-4.5", "provider": "anthropic", "quality": "standard",
     "price_per_1k_input": 0.001, "price_per_1k_output": 0.005}
  ]
}
```

### POST /route
Pick the cheapest eligible model without running it. Cheap and fast. Use this when the caller wants to see the choice before spending.

Body:
```
{"prompt": "Summarize this doc in 3 lines.",
 "min_quality": "standard",
 "max_output_tokens": 512}
```
- `prompt` (required): the prompt you would send to an LLM.
- `min_quality` (optional, default `basic`): one of `basic | standard | high | frontier`.
- `max_output_tokens` (optional, default 512): used to estimate output cost.

Example reply:
```
{
  "chosen_model": "haiku-4.5",
  "provider": "anthropic",
  "quality": "standard",
  "estimated_cost_cents": 0.2560,
  "estimated_input_tokens": 12,
  "why": "Cheapest model meeting min_quality=standard..."
}
```

### POST /complete
Pick the cheapest eligible model AND run the completion. Returns the answer and the actual cost. Body is identical to `/route`.

Example reply:
```
{
  "model": "haiku-4.5",
  "provider": "anthropic",
  "response": "The three main themes of the document are ...",
  "cost_cents": 0.2560,
  "input_tokens": 12,
  "output_tokens_max": 512
}
```

## How the agent should use this

1. If the user gives a quality hint ("use a strong model", "just cheap"), map it to `min_quality`: cheap → `basic`, default → `standard`, strong → `high`, best → `frontier`. Otherwise omit and let it default to `basic`.
2. If the user wants to preview before paying, call `POST /route`, then tell them `chosen_model` and `estimated_cost_cents` and ask to confirm.
3. Otherwise call `POST /complete` directly, return `response` to the user, and mention `model` + `cost_cents` so they know what they paid for.
4. If you get `400 No models meet min_quality=...`, drop the bar one tier and retry, or tell the user the requested tier is unreachable.
5. Call `GET /models` only if the user asks to see the full list. The router adds new models without breaking this SkillMD.

## Notes for judges
- No API key required. The demo build returns deterministic mock completions so the flow always works offline. The routing logic is real.
- Health check: `GET /` returns the service metadata.
- Interactive OpenAPI docs at `/docs`.
