"""Entry point that wires the pieces together."""

import argparse

from config.settings import AUDIT_STORE_DIR
from engine.bounded_loop import BoundedLoop
from reporting.report_builder import ReportBuilder


def main() -> None:
    parser = argparse.ArgumentParser(description="Anti-forensic behavior analysis agent")
    parser.add_argument("case_path", help="Path to the acquired artifact set to analyze")
    args = parser.parse_args()

    loop = BoundedLoop()
    memory = loop.run(args.case_path)

    report = ReportBuilder(memory, str(AUDIT_STORE_DIR)).build()
    print(report)


if __name__ == "__main__":
    main()
