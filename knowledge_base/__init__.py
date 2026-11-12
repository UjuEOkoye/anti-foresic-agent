"""
knowledge_base/ — box 6.2's companion: the agent's general forensic "textbook".

This package holds GENERAL domain knowledge (behavior classes, generic indicators,
normal-behavior baselines) that is true across ALL cases — NOT facts about any one
case (those live in engine/case_memory.py), and NEVER app names (that would make the
agent a signature-matcher instead of a behavior-based detector).
"""
from knowledge_base.kb import KnowledgeCard, KnowledgeBase, build_knowledge_base

__all__ = ["KnowledgeCard", "KnowledgeBase", "build_knowledge_base"]