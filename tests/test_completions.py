#!/usr/bin/env python3
"""Tests to ensure shell completions stay in sync with CLI arguments."""

import re
from pathlib import Path

import pytest

from kpf.cli import create_parser


def extract_cli_flags():
    """Extract all flags from the CLI parser."""
    parser = create_parser()
    flags = set()

    for action in parser._actions:
        if action.option_strings:
            for opt in action.option_strings:
                flags.add(opt)

    return flags


def extract_bash_completion_flags():
    """Extract flags from the Bash completion script."""
    completion_file = Path(__file__).parent.parent / "completions" / "kpf.bash"
    content = completion_file.read_text()

    # Find the line with flag completions
    match = re.search(r'compgen -W "([^"]+)"', content)
    if not match:
        return set()

    flags_str = match.group(1)
    return set(flags_str.split())


def extract_zsh_completion_flags():
    """Extract flags from the Zsh completion script."""
    completion_file = Path(__file__).parent.parent / "completions" / "_kpf"
    content = completion_file.read_text()

    flags = set()

    # Match patterns like '(-n --namespace)'{-n,--namespace}
    # or '(-0)-0[...]' for special flags
    # or '--flag[...]' for standalone flags
    patterns = [
        r"'\(([^)]+)\)'\{([^}]+)\}",  # Grouped flags like (-n --namespace)'{-n,--namespace}
        r"'\([^)]+\)(-\d+)\[",  # Special flags like '(-0)-0[...]'
        r"'(--[a-z-]+)\[",  # Standalone flags like '--auto-reconnect[...]'
    ]

    for pattern in patterns:
        matches = re.finditer(pattern, content)
        for match in matches:
            if len(match.groups()) > 1 and match.group(2):
                # For grouped flags, extract from the braces
                flags_group = match.group(2)
            else:
                flags_group = match.group(1)

            # Split by comma or space to get individual flags
            for flag in flags_group.replace(",", " ").split():
                flags.add(flag)

    return flags


def normalize_flags(flags):
    """Normalize flags for comparison (handle -h, --help special cases)."""
    # argparse adds -h/--help automatically, so we should include them
    normalized = set(flags)
    return normalized


