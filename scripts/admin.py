"""Gateway admin helper.

Runs *inside* the litellm container (piped over stdin by ./llmctl) so the host
needs nothing but Docker and bash. Talks to LiteLLM on localhost with the
master key from the container environment.

    python3 - <command> [args...] < scripts/admin.py
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "http://localhost:4000"
MASTER = os.environ["LITELLM_MASTER_KEY"]


def call(method, path, body=None, key=MASTER, base=BASE, stream=False, timeout=120):
    req = urllib.request.Request(
        base + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        # Cloudflare's browser integrity check rejects the default Python-urllib UA.
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": "llmctl/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            return r.status, raw if stream else (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        return 0, str(e)


def parse_flags(args):
    flags, rest = {}, []
    it = iter(args)
    for a in it:
        if a.startswith("--"):
            flags[a[2:]] = next(it)
        else:
            rest.append(a)
    return flags, rest


def key_create(args):
    flags, rest = parse_flags(args)
    if not rest:
        sys.exit("usage: key create <alias> [--models m1,m2] [--rpm N] [--tpm N] "
                 "[--parallel N] [--budget USD] [--duration 30d]")
    body = {"key_alias": rest[0], "metadata": {"created_by": "llmctl"}}
    if "models" in flags:
        body["models"] = flags["models"].split(",")
    for flag, field, cast in [("rpm", "rpm_limit", int), ("tpm", "tpm_limit", int),
                              ("parallel", "max_parallel_requests", int),
                              ("budget", "max_budget", float), ("duration", "duration", str)]:
        if flag in flags:
            body[field] = cast(flags[flag])
    status, res = call("POST", "/key/generate", body)
    if status != 200:
        sys.exit(f"key create failed ({status}): {res}")
    print(json.dumps({k: res.get(k) for k in
                      ("key", "key_alias", "models", "rpm_limit", "tpm_limit",
                       "max_parallel_requests", "max_budget", "expires")}, indent=2))


def key_list(_args):
    status, res = call("GET", "/key/list?return_full_object=true&size=100")
    if status != 200:
        sys.exit(f"key list failed ({status}): {res}")
    rows = [("ALIAS", "KEY", "MODELS", "RPM", "TPM", "SPEND", "EXPIRES")]
    for k in res.get("keys", []):
        rows.append((k.get("key_alias") or "-", k.get("key_name") or "-",
                     ",".join(k.get("models") or []) or "all",
                     str(k.get("rpm_limit")), str(k.get("tpm_limit")),
                     f"{k.get('spend') or 0:.4f}", str(k.get("expires") or "never")))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)))


def key_revoke(args):
    if not args:
        sys.exit("usage: key revoke <alias>")
    status, res = call("POST", "/key/delete", {"key_aliases": args})
    if status != 200:
        sys.exit(f"key revoke failed ({status}): {res}")
    print(f"revoked: {', '.join(args)}")


def wait(args):
    deadline = time.time() + int(args[0] if args else 900)
    while time.time() < deadline:
        status, res = call("GET", "/health/readiness")
        if status == 200:
            status, res = call("GET", "/v1/models")
            if status == 200:
                print("gateway ready:", ", ".join(m["id"] for m in res["data"]))
                return
        time.sleep(5)
    sys.exit("timed out waiting for gateway")


def smoke(args):
    """End-to-end test: auth, model list, completion, streaming.

    smoke [base_url] [api_key] [model] — defaults to the local gateway + master key.
    """
    base = args[0].rstrip("/") if len(args) > 0 else BASE
    key = args[1] if len(args) > 1 else MASTER
    model = args[2] if len(args) > 2 else "local-chat"
    failures = 0

    def check(name, ok, detail=""):
        nonlocal failures
        failures += 0 if ok else 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}{'  ' + detail if detail else ''}")

    print(f"smoke test -> {base}  model={model}")
    status, _ = call("GET", "/health/liveliness", base=base, key="")
    check("liveness", status == 200, f"HTTP {status}")

    status, _ = call("GET", "/v1/models", base=base, key="sk-invalid")
    check("rejects bad key", status in (401, 403), f"HTTP {status}")

    status, res = call("GET", "/v1/models", base=base, key=key)
    ids = [m["id"] for m in res["data"]] if status == 200 else []
    check("lists models", model in ids, ", ".join(ids) or str(res)[:200])

    t0 = time.time()
    status, res = call("POST", "/v1/chat/completions", base=base, key=key, body={
        "model": model, "max_tokens": 32, "temperature": 0,
        "messages": [{"role": "user", "content": "Reply with exactly: pong"}]})
    ok = status == 200 and "pong" in res["choices"][0]["message"]["content"].lower()
    detail = (f"{time.time() - t0:.2f}s  -> {res['choices'][0]['message']['content']!r}"
              if status == 200 else f"HTTP {status} {str(res)[:200]}")
    check("chat completion", ok, detail)

    t0 = time.time()
    status, raw = call("POST", "/v1/chat/completions", base=base, key=key, stream=True, body={
        "model": model, "max_tokens": 64, "stream": True,
        "messages": [{"role": "user", "content": "Count from 1 to 10."}]})
    chunks = raw.count("data: ") if status == 200 else 0
    check("streaming", status == 200 and chunks > 3 and "[DONE]" in raw,
          f"{chunks} chunks in {time.time() - t0:.2f}s")

    if base == BASE:
        status, _ = call("GET", "/key/list", base=base, key="sk-invalid")
        check("admin routes need master key", status in (401, 403), f"HTTP {status}")
    else:
        status, _ = call("GET", "/ui/", base=base, key=key)
        check("admin UI not public", status == 404, f"HTTP {status}")

    print("OK" if failures == 0 else f"{failures} check(s) failed")
    sys.exit(1 if failures else 0)


def ollama_unload(_args):
    """Evict every model Ollama holds in VRAM so vLLM can claim its share.

    vLLM sizes its KV cache from free VRAM at startup; resident Ollama models
    make that budget negative and the engine refuses to start.
    """
    status, res = call("GET", "/api/ps", base=OLLAMA, key="", timeout=5)
    if status != 200:
        print(f"ollama not reachable at {OLLAMA}; nothing to unload")
        return
    for m in res.get("models", []):
        if m.get("size_vram", 0) > 0:
            call("POST", "/api/generate", {"model": m["name"], "keep_alive": 0}, base=OLLAMA, key="")
            print(f"unloaded ollama model {m['name']} ({m['size_vram'] / 2**30:.1f} GiB VRAM)")


def ollama_prepare(_args):
    """Ensure the fallback model exists as a CPU-only variant.

    local-chat-small must never compete with vLLM for VRAM, otherwise a
    fallback during a model swap starves the engine that is starting up.
    """
    status, res = call("GET", "/api/tags", base=OLLAMA, key="", timeout=5)
    if status != 200:
        print(f"ollama not reachable at {OLLAMA}; skipping fallback model setup")
        return
    have = {m["name"] for m in res.get("models", [])}
    if FALLBACK_CPU in have:
        return
    if FALLBACK_BASE not in have:
        print(f"pulling {FALLBACK_BASE} (~2 GB)...")
        status, res = call("POST", "/api/pull", {"model": FALLBACK_BASE, "stream": False},
                           base=OLLAMA, key="", timeout=1800)
        if status != 200:
            sys.exit(f"ollama pull failed ({status}): {res}")
    status, res = call("POST", "/api/create", {"model": FALLBACK_CPU, "from": FALLBACK_BASE,
                                               "parameters": {"num_gpu": 0}, "stream": False},
                       base=OLLAMA, key="")
    if status != 200:
        sys.exit(f"ollama create failed ({status}): {res}")
    print(f"created CPU-only fallback model {FALLBACK_CPU}")


OLLAMA = os.environ.get("OLLAMA_API_BASE", "http://host.docker.internal:11434")
FALLBACK_BASE, FALLBACK_CPU = "llama3.2:3b", "llama3.2:3b-cpu"

COMMANDS = {"key-create": key_create, "key-list": key_list, "key-revoke": key_revoke,
            "wait": wait, "smoke": smoke, "ollama-unload": ollama_unload,
            "ollama-prepare": ollama_prepare}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit(f"commands: {', '.join(COMMANDS)}")
    COMMANDS[sys.argv[1]](sys.argv[2:])
