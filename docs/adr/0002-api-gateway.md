# ADR-0002: LiteLLM proxy as the API gateway

**Status:** accepted · **Date:** 2026-10-29

## Context

Exposing vLLM directly would give one shared static API key, no per-client limits,
no usage accounting, no fallback, and couple clients to the loaded model's name.

## Decision

Put **LiteLLM proxy** (Postgres-backed) in front of all engines. It provides:

- Virtual keys per consumer with model allowlists, RPM/TPM/parallel limits, budgets, expiry.
- Stable public model aliases (`local-chat`) mapped to whatever engine/model is current.
- Routing, retries, fallbacks (`local-chat` → `local-chat-small`), load balancing across workers.
- Spend/usage logs and an admin UI.
- One integration point for cloud providers later (same API, real fallbacks).

Alternatives considered: plain nginx/Caddy with a static key (no per-key limits or
fallbacks), Kong/Envoy AI gateway (heavier, more infra than one box warrants), Cloudflare
AI Gateway (built for upstream SaaS providers, not private origins behind a tunnel).

## Consequences

- Adds Postgres and ~1 GB RAM. Acceptable.
- LiteLLM's admin surface must never be public → solved by ADR-0003/0004.
- LiteLLM releases are frequent; we pin a version tag and upgrade deliberately.
