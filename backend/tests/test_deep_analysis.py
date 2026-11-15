"""Deep-analysis regression tests (no network, Groq is faked)."""
import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import analysis_service as svc


class FakeAPIError(Exception):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code, self.message = status_code, message


class ScriptedGroq:
    """chat.completions.create(**kw) replays a script of results/exceptions and records the calls."""
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        content, finish = step if isinstance(step, tuple) else (step, "stop")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish)])


def make_session(evidence=None, assets=None, record=None):
    return {
        "session_id": "PSI-117_abcdef123456", "study_id": "PSI-117", "created_at": time.time(), "workspace": "/tmp/none",
        "record": record if record is not None else {"study_id": "PSI-117", "title": "Test study", "objective": "Study flame spread in microgravity.", "approach": "Drop tower tests."},
        "discovery": {"status": "complete"}, "assets": assets or [], "capabilities": {},
        "evidence": evidence or [], "downloaded_bytes": 0,
    }


def report_chunks(n=30):
    return [{"filename": "PSI-117_report.txt", "category": "report", "status": "extracted", "page_number": i // 3 + 1,
             "chunk_index": i, "source": "local report", "content": ("Smoke aerosol particle diameter measured at 2.5 um. " if i % 4 == 0 else "Flame spread rate depends on oxygen concentration. ") * 60}
            for i in range(n)]


class RoutingTests(unittest.TestCase):
    def test_explain_with_fire_safety_words_is_an_overview(self):
        route, _ = svc.classify_question("Explain this investigation in depth. Summarize its objective, approach, available evidence, major findings, limitations, and potential relevance to spacecraft fire safety.")
        self.assertEqual(route["intent"], "overview")

    def test_show_me_is_not_a_visual_question(self):
        self.assertNotEqual(svc.classify_question("Show me the main findings")[0]["intent"], "visual_analysis")

    def test_real_visual_and_numeric_and_comparison(self):
        self.assertEqual(svc.classify_question("What videos or images exist?")[0]["intent"], "visual_analysis")
        self.assertEqual(svc.classify_question("What was the maximum temperature measured?")[0]["intent"], "experimental_analysis")
        self.assertEqual(svc.classify_question("Compare this with PSI-69")[0]["intent"], "comparison")
        self.assertEqual(svc.classify_question("How does fire suppression work here?")[0]["intent"], "safety_insights")


class RetrievalTests(unittest.TestCase):
    def test_diversify_is_defined_and_uses_whole_budget_for_single_document(self):
        ranked = svc._score_evidence("smoke particle", {"evidence_terms": ["smoke", "particle"], "preferred_categories": ["report"]}, report_chunks())
        picked = svc._diversify_evidence(ranked, limit=16, per_file=3)
        self.assertEqual(len(picked), 16)  # one file, but 16 slots are still filled
        smoke_total = sum(1 for c in report_chunks() if "smoke" in c["content"].casefold())
        self.assertEqual(sum(1 for p in picked if "smoke" in p["content"].casefold()), smoke_total)  # every relevant chunk is kept

    def test_diversify_spreads_across_files(self):
        ev = report_chunks(10) + [{"filename": "data.csv", "category": "experimental_data", "status": "extracted", "columns": ["t"], "content": "Columns: t smoke"}]
        ranked = svc._score_evidence("smoke", {"evidence_terms": ["smoke"], "preferred_categories": ["experimental_data"]}, ev)
        picked = svc._diversify_evidence(ranked, limit=5, per_file=2)
        self.assertIn("data.csv", [p["filename"] for p in picked])


