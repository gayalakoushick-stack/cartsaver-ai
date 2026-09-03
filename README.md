# CartSaver AI

### Autonomous Revenue Recovery Agent for Indian E-Commerce

**Razorpay AI Buildathon 2026 — Track 3: AI Revenue Recovery**

---

## Overview

Every day, payments fail and carts get abandoned mid-checkout — and most of that revenue is recoverable if the right intervention happens quickly and intelligently. **CartSaver AI** is an autonomous agent that closes that loop end-to-end: it detects at-risk carts, diagnoses _why_ the payment actually failed, and runs a bounded, escalating recovery workflow — with every decision logged in a full audit trail.

This isn't a single LLM call wrapped in a UI. It's a multi-step reasoning agent: **score → diagnose → escalate → stop → log.**

---

## Why This Fits Track 3

Razorpay's brief for AI Revenue Recovery asks for more than problem detection — it explicitly asks: _"Don't just identify the problem. Show measured money recovered across a batch, with compliant escalation, stopping rules, and an audit trail."_

CartSaver AI was built directly against that bar:

| Requirement              | How CartSaver AI meets it                                                                 |
| ------------------------ | ----------------------------------------------------------------------------------------- |
| Measured money recovered | ₹4.6L+ recovered of ₹16.3L at risk (~28% recovery rate) across a 300-cart batch           |
| Compliant escalation     | 3-stage tiered contact — never one-shot spam                                              |
| Stopping rules           | Deterministic limits: max attempts, minimum recovery-score threshold, cost-vs-value check |
| Audit trail              | Every attempt's diagnosis, message, reasoning, and outcome is logged and viewable         |

---

## How It Works

1. **Detect** — ingest abandoned/failed-payment cart events (value, payment method, failure reason, customer history)
2. **Score** — a Logistic Regression model predicts each cart's recovery likelihood and assigns a segment (High-Value High-Intent / Payment-Failed-Technical / Price-Sensitive / Low-Intent)
3. **Diagnose root cause** — Gemini determines _why_ the payment failed and what kind of message would actually help — a declined card needs a different response than a bank timeout
4. **Recover, on a bounded ladder** — 3-stage escalation (gentle reminder → stronger nudge + incentive → final urgency-framed attempt), message drafted to match the diagnosed cause
5. **Stop, deterministically** — hard rules are enforced in plain Python, **not** left to the LLM's judgment, because compliance-critical decisions shouldn't be probabilistic
6. **Log everything** — every decision, message, and outcome is written to a full audit trail

---

## Key Design Decision: Deterministic Rules vs. LLM Judgment

A deliberate choice in this build: **the LLM never decides whether or when to stop contacting a customer.** Stopping rules and the escalation ladder are hardcoded in Python. Gemini's role is scoped strictly to the reasoning-heavy parts — diagnosing root cause and drafting the message — while every compliance-critical decision (how many times, how far, when to give up) is deterministic and auditable.

This is intentional: the right tool for each part of the problem, not "LLM does everything."

---

## Architecture

```
generate_carts.py   ->  synthetic cart data                        ->  cartsaver.db
score_carts.py       ->  recovery_score + segment (scikit-learn)     ->  cartsaver.db
recovery_agent.py    ->  root cause -> escalation -> stop -> log (Gemini)  ->  recovery_log
main.py               ->  FastAPI REST layer over cartsaver.db
```

## Tech Stack

**Python** · **SQLite** · **scikit-learn** (Logistic Regression) · **Google Gemini API** (structured output) · **FastAPI**

---

## Results

| Metric                       | Value                     |
| ---------------------------- | ------------------------- |
| Total carts processed        | 300                       |
| Total value at risk          | Rs. 16,31,265.83          |
| Total value recovered        | Rs. 4,64,675.01           |
| **Recovery rate**            | **28.0%**                 |
| Contact attempts made        | 777                       |
| Carts stopped before contact | 12 (compliance guardrail) |

_Recovery rate is deliberately calibrated to real-world cart-recovery benchmarks (15-35%), not inflated for demo effect._

---

## A Note on Data

All data is synthetically generated (via `faker`) with realistic Indian e-commerce distributions — cart values, failure-reason mix, customer segments — since real merchant data wasn't available for this build. The pipeline is designed to plug directly into real payment-failure events (e.g. Razorpay's test-mode webhook events) with no architectural changes.

---

## Running Locally

```bash
# Clone and set up
git clone <your-repo-url>
cd cartsaver-ai
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Add your environment variables (.env):
# GEMINI_API_KEY=your_key_here
# RAZORPAY_WEBHOOK_SECRET=cartsaver_razorpay_secret_live_8912

# Run the pipeline
python generate_carts.py
python score_carts.py
python recovery_agent.py

# Start the backend REST API
python main.py                # http://localhost:8000/docs

# Test Real-Time Razorpay Webhook Ingestion & Recovery Simulation
python simulate_webhook.py --scenario bank_timeout
python simulate_webhook.py --all-scenarios

# Run Automated Test Suite
pytest -v
```

---

**Built for the Razorpay AI Buildathon 2026 — Track 3: AI Revenue Recovery**
