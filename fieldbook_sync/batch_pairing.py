from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable


_ROLE_WORDS = {
    "survey", "surveys", "points", "point", "pts", "raw", "data", "coords", "coordinates",
    "fieldbook", "fieldbooks", "field", "book", "books", "fb", "notes", "note", "scan", "scans",
    "photo", "photos", "image", "images", "img", "export", "input",
}
_PAGE_WORDS = {"page", "pg", "p"}


def _tokens(filename: str) -> list[str]:
    stem = Path(filename).stem.lower()
    return re.findall(r"[a-z]+|\d+", stem)


def batch_group_key(filename: str, role: str) -> str:
    """Return a conservative job key from a survey/field-book filename.

    Only generic role/page words are removed. Job numbers, client names, dates and other
    identifying tokens are retained, so unrelated files are not paired merely because they
    both contain words such as "survey" or "fieldbook".
    """
    tokens = _tokens(filename)
    cleaned: list[str] = []
    skip_next_page_number = False
    for token in tokens:
        if token in _ROLE_WORDS:
            continue
        if token in _PAGE_WORDS:
            skip_next_page_number = True
            continue
        if skip_next_page_number and token.isdigit() and len(token) <= 4:
            skip_next_page_number = False
            continue
        skip_next_page_number = False
        cleaned.append(token)
    return " ".join(cleaned).strip()


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    at, bt = set(a.split()), set(b.split())
    union = at | bt
    jaccard = len(at & bt) / len(union) if union else 0.0
    seq = SequenceMatcher(None, a, b).ratio()
    # Shared numeric job/order tokens are unusually strong evidence in survey filenames.
    nums_a = {t for t in at if t.isdigit() and len(t) >= 3}
    nums_b = {t for t in bt if t.isdigit() and len(t) >= 3}
    numeric_bonus = 0.18 if nums_a & nums_b else 0.0
    return min(1.0, 0.55 * jaccard + 0.45 * seq + numeric_bonus)


@dataclass(frozen=True)
class BatchPair:
    key: str
    survey_files: tuple[str, ...]
    fieldbook_files: tuple[str, ...]
    score: float
    method: str


@dataclass(frozen=True)
class BatchPairingResult:
    pairs: tuple[BatchPair, ...]
    unmatched_surveys: tuple[str, ...]
    unmatched_fieldbooks: tuple[str, ...]
    ambiguous_surveys: tuple[str, ...]


def _group(files: Iterable[str], role: str) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for name in files:
        key = batch_group_key(name, role)
        if not key:
            # Keep an unmatchable unique key instead of merging unrelated generic filenames.
            key = f"__unmatchable__:{Path(name).name.lower()}"
        groups.setdefault(key, []).append(name)
    return groups


def pair_batch_files(
    survey_files: Iterable[str],
    fieldbook_files: Iterable[str],
    *,
    min_score: float = 0.62,
    min_margin: float = 0.12,
) -> BatchPairingResult:
    """Pair raw survey files and field books without silently guessing ambiguous jobs.

    Exact normalized job keys are paired first. Remaining groups are paired only when one
    candidate is sufficiently similar *and* clearly better than the runner-up. Anything
    ambiguous is returned for manual renaming/reselection rather than being guessed.
    """
    surveys = _group(survey_files, "survey")
    books = _group(fieldbook_files, "fieldbook")
    pairs: list[BatchPair] = []
    used_books: set[str] = set()
    paired_surveys: set[str] = set()
    ambiguous: set[str] = set()

    # Exact normalized keys are deterministic.
    for skey, sfiles in surveys.items():
        if skey.startswith("__unmatchable__"):
            continue
        if skey in books:
            pairs.append(BatchPair(skey, tuple(sfiles), tuple(books[skey]), 1.0, "exact filename key"))
            paired_surveys.add(skey)
            used_books.add(skey)

    # Conservative fuzzy match for useful-but-not-identical names.
    for skey, sfiles in surveys.items():
        if skey in paired_surveys or skey.startswith("__unmatchable__"):
            continue
        ranked = sorted(
            ((_similarity(skey, bkey), bkey) for bkey in books if bkey not in used_books and not bkey.startswith("__unmatchable__")),
            reverse=True,
        )
        if not ranked:
            continue
        best_score, best_key = ranked[0]
        runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
        if best_score >= min_score and (best_score - runner_up) >= min_margin:
            pairs.append(BatchPair(skey, tuple(sfiles), tuple(books[best_key]), round(best_score, 3), "conservative filename similarity"))
            paired_surveys.add(skey)
            used_books.add(best_key)
        elif best_score >= min_score:
            ambiguous.add(skey)

    unmatched_surveys = tuple(
        name for key, names in surveys.items() if key not in paired_surveys for name in names
    )
    unmatched_fieldbooks = tuple(
        name for key, names in books.items() if key not in used_books for name in names
    )
    ambiguous_surveys = tuple(
        name for key in ambiguous for name in surveys.get(key, [])
    )
    return BatchPairingResult(tuple(pairs), unmatched_surveys, unmatched_fieldbooks, ambiguous_surveys)
