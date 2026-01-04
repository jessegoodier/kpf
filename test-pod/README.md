# KPF Test Application

A simple Python web application designed specifically for testing `kpf` (kubectl port-forward) functionality. The app tracks and displays container uptime and provides multiple endpoints for testing various port-forwarding scenarios.

## Features

- **Uptime Tracking**: Shows how long the container has been running
- **Multiple Endpoints**: Various endpoints to test different scenarios
- **Auto-refreshing Web UI**: HTML interface that updates every 5 seconds
- **Health Checks**: Built-in liveness and readiness probe endpoints
- **JSON APIs**: RESTful endpoints for programmatic access
- **Metrics**: Prometheus-style metrics endpoint

## Endpoints

- `/` - Interactive HTML dashboard (auto-refreshes every 5 seconds)
- `/health` - Health check endpoint (JSON)
- `/api/uptime` - Uptime data (JSON)
- `/metrics` - Prometheus-style metrics

## Quick Deployment

Deploy the test application to your Kubernetes cluster:

```bash
# Navigate to test-pod directory
cd test-pod

# Deploy all resources
kubectl apply -f .

# Check deployment status
kubectl get pods -l app=kpf-test-app
kubectl get svc kpf-test-app-service
```

## Testing with KPF

Once deployed, test the kpf tool:

```bash
# Interactive service selection
kpf

# Direct port-forward to the service
kpf svc/kpf-test-app-service 8080:8080

# Port-forward with namespace
kpf svc/kpf-test-app-service 3000:8080 -n default

# Test multiple ports (service has port 8080 and 9090)
kpf --check  # Check endpoint status
```

Then open your browser to:

- `http://localhost:8080` (or whatever local port you chose)
- Watch the uptime counter increase in real-time
- Test the auto-restart functionality by deleting the pod

## Architecture

The application is built with:

- **ConfigMap**: Contains the Python application code
- **Deployment**: Runs the app in a `python:3.12-slim` container
- **Service**: Exposes the app on ports 8080 and 9090
- **Health Probes**: Kubernetes liveness and readiness checks

## Example Output

### HTML Interface

Visit the root endpoint to see:

```
🚀 KPF Test Application
Uptime: 2m 34s

Container Details:
Started: 2025-01-13T10:30:15.123456+00:00
Current Time: 2025-01-13T10:32:49.789012+00:00
Uptime (seconds): 154
```

### JSON API

```json
{
  "uptime_seconds": 154,
  "uptime_human": "2m 34s",
  "started_at": "2025-01-13T10:30:15.123456+00:00",
  "current_time": "2025-01-13T10:32:49.789012+00:00",
  "container_name": "kpf-test-app",
  "version": "1.0.0"
}
```

### Metrics

```
# HELP app_uptime_seconds Total uptime of the application in seconds
# TYPE app_uptime_seconds counter
app_uptime_seconds 154

# HELP app_start_time_seconds Unix timestamp when the application started
# TYPE app_start_time_seconds gauge
app_start_time_seconds 1736765415.123456
```

## Resource Usage

The application is designed to be lightweight:

- **Memory**: 32Mi request, 128Mi limit
- **CPU**: 10m request, 100m limit
- **Security**: Runs as non-root user with minimal privileges

## Cleanup

Remove all resources:

```bash
kubectl delete -f .
```

## Troubleshooting

### Pod not starting?

```bash
kubectl describe pod -l app=kpf-test-app
kubectl logs -l app=kpf-test-app
```

### Service not accessible?

```bash
kubectl get svc kpf-test-app-service
kubectl describe svc kpf-test-app-service
kubectl get endpoints kpf-test-app-service
```

### ConfigMap issues?

```bash
kubectl describe configmap kpf-test-app-config
kubectl get configmap kpf-test-app-config -o yaml
```

## Perfect for Testing

This application is ideal for testing kpf because it:

1. **Shows real-time updates**: Uptime increases every second
2. **Has multiple ports**: Test port selection functionality  
3. **Includes health checks**: Verify endpoint detection
4. **Provides visual feedback**: Easy to see if port-forwarding works
5. **Handles restarts**: Test automatic reconnection when pods restart
6. **Minimal resource usage**: Won't impact your cluster

Happy testing with kpf! 🚀
