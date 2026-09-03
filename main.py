import sys
import os
import json
import sqlite3
import random
import uuid
import hmac
import hashlib
import numpy as np
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Path, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# Load environment variables
load_dotenv()
print(f"[STARTUP CHECK] .env file found: {os.path.exists('.env')}")
print(f"[STARTUP CHECK] GEMINI_API_KEY loaded: {bool(os.getenv('GEMINI_API_KEY'))}")
print(f"[STARTUP CHECK] Key starts with: {os.getenv('GEMINI_API_KEY', 'NOT_FOUND')[:6]}")

# Ensure UTF-8 stdout encoding on Windows
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            getattr(sys.stdout, "reconfigure")(encoding='utf-8')
    except Exception:
        pass

# Import agent helper functions from recovery_agent for POST /carts/{cart_id}/recover
from recovery_agent import (
    check_stopping_rules,
    get_escalation_details,
    generate_recovery_content,
    simulate_outcome
)

DB_NAME = "cartsaver.db"

app = FastAPI(
    title="CartSaver AI REST API",
    description="AI Payment Recovery & Abandoned Cart Risk Engine for Indian E-Commerce",
    version="1.0.0"
)

# Enable CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# PYDANTIC RESPONSE SCHEMAS
# -----------------------------------------------------------------------------

class CartResponse(BaseModel):
    cart_id: str
    customer_name: str
    customer_type: str
    cart_value: float
    items: List[str]
    payment_method_attempted: str
    failure_reason: str
    abandoned_at: str
    recovered: bool
    recovery_score: Optional[float] = None
    customer_ltv_score: Optional[float] = None
    priority_score: Optional[float] = None
    segment: Optional[str] = None

class RecoveryLogResponse(BaseModel):
    log_id: str
    cart_id: str
    attempt_number: int
    timestamp: str
    escalation_stage: str
    channel: str
    root_cause_diagnosis: str
    message_draft: str
    agent_reasoning: str
    message_source: Optional[str] = "gemini"
    stopping_rule_triggered: bool
    stopping_reason: Optional[str] = None
    simulated_outcome: str

class CartDetailResponse(BaseModel):
    cart: CartResponse
    logs: List[RecoveryLogResponse]

class AnalyticsSummaryResponse(BaseModel):
    total_carts: int
    total_value_at_risk: float
    total_value_recovered: float
    recovery_rate_percent: float
    segment_breakdown: Dict[str, Dict[str, Any]]
    stopping_reason_breakdown: Dict[str, int]
    escalation_stage_breakdown: Dict[str, int]

class SingleRecoveryAttemptResponse(BaseModel):
    status: str
    message: str
    stopping_rule_triggered: bool
    stopping_reason: Optional[str] = None
    attempt_number: Optional[int] = None
    escalation_stage: Optional[str] = None
    channel: Optional[str] = None
    root_cause_diagnosis: Optional[str] = None
    message_draft: Optional[str] = None
    agent_reasoning: Optional[str] = None
    message_source: Optional[str] = None
    simulated_outcome: Optional[str] = None
    cart_recovered: bool

# -----------------------------------------------------------------------------
# HELPER FUNCTIONS
# -----------------------------------------------------------------------------

def get_db_connection():
    if not os.path.exists(DB_NAME):
        raise HTTPException(status_code=500, detail=f"Database '{DB_NAME}' not found.")
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def parse_cart_row(row: sqlite3.Row) -> CartResponse:
    row_dict = dict(row)
    try:
        items_list = json.loads(row_dict.get('items', '[]'))
    except Exception:
        items_list = [row_dict.get('items', '')]

    return CartResponse(
        cart_id=row_dict['cart_id'],
        customer_name=row_dict['customer_name'],
        customer_type=row_dict['customer_type'],
        cart_value=round(row_dict['cart_value'], 2),
        items=items_list,
        payment_method_attempted=row_dict['payment_method_attempted'],
        failure_reason=row_dict['failure_reason'],
        abandoned_at=row_dict['abandoned_at'],
        recovered=bool(row_dict['recovered']),
        recovery_score=round(row_dict['recovery_score'], 4) if row_dict.get('recovery_score') is not None else None,
        customer_ltv_score=round(row_dict['customer_ltv_score'], 4) if row_dict.get('customer_ltv_score') is not None else None,
        priority_score=round(row_dict['priority_score'], 4) if row_dict.get('priority_score') is not None else None,
        segment=row_dict.get('segment')
    )

