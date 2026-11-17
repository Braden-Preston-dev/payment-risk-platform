from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RiskResult:
    score: int
    decision: str
    triggered_rules: list[dict[str, Any]]


def evaluate_risk(
    *,
    amount: int,
    velocity_count: int,
    ml_score: int | None = None,
) -> RiskResult:
    score = 0
    rules: list[dict[str, Any]] = []

    if amount >= 1_000_000:
        score += 90
        rules.append({"rule": "very_high_amount", "score": 90})
    elif amount >= 250_000:
        score += 55
        rules.append({"rule": "high_amount", "score": 55})

    if velocity_count > 5:
        score += 30
        rules.append({"rule": "rapid_confirm_velocity", "score": 30})

    score = min(score, 100)
    if ml_score is not None and ml_score > score:
        score = min(ml_score, 100)
        rules.append({"rule": "ml_score_override", "score": score})
    if score >= 75:
        decision = "block"
    elif score >= 50:
        decision = "review"
    else:
        decision = "allow"
    return RiskResult(score=score, decision=decision, triggered_rules=rules)
