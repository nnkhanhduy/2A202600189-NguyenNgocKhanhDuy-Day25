from __future__ import annotations

import time
from dataclasses import dataclass

from reliability_lab.cache import ResponseCache, SharedRedisCache
from reliability_lab.circuit_breaker import CircuitBreaker, CircuitOpenError
from reliability_lab.providers import FakeLLMProvider, ProviderError, ProviderResponse


@dataclass(slots=True)
class GatewayResponse:
    text: str
    route: str
    provider: str | None
    cache_hit: bool
    latency_ms: float
    estimated_cost: float
    error: str | None = None
    route_reason: str | None = None


class ReliabilityGateway:
    """Routes requests through cache, circuit breakers, and fallback providers."""

    def __init__(
        self,
        providers: list[FakeLLMProvider],
        breakers: dict[str, CircuitBreaker],
        cache: ResponseCache | SharedRedisCache | None = None,
    ) -> None:
        self.providers = providers
        self.breakers = breakers
        self.cache = cache

    def complete(self, prompt: str) -> GatewayResponse:
        """Return a reliable response or a static fallback."""
        start = time.perf_counter()
        if self.cache is not None:
            cached, score = self._cache_get(prompt)
            if cached is not None:
                return GatewayResponse(
                    cached,
                    "cache_hit",
                    None,
                    True,
                    self._elapsed_ms(start),
                    0.0,
                    route_reason=f"cache_hit:{score:.2f}",
                )

        last_error: str | None = None
        for idx, provider in enumerate(self.providers):
            breaker = self.breakers[provider.name]
            try:
                response: ProviderResponse = breaker.call(provider.complete, prompt)
                if self.cache is not None:
                    self._cache_set(prompt, response.text, {"provider": provider.name})
                route_type = "primary" if idx == 0 else "fallback"
                return GatewayResponse(
                    text=response.text,
                    route=route_type,
                    provider=provider.name,
                    cache_hit=False,
                    latency_ms=self._elapsed_ms(start),
                    estimated_cost=response.estimated_cost,
                    route_reason=f"{route_type}:{provider.name}",
                )
            except (ProviderError, CircuitOpenError) as exc:
                last_error = str(exc)
                continue

        return GatewayResponse(
            text="The service is temporarily degraded. Please try again soon.",
            route="static_fallback",
            provider=None,
            cache_hit=False,
            latency_ms=self._elapsed_ms(start),
            estimated_cost=0.0,
            error=last_error,
            route_reason=f"static_fallback:{last_error}" if last_error else "static_fallback",
        )

    @staticmethod
    def _elapsed_ms(start: float) -> float:
        return (time.perf_counter() - start) * 1000

    def _cache_get(self, prompt: str) -> tuple[str | None, float]:
        try:
            return self.cache.get(prompt) if self.cache is not None else (None, 0.0)
        except Exception:
            return None, 0.0

    def _cache_set(self, prompt: str, text: str, metadata: dict[str, str]) -> None:
        try:
            if self.cache is not None:
                self.cache.set(prompt, text, metadata)
        except Exception:
            return
