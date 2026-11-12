"""Answer composition: citations, confidence, follow-ups, honesty on failure."""

from __future__ import annotations

from app.engine.answer import (
    Answer,
    CitedSentence,
    SourceDoc,
    build_answer,
    extract_followups,
    is_junk,
)


def _doc(text: str, idx: int = 0, fetched: bool = True) -> SourceDoc:
    return SourceDoc(
        title=f"Page {idx}",
        url=f"https://example{idx}.com/article",
        domain=f"example{idx}.com",
        text=text,
        snippet=text[:120],
        fetched=fetched,
    )


class TestBuildAnswer:
    def test_every_sentence_has_a_source(self):
        docs = [
            _doc(
                "Retrieval augmented generation pairs a search step with a language model. "
                "The retriever fetches documents that the model then reads.",
                0,
            ),
            _doc(
                "RAG reduces hallucination because the model answers from retrieved text. "
                "Citations let a reader verify each claim independently.",
                1,
            ),
        ]
        ans = build_answer("what is retrieval augmented generation", docs)
        assert ans.sentences
        for s in ans.sentences:
            assert 0 <= s.source_index < len(docs)

    def test_no_documents_is_honest(self):
        ans = build_answer("anything", [])
        assert ans.confidence == 0.0
        assert "no_documents" in ans.notes
        assert ans.sentences == []

    def test_irrelevant_documents_produce_no_answer(self):
        docs = [_doc("Gardening tips for growing tomatoes in small spaces.", 0)]
        ans = build_answer("quantum entanglement in superconductors", docs)
        assert ans.sentences == []
        assert ans.confidence == 0.0

    def test_confidence_rises_with_corroboration(self):
        one = [
            _doc(
                "Database indexing makes query lookups much faster in practice. "
                "An index is a separate structure pointing at rows.",
                0,
            )
        ]
        three = [
            *one,
            _doc(
                "Indexing database columns speeds up query lookups significantly. "
                "Query planners choose indexes automatically when available.",
                1,
            ),
            _doc(
                "A database index trades write speed for faster query lookups. "
                "Indexes are the first thing to check for slow queries.",
                2,
            ),
        ]
        a1 = build_answer("database indexing query lookups", one)
        a3 = build_answer("database indexing query lookups", three)
        assert a3.confidence >= a1.confidence

    def test_single_source_is_flagged(self):
        docs = [
            _doc(
                "The treaty was signed in the spring of that year. "
                "Negotiators had worked on the text for months.",
                0,
            )
        ]
        ans = build_answer("when was the treaty signed", docs)
        if ans.sentences:
            assert "single_source" in ans.notes

    def test_citations_for_maps_positions(self):
        docs = [
            _doc(
                "Vector databases store embeddings for similarity search. "
                "They index high dimensional vectors efficiently.",
                0,
            )
        ]
        ans = build_answer("vector database embeddings", docs)
        if ans.sentences:
            positions = ans.citations_for(0)
            assert len(positions) == len(ans.sentences)

    def test_summary_mentions_source_count(self):
        docs = [
            _doc(
                "Kubernetes schedules containers across a cluster of machines. "
                "The scheduler places pods based on resource requests.",
                0,
            )
        ]
        ans = build_answer("how does kubernetes scheduling work", docs)
        if ans.summary:
            assert "source" in ans.summary.lower()

    def test_sentences_are_capitalised_and_terminated(self):
        docs = [
            _doc(
                "the cache stores frequently requested data in memory. "
                "a cache hit avoids a database round trip entirely.",
                0,
            )
        ]
        ans = build_answer("what does a cache do", docs)
        for s in ans.sentences:
            assert s.text[0].isupper()
            assert s.text[-1] in ".!?"


class TestJunkFilter:
    def test_cookie_banner_is_junk(self):
        assert is_junk("Accept all cookies to continue browsing this site.")
        assert is_junk("Subscribe to our newsletter for weekly updates.")

    def test_real_sentence_is_not_junk(self):
        assert not is_junk(
            "The central bank raised its policy rate by 100 basis points on Monday."
        )

    def test_very_short_is_junk(self):
        assert is_junk("Read more")


class TestFollowups:
    def test_returns_requested_count(self):
        ans = Answer(summary="x", sentences=[CitedSentence("Some text.", 0)])
        out = extract_followups("what is a vector database", ans, limit=4)
        assert len(out) == 4

    def test_followups_are_unique(self):
        ans = Answer(summary="x")
        out = extract_followups("how does indexing work", ans, limit=4)
        assert len(set(out)) == len(out)

    def test_followups_reference_the_subject(self):
        ans = Answer(summary="x")
        out = extract_followups("what is retrieval augmented generation", ans, limit=3)
        assert any("retrieval" in f.lower() for f in out)

    def test_thin_coverage_adds_widening_question(self):
        ans = Answer(summary="x", notes=["partial_coverage"])
        out = extract_followups("what is a transformer", ans, limit=4)
        assert "other sources" in out[0].lower()
