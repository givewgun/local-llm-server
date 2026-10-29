# Architecture

> New to LLM serving? Read [how-it-works.md](how-it-works.md) first.

A self-hosted, OpenAI-compatible LLM API that runs on a consumer GPU box and is
reachable from anywhere on the internet — without opening a single inbound port.

## Goals

| Goal | How |
|------|-----|
| **OpenAI-compatible** — any SDK/tool works unchanged | vLLM + LiteLLM both speak the OpenAI API |
| **Production throughput** on one GPU | vLLM: PagedAttention, continuous batching, prefix caching, CUDA graphs |
| **Multi-tenant** — hand out keys, cap usage, revoke | LiteLLM virtual keys (Postgres-backed) with RPM/TPM/parallel/budget limits |
| **Model swaps without client changes** | Stable public aliases (`local-chat`) decoupled from the loaded model |
| **Zero inbound exposure** | Cloudflare Tunnel (outbound-only); admin plane only on Tailscale |
| **Resilient** | Healthchecks, restart policies, automatic fallback vLLM → Ollama |
| **Observable** | Prometheus + Grafana: tokens/s, TTFT, queue depth, KV cache, tunnel health |
| **Reproducible** | Everything is `compose.yaml` + pinned image tags + `.env`; one CLI (`llmctl`) |

## System context

```mermaid
flowchart LR
    subgraph Internet
        C1[Apps / SDKs<br/>e.g. Panya project]
        C2[Browser users]
    end

    subgraph CF[Cloudflare edge]
        DNS[llm.givewgun.com<br/>TLS · WAF · DDoS]
    end

    subgraph TN[Tailnet - private]
        ADM[Admin laptop / phone]
    end

    subgraph HOST[GPU host - Docker]
        CFD[cloudflared]
        LL[LiteLLM gateway :4000]
        PG[(Postgres<br/>keys · spend)]
        VL[vLLM :8000<br/>Qwen3-8B-AWQ]
        OL[Ollama :11434<br/>native or container]
        PR[Prometheus]
        GF[Grafana]
    end

    C1 -- HTTPS + virtual key --> DNS
    C2 -. optional chat UI .-> DNS
    DNS <-- outbound-only QUIC tunnel --> CFD
    CFD -- /v1/* only --> LL
    LL --> VL
    LL -- fallback / extra models --> OL
    LL --- PG
    PR -- scrape --> VL
    PR -- scrape --> CFD
    GF --> PR
    ADM -- tailscale serve HTTPS --> LL
    ADM -- tailscale serve HTTPS --> GF
```

## Components

| Component | Role | Exposed on |
|-----------|------|------------|
| **vLLM** | GPU inference engine. Loads one model preset (`models/*.yaml`), serves it as `primary`. | Docker network; host loopback `:8000` for debugging |
| **Ollama** | Secondary engine: hot-swappable GGUF models, CPU/GPU offload, fallback target. Native on Windows/macOS, `ollama` profile on Linux. | Host `:11434` |
| **LiteLLM** | API gateway: auth (virtual keys), rate limits, budgets, routing, fallbacks, retries, spend logging, admin UI. | Docker network; host loopback `:4000` |
| **Postgres** | LiteLLM state: keys, users, teams, spend logs. | Docker network only |
| **cloudflared** | Outbound tunnel to Cloudflare. Path-allowlists the public surface. | Nothing — outbound only |
| **Prometheus / Grafana** | Metrics + the `LLM Server` dashboard. | Host loopback `:9090` / `:3000` |
| **API docs** *(optional, `docs` profile)* | Swagger UI over a hand-curated OpenAPI spec (`config/api-docs/openapi.yaml`) covering only the public routes. Same origin as the API, so *Try it out* works. | `<api-host>/docs` via the tunnel; no host port |
| **Open WebUI** *(optional)* | ChatGPT-style UI for non-developers, uses a LiteLLM virtual key. | Host loopback `:8080`; `chat.<domain>` when enabled |

## Request flow

```mermaid
sequenceDiagram
    autonumber
    participant App as Client app
    participant CF as Cloudflare edge
    participant T as cloudflared
    participant G as LiteLLM
    participant DB as Postgres
    participant V as vLLM
    participant O as Ollama

    App->>CF: POST https://llm.givewgun.com/v1/chat/completions<br/>Authorization: Bearer sk-…
    CF->>T: forward over existing tunnel (TLS terminated at edge)
    T->>T: path matches ^/(v1/.*|health/liveliness)$ ? else 404
    T->>G: http://litellm:4000/v1/chat/completions
    G->>DB: validate virtual key (cached), check RPM/TPM/budget
    alt key invalid or over limit
        G-->>App: 401 / 429
    end
    G->>G: resolve alias local-chat → hosted_vllm/primary
    G->>V: /v1/chat/completions (stream)
    alt vLLM healthy
        V-->>G: SSE tokens
    else vLLM down / erroring
        G->>O: fallback local-chat-small (llama3.2:3b-cpu, CPU only)
        O-->>G: tokens
    end
    G-->>App: SSE tokens (via tunnel + edge)
    G->>DB: async spend log (tokens, latency, key — no prompt text)
```

