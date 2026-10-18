"""Polymarket inventory probe (no conclusions): what sports markets exist, how
many are player props, what volume they carry, and what the public endpoints
return for history. Runs on GitHub Actions (the research sandbox cannot reach
Polymarket). Writes outputs/polymarket/probe.json and probe.md.

    python -m research.polymarket.probe
"""

import json
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA = "https://data-api.polymarket.com"
OUT = Path("outputs/polymarket")
import re

# A per-game player prop: a named player's stat against a threshold, or an
# event explicitly labelled as player props. Game totals ("Seahawks vs.
# Patriots: O/U 45.5") and season leaders ("lead the NBA in assists") are not.
PROP_RE = re.compile(
    r"(\d+(\.\d)?\+ ?(points|pts|rebounds|reb|assists|ast|3-pointers|threes|three-pointers|"
    r"receiving yards|rushing yards|passing yards|receptions|rec yards|rush yards|pass yards|"
    r"touchdowns?|saves|shots on goal|shots|strikeouts|hits|home runs?|total bases|goals|"
    r"steals|blocks|pra|points \+ rebounds \+ assists))|anytime (td|touchdown|goalscorer|scorer)|"
    r"to score a touchdown|to record a (double-double|triple-double)|first (td|touchdown) scorer",
    re.I,
)
SPORT_TAGS = [
    "nba",
    "nfl",
    "nhl",
    "mlb",
    "soccer",
    "epl",
    "ufc",
    "tennis",
    "cfb",
    "cbb",
    "sports",
]


