"""Best-effort public NASA PSI investigation asset discovery.

PSI's public UI is the source of truth. This adapter deliberately reports an
inventory as partial/unknown when its file list is rendered client-side or
cannot be parsed; it never invents asset records.
"""
from __future__ import annotations

import re
import json
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any

PSI_BASE = "https://psi.nasa.gov/physci/repo/data/investigations/"
FILE_EXTENSIONS = {
    ".pdf", ".csv", ".tsv", ".xlsx", ".xls", ".json", ".txt", ".docx",
    ".doc", ".pptx", ".ppt", ".mp4", ".mov", ".avi", ".png", ".jpg",
    ".jpeg", ".tif", ".tiff", ".zip", ".tar", ".gz", ".tgz", ".fits",
    ".h5", ".hdf5", ".mat", ".dat", ".bin", ".nc", ".xml", ".md", ".rtf"
}

class _AnchorParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[dict[str, str]] = []
        self._href = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.links.append({"href": self._href, "label": " ".join(" ".join(self._text).split())})
            self._href = None
            self._text = []




class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables: list[dict[str, Any]] = []
        self.current_table = None
        self.current_row = None
        self.current_cell = None
        self.recent_text = ""
        self.current_heading = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag.lower() in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.current_heading = ""
        if tag.lower() == "table":
            self.current_table = {"id": attrs.get("id", ""), "class": attrs.get("class", ""), "label": self.current_heading or self.recent_text[-240:], "rows": []}
        elif tag.lower() == "tr" and self.current_table is not None:
            self.current_row = []
        elif tag.lower() in {"td", "th"} and self.current_row is not None:
            self.current_cell = []

    def handle_data(self, data):
        value = " ".join(data.split())
        if not value:
            return
        self.recent_text = (self.recent_text + " " + value)[-500:]
        self.current_heading = (self.current_heading + " " + value).strip()[-240:]
        if self.current_cell is not None:
            self.current_cell.append(value)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"td", "th"} and self.current_cell is not None and self.current_row is not None:
            self.current_row.append(" ".join(self.current_cell).strip())
            self.current_cell = None
        elif tag == "tr" and self.current_row is not None and self.current_table is not None:
            if any(self.current_row) and len(self.current_table["rows"]) < 1001:
                self.current_table["rows"].append(self.current_row)
            self.current_row = None
        elif tag == "table" and self.current_table is not None:
            if self.current_table["rows"]:
                self.tables.append(self.current_table)
            self.current_table = None


def is_allowed_psi_file_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    if host == "psi.nasa.gov" or host.endswith(".nasa.gov"):
        return True
    if host in {"psi-repo-prod.s3.amazonaws.com", "psi-repo-prod.s3.us-west-2.amazonaws.com"}:
        # This bucket is shared; accept only object keys scoped to a PSI study.
        return bool(re.match(r"^/psi-data/PSI-\d+/.+", urllib.parse.unquote(parsed.path), re.IGNORECASE))
    if host in {"nasa-psi.s3.us-west-2.amazonaws.com", "nasa-psi.s3.amazonaws.com"}:
        return True
    # Retain the historical NASA PSI bucket's regional endpoint.
    if host == "s3.amazonaws.com" and parsed.path.startswith("/nasa-psi/"):
        return True
    if host == "s3.us-west-2.amazonaws.com" and parsed.path.startswith("/nasa-psi/"):
        return True
    return False


def _category(label: str, filename: str) -> str:
    raw_value = f"{label} {filename}".casefold().replace("_", " ").replace("-", " ")
    value = raw_value
    mappings = [
        ("metadata", ("metadata files", "investigation metadata", "study metadata")),
        ("experimental_data", ("experimental table", "experimental data", "experiment data", "measurement data")),
        ("modeling_data", ("modeling table", "modeling data", "simulation", "numerical model", "computational")),
        ("raw_data", ("raw data", "raw measurements")),
        ("analyzed_data", ("analyzed data", "analysed data", "processed data", "proc1", "mst")),
        ("report", ("report", "final report", "research report", "technical report")),
        ("science_documents", ("science documents", "science document", "research docs", "research documents", "publication")),
        ("engineering_documents", ("engineering documents", "engineering document", "vpred", "verification plan")),
        ("presentation", ("presentation", "presentations", "slides", "powerpoint")),
        ("calibration", ("calibration",)),
        ("image", ("image", "photo", "figure")),
        ("video", ("video", "movie")),
    ]
    # PSI folders can contain a meaningful category and a nested subfolder
    # such as "Simulation". Prefer the first explicit category in the folder
    # hierarchy so "Analyzed Data/.../Simulation" is not mislabeled as modeling.
    path_segments = [segment.strip() for segment in re.split(r"[/\\\\]+", raw_value) if segment.strip()]
    for segment in path_segments:
        for category, terms in mappings:
            if any(term in segment for term in terms):
                return category
    for category, terms in mappings:
        if any(term in value for term in terms):
            return category
    return "other"


