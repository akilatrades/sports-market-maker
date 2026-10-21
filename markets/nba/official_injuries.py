"""The NBA's official injury report, read without extra libraries.

The league publishes the report as a PDF every 15 minutes at a fixed address,
for example ``Injury-Report_2026-10-21_03_15PM.pdf`` (Eastern time). Teams
file an advance report by 5 p.m. local time the day before a game (1 p.m. on
the day for the second game of a back-to-back) and a game-day report between
11 a.m. and 1 p.m. local time (8-10 a.m. for tip-offs at 5 p.m. or earlier).

The PDFs are simple: one table drawn cell by cell, every cell inside its own
clipping box, plain TrueType fonts with WinAnsi encoding, Flate-compressed
pages. So the table can be read exactly from the boxes, with only the
standard library (``requirements.txt`` stays unchanged). If the layout ever
changes, ``parse`` raises ``ReportError`` instead of guessing.

``assess`` turns the report into the bot's vetoes (see ``live/prod_nba_auto``).
"""

import os
import re
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from kalshi.books import TEAMS
from markets.nba.kalshi import normalize_name

ET = ZoneInfo("America/New_York")
URL = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_{slot}.pdf"
MAX_BYTES = 5_000_000
MAX_STREAM_BYTES = 20_000_000  # decompressed, per stream
STATUSES = ("Out", "Doubtful", "Questionable", "Probable", "Available")
HIGH_RISK = {"Out", "Doubtful", "Questionable"}
NOT_SUBMITTED = "NOT YET SUBMITTED"
HEADERS = {
    "Game Date": "game_date",
    "Game Time": "game_time",
    "Matchup": "matchup",
    "Team": "team",
    "Player Name": "player",
    "Current Status": "status",
    "Reason": "reason",
}
COLUMNS = [*HEADERS.values(), "team_espn", "player_key"]
# Kalshi team codes that differ from ESPN's (as in markets/nba/market.py).
KALSHI_TO_ESPN = {
    "SAS": "SA",
    "NYK": "NY",
    "GSW": "GS",
    "NOP": "NO",
    "UTA": "UTAH",
    "WAS": "WSH",
    "PHO": "PHX",
    "BRK": "BKN",
    "CHO": "CHA",
}
ESPN_TEAMS = {name: KALSHI_TO_ESPN.get(code, code) for name, code in TEAMS.items()}


class ReportError(ValueError):
    pass


# --- reading the PDF ---------------------------------------------------------

_TOKEN = re.compile(
    rb"\((?:\\.|[^\\()]|\((?:\\.|[^\\()])*\))*\)"  # string (one level of nesting)
    rb"|<[0-9A-Fa-f\s]*>"  # hex string
    rb"|/[^\s/\[\]()<>{}%]*"  # name
    rb"|[-+]?(?:\d+\.?\d*|\.\d+)"  # number
    rb"|[A-Za-z'\"*]+"  # operator
    rb"|\[|\]"
)
_ESCAPES = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f"}


def _literal(token):
    body, out, i = token[1:-1], bytearray(), 0
    while i < len(body):
        c = body[i : i + 1]
        if c != b"\\":
            out += c
            i += 1
            continue
        nxt = body[i + 1 : i + 2]
        octal = re.match(rb"[0-7]{1,3}", body[i + 1 : i + 4])
        if octal:
            out.append(int(octal.group(), 8) & 0xFF)
            i += 1 + len(octal.group())
        else:
            out += _ESCAPES.get(nxt, nxt)
            i += 2
    return bytes(out)


def _string(token):
    if token.startswith(b"<"):
        digits = re.sub(rb"\s", b"", token[1:-1])
        return bytes.fromhex((digits + b"0" * (len(digits) % 2)).decode())
    return _literal(token)


