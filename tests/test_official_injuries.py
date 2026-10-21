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
from markets.nba.official_injuries import download as real_download

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
    """One clipped cell; words placed with Td like the league's generator.

    A space starts a new word after a gap; "|" splits a word into pieces drawn
    separately with no gap (the league draws "Two-" and "Way" that way).
    """
    out = [f"q\n{x} {y} 100 {height} re\nW* n\nBT\n0 g"]
    prev_end = 0.0  # x offset of the last piece on the previous line
    for i, line in enumerate(lines):
        pieces = []
        for word in line.split(" "):
            parts = word.split("|")
            pieces += [(parts[0], True)] + [(part, False) for part in parts[1:]]
        if i == 0:
            out.append(f"{x + 5} {y + 14.5} Td ({_escape(pieces[0][0])}) Tj")
        else:
            out.append(f"{-prev_end} 11 Td ({_escape(pieces[0][0])}) Tj")
        pos = 0.0
        for (previous, _), (piece, gap) in zip(pieces, pieces[1:]):
            step = len(previous) * WIDTH / 100 + (2.5 if gap else 0)
            out.append(f"{step} 0 Td ({_escape(piece)}) Tj")
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
            for column in HEADER_TEXT:
                x = COLUMNS_X[column]
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


TONIGHT_DATE = "10/21/2026"
TONIGHT = [
    [
        {
            "game_date": TONIGHT_DATE,
            "game_time": "07:00 (ET)",
            "matchup": "ATL@ORL",
            "team": "Atlanta Hawks",
            "player": "Dennis, RayJ",
            "status": "Questionable",
            "reason": "G League - Two-|Way",
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
        {"player": "Isaac, Jonathan", "status": "Doubtful", "reason": "Injury"},
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
    teams = ["ATL", "ATL", "ORL", "ORL", "GS", "LAL", "DEN", "OKC"]
    assert rows.team_espn.tolist() == teams
    assert rows.matchup.tolist()[3:6] == ["ATL@ORL", "GSW@LAL", "GSW@LAL"]
    assert rows.game_date.tolist()[-2:] == ["10/22/2026", "10/22/2026"]
    assert rows.status.tolist()[-2:] == [official.NOT_SUBMITTED] * 2
    assert rows.reason[2] == "Injury/Illness - Right Ankle Sprain"
    assert rows.reason[0] == "G League - Two-Way"  # pieces drawn with no gap
    assert rows.reason[1] == "Injury/Illness - Left Foot Fracture"
    assert rows.player_key[4] == "jimmy butler"


def _first_row(**change):
    return [[{**TONIGHT[0][0], **change}]]


def test_layout_changes_raise_instead_of_guessing():
    with pytest.raises(official.ReportError, match="not_a_pdf"):
        official.parse(b"<html>")
    with pytest.raises(official.ReportError, match="columns"):
        official.parse(report_pdf(TONIGHT, header=False))
    with pytest.raises(official.ReportError, match="unknown_status"):
        official.parse(report_pdf(_first_row(status="Maybe")))
    with pytest.raises(official.ReportError, match="unknown_team"):
        official.parse(report_pdf(_first_row(team="Seattle SuperSonics")))
    with pytest.raises(official.ReportError, match="not_in_matchup"):
        official.parse(report_pdf(_first_row(matchup="BOS@NYK")))
    teamless = [[{"player": "Gueye, Mouhamed", "status": "Out", "reason": "x"}]]
    with pytest.raises(official.ReportError, match="without_team"):
        official.parse(report_pdf(teamless))


def test_text_outside_the_known_columns_raises(monkeypatch):
    monkeypatch.setitem(COLUMNS_X, "note", 760.0)  # a new column, no heading
    with pytest.raises(official.ReportError, match="unknown_column"):
        official.parse(report_pdf(_first_row(note="extra")))


def test_oversized_streams_are_refused(monkeypatch):
    monkeypatch.setattr(official, "MAX_STREAM_BYTES", 100)
    with pytest.raises(official.ReportError, match="too_large"):
        official.parse(report_pdf(TONIGHT))


def test_report_address_uses_eastern_quarter_hours():
    utc = datetime(2026, 10, 21, 19, 29, tzinfo=timezone.utc)
    slot = pd.Timestamp(utc).tz_convert(official.ET).floor("15min")
    assert official.slot_url(slot).endswith("Injury-Report_2026-10-21_03_15PM.pdf")
    assert official.slot_url(slot - timedelta(hours=15, minutes=15)).endswith(
        "Injury-Report_2026-10-21_12_00AM.pdf"
    )
    assert official.slot_url(slot - timedelta(hours=3, minutes=15)).endswith(
        "Injury-Report_2026-10-21_12_00PM.pdf"
    )


WHEN = datetime(2026, 10, 21, 19, 40, tzinfo=timezone.utc)  # 3:40 PM ET


def test_newest_report_is_found_by_stepping_back(tmp_path):
    pdf = report_pdf(TONIGHT)
    asked = []

    def fetch(url, timeout):
        asked.append(url.rsplit("_", 1)[-1])
        if len(asked) == 1:
            return b"<html>not yet</html>"  # an error page counts as missing
        return pdf if len(asked) == 3 else None

    issued, rows = official.report_at(WHEN, fetch=fetch, cache_dir=tmp_path)
    assert asked == ["30PM.pdf", "15PM.pdf", "00PM.pdf"]
    assert len(rows) == 8
    # Saved under its slot name; the next look reads the disk, not the site.
    assert [p.name for p in tmp_path.glob("*.pdf")] == [
        "Injury-Report_2026-10-21_03_00PM.pdf"
    ]
    asked.clear()
    assert len(official.report_at(WHEN, fetch=fetch, cache_dir=tmp_path)[1]) == 8
    assert asked == ["30PM.pdf", "15PM.pdf"]  # misses still checked, hit cached
    assert len(official.from_cache(WHEN, tmp_path)[1]) == 8
    with pytest.raises(official.ReportError, match="no_report_found"):
        official.from_cache(WHEN - timedelta(hours=1), tmp_path)


def test_errors_and_deadline_stop_the_search():
    def broken(url, timeout):
        raise OSError("down")

    with pytest.raises(OSError):
        official.report_at(WHEN, fetch=broken)
    with pytest.raises(official.ReportError, match="no_report_found"):
        official.report_at(WHEN, fetch=lambda url, timeout: None, back=2)
    with pytest.raises(official.ReportError, match="deadline"):
        official.report_at(WHEN, fetch=broken, deadline=time.monotonic())


def test_download_maps_missing_files_and_refuses_huge_ones(monkeypatch):
    import io
    import urllib.error
    import urllib.request

    def answer(code=None, body=b"%PDF-1.4"):
        def urlopen(request, timeout):
            assert "sports-market-maker" in request.get_header("User-agent")
            if code:
                raise urllib.error.HTTPError(request.full_url, code, "x", {}, None)
            return io.BytesIO(body)

        return urlopen

    for code in (403, 404):
        monkeypatch.setattr(urllib.request, "urlopen", answer(code))
        assert real_download("https://example.invalid/x.pdf") is None
    monkeypatch.setattr(urllib.request, "urlopen", answer(500))
    with pytest.raises(urllib.error.HTTPError):
        real_download("https://example.invalid/x.pdf")
    monkeypatch.setattr(urllib.request, "urlopen", answer(body=b"%PDF-1.4"))
    assert real_download("https://example.invalid/x.pdf") == b"%PDF-1.4"
    monkeypatch.setattr(official, "MAX_BYTES", 3)
    with pytest.raises(official.ReportError, match="too_large"):
        real_download("https://example.invalid/x.pdf")


def _rows(*items, date=TONIGHT_DATE):
    return pd.DataFrame(
        [
            {
                "team_espn": team,
                "player_key": official.player_key(player),
                "player": player,
                "status": status,
                "reason": reason,
                "game_date": item_date,
            }
            for team, player, status, reason, *rest in items
            for item_date in [rest[0] if rest else date]
        ]
    )


T = TONIGHT_DATE
TOMORROW = "10/22/2026"


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
        ("LAL", T, "collin sexton"): "UNCERTAIN_PLAYER_AVAILABILITY",
        ("GS", T, "jimmy butler"): "OFFICIAL_OUT_OR_DOUBTFUL",
        ("BOS", T, "jaylen brown"): "NEW_INJURY_NEWS",
        ("ATL", T, "rayj dennis"): "OFFICIAL_OUT_OR_DOUBTFUL",
        ("DEN", T, "nikola jokic"): "UNCERTAIN_PLAYER_AVAILABILITY",
        ("MIA", T, "tyler herro"): "OFFICIAL_OUT_OR_DOUBTFUL",
    }
    assert result["teams"] == {
        ("LAL", T): "OFFICIAL_TEAM_INJURY_CHANGE",
        ("MIA", T): "OFFICIAL_TEAM_INJURY_CHANGE",
        ("OKC", T): "OFFICIAL_REPORT_NOT_SUBMITTED",
    }
    # Questionable (LAL, DEN) and a first filing after the model (DEN).
    assert result["two_books"] == {("LAL", T), ("DEN", T)}
    # Without a baseline there is no "since the model" comparison.
    assert set(official.assess(latest)["teams"]) == {("OKC", T)}


def test_tomorrows_listing_never_touches_tonight():
    """A back-to-back: LAL plays tonight and tomorrow."""
    baseline = _rows(
        ("LAL", "Sexton, Collin", "Questionable", "Injury", T),
        ("LAL", "", official.NOT_SUBMITTED, "", TOMORROW),
    )
    latest = _rows(
        ("LAL", "Sexton, Collin", "Questionable", "Injury", T),
        ("LAL", "Sexton, Collin", "Out", "Injury", TOMORROW),  # rest tomorrow
        ("LAL", "James, LeBron", "Out", "Injury", TOMORROW),
    )
    result = official.assess(latest, baseline)
    assert ("LAL", T) not in result["teams"]
    assert result["players"][("LAL", T, "collin sexton")] == (
        "UNCERTAIN_PLAYER_AVAILABILITY"
    )
    assert ("LAL", T, "lebron james") not in result["players"]
    # Tomorrow not yet filed at the model's time does not switch off
    # tonight's change rule.
    worse = _rows(
        ("LAL", "Sexton, Collin", "Out", "Injury", T),
        ("LAL", "", official.NOT_SUBMITTED, "", TOMORROW),
    )
    assert official.assess(worse, baseline)["teams"] == {
        ("LAL", T): "OFFICIAL_TEAM_INJURY_CHANGE",
        ("LAL", TOMORROW): "OFFICIAL_REPORT_NOT_SUBMITTED",
    }


def test_for_games_filters_by_team_and_date_and_handles_empty_reports():
    rows = _rows(("OKC", "", official.NOT_SUBMITTED, "", TOMORROW))
    assert official.for_games(rows, {("OKC", T)}).empty
    assert len(official.for_games(rows, {("OKC", TOMORROW)})) == 1
    empty = official.for_games(rows.iloc[0:0], {("OKC", T)})
    assert list(empty.columns) == list(rows.columns)
    assert official.assess(empty, empty)["teams"] == {}


# --- inside the bot ------------------------------------------------------------


@pytest.fixture
def bot(tmp_path, monkeypatch):
    """Run nba_candidates for one LAL prop tonight, with the report website
    replaced by ``pages_by_slot``: {slot ET 'HH:MM': report rows}."""
    from tests.test_prod_nba_auto import NOW, priced
    from live import prod_nba_auto as nba
    from live.nba_inputs import publish
    import kalshi.books as books
    import live.nba_trade as trader
    import markets.nba.live as source

    tip = pd.Timestamp(NOW + timedelta(hours=4))
    tonight = tip.tz_convert(official.ET).strftime("%m/%d/%Y")
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
                    "tip_utc": tip,
                }
            ]
        ),
    )
    monkeypatch.setattr(trader, "refresh_quotes", lambda f, now: f.copy())
    books_n = {"n": 2}
    monkeypatch.setattr(books, "attach_latest", lambda f: f.assign(book_n=books_n["n"]))
    monkeypatch.setattr(
        source,
        "injuries",
        lambda: pd.DataFrame(columns=["player_id", "team", "updated", "out"]),
    )
    latest = tmp_path / "inputs" / "latest.csv"
    latest.parent.mkdir()
    priced().to_csv(latest, index=False)
    model_utc = NOW - timedelta(hours=1)
    publish(priced(), latest.parent, model_utc)
    now_slot = pd.Timestamp(NOW).tz_convert(official.ET).floor("15min")
    model_slot = pd.Timestamp(model_utc).tz_convert(official.ET).floor("15min")

    def run(latest_rows=None, baseline_rows=None, books=2, delay=0.0, newest=None):
        """Rows are lists of row dicts for the LAL/GS game tonight."""
        books_n["n"] = books
        newest_slot = newest if newest is not None else now_slot

        def page(rows, slot):
            items = [
                {
                    "game_date": tonight,
                    "game_time": "10:00 (ET)",
                    "matchup": "LAL@GSW",
                    "team": "Los Angeles Lakers",
                    **rows[0],
                },
                *rows[1:],
            ]
            return report_pdf([items], issued=slot.strftime("%m/%d/%y %I:%M %p"))

        def fetch(url, timeout=8):
            time.sleep(delay)
            name = url.rsplit("/", 1)[1]
            if latest_rows is not None and name in official.slot_url(newest_slot):
                return page(latest_rows, newest_slot)
            if baseline_rows is not None and name in official.slot_url(model_slot):
                return page(baseline_rows, model_slot)
            return None

        monkeypatch.setattr(official, "download", fetch)
        return nba.nba_candidates(NOW, latest=latest)

    run.cache = latest.parent / "official_injury_reports"
    run.now_slot = now_slot

    def clear():  # a new situation: reports already downloaded are forgotten
        for path in run.cache.glob("*.pdf"):
            path.unlink()

    run.clear = clear
    return run


