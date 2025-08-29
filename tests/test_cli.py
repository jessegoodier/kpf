"""Tests for CLI module."""

from unittest.mock import Mock, patch

import pytest

from src.kpf.cli import create_parser, handle_prompt_mode, main


class TestArgumentParser:
    """Test CLI argument parsing."""

    def test_create_parser_basic(self):
        """Test basic parser creation."""
        parser = create_parser()
        assert parser.prog == "kpf"
        assert "kubectl port-forward" in parser.description.lower()

    def test_parser_version_argument(self):
        """Test --version argument."""
        parser = create_parser()

        with pytest.raises(SystemExit):
            parser.parse_args(["--version"])

    def test_parser_help_argument(self):
        """Test --help argument."""
        parser = create_parser()

        with pytest.raises(SystemExit):
            parser.parse_args(["--help"])

    def test_parser_prompt_argument(self):
        """Test --prompt argument."""
        parser = create_parser()
        args = parser.parse_args(["--prompt"])

        assert args.prompt is True
        assert args.all is False
        assert args.check is False

    def test_parser_all_argument(self):
        """Test --all argument."""
        parser = create_parser()
        args = parser.parse_args(["--all"])

        assert args.all is True
        assert args.prompt is False

    def test_parser_namespace_argument(self):
        """Test --namespace argument."""
        parser = create_parser()
        args = parser.parse_args(["-n", "production"])

        assert args.namespace == "production"

    def test_parser_check_argument(self):
        """Test --check argument."""
        parser = create_parser()
        args = parser.parse_args(["--check"])

        assert args.check is True

    def test_parser_all_ports_argument(self):
        """Test --all-ports argument."""
        parser = create_parser()
        args = parser.parse_args(["--all-ports"])

        assert args.all_ports is True

    def test_parser_debug_argument(self):
        """Test --debug argument."""
        parser = create_parser()
        args = parser.parse_args(["--debug"])

        assert args.debug is True

    def test_parser_combined_arguments(self):
        """Test multiple arguments together."""
        parser = create_parser()
        args = parser.parse_args(
            ["--prompt", "--check", "-n", "kube-system", "--debug"]
        )

        assert args.prompt is True
        assert args.check is True
        assert args.namespace == "kube-system"
        assert args.debug is True

    def test_parser_legacy_args(self):
        """Test legacy kubectl port-forward arguments."""
        parser = create_parser()
        args, unknown_args = parser.parse_known_args(
            ["svc/frontend", "8080:8080", "-n", "production"]
        )

        # The parser separates namespace from positional args
        assert args.args == ["svc/frontend", "8080:8080"]
        assert args.namespace == "production"
        assert unknown_args == []
        assert args.prompt is False
        assert args.all is False

    def test_parser_short_flags(self):
        """Test short flag versions."""
        parser = create_parser()
        args, unknown_args = parser.parse_known_args(
            ["-p", "-c", "-A", "-l", "-n", "test", "-d"]
        )

        assert args.prompt is True
        assert args.check is True
        assert args.all is True
        assert args.all_ports is True
        assert args.namespace == "test"
        assert args.debug is True
        assert unknown_args == []


