"""Discovery + download must work for any PSI study, not only PSI-117.

NASA is simulated: each fake study has its own study version, folder layout and
download behaviour, mirroring the ways PSI-117 differs from other studies.
"""
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from app.psi_discovery import discover_psi_v2, is_allowed_psi_file_url, _flatten_psi_v2, _empty_folder_keys
from app.session_service import _psi_download_candidates, _download_asset


class FakeResponse:
    def __init__(self, body: bytes, url: str, content_type="application/octet-stream"):
        self.body, self.url, self.offset, self.status = body, url, 0, 200
        self.headers = {"Content-Type": content_type, "Content-Length": str(len(body))}
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def geturl(self): return self.url
    def read(self, n=-1):
        if n is None or n < 0: n = len(self.body) - self.offset
        chunk = self.body[self.offset:self.offset + n]; self.offset += len(chunk); return chunk


def http_error(url, code, body=b'{"error":"nope"}'):
    return urllib.error.HTTPError(url, code, "Err", {}, io.BytesIO(body))


def leaf(study, folder, name, fid):
    return {"id": fid, "key": f"psi-data/{study}/{folder}/{name}", "directory": False, "files": [], "bytes_size": 40}


class FakeNasa:
    """PSI-117: study v2, fully nested manifest, download by filename.
    PSI-100: study v4, lazy folders, filename route returns the SPA page, opaque-id route needs studyVersion=4,
             signed URL is on the PSI bucket under a non-"psi-data" key.
    """
    FILES_URL = "https://psi.nasa.gov/geode-py/ws/files/v2"
    SIGNED = "https://psi-repo-prod.s3.us-west-2.amazonaws.com/PSI-100/raw/run1.csv?X-Amz-Signature=abc"

    def __init__(self):
        self.calls = []

    def __call__(self, request, timeout=None):
        url = request if isinstance(request, str) else request.full_url
        self.calls.append(url)
        if url == self.FILES_URL:
            return self.files(json.loads(request.data.decode()))
        if "/geode-py/ws/studies/PSI-117/download" in url:
            if "source=datamanager" in url and "file=ops.csv" in url:
                return FakeResponse(b"a,b\n1,2\n", url)
            raise http_error(url, 404)
        if "/geode-py/ws/studies/PSI-100/download" in url:
            if "source=datamanager" in url:
                return FakeResponse(b"<!doctype html><html><body>PSI app</body></html>", url, "text/html")
            if "studyVersion=4" in url and "redirect=false" in url:
                return FakeResponse(json.dumps({"downloadUrl": self.SIGNED}).encode(), url, "application/octet-stream")
            raise http_error(url, 404)
        if url == self.SIGNED:
            return FakeResponse(b"t,v\n0,1\n1,2\n", url)
        raise http_error(url, 404)

    def files(self, payload):
        study, folder, version = payload["studyId"], payload["folder"], payload.get("version")
        if study == "PSI-117":
            if version != 2:
                return FakeResponse(json.dumps({"files": []}).encode(), self.FILES_URL)
            tree = {"files": [{"key": "psi-data/PSI-117/Raw Data/", "files": [leaf("PSI-117", "Raw Data", "ops.csv", "id117a")]}]}
            return FakeResponse(json.dumps(tree).encode(), self.FILES_URL)
        if study == "PSI-100":
            if version != 4:
                return FakeResponse(json.dumps({"files": []}).encode(), self.FILES_URL)
            if folder == "PSI-100/":
                return FakeResponse(json.dumps({"files": [{"key": "psi-data/PSI-100/Raw Data/", "files": []},
                                                          {"key": "psi-data/PSI-100/Science Documents/", "files": []}]}).encode(), self.FILES_URL)
            if folder == "PSI-100/Raw Data/":      # only the stripped variant is understood
                return FakeResponse(json.dumps({"files": [leaf("PSI-100", "Raw Data", "run1.csv", "id100a"),
                                                          leaf("PSI-100", "Raw Data", "run2.csv", "id100b")]}).encode(), self.FILES_URL)
            if folder == "PSI-100/Science Documents/":
                return FakeResponse(json.dumps({"files": [leaf("PSI-100", "Science Documents", "paper.pdf", "id100c")]}).encode(), self.FILES_URL)
            raise http_error(self.FILES_URL, 400)
        return FakeResponse(json.dumps({"files": []}).encode(), self.FILES_URL)


