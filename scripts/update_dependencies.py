#!/usr/bin/env python3
"""Update Python (uv) and Node (npm) dependencies to the latest versions."""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from collections.abc import Mapping
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "apps" / "web"
PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"
PACKAGE_JSON = WEB_DIR / "package.json"
PACKAGE_LOCK = WEB_DIR / "package-lock.json"


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        console.print(f"[bold red]Command failed:[/bold red] {' '.join(command)}")
        if result.stdout.strip():
            console.print(result.stdout)
        if result.stderr.strip():
            console.print(result.stderr)
        raise SystemExit(result.returncode)
    return result


CONSTRAINT_RE = re.compile(r"^(.+?)(>=|==|~=|<=|<|!=)([^;\s]+)")
DEP_LINE_RE = re.compile(r'^(\s+)"([^"]+)"(.*)$')


def normalized_version(version: str) -> str:
    parts = version.lstrip("v").split("-", 1)[0].split(".")
    while len(parts) > 1 and parts[-1] == "0":
        parts.pop()
    return ".".join(parts)


def bump_constraint_spec(spec: str, locked_version: str) -> str | None:
    if not locked_version:
        return None
    base = spec.split(";", 1)[0].strip()
    marker = spec[len(base) :].strip()
    match = CONSTRAINT_RE.match(base)
    if not match or match.group(2) != ">=":
        return None
    name_part, _, current_min = match.groups()
    next_min = normalized_version(locked_version)
    if version_parts(next_min) <= version_parts(current_min):
        return None
    updated = f"{name_part}>={next_min}"
    if marker:
        updated = f"{updated} ; {marker.removeprefix(';').strip()}"
    return updated


def update_pyproject_constraints(
    locked_versions: dict[str, str],
) -> list[tuple[str, str, str]]:
    lines = PYPROJECT.read_text(encoding="utf-8").splitlines(keepends=True)
    changes: list[tuple[str, str, str]] = []
    section: str | None = None

    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "dependencies = [":
            section = "dependencies"
            continue
        if stripped == "dev = [":
            section = "dev"
            continue
        if section and stripped == "]":
            section = None
            continue
        if section is None:
            continue

        match = DEP_LINE_RE.match(line.rstrip("\n"))
        if not match:
            continue

        spec = match.group(2)
        locked = locked_versions.get(pep508_name(spec))
        if not locked:
            continue
        updated = bump_constraint_spec(spec, locked)
        if not updated or updated == spec:
            continue

        suffix = match.group(3)
        if not suffix.rstrip().endswith(",") and index + 1 < len(lines):
            next_line = lines[index + 1].strip()
            if next_line and next_line != "]":
                suffix = f"{suffix.rstrip()},"
        lines[index] = f'{match.group(1)}"{updated}"{suffix}\n'
        changes.append((pep508_name(spec), spec, updated))

    if changes:
        PYPROJECT.write_text("".join(lines), encoding="utf-8")

    return changes


def pep508_name(spec: str) -> str:
    name = re.split(r"[<>=!~\[]", spec.split(";", 1)[0].strip(), maxsplit=1)[0].strip()
    return name.lower().replace("_", "-")


def parse_pyproject_direct() -> set[str]:
    with PYPROJECT.open("rb") as handle:
        data = tomllib.load(handle)
    names: set[str] = set()
    for spec in data["project"]["dependencies"]:
        names.add(pep508_name(spec))
    for spec in data.get("dependency-groups", {}).get("dev", []):
        names.add(pep508_name(spec))
    return names


def parse_uv_lock() -> dict[str, str]:
    with UV_LOCK.open("rb") as handle:
        data = tomllib.load(handle)
    return {pkg["name"]: pkg["version"] for pkg in data.get("package", [])}


def parse_package_json() -> dict[str, dict[str, str]]:
    with PACKAGE_JSON.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return {
        "dependencies": data.get("dependencies", {}),
        "devDependencies": data.get("devDependencies", {}),
    }


