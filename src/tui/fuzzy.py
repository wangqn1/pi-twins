# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, TypeVar


@dataclass(frozen=True)
class FuzzyMatch:
    matches: bool
    score: float


def fuzzy_match(query: str, text: str) -> FuzzyMatch:
    query_lower = query.lower()
    text_lower = text.lower()

    def match_query(normalized_query: str) -> FuzzyMatch:
        if not normalized_query:
            return FuzzyMatch(matches=True, score=0)
        if len(normalized_query) > len(text_lower):
            return FuzzyMatch(matches=False, score=0)

        query_index = 0
        score = 0.0
        last_match_index = -1
        consecutive_matches = 0

        for index, char in enumerate(text_lower):
            if query_index >= len(normalized_query):
                break
            if char != normalized_query[query_index]:
                continue

            is_word_boundary = index == 0 or text_lower[index - 1] in " -_./:"
            if last_match_index == index - 1:
                consecutive_matches += 1
                score -= consecutive_matches * 5
            else:
                consecutive_matches = 0
                if last_match_index >= 0:
                    score += (index - last_match_index - 1) * 2

            if is_word_boundary:
                score -= 10
            score += index * 0.1
            last_match_index = index
            query_index += 1

        if query_index < len(normalized_query):
            return FuzzyMatch(matches=False, score=0)
        return FuzzyMatch(matches=True, score=score)

    primary = match_query(query_lower)
    if primary.matches:
        return primary

    alpha_numeric = re.match(r"^(?P<letters>[a-z]+)(?P<digits>[0-9]+)$", query_lower)
    numeric_alpha = re.match(r"^(?P<digits>[0-9]+)(?P<letters>[a-z]+)$", query_lower)
    swapped_query = ""
    if alpha_numeric:
        swapped_query = f"{alpha_numeric.group('digits')}{alpha_numeric.group('letters')}"
    elif numeric_alpha:
        swapped_query = f"{numeric_alpha.group('letters')}{numeric_alpha.group('digits')}"

    if not swapped_query:
        return primary

    swapped = match_query(swapped_query)
    if not swapped.matches:
        return primary
    return FuzzyMatch(matches=True, score=swapped.score + 5)


T = TypeVar("T")


def fuzzy_filter(items: list[T], query: str, get_text: Callable[[T], str]) -> list[T]:
    if not query.strip():
        return items

    tokens = [token for token in query.strip().split() if token]
    if not tokens:
        return items

    results: list[tuple[float, T]] = []
    for item in items:
        text = get_text(item)
        total_score = 0.0
        for token in tokens:
            match = fuzzy_match(token, text)
            if not match.matches:
                break
            total_score += match.score
        else:
            results.append((total_score, item))

    results.sort(key=lambda item: item[0])
    return [item for _, item in results]
