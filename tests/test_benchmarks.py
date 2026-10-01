"""Smoke tests for the synthetic-corpus evaluation harness."""

from benchmarks.baseline import ProhibitionOnlyBaseline
from benchmarks.corpus import generate_corpus
from benchmarks.run_evaluation import run
from pranidhi.models import Disposition, UserContext


class TestCorpus:

    def test_generates_requested_size(self):
        corpus = generate_corpus(size=100, seed=1)
        assert len(corpus) == 100

    def test_deterministic_with_fixed_seed(self):
        a = generate_corpus(size=50, seed=42)
        b = generate_corpus(size=50, seed=42)
        assert [i.prompt for i in a] == [i.prompt for i in b]

    def test_every_category_represented(self):
        corpus = generate_corpus(size=200, seed=7)
        categories = {i.category for i in corpus}
        assert {"benign", "pii", "credential", "code", "financial_leak"} <= categories


class TestBaseline:

    def test_blocks_credential_content(self):
        baseline = ProhibitionOnlyBaseline()
        ctx = UserContext(user_id="test")
        result = baseline.scan("Here is my key secret_test_abcdefghijklmnopqrstuvwxyz123456", ctx)
        assert result.disposition == Disposition.RED

    def test_allows_clean_benign_prompt_in_low_risk_context(self):
        # Default UserContext carries an "unknown" platform and untrained role,
        # both of which inflate exposure risk by design (see risk_scorer.py's
        # PLATFORM_RISK and role modifier): a genuinely low-risk context is
        # needed to observe a GREEN disposition even for benign content.
        baseline = ProhibitionOnlyBaseline()
        ctx = UserContext(user_id="test", role="security", target_platform="internal")
        result = baseline.scan("What is the capital of France?", ctx)
        assert result.disposition == Disposition.GREEN


class TestRunEvaluation:

    def test_run_produces_well_formed_summary(self):
        summary = run(corpus_size=50, seed=99)
        assert summary["corpus_size"] == 50
        assert "pranidhi" in summary and "prohibition_only_baseline" in summary
        pct_total = sum(summary["pranidhi"]["disposition_distribution_pct"].values())
        assert 99.0 <= pct_total <= 100.01

    def test_pranidhi_coaches_more_than_baseline(self):
        summary = run(corpus_size=100, seed=99)
        assert summary["pranidhi"]["coaching_coverage_pct"] > summary["prohibition_only_baseline"]["coaching_coverage_pct"]
