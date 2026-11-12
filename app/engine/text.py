"""Text plumbing: sentence splitting, tokenising, and sentence ranking.

This is the part that decides *which* sentences from a pile of web pages
actually answer the question. It is deliberately boring and deterministic —
no model, no API, no randomness. Same input, same answer, every time, which
is what makes it testable and what makes the citations trustworthy.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

# Abbreviations that end in a period but do not end a sentence. Without this
# list "Dr. Khan said..." becomes two sentences and the citation lands on the
# wrong half.
_ABBREVIATIONS = {
    "mr",
    "mrs",
    "ms",
    "dr",
    "prof",
    "sr",
    "jr",
    "st",
    "vs",
    "etc",
    "e.g",
    "i.e",
    "inc",
    "ltd",
    "co",
    "corp",
    "gov",
    "sen",
    "rep",
    "gen",
    "col",
    "capt",
    "lt",
    "sgt",
    "no",
    "vol",
    "fig",
    "approx",
    "dept",
    "univ",
    "jan",
    "feb",
    "mar",
    "apr",
    "jun",
    "jul",
    "aug",
    "sep",
    "sept",
    "oct",
    "nov",
    "dec",
    "u.s",
    "u.k",
    "a.m",
    "p.m",
}

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

# Wikipedia and many news sites leave inline reference markers in the prose:
# "[ 99 ]", "[12]", "[edit]", "[citation needed]". They are noise in an answer
# and they break sentence boundaries, so they go before anything else.
_REF_MARKER = re.compile(
    r"\[\s*(?:\d{1,3}|edit|citation needed|note \d+|nb \d+|a|b|c)\s*\]", re.I
)
_WHITESPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"[a-z0-9][a-z0-9'\-]*")

STOPWORDS = frozenset(
    [
        "a",
        "about",
        "above",
        "after",
        "again",
        "against",
        "all",
        "am",
        "an",
        "and",
        "any",
        "are",
        "aren't",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "can't",
        "cannot",
        "could",
        "couldn't",
        "did",
        "didn't",
        "do",
        "does",
        "doesn't",
        "doing",
        "don't",
        "down",
        "during",
        "each",
        "few",
        "for",
        "from",
        "further",
        "had",
        "hadn't",
        "has",
        "hasn't",
        "have",
        "haven't",
        "having",
        "he",
        "he'd",
        "he'll",
        "he's",
        "her",
        "here",
        "here's",
        "hers",
        "herself",
        "him",
        "himself",
        "his",
        "how",
        "how's",
        "i",
        "i'd",
        "i'll",
        "i'm",
        "i've",
        "if",
        "in",
        "into",
        "is",
        "isn't",
        "it",
        "it's",
        "its",
        "itself",
        "let's",
        "me",
        "more",
        "most",
        "mustn't",
        "my",
        "myself",
        "no",
        "nor",
        "not",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "other",
        "ought",
        "our",
        "ours",
        "ourselves",
        "out",
        "over",
        "own",
        "same",
        "shan't",
        "she",
        "she'd",
        "she'll",
        "she's",
        "should",
        "shouldn't",
        "so",
        "some",
        "such",
        "than",
        "that",
        "that's",
        "the",
        "their",
        "theirs",
        "them",
        "themselves",
        "then",
        "there",
        "there's",
        "these",
        "they",
        "they'd",
        "they'll",
        "they're",
        "they've",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "very",
        "was",
        "wasn't",
        "we",
        "we'd",
        "we'll",
        "we're",
        "we've",
        "were",
        "weren't",
        "what",
        "what's",
        "when",
        "when's",
        "where",
        "where's",
        "which",
        "while",
        "who",
        "who's",
        "whom",
        "why",
        "why's",
        "with",
        "won't",
        "would",
        "wouldn't",
        "you",
        "you'd",
        "you'll",
        "you're",
        "you've",
        "your",
        "yours",
        "yourself",
        "yourselves",
        "also",
        "just",
        "like",
        "get",
        "got",
        "make",
        "made",
        "many",
        "much",
        "may",
        "might",
        "must",
        "new",
        "now",
        "one",
        "two",
        "said",
        "says",
        "say",
        "according",
        "report",
        "reports",
        "reported",
    ]
)


def strip_reference_markers(text: str) -> str:
    """Remove inline citation markers like [12] or [edit] from prose."""
    return _REF_MARKER.sub(" ", text)


def normalise_whitespace(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def split_sentences(text: str) -> list[str]:
    """Split prose into sentences, respecting common abbreviations.

    Not a full NLP sentence tokeniser — but it handles the cases that actually
    show up in news articles and documentation, which is what we read.
    """
    text = normalise_whitespace(strip_reference_markers(text))
    if not text:
        return []

    rough = _SENTENCE_END.split(text)
    out: list[str] = []
    buffer = ""

    for chunk in rough:
        candidate = f"{buffer} {chunk}".strip() if buffer else chunk
        # If the chunk ends with a known abbreviation, glue the next one on.
        tail = candidate.rsplit(" ", 1)[-1].rstrip(".").lower()
        if tail in _ABBREVIATIONS and not candidate.endswith(("?", "!")):
            buffer = candidate
            continue
        buffer = ""
        if candidate:
            out.append(candidate)

    if buffer:
        out.append(buffer)

    return [s for s in out if s]


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def content_terms(text: str) -> list[str]:
    """Tokens minus stopwords, with a crude singular/plural fold."""
    terms = []
    for tok in tokenize(text):
        if tok in STOPWORDS or len(tok) < 2:
            continue
        if len(tok) > 4 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]
        terms.append(tok)
    return terms


@dataclass(frozen=True)
class Candidate:
    """One sentence, with where it came from."""

    text: str
    source_index: int
    position: int
    score: float = 0.0


def _idf(corpus: list[list[str]]) -> dict[str, float]:
    """Inverse document frequency over the sentence corpus.

    A word that appears in every sentence tells us nothing; a word that
    appears in two sentences is probably the subject. This is what stops the
    answer from being a pile of sentences that all say "the company said".
    """
    n = len(corpus)
    if n == 0:
        return {}
    df: Counter[str] = Counter()
    for terms in corpus:
        df.update(set(terms))
    return {term: math.log((n + 1) / (count + 0.5)) for term, count in df.items()}


def rank_sentences(
    question: str,
    documents: list[str],
    *,
    min_chars: int = 45,
    max_chars: int = 320,
) -> list[Candidate]:
    """Score every sentence in every document against the question.

    Returns candidates sorted best-first. The score blends three things:
    how many question terms the sentence covers, how rare those terms are,
    and a small bonus for sentences that sit early in their document (leads
    usually carry the point).
    """
    q_terms = content_terms(question)
    if not q_terms:
        return []

    q_set = set(q_terms)

    # The subject of a question usually comes first: "retrieval augmented
    # generation" before "why does it reduce hallucination". A sentence that
    # matches only the tail terms is usually a coincidence — an article about
    # a medical catheter that happens to contain "hallucinations" and
    # "reduces". Require a match on the subject, or strong overall coverage.
    head_len = max(1, math.ceil(len(q_terms) * 0.6))
    subject_terms = set(q_terms[:head_len])

    # Build the corpus first so IDF is computed over everything we have.
    per_doc: list[list[tuple[str, int]]] = []
    for doc in documents:
        sents = split_sentences(doc)
        per_doc.append([(s, i) for i, s in enumerate(sents)])

    flat = [s for doc in per_doc for s, _ in doc]
    corpus = [content_terms(s) for s in flat]
    idf = _idf(corpus)

    # Total weight of the question, so coverage is a fraction not a raw count.
    q_weight = sum(idf.get(t, 1.0) for t in q_set) or 1.0

    candidates: list[Candidate] = []
    for doc_idx, doc in enumerate(per_doc):
        doc_len = max(len(doc), 1)
        for text, pos in doc:
            if not (min_chars <= len(text) <= max_chars):
                continue
            terms = content_terms(text)
            if not terms:
                continue

            term_set = set(terms)
            matched = q_set & term_set
            if not matched:
                continue

            coverage = sum(idf.get(t, 1.0) for t in matched) / q_weight

            # Relevance floor: the sentence must be about the question's
            # subject. A page can contain "hallucination" and "reduces" while
            # being about something else entirely — a medical catheter, say —
            # and lexical scoring alone can't tell the difference. Requiring a
            # subject term is the cheap, honest guard.
            if not (matched & subject_terms):
                continue

            # Term frequency, damped — repeating a word five times is not
            # five times as relevant.
            tf = sum(1 for t in terms if t in q_set)
            density = tf / (1.0 + math.log(1 + len(terms)))

            # Early sentences in a document are usually the lede.
            position_bonus = 0.15 * (1.0 - pos / doc_len)

            score = (0.62 * coverage) + (0.23 * min(density, 1.0)) + position_bonus

            candidates.append(
                Candidate(
                    text=text.strip(),
                    source_index=doc_idx,
                    position=pos,
                    score=round(score, 6),
                )
            )

    candidates.sort(key=lambda c: (-c.score, c.source_index, c.position))
    return candidates


# A sentence needs a verb to be a sentence. Without one it is almost always
# a page title, a heading, or a table caption that leaked into the text —
# exactly the junk that made the first version of this answer read badly.
_VERB_HINTS = frozenset(
    [
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "has",
        "have",
        "had",
        "do",
        "does",
        "did",
        "can",
        "could",
        "will",
        "would",
        "shall",
        "should",
        "may",
        "might",
        "must",
        "makes",
        "make",
        "made",
        "uses",
        "use",
        "used",
        "allows",
        "allow",
        "reduces",
        "reduce",
        "provides",
        "provide",
        "shows",
        "show",
        "found",
        "finds",
        "gives",
        "give",
        "takes",
        "take",
        "comes",
        "come",
        "works",
        "work",
        "means",
        "mean",
        "includes",
        "include",
        "requires",
        "require",
        "became",
        "become",
        "said",
        "says",
        "reported",
        "reports",
        "added",
        "adds",
        "noted",
        "notes",
        "argued",
        "argues",
        "suggests",
        "suggest",
        "found",
        "reported",
        "published",
        "released",
        "launched",
        "introduced",
        "developed",
        "built",
        "created",
        "designed",
        "enables",
        "enable",
        "lets",
        "let",
    ]
)


def _has_verb(words: list[str]) -> bool:
    """Best-effort verb detection without a parser.

    Three signals, cheapest first: a known verb, an auxiliary, or a word
    carrying a verb-ish suffix. The suffix check is what catches "pairs",
    "fetches", "reduces" — words no hand-written list will ever cover.
    """
    if any(w in _VERB_HINTS for w in words):
        return True

    for w in words[1:]:  # skip the first word; it's often a capitalised noun
        if len(w) < 4:
            continue
        if w.endswith(("ed", "ing")):
            return True
        # Third-person singular: ends in s but is not a common plural noun.
        if w.endswith("s") and not w.endswith(("ss", "us", "is", "as", "os")):
            return True

    return False


def looks_like_title(sentence: str) -> bool:
    """True for heading-like fragments that carry no statement.

    Two signals: no verb at all, or a quoted title followed by a lone period
    (the shape you get when a page's <h1> is scraped as prose).
    """
    s = sentence.strip()
    if not s:
        return True

    # "Some Article Title" .  — a quoted title with a stray full stop.
    if re.match(r'^["\u201c].{10,}["\u201d]\s*\.?$', s):
        return True

    words = tokenize(s)
    if len(words) < 5:
        return True

    if not _has_verb(words):
        # No verb anywhere: a heading, a list of nouns, a caption.
        return True

    # A sentence that is mostly capitalised words is a title in disguise.
    raw_words = [w for w in s.split() if w[:1].isalpha()]
    if raw_words:
        caps = sum(1 for w in raw_words if w[0].isupper())
        if caps / len(raw_words) > 0.75 and len(raw_words) < 14:
            return True

    return False


def _fingerprint(text: str) -> frozenset[str]:
    return frozenset(content_terms(text))


def dedupe(candidates: list[Candidate], threshold: float = 0.72) -> list[Candidate]:
    """Drop sentences that are near-copies of one already chosen.

    News syndication means the same paragraph shows up on five sites. Without
    this the answer reads like a stutter and every citation points at the
    same wire copy.
    """
    kept: list[Candidate] = []
    kept_prints: list[frozenset[str]] = []

    for cand in candidates:
        fp = _fingerprint(cand.text)
        if not fp:
            continue
        duplicate = False
        for prev in kept_prints:
            overlap = len(fp & prev) / max(len(fp | prev), 1)
            if overlap >= threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append(cand)
            kept_prints.append(fp)

    return kept
