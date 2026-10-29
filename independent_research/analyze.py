"""Retrospective component tests. Never represents candle prices as fills."""

import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

OUT = Path("independent_results")
RAW = OUT / "raw"
SEED = 20261029


def clean(v):
    if isinstance(v, dict):
        return {str(k): clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, np.ndarray)):
        return [clean(x) for x in v]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return float(v) if np.isfinite(v) else None
    if isinstance(v, (pd.Timestamp, dt.date, dt.datetime)):
        return v.isoformat()
    return v


def save(name, v):
    (OUT / name).write_text(json.dumps(clean(v), indent=2, allow_nan=False) + "\n")


def bootstrap(values, block=7):
    values = np.asarray(values, float)
    values = values[np.isfinite(values)]
    n = len(values)
    if n < 2:
        return {"n": n, "mean": None, "ci95": None}
    rng = np.random.default_rng(SEED)
    means = []
    for _ in range(2000):
        starts = rng.integers(0, n, size=int(np.ceil(n / block)))
        idx = (starts[:, None] + np.arange(block)) % n
        means.append(values[idx.ravel()[:n]].mean())
    return {"n": n, "mean": values.mean(), "ci95": np.quantile(means, [0.025, 0.975])}


def point_scores(frame):
    d = {}
    for m in ["baseline", "challenger"]:
        err = frame[m] - frame.actual
        d[m] = {
            "mae": err.abs().mean(),
            "rmse": np.sqrt((err**2).mean()),
            "bias": err.mean(),
        }
    paired = (frame.baseline - frame.actual).abs() - (
        frame.challenger - frame.actual
    ).abs()
    d["mae_improvement_baseline_minus_challenger"] = bootstrap(paired)
    d["relative_mae_improvement"] = (
        1 - d["challenger"]["mae"] / d["baseline"]["mae"] if len(frame) else None
    )
    d["n_targets"] = len(frame)
    d["first"] = str(frame.date.min()) if len(frame) else None
    d["last"] = str(frame.date.max()) if len(frame) else None
    return d


HOLIDAYS = USFederalHolidayCalendar().holidays("2019-01-01", "2027-12-31")


def features(dates):
    dates = pd.DatetimeIndex(dates)
    t = (dates - pd.Timestamp("2024-01-01")).days.to_numpy() / 365.25
    cols = [np.ones(len(dates)), t]
    cols += [(dates.dayofweek == k).astype(float) for k in range(6)]
    for h in range(1, 4):
        cols += [np.sin(2 * np.pi * h * t), np.cos(2 * np.pi * h * t)]
    for shift in range(-3, 4):
        cols += [dates.isin(HOLIDAYS + pd.Timedelta(days=shift)).astype(float)]
    return np.column_stack(cols)


