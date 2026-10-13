"""
Dynasty wealth simulator: Vanderbilt vs. "Rockefeller Waterfall" vs. Colombia.

Pure standard library (no numpy/matplotlib). Writes:
  results/per_capita.csv   per-heir real wealth, every year, every model
  results/summary.md       per-generation table
  results/chart.svg        log-scale line chart (renders on GitHub)

All figures are REAL (inflation-adjusted) and ILLUSTRATIVE. Every assumption
lives in MODELS / GLOBAL below so you can argue with it in a pull request.

Run:  python3 simulation/dynasty_sim.py
"""

from __future__ import annotations

import csv
import math
from html import escape
from pathlib import Path

GLOBAL = {
    "start_wealth": 100.0,   # founder's fortune, in arbitrary units (think USD millions)
    "years": 150,            # ~5 generations
    "gen_length": 30,        # years per generation
    "kids_per_heir": 3,      # family tree branching factor
    "market_return": 0.05,   # gross real return on a diversified portfolio
}

MODELS = {
    # Split at every death, heirs spend like Gilded Age Vanderbilts.
    "A_vanderbilt": {
        "label": "A. Split & spend (Vanderbilt)",
        "spend": 0.07,            # annual consumption as share of wealth
        "fee": 0.0,
        "tax_drag": 0.0,
        "premium": 0.0,
        "ins_irr": 0.0,
        "succession_tax": 0.0,
        "succession_cost": 0.05,  # lawyers, probate, forced sales
        "insurance_pays_tax": False,
    },
    # US-style dynasty trust: pooled, members borrow (loans repaid), life
    # insurance on each member refills the pool when they die.
    "B_waterfall": {
        "label": "B. Pooled + loans + insurance (US 'Waterfall')",
        "spend": 0.02,            # net leakage: loan defaults, forgiven notes, admin perks
        "fee": 0.0075,            # trustee + advisors
        "tax_drag": 0.0,          # dynasty trust in a no-GST/no-estate-tax jurisdiction
        "premium": 0.01,          # share of pool paid each year as premiums
        "ins_irr": 0.035,         # internal return of the policies (below market)
        "succession_tax": 0.0,
        "succession_cost": 0.0,
        "insurance_pays_tax": False,
    },
    # Colombian adaptation: family holding S.A.S. + protocol + fiducia de
    # administración. Shares pass to heirs (legítima respected) but the
    # underlying assets are never divided. 15% ganancia ocasional per succession.
    "C_colombia_holding": {
        "label": "C. Holding SAS + protocol (Colombia, planned)",
        "spend": 0.02,            # dividend policy paid out to the family
        "fee": 0.0075,
        "tax_drag": 0.01,         # corporate income tax + dividend tax, net of planning
        "premium": 0.01,
        "ins_irr": 0.035,
        "succession_tax": 0.15,   # ganancia ocasional on inherited shares (ET art. 314)
        "succession_cost": 0.01,  # notarial succession, valuations
        "insurance_pays_tax": True,  # policies on parents provide heirs' liquidity
    },
    # Colombian family with no structure: assets split, moderate spending.
    "D_colombia_unplanned": {
        "label": "D. No structure (Colombia, unplanned)",
        "spend": 0.04,
        "fee": 0.0,
        "tax_drag": 0.0,
        "premium": 0.0,
        "ins_irr": 0.0,
        "succession_tax": 0.15,
        "succession_cost": 0.04,  # sucesión, avalúos, discounted fire sales
        "insurance_pays_tax": False,
    },
}

INS_PROCEEDS_TAX = 0.15  # proceeds above 3,250 UVT per beneficiary taxed as GO (ET art. 303-1); exemption ignored at this scale


def simulate(p: dict, g: dict) -> list[tuple[int, int, float, float]]:
    """Return rows of (year, heirs, total_wealth, per_capita)."""
    wealth = g["start_wealth"]
    policy_bucket = 0.0
    heirs = 1
    rows = [(0, heirs, wealth, wealth)]
    net_growth = g["market_return"] - p["fee"] - p["tax_drag"] - p["spend"]

    for year in range(1, g["years"] + 1):
        premium = wealth * p["premium"]
        wealth = (wealth - premium) * (1 + net_growth)
        policy_bucket = (policy_bucket + premium) * (1 + p["ins_irr"])

        if year % g["gen_length"] == 0:
            # Generation dies. Insurance pays out, succession is taxed, tree branches.
            tax = wealth * p["succession_tax"]
            proceeds = policy_bucket
            if p["insurance_pays_tax"]:
                proceeds *= 1 - INS_PROCEEDS_TAX
                covered = min(tax, proceeds)
                wealth -= tax - covered          # shortfall paid out of the pool
                wealth += proceeds - covered     # surplus refills the pool
            else:
                wealth += proceeds - tax
            wealth *= 1 - p["succession_cost"]
            policy_bucket = 0.0
            heirs *= g["kids_per_heir"]

        rows.append((year, heirs, wealth, wealth / heirs))
    return rows


