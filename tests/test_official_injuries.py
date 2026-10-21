"""The NBA's official injury report: reading the PDF and the bot's vetoes.

The PDFs here are built by ``report_pdf`` in the same shape as the league's
(one clipped box per cell, TrueType WinAnsi fonts, Flate streams, a classic
cross-reference table). The reader was also checked by hand against the real
reports of 2026-10-21 03:00 PM and 03:15 PM ET (81 rows each, every name and
status matching pdfplumber's text); those files are not committed.
"""

import json
import time
import zlib
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from markets.nba import official_injuries as official

WIDTH = 500  # every glyph is 5 points wide at size 10 in the test fonts
COLUMNS_X = {
    "game_date": 19.1488,
    "game_time": 115.5871,
    "matchup": 195.9523,
    "team": 260.2445,
    "player": 420.975,
    "status": 581.7055,
    "reason": 662.0708,
}
HEADER_TEXT = {
    "game_date": "Game Date",
    "game_time": "Game Time",
    "matchup": "Matchup",
    "team": "Team",
    "player": "Player Name",
    "status": "Current Status",
    "reason": "Reason",
}


def _escape(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _cell(x, y, lines, height=22.0):
    """One clipped cell; words placed with Td like the league's generator."""
    out = [f"q\n{x} {y} 100 {height} re\nW* n\nBT\n0 g"]
    prev_end = 0.0  # x offset of the last word on the previous line
    for i, line in enumerate(lines):
        words = line.split(" ")
        start_x, start_y = x + 5, y + 14.5 + 11 * i
        if i == 0:
            out.append(f"{start_x} {start_y} Td ({_escape(words[0])}) Tj")
        else:
            out.append(f"{-prev_end} 11 Td ({_escape(words[0])}) Tj")
        pos = 0.0
        for previous, word in zip(words, words[1:]):
            step = len(previous) * WIDTH / 100 + 2.5  # a space
            out.append(f"{step} 0 Td ({_escape(word)}) Tj")
            pos += step
        prev_end = pos
    out.append("ET\nQ")
    return "\n".join(out)


def report_pdf(pages, issued="10/21/26 03:15 PM", header=True):
    """A report PDF. ``pages`` is a list of pages, each a list of row dicts
    (keys from COLUMNS_X; a value may be a list of lines; ``_dy`` shifts a
    row's team cell down, as the league's PDFs sometimes do)."""
    streams = []
    for index, rows in enumerate(pages):
        parts = [
            "q\n1 0 0 -1 0 595.35 cm -100 Tz",
            "q\n84.195 35.4 757.755 40 re\nW* n\nBT\n1 g\n/F0 -22 Tf",
            f"289.1 62.0 Td ({' '.join(issued.split()[:1])}) Tj",
            "ET\nQ",
            "BT\n/F1 -10 Tf\n398.5 545.4 Td (Page) Tj\nET",
        ]
        # The title, word by word (Injury Report: <date> <time> <AM/PM>).
        words = ["Injury", "Report:", *issued.split()]
        title = ["q\n84.195 35.4 757.755 40 re\nW* n\nBT\n1 g\n/F0 -22 Tf"]
        title.append(f"289.1 62.0 Td ({words[0]}) Tj")
        for previous, word in zip(words, words[1:]):
            title.append(f"{len(previous) * WIDTH * 22 / 1000 + 5.5} 0 Td ({word}) Tj")
        title.append("ET\nQ")
        parts[1:4] = ["\n".join(title)]
        y = 100.4
        if header and index == 0:
            for column, x in COLUMNS_X.items():
                parts.append("q\n/F0 -10 Tf\n" + _cell(x, y, [HEADER_TEXT[column]])[2:])
            y += 21.3
        for row in rows:
            for column, value in row.items():
                if column.startswith("_"):
                    continue
                lines = value if isinstance(value, list) else [value]
                shift = row.get("_dy", 0) if column == "team" else 0
                parts.append(_cell(COLUMNS_X[column], y + shift, lines))
            lines = [len(v) for v in row.values() if isinstance(v, list)]
            y += 22.0 + 11 * (max(lines, default=1) - 1)
        parts.append("Q")
        streams.append(zlib.compress("\n".join(parts).encode("cp1252")))
    widths = " ".join([str(WIDTH)] * 256)
    objects = {
        1: "<< /Type/Catalog /Pages 2 0 R >>",
        3: f"<< /Type/Font /Subtype/TrueType /BaseFont/AAAAAA+Bold /Encoding/WinAnsiEncoding /FirstChar 0 /LastChar 255 /Widths[{widths}] >>",
        4: f"<< /Type/Font /Subtype/TrueType /BaseFont/BBBBBB+Calibri /Encoding/WinAnsiEncoding /FirstChar 0 /LastChar 255 /Widths[{widths}] >>",
    }
    kids = []
    for i, stream in enumerate(streams):
        page, content = 10 + 2 * i, 11 + 2 * i
        kids.append(f"{page} 0 R")
        objects[page] = (
            "<< /Type/Page /MediaBox[0 0 841.95 595.35] /Parent 2 0 R "
            f"/Contents {content} 0 R /Resources << /Font << /F0 3 0 R /F1 4 0 R >> >> >>"
        )
        objects[content] = stream
    objects[2] = f"<< /Type/Pages /Count {len(kids)} /Kids[{' '.join(kids)}] >>"
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        body = objects[number]
        if isinstance(body, bytes):
            out += (
                f"{number} 0 obj\n<< /Length {len(body)} /Filter/FlateDecode >>\nstream\n".encode()
                + body
                + b"\nendstream\nendobj\n"
            )
        else:
            out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    size = max(objects) + 1
    xref = len(out)
    out += f"xref\n0 {size}\n0000000000 65535 f \n".encode()
    for number in range(1, size):
        if number in offsets:
            out += f"{offsets[number]:010d} 00000 n \n".encode()
        else:
            out += b"0000000000 65535 f \n"
    out += (
        f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


TONIGHT = [
    [
        {
            "game_date": "10/21/2026",
            "game_time": "07:00 (ET)",
            "matchup": "ATL@ORL",
            "team": "Atlanta Hawks",
            "player": "Dennis, RayJ",
            "status": "Questionable",
            "reason": "G League - Two-Way",
        },
        {
            "player": "Gueye, Mouhamed",
            "status": "Out",
            "reason": "Injury/Illness - Left Foot Fracture",
        },
        {
            "team": "Orlando Magic",
            "player": "Black, Anthony",
            "status": "Out",
            "reason": ["Injury/Illness - Right Ankle", "Sprain"],
        },
    ],
    [
        # The page break keeps the game and team going.
        {
            "player": "Isaac, Jonathan",
            "status": "Doubtful",
            "reason": "Injury/Illness - Left Knee",
        },
        {
            "game_time": "10:00 (ET)",
            "matchup": "GSW@LAL",
            "team": "Golden State Warriors",
            "player": "Butler III, Jimmy",
            "status": "Questionable",
            "reason": "Injury/Illness - Right Knee",
        },
        {
            "team": "Los Angeles Lakers",
            "player": "Sexton, Collin",
            "status": "Probable",
            "reason": "Rest",
        },
        {
            "game_date": "10/22/2026",
            "game_time": "09:30 (ET)",
            "matchup": "DEN@OKC",
            "team": "Denver Nuggets",
            "reason": "NOT YET SUBMITTED",
        },
        {"team": "Oklahoma City Thunder", "reason": "NOT YET SUBMITTED", "_dy": 1.0},
    ],
]


def test_reads_rows_games_teams_and_wrapped_reasons_across_pages():
    issued, rows = official.parse(report_pdf(TONIGHT))
    assert issued == datetime(2026, 10, 21, 15, 15, tzinfo=official.ET)
    assert rows.player.tolist() == [
        "Dennis, RayJ",
        "Gueye, Mouhamed",
        "Black, Anthony",
        "Isaac, Jonathan",
        "Butler III, Jimmy",
        "Sexton, Collin",
        "",
        "",
    ]
    assert rows.team_espn.tolist() == [
        "ATL",
        "ATL",
        "ORL",
        "ORL",
        "GS",
        "LAL",
        "DEN",
        "OKC",
    ]
    assert rows.matchup.tolist()[3:6] == ["ATL@ORL", "GSW@LAL", "GSW@LAL"]
    assert rows.game_date.tolist()[-2:] == ["10/22/2026", "10/22/2026"]
    assert rows.status.tolist()[-2:] == [official.NOT_SUBMITTED] * 2
    assert rows.reason[2] == "Injury/Illness - Right Ankle Sprain"
    assert rows.reason[0] == "G League - Two-Way"  # no space where none was drawn
    assert rows.player_key[4] == "jimmy butler"


def test_layout_changes_raise_instead_of_guessing():
    with pytest.raises(official.ReportError, match="not_a_pdf"):
        official.parse(b"<html>")
    with pytest.raises(official.ReportError, match="columns"):
        official.parse(report_pdf(TONIGHT, header=False))
    odd = [[{**TONIGHT[0][0], "status": "Maybe"}]]
    with pytest.raises(official.ReportError, match="unknown_status"):
        official.parse(report_pdf(odd))
    teamless = [[{"player": "Gueye, Mouhamed", "status": "Out", "reason": "x"}]]
    with pytest.raises(official.ReportError, match="without_team"):
        official.parse(report_pdf(teamless))


def test_report_address_uses_eastern_quarter_hours():
    utc = datetime(2026, 10, 21, 19, 29, tzinfo=timezone.utc)
    slot = pd.Timestamp(utc).tz_convert(official.ET).floor("15min")
    assert official.slot_url(slot).endswith("Injury-Report_2026-10-21_03_15PM.pdf")
    assert official.slot_url(slot - timedelta(hours=15, minutes=15)).endswith(
        "Injury-Report_2026-10-21_12_00AM.pdf"
    )


def test_newest_report_is_found_by_stepping_back_and_errors_stop_the_search():
    pdf = report_pdf(TONIGHT)
    asked = []

    def fetch(url, timeout):
        asked.append(url.rsplit("_", 2)[-2:])
        return pdf if len(asked) == 3 else None

    when = datetime(2026, 10, 21, 19, 40, tzinfo=timezone.utc)  # 3:40 PM ET
    issued, rows = official.report_at(when, fetch=fetch)
    assert [a[1] for a in asked] == ["30PM.pdf", "15PM.pdf", "00PM.pdf"]
    assert len(rows) == 8

    def broken(url, timeout):
        raise OSError("down")

    with pytest.raises(OSError):
        official.report_at(when, fetch=broken)
    with pytest.raises(official.ReportError, match="no_report_found"):
        official.report_at(when, fetch=lambda url, timeout: None, back=2)
    with pytest.raises(official.ReportError, match="deadline"):
        official.report_at(when, fetch=fetch, deadline=time.monotonic())


def _rows(*items):
    return pd.DataFrame(
        [
            {
                "team_espn": team,
                "player_key": official.player_key(player),
                "player": player,
                "status": status,
                "reason": reason,
                "game_date": "10/21/2026",
            }
            for team, player, status, reason in items
        ]
    )


def test_assess_player_and_team_rules():
    baseline = _rows(
        ("LAL", "Sexton, Collin", "Probable", "Injury"),
        ("GS", "Butler III, Jimmy", "Out", "Injury"),
        ("BOS", "Brown, Jaylen", "Questionable", "Injury"),
        ("DEN", "", official.NOT_SUBMITTED, ""),
    )
    latest = _rows(
        ("LAL", "Sexton, Collin", "Questionable", "Injury"),  # worse since the model
        ("GS", "Butler III, Jimmy", "Out", "Injury"),  # unchanged
        ("BOS", "Brown, Jaylen", "Available", "Injury"),  # better: player only
        ("ATL", "Dennis, RayJ", "Out", "G League - Two-Way"),  # G League only
        ("DEN", "Jokic, Nikola", "Questionable", "Injury"),  # first filing
        ("OKC", "", official.NOT_SUBMITTED, ""),
        ("MIA", "Herro, Tyler", "Doubtful", "Injury"),  # team healthy before
    )
    result = official.assess(latest, baseline)
    assert result["players"] == {
        ("LAL", "collin sexton"): "UNCERTAIN_PLAYER_AVAILABILITY",
        ("GS", "jimmy butler"): "OFFICIAL_OUT_OR_DOUBTFUL",
        ("BOS", "jaylen brown"): "NEW_INJURY_NEWS",
        ("ATL", "rayj dennis"): "OFFICIAL_OUT_OR_DOUBTFUL",
        ("DEN", "nikola jokic"): "UNCERTAIN_PLAYER_AVAILABILITY",
        ("MIA", "tyler herro"): "OFFICIAL_OUT_OR_DOUBTFUL",
    }
    assert result["teams"] == {
        "LAL": "OFFICIAL_TEAM_INJURY_CHANGE",
        "MIA": "OFFICIAL_TEAM_INJURY_CHANGE",
        "OKC": "OFFICIAL_REPORT_NOT_SUBMITTED",
    }
    assert result["uncertain_teams"] == {"LAL", "DEN"}
    # Without a baseline there is no "since the model" comparison.
    assert set(official.assess(latest)["teams"]) == {"OKC"}


def test_report_ahead_of_espn_requires_two_books_for_teammates():
    latest = _rows(
        ("MIA", "Herro, Tyler", "Out", "Injury"),
        ("LAL", "Sexton, Collin", "Out", "Injury"),
        ("ATL", "Dennis, RayJ", "Out", "G League - Two-Way"),
    )
    espn = pd.DataFrame(
        [{"team": "LAL", "player": "Collin Sexton", "status": "Day-To-Day"}]
    )
    result = official.assess(latest, None, espn)
    assert result["ahead_of_espn_teams"] == ["MIA"]
    assert result["uncertain_teams"] == {"MIA"}


def test_only_tonights_games_count():
    rows = _rows(("OKC", "", official.NOT_SUBMITTED, ""))
    rows.loc[0, "game_date"] = "10/22/2026"
    assert official.for_games(rows, {("OKC", "10/21/2026")}).empty
    assert len(official.for_games(rows, {("OKC", "10/22/2026")})) == 1


# --- inside the bot ------------------------------------------------------------


@pytest.fixture
def bot(tmp_path, monkeypatch):
    from tests.test_prod_nba_auto import NOW, priced
    from live import prod_nba_auto as nba
    from live.nba_inputs import publish
    import kalshi.books as books
    import live.nba_trade as trader
    import markets.nba.live as source

    monkeypatch.setattr(source, "rosters", lambda teams: {"LAL": {1234}})
    monkeypatch.setattr(
        source,
        "scoreboard",
        lambda day, season: pd.DataFrame(
            [
                {
                    "game_id": 20261020,
                    "home": "GS",
                    "away": "LAL",
                    "completed": False,
                    "tip_utc": pd.Timestamp(NOW + timedelta(hours=4)),
                }
            ]
        ),
    )
    monkeypatch.setattr(trader, "refresh_quotes", lambda f, now: f.copy())
    monkeypatch.setattr(books, "attach_latest", lambda f: f.copy())
    monkeypatch.setattr(
        source,
        "injuries",
        lambda: pd.DataFrame(columns=["player_id", "team", "updated", "out"]),
    )
    latest = tmp_path / "latest.csv"
    priced().to_csv(latest, index=False)
    publish(priced(), tmp_path, NOW - timedelta(hours=1))
    tonight = (
        pd.Timestamp(NOW + timedelta(hours=4))
        .tz_convert(official.ET)
        .strftime("%m/%d/%Y")
    )

    def run(latest_rows=None, baseline_rows=None):
        def report_at(when, deadline=None, **kw):
            rows = baseline_rows if when != NOW else latest_rows
            if rows is None:
                raise official.ReportError("no_report_found")
            rows = rows.assign(game_date=tonight)
            return pd.Timestamp(when).tz_convert(official.ET).floor("15min"), rows

        monkeypatch.setattr(official, "report_at", report_at)
        return nba.nba_candidates(NOW, latest=latest)

    return run


def test_bot_ignores_an_unreadable_report_and_says_so(bot):
    out = bot()
    assert len(out) == 1 and out.injury_status.iloc[0] == ""
    report = out.attrs["diagnostics"]["official_injury_report"]
    assert report == {"status": "unavailable", "reason": "no_report_found"}


def test_bot_vetoes_a_questionable_player(bot):
    out = bot(_rows(("LAL", "Test Player", "Questionable", "Injury")))
    assert out.injury_status.iloc[0] == "UNCERTAIN_PLAYER_AVAILABILITY"
    report = out.attrs["diagnostics"]["official_injury_report"]
    assert report["status"] == "ok" and report["vetoed_rows"] == 1
    assert report["baseline_error"] == "ReportError"


def test_bot_vetoes_the_team_after_news_since_the_projection(bot):
    before = _rows(("LAL", "Other Guy", "Probable", "Injury"))
    after = _rows(("LAL", "Other Guy", "Out", "Injury"))
    out = bot(after, before)
    assert out.injury_status.iloc[0] == "OFFICIAL_TEAM_INJURY_CHANGE"
    report = out.attrs["diagnostics"]["official_injury_report"]
    assert report["team_vetoes"] == {"LAL": "OFFICIAL_TEAM_INJURY_CHANGE"}
    json.dumps(report)  # goes into last_scan.json
    # No change since the projection: no team veto, and the teammate trades.
    same = bot(after, after)
    assert same.injury_status.iloc[0] == ""


def test_bot_never_replaces_an_existing_veto(bot, monkeypatch):
    import markets.nba.live as source
    from tests.test_prod_nba_auto import NOW

    monkeypatch.setattr(
        source,
        "injuries",
        lambda: pd.DataFrame(
            [
                {
                    "player_id": 1234,
                    "team": "LAL",
                    "updated": NOW.isoformat(),
                    "out": True,
                }
            ]
        ),
    )
    out = bot(_rows(("LAL", "Test Player", "Questionable", "Injury")))
    assert out.injury_status.iloc[0] == "TEAM_INJURY_CHANGE"


def test_cancel_record_names_the_veto(tmp_path):
    from tests.test_prod_nba_auto import NOW, priced
    from live import prod_nba_auto as nba

    row = priced().iloc[0].copy()
    row["injury_status"] = "OFFICIAL_TEAM_INJURY_CHANGE"
    ticker = str(row.ticker)
    events = [
        {
            "event": "intent",
            "client_order_id": "cid",
            "ticker": ticker,
            "price_cents": 51,
            "count": 1,
            "probability_source": "sportsbook",
        },
        {"event": "accepted", "client_order_id": "cid", "order_id": "oid"},
    ]

    class Client:
        def cancel(self, order_id, ticker=None):
            pass

    journal = tmp_path / "journal.jsonl"
    state = {"resting": [{"order_id": "oid", "ticker": ticker}]}
    nba.cancel_invalid_resting(
        Client(), journal, state, pd.DataFrame([row]), NOW, events
    )
    saved = [json.loads(line) for line in journal.read_text().splitlines()]
    assert saved[0]["reason"] == "unverified_roster_injury_or_model"
    assert saved[0]["veto"] == "OFFICIAL_TEAM_INJURY_CHANGE"


def test_an_error_after_download_never_blocks_the_scan(bot, monkeypatch):
    def broken(*args, **kwargs):
        raise KeyError("player_key")

    monkeypatch.setattr(official, "assess", broken)
    out = bot(_rows(("LAL", "Test Player", "Questionable", "Injury")))
    assert len(out) == 1 and out.injury_status.iloc[0] == ""
    report = out.attrs["diagnostics"]["official_injury_report"]
    assert report == {"status": "unavailable", "reason": "KeyError"}
