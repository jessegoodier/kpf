# Recording the kpf Demo GIF

The `demo.gif` in the README is recorded using [VHS](https://github.com/charmbracelet/vhs), a terminal recording tool by Charm.

## Prerequisites

- [VHS](https://github.com/charmbracelet/vhs) installed (`brew install vhs` or `go install github.com/charmbracelet/vhs@latest`)
- [ffmpeg](https://ffmpeg.org/) (required by VHS for gif encoding)
- A running Kubernetes cluster with a service to port-forward to
- `kpf` installed and available in your PATH

## How the Demo Works

The `demo.tape` file defines the recording script:

1. **Hidden setup** - Sets a clean shell prompt, and schedules a background `kubectl delete pod` command with a delay (to trigger endpoint changes while kpf is running)
2. **Visible recording** - Types and runs the `kpf` command to port-forward to Prometheus
3. **Auto-reconnect** - The background pod deletion triggers endpoint changes, and kpf automatically detects and reconnects
4. **Clean exit** - Sends Ctrl+C for a graceful shutdown

## Recording a New Demo

### 1. Ensure your cluster has a target service running

The current demo uses Prometheus in the `monitoring` namespace:

```bash
kubectl get svc -n monitoring kube-prometheus-stack-prometheus
kubectl get pod -n monitoring -l app.kubernetes.io/name=prometheus
```

### 2. Edit `demo.tape` if needed

Update the service name, namespace, or pod name to match your cluster. Key lines to change:

- The `kubectl delete pod` command (line with `sleep 8 &&`)
- The `kpf` command line

### 3. Generate the gif

```bash
vhs demo.tape
```

This will create `demo.gif` in the current directory. The recording takes about 40 seconds.

### 4. Verify the output

Check the gif plays correctly and shows the connect -> reconnect -> exit cycle:

```bash
# Check duration
ffprobe -v quiet -print_format json -show_format demo.gif | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Duration: {d[\"format\"][\"duration\"]}s')"

# Extract a frame at a specific timestamp to inspect
ffmpeg -ss 15 -i demo.gif -frames:v 1 /tmp/demo_check.png -y
```

### 5. Wait for the pod to recover before re-recording

If you need to re-record, wait for the pod to be ready again:

```bash
kubectl get pod -n monitoring -l app.kubernetes.io/name=prometheus -w
```

## VHS Settings

| Setting | Value | Notes |
|---------|-------|-------|
| FontSize | 16 | Clear text at reasonable size |
| Width | 900 | Wide enough for kpf output |
| Height | 500 | Tall enough for reconnect messages |
| Framerate | 30 | Smooth animation |
| TypingSpeed | 40ms | Natural typing speed |
| Theme | Catppuccin Mocha | Dark theme matching terminal aesthetics |

## Tips

- Keep the demo under 45 seconds for a reasonable gif file size
- Use `--grace-period=1` on the pod delete to speed up the reconnect cycle
- Use `disown` after the background job to suppress job control messages
- Redirect kubectl delete output to `/dev/null` to keep it hidden
