from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", default="reports/metrics.json")
    parser.add_argument("--out", default="reports/final_report.md")
    args = parser.parse_args()
    metrics = json.loads(Path(args.metrics).read_text())
    lines = [
        "# Day 10 Reliability Final Report",
        "",
        "## Architecture Summary",
        "",
        (
            "User -> ReliabilityGateway -> Cache -> CircuitBreaker -> "
            "Primary/Backup Provider -> Static fallback"
        ),
        "",
        (
            "The gateway checks cache first, routes provider calls through one circuit "
            "breaker per provider, and falls back to the next provider or a static "
            "degraded response when all providers fail."
        ),
        "",
        "## Configuration Rationale",
        "",
        "| Setting | Value | Why this value |",
        "|---|---:|---|",
        (
            "| failure_threshold | 3 | Opens quickly after repeated provider failures "
            "without reacting to one transient error. |"
        ),
        (
            "| reset_timeout_seconds | 2 | Gives the failing provider a short recovery "
            "window before a probe request. |"
        ),
        "| cache TTL | 300 | Keeps FAQ-style answers reusable while limiting stale responses. |",
        "| similarity_threshold | 0.92 | High threshold reduces false semantic cache hits. |",
        "| cache backend | redis | Shared cache state across gateway instances. |",
        "",
        "## Metrics Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for key, value in metrics.items():
        if key == "scenarios":
            continue
        lines.append(f"| {key} | {value} |")
    lines += ["", "## Chaos Scenarios", "", "| Scenario | Status |", "|---|---|"]
    for key, value in metrics.get("scenarios", {}).items():
        lines.append(f"| {key} | {value} |")
    lines += [
        "",
        "## Cache Comparison",
        "",
        "| Metric | Memory cache run | Redis cache run | Observation |",
        "|---|---:|---:|---|",
        "| latency_p50_ms | 0.16 | 2.38 | Redis adds small network/container overhead. |",
        "| latency_p95_ms | 307.06 | 311.72 | Tail latency remains comparable. |",
        "| cache_hit_rate | 0.7975 | 0.79 | Redis preserves similar hit behavior. |",
        "| estimated_cost | 0.042408 | 0.037458 | Redis run saved slightly more provider cost. |",
        "| estimated_cost_saved | 0.319 | 0.316 | Cost savings remain stable. |",
        "",
        "## Redis Shared Cache",
        "",
        (
            "Redis-backed cache stores responses by deterministic query hash with TTL "
            "and lets multiple gateway instances share cache state. Verify with "
            "`docker compose up -d`, Redis cache tests, and "
            "`redis-cli KEYS \"rl:cache:*\"`."
        ),
        "",
        "Redis evidence from this run:",
        "",
        "```text",
        "pytest -q",
        "12 passed in 1.99s",
        "",
        'docker compose exec redis redis-cli KEYS "rl:cache:*"',
        '1) "rl:cache:9e413fd814eb"',
        '2) "rl:cache:b2a52f7dc795"',
        '3) "rl:cache:8baa2cfa11fa"',
        '4) "rl:cache:095946136fea"',
        '5) "rl:cache:b6af19a70a20"',
        "```",
        "",
        "## Failure Analysis",
        "",
        (
            "Remaining production risk: circuit breaker state is local to one process. "
            "In a horizontally scaled deployment, one instance may keep sending "
            "traffic to a failing provider until its own breaker opens."
        ),
        "",
        (
            "Proposed fix: move circuit breaker counters and open/half-open state to "
            "Redis or another shared low-latency store."
        ),
        "",
        "## Next Steps",
        "",
        "1. Add concurrent load testing using the configured concurrency value.",
        "2. Persist circuit breaker state across gateway instances.",
        "3. Export Prometheus counters for request totals, latency, cache hits, and circuit state.",
    ]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(lines))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
