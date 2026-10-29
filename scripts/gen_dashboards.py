"""Generate the three provisioned Grafana dashboards.

python3 scripts/gen_dashboards.py config/grafana/dashboards
"""
import json
import sys
from pathlib import Path

OUT = Path(sys.argv[1])
DS = {"type": "prometheus", "uid": "prometheus"}
UP_MAP = [{"type": "value", "options": {"0": {"text": "DOWN", "color": "red"}, "1": {"text": "UP", "color": "green"}}}]


class Dash:
    def __init__(self):
        self.panels, self.pid, self.y = [], 0, 0

    def _next(self):
        self.pid += 1
        return self.pid

    def row(self, title):
        self.panels.append({"id": self._next(), "type": "row", "title": title, "collapsed": False,
                            "gridPos": {"x": 0, "y": self.y, "w": 24, "h": 1}})
        self.y += 1

    def panel(self, kind, title, targets, x, w, h, unit="short", desc="", defaults=None, options=None,
              new_line=False):
        p = {"id": self._next(), "type": kind, "title": title, "description": desc, "datasource": DS,
             "gridPos": {"x": x, "y": self.y, "w": w, "h": h},
             "fieldConfig": {"defaults": {"unit": unit, **(defaults or {})}, "overrides": []},
             "targets": [{"datasource": DS, "expr": e, "legendFormat": l, "refId": chr(65 + i),
                          **({"instant": True} if kind in ("bargauge",) else {})}
                         for i, (e, l) in enumerate(targets)]}
        if kind == "stat":
            p["options"] = {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "value",
                            "graphMode": "area", "textMode": "value"}
        if kind == "bargauge":
            p["options"] = {"reduceOptions": {"calcs": ["lastNotNull"]}, "orientation": "horizontal",
                            "displayMode": "gradient", "showUnfilled": True}
        if kind == "timeseries":
            p["options"] = {"legend": {"displayMode": "list", "placement": "bottom"},
                            "tooltip": {"mode": "multi", "sort": "desc"}}
        if options:
            p["options"].update(options)
        self.panels.append(p)
        if x + w >= 24:
            self.y += h

    def dump(self, uid, title, desc, name, variables=()):
        dash = {
            "uid": uid, "title": title, "description": desc, "tags": ["llm"],
            "timezone": "browser", "schemaVersion": 39, "version": 1, "refresh": "10s",
            "time": {"from": "now-1h", "to": "now"}, "panels": self.panels,
            "templating": {"list": list(variables)}, "annotations": {"list": []},
            "links": [{"type": "dashboards", "tags": ["llm"], "asDropdown": False,
                       "title": "LLM dashboards", "includeVars": False, "keepTime": True}],
        }
        (OUT / name).write_text(json.dumps(dash, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"{name}: {len([p for p in self.panels if p['type'] != 'row'])} panels")


def q(p, metric, by="", flt=""):
    return f"histogram_quantile({p}, sum by (le{', ' + by if by else ''}) (rate({metric}_bucket{{{flt}}}[$__rate_interval])))"


THRESH = lambda *steps: {"thresholds": {"mode": "absolute", "steps": [
    {"color": c, "value": v} for v, c in steps]}}

# ------------------------------------------------------------------ engine
d = Dash()
d.row("Overview")
d.panel("stat", "vLLM", [('up{job="vllm"}', "")], 0, 4, 4, defaults={"mappings": UP_MAP})
d.panel("stat", "Tunnel", [('up{job="cloudflared"}', "")], 4, 4, 4, defaults={"mappings": UP_MAP})
d.panel("stat", "Running requests", [("sum(vllm:num_requests_running)", "")], 8, 4, 4,
        desc="Requests currently decoding on the GPU.")
d.panel("stat", "Waiting requests", [("sum(vllm:num_requests_waiting)", "")], 12, 4, 4,
        desc="Requests queued because the batch or KV cache is full. Sustained > 0 means the GPU is saturated.",
        defaults=THRESH((None, "green"), (1, "orange"), (8, "red")))
d.panel("stat", "KV cache used", [("avg(vllm:kv_cache_usage_perc)", "")], 16, 4, 4, "percentunit",
        defaults=THRESH((None, "green"), (0.8, "orange"), (0.95, "red")))
d.panel("stat", "Generation tok/s", [("sum(rate(vllm:generation_tokens_total[1m]))", "")], 20, 4, 4)
d.row("Throughput")
d.panel("timeseries", "Tokens / second", [("sum(rate(vllm:prompt_tokens_total[$__rate_interval]))", "prompt (prefill)"),
                                          ("sum(rate(vllm:generation_tokens_total[$__rate_interval]))", "generation (decode)")], 0, 12, 8)
d.panel("timeseries", "Requests in flight", [("sum(vllm:num_requests_running)", "running"),
                                             ("sum(vllm:num_requests_waiting)", "waiting")], 12, 12, 8)
d.panel("timeseries", "Finished requests / s by reason",
        [("sum by (finished_reason) (rate(vllm:request_success_total[$__rate_interval]))", "{{finished_reason}}")], 0, 12, 8, "reqps",
        desc="stop = model finished; length = hit max_tokens or context limit.")
d.panel("timeseries", "Cache", [("avg(vllm:kv_cache_usage_perc)", "KV cache used"),
                                ("sum(rate(vllm:prefix_cache_hits_total[$__rate_interval])) / sum(rate(vllm:prefix_cache_queries_total[$__rate_interval]))", "prefix cache hit rate")],
        12, 12, 8, "percentunit")
d.row("Latency")
d.panel("timeseries", "Time to first token", [(q(0.5, "vllm:time_to_first_token_seconds"), "p50"), (q(0.95, "vllm:time_to_first_token_seconds"), "p95")], 0, 8, 8, "s")
d.panel("timeseries", "Inter-token latency", [(q(0.5, "vllm:inter_token_latency_seconds"), "p50"), (q(0.95, "vllm:inter_token_latency_seconds"), "p95")], 8, 8, 8, "s")
d.panel("timeseries", "End-to-end request latency", [(q(0.5, "vllm:e2e_request_latency_seconds"), "p50"), (q(0.95, "vllm:e2e_request_latency_seconds"), "p95")], 16, 8, 8, "s")
d.panel("timeseries", "Queue time", [(q(0.95, "vllm:request_queue_time_seconds"), "p95")], 0, 12, 8, "s")
d.panel("timeseries", "Preemptions / s (KV cache pressure)", [("sum(rate(vllm:num_preemptions_total[$__rate_interval]))", "preemptions")], 12, 12, 8)
d.row("Edge (Cloudflare Tunnel)")
d.panel("timeseries", "Tunnel requests / s", [("sum(rate(cloudflared_tunnel_total_requests[$__rate_interval]))", "requests"),
                                              ("sum(rate(cloudflared_tunnel_request_errors[$__rate_interval]))", "errors")], 0, 12, 8, "reqps")
d.panel("timeseries", "Tunnel HA connections", [("sum(cloudflared_tunnel_ha_connections)", "connections")], 12, 12, 8)
d.dump("llm-server", "LLM Engine (vLLM)", "GPU inference engine: throughput, latency, queue, KV cache, tunnel.", "llm-server.json")

# ----------------------------------------------------------------- gateway
K = 'api_key_alias=~"$key"'
R = "litellm_proxy_total_requests_metric_total"
F = "litellm_proxy_failed_requests_metric_total"
key_var = {"name": "key", "label": "API key", "type": "query", "datasource": DS,
           "query": {"query": f"label_values({R}, api_key_alias)", "refId": "keys"},
           "definition": f"label_values({R}, api_key_alias)", "refresh": 2, "includeAll": True,
           "multi": True, "allValue": ".*", "current": {"text": "All", "value": "$__all"}, "sort": 1}
d = Dash()
d.row("Overview")
d.panel("stat", "Requests / min", [(f"sum(rate({R}{{{K}}}[5m])) * 60", "")], 0, 4, 4, defaults={"decimals": 1})
d.panel("stat", "Error rate", [(f"sum(rate({R}{{{K},status_code!~\"2..\"}}[5m])) / sum(rate({R}{{{K}}}[5m]))", "")], 4, 4, 4, "percentunit",
        desc="Share of requests that did not return 2xx (includes 401 from bad keys).",
        defaults=THRESH((None, "green"), (0.01, "orange"), (0.05, "red")))
d.panel("stat", "In flight", [("sum(litellm_in_flight_requests)", "")], 8, 4, 4)
d.panel("stat", "Tokens / min", [(f"sum(rate(litellm_total_tokens_metric_total{{{K}}}[5m])) * 60", "")], 12, 4, 4)
d.panel("stat", "Active keys (24h)", [(f"count(sum by (api_key_alias) (increase({R}{{api_key_alias!=\"None\"}}[24h])) > 0) or vector(0)", "")], 16, 4, 4)
d.panel("stat", "Backend health", [("max by (litellm_model_name) (litellm_deployment_state)", "{{litellm_model_name}}")], 20, 4, 4,
        desc="LiteLLM's view of each backend: healthy, partial outage, or outage (cooled down).",
        defaults={"mappings": [{"type": "value", "options": {"0": {"text": "healthy", "color": "green"},
                                                             "1": {"text": "partial", "color": "orange"},
                                                             "2": {"text": "outage", "color": "red"}}}]},
        options={"textMode": "value_and_name"})
d.row("Traffic")
d.panel("timeseries", "Requests / s by key", [(f"sum by (api_key_alias) (rate({R}{{{K}}}[$__rate_interval]))", "{{api_key_alias}}")], 0, 12, 8, "reqps",
        desc="'None' = requests without a valid key.")
d.panel("timeseries", "Requests / s by status", [(f"sum by (status_code) (rate({R}{{{K}}}[$__rate_interval]))", "{{status_code}}")], 12, 12, 8, "reqps")
d.panel("timeseries", "Tokens / s by key", [(f"sum by (api_key_alias) (rate(litellm_input_tokens_metric_total{{{K}}}[$__rate_interval]))", "{{api_key_alias}} in"),
                                            (f"sum by (api_key_alias) (rate(litellm_output_tokens_metric_total{{{K}}}[$__rate_interval]))", "{{api_key_alias}} out")], 0, 12, 8)
d.panel("timeseries", "Requests / s by model", [(f"sum by (requested_model) (rate({R}{{{K}}}[$__rate_interval]))", "{{requested_model}}"),
                                                (f"sum by (litellm_model_name) (rate(litellm_deployment_total_requests_total{{{K}}}[$__rate_interval]))", "served by {{litellm_model_name}}")],
        12, 12, 8, "reqps", desc="What clients asked for vs. which backend actually served it.")
d.row("Usage over the selected range")
d.panel("bargauge", "Requests by key", [(f"sort_desc(sum by (api_key_alias) (increase({R}{{{K}}}[$__range])))", "{{api_key_alias}}")], 0, 8, 8, defaults={"decimals": 0})
d.panel("bargauge", "Tokens by key", [(f"sort_desc(sum by (api_key_alias) (increase(litellm_total_tokens_metric_total{{{K}}}[$__range])))", "{{api_key_alias}}")], 8, 8, 8, defaults={"decimals": 0})
d.panel("bargauge", "Failures by reason", [(f"sort_desc(sum by (exception_status, exception_class) (increase({F}{{{K}}}[$__range])))", "{{exception_status}} {{exception_class}}")], 16, 8, 8,
        defaults={"decimals": 0, "color": {"mode": "fixed", "fixedColor": "red"}})
d.row("Latency")
d.panel("timeseries", "Total latency by model", [(q(0.5, "litellm_request_total_latency_metric", "requested_model", K), "p50 {{requested_model}}"),
                                                 (q(0.95, "litellm_request_total_latency_metric", "requested_model", K), "p95 {{requested_model}}")], 0, 8, 8, "s",
        desc="Client-observed time inside the gateway, request in to last byte out.")
d.panel("timeseries", "Backend (LLM) latency", [(q(0.95, "litellm_llm_api_latency_metric", "model", K), "p95 {{model}}")], 8, 8, 8, "s")
d.panel("timeseries", "Gateway overhead", [(q(0.95, "litellm_overhead_latency_metric", "", ""), "p95")], 16, 8, 8, "s",
        desc="Time LiteLLM itself adds (auth, routing, logging).")
d.row("Resilience")
d.panel("timeseries", "Fallbacks / s", [("sum(rate(litellm_deployment_successful_fallbacks_total[$__rate_interval])) or vector(0)", "successful"),
                                        ("sum(rate(litellm_deployment_failed_fallbacks_total[$__rate_interval])) or vector(0)", "failed")], 0, 12, 8, "reqps",
        desc="local-chat served by local-chat-small because vLLM was unavailable.")
d.panel("timeseries", "Rate-limit usage by key", [("max by (api_key_alias, rate_limit_type) (litellm_api_key_rate_limit_used_metric{api_key_alias=~\"$key\"} / litellm_api_key_rate_limit_allowed_metric{api_key_alias=~\"$key\"})", "{{api_key_alias}} {{rate_limit_type}}")],
        12, 12, 8, "percentunit", desc="Share of each key's per-minute request/token limit used. At 100% the key gets 429s.",
        defaults={"max": 1, **THRESH((None, "green"), (0.8, "orange"), (1, "red"))})
d.dump("llm-gateway", "LLM Gateway (LiteLLM)", "API gateway: who is calling, how much, how fast, what fails.", "llm-gateway.json", [key_var])

# --------------------------------------------------------------------- gpu
G = 'nvidia_smi'
d = Dash()
d.row("Now")
d.panel("stat", "GPU utilisation", [(f"avg({G}_utilization_gpu_ratio)", "")], 0, 4, 4, "percentunit")
d.panel("stat", "VRAM used", [(f"sum({G}_memory_used_bytes) / sum({G}_memory_total_bytes)", "")], 4, 4, 4, "percentunit",
        defaults=THRESH((None, "green"), (0.85, "orange"), (0.95, "red")))
d.panel("stat", "VRAM free", [(f"sum({G}_memory_total_bytes) - sum({G}_memory_used_bytes)", "")], 8, 4, 4, "bytes",
        desc="Headroom for games / Ollama GPU models while vLLM is running.")
d.panel("stat", "Temperature", [(f"max({G}_temperature_gpu)", "")], 12, 4, 4, "celsius",
        defaults=THRESH((None, "green"), (75, "orange"), (85, "red")))
d.panel("stat", "Power draw", [(f"sum({G}_power_draw_watts)", "")], 16, 4, 4, "watt")
d.panel("stat", "GPU exporter", [('up{job="gpu"}', "")], 20, 4, 4, defaults={"mappings": UP_MAP})
d.row("Over time")
d.panel("timeseries", "Utilisation vs running requests", [(f"avg({G}_utilization_gpu_ratio)", "GPU utilisation"),
                                                          ("sum(vllm:num_requests_running) / 16", "vLLM running requests (÷ max-num-seqs 16)")],
        0, 12, 8, "percentunit", desc="Spikes in utilisation that don't match running requests come from something else on the PC (a game, Ollama).")
d.panel("timeseries", "VRAM", [(f"sum({G}_memory_used_bytes)", "used"), (f"sum({G}_memory_total_bytes)", "total")], 12, 12, 8, "bytes")
d.panel("timeseries", "Temperature", [(f"max({G}_temperature_gpu)", "GPU")], 0, 8, 8, "celsius")
d.panel("timeseries", "Power draw", [(f"sum({G}_power_draw_watts)", "draw")], 8, 8, 8, "watt")
d.panel("timeseries", "Graphics clock", [(f"max({G}_clocks_current_graphics_clock_hz)", "graphics")], 16, 8, 8, "hertz")
d.dump("llm-gpu", "GPU", "GPU hardware: utilisation, VRAM, temperature, power (nvidia-smi exporter).", "llm-gpu.json")
