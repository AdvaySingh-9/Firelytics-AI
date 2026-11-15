"""Temporary investigation workspaces. Raw downloads and extracted evidence expire with the session."""
from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
import tarfile
import time
import urllib.error
import urllib.request
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any

from .psi_discovery import discover_investigation_files, is_allowed_psi_file_url, _category

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_DIR = PROJECT_ROOT / "database"
if str(DB_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(DB_DIR))
from psi_db import config as psi_config
from .search_service import get_catalogue_record
from .data import INVESTIGATIONS

_SESSION_DIR_ENV = os.getenv("FIRELYTICS_SESSION_DIR", "").strip()
SESSION_ROOT = Path(_SESSION_DIR_ENV) if _SESSION_DIR_ENV else Path(__file__).resolve().parents[1] / "temporary" / "sessions"
SESSION_TTL_SECONDS = int(os.getenv("FIRELYTICS_SESSION_TTL_SECONDS", "7200"))
MAX_FILE_MB = int(os.getenv("FIRELYTICS_MAX_FILE_MB", "512"))
ON_DEMAND_MAX_FILE_MB = int(os.getenv("FIRELYTICS_ON_DEMAND_MAX_FILE_MB", "512"))
MAX_SESSION_MB = int(os.getenv("FIRELYTICS_MAX_SESSION_MB", "2048"))
MAX_TEXT_CHARS = int(os.getenv("FIRELYTICS_MAX_EXTRACTED_CHARS", "50000"))
SESSIONS: dict[str, dict[str, Any]] = {}


def _size_bytes(value: Any) -> int:
    """Convert PSI size values (e.g. 0B, 12 KB, 1.5 MiB) to bytes safely.

    NASA's inventory sometimes returns display-formatted sizes rather than
    integers. Unknown/empty values are treated as unknown (0), never as a
    reason to abort the entire experiment ingestion.
    """
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return max(0, int(value))
    raw = str(value).strip().replace(",", "")
    if not raw:
        return 0
    match = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*([A-Za-z]{0,4})", raw)
    if not match:
        return 0
    try:
        amount = float(match.group(1))
    except (TypeError, ValueError, OverflowError):
        return 0
    unit = match.group(2).casefold()
    multipliers = {
        "": 1, "b": 1, "byte": 1, "bytes": 1,
        "k": 1000, "kb": 1000, "kib": 1024,
        "m": 1000**2, "mb": 1000**2, "mib": 1024**2,
        "g": 1000**3, "gb": 1000**3, "gib": 1024**3,
        "t": 1000**4, "tb": 1000**4, "tib": 1024**4,
    }
    multiplier = multipliers.get(unit)
    if multiplier is None or amount < 0:
        return 0
    return int(amount * multiplier)


def _json_write(path: Path, data: Any):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _asset_uid(asset: dict[str, Any]) -> str:
    import hashlib
    identity = str(asset.get("key") or asset.get("url") or asset.get("filename") or "unknown")
    return hashlib.sha1(identity.encode("utf-8", "replace")).hexdigest()[:16]


def _persist_session(session: dict[str, Any]) -> None:
    """Persist session-only table equivalents as JSON/JSONL; never writes SQLite."""
    workspace = Path(session["workspace"])
    assets = session.get("assets", [])
    evidence = session.get("evidence", [])
    _json_write(workspace / "session.json", {k: v for k, v in session.items() if k != "evidence"})
    _json_write(workspace / "assets.json", assets)
    _json_write(workspace / "capabilities.json", session.get("capabilities", {}))
    datasets = []
    for item in evidence:
        if item.get("columns") or item.get("sheets") or item.get("numeric_summary"):
            datasets.append({k: item.get(k) for k in ("filename", "source", "category", "format", "columns", "column_schema", "sheets", "row_count_scanned", "column_count", "scan_truncated", "numeric_summary", "status") if item.get(k) is not None})
    _json_write(workspace / "datasets.json", datasets)
    # JSONL keeps document chunks streamable and avoids a single huge JSON document.
    tmp = workspace / "document_chunks.jsonl.tmp"
    with tmp.open("w", encoding="utf-8") as stream:
        for item in evidence:
            stream.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
    tmp.replace(workspace / "document_chunks.jsonl")
    _json_write(workspace / "relationships.json", session.get("relationships", {"status": "not_indexed", "items": []}))
    _json_write(workspace / "processing.json", {"downloaded_bytes": session.get("downloaded_bytes", 0), "updated_at": time.time(), "assets": [{"asset_id": a.get("asset_id"), "download_status": a.get("download_status"), "processing_status": a.get("processing_status"), "attempts": a.get("attempts", 0)} for a in assets]})


def _local_record(study_id: str) -> dict | None:
    try:
        record = get_catalogue_record(study_id, {})
        if record:
            return record
    except Exception:
        pass
    fallback = next((x for x in INVESTIGATIONS if x["study_id"].casefold() == study_id.casefold()), None)
    if fallback:
        return fallback
    if re.fullmatch(r"PSI-\d+", study_id.upper()):
        return {
            "study_id": study_id.upper(), "title": f"NASA PSI investigation {study_id.upper()}",
            "objective": "Not present in the supplied local catalogue; retrieve details from the official PSI record.",
            "summary": "Local metadata unavailable.", "assets": [],
            "source_url": f"https://psi.nasa.gov/physci/repo/data/investigations/{study_id.upper()}",
            "note": "No local investigation metadata was available when this session was created."
        }
    return None


def _local_report(study_id: str) -> str:
    study_id = study_id.strip().upper()
    if not psi_config.DB_PATH.exists():
        return ""
    try:
        con = sqlite3.connect(f"file:{psi_config.DB_PATH}?mode=ro", uri=True)
        try:
            row = con.execute("SELECT text FROM reports WHERE study_id = ?", (study_id,)).fetchone()
            return row[0] if row and row[0] else ""
        finally:
            con.close()
    except Exception:
        return ""


def _safe_extract_zip(path: Path, destination: Path) -> list[Path]:
    extracted = []
    total_uncompressed = 0
    max_uncompressed = min(MAX_SESSION_MB * 1024 * 1024, 150 * 1024 * 1024)
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            # Avoid path traversal and only unpack files under the workspace.
            target = (destination / member.filename).resolve()
            if destination.resolve() not in target.parents and target != destination.resolve():
                continue
            if member.is_dir() or member.file_size > MAX_FILE_MB * 1024 * 1024:
                continue
            if total_uncompressed + member.file_size > max_uncompressed or len(extracted) >= 100:
                break
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            total_uncompressed += member.file_size
            extracted.append(target)
    return extracted