class TestCompletionSync:
    """Test that completion scripts are in sync with CLI."""

    def test_bash_completion_has_all_flags(self):
        """Verify Bash completion includes all CLI flags."""
        cli_flags = extract_cli_flags()
        bash_flags = extract_bash_completion_flags()

        # Normalize both sets
        cli_flags = normalize_flags(cli_flags)
        bash_flags = normalize_flags(bash_flags)

        missing_flags = cli_flags - bash_flags
        assert not missing_flags, f"Bash completion is missing flags: {sorted(missing_flags)}"

    def test_zsh_completion_has_all_flags(self):
        """Verify Zsh completion includes all CLI flags."""
        cli_flags = extract_cli_flags()
        zsh_flags = extract_zsh_completion_flags()

        # Normalize both sets
        cli_flags = normalize_flags(cli_flags)
        zsh_flags = normalize_flags(zsh_flags)

        missing_flags = cli_flags - zsh_flags
        assert not missing_flags, f"Zsh completion is missing flags: {sorted(missing_flags)}"

    def test_no_extra_flags_in_bash(self):
        """Verify Bash completion doesn't have extra flags not in CLI."""
        cli_flags = extract_cli_flags()
        bash_flags = extract_bash_completion_flags()

        cli_flags = normalize_flags(cli_flags)
        bash_flags = normalize_flags(bash_flags)

        extra_flags = bash_flags - cli_flags
        assert not extra_flags, f"Bash completion has extra flags: {sorted(extra_flags)}"

    def test_no_extra_flags_in_zsh(self):
        """Verify Zsh completion doesn't have extra flags not in CLI."""
        cli_flags = extract_cli_flags()
        zsh_flags = extract_zsh_completion_flags()

        cli_flags = normalize_flags(cli_flags)
        zsh_flags = normalize_flags(zsh_flags)

        extra_flags = zsh_flags - cli_flags
        assert not extra_flags, f"Zsh completion has extra flags: {sorted(extra_flags)}"

    def test_bash_has_namespace_completion(self):
        """Verify Bash completion handles namespace flag."""
        completion_file = Path(__file__).parent.parent / "completions" / "kpf.bash"
        content = completion_file.read_text()

        # Check for namespace handling
        assert "-n|--namespace" in content, "Bash completion missing namespace handling"
        assert "kubectl get namespaces" in content, (
            "Bash completion missing namespace completion logic"
        )

    def test_zsh_has_namespace_completion(self):
        """Verify Zsh completion handles namespace flag."""
        completion_file = Path(__file__).parent.parent / "completions" / "_kpf"
        content = completion_file.read_text()

        # Check for namespace handling
        assert "_kpf_namespaces" in content, "Zsh completion missing namespace function"
        assert "kubectl get namespaces" in content, (
            "Zsh completion missing namespace completion logic"
        )

    def test_bash_has_service_completion(self):
        """Verify Bash completion has service completion logic."""
        completion_file = Path(__file__).parent.parent / "completions" / "kpf.bash"
        content = completion_file.read_text()

        assert "kubectl get services" in content, "Bash completion missing service completion"
        assert "svc/" in content, "Bash completion should prefix services with 'svc/'"

    def test_zsh_has_service_completion(self):
        """Verify Zsh completion has service completion logic."""
        completion_file = Path(__file__).parent.parent / "completions" / "_kpf"
        content = completion_file.read_text()

        assert "kubectl get services" in content, "Zsh completion missing service completion"
        assert "svc/" in content, "Zsh completion should prefix services with 'svc/'"

    def test_bash_has_port_completion(self):
        """Verify Bash completion has port completion logic."""
        completion_file = Path(__file__).parent.parent / "completions" / "kpf.bash"
        content = completion_file.read_text()

        assert "kubectl get service" in content, "Bash completion missing port lookup"
        # Check for port:port format in completions
        assert ":$port" in content or "port:port" in content.lower() or "$port:$port" in content

    def test_zsh_has_port_completion(self):
        """Verify Zsh completion has port completion logic."""
        completion_file = Path(__file__).parent.parent / "completions" / "_kpf"
        content = completion_file.read_text()

        assert "_kpf_ports" in content, "Zsh completion missing port completion function"
        assert "kubectl get service" in content, "Zsh completion missing port lookup"

    def test_completions_use_correct_jsonpath(self):
        """Verify completions use the correct jsonpath format (with range)."""
        bash_file = Path(__file__).parent.parent / "completions" / "kpf.bash"
        zsh_file = Path(__file__).parent.parent / "completions" / "_kpf"

        bash_content = bash_file.read_text()
        zsh_content = zsh_file.read_text()

        # Check for the correct jsonpath pattern with range
        assert "{range .items[*]}" in bash_content, (
            "Bash completion should use '{range .items[*]}' jsonpath"
        )
        assert "{range .items[*]}" in zsh_content, (
            "Zsh completion should use '{range .items[*]}' jsonpath"
        )

        # Make sure we're not using the old broken pattern
        assert "{.items[*].metadata.name}" not in bash_content, (
            "Bash completion using old broken jsonpath pattern"
        )
        assert "{.items[*].metadata.name}" not in zsh_content, (
            "Zsh completion using old broken jsonpath pattern"
        )


class TestCompletionFunctionality:
    """Test the actual functionality of completions."""

    def test_cli_parser_accepts_all_flags(self):
        """Verify the CLI parser can handle all defined flags."""
        parser = create_parser()

        # Test combinations of flags
        test_cases = [
            ["-n", "default"],
            ["--namespace", "kube-system"],
            ["-A"],
            ["--all"],
            ["-l"],
            ["--all-ports"],
            ["-c"],
            ["--check"],
            ["-d"],
            ["--debug"],
            ["-t"],
            ["--debug-terminal"],
            ["-z"],
            ["-p"],
            ["--prompt-namespace"],
            ["-v"],  # This will trigger version and exit, but should parse
        ]

        for test_args in test_cases:
            try:
                # Use parse_known_args to avoid SystemExit on -v/--version
                args, _ = parser.parse_known_args(test_args)
                # If we got here, parsing succeeded
            except SystemExit as e:
                # Version flag causes SystemExit(0), which is expected
                if "-v" in test_args or "--version" in test_args:
                    assert e.code == 0
                else:
                    raise

    def test_namespace_flag_variations(self):
        """Test that both -n and --namespace work."""
        parser = create_parser()

        args1, _ = parser.parse_known_args(["-n", "test-ns"])
        args2, _ = parser.parse_known_args(["--namespace", "test-ns"])

        assert args1.namespace == "test-ns"
        assert args2.namespace == "test-ns"


if __name__ == "__main__":
    # Allow running tests directly for debugging
    pytest.main([__file__, "-v"])
