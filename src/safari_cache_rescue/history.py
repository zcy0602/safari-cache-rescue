import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

from .models import HistoryEntry


APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


class HistoryUnavailable(RuntimeError):
    pass


def datetime_to_apple_seconds(value: datetime) -> float:
    return (value.astimezone(timezone.utc) - APPLE_EPOCH).total_seconds()


def apple_seconds_to_datetime(value: float) -> datetime:
    timestamp = APPLE_EPOCH.timestamp() + float(value)
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone()


class HistoryReader:
    def __init__(self, path: Path):
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        if not self.path.exists():
            raise HistoryUnavailable("Safari History.db was not found")
        uri = "file:{}?mode=ro".format(quote(str(self.path)))
        try:
            connection = sqlite3.connect(uri, uri=True, timeout=1.0)
            connection.execute("PRAGMA query_only = ON")
            return connection
        except (OSError, sqlite3.Error) as error:
            raise HistoryUnavailable(str(error)) from error

    def probe(self) -> None:
        try:
            with closing(self._connect()) as connection:
                connection.execute("SELECT 1 FROM history_items LIMIT 1").fetchone()
        except (OSError, sqlite3.Error, HistoryUnavailable) as error:
            if isinstance(error, HistoryUnavailable):
                raise
            raise HistoryUnavailable(str(error)) from error

    def entries(
        self,
        query: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> List[HistoryEntry]:
        sql = """
            SELECT history_items.url, COALESCE(history_visits.title, ''),
                   history_visits.visit_time
            FROM history_visits
            JOIN history_items ON history_items.id = history_visits.history_item
        """
        clauses = []
        parameters = []
        if query:
            escaped = query.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append(
                "(LOWER(history_items.url) LIKE ? ESCAPE '\\' "
                "OR LOWER(COALESCE(history_visits.title, '')) LIKE ? ESCAPE '\\')"
            )
            parameters.extend(["%{}%".format(escaped), "%{}%".format(escaped)])
        if start:
            clauses.append("history_visits.visit_time >= ?")
            parameters.append(datetime_to_apple_seconds(start))
        if end:
            clauses.append("history_visits.visit_time <= ?")
            parameters.append(datetime_to_apple_seconds(end))
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY history_visits.visit_time DESC"

        try:
            with closing(self._connect()) as connection:
                rows =connection.execute(sql, parameters).fetchall()
        except (OSError, sqlite3.Error, HistoryUnavailable) as error:
            if isinstance(error, HistoryUnavailable):
                raise
            raise HistoryUnavailable(str(error)) from error
        return [
            HistoryEntry(url=row[0], title=row[1], visit_time=apple_seconds_to_datetime(row[2]))
            for row in rows
        ]
