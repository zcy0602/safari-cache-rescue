import codecs
import hashlib
import html
import json
import os
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from . import cache_records
from .history import HistoryReader, HistoryUnavailable
from .models import BlobSource, Candidate, HistoryEntry


MAX_HTML_BYTES = 64 * 1024 * 1024
_TITLE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")
_TAG = re.compile(r"(?s)<[^>]+>")
_LINK_TAG = re.compile(r"(?is)<link\b[^>]*>")
_ATTRIBUTE = re.compile(r"""(?s)([^\s"'<>/=]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""")
_META_CHARSET = re.compile(r"""(?i)<meta\b[^>]*?charset\s*=\s*["']?\s*([a-z0-9._:-]+)""")
_HTML_MARKERS = ("<!doctype html", "<html", "<head", "<title")
# Labels that browsers (per the WHATWG Encoding spec) decode with a superset codec.
_CHARSET_ALIASES = {
    "gb2312": "gb18030",
    "gbk": "gb18030",
    "x-gbk": "gb18030",
    "big5": "big5hkscs",
    "shift_jis": "cp932",
    "shift-jis": "cp932",
    "sjis": "cp932",
    "x-sjis": "cp932",
    "euc-kr": "cp949",
    "iso-8859-1": "cp1252",
    "latin1": "cp1252",
    "us-ascii": "cp1252",
    "ascii": "cp1252",
}
_WORD = re.compile(r"\w+", re.UNICODE)


class CacheUnavailable(RuntimeError):
    pass


class CandidateUnavailable(RuntimeError):
    pass


class ExportFailure(RuntimeError):
    pass


def default_history_path(home: Optional[Path] = None) -> Path:
    base = home or Path.home()
    return base / "Library" / "Safari" / "History.db"


def default_cache_roots(home: Optional[Path] = None) -> List[Path]:
    base = home or Path.home()
    return [
        base / "Library" / "Caches" / "com.apple.Safari" / "WebKitCache",
        base
        / "Library"
        / "Containers"
        / "com.apple.Safari"
        / "Data"
        / "Library"
        / "Caches"
        / "com.apple.Safari"
        / "WebKitCache",
    ]


def normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def meaningful_tokens(value: str) -> List[str]:
    return list(dict.fromkeys(token.casefold() for token in _WORD.findall(value) if len(token) >= 2))


def _has_html_marker(text: str) -> bool:
    lowered = text[:65536].casefold()
    return any(marker in lowered for marker in _HTML_MARKERS)


def declared_charset(data: bytes) -> Optional[str]:
    """Return the Python codec for a ``<meta charset>`` declaration, if any."""
    match = _META_CHARSET.search(data[:65536].decode("latin-1"))
    if not match:
        return None
    label = match.group(1).casefold()
    if label.startswith("utf-16"):
        # A meta tag readable as ASCII cannot really be UTF-16; browsers use UTF-8.
        label = "utf-8"
    label = _CHARSET_ALIASES.get(label, label)
    try:
        return codecs.lookup(label).name
    except LookupError:
        return None


def decode_html(data: bytes) -> Optional[str]:
    prefix = data[:65536]
    if prefix.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings = ["utf-16"]
    elif prefix.startswith(b"\xef\xbb\xbf"):
        encodings = ["utf-8-sig"]
    else:
        # Strict UTF-8 first: non-ASCII text in legacy encodings is almost never valid UTF-8.
        encodings = ["utf-8"]
        declared = declared_charset(prefix)
        if declared and declared != "utf-8":
            encodings.append(declared)
    for encoding in encodings:
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if _has_html_marker(text):
            return text
    # Last resort: a stray invalid byte should not hide an otherwise readable page.
    # Export always copies the original bytes, so this only affects matching.
    text = data.decode(encodings[-1], errors="replace")
    return text if _has_html_marker(text) else None


def looks_like_html(data: bytes) -> bool:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        prefix = data.decode("utf-16", errors="ignore")
    else:
        prefix = data.decode("utf-8-sig", errors="ignore")
    return _has_html_marker(prefix)


