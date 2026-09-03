import sys
import os
import json
import time
import hmac
import hashlib
import uuid
import argparse
import requests
from typing import Optional
from dotenv import load_dotenv

# Ensure UTF-8 stdout encoding on Windows
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            getattr(sys.stdout, "reconfigure")(encoding='utf-8')
    except Exception:
        pass

# Load environment variables
load_dotenv()
WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "cartsaver_razorpay_secret_live_8912")
DEFAULT_URL = "http://localhost:8000/webhooks/razorpay"

SCENARIOS = {
    "bank_timeout": {
        "description": "UPI payment timed out at bank server",
        "method": "upi",
        "amount_inr": 3499.00,
        "customer_name": "Rohan Deshmukh",
        "customer_type": "high-value",
        "email": "rohan.deshmukh@example.com",
        "contact": "+919876543210",
        "error_code": "GATEWAY_ERROR",
        "error_description": "Payment processing failed due to upstream bank gateway timeout",
        "error_source": "gateway",
        "error_step": "payment_authorization",
        "error_reason": "payment_failed_due_to_bank_timeout",
        "items": ["Smart Fitness Watch Pro", "Silicone Strap"]
    },
    "insufficient_balance": {
        "description": "Debit card declined due to insufficient funds in account",
        "method": "card",
        "amount_inr": 8990.00,
        "customer_name": "Pooja Verma",
        "customer_type": "returning",
        "email": "pooja.verma@example.com",
        "contact": "+919811223344",
        "error_code": "BAD_REQUEST_ERROR",
        "error_description": "Payment failed: Insufficient balance in customer account",
        "error_source": "issuing_bank",
        "error_step": "payment_authorization",
        "error_reason": "account_insufficient_balance",
        "items": ["Kanjivaram Silk Saree", "Jewelry Box"]
    },
    "otp_failed": {
        "description": "UPI 2-Factor / OTP authentication failed",
        "method": "upi",
        "amount_inr": 2150.00,
        "customer_name": "Kavya Nair",
        "customer_type": "returning",
        "email": "kavya.nair@example.com",
        "contact": "+919822334455",
        "error_code": "BAD_REQUEST_AUTHENTICATION_FAILED",
        "error_description": "Incorrect OTP entered by user during 3D Secure verification",
        "error_source": "customer",
        "error_step": "payment_authentication",
        "error_reason": "otp_verification_failed",
        "items": ["Cotton Printed Kurta", "Palazzo Pants"]
    },
    "user_exited": {
        "description": "Customer exited checkout or cancelled payment",
        "method": "netbanking",
        "amount_inr": 1250.00,
        "customer_name": "Vikram Sethi",
        "customer_type": "new",
        "email": "vikram.sethi@example.com",
        "contact": "+919833445566",
        "error_code": "BAD_REQUEST_PAYMENT_CANCELLED_BY_USER",
        "error_description": "Payment process cancelled by user on bank redirect page",
        "error_source": "customer",
        "error_step": "payment_authorization",
        "error_reason": "user_cancelled_transaction",
        "items": ["Wireless Gaming Mouse"]
    },
    "payment_declined": {
        "description": "General bank decline on credit card",
        "method": "card",
        "amount_inr": 6799.00,
        "customer_name": "Siddharth Rao",
        "customer_type": "high-value",
        "email": "siddharth.rao@example.com",
        "contact": "+919844556677",
        "error_code": "CARD_DECLINED",
        "error_description": "Transaction declined by issuing bank security filters",
        "error_source": "issuing_bank",
        "error_step": "payment_authorization",
        "error_reason": "bank_risk_decline",
        "items": ["Mechanical RGB Keyboard", "Desk Mat XXL"]
    }
}