def _safe_extract_tar(path: Path, destination: Path) -> list[Path]:
    """Safely unpack a bounded subset of regular TAR members into the session."""
    extracted: list[Path] = []
    total_uncompressed = 0
    max_uncompressed = min(MAX_SESSION_MB * 1024 * 1024, 150 * 1024 * 1024)
    with tarfile.open(path, mode="r:*") as archive:
        for member in archive:
            if not member.isfile():
                continue
            target = (destination / member.name).resolve()
            if destination.resolve() not in target.parents:
                continue
            if member.size < 0 or member.size > MAX_FILE_MB * 1024 * 1024:
                continue
            if total_uncompressed + member.size > max_uncompressed or len(extracted) >= 100:
                break
            source = archive.extractfile(member)
            if source is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            total_uncompressed += member.size
            extracted.append(target)
    return extracted


def _safe_extract_archive(path: Path, destination: Path) -> list[Path]:
    name = path.name.casefold()
    if path.suffix.casefold() == ".zip":
        return _safe_extract_zip(path, destination)
    if name.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")):
        return _safe_extract_tar(path, destination)
    if name.endswith(".gz"):
        # A standalone gzip-compressed CSV/text file is common in scientific repositories.
        output_name = path.name[:-3] or "decompressed_asset"
        target = (destination / output_name).resolve()
        if destination.resolve() not in target.parents:
            return []
        target.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "rb") as source, target.open("wb") as output:
            copied = 0
            limit = min(MAX_FILE_MB * 1024 * 1024, 150 * 1024 * 1024)
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > limit:
                    target.unlink(missing_ok=True)
                    return []
                output.write(chunk)
        return [target]
    return []


def _column_schema(headers: list[Any], sample_rows: list[Any]) -> list[dict[str, Any]]:
    """Describe observed column structure without inventing units/descriptions."""
    schema = []
    for index, raw_header in enumerate(headers[:200]):
        name = str(raw_header if raw_header is not None else f"column_{index + 1}").strip()
        values = []
        for row in sample_rows[:100]:
            if isinstance(row, dict):
                value = row.get(name)
            else:
                value = row[index] if index < len(row) else None
            if value not in (None, ""):
                values.append(value)
        observed_types = set()
        for value in values:
            if isinstance(value, bool):
                observed_types.add("boolean")
            elif isinstance(value, (int, float)):
                observed_types.add("number")
            else:
                try:
                    float(str(value).replace(",", "").strip())
                    observed_types.add("number")
                except (TypeError, ValueError):
                    observed_types.add("text")
        type_name = next(iter(observed_types)) if len(observed_types) == 1 else ("mixed" if observed_types else "unknown")
        unit_match = re.search(r"(?:\(|\[)([^\)\]]{1,24})(?:\)|\])\s*$", name)
        schema.append({"name": name, "observed_type": type_name, "unit": unit_match.group(1).strip() if unit_match else None, "description": None})
    return schema


def _extract_file(path: Path) -> dict[str, Any]:
    ext = path.suffix.lower()
    result: dict[str, Any] = {"filename": path.name, "format": ext.lstrip("."), "status": "unsupported", "content": ""}
    try:
        if ext in {".txt", ".md", ".rtf", ".xml", ".html", ".json", ".log", ".dat", ".out", ".prn"}:
            with path.open("r", encoding="utf-8", errors="replace") as stream:
                raw = stream.read(MAX_TEXT_CHARS * 4)
            if ext in {".dat", ".out", ".prn"}:
                printable = sum(ch.isprintable() or ch in "\r\n\t" for ch in raw) / max(1, len(raw))
                if "\x00" in raw or printable < 0.85:
                    result.update(status="metadata_only", content=f"{ext} file appears binary or non-text; a format-specific parser is required.")
                    return result
            if ext == ".json":
                try:
                    obj = json.loads(raw)
                    raw = json.dumps(obj, ensure_ascii=False, indent=2)[:MAX_TEXT_CHARS]
                except Exception:
                    pass
            result.update(status="extracted", content=raw[:MAX_TEXT_CHARS])
        elif ext == ".gz":
            import gzip
            import io
            with gzip.open(path, "rb") as stream:
                sample = stream.read(min(MAX_TEXT_CHARS * 4, 16 * 1024 * 1024))
            decoded = sample.decode("utf-8", errors="replace")
            printable = sum(ch.isprintable() or ch in "\\r\\n\\t" for ch in decoded) / max(1, len(decoded))
            if "\\x00" in decoded or printable < 0.85:
                result.update(status="metadata_only", content="Gzip payload is binary/compressed scientific data; a format-specific parser is required.")
            else:
                result.update(status="extracted", content=decoded[:MAX_TEXT_CHARS], decompressed_bytes=len(sample))
        elif ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            pages = []
            remaining_chars = MAX_TEXT_CHARS
            for i, page in enumerate(reader.pages[:100]):
                if remaining_chars <= 0:
                    break
                text = page.extract_text() or ""
                if text.strip():
                    page_text = text[:min(12000, remaining_chars)]
                    pages.append({"page": i + 1, "text": page_text})
                    remaining_chars -= len(page_text)
            result.update(status="extracted" if pages else "no_text", pages=pages, content="\n\n".join(f"[Page {p['page']}]\n{p['text']}" for p in pages)[:MAX_TEXT_CHARS])
        elif ext in {".csv", ".tsv"}:
            delimiter = "\t" if ext == ".tsv" else ","
            with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
                reader = csv.DictReader(f, delimiter=delimiter)
                columns = (reader.fieldnames or [])[:200]
                rows = []
                stats = {column: {"count": 0, "sum": 0.0, "min": None, "max": None} for column in columns}
                row_count = 0
                truncated_scan = False
                for row in reader:
                    row_count += 1
                    if row_count <= 100:
                        rows.append(row)
                    if row_count > 1_000_000:
                        truncated_scan = True
                        break
                    for column in columns:
                        value = str(row.get(column, "") or "").strip()
                        if not value:
                            continue
                        try:
                            number = float(value.replace(",", ""))
                        except (TypeError, ValueError):
                            continue
                        stat = stats[column]
                        stat["count"] += 1
                        stat["sum"] += number
                        stat["min"] = number if stat["min"] is None else min(stat["min"], number)
                        stat["max"] = number if stat["max"] is None else max(stat["max"], number)
            numeric_summary = {k: {"count": v["count"], "min": v["min"], "max": v["max"], "mean": (v["sum"] / v["count"] if v["count"] else None)} for k, v in stats.items() if v["count"]}
            sample = json.dumps(rows[:20], ensure_ascii=False, default=str)
            summary_text = json.dumps(numeric_summary, ensure_ascii=False, default=str)
            column_schema = _column_schema(columns, rows)
            result.update(status="extracted", columns=columns, column_schema=column_schema, row_count_scanned=row_count, column_count=len(columns), sample_rows=rows, scan_truncated=truncated_scan, numeric_summary=numeric_summary, content=f"Columns: {columns}\nColumn schema: {json.dumps(column_schema, ensure_ascii=False)}\nRows scanned: {row_count}\nNumeric summaries (units are taken only from explicit headers; no units are inferred): {summary_text}\nSample rows (up to 100): {sample}")
        elif ext in {".xlsx", ".xlsm"}:
            from openpyxl import load_workbook
            wb = load_workbook(path, read_only=True, data_only=True)
            sheets = []
            for ws in wb.worksheets[:20]:
                values = list(ws.iter_rows(values_only=True, max_row=101, max_col=80))
                header = list(values[0]) if values else []
                sample_rows = [list(r) for r in values[1:101]]
                sheets.append({"sheet": ws.title, "row_count": ws.max_row, "column_count": ws.max_column, "header": header, "column_schema": _column_schema(header, sample_rows), "sample_rows": sample_rows[:20]})
            wb.close()
            result.update(status="extracted", sheets=sheets, columns=[str(x) for sheet in sheets for x in sheet.get("header", [])], row_count_scanned=sum(x.get("row_count", 0) for x in sheets), content=json.dumps(sheets, ensure_ascii=False, default=str)[:MAX_TEXT_CHARS])
        elif ext == ".xls":
            import xlrd
            book = xlrd.open_workbook(str(path), on_demand=True)
            sheets = []
            for sheet in book.sheets()[:20]:
                rows = []
                for row_index in range(min(sheet.nrows, 101)):
                    rows.append([sheet.cell_value(row_index, col) for col in range(min(sheet.ncols, 80))])
                header = rows[0] if rows else []
                sample_rows = rows[1:101]
                sheets.append({"sheet": sheet.name, "row_count": sheet.nrows, "column_count": sheet.ncols, "header": header, "column_schema": _column_schema(header, sample_rows), "sample_rows": sample_rows[:20]})
            book.release_resources()
            result.update(status="extracted", sheets=sheets, columns=[str(x) for sheet in sheets for x in sheet.get("header", [])], row_count_scanned=sum(x.get("row_count", 0) for x in sheets), content=json.dumps(sheets, ensure_ascii=False, default=str)[:MAX_TEXT_CHARS])
        elif ext == ".docx":
            from docx import Document
            doc = Document(str(path))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            tables = [[[cell.text for cell in row.cells] for row in table.rows[:100]] for table in doc.tables[:20]]
            content = "\n".join(paragraphs) + "\nTABLES:\n" + json.dumps(tables, ensure_ascii=False)
            result.update(status="extracted", content=content[:MAX_TEXT_CHARS])
        elif ext == ".pptx":
            from pptx import Presentation
            prs = Presentation(str(path))
            slides = []
            for i, slide in enumerate(list(prs.slides)[:200]):
                texts = [shape.text for shape in slide.shapes if getattr(shape, "has_text_frame", False) and shape.text.strip()]
                if texts:
                    slides.append({"slide": i + 1, "text": texts})
            result.update(status="extracted", slides=slides, content=json.dumps(slides, ensure_ascii=False)[:MAX_TEXT_CHARS])
        else:
            result.update(status="metadata_only", content=f"File type {ext or '(unknown)'} is not text-extracted by this processor; a format-specific parser may be required.")
    except Exception as exc:
        result.update(status="extraction_failed", error=f"{type(exc).__name__}: {exc}"[:300])
    return result


