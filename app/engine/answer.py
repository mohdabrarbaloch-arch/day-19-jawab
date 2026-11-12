"""Turning ranked sentences into an answer with real citations.

The contract this module keeps: every sentence in the output carries the
index of the source it came from, and that index is the same one the UI
renders as a numbered chip. If a sentence has no source, it does not go in
the answer. That is the whole difference between this and a chatbot that
sounds confident.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.engine.text import (
    Candidate,
    content_terms,
    dedupe,
    looks_like_title,
    normalise_whitespace,
    rank_sentences,
    split_sentences,
)

# Sentences that are pure navigation or boilerplate. They score well on
# keyword overlap and add nothing, so they get filtered before ranking.
_JUNK_PATTERNS = [
    re.compile(r"^(accept|reject) (all )?cookies", re.IGNORECASE),
    re.compile(r"^(subscribe|sign up|log ?in|register)\b", re.IGNORECASE),
    re.compile(r"^(share|tweet|print|email) this", re.IGNORECASE),
    re.compile(r"^(advertisement|sponsored|read more|related articles?)\b", re.IGNORECASE),
    re.compile(r"^(click|tap) here", re.IGNORECASE),
    re.compile(r"^(copyright|©|all rights reserved)", re.IGNORECASE),
    re.compile(r"^(privacy policy|terms of (use|service)|cookie policy)", re.IGNORECASE),
    re.compile(r"^(menu|home|search|skip to content)\b", re.IGNORECASE),
    # Wikipedia-style navigation runs: "Mitigation strategies Retrieval-
    # augmented generation Main article: Retrieval-augmented generation".
    # These are headings glued together by the extractor, not prose.
    re.compile(r"\bmain article\b", re.IGNORECASE),
    re.compile(r"\bsee also\b", re.IGNORECASE),
    re.compile(r"\b(jump to|read more|learn more)\b", re.IGNORECASE),
    re.compile(r"^\W*$"),
]


def is_junk(sentence: str) -> bool:
    s = sentence.strip()
    if len(s) < 20:
        return True
    return any(p.search(s) for p in _JUNK_PATTERNS)


@dataclass
class SourceDoc:
    """A page we actually read, ready to be cited."""

    title: str
    url: str
    domain: str
    text: str
    snippet: str = ""
    fetched: bool = False


@dataclass
class CitedSentence:
    text: str
    source_index: int


@dataclass
class Answer:
    summary: str
    sentences: list[CitedSentence] = field(default_factory=list)
    confidence: float = 0.0
    coverage: float = 0.0
    source_count: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.sentences)

    def citations_for(self, source_index: int) -> list[int]:
        """Which sentence positions (0-based) this source backs."""
        return [i for i, s in enumerate(self.sentences) if s.source_index == source_index]


def _strip_heading_prefix(sentence: str) -> str:
    """Drop a page heading that got glued onto the front of a sentence.

    Scraped pages often produce "Some Heading Some Heading is a thing that…"
    because the <h1> and the first paragraph run together. If the opening
    words repeat, keep only the second copy.
    """
    words = sentence.split()
    n = len(words)
    # Look for a repeated run of 2-8 words at the start.
    for size in range(min(8, n // 2), 1, -1):
        first = [w.lower().strip(",;:") for w in words[:size]]
        second = [w.lower().strip(",;:") for w in words[size : size * 2]]
        if first == second:
            return " ".join(words[size:])
    return sentence


def _clean(sentence: str) -> str:
    s = normalise_whitespace(_strip_heading_prefix(normalise_whitespace(sentence)))
    # Strip a leading bullet or stray dash left over from list markup.
    s = re.sub(r"^[\-\u2022\*\u00b7]\s*", "", s)
    # HTML extraction leaves a space before punctuation ("reasoning , RAG").
    # Tighten it, but leave ellipses and dashes alone.
    s = re.sub(r"\s+([,;:.!?%])", r"\1", s)
    s = re.sub(r"([(\[])\s+", r"\1", s)
    s = re.sub(r"\s+([)\]])", r"\1", s)
    s = re.sub(r"\s{2,}", " ", s)
    if s and s[0].islower():
        s = s[0].upper() + s[1:]
    if s and s[-1] not in ".!?":
        s += "."
    return s


def _coverage(question: str, answer_text: str) -> float:
    """What fraction of the question's content words the answer touches."""
    q = set(content_terms(question))
    if not q:
        return 0.0
    a = set(content_terms(answer_text))
    return len(q & a) / len(q)


