#!/usr/bin/env python3
"""Generate the MOCK internal data room for the SYNTHETIC demo business (services/api/data/internal/*.json).

Every table is SYNTHETIC (mock internal data): invented by this script from a fixed seed, for a fictional company.
Nothing here is a real company's ledger, customer or supplier. Company and person names are made up.

The tables are anchored on services/api/data/demo_business.json so the data room and the cash engine agree:
- weekly sales of 50,000 split over the three stores (18,000 / 17,000 / 15,000), gross margin 35% (COGS = 65% of
  sales), payroll 12,000 a week, opex 6,000 a week, interest on the 600,000 term loan at the 8% base rate;
- 80% of sales are collected in the same week, so the open receivables are about one week of the other 20%;
- purchases are paid with a two-week supplier lag, so open payables are about two weeks of purchases;
- inventory on hand sums to inventory_0 (65,000); the revolver limit (150,000), spread (2%), minimum cash
  (25,000) and the supplier-outage dependent share (40% of sales on the primary distributor's lines) are copied.

The cash engine does not read these tables: they are context for the chat's `query_internal_data` tool and
GET /api/internal-data. Re-run to regenerate (output is byte-identical for the same seed and business file):

    python3 scripts/gen_internal_data.py            # writes services/api/data/internal/
    python3 scripts/gen_internal_data.py --check    # exit 1 if the committed files differ
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUSINESS_FILE = ROOT / "services" / "api" / "data" / "demo_business.json"
OUT_DIR = ROOT / "services" / "api" / "data" / "internal"
SEED = 20261115
LABEL = "SYNTHETIC (mock internal data)"
# The day before week 1 of the 26-week horizon. History weeks end on Sundays up to this date.
SNAPSHOT_DATE = date(2026, 11, 15)
HISTORY_WEEKS = 52


def _r(x: float) -> float:
    return round(float(x), 2)


def _table(name: str, description: str, schema: dict[str, str], rows: list[dict], **extra) -> dict:
    return {
        "provenance": "SYNTHETIC",
        "label": LABEL,
        "table": name,
        "description": description,
        "generator": "scripts/gen_internal_data.py",
        "seed": SEED,
        "snapshot_date": SNAPSHOT_DATE.isoformat(),
        "schema": schema,
        **extra,
        "rows": rows,
    }


def _scale_to(values: list[float], total: float) -> list[float]:
    """Scale to `total` and round to cents, putting the rounding remainder on the largest entry."""
    s = sum(values)
    out = [_r(v * total / s) for v in values]
    i = max(range(len(out)), key=lambda k: out[k])
    out[i] = _r(out[i] + (total - sum(out)))
    return out


def build(business: dict) -> dict[str, dict]:
    rng = random.Random(SEED)
    b = business["business"]
    stores = [(s["name"], float(s["base_sales"])) for s in b["stores"]]
    sales_0 = sum(v for _, v in stores)
    margin = float(b["gross_margin"])
    payroll = float(b["payroll"])
    opex = float(b["opex"])
    loan = float(b["term_loan_principal_1"])
    base_rate = float(b["base_rate"])
    collect = float(b["same_week_collection"])
    lag = int(b["supplier_lag_weeks"])
    inventory_0 = float(b["inventory_0"])
    dependent = float(business["scenario_parameters"]["supplier_outage_dependent_share"])
    store_share = {name: v / sales_0 for name, v in stores}
    tables: dict[str, dict] = {}

    # ---- general ledger: 52 weeks of history, per store and account
    gl = []
    for k in range(HISTORY_WEEKS):
        week_index = k - HISTORY_WEEKS  # -52 .. -1
        week_end = SNAPSHOT_DATE - timedelta(days=7 * (HISTORY_WEEKS - 1 - k) + 7)
        season = 1.0 + 0.06 * math.sin(2 * math.pi * (k + 6) / 52)
        for name, base in stores:
            revenue = _r(base * season * (1 + rng.gauss(0, 0.03)))
            rows = [("revenue", revenue), ("cogs", -_r(revenue * (1 - margin))),
                    ("payroll", -_r(payroll * store_share[name])),
                    ("opex", -_r(opex * store_share[name] * (1 + rng.gauss(0, 0.04))))]
            gl.extend({"week_index": week_index, "week_ending": week_end.isoformat(), "store": name,
                       "account": acct, "amount": amt} for acct, amt in rows)
        gl.append({"week_index": week_index, "week_ending": week_end.isoformat(), "store": "Head office",
                   "account": "interest", "amount": -_r(loan * base_rate / 52)})
    tables["general_ledger"] = _table(
        "general_ledger", "Weekly P&L lines for the 52 weeks before the forecast horizon, per store and account. "
        "Revenue is positive, costs negative.",
        {"week_index": "int, -52..-1 (week 1 of the forecast horizon follows week -1)",
         "week_ending": "date (Sunday)", "store": "Store 1 | Store 2 | Store 3 | Head office",
         "account": "revenue | cogs | payroll | opex | interest", "amount": "USD, signed"}, gl,
        anchors={"weekly_sales_base": sales_0, "gross_margin": margin, "weekly_payroll": payroll,
                 "weekly_opex": opex, "closing_cash_week_minus_1": float(b["cash_0"])})

    # ---- customers: the credit (account) customers behind the 20% of sales not collected in the same week
    names = ["Harbor Lane Catering Co.", "Maple Ridge School District Cafeterias", "Oakview Senior Living",
             "Bluestone Office Park Canteens", "Riverside Community Hospital Kitchen", "Cedar Point Events",
             "Summit Youth Sports League", "Willow Creek Daycare Group", "Northgate Corporate Lunches",
             "Pinecrest Hotel Breakfast Bar", "Elm Street Food Pantry", "Granite Hills Golf Club"]
    weights = [rng.paretovariate(1.6) for _ in names]
    weights.sort(reverse=True)
    credit_weekly = sales_0 * (1 - collect)
    weekly = _scale_to(weights, credit_weekly)
    risks = ["low", "low", "medium", "low", "medium", "high", "medium", "low", "high", "medium", "low", "low"]
    customers = []
    for i, (cname, wk) in enumerate(zip(names, weekly, strict=True)):
        customers.append({
            "customer_id": f"C{i + 1:03d}", "name": cname, "segment": "account (invoiced)",
            "weekly_revenue": wk, "annual_revenue": _r(wk * 52),
            "share_of_credit_sales": round(wk / credit_weekly, 4), "share_of_total_sales": round(wk / sales_0, 4),
            "avg_days_to_pay": int(7 + rng.randint(0, 9) + (12 if risks[i] == "high" else 0)),
            "churn_risk": risks[i],
            "contract_end": (SNAPSHOT_DATE + timedelta(days=rng.randint(30, 540))).isoformat(),
        })
    customers.append({"customer_id": "C000", "name": "Walk-in retail (all stores, aggregated)",
                      "segment": "retail (paid at till)", "weekly_revenue": _r(sales_0 * collect),
                      "annual_revenue": _r(sales_0 * collect * 52), "share_of_credit_sales": 0.0,
                      "share_of_total_sales": round(collect, 4), "avg_days_to_pay": 0, "churn_risk": "low",
                      "contract_end": None})
    tables["customers"] = _table(
        "customers", "Customers by revenue. Walk-in retail (paid at the till) is one aggregated row; the account "
        "customers are invoiced and make up the share of sales not collected in the same week.",
        {"customer_id": "str", "name": "str (fictional)", "segment": "retail (paid at till) | account (invoiced)",
         "weekly_revenue": "USD", "annual_revenue": "USD (weekly x 52)", "share_of_credit_sales": "0..1",
         "share_of_total_sales": "0..1", "avg_days_to_pay": "days", "churn_risk": "low | medium | high",
         "contract_end": "date or null"}, customers)

    # ---- AR aging: open invoices of the account customers (about one week of credit sales, some overdue)
    ar = []
    n = 0
    for c in customers[:-1]:
        for _ in range(rng.randint(1, 3)):
            n += 1
            days = rng.choice([2, 4, 6, 9, 12, 16, 23, 38, 47, 66]) if c["churn_risk"] == "high" else \
                rng.choice([1, 2, 3, 5, 6, 8, 11, 15, 19, 33])
            issued = SNAPSHOT_DATE - timedelta(days=days)
            ar.append({"invoice_id": f"INV-{26000 + n}", "customer_id": c["customer_id"], "customer": c["name"],
                       "amount": 0.0, "issued": issued.isoformat(),
                       "due": (issued + timedelta(days=14)).isoformat(), "days_outstanding": days,
                       "bucket": "0-30" if days <= 30 else "31-60" if days <= 60 else "61-90"})
    amounts = _scale_to([rng.uniform(0.4, 1.6) for _ in ar], _r(credit_weekly * 1.15))
    for row, amt in zip(ar, amounts, strict=True):
        row["amount"] = amt
    tables["ar_aging"] = _table(
        "ar_aging", "Open customer invoices at the snapshot date with days outstanding and aging bucket.",
        {"invoice_id": "str", "customer_id": "str", "customer": "str", "amount": "USD", "issued": "date",
         "due": "date (net 14)", "days_outstanding": "days", "bucket": "0-30 | 31-60 | 61-90"}, ar)

    # ---- suppliers and AP schedule: about `lag` weeks of purchases are open
    purchases_weekly = sales_0 * (1 - margin)
    suppliers = [
        ("S01", "Northfield Fresh Distributors", "primary distributor: fresh, deli, produce", dependent + 0.1, 14),
        ("S02", "Prairie Dry Goods Wholesale", "dry goods and grocery", 0.22, 21),
        ("S03", "Valley Dairy Co-op", "dairy and eggs", 0.15, 14),
        ("S04", "Coastline Packaging Supply", "packaging and consumables", 0.05, 30),
        ("S05", "Metro Backup Foods", "backup supplier (12% price premium), on call", 0.08, 7),
    ]
    ap = []
    n = 0
    for sid, sname, scope, share, terms in suppliers:
        weekly_spend = purchases_weekly * share
        for w in range(lag):
            n += 1
            invoiced = SNAPSHOT_DATE - timedelta(days=7 * (w + 1) - rng.randint(0, 3))
            due = invoiced + timedelta(days=terms)
            ap.append({"bill_id": f"BILL-{8800 + n}", "supplier_id": sid, "supplier": sname, "category": scope,
                       "amount": _r(weekly_spend * (1 + rng.gauss(0, 0.05))), "invoiced": invoiced.isoformat(),
                       "terms_days": terms, "due": due.isoformat(), "days_until_due": (due - SNAPSHOT_DATE).days})
    tables["ap_schedule"] = _table(
        "ap_schedule", "Open supplier bills with payment terms and due dates (purchases are paid with a "
        f"{lag}-week lag in the cash model).",
        {"bill_id": "str", "supplier_id": "str", "supplier": "str (fictional)", "category": "str",
         "amount": "USD", "invoiced": "date", "terms_days": "days", "due": "date",
         "days_until_due": "days from the snapshot date (negative = overdue)"}, ap,
        anchors={"weekly_purchases_base": purchases_weekly, "supplier_lag_weeks": lag,
                 "primary_distributor_dependent_share_of_sales": dependent})

    # ---- payroll by store and department; sums to the weekly payroll exactly
    depts = [("Front of house", 0.34, 9), ("Deli and fresh", 0.30, 6), ("Stock and receiving", 0.18, 4),
             ("Store management", 0.18, 2)]
    pay_rows = []
    hq_share = 0.08
    for name, base in stores:
        for dept, share, heads in depts:
            pay_rows.append({"store": name, "department": dept,
                             "headcount": max(1, round(heads * base / 17000)),
                             "weekly_cost_raw": share * (1 - hq_share) * base / sales_0})
    pay_rows.append({"store": "Head office", "department": "Admin and finance", "headcount": 2,
                     "weekly_cost_raw": hq_share})
    costs = _scale_to([r.pop("weekly_cost_raw") for r in pay_rows], payroll)
    for row, cost in zip(pay_rows, costs, strict=True):
        row["weekly_cost"] = cost
        row["avg_weekly_cost_per_head"] = _r(cost / row["headcount"])
    tables["payroll"] = _table(
        "payroll", "Weekly payroll by store and department. Totals the demo business's weekly payroll, which "
        "FAULTLINE protects as a hard rule.",
        {"store": "str", "department": "str", "headcount": "people", "weekly_cost": "USD",
         "avg_weekly_cost_per_head": "USD"}, pay_rows, anchors={"weekly_payroll": payroll})

    # ---- inventory by SKU group; on-hand sums to inventory_0
    skus = [("Fresh produce", "S01", True), ("Deli meats", "S01", True), ("Prepared meals", "S01", True),
            ("Bakery", "S01", True), ("Fresh seafood", "S01", True), ("Cheese counter", "S03", True),
            ("Milk and cream", "S03", True), ("Eggs", "S03", True), ("Yogurt", "S03", True),
            ("Canned goods", "S02", False), ("Pasta and rice", "S02", False), ("Snacks", "S02", False),
            ("Beverages", "S02", False), ("Frozen foods", "S02", False), ("Spices and sauces", "S02", False),
            ("Coffee and tea", "S02", False), ("Paper goods", "S04", False), ("Containers and wrap", "S04", False)]
    supplier_name = {s[0]: s[1] for s in suppliers}
    usage_w = [rng.uniform(0.6, 1.4) * (1.6 if per else 1.0) for _, _, per in skus]
    usage = _scale_to(usage_w, purchases_weekly)
    cover_target = [rng.uniform(0.6, 1.4) if per else rng.uniform(2.5, 5.0) for _, _, per in skus]
    on_hand = _scale_to([u * c for u, c in zip(usage, cover_target, strict=True)], inventory_0)
    inv = []
    for i, ((group, sid, per), u, oh) in enumerate(zip(skus, usage, on_hand, strict=True)):
        inv.append({"sku": f"SKU-{100 + i}", "group": group, "supplier_id": sid, "supplier": supplier_name[sid],
                    "perishable": per, "on_hand_value": oh, "weekly_usage_value": u,
                    "weeks_of_cover": round(oh / u, 2)})
    tables["inventory"] = _table(
        "inventory", "Inventory on hand by SKU group at cost, weekly usage at cost and weeks of cover "
        "(on hand / weekly usage).",
        {"sku": "str", "group": "str", "supplier_id": "str", "supplier": "str", "perishable": "bool",
         "on_hand_value": "USD at cost", "weekly_usage_value": "USD at cost", "weeks_of_cover": "weeks"}, inv,
        anchors={"inventory_0": inventory_0, "min_inventory": float(b["min_inventory"])})

    # ---- debt facilities and covenants
    rev_rate = base_rate + float(b["revolver_spread"])
    debt = [
        {"item_id": "D1", "facility": "Term loan", "kind": "facility", "limit": loan, "balance": loan,
         "annual_rate": base_rate, "weekly_interest": _r(loan * base_rate / 52), "maturity": "2029-06-30",
         "threshold": None, "unit": "USD", "note": "floating at the base rate; no scheduled amortization"},
        {"item_id": "D2", "facility": "Revolving credit facility", "kind": "facility",
         "limit": float(b["revolver_limit"]), "balance": float(b["revolver_balance_0"]), "annual_rate": rev_rate,
         "weekly_interest": 0.0, "maturity": "2027-12-31", "threshold": None, "unit": "USD",
         "note": "base rate plus spread on drawn balance"},
        {"item_id": "D3", "facility": "Revolving credit facility", "kind": "covenant", "limit": None,
         "balance": None, "annual_rate": None, "weekly_interest": None, "maturity": None,
         "threshold": float(b["min_cash"]), "unit": "USD", "note": "minimum cash balance at every week end"},
        {"item_id": "D4", "facility": "Term loan", "kind": "covenant", "limit": None, "balance": None,
         "annual_rate": None, "weekly_interest": None, "maturity": None, "threshold": 1.2, "unit": "ratio",
         "note": "fixed-charge cover tested quarterly (mock covenant; the cash engine does not test it)"},
    ]
    tables["debt"] = _table(
        "debt", "Debt facilities (limits, balances, rates) and their covenants.",
        {"item_id": "str", "facility": "str", "kind": "facility | covenant", "limit": "USD or null",
         "balance": "USD or null", "annual_rate": "0..1 or null", "weekly_interest": "USD or null",
         "maturity": "date or null", "threshold": "covenant threshold or null", "unit": "USD | ratio",
         "note": "str"}, debt)

    # ---- contracts: supplier minimums, leases, services, renewal dates
    contracts = []
    for i, (sid, sname, scope, share, _terms) in enumerate(suppliers):
        weekly_min = _r(purchases_weekly * share * (0.6 if sid != "S05" else 0.0))
        renew = SNAPSHOT_DATE + timedelta(days=rng.randint(45, 400))
        contracts.append({"contract_id": f"K{i + 1:02d}", "counterparty": sname, "type": "supply",
                          "weekly_minimum": weekly_min, "annual_minimum": _r(weekly_min * 52),
                          "renewal_date": renew.isoformat(), "notice_days": 60 if share > 0.2 else 30,
                          "auto_renew": sid != "S05",
                          "note": ("take-or-pay minimum on the primary distributor's lines" if sid == "S01" else
                                   "no minimum; switch fee applies when activated" if sid == "S05" else
                                   "volume minimum, shortfall billed at 10%")})
    for j, (name, base) in enumerate(stores):
        rent = _r(opex * 0.45 * base / sales_0)
        contracts.append({"contract_id": f"L{j + 1:02d}", "counterparty": f"{name} landlord", "type": "lease",
                          "weekly_minimum": rent, "annual_minimum": _r(rent * 52),
                          "renewal_date": (SNAPSHOT_DATE + timedelta(days=rng.randint(200, 1100))).isoformat(),
                          "notice_days": 180, "auto_renew": False, "note": "store lease (part of weekly opex)"})
    tables["contracts"] = _table(
        "contracts", "Supplier minimums, store leases and their renewal dates.",
        {"contract_id": "str", "counterparty": "str (fictional)", "type": "supply | lease",
         "weekly_minimum": "USD", "annual_minimum": "USD (weekly x 52)", "renewal_date": "date",
         "notice_days": "days", "auto_renew": "bool", "note": "str"}, contracts)
    return tables


def render(table: dict) -> str:
    return json.dumps(table, indent=1, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the committed files differ")
    args = parser.parse_args()
    tables = build(json.loads(BUSINESS_FILE.read_text(encoding="utf-8")))
    if args.check:
        stale = [n for n, t in tables.items()
                 if not (OUT_DIR / f"{n}.json").is_file()
                 or (OUT_DIR / f"{n}.json").read_text(encoding="utf-8") != render(t)]
        if stale:
            print("internal data out of date: " + ", ".join(stale) + " (run scripts/gen_internal_data.py)")
            return 1
        print(f"internal data up to date ({len(tables)} tables)")
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        (OUT_DIR / f"{name}.json").write_text(render(table), encoding="utf-8")
        print(f"wrote {name}.json ({len(table['rows'])} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
