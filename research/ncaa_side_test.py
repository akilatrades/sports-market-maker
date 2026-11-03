"""College basketball on the spread maker's replay: NO only, YES only or both?

RESEARCH_LOG.md, 2026-11-03, "College basketball: sell NO only on first-half
spreads? (pre-registered)". SIMULATED and in-sample: the 24-to-4-hour scan
(``outputs/scan_24h``), one contract per side per hourly quote, held to
settlement, v6 quote rule unless stated.

    python -m research.ncaa_side_test   # outputs/research/ncaa_side_test.json
"""

import json
from pathlib import Path

from research.fills_first_sweep import (
    DRAWS,
    median_draw,
    spread_fills,
    spread_quotes,
    spread_variant,
    summary,
)

OUT = Path("outputs/research/ncaa_side_test.json")
PRIMARY = "KXNCAAMB1HSPREAD"
SERIES = (PRIMARY, "KXNCAAMB1HTOTAL", "KXNCAAWBGAME", "KXNCAAWBSPREAD", "KXNCAAWBTOTAL")
SIDES = {"no_only": ("no",), "yes_only": ("yes",), "both": ("yes", "no")}


def table(v):
    out = {}
    for name, sides in SIDES.items():
        s = v[v.side.isin(sides)]
        first = summary(spread_fills(s, 1.0), "event_ticker")
        flow = median_draw(
            [summary(spread_fills(s, 0.25, d), "event_ticker") for d in range(DRAWS)]
        )
        out[name] = {"quotes": len(s), "first_in_line": first, "flow_0.25": flow}
    return out


def main():
    q = spread_quotes()
    v6 = spread_variant(q, 24, None, 0.04, True)
    res = {
        "note": "SIMULATED, in-sample; RESEARCH_LOG.md 2026-11-03",
        "series": {},
    }
    for series in SERIES:
        v = v6[v6.series.eq(series)]
        res["series"][series] = {
            "events": int(v.event_ticker.nunique()),
            "v6": table(v),
        }
    wide = spread_variant(q, 24, None, 0.08, True)
    res["series"][PRIMARY]["8c_plus"] = table(wide[wide.series.eq(PRIMARY)])
    p = res["series"][PRIMARY]["v6"]
    no, yes = p["no_only"]["flow_0.25"], p["yes_only"]["flow_0.25"]
    both = p["both"]["flow_0.25"]
    res["pass"] = bool(
        (no.get("cents") or -1) > 0
        and (no.get("t") or 0) >= 2
        and (yes.get("cents") if yes.get("cents") is not None else 1) <= 0
        and (no.get("dollars") or 0) > (both.get("dollars") or 0)
        and (no.get("earlier_cents") or -1) > 0
        and (no.get("later_cents") or -1) > 0
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1) + "\n")
    return res


if __name__ == "__main__":
    r = main()
    for s, block in r["series"].items():
        print(f"== {s} ({block['events']} events)")
        for key in ("v6", "8c_plus"):
            if key not in block:
                continue
            for side, cell in block[key].items():
                f, a = cell["flow_0.25"], cell["first_in_line"]
                print(
                    f"  {key:7s} {side:8s} quotes {cell['quotes']:6d} | "
                    f"flow fills {f['fills']:5d} {f.get('cents')!s:>6}c "
                    f"t {f.get('t')!s:>5} ${f.get('dollars')!s:>7} "
                    f"halves {f.get('earlier_cents')!s:>6}/{f.get('later_cents')!s:>6} | "
                    f"first {a['fills']:5d} {a.get('cents')!s:>6}c"
                )
    print("PASS", r["pass"])
