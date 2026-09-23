"""Within-session anomaly signals, independent of role classification.

The public function consumes native integer gids. All randomness is local, and
the optional torch backend is imported only when it is actually requested.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
from importlib import metadata
from time import perf_counter

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler


BASE_FEATURES = (
    "in_degree", "out_degree", "in_kzt", "out_kzt", "in_tx", "out_tx",
    "pagerank", "betweenness", "pass_through_ratio", "retention_ratio",
    "seed_reach_count", "seed_convergence_score", "min_seed_distance",
    "cluster_bridge_score", "rapid_pass_through_score", "temporal_burst_score",
    "synchronized_fan_in_score", "synchronized_fan_out_score",
    "incoming_active_days", "outgoing_active_days", "depth",
)
MISSING_FEATURES = (
    "pass_through_ratio", "retention_ratio", "rapid_pass_through_score",
    "min_seed_distance",
)
FEATURE_NAMES = BASE_FEATURES + tuple(f"{name}_missing" for name in MISSING_FEATURES)
LOG_FEATURES = frozenset({
    "in_degree", "out_degree", "in_kzt", "out_kzt", "in_tx", "out_tx",
    "seed_reach_count", "min_seed_distance", "incoming_active_days",
    "outgoing_active_days", "pass_through_ratio",
})


def _version(package: str) -> str | None:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None


def _number(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return float("nan")
    return number if math.isfinite(number) else float("nan")


def _prepare(features: dict[int, dict], gids: list[int], seed: int):
    """Fit medians and scaler on a seeded training partition, never holdout."""
    raw = np.array([
        [_number(features[gid].get(name)) for name in BASE_FEATURES]
        for gid in gids
    ], dtype=np.float64)
    for column, name in enumerate(BASE_FEATURES):
        if name in LOG_FEATURES:
            raw[raw[:, column] < 0, column] = np.nan
            raw[:, column] = np.log1p(raw[:, column])
    # Invalid non-count measurements cannot overflow StandardScaler's variance.
    raw[np.abs(raw) > 1e100] = np.nan
    missing_columns = [BASE_FEATURES.index(name) for name in MISSING_FEATURES]
    masks = (~np.isfinite(raw[:, missing_columns])).astype(np.float64)
    matrix = np.column_stack((raw, masks))
    order = np.random.default_rng(seed).permutation(len(gids))
    n_validation = max(1, int(round(len(gids) * 0.2))) if len(gids) > 5 else 0
    validation_indices, train_indices = order[:n_validation], order[n_validation:]
    medians = []
    for column in range(matrix.shape[1]):
        observed = matrix[train_indices, column]
        observed = observed[np.isfinite(observed)]
        medians.append(float(np.median(observed)) if observed.size else 0.0)
    imputed = np.where(np.isfinite(matrix), matrix, np.array(medians))
    scaler = StandardScaler().fit(imputed[train_indices])
    scaled = scaler.transform(imputed)
    # A finite bound also makes unseen holdout values safe for float32 training.
    clipped = np.abs(scaled) > 20.0
    scaled = np.clip(scaled, -20.0, 20.0).astype(np.float32)
    preprocessing = {
        "fit_partition": "train_only",
        "method": "log1p -> train median imputation -> StandardScaler -> clip [-20,20]",
        "log1p_features": sorted(LOG_FEATURES),
        "missing_indicator_features": list(MISSING_FEATURES),
        "imputation_medians": dict(zip(FEATURE_NAMES, medians)),
        "scaler_mean": scaler.mean_.tolist(),
        "scaler_scale": scaler.scale_.tolist(),
        "constant_train_features": [
            name for name, variance in zip(FEATURE_NAMES, scaler.var_) if variance == 0
        ],
        "missing_counts": {
            name: int((~np.isfinite(matrix[:, column])).sum())
            for column, name in enumerate(FEATURE_NAMES)
        },
        "clipped_values": int(clipped.sum()),
        "train_rows": int(len(train_indices)),
        "validation_rows": int(len(validation_indices)),
        "split_digest": hashlib.sha256(json.dumps({
            "train": [str(gids[index]) for index in train_indices],
            "validation": [str(gids[index]) for index in validation_indices],
        }, sort_keys=True).encode()).hexdigest(),
    }
    return scaled, train_indices, validation_indices, preprocessing


def _rank_scores(raw_scores: np.ndarray) -> np.ndarray:
    """Equal values receive equal ranks; a constant model contributes zero."""
    if len(raw_scores) < 2 or np.isclose(
        raw_scores.min(), raw_scores.max(), rtol=1e-9, atol=1e-12
    ):
        return np.zeros(len(raw_scores))
    _, inverse, counts = np.unique(raw_scores, return_inverse=True, return_counts=True)
    ranks = np.cumsum(counts) - counts + (counts - 1) / 2
    return ((ranks - ranks.min()) / (ranks.max() - ranks.min()))[inverse]


def _distribution(values: np.ndarray) -> dict:
    if not values.size:
        return {name: None for name in ("min", "p50", "p95", "max")}
    return dict(zip(("min", "p50", "p95", "max"), [
        float(value) for value in np.quantile(values, [0, 0.5, 0.95, 1])
    ]))


def _forest(matrix: np.ndarray, train_indices: np.ndarray, seed: int):
    start = perf_counter()
    forest = IsolationForest(
        n_estimators=100, max_samples=min(256, len(train_indices)),
        contamination="auto", random_state=seed, n_jobs=1,
    )
    forest.fit(matrix[train_indices])
    # sklearn uses lower scores for more unusual rows.
    raw_scores = -forest.score_samples(matrix)
    if not np.isfinite(raw_scores).all():
        raise ValueError("IsolationForest returned non-finite anomaly scores")
    return raw_scores, {
        "n_estimators": 100, "max_samples": int(forest.max_samples_),
        "contamination": "auto", "n_jobs": 1,
        "epochs_completed": 0, "training_seconds": perf_counter() - start,
        "stopping_reason": "forest_complete",
    }


def score_anomalies(features: dict[int, dict], config: dict) -> tuple[dict[int, dict], dict]:
    """Score every node without modifying input features or assigning roles.

    ``model='auto'`` and ``model='autoencoder'`` both attempt the CPU neural
    model and fall back to IsolationForest on any unavailable/failed training.
    ``ae_max_seconds=0`` explicitly exercises the fallback path.
    """
    started = perf_counter()
    requested = config.get("model", "auto")
    if requested not in {"auto", "autoencoder", "isolation_forest"}:
        raise ValueError("model must be auto, autoencoder or isolation_forest")
    seed = int(config.get("random_seed", 42))
    if not 0 <= seed < 2**32:
        raise ValueError("random_seed must be between 0 and 2**32 - 1")
    gids = sorted(features)
    info = {
        "requested_backend": requested,
        "backend": "degenerate",
        "device": "cpu",
        "features": list(FEATURE_NAMES),
        "base_features": list(BASE_FEATURES),
        "input_dim": len(FEATURE_NAMES),
        "random_seed": seed,
        "versions": {
            "python": platform.python_version(), "numpy": _version("numpy"),
            "scikit_learn": _version("scikit-learn"), "torch": _version("torch"),
        },
        "fallback_reason": None,
        "warnings": [],
        "training": {"rows": len(gids), "epochs_completed": 0, "training_seconds": 0.0},
        "score_normalization": "rescaled empirical midrank; ties equal; constant scores zero",
        "interpretation": "Within-session unusualness, not a role or calibrated risk probability.",
    }
    if not gids:
        info.update({"fallback_reason": "empty_session", "total_seconds": perf_counter() - started})
        info["warnings"].append("No nodes are available for anomaly analysis.")
        return {}, info

    matrix, train_indices, validation_indices, preprocessing = _prepare(features, gids, seed)
    info["preprocessing"] = preprocessing
    info["training"].update({"train_rows": len(train_indices), "validation_rows": len(validation_indices)})
    info["input_matrix_digest"] = hashlib.sha256(matrix.tobytes()).hexdigest()
    per_feature_errors = None
    raw_scores = np.zeros(len(gids), dtype=np.float64)
    constant_matrix = bool(np.all(np.ptp(matrix, axis=0) <= 1e-12))
    if len(gids) < 2 or constant_matrix:
        info["fallback_reason"] = "insufficient_variation"
        info["warnings"].append("All profiles are identical or there is only one node; anomaly is zero.")
    else:
        if requested != "isolation_forest":
            if len(gids) <= 5:
                info["fallback_reason"] = "too_few_rows_for_autoencoder_holdout"
            elif float(config.get("ae_max_seconds", 45)) == 0:
                info["fallback_reason"] = "autoencoder_time_budget_disabled"
            else:
                try:
                    from .autoencoder import train_autoencoder
                    raw_scores, per_feature_errors, training = train_autoencoder(
                        matrix, train_indices, validation_indices, config, seed,
                    )
                    info["backend"] = "autoencoder"
                    info["training"].update(training)
                except Exception as error:
                    # Optional model failures must not interrupt the graph engine.
                    info["fallback_reason"] = f"autoencoder_failed:{type(error).__name__}:{str(error)[:200]}"
                    attempt = getattr(error, "training_info", None)
                    if attempt is not None:
                        info["autoencoder_attempt"] = attempt
        if info["backend"] != "autoencoder":
            try:
                raw_scores, training = _forest(matrix, train_indices, seed)
                info["backend"] = "isolation_forest"
                info["training"].update(training)
            except Exception as error:
                info["fallback_reason"] = (
                    f"{info['fallback_reason'] or ''};isolation_forest_failed:"
                    f"{type(error).__name__}:{str(error)[:200]}"
                ).lstrip(";")
                info["warnings"].append("No usable anomaly model; all anomaly signals are zero.")
                raw_scores = np.zeros(len(gids), dtype=np.float64)

    scores = _rank_scores(raw_scores)
    if len(gids) <= 5:
        info["warnings"].append("A very small session gives unstable relative anomaly ranks.")
    if np.ptp(scores) == 0:
        info["warnings"].append("Anomaly score distribution is constant; it carries no ranking signal.")
    method = {
        "autoencoder": "autoencoder_reconstruction_error",
        "isolation_forest": "standardized_feature_deviation_not_model_attribution",
        "degenerate": "no_anomaly_signal",
    }[info["backend"]]
    contributions = per_feature_errors if per_feature_errors is not None else np.abs(matrix)
    if info["backend"] == "degenerate":
        contributions = np.zeros_like(matrix)
    results = {}
    for row, gid in enumerate(gids):
        columns = np.argsort(-contributions[row], kind="stable")[:3]
        columns = [int(column) for column in columns if contributions[row, column] > 1e-12]
        results[gid] = {
            "anomaly_score": float(scores[row]),
            "main_anomaly_features": [FEATURE_NAMES[column] for column in columns],
            "explanation_method": method,
            "feature_deviations": {FEATURE_NAMES[column]: float(matrix[row, column]) for column in columns},
        }
    info["explanation_method"] = method
    info["raw_score_distribution"] = _distribution(raw_scores)
    info["anomaly_score_distribution"] = _distribution(scores)
    info["dominant_features"] = [
        FEATURE_NAMES[column]
        for column in np.argsort(-contributions.mean(axis=0), kind="stable")[:5]
        if contributions[:, column].mean() > 1e-12
    ]
    info["total_seconds"] = perf_counter() - started
    return results, info
