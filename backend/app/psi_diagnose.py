"""Live diagnostics for NASA PSI discovery and download routes.

    python -m app.psi_diagnose PSI-100            (run from the backend/ folder)
    GET /api/diagnostics/psi/PSI-100

For one investigation it reports: which study versions returned a file list,
how many files were found, and - for a few of the smallest files - the HTTP
status, content type and first bytes of every download route that
``_psi_download_candidates`` generates. If a study fails to download, this shows
which step fails.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .psi_discovery import discover_investigation_files, is_allowed_psi_file_url
from .session_service import _psi_download_candidates, _size_bytes, _find_download_url


def _probe(url: str, timeout: int = 15) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 FirelyticsAI/1.0",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://psi.nasa.gov/",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            head = response.read(400)
            final = response.geturl()
            kind = "binary/file"
            stripped = head.lstrip()
            envelope_url = None
            if stripped.startswith((b"{", b"[")):
                kind = "json"
                try:
                    envelope_url = _find_download_url(json.loads(head.decode("utf-8", "replace") + ("" if len(head) < 400 else "")))
                except Exception:
                    envelope_url = None
            elif stripped.lower().startswith((b"https://", b"http://")):
                kind = "plain-text url"
                envelope_url = stripped.decode("utf-8", "replace").split()[0]
            elif b"<html" in stripped.lower() or b"<!doctype" in stripped.lower():
                kind = "html (not a file)"
            return {"url": url, "status": response.status, "content_type": response.headers.get("Content-Type"),
                    "content_length": response.headers.get("Content-Length"), "final_host": urllib.parse.urlparse(final).hostname,
                    "final_allowed": is_allowed_psi_file_url(final, trusted=True), "looks_like": kind,
                    "envelope_url_host": urllib.parse.urlparse(envelope_url).hostname if envelope_url else None,
                    "envelope_allowed": is_allowed_psi_file_url(envelope_url, trusted=True) if envelope_url else None,
                    "first_bytes": head[:120].decode("utf-8", "replace")}
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(160).decode("utf-8", "replace")
        except Exception:
            body = ""
        return {"url": url, "status": exc.code, "error": f"HTTP {exc.code} {exc.reason}", "body": body}
    except Exception as exc:
        return {"url": url, "status": None, "error": f"{type(exc).__name__}: {exc}"}


def diagnose(study_id: str, max_files: int = 2) -> dict[str, Any]:
    discovery = discover_investigation_files(study_id, timeout=12)
    assets = discovery.get("assets", [])
    report: dict[str, Any] = {
        "study_id": study_id, "discovery_status": discovery.get("status"), "message": discovery.get("message"),
        "study_version": discovery.get("study_version"), "study_version_candidates": discovery.get("study_version_candidates"),
        "versions_probed": discovery.get("probe"), "folder_requests": discovery.get("folder_requests"),
        "files_listed": len(assets), "sample_files": [],
    }
    usable = [a for a in assets if not (a.get("restricted") or a.get("restrictedAccess"))]
    usable.sort(key=lambda a: _size_bytes(a.get("bytes_size")) or 10 ** 12)
    for asset in usable[:max_files]:
        item = {**asset, "study_id": study_id}
        routes = [_probe(url) for url in _psi_download_candidates(item)]
        report["sample_files"].append({"filename": asset.get("filename"), "key": asset.get("key"), "id": asset.get("id"),
                                       "size": asset.get("bytes_size"), "category": asset.get("category"), "routes": routes})
    return report


if __name__ == "__main__":
    target = (sys.argv[1] if len(sys.argv) > 1 else "PSI-117").upper()
    print(json.dumps(diagnose(target), indent=2, default=str))
