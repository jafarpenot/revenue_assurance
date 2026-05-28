"""
Phase 1 — Generate the dummy data for the Telco B2B Revenue Assurance demo.

Produces:
  data/billing.db           SQLite with subscribers + cdr_records
  data/tariffs.xlsx         Standard tariff catalog
  data/contracts/*.pdf      5 corporate contract PDFs

Plants exactly 10 anomalies (8 real + 2 false positives) per the brief.
"""

import os
import sqlite3
import random
from datetime import datetime, timedelta

import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.units import inch


random.seed(42)

DATA_DIR = "data"
CONTRACTS_DIR = os.path.join(DATA_DIR, "contracts")
DB_PATH = os.path.join(DATA_DIR, "billing.db")
EXCEL_PATH = os.path.join(DATA_DIR, "tariffs.xlsx")

os.makedirs(CONTRACTS_DIR, exist_ok=True)
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)


# -----------------------------------------------------------------------------
# Tariff catalog
# -----------------------------------------------------------------------------
TARIFFS = [
    # plan_id,         plan_name,           monthly, quota_mb, overage, zero_rated,                                  corp_eligible
    ("BASIC_15",       "Basic 15GB",          5000,    15000,    0.30, "beeline.kz",                                  False),
    ("UNLIM_30",       "Unlimited 30GB",     10000,    30000,    0.50, "beeline.kz,youtube.com",                      False),
    ("SOCIAL_25",      "Social Plus",         7000,    25000,    0.40, "beeline.kz,whatsapp.com,instagram.com",       False),
    ("VIDEO_50",       "Video Stream",       15000,    50000,    0.45, "beeline.kz,youtube.com,netflix.com",          False),
    ("LITE_5",         "Lite 5GB",            2500,     5000,    0.50, "beeline.kz",                                  False),
    ("TOURIST_7",      "Tourist Pack",        3000,     7000,    0.60, "beeline.kz",                                  False),
    ("CORP_STANDARD",  "Corporate Standard", 25000,   100000,    0.50, "beeline.kz",                                  True),
    ("CORP_PREMIUM",   "Corporate Premium",  60000,   300000,    0.40, "beeline.kz",                                  True),
    ("CORP_POOLED",    "Corporate Pooled",  100000,   500000,    0.35, "beeline.kz",                                  True),
]

PLAN_RATES = {row[0]: row[4] for row in TARIFFS}
PLAN_ZERO_RATED = {row[0]: [d.strip() for d in row[5].split(",")] for row in TARIFFS}

df_tariffs = pd.DataFrame(TARIFFS, columns=[
    "plan_id", "plan_name", "monthly_fee_kzt", "data_quota_mb",
    "overage_rate_kzt_per_mb", "zero_rated_domains", "is_corporate_eligible",
])
df_tariffs.to_excel(EXCEL_PATH, sheet_name="tariffs", index=False)
print(f"[OK] Tariff catalog: {EXCEL_PATH}  ({len(TARIFFS)} plans)")


# -----------------------------------------------------------------------------
# Corporate accounts & contract terms
# -----------------------------------------------------------------------------
CORPS = {
    "CORP_001": "MiningCo LLP",
    "CORP_002": "RegionalBank JSC",
    "CORP_003": "LogisticsKZ",
    "CORP_004": "RetailChain Holdings",
    "CORP_005": "EnergyPartners LLP",
}

CONTRACT_TERMS = {
    # Only CORP_003 has true pooled-quota semantics (anomaly 8 hinges on this).
    # The other corps simply have a per-line negotiated overage rate.
    "CORP_001": {"overage": 0.20, "pooled_gb": None, "extra_zero_rated": ["mining-vpn.kz"]},
    "CORP_002": {"overage": 0.18, "pooled_gb": None, "extra_zero_rated": ["bank-internal.kz"]},
    "CORP_003": {"overage": 0.25, "pooled_gb": 500,  "extra_zero_rated": ["logistics-fleet.kz"]},
    "CORP_004": {"overage": 0.30, "pooled_gb": None, "extra_zero_rated": ["retail-pos.kz"]},
    "CORP_005": {"overage": 0.22, "pooled_gb": None, "extra_zero_rated": []},
}

