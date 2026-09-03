import os
import json
import hmac
import hashlib
import pytest
from fastapi.testclient import TestClient
from main import app, map_razorpay_error, normalize_payment_method, score_and_segment_cart

client = TestClient(app)
WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "cartsaver_razorpay_secret_live_8912")

def sign_payload(payload_bytes: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()

def make_sample_payload(
    error_code="GATEWAY_ERROR",
    error_desc="Bank gateway timeout",
    method="upi",
    amount_paise=349900,
    event="payment.failed"
):
    return {
        "entity": "event",
        "account_id": "acc_test123",
        "event": event,
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test_001",
                    "amount": amount_paise,
                    "currency": "INR",
                    "status": "failed",
                    "method": method,
                    "error_code": error_code,
                    "error_description": error_desc,
                    "notes": {
                        "customer_name": "Deepak Joshi",
                        "customer_type": "high-value"
                    }
                }
            }
        }
    }

def test_webhook_successful_ingestion_and_recovery():
    """Confirm a valid signed payment.failed webhook is ingested, scored, and processed."""
    payload = make_sample_payload(
        error_code="GATEWAY_ERROR",
        error_desc="Gateway timed out",
        method="upi",
        amount_paise=450000
    )
    raw_body = json.dumps(payload).encode("utf-8")
    sig = sign_payload(raw_body)

    response = client.post(
        "/webhooks/razorpay",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": sig
        }
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "cart_id" in data
    assert data["transaction"]["amount_inr"] == 4500.00
    assert data["transaction"]["method"] == "UPI"
    assert data["transaction"]["mapped_failure_reason"] == "bank timeout"
    assert data["scoring"]["recovery_score"] > 0
    assert data["scoring"]["priority_score"] > 0
    assert data["recovery_action"]["status"] in ["contacted", "stopped"]

def test_webhook_invalid_signature_rejected():
    """Confirm webhook with mismatched signature returns 400 Bad Request."""
    payload = make_sample_payload()
    raw_body = json.dumps(payload).encode("utf-8")
    fake_sig = "0" * 64

    response = client.post(
        "/webhooks/razorpay",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": fake_sig
        }
    )

    assert response.status_code == 400
    assert "Invalid webhook signature" in response.json()["detail"]

def test_webhook_missing_signature_rejected():
    """Confirm webhook without X-Razorpay-Signature header returns 400 Bad Request."""
    payload = make_sample_payload()
    raw_body = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/webhooks/razorpay",
        content=raw_body,
        headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 400
    assert "Missing required 'X-Razorpay-Signature'" in response.json()["detail"]

def test_webhook_non_failure_event_ignored():
    """Confirm non-payment.failed events return 200 OK with ignored status."""
    payload = make_sample_payload(event="payment.captured")
    raw_body = json.dumps(payload).encode("utf-8")
    sig = sign_payload(raw_body)

    response = client.post(
        "/webhooks/razorpay",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": sig
        }
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ignored"

def test_razorpay_error_mapping_rules():
    """Confirm Razorpay error codes map cleanly to CartSaver failure categories."""
    assert map_razorpay_error("GATEWAY_ERROR", "timeout occurred") == "bank timeout"
    assert map_razorpay_error("BAD_REQUEST_ERROR", "Insufficient balance in account") == "insufficient balance"
    assert map_razorpay_error("BAD_REQUEST_AUTHENTICATION_FAILED", "OTP verification failed") == "OTP failed"
    assert map_razorpay_error("BAD_REQUEST_PAYMENT_CANCELLED_BY_USER", "User cancelled") == "user exited at payment"
    assert map_razorpay_error("CARD_DECLINED", "Generic decline") == "payment declined"
