#!/usr/bin/env python3
"""Sync spyrrow's Cargo.toml with the latest sparrow & jagua-rs revs.

Usage:
    python scripts/sync_sparrow.py                            # from GitHub
    python scripts/sync_sparrow.py --local-sparrow ../sparrow # from local checkout
    python scripts/sync_sparrow.py --dry-run                  # preview only
"""
# MARK: sync-script

import argparse, re, subprocess, sys
from pathlib import Path

CARGO_TOML = Path(__file__).resolve().parent.parent / "Cargo.toml"
SPARROW_REPO = "https://github.com/JeroenGar/sparrow.git"


def get_latest_sparrow_rev(local_path: str | None) -> str:
    if local_path:
        return subprocess.check_output(
            ["git", "-C", local_path, "rev-parse", "HEAD"], text=True
        ).strip()
    # ls-remote returns "<hash>\tHEAD"
    out = subprocess.check_output(
        ["git", "ls-remote", SPARROW_REPO, "HEAD"], text=True
    )
    return out.split()[0]


def get_jagua_rev_from_sparrow(sparrow_rev: str, local_path: str | None) -> str:
    if local_path:
        cargo = (Path(local_path) / "Cargo.toml").read_text()
    else:
        cargo = subprocess.check_output(
            ["git", "archive", f"--remote={SPARROW_REPO}", sparrow_rev, "Cargo.toml"],
            text=True,
        )
        # git archive may not work on GitHub; fall back to raw URL
        if not cargo.strip():
            import urllib.request
            url = f"https://raw.githubusercontent.com/JeroenGar/sparrow/{sparrow_rev}/Cargo.toml"
            cargo = urllib.request.urlopen(url).read().decode()

    m = re.search(r'jagua-rs\s*=\s*\{[^}]*rev\s*=\s*"([a-f0-9]+)"', cargo)
    if not m:
        sys.exit("Could not find jagua-rs rev in sparrow's Cargo.toml")
    return m.group(1)


def update_cargo_toml(sparrow_rev: str, jagua_rev: str, dry_run: bool) -> bool:
    text = CARGO_TOML.read_text()
    original = text

    text = re.sub(
        r'(sparrow\s*=\s*\{[^}]*rev\s*=\s*")[a-f0-9]+(")',
        rf"\g<1>{sparrow_rev}\2",
        text,
    )
    text = re.sub(
        r'(jagua-rs\s*=\s*\{[^}]*rev\s*=\s*")[a-f0-9]+(")',
        rf"\g<1>{jagua_rev}\2",
        text,
    )

    if text == original:
        print("Already up to date.")
        return False

    print(f"sparrow → {sparrow_rev[:12]}")
    print(f"jagua-rs → {jagua_rev[:12]}")
    if not dry_run:
        CARGO_TOML.write_text(text)
        print("Cargo.toml updated.")
    else:
        print("(dry run — no files changed)")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--local-sparrow", help="Path to local sparrow checkout")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sparrow_rev = get_latest_sparrow_rev(args.local_sparrow)
    jagua_rev = get_jagua_rev_from_sparrow(sparrow_rev, args.local_sparrow)
    update_cargo_toml(sparrow_rev, jagua_rev, args.dry_run)


if __name__ == "__main__":
    main()
