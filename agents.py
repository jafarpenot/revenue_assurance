"""
Phase 2 — Investigator + Orchestrator agents.

Both run an Anthropic tool-use loop. The Investigator handles a single
subscriber case end-to-end; the Orchestrator scans the base and dispatches
suspicious cases to the Investigator via a synthetic dispatch tool.

All agent activity is streamed to the console AND written verbatim to
`agent_trace.log` so the full reasoning trail can be replayed.
"""

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import anthropic

from tools import query_billing_db, read_tariff_excel, read_contract_pdf


MODEL = "claude-sonnet-4-5"
MAX_INVESTIGATOR_TURNS = 12
MAX_ORCHESTRATOR_TURNS = 40
MAX_TOKENS = 4096
DISPATCH_PARALLELISM = 4  # max simultaneous investigators

_client = None
_client_lock = threading.Lock()
_log_fh = None
_output_lock = threading.Lock()  # serialise multi-line prints / log writes
_ui_callback = None  # optional: agents.py emits (label, kind, content) events here too


def set_ui_callback(cb):
    """Register a UI callback that receives every agent event (label, kind, content).
    Pass None to clear. Used by app.py to stream agent reasoning into the chat."""
    global _ui_callback
    _ui_callback = cb


# -----------------------------------------------------------------------------
# Logging / console plumbing
# -----------------------------------------------------------------------------
def _get_client():
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = anthropic.Anthropic()
    return _client


def init_log(path: str = "agent_trace.log"):
    global _log_fh
    _log_fh = open(path, "w", encoding="utf-8")
    _log_fh.write(f"=== Agent trace begun {datetime.now().isoformat()} ===\n\n")
    _log_fh.flush()


def close_log():
    global _log_fh
    if _log_fh is not None:
        _log_fh.write(f"\n=== Agent trace ended {datetime.now().isoformat()} ===\n")
        _log_fh.close()
        _log_fh = None


def log(msg: str):
    if _log_fh is None:
        return
    with _output_lock:
        _log_fh.write(msg)
        if not msg.endswith("\n"):
            _log_fh.write("\n")
        _log_fh.flush()


def _short(s, n: int = 500) -> str:
    s = str(s).strip()
    if len(s) > n:
        return s[:n] + f"  …[+{len(s) - n} chars truncated]"
    return s


def _say(label: str, kind: str, content: str):
    """Print a single agent event to the console with consistent formatting.

    Lock-guarded so multi-line blocks stay together when several investigators
    run in parallel."""
    glyphs = {
        "think": "[think]",
        "call":  "[call] ",
        "recv":  "[recv] ",
        "final": "[final]",
        "info":  "[info] ",
    }
    glyph = glyphs.get(kind, f"[{kind}]")
    text = str(content)
    with _output_lock:
        if "\n" in text:
            print(f"  {label:<14} {glyph}")
            for line in text.split("\n"):
                print(f"  {label:<14}     {line}")
        else:
            print(f"  {label:<14} {glyph} {text}")
    if _ui_callback is not None:
        try:
            _ui_callback(label, kind, text)
        except Exception:
            pass


# -----------------------------------------------------------------------------
# Tool definitions (sent to the API)
# -----------------------------------------------------------------------------
TOOL_QUERY_DB = {
    "name": "query_billing_db",
    "description": (
        "Execute a read-only SELECT (or WITH) query against the billing database "
        "and return the result as a formatted text table.\n\n"
        "Schema:\n"
        "  subscribers(subscriber_id, phone_number, full_name, account_type "
        "['B2C' or 'B2B'], corporate_account_id, plan_id, plan_start_date, status)\n"
        "  cdr_records(cdr_id, subscriber_id, timestamp, usage_mb, domain, "
        "applied_plan_id, billed_rate_kzt, charge_kzt)\n\n"
        "JOINs on subscriber_id are supported. Only SELECT queries are allowed."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "A read-only SQL SELECT or WITH statement."}
        },
        "required": ["sql"],
    },
}

TOOL_READ_TARIFF = {
    "name": "read_tariff_excel",
    "description": (
        "Read the official tariff catalog (tariffs.xlsx). Columns: plan_id, "
        "plan_name, monthly_fee_kzt, data_quota_mb, overage_rate_kzt_per_mb, "
        "zero_rated_domains (comma-separated list), is_corporate_eligible. "
        "Provide plan_id to look up one plan, or omit to return all plans."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string", "description": "Optional plan_id like 'UNLIM_30'."}
        },
        "required": [],
    },
}

TOOL_READ_CONTRACT = {
    "name": "read_contract_pdf",
    "description": (
        "Return the extracted text of the B2B corporate contract for a given "
        "corporate_account_id (e.g. 'CORP_001'). Contracts contain negotiated "
        "overage rates, pooled data quotas, and contract-specific zero-rated "
        "domains that override the standard tariff."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "corporate_account_id": {
                "type": "string",
                "description": "Corporate account identifier such as 'CORP_002'.",
            }
        },
        "required": ["corporate_account_id"],
    },
}