class TestKubectlArgumentPassthrough:
    """Test kubectl argument passthrough functionality.

    These tests ensure that kpf can pass through kubectl port-forward arguments
    that it doesn't recognize, allowing full compatibility with kubectl options
    like --address, --pod-running-timeout, and global kubectl options.

    This functionality was added to support the original issue where commands like:
    `kpf service/porthole 7070:7070 -n porthole --address 0.0.0.0`
    were failing with "unrecognized arguments" errors.
    """

    def test_parser_kubectl_address_option(self):
        """Test kubectl --address option is passed through."""
        parser = create_parser()
        args, unknown_args = parser.parse_known_args(
            ["svc/frontend", "8080:8080", "-n", "production", "--address", "0.0.0.0"]
        )

        assert args.args == ["svc/frontend", "8080:8080"]
        assert args.namespace == "production"
        assert unknown_args == ["--address", "0.0.0.0"]

    def test_parser_kubectl_pod_running_timeout(self):
        """Test kubectl --pod-running-timeout option is passed through."""
        parser = create_parser()
        args, unknown_args = parser.parse_known_args(
            [
                "svc/frontend",
                "8080:8080",
                "--pod-running-timeout",
                "2m",
                "-n",
                "production",
            ]
        )

        assert args.args == ["svc/frontend", "8080:8080"]
        assert args.namespace == "production"
        assert unknown_args == ["--pod-running-timeout", "2m"]

    def test_parser_multiple_kubectl_options(self):
        """Test multiple kubectl options are passed through."""
        parser = create_parser()
        args, unknown_args = parser.parse_known_args(
            [
                "svc/frontend",
                "8080:8080",
                "-n",
                "production",
                "--address",
                "0.0.0.0",
                "--pod-running-timeout",
                "30s",
            ]
        )

        assert args.args == ["svc/frontend", "8080:8080"]
        assert args.namespace == "production"
        assert unknown_args == ["--address", "0.0.0.0", "--pod-running-timeout", "30s"]

    def test_parser_kubectl_global_options(self):
        """Test kubectl global options are passed through."""
        parser = create_parser()
        args, unknown_args = parser.parse_known_args(
            [
                "svc/frontend",
                "8080:8080",
                "-n",
                "production",
                "--context",
                "my-cluster",
                "--kubeconfig",
                "/path/to/config",
            ]
        )

        assert args.args == ["svc/frontend", "8080:8080"]
        assert args.namespace == "production"
        assert unknown_args == [
            "--context",
            "my-cluster",
            "--kubeconfig",
            "/path/to/config",
        ]

    def test_parser_only_kubectl_options(self):
        """Test when only kubectl options are provided (no args)."""
        parser = create_parser()
        args, unknown_args = parser.parse_known_args(
            ["--address", "0.0.0.0", "svc/frontend", "8080:8080"]
        )

        # Note: argparse treats the value "0.0.0.0" as a positional arg when --address appears before resource
        # This behavior is consistent with how kubectl itself works
        assert args.args == ["0.0.0.0", "svc/frontend", "8080:8080"]
        assert unknown_args == ["--address"]

    def test_parser_mixed_kpf_kubectl_options(self):
        """Test mixing kpf and kubectl options."""
        parser = create_parser()
        args, unknown_args = parser.parse_known_args(
            [
                "--debug",
                "svc/frontend",
                "8080:8080",
                "--address",
                "0.0.0.0",
                "-n",
                "production",
            ]
        )

        assert args.debug is True
        assert args.namespace == "production"
        assert args.args == ["svc/frontend", "8080:8080"]
        assert unknown_args == ["--address", "0.0.0.0"]


class TestHandlePromptMode:
    """Test handle_prompt_mode function."""

    @patch("src.kpf.cli.KubernetesClient")
    @patch("src.kpf.cli.ServiceSelector")
    def test_handle_prompt_mode_namespace(self, mock_selector_class, mock_client_class):
        """Test handle_prompt_mode with specific namespace."""
        mock_client = Mock()
        mock_selector = Mock()
        mock_client_class.return_value = mock_client
        mock_selector_class.return_value = mock_selector
        mock_selector.select_service_in_namespace.return_value = [
            "svc/test",
            "8080:8080",
            "-n",
            "test",
        ]

        result = handle_prompt_mode(namespace="test", show_all=False)

        assert result == ["svc/test", "8080:8080", "-n", "test"]
        mock_selector.select_service_in_namespace.assert_called_once_with(
            "test", False, False
        )
        mock_selector.select_service_all_namespaces.assert_not_called()

    @patch("src.kpf.cli.KubernetesClient")
    @patch("src.kpf.cli.ServiceSelector")
    def test_handle_prompt_mode_all_namespaces(
        self, mock_selector_class, mock_client_class
    ):
        """Test handle_prompt_mode with all namespaces."""
        mock_client = Mock()
        mock_selector = Mock()
        mock_client_class.return_value = mock_client
        mock_selector_class.return_value = mock_selector
        mock_selector.select_service_all_namespaces.return_value = [
            "svc/test",
            "8080:8080",
            "-n",
            "default",
        ]

        result = handle_prompt_mode(show_all=True)

        assert result == ["svc/test", "8080:8080", "-n", "default"]
        mock_selector.select_service_all_namespaces.assert_called_once_with(
            False, False
        )
        mock_selector.select_service_in_namespace.assert_not_called()

    @patch("src.kpf.cli.KubernetesClient")
    @patch("src.kpf.cli.ServiceSelector")
    def test_handle_prompt_mode_with_options(
        self, mock_selector_class, mock_client_class
    ):
        """Test handle_prompt_mode with all options enabled."""
        mock_client = Mock()
        mock_selector = Mock()
        mock_client_class.return_value = mock_client
        mock_selector_class.return_value = mock_selector
        mock_selector.select_service_in_namespace.return_value = [
            "svc/test",
            "8080:8080",
            "-n",
            "test",
        ]

        handle_prompt_mode(
            namespace="test", show_all=False, show_all_ports=True, check_endpoints=True
        )

        mock_selector.select_service_in_namespace.assert_called_once_with(
            "test", True, True
        )