PDF_FILENAMES = {
    "CORP_001": "CORP_001_MiningCo.pdf",
    "CORP_002": "CORP_002_RegionalBank.pdf",
    "CORP_003": "CORP_003_LogisticsKZ.pdf",
    "CORP_004": "CORP_004_RetailChain.pdf",
    "CORP_005": "CORP_005_EnergyPartners.pdf",
}


# -----------------------------------------------------------------------------
# Subscriber roster
# -----------------------------------------------------------------------------
# 54 B2C (SUB_001 .. SUB_054) + 10 B2B (SUB_055 .. SUB_064) = 64 total.
# The B2B range is sized to accommodate SUB_062 (false positive 10).

B2C_PLANS = ["BASIC_15", "UNLIM_30", "SOCIAL_25", "VIDEO_50", "LITE_5", "TOURIST_7"]

# Anomaly-specific plan assignments (must be exact)
B2C_PLAN_OVERRIDES = {
    "SUB_007": "UNLIM_30",   # anomaly 1
    "SUB_019": "BASIC_15",   # anomaly 2
    "SUB_031": "BASIC_15",   # anomaly 3 (plan does NOT zero-rate netflix.com)
    "SUB_044": "BASIC_15",   # anomaly 4 (plan does NOT zero-rate instagram.com)
    "SUB_052": "UNLIM_30",   # anomaly 5 (plan does NOT zero-rate telegram.org)
}

B2B_MAP = {
    "SUB_055": "CORP_001", "SUB_056": "CORP_001",
    "SUB_057": "CORP_002", "SUB_058": "CORP_002",
    "SUB_059": "CORP_003", "SUB_060": "CORP_003",
    "SUB_061": "CORP_004", "SUB_062": "CORP_004",
    "SUB_063": "CORP_005", "SUB_064": "CORP_005",
}

B2B_PLANS = {
    "SUB_055": "CORP_STANDARD",  # anomaly 6
    "SUB_056": "CORP_STANDARD",  # clean
    "SUB_057": "CORP_PREMIUM",   # anomaly 7
    "SUB_058": "CORP_PREMIUM",   # false positive 9
    "SUB_059": "CORP_POOLED",    # clean (CORP_003 is pooled)
    "SUB_060": "CORP_POOLED",    # anomaly 8
    "SUB_061": "CORP_STANDARD",  # clean
    "SUB_062": "CORP_STANDARD",  # false positive 10
    "SUB_063": "CORP_PREMIUM",   # clean
    "SUB_064": "CORP_STANDARD",  # clean
}

B2B_NAMES = {
    "SUB_055": "Daniyar Akhmetov",     "SUB_056": "Anel Bekzhanova",
    "SUB_057": "Marat Iskakov",        "SUB_058": "Gulnara Sapieva",
    "SUB_059": "Ruslan Dzhumagaliev",  "SUB_060": "Aida Nurpeisova",
    "SUB_061": "Bolat Karimov",        "SUB_062": "Zhanar Tashenova",
    "SUB_063": "Yerbol Kassymov",      "SUB_064": "Saule Aitzhanova",
}

B2C_NAMES = [
    "Aigerim Bekova", "Dauren Nurlanov", "Madina Sultanova", "Yerlan Ospanov",
    "Aliya Tursunova", "Nurzhan Kalievich", "Kamila Iskakova", "Bauyrzhan Aliev",
    "Saltanat Yermekova", "Timur Abdikarimov", "Aida Mukhamedjanova", "Askar Beisembaev",
    "Zhanna Toleukhanova", "Ruslan Kenzhebek", "Elena Petrova", "Ivan Sidorov",
    "Olga Volkova", "Maxim Lebedev", "Sofia Kuznetsova", "Andrei Smirnov",
    "Dinara Yesenova", "Arman Zhaksybekov", "Karlygash Omarova", "Sergey Popov",
    "Natalya Ivanova", "Aibek Serikuly", "Zhaniya Mukasheva", "Anton Belov",
    "Aliya Konysbayeva", "Yerkebulan Tazhibayev", "Marina Sokolova", "Dmitry Orlov",
    "Aizhan Sagyntayeva", "Talgat Mussin", "Botagoz Sariyeva", "Pavel Morozov",
    "Asem Kabdylova", "Sanzhar Berdibekov", "Tatyana Egorova", "Aleksandr Vasiliev",
    "Madi Tulegenov", "Aknur Bekmurat", "Vladimir Kuzmin", "Galiya Asylbekova",
    "Nurlan Zhumabayev", "Inna Romanova", "Beibit Karagulov", "Tolkyn Aliaskarova",
    "Stas Kozlov", "Almira Begimbayeva", "Vadim Antonov", "Asyl Khairullina",
    "Daulet Suleimenov", "Yana Maximova",
]


