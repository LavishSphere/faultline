"""Build the independent bad-quarter hand model (issue #108) and export its CSV.

Independence: this script was written from docs/MATH_MODEL.md (sections 1-3 and 10),
services/api/data/demo_business.json and services/api/data/scenarios.json only. It does not
import or read the FAULTLINE engine.

Step 1 writes docs/finance/bad_quarter_independent.xlsx with real spreadsheet formulas
(every weekly number is a formula that refers to the Parameters sheet or to other cells).
Step 2 evaluates those formulas with the pure-Python `pycel` package (no Excel installed)
and writes services/api/tests/golden/bad_quarter_independent.csv from the evaluated cells.

Usage (needs openpyxl and pycel, not part of the API's dependencies):
    python docs/finance/build_bad_quarter_independent.py
"""

from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.workbook.defined_name import DefinedName
from pycel import ExcelCompiler
from pycel.excelwrapper import ExcelOpxWrapper


def _defined_names(self):
    """pycel 1.0b30 expects openpyxl < 3.1 (`defined_names.definedName`); openpyxl 3.1 stores a dict.

    Same logic as pycel's own property, reading workbook-scoped names from the 3.1 dict.
    """
    if self.workbook is not None and self._defined_names is None:
        self._defined_names = {}
        for d_name in self.workbook.defined_names.values():
            destinations = [(alias, ws) for ws, alias in d_name.destinations if ws in self.workbook]
            if destinations:
                self._defined_names[str(d_name.name)] = destinations
    return self._defined_names


ExcelOpxWrapper.defined_names = property(_defined_names)

REPO = Path(__file__).resolve().parents[2]
XLSX = REPO / "docs" / "finance" / "bad_quarter_independent.xlsx"
CSV = REPO / "services" / "api" / "tests" / "golden" / "bad_quarter_independent.csv"

T = 26
# Bad-quarter supplier availability kappa_t, weeks 1..26, copied from scenarios.json ("bad-quarter").
AVAILABILITY = [1.0] * 4 + [0.0] * 3 + [1.0] * 19
assert len(AVAILABILITY) == T

# (name, value, unit, source) -- every number the Model sheet uses lives here.
PARAMS = [
    ("Horizon_T", 26, "weeks", "§10 Horizon T; demo_business.json horizon_weeks"),
    ("S_base_1", 18000, "$/wk", "§10 store weekly sales (Store 1)"),
    ("S_base_2", 17000, "$/wk", "§10 store weekly sales (Store 2)"),
    ("S_base_3", 15000, "$/wk", "§10 store weekly sales (Store 3)"),
    ("gm", 0.35, "fraction", "§10 gross margin"),
    ("a_coll", 0.80, "fraction", "§10 same-week collection"),
    ("Lp", 2, "weeks", "§10 supplier lag (Net-14)"),
    ("W_pay", 12000, "$/wk", "§10 payroll"),
    ("O_opex", 6000, "$/wk", "§10 fixed opex"),
    ("D_1", 600000, "$", "§10 term loan principal at start of week 1 (the 'D_0' of §10, see §3)"),
    ("r_base", 0.08, "1/yr", "§10 all-in floating rate"),
    ("A_amort", 0, "$/wk", "§10 amortization (interest-only)"),
    ("s_R", 0.02, "1/yr", "§10 revolver spread"),
    ("B_0", 0, "$", "§10 revolver opening balance"),
    ("C_0", 100000, "$", "§10 starting cash"),
    ("I_0", 65000, "$", "§10 starting inventory at cost"),
    ("S_0", 50000, "$", "§10 pre-horizon sales"),
    ("P_m1", 32500, "$", "§10 pre-horizon purchases P_-1"),
    ("P_0", 32500, "$", "§10 pre-horizon purchases P_0"),
    ("pi_b", 0.12, "fraction", "§10 backup premium"),
    ("F_b", 2000, "$", "§10 backup switching fee"),
    ("K_capex", 0, "$/wk", "§10 capex: 0 in the base business (demo_business.json)"),
    ("E_exp", 0, "$/wk", "§10 expansion outflow: 0 in the base business (demo_business.json)"),
    ("X_exp", 0, "$/wk", "§10 expansion sales: 0 in the base business (demo_business.json)"),
    ("C_min", 25000, "$", "§10 liquidity floor (reporting only)"),
    # Scenario: bad-quarter (scenarios.json)
    ("dr", 0.02, "1/yr", "scenarios.json bad-quarter rate.delta_rate"),
    ("t_r", 1, "week", "scenarios.json bad-quarter rate.start_week"),
    ("delta", 0.20, "fraction", "scenarios.json bad-quarter demand.delta"),
    ("t_1", 3, "week", "scenarios.json bad-quarter demand.start_week"),
    ("t_2", 8, "week", "scenarios.json bad-quarter demand.end_week"),
    ("rho", 4, "weeks", "scenarios.json bad-quarter demand.recovery_weeks"),
    ("phi", 0.40, "fraction", "scenarios.json bad-quarter supplier.dependent_share (= §10 outage share)"),
    # Decisions: the do-nothing plan (no recovery action taken)
    ("x_b", 0, "0/1", "decision: use backup supplier (no action)"),
    ("x_c", 0, "0/1", "decision: defer non-critical capex (no action)"),
    ("x_e", 0, "0/1", "decision: delay expansion (no action)"),
    ("v_cut", 0, "$/wk", "decision: purchase cut v_t (no action)"),
    ("z_pay", 0, "share", "decision: payroll reduction z_t (no action)"),
    ("y_draw", 0, "$/wk", "decision: revolver draw y_t (no action)"),
    ("q_repay", 0, "$/wk", "decision: revolver repayment q_t (no action)"),
]

