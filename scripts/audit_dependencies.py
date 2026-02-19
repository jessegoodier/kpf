#!/usr/bin/env python3
import json
import subprocess
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def run_command(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        return result
    except FileNotFoundError:
        return None


def check_security():
    console.print("[bold blue]Checking for security vulnerabilities...[/bold blue]")

    # Run pip-audit using uv run
    result = run_command(["uv", "run", "--with", "pip-audit", "pip-audit", "--format", "json"])

    if result is None:
        console.print("[bold red]Error: uv or pip-audit not found.[/bold red]")
        return False, []

    if result.returncode != 0 and not result.stdout:
        console.print(f"[bold red]Error running pip-audit:[/bold red] {result.stderr}")
        return False, []

    try:
        data = json.loads(result.stdout)
        # pip-audit format: {"dependencies": [{"name": "...", "version": "...", "vulns": [...]}, ...]}
        all_deps = data.get("dependencies", [])
        vulnerabilities = [d for d in all_deps if d.get("vulns")]
    except json.JSONDecodeError:
        # If no vulnerabilities found, pip-audit might return empty list or different output
        if "No known vulnerabilities found" in result.stderr or not result.stdout:
            return True, []
        console.print("[bold red]Failed to parse pip-audit output.[/bold red]")
        return False, []

    if not vulnerabilities:
        return True, []

    return False, vulnerabilities


def check_outdated():
    console.print("\n[bold blue]Checking for outdated dependencies...[/bold blue]")

    result = run_command(["uv", "pip", "list", "--outdated", "--format", "json"])

    if result is None:
        console.print("[bold red]Error: uv not found.[/bold red]")
        return []

    if result.returncode != 0:
        # If no packages are outdated, uv might return error or empty
        return []

    try:
        outdated = json.loads(result.stdout)
        return outdated
    except json.JSONDecodeError:
        return []


def run_sync():
    console.print("\n[bold blue]Running uv sync...[/bold blue]")
    result = run_command(["uv", "sync"])
    if result is None:
        console.print("[bold red]Error: uv not found.[/bold red]")
        return
    if result.returncode != 0:
        console.print(f"[bold red]Error running uv sync:[/bold red] {result.stderr}")
        return


def main():
    console.print(Panel.fit("KPF Dependency & Security Audit", style="bold magenta"))

    security_ok, vulnerabilities = check_security()

    if security_ok:
        console.print("[bold green]✅ No known vulnerabilities found.[/bold green]")
    else:
        console.print(
            f"[bold red]❌ Found {len(vulnerabilities)} packages with vulnerabilities![/bold red]"
        )
        table = Table(title="Vulnerabilities")
        table.add_column("Package", style="cyan")
        table.add_column("Version", style="magenta")
        table.add_column("ID", style="yellow")
        table.add_column("Fix Versions")

        for pkg in vulnerabilities:
            name = pkg.get("name")
            version = pkg.get("version")
            for vuln in pkg.get("vulns", []):
                table.add_row(
                    name, version, vuln.get("id"), ", ".join(vuln.get("fix_versions", ["N/A"]))
                )
        console.print(table)
    run_sync()
    outdated = check_outdated()
    if not outdated:
        console.print("[bold green]✅ All dependencies are up to date.[/bold green]")
    else:
        console.print(f"[bold yellow]ℹ️ Found {len(outdated)} outdated dependencies.[/bold yellow]")
        table = Table(title="Outdated Dependencies")
        table.add_column("Package", style="cyan")
        table.add_column("Installed", style="magenta")
        table.add_column("Latest", style="green")

        for item in outdated:
            table.add_row(item["name"], item["version"], item["latest_version"])
        console.print(table)

    if not security_ok:
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
