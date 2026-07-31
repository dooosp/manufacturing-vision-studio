#!/usr/bin/env python3
"""Fail when unsafe or generated artifacts are tracked by Git."""

from __future__ import annotations

import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath

REPOSITORY = Path(__file__).resolve().parents[1]
MAX_TRACKED_BYTES = 10 * 1024 * 1024
MAX_SECRET_SCAN_BYTES = 2 * 1024 * 1024

ROOT_ONLY_DIRECTORIES = {
    "customer-data",
    "data",
    "mvtec",
    "mvtec-ad",
    "mvtec_anomaly_detection",
    "output",
    "private",
    "private-data",
    "tmp",
    "uploads",
}
FORBIDDEN_DIRECTORIES = {
    ".mypy_cache",
    ".playwright",
    ".playwright-cli",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "customer-data",
    "dist",
    "htmlcov",
    "node_modules",
    "playwright-report",
    "private",
    "private-data",
    "test-results",
    "uploads",
}
DATABASE_SUFFIXES = {
    ".db",
    ".db-shm",
    ".db-wal",
    ".sqlite",
    ".sqlite-shm",
    ".sqlite-wal",
    ".sqlite3",
    ".sqlite3-shm",
    ".sqlite3-wal",
}
MVTec_PAYLOAD_SUFFIXES = {
    ".7z",
    ".bmp",
    ".bz2",
    ".gz",
    ".jpeg",
    ".jpg",
    ".json",
    ".npz",
    ".pgm",
    ".png",
    ".ppm",
    ".tar",
    ".tif",
    ".tiff",
    ".xz",
    ".zip",
}
SENSITIVE_FILENAMES = {
    "credentials.json",
    "id_ed25519",
    "id_rsa",
    "secrets.json",
}
SENSITIVE_SUFFIXES = {".key", ".p12", ".pfx"}
SECRET_PATTERNS = {
    "private key material": re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?" + r"PRIVATE KEY-----"
    ),
    "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "GitHub legacy token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36,255}"),
    "GitHub fine-grained token": re.compile(r"github_pat_[A-Za-z0-9_]{60,255}"),
    "OpenAI API key": re.compile(r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}"),
    "Slack token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"),
    "Google API key": re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    "Stripe live secret": re.compile(r"sk_live_[0-9A-Za-z]{20,}"),
    "high-risk environment assignment": re.compile(
        r"(?im)^\s*(?:OPENAI_API_KEY|ANTHROPIC_API_KEY|GITHUB_TOKEN|GH_TOKEN|"
        r"AWS_SECRET_ACCESS_KEY|SLACK_TOKEN|SLACK_BOT_TOKEN|PRIVATE_KEY|SECRET_KEY|"
        r"API_KEY|ACCESS_TOKEN|AUTH_TOKEN|PASSWORD)\s*[:=]\s*[\"']?"
        r"(?!\$|<|YOUR_|REPLACE_|CHANGEME|EXAMPLE|DUMMY|TEST_)[^\s\"'#]{16,}"
    ),
}


def repository_paths() -> list[PurePosixPath]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
    )
    return [PurePosixPath(item.decode()) for item in result.stdout.split(b"\0") if item]


def path_violations(relative: PurePosixPath) -> list[str]:
    parts = tuple(part.lower() for part in relative.parts)
    basename = relative.name.lower()
    suffixes = "".join(relative.suffixes).lower()
    violations: list[str] = []

    if parts and (parts[0] in ROOT_ONLY_DIRECTORIES or parts[0].startswith("mvtec-")):
        violations.append("runtime, private, generated, or external dataset directory")
    if any(part in FORBIDDEN_DIRECTORIES for part in parts[:-1]):
        violations.append("generated, private, or upload directory")
    if basename == ".env" or (basename.startswith(".env.") and basename != ".env.example"):
        violations.append("environment file")
    if any(suffixes.endswith(suffix) for suffix in DATABASE_SUFFIXES):
        violations.append("runtime database")
    if basename in SENSITIVE_FILENAMES or relative.suffix.lower() in SENSITIVE_SUFFIXES:
        violations.append("credential or private-key file")
    if any("mvtec" in part for part in parts) and relative.suffix.lower() in MVTec_PAYLOAD_SUFFIXES:
        violations.append("MVTec dataset or derived payload")
    return violations


def content_violations(path: Path) -> list[str]:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        return ["symbolic link"]
    if not stat.S_ISREG(metadata.st_mode):
        return ["non-regular file"]

    violations: list[str] = []
    if metadata.st_size > MAX_TRACKED_BYTES:
        violations.append(f"file exceeds {MAX_TRACKED_BYTES} bytes")
    if metadata.st_size > MAX_SECRET_SCAN_BYTES:
        return violations

    content = path.read_bytes()
    if b"\0" in content:
        return violations
    text = content.decode("utf-8", errors="replace")
    for label, pattern in SECRET_PATTERNS.items():
        if pattern.search(text):
            violations.append(label)
    return violations


def main() -> int:
    failures: list[tuple[str, str]] = []
    paths = repository_paths()
    for relative in paths:
        rendered = relative.as_posix()
        for reason in path_violations(relative):
            failures.append((rendered, reason))

        absolute = REPOSITORY / relative
        if not absolute.exists() and not absolute.is_symlink():
            failures.append((rendered, "tracked path is missing from the worktree"))
            continue
        for reason in content_violations(absolute):
            failures.append((rendered, reason))

    if failures:
        print("Repository hygiene check failed:", file=sys.stderr)
        for path, reason in sorted(set(failures)):
            print(f"- {path}: {reason}", file=sys.stderr)
        return 1

    print(f"Repository hygiene check passed for {len(paths)} tracked or unignored files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
