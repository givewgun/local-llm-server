# ADR-0001: vLLM as primary inference engine, Ollama as secondary

**Status:** accepted · **Date:** 2026-10-29

## Context

We need to serve a ~7–8B model from a 16 GB consumer GPU to several remote clients
concurrently, OpenAI-compatible, with good latency under load. Ollama was already
installed on the host.

## Options

| | vLLM | Ollama | llama.cpp server | SGLang / TGI |
|-|------|--------|------------------|--------------|
| Concurrent throughput | **Excellent** — continuous batching, PagedAttention | Limited (parallel slots, no paged KV) | Moderate | Excellent |
| Model formats | HF safetensors, AWQ/GPTQ/FP8 | GGUF | GGUF | HF |
| Ops ergonomics | One model per process, slower start | **Excellent** — pull/run, auto load/unload | Good | Similar to vLLM |
| Metrics | Rich Prometheus | Minimal | Basic | Rich |
| Industry use | De-facto standard for self-hosted serving | Dev/desktop | Edge/CPU | Production |

## Decision

- **vLLM** serves the primary model (`local-chat`): it is the industry standard for
  serving open models, scales with concurrent users, and exposes the metrics we need.
- **Ollama** stays as a secondary engine: instant access to any GGUF model
  (`ollama/*`), the fallback target when vLLM is down or swapping models, and it can
  run partially on CPU.
- Model selection lives in `models/*.yaml` presets so changing models is data, not code.

## Consequences

- vLLM pre-allocates VRAM (`gpu-memory-utilization`); Ollama gets the remainder. Big
  Ollama models will run partly on CPU while vLLM is up.
- vLLM cold start is minutes (download + CUDA graph capture); mitigated by the Ollama fallback.
- vLLM on Windows requires Docker Desktop + WSL 2 GPU support (works on Blackwell, verified).
