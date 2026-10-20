"""Pin and verify fresh NFL production inputs without pulling executable code.

A live worker downloads public, commit-pinned NFL schedule, injuries, latest
probability ladder and optional sportsbook quotes into an immutable private
bundle. A single atomic symlink selects the complete bundle. No Kalshi writes.
"""

import hashlib
import json
import os
import re
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPOSITORY = "akilatrades/sports-market-maker"
CACHE = Path("/home/trader/prod-nfl-auto/inputs/nfl")
CHECK_INTERVAL = timedelta(minutes=15)
MAX_DOWNLOAD_BYTES = 32_000_000
LADDER_PATTERN = re.compile(
    r"^outputs/nfl/projections/ladders/20\d{2}_week\d{2}_"
    r"(\d{4}-\d{2}-\d{2}T\d{4}Z)\.csv\.gz$"
)
REQUIRED = ("data/nfl/retrieval.json", "data/nfl/games.csv", "data/nfl/injuries.csv.gz")
BOOK = "outputs/books/nfl_latest.csv"


def download(url):
    request = urllib.request.Request(
        url, headers={"User-Agent": "sports-market-maker-nfl-inputs"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read(MAX_DOWNLOAD_BYTES + 1)
    if len(raw) > MAX_DOWNLOAD_BYTES:
        raise ValueError("NFL production input too large")
    return raw


def now_utc():
    return datetime.now(UTC)


def stamp(text):
    parsed = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        # nflverse fetch stamp is intentionally a date-only UTC string.
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def source_paths(tree, now):
    """Choose the newest not-future ladder in the current NFL model cohort."""
    entries = {
        item["path"]: item["sha"]
        for item in tree.get("tree", [])
        if item.get("type") == "blob"
        and isinstance(item.get("path"), str)
        and isinstance(item.get("sha"), str)
    }
    if tree.get("truncated"):
        raise ValueError("Incomplete GitHub source tree")
    if any(path not in entries for path in REQUIRED):
        raise ValueError("Missing NFL schedule/injury source blob")
    ladders = []
    for path in entries:
        match = LADDER_PATTERN.fullmatch(path)
        if match:
            made = datetime.strptime(match.group(1), "%Y-%m-%dT%H%MZ").replace(
                tzinfo=UTC
            )
            if timedelta() <= now - made <= timedelta(hours=36):
                ladders.append((made, path))
    if not ladders:
        raise ValueError("No recent NFL projection ladder in verified source")
    newest = max(ladders)[1]
    # Optional books are data, never a substitute for verified model/roster.
    paths = (*REQUIRED, newest)
    if BOOK in entries:
        paths += (BOOK,)
    return paths, entries


def verify_bundle(files, ladder, now):
    retrieval = json.loads(files["data/nfl/retrieval.json"])
    age = now - stamp(retrieval["retrieved"])
    if not timedelta() <= age <= timedelta(hours=48):
        raise ValueError("NFL schedule/injury source is stale")
    checksums = retrieval["sha256"]
    for name in ("games.csv", "injuries.csv.gz"):
        data = files["data/nfl/" + name]
        if hashlib.sha256(data).hexdigest() != checksums[name]:
            raise ValueError("NFL source checksum mismatch")
    if not files[ladder].startswith(b"\x1f\x8b"):
        raise ValueError("Invalid compressed NFL model ladder")
    if BOOK in files and not files[BOOK].startswith(b"player_key,"):
        raise ValueError("Unrecognized NFL sportsbook file schema")


def use_bundle(bundle):
    """Call before importing live.nfl_trade or markets.nfl.data/paper."""
    if not (bundle / "data/nfl/retrieval.json").exists():
        raise ValueError("Incomplete NFL production input bundle")
    os.environ["SMM_NFL_DATA_DIR"] = str(bundle / "data/nfl")
    os.environ["SMM_NFL_LADDERS_DIR"] = str(bundle / "outputs/nfl/projections/ladders")
    os.environ["SMM_NFL_RETRIEVAL"] = str(bundle / "data/nfl/retrieval.json")
    os.environ["SMM_NFL_BOOKS"] = str(bundle / BOOK)


def sync(directory=CACHE, now=None):
    """Refresh at most every 15 minutes; no git pull and no order submits."""
    now = now or now_utc()
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    active = directory / "active"
    check = directory / "last_check.json"
    try:
        checked = json.loads(check.read_text())
        if (
            active.is_dir()
            and timedelta() <= now - stamp(checked["checked_utc"]) < CHECK_INTERVAL
        ):
            use_bundle(active)
            return {"status": "cached", "source_commit": checked["source_commit"]}
    except (OSError, ValueError, KeyError, TypeError):
        pass

    head = json.loads(
        download(f"https://api.github.com/repos/{REPOSITORY}/commits/main")
    )["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("Invalid pinned GitHub commit")
    tree = json.loads(
        download(
            f"https://api.github.com/repos/{REPOSITORY}/git/trees/{head}?recursive=1"
        )
    )
    paths, blob_shas = source_paths(tree, now)
    digest = hashlib.sha256("".join(blob_shas[p] for p in paths).encode()).hexdigest()[
        :24
    ]
    version = directory / "versions" / digest
    ladder = next(p for p in paths if p.startswith("outputs/nfl/projections/ladders/"))

    if not version.is_dir():
        root = directory / "versions"
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        temp = root / (digest + ".partial")
        if temp.exists():
            raise ValueError("Incomplete NFL bundle; inspect before retry")
        temp.mkdir(mode=0o700)
        try:
            files = {}
            for path in paths:
                payload = download(
                    f"https://raw.githubusercontent.com/{REPOSITORY}/{head}/{path}"
                )
                files[path] = payload
            verify_bundle(files, ladder, now)
            for path, payload in files.items():
                target = temp / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
                target.chmod(0o600)
            temp.rename(version)
        finally:
            if temp.exists():
                for file in sorted(temp.rglob("*"), reverse=True):
                    if file.is_file():
                        file.unlink()
                    elif file.is_dir():
                        file.rmdir()
                temp.rmdir()

    # Validate the cached data against the latest real clock before use.
    cached = {p: (version / p).read_bytes() for p in paths}
    verify_bundle(cached, ladder, now)
    tmp_link = directory / ".active-next"
    if tmp_link.is_symlink():
        tmp_link.unlink()
    tmp_link.symlink_to(version, target_is_directory=True)
    os.replace(tmp_link, active)
    check.write_text(
        json.dumps(
            {
                "checked_utc": now.isoformat(),
                "source_commit": head,
                "bundle": digest,
                "model_ladder": ladder.split("/")[-1],
            }
        )
        + "\n"
    )
    check.chmod(0o600)
    use_bundle(active)
    return {"status": "verified", "source_commit": head}