def _player(name, status, reason="Injury"):
    return {"player": name, "status": status, "reason": reason}


def _report(out):
    return out.attrs["diagnostics"]["official_injury_report"]


def test_bot_ignores_an_unreadable_report_and_says_so(bot):
    out = bot()
    assert len(out) == 1 and out.injury_status.iloc[0] == ""
    assert _report(out) == {"status": "unavailable", "reason": "no_report_found"}


def test_bot_vetoes_a_questionable_player(bot):
    out = bot([_player("Player, Test", "Questionable")])
    assert out.injury_status.iloc[0] == "UNCERTAIN_PLAYER_AVAILABILITY"
    report = _report(out)
    assert report["status"] == "ok" and report["vetoed_rows"] == 1
    assert report["baseline_issued_et"] is None  # no baseline report on file


def test_bot_vetoes_the_team_after_news_since_the_projection(bot):
    before = [_player("Guy, Other", "Probable")]
    after = [_player("Guy, Other", "Out")]
    out = bot(after, before)
    assert out.injury_status.iloc[0] == "OFFICIAL_TEAM_INJURY_CHANGE"
    report = _report(out)
    assert list(report["team_vetoes"].values()) == ["OFFICIAL_TEAM_INJURY_CHANGE"]
    json.dumps(report)  # goes into last_scan.json
    # Unchanged since the projection: no team veto, the teammate trades.
    bot.clear()
    assert bot(after, after).injury_status.iloc[0] == ""


