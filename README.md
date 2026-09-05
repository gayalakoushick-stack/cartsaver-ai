# CartSaver AI: Autonomous Revenue Recovery Decision Engine

### Track 03: AI Revenue Recovery (Razorpay AI Buildathon)

🚀 **Live Demo:** [https://cartsaver-ai-kl6omqq4ek3xeftmhnnt8z.streamlit.app](https://cartsaver-ai-kl6omqq4ek3xeftmhnnt8z.streamlit.app/)  
🔌 **Live Backend API:** [https://cartsaver-ai.onrender.com](https://cartsaver-ai.onrender.com/)

> *"Detect revenue at risk, diagnose why it's at risk, propose the right recovery action, and execute it under authoritative, deterministic safety limits."*

CartSaver AI is an explainable, closed-loop revenue recovery decision engine for failed payments and abandoned checkouts in Indian e-commerce. It combines an ML recovery-likelihood model, customer LTV prioritization, and a Google Gemini reasoning layer for root-cause diagnosis and message drafting — governed at every step by authoritative deterministic safety rules, a bounded escalation ladder, and a complete auditable ledger.

> **Important:** All data used in this build is synthetically generated (via `faker`) with realistic Indian e-commerce distributions. Recovery messages are drafted and logged, never actually dispatched through a live WhatsApp/SMS provider. The webhook pipeline processes real, cryptographically-signed Razorpay-shaped event payloads via a local simulator (`simulate_webhook.py`) — no real Razorpay merchant account or live transactions are involved.

---

## 1. System Architecture & Control Boundary

CartSaver AI enforces a strict architectural boundary between **AI Reasoning & Explainability** and **Authoritative Deterministic Safety & Execution**:

> *"Gemini proposes. Deterministic Python decides. The escalation ladder executes."*

```text
┌─────────────────────────── 1. AI SCORING & REASONING LAYER ───────────────────────────┐
│                                                                                       │
│   Ingest Failed/            ML Recovery          LTV + Priority     Gemini Root Cause │
│   Abandoned Cart    ──▶    Scoring Model   ──▶     Weighting    ──▶ Diagnosis+Message │
│ (webhook or batch)        (scikit-learn)       (customer value)   Draft (or fallback) │
│                                                                                       │
└──────────────────────────────────────┬────────────────────────────────────────────────┘
                                       ▼
┌─────────────────────── 2. AUTHORITATIVE DETERMINISTIC SAFETY LAYER ───────────────────┐
│                                                                                       │
│                           Stopping Rule Guardrail Check                               │
│        (max 3 attempts / recovery_score < 0.15 / cart_value < ₹300 & score < 0.4 /    │
│                               already recovered)                                      │
│                                       │                                               │
│                     ┌─────────────────┴─────────────────┐                             │
│                     ▼                                   ▼                             │
│                  BLOCKED                             ALLOWED                          │
│                     │                                   │                             │
│             Halt & Log Reason                Execute Escalation Stage                 │
│                                       (Gentle Reminder / Nudge+Incentive /            │
│                                                    Final Urgency)                     │
│                                                         │                             │
│                                             Simulate & Observe Outcome                │
│                                                         │                             │
│                                          Write Full Entry to recovery_log             │
│                                                   (Audit Trail)                       │
│                                                                                       │
└──────────────────────────────────────┬────────────────────────────────────────────────┘
                                       ▼
             Streamlit Dashboard (Overview / Carts Explorer / Audit Trail)
```

### The Safety Boundary Rule
> *"The LLM never decides whether or when to stop contacting a customer. Compliance-critical decisions are deterministic, not probabilistic."*

The stopping-rule engine (`check_stopping_rules` in `recovery_agent.py`) is strictly authoritative for:
- **Max attempts** (`attempt_number > 3` → BLOCKED)
- **Low recovery likelihood** (`recovery_score < 0.15` → BLOCKED, never contacted)
- **Negative cost-vs-value** (`cart_value < ₹300` AND `recovery_score < 0.4` → BLOCKED)
- **Already-recovered carts** (`recovered == True` → BLOCKED)

Every stopping decision, along with its exact reason, is written to the audit trail — nothing is silently skipped.

---

## 2. Direct Google Gemini Integration (`recovery_agent.py`)

CartSaver AI connects directly to Google's Gemini API (`gemini-2.5-flash-lite`) for the reasoning-heavy parts of the pipeline only — never for compliance decisions.

- **Structured decision output:** For each non-blocked cart, Gemini returns a `root_cause_diagnosis`, a personalized `message_draft` matched to the current escalation stage, and a one-line `agent_reasoning` explaining the approach.
- **Truthful source telemetry:** Every logged message carries a `message_source` field — `"gemini"` for a live, real-time reasoned response, or `"fallback"` when Gemini is unavailable.
- **Zero-downtime graceful fallback:** If Gemini errors out, times out, or hits a rate limit (`429 RESOURCE_EXHAUSTED`), the agent retries with backoff, then falls back to a safe, deterministic pre-written template rather than crashing or skipping the cart — the recovery workflow never stops because of an LLM failure.
- **Rate-aware pacing:** Requests are paced with a short delay and sequential (non-bursty) execution to stay within free-tier limits during full-batch runs.

---

## 3. Real-Time Webhook Simulation (`simulate_webhook.py`)

CartSaver AI exposes `POST /webhooks/razorpay`, which receives and cryptographically verifies (HMAC-SHA256) real Razorpay-shaped `payment.failed` webhook events, maps Razorpay's error codes to CartSaver's failure categories, and immediately runs the new cart through scoring and the first recovery attempt — in real time, not batch.

Since public tunneling tools were unavailable in the development environment, `simulate_webhook.py` was built to construct realistic, correctly-signed webhook payloads across five failure scenarios — bank timeout, insufficient balance, OTP failed, user exited, payment declined — and POST them locally, proving the full webhook-to-recovery pipeline end-to-end without needing a public tunnel:

```bash
python simulate_webhook.py --scenario bank_timeout
python simulate_webhook.py --all-scenarios
```

---

## 4. Bounded Closed-Loop Recovery Lifecycle

Every failed/abandoned cart flows through an explicit, auditable lifecycle:

1. **DETECT:** Ingest the cart event (value, payment method, failure reason, customer type), from either the batch pipeline or a live webhook.
2. **SCORE:** A Logistic Regression model predicts `recovery_score` and assigns a segment (High-Value High-Intent / Payment-Failed-Technical / Price-Sensitive / Low-Intent).
3. **PRIORITIZE:** A `customer_ltv_score` combines with `recovery_score` into a `priority_score`, so the agent processes high-value customers first.
4. **DIAGNOSE:** Gemini determines the specific root cause of the failure and drafts a message matched to it.
5. **GUARDRAIL CHECK:** The deterministic stopping-rule engine authoritatively allows or blocks the attempt.
6. **ESCALATE & ACT:** If allowed, the agent executes the current escalation stage (gentle reminder → stronger nudge + incentive → final urgency).
7. **OBSERVE:** The outcome (`recovered` / `attempt_failed`) is simulated and recorded.
8. **AUDIT & COMMIT:** The full entry — diagnosis, message, reasoning, source, outcome — is written to `recovery_log` for later inspection.

---

## 5. Batch Revenue Recovery Metrics (Real Benchmark)

Evaluated on a full production run of 300 real (synthetic) abandoned-cart records:

```text
=================================================================
             CARTSAVER AI RECOVERY BENCHMARK (300 Carts)
=================================================================
Total Carts Processed        : 300
Total Revenue At Risk (INR)  : ₹16,31,265.83
Total Contact Attempts Made  : 792
  • Gemini-sourced reasoning : 632 (79.8%)
  • Deterministic fallback   : 160 (20.2%)
Carts Stopped Before Contact : 12 (compliance guardrail)
Total Revenue Recovered (INR): ₹5,36,408.81
Recovery Rate                : 27.33%
=================================================================
```

*(Note: evaluated on synthetic transaction batches generated with realistic Indian payment-failure distributions. Recovery rate is deliberately calibrated to match real-world cart-recovery benchmarks of 15–35%, not inflated for demo effect.)*

---

## 6. Interactive Web Dashboard

CartSaver AI includes a Streamlit-based Recovery Operations Dashboard, served independently from the FastAPI backend and consuming it entirely over REST:

- **Portfolio Overview:** Live hero KPIs — total carts, value at risk, value recovered, recovery rate — plus segment, escalation-stage, and stopping-rule breakdown charts.
- **Carts Explorer:** A filterable (segment / status / failure reason) table of every cart, with recovery-score visualization and a one-click manual Recover trigger per row.
- **Audit Trail:** Select any cart and inspect its full chronological recovery timeline — root cause, message draft, agent reasoning, and outcome, attempt by attempt.
- **Run Full Pipeline:** A one-click control that regenerates the batch, re-scores, and re-runs the full recovery workflow end-to-end from the dashboard itself.

---

## 7. How to Run & Verify

### 1. Run the complete test suite
```bash
pytest -v
```
*(11 tests covering stopping-rule enforcement, LTV/priority scoring, webhook signature verification, error-code mapping, and full escalation-stage progression.)*

### 2. Run the batch pipeline
```bash
python generate_carts.py
python score_carts.py
python recovery_agent.py
```

### 3. Launch the backend API
```bash
python main.py
# Open http://localhost:8000/docs
```

### 4. Launch the dashboard (separate terminal)
```bash
streamlit run dashboard.py
# Open http://localhost:8501
```

### 5. Test real-time webhook ingestion (separate terminal, backend must be running)
```bash
python simulate_webhook.py --scenario bank_timeout
python simulate_webhook.py --all-scenarios
```

---

## 8. Environment Configuration (`.env`)

```env
GEMINI_API_KEY=your_gemini_api_key_here
RAZORPAY_WEBHOOK_SECRET=your_webhook_secret_here
```

If `GEMINI_API_KEY` is not set or the API is unreachable, CartSaver AI operates fully offline using deterministic fallback templates — the workflow never breaks due to a missing or failing key.

---

## 9. Architectural Notes & Production Upgrade Path

- **Storage:** Currently SQLite for simplicity and zero-setup evaluation. In production, this would move to a managed relational database (e.g. PostgreSQL) to support concurrent writes at scale.
- **Recovery scorer:** A transparent, explainable Logistic Regression model over cart value, customer type, payment method, failure reason, and time-since-abandonment — not a black box.
- **Rate limiting:** Currently in-process pacing with retry-and-backoff against Gemini's free tier. In production, this would move to a proper request queue with distributed rate limiting.
- **Messaging:** Recovery messages are currently drafted and logged, not dispatched. Production would integrate a real WhatsApp Business API / SMS provider once business template approval is obtained.
- **Webhooks:** The signature-verification and error-mapping logic in `main.py` is written against Razorpay's real webhook contract and is designed to accept live production webhooks with no architectural changes.

---

## Tech Stack

**Python** · **SQLite** · **scikit-learn** (Logistic Regression, Decision Tree) · **Google Gemini API** · **FastAPI** · **Streamlit** · **pytest** · Deployed on **Render** (backend) + **Streamlit Community Cloud** (dashboard)

---

**Built for the Razorpay AI Buildathon 2026 — Track 3: AI Revenue Recovery**