def _flatten_psi_v2(nodes: list[dict] | dict, parent_path: str = "", output: list[dict] | None = None) -> list[dict]:
    """Flatten PSI/Geode file manifests across known and wrapped response shapes.

    The API has returned plain ``files`` arrays, nested folder trees, and
    envelopes such as ``result -> data -> files``. Walk the complete JSON tree
    rather than assuming one envelope shape. Only dictionaries that look like
    file records are emitted; folder and metadata nodes are traversed.
    """
    output = output if output is not None else []
    seen_nodes: set[int] = set()
    seen_assets = {str(a.get("id") or a.get("key") or a.get("filename") or "") for a in output}
    filename_keys = ("filename", "fileName", "file_name", "file", "name")
    url_keys = ("url", "downloadUrl", "download_url", "remote_url", "remoteUrl", "fileUrl")
    size_keys = ("bytes_size", "file_size", "fileSize", "sizeBytes", "size", "filesize")

    def walk(value: Any, inherited_path: str = "") -> None:
        if isinstance(value, list):
            for child in value:
                walk(child, inherited_path)
            return
        if not isinstance(value, dict) or id(value) in seen_nodes:
            return
        seen_nodes.add(id(value))

        key = str(value.get("key") or value.get("path") or value.get("folderPath") or "")
        path = key.rstrip("/") if key else inherited_path
        children = []
        for child_key in ("files", "children", "folders", "items", "results", "study_files"):
            child_value = value.get(child_key)
            if isinstance(child_value, (list, dict)):
                children.append(child_value)
        filename_value = next((value.get(k) for k in filename_keys if value.get(k)), None)
        direct_url = next((value.get(k) for k in url_keys if value.get(k)), None)
        file_id = next((value.get(k) for k in ("id", "fileId", "file_id", "fileID", "fileid", "uuid") if value.get(k)), None)
        # Some PSI leaf records contain only an opaque id + a key ending in
        # the filename, with no `fileName` field at all.
        key_basename = key.rstrip("/").rsplit("/", 1)[-1] if key else ""
        filename_text = str(filename_value or key_basename)
        explicit_filename = any(value.get(k) for k in ("filename", "fileName", "file_name", "file"))
        key_looks_like_file = bool(key_basename and "." in key_basename and not key_basename.endswith("."))
        looks_like_file = bool(direct_url or explicit_filename or key_looks_like_file or (filename_text and "." in filename_text.rsplit("/", 1)[-1] and not children))

        if looks_like_file:
            file_key = key or filename_text
            filename = filename_text.rsplit("/", 1)[-1] if filename_text else file_key.rstrip("/").rsplit("/", 1)[-1] or "unnamed"
            folder = (file_key.rsplit("/", 1)[0] if "/" in file_key else path)
            label = str(value.get("sortingCategory") or value.get("category") or value.get("label") or value.get("displayName") or "")
            size = next((value.get(k) for k in size_keys if value.get(k) is not None), None)
            identity = str(file_id or file_key or filename)
            if identity not in seen_assets:
                seen_assets.add(identity)
                restricted = bool(value.get("restricted") or value.get("restrictedAccess"))
                output.append({
                    "filename": filename, "label": label, "folder_path": folder,
                    "key": file_key, "id": file_id, "file_id": file_id,
                    "version": value.get("version") or value.get("fileVersion") or value.get("file_version") or 2,
                    "study_version": value.get("studyVersion") or value.get("study_version") or 2,
                    "url": direct_url, "download_url": direct_url,
                    "remote_url": value.get("remote_url") or value.get("remoteUrl"),
                    "bytes_size": size, "size": size,
                    "extension": "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else "",
                    "category": _category(f"{label} {folder}", filename),
                    "restricted": restricted, "status": value.get("status"),
                    "updated": value.get("updated"), "visible": value.get("visible", True),
                    "source": "NASA PSI v2 file inventory",
                    "download_status": "restricted" if restricted else ("listed" if direct_url or file_id else "no_download_url"),
                })

        # Preserve the folder context when walking nested children. Then walk
        # all remaining JSON containers too, covering API envelope aliases.
        child_ids = set()
        for child in children:
            child_ids.add(id(child))
            walk(child, path or inherited_path)
        for child_key, child in value.items():
            if child_key in {"files", "children", "folders", "items", "results", "study_files"}:
                continue
            if isinstance(child, (dict, list)):
                walk(child, path or inherited_path)

    walk(nodes, parent_path)
    return output


