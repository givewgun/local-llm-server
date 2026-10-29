# ADR-0004: Admin plane on Tailscale only

**Status:** accepted · **Date:** 2026-10-29

## Context

The LiteLLM admin UI, key management API, Grafana and Prometheus must be reachable by
the operator from anywhere, but never by the public.

## Decision

- All admin services publish to `127.0.0.1` only.
- `./llmctl admin expose` runs `tailscale serve` to publish them with HTTPS on the
  tailnet hostname (`https://<machine>.<tailnet>.ts.net`, Grafana on `:8443`).
- The public tunnel never routes admin paths (ADR-0003).

Alternative: Cloudflare Access in front of `admin.<domain>`. Good option too, but needs
Zero Trust configuration outside this repo, and Tailscale was already deployed.

## Consequences

- Admin access requires being on the tailnet (device auth via Tailscale SSO).
- Two independent layers must both fail for admin exposure: the tunnel path allowlist
  and LiteLLM's master-key auth.
