"""Public configuration. Scores are heuristics, not calibrated probabilities."""

from dataclasses import asdict, dataclass, field
import math


@dataclass
class AnalysisConfig:
    random_seed: int = 42
    max_depth: int = 4
    temporal_window_days: int = 2
    betweenness_samples: int = 256
    community_resolution: float = 1.0
    model: str = "auto"
    ae_max_epochs: int = 100
    ae_patience: int = 10
    ae_max_seconds: float = 45.0
    ae_batch_size: int = 64
    counterfactual_top_n: int = 25
    role_threshold: float = 0.45
    ambiguity_margin: float = 0.08
    role_methodology_version: int = 2
    priority_weights: dict[str, float] = field(default_factory=lambda: {
        "seed_convergence": 0.30,
        "structural_importance": 0.20,
        "flow_significance": 0.20,
        "role_strength": 0.15,
        "anomaly_score": 0.10,
        "cluster_bridge": 0.05,
    })
    role_weights: dict[str, dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        config = asdict(self)
        if isinstance(self.random_seed, bool) or not isinstance(self.random_seed, int) or not 0 <= self.random_seed < 2**32:
            raise ValueError("random_seed must be an integer between 0 and 2**32 - 1")
        if self.model not in {"auto", "autoencoder", "isolation_forest"}:
            raise ValueError("model must be auto, autoencoder or isolation_forest")
        if (isinstance(self.role_methodology_version, bool)
                or not isinstance(self.role_methodology_version, int)
                or self.role_methodology_version not in {1, 2}):
            raise ValueError("role_methodology_version must be integer 1 or 2")
        for name in ("max_depth", "temporal_window_days", "betweenness_samples", "ae_max_epochs",
                     "ae_patience", "ae_batch_size", "counterfactual_top_n"):
            if not isinstance(config[name], int) or isinstance(config[name], bool) or config[name] < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.counterfactual_top_n > 30:
            raise ValueError("counterfactual_top_n must be <= 30")
        for name in ("role_threshold", "ambiguity_margin"):
            if not math.isfinite(config[name]) or not 0 <= config[name] <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if not math.isfinite(self.ae_max_seconds) or self.ae_max_seconds < 0:
            raise ValueError("ae_max_seconds must be finite and nonnegative")
        if not math.isfinite(self.community_resolution) or self.community_resolution <= 0:
            raise ValueError("community_resolution must be positive")
        expected = {"seed_convergence", "structural_importance", "flow_significance",
                    "role_strength", "anomaly_score", "cluster_bridge"}
        if set(self.priority_weights) != expected:
            raise ValueError(f"priority_weights must contain {sorted(expected)}")
        for weights in [self.priority_weights, *self.role_weights.values()]:
            if not weights or any(not math.isfinite(v) or v < 0 for v in weights.values()) or sum(weights.values()) <= 0:
                raise ValueError("weights must be finite, nonnegative and have positive total")
        return config
