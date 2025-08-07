# kpf - Kubectl Port-Forward Restarter

A Python utility that automatically restarts kubectl port-forward when endpoint changes are detected. Features interactive service discovery with colored tables and support for multiple Kubernetes resource types.

## Features

- 🔄 **Automatic Restart**: Monitors endpoint changes and restarts port-forward automatically
- 🎯 **Interactive Selection**: Choose services with a colorful, intuitive interface
- 🌈 **Color-coded Status**: Green for services with endpoints, red for those without
- 🔍 **Multi-resource Support**: Services, pods, deployments, and more
- 📊 **Rich Tables**: Beautiful formatted output with port information
- 🏷️ **Namespace Aware**: Work with specific namespaces or across all namespaces

## Installation

**Note**: `oh-my-zsh` kubectl plugin will conflict with this `kpf` command. If you prefer this tool, you can alias at the bottom of your `~/.zshrc` file or use a different alias.

If you have `uv` installed, you can install `kpf` with:

```bash
alias kpf="uvx kpf"
```

Install uv with pipx:

```bash
pipx install uv
```

## Usage

### Interactive Mode (Recommended)

Select services interactively with a colored table:

```bash
# Interactive selection in current namespace
kpf --prompt

# or just:
kpf -p

# Interactive selection in specific namespace
kpf --prompt -n production

# or just:
kpf -p -n production

# Show all services across all namespaces
kpf --all

# Include pods and deployments with ports defined
kpf --all-ports
```

### Check Mode

Add endpoint status checking to service selection (slower but shows endpoint health):

```bash
# Interactive selection with endpoint status
kpf --prompt --check

# Show all services with endpoint status
kpf --all --check

# Include pods and deployments with status
kpf --all-ports --check
```

### Legacy Mode

Direct port-forward (backward compatible):

```bash
# Traditional kubectl port-forward syntax
kpf svc/frontend 8080:8080 -n production
kpf pod/my-pod 3000:3000
```

### Command Options

```
Options:
  -p, --prompt          Interactive service selection
  -n, --namespace       Specify kubernetes namespace
  -A, --all            Show all services across all namespaces
  -l, --all-ports      Include ports from pods, deployments, etc.
  -c, --check          Include endpoint status in service selection table
  -h, --help           Show help message
  -v, --version        Show version
```

## Examples

### Interactive Service Selection

Fast mode (without endpoint checking):

```bash
$ kpf --prompt -n kube-system

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
$ kpf --prompt --check -n kube-system

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

## How It Works

1. **Port-Forward Thread**: Runs kubectl port-forward in a separate thread
2. **Endpoint Watcher**: Monitors endpoint changes using `kubectl get ep -w`
3. **Automatic Restart**: When endpoints change, gracefully restarts the port-forward
4. **Service Discovery**: Uses kubectl to discover services and their endpoint status

## Requirements

- Python 3.8+
- kubectl configured with cluster access
- Rich library for colored output

## Development

### Setup Development Environment

```bash
# Clone the repository
git clone https://github.com/jessegoodier/kpf.git
cd kpf

# Install with development dependencies
uv pip install -e ".[dev]"
```

### Code Quality Tools

```bash
# Format and lint code
ruff check src/
ruff check src/ --fix

# Sort imports
isort src/

# Run tests
pytest

# Bump version
bump-my-version bump patch  # or minor, major
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests and linting
5. Submit a pull request

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Changelog

### v0.1.0

- Initial release
- Interactive service selection
- Automatic port-forward restart
- Multi-namespace support
- Color-coded service status
- Support for pods and deployments
