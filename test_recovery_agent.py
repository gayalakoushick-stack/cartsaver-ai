import pytest
from recovery_agent import (
    check_stopping_rules,
    process_cart,
    get_escalation_details,
    generate_recovery_content,
    simulate_outcome
)

@pytest.fixture
def sample_normal_cart():
    return {
        "cart_id": "test-cart-normal-001",
        "customer_name": "Aarav Sharma",
        "customer_type": "returning",
        "cart_value": 2499.00,
        "items": "['Wireless Earbuds', 'Leather Case']",
        "payment_method_attempted": "UPI",
        "failure_reason": "bank timeout",
        "abandoned_at": "2026-08-31T10:00:00Z",
        "recovered": 0,
        "recovery_score": 0.65,
        "segment": "High-Value High-Intent"
    }

def test_cart_stops_after_max_attempts(sample_normal_cart):
    """Confirm a cart stops after 3 attempts have already been made."""
    # Attempts 1, 2, and 3 should not trigger the max attempts rule
    for attempt in [1, 2, 3]:
        stop_triggered, reason = check_stopping_rules(sample_normal_cart, attempt)
        assert not stop_triggered, f"Attempt {attempt} unexpectedly stopped: {reason}"
        assert reason is None

    # Attempt 4 must trigger the max attempts stopping rule
    stop_triggered, reason = check_stopping_rules(sample_normal_cart, 4)
    assert stop_triggered is True
    assert reason == "Max 3 attempts per cart reached"

def test_cart_with_recovery_score_below_threshold_never_contacted(sample_normal_cart):
    """Confirm a cart with recovery_score below 0.15 is stopped before any contact attempt."""
    low_score_cart = dict(sample_normal_cart)
    low_score_cart["recovery_score"] = 0.12

    # Check stopping rules directly
    stop_triggered, reason = check_stopping_rules(low_score_cart, attempt_number=1)
    assert stop_triggered is True
    assert "Low recovery score" in reason
    assert "0.12" in reason

    # Confirm through process_cart that no messages are sent and process halts immediately
    logs, is_recovered, cart_id = process_cart(low_score_cart)
    assert is_recovered is False
    assert len(logs) == 1
    assert logs[0]["is_stop"] is True
    assert logs[0]["stopping_rule_triggered"] == 1
    assert logs[0]["escalation_stage"] == "Stopped Before Attempt"
    assert logs[0]["message_draft"] == "N/A"
    assert logs[0]["channel"] == "N/A"

def test_low_value_and_low_score_cart_stops(sample_normal_cart):
    """Confirm a low-value (< ₹300) AND low-score (< 0.40) cart stops due to negative ROI."""
    low_val_low_score_cart = dict(sample_normal_cart)
    low_val_low_score_cart["cart_value"] = 250.00
    low_val_low_score_cart["recovery_score"] = 0.30

    # Case 1: Both low value (< 300) and low score (< 0.40) -> Stop
    stop_triggered, reason = check_stopping_rules(low_val_low_score_cart, attempt_number=1)
    assert stop_triggered is True
    assert "Low cart value" in reason

    # Case 2: Low value (< 300) but high score (>= 0.40) -> Should NOT stop
    high_score_low_val = dict(low_val_low_score_cart)
    high_score_low_val["recovery_score"] = 0.55
    stop_triggered, reason = check_stopping_rules(high_score_low_val, attempt_number=1)
    assert stop_triggered is False
    assert reason is None

    # Case 3: High value (>= 300) with moderate score (>= 0.15 but < 0.40) -> Should NOT stop
    high_val_mod_score = dict(low_val_low_score_cart)
    high_val_mod_score["cart_value"] = 1200.00
    high_val_mod_score["recovery_score"] = 0.30
    stop_triggered, reason = check_stopping_rules(high_val_mod_score, attempt_number=1)
    assert stop_triggered is False
    assert reason is None

def test_already_recovered_cart_stops(sample_normal_cart):
    """Confirm a cart that has already been recovered halts any further attempts."""
    recovered_cart = dict(sample_normal_cart)
    recovered_cart["recovered"] = 1

    stop_triggered, reason = check_stopping_rules(recovered_cart, attempt_number=1)
    assert stop_triggered is True
    assert reason == "Cart already recovered"

def test_normal_cart_proceeds_through_all_stages_correctly(sample_normal_cart, monkeypatch):
    """Confirm a normal cart progresses through all escalation stages with proper message generation."""
    # Sequence outcomes: fail attempt 1 & 2, recover on attempt 3
    outcome_sequence = iter(["attempt_failed", "attempt_failed", "recovered"])
    monkeypatch.setattr("recovery_agent.simulate_outcome", lambda cart, attempt: next(outcome_sequence))

    logs, is_recovered, cart_id = process_cart(sample_normal_cart)

    assert is_recovered is True
    assert len(logs) == 3

    # Stage 1 Checks
    assert logs[0]["attempt_number"] == 1
    assert logs[0]["escalation_stage"] == "Attempt 1: Gentle Reminder"
    assert logs[0]["channel"] == "WhatsApp"
    assert logs[0]["stopping_rule_triggered"] == 0
    assert logs[0]["message_source"] in ["gemini", "fallback"]
    assert len(logs[0]["message_draft"]) > 10
    assert logs[0]["simulated_outcome"] == "attempt_failed"

    # Stage 2 Checks
    assert logs[1]["attempt_number"] == 2
    assert logs[1]["escalation_stage"] == "Attempt 2: Stronger Nudge + Incentive"
    assert logs[1]["channel"] == "WhatsApp"
    assert logs[1]["stopping_rule_triggered"] == 0
    assert logs[1]["message_source"] in ["gemini", "fallback"]
    assert len(logs[1]["message_draft"]) > 10
    assert logs[1]["simulated_outcome"] == "attempt_failed"

    # Stage 3 Checks
    assert logs[2]["attempt_number"] == 3
    assert logs[2]["escalation_stage"] == "Attempt 3: Final Attempt + Urgency"
    assert logs[2]["channel"] == "WhatsApp"
    assert logs[2]["stopping_rule_triggered"] == 0
    assert logs[2]["message_source"] in ["gemini", "fallback"]
    assert len(logs[2]["message_draft"]) > 10
    assert logs[2]["simulated_outcome"] == "recovered"

def test_priority_and_ltv_scoring():
    """Confirm customer_ltv_score and combined priority_score calculations."""
    import pandas as pd
    from score_carts import compute_customer_ltv_and_priority_scores

    test_df = pd.DataFrame([
        {
            "cart_id": "c1",
            "customer_type": "high-value",
            "cart_value": 15000.0,
            "recovery_score": 0.90
        },
        {
            "cart_id": "c2",
            "customer_type": "new",
            "cart_value": 100.0,
            "recovery_score": 0.20
        }
    ])

    scored_df = compute_customer_ltv_and_priority_scores(test_df)

    # High value customer with max cart value should have max LTV (1.0 * 0.6 + 1.0 * 0.4 = 1.0)
    assert scored_df.loc[0, "customer_ltv_score"] == 1.0
    # Combined priority: 0.90 * 0.6 + 1.0 * 0.4 = 0.54 + 0.40 = 0.94
    assert scored_df.loc[0, "priority_score"] == 0.94

    # New customer with min cart value: 0.3 * 0.6 + 0.0 * 0.4 = 0.18
    assert scored_df.loc[1, "customer_ltv_score"] == 0.18
    # Combined priority: 0.20 * 0.6 + 0.18 * 0.4 = 0.12 + 0.072 = 0.192
    assert scored_df.loc[1, "priority_score"] == 0.192