# -----------------------------------------------------------------------------
# CDR helpers
# -----------------------------------------------------------------------------
APRIL_START = datetime(2026, 4, 1)
APRIL_END = datetime(2026, 4, 30, 23, 59, 59)

def rand_april_ts():
    delta_secs = int((APRIL_END - APRIL_START).total_seconds())
    return (APRIL_START + timedelta(seconds=random.randint(0, delta_secs))).strftime("%Y-%m-%d %H:%M:%S")

B2C_DOMAINS_GENERIC = ["youtube.com", "netflix.com", "whatsapp.com", "instagram.com",
                       "telegram.org", "beeline.kz", "facebook.com", "tiktok.com",
                       "google.com", "spotify.com"]

B2B_DOMAINS_GENERIC = ["beeline.kz", "google.com", "office365.com", "slack.com",
                       "github.com", "linkedin.com", "salesforce.com"]

CONTRACT_RATE = {cid: t["overage"] for cid, t in CONTRACT_TERMS.items()}
CONTRACT_ZERO_RATED = {cid: ["beeline.kz"] + t["extra_zero_rated"] for cid, t in CONTRACT_TERMS.items()}

cdr_rows = []
_cdr_counter = [0]

def add_cdr(sub_id, usage_mb, domain, applied_plan_id, billed_rate, charge=None):
    _cdr_counter[0] += 1
    cdr_id = f"CDR_{_cdr_counter[0]:05d}"
    if charge is None:
        charge = round(usage_mb * billed_rate, 2)
    cdr_rows.append((
        cdr_id, sub_id, rand_april_ts(), round(usage_mb, 2),
        domain, applied_plan_id, billed_rate, round(charge, 2),
    ))


# Subscribers whose CDRs are planted explicitly below (skip the generic loop for them)
EXPLICIT_CDR_SUBS = {
    "SUB_007", "SUB_019", "SUB_031", "SUB_044", "SUB_052",  # B2C anomalies
    "SUB_055", "SUB_057", "SUB_058", "SUB_060", "SUB_062",  # B2B anomalies + false positives
}


# -----------------------------------------------------------------------------
# Build subscribers
# -----------------------------------------------------------------------------
subscribers = []

def gen_phone(seed_int):
    return f"7701{2000000 + seed_int:07d}"

# B2C — 54 subscribers
for i in range(54):
    sub_id = f"SUB_{i+1:03d}"
    plan = B2C_PLAN_OVERRIDES.get(sub_id) or random.choice(B2C_PLANS)
    subscribers.append((sub_id, gen_phone(i), B2C_NAMES[i], "B2C", None, plan, "2026-01-01", "active"))

# B2B — 10 subscribers
for idx, (sub_id, corp_id) in enumerate(B2B_MAP.items()):
    subscribers.append((sub_id, gen_phone(100 + idx), B2B_NAMES[sub_id], "B2B", corp_id, B2B_PLANS[sub_id], "2026-01-01", "active"))


