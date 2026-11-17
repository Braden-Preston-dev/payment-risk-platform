"""Generate deterministic synthetic payment scenarios for demos and analysis."""

import argparse
import csv
import random
from pathlib import Path


def generate(path: Path, rows: int, seed: int) -> None:
    randomizer = random.Random(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=(
                "customer_external_id",
                "amount",
                "currency",
                "payment_method_type",
                "velocity_count",
                "scenario",
                "expected_decision",
            ),
        )
        writer.writeheader()
        for index in range(rows):
            roll = randomizer.random()
            if roll < 0.08:
                amount, method, scenario, decision = (
                    randomizer.randint(1_000_000, 2_500_000),
                    "card",
                    "very_high_amount",
                    "block",
                )
            elif roll < 0.20:
                amount, method, scenario, decision = (
                    randomizer.randint(250_000, 999_999),
                    "card",
                    "high_amount",
                    "review",
                )
            elif roll < 0.28:
                amount, method, scenario, decision = (
                    randomizer.randint(100, 50_000),
                    "card_declined",
                    "simulated_decline",
                    "allow",
                )
            elif roll < 0.40:
                amount, method, scenario, decision = (
                    randomizer.randint(100, 50_000),
                    "card",
                    "rapid_velocity",
                    "review",
                )
            else:
                amount, method, scenario, decision = (
                    randomizer.randint(100, 50_000),
                    "card",
                    "normal",
                    "allow",
                )
            writer.writerow(
                {
                    "customer_external_id": f"synthetic-{index:06d}",
                    "amount": amount,
                    "currency": randomizer.choice(("usd", "eur", "gbp")),
                    "payment_method_type": method,
                    "velocity_count": (
                        randomizer.randint(6, 12)
                        if scenario == "rapid_velocity"
                        else randomizer.randint(1, 5)
                    ),
                    "scenario": scenario,
                    "expected_decision": decision,
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("synthetic_payments.csv"))
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    if args.rows < 1:
        raise SystemExit("--rows must be positive")
    generate(args.output, args.rows, args.seed)
    print(f"wrote {args.rows} rows to {args.output}")


if __name__ == "__main__":
    main()
