"""CLI entry point for WizTry disk space analyzer."""

import argparse
import json
import os
import sys

from wiztry.scanner import clean_root
from wiztry.scanner import timed_scan
from wiztry.scanner import summary


def main(argv=None):
    """Run a scan from the command line and write the JSON report."""
    parser = argparse.ArgumentParser(prog="WizTry")
    parser.add_argument("--scan", required=True, help="Folder to scan")
    parser.add_argument("--json", required=True, help="Report file path")
    args = parser.parse_args(argv)

    root = clean_root(args.scan)
    top, skipped, seconds = timed_scan(root)
    report = summary(top, skipped, seconds)

    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)

    return 0


if __name__ == "__main__":
    sys.exit(main())