TOOL_DISPATCH = {
    "name": "dispatch_to_investigator",
    "description": (
        "Hand a specific subscriber case to the Investigator agent for deep "
        "cross-source analysis. The Investigator will query the billing data, "
        "tariff catalog, and corporate contract as needed and return a "
        "structured finding (finding_type ∈ {leakage, overbilling, cleared}, "
        "evidence trail, estimated KZT impact, recommended action). Use this "
        "for any subscriber whose billing looks anomalous and merits "
        "subscriber-level investigation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "subscriber_id": {"type": "string"},
            "reason": {
                "type": "string",
                "description": "Why you suspect this subscriber needs investigation.",
            },
        },
        "required": ["subscriber_id", "reason"],
    },
}

INVESTIGATOR_TOOLS = [TOOL_QUERY_DB, TOOL_READ_TARIFF, TOOL_READ_CONTRACT]
ORCHESTRATOR_TOOLS = [TOOL_QUERY_DB, TOOL_DISPATCH]


# -----------------------------------------------------------------------------
# System prompts
# -----------------------------------------------------------------------------
INVESTIGATOR_SYSTEM = """You are a B2B Revenue Assurance Investigator for a major telecommunications operator.

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

For each case, return a structured finding. End your final response with a
JSON code block on its own (no other code blocks) containing exactly these
fields:
- subscriber_id (string)
- finding_type (one of: "leakage", "overbilling", "cleared")
- evidence (string — the trail of what you checked across which sources)
- estimated_kzt_impact (number; 0 if cleared)
- recommended_action (short string)

Example final block:
```json
{"subscriber_id": "SUB_055", "finding_type": "overbilling", "evidence": "CDRs billed at 0.50/MB; CORP_001 contract specifies 0.20/MB; delta 28,400 MB * 0.30 = 8,520 KZT", "estimated_kzt_impact": 8520, "recommended_action": "Refund client and re-rate April CDRs at contract rate"}
```
"""

ORCHESTRATOR_SYSTEM = """You are a Revenue Assurance Manager for a major telecommunications operator.

Your job is to scan the subscriber base for potential revenue anomalies and
delegate suspicious cases to your Investigator for deep analysis. At the end,
you write an executive summary report.

You have access to:
- query_billing_db: to identify candidate cases worth investigating
- dispatch_to_investigator(subscriber_id, reason): hand a case to your investigator

You do not know in advance where anomalies exist. Your scan strategy:

- For all B2B subscribers: dispatch every one to the investigator. Negotiated
  contracts must always be reconciled against actual billing, even when the
  billing looks normal — a standard charge can be wrong if the contract
  specified otherwise. You yourself cannot read contracts (only the
  Investigator can), so contract-driven anomalies are invisible to your SQL
  alone; the Investigator must be the one to verify every B2B case.
- For B2C subscribers: query the billing database for internal anomalies
  (applied_plan_id vs registered plan_id, suspicious zero charges on domains
  the plan shouldn't zero-rate, unusual rate patterns) and dispatch only the
  ones that look suspicious. Don't dispatch clean B2C subscribers.

Always include the subscriber_id and a concrete one-line reason when
dispatching.

PARALLEL DISPATCH: investigations are independent of each other. When you
have several subscribers ready to dispatch, emit MULTIPLE
dispatch_to_investigator tool calls in the SAME assistant turn — they will
run in parallel and the results will all come back together. This is much
faster than dispatching one at a time. Prefer batches of 3-5 dispatches per
turn.

After all investigations are complete, write the final executive report in
EXACTLY the following markdown format (verbatim section headers):

EXECUTIVE SUMMARY
<one short paragraph summarising scan strategy, what was found, and total
financial impact. Numbers here MUST match the totals in the sections below.>

CONFIRMED LEAKAGE — Total: KZT <total>
<list every leakage finding. For each: subscriber_id, one-line evidence
summary citing the sources checked, KZT impact, recommended action. The
"Total" above MUST equal the sum of the per-finding KZT impacts in this
section.>

CONFIRMED OVERBILLING — Total: KZT <total>
<same format as the leakage section, for overbilling findings. The "Total"
MUST equal the sum of the per-finding KZT impacts in this section.>

CLEARED CASES — <count>
<for each cleared case: subscriber_id, what initially looked anomalous, why
it was cleared (must reference the contract). The count MUST equal the
number of items listed here.>

RECOMMENDED ACTIONS
<bulleted list of concrete remediation steps>

Rules for arithmetic and categories: every finding belongs to exactly one of
{leakage, overbilling, cleared} — do not invent additional categories. All
totals must match the sum of the listed items, with no rounding drift.
"""