def extract_title(text: str) -> str:
    match = _TITLE.search(text)
    if not match:
        return ""
    return " ".join(html.unescape(_TAG.sub("", match.group(1))).split())


_INVISIBLE = re.compile(r"(?is)<!--.*?-->|<(script|style|noscript|template|svg|head)\b.*?</\1\s*>")
_BLOCK_BOUNDARY = re.compile(
    r"(?i)<(?:br|/?(?:p|div|li|ul|ol|tr|table|h[1-6]|section|article|header|footer|blockquote|pre))\b[^>]*>"
)


def html_to_text(text: str) -> List[str]:
    """Return the readable paragraphs of an HTML document, for previews only."""
    visible = _BLOCK_BOUNDARY.sub("\n", _INVISIBLE.sub(" ", text))
    plain = html.unescape(_TAG.sub(" ", visible))
    paragraphs = []
    for block in plain.split("\n"):
        paragraph = " ".join(block.split())
        if paragraph:
            paragraphs.append(paragraph)
    return paragraphs


def is_complete_html(text: str) -> bool:
    lowered = text.casefold()
    return "</html>" in lowered and ("</body>" in lowered or "<body" not in lowered)


def domain_from_url(value: str) -> str:
    try:
        return (urlparse(value).hostname or "").casefold()
    except ValueError:
        return ""


def normalize_url_identity(value: str) -> str:
    try:
        parsed = urlparse(html.unescape(value.strip()))
    except ValueError:
        return ""
    if not parsed.scheme or not parsed.netloc:
        return ""
    return parsed._replace(
        scheme=parsed.scheme.casefold(),
        netloc=parsed.netloc.casefold(),
        path=parsed.path or "/",
        fragment="",
    ).geturl()


def canonical_url_from_html(text: str) -> str:
    for tag in _LINK_TAG.finditer(text):
        attributes: Dict[str, str] = {}
        for attribute in _ATTRIBUTE.finditer(tag.group(0)):
            value = next(group for group in attribute.group(2, 3, 4) if group is not None)
            attributes.setdefault(attribute.group(1).casefold(), value)
        if "canonical" in attributes.get("rel", "").casefold().split():
            href = html.unescape(attributes.get("href", "")).strip()
            if href:
                return href
    return ""


def domain_from_html(text: str) -> str:
    return domain_from_url(canonical_url_from_html(text))