# Model sheet columns: (letter, header, formula template for week rows; {r} = row, {p} = previous row)
COLS = [
    ("A", "week t", None),
    ("B", "demand multiplier m_t (§1)",
     "=IF(AND(A{r}>=t_1,A{r}<=t_2),1-delta,IF(AND(A{r}>t_2,A{r}<=t_2+rho),1-delta*(1-(A{r}-t_2)/rho),1))"),
    ("C", "supplier availability kappa_t (scenario input)", None),
    ("D", "lost-sales fraction lambda_t = phi(1-kappa_t) (§1)", "=phi*(1-C{r})"),
    ("E", "base-store demand S_core_t = m_t * sum S_base (§2)", "=B{r}*(S_base_1+S_base_2+S_base_3)"),
    ("F", "sales S_t (§2)", "=E{r}*(1-D{r}*(1-x_b))+(1-x_e)*X_exp"),
    ("G", "receipts R_t = a S_t + (1-a) S_t-1 (§3)", "=a_coll*F{r}+(1-a_coll)*F{p}"),
    ("H", "purchases P_t (§3)", "=(1-gm)*F{r}-v_cut+pi_b*(1-gm)*E{r}*D{r}*x_b"),
    ("I", "purchases paid P_t-Lp (§3)", "=INDEX($H$1:$H$40,ROW()-Lp)"),
    ("J", "inventory I_t at cost (§3)", "=J{p}+H{r}-(1-gm)*F{r}-pi_b*(1-gm)*E{r}*D{r}*x_b"),
    ("K", "payroll paid (1-z)W (§3)", "=(1-z_pay)*W_pay"),
    ("L", "opex O (§3)", "=O_opex"),
    ("M", "annual rate r_t = r_base + dr*1[t>=t_r] (§1)", "=r_base+IF(A{r}>=t_r,dr,0)"),
    ("N", "term principal D_t at start of week (§3)", "=N{p}-P{p}"),
    ("O", "term interest J_t = D_t r_t/52 (§3)", "=N{r}*M{r}/52"),
    ("P", "amortization A_t (§3)", "=A_amort"),
    ("Q", "revolver interest J^R_t = B_t-1 (r_t+s_R)/52 (§3)", "=R{p}*(M{r}+s_R)/52"),
    ("R", "revolver balance B_t = B_t-1 + y - q (§3)", "=R{p}+y_draw-q_repay"),
    ("S", "capex paid (1-x_c)K (§3)", "=(1-x_c)*K_capex"),
    ("T", "expansion paid (1-x_e)E (§3)", "=(1-x_e)*E_exp"),
    ("U", "backup fee F_b x_b 1[t=1] (§3)", "=F_b*x_b*IF(A{r}=1,1,0)"),
    ("V", "total interest J_t + J^R_t", "=O{r}+Q{r}"),
    ("W", "cash C_t (§3 boxed recurrence)",
     "=W{p}+G{r}-I{r}-K{r}-L{r}-O{r}-P{r}-Q{r}-S{r}-T{r}-U{r}+y_draw-q_repay"),
    ("X", "below C_min? (reporting)", '=IF(W{r}<C_min,"BELOW","")'),
]

