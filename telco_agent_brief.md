# Claude Code Brief: Telco B2B Revenue Assurance Agent (Demo MVP)

## Context

This is a demo MVP for a keynote/client meeting with Beeline Kazakhstan (a large telco, 11.6M subscribers). The audience is from the finance / revenue assurance side. The goal is to demonstrate an agentic AI system that detects B2B revenue leakage by reasoning across multiple disconnected systems — the kind of leakage that lives in the seams between billing, pricing, and contracts.

The demo must feel like a serious, plausible agent — not a scripted automation. The agent must reason about what to check, not be told where to look.

Build target: 2-3 hours total.

---

## Architecture overview

Two-agent system, three tools, three data systems.

```
                 ┌──────────────────┐
                 │   ORCHESTRATOR   │
                 │  (plans scan,    │
                 │  aggregates,     │
                 │  writes report)  │
                 └────────┬─────────┘
                          │ dispatches cases
                          ▼
                 ┌──────────────────┐
                 │   INVESTIGATOR   │
                 │ (cross-source    │
                 │  detective work) │
                 └────────┬─────────┘
                          │
            ┌─────────────┼─────────────┐
            ▼             ▼             ▼
       query_billing  read_tariff   read_contract
          _db          _excel          _pdf
            │             │             │
            ▼             ▼             ▼
        SQLite        Excel         PDFs (4-5)
        (billing)     (tariffs)     (B2B contracts)
```

---

## Build in three phases

### PHASE 1 — Generate the dummy data

Create three data sources representing three real telco systems.

#### 1a. SQLite database `billing.db`

**Table `subscribers`** (~60 rows):
- `subscriber_id` (e.g. SUB_001)
- `phone_number` (Kazakhstan format: 7701XXXXXXX)
- `full_name`
- `account_type` — "B2C" or "B2B"
- `corporate_account_id` — nullable; links B2B subscribers to a corporate parent (e.g. CORP_001)
- `plan_id` — references the tariff catalog
- `plan_start_date`
- `status` — "active"

Split: ~50 B2C subscribers + ~10 B2B subscribers, the B2B ones distributed across 4-5 corporate accounts (CORP_001 through CORP_005).

Corporate account names (used in the contract PDFs and referenced informally):
- CORP_001 — MiningCo LLP
- CORP_002 — RegionalBank JSC
- CORP_003 — LogisticsKZ
- CORP_004 — RetailChain Holdings
- CORP_005 — EnergyPartners LLP

**Table `cdr_records`** (~200 rows):
- `cdr_id`
- `subscriber_id`
- `timestamp` — spread across April 2026
- `usage_mb`
- `domain` — realistic mix: youtube.com, netflix.com, whatsapp.com, beeline.kz, instagram.com, telegram.org, corporate VPN domains, etc.
- `applied_plan_id` — the plan the billing system actually used
- `billed_rate_kzt` — rate per MB applied
- `charge_kzt` — total charge

Distribute roughly 3-4 CDRs per subscriber on average across the month.

#### 1b. Excel tariff catalog `tariffs.xlsx`

One sheet, 8-10 standard plans, columns:
- `plan_id`
- `plan_name`
- `monthly_fee_kzt`
- `data_quota_mb`
- `overage_rate_kzt_per_mb` (standard rate, typically 0.50)
- `zero_rated_domains` — comma-separated list (always includes beeline.kz; some plans also include specific partners like youtube.com)
- `is_corporate_eligible` — true/false

Mix of B2C plans (UNLIM_30, BASIC_15, etc.) and B2B-eligible plans (CORP_STANDARD, CORP_PREMIUM, etc.).

#### 1c. Contract PDFs (4-5 files in `contracts/` folder)

One PDF per corporate account. Each PDF should contain:
- Header with client name and corporate_account_id
- Contract effective period (e.g. "Effective Jan 2026 – Dec 2026")
- 2-3 paragraphs of standard legal boilerplate (so the agent has to locate the relevant clause, not just read off the top)
- A clearly labeled **Negotiated Rates** section specifying:
  - Negotiated overage rate (e.g. ₸0.20/MB instead of standard ₸0.50)
  - Pooled data quota if any
  - Any contract-specific zero-rated domains (e.g. a corporate VPN domain)
- Signature block

Keep PDFs simple — generated with a Python PDF library is fine. Realistic enough to require parsing, not visually polished.

#### 1d. Plant exactly these 10 anomalies

