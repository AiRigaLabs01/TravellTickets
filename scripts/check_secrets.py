"""Focused credential guard for tracked files/history; never prints matched values.

This is not a comprehensive secret detector. Provider-side secret scanning and
an operator audit/rotation of credentials are still required before migration.
"""

import argparse
import re
import subprocess
from pathlib import Path


PATTERNS = {
    "private-key": re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    "github-token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{50,255})\b"),
    "telegram-token": re.compile(rb"\b[0-9]{6,12}:[A-Za-z0-9_-]{35}\b"),
    "aws-access-key": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "provider-token-assignment": re.compile(
        rb"(?im)^\s*(?:TRAVELPAYOUTS_TOKEN|TELEGRAM_BOT_TOKEN|SESSION_SECRET|POSTGRES_PASSWORD)"
        rb"\s*=\s*[\"']?[A-Za-z0-9_+/=-]{24,}[\"']?\s*$"
    ),
    "database-password-url": re.compile(rb"postgres(?:ql)?://[^\s/:]+:[^\s/@$<>\"']{8,}@"),
}


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args])


def findings(data: bytes) -> list[tuple[str, int]]:
    return [
        (rule, data.count(b"\n", 0, match.start()) + 1)
        for rule, pattern in PATTERNS.items()
        for match in pattern.finditer(data)
    ]


def forbidden_path(path: str) -> bool:
    parts = Path(path).parts
    name = Path(path).name
    return (
        "operator" in parts or ".ssh" in parts
        or name == "vps_secrets.txt"
        or (name == ".env" or name.startswith(".env.")) and not name.endswith(".example")
        or name.endswith((".pem", ".key"))
    )


def scan(history: bool = False) -> int:
    root = Path(git("rev-parse", "--show-toplevel").decode().strip())
    count = 0
    files = git("ls-files", "-z").decode().split("\0")
    for path in filter(None, files):
        if forbidden_path(path):
            print(f"FAIL forbidden tracked path: {path}")
            count += 1
        source = root / path
        if source.is_file():
            for rule, line in findings(source.read_bytes()):
                print(f"FAIL {path}:{line}: {rule} [REDACTED]")
                count += 1

    blob_count = 0
    if history:
        objects = git("rev-list", "--objects", "--all").decode().splitlines()
        process = subprocess.Popen(
            ["git", "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        )
        try:
            for obj in objects:
                oid, _, path = obj.partition(" ")
                process.stdin.write(oid.encode() + b"\n")
                process.stdin.flush()
                header = process.stdout.readline().split()
                size = int(header[2])
                data = process.stdout.read(size)
                process.stdout.read(1)
                if header[1] != b"blob":
                    continue
                blob_count += 1
                if forbidden_path(path):
                    print(f"FAIL history {oid[:12]} {path}: forbidden path")
                    count += 1
                for rule, line in findings(data):
                    print(f"FAIL history {oid[:12]} {path}:{line}: {rule} [REDACTED]")
                    count += 1
        finally:
            process.stdin.close()
            process.wait()
    print(f"Scanned tracked files; history blobs={blob_count}; findings={count}.")
    return 1 if count else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true", help="also scan all locally reachable Git history")
    raise SystemExit(scan(parser.parse_args().history))
