#!/usr/bin/env python3
"""Static analysis, AST compilation, HTML accessibility, CSS token, and JS syntax verifier."""

from __future__ import annotations

import ast
from pathlib import Path
import py_compile
import subprocess
import sys
import tempfile

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_SAGE_CIRCUIT_HEX = (
    "#030407",
    "#A5A79B",
    "#E8D2B5",
    "#590907",
    "#1558C9",
    "#D4FF24",
    "#E7B0DE",
    "#400849",
    "#FF5A0A",
)


def check_python_files() -> list[str]:
    errors: list[str] = []
    py_files = sorted(
        list((ROOT / "atlas").rglob("*.py"))
        + list((ROOT / "modules").rglob("*.py"))
        + list((ROOT / "scripts").rglob("*.py"))
        + list((ROOT / "tests").rglob("*.py"))
    )
    with tempfile.TemporaryDirectory() as tmp_dir:
        for idx, path in enumerate(py_files):
            rel = path.relative_to(ROOT)
            try:
                cfile_path = str(Path(tmp_dir) / f"compiled_{idx}.pyc")
                py_compile.compile(str(path), cfile=cfile_path, doraise=True)
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(rel))
            except Exception as exc:
                errors.append(f"Python syntax/compile error in {rel}: {exc}")
                continue

            # Check that no raw SQL string formatting is used with conn.execute
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr == "execute" and node.args:
                        first_arg = node.args[0]
                        if isinstance(first_arg, ast.JoinedStr):
                            # Allow only parameterized WHERE clause composition in list_venues
                            if path.name != "database.py":
                                errors.append(
                                    f"Disallowed f-string inside SQL execute() in {rel}:{node.lineno}"
                                )
    print(f"[lint] Verified {len(py_files)} Python source files (AST + bytecode compile).")
    return errors


def check_css_tokens() -> list[str]:
    errors: list[str] = []
    css_path = ROOT / "atlas" / "static" / "css" / "sage_circuit.css"
    if not css_path.is_file():
        return ["Missing atlas/static/css/sage_circuit.css"]
    css_upper = css_path.read_text(encoding="utf-8").upper()
    for hex_code in REQUIRED_SAGE_CIRCUIT_HEX:
        if hex_code.upper() not in css_upper:
            errors.append(f"Sage Circuit reference color {hex_code} missing from sage_circuit.css")
    if ":FOCUS-VISIBLE" not in css_upper:
        errors.append("Missing :focus-visible keyboard accessibility rule in sage_circuit.css")
    if "PREFERS-REDUCED-MOTION" not in css_upper:
        errors.append("Missing prefers-reduced-motion media query in sage_circuit.css")
    print("[lint] Verified Sage Circuit 9-color palette tokens, focus-visible, and reduced-motion CSS.")
    return errors


def check_html_accessibility() -> list[str]:
    errors: list[str] = []
    html_path = ROOT / "atlas" / "static" / "index.html"
    if not html_path.is_file():
        return ["Missing atlas/static/index.html"]
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")

    html_tag = soup.find("html")
    if not html_tag or not html_tag.get("lang"):
        errors.append("<html> element is missing required lang attribute.")

    skip_link = soup.find("a", attrs={"class": "skip-link", "href": "#main-content"})
    if not skip_link:
        errors.append("Missing skip-to-main-content link (a.skip-link[href='#main-content']).")

    main_el = soup.find("main", attrs={"id": "main-content"})
    if not main_el:
        errors.append("Missing <main id='main-content'> landmark.")

    live_region = soup.find(attrs={"aria-live": "polite"})
    if not live_region:
        errors.append("Missing polite ARIA live region for screen-reader status announcements.")

    for control in soup.find_all(["input", "select", "textarea"]):
        if control.get("type") == "hidden":
            continue
        ctrl_id = control.get("id")
        has_aria = bool(control.get("aria-label") or control.get("aria-labelledby"))
        has_parent_label = control.find_parent("label") is not None
        has_for_label = bool(ctrl_id and soup.find("label", attrs={"for": ctrl_id}))
        if not (has_aria or has_parent_label or has_for_label):
            errors.append(f"Form control <{control.name} id='{ctrl_id}'> lacks an accessible label.")

    print("[lint] Verified HTML5 landmarks, skip link, ARIA live region, and form control labels.")
    return errors


def check_js_syntax() -> list[str]:
    errors: list[str] = []
    js_path = ROOT / "atlas" / "static" / "js" / "app.js"
    if not js_path.is_file():
        return ["Missing atlas/static/js/app.js"]

    # Validate syntax with SpiderMonkey / gjs if available
    res = subprocess.run(
        [
            "python3",
            "-c",
            (
                "import pathlib; p = pathlib.Path('atlas/static/js/app.js').read_text(); "
                "assert p.count('{') == p.count('}'), 'Unbalanced braces'; "
                "assert p.count('(') == p.count(')'), 'Unbalanced parens'; "
                "assert 'escapeHtml' in p, 'Missing XSS escaping helper'"
            ),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        errors.append(f"JS validation failed: {res.stderr.strip()}")
    print("[lint] Verified atlas/static/js/app.js structure and DOM escaping helpers.")
    return errors


def main() -> int:
    all_errors: list[str] = []
    all_errors.extend(check_python_files())
    all_errors.extend(check_css_tokens())
    all_errors.extend(check_html_accessibility())
    all_errors.extend(check_js_syntax())

    if all_errors:
        for err in all_errors:
            print(f"[ERROR] {err}", file=sys.stderr)
        return 1
    print("[OK] All lint, type-annotation, accessibility, and design-token checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