def _psi_download_candidates(asset: dict) -> list[str]:
    """Build the same per-file Geode download request used by the PSI web UI.

    PSI v2 manifest entries commonly expose an opaque file id but no direct
    URL. The UI's study download endpoint requires that id plus file and study
    versions; a filename/key-only request can return a page or fail to resolve.
    """
    candidates: list[str] = []
    direct_fields = (
        "url", "download_url", "downloadUrl", "remote_url", "remoteUrl",
        "download_uri", "downloadUri", "fileUrl", "file_url",
        "download_link", "downloadLink",
    )
    for field in direct_fields:
        value = asset.get(field)
        if not value:
            continue
        direct = str(value).strip()
        if direct.startswith("//"):
            direct = "https:" + direct
        elif not urllib.parse.urlparse(direct).scheme:
            direct = urllib.parse.urljoin("https://psi.nasa.gov/", direct)
        if is_allowed_psi_file_url(direct):
            candidates.append(direct)

    study_id = str(asset.get("study_id") or "").strip().upper()
    file_id = str(asset.get("id") or asset.get("fileId") or asset.get("file_id")
                  or asset.get("fileID") or asset.get("fileid") or "").strip()
    if study_id and asset.get("filename"):
        # NASA's published Geode/OSDR file route resolves data-manager objects
        # by their repository filename (remote_url uses this exact form). PSI v2
        # opaque Mongo IDs are inventory IDs, not necessarily Geode's `file` arg.
        base = f"https://psi.nasa.gov/geode-py/ws/studies/{urllib.parse.quote(study_id, safe='')}/download"
        candidates.append(base + "?" + urllib.parse.urlencode({
            "source": "datamanager", "file": str(asset.get("filename"))
        }))
        key = str(asset.get("key") or "").strip()
        if key and key != str(asset.get("filename")):
            candidates.append(base + "?" + urllib.parse.urlencode({
                "source": "datamanager", "file": key
            }))
    if study_id and file_id:
        # Keep the PSI v2 opaque-ID route as a secondary fallback; some
        # investigation versions accept it, but it is not the standard route.
        base = f"https://psi.nasa.gov/geode-py/ws/studies/{urllib.parse.quote(study_id, safe='')}/download"
        query = {
            "file": file_id,
            "version": str(asset.get("version") or asset.get("fileVersion") or asset.get("file_version") or 2),
            "studyVersion": str(asset.get("study_version") or asset.get("studyVersion") or asset.get("studyversion") or 2),
            "redirect": "false",
        }
        candidates.append(base + "?" + urllib.parse.urlencode(query))
        candidates.append(base + "?" + urllib.parse.urlencode({**query, "redirect": "true"}))

    # Keep support for deployments that have verified a different endpoint.
    template = os.getenv("PSI_DOWNLOAD_URL_TEMPLATE", "").strip()
    if template:
        try:
            rendered = template.format(
                id=urllib.parse.quote(str(asset.get("id") or ""), safe=""),
                key=urllib.parse.quote(str(asset.get("key") or ""), safe="/"),
                study_id=urllib.parse.quote(study_id, safe=""),
                filename=urllib.parse.quote(str(asset.get("filename") or ""), safe=""),
            )
            if rendered.startswith("/"):
                rendered = urllib.parse.urljoin("https://psi.nasa.gov", rendered)
            if is_allowed_psi_file_url(rendered):
                candidates.append(rendered)
        except (KeyError, ValueError):
            pass
    return list(dict.fromkeys(candidates))


def _find_download_url(payload: Any) -> str | None:
    """Find a download URL in common Geode JSON response envelopes."""
    url_keys = {"url", "downloadurl", "downloadlink", "downloaduri", "redirecturl", "href", "uri", "location", "fileurl", "presignedurl", "signedurl"}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).casefold().replace("_", "") in url_keys and isinstance(value, str) and value.strip():
                return value.strip()
        for value in payload.values():
            found = _find_download_url(value)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_download_url(value)
            if found:
                return found
    return None


