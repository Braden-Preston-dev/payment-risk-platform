import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.config import settings


@dataclass(frozen=True)
class FraudFeatures:
    amount_ratio: float
    velocity_ratio: float
    is_declined_method: float

    def as_dict(self) -> dict[str, float]:
        return {
            "amount_ratio": self.amount_ratio,
            "velocity_ratio": self.velocity_ratio,
            "is_declined_method": self.is_declined_method,
        }


@dataclass(frozen=True)
class LinearFraudModel:
    intercept: float
    weights: dict[str, float]

    def predict_score(self, features: FraudFeatures) -> int:
        value = self.intercept
        for name, feature_value in features.as_dict().items():
            value += self.weights.get(name, 0.0) * feature_value
        probability = 1 / (1 + math.exp(-max(-30, min(30, value))))
        return round(probability * 100)


def extract_features(
    *,
    amount: int,
    velocity_count: int,
    payment_method_type: str,
) -> FraudFeatures:
    return FraudFeatures(
        amount_ratio=min(amount / 1_000_000, 2.5),
        velocity_ratio=min(velocity_count / 10, 2.0),
        is_declined_method=float(payment_method_type == "card_declined"),
    )


@lru_cache(maxsize=4)
def load_model(path: str) -> LinearFraudModel:
    model_path = Path(path)
    if not model_path.is_absolute() and not model_path.exists():
        parents = Path(__file__).resolve().parents
        if len(parents) > 4:
            repository_path = parents[4] / model_path
            if repository_path.exists():
                model_path = repository_path
    payload = json.loads(model_path.read_text(encoding="utf-8"))
    if payload.get("model_type") != "logistic_regression":
        raise ValueError("Unsupported fraud model type")
    weights = {str(key): float(value) for key, value in payload["weights"].items()}
    return LinearFraudModel(intercept=float(payload["intercept"]), weights=weights)


def predict_ml_score(
    *,
    amount: int,
    velocity_count: int,
    payment_method_type: str,
) -> int | None:
    if not settings.ML_MODEL_PATH:
        return None
    try:
        model = load_model(settings.ML_MODEL_PATH)
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None
    features = extract_features(
        amount=amount,
        velocity_count=velocity_count,
        payment_method_type=payment_method_type,
    )
    return model.predict_score(features)