class MultiStudyTests(unittest.TestCase):
    def test_psi_117_still_works(self):
        with patch("urllib.request.urlopen", new=FakeNasa()):
            result = discover_psi_v2("PSI-117")
            self.assertEqual(result["status"], "complete")
            self.assertEqual([a["filename"] for a in result["assets"]], ["ops.csv"])
            self.assertEqual(result["study_version"], 2)
            asset = {**result["assets"][0], "study_id": "PSI-117"}
            with tempfile.TemporaryDirectory() as tmp:
                out, size = _download_asset(asset, Path(tmp), 10_000_000)
            self.assertEqual(out["download_status"], "downloaded")

    def test_study_with_other_version_and_lazy_folders_is_discovered(self):
        with patch("urllib.request.urlopen", new=FakeNasa()):
            result = discover_psi_v2("PSI-100")
        self.assertEqual(result["status"], "complete", result.get("message"))
        self.assertEqual(sorted(a["filename"] for a in result["assets"]), ["paper.pdf", "run1.csv", "run2.csv"])
        self.assertEqual(result["study_version"], 4)
        self.assertEqual(result["probe"]["4"], 0)  # top level lists folders only
        self.assertTrue(all(a["study_version"] == 4 for a in result["assets"]))
        self.assertIn(4, result["assets"][0]["study_version_candidates"])

    def test_download_uses_discovered_study_version_and_trusted_signed_url(self):
        fake = FakeNasa()
        with patch("urllib.request.urlopen", new=fake):
            asset = next(a for a in discover_psi_v2("PSI-100")["assets"] if a["filename"] == "run1.csv")
            asset = {**asset, "study_id": "PSI-100"}
            with tempfile.TemporaryDirectory() as tmp:
                out, size = _download_asset(asset, Path(tmp), 10_000_000)
                self.assertEqual(out["download_status"], "downloaded", out.get("download_error"))
                self.assertEqual(Path(out["local_path"]).read_bytes(), b"t,v\n0,1\n1,2\n")
        # The SPA-HTML datamanager route was rejected and the studyVersion=4 route used.
        self.assertTrue(any("studyVersion=4" in c for c in fake.calls))

    def test_candidates_cover_discovered_versions_not_only_two(self):
        urls = _psi_download_candidates({"study_id": "PSI-55", "id": "abc", "filename": "f.csv",
                                         "study_version": 6, "study_version_candidates": [6, 5]})
        joined = "\n".join(urls)
        self.assertIn("studyVersion=6", joined)
        self.assertIn("studyVersion=5", joined)
        self.assertLessEqual(len(urls), 16)

    def test_relative_key_is_tried_as_file_name(self):
        urls = _psi_download_candidates({"study_id": "PSI-55", "filename": "f.csv", "key": "psi-data/PSI-55/Raw Data/f.csv"})
        self.assertTrue(any("file=Raw+Data%2Ff.csv" in u for u in urls))

    def test_trusted_urls_accept_any_key_in_psi_bucket_but_strict_mode_does_not(self):
        url = "https://psi-repo-prod.s3.us-west-2.amazonaws.com/PSI-100/raw/run1.csv?sig=1"
        self.assertTrue(is_allowed_psi_file_url(url, trusted=True))
        self.assertFalse(is_allowed_psi_file_url(url))
        self.assertFalse(is_allowed_psi_file_url("https://evil.example.com/psi-data/PSI-1/a.csv", trusted=True))
        self.assertFalse(is_allowed_psi_file_url("http://psi-repo-prod.s3.amazonaws.com/a.csv", trusted=True))

    def test_folder_with_dot_in_name_is_not_mistaken_for_a_file(self):
        tree = {"files": [{"key": "psi-data/PSI-9/Run 1.2/", "files": []}]}
        self.assertEqual(_flatten_psi_v2(tree), [])
        self.assertEqual(_empty_folder_keys(tree), ["psi-data/PSI-9/Run 1.2/"])

    def test_error_details_reach_the_ui(self):
        def always_404(request, timeout=None):
            raise http_error(request.full_url, 404, b'{"message":"file not registered"}')
        asset = {"study_id": "PSI-77", "id": "x", "filename": "f.csv", "study_version": 3}
        with patch("urllib.request.urlopen", side_effect=always_404), tempfile.TemporaryDirectory() as tmp:
            out, _ = _download_asset(asset, Path(tmp), 1_000_000)
        self.assertEqual(out["download_status"], "not_found")
        self.assertIn("file not registered", out["download_error"])


if __name__ == "__main__":
    unittest.main()
