"""Train the small JSON logistic model used by PRP from synthetic CSV data."""

import argparse
import csv
import json
import math
import random
from pathlib import Path


FEATURES = ("amount_ratio", "velocity_ratio", "is_declined_method")


def _features(row: dict[str, str]) -> dict[str, float]:
    return {
        "amount_ratio": min(int(row["amount"]) / 1_000_000, 2.5),
        "velocity_ratio": min(int(row["velocity_count"]) / 10, 2.0),
        "is_declined_method": float(row["payment_method_type"] == "card_declined"),
    }


def train(input_path: Path, output_path: Path, epochs: int, learning_rate: float) -> None:
    with input_path.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    if not rows:
        raise SystemExit("training data is empty")

    weights = {name: 0.0 for name in FEATURES}
    intercept = 0.0
    randomizer = random.Random(2026)
    for _ in range(epochs):
        randomizer.shuffle(rows)
        for row in rows:
            features = _features(row)
            target = float(row["expected_decision"] in {"review", "block"})
            logit = intercept + sum(weights[name] * features[name] for name in FEATURES)
            probability = 1 / (1 + math.exp(-max(-30, min(30, logit))))
            error = probability - target
            intercept -= learning_rate * error
            for name in FEATURES:
                weights[name] -= learning_rate * error * features[name]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "model_type": "logistic_regression",
                "version": 1,
                "intercept": intercept,
                "weights": weights,
                "training": {"rows": len(rows), "epochs": epochs, "seed": 2026},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"trained model on {len(rows)} rows and wrote {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, default=Path("models/fraud_model.json"))
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--learning-rate", type=float, default=0.01)
    args = parser.parse_args()
    train(args.input, args.output, args.epochs, args.learning_rate)


if __name__ == "__main__":
    main()
