"""Base class for any source that returns a list of raw flight offers."""
from __future__ import annotations
from abc import ABC, abstractmethod


class Source(ABC):
    name: str = "unknown"

    @abstractmethod
    def fetch(self) -> list[dict]:
        """Return a list of raw offers. Each must contain at least:

          - source: str (the source name)
          - title: str (raw title text from the post)
          - url: str (canonical URL)
          - slug: str (URL slug — used for parsing)
          - posted_at: str | None (ISO date if available)

        The normalizer will pull origin/destination/price/etc. from those fields.
        """
