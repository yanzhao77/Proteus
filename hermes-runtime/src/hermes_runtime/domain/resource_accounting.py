from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional, Tuple


class ResourceAccountingRejected(ValueError):
    pass


class ResourceDimension(str, Enum):
    LLM_TOKENS = "llm_tokens"
    LLM_COST_MINOR = "llm_cost_minor"
    AGENT_RUNS = "agent_runs"
    RETRY_COUNT = "retry_count"
    EXECUTION_TIME_MS = "execution_time_ms"
    CPU_TIME_MS = "cpu_time_ms"
    GPU_TIME_MS = "gpu_time_ms"
    DOCKER_RUNTIME_MS = "docker_runtime_ms"
    BROWSER_RUNTIME_MS = "browser_runtime_ms"
    EXTERNAL_API_CALLS = "external_api_calls"
    STORAGE_BYTES = "storage_bytes"
    HUMAN_ATTENTION_REQUESTS = "human_attention_requests"


RESOURCE_UNITS = {
    ResourceDimension.LLM_TOKENS: "token",
    ResourceDimension.LLM_COST_MINOR: "currency_minor_unit",
    ResourceDimension.AGENT_RUNS: "count",
    ResourceDimension.RETRY_COUNT: "count",
    ResourceDimension.EXECUTION_TIME_MS: "millisecond",
    ResourceDimension.CPU_TIME_MS: "millisecond",
    ResourceDimension.GPU_TIME_MS: "millisecond",
    ResourceDimension.DOCKER_RUNTIME_MS: "millisecond",
    ResourceDimension.BROWSER_RUNTIME_MS: "millisecond",
    ResourceDimension.EXTERNAL_API_CALLS: "count",
    ResourceDimension.STORAGE_BYTES: "byte",
    ResourceDimension.HUMAN_ATTENTION_REQUESTS: "count",
}


class ThresholdStatus(str, Enum):
    NORMAL = "NORMAL"
    WARN = "WARN"
    GATE = "GATE"
    HARD_STOP = "HARD_STOP"


@dataclass(frozen=True)
class ThresholdPolicy:
    warn_basis_points: int = 7500
    gate_basis_points: int = 9500
    hard_stop_basis_points: int = 10000

    def validate(self) -> None:
        if not (
            0 <= self.warn_basis_points
            <= self.gate_basis_points
            <= self.hard_stop_basis_points
        ):
            raise ResourceAccountingRejected("RESOURCE_THRESHOLD_INVALID")


@dataclass(frozen=True)
class SettlementPlan:
    consumed: Mapping[str, int]
    released: Mapping[str, int]
    over_limit: Mapping[str, int]


def validate_amounts(amounts: Mapping[str, int]) -> None:
    if not amounts:
        raise ResourceAccountingRejected("RESOURCE_AMOUNT_INVALID")
    for name, amount in amounts.items():
        try:
            ResourceDimension(name)
        except ValueError:
            raise ResourceAccountingRejected("RESOURCE_DIMENSION_UNKNOWN")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise ResourceAccountingRejected("RESOURCE_AMOUNT_INVALID")


def validate_currency(amounts: Mapping[str, int], currency: Optional[str]) -> None:
    if ResourceDimension.LLM_COST_MINOR.value in amounts:
        if not currency or len(currency) != 3 or currency.upper() != currency:
            raise ResourceAccountingRejected("RESOURCE_CURRENCY_MISMATCH")


def available(limit: int, consumed: int, reserved: int) -> int:
    if min(limit, consumed, reserved) < 0:
        raise ResourceAccountingRejected("RESOURCE_AMOUNT_INVALID")
    return max(0, limit - consumed - reserved)


def reservation_is_feasible(
    balances: Mapping[str, Tuple[int, int, int]], amounts: Mapping[str, int]
) -> bool:
    validate_amounts(amounts)
    return all(
        name in balances and amount <= available(*balances[name])
        for name, amount in amounts.items()
    )


def evaluate_threshold(
    balances: Mapping[str, Tuple[int, int, int]], policy: ThresholdPolicy
) -> ThresholdStatus:
    policy.validate()
    highest = 0
    for limit, consumed, reserved in balances.values():
        if min(limit, consumed, reserved) < 0:
            raise ResourceAccountingRejected("RESOURCE_AMOUNT_INVALID")
        used = consumed + reserved
        ratio = 0 if limit == 0 and used == 0 else (
            policy.hard_stop_basis_points if limit == 0 else used * 10000 // limit
        )
        highest = max(highest, ratio)
    if highest >= policy.hard_stop_basis_points:
        return ThresholdStatus.HARD_STOP
    if highest >= policy.gate_basis_points:
        return ThresholdStatus.GATE
    if highest >= policy.warn_basis_points:
        return ThresholdStatus.WARN
    return ThresholdStatus.NORMAL


def plan_settlement(
    reserved: Mapping[str, int], actual: Mapping[str, int]
) -> SettlementPlan:
    validate_amounts(actual)
    for name, amount in reserved.items():
        validate_amounts({name: amount})
    dimensions = set(reserved) | set(actual)
    return SettlementPlan(
        consumed={name: actual.get(name, 0) for name in dimensions},
        released={name: reserved.get(name, 0) for name in dimensions},
        over_limit={
            name: max(0, actual.get(name, 0) - reserved.get(name, 0))
            for name in dimensions
        },
    )