def get(url, params=None, tries=3):
    if params:
        url = f"{url}?{urlencode(params)}"
    for i in range(tries):
        try:
            with urlopen(
                Request(url, headers={"User-Agent": "smm-probe/0.1"}), timeout=30
            ) as r:
                return json.loads(r.read().decode())
        except Exception as error:  # noqa: BLE001 - report and retry
            last = error
            time.sleep(1.5 * (i + 1))
    return {"error": repr(last)[:200]}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"tags": {}, "samples": {}}
    all_markets = []
    for tag in SPORT_TAGS:
        events = []
        for closed in ("false", "true"):
            offset = 0
            while True:
                page = get(
                    f"{GAMMA}/events",
                    {"tag_slug": tag, "closed": closed, "limit": 100, "offset": offset},
                )
                if not isinstance(page, list) or not page:
                    break
                events += [dict(e, _closed=closed) for e in page]
                offset += 100
                if offset >= 2000:
                    break
        markets = []
        for e in events:
            for m in e.get("markets", []) or []:
                q = (m.get("question") or "").lower()
                slug_title = f"{e.get('slug') or ''} {e.get('title') or ''}".lower()
                is_prop = (
                    bool(PROP_RE.search(q))
                    or "player prop" in slug_title
                    or "player-prop" in slug_title
                )
                markets.append(
                    {
                        "tag": tag,
                        "event": e.get("title"),
                        "event_slug": e.get("slug"),
                        "closed": e["_closed"] == "true",
                        "question": m.get("question"),
                        "is_prop": is_prop,
                        "volume": float(m.get("volumeNum") or m.get("volume") or 0),
                        "liquidity": float(
                            m.get("liquidityNum") or m.get("liquidity") or 0
                        ),
                        "condition_id": m.get("conditionId"),
                        "clob_token_ids": m.get("clobTokenIds"),
                        "end": m.get("endDate"),
                        "neg_risk": m.get("negRisk"),
                        "tick": m.get("orderPriceMinTickSize"),
                        "fees_enabled": m.get("feesEnabled", m.get("takerFeeBps")),
                    }
                )
        props = [m for m in markets if m["is_prop"]]
        report["tags"][tag] = {
            "events": len(events),
            "markets": len(markets),
            "prop_markets": len(props),
            "prop_volume": round(sum(m["volume"] for m in props)),
            "all_volume": round(sum(m["volume"] for m in markets)),
            "top_props": sorted(props, key=lambda m: -m["volume"])[:15],
        }
        all_markets += markets
        print(
            tag,
            report["tags"][tag]["events"],
            report["tags"][tag]["markets"],
            report["tags"][tag]["prop_markets"],
            flush=True,
        )
    import csv
    import gzip

    with gzip.open(OUT / "markets.csv.gz", "wt", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=list(all_markets[0].keys()) if all_markets else ["tag"]
        )
        w.writeheader()
        for m in all_markets:
            w.writerow(m)
    open_props = [
        m
        for m in all_markets
        if m["is_prop"] and not m["closed"] and m["clob_token_ids"]
    ]
    open_props.sort(key=lambda m: -m["volume"])
    for m in open_props[:2]:
        try:
            tokens = (
                json.loads(m["clob_token_ids"])
                if isinstance(m["clob_token_ids"], str)
                else m["clob_token_ids"]
            )
        except Exception:  # noqa: BLE001
            tokens = []
        tok = tokens[0] if tokens else None
        sample = {
            "market": m["question"],
            "open": True,
            "volume": m["volume"],
            "token": tok,
        }
        if tok:
            ph = get(
                f"{CLOB}/prices-history",
                {"market": tok, "interval": "max", "fidelity": 60},
            )
            sample["prices_history_points"] = (
                len(ph.get("history", [])) if isinstance(ph, dict) else ph
            )
            book = get(f"{CLOB}/book", {"token_id": tok})
            sample["book"] = (
                {k: (v[:3] if isinstance(v, list) else v) for k, v in book.items()}
                if isinstance(book, dict)
                else book
            )
        report["samples"]["open:" + str(m["condition_id"])] = sample
    # endpoint shapes on the highest-volume closed prop (settled history)
    closed_props = [
        m for m in all_markets if m["is_prop"] and m["closed"] and m["clob_token_ids"]
    ]
    closed_props.sort(key=lambda m: -m["volume"])
    for m in closed_props[:3]:
        try:
            tokens = (
                json.loads(m["clob_token_ids"])
                if isinstance(m["clob_token_ids"], str)
                else m["clob_token_ids"]
            )
        except Exception:  # noqa: BLE001
            tokens = []
        tok = tokens[0] if tokens else None
        sample = {"market": m["question"], "volume": m["volume"], "token": tok}
        if tok:
            ph = get(
                f"{CLOB}/prices-history",
                {"market": tok, "interval": "max", "fidelity": 60},
            )
            sample["prices_history_points"] = (
                len(ph.get("history", [])) if isinstance(ph, dict) else ph
            )
            sample["prices_history_first"] = (
                (ph.get("history") or [None])[0] if isinstance(ph, dict) else None
            )
            tr = get(f"{DATA}/trades", {"market": m["condition_id"], "limit": 5})
            sample["trades_sample"] = tr if isinstance(tr, list) else tr
            book = get(f"{CLOB}/book", {"token_id": tok})
            sample["book_keys"] = list(book.keys()) if isinstance(book, dict) else book
        report["samples"][m["condition_id"]] = sample
    (OUT / "probe.json").write_text(json.dumps(report, indent=1, default=str) + "\n")
    lines = [
        "# Polymarket inventory probe",
        "",
        "| Tag | Events | Markets | Prop markets | Prop volume $ | All volume $ |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for tag, t in report["tags"].items():
        lines.append(
            f"| {tag} | {t['events']} | {t['markets']} | {t['prop_markets']} | {t['prop_volume']:,} | {t['all_volume']:,} |"
        )
    lines += ["", "## Top prop markets by volume", ""]
    seen = set()
    for tag, t in report["tags"].items():
        for m in t["top_props"]:
            if m["condition_id"] in seen:
                continue
            seen.add(m["condition_id"])
            lines.append(
                f"- {m['question']} — ${m['volume']:,.0f} ({'closed' if m['closed'] else 'open'}, tick {m['tick']}, fees {m['fees_enabled']})"
            )
    (OUT / "probe.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:40]))


if __name__ == "__main__":
    main()
