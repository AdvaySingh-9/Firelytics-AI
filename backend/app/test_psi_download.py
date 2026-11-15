import json
import io
import zipfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.psi_discovery import _flatten_psi_v2, _history_assets, _metadata_version, is_allowed_psi_file_url
from app.session_service import _psi_download_candidates, _download_asset, fetch_deferred_assets


class FakeResponse:
    def __init__(self, body, headers=None, url="https://psi.nasa.gov/geode-py/ws/studies/PSI-117/download"):
        self.body = body
        self.headers = headers or {}
        self.url = url
        self.offset = 0
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def geturl(self): return self.url
    def read(self, n=-1):
        if n < 0: n = len(self.body) - self.offset
        chunk = self.body[self.offset:self.offset+n]
        self.offset += len(chunk)
        return chunk


class PsiDownloadTests(unittest.TestCase):
    def test_flatten_wrapped_manifest_envelope_and_study_files(self):
        payload = {"result": {"data": {"study_files": [
            {"file_name": "sample.csv", "remote_url": "/geode-py/ws/studies/PSI-117/download?file=sample.csv", "file_size": "1.2MB"}
        ]}}}
        assets = _flatten_psi_v2(payload)
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["filename"], "sample.csv")
        self.assertEqual(assets[0]["url"], "/geode-py/ws/studies/PSI-117/download?file=sample.csv")

    def test_flatten_nested_v2_folder_tree(self):
        tree = {"result": {"data": {"files": [
            {"name": "Raw Data", "key": "PSI-117/Raw Data/", "files": [
                {"fileName": "camera.csv", "key": "PSI-117/Raw Data/camera.csv",
                 "id": "6a282739d9d7246402cb43de", "version": 2}
            ]}
        ]}}}
        assets = _flatten_psi_v2(tree)
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["filename"], "camera.csv")
        self.assertEqual(assets[0]["id"], "6a282739d9d7246402cb43de")


    def test_version_history_reconstructs_added_and_removed_files(self):
        payload = {"versions": [
            {"version": 1, "added": [{"fileName": "a.csv", "id": "a"}], "removed": []},
            {"version": 2, "added": [{"fileName": "b.csv", "id": "b"}],
             "removed": [{"fileName": "a.csv", "id": "a"}]},
        ]}
        assets = _history_assets(payload, "PSI-117")
        self.assertEqual([item["filename"] for item in assets], ["b.csv"])
        self.assertEqual(_metadata_version({"study": {"version": 4}}), 4)

    def test_download_candidates_include_opaque_id_and_basename(self):
        asset = {"study_id": "PSI-117", "id": "6a282739d9d7246402cb43de",
                 "filename": "camera.csv", "key": "PSI-117/Raw Data/camera.csv",
                 "version": 2, "study_version": 2}
        urls = _psi_download_candidates(asset)
        self.assertTrue(any("file=6a282739d9d7246402cb43de" in u for u in urls))
        self.assertTrue(any("file=camera.csv" in u for u in urls))


    def test_extracted_original_is_retained_for_user_download(self):
        with tempfile.TemporaryDirectory() as temp:
            asset = {"study_id": "PSI-117", "asset_id": "asset123", "filename": "readme.txt",
                     "category": "report", "download_status": "listed", "attempts": 0}
            session = {"workspace": temp, "study_id": "PSI-117", "assets": [asset],
                       "evidence": [], "downloaded_bytes": 0, "discovery": {"status": "complete"},
                       "capabilities": {}, "relationships": {"status": "not_indexed", "items": []}}
            def fake_download(item, folder, remaining, max_file_bytes=None):
                target = folder / "readme.txt"
                target.write_text("NASA PSI sample source file", encoding="utf-8")
                return ({**item, "download_status": "downloaded", "local_path": str(target)}, target.stat().st_size)
            with patch("app.session_service._download_asset", side_effect=fake_download):
                fetch_deferred_assets(session, ["report"], evidence_terms=[], max_candidates=1)
            saved = session["assets"][0]
            self.assertEqual(saved["download_status"], "downloaded_and_extracted")
            self.assertTrue(Path(saved["local_path"]).is_file())
            self.assertEqual(Path(saved["local_path"]).read_text(), "NASA PSI sample source file")

    def test_current_psi_repository_s3_host_is_allowlisted_exactly(self):
        signed = "https://psi-repo-prod.s3.amazonaws.com/psi-data/PSI-117/metadata/file.zip?versionId=v1&Signature=abc"
        self.assertTrue(is_allowed_psi_file_url(signed))
        self.assertTrue(is_allowed_psi_file_url("https://psi-repo-prod.s3.us-west-2.amazonaws.com/psi-data/PSI-204/raw/a.csv?X-Amz-Signature=x"))
        self.assertFalse(is_allowed_psi_file_url("https://some-other-bucket.s3.amazonaws.com/a.csv"))
        self.assertFalse(is_allowed_psi_file_url("http://psi-repo-prod.s3.amazonaws.com/a.csv"))

    def test_direct_signed_psi_repo_zip_downloads(self):
        signed = "https://psi-repo-prod.s3.amazonaws.com/psi-data/PSI-117/metadata/sample.zip?versionId=v1&Signature=abc&Expires=9999999999"
        asset = {"study_id": "PSI-117", "filename": "sample.zip", "url": signed, "category": "metadata"}
        with tempfile.TemporaryDirectory() as temp, patch(
            "app.session_service.urllib.request.urlopen",
            return_value=FakeResponse(b"PK\x03\x04fake-zip-payload", {"Content-Type": "application/zip"}, url=signed),
        ):
            result, size = _download_asset(asset, Path(temp), 1024 * 1024)
            self.assertEqual(result["download_status"], "downloaded")
            self.assertEqual(size, len(b"PK\x03\x04fake-zip-payload"))
            self.assertEqual(Path(result["local_path"]).read_bytes(), b"PK\x03\x04fake-zip-payload")

    def test_signed_psi_repo_zip_is_downloaded_and_csv_evidence_extracted(self):
        signed = "https://psi-repo-prod.s3.amazonaws.com/psi-data/PSI-117/metadata/sample.zip?versionId=v1&Signature=abc&Expires=9999999999"
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("metadata/measurements.csv", "time_s,oxygen_pct\n0,20.9\n1,20.8\n")
        payload = archive_bytes.getvalue()
        with tempfile.TemporaryDirectory() as temp:
            asset = {"study_id": "PSI-117", "asset_id": "zipasset", "filename": "sample.zip",
                     "url": signed, "category": "metadata", "download_status": "listed", "attempts": 0}
            session = {"workspace": temp, "study_id": "PSI-117", "assets": [asset], "evidence": [],
                       "downloaded_bytes": 0, "discovery": {"status": "complete"},
                       "capabilities": {}, "relationships": {"status": "not_indexed", "items": []}}
            with patch("app.session_service.urllib.request.urlopen",
                       return_value=FakeResponse(payload, {"Content-Type": "application/zip"}, url=signed)):
                loaded = fetch_deferred_assets(session, ["metadata"], evidence_terms=[], max_candidates=1)
            self.assertEqual(loaded, 1)
            self.assertEqual(session["assets"][0]["download_status"], "downloaded_and_extracted")
            self.assertTrue(any("oxygen_pct" in item.get("content", "") for item in session["evidence"]))
            self.assertTrue(any(item.get("archive_member", "").endswith("measurements.csv") for item in session["evidence"]))

    def test_expired_psi_signed_url_refreshes_manifest_once(self):
        old_url = "https://psi-repo-prod.s3.amazonaws.com/psi-data/PSI-117/metadata/sample.zip?Signature=expired"
        fresh_url = "https://psi-repo-prod.s3.amazonaws.com/psi-data/PSI-117/metadata/sample.zip?Signature=fresh"
        asset = {"study_id": "PSI-117", "filename": "sample.zip", "url": old_url, "category": "metadata"}
        calls = []
        def fake_urlopen(request, timeout=60):
            url = request.full_url
            calls.append(url)
            if url == old_url:
                raise __import__("urllib.error", fromlist=["HTTPError"]).HTTPError(url, 403, "ExpiredRequest", {}, None)
            if url == fresh_url:
                return FakeResponse(b"fresh archive bytes", {"Content-Type": "application/zip"}, url=fresh_url)
            raise AssertionError(f"Unexpected URL requested: {url}")
        with tempfile.TemporaryDirectory() as temp, \
             patch("app.session_service.urllib.request.urlopen", side_effect=fake_urlopen), \
             patch("app.session_service.discover_investigation_files", return_value={"assets": [{"filename": "sample.zip", "url": fresh_url}]}):
            result, size = _download_asset(asset, Path(temp), 1024 * 1024)
            self.assertEqual(result["download_status"], "downloaded")
            self.assertEqual(Path(result["local_path"]).read_bytes(), b"fresh archive bytes")
        self.assertEqual(calls[0], old_url)
        self.assertIn(fresh_url, calls)
        self.assertEqual(calls[-1], fresh_url)

    def test_plain_text_signed_s3_url_is_followed(self):
        asset = {"study_id": "PSI-117", "id": "opaque-id", "filename": "tiny.txt",
                 "version": 2, "study_version": 2}
        signed = "https://nasa-psi.s3.us-west-2.amazonaws.com/test/tiny.txt?signature=x"
        def fake_urlopen(request, timeout=60):
            url = request.full_url
            if "geode-py/ws/studies/" in url:
                return FakeResponse(signed.encode(), {"Content-Type": "text/plain"})
            return FakeResponse(b"actual file data", {"Content-Type": "text/plain"},
                                url=signed)
        with tempfile.TemporaryDirectory() as temp, patch("app.session_service.urllib.request.urlopen", side_effect=fake_urlopen):
            result, size = _download_asset(asset, Path(temp), 1024 * 1024)
            self.assertEqual(result["download_status"], "downloaded")
            self.assertEqual(size, len(b"actual file data"))
            self.assertEqual(Path(result["local_path"]).read_bytes(), b"actual file data")


if __name__ == "__main__":
    unittest.main()
