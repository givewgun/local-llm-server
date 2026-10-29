# local-llm-server

A reusable setup for running an OpenAI-compatible LLM API on your own GPU and
serving it on the internet over HTTPS, with no open router ports.

```text
Client ──HTTPS──▶ Cloudflare edge ──tunnel──▶ cloudflared ──▶ LiteLLM gateway ──▶ vLLM (GPU)
                                                          (keys, limits,         └─▶ Ollama (fallback / extras)
                                                           routing, logs)
Admin  ──Tailscale──▶ LiteLLM UI · Grafana
```

| Layer | Component | Why |
|-------|-----------|-----|
| Inference | **vLLM** (+ Ollama) | High concurrent throughput on one GPU; Ollama for quick model swaps and fallback |
| Gateway | **LiteLLM** + Postgres | Per-client API keys, rate limits, stable model aliases, fallbacks, usage logs |
| Ingress | **Cloudflare Tunnel** | Public HTTPS on your domain with no inbound ports, your home IP hidden, WAF/DDoS at the edge |
| Admin | **Tailscale** | Admin UI and dashboards are reachable only on your tailnet |
| Observability | **Prometheus + Grafana** | Tokens/s, TTFT, queue depth, KV cache, tunnel health |
| Ops | **Docker Compose + `llmctl`** | Pinned, reproducible; the only host requirements are Docker and bash |

## Quick start

```bash
git clone https://github.com/givewgun/local-llm-server.git && cd local-llm-server
./llmctl init                 # .env with generated secrets → edit hostnames/profiles
./llmctl doctor               # Docker, GPU, config checks
./llmctl up && ./llmctl test  # local stack + smoke test
./llmctl tunnel setup         # Cloudflare login → tunnel → DNS
./llmctl up
./llmctl key create my-app --rpm 60
./llmctl test public sk-...   # end-to-end through Cloudflare
./llmctl admin expose         # admin UI + Grafana on your tailnet
```

On Windows, run these from Git Bash as `bash llmctl …`. Full walkthrough: **[docs/setup.md](docs/setup.md)**.

## Calling it

```python
from openai import OpenAI
client = OpenAI(base_url="https://llm.givewgun.com/v1", api_key="sk-...")
client.chat.completions.create(model="local-chat", messages=[{"role": "user", "content": "hi"}])
```

More examples (streaming, tools, reasoning mode, TS, curl): **[docs/client-usage.md](docs/client-usage.md)**.

## Interactive API docs

Swagger UI at **https://llm.givewgun.com/docs** (`docs` profile). It documents only the public
routes and has examples; click **Authorize** with your key, then **Try it out**.
LiteLLM's full admin Swagger stays private on the tailnet.

## Switching models

```bash
./llmctl model list
./llmctl model use qwen2.5-7b-instruct-awq
```

Clients always call `local-chat`. While vLLM reloads, the gateway serves requests from
the Ollama fallback. Presets are small YAML files in [`models/`](models/); add one per model.

| Preset | Model | VRAM (weights) | Verified |
|--------|-------|----------------|----------|
| `qwen3-8b-awq` *(default)* | Qwen3-8B AWQ, 16k ctx, tools, optional thinking | ~6 GB | ✅ RTX 5060 Ti 16 GB |
| `qwen2.5-7b-instruct-awq` | Qwen2.5-7B-Instruct AWQ, 16k ctx, tools | ~6 GB | ✅ RTX 5060 Ti 16 GB |
| `qwen3-4b-awq` | Qwen3-4B AWQ, for 8 GB cards | ~3 GB | – |
| `qwen3-14b-awq` | Qwen3-14B AWQ, needs a dedicated 16 GB or 24 GB GPU | ~10 GB | – |
| `llama-3.1-8b-instruct-awq` | Llama 3.1 8B Instruct AWQ | ~6 GB | – |

## Repository layout

```text
compose.yaml                 every service; profiles pick what runs
.env.example                 all knobs + pinned image versions
llmctl                       operator CLI (bash)
models/*.yaml                vLLM model presets
config/litellm/config.yaml   public model aliases, fallbacks, key limits
config/cloudflared/          tunnel ingress template (public path allowlist)
config/api-docs/openapi.yaml curated public API spec served at /docs
config/prometheus/, grafana/ scrape config + provisioned "LLM Server" dashboard
scripts/admin.py             gateway admin/smoke-test helper (runs inside the container)
docs/                        architecture, setup, operations, security, scaling, ADRs
```

## Documentation

- [Architecture](docs/architecture.md): components, request flow, trust zones, diagrams
- [Setup](docs/setup.md): fresh machine to public API
- [Operations](docs/operations.md): models, keys, upgrades, backups, troubleshooting
- [Security](docs/security.md): threat model, key handling, Cloudflare hardening
- [Scaling and reuse](docs/scaling.md): gateway + GPU workers over Tailscale, cloud fallback
- [Client usage](docs/client-usage.md): how consumers call the API
- [Decision records](docs/adr/): why vLLM + LiteLLM + Cloudflare Tunnel + Tailscale + Compose

## License

MIT