def test_questionable_teammate_needs_two_books(bot):
    rows = [_player("Guy, Other", "Questionable")]
    assert bot(rows, rows, books=2).injury_status.iloc[0] == ""
    bot.clear()
    out = bot(rows, rows, books=1)
    assert out.injury_status.iloc[0] == "UNCERTAIN_TEAM_REQUIRES_TWO_BOOKS"


def test_bot_rejects_a_stale_report(bot):
    old = bot.now_slot - timedelta(minutes=75)
    out = bot([_player("Player, Test", "Out")], newest=old)
    assert _report(out) == {"status": "unavailable", "reason": "report_too_old"}
    assert out.injury_status.iloc[0] == ""


def test_hard_time_limit_and_cached_fallback(bot, monkeypatch):
    from live import prod_nba_auto as nba

    rows = [_player("Player, Test", "Out")]
    earlier = bot.now_slot - timedelta(minutes=15)
    assert bot(rows, newest=earlier).injury_status.iloc[0] == "OFFICIAL_OUT_OR_DOUBTFUL"
    monkeypatch.setattr(nba, "OFFICIAL_REPORT_SECONDS", 0.3)
    started = time.monotonic()
    # The newest slot stalls; the copy already on disk is used instead.
    out = bot(rows, delay=2.0)
    assert time.monotonic() - started < 1.5
    report = _report(out)
    assert report["status"] == "ok" and report["latest_from_cache"] is True
    assert report["fetch_error"] == "report_fetch_deadline"
    assert out.injury_status.iloc[0] == "OFFICIAL_OUT_OR_DOUBTFUL"
    bot.clear()
    out = bot(rows, delay=2.0)  # nothing cached: ESPN checks only
    assert _report(out) == {"status": "unavailable", "reason": "report_fetch_deadline"}
    assert out.injury_status.iloc[0] == ""


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
    out = bot([_player("Player, Test", "Questionable")])
    assert out.injury_status.iloc[0] == "TEAM_INJURY_CHANGE"