def parse_log_row(row: sqlite3.Row) -> RecoveryLogResponse:
    row_dict = dict(row)
    return RecoveryLogResponse(
        log_id=row_dict['log_id'],
        cart_id=row_dict['cart_id'],
        attempt_number=row_dict['attempt_number'],
        timestamp=row_dict['timestamp'],
        escalation_stage=row_dict['escalation_stage'],
        channel=row_dict['channel'],
        root_cause_diagnosis=row_dict['root_cause_diagnosis'],
        message_draft=row_dict['message_draft'],
        agent_reasoning=row_dict['agent_reasoning'],
        message_source=row_dict.get('message_source', 'gemini'),
        stopping_rule_triggered=bool(row_dict['stopping_rule_triggered']),
        stopping_reason=row_dict.get('stopping_reason'),
        simulated_outcome=row_dict['simulated_outcome']
    )

# -----------------------------------------------------------------------------
# REST ENDPOINTS
# -----------------------------------------------------------------------------

@app.get("/", tags=["Info"])
def read_root():
    """Root endpoint returning basic API metadata."""
    return {
        "app": "CartSaver AI REST API",
        "description": "Autonomous AI Agent for Payment Recovery & Abandoned Cart Scoring",
        "version": "1.0.0",
        "docs_url": "/docs",
        "health_url": "/health"
    }

@app.get("/health", tags=["Info"])
def health_check():
    """Health check endpoint confirming database status."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM carts")
    count = cursor.fetchone()[0]
    conn.close()
    return {
        "status": "healthy",
        "database": DB_NAME,
        "carts_count": count
    }

@app.get("/carts", response_model=List[CartResponse], tags=["Carts"])
def list_carts(
    segment: Optional[str] = Query(None, description="Filter by customer segment"),
    recovered: Optional[bool] = Query(None, description="Filter by recovery status"),
    failure_reason: Optional[str] = Query(None, description="Filter by payment failure reason")
):
    """List all carts with optional filtering parameters."""
    conn = get_db_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM carts WHERE 1=1"
    params = []

    if segment is not None:
        query += " AND segment = ?"
        params.append(segment)
    if recovered is not None:
        query += " AND recovered = ?"
        params.append(1 if recovered else 0)
    if failure_reason is not None:
        query += " AND failure_reason = ?"
        params.append(failure_reason)

    query += " ORDER BY abandoned_at DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    return [parse_cart_row(row) for row in rows]

@app.get("/carts/{cart_id}", response_model=CartDetailResponse, tags=["Carts"])
def get_cart_detail(cart_id: str = Path(..., description="UUID of the cart")):
    """Get full details for a specific cart including its recovery_log history."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM carts WHERE cart_id = ?", (cart_id,))
    cart_row = cursor.fetchone()
    if not cart_row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Cart with ID '{cart_id}' not found.")

    cursor.execute("SELECT * FROM recovery_log WHERE cart_id = ? ORDER BY attempt_number ASC", (cart_id,))
    log_rows = cursor.fetchall()
    conn.close()

    cart_data = parse_cart_row(cart_row)
    logs_data = [parse_log_row(r) for r in log_rows]

    return CartDetailResponse(cart=cart_data, logs=logs_data)