def construct_payload(scenario_key: str = "bank_timeout", custom_amount: Optional[float] = None, custom_name: Optional[str] = None):
    sc = SCENARIOS.get(scenario_key, SCENARIOS["bank_timeout"])
    
    amount_inr = custom_amount if custom_amount is not None else sc["amount_inr"]
    customer_name = custom_name if custom_name is not None else sc["customer_name"]
    amount_paise = int(amount_inr * 100)
    
    payment_id = f"pay_{uuid.uuid4().hex[:14]}"
    order_id = f"order_{uuid.uuid4().hex[:14]}"
    created_ts = int(time.time())
    
    payload = {
        "entity": "event",
        "account_id": "acc_CartSaverProd99",
        "event": "payment.failed",
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "entity": "payment",
                    "amount": amount_paise,
                    "currency": "INR",
                    "status": "failed",
                    "order_id": order_id,
                    "invoice_id": None,
                    "international": False,
                    "method": sc["method"],
                    "amount_refunded": 0,
                    "refund_status": None,
                    "captured": False,
                    "description": f"Order #{order_id[:10]} - CartSaver Store",
                    "card_id": f"card_{uuid.uuid4().hex[:10]}" if sc["method"] == "card" else None,
                    "bank": "HDFC" if sc["method"] == "netbanking" else None,
                    "wallet": None,
                    "vpa": f"{customer_name.lower().replace(' ', '')}@okhdfcbank" if sc["method"] == "upi" else None,
                    "email": sc["email"],
                    "contact": sc["contact"],
                    "notes": {
                        "customer_name": customer_name,
                        "customer_type": sc["customer_type"],
                        "items": json.dumps(sc["items"])
                    },
                    "fee": None,
                    "tax": None,
                    "error_code": sc["error_code"],
                    "error_description": sc["error_description"],
                    "error_source": sc["error_source"],
                    "error_step": sc["error_step"],
                    "error_reason": sc["error_reason"],
                    "created_at": created_ts
                }
            }
        },
        "created_at": created_ts
    }
    return payload

def sign_payload(payload_bytes: bytes, secret: str) -> str:
    """Generate HMAC-SHA256 hex signature as expected by Razorpay webhooks."""
    return hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()

def send_webhook(url: str, payload_dict: dict, secret: str):
    raw_body = json.dumps(payload_dict, indent=2).encode("utf-8")
    signature = sign_payload(raw_body, secret)
    
    headers = {
        "Content-Type": "application/json",
        "X-Razorpay-Signature": signature,
        "User-Agent": "Razorpay-Webhook-Simulator/1.0"
    }
    
    print("\n" + "="*70)
    print("           RAZORPAY WEBHOOK DISPATCH SIMULATOR           ")
    print("="*70)
    print(f"Target URL              : {url}")
    print(f"Event Type              : {payload_dict.get('event')}")
    print(f"Payment ID              : {payload_dict['payload']['payment']['entity']['id']}")
    print(f"Amount                  : ₹{payload_dict['payload']['payment']['entity']['amount'] / 100:.2f}")
    print(f"Method                  : {payload_dict['payload']['payment']['entity']['method'].upper()}")
    print(f"Error Code              : {payload_dict['payload']['payment']['entity']['error_code']}")
    print(f"Error Description       : {payload_dict['payload']['payment']['entity']['error_description']}")
    print(f"Calculated Signature    : {signature[:16]}...{signature[-8:]}")
    print("="*70)
    
    try:
        response = requests.post(url, data=raw_body, headers=headers, timeout=10)
        print(f"\n[Response Status]       : {response.status_code} {response.reason}")
        
        try:
            res_json = response.json()
            print("\n[Response Body]:")
            print(json.dumps(res_json, indent=2))
        except Exception:
            print(f"\n[Response Raw]:\n{response.text}")
            
        print("\n" + "="*70)
        return response
    except requests.exceptions.ConnectionError:
        print(f"\n❌ Connection Error: Could not reach {url}.")
        print("   Make sure the FastAPI server is running via:")
        print("   .venv\\Scripts\\python.exe -m uvicorn main:app --port 8000")
        print("="*70 + "\n")
        return None
    except Exception as e:
        print(f"\n❌ Error during dispatch: {e}")
        print("="*70 + "\n")
        return None

def main():
    parser = argparse.ArgumentParser(description="Simulate Razorpay payment.failed Webhooks to CartSaver AI")
    parser.add_argument(
        "--scenario",
        choices=list(SCENARIOS.keys()),
        default="bank_timeout",
        help="Failure scenario to simulate (default: bank_timeout)"
    )
    parser.add_argument("--url", default=DEFAULT_URL, help=f"Webhook receiver URL (default: {DEFAULT_URL})")
    parser.add_argument("--amount", type=float, default=None, help="Custom cart amount in INR")
    parser.add_argument("--name", type=str, default=None, help="Custom customer name")
    parser.add_argument("--secret", default=WEBHOOK_SECRET, help="Razorpay webhook secret key")
    parser.add_argument("--all-scenarios", action="store_true", help="Sequentially run all available scenarios")
    
    args = parser.parse_args()
    
    if args.all_scenarios:
        for sc_name in SCENARIOS.keys():
            print(f"\n--- Running Scenario: {sc_name} ---")
            payload = construct_payload(sc_name, args.amount, args.name)
            send_webhook(args.url, payload, args.secret)
    else:
        payload = construct_payload(args.scenario, args.amount, args.name)
        send_webhook(args.url, payload, args.secret)

if __name__ == "__main__":
    main()