def _download_asset(asset: dict, folder: Path, remaining_bytes: int, max_file_bytes: int | None = None) -> tuple[dict, int]:
    if asset.get("restricted") or asset.get("restrictedAccess"):
        return {**asset, "download_status": "restricted"}, 0
    candidates = _psi_download_candidates(asset)
    if not candidates:
        direct_fields = ("url", "download_url", "downloadUrl", "remote_url", "remoteUrl", "download_uri", "downloadUri", "fileUrl", "file_url", "download_link", "downloadLink")
        has_untrusted_direct = any(asset.get(field) for field in direct_fields)
        status = "blocked_external_url" if has_untrusted_direct else "no_download_url"
        return {**asset, "download_status": status}, 0
    max_file = min(max_file_bytes or (MAX_FILE_MB * 1024 * 1024), remaining_bytes)
    declared_size = _size_bytes(asset.get("bytes_size") or asset.get("file_size") or asset.get("fileSize") or asset.get("sizeBytes") or asset.get("size") or 0)
    if declared_size and declared_size > max_file:
        return {**asset, "download_status": "deferred_size_limit", "remote_size": declared_size}, 0
    if max_file <= 0:
        return {**asset, "download_status": "session_budget_reached"}, 0

    errors: list[str] = []
    http_codes: list[int] = []
    refreshed_signed_url = False
    for url in candidates:
        target: Path | None = None
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 FirelyticsAI/1.0",
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": f"https://psi.nasa.gov/physci/repo/data/investigations/{str(asset.get('study_id') or '').upper()}",
                },
            )
            with urllib.request.urlopen(request, timeout=12) as response:
                final_url = response.geturl()
                if not is_allowed_psi_file_url(final_url):
                    errors.append(f"{url}: blocked redirect to an untrusted host")
                    continue

                length = _size_bytes(response.headers.get("Content-Length")) or declared_size
                if length and length > max_file:
                    return {
                        **asset, "download_status": "deferred_size_limit",
                        "remote_size": length, "download_url_used": url,
                    }, 0

                filename = Path(asset.get("filename") or "asset.bin").name
                import hashlib
                identity = str(asset.get("asset_id") or url)
                suffix = hashlib.sha1(identity.encode("utf-8", "replace")).hexdigest()[:10]
                # Unique destinations prevent parallel transfers with the same
                # basename from overwriting one another in the session folder.
                target = folder / f"{Path(filename).stem}_{suffix}{Path(filename).suffix}"

                content_type = (response.headers.get("Content-Type") or "").casefold()
                ext = Path(filename).suffix.casefold()
                # With redirect=false, Geode may return a JSON envelope containing
                # a signed object-store URL. Do not trust Content-Type alone: some
                # PSI deployments label this response application/octet-stream.
                first = response.read(512)
                is_geode_download = "/geode-py/ws/studies/" in url
                looks_json = first.lstrip().startswith((b"{", b"["))
                if is_geode_download and ext != ".json" and (looks_json or first.lstrip().lower().startswith((b"https://", b"http://"))):
                    envelope = first + response.read(max(0, 2 * 1024 * 1024 - len(first)))
                    resolved = None
                    if looks_json:
                        try:
                            payload = json.loads(envelope.decode("utf-8", errors="replace"))
                        except (ValueError, UnicodeDecodeError):
                            payload = None
                        resolved = _find_download_url(payload)
                    else:
                        # Some PSI deployments return a signed S3 URL as plain
                        # text instead of wrapping it in JSON.
                        resolved = envelope.decode("utf-8", errors="replace").strip().strip('"\'')
                    if resolved:
                        resolved = urllib.parse.urljoin(url, resolved)
                        if is_allowed_psi_file_url(resolved):
                            if resolved not in candidates:
                                candidates.append(resolved)
                            continue
                        errors.append(f"{url}: Geode returned a download URL on a host not allow-listed: {urllib.parse.urlparse(resolved).hostname}")
                    else:
                        errors.append(f"{url}: Geode returned an unrecognized download URL response")
                    continue
                looks_like_html = (
                    b"<!doctype html" in first.lower()
                    or b"<html" in first.lower()
                    or b"<error>" in first.lower()
                )
                if ext not in {".html", ".htm"} and (
                    "text/html" in content_type or looks_like_html
                ):
                    errors.append(f"{url}: server returned an HTML/error page instead of {filename}")
                    continue

                total = len(first)
                with target.open("wb") as output:
                    output.write(first)
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_file:
                            output.close()
                            target.unlink(missing_ok=True)
                            return {
                                **asset, "download_status": "deferred_size_limit",
                                "remote_size": total, "download_url_used": url,
                            }, 0
                        output.write(chunk)
                if total == 0:
                    target.unlink(missing_ok=True)
                    raise OSError("NASA returned an empty file")
                return {
                    **asset,
                    "url": url,
                    "download_url_used": url,
                    "download_status": "downloaded",
                    "local_path": str(target),
                    "downloaded_bytes": total,
                }, total
        except urllib.error.HTTPError as exc:
            http_codes.append(int(exc.code))
            errors.append(f"{url}: HTTP {exc.code} {exc.reason}")
            if target:
                target.unlink(missing_ok=True)
            # PSI S3 links are signed and expire. If one has gone stale, refresh
            # the investigation manifest once and retry the matching asset's
            # newly issued URL instead of making the user restart the session.
            host = (urllib.parse.urlparse(url).hostname or "").lower()
            if (int(exc.code) in {401, 403}
                    and host in {"psi-repo-prod.s3.amazonaws.com", "psi-repo-prod.s3.us-west-2.amazonaws.com"}
                    and not refreshed_signed_url):
                refreshed_signed_url = True
                try:
                    refreshed = discover_investigation_files(str(asset.get("study_id") or ""), timeout=8)
                    for fresh_asset in refreshed.get("assets", []):
                        same_id = bool(asset.get("id") and str(fresh_asset.get("id") or "") == str(asset.get("id")))
                        same_key = bool(asset.get("key") and str(fresh_asset.get("key") or "") == str(asset.get("key")))
                        same_name = str(fresh_asset.get("filename") or "").casefold() == str(asset.get("filename") or "").casefold()
                        fresh_url = fresh_asset.get("url") or fresh_asset.get("download_url")
                        if (same_id or same_key or (same_name and not asset.get("id") and not asset.get("key"))) and fresh_url and is_allowed_psi_file_url(str(fresh_url)) and fresh_url not in candidates:
                            candidates.append(str(fresh_url))
                            errors.append("PSI issued a refreshed signed URL; retrying the file.")
                            break
                except Exception as refresh_exc:
                    errors.append(f"PSI signed-URL refresh failed: {type(refresh_exc).__name__}: {refresh_exc}")
        except Exception as exc:
            if target:
                target.unlink(missing_ok=True)
            errors.append(f"{url}: {type(exc).__name__}: {exc}")

    # A missing object is different from a transient network failure. Mark it
    # terminal for this session rather than retrying the same stale key again.
    if http_codes and len(http_codes) == len(candidates) and all(code == 404 for code in http_codes):
        status = "not_found"
    elif http_codes and all(code in {401, 403} for code in http_codes):
        status = "access_denied"
    else:
        status = "download_failed"
    return {
        **asset,
        "download_status": status,
        "download_error": " | ".join(errors)[:700],
    }, 0


