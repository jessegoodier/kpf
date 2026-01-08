"""Configuration management for kpf."""

import json
import os
import re
from pathlib import Path
from typing import Any

from rich.console import Console

console = Console()


class KpfConfig:
    """Configuration manager for kpf following XDG Base Directory Specification."""

    # Default configuration values
    DEFAULTS = {
        "autoSelectFreePort": True,  # When 9090 is in use, try 9091, 9092, ...
        "showDirectCommand": True,
        "showDirectCommandIncludeContext": True,
        "directCommandMultiLine": True,
        "autoReconnect": True,
        "reconnectAttempts": 30,
        "reconnectDelaySeconds": 5,
        "captureUsageDetails": False,  # local usage details, not sent anywhere
        "usageDetailFolder": "${HOME}/.config/kpf/usage-details",
    }

    def __init__(self):
        """Initialize configuration with defaults and load user config if available."""
        self.config = self.DEFAULTS.copy()
        self._load_config()

    def _get_config_path(self) -> Path:
        """Get config file path following XDG Base Directory Specification.

        Returns the path to the config file, preferring XDG_CONFIG_HOME if set,
        otherwise falling back to ~/.config/kpf/kpf.json
        """
        xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config_home:
            config_dir = Path(xdg_config_home) / "kpf"
        else:
            config_dir = Path.home() / ".config" / "kpf"
        return config_dir / "kpf.json"

    def _expand_vars(self, value: str) -> str:
        """Expand environment variables in config values.

        Supports ${VAR} syntax for environment variable expansion.

        Args:
            value: String that may contain ${VAR} patterns

        Returns:
            String with environment variables expanded
        """
        if isinstance(value, str):
            # Replace ${VAR} with environment variable value
            def replacer(match):
                var_name = match.group(1)
                return os.environ.get(var_name, match.group(0))

            return re.sub(r"\$\{(\w+)\}", replacer, value)
        return value

    def _load_config(self):
        """Load configuration from file if it exists.

        Merges user configuration with defaults. Invalid keys are ignored with a warning.
        JSON parse errors result in falling back to defaults.
        """
        config_path = self._get_config_path()

        if not config_path.exists():
            return  # Use defaults

        try:
            with open(config_path, "r") as f:
                user_config = json.load(f)

            # Merge user config with defaults
            for key, value in user_config.items():
                if key in self.DEFAULTS:
                    # Expand variables in string values
                    if isinstance(value, str):
                        value = self._expand_vars(value)
                    self.config[key] = value
                else:
                    console.print(
                        f"[yellow]Warning: Unknown config key '{key}' in {config_path} (ignored)[/yellow]"
                    )

        except json.JSONDecodeError as e:
            console.print(f"[red]Error: Invalid JSON in config file {config_path}: {e}[/red]")
            console.print("[yellow]Using default configuration[/yellow]")
        except Exception as e:
            console.print(
                f"[yellow]Warning: Could not load config from {config_path}: {e}[/yellow]"
            )
            console.print("[yellow]Using default configuration[/yellow]")

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value.

        Args:
            key: Configuration key to retrieve
            default: Default value if key is not found

        Returns:
            Configuration value or default
        """
        return self.config.get(key, default)

    def get_config_path(self) -> Path:
        """Get the path to the config file (public accessor)."""
        return self._get_config_path()


# Singleton instance
_config = None


def get_config() -> KpfConfig:
    """Get the global configuration instance.

    Returns:
        Singleton KpfConfig instance
    """
    global _config
    if _config is None:
        _config = KpfConfig()
    return _config
