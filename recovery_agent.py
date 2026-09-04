import sys
import os
import json
import sqlite3
import random
import time
import uuid
import argparse
import numpy as np
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Ensure UTF-8 stdout encoding on Windows
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            getattr(sys.stdout, "reconfigure")(encoding='utf-8')
    except Exception:
        pass

# Load environment variables
load_dotenv()
print(f"[STARTUP CHECK] .env file found: {os.path.exists('.env')}")
print(f"[STARTUP CHECK] GEMINI_API_KEY loaded: {bool(os.getenv('GEMINI_API_KEY'))}")
print(f"[STARTUP CHECK] Key starts with: {os.getenv('GEMINI_API_KEY', 'NOT_FOUND')[:6]}")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

genai_client = None
if GEMINI_API_KEY:
    try:
        from google import genai
        from google.genai import types
        genai_client = genai.Client(api_key=GEMINI_API_KEY)
        print("✓ Google GenAI Client (gemini-3.5-flash-lite) initialized successfully.", flush=True)
    except Exception as e:
        print(f"Warning: Could not initialize google-genai client ({e}).", flush=True)

DB_NAME = "cartsaver.db"

class GeminiRecoveryResponse(BaseModel):
    root_cause_diagnosis: str = Field(description="Short 1-2 sentence diagnosis of root cause and customer mindset")
    message_draft: str = Field(description="Personalized recovery message tailored to stage, segment, and failure reason")
    agent_reasoning: str = Field(description="One-line summary explaining the strategic reason for this message")

def create_recovery_log_table():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recovery_log (
            log_id TEXT PRIMARY KEY,
            cart_id TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            escalation_stage TEXT NOT NULL,
            channel TEXT NOT NULL,
            root_cause_diagnosis TEXT NOT NULL,
            message_draft TEXT NOT NULL,
            agent_reasoning TEXT NOT NULL,
            message_source TEXT NOT NULL,
            stopping_rule_triggered INTEGER NOT NULL,
            stopping_reason TEXT,
            simulated_outcome TEXT NOT NULL,
            FOREIGN KEY (cart_id) REFERENCES carts(cart_id)
        )
    """)
    cursor.execute("PRAGMA table_info(recovery_log)")
    columns = [col[1] for col in cursor.fetchall()]
    if "message_source" not in columns:
        cursor.execute("ALTER TABLE recovery_log ADD COLUMN message_source TEXT DEFAULT 'gemini'")
    conn.commit()
    conn.close()

def check_stopping_rules(cart, attempt_number):
    """
    Deterministic stopping rules (checked before EVERY attempt):
    1. Cart already recovered -> Stop
    2. Max 3 attempts per cart reached -> Stop
    3. recovery_score < 0.15 (not worth contacting) -> Stop
    4. cart_value < 300 AND recovery_score < 0.40 (cost exceeds expected value) -> Stop
    """
    if cart.get('recovered') == 1:
        return True, "Cart already recovered"
    if attempt_number > 3:
        return True, "Max 3 attempts per cart reached"

    rec_score = cart['recovery_score'] if cart.get('recovery_score') is not None else 0.0
    c_val = cart['cart_value'] if cart.get('cart_value') is not None else 0.0

    if rec_score < 0.15:
        return True, f"Low recovery score ({rec_score:.4f} < 0.15)"
    if c_val < 300 and rec_score < 0.40:
        return True, f"Low cart value (₹{c_val:.2f} < ₹300) with low score ({rec_score:.4f} < 0.40)"
    return False, None

def get_escalation_details(attempt_number, payment_method):
    """
    Escalation ladder (deterministic, by attempt_number):
    - Attempt 1: gentle reminder, no incentive
    - Attempt 2: stronger nudge + small incentive (alt payment method / free shipping)
    - Attempt 3: final attempt, urgency framing
    """
    channel = "WhatsApp" if payment_method in ["UPI", "Wallet"] else "SMS"
    
    if attempt_number == 1:
        stage = "Attempt 1: Gentle Reminder"
        guidelines = "Gentle reminder, friendly check-in, no discount or financial incentive."
    elif attempt_number == 2:
        stage = "Attempt 2: Stronger Nudge + Incentive"
        guidelines = "Stronger nudge, suggest alternate payment method (e.g. UPI QR code) or mention free express shipping."
    else:
        stage = "Attempt 3: Final Attempt + Urgency"
        guidelines = "Final attempt, high urgency framing, notification that cart reservation expires in 2 hours."
        
    return stage, channel, guidelines

DEBUG_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_log.txt")

def write_debug_log(message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception as e:
        print(f"Failed writing to debug log: {e}", flush=True)

def generate_recovery_content(cart, attempt_number, stage, guidelines, max_retries=2, retry_delay=1.0):
    """
    Calls Gemini API via google-genai SDK (gemini-3.5-flash-lite) using JSON mode with error handling.
    Retries up to max_retries times with a short delay on failure.
    If all retries fail or client is unavailable, falls back to deterministic default message.
    Returns: (root_cause_diagnosis, message_draft, agent_reasoning, message_source)
    """
    prompt = f"""You are CartSaver AI, an autonomous payment recovery agent for Indian e-commerce.