FIRST_WEEK_ROW = 4  # row 2 = week -1, row 3 = week 0, rows 4..29 = weeks 1..26

README = [
    "FAULTLINE bad-quarter scenario: INDEPENDENT hand model (issue #108)",
    "",
    "Provenance: SYNTHETIC business (fictional 3-store food retailer);",
    "every weekly value is SIMULATED by the formulas below.",
    "Not a real company, not a forecast, not trading P&L.",
    "",
    "Sources used (and only these): docs/MATH_MODEL.md §1 (shocks), §2 (sales), §3 (cash recurrence),",
    "§10 (parameters);",
    "services/api/data/demo_business.json (same §10 values); services/api/data/scenarios.json (bad-quarter shock).",
    "The FAULTLINE engine code (services/api/core/) was NOT read or run while building this workbook.",
    "",
    "Sheets: Parameters (every input, as named cells) -> Model (one row per week, all formulas).",
    "Rows for week -1 and week 0 hold the pre-horizon initial conditions (S_0, P_-1, P_0, I_0, C_0, B_0, D_1).",
    "",
    "Plan simulated: the do-nothing plan. All decisions are 0: no backup supplier, no capex deferral, no expansion",
    "delay, no purchase cuts, no payroll cut, no revolver draw or repayment.",
    "",
    "How each column is computed:",
    "  m_t: 1-delta in weeks t_1..t_2 (3..8); 1-delta*(1-(t-t_2)/rho) for t_2 < t <= t_2+rho (9..12); else 1.",
    "  lambda_t = phi*(1-kappa_t); kappa_t = 0 in weeks 5-7, else 1 (scenarios.json availability list).",
    "  S_core_t = m_t * (18,000+17,000+15,000).  S_t = S_core_t*(1-lambda_t*(1-x_b)) + (1-x_e)*X_t.",
    "  R_t = a*S_t + (1-a)*S_t-1, with S_0 = 50,000.",
    "  P_t = (1-g)*S_t - v_t + pi*(1-g)*S_core_t*lambda_t*x_b;",
    "  the cash paid in week t is P_t-Lp (Lp = 2; P_-1 = P_0 = 32,500).",
    "  I_t = I_t-1 + P_t - (1-g)*S_t - premium = I_t-1 - v_t, so 65,000 every week when v_t = 0.",
    "  r_t = 8% + 2% from week 1 = 10%.  J_t = D_t*r_t/52 = 600,000*10%/52 = 1,153.85.",
    "  J^R_t = B_t-1*(r_t+s_R)/52 = 0.",
    "  C_t = C_t-1 + R_t - P_t-Lp - (1-z)W - O - J_t - A_t - J^R_t - (1-x_c)K - (1-x_e)E - F_b*x_b*1[t=1] + y_t - q_t.",
    "  CSV column 'interest' = J_t + J^R_t (term loan plus revolver; revolver part is 0 here).",
    "",
    "Ambiguities in MATH_MODEL and how this model reads them:",
    "  1. Which plan? The issue names a scenario, not a plan. Read as the do-nothing plan (all decisions 0).",
    "  2. Recovery weeks: §1 counts recovery as t_2 < t <= t_2+rho with m back to 1 at t = t_2+rho. With rho = 4 the",
    "     path is 0.85, 0.90, 0.95, 1.00 in weeks 9-12, so week 12 is already back to normal.",
    "  3. Outage plus demand drop: §2 multiplies them (S = m*S_base*(1-lambda)). In weeks 5-7 sales are",
    "     50,000*0.8*0.6 = 24,000, not 50,000*(1-0.2-0.4) = 20,000.",
    "  4. Outage scope: §2 (issue #16) - the outage hits base-store sales only; X_t = 0 here so it does not matter.",
    "  5. Rate shock 'from week 1' (t >= t_r with t_r = 1) means every week of the horizon pays 10%.",
    "     The same r_t feeds the revolver rate, which is irrelevant here because the revolver stays at 0.",
    "  6. Purchases: §3 says purchases replace what was sold (no stock rebuild after the shock), so purchases fall",
    "     with sales and inventory stays at 65,000. Lost sales do not leave extra stock on the shelf.",
    "  7. Supplier lag: the week-t cash outflow is P_t-Lp, the purchase made Lp = 2 weeks earlier; P_-1 and P_0 come",
    "     from §10. Receipts use a one-week tail (S_0 for week 1) regardless of Lp.",
    "  8. Interest uses D_t/52 per week with D_t = 600,000 throughout (A_t = 0);",
    "     the weekly rate is annual/52, no compounding.",
    "  9. Sales and purchases columns are the week-t values (S_t, P_t), not the cash paid; cash paid is P_t-Lp.",
    "",
    "Check by hand: no-shock cash falls 1,423.08/wk; +2% rate adds 230.77/wk -> 1,653.85/wk -> 26 weeks = 43,000.",
    "Lost sales total 123,000 (weeks 3-11); lost gross margin 35% x 123,000 = 43,050, all inside the horizon.",
    "So C_26 = 100,000 - 43,000 - 43,050 = 13,950.",
    "",
    "Built by docs/finance/build_bad_quarter_independent.py (openpyxl writes the formulas; the 'pycel'",
    "package evaluates them to produce services/api/tests/golden/bad_quarter_independent.csv).",
    "The file stores formulas; Excel/LibreOffice recalculate on open (full calculation on load is set).",
]