def _metadata_version(payload: Any) -> int | None:
    """Read a study version from common PSI metadata envelopes."""
    if isinstance(payload, dict):
        for key in ("studyVersion", "study_version", "version"):
            value = payload.get(key)
            if isinstance(value, (int, float)) and value > 0:
                return int(value)
        for value in payload.values():
            found = _metadata_version(value)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _metadata_version(value)
            if found is not None:
                return found
    return None


def _history_assets(payload: Any, study_id: str) -> list[dict[str, Any]]:
    """Reconstruct the currently active files from a version-history response."""
    versions = payload.get("versions", []) if isinstance(payload, dict) else []
    active: dict[str, dict[str, Any]] = {}
    for version in versions if isinstance(versions, list) else []:
        if not isinstance(version, dict):
            continue
        for item in version.get("added", []) or []:
            if not isinstance(item, dict):
                continue
            name = item.get("filename") or item.get("fileName") or item.get("file_name") or item.get("name") or item.get("key")
            if not name:
                continue
            identity = str(item.get("id") or name)
            active[identity] = {**item, "study_id": study_id.upper(), "filename": str(name).rsplit("/", 1)[-1]}
        for item in version.get("removed", []) or []:
            if not isinstance(item, dict):
                continue
            name = item.get("filename") or item.get("fileName") or item.get("file_name") or item.get("name") or item.get("key")
            identity = str(item.get("id") or name or "")
            active.pop(identity, None)
    return list(active.values())