# -----------------------------------------------------------------------------
# Generate clean CDRs (skip explicit-anomaly subscribers)
# -----------------------------------------------------------------------------
for sub in subscribers:
    sub_id, _, _, acct_type, corp_id, plan, _, _ = sub
    if sub_id in EXPLICIT_CDR_SUBS:
        continue

    n_cdrs = random.randint(3, 5)
    for _ in range(n_cdrs):
        if acct_type == "B2C":
            domain = random.choice(B2C_DOMAINS_GENERIC)
            usage = random.uniform(400, 3500)
            rate = 0.0 if domain in PLAN_ZERO_RATED[plan] else PLAN_RATES[plan]
            add_cdr(sub_id, usage, domain, plan, rate)
        else:
            # B2B clean: bill at contract rate, honour contract zero-rated list.
            # For CORP_POOLED accounts (CORP_003), within-pool usage shows as 0 charge.
            domain = random.choice(B2B_DOMAINS_GENERIC)
            usage = random.uniform(500, 3000)
            if domain in CONTRACT_ZERO_RATED[corp_id]:
                rate = 0.0
            elif plan == "CORP_POOLED":
                rate = 0.0  # within pooled quota — no overage
            else:
                rate = CONTRACT_RATE[corp_id]
            add_cdr(sub_id, usage, domain, plan, rate)


# -----------------------------------------------------------------------------
# Plant the 10 anomalies
# -----------------------------------------------------------------------------

# Anomaly 1 — SUB_007: plan UNLIM_30 (0.50/MB) but CDRs applied BASIC_15 (0.30/MB). Underbilled.
# delta = 0.20/MB × 18,000 MB = 3,600 KZT
for _ in range(4):
    add_cdr("SUB_007", 4500, "facebook.com", "BASIC_15", 0.30)

# Anomaly 2 — SUB_019: plan BASIC_15 (0.30) but CDRs applied UNLIM_30 (0.50). Overbilled.
# delta = 0.20/MB × 11,100 MB = 2,220 KZT
for _ in range(3):
    add_cdr("SUB_019", 3700, "tiktok.com", "UNLIM_30", 0.50)

# Anomaly 3 — SUB_031: netflix.com zero-rated wrongly (BASIC_15 plan).
# Loss = 16,000 MB × 0.30/MB = 4,800 KZT
for _ in range(3):
    add_cdr("SUB_031", 5333, "netflix.com", "BASIC_15", 0.0)
add_cdr("SUB_031", 1000, "google.com", "BASIC_15", 0.30)  # one clean CDR

# Anomaly 4 — SUB_044: instagram.com zero-rated wrongly (BASIC_15 plan).
# Loss = 6,340 MB × 0.30/MB = 1,902 KZT
for _ in range(2):
    add_cdr("SUB_044", 3170, "instagram.com", "BASIC_15", 0.0)
add_cdr("SUB_044", 1200, "google.com", "BASIC_15", 0.30)

# Anomaly 5 — SUB_052: telegram.org zero-rated wrongly (UNLIM_30 plan).
# Loss = 4,800 MB × 0.50/MB = 2,400 KZT
for _ in range(2):
    add_cdr("SUB_052", 2400, "telegram.org", "UNLIM_30", 0.0)
add_cdr("SUB_052", 1500, "tiktok.com", "UNLIM_30", 0.50)

# Anomaly 6 — SUB_055 (CORP_001 MiningCo): billed at standard 0.50 but contract is 0.20.
# Overbilled delta = 0.30/MB × 28,400 MB = 8,520 KZT (customer dispute risk)
for _ in range(4):
    add_cdr("SUB_055", 7100, "google.com", "CORP_STANDARD", 0.50)
add_cdr("SUB_055", 800, "beeline.kz", "CORP_STANDARD", 0.0)
add_cdr("SUB_055", 500, "mining-vpn.kz", "CORP_STANDARD", 0.0)  # contract zero-rate correctly applied

# Anomaly 7 — SUB_057 (CORP_002 RegionalBank): contract zero-rates bank-internal.kz
# but CDRs to that domain were charged at contract rate 0.18/MB. Overbilled.
# Loss = 34,500 MB × 0.18/MB = 6,210 KZT
for _ in range(3):
    add_cdr("SUB_057", 11500, "bank-internal.kz", "CORP_PREMIUM", 0.18)
add_cdr("SUB_057", 1200, "office365.com", "CORP_PREMIUM", 0.18)  # legitimate overage at contract rate
add_cdr("SUB_057", 500, "beeline.kz", "CORP_PREMIUM", 0.0)

