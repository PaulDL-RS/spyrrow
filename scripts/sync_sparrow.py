#!/usr/bin/env python3
"""Sync spyrrow's Cargo.toml with the latest sparrow rev and the jagua-rs version it requires.

Usage:
    python scripts/sync_sparrow.py                            # from GitHub
    python scripts/sync_sparrow.py --local-sparrow ../sparrow # from local checkout
    python scripts/sync_sparrow.py --rev <sha>                # pin a specific sparrow commit
    python scripts/sync_sparrow.py --dry-run                  # preview only
"""
# MARK: sync-script

import argparse
import re
import subprocess
import sys
import tomllib
import urllib.request
from pathlib import Path

CARGO_TOML = Path(__file__).resolve().parent.parent / "Cargo.toml"
SPARROW_REPO = "https://github.com/JeroenGar/sparrow.git"
SPARROW_RAW = "https://raw.githubusercontent.com/JeroenGar/sparrow/{rev}/Cargo.toml"

# Only match active (non commented) dependency lines, a table may span several lines
SPARROW_DEP_RE = re.compile(r'(?m)^(sparrow\s*=\s*\{[^}]*?rev\s*=\s*")([a-f0-9]+)(")')
JAGUA_DEP_RE = re.compile(r"(?m)^jagua-rs\s*=\s*\{[^}]*\}")


def get_latest_sparrow_rev(local_path: str | None) -> str:
    if local_path:
        return subprocess.check_output(
            ["git", "-C", local_path, "rev-parse", "HEAD"], text=True
        ).strip()
    # ls-remote returns "<hash>\tHEAD"
    out = subprocess.check_output(["git", "ls-remote", SPARROW_REPO, "HEAD"], text=True)
    return out.split()[0]


def get_sparrow_cargo_toml(sparrow_rev: str, local_path: str | None) -> dict:
    if local_path:
        text = subprocess.check_output(
            ["git", "-C", local_path, "show", f"{sparrow_rev}:Cargo.toml"], text=True
        )
    else:
        # `git archive --remote` is not supported by GitHub, use the raw file endpoint instead
        with urllib.request.urlopen(SPARROW_RAW.format(rev=sparrow_rev), timeout=30) as resp:
            text = resp.read().decode()
    return tomllib.loads(text)


def jagua_dep_line(sparrow_cargo: dict) -> str:
    """Build spyrrow's jagua-rs dependency line from the spec used by sparrow."""
    spec = sparrow_cargo.get("dependencies", {}).get("jagua-rs")
    if spec is None:
        sys.exit("Could not find jagua-rs in sparrow's Cargo.toml")
    if isinstance(spec, str):
        spec = {"version": spec}
    features = sorted(set(spec.get("features", [])) | {"spp"})
    features_str = ", ".join(f'"{f}"' for f in features)
    if "git" in spec:
        ref = next((k for k in ("rev", "tag", "branch") if k in spec), None)
        ref_str = f', {ref} = "{spec[ref]}"' if ref else ""
        return f'jagua-rs = {{ git = "{spec["git"]}"{ref_str}, features = [{features_str}] }}'
    if "version" in spec:
        return f'jagua-rs = {{ features = [{features_str}], version = "{spec["version"]}" }}'
    sys.exit(f"Unsupported jagua-rs dependency spec in sparrow: {spec!r}")


def update_cargo_toml(sparrow_rev: str, jagua_line: str, dry_run: bool) -> bool:
    text = CARGO_TOML.read_text()
    original = text

    text, n = SPARROW_DEP_RE.subn(rf"\g<1>{sparrow_rev}\g<3>", text)
    if n != 1:
        sys.exit(f"Expected exactly one sparrow git dependency in {CARGO_TOML}, found {n}")
    text, n = JAGUA_DEP_RE.subn(jagua_line, text)
    if n != 1:
        sys.exit(f"Expected exactly one jagua-rs dependency in {CARGO_TOML}, found {n}")

    if text == original:
        print("Already up to date.")
        return False

    print(f"sparrow  → {sparrow_rev[:12]}")
    print(f"jagua-rs → {jagua_line}")
    if not dry_run:
        CARGO_TOML.write_text(text)
        print("Cargo.toml updated.")
    else:
        print("(dry run — no files changed)")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local-sparrow", help="Path to local sparrow checkout")
    ap.add_argument("--rev", help="Sparrow commit to sync to (defaults to the latest HEAD)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sparrow_rev = args.rev or get_latest_sparrow_rev(args.local_sparrow)
    sparrow_cargo = get_sparrow_cargo_toml(sparrow_rev, args.local_sparrow)
    update_cargo_toml(sparrow_rev, jagua_dep_line(sparrow_cargo), args.dry_run)


if __name__ == "__main__":
    main()
