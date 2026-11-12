"""T04: the command line for WizTry - scan a folder and write a JSON report."""
import argparse
import json

from wiztry.scanner import summary, timed_scan


def main(argv: list[str] | None = None) -> int:
    """Run a scan from the command line and write the report; returns 0."""
    parser = argparse.ArgumentParser(prog="WizTry")
    parser.add_argument("--scan", required=True, help="the folder to scan")
    parser.add_argument("--json", required=True, help="the report file to write")
    args = parser.parse_args(argv)
    top, skipped, seconds = timed_scan(args.scan)
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(summary(top, skipped, seconds), f, indent=1, ensure_ascii=False)
    return 0