def write_csv(results: dict, out: Path) -> None:
    keys = list(results)
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["year", "heirs"] + [f"{k}_per_capita" for k in keys] + [f"{k}_total" for k in keys])
        for i in range(len(results[keys[0]])):
            year, heirs = results[keys[0]][i][:2]
            w.writerow(
                [year, heirs]
                + [round(results[k][i][3], 4) for k in keys]
                + [round(results[k][i][2], 4) for k in keys]
            )


def write_summary(results: dict, g: dict, out: Path) -> None:
    gens = range(0, g["years"] + 1, g["gen_length"])
    lines = [
        "| Model | " + " | ".join(f"Gen {y // g['gen_length']} (yr {y})" for y in gens) + " |",
        "|---|" + "---:|" * len(gens),
    ]
    for k, rows in results.items():
        cells = [f"{rows[y][3]:,.2f}" for y in gens]
        lines.append(f"| {MODELS[k]['label']} | " + " | ".join(cells) + " |")
    heirs = [results[next(iter(results))][y][1] for y in gens]
    lines.append("| *Heirs alive* | " + " | ".join(str(h) for h in heirs) + " |")
    lines += [
        "",
        f"Per-heir real wealth, starting fortune = {g['start_wealth']:.0f}. "
        f"Market return {g['market_return']:.1%}, {g['kids_per_heir']} children per heir, "
        f"{g['gen_length']}-year generations.",
    ]
    out.write_text("\n".join(lines) + "\n")


def write_svg(results: dict, g: dict, out: Path) -> None:
    W, H = 820, 440
    L, R, T, B = 60, 290, 40, 50
    pw, ph = W - L - R, H - T - B
    colors = ["#c0392b", "#2471a3", "#1e8449", "#b9770e"]

    lo, hi = -2, 3  # log10 range: 0.01 .. 1000
    def x(year): return L + pw * year / g["years"]
    def y(v): return T + ph * (hi - math.log10(max(v, 10 ** lo))) / (hi - lo)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="Helvetica,Arial,sans-serif" font-size="12">',
        f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
        f'<text x="{L}" y="22" font-size="15" font-weight="bold" fill="#222">Real wealth per heir (log scale), start = {g["start_wealth"]:.0f}</text>',
    ]
    for e in range(lo, hi + 1):
        yy = y(10 ** e)
        parts.append(f'<line x1="{L}" y1="{yy:.1f}" x2="{L + pw}" y2="{yy:.1f}" stroke="#e5e5e5"/>')
        label = f"{10 ** e:g}"
        parts.append(f'<text x="{L - 8}" y="{yy + 4:.1f}" text-anchor="end" fill="#666">{label}</text>')
    for yr in range(0, g["years"] + 1, g["gen_length"]):
        xx = x(yr)
        parts.append(f'<line x1="{xx:.1f}" y1="{T}" x2="{xx:.1f}" y2="{T + ph}" stroke="#f0f0f0"/>')
        parts.append(f'<text x="{xx:.1f}" y="{T + ph + 18}" text-anchor="middle" fill="#666">yr {yr}</text>')
    parts.append(f'<text x="{L + pw / 2}" y="{H - 8}" text-anchor="middle" fill="#444">Years since founder\'s death (generation boundaries every {g["gen_length"]} yrs)</text>')

    for (k, rows), c in zip(results.items(), colors):
        pts = " ".join(f"{x(r[0]):.1f},{y(r[3]):.1f}" for r in rows)
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="2.2"/>')

    for i, (k, c) in enumerate(zip(results, colors)):
        ly = T + 20 + i * 44
        end = results[k][-1][3]
        parts.append(f'<line x1="{L + pw + 16}" y1="{ly}" x2="{L + pw + 36}" y2="{ly}" stroke="{c}" stroke-width="3"/>')
        label = MODELS[k]["label"]
        head, _, tail = label.partition(" (")
        parts.append(f'<text x="{L + pw + 42}" y="{ly + 4}" fill="#222">{escape(head)}</text>')
        parts.append(f'<text x="{L + pw + 42}" y="{ly + 19}" fill="#777">{escape("(" + tail)} → {end:,.3g}/heir</text>')
    parts.append("</svg>")
    out.write_text("\n".join(parts))


def main() -> None:
    out_dir = Path(__file__).resolve().parent.parent / "results"
    out_dir.mkdir(exist_ok=True)
    results = {k: simulate(p, GLOBAL) for k, p in MODELS.items()}
    write_csv(results, out_dir / "per_capita.csv")
    write_summary(results, GLOBAL, out_dir / "summary.md")
    write_svg(results, GLOBAL, out_dir / "chart.svg")
    print((out_dir / "summary.md").read_text())


if __name__ == "__main__":
    main()
