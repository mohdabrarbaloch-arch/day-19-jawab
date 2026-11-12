# Usage

How to actually use Jawab, and what the numbers on screen mean.

---

## The basic loop

1. Sign in (or click **Use the demo account**).
2. Type a question. Press Enter.
3. Read the answer. Every sentence ends with a small numbered chip.
4. Click a chip — it opens the page that sentence came from.
5. Click a follow-up at the bottom to keep going in the same thread.

That's it. There is no prompt engineering to learn.

---

## What the answer is made of

An answer has four parts:

**The summary** — one line at the top, in a serif face, ending with a source
count. It's the strongest sentence from the answer plus how many pages back
it. If it says "(1 source)", treat it as a lead, not a fact.

**The body** — up to seven sentences, each with a citation chip. These are
quoted from pages that were downloaded and read. Nothing is paraphrased,
because paraphrasing is where a search engine starts lying.

**The meta row** — three or four small pills:

| Pill | Meaning |
|---|---|
| `91% confidence` | Green ≥70, amber ≥45, red below. See below. |
| `5 cited` | How many sources actually contributed a sentence |
| `0.8s` | How long the whole pipeline took |
| `single source` | Only one page backed the answer — be careful |
| `partial coverage` | The answer didn't touch all of your question's terms |
| `snippets only` | No page could be downloaded; the answer is from search snippets |

**The sources** — every result, numbered. Cited ones have a green number.
Unread ones carry a small `not read` badge, which means exactly that: the
search engine found it, we couldn't download it, so it is never quoted.

---

## Reading the confidence number

It is not a probability that the answer is true. It's a measure of how well
the answer is supported by what was read:

```
confidence = 0.35 + 0.45 × coverage + 0.20 × agreement
```

- **coverage** — what fraction of your question's content words appear in the
  answer. Ask about "RAG and hallucination" and get an answer that only
  mentions RAG, and coverage drops.
- **agreement** — how many distinct sources back the chosen sentences,
  capped at three. One page is an anecdote; three saying the same thing is
  a fact.

So a 91% answer means: it covered your question well and multiple pages
agreed. A 40% answer means: it found something adjacent and you should read
the sources yourself.

**The number is capped at 97%.** Nothing here is ever certain.

---

## Asking better questions

Jawab matches words, not meaning. That shapes what works:

**Good** — specific nouns and the actual terms you want to see:
- `what is retrieval augmented generation and why does it reduce hallucination`
- `SQLite WAL mode vs rollback journal performance`
- `how does Pakistan current account deficit work`

**Weak** — vague or purely conversational:
- `tell me about AI` (too broad — which part?)
- `is it good?` (no subject to match)
- `what do experts think` (no topic)

If an answer comes back thin, the fastest fix is usually to add the specific
term you expected to see. `how does indexing work` → `how does database
indexing work` changes the result completely.

---

## Threads

Every question starts or continues a thread. Threads appear in the left
sidebar, newest first, titled with your question.

- **Click a thread** to reopen it with its full history.
- **Hover and click ×** to delete it. Deletion is immediate and permanent.
- **Click +** (top of sidebar) to start fresh.

A follow-up asked inside a thread keeps the context in the URL, not in the
model — each question is answered independently. That's a real limitation:
Jawab doesn't remember that "it" refers to what you asked two turns ago. Ask
with the noun included.

---

## Keyboard

| Key | Action |
|---|---|
| `Enter` | Ask |
| `Shift + Enter` | New line in the question box |
| `Esc` | Close the sidebar (mobile) |

---

## Mobile

The sidebar collapses behind the ☰ button. Everything else is the same. The
layout is built mobile-first, so the composer sits at the bottom where your
thumb is.

---

## What Jawab won't do

Worth knowing before you're disappointed:

- **It won't reason across sources.** If page A says X and page B says Y and
  the answer requires combining them, you'll get both sentences side by side
  and have to do the combining.
- **It won't paraphrase.** If the source says it awkwardly, the answer says
  it awkwardly. That's the price of every sentence being checkable.
- **It won't answer from memory.** No training data is involved. If the web
  doesn't say it, Jawab doesn't know it.
- **It won't remember your last question.** Each question is answered on its
  own terms.

---

## A worked example

Ask: `what is retrieval augmented generation and why does it reduce hallucination`

What comes back, roughly:

```
SUMMARY
Efforts to reduce or compensate for hallucinations have employed automated
reasoning, retrieval-augmented generation (RAG), fine-tuning, and other
methods. (5 sources)

BODY
Efforts to reduce or compensate for hallucinations have employed automated
reasoning, retrieval-augmented generation (RAG), fine-tuning, and other
methods.¹
Retrieval-augmented generation, used by many modern chatbots, reduces
hallucinations by allowing LLMs to access external sources before providing
information.²
Retrieval-augmented generation (RAG) is an approach that integrates LLMs with
document retrieval systems.³
...

META
91% confidence · 5 cited · 0.8s

SOURCES
1. en.wikipedia.org  ✓ cited
2. en.wikipedia.org  ✓ cited
3. en.wikipedia.org  ✓ cited
...
```

Note that the answer quotes rather than explains. If you want the explanation,
the sources are one click away — and that's the point.