Cart Details:
- Customer Name: {cart['customer_name']}
- Customer Type: {cart['customer_type']}
- Cart Value: ₹{cart['cart_value']:.2f}
- Items: {cart['items']}
- Payment Method Attempted: {cart['payment_method_attempted']}
- Failure Reason: {cart['failure_reason']}
- Customer Segment: {cart['segment']}
- Recovery Score: {cart['recovery_score']:.4f}

Current Escalation Stage: {stage} (Attempt {attempt_number} of 3)
Stage Guidelines: {guidelines}

Task:
Respond in JSON format with exactly three string fields:
1. `root_cause_diagnosis`: A 1-2 sentence diagnosis of why payment failed and customer mindset.
2. `message_draft`: A realistic, highly personalized message suitable for WhatsApp/SMS matching the escalation stage and Indian e-commerce context.
3. `agent_reasoning`: A single concise sentence explaining your strategic decision making.
"""

    last_error = None
    if genai_client:
        for attempt_idx in range(max_retries + 1):
            try:
                from google.genai import types
                response = genai_client.models.generate_content(
                    model='gemini-3.5-flash-lite',
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.7,
                    ),
                )
                if response and response.text:
                    data = json.loads(response.text)
                    diag = data.get("root_cause_diagnosis", "Friction during payment authentication.")
                    draft = data.get("message_draft", f"Hi {cart['customer_name'].split()[0]}, tap to complete your order.")
                    reasoning = data.get("agent_reasoning", "Engaged customer with stage-appropriate messaging.")
                    time.sleep(2)  # Delay between Gemini API calls to stay within free-tier rate limits
                    return diag, draft, reasoning, "gemini"
                else:
                    last_error = "Gemini returned empty or invalid response text."
            except Exception as e:
                last_error = e
                err_str = str(e)
                # If rate limited (429 / RESOURCE_EXHAUSTED), wait briefly to allow quota recovery
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "Quota exceeded" in err_str:
                    time.sleep(5)
                elif attempt_idx < max_retries:
                    time.sleep(retry_delay)
                else:
                    break
        error_msg = f"Gemini call bypassed/failed, using fallback. Reason: {last_error}"
        write_debug_log(error_msg)
    else:
        error_msg = "Gemini client not initialized (GEMINI_API_KEY not set), using fallback."
        write_debug_log(error_msg)

    return fallback_content_generator(cart, attempt_number, stage)

def fallback_content_generator(cart, attempt_number, stage):
    name = cart.get('customer_name', 'Customer').split()[0]
    reason = cart.get('failure_reason', 'technical glitch')
    method = cart.get('payment_method_attempted', 'selected payment method')
    val = cart.get('cart_value', 0.0)
    cart_id_short = str(cart.get('cart_id', ''))[:8]
    
    if reason in ["bank timeout", "OTP failed"]:
        diag = f"Transaction failed due to technical friction ({reason}) during {method} authentication."
    elif reason == "insufficient balance":
        diag = f"Customer encountered account balance constraints during payment via {method}."
    elif reason == "user exited at payment":
        diag = f"Customer abandoned checkout due to price hesitation or exit intent at payment page."
    else:
        diag = f"Payment declined by issuing bank during {method} processing."
        
    if attempt_number == 1:
        msg = f"Hi {name}, we noticed your payment of ₹{val:.2f} via {method} couldn't complete due to {reason}. Click here to easily resume your order: https://cartsaver.in/pay/{cart_id_short}"
        reasoning = f"Deterministic Fallback: Attempt 1 uses gentle reassurance for {reason} without discount."
    elif attempt_number == 2:
        msg = f"Hi {name}, we saved your cart items! Try paying with UPI for instant checkout + Free Express Shipping: https://cartsaver.in/pay/{cart_id_short}"
        reasoning = "Deterministic Fallback: Attempt 2 offers alternative payment option (UPI) and free shipping incentive."
    else:
        msg = f"FINAL NOTICE: Hi {name}, your reserved items (Total: ₹{val:.2f}) will return to stock in 2 hours. Complete your order now: https://cartsaver.in/pay/{cart_id_short}"
        reasoning = "Deterministic Fallback: Attempt 3 uses urgency framing with cart reservation expiration countdown."
        
    return diag, msg, reasoning, "fallback"

def simulate_outcome(cart, attempt_number):
    """
    Simulate recovery outcome realistically:
    Base per-attempt probability = recovery_score * 0.15
    Escalation boost: Attempt 1 (+0.00), Attempt 2 (+0.02), Attempt 3 (+0.04)
    Target overall cumulative recovery rate: 20%–35%
    """
    rec_score = cart['recovery_score'] if cart.get('recovery_score') is not None else 0.0
    base_prob = rec_score * 0.15
    boost = (attempt_number - 1) * 0.02
    effective_prob = min(0.40, base_prob + boost)
    
    success = (random.random() < effective_prob)
    return "recovered" if success else "attempt_failed"

def process_cart(cart):
    """Process a single cart through its bounded recovery workflow."""
    cart = dict(cart)
    cart_logs = []
    cart_recovered = False

    for attempt_number in range(1, 4):
        stop_triggered, stop_reason = check_stopping_rules(cart, attempt_number)

        if stop_triggered:
            if attempt_number == 1:
                cart_logs.append({
                    'is_stop': True,
                    'log_id': str(uuid.uuid4()),
                    'cart_id': cart['cart_id'],
                    'attempt_number': attempt_number,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'escalation_stage': "Stopped Before Attempt",
                    'channel': "N/A",
                    'root_cause_diagnosis': "N/A",
                    'message_draft': "N/A",
                    'agent_reasoning': "Agent stopped contact based on risk/ROI rule",
                    'message_source': "N/A",
                    'stopping_rule_triggered': 1,
                    'stopping_reason': stop_reason,
                    'simulated_outcome': "stopped"
                })
            break

        stage, channel, guidelines = get_escalation_details(attempt_number, cart['payment_method_attempted'])
        diag, draft, reasoning, source = generate_recovery_content(cart, attempt_number, stage, guidelines)
        outcome = simulate_outcome(cart, attempt_number)

        if outcome == "recovered":
            cart['recovered'] = 1
            cart_recovered = True

        cart_logs.append({
            'is_stop': False,
            'log_id': str(uuid.uuid4()),
            'cart_id': cart['cart_id'],
            'attempt_number': attempt_number,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'escalation_stage': stage,
            'channel': channel,
            'root_cause_diagnosis': diag,
            'message_draft': draft,
            'agent_reasoning': reasoning,
            'message_source': source,
            'stopping_rule_triggered': 0,
            'stopping_reason': None,
            'simulated_outcome': outcome
        })

        if cart_recovered:
            break

    return cart_logs, cart_recovered, cart['cart_id']

def run_recovery_workflow(limit=None):
    random.seed(42)
    np.random.seed(42)

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Reset recovery_log and carts table for clean simulation
    cursor.execute("DELETE FROM recovery_log")
    cursor.execute("UPDATE carts SET recovered = 0")
    conn.commit()

    # Order carts by priority_score descending (combining recovery score and customer LTV)
    cursor.execute("PRAGMA table_info(carts)")
    cols = [col[1] for col in cursor.fetchall()]
    order_clause = "ORDER BY priority_score DESC, recovery_score DESC" if "priority_score" in cols else ""
    limit_clause = f"LIMIT {int(limit)}" if limit is not None and limit > 0 else ""
    cursor.execute(f"SELECT * FROM carts {order_clause} {limit_clause}".strip())
    carts = cursor.fetchall()
    conn.close()

    total_carts = len(carts)
    print(f"\nProcessing {total_carts} carts through Bounded Recovery Workflow (sorted by priority_score DESC)...", flush=True)

    # Process carts sequentially to respect free-tier rate limits with 2s delay
    all_logs = []
    recovered_cart_ids = []
    
    with ThreadPoolExecutor(max_workers=1) as executor:
        results = executor.map(process_cart, carts)
        for cart_logs, is_recovered, cart_id in results:
            all_logs.extend(cart_logs)
            if is_recovered:
                recovered_cart_ids.append(cart_id)

    # Aggregations
    total_attempts_made = sum(1 for log in all_logs if not log['is_stop'])
    gemini_attempts_count = sum(1 for log in all_logs if not log['is_stop'] and log.get('message_source') == 'gemini')
    fallback_attempts_count = sum(1 for log in all_logs if not log['is_stop'] and log.get('message_source') == 'fallback')
    carts_recovered_count = len(recovered_cart_ids)
    stopped_logs = [log for log in all_logs if log['is_stop']]
    stopped_carts_count = len(stopped_logs)

    stopping_reasons_counter = {}
    for log in stopped_logs:
        reason = log['stopping_reason']
        stopping_reasons_counter[reason] = stopping_reasons_counter.get(reason, 0) + 1

    attempts_by_stage = {1: 0, 2: 0, 3: 0}
    for log in all_logs:
        if not log['is_stop']:
            attempts_by_stage[log['attempt_number']] += 1

    # Save to database
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    logs_tuple_list = [
        (
            log['log_id'], log['cart_id'], log['attempt_number'], log['timestamp'],
            log['escalation_stage'], log['channel'], log['root_cause_diagnosis'],
            log['message_draft'], log['agent_reasoning'], log['message_source'],
            log['stopping_rule_triggered'], log['stopping_reason'], log['simulated_outcome']
        )
        for log in all_logs
    ]

    cursor.executemany("""
        INSERT INTO recovery_log (
            log_id, cart_id, attempt_number, timestamp, escalation_stage, channel,
            root_cause_diagnosis, message_draft, agent_reasoning, message_source,
            stopping_rule_triggered, stopping_reason, simulated_outcome
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, logs_tuple_list)

    for c_id in recovered_cart_ids:
        cursor.execute("UPDATE carts SET recovered = 1 WHERE cart_id = ?", (c_id,))

    conn.commit()
    conn.close()

    # Print Executive Summary Report
    print("\n" + "="*65, flush=True)
    print("         BOUNDED RECOVERY WORKFLOW SUMMARY REPORT        ", flush=True)
    print("="*65, flush=True)
    print(f"Total Carts Evaluated            : {total_carts}", flush=True)
    print(f"Total Contact Attempts Made      : {total_attempts_made}", flush=True)
    print(f"  • Attempts via Gemini AI       : {gemini_attempts_count} ({(gemini_attempts_count/total_attempts_made)*100:.1f}%)" if total_attempts_made > 0 else "  • Attempts via Gemini AI       : 0", flush=True)
    print(f"  • Attempts via Fallback Path   : {fallback_attempts_count} ({(fallback_attempts_count/total_attempts_made)*100:.1f}%)" if total_attempts_made > 0 else "  • Attempts via Fallback Path   : 0", flush=True)
    print(f"Carts Successfully Recovered     : {carts_recovered_count} ({(carts_recovered_count/total_carts)*100:.1f}%)", flush=True)
    print(f"Carts Stopped Before Contact     : {stopped_carts_count} ({(stopped_carts_count/total_carts)*100:.1f}%)\n", flush=True)

    print("--- Breakdown of Stopping Reasons ---", flush=True)
    for reason, count in stopping_reasons_counter.items():
        print(f"  • {reason:<52}: {count:>3} carts", flush=True)

    print("\n--- Breakdown of Contact Attempts by Escalation Stage ---", flush=True)
    for stage_num, count in attempts_by_stage.items():
        stage_name = get_escalation_details(stage_num, 'UPI')[0]
        print(f"  • Stage {stage_num} ({stage_name}): {count:>3} attempts", flush=True)

    print("="*65 + "\n", flush=True)

    print_sample_audit_logs()
    print_final_message_source_summary()

