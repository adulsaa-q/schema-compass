"""Keyword search over table contracts.

Queries are split into words so that natural phrases ("invoice total",
"tracks by genre") match across table and column names instead of having to
equal one substring.
"""

import re
from dataclasses import dataclass

from schema_compass.models import TableContract

STOPWORDS = frozenset(
    {"a", "an", "and", "by", "for", "from", "in", "of", "on", "or", "per", "the", "to", "with"}
)

_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")

TABLE_NAME_SCORE = 10.0
EXACT_TABLE_NAME_BONUS = 10.0
TABLE_DESCRIPTION_SCORE = 3.0
COLUMN_NAME_SCORE = 5.0
COLUMN_DESCRIPTION_SCORE = 2.0
EXTRA_WORD_BONUS = 5.0


@dataclass(frozen=True)
class SearchHit:
    score: float
    contract: TableContract
    matched_columns: list[str]


def tokenize(text: str) -> list[str]:
    """Lower-cased words of `text`, splitting on camelCase, snake_case and punctuation."""
    words = (w.lower() for w in _WORD.findall(text))
    return [w for w in words if w not in STOPWORDS]


def _variants(word: str) -> tuple[str, ...]:
    """The word itself plus a naive singular, so "tracks" also finds "Track"."""
    if len(word) > 3 and word.endswith("s"):
        return (word, word[:-1])
    return (word,)


def _contains(haystack: str, variants: tuple[str, ...]) -> bool:
    return any(v in haystack for v in variants)


def search_contracts(contracts: list[TableContract], query: str, top_k: int = 5) -> list[SearchHit]:
    """Rank contracts by how many query words appear in table and column names/descriptions."""
    words = list(dict.fromkeys(tokenize(query)))
    if not words:
        return []

    # table names are compared with separators removed: "InvoiceLine" == "invoice line"
    query_keys = {"".join(words), "".join(words[:-1] + [_variants(words[-1])[-1]])}
    hits: list[SearchHit] = []
    for contract in contracts:
        name = contract.name.lower()
        description = (contract.description or "").lower()
        score = EXACT_TABLE_NAME_BONUS if "".join(tokenize(contract.name)) in query_keys else 0.0
        matched_columns: list[str] = []
        words_matched = 0

        for word in words:
            variants = _variants(word)
            word_score = 0.0
            if _contains(name, variants):
                word_score += TABLE_NAME_SCORE
            if description and _contains(description, variants):
                word_score += TABLE_DESCRIPTION_SCORE
            for col in contract.columns:
                if _contains(col.name.lower(), variants):
                    word_score += COLUMN_NAME_SCORE
                elif col.description and _contains(col.description.lower(), variants):
                    word_score += COLUMN_DESCRIPTION_SCORE
                else:
                    continue
                if col.name not in matched_columns:
                    matched_columns.append(col.name)
            if word_score:
                words_matched += 1
                score += word_score

        if words_matched:
            score += EXTRA_WORD_BONUS * (words_matched - 1)
            hits.append(SearchHit(score, contract, matched_columns))

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:top_k]