# Anomaly 8 — SUB_060 (CORP_003 LogisticsKZ): pooled quota 500GB not honoured;
# overage applied per-line at 0.35/MB. Total CORP_003 usage stays well under 500 GB.
# Wrongful charges = 34,500 MB × 0.35/MB = 12,075 KZT
for _ in range(3):
    add_cdr("SUB_060", 11500, "logistics-portal.kz", "CORP_POOLED", 0.35)
add_cdr("SUB_060", 800, "beeline.kz", "CORP_POOLED", 0.0)
add_cdr("SUB_060", 600, "logistics-fleet.kz", "CORP_POOLED", 0.0)  # contract zero-rate correctly applied

# Anomaly 9 (FALSE POSITIVE) — SUB_058 (CORP_002 RegionalBank): rate 0.18/MB looks suspiciously
# low vs Excel standard 0.40/0.50, BUT contract legitimately specifies 0.18. Should be CLEARED.
for _ in range(4):
    add_cdr("SUB_058", 2200, "office365.com", "CORP_PREMIUM", 0.18)
add_cdr("SUB_058", 500, "beeline.kz", "CORP_PREMIUM", 0.0)

# Anomaly 10 (FALSE POSITIVE) — SUB_062 (CORP_004 RetailChain): retail-pos.kz zero-rated,
# domain NOT in standard tariff zero-rate list, BUT contract explicitly negotiates it. CLEARED.
for _ in range(3):
    add_cdr("SUB_062", 3000, "retail-pos.kz", "CORP_STANDARD", 0.0)
add_cdr("SUB_062", 1500, "office365.com", "CORP_STANDARD", 0.30)  # legitimate overage at contract rate
add_cdr("SUB_062", 600, "beeline.kz", "CORP_STANDARD", 0.0)


# -----------------------------------------------------------------------------
# Write SQLite
# -----------------------------------------------------------------------------
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
c.execute("""
CREATE TABLE subscribers (
    subscriber_id TEXT PRIMARY KEY,
    phone_number TEXT,
    full_name TEXT,
    account_type TEXT,
    corporate_account_id TEXT,
    plan_id TEXT,
    plan_start_date TEXT,
    status TEXT
)
""")
c.execute("""
CREATE TABLE cdr_records (
    cdr_id TEXT PRIMARY KEY,
    subscriber_id TEXT,
    timestamp TEXT,
    usage_mb REAL,
    domain TEXT,
    applied_plan_id TEXT,
    billed_rate_kzt REAL,
    charge_kzt REAL,
    FOREIGN KEY (subscriber_id) REFERENCES subscribers(subscriber_id)
)
""")
c.executemany("INSERT INTO subscribers VALUES (?,?,?,?,?,?,?,?)", subscribers)
c.executemany("INSERT INTO cdr_records VALUES (?,?,?,?,?,?,?,?)", cdr_rows)
conn.commit()
conn.close()
print(f"[OK] Billing DB:      {DB_PATH}  ({len(subscribers)} subscribers, {len(cdr_rows)} CDRs)")


