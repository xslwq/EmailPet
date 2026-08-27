#!/usr/bin/env python3
"""Validate EmailPet's living documentation baseline with the Python stdlib."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parent.parent
REQUIRED_PATHS = (
    "AGENTS.md",
    "progress.md",
    "README.md",
    "backend/README.md",
    "frontend/README.md",
    "docs/README.md",
    "docs/product.md",
    "docs/architecture.md",
    "docs/contracts.md",
    "docs/development.md",
    "docs/decisions/README.md",
)
REQUIRED_PROGRESS_FIELDS = (
    "状态",
    "开始时间",
    "当前分支",
    "基准提交",
    "目标",
    "范围",
    "Session 开始前工作区",
    "已完成",
    "剩余事项",
    "关键决策",
    "验证结果",
    "文档影响",
    "现场清理",
    "下一步",
)
TEXT_SUFFIXES = {".md", ".py", ".ts", ".tsx", ".yaml", ".yml", ".toml", ".json"}
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
LEGACY_REFERENCE = re.compile(
    r"(?:See\s+|\]\()(?P<path>docs/modules/[A-Za-z0-9_./-]+\.md)"
)
PROGRESS_FIELD = re.compile(r"^-\s+([^：]+)：\s*(.*)$")
EXTERNAL_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def git_paths(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
    )
    return [part.decode("utf-8") for part in result.stdout.split(b"\0") if part]


def repository_text_files() -> list[Path]:
    """Return tracked and visible untracked text files, excluding ignored files."""
    try:
        names = git_paths("ls-files", "-z", "--cached", "--others", "--exclude-standard")
    except (FileNotFoundError, subprocess.CalledProcessError):
        names = [str(path.relative_to(ROOT)) for path in ROOT.rglob("*") if path.is_file()]
    return sorted(
        path
        for name in names
        if (path := ROOT / name).is_file() and path.suffix.lower() in TEXT_SUFFIXES
    )


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path.relative_to(ROOT)} is not valid UTF-8: {exc}") from exc


def check_required_paths(errors: list[str]) -> None:
    for relative in REQUIRED_PATHS:
        if not (ROOT / relative).is_file():
            errors.append(f"missing required documentation: {relative}")


def normalize_link_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    if " " in target:
        target = target.split(" ", 1)[0]
    return unquote(target.split("#", 1)[0].split("?", 1)[0])


def check_markdown_links(files: list[Path], errors: list[str]) -> int:
    checked = 0
    for path in files:
        if path.suffix.lower() != ".md":
            continue
        checked += 1
        in_fence = False
        for line_number, line in enumerate(read_text(path).splitlines(), start=1):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for match in MARKDOWN_LINK.finditer(line):
                raw_target = match.group(1)
                if raw_target.startswith("#") or EXTERNAL_SCHEME.match(raw_target):
                    continue
                target = normalize_link_target(raw_target)
                if not target:
                    continue
                resolved = (ROOT / target.lstrip("/")) if target.startswith("/") else (path.parent / target)
                if not resolved.exists():
                    relative = path.relative_to(ROOT)
                    errors.append(f"{relative}:{line_number}: broken relative link: {raw_target}")
    return checked


def check_legacy_references(files: list[Path], errors: list[str]) -> None:
    for path in files:
        for line_number, line in enumerate(read_text(path).splitlines(), start=1):
            for match in LEGACY_REFERENCE.finditer(line):
                target = ROOT / match.group("path")
                if not target.exists():
                    relative = path.relative_to(ROOT)
                    errors.append(
                        f"{relative}:{line_number}: dangling legacy documentation reference: "
                        f"{match.group('path')}"
                    )


def parse_progress(errors: list[str]) -> dict[str, str]:
    path = ROOT / "progress.md"
    if not path.is_file():
        return {}
    fields: dict[str, str] = {}
    for line in read_text(path).splitlines():
        match = PROGRESS_FIELD.match(line)
        if match:
            fields[match.group(1)] = match.group(2).strip()
    for name in REQUIRED_PROGRESS_FIELDS:
        if not fields.get(name):
            errors.append(f"progress.md: missing or empty field: {name}")
    return fields


def changed_runtime_paths() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z"],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []

    changed: list[str] = []
    entries = [entry for entry in result.stdout.split(b"\0") if entry]
    index = 0
    while index < len(entries):
        entry = entries[index].decode("utf-8")
        status = entry[:2]
        name = entry[3:]
        if "R" in status or "C" in status:
            index += 1
            if index < len(entries):
                name = entries[index].decode("utf-8")
        index += 1
        path = Path(name)
        if path.parts and path.parts[0] in {"backend", "frontend"} and path.suffix in {
            ".py",
            ".ts",
            ".tsx",
            ".toml",
            ".json",
            ".yaml",
            ".yml",
        }:
            changed.append(name)
    return changed


def check_final_progress(fields: dict[str, str], errors: list[str]) -> None:
    status = fields.get("状态", "").strip("` ")
    if status not in {"completed", "blocked"}:
        errors.append("progress.md: final check requires status completed or blocked")

    for name in ("已完成", "验证结果", "文档影响", "现场清理"):
        value = fields.get(name, "")
        if not value or "待" in value:
            errors.append(f"progress.md: final field is not resolved: {name}")

    runtime_changes = changed_runtime_paths()
    impact = fields.get("文档影响", "")
    if runtime_changes and "docs/" not in impact and "README" not in impact and "无需" not in impact:
        errors.append(
            "progress.md: runtime files changed but 文档影响 neither names updated docs "
            "nor gives an explicit 无需更新 reason"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--final",
        action="store_true",
        help="also require a completed/blocked progress snapshot with validation and cleanup",
    )
    args = parser.parse_args()

    errors: list[str] = []
    check_required_paths(errors)
    files = repository_text_files()
    markdown_count = check_markdown_links(files, errors)
    check_legacy_references(files, errors)
    fields = parse_progress(errors)
    if args.final:
        check_final_progress(fields, errors)

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"documentation check failed with {len(errors)} error(s)", file=sys.stderr)
        return 1

    mode = "final" if args.final else "structural"
    print(f"documentation {mode} check passed ({markdown_count} Markdown files checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
