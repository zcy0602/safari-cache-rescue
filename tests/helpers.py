import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable, Tuple

from safari_cache_rescue.history import datetime_to_apple_seconds


def safari_paths(home: Path) -> Tuple[Path, Path]:
    history = home / "Library" / "Safari" / "History.db"
    cache = home / "Library" / "Caches" / "com.apple.Safari" / "WebKitCache"
    return history, cache


def create_history(path: Path, entries: Iterable[Tuple[str, str, datetime]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE history_items (
                id INTEGER PRIMARY KEY,
                url TEXT NOT NULL
            );
            CREATE TABLE history_visits (
                id INTEGER PRIMARY KEY,
                history_item INTEGER NOT NULL,
                visit_time REAL NOT NULL,
                title TEXT
            );
            """
        )
        for index, (url, title, visit_time) in enumerate(entries, start=1):
            connection.execute("INSERT INTO history_items(id, url) VALUES (?, ?)", (index, url))
            connection.execute(
                "INSERT INTO history_visits(id, history_item, visit_time, title) VALUES (?, ?, ?, ?)",
                (index, index, datetime_to_apple_seconds(visit_time), title),
            )


def create_blob(cache_root: Path, name: str, data: bytes, version: str = "Version 17") -> Path:
    blob = cache_root / version / "Blobs" / name
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(data)
    return blob


def complete_html(title: str, body: str, encoding: str = "utf-8") -> bytes:
    document = "<!doctype html><html><head><title>{}</title></head><body>{}</body></html>".format(
        title, body
    )
    return document.encode(encoding)

