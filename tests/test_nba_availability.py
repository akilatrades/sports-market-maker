import pytest

from live.nba_availability import explicit_minutes_limit


@pytest.mark.parametrize(
    "comment",
    [
        "Will be on a minutes restriction tonight",
        "Expected to play limited minutes",
        "Coach will limit him to 22 minutes",
        "Player is on a minute limit",
        "Will be restricted to 18 minutes",
    ],
)
def test_reported_minutes_cap_is_not_ignored(comment):
    assert explicit_minutes_limit(comment)


@pytest.mark.parametrize(
    "comment",
    [
        "Scored 20 points in 33 minutes last season",
        "Probable with minor ankle soreness",
        "Questionable, decision expected before game",
        "Minutes increased each of last three games",
        "", None, float("nan"),
    ],
)
def test_no_invented_minutes_cap_from_unrelated_news(comment):
    assert not explicit_minutes_limit(comment)
