# kpf - A better way to port-forward with kubectl

This is a Python utility that (attempts to) dramatically improve the experience of port-forwarding with kubectl.

It is essentially a wrapper around `kubectl port-forward` that adds an interactive service selection with automatic reconnect when the pods are restarted or your network connection is interrupted (computer goes to sleep, etc).

## Features

- 🔄 **Automatic Restart**: Monitors endpoint changes and restarts port-forward automatically
- 🎯 **Interactive Selection**: Choose services with a colorful, intuitive interface
- 🌈 **Color-coded Status**: Green for services with endpoints, red for those without
- 🔍 **Multi-resource Support**: Services, pods, deployments, etc.
- 🔐 **Smart Port Handling**: Automatically detects privileged port issues (< 1024) and suggests alternatives

## Installation

**Note**: The `oh-my-zsh` kubectl plugin will conflict with this `kpf` command. You must unalias `kpf` before using this tool.

```sh
echo "unalias kpf" >> ~/.zshrc
```

### Homebrew (Recommended)

```bash
brew tap jessegoodier/kpf
brew install kpf
```

Or install directly:

```bash
brew install jessegoodier/kpf/kpf
```

### Using pipx

```bash
pipx install kpf
```

### Using uv

If you have `uv` installed, you can install `kpf` with:

```bash
uv tool install kpf
```

Install `uv` with pipx (brew can be behind):

```bash
pipx install uv
```

## Usage

### Interactive Mode (Recommended)

**Warm Tip**: You can use the interactive mode to find the service you want, and it will output the command to connect to that service directly next time.

**Note**: You might think that "warm tip" is something that AI wrote, but that's not the case. It really is just a little bit cooler than a hot tip.

![screenshot1](kpf-screenshot1.png)
![screenshot2](kpf-screenshot2.png)
![screenshot3](kpf-screenshot3.png)

Select services interactively:

Interactive selection in current namespace:

```bash
kpf
```

Interactive selection in specific namespace:

```bash
kpf -n production
```

Interactive selection with namespace prompt:

```bash
kpf -pn
```

Show all services across all namespaces:

```bash
kpf --all
```

Include pods and deployments with ports defined:

```bash
kpf --all-ports
```

Combine a few options (interactive mode, all services, and endpoint status checking, debug mode):

```bash
kpf -pAdl
```

### Check Mode

Add endpoint status checking to service selection (slower but shows endpoint health):

```bash
# Interactive selection with endpoint status
kpf --check

# Show all services with endpoint status
kpf --all --check

# Include pods and deployments with status
kpf --all-ports --check
```

### Legacy Mode

Direct port-forward (maintain expected behavior):

```bash
# Traditional kubectl port-forward syntax
kpf svc/frontend 8080:8080 -n production
kpf pod/my-pod 3000:3000
```

### Command Options

```sh

Example usage:
  kpf                                           # Interactive mode
  kpf svc/frontend 8080:8080 -n production      # Direct port-forward (maintain expected behavior)
  kpf -n production                             # Interactive selection in specific namespace
  kpf --all (or -A)                             # Show all services across all namespaces
  kpf --all-ports (or -l)                       # Show all services with their ports
  kpf --check -n production                     # Interactive selection with endpoint status
  kpf --prompt-namespace (or -pn)               # Interactive namespace selection
  kpf -0                                        # Listen on 0.0.0.0 (all interfaces)
```

## Examples

### Interactive Service Selection

Fast mode (without endpoint checking):

```bash
$ kpf -n kube-system

Services in namespace: kube-system

#    Type     Name                    Ports
1    SERVICE  kube-dns               53, 9153
2    SERVICE  metrics-server         443
3    SERVICE  kubernetes-dashboard   443

Select a service [1]: 1
Local port (press Enter for 53): 5353
```

With endpoint status checking:

```bash
$ kpf --check -n kube-system

Services in namespace: kube-system

#    Type     Name                    Ports           Status
1    SERVICE  kube-dns               53, 9153         ✓
2    SERVICE  metrics-server         443              ✓
3    SERVICE  kubernetes-dashboard   443              ✗

✓ = Has endpoints  ✗ = No endpoints

Select a service [1]: 1
Local port (press Enter for 53): 5353
```

### Cross-Namespace Discovery

```bash
$ kpf --all

Services across all namespaces

#    Namespace    Type     Name           Ports        Status
1    default      SERVICE  kubernetes     443          ✓
2    kube-system  SERVICE  kube-dns      53, 9153     ✓
3    production   SERVICE  frontend      80, 443      ✓
4    production   SERVICE  backend       8080         ✗
```