@app.get("/audit-log", response_model=List[RecoveryLogResponse], tags=["Audit Trail"])
def get_audit_log(
    limit: int = Query(50, ge=1, le=500, description="Number of log records to return"),
    offset: int = Query(0, ge=0, description="Offset position for pagination")
):
    """Paginated view of all recovery_log entries (agent audit trail)."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM recovery_log ORDER BY timestamp DESC LIMIT ? OFFSET ?", (limit, offset))
    rows = cursor.fetchall()
    conn.close()

    return [parse_log_row(row) for row in rows]

@app.get("/analytics/summary", response_model=AnalyticsSummaryResponse, tags=["Analytics"])
def get_analytics_summary():
    """Key portfolio metrics, financial risk, recovery rate %, and breakdowns."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Total carts
    cursor.execute("SELECT COUNT(*) FROM carts")
    total_carts = cursor.fetchone()[0] or 0

    # Total cart value at risk
    cursor.execute("SELECT SUM(cart_value) FROM carts")
    total_value_at_risk = round(cursor.fetchone()[0] or 0.0, 2)

    # Total value recovered
    cursor.execute("SELECT SUM(cart_value) FROM carts WHERE recovered = 1")
    total_value_recovered = round(cursor.fetchone()[0] or 0.0, 2)

    # Count recovered
    cursor.execute("SELECT COUNT(*) FROM carts WHERE recovered = 1")
    recovered_count = cursor.fetchone()[0] or 0

    recovery_rate_percent = round((recovered_count / total_carts * 100), 2) if total_carts > 0 else 0.0

    # Segment breakdown
    cursor.execute("""
        SELECT segment, COUNT(*) as count, SUM(cart_value) as total_val, AVG(recovery_score) as avg_score
        FROM carts
        GROUP BY segment
    """)
    seg_rows = cursor.fetchall()
    segment_breakdown = {}
    for r in seg_rows:
        seg_name = r['segment'] or "Unsegmented"
        segment_breakdown[seg_name] = {
            "count": r['count'],
            "total_value": round(r['total_val'] or 0.0, 2),
            "avg_recovery_score": round(r['avg_score'] or 0.0, 4)
        }

    # Stopping reason breakdown
    cursor.execute("""
        SELECT stopping_reason, COUNT(*) as count
        FROM recovery_log
        WHERE stopping_rule_triggered = 1
        GROUP BY stopping_reason
    """)
    stop_rows = cursor.fetchall()
    stopping_reason_breakdown = {}
    for r in stop_rows:
        reason_str = r['stopping_reason']
        if not reason_str:
            continue
        if "Low recovery score" in reason_str:
            cat = "Low Recovery Score (< 0.15)"
        elif "Low cart value" in reason_str:
            cat = "Low Cart Value (< ₹300) & Low Score"
        elif "Max 3 attempts" in reason_str:
            cat = "Max Attempts Exceeded"
        elif "already recovered" in reason_str.lower():
            cat = "Already Recovered"
        else:
            cat = reason_str.split("(")[0].strip() if "(" in reason_str else reason_str

        stopping_reason_breakdown[cat] = stopping_reason_breakdown.get(cat, 0) + r['count']


    # Escalation stage breakdown
    cursor.execute("""
        SELECT escalation_stage, COUNT(*) as count
        FROM recovery_log
        WHERE stopping_rule_triggered = 0
        GROUP BY escalation_stage
    """)
    stage_rows = cursor.fetchall()
    escalation_stage_breakdown = {r['escalation_stage']: r['count'] for r in stage_rows}

    conn.close()

    return AnalyticsSummaryResponse(
        total_carts=total_carts,
        total_value_at_risk=total_value_at_risk,
        total_value_recovered=total_value_recovered,
        recovery_rate_percent=recovery_rate_percent,
        segment_breakdown=segment_breakdown,
        stopping_reason_breakdown=stopping_reason_breakdown,
        escalation_stage_breakdown=escalation_stage_breakdown
    )

