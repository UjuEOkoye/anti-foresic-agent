"""
knowledge_base/kb.py — box 6.2's companion (logic only; content lives in cards.py).

The agent's general forensic "textbook". It can be asked a question and it returns
the few most relevant cards to drop into the agent's reasoning context (RAG).

v1 retrieval is deliberately SIMPLE and DETERMINISTIC: score each card by how many
of the question's words it matches (keywords + title + summary + indicators), and
return the top few. No embeddings / vector DB yet — that is a noted future upgrade,
and keeping it simple makes it testable and easy to understand.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import re


# words too common to be useful for matching (kept tiny on purpose)
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "of", "to", "in", "on", "for",
    "and", "or", "it", "this", "that", "with", "as", "by", "be", "can", "could",
    "does", "do", "did", "has", "have", "had", "what", "which", "any", "some",
    "i", "we", "you", "they", "there", "here", "not",  # 'not' is a stopword for scoring
}


def _tokenize(text: str) -> set[str]:
    """Lowercase, split into words, drop stopwords and 1-character tokens."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if len(w) > 1 and w not in _STOPWORDS}


@dataclass
class KnowledgeCard:
    """One textbook entry. GENERAL knowledge — never about a specific case or app."""
    card_id: str
    title: str
    category: str                               # see cards.py for the allowed set
    summary: str
    indicators: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    def _strong_tokens(self) -> set[str]:
        """Words that should count DOUBLE — the card's title, keywords, and category.
        These are deliberately chosen, so a match here is a strong signal."""
        return _tokenize(" ".join([self.title, " ".join(self.keywords), self.category]))

    def _weak_tokens(self) -> set[str]:
        """Words from the body (summary + indicators) — count single. These can match
        incidentally (e.g. a baseline card that happens to say 'not overwritten')."""
        return _tokenize(" ".join([self.summary, " ".join(self.indicators)]))

    def _score(self, query_tokens: set[str]) -> int:
        """Relevance: a keyword/title hit is worth 2, a body hit is worth 1."""
        return 2 * len(query_tokens & self._strong_tokens()) + len(query_tokens & self._weak_tokens())


class KnowledgeBase:
    """A small, searchable collection of KnowledgeCards."""

    def __init__(self, cards: list[KnowledgeCard]) -> None:
        self.cards = list(cards)

    def all_cards(self) -> list[KnowledgeCard]:
        return list(self.cards)

    def by_category(self, category: str) -> list[KnowledgeCard]:
        return [c for c in self.cards if c.category == category]

    def retrieve(self, query: str, k: int = 3) -> list[KnowledgeCard]:
        """
        Return the up-to-k cards most relevant to `query`, best first.
        Score = how many of the query's words the card matches. Cards that match
        nothing are dropped. Ties break by card_id so results are deterministic.
        """
        q = _tokenize(query)
        scored: list[tuple[int, KnowledgeCard]] = []
        for card in self.cards:
            score = card._score(q)
            if score > 0:
                scored.append((score, card))
        scored.sort(key=lambda sc: (-sc[0], sc[1].card_id))
        return [card for _, card in scored[:k]]

    def as_prompt_block(self, cards: list[KnowledgeCard]) -> str:
        """
        Render retrieved cards as a compact block for the agent's context. Labelled
        clearly as GENERAL knowledge so the agent never mistakes it for case evidence.
        """
        if not cards:
            return "RELEVANT FORENSIC KNOWLEDGE (general): (none retrieved)"
        lines = ["RELEVANT FORENSIC KNOWLEDGE (general background — NOT evidence from this case):"]
        for c in cards:
            lines.append(f"- [{c.category}] {c.title}: {c.summary}")
            if c.indicators:
                lines.append("    indicators: " + "; ".join(c.indicators))
        return "\n".join(lines)


def build_knowledge_base() -> KnowledgeBase:
    """The single place the knowledge base is assembled (mirrors tools/registry.py)."""
    from knowledge_base.cards import STARTER_CARDS
    return KnowledgeBase(STARTER_CARDS)