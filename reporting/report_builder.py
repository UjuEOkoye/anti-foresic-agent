"""Assembles the final forensic report from case memory and the audit store."""

from engine.case_memory import CaseMemory


class ReportBuilder:
    def __init__(self, memory: CaseMemory, audit_store_dir: str):
        self.memory = memory
        self.audit_store_dir = audit_store_dir

    def build(self) -> str:
        """Return the final report as Markdown."""
        raise NotImplementedError