@app.post("/carts/{cart_id}/recover", response_model=SingleRecoveryAttemptResponse, tags=["Action"])
def trigger_manual_recovery(cart_id: str = Path(..., description="UUID of cart to recover")):
    """Manually trigger a fresh recovery attempt for a single cart using agent workflow logic."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM carts WHERE cart_id = ?", (cart_id,))
    cart_row = cursor.fetchone()
    if not cart_row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Cart with ID '{cart_id}' not found.")

    cart = dict(cart_row)

    # Determine attempt number
    cursor.execute("SELECT COUNT(*) FROM recovery_log WHERE cart_id = ? AND stopping_rule_triggered = 0", (cart_id,))
    attempts_made = cursor.fetchone()[0]
    next_attempt = attempts_made + 1

    # Check stopping rules
    stop_triggered, stop_reason = check_stopping_rules(cart, next_attempt)

    if stop_triggered:
        # Log stopping attempt
        log_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
            INSERT INTO recovery_log (
                log_id, cart_id, attempt_number, timestamp, escalation_stage, channel,
                root_cause_diagnosis, message_draft, agent_reasoning, message_source,
                stopping_rule_triggered, stopping_reason, simulated_outcome
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            log_id, cart_id, next_attempt, timestamp, "Stopped Before Attempt", "N/A",
            "N/A", "N/A", "Agent stopped contact based on risk/ROI rule", "N/A",
            1, stop_reason, "stopped"
        ))
        conn.commit()
        conn.close()

        return SingleRecoveryAttemptResponse(
            status="stopped",
            message=f"Recovery attempt halted by agent stopping rule: {stop_reason}",
            stopping_rule_triggered=True,
            stopping_reason=stop_reason,
            cart_recovered=bool(cart['recovered'])
        )

    # Proceed with recovery attempt
    stage, channel, guidelines = get_escalation_details(next_attempt, cart['payment_method_attempted'])
    diag, draft, reasoning, source = generate_recovery_content(cart, next_attempt, stage, guidelines)
    outcome = simulate_outcome(cart, next_attempt)

    is_recovered = (outcome == "recovered")
    if is_recovered:
        cursor.execute("UPDATE carts SET recovered = 1 WHERE cart_id = ?", (cart_id,))

    log_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    cursor.execute("""
        INSERT INTO recovery_log (
            log_id, cart_id, attempt_number, timestamp, escalation_stage, channel,
            root_cause_diagnosis, message_draft, agent_reasoning, message_source,
            stopping_rule_triggered, stopping_reason, simulated_outcome
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        log_id, cart_id, next_attempt, timestamp, stage, channel,
        diag, draft, reasoning, source, 0, None, outcome
    ))
    conn.commit()
    conn.close()

    return SingleRecoveryAttemptResponse(
        status="success",
        message=f"Attempt {next_attempt} completed with outcome '{outcome}'.",
        stopping_rule_triggered=False,
        attempt_number=next_attempt,
        escalation_stage=stage,
        channel=channel,
        root_cause_diagnosis=diag,
        message_draft=draft,
        agent_reasoning=reasoning,
        message_source=source,
        simulated_outcome=outcome,
        cart_recovered=is_recovered or bool(cart['recovered'])
    )

# -----------------------------------------------------------------------------
# RAZORPAY WEBHOOK PROCESSING & REAL-TIME CART RECOVERY
# -----------------------------------------------------------------------------

def map_razorpay_error(error_code: Optional[str], error_description: Optional[str], error_reason: Optional[str] = None) -> str:
    """Map Razorpay error codes and descriptions into CartSaver failure_reason categories."""
    combined = f"{error_code or ''} {error_description or ''} {error_reason or ''}".lower()

    if "insufficient" in combined or "low_balance" in combined:
        return "insufficient balance"
    elif "otp" in combined or "auth" in combined or "verification" in combined:
        return "OTP failed"
    elif "timeout" in combined or "gateway" in combined or "timed_out" in combined or "bank_network" in combined:
        return "bank timeout"
    elif "user" in combined or "cancel" in combined or "exit" in combined or "drop" in combined:
        return "user exited at payment"
    else:
        return "payment declined"

def normalize_payment_method(method_raw: Optional[str]) -> str:
    """Normalize raw payment method strings to standard categories."""
    m = (method_raw or "").lower()
    if "upi" in m:
        return "UPI"
    elif "card" in m:
        return "Card"
    elif "netbank" in m or "nb" in m:
        return "Netbanking"
    elif "wallet" in m:
        return "Wallet"
    return "UPI"

