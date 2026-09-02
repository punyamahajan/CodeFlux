from prometheus_client import Counter, Gauge, Histogram

REQUESTS = Counter("codeflux_requests_total", "Gateway requests", ["route", "provider", "status"])
LATENCY = Histogram("codeflux_provider_latency_seconds", "Provider latency", ["provider"])
FAILOVERS = Counter("codeflux_failovers_total", "Provider failover attempts", ["provider", "reason"])
CIRCUITS = Gauge("codeflux_circuit_open", "Circuit state (1=open)", ["identity"])
TOKENS = Counter("codeflux_tokens_total", "Processed tokens", ["provider", "kind", "key_ref"])

