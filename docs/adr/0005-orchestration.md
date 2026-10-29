# ADR-0005: Docker Compose with profiles

**Status:** accepted · **Date:** 2026-10-29

## Context

One GPU host today; maybe a few more later. Must be reproducible on Windows (Docker
Desktop/WSL 2) and Linux.

## Decision

A single `compose.yaml` with profiles (`vllm`, `ollama`, `tunnel`, `monitoring`, `webui`)
selected by `COMPOSE_PROFILES` in `.env`. Pinned image tags, healthchecks with
`depends_on: condition: service_healthy`, `restart: unless-stopped`, log rotation.
A single bash CLI (`llmctl`) wraps the workflows and runs helper Python *inside* the
gateway container so the host needs only Docker and bash.

## Consequences

- Same files serve single-node and gateway/worker topologies (docs/scaling.md).
- No scheduler, no autoscaling, no rolling updates. When we have several GPU nodes that
  need those, move to Kubernetes (vLLM production-stack / KServe) and keep the LiteLLM
  config.