**The data generator must know exactly where to plant these. The agent must NOT.**

| # | Anomaly type | Sources to detect | Subscriber | Description | Expected KZT impact |
|---|---|---|---|---|---|
| 1 | Plan mismatch (underbill) | DB only | SUB_007 (B2C) | Subscriber's `plan_id` in subscribers table is UNLIM_30, but their CDRs have `applied_plan_id` = BASIC_15 (cheaper) → undercharged | ~3,500 KZT |
| 2 | Plan mismatch (overbill) | DB only | SUB_019 (B2C) | Plan_id is BASIC_15 but CDRs applied UNLIM_30 charges (more expensive overage) | ~2,200 KZT |
| 3 | Zero-rate misapplication | DB + Excel | SUB_031 (B2C) | Multiple Netflix CDRs charged at 0.0 KZT, but Excel shows their plan does NOT include netflix.com as zero-rated | ~4,800 KZT |
| 4 | Zero-rate misapplication | DB + Excel | SUB_044 (B2C) | Instagram traffic zero-rated, but not on this plan's zero-rated list | ~1,900 KZT |
| 5 | Zero-rate misapplication | DB + Excel | SUB_052 (B2C) | Telegram traffic zero-rated, but not on this plan's zero-rated list | ~2,400 KZT |
| 6 | Contract rate violation | DB + PDF | SUB_055 (B2B, CORP_001 MiningCo) | Contract says ₸0.20/MB overage, but CDRs billed at ₸0.50/MB → overcharged client (dispute risk) | ~8,500 KZT |
| 7 | Contract rate violation | DB + PDF | SUB_057 (B2B, CORP_002 RegionalBank) | Contract specifies a special zero-rated banking domain that IS in contract, but CDRs to that domain were charged at standard rate | ~6,200 KZT |
| 8 | Contract rate violation | DB + PDF | SUB_060 (B2B, CORP_003 LogisticsKZ) | Pooled quota in contract is 500 GB, but billing is treating each line individually → overage charges that shouldn't exist | ~12,000 KZT |
| 9 | **False positive (must be CLEARED)** | DB + Excel + PDF | SUB_058 (B2B, CORP_002 RegionalBank) | CDRs billed at ₸0.18/MB which looks low vs Excel standard ₸0.50 — appears as underbilling — BUT the contract legitimately specifies ₸0.18/MB. Agent must check the contract and clear this. | 0 (cleared) |
| 10 | **False positive (must be CLEARED)** | DB + Excel + PDF | SUB_062 (B2B, CORP_004 RetailChain) | Zero-rated traffic to a domain that isn't in the standard Excel zero-rate list — looks like misapplication — BUT contract explicitly negotiated that domain as zero-rated. Agent must clear this. | 0 (cleared) |

**Total expected detected leakage (excluding cleared cases): ~41,500 KZT**

Subscribers not listed above should have clean, consistent billing.

---

### PHASE 2 — Build the agent system

#### Tools (Python functions exposed to the agent)

1. **`query_billing_db(sql: str) -> str`** — Executes a read-only SQL query against `billing.db` and returns results as a formatted table string. Should allow JOINs across subscribers and cdr_records.

2. **`read_tariff_excel(plan_id: str = None) -> str`** — Reads `tariffs.xlsx`. If `plan_id` is provided, returns details for that plan only; otherwise returns all plans.

3. **`read_contract_pdf(corporate_account_id: str) -> str`** — Locates the matching PDF in `contracts/` and returns its extracted text.

Use the Anthropic Python SDK with `claude-sonnet-4-5` (or current Sonnet) and the tool_use API.

#### Investigator agent — system prompt

```
You are a B2B Revenue Assurance Investigator for a major telecommunications operator.

Your job is to investigate specific subscribers or cases handed to you by the
orchestrator, and determine whether there is genuine revenue leakage, an
overbilling situation, or whether the case can be cleared.

You have domain knowledge that revenue leakage in telco commonly arises from:
- Incorrect tariff plans being applied during rating
- Charges (or absence of charges) that don't match the customer's actual plan
- Mismatches between standard pricing and negotiated B2B contract terms
- Pooled quota arrangements not being correctly enforced

You have three tools:
- query_billing_db: SQL access to subscribers and CDR records
- read_tariff_excel: the official tariff/pricing catalog
- read_contract_pdf: B2B corporate contract documents

Important: B2B subscribers may have negotiated rates in their contract that
differ from the standard Excel tariff. A rate that looks anomalous against the
standard tariff may be perfectly legitimate per the contract. Always check the
contract before concluding leakage exists on a B2B account.

For each case, return a structured finding:
- subscriber_id
- finding_type: "leakage", "overbilling", or "cleared"
- evidence: the trail of what you checked across which sources
- estimated_kzt_impact: number (0 if cleared)
- recommended_action: short string
```