def test_an_error_after_download_never_blocks_the_scan(bot, monkeypatch):
    def broken(*args, **kwargs):
        raise KeyError("player_key")

    monkeypatch.setattr(official, "assess", broken)
    out = bot([_player("Player, Test", "Questionable")])
    assert len(out) == 1 and out.injury_status.iloc[0] == ""
    assert _report(out) == {"status": "unavailable", "reason": "KeyError"}


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


def test_truncated_streams_and_unwritable_cache(tmp_path, monkeypatch):
    pdf = report_pdf(TONIGHT)
    cut = zlib.compress(b"q 1 0 0 1 0 0 cm Q" * 50)[:-8]  # stream ends early
    objects = official._objects(pdf)
    number = next(n for n, o in objects.items() if b"/FlateDecode" in official._dict(o))
    monkeypatch.setitem(
        objects,
        number,
        b" << /Length %d /Filter/FlateDecode >>\nstream\n%s" % (len(cut), cut),
    )
    with pytest.raises(official.ReportError, match="truncated"):
        official._stream(objects, number)

    def readonly(path, data):
        raise PermissionError("read-only")

    monkeypatch.setattr(official, "_save", readonly)
    fetch = lambda url, timeout: pdf  # noqa: E731
    assert len(official.report_at(WHEN, fetch=fetch, cache_dir=tmp_path)[1]) == 8
