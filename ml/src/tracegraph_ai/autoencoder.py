"""Optional CPU autoencoder; importing this module does not import torch."""

from __future__ import annotations

import math
import threading
from time import perf_counter

import numpy as np


_TORCH_LOCK = threading.Lock()


class AutoencoderFailure(RuntimeError):
    def __init__(self, reason: str, training_info: dict):
        super().__init__(reason)
        self.training_info = training_info


def train_autoencoder(matrix, train_indices, validation_indices, config, seed):
    """Return raw reconstruction errors and metadata; restore CPU RNG/threads."""
    started = perf_counter()
    seconds = float(config.get("ae_max_seconds", 45.0))
    epochs = int(config.get("ae_max_epochs", 100))
    patience = int(config.get("ae_patience", 10))
    batch_size = int(config.get("ae_batch_size", 64))
    if not math.isfinite(seconds) or seconds < 0 or min(epochs, patience, batch_size) < 1:
        raise ValueError("Invalid autoencoder training budget")
    seconds, epochs = min(seconds, 45.0), min(epochs, 100)
    training = {
        "architecture": [int(matrix.shape[1]), 16, 8, 4, 8, 16, int(matrix.shape[1])],
        "optimizer": "Adam", "learning_rate": 0.001, "loss": "MSELoss",
        "batch_size": batch_size, "max_epochs": epochs, "patience": patience,
        "max_seconds": seconds, "epochs_completed": 0, "best_epoch": None,
        "best_validation_mse": None, "training_seconds": 0.0,
        "stopping_reason": "max_epochs",
    }

    def check_budget():
        training["training_seconds"] = perf_counter() - started
        if training["training_seconds"] >= seconds:
            training["stopping_reason"] = "time_budget_exceeded"
            raise AutoencoderFailure("autoencoder_time_budget_exceeded", dict(training))

    check_budget()
    import torch
    from torch import nn

    # Serialize only this optional backend. Neither NumPy's nor torch's caller
    # random sequence is consumed. Thread settings are restored even on failure.
    with _TORCH_LOCK:
        previous_threads = torch.get_num_threads()
        try:
            torch.set_num_threads(min(2, previous_threads))
            training["cpu_threads"] = torch.get_num_threads()
            with torch.random.fork_rng(devices=[]):
                generator = torch.Generator(device="cpu").manual_seed(seed)
                torch.random.set_rng_state(generator.get_state())
                dimensions = training["architecture"]
                layers = []
                for index, (left, right) in enumerate(zip(dimensions, dimensions[1:])):
                    layers.append(nn.Linear(left, right))
                    if index < len(dimensions) - 2:
                        layers.append(nn.ReLU())
                model = nn.Sequential(*layers).to(device="cpu", dtype=torch.float32)
                optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
                loss_fn = nn.MSELoss()
                all_rows = torch.from_numpy(np.ascontiguousarray(matrix))
                train_rows = all_rows[train_indices]
                validation_rows = all_rows[validation_indices]
                shuffle = np.random.default_rng(seed)
                best_state, best_loss, stale = None, float("inf"), 0
                for epoch in range(epochs):
                    check_budget()
                    model.train()
                    order = shuffle.permutation(len(train_rows))
                    for offset in range(0, len(order), batch_size):
                        check_budget()
                        batch = train_rows[order[offset:offset + batch_size]]
                        optimizer.zero_grad(set_to_none=True)
                        loss = loss_fn(model(batch), batch)
                        if not torch.isfinite(loss):
                            raise AutoencoderFailure("nonfinite_training_loss", dict(training))
                        loss.backward()
                        optimizer.step()
                    model.eval()
                    with torch.no_grad():
                        validation_loss = float(loss_fn(model(validation_rows), validation_rows).item())
                    if not math.isfinite(validation_loss):
                        raise AutoencoderFailure("nonfinite_validation_loss", dict(training))
                    training["epochs_completed"] = epoch + 1
                    if validation_loss < best_loss - 1e-6:
                        best_loss, stale = validation_loss, 0
                        best_state = {name: value.detach().clone() for name, value in model.state_dict().items()}
                        training["best_epoch"] = epoch + 1
                        training["best_validation_mse"] = best_loss
                    else:
                        stale += 1
                    check_budget()
                    if stale >= patience:
                        training["stopping_reason"] = "early_stopping"
                        break
                model.load_state_dict(best_state)
                model.eval()
                with torch.no_grad():
                    per_feature_errors = (model(all_rows) - all_rows).square().numpy().astype(np.float64)
                if not np.isfinite(per_feature_errors).all():
                    raise AutoencoderFailure("nonfinite_reconstruction_error", dict(training))
                check_budget()
        finally:
            torch.set_num_threads(previous_threads)
    training["training_seconds"] = perf_counter() - started
    return per_feature_errors.mean(axis=1), per_feature_errors, training