def print_sample_audit_logs():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT log_id, cart_id, attempt_number, escalation_stage, channel,
               root_cause_diagnosis, message_draft, agent_reasoning, message_source, simulated_outcome
        FROM recovery_log
        WHERE stopping_rule_triggered = 0
        ORDER BY RANDOM()
        LIMIT 3
    """)
    samples = cursor.fetchall()
    conn.close()

    print("="*65, flush=True)
    print("               SAMPLE AGENT AUDIT LOG ENTRIES               ", flush=True)
    print("="*65, flush=True)
    for idx, sample in enumerate(samples, 1):
        print(f"\n[Sample Log #{idx}]", flush=True)
        print(f"  Cart ID           : {sample[1]}", flush=True)
        print(f"  Attempt & Stage   : Attempt {sample[2]} ({sample[3]})", flush=True)
        print(f"  Channel           : {sample[4]}", flush=True)
        print(f"  Message Source    : {sample[8]}", flush=True)
        print(f"  Root Cause        : {sample[5]}", flush=True)
        print(f"  Message Draft     : {sample[6]}", flush=True)
        print(f"  Agent Reasoning   : {sample[7]}", flush=True)
        print(f"  Simulated Outcome : {sample[9]}", flush=True)
    print("="*65 + "\n", flush=True)

def print_final_message_source_summary():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT message_source, COUNT(*) 
        FROM recovery_log 
        WHERE message_source IN ('gemini', 'fallback') 
        GROUP BY message_source
    """)
    counts = dict(cursor.fetchall())
    conn.close()

    gemini_count = counts.get("gemini", 0)
    fallback_count = counts.get("fallback", 0)
    total_messages = gemini_count + fallback_count

    gemini_pct = (gemini_count / total_messages * 100.0) if total_messages > 0 else 0.0
    fallback_pct = (fallback_count / total_messages * 100.0) if total_messages > 0 else 0.0

    print("="*65, flush=True)
    print("             FINAL MESSAGE SOURCE COUNT SUMMARY              ", flush=True)
    print("="*65, flush=True)
    print(f"Total Log Entries (Contact Messages): {total_messages}", flush=True)
    print(f"  • message_source == 'gemini'   : {gemini_count:>5} ({gemini_pct:5.1f}%)", flush=True)
    print(f"  • message_source == 'fallback' : {fallback_count:>5} ({fallback_pct:5.1f}%)", flush=True)
    print("="*65 + "\n", flush=True)

def main():
    parser = argparse.ArgumentParser(description="Bounded Recovery Workflow for abandoned carts.")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit on the number of carts to process (ordered by priority_score descending). Defaults to all carts."
    )
    args = parser.parse_args()

    create_recovery_log_table()
    run_recovery_workflow(limit=args.limit)

if __name__ == "__main__":
    main()