def _objects(data):
    """Object number -> raw bytes, from the classic cross-reference table."""
    start = data.rfind(b"startxref")
    if start < 0:
        raise ReportError("pdf_no_startxref")
    offset = int(re.match(rb"startxref\s+(\d+)", data[start:]).group(1))
    table = re.match(
        rb"xref\s+((?:\d+\s+\d+\s+(?:\d{10}\s+\d{5}\s+[fn]\s*)+)+)", data[offset:]
    )
    if not table:
        raise ReportError("pdf_unsupported_xref")
    offsets, body = {}, table.group(1)
    for section in re.finditer(
        rb"(\d+)\s+(\d+)\s+((?:\d{10}\s+\d{5}\s+[fn]\s*)+)", body
    ):
        first = int(section.group(1))
        for i, entry in enumerate(
            re.findall(rb"(\d{10})\s+\d{5}\s+([fn])", section.group(3))
        ):
            if entry[1] == b"n":
                offsets[first + i] = int(entry[0])
    # Each object runs to the next object (or the xref table): bounded slices.
    bounds = sorted({*offsets.values(), offset})
    objects = {}
    for number, at in offsets.items():
        end = next((b for b in bounds if b > at), len(data))
        head = re.match(rb"\s*(\d+)\s+\d+\s+obj", data[at:end])
        if not head or int(head.group(1)) != number:
            raise ReportError("pdf_bad_object_offset")
        objects[number] = data[at + head.end() : end]
    return objects


def _dict(obj):
    """The object's dictionary text (up to its stream or endobj)."""
    end = min(i for i in (obj.find(b"stream"), obj.find(b"endobj"), len(obj)) if i >= 0)
    return obj[:end]


def _ref(text, key):
    m = re.search(rb"/" + key + rb"\s*(\d+)\s+\d+\s+R", text)
    return int(m.group(1)) if m else None


def _stream(objects, number):
    obj = objects[number]
    head = _dict(obj)
    length = re.search(rb"/Length\s+(\d+)(\s+\d+\s+R)?", head)
    if not length:
        raise ReportError("pdf_stream_length")
    n = int(length.group(1))
    if length.group(2):  # indirect length
        n = int(re.match(rb"\s*(\d+)", objects[n]).group(1))
    m = re.search(rb"stream\r?\n", obj)
    raw = obj[m.end() : m.end() + n]
    filters = re.findall(
        rb"/(\w+)", (re.search(rb"/Filter\s*(\[[^\]]*\]|/\w+)", head) or [b"", b""])[1]
    )
    for name in filters:
        if name != b"FlateDecode":
            raise ReportError("pdf_unsupported_filter")
        inflate = zlib.decompressobj()
        out = inflate.decompress(raw, MAX_STREAM_BYTES)
        if inflate.unconsumed_tail:
            raise ReportError("pdf_stream_too_large")
        raw = out
    return raw


def _fonts(objects, page):
    """Font resource name -> (first char, widths), for spacing words."""
    resources = _dict(objects[page])
    ref = _ref(resources, b"Resources")
    if ref is not None:
        resources = _dict(objects[ref])
    block = re.search(rb"/Font\s*<<(.*?)>>", resources, re.S)
    if not block:
        ref = _ref(resources, b"Font")
        block = re.search(rb"<<(.*?)>>", _dict(objects[ref]), re.S) if ref else None
    fonts = {}
    for name, number in re.findall(
        rb"/(\w+)\s+(\d+)\s+\d+\s+R", block.group(1) if block else b""
    ):
        font = _dict(objects[int(number)])
        if b"/WinAnsiEncoding" not in font or b"/TrueType" not in font:
            raise ReportError("pdf_unsupported_font")
        first = re.search(rb"/FirstChar\s+(\d+)", font)
        widths = re.search(rb"/Widths\s*\[([^\]]*)\]", font)
        if not widths:
            ref = _ref(font, b"Widths")
            widths = re.search(rb"\[([^\]]*)\]", objects[ref]) if ref else None
        fonts[name] = (
            int(first.group(1)) if first else 0,
            [float(w) for w in widths.group(1).split()] if widths else [],
        )
    return fonts


def _pages(objects):
    catalog = next(
        (o for o in objects.values() if re.search(rb"/Type\s*/Catalog", _dict(o))), None
    )
    if catalog is None:
        raise ReportError("pdf_no_catalog")
    order = []

    def walk(number, depth=0):
        node = _dict(objects[number])
        if depth > 10:
            raise ReportError("pdf_page_tree_depth")
        if re.search(rb"/Type\s*/Pages", node):
            kids = re.search(rb"/Kids\s*\[([^\]]*)\]", node)
            for kid in re.findall(rb"(\d+)\s+\d+\s+R", kids.group(1) if kids else b""):
                walk(int(kid), depth + 1)
        elif re.search(rb"/Type\s*/Page\b", node):
            order.append(number)

    walk(_ref(_dict(catalog), b"Pages"))
    return order


