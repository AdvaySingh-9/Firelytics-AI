"""Offline smoke tests for the temporary deep-analysis layer."""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

from app.analysis_service import classify_question, _score_evidence
from app.session_service import (_derive_capabilities, _persist_session, _extract_file,
    fetch_deferred_assets, session_summary, _psi_download_candidates, ingest_session_batch)
from app.psi_discovery import _flatten_psi_v2


class TemporaryAnalysisTests(unittest.TestCase):
    def test_psi_human_readable_sizes_are_parsed_without_crashing(self):
        from app.session_service import _size_bytes
        self.assertEqual(_size_bytes("0B"), 0)
        self.assertEqual(_size_bytes("12KB"), 12_000)
        self.assertEqual(_size_bytes("1.5MB"), 1_500_000)
        self.assertEqual(_size_bytes("2 MiB"), 2 * 1024 * 1024)
        self.assertEqual(_size_bytes("8384"), 8384)
        self.assertEqual(_size_bytes("unknown"), 0)

    def test_manifest_leaf_aliases_are_preserved_as_downloadable_assets(self):
        assets = _flatten_psi_v2([{
            "file_name": "measurements.csv",
            "remote_url": "/geode-py/ws/files/download?id=abc",
            "file_size": 1234,
            "category": "Experimental Data",
            "id": "abc",
        }])
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["filename"], "measurements.csv")
        self.assertEqual(assets[0]["bytes_size"], 1234)
        self.assertEqual(assets[0]["download_url"], "/geode-py/ws/files/download?id=abc")
        candidates = _psi_download_candidates(assets[0])
        self.assertEqual(candidates[0], "https://psi.nasa.gov/geode-py/ws/files/download?id=abc")

    def test_manifest_relative_download_url_without_leading_slash_is_resolved(self):
        candidates = _psi_download_candidates({
            "filename": "data.csv",
            "remote_url": "geode-py/ws/files/download?id=abc",
        })
        self.assertEqual(candidates[0], "https://psi.nasa.gov/geode-py/ws/files/download?id=abc")

    def test_gzip_text_payload_is_extracted(self):
        import gzip
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "measurements.txt.gz"
            with gzip.open(path, "wb") as stream:
                stream.write(b"time,temperature\\n0,21.5\\n1,22.0\\n")
            result = _extract_file(path)
            self.assertEqual(result["status"], "extracted")
            self.assertIn("temperature", result["content"])

    def test_report_listing_does_not_prove_safety_evidence(self):
        assets = [{"filename": "generic_report.pdf", "category": "report", "download_status": "listed"}]
        evidence = [{"filename": "generic_report.pdf", "category": "report", "status": "extracted", "content": "This investigation describes an experiment and its methodology."}]
        capabilities = _derive_capabilities(assets, evidence, "complete")
        self.assertEqual(capabilities["safety_insights"]["status"], "partial")
        self.assertEqual(capabilities["investigation_explanation"]["status"], "available")

    def test_extracted_smoke_evidence_can_support_safety_capability(self):
        evidence = [{"filename": "smoke_report.pdf", "category": "report", "status": "extracted", "content": "Smoke aerosol measurements were recorded during combustion."}]
        capabilities = _derive_capabilities([], evidence, "complete")
        self.assertEqual(capabilities["safety_insights"]["status"], "available")

    def test_question_classifier_routes_numeric_smoke_question(self):
        route, _ = classify_question("What experimental data is available about smoke particle size distribution?")
        self.assertEqual(route["intent"], "experimental_analysis")
        self.assertIn("smoke", route["evidence_terms"])

    def test_question_routing_is_fast_and_does_not_require_a_second_llm_call(self):
        route, mode = classify_question("Explain this investigation's experimental approach")
        self.assertEqual(route["intent"], "overview")
        self.assertEqual(mode, "local_fast_router")

    def test_download_endpoint_generation_is_not_hardcoded_to_psi_117(self):
        from urllib.parse import urlparse, parse_qs
        candidates = _psi_download_candidates({"study_id": "PSI-204", "filename": "results.csv", "id": "abc204"})
        self.assertTrue(candidates)
        self.assertTrue(all("PSI-204" in url for url in candidates))
        self.assertEqual(parse_qs(urlparse(candidates[0]).query).get("file"), ["results.csv"])

    def test_manifest_relevance_prefers_matching_dataset(self):
        ranked = _score_evidence(
            "smoke particle size",
            {"evidence_terms": ["smoke", "particle", "size"], "preferred_categories": ["experimental_data"]},
            [
                {"filename": "unrelated.txt", "category": "report", "status": "extracted", "content": "general overview"},
                {"filename": "smoke_particle_size.csv", "category": "experimental_data", "status": "extracted", "content": "particle diameter measurements"},
            ],
        )
        self.assertEqual(ranked[0]["filename"], "smoke_particle_size.csv")

    def test_csv_schema_keeps_only_explicit_units(self):
        folder = Path(tempfile.mkdtemp())
        path = folder / "measurements.csv"
        path.write_text("Time (s),Diameter (um)\n0,1.2\n1,1.5\n", encoding="utf-8")
        result = _extract_file(path)
        self.assertEqual(result["status"], "extracted")
        self.assertEqual(result["column_schema"][0]["unit"], "s")
        self.assertIsNone(result["column_schema"][0]["description"])

    def test_temporary_tables_are_written_outside_sqlite(self):
        workspace = Path(tempfile.mkdtemp())
        session = {
            "workspace": str(workspace),
            "assets": [],
            "evidence": [],
            "capabilities": {"safety_insights": {"status": "not_indexed"}},
            "relationships": {"status": "not_indexed", "items": []},
            "downloaded_bytes": 0,
            "created_at": 1,
            "session_id": "PSI-101_123456789abc",
            "study_id": "PSI-101",
            "record": {},
            "discovery": {"status": "complete"},
        }
        _persist_session(session)
        for name in ("assets.json", "capabilities.json", "datasets.json", "document_chunks.jsonl", "relationships.json", "processing.json", "session.json"):
            self.assertTrue((workspace / name).exists(), name)


    def test_manifest_download_url_relative_is_resolved_to_nasa(self):
        candidates = _psi_download_candidates({
            "filename": "dataset.csv",
            "url": "/geode-py/ws/files/download?id=abc123",
        })
        self.assertEqual(candidates[0], "https://psi.nasa.gov/geode-py/ws/files/download?id=abc123")

    def test_manifest_key_is_not_guessed_into_a_public_s3_url(self):
        candidates = _psi_download_candidates({
            "filename": "a file.csv",
            "key": "psi-data/PSI-117/Raw Data/a file.csv",
        })
        self.assertEqual(candidates, [])

    def test_psi_manifest_file_id_alias_and_study_version_are_used(self):
        from urllib.parse import urlparse, parse_qs
        assets = _flatten_psi_v2([{
            "file_name": "ops.pdf", "file_id": "6a282739d9d7246402cb43de",
            "file_version": 2, "study_version": 2, "file_size": 2048,
        }])
        self.assertEqual(assets[0]["id"], "6a282739d9d7246402cb43de")
        self.assertEqual(assets[0]["study_version"], 2)
        candidates = _psi_download_candidates({**assets[0], "study_id": "PSI-117"})
        self.assertGreaterEqual(len(candidates), 3)
        # Published PSI/Geode route resolves data-manager files by filename first.
        parsed = urlparse(candidates[0])
        self.assertEqual(parse_qs(parsed.query)["file"], ["ops.pdf"])
        self.assertEqual(parse_qs(parsed.query)["source"], ["datamanager"])
        self.assertTrue(any(parse_qs(urlparse(u).query).get("file") == ["6a282739d9d7246402cb43de"] for u in candidates))


    def test_geode_json_envelope_is_followed_even_with_octet_stream_content_type(self):
        import io, json
        from unittest.mock import patch
        from app.session_service import _download_asset
        class FakeResponse:
            def __init__(self, body, url, content_type):
                self.stream = io.BytesIO(body)
                self.headers = {"Content-Type": content_type}
                self.url = url
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, size=-1): return self.stream.read(size)
            def geturl(self): return self.url
        geode = "https://psi.nasa.gov/geode-py/ws/studies/PSI-117/download?file=abc&version=2&studyVersion=2&redirect=false"
        signed = "https://nasa-psi.s3.us-west-2.amazonaws.com/PSI-117/data.csv?signature=ok"
        responses = [
            FakeResponse(json.dumps({"downloadUrl": signed}).encode(), geode, "application/octet-stream"),
            FakeResponse(b"a,b\n1,2\n", signed, "application/octet-stream"),
        ]
        with tempfile.TemporaryDirectory() as directory, patch("app.session_service.urllib.request.urlopen", side_effect=responses):
            result, size = _download_asset({"study_id":"PSI-117", "id":"abc", "filename":"data.csv", "version":2, "study_version":2}, Path(directory), 10000, 10000)
            self.assertEqual(result["download_status"], "downloaded")
            self.assertEqual(size, 8)
            self.assertTrue(Path(result["local_path"]).exists())

    def test_manifest_file_id_uses_study_download_endpoint_and_versions(self):
        from urllib.parse import urlparse, parse_qs
        candidates = _psi_download_candidates({
            "study_id": "PSI-117", "id": "6a282739d9d7246402cb43de",
            "filename": "data.csv", "version": 2, "study_version": 2,
        })
        self.assertGreaterEqual(len(candidates), 3)
        parsed = urlparse(candidates[0])
        self.assertEqual(parsed.path, "/geode-py/ws/studies/PSI-117/download")
        self.assertEqual(parse_qs(parsed.query), {"source": ["datamanager"], "file": ["data.csv"]})
        self.assertTrue(any(parse_qs(urlparse(u).query).get("file") == ["6a282739d9d7246402cb43de"] and parse_qs(urlparse(u).query).get("redirect") == ["false"] for u in candidates))

    def test_manifest_without_direct_url_uses_nasa_geode_study_download_route(self):
        candidates = _psi_download_candidates({
            "study_id": "PSI-100", "filename": "SAFFIRE-III Update Log Final.pdf",
            "key": "psi-data/PSI-100/Raw Data/SAFFIRE-III Update Log Final.pdf",
        })
        self.assertTrue(candidates)
        self.assertTrue(candidates[0].startswith("https://psi.nasa.gov/geode-py/ws/studies/PSI-100/download?"))
        self.assertIn("file=SAFFIRE-III+Update+Log+Final.pdf", candidates[0])

    def test_verified_download_template_can_use_manifest_id_and_key(self):
        with patch.dict(os.environ, {"PSI_DOWNLOAD_URL_TEMPLATE": "/geode-py/ws/files/{id}/download?key={key}"}):
            candidates = _psi_download_candidates({
                "id": "abc123", "filename": "a file.csv",
                "key": "psi-data/PSI-117/Raw Data/a file.csv",
            })
        self.assertEqual(
            candidates[0],
            "https://psi.nasa.gov/geode-py/ws/files/abc123/download?key=psi-data/PSI-117/Raw%20Data/a%20file.csv",
        )

    def test_psi_manifest_flattens_arbitrary_nested_folder_structure(self):
        tree = [{
            "displayName": "Analyzed Data",
            "key": "psi-data/PSI-117/Analyzed Data/",
            "files": [{
                "displayName": "Reduced Gravity",
                "key": "psi-data/PSI-117/Analyzed Data/Reduced Gravity/",
                "files": [{
                    "displayName": "Simulation",
                    "key": "psi-data/PSI-117/Analyzed Data/Reduced Gravity/Simulation/",
                    "files": [{
                        "directory": False, "files": [], "id": "abc123",
                        "key": "psi-data/PSI-117/Analyzed Data/Reduced Gravity/Simulation/result.csv",
                        "bytes_size": 1234, "sortingCategory": "PROC1",
                    }],
                }],
            }],
        }]
        assets = _flatten_psi_v2(tree)
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["category"], "analyzed_data")
        self.assertEqual(assets[0]["id"], "abc123")
        self.assertEqual(assets[0]["bytes_size"], 1234)

    def test_failed_downloads_are_bounded_by_candidate_attempt_limit(self):
        workspace = Path(tempfile.mkdtemp())
        assets = [
            {"filename": f"report_{i}.pdf", "category": "report", "key": f"psi-data/PSI-1/report_{i}.pdf",
             "download_status": "listed", "asset_id": str(i)}
            for i in range(30)
        ]
        session = {
            "workspace": str(workspace), "assets": assets, "evidence": [],
            "capabilities": {}, "relationships": {"status": "not_indexed", "items": []},
            "downloaded_bytes": 0, "created_at": 1, "session_id": "PSI-1_123456789abc",
            "study_id": "PSI-1", "record": {}, "discovery": {"status": "complete"},
        }
        with patch("app.session_service._download_asset", side_effect=lambda a, *_: ({**a, "download_status": "download_failed"}, 0)) as mocked:
            fetch_deferred_assets(session, ["report"], ["PSI-1", "the", "investigation"], max_candidates=4)
        self.assertEqual(mocked.call_count, 4)
        self.assertTrue(all(a["attempts"] == 1 for a in session["assets"][:4]))

    def test_full_ingestion_uses_all_categories_and_bounded_batches(self):
        workspace = Path(tempfile.mkdtemp())
        session = {
            "workspace": str(workspace), "study_id": "PSI-100",
            "assets": [{"filename": "a.pdf", "category": "raw_data", "download_status": "listed", "attempts": 0},
                       {"filename": "b.xlsx", "category": "experimental_data", "download_status": "listed", "attempts": 0}],
            "evidence": [], "capabilities": {}, "relationships": {"status": "not_indexed", "items": []},
            "downloaded_bytes": 0, "created_at": 1, "session_id": "PSI-100_123456789abc",
            "record": {}, "discovery": {"status": "complete"},
        }
        with patch("app.session_service.fetch_deferred_assets", return_value=1) as fetch:
            result = ingest_session_batch(session, batch_size=50)
        self.assertEqual(fetch.call_args.args[1], ["experimental_data", "raw_data"])
        self.assertEqual(fetch.call_args.kwargs["max_candidates"], 20)
        self.assertEqual(result["extracted_this_batch"], 1)

    def test_session_summary_returns_manifest_preview_not_all_23k_assets(self):
        assets = [{"filename": f"file_{i}.csv", "category": "experimental_data", "download_status": "listed"} for i in range(23466)]
        data = {
            "session_id": "PSI-1_123456789abc", "study_id": "PSI-1", "record": {},
            "discovery": {"status": "complete", "message": "ok", "source_url": "https://psi.nasa.gov/"},
            "assets": assets, "capabilities": {}, "evidence": [], "downloaded_bytes": 0,
            "created_at": 1, "workspace": tempfile.mkdtemp(),
        }
        summary = session_summary(data)
        self.assertEqual(summary["listed_file_count"], 23466)
        self.assertEqual(len(summary["assets"]), 100)
        self.assertTrue(summary["assets_truncated"])
        self.assertEqual(summary["asset_categories"], ["experimental_data"])


    def test_metadata_objective_question_is_synthesized_by_120b_without_manifest(self):
        from app.session_service import create_session, get_session, delete_session
        from app.analysis_service import answer_from_session
        class FakeCompletions:
            def __init__(self): self.calls = []
            def create(self, **kwargs):
                self.calls.append(kwargs)
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="The objective is to measure microgravity smoke-particle sizes and use those measurements to support a predictive droplet-growth model."))])
        fake = FakeCompletions()
        fake.chat = SimpleNamespace(completions=fake)
        session_summary = create_session("PSI-102")
        try:
            self.assertEqual(session_summary["discovery_status"], "metadata_only")
            self.assertEqual(session_summary["listed_file_count"], 0)
            session = get_session(session_summary["session_id"])
            with patch("app.analysis_service._groq_client", return_value=fake):
                result = answer_from_session("what is objective", session)
            self.assertEqual(result["analysis_mode"], "groq_metadata_analysis")
            self.assertIn("measure microgravity smoke-particle sizes", result["answer"])
            self.assertEqual(fake.calls[0]["model"], "openai/gpt-oss-120b")
        finally:
            delete_session(session_summary["session_id"])

    def test_uploaded_dataset_analysis_uses_120b_and_only_matching_session_file(self):
        from app.session_service import create_session, get_session, delete_session
        from app.analysis_service import analyze_uploaded_dataset
        class FakeCompletions:
            def __init__(self): self.calls = []
            def create(self, **kwargs):
                self.calls.append(kwargs)
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="The uploaded table contains smoke particle measurements. The file does not state a validated detector threshold."))])
        fake = FakeCompletions()
        fake.chat = SimpleNamespace(completions=fake)
        created = create_session("PSI-102")
        try:
            session = get_session(created["session_id"])
            upload = {
                "__filename__": "same_measurements.csv",
                "__file_text__": "Particle diameter (um),Time (s)\\n1.2,0\\n1.5,1",
                "__columns__": ["Particle diameter (um)", "Time (s)"],
                "__study_id__": session["study_id"],
                "__session_id__": session["session_id"],
            }
            with patch("app.analysis_service._groq_client", return_value=fake):
                result = analyze_uploaded_dataset(session, "Analyze the uploaded measurements", [upload])
            self.assertEqual(result["mode"], "groq_120b_uploaded_dataset_analysis")
            self.assertEqual(fake.calls[0]["model"], "openai/gpt-oss-120b")
            self.assertIn("same_measurements.csv", fake.calls[0]["messages"][1]["content"])
        finally:
            delete_session(created["session_id"])

    def test_upload_from_another_study_is_never_sent_to_120b(self):
        from app.session_service import create_session, get_session, delete_session
        from app.analysis_service import answer_from_session
        class FakeCompletions:
            def __init__(self): self.calls = []
            def create(self, **kwargs):
                self.calls.append(kwargs)
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="I could not find that detail in the selected investigation metadata."))])
        fake = FakeCompletions()
        fake.chat = SimpleNamespace(completions=fake)
        created = create_session("PSI-102")
        try:
            session = get_session(created["session_id"])
            foreign_upload = {
                "__filename__": "psi-101-secret-results.csv",
                "__file_text__": "FOREIGN_STUDY_UNIQUE_MEASUREMENT 98765",
                "__study_id__": "PSI-101",
                "__session_id__": "PSI-101_aaaaaaaaaaaa",
            }
            with patch("app.analysis_service._groq_client", return_value=fake):
                result = answer_from_session("summarize the uploaded experiment", session, uploaded_data=[foreign_upload])
            self.assertEqual(result["analysis_mode"], "upload_scope_mismatch")
            self.assertIn("not attached to the active PSI-102", result["answer"])
            self.assertEqual(fake.calls, [])
        finally:
            delete_session(created["session_id"])

    def test_uploaded_file_extraction_includes_text_for_llm_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "same_report.txt"
            path.write_text("Smoke particle size measurements were collected in microgravity.", encoding="utf-8")
            extracted = _extract_file(path)
            self.assertEqual(extracted["status"], "extracted")
            self.assertIn("Smoke particle size", extracted["content"])


    def test_unmatched_uploaded_file_question_reports_missing_relevant_data(self):
        from app.session_service import create_session, get_session, delete_session
        from app.analysis_service import answer_from_session
        session_summary = create_session("PSI-102")
        try:
            session = get_session(session_summary["session_id"])
            result = answer_from_session(
                "what does the uploaded report say about radiation shielding?",
                session,
                uploaded_data=[{"__filename__": "smoke.txt", "__file_text__": "Smoke particle size measurements were collected in microgravity.", "__study_id__": session["study_id"], "__session_id__": session["session_id"]}],
            )
            self.assertEqual(result["analysis_mode"], "uploaded_data_not_relevant")
            self.assertIn("I could not find relevant data", result["answer"])
        finally:
            delete_session(session_summary["session_id"])

if __name__ == "__main__":
    unittest.main()