def tsa():
    p = OUT / "tsa_vintages.csv"
    if not p.exists():
        return {"status": "blocked", "reason": "No vintage archive retrieved"}
    f = pd.read_csv(p)
    f["snapshot"] = pd.to_datetime(f.snapshot, utc=True)
    f["date"] = pd.to_datetime(f.date).dt.normalize()
    assert not f.duplicated(["snapshot", "date"]).any()
    snapshots = {
        s: g.set_index("date").passengers.sort_index() for s, g in f.groupby("snapshot")
    }
    labels = f.sort_values("snapshot").drop_duplicates("date").set_index("date")
    snapshot_times = sorted(snapshots)
    predictions = []
    skipped = []
    for date in pd.date_range("2026-03-11", "2026-10-22"):
        origin = (date - pd.Timedelta(days=1)).tz_localize("UTC") + pd.Timedelta(
            hours=12
        )
        available = [s for s in snapshot_times if s < origin]
        if not available or (origin - available[-1]) > pd.Timedelta(days=10):
            skipped.append(
                {"date": str(date.date()), "reason": "no snapshot within 10 days"}
            )
            continue
        stamp = available[-1]
        series = snapshots[stamp]
        # The snapshot is the entire information set; dates still in its future are excluded.
        series = series[series.index < origin.tz_localize(None).normalize()]
        if date not in labels.index or labels.loc[date, "snapshot"] <= origin:
            skipped.append(
                {"date": str(date.date()), "reason": "missing or already known target"}
            )
            continue
        prior = series[series.index.dayofweek == date.dayofweek].tail(4)
        anchor = date - pd.Timedelta(days=364)
        if len(prior) < 4 or anchor not in series.index:
            skipped.append(
                {
                    "date": str(date.date()),
                    "reason": "baseline or annual anchor missing",
                }
            )
            continue
        train = series[(series.index >= date - pd.Timedelta(days=730))]
        anchors = series.reindex(train.index - pd.Timedelta(days=364)).to_numpy()
        ok = np.isfinite(anchors) & (anchors > 0) & (train.to_numpy() > 0)
        train = train[ok]
        anchors = anchors[ok]
        if len(train) < 180:
            continue
        X = features(train.index)
        y = np.log(train.to_numpy() / anchors)
        penalty = np.eye(X.shape[1]) * 10
        penalty[0, 0] = 0
        coef = np.linalg.solve(X.T @ X + penalty, X.T @ y)
        estimate = float(series.loc[anchor] * np.exp(features([date]) @ coef)[0])
        predictions.append(
            {
                "date": date,
                "origin": origin,
                "snapshot": stamp,
                "snapshot_latest_count": series.index.max(),
                "target_observed_at": labels.loc[date, "snapshot"],
                "actual": int(labels.loc[date, "passengers"]),
                "baseline": float(prior.mean()),
                "challenger": estimate,
                "train_rows": len(train),
            }
        )
    pred = pd.DataFrame(predictions)
    if pred.empty:
        return {
            "status": "blocked",
            "reason": "no eligible vintage forecasts",
            "skipped": skipped,
        }
    # Only earlier forecast errors whose target had appeared by the origin may calibrate.
    thresholds = np.array([1_500_000, 2_000_000, 2_500_000, 3_000_000])
    for i, row in pred.iterrows():
        history = pred[
            (pred.date < row.date) & (pred.target_observed_at < row.origin)
        ].tail(60)
        if len(history) < 30:
            continue
        outcomes = (row.actual > thresholds).astype(float)
        for m in ["baseline", "challenger"]:
            residual = np.log(history.actual / history[m]).to_numpy()
            samples = row[m] * np.exp(residual)
            probs = ((samples[:, None] > thresholds).sum(axis=0) + 1) / (
                len(samples) + 2
            )
            pred.loc[i, m + "_brier"] = np.mean((probs - outcomes) ** 2)
            pred.loc[i, m + "_log_score"] = -np.mean(
                outcomes * np.log(probs) + (1 - outcomes) * np.log1p(-probs)
            )
            lo, hi = np.quantile(samples, [0.05, 0.95])
            pred.loc[i, m + "_covered90"] = int(lo <= row.actual <= hi)
            pred.loc[i, m + "_width90"] = hi - lo
    pred.to_csv(OUT / "tsa_predictions.csv", index=False)
    test = pred[pred.date >= "2026-07-01"].copy()
    result = point_scores(test)
    result.update(
        {
            "status": "forecast_proxy_completed",
            "no_trading_pnl": True,
            "label": "first observed in third-party weekly archive; first official release not verified",
            "snapshots": len(snapshots),
            "all_forecasts": len(pred),
            "skipped": len(skipped),
            "protocol": "one preceding-day 12 UTC origin per target; known snapshot only; fixed ridge=10",
            "thresholds": thresholds.tolist(),
            "max_feature_snapshot_age_days": (
                (test.origin - test.snapshot).dt.total_seconds() / 86400
            ).max(),
        }
    )
    for m in ["baseline", "challenger"]:
        for metric in ["brier", "log_score", "covered90", "width90"]:
            col = m + "_" + metric
            result[m][metric] = test[col].mean() if col in test else None
    if "baseline_brier" in test:
        scored = test.dropna(subset=["baseline_brier", "challenger_brier"])
        result["brier_improvement"] = bootstrap(
            scored.baseline_brier - scored.challenger_brier
        )
    result["by_month"] = {
        str(k): point_scores(g) for k, g in test.groupby(test.date.dt.to_period("M"))
    }
    result["revisions_after_first_observed"] = int(
        (f.groupby("date").passengers.nunique() > 1).sum()
    )
    save("tsa_skips.json", skipped)
    return result