def _cells(content, fonts):
    """Text drawn inside each clipping box, in drawing order.

    Returns [(x, y, width, height, lines)], where lines are lists of words.
    Words are joined without a space when the next word starts where the
    previous one ended (e.g. "Two-" + "Way").
    """
    tokens = _TOKEN.findall(content)
    stack, clip, rect, operands = [], None, None, []
    cells, current = [], None
    font, size, scale = None, 10.0, 1.0
    line_x = line_y = 0.0  # start of the current text line (text space)
    end_x = None  # where the last word ended, on the same line
    for token in tokens:
        if token[:1] in b"(<[]/" or re.match(rb"[-+.\d]", token):
            operands.append(token)
            continue
        op = token
        nums = [float(t) for t in operands if re.match(rb"[-+.\d]", t)]
        if op == b"q":  # the font is part of the saved graphics state
            stack.append((clip, font, size, scale))
        elif op == b"Q":
            clip, font, size, scale = (
                stack.pop() if stack else (None, font, size, scale)
            )
        elif op == b"re" and len(nums) >= 4:
            rect = tuple(nums[-4:])
        elif op in (b"W", b"W*"):
            clip = rect
        elif op == b"Tz" and nums:
            scale = abs(nums[-1]) / 100
        elif op == b"Tf" and nums:
            font, size = operands[-2][1:], abs(nums[-1])
        elif op == b"BT":
            line_x = line_y = 0.0
            end_x = None
        elif op in (b"Td", b"TD") and len(nums) >= 2:
            line_x, line_y = line_x + nums[-2], line_y + nums[-1]
            if nums[-1] != 0:
                end_x = None
        elif op == b"Tm" and len(nums) >= 6:
            line_x, line_y = nums[-2], nums[-1]
            end_x = None
        elif op in (b"Tj", b"TJ", b"'", b'"'):
            text = b"".join(_string(t) for t in operands if t[:1] in b"(<")
            word = text.decode("cp1252", "replace")
            if current is None or current[0] != clip:
                current = (clip, [])
                cells.append(current)
            lines = current[1]
            first, widths = fonts.get(font, (0, []))
            width = sum(
                widths[c - first] if 0 <= c - first < len(widths) else 500 for c in text
            )
            width *= size * scale / 1000
            if lines and end_x is not None and op == b"Tj":
                gap = line_x - end_x
                lines[-1][-1] += word if abs(gap) < 0.6 else " " + word
            else:
                lines.append([word])
            end_x = line_x + width
        operands = []
    return [
        (*(clip or (None, None, None, None)), [" ".join(w) for w in lines])
        for clip, lines in cells
    ]


