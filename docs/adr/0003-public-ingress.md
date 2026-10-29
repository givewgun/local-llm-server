# ADR-0003: Cloudflare Tunnel for public ingress

**Status:** accepted · **Date:** 2026-10-29

## Context

Clients outside the home network must reach the API over HTTPS on `givewgun.com`.
The host is a home PC behind a consumer router (possibly CGNAT).

## Options

1. **Port-forward + reverse proxy (Caddy/Traefik) + Let's Encrypt** — exposes home IP,
   requires router access, breaks under CGNAT, we own DDoS/TLS.
2. **Tailscale Funnel** — simple, but `*.ts.net` hostname only, limited bandwidth, no WAF.
3. **Cloudflare Tunnel** — outbound-only connector, custom domain, TLS + WAF + DDoS at
   the edge, free.
4. **Reverse proxy on the Oracle VM + Tailscale back to the PC** — workable, but adds a hop
   and makes the free VM a bottleneck/single point for traffic.

## Decision

Cloudflare Tunnel (`cloudflared` container), locally-managed: the ingress rules live in
`config/cloudflared/config.yml.tmpl` in git, so the public surface is reviewed code.
Only `^/(v1/.*|health/liveliness)$` is routed; everything else on the hostname is 404.

## Consequences

- No inbound ports, home IP hidden.
- Cloudflare terminates TLS (sees plaintext). Acceptable for this use; sensitive workloads
  should use Tailscale-only access.
- Cloudflare's ~100 s proxy read timeout → clients must stream long generations.
- Setup needs a one-time browser authorisation (`cloudflared tunnel login`).
