"""
Phase 2 — Tools exposed to the agent system.

Three read-only tools, each returning a string suitable for an LLM tool result:
  - query_billing_db(sql)
  - read_tariff_excel(plan_id=None)
  - read_contract_pdf(corporate_account_id)
"""

import os
import re
import sqlite3

import pandas as pd
from pypdf import PdfReader


DATA_DIR = "data"
DB_PATH = os.path.join(DATA_DIR, "billing.db")
EXCEL_PATH = os.path.join(DATA_DIR, "tariffs.xlsx")
CONTRACTS_DIR = os.path.join(DATA_DIR, "contracts")

PDF_FILENAMES = {
    "CORP_001": "CORP_001_MiningCo.pdf",
    "CORP_002": "CORP_002_RegionalBank.pdf",
    "CORP_003": "CORP_003_LogisticsKZ.pdf",
    "CORP_004": "CORP_004_RetailChain.pdf",
    "CORP_005": "CORP_005_EnergyPartners.pdf",
}

_DANGEROUS_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "create",
    "replace", "attach", "detach", "pragma", "vacuum", "reindex",
}


def _is_safe_select(sql: str) -> bool:
    s = sql.strip().lower()
    if not (s.startswith("select") or s.startswith("with")):
        return False
    words = set(re.findall(r"[a-z_]+", s))
    return not (words & _DANGEROUS_KEYWORDS)


def query_billing_db(sql: str) -> str:
    """Run a read-only SELECT against data/billing.db and return a text table."""
    sql = sql.strip().rstrip(";").strip()
    if not _is_safe_select(sql):
        return ("REJECTED: only read-only SELECT or WITH queries are permitted. "
                "Schema: subscribers(subscriber_id, phone_number, full_name, "
                "account_type, corporate_account_id, plan_id, plan_start_date, "
                "status); cdr_records(cdr_id, subscriber_id, timestamp, usage_mb, "
                "domain, applied_plan_id, billed_rate_kzt, charge_kzt).")
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        try:
            df = pd.read_sql_query(sql, conn)
        finally:
            conn.close()
    except Exception as e:
        return f"SQL ERROR: {type(e).__name__}: {e}"

    if df.empty:
        return "(0 rows returned)"

    truncated_note = ""
    if len(df) > 50:
        truncated_note = f"\n... ({len(df) - 50} more rows truncated; {len(df)} total)"
        df = df.head(50)

    with pd.option_context("display.max_colwidth", 80, "display.width", 200):
        body = df.to_string(index=False)
    return f"{body}{truncated_note}"


def read_tariff_excel(plan_id: str = None) -> str:
    """Read tariffs.xlsx. Optionally filter to one plan_id."""
    try:
        df = pd.read_excel(EXCEL_PATH, sheet_name="tariffs")
    except Exception as e:
        return f"EXCEL ERROR: {e}"

    if plan_id:
        plan_id = plan_id.strip()
        sub = df[df["plan_id"] == plan_id]
        if sub.empty:
            known = ", ".join(df["plan_id"].tolist())
            return f"No plan with plan_id='{plan_id}'. Known plans: {known}"
        return sub.to_string(index=False)

    with pd.option_context("display.max_colwidth", 80, "display.width", 220):
        return df.to_string(index=False)


def read_contract_pdf(corporate_account_id: str) -> str:
    """Extract and return text of the B2B contract PDF for a corporate account."""
    corp_id = corporate_account_id.strip().upper()
    filename = PDF_FILENAMES.get(corp_id)
    if not filename:
        known = ", ".join(PDF_FILENAMES.keys())
        return (f"No contract on file for corporate_account_id='{corporate_account_id}'. "
                f"Known accounts: {known}")
    path = os.path.join(CONTRACTS_DIR, filename)
    if not os.path.exists(path):
        return f"Contract file missing: {path}"
    try:
        reader = PdfReader(path)
        pages = [(p.extract_text() or "") for p in reader.pages]
    except Exception as e:
        return f"PDF ERROR: {e}"
    text = "\n".join(pages).strip()
    return f"[Contract for {corp_id} — {len(reader.pages)} page(s)]\n\n{text}"
