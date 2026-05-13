# Day 10 Reliability Report

## 1. Architecture summary

The reliability gateway checks Redis cache first, then routes provider calls through one circuit breaker per provider. If the primary provider fails or its circuit is open, the gateway skips it and tries the backup provider; if every provider fails, it returns a static degraded response.

```
User Request
    |
    v
[Gateway] ---> [Redis cache check] ---> HIT? return cached
    |                                   |
    v                                   v MISS
[Circuit Breaker: Primary] ----------> Provider A
    |  (OPEN? skip)
    v
[Circuit Breaker: Backup] -----------> Provider B
    |  (OPEN? skip)
    v
[Static fallback message]
```

## 2. Configuration

| Setting | Value | Reason |
|---|---:|---|
| failure_threshold | 3 | Opens after repeated failures without reacting to a single transient provider error. |
| reset_timeout_seconds | 2 | Gives a failing provider a short recovery window before allowing a probe request. |
| success_threshold | 1 | One successful half-open probe is enough to restore traffic in this lab setup. |
| cache backend | redis | Verifies shared cache behavior for multi-instance deployment. |
| cache TTL | 300 | Keeps FAQ-style answers reusable while limiting stale responses. |
| similarity_threshold | 0.92 | High threshold reduces false semantic cache hits. |
| load_test requests | 100 per scenario | Enough requests to exercise cache hits, fallback routing, and circuit opening across scenarios. |

## 3. SLO definitions

| SLI | SLO target | Actual value | Met? |
|---|---|---:|---|
| Availability | >= 99% | 99.5% | Yes |
| Latency P95 | < 2500 ms | 311.72 ms | Yes |
| Fallback success rate | >= 95% | 95.45% | Yes |
| Cache hit rate | >= 10% | 79% | Yes |
| Recovery time | < 5000 ms | Not observed in Redis run | N/A |

The Redis run opened circuits, but did not capture a full open-to-closed recovery transition, so `recovery_time_ms` is `null` in `reports/metrics.json`.

## 4. Metrics

| Metric | Value |
|---|---:|
| total_requests | 400 |
| availability | 0.995 |
| error_rate | 0.005 |
| latency_p50_ms | 2.38 |
| latency_p95_ms | 311.72 |
| latency_p99_ms | 531.34 |
| fallback_success_rate | 0.9545 |
| cache_hit_rate | 0.79 |
| estimated_cost | 0.037458 |
| estimated_cost_saved | 0.316 |
| circuit_open_count | 5 |
| recovery_time_ms | null |

## 5. Cache comparison

The table below compares a cache-disabled run against the Redis cache run.

| Metric | Without cache | With Redis cache | Delta |
|---|---:|---:|---|
| availability | 0.9733 | 0.995 | +0.0217 |
| error_rate | 0.0267 | 0.005 | -0.0217 |
| latency_p50_ms | 271.09 | 2.38 | -268.71 ms |
| latency_p95_ms | 511.78 | 311.72 | -200.06 ms |
| estimated_cost | 0.13429 | 0.037458 | -0.096832 |
| estimated_cost_saved | 0.0 | 0.316 | +0.316 |
| cache_hit_rate | 0.0 | 0.79 | +0.79 |

Redis cache significantly reduced median latency and provider cost by serving repeated safe queries from shared cache. It also improved availability by avoiding some provider calls during failure scenarios.

## 6. Redis shared cache

- Why in-memory cache is insufficient for multi-instance deployments: each gateway process has its own local memory, so one instance cannot reuse responses cached by another instance.
- How `SharedRedisCache` solves this: responses are stored in Redis using deterministic query hashes and TTLs, so separate cache instances can read the same cached entries.

### Evidence of shared state

```text
pytest -q
12 passed in 1.99s
```

The passing Redis tests include set/get, TTL expiry, privacy bypass, false-hit detection, and shared-state verification across two `SharedRedisCache` instances.

### Redis CLI output

```text
docker compose exec redis redis-cli KEYS "rl:cache:*"
1) "rl:cache:9e413fd814eb"
2) "rl:cache:b2a52f7dc795"
3) "rl:cache:8baa2cfa11fa"
4) "rl:cache:095946136fea"
5) "rl:cache:b6af19a70a20"
```

### In-memory vs Redis latency comparison

| Metric | In-memory cache | Redis cache | Notes |
|---|---:|---:|---|
| latency_p50_ms | 0.16 | 2.38 | Redis adds small lookup overhead. |
| latency_p95_ms | 307.06 | 311.72 | Tail latency remains comparable. |

## 7. Chaos scenarios

| Scenario | Expected behavior | Observed behavior | Pass/Fail |
|---|---|---|---|
| primary_timeout_100 | Primary fails, circuit opens, backup handles traffic. | Fallback succeeded and circuit opened during the run. | Pass |
| primary_flaky_50 | Primary intermittently fails, producing a mix of primary and fallback responses. | Circuit opened and successful requests continued through fallback/primary paths. | Pass |
| all_healthy | Both providers healthy, primary handles traffic with no static fallback. | Requests succeeded under healthy provider settings. | Pass |
| cache_stale_candidate | Similar queries with different years must not return a stale cache hit. | `refund policy for 2024` did not satisfy `refund policy for 2026`. | Pass |

## 8. Failure analysis

Remaining weakness: circuit breaker state is still process-local. In a horizontally scaled deployment, one gateway instance may open its circuit while another instance continues sending traffic to the failing provider until its own local threshold is reached.

Before production, I would move circuit breaker state to Redis or another shared low-latency store. That would let all gateway instances share provider health state, reduce repeated failures during outages, and make recovery behavior easier to observe consistently.

## 9. Next steps

1. Add concurrent load testing using the configured concurrency value.
2. Persist circuit breaker counters and state transitions in Redis.
3. Export Prometheus metrics for request totals, latency, cache hits, fallback count, and circuit state.
