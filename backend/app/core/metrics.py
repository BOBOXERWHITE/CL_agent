from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest


HTTP_REQUESTS_TOTAL = Counter(
    "travel_ops_http_requests_total",
    "Total HTTP requests handled by the API.",
    ["method", "path", "status_code"],
)
HTTP_REQUEST_LATENCY_MS = Histogram(
    "travel_ops_http_request_latency_ms",
    "HTTP request latency in milliseconds.",
    ["method", "path"],
    buckets=(5, 10, 25, 50, 100, 250, 500, 1000, 3000, 8000, 15000),
)
LLM_TOKENS_TOTAL = Counter(
    "travel_ops_llm_tokens_total",
    "Token usage grouped by model and direction.",
    ["model_name", "direction"],
)
AGENT_RUNS_TOTAL = Counter(
    "travel_ops_agent_runs_total",
    "Agent runs grouped by agent and final status.",
    ["agent_name", "status"],
)
EVAL_RUNS_TOTAL = Counter(
    "travel_ops_eval_runs_total",
    "Evaluation runs grouped by dataset and status.",
    ["dataset_name", "status"],
)


def observe_request(method: str, path: str, status_code: int, latency_ms: int) -> None:
    HTTP_REQUESTS_TOTAL.labels(method=method, path=path, status_code=str(status_code)).inc()
    HTTP_REQUEST_LATENCY_MS.labels(method=method, path=path).observe(latency_ms)


def observe_token_usage(model_name: str | None, token_usage: dict[str, int] | None) -> None:
    if not model_name or not token_usage:
        return

    input_tokens = int(token_usage.get("input_tokens", 0))
    output_tokens = int(token_usage.get("output_tokens", 0))
    if input_tokens > 0:
        LLM_TOKENS_TOTAL.labels(model_name=model_name, direction="input").inc(input_tokens)
    if output_tokens > 0:
        LLM_TOKENS_TOTAL.labels(model_name=model_name, direction="output").inc(output_tokens)


def observe_agent_run(agent_name: str, status: str) -> None:
    AGENT_RUNS_TOTAL.labels(agent_name=agent_name, status=status).inc()


def observe_eval_run(dataset_name: str, status: str) -> None:
    EVAL_RUNS_TOTAL.labels(dataset_name=dataset_name, status=status).inc()


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
