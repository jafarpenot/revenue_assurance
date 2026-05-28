"""
Phase 3 — End-to-end demo runner.

Loads .env, runs the orchestrator (which delegates to investigators), prints
the final executive report. Full reasoning trail goes to agent_trace.log.
"""

import os
import sys
import time

from dotenv import load_dotenv


def main():
    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not found in .env or environment.", file=sys.stderr)
        sys.exit(1)

    # Import after env is loaded so the Anthropic client picks up the key
    from agents import run_orchestrator, init_log, close_log

    log_path = "agent_trace.log"
    billing_period = "April 2026"

    print()
    print("┌" + "─" * 76)
    print(f"│ B2B Revenue Assurance — agentic scan for {billing_period}")
    print(f"│ Full trace will be written to: {log_path}")
    print("└" + "─" * 76)

    init_log(log_path)
    start = time.time()
    try:
        report = run_orchestrator(billing_period)
    finally:
        close_log()
    elapsed = time.time() - start

    print()
    print("=" * 78)
    print(f"  B2B REVENUE ASSURANCE REPORT — {billing_period}")
    print("=" * 78)
    print()
    print(report.strip())
    print()
    print("=" * 78)
    print(f"  Runtime: {elapsed:.1f}s   |   Full reasoning trail: {log_path}")
    print("=" * 78)


if __name__ == "__main__":
    main()
