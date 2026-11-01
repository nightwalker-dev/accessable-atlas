#!/usr/bin/env python3
"""Secret scanner for working tree and git commit history."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Private Key Header", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("GitHub Personal Access Token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b")),
    ("Supabase Personal/Service Token", re.compile(r"\bsbp_[a-f0-9]{40}\b")),
    ("OpenAI Live Key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}\b")),
    ("AWS Access Key ID", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack Token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,48}\b")),
]

SKIP_DIRS = {".git", "__pycache__", "data", ".venv", "venv"}


def scan_working_tree() -> list[str]:
    findings: list[str] = []
    for path in ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts) or not path.is_file():
            continue
        if path.name == ".env":
            findings.append("Unignored .env file present in working tree.")
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = path.relative_to(ROOT)
        for label, pattern in SECRET_PATTERNS:
            match = pattern.search(content)
            if match:
                sample = match.group(0)
                masked = sample[:4] + "..." + sample[-3:]
                findings.append(f"{rel}: matched {label} ({masked})")
    return findings


def scan_git_history() -> list[str]:
    findings: list[str] = []
    res = subprocess.run(
        ["git", "log", "-p", "--all"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        return findings
    history_text = res.stdout
    for label, pattern in SECRET_PATTERNS:
        match = pattern.search(history_text)
        if match:
            sample = match.group(0)
            masked = sample[:4] + "..." + sample[-3:]
            findings.append(f"git history: matched {label} ({masked})")
    return findings


def main() -> int:
    tree_findings = scan_working_tree()
    hist_findings = scan_git_history()
    all_findings = tree_findings + hist_findings
    if all_findings:
        for f in all_findings:
            print(f"[SECRET-SCAN-FAIL] {f}", file=sys.stderr)
        return 1
    print("[OK] Secret scan passed: 0 hardcoded secrets in working tree or git history.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

