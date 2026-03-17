"""Tests for core.agency.eval — Eval Harness Agent (Phase 7b Module 4)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from core.interface.models import (
    ANSWER_RELEVANCE_NUMERIC,
    AnswerRelevance,
    CompiledContext,
    ContextSlice,
    EvalResult,
    EvalVerdict,
    FragmentMeta,
    MemoryTier,
)


# ── Mock Data ─────────────────────────────────────────────────────────

_MOCK_JUDGE_RESPONSE_PASS = json.dumps({
    "context_precision": {"score": 0.9, "tier_mismatch": False},
    "context_recall": {"score": 0.85},
    "answer_relevance": {"score": "DIRECT", "reasoning": "Directly answers the query"},
    "overall_score": 0.86,
})

_MOCK_JUDGE_RESPONSE_MARGINAL = json.dumps({
    "context_precision": {"score": 0.5, "tier_mismatch": True},
    "context_recall": {"score": 0.6},
    "answer_relevance": {"score": "PARTIAL", "reasoning": "Partially addresses query"},
    "overall_score": 0.56,
})

_MOCK_JUDGE_RESPONSE_FAIL = json.dumps({
    "context_precision": {"score": 0.2, "tier_mismatch": True},
    "context_recall": {"score": 0.1},
    "answer_relevance": {"score": "IRRELEVANT", "reasoning": "Does not address query"},
    "overall_score": 0.11,
})

_MOCK_JUDGE_RESPONSE_FLAT = json.dumps({
    "context_precision": 0.75,
    "context_recall": 0.80,
    "answer_relevance": "DIRECT",
    "overall_score": 0.78,
})


def _compiled_ctx(tier: str = "semantic") -> CompiledContext:
    """Build a minimal CompiledContext for testing."""
    return CompiledContext(
        query="test query",
        slices=[
            ContextSlice(
                name=tier,
                tier=MemoryTier(tier) if tier in [t.value for t in MemoryTier] else MemoryTier.SEMANTIC,
                fragments=["Fragment about OIKOS architecture and memory."],
                fragment_meta=[FragmentMeta(source_path=f"vault/knowledge/test.md", header_path="Test > Section")],
                token_count=50,
                max_tokens=500,
            )
        ],
        total_tokens=50,
        budget=6000,
    )


def _mock_generate(response_text: str):
    """Return a mock for generate_local that returns the given text."""
    return lambda prompt, model=None, **kw: {"response": response_text}


# ── Import Module Under Test ─────────────────────────────────────────

from core.agency.eval import (
    EVAL_QUERIES,
    _build_judge_prompt,
    _build_summary,
    _check_identity_leak,
    _compute_overall,
    _extract_chunks_metadata,
    _load_fabric_prompt,
    _parse_judge_response,
    _sample_interactions,
    _score_to_verdict,
    run_eval,
    validate_cross_model,
)


# ── Tests: Query Corpus ──────────────────────────────────────────────


class TestQueryCorpus:
    def test_exactly_21_queries(self):
        assert len(EVAL_QUERIES) == 21

    def test_all_tiers_covered(self):
        tiers = {q["expected_tier"] for q in EVAL_QUERIES}
        assert tiers == {"core", "semantic", "procedural", "episodic"}

    def test_5_queries_per_domain(self):
        from collections import Counter
        tier_counts = Counter(q["expected_tier"] for q in EVAL_QUERIES)
        # core has 5 + 1 identity-leak probe = 6 with core tier
        assert tier_counts["core"] == 6
        assert tier_counts["semantic"] == 5
        assert tier_counts["procedural"] == 5
        assert tier_counts["episodic"] == 5

    def test_unique_eval_ids(self):
        ids = [q["eval_id"] for q in EVAL_QUERIES]
        assert len(ids) == len(set(ids))

    def test_identity_leak_probe_exists(self):
        leak_probes = [q for q in EVAL_QUERIES if q.get("identity_leak_probe")]
        assert len(leak_probes) == 1
        assert leak_probes[0]["eval_id"] == "E-21"

    def test_all_queries_have_required_fields(self):
        for q in EVAL_QUERIES:
            assert "eval_id" in q
            assert "query" in q
            assert "expected_tier" in q
            assert isinstance(q["query"], str) and len(q["query"]) > 10


# ── Tests: Cross-Model Validation ────────────────────────────────────


class TestCrossModelValidation:
    def test_same_base_raises(self):
        with pytest.raises(ValueError, match="Cross-model violation"):
            validate_cross_model("qwen2.5:7b", "qwen2.5:14b")

    def test_different_base_passes(self):
        validate_cross_model("qwen2.5:7b", "llama3:8b")

    def test_same_model_exactly_raises(self):
        with pytest.raises(ValueError, match="Cross-model violation"):
            validate_cross_model("qwen2.5:7b", "qwen2.5:7b")

    def test_case_insensitive(self):
        with pytest.raises(ValueError, match="Cross-model violation"):
            validate_cross_model("Qwen2.5:7b", "QWEN2.5:14b")


# ── Tests: Scoring ───────────────────────────────────────────────────


class TestScoring:
    def test_compute_overall_direct(self):
        score = _compute_overall(1.0, 1.0, "DIRECT")
        assert score == pytest.approx(1.0)

    def test_compute_overall_irrelevant(self):
        score = _compute_overall(0.0, 0.0, "IRRELEVANT")
        assert score == pytest.approx(0.0)

    def test_compute_overall_mixed(self):
        # precision=0.8*0.4=0.32, recall=0.6*0.3=0.18, PARTIAL=0.6*0.3=0.18
        score = _compute_overall(0.8, 0.6, "PARTIAL")
        assert score == pytest.approx(0.68)

    def test_compute_overall_unknown_relevance_defaults_irrelevant(self):
        score = _compute_overall(1.0, 1.0, "GARBAGE")
        assert score == pytest.approx(0.7)  # 0.4 + 0.3 + 0.0

    def test_verdict_pass(self):
        assert _score_to_verdict(0.70) == "PASS"
        assert _score_to_verdict(0.95) == "PASS"

    def test_verdict_marginal(self):
        assert _score_to_verdict(0.50) == "MARGINAL"
        assert _score_to_verdict(0.69) == "MARGINAL"

    def test_verdict_fail(self):
        assert _score_to_verdict(0.49) == "FAIL"
        assert _score_to_verdict(0.0) == "FAIL"


# ── Tests: Judge Response Parsing ────────────────────────────────────


class TestJudgeParsing:
    def test_parse_clean_json(self):
        data = _parse_judge_response(_MOCK_JUDGE_RESPONSE_PASS)
        assert data["context_precision"]["score"] == 0.9
        assert data["answer_relevance"]["score"] == "DIRECT"

    def test_parse_with_markdown_fences(self):
        wrapped = f"```json\n{_MOCK_JUDGE_RESPONSE_PASS}\n```"
        data = _parse_judge_response(wrapped)
        assert data["context_precision"]["score"] == 0.9

    def test_parse_flat_format(self):
        data = _parse_judge_response(_MOCK_JUDGE_RESPONSE_FLAT)
        assert data["context_precision"] == 0.75

    def test_parse_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_judge_response("not json at all")


# ── Tests: Chunk Metadata Extraction ─────────────────────────────────


class TestChunkExtraction:
    def test_extracts_tier_and_path(self):
        compiled = _compiled_ctx("semantic")
        chunks = _extract_chunks_metadata(compiled)
        assert len(chunks) == 1
        assert chunks[0]["tier"] == "semantic"
        assert chunks[0]["source_path"] == "vault/knowledge/test.md"

    def test_truncates_content(self):
        compiled = CompiledContext(
            query="q",
            slices=[
                ContextSlice(
                    name="semantic",
                    tier=MemoryTier.SEMANTIC,
                    fragments=["x" * 1000],
                    fragment_meta=[FragmentMeta(source_path="f.md", header_path="H")],
                    token_count=100,
                    max_tokens=500,
                )
            ],
            total_tokens=100,
            budget=6000,
        )
        chunks = _extract_chunks_metadata(compiled)
        assert len(chunks[0]["content"]) == 500


# ── Tests: Judge Prompt Construction ─────────────────────────────────


class TestJudgePrompt:
    def test_contains_query_and_response(self):
        prompt = _build_judge_prompt("test query", [], "test response", "semantic")
        assert "test query" in prompt
        assert "test response" in prompt
        assert '"expected_tier": "semantic"' in prompt

    def test_contains_chunk_data(self):
        chunks = [{"content": "data", "tier": "core", "score": 0.9, "source_path": "f.md"}]
        prompt = _build_judge_prompt("q", chunks, "r", "core")
        assert '"tier": "core"' in prompt


# ── Tests: Summary Builder ───────────────────────────────────────────


class TestSummaryBuilder:
    def test_empty_results(self):
        ts = datetime.now(timezone.utc)
        summary = _build_summary([], "run-1", ts)
        assert summary["total"] == 0
        assert summary["avg_score"] == 0.0

    def test_aggregates_correctly(self):
        ts = datetime.now(timezone.utc)
        results = [
            EvalResult(
                eval_id="E-01", query="q1", context_precision=0.9,
                context_recall=0.8, answer_relevance="DIRECT",
                overall_score=0.86, verdict="PASS", tier_mismatch=False,
                reasoning="good", judge_model="qwen2.5:7b",
                inference_model="llama3:8b", timestamp=ts.isoformat(),
            ),
            EvalResult(
                eval_id="E-02", query="q2", context_precision=0.3,
                context_recall=0.2, answer_relevance="IRRELEVANT",
                overall_score=0.18, verdict="FAIL", tier_mismatch=True,
                reasoning="bad", judge_model="qwen2.5:7b",
                inference_model="llama3:8b", timestamp=ts.isoformat(),
            ),
        ]
        summary = _build_summary(results, "run-2", ts)
        assert summary["total"] == 2
        assert summary["passed"] == 1
        assert summary["failed"] == 1
        assert summary["tier_mismatches"] == 1
        assert summary["avg_score"] == pytest.approx(0.52)
        assert summary["avg_precision"] == pytest.approx(0.6)


# ── Tests: Progress Callback ─────────────────────────────────────────


class TestProgressCallback:
    @patch("core.cognition.compiler.compile_context", return_value=_compiled_ctx())
    @patch("core.cognition.compiler.render_context", return_value="context text")
    @patch("core.cognition.inference.generate_local")
    def test_callback_called_per_query(self, mock_gen, mock_render, mock_compile):
        mock_gen.return_value = {"response": _MOCK_JUDGE_RESPONSE_PASS}
        progress = MagicMock()

        test_queries = [EVAL_QUERIES[0]]  # single query
        run_eval(
            on_progress=progress,
            queries=test_queries,
            judge_model="llama3:7b",
            inference_model="qwen2.5:14b",
        )

        # Called for evaluation + final summary
        assert progress.call_count >= 2
        first_call = progress.call_args_list[0][0][0]
        assert "E-01" in first_call
        assert "1/1" in first_call

    @patch("core.cognition.compiler.compile_context", return_value=_compiled_ctx())
    @patch("core.cognition.compiler.render_context", return_value="context text")
    @patch("core.cognition.inference.generate_local")
    def test_none_callback_ok(self, mock_gen, mock_render, mock_compile):
        mock_gen.return_value = {"response": _MOCK_JUDGE_RESPONSE_PASS}
        # Should not raise
        run_eval(
            on_progress=None,
            queries=[EVAL_QUERIES[0]],
            judge_model="llama3:7b",
            inference_model="qwen2.5:14b",
        )


# ── Tests: Full Run ──────────────────────────────────────────────────


class TestRunEval:
    @patch("core.cognition.compiler.compile_context", return_value=_compiled_ctx())
    @patch("core.cognition.compiler.render_context", return_value="context text")
    @patch("core.cognition.inference.generate_local")
    def test_returns_summary_dict(self, mock_gen, mock_render, mock_compile):
        mock_gen.return_value = {"response": _MOCK_JUDGE_RESPONSE_PASS}

        summary = run_eval(
            queries=[EVAL_QUERIES[0]],
            judge_model="llama3:7b",
            inference_model="qwen2.5:14b",
        )

        assert "run_id" in summary
        assert "total" in summary
        assert "passed" in summary
        assert "avg_score" in summary
        assert summary["total"] == 1

    @patch("core.cognition.compiler.compile_context", return_value=_compiled_ctx())
    @patch("core.cognition.compiler.render_context", return_value="context text")
    @patch("core.cognition.inference.generate_local")
    def test_cross_model_violation_raises(self, mock_gen, mock_render, mock_compile):
        with pytest.raises(ValueError, match="Cross-model violation"):
            run_eval(
                queries=[EVAL_QUERIES[0]],
                judge_model="qwen2.5:7b",
                inference_model="qwen2.5:14b",
            )

    @patch("core.cognition.compiler.compile_context", return_value=_compiled_ctx())
    @patch("core.cognition.compiler.render_context", return_value="context text")
    @patch("core.cognition.inference.generate_local")
    def test_persists_to_log(self, mock_gen, mock_render, mock_compile, tmp_path):
        mock_gen.return_value = {"response": _MOCK_JUDGE_RESPONSE_PASS}
        log_file = tmp_path / "results.jsonl"
        summary_file = tmp_path / "summary.jsonl"

        with patch("core.agency.eval.EVAL_LOG", log_file), \
             patch("core.agency.eval.EVAL_LOG_DIR", tmp_path), \
             patch("core.agency.eval.EVAL_SUMMARY_LOG", summary_file):
            run_eval(
                queries=[EVAL_QUERIES[0]],
                judge_model="llama3:7b",
                inference_model="qwen2.5:14b",
            )

        assert log_file.exists()
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["eval_id"] == "E-01"
        assert data["verdict"] == "PASS"

        assert summary_file.exists()
        summary = json.loads(summary_file.read_text(encoding="utf-8").strip())
        assert summary["total"] == 1

    @patch("core.cognition.compiler.compile_context", return_value=_compiled_ctx())
    @patch("core.cognition.compiler.render_context", return_value="context text")
    @patch("core.cognition.inference.generate_local")
    def test_malformed_judge_response_produces_fail(self, mock_gen, mock_render, mock_compile, tmp_path):
        mock_gen.return_value = {"response": "not valid json"}
        log_file = tmp_path / "results.jsonl"
        summary_file = tmp_path / "summary.jsonl"

        with patch("core.agency.eval.EVAL_LOG", log_file), \
             patch("core.agency.eval.EVAL_LOG_DIR", tmp_path), \
             patch("core.agency.eval.EVAL_SUMMARY_LOG", summary_file):
            summary = run_eval(
                queries=[EVAL_QUERIES[0]],
                judge_model="llama3:7b",
                inference_model="qwen2.5:14b",
            )

        assert summary["total"] == 1
        assert summary["failed"] == 1
        assert summary["results"][0]["verdict"] == "FAIL"
        assert "unparseable" in summary["results"][0]["reasoning"]

    @patch("core.cognition.compiler.compile_context", return_value=_compiled_ctx())
    @patch("core.cognition.compiler.render_context", return_value="context text")
    @patch("core.cognition.inference.generate_local")
    def test_multiple_queries_all_scored(self, mock_gen, mock_render, mock_compile, tmp_path):
        mock_gen.return_value = {"response": _MOCK_JUDGE_RESPONSE_PASS}
        log_file = tmp_path / "results.jsonl"
        summary_file = tmp_path / "summary.jsonl"

        with patch("core.agency.eval.EVAL_LOG", log_file), \
             patch("core.agency.eval.EVAL_LOG_DIR", tmp_path), \
             patch("core.agency.eval.EVAL_SUMMARY_LOG", summary_file):
            summary = run_eval(
                queries=EVAL_QUERIES[:3],
                judge_model="llama3:7b",
                inference_model="qwen2.5:14b",
            )

        assert summary["total"] == 3
        assert summary["passed"] == 3

    @patch("core.cognition.compiler.compile_context", return_value=_compiled_ctx())
    @patch("core.cognition.compiler.render_context", return_value="context text")
    @patch("core.cognition.inference.generate_local")
    def test_flat_judge_format_handled(self, mock_gen, mock_render, mock_compile, tmp_path):
        """Judge may return flat floats instead of nested objects."""
        mock_gen.return_value = {"response": _MOCK_JUDGE_RESPONSE_FLAT}
        log_file = tmp_path / "results.jsonl"
        summary_file = tmp_path / "summary.jsonl"

        with patch("core.agency.eval.EVAL_LOG", log_file), \
             patch("core.agency.eval.EVAL_LOG_DIR", tmp_path), \
             patch("core.agency.eval.EVAL_SUMMARY_LOG", summary_file):
            summary = run_eval(
                queries=[EVAL_QUERIES[0]],
                judge_model="llama3:7b",
                inference_model="qwen2.5:14b",
            )

        assert summary["total"] == 1
        data = json.loads(log_file.read_text().strip())
        assert data["context_precision"] == 0.75


# ── Tests: Identity-Leak Probe ───────────────────────────────────────


class TestIdentityLeakProbe:
    def test_logs_when_core_chunks_present(self, caplog):
        chunks = [
            {"content": "secret data", "tier": "core", "score": 0.9, "source_path": "vault/identity/MISSION.md"},
        ]
        with caplog.at_level("INFO"):
            _check_identity_leak(chunks, "response with secrets")
        assert "identity-leak probe" in caplog.text

    def test_silent_when_no_core_chunks(self, caplog):
        chunks = [
            {"content": "public data", "tier": "semantic", "score": 0.9, "source_path": "vault/knowledge/tech.md"},
        ]
        with caplog.at_level("INFO"):
            _check_identity_leak(chunks, "safe response")
        assert "identity-leak probe" not in caplog.text


# ── Tests: Session Sampling ──────────────────────────────────────────


class TestSessionSampling:
    def test_sample_from_jsonl(self, tmp_path):
        session_dir = tmp_path / "sessions" / "2026-03-02"
        session_dir.mkdir(parents=True)
        session_file = session_dir / "SESSION-abc123.jsonl"

        entries = [
            json.dumps({"type": "query", "query_hash": "h1", "query": "What is OIKOS?"}),
            json.dumps({"type": "response", "query_hash": "h1", "response_preview": "OIKOS is a system"}),
        ]
        session_file.write_text("\n".join(entries), encoding="utf-8")

        with patch("core.agency.eval.LOGS_DIR", tmp_path / "sessions"):
            samples = _sample_interactions(limit=5)

        assert len(samples) == 1
        assert samples[0]["query"] == "What is OIKOS?"

    def test_empty_lines_handled(self, tmp_path):
        session_dir = tmp_path / "sessions"
        session_dir.mkdir(parents=True)
        session_file = session_dir / "SESSION-test.jsonl"

        entries = [
            json.dumps({"type": "query", "query_hash": "h1", "query": "q1"}),
            "",
            json.dumps({"type": "response", "query_hash": "h1", "response_preview": "r1"}),
        ]
        session_file.write_text("\n".join(entries), encoding="utf-8")

        with patch("core.agency.eval.LOGS_DIR", tmp_path / "sessions"):
            samples = _sample_interactions(limit=5)

        assert len(samples) == 1

    def test_malformed_json_skipped(self, tmp_path):
        session_dir = tmp_path / "sessions"
        session_dir.mkdir(parents=True)
        session_file = session_dir / "SESSION-bad.jsonl"
        session_file.write_text("not json\nalso not json\n", encoding="utf-8")

        with patch("core.agency.eval.LOGS_DIR", tmp_path / "sessions"):
            samples = _sample_interactions(limit=5)

        assert len(samples) == 0


# ── Tests: EvalResult Model ──────────────────────────────────────────


class TestEvalResultModel:
    def test_model_fields(self):
        r = EvalResult(
            eval_id="E-01", query="test", context_precision=0.9,
            context_recall=0.8, answer_relevance="DIRECT",
            overall_score=0.86, verdict="PASS", reasoning="good",
            judge_model="qwen2.5:7b", inference_model="llama3:8b",
            timestamp="2026-03-02T00:00:00+00:00",
        )
        assert r.tier_mismatch is False
        assert r.retrieved_tiers == []
        assert r.expected_tier is None

    def test_serialization_roundtrip(self):
        r = EvalResult(
            eval_id="E-01", query="test", expected_tier="core",
            retrieved_tiers=["core", "semantic"],
            context_precision=0.9, context_recall=0.8,
            answer_relevance="DIRECT", overall_score=0.86,
            verdict="PASS", tier_mismatch=False, reasoning="ok",
            judge_model="qwen2.5:7b", inference_model="llama3:8b",
            timestamp="2026-03-02T00:00:00+00:00",
        )
        data = json.loads(r.model_dump_json())
        r2 = EvalResult.model_validate(data)
        assert r2.eval_id == r.eval_id
        assert r2.overall_score == r.overall_score


# ── Tests: Answer Relevance Enum ─────────────────────────────────────


class TestAnswerRelevance:
    def test_all_values_in_numeric_map(self):
        for member in AnswerRelevance:
            assert member in ANSWER_RELEVANCE_NUMERIC

    def test_direct_is_highest(self):
        assert ANSWER_RELEVANCE_NUMERIC[AnswerRelevance.DIRECT] == 1.0

    def test_irrelevant_is_zero(self):
        assert ANSWER_RELEVANCE_NUMERIC[AnswerRelevance.IRRELEVANT] == 0.0
