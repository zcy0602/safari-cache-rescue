from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(frozen=True)
class HistoryEntry:
    url: str
    title: str
    visit_time: datetime


@dataclass(frozen=True)
class BlobSource:
    """Cached response body: a whole ``Blobs`` file, or the tail of a record file."""

    path: Path
    cache_version: str
    # Request URL from the matching cache record, when one was found.
    url: str = ""
    # Body start inside ``path``; non-zero only for bodies stored inline in a record.
    offset: int = 0


@dataclass
class Candidate:
    sha256: str
    title: str
    domain: str
    visit_time: Optional[datetime]
    byte_length: int
    cache_version: str
    confidence: str
    match_reasons: List[str]
    source: BlobSource = field(repr=False)

    @property
    def candidate_id(self) -> str:
        return self.sha256

    def public_dict(self) -> Dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "sha256": self.sha256,
            "confidence": self.confidence,
            "title": self.title,
            "domain": self.domain,
            "visit_time": self.visit_time.isoformat() if self.visit_time else None,
            "byte_length": self.byte_length,
            "cache_version": self.cache_version,
            "match_reasons": list(self.match_reasons),
        }