def weather(station, tz):
    files = sorted((RAW / "weather").glob(station + "_20????.csv"))
    if not files:
        return {"status": "blocked", "reason": "no forecast archive"}
    frames = []
    for p in files:
        try:
            frames.append(pd.read_csv(p, low_memory=False))
        except Exception:
            pass
    if not frames:
        return {"status": "blocked", "reason": "forecast files empty"}
    f = pd.concat(frames, ignore_index=True)
    required = {"runtime", "ftime", "tmp"}
    if not required.issubset(f.columns):
        return {
            "status": "blocked",
            "reason": "unexpected schema",
            "columns": list(f.columns),
        }
    f["runtime"] = pd.to_datetime(f.runtime, utc=True, errors="coerce")
    f["ftime"] = pd.to_datetime(f.ftime, utc=True, errors="coerce")
    f["tmp"] = pd.to_numeric(f.tmp, errors="coerce")
    f = f[(f.runtime.dt.hour == 0) & f.tmp.between(-80, 140)].drop_duplicates(
        ["runtime", "ftime"]
    )
    f["date"] = f.runtime.dt.tz_localize(None).dt.normalize()
    f["local_date"] = f.ftime.dt.tz_convert(tz).dt.tz_localize(None).dt.normalize()
    f = f[f.local_date == f.date]
    f["local_hour"] = f.ftime.dt.tz_convert(tz).dt.hour
    g = f.groupby("date").agg(
        baseline=("tmp", "max"),
        grid_points=("tmp", "size"),
        first_hour=("local_hour", "min"),
        last_hour=("local_hour", "max"),
    )
    # Eight three-hourly points are an approximation to the daily maximum, not an exact max forecast.
    g = g[(g.grid_points >= 8) & (g.first_hour <= 3) & (g.last_hour >= 21)]
    labels = []
    for p in sorted((RAW / "weather").glob(station + "_cli_*.json")):
        d = json.loads(p.read_text())
        labels += d.get("results", [])
    h = pd.DataFrame(labels)
    if not {"valid", "high"}.issubset(h.columns):
        return {
            "status": "blocked",
            "reason": "missing CLI target schema",
            "columns": list(h.columns),
        }
    h["date"] = pd.to_datetime(h.valid, errors="coerce").dt.normalize()
    h["actual"] = pd.to_numeric(h.high, errors="coerce")
    h = (
        h[h.actual.between(-80, 140)]
        .sort_values("date")
        .drop_duplicates("date", keep="last")
    )
    g = g.join(h.set_index("date").actual).dropna(subset=["actual"]).sort_index()
    rows = []
    for date, row in g.iterrows():
        past = g[
            (g.index >= date - pd.Timedelta(days=61))
            & (g.index <= date - pd.Timedelta(days=2))
        ]
        if len(past) < 30:
            continue
        bias = (past.actual - past.baseline).mean()
        rows.append(
            {
                "date": date,
                "actual": row.actual,
                "baseline": row.baseline,
                "challenger": row.baseline + bias,
                "train_rows": len(past),
                "grid_points": row.grid_points,
            }
        )
    pred = pd.DataFrame(rows)
    if pred.empty:
        return {
            "status": "blocked",
            "reason": "no complete grids with labels",
            "joined_days": len(g),
        }
    pred.to_csv(OUT / f"weather_{station}_predictions.csv", index=False)
    test = pred[(pred.date >= "2026-01-01") & (pred.date <= "2026-09-30")]
    result = point_scores(test)
    result.update(
        {
            "status": "forecast_component_completed",
            "no_trading_pnl": True,
            "station": station,
            "raw_forecast_rows": len(f),
            "joined_days": len(g),
            "label": "NWS CLI archive; exchange settlement and revision identity not verified",
            "signal": "00 UTC GFS MOS temperature grid max for local day; fixed trailing bias correction",
            "limitations": [
                "grid maximum approximates daily maximum",
                "assumed 6-hour publication lag, receipt timestamps absent",
                "not an NBM distribution or intraday conditional-nowcast test",
                "two cities, shared regional shocks",
            ],
        }
    )
    result["by_month"] = {
        str(k): point_scores(v) for k, v in test.groupby(test.date.dt.to_period("M"))
    }
    return result


def dollars(block):
    if not isinstance(block, dict):
        return np.nan
    for key in ["close_dollars", "close"]:
        try:
            value = float(block[key])
            return value if 0 <= value <= 1 else np.nan
        except (KeyError, ValueError, TypeError):
            continue
    return np.nan