def cleanup_expired_sessions():
    now = time.time()
    for sid, data in list(SESSIONS.items()):
        if now - data.get("created_at", now) > SESSION_TTL_SECONDS:
            shutil.rmtree(data.get("workspace", ""), ignore_errors=True)
            SESSIONS.pop(sid, None)
    # Sessions cannot survive a backend restart (their in-memory evidence index
    # is gone), so remove expired/orphaned temporary directories as well.
    if SESSION_ROOT.exists():
        for folder in SESSION_ROOT.iterdir():
            try:
                if folder.is_dir() and now - folder.stat().st_mtime > SESSION_TTL_SECONDS:
                    shutil.rmtree(folder, ignore_errors=True)
            except OSError:
                continue




def _psi_html_table_evidence(table: dict[str, Any]) -> dict[str, Any] | None:
    rows = table.get("rows") or []
    if len(rows) < 2:
        return None
    columns = [str(x).strip() for x in rows[0]][:200]
    data_rows = rows[1:1000]
    stats = {column: {"count": 0, "sum": 0.0, "min": None, "max": None} for column in columns}
    normalized_rows = []
    for row in data_rows:
        normalized = {columns[i]: (row[i] if i < len(row) else "") for i in range(len(columns))}
        normalized_rows.append(normalized)
        for column, value in normalized.items():
            try:
                number = float(str(value).replace(",", "").strip())
            except (TypeError, ValueError):
                continue
            stat = stats[column]
            stat["count"] += 1
            stat["sum"] += number
            stat["min"] = number if stat["min"] is None else min(stat["min"], number)
            stat["max"] = number if stat["max"] is None else max(stat["max"], number)
    numeric_summary = {k: {"count": v["count"], "min": v["min"], "max": v["max"], "mean": v["sum"] / v["count"]} for k, v in stats.items() if v["count"]}
    label = table.get("label") or table.get("table_id") or "NASA PSI experimental table"
    return {
        "filename": label, "format": "html_table", "category": table.get("category", "experimental_data"),
        "status": "extracted", "columns": columns, "sample_rows": normalized_rows[:100],
        "row_count_scanned": len(data_rows), "scan_truncated": bool(table.get("truncated")),
        "numeric_summary": numeric_summary,
        "content": f"NASA PSI HTML table: {label}\nColumns: {columns}\nRows returned: {len(data_rows)}\nNumeric summaries (units not inferred): {json.dumps(numeric_summary, ensure_ascii=False)}\nSample rows: {json.dumps(normalized_rows[:30], ensure_ascii=False)}",
        "source": "NASA PSI investigation page HTML"
    }


def _text_chunks(text: str, chunk_chars: int = 3500, overlap: int = 300) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    chunks, start = [], 0
    while start < len(text):
        end = min(len(text), start + chunk_chars)
        if end < len(text):
            # Prefer a paragraph/sentence boundary near the end of the window.
            boundary = max(text.rfind("\n\n", start, end), text.rfind(". ", start, end))
            if boundary > start + int(chunk_chars * 0.55):
                end = boundary + (2 if text[boundary:boundary + 2] == "\n\n" else 1)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def _evidence_records(extracted: dict[str, Any], source: str | None, category: str) -> list[dict[str, Any]]:
    """Turn long documents into retrievable chunks; keep tabular evidence structured."""
    base = {"filename": extracted.get("filename", "Unknown file"), "category": category,
            "status": extracted.get("status", "unknown"), "source": source,
            "format": extracted.get("format")}
    if extracted.get("status") != "extracted":
        return [{**base, **{k: v for k, v in extracted.items() if k not in {"content", "pages"}}, "content": extracted.get("content", "")}]
    if extracted.get("pages"):
        records = []
        for page in extracted["pages"]:
            for idx, chunk in enumerate(_text_chunks(page.get("text", ""))):
                records.append({**base, "page_number": page.get("page"), "chunk_index": idx, "content": chunk})
        return records or [{**base, "content": extracted.get("content", "")}]
    if extracted.get("slides"):
        records = []
        for slide in extracted["slides"]:
            slide_text = "\n".join(slide.get("text", []))
            for idx, chunk in enumerate(_text_chunks(slide_text)):
                records.append({**base, "slide_number": slide.get("slide"), "chunk_index": idx, "content": chunk})
        return records or [{**base, "content": extracted.get("content", "")}]
    if extracted.get("sheets"):
        records = []
        for sheet in extracted["sheets"]:
            sheet_payload = {k: sheet.get(k) for k in ("sheet", "row_count", "column_count", "header", "column_schema", "sample_rows") if sheet.get(k) is not None}
            records.append({**base, "sheet": sheet.get("sheet"), "columns": [str(x) for x in sheet.get("header", [])], "column_schema": sheet.get("column_schema", []), "row_count_scanned": sheet.get("row_count"), "column_count": sheet.get("column_count"), "sheets": [sheet], "content": json.dumps(sheet_payload, ensure_ascii=False, default=str)})
        return records or [{**base, "content": extracted.get("content", "")}]
    content = extracted.get("content", "")
    # CSV evidence carries schemas and measurements; keep its structured summary intact.
    if extracted.get("columns") or extracted.get("numeric_summary"):
        return [{**base, **{k: v for k, v in extracted.items() if k not in {"pages"}}, "content": content}]
    chunks = _text_chunks(content)
    return [{**base, "chunk_index": idx, "content": chunk} for idx, chunk in enumerate(chunks)] or [{**base, "content": content}]