class TestMainFunction:
    """Test main CLI entry point."""

    @patch("src.kpf.cli.handle_prompt_mode")
    @patch("src.kpf.cli.run_port_forward")
    @patch("sys.argv", ["kpf", "--prompt"])
    def test_main_prompt_mode(self, mock_run_pf, mock_handle_prompt):
        """Test main function with --prompt."""
        mock_handle_prompt.return_value = ["svc/test", "8080:8080", "-n", "default"]

        main()

        mock_handle_prompt.assert_called_once()
        mock_run_pf.assert_called_once_with(
            ["svc/test", "8080:8080", "-n", "default"], debug_mode=False
        )

    @patch("src.kpf.cli.handle_prompt_mode")
    @patch("src.kpf.cli.run_port_forward")
    @patch("sys.argv", ["kpf", "--prompt", "--debug"])
    def test_main_prompt_mode_with_debug(self, mock_run_pf, mock_handle_prompt):
        """Test main function with --prompt and --debug."""
        mock_handle_prompt.return_value = ["svc/test", "8080:8080", "-n", "default"]

        main()

        mock_run_pf.assert_called_once_with(
            ["svc/test", "8080:8080", "-n", "default"], debug_mode=True
        )

    @patch("src.kpf.cli.run_port_forward")
    @patch("sys.argv", ["kpf", "svc/frontend", "8080:8080"])
    def test_main_legacy_mode(self, mock_run_pf):
        """Test main function with legacy arguments."""
        main()

        mock_run_pf.assert_called_once_with(
            ["svc/frontend", "8080:8080"], debug_mode=False
        )

    @patch("src.kpf.cli.run_port_forward")
    @patch("sys.argv", ["kpf", "svc/frontend", "8080:8080", "-n", "production"])
    def test_main_legacy_mode_with_namespace(self, mock_run_pf):
        """Test main function with legacy arguments and existing namespace."""
        main()

        mock_run_pf.assert_called_once_with(
            ["svc/frontend", "8080:8080", "-n", "production"], debug_mode=False
        )

    @patch("src.kpf.cli.run_port_forward")
    @patch(
        "sys.argv", ["kpf", "svc/frontend", "8080:8080", "--namespace", "production"]
    )
    def test_main_legacy_mode_add_namespace(self, mock_run_pf):
        """Test main function adding namespace to legacy arguments."""
        main()

        mock_run_pf.assert_called_once_with(
            ["svc/frontend", "8080:8080", "-n", "production"], debug_mode=False
        )

    @patch("src.kpf.cli.run_port_forward")
    @patch(
        "sys.argv",
        [
            "kpf",
            "svc/frontend",
            "8080:8080",
            "-n",
            "production",
            "--address",
            "0.0.0.0",
        ],
    )
    def test_main_kubectl_address_option(self, mock_run_pf):
        """Test main function with kubectl --address option."""
        main()

        mock_run_pf.assert_called_once_with(
            ["svc/frontend", "8080:8080", "--address", "0.0.0.0", "-n", "production"],
            debug_mode=False,
        )

    @patch("src.kpf.cli.run_port_forward")
    @patch(
        "sys.argv", ["kpf", "svc/frontend", "8080:8080", "--pod-running-timeout", "2m"]
    )
    def test_main_kubectl_pod_timeout_option(self, mock_run_pf):
        """Test main function with kubectl --pod-running-timeout option."""
        main()

        mock_run_pf.assert_called_once_with(
            ["svc/frontend", "8080:8080", "--pod-running-timeout", "2m"],
            debug_mode=False,
        )

    @patch("src.kpf.cli.run_port_forward")
    @patch(
        "sys.argv",
        [
            "kpf",
            "svc/frontend",
            "8080:8080",
            "-n",
            "prod",
            "--address",
            "0.0.0.0",
            "--pod-running-timeout",
            "30s",
        ],
    )
    def test_main_multiple_kubectl_options(self, mock_run_pf):
        """Test main function with multiple kubectl options."""
        main()

        mock_run_pf.assert_called_once_with(
            [
                "svc/frontend",
                "8080:8080",
                "--address",
                "0.0.0.0",
                "--pod-running-timeout",
                "30s",
                "-n",
                "prod",
            ],
            debug_mode=False,
        )

    @patch("src.kpf.cli.run_port_forward")
    @patch(
        "sys.argv",
        ["kpf", "--debug", "svc/frontend", "8080:8080", "--address", "0.0.0.0"],
    )
    def test_main_mixed_kpf_kubectl_options(self, mock_run_pf):
        """Test main function mixing kpf and kubectl options."""
        main()

        mock_run_pf.assert_called_once_with(
            ["svc/frontend", "8080:8080", "--address", "0.0.0.0"], debug_mode=True
        )

    @patch("src.kpf.cli.run_port_forward")
    @patch("sys.argv", ["kpf", "svc/frontend", "8080:8080", "--namespace", "ignored"])
    def test_main_namespace_precedence(self, mock_run_pf):
        """Test that kpf --namespace option is parsed and used."""
        main()

        # kpf's --namespace should be parsed as a known argument and added as -n
        mock_run_pf.assert_called_once_with(
            ["svc/frontend", "8080:8080", "-n", "ignored"], debug_mode=False
        )

    @patch("src.kpf.cli.run_port_forward")
    @patch(
        "sys.argv",
        [
            "kpf",
            "svc/frontend",
            "8080:8080",
            "-n",
            "existing",
            "--namespace",
            "kpf-arg",
        ],
    )
    def test_main_namespace_override(self, mock_run_pf):
        """Test that kpf --namespace overrides earlier -n argument."""
        main()

        # When both -n and --namespace are specified, --namespace (kpf's option) takes precedence
        # This is the expected argparse behavior - later arguments override earlier ones
        mock_run_pf.assert_called_once_with(
            ["svc/frontend", "8080:8080", "-n", "kpf-arg"], debug_mode=False
        )

    @patch("src.kpf.cli.run_port_forward")
    @patch(
        "sys.argv",
        [
            "kpf",
            "svc/frontend",
            "8080:8080",
            "--context",
            "my-cluster",
            "-n",
            "kubectl-ns",
        ],
    )
    def test_main_kubectl_namespace_no_duplication(self, mock_run_pf):
        """Test that -n is not duplicated when it already exists in known args."""
        main()

        # -n is parsed as kpf's namespace argument, so no additional -n should be added
        # --context remains as unknown kubectl arg
        mock_run_pf.assert_called_once_with(
            [
                "svc/frontend",
                "8080:8080",
                "--context",
                "my-cluster",
                "-n",
                "kubectl-ns",
            ],
            debug_mode=False,
        )

    @patch("src.kpf.cli.run_port_forward")
    @patch("sys.argv", ["kpf", "--address", "0.0.0.0", "svc/frontend", "8080:8080"])
    def test_main_kubectl_option_before_resource(self, mock_run_pf):
        """Test kubectl options appearing before resource specification."""
        main()

        # Note: When --address appears before resource, argparse treats "0.0.0.0" as positional arg
        # This matches kubectl behavior where options should come after resource and port specs
        mock_run_pf.assert_called_once_with(
            ["0.0.0.0", "svc/frontend", "8080:8080", "--address"], debug_mode=False
        )

    @patch("src.kpf.cli.handle_prompt_mode")
    @patch("sys.argv", ["kpf", "--prompt"])
    def test_main_no_service_selected(self, mock_handle_prompt):
        """Test main function when no service is selected."""
        mock_handle_prompt.return_value = []

        with patch("sys.exit") as mock_exit:
            main()
            # The first call should be sys.exit(0) from the "No service selected" path
            mock_exit.assert_any_call(0)

    @patch("sys.argv", ["kpf"])
    def test_main_no_arguments(self):
        """Test main function with no arguments (should show help)."""
        with patch("sys.exit") as mock_exit:
            main()
            # Should call sys.exit(1) after printing help
            mock_exit.assert_any_call(0)

    @patch("src.kpf.cli.handle_prompt_mode")
    @patch("sys.argv", ["kpf", "--prompt"])
    def test_main_keyboard_interrupt(self, mock_handle_prompt):
        """Test main function with keyboard interrupt."""
        mock_handle_prompt.side_effect = KeyboardInterrupt()

        with patch("sys.exit") as mock_exit:
            main()
            mock_exit.assert_called_once_with(0)

    @patch("src.kpf.cli.handle_prompt_mode")
    @patch("sys.argv", ["kpf", "--prompt"])
    def test_main_exception(self, mock_handle_prompt):
        """Test main function with general exception."""
        mock_handle_prompt.side_effect = Exception("Test error")

        with patch("sys.exit") as mock_exit:
            main()
            mock_exit.assert_called_once_with(1)
