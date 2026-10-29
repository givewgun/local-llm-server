# Using the API

The server speaks the OpenAI API. Point any OpenAI-compatible client at:

```text
base_url = https://llm.givewgun.com/v1
api_key  = sk-...   (a virtual key from the operator)
model    = local-chat
```

## Interactive docs

**https://llm.givewgun.com/docs**: Swagger UI. Click **Authorize**, paste your key
(no `Bearer ` prefix), open an endpoint, edit the example body, and click **Execute**.
Pick a ready-made example (simple, thinking, JSON, tools) from the *Examples* dropdown.
Streaming responses don't render well there; use curl or an SDK for those.

## Models

| `model` | What it is |
|---------|-----------|
| `local-chat` | Primary GPU model (currently Qwen3-8B AWQ, 16k context). Falls back to `local-chat-small` if the GPU engine is down. |
| `local-chat-small` | Llama 3.2 3B on CPU via Ollama: lower quality, ~20 tok/s |
| `ollama/<name>` | Any model pulled into Ollama (if your key allows it) |

`GET /v1/models` lists what your key can use.

## curl

```bash
curl https://llm.givewgun.com/v1/chat/completions \
  -H "Authorization: Bearer $LLM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "local-chat",
    "messages": [{"role": "user", "content": "Explain RAG in two sentences."}],
    "stream": true
  }'
```

## Python (openai SDK)

```python
from openai import OpenAI

client = OpenAI(base_url="https://llm.givewgun.com/v1", api_key=os.environ["LLM_API_KEY"])

stream = client.chat.completions.create(
    model="local-chat",
    messages=[{"role": "user", "content": "Write a haiku about GPUs."}],
    stream=True,
)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="")
```

## TypeScript

```ts
import OpenAI from "openai";

const client = new OpenAI({ baseURL: "https://llm.givewgun.com/v1", apiKey: process.env.LLM_API_KEY });
const res = await client.chat.completions.create({
  model: "local-chat",
  messages: [{ role: "user", content: "Hello!" }],
});
console.log(res.choices[0].message.content);
```

## LangChain / LlamaIndex / others

Use their OpenAI integrations with the base URL above, e.g.
`ChatOpenAI(base_url="https://llm.givewgun.com/v1", api_key=..., model="local-chat")`.

## Features

- **Streaming** — recommended for anything long. Non-streamed requests are cut by Cloudflare after ~100 s.
- **Tool / function calling** — `tools` + `tool_choice: "auto"` supported on `local-chat`.
- **Reasoning (Qwen3 thinking mode)** — off by default for speed. Turn on per request:
  ```json
  {"model": "local-chat", "messages": [...], "chat_template_kwargs": {"enable_thinking": true}}
  ```
  The reasoning arrives in `message.reasoning_content`, the answer in `message.content`.
  With the Python SDK pass it as `extra_body={"chat_template_kwargs": {"enable_thinking": True}}`.
- **JSON output** — `response_format: {"type": "json_object"}` or a JSON schema (`json_schema`).

## Limits and errors

| HTTP | Meaning |
|------|---------|
| 401 | Missing/invalid key |
| 404 | Wrong path — only `/v1/*` (and `/docs`) is public |
| 429 | Your key's rate / token / concurrency limit — back off and retry |
| 5xx / 524 | Server busy or restarting; retry with backoff, use streaming |

Context window is 16,384 tokens (prompt + completion) on the default model.
Response headers `x-litellm-model-group` and `x-litellm-attempted-fallbacks` tell you which model actually answered.