#### Orchestrator agent — system prompt

```
You are a Revenue Assurance Manager for a major telecommunications operator.

Your job is to scan the subscriber base for potential revenue anomalies and
delegate suspicious cases to your Investigator for deep analysis. At the end,
you write an executive summary report.

You have access to:
- query_billing_db: to identify candidate cases worth investigating
- dispatch_to_investigator(subscriber_id, reason): hand a case to your investigator

You do not know in advance where anomalies exist. You must develop a scan
strategy: think about what patterns in billing data might indicate leakage
(rate inconsistencies, suspicious zero charges, plan/CDR mismatches), query
to find candidates, and dispatch the suspicious ones to the investigator.

After all investigations, aggregate the findings into an executive report with:
- Executive summary (1 paragraph)
- Confirmed leakage findings (grouped by type) with total KZT impact
- Cleared cases (cases that initially looked anomalous but were legitimate)
- Recommended actions
```

#### Reasoning loop

Standard tool-use loop: model produces tool calls, system executes them, results fed back, until the model produces its final text response. Investigator runs to completion per case; orchestrator runs the outer loop.

---

### PHASE 3 — Output

Print to terminal as formatted Markdown:

```
================================================================
  B2B REVENUE ASSURANCE REPORT — April 2026
================================================================

EXECUTIVE SUMMARY
[1 paragraph from the orchestrator]

CONFIRMED LEAKAGE — Total: KZT XX,XXX
─────────────────────────────────────
[grouped by anomaly type, each with subscriber, evidence, KZT impact, action]

CLEARED CASES — 2
─────────────────────────────────────
[each cleared case with subscriber, why it looked anomalous, why it was cleared]

RECOMMENDED ACTIONS
[from orchestrator]
================================================================
```

Also log the full agent trace (tool calls + responses) to `agent_trace.log` so we can show the reasoning during the demo if asked.

---

## Project structure

```
telco_agent_demo/
├── data/
│   ├── billing.db
│   ├── tariffs.xlsx
│   └── contracts/
│       ├── CORP_001_MiningCo.pdf
│       ├── CORP_002_RegionalBank.pdf
│       ├── CORP_003_LogisticsKZ.pdf
│       ├── CORP_004_RetailChain.pdf
│       └── CORP_005_EnergyPartners.pdf
├── generate_data.py       # Phase 1 — run once to create the data
├── tools.py               # Phase 2 — the three tool functions
├── agents.py              # Phase 2 — investigator + orchestrator
├── run_demo.py            # Phase 3 — main entry point
├── agent_trace.log        # generated at run time
├── requirements.txt
└── README.md
```

`requirements.txt`: anthropic, pandas, openpyxl, reportlab (for PDF generation), pypdf (for PDF reading).

---

## Acceptance criteria

The build is successful when:

1. `python generate_data.py` produces all data files with the 10 planted anomalies.
2. `python run_demo.py` runs the orchestrator + investigator end-to-end without manual intervention.
3. The final report identifies the 8 real anomalies with approximately correct KZT impact (totals within ±10% of expected).
4. The 2 false positives are explicitly listed in the "Cleared Cases" section with reasoning that references the contract.
5. The agent trace in `agent_trace.log` shows genuine investigation steps — multiple tool calls per case, cross-referencing across systems — not a scripted lookup pattern.
6. Total runtime under ~3 minutes per full report run.

---

## Out of scope for this build (deferred to v2)

- Gradio/Streamlit UI wrapper
- CDR gap detection (timestamp continuity)
- Russian-language output
- More than 5 corporate contracts
- Production-scale CDR volumes (the demo is honest about being illustrative)

---

## Key principles

- **The data generator knows where anomalies are. The agent does not.** That separation is what makes this a real test of agent reasoning rather than a scripted demo.
- **The false positives are the point.** An agent that only flags is a detector. An agent that flags AND correctly clears is judgment. Make sure both cleared cases work correctly — they are the demo's strongest moment.
- **Cross-source reasoning must be necessary, not decorative.** Anomalies 3-10 cannot be solved from a single source. Verify this in the agent trace.