def build_workbook(path: Path) -> None:
    wb = Workbook()
    ws_readme = wb.active
    ws_readme.title = "README"
    for i, line in enumerate(README, start=1):
        ws_readme.cell(row=i, column=1, value=line)
    ws_readme["A1"].font = Font(bold=True)
    ws_readme.column_dimensions["A"].width = 120

    ws_p = wb.create_sheet("Parameters")
    for c, h in enumerate(["name", "value", "unit", "source"], start=1):
        ws_p.cell(row=1, column=c, value=h).font = Font(bold=True)
    for i, (name, value, unit, source) in enumerate(PARAMS, start=2):
        ws_p.cell(row=i, column=1, value=name)
        ws_p.cell(row=i, column=2, value=value)
        ws_p.cell(row=i, column=3, value=unit)
        ws_p.cell(row=i, column=4, value=source)
        wb.defined_names[name] = DefinedName(name, attr_text=f"Parameters!$B${i}")
    ws_p.column_dimensions["A"].width = 14
    ws_p.column_dimensions["D"].width = 90

    ws = wb.create_sheet("Model")
    for letter, header, _ in COLS:
        ws[f"{letter}1"] = header
        ws[f"{letter}1"].font = Font(bold=True)
        ws.column_dimensions[letter].width = 16
    # Pre-horizon rows (initial conditions, all referencing Parameters).
    ws["A2"], ws["H2"] = -1, "=P_m1"
    ws["A3"], ws["F3"], ws["H3"], ws["J3"] = 0, "=S_0", "=P_0", "=I_0"
    ws["N3"], ws["P3"], ws["R3"], ws["W3"] = "=D_1+A_amort", "=A_amort", "=B_0", "=C_0"
    # N3 + P3 makes N4 = D_1 via the recurrence D_t+1 = D_t - A_t.
    for t in range(1, T + 1):
        r = FIRST_WEEK_ROW + t - 1
        ws[f"A{r}"] = t
        ws[f"C{r}"] = AVAILABILITY[t - 1]
        for letter, _, tmpl in COLS:
            if tmpl is not None:
                ws[f"{letter}{r}"] = tmpl.format(r=r, p=r - 1)
    ws.freeze_panes = "B2"
    wb.calculation.fullCalcOnLoad = True
    wb.save(path)


def evaluate(path: Path) -> list[dict[str, float]]:
    """Evaluate the workbook's formulas with pycel (pure-Python Excel formula engine)."""
    xl = ExcelCompiler(filename=str(path))
    rows = []
    for t in range(1, T + 1):
        r = FIRST_WEEK_ROW + t - 1

        def cell(col: str, r: int = r) -> float:
            return xl.evaluate(f"Model!{col}{r}")

        rows.append({
            "week": int(cell("A")),
            "sales": float(cell("F")),
            "receipts": float(cell("G")),
            "purchases": float(cell("H")),
            "inventory": float(cell("J")),
            "interest": float(cell("V")),
            "cash": float(cell("W")),
        })
    return rows


def write_csv(rows: list[dict[str, float]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["week", "sales", "receipts", "purchases", "inventory", "interest", "cash"]
    with path.open("w", newline="\n", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(cols)
        for row in rows:
            w.writerow([row["week"]] + [f"{row[c]:.6f}" for c in cols[1:]])


if __name__ == "__main__":
    XLSX.parent.mkdir(parents=True, exist_ok=True)
    build_workbook(XLSX)
    rows = evaluate(XLSX)
    write_csv(rows, CSV)
    for row in rows:
        print(row["week"], round(row["sales"], 2), round(row["cash"], 2))