def discover_psi_v2(study_id: str, timeout: int = 12) -> dict[str, Any]:
    endpoint = "https://psi.nasa.gov/geode-py/ws/files/v2"
    payload = {"folder": f"{study_id.upper()}/", "fileType": "study", "studyId": study_id.upper(), "version": 2, "obfuscationcode": ""}
    request = urllib.request.Request(endpoint, data=json.dumps(payload).encode(), method="POST",
        headers={"Accept":"application/json", "Content-Type":"application/json", "Origin":"https://psi.nasa.gov",
                 "Referer": f"https://psi.nasa.gov/physci/repo/data/investigations/{study_id.upper()}", "User-Agent":"FirelyticsAI/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data=json.loads(response.read(64*1024*1024 + 1).decode("utf-8", "replace"))
        assets = _flatten_psi_v2(data)
        return {"status":"complete" if assets else "empty", "source_url":f"https://psi.nasa.gov/physci/repo/data/investigations/{study_id.upper()}",
                "assets":assets,"tables":[],"message":f"NASA PSI v2 inventory: {len(assets)} files."}
    except Exception as exc:
        return {"status":"api_failed","source_url":f"https://psi.nasa.gov/physci/repo/data/investigations/{study_id.upper()}",
                "assets":[],"tables":[],"message":f"PSI v2 inventory request failed: {type(exc).__name__}: {exc}"}

def discover_investigation_files(study_id: str, timeout: int = 8) -> dict[str, Any]:
    api_result = discover_psi_v2(study_id, timeout=timeout)
    if api_result.get("assets"):
        return api_result
    url = PSI_BASE + urllib.parse.quote(study_id.upper())
    request = urllib.request.Request(url, headers={"User-Agent": "FirelyticsAI/1.0 (research support; contact via project)"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            html = response.read(8 * 1024 * 1024).decode("utf-8", errors="replace")
            final_url = response.geturl()
    except Exception as exc:
        return {"status": "access_failed", "source_url": url, "assets": [], "tables": [], "message": f"Could not access the public PSI record: {type(exc).__name__}: {exc}"}

    parser = _AnchorParser()
    parser.feed(html)
    table_parser = _TableParser()
    table_parser.feed(html)
    tables = []
    for index, table in enumerate(table_parser.tables, 1):
        label = " ".join([table.get("label", ""), table.get("id", ""), table.get("class", "")]).casefold()
        if "experimental" not in label and "model" not in label:
            continue
        rows = table.get("rows", [])
        if len(rows) < 2:
            continue
        tables.append({"table_id": f"psi_html_table_{index}", "label": table.get("label", ""), "category": "modeling_data" if "model" in label else "experimental_data", "rows": rows[:1000], "row_count_returned": len(rows), "truncated": len(rows) >= 1001})
    assets, seen = [], set()
    for link in parser.links:
        href = (link.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        absolute = urllib.parse.urljoin(final_url, href)
        parsed = urllib.parse.urlparse(absolute)
        path = urllib.parse.unquote(parsed.path)
        filename = path.rsplit("/", 1)[-1]
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        label = link.get("label") or filename
        # Only direct file-like links are accepted. Avoid treating navigation links as assets.
        if ext not in FILE_EXTENSIONS or not is_allowed_psi_file_url(absolute):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        assets.append({
            "filename": filename or label,
            "label": label,
            "url": absolute,
            "extension": ext,
            "category": _category(label, filename),
            "source": "NASA PSI public record link",
        })

    # Some PSI builds place file URLs in embedded JSON rather than anchor tags.
    # Recover only explicit direct URLs ending in known file extensions.
    ext_pattern = "|".join(re.escape(x.lstrip(".")) for x in sorted(FILE_EXTENSIONS))
    url_pattern = re.compile(r"(?:https?:)?//[^\"'\s<>]+?\.(?:" + ext_pattern + r")(?:\?[^\"'\s<>]*)?", re.I)
    for match in url_pattern.findall(html):
        candidate = urllib.parse.urljoin(final_url, match.rstrip("),;\\"))
        if candidate in seen:
            continue
        parsed = urllib.parse.urlparse(candidate)
        filename = urllib.parse.unquote(parsed.path).rsplit("/", 1)[-1]
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in FILE_EXTENSIONS or not is_allowed_psi_file_url(candidate):
            continue
        seen.add(candidate)
        assets.append({"filename": filename, "label": filename, "url": candidate, "extension": ext, "category": _category(filename, filename), "source": "NASA PSI embedded file URL"})

    # Some rendered PSI file browsers expose filenames in embedded state without
    # a direct download URL. Keep these as metadata-only candidates; never guess
    # a download endpoint from a filename.
    filename_pattern = re.compile(r"[\"']([^\"'<>/\\]+\.(?:" + ext_pattern + r"))[\"']", re.I)
    for match in filename_pattern.finditer(html):
        filename = match.group(1)
        context = html[max(0, match.start() - 220):min(len(html), match.end() + 220)]
        key = f"metadata-only::{filename}"
        if key in seen:
            continue
        seen.add(key)
        assets.append({"filename": filename, "label": filename, "url": None, "extension": "." + filename.rsplit(".", 1)[-1].lower(), "category": _category(context, filename), "source": "NASA PSI embedded file metadata", "download_status": "no_direct_url"})

    if assets or tables:
        status = "partial"  # HTML discovery cannot prove the page exposed every file/table row
        message = "Discovered file metadata and/or experimental tables from the public PSI page. The inventory may be partial if PSI renders additional content dynamically."
    else:
        status = "inventory_unavailable"
        api_message = api_result.get("message", "PSI file API returned no file records.")
        message = ("No file inventory could be confirmed for this investigation. "
                   "The public HTML did not expose direct file links or experimental tables, and the PSI file API returned: "
                   f"{api_message} The app will not invent file links or report a successful download.")
    return {"status": status, "source_url": final_url, "assets": assets, "tables": tables, "message": message}