def parse(data):
    """(report time in Eastern time, table rows) from one report PDF."""
    if not data.startswith(b"%PDF-"):
        raise ReportError("not_a_pdf")
    objects = _objects(data)
    cells = []
    for index, page in enumerate(_pages(objects)):
        node = _dict(objects[page])
        contents = re.search(rb"/Contents\s*(\[[^\]]*\]|\d+\s+\d+\s+R)", node)
        refs = re.findall(rb"(\d+)\s+\d+\s+R", contents.group(1) if contents else b"")
        content = b"\n".join(_stream(objects, int(r)) for r in refs)
        cells += [(index, *c) for c in _cells(content, _fonts(objects, page))]
    title = next(
        (" ".join(c[5]) for c in cells if " ".join(c[5]).startswith("Injury Report:")),
        "",
    )
    stamp = re.match(r"Injury Report: (\d\d/\d\d/\d\d) (\d\d:\d\d [AP]M)", title)
    if not stamp:
        raise ReportError("report_title_missing")
    issued = datetime.strptime(" ".join(stamp.groups()), "%m/%d/%y %I:%M %p")
    columns = {}
    for _, x, _, _, _, lines in cells:
        name = " ".join(lines)
        if name in HEADERS and x is not None:
            columns[round(x, 1)] = HEADERS[name]
    if sorted(columns.values()) != sorted(HEADERS.values()):
        raise ReportError("report_columns_missing")
    placed = []
    for page, x, y, _, _, lines in cells:
        text = " ".join(" ".join(lines).split())
        if (
            x is None
            or not text
            or text in HEADERS
            or text.startswith("Injury Report:")
        ):
            continue  # unclipped page footer, column headings, page title
        column = columns.get(round(x, 1))
        if column is None:  # text outside the known columns: layout changed
            raise ReportError("report_unknown_column")
        placed.append((page, y, column, text))
    # Cells of one row share a top edge (within a point or so); rows are at
    # least 20 points apart.
    rows = []
    for page, y, column, text in sorted(placed, key=lambda c: (c[0], c[1])):
        if not rows or rows[-1][0] != page or y - rows[-1][1] > 3:
            rows.append((page, y, {}))
        if column in rows[-1][2]:
            raise ReportError("report_overlapping_cells")
        rows[-1][2][column] = text
    table, carry = [], {}
    for _, _, row in rows:
        for column in ("game_date", "game_time", "matchup", "team"):
            if row.get(column):
                carry[column] = row[column]
                if column == "matchup":  # a new game starts with its first team
                    carry["team"] = row.get("team", "")
        status = row.get("status", "")
        reason = row.get("reason", "")
        player = row.get("player", "")
        if NOT_SUBMITTED in (player, status, reason):
            status, player, reason = NOT_SUBMITTED, "", ""
        elif not player and not status:
            if reason and table:  # a reason that spilled into its own row
                table[-1]["reason"] = (table[-1]["reason"] + " " + reason).strip()
            continue
        if status not in STATUSES and status != NOT_SUBMITTED:
            raise ReportError("report_unknown_status")
        if not carry.get("team"):
            raise ReportError("report_row_without_team")
        code = TEAMS.get(carry["team"])
        if code is None:
            raise ReportError("report_unknown_team")
        if code not in str(carry.get("matchup", "")).split("@"):
            raise ReportError("report_team_not_in_matchup")
        table.append({**carry, "player": player, "status": status, "reason": reason})
    frame = pd.DataFrame(table, columns=list(HEADERS.values()))
    frame["team_espn"] = frame.team.map(ESPN_TEAMS)
    frame["player_key"] = frame.player.map(player_key)
    return issued.replace(tzinfo=ET), frame


def player_key(name):
    """'Butler III, Jimmy' -> 'jimmy butler' (the same key as Kalshi's names)."""
    if not name:
        return ""
    last, _, first = str(name).partition(",")
    return normalize_name(f"{first} {last}")


# --- fetching ----------------------------------------------------------------


def slot_url(slot):
    return URL.format(slot=slot.astimezone(ET).strftime("%Y-%m-%d_%I_%M%p"))