## Trust zones

```mermaid
flowchart TB
    subgraph Z0[Zone 0 · Public internet — untrusted]
        U[Anyone]
    end
    subgraph Z1[Zone 1 · Cloudflare edge]
        E[TLS, WAF, rate limiting, bot checks]
    end
    subgraph Z2[Zone 2 · Data plane — Docker network]
        L[LiteLLM: /v1/* with virtual key]
    end
    subgraph Z3[Zone 3 · Admin plane — Tailnet only]
        A[LiteLLM UI + key mgmt · Grafana · Prometheus]
    end
    subgraph Z4[Zone 4 · Backends — never published]
        B[vLLM · Ollama · Postgres]
    end

    U --> E --> L --> B
    A --> L
    A --> B
```

Rules enforced:

1. **No inbound ports.** Router/NAT untouched. All public traffic arrives over the tunnel.
2. **Path allowlist at the edge connector.** `cloudflared` forwards only `/v1/*`, `/health/liveliness` and (with the `docs` profile) the curated Swagger UI at `/docs`; `/ui`, `/key/*`, `/spend/*` etc. return 404 from the public hostname.
3. **Everything else binds to `127.0.0.1`.** Admin UIs are reached through `tailscale serve` (tailnet-only HTTPS).
4. **Defence in depth on backends.** vLLM requires its own API key even on the internal network.
5. **Least-privilege keys.** Clients get LiteLLM virtual keys with model allowlists and limits; the master key never leaves the host.

See [security.md](security.md) for the threat model.

## Model abstraction

```mermaid
flowchart LR
    subgraph Public names - stable contract
        A[local-chat]
        B[local-chat-small]
        C["ollama/&lt;any pulled model&gt;"]
    end
    subgraph Gateway routing
        A -->|primary| V[hosted_vllm/primary]
        A -.->|fallback| B
        B --> O1[ollama_chat/llama3.2:3b-cpu<br/>CPU only]
        C --> O2["ollama_chat/*"]
    end
    subgraph Engines
        V --> P["vLLM loads models/$MODEL_PRESET.yaml"]
        O1 --> OL[Ollama]
        O2 --> OL
    end
```

Swapping the model is `./llmctl model use <preset>`: vLLM restarts with a new
preset while LiteLLM keeps answering `local-chat` from the Ollama fallback. Clients
never change a line.

## Deployment topologies

The same repo covers single-box and multi-box setups by toggling `COMPOSE_PROFILES`
and two URLs. See [scaling.md](scaling.md).

```mermaid
flowchart LR
    subgraph A[Topology A · single node - current]
        A1[cloudflared + LiteLLM + Postgres + vLLM + monitoring]
    end
    subgraph B[Topology B · gateway + GPU workers over Tailscale]
        B1[Gateway node<br/>e.g. Oracle free VM<br/>cloudflared + LiteLLM + Postgres]
        B2[GPU worker 1<br/>vLLM]
        B3[GPU worker 2<br/>vLLM]
        B1 -- tailnet --> B2
        B1 -- tailnet --> B3
    end
```

## Why these choices

Short versions; full reasoning in [`docs/adr/`](adr/).

- **vLLM *and* LiteLLM, not either/or.** vLLM is the engine (fast batching on the GPU); LiteLLM is the gateway (keys, limits, routing, fallbacks). Different layers — industry setups run both. Ollama stays as the convenient secondary engine. → [ADR-0001](adr/0001-inference-engine.md), [ADR-0002](adr/0002-api-gateway.md)
- **Cloudflare Tunnel, not port-forwarding.** No exposed home IP, free TLS/WAF/DDoS, works behind CGNAT. → [ADR-0003](adr/0003-public-ingress.md)
- **Tailscale for admin, not public auth.** The admin surface simply isn't on the internet. → [ADR-0004](adr/0004-admin-plane.md)
- **Docker Compose, not Kubernetes.** One box; Compose gives healthchecks, restarts, profiles with zero platform overhead. Move to k8s only at multiple GPU nodes needing scheduling. → [ADR-0005](adr/0005-orchestration.md)