# -----------------------------------------------------------------------------
# Contract PDFs
# -----------------------------------------------------------------------------
def make_contract_pdf(corp_id):
    name = CORPS[corp_id]
    terms = CONTRACT_TERMS[corp_id]
    overage = terms["overage"]
    pooled_gb = terms["pooled_gb"]
    extra_zr = terms["extra_zero_rated"]

    path = os.path.join(CONTRACTS_DIR, PDF_FILENAMES[corp_id])
    doc = SimpleDocTemplate(path, pagesize=letter, title=f"{corp_id} Contract")
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("CORPORATE TELECOMMUNICATIONS SERVICE AGREEMENT", styles["Title"]))
    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph(f"<b>Client:</b> {name}", styles["Normal"]))
    story.append(Paragraph(f"<b>Corporate Account ID:</b> {corp_id}", styles["Normal"]))
    story.append(Paragraph("<b>Effective Period:</b> January 2026 – December 2026", styles["Normal"]))
    story.append(Spacer(1, 0.25 * inch))

    story.append(Paragraph("<b>Section 1. General Terms</b>", styles["Heading2"]))
    story.append(Paragraph(
        f"This Agreement is entered into between Beeline Kazakhstan JSC (the \"Operator\") and "
        f"{name} (the \"Client\") to govern the provision of mobile telecommunications services, "
        "including voice, messaging, and mobile data, across all corporate subscriber lines registered "
        "under the Client's corporate account. The Client agrees to abide by the Operator's acceptable "
        "use policy and all applicable telecommunications regulations of the Republic of Kazakhstan. "
        "The Operator warrants that services shall be delivered in accordance with industry-standard "
        "quality benchmarks.",
        styles["BodyText"],
    ))
    story.append(Spacer(1, 0.1 * inch))

    story.append(Paragraph("<b>Section 2. Service Continuity and Support</b>", styles["Heading2"]))
    story.append(Paragraph(
        "The Operator shall provide 24/7 technical support and shall maintain network availability of "
        "no less than 99.5% on a monthly basis. Scheduled maintenance windows are excluded from "
        "availability calculations. In the event of a service-impacting incident, the Operator shall "
        "notify the Client's designated technical contact within four (4) business hours and shall "
        "deliver a written root cause analysis within ten (10) business days of incident closure.",
        styles["BodyText"],
    ))
    story.append(Spacer(1, 0.1 * inch))

    story.append(Paragraph("<b>Section 3. Billing and Invoicing</b>", styles["Heading2"]))
    story.append(Paragraph(
        "Invoices shall be issued monthly in arrears and shall be payable within thirty (30) days of "
        "issuance. Disputes regarding any line item must be raised in writing within sixty (60) days "
        "of the invoice date. Payments not received within the agreed timeframe shall accrue interest "
        "at a rate of 0.05% per day. All amounts are denominated in Kazakhstani Tenge (KZT) unless "
        "otherwise stated.",
        styles["BodyText"],
    ))
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("<b>Section 4. Negotiated Rates</b>", styles["Heading2"]))
    story.append(Paragraph(
        f"Notwithstanding the Operator's standard published tariffs, the following negotiated rates "
        f"shall apply to all subscriber lines under corporate account <b>{corp_id}</b> for the duration "
        f"of this Agreement:",
        styles["BodyText"],
    ))
    story.append(Spacer(1, 0.08 * inch))
    story.append(Paragraph(
        f"<b>(a) Negotiated overage rate:</b> KZT {overage:.2f} per MB. This rate replaces the standard "
        f"tariff overage rate for all data usage under this corporate account and shall be applied to "
        f"each subscriber line individually unless a pooled quota is specified below.",
        styles["BodyText"],
    ))
    if pooled_gb is not None:
        story.append(Paragraph(
            f"<b>(b) Pooled data quota:</b> {pooled_gb} GB shared across all subscriber lines under this "
            f"account. Usage exceeding the pooled quota shall be billed at the negotiated overage rate "
            f"specified in (a). Individual lines shall not be assessed overage charges so long as total "
            f"account usage remains within the pooled quota.",
            styles["BodyText"],
        ))
        zr_letter = "(c)"
        zr_pool_phrase = "shall not be counted against the pooled quota and "
    else:
        zr_letter = "(b)"
        zr_pool_phrase = ""

    if extra_zr:
        zr_text = ", ".join(extra_zr)
        story.append(Paragraph(
            f"<b>{zr_letter} Contract-specific zero-rated domains:</b> {zr_text}. Traffic to these "
            f"domains {zr_pool_phrase}shall not incur charges, in addition to any zero-rated domains "
            f"in the Operator's standard tariff (e.g. beeline.kz).",
            styles["BodyText"],
        ))
    else:
        story.append(Paragraph(
            f"<b>{zr_letter} Contract-specific zero-rated domains:</b> None negotiated beyond the "
            f"Operator's standard zero-rated domains (e.g. beeline.kz).",
            styles["BodyText"],
        ))
    story.append(Spacer(1, 0.3 * inch))

    story.append(Paragraph("<b>Section 5. Signatures</b>", styles["Heading2"]))
    story.append(Paragraph("Signed for and on behalf of Beeline Kazakhstan JSC:", styles["BodyText"]))
    story.append(Paragraph("_____________________________", styles["Normal"]))
    story.append(Paragraph("Director of Corporate Sales", styles["Normal"]))
    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph(f"Signed for and on behalf of {name}:", styles["BodyText"]))
    story.append(Paragraph("_____________________________", styles["Normal"]))
    story.append(Paragraph("Authorized Signatory", styles["Normal"]))

    doc.build(story)
    print(f"[OK] Contract PDF:    {path}")