def structural():
    if not (OUT / "market_sample.json").exists():
        return {"status": "blocked", "reason": "no market metadata"}
    markets = json.loads((OUT / "market_sample.json").read_text())
    records = []
    meta = {}
    coverage = {}
    invalid = 0
    for m in markets:
        meta[m["ticker"]] = m
        series = m["ticker"].split("-")[0]
        p = RAW / "candles" / f"{m['ticker']}.json"
        if not p.exists():
            continue
        cs = json.loads(p.read_text()).get("candlesticks", [])
        for c in cs:
            b, a = dollars(c.get("yes_bid")), dollars(c.get("yes_ask"))
            t = pd.Timestamp(c["end_period_ts"], unit="s", tz="UTC")
            # Exclude final/after-close candles. A rule-specific outcome-time screen is still required.
            if t >= pd.Timestamp(m["close_time"]):
                continue
            if not np.isfinite(b + a) or not (0 <= b <= a <= 1):
                invalid += 1
                continue
            records.append(
                {
                    "ticker": m["ticker"],
                    "event": m["event_ticker"],
                    "series": series,
                    "timestamp": t,
                    "bid": b,
                    "ask": a,
                }
            )
    if not records:
        return {
            "status": "blocked",
            "reason": "no valid historical bid/ask pairs",
            "invalid_rows": invalid,
        }
    f = pd.DataFrame(records)
    checks = []
    # Ordinary binary complement checks (no assumptions about cross-market rules).
    for r in f.itertuples():
        margin = r.bid - r.ask
        checks.append(
            {
                "kind": "same_binary",
                "series": r.series,
                "event": r.event,
                "timestamp": r.timestamp,
                "leg1": r.ticker,
                "leg2": r.ticker,
                "margin_before_costs": margin,
            }
        )
    # Within-event ordered threshold inversions. Rule identity is not certified.
    for (event, timestamp), g in f.groupby(["event", "timestamp"]):
        rs = list(g.itertuples())
        for i, x in enumerate(rs):
            a = meta[x.ticker]
            if a.get("strike_type") not in ["greater", "greater_or_equal"]:
                continue
            try:
                sa = float(a["floor_strike"])
            except (ValueError, TypeError, KeyError):
                continue
            for y in rs[i + 1 :]:
                b = meta[y.ticker]
                if b.get("strike_type") != a.get("strike_type"):
                    continue
                try:
                    sb = float(b["floor_strike"])
                except (ValueError, TypeError, KeyError):
                    continue
                if sa == sb:
                    continue
                lower, upper = (x, y) if sa < sb else (y, x)
                checks.append(
                    {
                        "kind": "nested_threshold",
                        "series": x.series,
                        "event": event,
                        "timestamp": timestamp,
                        "leg1": lower.ticker,
                        "leg2": upper.ticker,
                        "margin_before_costs": upper.bid - lower.ask,
                    }
                )
    c = pd.DataFrame(checks)
    positives = c[c.margin_before_costs > 1e-9].copy()
    positives.to_csv(OUT / "structural_positive_candidates.csv", index=False)
    c.groupby(["series", "kind"]).agg(
        checks=("margin_before_costs", "size"),
        best_margin=("margin_before_costs", "max"),
        positives=("margin_before_costs", lambda x: int((x > 1e-9).sum())),
    ).reset_index().to_csv(OUT / "structural_counts.csv", index=False)
    for s, g in f.groupby("series"):
        coverage[s] = {
            "markets": g.ticker.nunique(),
            "events": g.event.nunique(),
            "quote_dates": g.timestamp.dt.date.nunique(),
            "candle_rows": len(g),
            "first": g.timestamp.min(),
            "last": g.timestamp.max(),
        }
    return {
        "status": "historical_price_screen_completed",
        "no_trading_pnl": True,
        "valid_bid_ask_rows": len(f),
        "invalid_or_crossed_rows": invalid,
        "checks": len(c),
        "positive_raw_candidates": len(positives),
        "candidate_events": positives.event.nunique(),
        "max_raw_margin": c.margin_before_costs.max(),
        "coverage": coverage,
        "limitations": [
            "no historical depth or quote-update age",
            "candle close timestamps do not ensure simultaneous executable quotes",
            "rule versions, exceptional settlement, fees, publication cutoff and failed-leg execution not certified",
            "no exhaustive-bucket basket test without complete interval/rule certification",
        ],
        "candidate_definition": "positive ordinary-payout price inconsistency before fees, not realized profit",
    }


def main():
    results = {
        "run_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "scope": "independent research only",
        "analysis_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "trading_backtests_completed": 0,
    }
    for name, fn in [
        ("tsa", tsa),
        ("weather_jfk", lambda: weather("KJFK", "America/New_York")),
        ("weather_ord", lambda: weather("KORD", "America/Chicago")),
        ("structural", structural),
    ]:
        try:
            results[name] = fn()
        except Exception as e:
            import traceback

            traceback.print_exc()
            results[name] = {"status": "error", "error": str(e)}
    results["spx"] = {
        "status": "blocked",
        "missing": "timestamp-matched historical SPXW option bid/ask surface and matched settlement audit",
    }
    results["macro"] = {
        "status": "data_audit_only",
        "missing": "frozen challenger, first-release/vintage series joined to market quotes",
    }
    results["politics_mentions_entertainment"] = {
        "status": "not_a_defined_strategy",
        "missing": "one recurring contract family, fixed signal, point-in-time text/poll inputs and target rules",
    }
    results["short_crypto_gold"] = {
        "status": "blocked",
        "missing": "synchronized underlying feeds and event books with measured receipt/latency/depth; minute bars insufficient",
    }
    save("results.json", results)
    print(json.dumps(clean(results), indent=2, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