def score_and_segment_cart(cart_value: float, customer_type: str, payment_method: str, failure_reason: str):
    """
    Computes recovery_score, segment, customer_ltv_score, and priority_score
    for a real-time incoming cart from Razorpay webhook.
    """
    prob = 0.35
    if cart_value > 5000:
        prob += 0.20
    elif cart_value > 2000:
        prob += 0.10
    elif cart_value < 800:
        prob -= 0.10

    if customer_type == "high-value":
        prob += 0.25
    elif customer_type == "returning":
        prob += 0.12
    elif customer_type == "new":
        prob -= 0.08

    if failure_reason == "bank timeout":
        prob += 0.25
    elif failure_reason == "OTP failed":
        prob += 0.20
    elif failure_reason == "payment declined":
        prob += 0.05
    elif failure_reason == "insufficient balance":
        prob -= 0.15
    elif failure_reason == "user exited at payment":
        prob -= 0.25

    if payment_method == "UPI":
        prob += 0.05

    recovery_score = round(float(np.clip(prob, 0.05, 0.98)), 4)

    if recovery_score >= 0.60 and cart_value >= 3000:
        segment = "High-Value High-Intent"
    elif recovery_score >= 0.40 and failure_reason in ["bank timeout", "OTP failed"]:
        segment = "Payment-Failed-Technical"
    elif cart_value < 1500 or (recovery_score < 0.40 and failure_reason in ["user exited at payment", "insufficient balance"]):
        segment = "Price-Sensitive"
    else:
        segment = "Low-Intent"

    type_weight = {"high-value": 1.0, "returning": 0.6, "new": 0.3}.get(customer_type, 0.3)
    norm_val = min(1.0, max(0.0, (cart_value - 100.0) / (15000.0 - 100.0)))
    customer_ltv_score = round(float(np.clip(type_weight * 0.6 + norm_val * 0.4, 0.0, 1.0)), 4)

    priority_score = round(float(np.clip(recovery_score * 0.6 + customer_ltv_score * 0.4, 0.0, 1.0)), 4)

    return recovery_score, segment, customer_ltv_score, priority_score