class AnswerTests(unittest.TestCase):
    def run_answer(self, script, session=None, question="What does the report say about smoke?", env=None):
        client = ScriptedGroq(script)
        with patch.object(svc, "_groq_client", return_value=client), patch.dict(os.environ, {"GROQ_API_KEY": "x", **(env or {})}):
            with patch("app.session_service.session_summary", return_value={"ok": True}):
                result = svc.answer_from_session(question, session or make_session(evidence=report_chunks()))
        return result, client

    def test_normal_answer_converts_citations(self):
        result, client = self.run_answer(["Smoke diameter was 2.5 um [E1, E2]."])
        self.assertEqual(result["analysis_mode"], "groq_deep_file_analysis")
        self.assertIn("PSI-117_report.txt", result["answer"])
        self.assertNotIn("[E1", result["answer"])
        self.assertEqual(client.calls[0]["model"], "openai/gpt-oss-20b")
        self.assertEqual(client.calls[0]["reasoning_effort"], "low")

    def test_413_request_too_large_retries_with_smaller_evidence(self):
        too_big = FakeAPIError(413, "Request too large for model `openai/gpt-oss-20b` on tokens per minute (TPM): Limit 8000, Requested 12000, please reduce your message size")
        result, client = self.run_answer([too_big, "Answer [E1]."])
        self.assertEqual(result["analysis_mode"], "groq_deep_file_analysis")
        first, second = (len(c["messages"][-1]["content"]) for c in client.calls)
        self.assertLess(second, first)

    def test_rate_limit_falls_back_to_next_model(self):
        limited = FakeAPIError(429, "Rate limit reached for model `openai/gpt-oss-20b` on tokens per minute (TPM): Limit 8000, Used 7900, Requested 3000. Please try again in 40s.")
        result, client = self.run_answer([limited, "Fallback model answer [E1]."])
        self.assertEqual(result["analysis_model"], "llama-3.3-70b-versatile")
        self.assertNotIn("reasoning_effort", client.calls[1])  # reasoning params only for gpt-oss

    def test_old_sdk_typeerror_drops_optional_params(self):
        result, client = self.run_answer([TypeError("create() got an unexpected keyword argument 'include_reasoning'"), "Works [E1]."])
        self.assertEqual(result["analysis_mode"], "groq_deep_file_analysis")
        self.assertNotIn("include_reasoning", client.calls[1])

    def test_empty_content_retries_with_more_tokens(self):
        result, client = self.run_answer([("", "length"), "Now it answers [E1]."])
        self.assertIn("answers", result["answer"])
        self.assertGreater(client.calls[1]["max_completion_tokens"], client.calls[0]["max_completion_tokens"])

    def test_total_failure_returns_preview_not_http_500(self):
        err = FakeAPIError(500, "boom")
        result, _ = self.run_answer([err, err, err])
        self.assertEqual(result["analysis_mode"], "evidence_preview_fallback")
        self.assertIn("evidence preview", result["answer"])
        self.assertIn("llm_error", result)

    def test_missing_key_is_explained(self):
        with patch.object(svc, "_groq_client", return_value=None), patch("app.session_service.session_summary", return_value={}):
            result = svc.answer_from_session("hi?", make_session(evidence=report_chunks()))
        self.assertEqual(result["analysis_mode"], "evidence_preview_fallback")
        self.assertIn("GROQ_API_KEY", result["answer"])

    def test_metadata_only_session_still_gets_an_llm_answer(self):
        result, client = self.run_answer(["From the catalogue metadata [Metadata]: flame spread."], session=make_session(evidence=[]))
        self.assertEqual(result["analysis_mode"], "groq_metadata_analysis")
        self.assertIn("No file text could be extracted", client.calls[0]["messages"][-1]["content"])

    def test_no_evidence_and_no_metadata_does_not_call_llm(self):
        result, client = self.run_answer([], session=make_session(evidence=[], record={}))
        self.assertEqual(result["analysis_mode"], "no_evidence")
        self.assertEqual(client.calls, [])

    def test_show_question_with_text_evidence_is_answered_not_refused(self):
        result, _ = self.run_answer(["Findings [E1]."], question="Show me the key results")
        self.assertEqual(result["analysis_mode"], "groq_deep_file_analysis")


if __name__ == "__main__":
    unittest.main()
