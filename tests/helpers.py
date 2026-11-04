import hashlib
import os
import sqlite3
import struct
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Tuple

from safari_cache_rescue.history import datetime_to_apple_seconds


def safari_paths(home: Path) -> Tuple[Path, Path]:
    history = home / "Library" / "Safari" / "History.db"
    cache = home / "Library" / "Caches" / "com.apple.Safari" / "WebKitCache"
    return history, cache


def create_history(path: Path, entries: Iterable[Tuple[str, str, datetime]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection, connection:
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


def _encode_string(value: str) -> bytes:
    raw = value.encode("latin-1")
    return struct.pack("<IB", len(raw), 1) + raw


def create_record(
    cache_root: Path,
    url: str,
    body: Optional[bytes] = None,
    blob_name: Optional[str] = None,
    hard_link: bool = False,
    version: str = "Version 17",
    partition: str = "example.test",
) -> Path:
    """Write a synthetic NetworkCache record laid out like WebKit's ``Storage::encodeRecord``.

    With ``body`` the body is stored inline at the end of the record. With
    ``blob_name`` the record references ``Blobs/<blob_name>`` by hash and,
    if ``hard_link`` is set, through a ``<record>-blob`` hard link.
    """
    key_hash = hashlib.sha1(url.encode()).digest()
    try:
        body_hash = bytes.fromhex(blob_name or "")
    except ValueError:
        body_hash = b""
    body_hash = body_hash or hashlib.sha1(body or b"").digest()
    header = b"\x00" * 7 + b"text/html" + b"\x00" * 9
    metadata = (
        struct.pack("<I", 17)
        + _encode_string(partition)
        + _encode_string("Resource")
        + _encode_string(url)
        + struct.pack("<I", 0xFFFFFFFF)  # null range string
        + key_hash
        + hashlib.sha1(partition.encode()).digest()
        + struct.pack("<q", 1_000_000)
        + hashlib.sha1(header).digest()
        + struct.pack("<Q", len(header))
        + body_hash
        + struct.pack("<Q", len(body) if body is not None else 4096)
        + struct.pack("<B", 1 if body is not None else 0)
    )
    checksum = hashlib.sha1(metadata).digest()
    record_dir = cache_root / version / "Records" / hashlib.sha1(partition.encode()).hexdigest() / "Resource"
    record_dir.mkdir(parents=True, exist_ok=True)
    record = record_dir / key_hash.hex()
    record.write_bytes(metadata + checksum + header + (body or b""))
    if blob_name and hard_link:
        os.link(cache_root / version / "Blobs" / blob_name, str(record) + "-blob")
    return record