def version_parts(version: str) -> tuple[int, int, int]:
    cleaned = version.lstrip("v").split("-", 1)[0]
    parts: list[int] = []
    for piece in cleaned.split("."):
        digits = "".join(char for char in piece if char.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def bump_type(old: str, new: str) -> str | None:
    old_parts = version_parts(old)
    new_parts = version_parts(new)
    if new_parts <= old_parts:
        return None
    if new_parts[0] > old_parts[0]:
        return "major"
    if new_parts[1] > old_parts[1]:
        return "minor"
    return "patch"


def collect_changes(
    before: Mapping[str, str],
    after: Mapping[str, str],
    *,
    direct: set[str] | None = None,
) -> dict[str, list[tuple[str, str, str]]]:
    changes: dict[str, list[tuple[str, str, str]]] = {
        "major": [],
        "minor": [],
        "patch": [],
    }
    for name in sorted(set(before) | set(after)):
        if direct is not None and name not in direct:
            continue
        old = before.get(name)
        new = after.get(name)
        if not old or not new or old == new:
            continue
        kind = bump_type(old, new)
        if kind:
            changes[kind].append((name, old, new))
    return changes


def print_direct_changes(
    ecosystem: str,
    changes: dict[str, list[tuple[str, str, str]]],
) -> None:
    rows: list[tuple[str, str, str, str]] = []
    for kind in ("major", "minor", "patch"):
        for name, old, new in changes[kind]:
            rows.append((kind, name, old, new))
    if not rows:
        console.print(f"[dim]No direct {ecosystem} dependency changes.[/dim]")
        return
    table = Table(title=f"Direct {ecosystem} dependencies", show_header=True)
    table.add_column("Bump", style="yellow")
    table.add_column("Package", style="cyan")
    table.add_column("Before", style="magenta")
    table.add_column("After", style="green")
    for kind, name, old, new in rows:
        table.add_row(kind, name, old, new)
    console.print(table)


def update_python() -> tuple[dict[str, str], list[tuple[str, str, str]]]:
    console.print("[bold blue]Updating Python lockfile (uv lock --upgrade)...[/bold blue]")
    run(["uv", "lock", "--upgrade"])

    locked = parse_uv_lock()
    console.print("[bold blue]Updating pyproject.toml version constraints...[/bold blue]")
    constraint_changes = update_pyproject_constraints(locked)
    if constraint_changes:
        run(["uv", "lock"])
    else:
        console.print("[dim]No pyproject.toml constraint changes needed.[/dim]")

    console.print("[bold blue]Syncing Python environment...[/bold blue]")
    run(["uv", "sync"])
    return parse_uv_lock(), constraint_changes


def update_node() -> tuple[dict[str, str], set[str]]:
    console.print(
        "[bold blue]Updating Node dependencies (npm-check-updates + npm install)...[/bold blue]"
    )
    run(
        [
            "npx",
            "--yes",
            "npm-check-updates@latest",
            "-u",
            "--peer",
        ],
        cwd=WEB_DIR,
    )
    run(["npm", "install"], cwd=WEB_DIR)
    pkg = parse_package_json()
    direct = set(pkg["dependencies"]) | set(pkg["devDependencies"])
    return direct


def print_constraint_changes(changes: list[tuple[str, str, str]]) -> None:
    if not changes:
        return
    table = Table(title="pyproject.toml constraints", show_header=True)
    table.add_column("Package", style="cyan")
    table.add_column("Before", style="magenta")
    table.add_column("After", style="green")
    for _, old, new in changes:
        table.add_row(pep508_name(old), old, new)
    console.print(table)


def print_summary(
    *,
    python_direct: set[str],
    python_before: dict[str, str],
    python_after: dict[str, str],
    pyproject_constraint_changes: list[tuple[str, str, str]],
) -> None:
    python_direct_changes = collect_changes(python_before, python_after, direct=python_direct)
    python_all_changes = collect_changes(python_before, python_after)

    console.print()
    console.print(Panel.fit("Direct dependency updates", style="bold magenta"))

    print_direct_changes("Python (uv.lock)", python_direct_changes)
    print_constraint_changes(pyproject_constraint_changes)

    major: list[tuple[str, str, str, str]] = []
    minor: list[tuple[str, str, str, str]] = []
    for ecosystem, changes in (("python", python_all_changes),):
        for name, old, new in changes["major"]:
            major.append((ecosystem, name, old, new))
        for name, old, new in changes["minor"]:
            minor.append((ecosystem, name, old, new))

    patch_count = len(python_all_changes["patch"])

    console.print()
    console.print(Panel.fit("Version bump summary", style="bold yellow"))
    if major:
        table = Table(title=f"Major bumps ({len(major)})", show_header=True)
        table.add_column("Ecosystem", style="cyan")
        table.add_column("Package", style="cyan")
        table.add_column("Before", style="magenta")
        table.add_column("After", style="green")
        for ecosystem, name, old, new in major:
            table.add_row(ecosystem, name, old, new)
        console.print(table)
    else:
        console.print("[green]No major version bumps.[/green]")

    if minor:
        table = Table(title=f"Minor bumps ({len(minor)})", show_header=True)
        table.add_column("Ecosystem", style="cyan")
        table.add_column("Package", style="cyan")
        table.add_column("Before", style="magenta")
        table.add_column("After", style="green")
        for ecosystem, name, old, new in minor:
            table.add_row(ecosystem, name, old, new)
        console.print(table)
    else:
        console.print("[green]No minor version bumps.[/green]")

    if patch_count:
        console.print(
            f"[dim]{patch_count} patch-only bump(s) across lockfiles "
            "(not listed individually).[/dim]"
        )

    if not major and not minor and not patch_count:
        if pyproject_constraint_changes:
            console.print(
                "[green]Lockfiles were current; pyproject.toml constraints were refreshed.[/green]"
            )
        else:
            console.print("[green]All dependencies were already up to date.[/green]")


def main() -> None:
    console.print(Panel.fit("Fleet Manager dependency update", style="bold magenta"))

    for tool in ("uv", "npm", "npx"):
        if subprocess.run(["which", tool], capture_output=True).returncode != 0:
            console.print(f"[bold red]Required tool not found:[/bold red] {tool}")
            raise SystemExit(1)

    python_before = parse_uv_lock()
    python_direct = parse_pyproject_direct()

    python_after, pyproject_constraint_changes = update_python()

    print_summary(
        python_direct=python_direct,
        python_before=python_before,
        python_after=python_after,
        pyproject_constraint_changes=pyproject_constraint_changes,
    )


if __name__ == "__main__":
    main()
