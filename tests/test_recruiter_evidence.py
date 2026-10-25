"""Portfolio provenance tests: hiring-facing claims must have navigable sources.

These are content integrity checks, not market-performance assertions.
"""

import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
BRIEF = ROOT / "docs" / "PROJECT_BRIEF.md"


def test_recruiter_case_study_local_sources_exist():
    prose = BRIEF.read_text(encoding="utf-8")
    # External references have their own availability; all checked-in source
    # links must point at a real versioned file.
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", prose)
    assert links
    for link in links:
        if link.startswith(("http:", "https:", "#", "mailto:")):
            continue
        path = unquote(link.split("#", 1)[0])
        assert (BRIEF.parent / path).exists(), f"Broken project source link: {link}"


def test_recruiter_readme_does_not_say_nba_never_started():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/PROJECT_BRIEF.md" in text
    assert "NBA player props | Not started" not in text
    assert "nine accepted orders" in text.lower()
    assert "1 | Not published | 1 | Positive (amount private)" in text
    assert "not yet independently verified" in text.lower()
    assert "not a statistically" in text.lower()


def test_public_dashboard_focuses_on_actual_spread_results_with_sample_context():
    html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    assert "Net realized P&amp;L" in html
    assert "https://github.com/akilatrades/sports-market-maker" in html
    assert "Small sample. Profitability is still being evaluated." in html
    assert "reconciled manual exits and reported fees" in html


def test_case_study_does_not_blend_simulation_with_exchange_settlements():
    prose = BRIEF.read_text(encoding="utf-8")
    for term in (
        "one-sided",
        "in-sample",
        "public trade prints",
        "9 accepted orders",
        "1 fully filled",
        "signed",
        "executable NO bid did not improve",
        "AI assistance",
    ):
        assert term.lower() in prose.lower()
