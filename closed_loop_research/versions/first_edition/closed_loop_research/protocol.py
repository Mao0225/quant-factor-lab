"""All research decisions are explicit and included in the protocol identity."""
from dataclasses import dataclass, asdict, fields
from datetime import date
import math

from .storage import digest

METHOD_VERSION = "v0.4-kernel-1"
OPERATOR_VERSION = "prefix-causal-1"
EXECUTION_VERSION = "raw-cash-open-1"


@dataclass(frozen=True)
class Protocol:
    name: str
    synthetic: bool
    seed: int
    segments: tuple
    fields: tuple
    windows: tuple
    constants: tuple
    max_tokens: int
    max_factors: int
    top_k: int
    initial_cash: float
    lot_size: int
    buy_fee: float
    sell_fee: float
    minimum_fee: float
    slippage: float
    annual_days: int
    risk_lambda: float
    beta: float
    tau: float
    delta: float
    min_daily_coverage: float
    max_low_coverage_fraction: float
    max_degenerate_fraction: float
    epsilon: float
    search_budget: int
    perturbations: tuple
    restart_after: int
    batches: int
    episodes_per_batch: int
    selection_batches: tuple
    max_backtests: int
    wall_seconds: float | None
    ic_horizon: int
    reward_mode: str
    generator: str
    search_mode: str
    ppo_epochs: int
    learning_rate: float
    clip_ratio: float
    value_coefficient: float
    entropy_coefficient: float
    initial_expressions: tuple
    initial_weights: tuple
    universe_note: str
    execution_note: str
    data_mode: str = "audited"

    @classmethod
    def from_dict(cls, raw):
        raw = {"data_mode": "audited", **raw}
        names = {f.name for f in fields(cls)}
        if set(raw) != names:
            raise ValueError(f"protocol keys: missing={sorted(names-set(raw))}, unknown={sorted(set(raw)-names)}")
        raw = dict(raw)
        segments = raw["segments"]
        if set(segments) != {"F", "E", "V", "T"}:
            raise ValueError("require F/E/V/T")
        raw["segments"] = tuple((s, *segments[s]) for s in "FEVT")
        for key in ["fields", "windows", "constants", "perturbations", "selection_batches",
                    "initial_expressions", "initial_weights"]:
            raw[key] = tuple(raw[key])
        result = cls(**raw)
        result.validate()
        return result

    def validate(self):
        if self.data_mode not in {"audited", "legacy_prototype"}:
            raise ValueError("unknown data mode")
        last = None
        for s, start, end in self.segments:
            a, b = date.fromisoformat(start), date.fromisoformat(end)
            if a > b or (last and a <= last):
                raise ValueError("segments must be ordered, disjoint F < E < V < T")
            last = b
        positive_ints = ["max_tokens", "max_factors", "top_k", "lot_size", "annual_days",
                         "search_budget", "restart_after", "batches", "episodes_per_batch",
                         "max_backtests", "ic_horizon", "ppo_epochs"]
        for name in positive_ints:
            v = getattr(self, name)
            if type(v) is not int or v <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for name in ["initial_cash", "tau", "epsilon", "learning_rate", "clip_ratio"]:
            v = getattr(self, name)
            if not math.isfinite(v) or v <= 0:
                raise ValueError(f"invalid {name}")
        for name in ["buy_fee", "sell_fee", "minimum_fee", "slippage", "risk_lambda", "beta",
                     "delta", "value_coefficient", "entropy_coefficient"]:
            v = getattr(self, name)
            if not math.isfinite(v) or v < 0:
                raise ValueError(f"invalid {name}")
        for name in ["min_daily_coverage", "max_low_coverage_fraction", "max_degenerate_fraction"]:
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"invalid {name}")
        if self.slippage >= 1 or self.sell_fee >= 1 or self.clip_ratio >= 1:
            raise ValueError("rates must be < 1")
        if not self.fields or len(set(self.fields)) != len(self.fields) or any(not x.isidentifier() for x in self.fields):
            raise ValueError("fields must be unique identifiers")
        if not self.windows or any(type(w) is not int or w <= 0 for w in self.windows):
            raise ValueError("windows must be positive integers")
        if not self.constants or any(not math.isfinite(c) for c in self.constants):
            raise ValueError("constants must be finite")
        if not self.perturbations or any(not math.isfinite(x) or x <= 0 for x in self.perturbations):
            raise ValueError("invalid perturbations")
        if not self.selection_batches or tuple(sorted(set(self.selection_batches))) != self.selection_batches:
            raise ValueError("selection checkpoints must be unique and increasing")
        if any(type(b) is not int or not 1 <= b <= self.batches for b in self.selection_batches):
            raise ValueError("selection outside registered batches")
        if self.wall_seconds is not None and (not math.isfinite(self.wall_seconds) or self.wall_seconds <= 0):
            raise ValueError("invalid wall budget")
        if self.generator not in {"ppo", "random", "fixed"}:
            raise ValueError("unknown generator")
        if self.reward_mode not in {"trade_delta", "single_ic", "combo_ic", "absolute_trade"}:
            raise ValueError("unknown reward")
        if self.search_mode not in {"adaptive", "fixed"}:
            raise ValueError("unknown search mode")
        if not self.initial_expressions or len(self.initial_expressions) != len(self.initial_weights):
            raise ValueError("invalid initialization")
        if len(self.initial_expressions) > self.max_factors or len(set(self.initial_expressions)) != len(self.initial_expressions):
            raise ValueError("initial pool invalid")
        if any(not math.isfinite(w) or w == 0 for w in self.initial_weights) or not math.isclose(sum(abs(w) for w in self.initial_weights), 1.):
            raise ValueError("initial weights must be finite, active and L1=1")
        if not self.universe_note or not self.execution_note:
            raise ValueError("data/execution assumptions required")

    def bounds(self, segment):
        return next((a, b) for s, a, b in self.segments if s == segment)

    def to_dict(self):
        raw = asdict(self)
        raw["segments"] = {s: [a, b] for s, a, b in self.segments}
        return raw

    @property
    def digest(self):
        return digest({"protocol": self.to_dict(), "method": METHOD_VERSION,
                       "operators": OPERATOR_VERSION, "execution": EXECUTION_VERSION})

    @property
    def warmup(self):
        return self.max_tokens * max(self.windows) + 1

    @property
    def data_digest(self):
        return digest({"segments": self.segments, "fields": self.fields, "warmup": self.warmup,
                       "synthetic": self.synthetic, "mode": self.data_mode,
                       "universe": self.universe_note, "execution": self.execution_note})