for corp_id in CORPS:
    make_contract_pdf(corp_id)


# -----------------------------------------------------------------------------
# Print planted-anomaly summary for verification
# -----------------------------------------------------------------------------
ANOMALY_SUMMARY = [
    (1,  "Plan mismatch (underbill)",    "SUB_007", "B2C",  "Plan UNLIM_30 but CDRs applied BASIC_15 rate (0.30 instead of 0.50/MB).",                       3_600,  "leakage"),
    (2,  "Plan mismatch (overbill)",     "SUB_019", "B2C",  "Plan BASIC_15 but CDRs applied UNLIM_30 rate (0.50 instead of 0.30/MB).",                       2_220,  "overbilling"),
    (3,  "Zero-rate misapplication",     "SUB_031", "B2C",  "Netflix CDRs charged 0 KZT, but BASIC_15 plan does NOT zero-rate netflix.com.",                 4_800,  "leakage"),
    (4,  "Zero-rate misapplication",     "SUB_044", "B2C",  "Instagram CDRs charged 0 KZT, but BASIC_15 plan does NOT zero-rate instagram.com.",             1_902,  "leakage"),
    (5,  "Zero-rate misapplication",     "SUB_052", "B2C",  "Telegram CDRs charged 0 KZT, but UNLIM_30 plan does NOT zero-rate telegram.org.",               2_400,  "leakage"),
    (6,  "Contract rate violation",      "SUB_055", "CORP_001 MiningCo",       "Contract overage is 0.20/MB but CDRs billed at standard 0.50/MB.",            8_520,  "overbilling (dispute risk)"),
    (7,  "Contract rate violation",      "SUB_057", "CORP_002 RegionalBank",   "Contract zero-rates bank-internal.kz, but those CDRs were charged at 0.18/MB.", 6_210,  "leakage"),
    (8,  "Contract rate violation",      "SUB_060", "CORP_003 LogisticsKZ",    "Pooled quota of 500 GB ignored; individual overage applied at 0.35/MB.",     12_075, "leakage"),
    (9,  "FALSE POSITIVE — must clear",  "SUB_058", "CORP_002 RegionalBank",   "Rate 0.18/MB looks low vs standard, but contract legitimately specifies 0.18/MB.", 0,    "cleared"),
    (10, "FALSE POSITIVE — must clear",  "SUB_062", "CORP_004 RetailChain",    "retail-pos.kz zero-rated; not in Excel, but contract explicitly negotiates it.",  0,    "cleared"),
]

real_total = sum(a[5] for a in ANOMALY_SUMMARY if a[6] != "cleared")

print()
print("=" * 78)
print(" PLANTED ANOMALIES (for verification before agent runs)")
print("=" * 78)
print(f" {'#':>2}  {'Subscriber':<10}  {'Account':<24}  {'Expected KZT':>12}  Type")
print("-" * 78)
for n, kind, sub, acct, desc, kzt, classification in ANOMALY_SUMMARY:
    print(f" {n:>2}  {sub:<10}  {acct:<24}  {kzt:>12,}  {kind}")
    print(f"     -> {desc}")
print("-" * 78)
print(f" Total expected detected leakage/overbilling (excluding cleared): {real_total:,} KZT")
print(f" Cleared cases: 2  (must be flagged then cleared by the agent)")
print("=" * 78)
print()
print("Phase 1 complete. Inspect:")
print(f"  - sqlite3 {DB_PATH}  (tables: subscribers, cdr_records)")
print(f"  - open {EXCEL_PATH}")
print(f"  - open {CONTRACTS_DIR}/*.pdf")
