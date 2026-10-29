# Security

## Threat model

| Asset | Threat | Control |
|-------|--------|---------|
| Home network / host | Inbound attacks on exposed ports | **No inbound ports.** Cloudflare Tunnel is outbound-only; every service binds to `127.0.0.1` |
| Home IP address | Recon, targeted DDoS | Clients only ever see Cloudflare anycast IPs |
| GPU capacity | Free-riding, abuse, cost-of-electricity DoS | Virtual keys required; per-key RPM / TPM / parallel caps; global upper bounds; optional Cloudflare WAF rate limit |
| Admin functions (key minting, UI) | Takeover via public endpoint | Admin routes are **not routed** publicly (cloudflared path allowlist → 404); admin UI only via Tailscale; master key never leaves the host |
| Prompts / completions | Leakage via logs | `turn_off_message_logging: true` — spend logs keep metadata only. TLS from client to Cloudflare edge; tunnel is encrypted to the edge |
| Secrets | Leakage via git | `.env`, `cert.pem`, tunnel credentials are git-ignored; `llmctl init` generates unique random values per machine |
| Metrics | Leaking usage data | LiteLLM `/metrics` is unauthenticated (key aliases, token counts; no prompts) but only on loopback/tailnet; the tunnel never routes it (public `/metrics` → 404) |
| Backends | Lateral movement inside Docker | vLLM requires its own API key; Postgres has no published port |
| Supply chain | Malicious/changed images | Every image tag pinned; upgrades are explicit diffs |

## Accepted risks / out of scope

- **Cloudflare terminates TLS.** Cloudflare can technically see traffic. Acceptable for a test/hobby API; for sensitive data use Tailscale-only access (Topology B without the tunnel) instead.
- **Single host.** Power or ISP loss = outage (LiteLLM fallback doesn't help when the whole box is down). See [scaling.md](scaling.md) for a cloud fallback.
- **Model output safety.** No content filter is applied. Add LiteLLM guardrails if exposing to untrusted end users.
- **Public API docs** (`/docs`, `docs` profile) document only the routes that are already public, so they reveal nothing new. LiteLLM's own Swagger (737 routes including admin) stays on the tailnet. *Try it out* runs in the visitor's browser with their own key, and `PERSIST_AUTHORIZATION=false` means the key isn't kept after reload.
- **Open WebUI** has its own accounts; signup is enabled with `pending` role so you approve each user. Disable signup entirely once your users exist (`ENABLE_SIGNUP=false`).

## Key handling

- **Master key** (`LITELLM_MASTER_KEY`): admin only, on the host. Rotate by changing `.env` and `./llmctl up` (existing virtual keys keep working; `LITELLM_SALT_KEY` must *not* change — it encrypts stored credentials).
- **Virtual keys**: one per consumer/app, least privilege (`--models`), revoke on leak with `./llmctl key revoke <alias>`. Prefer `--duration` for anything temporary.
- **Tunnel credentials** (`config/cloudflared/<id>.json`): anyone holding it can run the tunnel. Treat like a private key.
- **`cert.pem`**: can create tunnels/DNS records in the zone. Delete it after setup if you don't plan to re-run `tunnel setup`.

## Recommended Cloudflare dashboard settings

Not automatable with the tunnel-scoped login, so do them once by hand:

1. **WAF → Rate limiting rules**: `hostname eq llm.<domain>` → 120 requests / 1 min per IP → Block 1 min.
2. **Security → Bots**: if Bot Fight Mode is on, add a WAF *skip* rule for `llm.<domain>` + `/v1/` (API clients aren't browsers).
3. **SSL/TLS → Edge certificates**: Always Use HTTPS on; minimum TLS 1.2.
4. Optional: **Zero Trust → Access** application on `chat.<domain>` (email OTP) for the web UI.

## Verifying the posture

```bash
./llmctl test public <virtual-key>     # includes "admin UI not public" check
curl -s -o /dev/null -w '%{http_code}\n' https://llm.<domain>/ui/          # 404
curl -s -o /dev/null -w '%{http_code}\n' https://llm.<domain>/key/list     # 404
curl -s -o /dev/null -w '%{http_code}\n' https://llm.<domain>/v1/models    # 401 (no key)
```
