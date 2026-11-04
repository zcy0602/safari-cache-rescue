"""Best-effort reader for WebKit NetworkCache record files.

A record lives at ``Version N/Records/<partition>/Resource/<key>``. It starts
with metadata written by ``WTF::Persistence::Encoder``: little-endian integers,
and strings encoded as ``uint32 length, uint8 is8Bit, characters``. The cache
key (partition, type, identifier) comes first, so the request URL is the
length-prefixed string that follows the ``Resource`` type string.

Bodies above WebKit's inline size limit are stored in ``Blobs/<hash>``; the
record then holds that hash and a ``<key>-blob`` hard link to the blob. Smaller
bodies are appended to the record, after the encoded response header, and the
metadata holds the body size as a ``uint64``.

The format is internal to WebKit and versioned. Every function here degrades
to "no information" instead of raising, so an unrecognized record is skipped
rather than breaking the scan.
"""

import re
import struct
from typing import Container, Optional, Tuple
from urllib.parse import urlparse


METADATA_SCAN_BYTES = 8192
_HASH_SCAN_BYTES = 1024
_MAX_BODY_PREFIX = 1024
_RESOURCE_TYPE = struct.pack("<IB", 8, 1) + b"Resource"
_URL_START = re.compile(rb"https?://|h\x00t\x00t\x00p\x00(?:s\x00)?:\x00/\x00/\x00")
_BARE_URL = re.compile(rb"https?://[\x21-\x7e]+")
_HTML_START = re.compile(rb"(?i)<!doctype\s+html|<html[\s>]")


def _is_http_url(value: str) -> bool:
    if any(ord(character) <= 0x20 or ord(character) == 0x7F for character in value):
        return False
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _length_prefixed_string(data: bytes, offset: int) -> Optional[Tuple[str, int]]:
    if offset < 0 or offset + 5 > len(data):
        return None
    length, is_8bit = struct.unpack_from("<IB", data, offset)
    if length == 0 or length > 65536:
        return None
    start = offset + 5
    if is_8bit == 1:
        end, encoding = start + length, "latin-1"
    elif is_8bit == 0:
        end, encoding = start + 2 * length, "utf-16-le"
    else:
        return None
    if end > len(data):
        return None
    try:
        return data[start:end].decode(encoding), end
    except UnicodeDecodeError:
        return None


def record_url(data: bytes) -> Tuple[str, int]:
    """Return the record's request URL and the offset just past it, or ``("", 0)``."""
    head = data[:METADATA_SCAN_BYTES]
    index = head.find(_RESOURCE_TYPE)
    if index >= 0:
        parsed = _length_prefixed_string(head, index + len(_RESOURCE_TYPE))
        if parsed and _is_http_url(parsed[0]):
            return parsed
    for match in _URL_START.finditer(head):
        parsed = _length_prefixed_string(head, match.start() - 5)
        if parsed and _is_http_url(parsed[0]):
            return parsed
    match = _BARE_URL.search(head)
    if match:
        value = match.group().decode("ascii")
        if _is_http_url(value):
            return value, match.end()
    return "", 0


def linked_blob_hash(data: bytes, url_end: int, known_hashes: Container[bytes]) -> Optional[bytes]:
    """Return the 20-byte blob hash stored in the record metadata, if it names a known blob."""
    region = data[url_end : url_end + _HASH_SCAN_BYTES]
    for offset in range(len(region) - 19):
        window = region[offset : offset + 20]
        if window in known_hashes:
            return window
    return None


def inline_body_offset(data: bytes, url_end: int) -> Optional[int]:
    """Return where an inline HTML body starts, or ``None`` if the record has none.

    The body is the tail of the record. Its exact start is the offset whose
    remaining length equals a ``uint64`` stored in the metadata (the body size),
    which keeps leading whitespace or comments before ``<!doctype``. Without
    such a match, the HTML marker itself is used.
    """
    match = _HTML_START.search(data, url_end)
    if not match:
        return None
    marker = match.start()
    region = data[: min(marker, METADATA_SCAN_BYTES)]
    sizes = {struct.unpack_from("<Q", region, offset)[0] for offset in range(len(region) - 7)}
    for start in range(marker, max(url_end, marker - _MAX_BODY_PREFIX) - 1, -1):
        if len(data) - start in sizes:
            return start
    return marker
