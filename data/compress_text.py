"""PDF text compression before an extraction call. No document cap.

Stages, each added on top of the previous one:
- unwrap: ligatures, line-break hyphens, collapsed whitespace
- boilerplate: arXiv stamp, page numbers, repeated running headers
- references: drop the bibliography (Grobid-style section cut)
- citations: drop numeric and author-year citation markers
- stopwords: basic English stopwords, negation words kept
"""

import re

# NLTK/sklearn-style function words. Negation stays: not, no, nor, neither,
# never, none, nothing, nobody, nowhere, without, cannot, and the n't forms.
STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "as", "at", "be", "because", "been", "before", "being", "below",
    "between", "both", "but", "by", "can", "could", "did", "do", "does", "doing",
    "down", "during", "each", "few", "for", "from", "further", "had", "has", "have",
    "having", "he", "her", "here", "hers", "herself", "him", "himself", "his", "how",
    "i", "if", "in", "into", "is", "it", "its", "itself", "just", "me", "more",
    "most", "my", "myself", "of", "off", "on", "once", "only", "or", "other", "our",
    "ours", "ourselves", "out", "over", "own", "same", "she", "should", "so", "some",
    "such", "than", "that", "the", "their", "theirs", "them", "themselves", "then",
    "there", "these", "they", "this", "those", "through", "to", "too", "under",
    "until", "up", "very", "was", "we", "were", "what", "when", "where", "which",
    "while", "who", "whom", "why", "will", "with", "would", "you", "your", "yours",
    "yourself", "yourselves",
}

LIGATURES = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
}

ARXIV_STAMP = re.compile(r"^arXiv:\s*\d{4}\.\d{4,5}", re.I)
PAGE_NUMBER = re.compile(r"^\d{1,3}$")
REF_HEADING = re.compile(
    r"^[^A-Za-z]*(references|bibliography|works cited)\s*$",
    re.I,
)
NUMERIC_CITE = re.compile(r"\[(?:\d+\s*[,–\-]\s*)*\d+\]")
AUTHOR_YEAR = re.compile(
    r"\((?:e\.g\.,?\s*|see\s+)?"
    r"(?:[A-Z][A-Za-z'\-]+(?:\s+et\s+al\.?)?(?:\s+(?:and|&)\s+[A-Z][A-Za-z'\-]+)?,\s*)+"
    r"\d{4}[a-z]?"
    r"(?:\s*;\s*(?:[A-Z][A-Za-z'\-]+(?:\s+et\s+al\.?)?,?\s*)*\d{4}[a-z]?)*"
    r"\)"
)
AUTHOR_PAREN_YEAR = re.compile(
    r"\b[A-Z][A-Za-z'\-]+(?:\s+(?:and|&)\s+[A-Z][A-Za-z'\-]+)?(?:\s+et\s+al\.?)?\s*\(\d{4}[a-z]?\)"
)
WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?|[^A-Za-z]+")


def page_lines(page):
    text = page.get_text("text")
    return [line.strip() for line in text.splitlines()]


def repeated_lines(pages):
    from collections import Counter

    counts = Counter()
    for lines in pages:
        for line in {ln for ln in lines if 12 <= len(ln) <= 140}:
            counts[line] += 1
    need = max(3, int(0.3 * len(pages)))
    return {line for line, n in counts.items() if n >= need}


def strip_boilerplate(pages):
    banners = repeated_lines(pages)
    cleaned = []
    for lines in pages:
        kept = []
        for line in lines:
            if not line:
                kept.append("")
                continue
            if ARXIV_STAMP.match(line) or PAGE_NUMBER.match(line) or line in banners:
                continue
            kept.append(line)
        cleaned.append(kept)
    return cleaned


def drop_references(pages):
    flat = []
    for lines in pages:
        flat.extend(lines)
        flat.append("")
    start = int(len(flat) * 0.45)
    cut = None
    for i in range(start, len(flat)):
        if REF_HEADING.match(flat[i] or ""):
            cut = i
    if cut is None:
        return flat
    return flat[:cut]


def unwrap(lines):
    text = "\n".join(lines)
    for src, dst in LIGATURES.items():
        text = text.replace(src, dst)
    text = re.sub(r"([A-Za-z])-\n([a-z])", r"\1\2", text)
    paragraphs = re.split(r"\n\s*\n", text)
    joined = []
    for paragraph in paragraphs:
        piece = re.sub(r"[ \t]*\n[ \t]*", " ", paragraph)
        piece = re.sub(r"[ \t]{2,}", " ", piece).strip()
        if piece:
            joined.append(piece)
    return "\n".join(joined)


def strip_citations(text):
    text = NUMERIC_CITE.sub("", text)
    text = AUTHOR_YEAR.sub("", text)
    text = AUTHOR_PAREN_YEAR.sub("", text)
    return re.sub(r"[ \t]{2,}", " ", text)


def strip_stopwords(text):
    parts = []
    for match in WORD.finditer(text):
        token = match.group(0)
        if token.isalpha() and token.lower() in STOPWORDS:
            continue
        parts.append(token)
    text = "".join(parts)
    text = re.sub(r"(?:\s*-\s*){2,}", "-", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def stages_from_pages(pages):
    """Cumulative stages. Extraction uses compress_pdf, which returns stopwords only."""
    boiled_pages = strip_boilerplate(pages)
    unwrapped = unwrap([line for lines in pages for line in lines])
    boiled = unwrap([line for lines in boiled_pages for line in lines])
    no_refs_lines = drop_references(boiled_pages)
    no_refs = unwrap(no_refs_lines)
    no_cites = strip_citations(no_refs)
    stopped = strip_stopwords(no_cites)
    return {
        "unwrap": unwrapped,
        "boilerplate": boiled,
        "no_references": no_refs,
        "no_citations": no_cites,
        "stopwords": stopped,
    }


def compress_pdf(pages):
    """The only PDF text the extractor sends. Full stack, including stopwords."""
    return stages_from_pages(pages)["stopwords"]


def compress_abstract(text):
    """Same stopword pass as the PDF. No bibliography cut: an abstract is one block."""
    if not text:
        return ""
    return strip_stopwords(unwrap([text]))


def split_sentences(text):
    sentences = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        for part in re.split(r"(?<=[.!?])\s+", para):
            part = part.strip()
            if part:
                sentences.append(part)
    return sentences


def extraction_document(abstract, pages):
    """Numbered sentences the model sees, and the same list used to check spans."""
    body = "\n".join(
        part
        for part in ("ABSTRACT", compress_abstract(abstract), "PAPER", compress_pdf(pages))
        if part
    )
    return split_sentences(body)