def download(url, timeout=8):
    """The PDF bytes, or None when the report for that slot does not exist."""
    request = urllib.request.Request(
        url, headers={"User-Agent": "sports-market-maker-nba-injury-report"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        if error.code in (403, 404):  # the CDN answers 403 for missing files
            return None
        raise
    if len(data) > MAX_BYTES:
        raise ReportError("report_too_large")
    return data


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def report_at(when, back=8, fetch=None, deadline=None, cache_dir=None):
    """The newest report published at or before ``when`` (checks ``back`` slots).

    A published slot never changes, so with ``cache_dir`` each one is
    downloaded once and read from disk afterwards. ``deadline`` (a
    ``time.monotonic()`` value) stops the search; the caller also runs this
    in a thread with a hard time limit. A missing slot (or a non-PDF answer)
    moves on to the previous one; any other error is raised.
    """
    fetch = fetch or download
    slot = pd.Timestamp(when).tz_convert(ET).floor("15min").to_pydatetime()
    for _ in range(back):
        url = slot_url(slot)
        cached = None if cache_dir is None else cache_dir / url.rsplit("/", 1)[1]
        if cached is not None and cached.exists():
            return parse(cached.read_bytes())
        left = 8.0 if deadline is None else deadline - time.monotonic()
        if left <= 1:
            raise ReportError("report_fetch_deadline")
        data = fetch(url, timeout=min(8.0, left))
        if data and data.startswith(b"%PDF-"):
            result = parse(data)
            if cached is not None:
                _save(cached, data)
            return result
        slot -= timedelta(minutes=15)
    raise ReportError("no_report_found")


def from_cache(when, cache_dir, back=8):
    """The newest already-downloaded report at or before ``when`` (no network)."""
    return report_at(
        when, back=back, fetch=lambda url, timeout: None, cache_dir=cache_dir
    )


def prune(cache_dir, now, days=2):
    for path in cache_dir.glob("Injury-Report_*.pdf"):
        if path.stat().st_mtime < now.timestamp() - days * 86400:
            path.unlink(missing_ok=True)


def for_games(rows, games):
    """Rows for the given (ESPN team, Eastern game date 'MM/DD/YYYY') pairs."""
    keep = pd.Series(
        [(t, d) in games for t, d in zip(rows.team_espn, rows.game_date)],
        index=rows.index,
        dtype=bool,
    )
    return rows.loc[keep]


# --- what the bot does with it -------------------------------------------------


def _material(frame):
    """Rows that can change a rotation: high-risk statuses, not G League moves."""
    reason = frame.reason.fillna("").str.lower().str.replace(r"[^a-z]", "", regex=True)
    return frame[frame.status.isin(HIGH_RISK) & ~reason.str.contains("gleague")]


def assess(latest, baseline=None):
    """Player and team vetoes from the latest report, per game date.

    Every key carries the game date ("MM/DD/YYYY"), so a team's listing for
    tomorrow never affects tonight:

    - players: {(team, date, player_key): label}
      - Out or Doubtful: OFFICIAL_OUT_OR_DOUBTFUL
      - Questionable: UNCERTAIN_PLAYER_AVAILABILITY
      - any status change since ``baseline``: NEW_INJURY_NEWS
    - teams: {(team, date): label}
      - "not yet submitted": OFFICIAL_REPORT_NOT_SUBMITTED
      - an Out/Doubtful/Questionable listing that is new or changed since
        ``baseline`` (the report when the projections were made):
        OFFICIAL_TEAM_INJURY_CHANGE, until the next projection run
    - two_books: {(team, date)}, whose props need a fresh two-book consensus
      - a Questionable listing
      - a high-risk listing from a team that had not filed at the baseline
        (its first filing cannot be told apart from news)

    G League two-way assignments never count as a team change or make
    teammates uncertain. A team missing from a report has nothing listed (the
    league omits healthy teams). Pass rows for the games being traded only
    (``for_games``). Nothing here removes a veto from other sources.
    """
    players, teams, two_books = {}, {}, set()
    for row in latest.itertuples():
        key = (row.team_espn, row.game_date, row.player_key)
        if row.status in ("Out", "Doubtful"):
            players[key] = "OFFICIAL_OUT_OR_DOUBTFUL"
        elif row.status == "Questionable":
            players[key] = "UNCERTAIN_PLAYER_AVAILABILITY"
        elif row.status == NOT_SUBMITTED:
            teams[(row.team_espn, row.game_date)] = "OFFICIAL_REPORT_NOT_SUBMITTED"
    material = _material(latest)
    for row in material.itertuples():
        if row.status == "Questionable":
            two_books.add((row.team_espn, row.game_date))
    changed_players = 0
    if baseline is not None:
        unfiled = {
            (r.team_espn, r.game_date)
            for r in baseline.itertuples()
            if r.status == NOT_SUBMITTED
        }
        before = {
            (r.team_espn, r.game_date, r.player_key): r.status
            for r in baseline.itertuples()
            if r.player_key
        }
        for row in latest.itertuples():
            game = (row.team_espn, row.game_date)
            key = (*game, row.player_key)
            if row.player_key and game not in unfiled and before.get(key) != row.status:
                changed_players += 1
                players.setdefault(key, "NEW_INJURY_NEWS")
        for row in material.itertuples():
            game = (row.team_espn, row.game_date)
            if game in unfiled:
                two_books.add(game)
            elif before.get((*game, row.player_key)) != row.status:
                teams.setdefault(game, "OFFICIAL_TEAM_INJURY_CHANGE")
    return {
        "players": players,
        "teams": teams,
        "two_books": two_books,
        "changed_players": changed_players,
    }
