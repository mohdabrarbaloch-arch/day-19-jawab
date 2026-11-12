"""Sentence splitting, tokenising, ranking, dedupe.

These are the tests that matter most: if ranking is wrong, the answer is
wrong, and no amount of nice UI fixes that.
"""

from __future__ import annotations

from app.engine.text import (
    Candidate,
    content_terms,
    dedupe,
    normalise_whitespace,
    rank_sentences,
    split_sentences,
    tokenize,
)


class TestSplitSentences:
    def test_splits_on_period(self):
        out = split_sentences("One thing happened. Another thing followed.")
        assert len(out) == 2
        assert out[0] == "One thing happened."

    def test_keeps_abbreviation_together(self):
        out = split_sentences("Dr. Khan said the trial would start soon.")
        assert len(out) == 1
        assert "Dr. Khan" in out[0]

    def test_handles_question_and_exclamation(self):
        out = split_sentences("Why did it fail? Nobody knows! It just did.")
        assert len(out) == 3

    def test_empty_input(self):
        assert split_sentences("") == []
        assert split_sentences("   ") == []

    def test_collapses_whitespace(self):
        out = split_sentences("A   sentence\n\nwith   gaps.  And another.")
        assert out[0] == "A sentence with gaps."


class TestTokenize:
    def test_lowercases(self):
        assert tokenize("Hello World") == ["hello", "world"]

    def test_keeps_hyphens_and_apostrophes(self):
        assert "state-of-the-art" in tokenize("a state-of-the-art model")
        assert "don't" in tokenize("don't stop")

    def test_drops_punctuation(self):
        assert tokenize("hello, world!") == ["hello", "world"]


class TestContentTerms:
    def test_removes_stopwords(self):
        terms = content_terms("what is the meaning of this")
        assert "the" not in terms
        assert "what" not in terms
        assert "meaning" in terms

    def test_folds_plurals(self):
        assert "model" in content_terms("models")
        assert "test" in content_terms("tests")

    def test_does_not_fold_double_s(self):
        # "class" must not become "clas"
        assert "class" in content_terms("class")

    def test_empty(self):
        assert content_terms("") == []


class TestRankSentences:
    def test_prefers_sentence_that_answers(self):
        docs = [
            (
                "The weather in Karachi was pleasant today. "
                "Retrieval augmented generation pairs a retriever with a language model. "
                "Many people enjoy tea in the afternoon."
            )
        ]
        ranked = rank_sentences("what is retrieval augmented generation", docs)
        assert ranked
        assert "retrieval" in ranked[0].text.lower()

    def test_returns_empty_when_nothing_matches(self):
        docs = ["Completely unrelated text about gardening and soil."]
        ranked = rank_sentences("quantum chromodynamics lattice", docs)
        assert ranked == []

    def test_respects_length_bounds(self):
        docs = ["Tiny. " + ("A long sentence about databases and indexing. " * 3)]
        ranked = rank_sentences("databases indexing", docs, min_chars=45, max_chars=120)
        for c in ranked:
            assert 45 <= len(c.text) <= 120

    def test_tracks_source_index(self):
        docs = [
            "Nothing relevant here at all, just filler about weather patterns.",
            "Database indexing speeds up query lookups considerably in practice.",
        ]
        ranked = rank_sentences("database indexing query", docs)
        assert ranked
        assert ranked[0].source_index == 1

    def test_empty_question(self):
        assert rank_sentences("", ["some text here"]) == []


class TestDedupe:
    def test_drops_near_duplicates(self):
        a = Candidate("The company reported strong revenue growth this quarter.", 0, 0, 0.9)
        b = Candidate("The company reported strong revenue growth this quarter.", 1, 0, 0.8)
        assert len(dedupe([a, b])) == 1

    def test_keeps_distinct_sentences(self):
        a = Candidate("Revenue grew sharply across all three regions.", 0, 0, 0.9)
        b = Candidate("Regulators opened an inquiry into the merger last week.", 1, 0, 0.8)
        assert len(dedupe([a, b])) == 2

    def test_empty_list(self):
        assert dedupe([]) == []


class TestNormalise:
    def test_strips_and_collapses(self):
        assert normalise_whitespace("  a   b \n c  ") == "a b c"