@app.post("/webhooks/razorpay", tags=["Webhooks"])
async def handle_razorpay_webhook(
    request: Request,
    x_razorpay_signature: Optional[str] = Header(None, alias="X-Razorpay-Signature")
):
    """
    Receives and cryptographically verifies Razorpay webhook events (e.g. payment.failed),
    extracts payment failure parameters, ingests as new cart, scores it in real time,
    and immediately triggers the bounded recovery agent workflow.
    """
    raw_body = await request.body()
    webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "cartsaver_razorpay_secret_live_8912")

    if not x_razorpay_signature:
        raise HTTPException(status_code=400, detail="Missing required 'X-Razorpay-Signature' header.")

    expected_signature = hmac.new(
        webhook_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, x_razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature verification failed.")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {e}")

    event = payload.get("event", "")
    if event != "payment.failed":
        return {
            "status": "ignored",
            "message": f"Webhook event '{event}' received. Only 'payment.failed' triggers recovery workflow."
        }

    # Extract payment entity
    payment_payload = payload.get("payload", {}).get("payment", {})
    entity = payment_payload.get("entity", {})
    if not entity:
        raise HTTPException(status_code=400, detail="Missing payment entity in webhook payload.")

    # Amount in paise -> convert to INR rupees
    amount_paise = entity.get("amount", 0)
    cart_value = round(float(amount_paise) / 100.0, 2)
    if cart_value <= 0:
        cart_value = 1499.00

    error_code = entity.get("error_code")
    error_desc = entity.get("error_description")
    error_reason = entity.get("error_reason")
    raw_method = entity.get("method", "upi")

    payment_method = normalize_payment_method(raw_method)
    failure_reason = map_razorpay_error(error_code, error_desc, error_reason)

    # Extract customer info from notes/entity or fallback to clean placeholders
    notes = entity.get("notes", {}) or {}
    customer_name = notes.get("customer_name") or (entity.get("email", "").split("@")[0].capitalize() if entity.get("email") else "Valued Shopper")
    customer_type = notes.get("customer_type") or "returning"
    if customer_type not in ["high-value", "returning", "new"]:
        customer_type = "returning"

    items_list = notes.get("items") or ["Cart Checkout Order (Razorpay)"]
    if isinstance(items_list, str):
        try:
            items_list = json.loads(items_list)
        except Exception:
            items_list = [items_list]

    cart_id = str(uuid.uuid4())
    abandoned_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Score cart
    recovery_score, segment, ltv_score, priority_score = score_and_segment_cart(
        cart_value=cart_value,
        customer_type=customer_type,
        payment_method=payment_method,
        failure_reason=failure_reason
    )

    # Insert into database
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO carts (
            cart_id, customer_name, customer_type, cart_value, items,
            payment_method_attempted, failure_reason, abandoned_at, recovered,
            recovery_score, segment, customer_ltv_score, priority_score
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        cart_id, customer_name, customer_type, cart_value, json.dumps(items_list),
        payment_method, failure_reason, abandoned_at, 0,
        recovery_score, segment, ltv_score, priority_score
    ))
    conn.commit()

    # Construct cart dict for recovery agent
    cart = {
        "cart_id": cart_id,
        "customer_name": customer_name,
        "customer_type": customer_type,
        "cart_value": cart_value,
        "items": items_list,
        "payment_method_attempted": payment_method,
        "failure_reason": failure_reason,
        "abandoned_at": abandoned_at,
        "recovered": 0,
        "recovery_score": recovery_score,
        "segment": segment,
        "customer_ltv_score": ltv_score,
        "priority_score": priority_score
    }

    # Run through stopping rules and first recovery attempt
    stop_triggered, stop_reason = check_stopping_rules(cart, attempt_number=1)
    attempt_res = {}

    if stop_triggered:
        log_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
            INSERT INTO recovery_log (
                log_id, cart_id, attempt_number, timestamp, escalation_stage, channel,
                root_cause_diagnosis, message_draft, agent_reasoning, message_source,
                stopping_rule_triggered, stopping_reason, simulated_outcome
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            log_id, cart_id, 1, timestamp, "Stopped Before Attempt", "N/A",
            "N/A", "N/A", "Agent stopped contact based on risk/ROI rule", "N/A",
            1, stop_reason, "stopped"
        ))
        conn.commit()
        attempt_res = {
            "status": "stopped",
            "stopping_rule_triggered": True,
            "stopping_reason": stop_reason,
            "cart_recovered": False
        }
    else:
        stage, channel, guidelines = get_escalation_details(1, payment_method)
        diag, draft, reasoning, source = generate_recovery_content(cart, 1, stage, guidelines)
        outcome = simulate_outcome(cart, 1)

        is_recovered = (outcome == "recovered")
        if is_recovered:
            cursor.execute("UPDATE carts SET recovered = 1 WHERE cart_id = ?", (cart_id,))

        log_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
            INSERT INTO recovery_log (
                log_id, cart_id, attempt_number, timestamp, escalation_stage, channel,
                root_cause_diagnosis, message_draft, agent_reasoning, message_source,
                stopping_rule_triggered, stopping_reason, simulated_outcome
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            log_id, cart_id, 1, timestamp, stage, channel,
            diag, draft, reasoning, source, 0, None, outcome
        ))
        conn.commit()
        attempt_res = {
            "status": "contacted",
            "escalation_stage": stage,
            "channel": channel,
            "message_draft": draft,
            "message_source": source,
            "agent_reasoning": reasoning,
            "simulated_outcome": outcome,
            "cart_recovered": is_recovered
        }

    conn.close()

    return {
        "status": "success",
        "message": "Razorpay payment failure processed and evaluated by CartSaver AI.",
        "cart_id": cart_id,
        "transaction": {
            "payment_id": entity.get("id"),
            "amount_inr": cart_value,
            "method": payment_method,
            "raw_error_code": error_code,
            "mapped_failure_reason": failure_reason
        },
        "scoring": {
            "recovery_score": recovery_score,
            "segment": segment,
            "customer_ltv_score": ltv_score,
            "priority_score": priority_score
        },
        "recovery_action": attempt_res
    }

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
