from __future__ import annotations

import re


ASCII_TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9]+")
CJK_SEQUENCE_PATTERN = re.compile(r"[\u4e00-\u9fff]+")


def normalize_text(text: str) -> str:
    return " ".join(text.strip().lower().split())


def extract_ascii_tokens(text: str) -> list[str]:
    return [token.lower() for token in ASCII_TOKEN_PATTERN.findall(text)]


def extract_cjk_sequences(text: str) -> list[str]:
    return CJK_SEQUENCE_PATTERN.findall(text)


def extract_cjk_ngrams(text: str, sizes: tuple[int, ...] = (2, 3)) -> list[str]:
    ngrams: list[str] = []
    for sequence in extract_cjk_sequences(text):
        if len(sequence) == 1:
            ngrams.append(sequence)
            continue
        for size in sizes:
            if len(sequence) < size:
                continue
            for index in range(len(sequence) - size + 1):
                ngrams.append(sequence[index : index + size])
    return ngrams


def build_search_terms(text: str) -> list[str]:
    normalized = normalize_text(text)
    terms: list[str] = []
    seen: set[str] = set()

    for term in extract_ascii_tokens(normalized):
        if term not in seen:
            terms.append(term)
            seen.add(term)

    for sequence in extract_cjk_sequences(normalized):
        if sequence not in seen:
            terms.append(sequence)
            seen.add(sequence)

    for ngram in extract_cjk_ngrams(normalized):
        if ngram not in seen:
            terms.append(ngram)
            seen.add(ngram)

    return terms
