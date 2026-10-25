"""Static page integrity; real phone scrolling is covered by the browser smoke."""

from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.anchors = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids.append(values["id"])
        if tag == "a" and values.get("href", "").startswith("#"):
            self.anchors.append(values["href"][1:])


def test_spread_page_has_unique_accessible_mounts():
    source = (ROOT / "dashboard/index.html").read_text()
    tags = Tags()
    tags.feed(source)
    assert len(tags.ids) == len(set(tags.ids))
    assert set(tags.anchors) <= set(tags.ids)
    assert {"spread-pnl", "feed-status", "contracts", "settled", "updated"} <= set(
        tags.ids
    )
    assert 'name="viewport"' in source
    assert '<html lang="en">' in source
    assert 'src="spread.js"' in source


def test_page_shows_only_spread_strategy_and_no_invented_chart():
    source = (ROOT / "dashboard/index.html").read_text()
    for retired in ("prop-maker", "research-section", "study-chart", "checkpoints"):
        assert f'id="{retired}"' not in source
    assert "NBA" not in source and "NFL" not in source
    assert "Net realized P&amp;L" in source
    assert "reconciled manual exits" in source
    assert "Open positions" in source
    assert "across strategy versions" in source
    assert "Small sample" in source
    assert "location.reload(" not in (ROOT / "dashboard/spread.js").read_text()