def _agreement(candidates: list[Candidate], chosen: list[Candidate]) -> float:
    """How many distinct sources back the chosen sentences.

    One source is an anecdote. Three sources saying the same thing is a fact.
    This is the honest part of the confidence number.
    """
    if not chosen:
        return 0.0
    distinct = len({c.source_index for c in chosen})
    return min(distinct / 3.0, 1.0)


def build_answer(
    question: str,
    documents: list[SourceDoc],
    *,
    max_sentences: int = 7,
    min_chars: int = 45,
    max_chars: int = 320,
) -> Answer:
    """Compose a cited answer from the documents we managed to read."""
    if not documents:
        return Answer(
            summary="I couldn't read any of the pages I found, so I have nothing to cite.",
            confidence=0.0,
            notes=["no_documents"],
        )

    texts = [d.text for d in documents]
    ranked = rank_sentences(question, texts, min_chars=min_chars, max_chars=max_chars)
    ranked = [c for c in ranked if not is_junk(c.text) and not looks_like_title(c.text)]
    ranked = dedupe(ranked)

    if not ranked:
        # Fall back to the search snippets — they are short but they are real
        # text from the page, and a thin answer beats a blank one.
        fallback_docs = [d.snippet for d in documents if d.snippet]
        if fallback_docs:
            ranked = rank_sentences(question, fallback_docs, min_chars=20, max_chars=400)
            ranked = [
                c for c in ranked if not is_junk(c.text) and not looks_like_title(c.text)
            ]
            ranked = dedupe(ranked)

    if not ranked:
        return Answer(
            summary="The pages I found didn't contain anything that answers this directly.",
            confidence=0.0,
            source_count=len(documents),
            notes=["no_relevant_sentences"],
        )

    chosen = _pick_diverse(ranked, max_sentences)

    # Keep the reading order roughly natural: strongest first, but don't
    # jump between sources so hard that the answer reads like a collage.
    chosen.sort(key=lambda c: (-c.score, c.source_index, c.position))

    sentences = [
        CitedSentence(text=_clean(c.text), source_index=c.source_index) for c in chosen
    ]

    answer_text = " ".join(s.text for s in sentences)
    coverage = _coverage(question, answer_text)
    agreement = _agreement(ranked, chosen)

    # Confidence is coverage first, corroboration second. A single-source
    # answer that covers the question well still shouldn't read as certain.
    confidence = round(min(0.35 + 0.45 * coverage + 0.20 * agreement, 0.97), 3)

    notes: list[str] = []
    if len({s.source_index for s in sentences}) == 1:
        notes.append("single_source")
    if coverage < 0.4:
        notes.append("partial_coverage")
    if not any(d.fetched for d in documents):
        notes.append("snippets_only")

    summary = _make_summary(question, sentences, documents)

    # The summary is the lead sentence. Repeating it as the first line of the
    # body reads like a bug, so drop it there and keep the citation on the
    # summary instead.
    if len(sentences) > 1 and summary.startswith(sentences[0].text[:80]):
        sentences = sentences[1:]

    return Answer(
        summary=summary,
        sentences=sentences,
        confidence=confidence,
        coverage=round(coverage, 3),
        source_count=len({s.source_index for s in sentences}),
        notes=notes,
    )


def _pick_diverse(ranked: list[Candidate], limit: int) -> list[Candidate]:
    """Choose the best sentences, but don't let one page take over.

    Without this, a single long article supplies six of seven sentences and
    the "4 sources" badge is a lie. We take the strongest sentence from each
    source first, then fill the remaining slots by score.
    """
    if not ranked:
        return []

    chosen: list[Candidate] = []
    used_sources: set[int] = set()

    # Pass 1: one per source, best first.
    for cand in ranked:
        if len(chosen) >= limit:
            break
        if cand.source_index in used_sources:
            continue
        chosen.append(cand)
        used_sources.add(cand.source_index)

    # Pass 2: fill the rest by score, allowing repeats.
    if len(chosen) < limit:
        taken = {id(c) for c in chosen}
        for cand in ranked:
            if len(chosen) >= limit:
                break
            if id(cand) in taken:
                continue
            chosen.append(cand)
            taken.add(id(cand))

    return chosen