def create_session(study_id: str) -> dict[str, Any]:
    cleanup_expired_sessions()
    record = _local_record(study_id)
    if not record:
        raise ValueError(f"Investigation {study_id} is not present in the local catalogue.")
    sid = re.sub(r"[^A-Za-z0-9_-]", "", study_id.upper())
    import uuid
    session_id = f"{sid}_{uuid.uuid4().hex[:12]}"
    SESSION_ROOT.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix=f"{session_id.lower()}_", dir=str(SESSION_ROOT)))
    raw_dir = workspace / "temporary_files"
    extracted_dir = workspace / "extracted"
    raw_dir.mkdir(); extracted_dir.mkdir()

    # No report/file contents are ingested automatically; this workspace is metadata-only.
    evidence = []

    # Metadata-first workspace: opening an investigation must not depend on a
    # live PSI manifest/network request. Users open the official PSI page and
    # upload any source files they want analyzed. No repository inventory is
    # fetched, downloaded, or displayed here.
    discovery = {
        "status": "metadata_only",
        "source_url": record.get("source_url") or f"https://psi.nasa.gov/physci/repo/data/investigations/{study_id.upper()}",
        "assets": [],
        "tables": [],
        "message": "Using locally indexed public investigation metadata. No PSI file inventory was requested.",
    }
    assets = []
    total_bytes = 0
    asset_results = []
    for asset in assets:
        item = dict(asset)
        item["study_id"] = study_id.upper()
        # Category inference uses PSI folder path as well as its label and filename.
        item["category"] = _category(f"{item.get('category', '')} {item.get('label', '')} {item.get('folder_path', '')}", item.get("filename", ""))
        item["asset_id"] = _asset_uid(item)
        item.setdefault("download_status", "restricted" if item.get("restricted") or item.get("restrictedAccess") else "listed")
        item.setdefault("attempts", 0)
        asset_results.append(item)

    capabilities = _derive_capabilities(asset_results, evidence, discovery.get("status", "unknown"))
    session_data = {
        "session_id": session_id,
        "study_id": study_id.upper(),
        "created_at": time.time(),
        "workspace": str(workspace),
        "record": record,
        "discovery": discovery,
        "assets": asset_results,
        "evidence": evidence,
        "capabilities": capabilities,
        "relationships": {"status": "not_indexed", "items": [], "note": "Cross-investigation relationships are not inferred without verified shared evidence."},
        "downloaded_bytes": total_bytes,
    }
    _persist_session(session_data)
    SESSIONS[session_id] = session_data
    return session_summary(session_data)



