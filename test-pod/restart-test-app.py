#!/usr/bin/env python3

"""
Simple test application that serves uptime information on port 8080.
Perfect for testing kubectl port-forward functionality with kpf.
"""

import json
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

# Track when the container started
START_TIME = time.time()
START_DATETIME = datetime.now(timezone.utc)


class UptimeHandler(BaseHTTPRequestHandler):
    """HTTP request handler that serves uptime information."""

    def do_GET(self):
        """Handle GET requests."""
        path = urlparse(self.path).path
        # query_params = parse_qs(urlparse(self.path).query)

        # Calculate uptime
        current_time = time.time()
        uptime_seconds = int(current_time - START_TIME)

        # Prepare response data
        response_data = {
            "uptime_seconds": uptime_seconds,
            "uptime_human": self._format_uptime(uptime_seconds),
            "started_at": START_DATETIME.isoformat(),
            "current_time": datetime.now(timezone.utc).isoformat(),
            "container_name": "kpf-test-app",
            "version": "1.0.0",
        }

        # Handle different endpoints
        if path == "/":
            self._serve_html(response_data)
        elif path == "/health":
            self._serve_json({"status": "healthy", "uptime_seconds": uptime_seconds})
        elif path == "/metrics":
            self._serve_metrics(uptime_seconds)
        elif path == "/api/uptime":
            self._serve_json(response_data)
        else:
            self._serve_404()

    def _serve_html(self, data):
        """Serve HTML response for the root endpoint."""
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>KPF Test App</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; background-color: #f5f5f5; }}
        .container {{ max-width: 600px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .uptime {{ font-size: 2em; color: #2196F3; margin: 20px 0; }}
        .error {{ font-size: 1.5em; color: #f44336; margin: 20px 0; text-align: center; }}
        .details {{ background: #f8f9fa; padding: 15px; border-radius: 4px; margin: 20px 0; }}
        .endpoint {{ background: #e3f2fd; padding: 10px; margin: 10px 0; border-radius: 4px; }}
        .status {{ background: #e8f5e8; padding: 10px; margin: 10px 0; border-radius: 4px; text-align: center; }}
        code {{ background: #f5f5f5; padding: 2px 4px; border-radius: 2px; }}
        .loading {{ color: #ff9800; }}
    </style>
    <script>
        let isConnected = false;
        let reconnectAttempts = 0;
        let lastUpdateTime = null;

        function updateUptime() {{
            fetch('/api/uptime')
                .then(response => {{
                    if (response.ok) {{
                        return response.json();
                    }}
                    throw new Error('HTTP ' + response.status);
                }})
                .then(data => {{
                    isConnected = true;
                    reconnectAttempts = 0;
                    lastUpdateTime = new Date();

                    document.getElementById('uptime-display').innerHTML =
                        `<div class="uptime">Uptime: ${{data.uptime_human}}</div>`;

                    document.getElementById('status-display').innerHTML =
                        `<div class="status">✅ Connected - Last updated: ${{lastUpdateTime.toLocaleTimeString()}}</div>`;

                    document.getElementById('details-display').innerHTML = `
                        <div class="details">
                            <h3>Container Details:</h3>
                            <p><strong>Started:</strong> ${{data.started_at}}</p>
                            <p><strong>Current Time:</strong> ${{data.current_time}}</p>
                            <p><strong>Uptime (seconds):</strong> ${{data.uptime_seconds}}</p>
                        </div>
                    `;
                }})
                .catch(error => {{
                    isConnected = false;
                    reconnectAttempts++;

                    document.getElementById('uptime-display').innerHTML =
                        `<div class="error">❌ Service Unavailable</div>`;

                    document.getElementById('status-display').innerHTML =
                        `<div class="status">🔄 Reconnecting... (Attempt ${{reconnectAttempts}})</div>`;

                    document.getElementById('details-display').innerHTML = `
                        <div class="details">
                            <h3>Connection Status:</h3>
                            <p><strong>Status:</strong> <span class="loading">Disconnected</span></p>
                            <p><strong>Last Attempt:</strong> ${{new Date().toLocaleTimeString()}}</p>
                            <p><strong>Reconnect Attempts:</strong> ${{reconnectAttempts}}</p>
                            <p><em>Automatically retrying every 1 second...</em></p>
                        </div>
                    `;
                }});
        }}

        // Update immediately and then every 1 second
        updateUptime();
        setInterval(updateUptime, 1000);
    </script>
</head>
<body>
    <div class="container">
        <h1>kpf Test Application</h1>

        <div id="uptime-display">
            <div class="uptime">Uptime: {data["uptime_human"]}</div>
        </div>

        <div id="status-display">
            <div class="status">✅ Connected - Initial load</div>
        </div>

        <div id="details-display">
            <div class="details">
                <h3>Container Details:</h3>
                <p><strong>Started:</strong> {data["started_at"]}</p>
                <p><strong>Current Time:</strong> {data["current_time"]}</p>
                <p><strong>Uptime (seconds):</strong> {data["uptime_seconds"]}</p>
            </div>
        </div>

        <div class="endpoint">
            <h3>Available Endpoints:</h3>
            <ul>
                <li><code>/</code> - This page (auto-updates every 1 second)</li>
                <li><code>/health</code> - Health check (JSON)</li>
                <li><code>/api/uptime</code> - Uptime data (JSON)</li>
                <li><code>/metrics</code> - Prometheus-style metrics</li>
            </ul>
        </div>

        <p><em>Perfect for testing kubectl port-forward with kpf!</em></p>
    </div>
</body>
</html>
        """
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def _serve_json(self, data):
        """Serve JSON response."""
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

    def _serve_metrics(self, uptime_seconds):
        """Serve Prometheus-style metrics."""
        metrics = f"""# TYPE app_uptime_seconds counter
app_uptime_seconds {uptime_seconds}
"""
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(metrics.encode())

    def _serve_404(self):
        """Serve 404 response."""
        self.send_response(404)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"404 Not Found")

    def _format_uptime(self, seconds):
        """Format uptime in human-readable format."""
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            minutes = seconds // 60
            secs = seconds % 60
            return f"{minutes}m {secs}s"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            secs = seconds % 60
            return f"{hours}h {minutes}m {secs}s"

    def log_message(self, format, *args):
        """Log requests with timestamp."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"[{timestamp}] {format % args}")


def main():
    """Main function to start the HTTP server."""
    port = 8080
    server = HTTPServer(("", port), UptimeHandler)

    print("🚀 KPF Test App starting...")
    print(f"📊 Server listening on port {port}")
    print(f"🕒 Started at: {START_DATETIME.isoformat()}")
    print(f"🌐 Available at: http://localhost:{port}")
    print("💡 Use 'kpf' to port-forward to this service!")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Server stopped gracefully")
        server.server_close()


if __name__ == "__main__":
    main()