### Smart Low Port Handling

When you try to use privileged ports (< 1024), `kpf` will detect the permission issue and offer to use a higher port automatically:

```bash
$ kpf -n monitoring svc/grafana 80:80

Error: Port 80 requires elevated privileges (root/sudo)
Low ports (< 1024) require administrator permissions on most systems

Suggested alternative: Use port 1080 instead?
This would forward: localhost:1080 -> service:80

Use suggested port? [Y/n]: y
Updated port mapping to 1080:80

Direct command: kpf svc/grafana 1080:80 -n monitoring

http://localhost:1080

🚀 port-forward started 🚀
```

This feature prevents confusing "port already in use" errors when the real issue is insufficient permissions.

## How It Works

1. **Port-Forward Thread**: Runs kubectl port-forward in a separate thread
2. **Endpoint Watcher**: Monitors endpoint changes using `kubectl get ep -w`
3. **Automatic Restart**: When endpoints change, gracefully restarts the port-forward
4. **Service Discovery**: Uses kubectl to discover services and their endpoint status

## Requirements

- kubectl configured with cluster access

## Configuration

kpf can be configured via `~/.config/kpf/kpf.json` (follows [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/basedir-spec-latest.html)).

All settings are optional with sensible defaults:

```json
{
    "autoSelectFreePort": true,
    "showDirectCommand": true,
    "showDirectCommandIncludeContext": true,
    "directCommandMultiLine": true,
    "autoReconnect": true,
    "reconnectAttempts": 30,
    "reconnectDelaySeconds": 5,
    "captureUsageDetails": false,
    "usageDetailFolder": "${HOME}/.config/kpf/usage-details"
}
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `autoSelectFreePort` | boolean | `true` | When requested port is busy, automatically try next ports (9091, 9092, etc.) |
| `showDirectCommand` | boolean | `true` | Show the direct `kpf` command for future use |
| `showDirectCommandIncludeContext` | boolean | `true` | Include kubectl context in the command display |
| `directCommandMultiLine` | boolean | `true` | Format direct command across multiple lines for readability |
| `autoReconnect` | boolean | `true` | Automatically reconnect when connection drops |
| `reconnectAttempts` | integer | `30` | Number of reconnection attempts before giving up |
| `reconnectDelaySeconds` | integer | `5` | Delay in seconds between reconnection attempts |
| `captureUsageDetails` | boolean | `false` | Capture usage details locally for debugging (not sent anywhere) |
| `usageDetailFolder` | string | `${HOME}/.config/kpf/usage-details` | Where to store usage detail logs |

**Notes:**
- All settings are optional - kpf will use defaults if the config file doesn't exist
- Environment variables like `${HOME}` are expanded automatically
- The config file location respects the `XDG_CONFIG_HOME` environment variable
- Invalid JSON or unknown keys will show warnings but won't prevent kpf from running
- CLI arguments override config file values when provided

### Example: Minimal Configuration

If you only want to change specific settings:

```json
{
    "showDirectCommand": false,
    "reconnectAttempts": 10
}
```

## Development

### Setup Development Environment

```bash
# Clone the repository
git clone https://github.com/jessegoodier/kpf.git
cd kpf

# Install with development dependencies
uv venv
uv pip install -e ".[dev]"
source .venv/bin/activate
```

### Code Quality Tools

```bash
# Format and lint code
uvx ruff check . --fix
uvx ruff format .

# Sort imports
uvx isort .

# Run tests
uv run pytest
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests and linting
5. Submit a pull request

## Shell Completion

Shell completion scripts are available in the `completions/` directory.

### Homebrew

If you installed via Homebrew (and the formula is updated), completions should be installed automatically. You may need to follow Homebrew's [shell completion instructions](https://docs.brew.sh/Shell-Completion) to ensure it's loaded.

### Manual Installation

#### Zsh

```zsh
# Add the completions directory to your fpath
fpath=(path/to/kpf/completions $fpath)
autoload -U compinit; compinit
```

#### Bash

```bash
source path/to/kpf/completions/kpf.bash
```

## License

MIT License - see [LICENSE](LICENSE) file for details.

<p align="center">
  <a href="https://www.buymeacoffee.com/jessegoodier">
    <img src="https://img.buymeacoffee.com/button-api/?text=Buy me a coffee&emoji=&slug=jessegoodier&button_colour=FFDD00&font_colour=000000&font_family=Cookie&outline_colour=000000&coffee_colour=ffffff" />
  </a>
</p>