def _make_summary(
    question: str, sentences: list[CitedSentence], documents: list[SourceDoc]
) -> str:
    """A one-or-two line lead that says what the answer is about.

    Built from the strongest sentence plus a count of how many sources back
    it — so the reader knows the shape of the evidence before reading it.
    """
    if not sentences:
        return ""

    lead = sentences[0].text
    # Trim a long lead at a clause boundary rather than mid-word.
    if len(lead) > 190:
        cut = lead[:190]
        for sep in ("; ", ", ", " — ", " - "):
            idx = cut.rfind(sep)
            if idx > 110:
                cut = cut[:idx]
                break
        lead = cut.rstrip(" ,;—-") + "…"

    distinct = len({s.source_index for s in sentences})
    tail = " (1 source)" if distinct == 1 else f" ({distinct} sources)"

    return lead + tail


# Words that start a question but are not part of its subject. Dropping them
# is what stops follow-ups reading like "How does what is retrieval work?".
_LEAD_WORDS = frozenset(
    [
        "what",
        "is",
        "are",
        "was",
        "were",
        "how",
        "does",
        "do",
        "did",
        "why",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "whose",
        "tell",
        "me",
        "about",
        "explain",
        "describe",
        "define",
        "meaning",
        "of",
        "the",
        "a",
        "an",
        "in",
        "on",
        "for",
        "to",
        "and",
        "or",
        "but",
        "with",
        "without",
        "between",
        "difference",
        "compare",
        "versus",
        "vs",
        "better",
    ]
)


def _subject_phrase(question: str) -> str:
    """Pull a clean noun phrase out of a question for use in follow-ups."""
    words = normalise_whitespace(question).rstrip("?.!").split()
    kept: list[str] = []
    for w in words:
        bare = w.lower().strip(",;:")
        if bare in _LEAD_WORDS and not kept:
            continue
        kept.append(w)
        if len(kept) >= 5:
            break
    # Cut at a conjunction: "retrieval augmented generation and why" should
    # become "retrieval augmented generation", not the whole clause.
    for i, w in enumerate(kept):
        if w.lower().strip(",;:") in {"and", "or", "but", "because", "so", "while"}:
            kept = kept[:i]
            break

    phrase = " ".join(kept).strip(" ,;:")
    return phrase


def extract_followups(question: str, answer: Answer, limit: int = 4) -> list[str]:
    """Suggest next questions that are actually answerable from the same topic.

    These are shaped by what the question already asked, so they read like a
    person continuing a thought rather than four generic prompts.
    """
    q = normalise_whitespace(question).rstrip("?.!")
    subject = _subject_phrase(question) or q

    lower = question.lower()
    pool: list[str] = []

    if any(w in lower for w in ("what is", "what are", "define", "meaning")):
        pool = [
            f"How does {subject} work in practice?",
            f"What are the main criticisms of {subject}?",
            f"Who are the key players in {subject}?",
            f"What changed about {subject} most recently?",
        ]
    elif any(w in lower for w in ("how", "why")):
        pool = [
            f"What are the trade-offs of {subject}?",
            f"Are there real-world examples of {subject}?",
            f"What do experts disagree about on {subject}?",
            f"What should I read next about {subject}?",
        ]
    elif any(w in lower for w in ("compare", "vs", "versus", "better", "difference")):
        pool = [
            f"What are the strongest arguments for each side of {subject}?",
            f"Which option performs better in benchmarks for {subject}?",
            f"What are the hidden costs of {subject}?",
            "How do practitioners choose between them?",
        ]
    elif any(w in lower for w in ("when", "latest", "news", "today", "2026")):
        pool = [
            f"What is the background behind {subject}?",
            f"How has {subject} developed over the past year?",
            f"What are people predicting next for {subject}?",
            f"Which sources are most reliable on {subject}?",
        ]
    else:
        pool = [
            f"What is the most important context for {subject}?",
            f"What are the counterarguments around {subject}?",
            f"How can I verify {subject} independently?",
            f"What are the practical implications of {subject}?",
        ]

    # If the answer flagged thin coverage, offer a question that would widen it.
    if "partial_coverage" in answer.notes or "single_source" in answer.notes:
        pool.insert(0, f"What do other sources say about {subject}?")

    seen: set[str] = set()
    out: list[str] = []
    for item in pool:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def split_for_display(text: str) -> list[str]:
    """Exposed for the UI: sentence-level rendering with citation anchors."""
    return split_sentences(text)