def read_stable(path: Path, offset: int = 0) -> Optional[bytes]:
    """Read the bytes of ``path`` from ``offset``, or ``None`` if not HTML or changed while reading."""
    try:
        before = path.stat()
        if before.st_size <= offset or before.st_size > MAX_HTML_BYTES:
            return None
        with path.open("rb") as handle:
            handle.seek(offset)
            prefix = handle.read(65536)
            if not looks_like_html(prefix):
                return None
            handle.seek(0)
            data = handle.read()
        after = path.stat()
    except (FileNotFoundError, PermissionError, OSError):
        return None
    identity_before = (before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after or len(data) != before.st_size:
        return None
    return data[offset:]


def _read_record(path: Path) -> Optional[bytes]:
    try:
        if path.stat().st_size > MAX_HTML_BYTES:
            return None
        return path.read_bytes()
    except OSError:
        return None


def _record_files(records_dir: Path) -> List[Path]:
    files: List[Path] = []
    with os.scandir(records_dir) as partitions:
        for partition in partitions:
            if not partition.is_dir(follow_symlinks=False):
                continue
            try:
                with os.scandir(os.path.join(partition.path, "Resource")) as entries:
                    for entry in entries:
                        if entry.is_file(follow_symlinks=False) and not entry.name.endswith("-blob"):
                            files.append(Path(entry.path))
            except FileNotFoundError:
                continue
    return files


def scan_cache_version(version_dir: Path) -> Tuple[List[BlobSource], int]:
    """Return the HTML-capable bodies of one ``Version N`` directory and how many parts were unreadable.

    ``Blobs`` files become sources; ``Records`` add the request URL to the blob
    they reference, and bodies stored inline in a record become sources of their own.
    """
    version = version_dir.name
    denied = 0
    blobs: Dict[str, BlobSource] = {}
    blob_by_inode: Dict[int, str] = {}
    try:
        with os.scandir(version_dir / "Blobs") as entries:
            for entry in entries:
                if entry.is_file(follow_symlinks=False):
                    blobs[entry.name] = BlobSource(Path(entry.path), version)
                    blob_by_inode[entry.inode()] = entry.name
    except FileNotFoundError:
        pass
    except OSError:
        denied += 1

    blob_by_hash: Dict[bytes, str] = {}
    for name in blobs:
        if len(name) == 40:
            try:
                blob_by_hash[bytes.fromhex(name)] = name
            except ValueError:
                pass

    try:
        record_paths = _record_files(version_dir / "Records")
    except FileNotFoundError:
        record_paths = []
    except OSError:
        denied += 1
        record_paths = []

    inline: List[BlobSource] = []
    for record_path in record_paths:
        data = _read_record(record_path)
        if not data:
            continue
        url, url_end = cache_records.record_url(data)
        if not url:
            continue
        name: Optional[str] = None
        try:
            name = blob_by_inode.get(os.stat(str(record_path) + "-blob").st_ino)
        except OSError:
            pass
        if name is None and blob_by_hash:
            linked = cache_records.linked_blob_hash(data, url_end, blob_by_hash)
            name = blob_by_hash.get(linked) if linked else None
        if name is not None:
            blobs[name] = replace(blobs[name], url=url)
            continue
        offset = cache_records.inline_body_offset(data, url_end)
        if offset is not None:
            inline.append(BlobSource(record_path, version, url=url, offset=offset))
    return list(blobs.values()) + inline, denied


class RecoveryEngine:
    def __init__(
        self,
        history_path: Optional[Path] = None,
        cache_roots: Optional[Sequence[Path]] = None,
    ):
        self.history = HistoryReader(history_path or default_history_path())
        self.cache_roots = list(cache_roots or default_cache_roots())
        self.warnings: List[str] = []
        self._history_accessible = True

    def blob_sources(self) -> List[BlobSource]:
        sources: List[BlobSource] = []
        denied = 0
        readable_root = False
        for root in self.cache_roots:
            try:
                if not root.exists():
                    continue
                with os.scandir(root):
                    pass
                readable_root = True
                version_dirs = sorted(path for path in root.glob("Version *") if path.is_dir())
            except (PermissionError, OSError):
                denied += 1
                continue
            for version_dir in version_dirs:
                version_sources, version_denied = scan_cache_version(version_dir)
                sources.extend(version_sources)
                denied += version_denied
        if denied and sources:
            self.warnings.append("One Safari cache location could not be read")
        if not sources and denied and not readable_root:
            raise CacheUnavailable(
                "Safari cache could not be read; grant Full Disk Access to this terminal app"
            )
        if not sources:
            raise CacheUnavailable("no Safari WebKit cache blobs were found")
        return sources

    def _history_entries(
        self,
        query: Optional[str],
        start: Optional[datetime],
        end: Optional[datetime],
        required: bool,
    ) -> List[HistoryEntry]:
        try:
            return self.history.entries(query=query, start=start, end=end)
        except HistoryUnavailable as error:
            self._history_accessible = False
            if required:
                raise
            self.warnings.append("History unavailable; using cache-only matching: {}".format(error))
            return []

    def find(
        self,
        query: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> List[Candidate]:
        entries = self._history_entries(query, start, end, required=False)
        time_filter_requested = start is not None or end is not None
        if time_filter_requested and not self._history_accessible:
            self.warnings.append("The requested time filter could not be applied without Safari History")
        return self._scan(
            query,
            entries,
            recent_mode=False,
            require_history_match=time_filter_requested and self._history_accessible,
        )

    def recent(self, start: datetime, end: datetime) -> List[Candidate]:
        candidates, _ = self.recent_with_sources(start, end)
        return candidates

    def recent_with_sources(
        self,
        start: datetime,
        end: datetime,
    ) -> Tuple[List[Candidate], List[BlobSource]]:
        entries = self._history_entries(None, start, end, required=True)
        sources = self.blob_sources()
        return (
            self._scan(
                None,
                entries,
                recent_mode=True,
                require_history_match=True,
                sources=sources,
            ),
            sources,
        )

    def _scan(
        self,
        query: Optional[str],
        entries: Sequence[HistoryEntry],
        recent_mode: bool,
        require_history_match: bool,
        sources: Optional[Sequence[BlobSource]] = None,
    ) -> List[Candidate]:
        candidates: Dict[str, Candidate] = {}
        query_normalized = normalize(query or "")
        query_domain = domain_from_url(query or "")
        is_url_query = bool(query_domain)
        query_url = normalize_url_identity(query or "") if is_url_query else ""
        query_tokens = [] if is_url_query else meaningful_tokens(query or "")
        # Per-entry work is hoisted out of the blob loop: it runs once instead of once per blob.
        prepared_entries = [
            (
                entry,
                normalize_url_identity(entry.url),
                normalize(entry.title),
                set(meaningful_tokens(entry.title)),
            )
            for entry in entries
        ]

        for source in sources if sources is not None else self.blob_sources():
            data = read_stable(source.path, source.offset)
            if data is None:
                continue
            text = decode_html(data)
            if text is None:
                continue
            title = extract_title(text)
            lowered = text.casefold() if query_normalized and not is_url_query else ""
            canonical_url = canonical_url_from_html(text)
            canonical_identity = normalize_url_identity(canonical_url)
            record_identity = normalize_url_identity(source.url)
            normalized_title = normalize(title)
            title_tokens = set(meaningful_tokens(title))
            complete = is_complete_html(text)
            reasons: List[str] = []
            matched_entries: List[HistoryEntry] = []

            exact_url = False
            exact_title = False
            title_overlap = False
            if query_url and query_url == record_identity:
                exact_url = True
                reasons.append("cache record URL matches query")
            elif query_url and query_url == canonical_identity:
                exact_url = True
                reasons.append("canonical URL matches query")
            for entry, entry_url, history_title, history_tokens in prepared_entries:
                if record_identity and entry_url == record_identity:
                    exact_url = True
                    matched_entries.append(entry)
                    reasons.append("cache record URL matches Safari history")
                elif canonical_identity and entry_url == canonical_identity:
                    exact_url = True
                    matched_entries.append(entry)
                    reasons.append("canonical URL matches Safari history")
                if title and entry.title and normalized_title == history_title:
                    exact_title = True
                    matched_entries.append(entry)
                    reasons.append("HTML title matches Safari history")
                elif title and entry.title:
                    overlap = title_tokens & history_tokens
                    overlap_ratio = len(overlap) / max(len(title_tokens), len(history_tokens), 1)
                    if (
                        (len(overlap) >= 2 and overlap_ratio >= 0.75)
                        or (len(normalized_title) >= 6 and normalized_title in history_title)
                        or (len(history_title) >= 6 and history_title in normalized_title)
                    ):
                        title_overlap = True
                        matched_entries.append(entry)
                        reasons.append("HTML title overlaps Safari history")

            literal_in_title = bool(
                query_normalized and not is_url_query and query_normalized in normalized_title
            )
            literal_in_body = bool(
                query_normalized and not is_url_query and query_normalized in lowered
            )
            token_hits = sum(1 for token in query_tokens if token in lowered)
            if literal_in_title:
                reasons.append("query appears in HTML title")
            elif literal_in_body:
                reasons.append("query appears in HTML")
            if token_hits >= 2:
                reasons.append("multiple query terms appear in HTML")

            if recent_mode or require_history_match:
                relevant = exact_url or exact_title or title_overlap
            else:
                relevant = exact_url or exact_title or title_overlap or literal_in_body or token_hits > 0
            if not relevant:
                continue

            if complete and (exact_url or exact_title):
                confidence = "high"
            elif complete and (title_overlap or literal_in_title or token_hits >= 2):
                confidence = "medium"
            else:
                confidence = "low"
                if not complete:
                    reasons.append("HTML may be incomplete")

            matched_entry = max(matched_entries, key=lambda item: item.visit_time) if matched_entries else None
            domain = (
                query_domain
                or domain_from_url(source.url)
                or (domain_from_url(matched_entry.url) if matched_entry else "")
                or domain_from_url(canonical_url)
            )
            digest = hashlib.sha256(data).hexdigest()
            candidate = Candidate(
                sha256=digest,
                title=title,
                domain=domain,
                visit_time=matched_entry.visit_time if matched_entry else None,
                byte_length=len(data),
                cache_version=source.cache_version,
                confidence=confidence,
                match_reasons=list(dict.fromkeys(reasons)),
                source=source,
            )
            existing = candidates.get(digest)
            if existing is None or _confidence_rank(candidate.confidence) > _confidence_rank(existing.confidence):
                candidates[digest] = candidate

        return sorted(
            candidates.values(),
            key=lambda item: (
                _confidence_rank(item.confidence),
                item.visit_time.timestamp() if item.visit_time else 0,
                item.byte_length,
            ),
            reverse=True,
        )

    def export(self, candidate_prefix: str, output: Path, force: bool = False) -> Tuple[Path, Path]:
        prefix = candidate_prefix.casefold()
        if len(prefix) < 12 or not all(character in "0123456789abcdef" for character in prefix):
            raise CandidateUnavailable("candidate ID must be a hexadecimal prefix of at least 12 characters")

        matches: Dict[str, Tuple[BlobSource, bytes, str]] = {}
        for source in self.blob_sources():
            data = read_stable(source.path, source.offset)
            if data is None:
                continue
            digest = hashlib.sha256(data).hexdigest()
            if digest.startswith(prefix):
                text = decode_html(data)
                if text is not None:
                    matches.setdefault(digest, (source, data, text))
        if not matches:
            raise CandidateUnavailable("candidate is no longer present in Safari cache")
        if len(matches) > 1:
            raise CandidateUnavailable("candidate ID prefix is ambiguous; provide more characters")
        digest, (source, data, text) = next(iter(matches.items()))

        report_path = Path(str(output) + ".recovery.json")
        if not force and (output.exists() or report_path.exists()):
            raise ExportFailure("output or recovery report already exists; use --force to replace it")
        output.parent.mkdir(parents=True, exist_ok=True)

        temporary = output.with_name(".{}.safari-rescue.tmp".format(output.name))
        report_temporary = report_path.with_name(".{}.safari-rescue.tmp".format(report_path.name))
        try:
            with temporary.open("wb") as handle:
                handle.write(data)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
                raise ExportFailure("exported bytes failed SHA-256 verification")

            title = extract_title(text)
            report = {
                "candidate_id": digest,
                "sha256": digest,
                "title": title,
                "domain": domain_from_url(source.url)
                or self._domain_for_title(title)
                or domain_from_html(text),
                "cache_version": source.cache_version,
                "byte_length": len(data),
                "recovered_at": datetime.now().astimezone().isoformat(),
            }
            with report_temporary.open("w", encoding="utf-8") as handle:
                json.dump(report, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temporary, output)
            os.replace(report_temporary, report_path)
        except (OSError, ExportFailure) as error:
            for path in (temporary, report_temporary):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            if isinstance(error, ExportFailure):
                raise
            raise ExportFailure(str(error)) from error
        return output, report_path

    def _domain_for_title(self, title: str) -> str:
        if not title:
            return ""
        try:
            entries = self.history.entries(query=title)
        except HistoryUnavailable:
            return ""
        for entry in entries:
            if normalize(entry.title) == normalize(title):
                return domain_from_url(entry.url)
        return ""


def _confidence_rank(value: str) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(value, 0)
