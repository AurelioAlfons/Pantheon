"""The contracts every integration adapter honours -- real and mock implement the same shape.

Protocol rather than ABC on purpose: the real and mock adapters share no implementation,
only a shape, so there's no base class worth inheriting. Structural typing says what an
adapter must look like without forcing an inheritance chain nobody needs.
"""

from typing import Protocol, TypedDict


class WebFinding(TypedDict):
    """one web search hit, already boiled down to what Hermes actually reports"""

    title: str
    url: str
    note: str
    date: str  # when the source is from, "unknown" if it can't be established -- research goes stale


class GitHubFinding(TypedDict):
    """one repo worth knowing about"""

    repo: str
    url: str
    note: str
    last_activity: str  # ISO date of the last push, "unknown" if the API didn't say


class WebSearchAdapter(Protocol):
    """searches the web -- real one asks Claude, mock returns canned findings"""

    def search(self, query: str) -> list[WebFinding]: ...


class GitHubAdapter(Protocol):
    """checks GitHub for relevant repo activity"""

    def check_activity(self, query: str) -> list[GitHubFinding]: ...
