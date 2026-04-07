from __future__ import annotations

from app.services.rules.engine import RuleEvaluationInput, evaluate_rules


def test_rule_engine_blocks_out_of_policy_amount() -> None:
    result = evaluate_rules(
        RuleEvaluationInput(
            amount=2500,
            city_tier="tier-2",
            expense_type="hotel",
        )
    )

    assert result.decision == "blocked"
    assert result.rule_hits
    assert result.rule_hits[0].rule_code == "hotel_amount_tier_2"
    assert "超出酒店标准" in result.reason