def fetch_deferred_assets(session: dict[str, Any], preferred_categories: list[str], evidence_terms: list[str] | None = None, max_candidates: int = 5) -> int:
    """Select, download and extract a bounded set of PSI assets for one question."""
    workspace = Path(session["workspace"])
    raw_dir = workspace / "temporary_files"
    raw_dir.mkdir(parents=True, exist_ok=True)
    wanted = {str(x).casefold() for x in (preferred_categories or [])}
    stop_terms = {
        "the", "and", "for", "with", "from", "what", "which", "about", "available",
        "investigation", "analysis", "analyze", "explain", "data", "research", "study",
        "file", "files", "nasa", "psi", "show", "find", "using", "based", "there",
        "their", "this", "that", "does", "have", "been", "into", "could", "would",
    }
    terms = set()
    for raw_term in evidence_terms or []:
        term = re.sub(r"\s+", " ", str(raw_term).casefold()).strip()
        if len(term) <= 2 or term in stop_terms or re.fullmatch(r"psi[-_ ]?\d+", term):
            continue
        terms.add(term)
    remaining = MAX_SESSION_MB * 1024 * 1024 - int(session.get("downloaded_bytes", 0))
    loaded = 0
    attempted_count = 0
    eligible = []
    retryable = {"listed", "session_budget_reached", "download_failed", "no_download_url"}
    for index, asset in enumerate(session.get("assets", [])):
        status = asset.get("download_status", "listed")
        if status not in retryable or int(asset.get("attempts", 0)) >= 2:
            continue
        category = str(asset.get("category", "other")).casefold()
        filename = str(asset.get("filename", ""))
        searchable = " ".join((filename, str(asset.get("label", "")), str(asset.get("folder_path", "")), str(asset.get("key", "")))).casefold()
        hits = sum(1 for term in terms if term in searchable)
        # Category is a weak prior, not a hard filter: PSI category labels vary
        # between investigations and often hide useful files in "other".
        category_score = 9 if category in wanted else (3 if category == "other" else 1)
        format_bonus = 4 if Path(filename).suffix.lower() in {".pdf", ".csv", ".tsv", ".xlsx", ".xls", ".docx", ".pptx", ".txt", ".zip"} else 0
        document_bonus = 2 if category in {"report", "science_documents", "experimental_data", "modeling_data", "raw_data", "analyzed_data"} else 0
        # Filename/folder term hits dominate category-only matches.
        score = hits * 8 + category_score + format_bonus + document_bonus
        if not terms and category not in wanted:
            continue
        size_hint = _size_bytes(asset.get("bytes_size") or asset.get("file_size") or asset.get("fileSize") or asset.get("sizeBytes") or asset.get("size") or 0)
        # For equally relevant assets, prefer smaller assets, but do not allow
        # a tiny unrelated file to outrank a filename match.
        eligible.append((score, size_hint or 10**18, index, asset, hits))

    eligible.sort(key=lambda row: (-row[0], row[1]))
    # If any filenames/folders match the question, do not waste downloads on
    # category-only files. If none match, use the best broad-category assets.
    if terms and any(row[4] > 0 for row in eligible):
        eligible = [row for row in eligible if row[4] > 0]

    # Download the bounded candidate set concurrently; extraction stays serial.
    selected = eligible[:max(1, min(int(max_candidates or 1), 8))] if remaining > 0 else []
    attempts = {}
    results = {}
    if selected and remaining > 0:
        with ThreadPoolExecutor(max_workers=min(4, len(selected))) as pool:
            futures = {}
            for _, _, index, asset, _hits in selected:
                attempted = {**asset, "study_id": session.get("study_id"), "attempts": int(asset.get("attempts", 0)) + 1}
                attempts[index] = attempted
                futures[pool.submit(_download_asset, attempted, raw_dir, remaining, ON_DEMAND_MAX_FILE_MB * 1024 * 1024)] = index
            for future in as_completed(futures):
                index = futures[future]
                try:
                    results[index] = future.result()
                except Exception as exc:
                    results[index] = ({**attempts[index], "download_status": "download_failed", "download_error": f"{type(exc).__name__}: {exc}"[:500]}, 0)

    for _, _, index, asset, _hits in selected:
        attempted_count += 1
        attempted = attempts[index]
        updated, size = results.get(index, ({**attempted, "download_status": "session_budget_reached"}, 0))
        if size and size > remaining:
            Path(updated.get("local_path", "")).unlink(missing_ok=True)
            updated = {**updated, "download_status": "session_budget_reached", "local_path": None}
            size = 0
        session["assets"][index] = updated
        if updated.get("download_status") != "downloaded":
            continue
        remaining -= size
        session["downloaded_bytes"] = int(session.get("downloaded_bytes", 0)) + size
        path = Path(updated["local_path"])
        extracted = _extract_file(path)
        source_url = updated.get("download_url_used") or updated.get("url") or asset.get("url") or asset.get("key")
        records = _evidence_records(extracted, source_url, asset.get("category", "other"))
        for record in records:
            record.update({"asset_id": asset.get("asset_id"), "psi_key": asset.get("key"), "folder_path": asset.get("folder_path"), "file_id": asset.get("id")})
        session["evidence"].extend(records)
        processing_status = extracted.get("status", "unknown")

        is_archive = path.name.casefold().endswith((".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".gz"))
        if is_archive and processing_status in {"unsupported", "metadata_only"}:
            try:
                children = _safe_extract_archive(path, workspace / "extracted")
                extracted_children = 0
                all_children_processed = bool(children)
                for child in children:
                    child_data = _extract_file(child)
                    child_category = _category(f"{asset.get('folder_path', '')} {child.name}", child.name)
                    child_records = _evidence_records(child_data, f"{source_url}::{child.name}", child_category if child_category != "other" else asset.get("category", "other"))
                    for record in child_records:
                        record.update({"asset_id": asset.get("asset_id"), "archive_member": child.name, "psi_key": asset.get("key")})
                    session["evidence"].extend(child_records)
                    if child_data.get("status") == "extracted" and str(child_data.get("content", "")).strip():
                        extracted_children += 1
                        child.unlink(missing_ok=True)
                    else:
                        all_children_processed = False
                if extracted_children:
                    processing_status = f"archive_processed_{extracted_children}_of_{len(children)}"
                    if all_children_processed:
                        updated["download_status"] = "downloaded_and_extracted"
                        updated["local_path"] = str(path)
                    else:
                        updated["download_status"] = "downloaded_partial_archive"
                        updated["local_path"] = str(path)
                else:
                    processing_status = "archive_no_extractable_members"
                    updated["download_status"] = "downloaded_no_text"
                    updated["local_path"] = str(path)
            except Exception as exc:
                processing_status = "archive_extraction_failed"
                updated["download_status"] = "downloaded_extraction_failed"
                updated["local_path"] = str(path)
                session["evidence"].append({"filename": path.name, "asset_id": asset.get("asset_id"), "category": asset.get("category", "other"), "status": processing_status, "error": str(exc)[:300], "content": ""})
        elif processing_status == "extracted" and str(extracted.get("content", "")).strip():
            updated["download_status"] = "downloaded_and_extracted"
            updated["local_path"] = str(path)
        else:
            # Never discard originals if extraction was empty, unsupported or failed.
            updated["download_status"] = "downloaded_unsupported" if processing_status in {"unsupported", "metadata_only", "no_text"} else "downloaded_extraction_failed"
            updated["local_path"] = str(path)
        updated["processing_status"] = processing_status
        session["assets"][index] = updated
        loaded += 1

    session["capabilities"] = _derive_capabilities(session.get("assets", []), session.get("evidence", []), session.get("discovery", {}).get("status", "unknown"))
    _persist_session(session)
    return loaded


def ingest_session_batch(session: dict[str, Any], batch_size: int = 8) -> dict[str, Any]:
    """Download and extract the next batch of every accessible asset in a PSI study.

    This is deliberately investigation-wide (not question-ranked) ingestion.
    Files are streamed to session disk, parsed, and deleted only after successful
    extraction. Existing session and aggregate byte limits remain in force.
    """
    batch_size = max(1, min(int(batch_size or 8), 20))
    retryable = {"listed", "session_budget_reached", "download_failed", "no_download_url"}
    before_attempts = sum(int(a.get("attempts", 0)) for a in session.get("assets", []))
    pending_before = sum(
        1 for a in session.get("assets", [])
        if a.get("download_status", "listed") in retryable and int(a.get("attempts", 0)) < 2
        and not (a.get("restricted") or a.get("restrictedAccess"))
    )
    categories = sorted({str(a.get("category") or "other") for a in session.get("assets", [])})
    loaded = fetch_deferred_assets(session, categories, evidence_terms=[], max_candidates=batch_size)
    after_attempts = sum(int(a.get("attempts", 0)) for a in session.get("assets", []))
    attempted = max(0, after_attempts - before_attempts)
    pending_after = sum(
        1 for a in session.get("assets", [])
        if a.get("download_status", "listed") in retryable and int(a.get("attempts", 0)) < 2
        and not (a.get("restricted") or a.get("restrictedAccess"))
    )
    budget_exhausted = int(session.get("downloaded_bytes", 0)) >= MAX_SESSION_MB * 1024 * 1024
    return {
        "batch_size": batch_size,
        "attempted": attempted,
        "extracted_this_batch": loaded,
        "pending_before": pending_before,
        "pending_after": pending_after,
        "has_more": bool(pending_after and not budget_exhausted and attempted > 0),
        "budget_exhausted": budget_exhausted,
        "downloaded_bytes": int(session.get("downloaded_bytes", 0)),
        "evidence_count": len(session.get("evidence", [])),
    }


def _derive_capabilities(assets: list[dict], evidence: list[dict], discovery_status: str = "unknown") -> dict[str, Any]:
    """Evidence-verified capability statuses; listing a filename alone is never proof."""
    extracted = [e for e in evidence if e.get("status") == "extracted" and str(e.get("content") or "").strip()]
    categories = {str(a.get("category", "other")).casefold() for a in assets}
    categories.update(str(e.get("category", "other")).casefold() for e in evidence)
    text = " ".join(str(e.get("content", "")) for e in extracted).casefold()
    filename_text = " ".join(" ".join(str(a.get(k, "")) for k in ("filename", "label", "folder_path")) for a in assets).casefold()

    def status_for(relevant_categories: set[str], terms: tuple[str, ...] = (), require_terms: bool = False) -> tuple[str, int, int]:
        matching_assets = [a for a in assets if str(a.get("category", "other")).casefold() in relevant_categories or any(t in " ".join(str(a.get(k, "")) for k in ("filename", "label", "folder_path")).casefold() for t in terms)]
        matching_evidence = [e for e in extracted if ((not require_terms and str(e.get("category", "other")).casefold() in relevant_categories) or any(t in str(e.get("content", "")).casefold() for t in terms))]
        if matching_evidence:
            return "available", len(matching_evidence), len(matching_assets)
        if matching_assets:
            return "partial", 0, len(matching_assets)
        if discovery_status not in {"complete", "empty"}:
            return "not_indexed", 0, 0
        return "unavailable", 0, 0

    definitions = {
        "research_findings": ({"report", "science_documents", "presentation"}, ("finding", "result", "conclusion")),
        "safety_insights": ({"report", "science_documents", "experimental_data", "raw_data", "analyzed_data"}, ("smoke", "aerosol", "ignition", "extinction", "flammability", "hazard", "suppress", "detection", "toxicity", "combustion")),
        "experimental_analysis": ({"experimental_data", "raw_data", "analyzed_data"}, ("measurement", "diameter", "temperature", "pressure", "concentration", "time")),
        "modeling_analysis": ({"modeling_data"}, ("model", "simulation", "calculation")),
        "visual_analysis": ({"image", "video"}, ()),
        "investigation_explanation": ({"report", "science_documents", "presentation"}, ("objective", "method", "experiment", "investigation")),
        "cross_investigation_comparison": (set(), ()),
    }
    capabilities = {}
    for name, (cats, terms) in definitions.items():
        if name == "cross_investigation_comparison":
            capabilities[name] = {"status": "not_indexed", "evidence_count": 0, "asset_count": 0, "reason": "Requires separately indexed evidence from multiple investigations."}
        else:
            # Safety requires extracted text that actually contains a safety-relevant
            # term; the mere existence of a report is not enough.
            status, evidence_count, asset_count = status_for(cats, terms, require_terms=(name == "safety_insights"))
            capabilities[name] = {"status": status, "evidence_count": evidence_count, "asset_count": asset_count}
    capabilities["summary"] = {
        "listed_assets": len(assets), "extracted_evidence_records": len(extracted),
        "discovery_status": discovery_status,
        "note": "available means extracted supporting content was found; partial means potentially relevant files are listed but not yet verified; unavailable means the completed inventory did not identify supporting assets; not_indexed means availability has not been evaluated."
    }
    return capabilities


def explore_session_datasets(session: dict[str, Any], question: str = "Find experimental and modeling datasets, measurement tables, and numerical results") -> dict[str, Any]:
    """Return PSI inventory metadata only; never download or extract repository files."""
    terms = [term.casefold() for term in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", question)]
    datasets = []
    for asset in session.get("assets", []):
        category = str(asset.get("category") or "").casefold()
        filename = str(asset.get("filename") or "").casefold()
        if any(token in category or token in filename for token in terms) or category in {"experimental_data", "modeling_data", "raw_data", "analyzed_data", "calibration"}:
            datasets.append({k: asset.get(k) for k in ("filename", "label", "category", "folder_path", "bytes_size", "extension", "restricted", "download_status", "source") if asset.get(k) is not None})
    return {"study_id": session.get("study_id"), "datasets": datasets, "dataset_count": len(datasets), "session_summary": session_summary(session), "mode": "metadata_inventory_only", "message": "This is a metadata inventory, not an inspected dataset. Download a relevant file from the official PSI page and upload it to analyze its contents."}


def get_session(session_id: str) -> dict[str, Any] | None:
    cleanup_expired_sessions()
    if session_id in SESSIONS:
        return SESSIONS[session_id]
    # Rehydrate from the temporary workspace so multiple Uvicorn workers can
    # serve a session. The workspace remains ephemeral and TTL-bound.
    if not re.fullmatch(r"PSI-\d+_[a-f0-9]{12}", session_id):
        return None
    for folder in SESSION_ROOT.glob(f"{session_id.lower()}_*") if SESSION_ROOT.exists() else []:
        try:
            metadata_path = folder / "session.json"
            evidence_path = folder / "document_chunks.jsonl"
            legacy_evidence_path = folder / "evidence.json"
            if not metadata_path.exists() or not (evidence_path.exists() or legacy_evidence_path.exists()):
                continue
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
            if evidence_path.exists():
                data["evidence"] = [json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            else:
                data["evidence"] = json.loads(legacy_evidence_path.read_text(encoding="utf-8"))
            data.setdefault("relationships", {"status": "not_indexed", "items": []})
            data["workspace"] = str(folder)
            SESSIONS[session_id] = data
            return data
        except Exception:
            continue
    return None



def _evidence_inventory(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in evidence:
        name = item.get("filename") or item.get("asset") or "Local report"
        row = grouped.setdefault(name, {"filename": name, "category": item.get("category", "report"), "status": item.get("status", "unknown"), "columns": item.get("columns", []), "row_count_scanned": item.get("row_count_scanned"), "numeric_summary": item.get("numeric_summary", {}), "sheets": [x.get("sheet") for x in item.get("sheets", [])], "pages": 0, "chunks": 0})
        row["chunks"] += 1
        if item.get("page_number"):
            row["pages"] = max(row["pages"], int(item["page_number"]))
    return list(grouped.values())


def session_summary(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": data["session_id"], "study_id": data["study_id"],
        "record": data["record"], "discovery_status": data["discovery"].get("status"),
        "discovery_message": data["discovery"].get("message"),
        "source_url": data["discovery"].get("source_url"),
        # The full manifest remains in the temporary workspace. Return a compact
        # preview to the browser so 20k+ file investigations do not create huge
        # API responses or React state objects on every analysis turn.
        "assets": [{k: v for k, v in a.items() if k != "local_path"} for a in data["assets"][:100]],
        "assets_preview_count": min(100, len(data.get("assets", []))),
        "assets_truncated": len(data.get("assets", [])) > 100,
        "asset_categories": sorted({str(a.get("category", "other")) for a in data.get("assets", []) if a.get("category")}),
        "capabilities": data["capabilities"],
        "evidence_count": len(data["evidence"]),
        "evidence_inventory": _evidence_inventory(data["evidence"]),
        "listed_file_count": len(data.get("assets", [])),
        "downloaded_file_count": sum(1 for a in data.get("assets", []) if str(a.get("download_status", "")).startswith("downloaded_")),
        "extracted_file_count": sum(1 for a in data.get("assets", []) if a.get("download_status") in {"downloaded_and_deleted", "downloaded_and_extracted", "downloaded_partial_archive"}),
        "failed_file_count": sum(1 for a in data.get("assets", []) if str(a.get("download_status", "")) in {"download_failed", "downloaded_extraction_failed", "downloaded_partial_archive", "downloaded_no_text", "not_found", "access_denied", "blocked_external_url"}),
        "restricted_file_count": sum(1 for a in data.get("assets", []) if a.get("download_status") == "restricted"),
        "deferred_file_count": sum(1 for a in data.get("assets", []) if a.get("download_status") in {"deferred_size_limit", "session_budget_reached"}),
        "no_download_url_count": sum(1 for a in data.get("assets", []) if a.get("download_status") == "no_download_url"),
        "unsupported_file_count": sum(1 for a in data.get("assets", []) if a.get("download_status") == "downloaded_unsupported"),
        "pending_file_count": sum(1 for a in data.get("assets", []) if a.get("download_status", "listed") in {"listed", "no_download_url", "download_failed", "session_budget_reached"} and int(a.get("attempts", 0)) < 2),
        "dataset_count": len({(str(e.get("filename") or e.get("asset")), str(e.get("sheet") or "")) for e in data.get("evidence", []) if e.get("columns") or e.get("sheets") or e.get("numeric_summary")}),
        "downloaded_bytes": data["downloaded_bytes"],
        "expires_in_seconds": max(0, SESSION_TTL_SECONDS - int(time.time() - data["created_at"])),
        "workspace_status": "ready"
    }


def delete_session(session_id: str) -> bool:
    data = SESSIONS.pop(session_id, None)
    if data:
        shutil.rmtree(data.get("workspace", ""), ignore_errors=True)
        return True
    if not re.fullmatch(r"PSI-\d+_[a-f0-9]{12}", session_id):
        return False
    deleted = False
    for folder in SESSION_ROOT.glob(f"{session_id.lower()}_*") if SESSION_ROOT.exists() else []:
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
            deleted = True
    return deleted


def append_evidence(session_id: str, evidence: dict[str, Any]):
    data = get_session(session_id)
    if not data:
        return
    data["evidence"].append(evidence)
    data["capabilities"] = _derive_capabilities(data.get("assets", []), data["evidence"], data.get("discovery", {}).get("status", "unknown"))
    _persist_session(data)