# -----------------------------------------------------------------------------
# Generic tool-use loop
# -----------------------------------------------------------------------------
def _run_agent_loop(label, system, tools, user_message, tool_handler, max_turns):
    client = _get_client()
    messages = [{"role": "user", "content": user_message}]
    log("\n" + "=" * 78)
    log(f"[{label}] LOOP START  {datetime.now().isoformat()}")
    log("=" * 78)
    log(f"USER MESSAGE:\n{user_message}\n")

    final_text = ""
    last_response = None

    for turn in range(1, max_turns + 1):
        log(f"\n--- {label} turn {turn} ---")
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=tools,
            messages=messages,
        )
        last_response = response
        log(f"stop_reason: {response.stop_reason}")

        assistant_blocks = []
        tool_uses = []

        for block in response.content:
            if block.type == "text":
                if block.text.strip():
                    _say(label, "think", _short(block.text, 600))
                    log(f"[text]\n{block.text}")
                assistant_blocks.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                arg_str = json.dumps(block.input, ensure_ascii=False)
                _say(label, "call", f"{block.name}  {_short(arg_str, 300)}")
                log(f"[tool_use] {block.name}  input={arg_str}")
                assistant_blocks.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
                tool_uses.append(block)

        messages.append({"role": "assistant", "content": assistant_blocks})

        if response.stop_reason == "end_turn" or not tool_uses:
            final_text = "\n".join(b.text for b in response.content if b.type == "text")
            break

        def _exec(tu):
            try:
                return str(tool_handler(tu.name, tu.input))
            except Exception as e:
                return f"TOOL ERROR: {type(e).__name__}: {e}"

        if len(tool_uses) > 1:
            _say(label, "info", f"executing {len(tool_uses)} tool calls in parallel")
            with ThreadPoolExecutor(max_workers=min(len(tool_uses), DISPATCH_PARALLELISM)) as ex:
                results = list(ex.map(_exec, tool_uses))
        else:
            results = [_exec(tool_uses[0])]

        tool_results = []
        for tu, result_str in zip(tool_uses, results):
            _say(label, "recv", _short(result_str, 400))
            log(f"[tool_result] {tu.name}\n{result_str}")
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": result_str,
            })
        messages.append({"role": "user", "content": tool_results})
    else:
        log(f"[WARN] {label} hit max_turns={max_turns}")
        _say(label, "info", f"(reached max_turns={max_turns})")
        if last_response is not None:
            final_text = "\n".join(b.text for b in last_response.content if b.type == "text")

    log(f"\n[{label}] FINAL TEXT:\n{final_text}")
    log(f"[{label}] LOOP END  {datetime.now().isoformat()}")
    log("=" * 78)
    return final_text


# -----------------------------------------------------------------------------
# Investigator
# -----------------------------------------------------------------------------
def _investigator_tool_handler(name, inp):
    if name == "query_billing_db":
        return query_billing_db(inp["sql"])
    if name == "read_tariff_excel":
        return read_tariff_excel(inp.get("plan_id"))
    if name == "read_contract_pdf":
        return read_contract_pdf(inp["corporate_account_id"])
    return f"Unknown tool: {name}"


def run_investigator(subscriber_id: str, reason: str) -> str:
    label = f"INV/{subscriber_id}"
    _say(label, "info", f"START — reason: {reason}")
    user_msg = (
        f"Please investigate subscriber {subscriber_id}.\n"
        f"Reason for investigation: {reason}\n\n"
        f"Use your tools to verify across the billing database, the tariff "
        f"catalog, and (if applicable) the corporate contract. End with a "
        f"structured JSON finding as specified."
    )
    result = _run_agent_loop(
        label=label,
        system=INVESTIGATOR_SYSTEM,
        tools=INVESTIGATOR_TOOLS,
        user_message=user_msg,
        tool_handler=_investigator_tool_handler,
        max_turns=MAX_INVESTIGATOR_TURNS,
    )
    _say(label, "info", "DONE")
    return result


# -----------------------------------------------------------------------------
# Orchestrator
# -----------------------------------------------------------------------------
def _orchestrator_tool_handler(name, inp):
    if name == "query_billing_db":
        return query_billing_db(inp["sql"])
    if name == "dispatch_to_investigator":
        return run_investigator(inp["subscriber_id"], inp["reason"])
    return f"Unknown tool: {name}"


def run_orchestrator(billing_period: str = "April 2026", user_message: str = None) -> str:
    _say("ORCH", "info", f"START — scanning subscriber base for {billing_period}")
    user_msg = user_message or (
        f"Please scan the subscriber base for {billing_period} and identify "
        f"revenue leakage and overbilling issues. Develop your own scan "
        f"strategy: query the billing database to find candidates, dispatch "
        f"suspicious cases to the Investigator (one at a time), and once all "
        f"investigations are complete produce the final executive report in "
        f"the exact format specified in your instructions."
    )
    return _run_agent_loop(
        label="ORCH",
        system=ORCHESTRATOR_SYSTEM,
        tools=ORCHESTRATOR_TOOLS,
        user_message=user_msg,
        tool_handler=_orchestrator_tool_handler,
        max_turns=MAX_ORCHESTRATOR_TURNS,
    )
