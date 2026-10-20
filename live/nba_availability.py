"""Conservative NBA injury/news checks used alongside historical minutes models.

This is NOT an independently sourced projected-minutes provider or a confirmed
starting-lineup feed. An explicit restriction reported by ESPN disqualifies
affected players until a new model can incorporate the constraint.
"""

import re

# A narrow veto: ordinary "left in third quarter" and past-game recaps must
# not be interpreted as an announced minutes restriction for tonight.
_LIMIT = re.compile(
    r"\b(?:minutes?\s+(?:limit(?:ation)?|restriction|cap)|"
    r"(?:limited|restricted)\s+to\s+\d{1,2}\s+minutes?|"
    r"(?:will|expected\s+to)\s+play\s+(?:limited|restricted)\s+minutes|"
    r"(?:on|under)\s+(?:a|an)\s+minutes?\s+restriction)\b",
    re.IGNORECASE,
)


def explicit_minutes_limit(comment):
    """Only match explicit prospective minutes constraints, not vague injury."""
    return isinstance(comment, str) and bool(_LIMIT.search(comment))
