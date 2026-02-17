import time

from rich.console import Console

# Initialize Rich console globally
console = Console()


class Debug:
    def __init__(self):
        self.enabled = False
        self.message_timestamps = {}
        self.MESSAGE_INTERVAL = 2.0  # Minimum interval between repeated debug messages

    def print(self, message: str, rate_limit: bool = False):
        """Print debug message with optional rate limiting.

        Args:
            message: The debug message to print
            rate_limit: If True, rate limit this message to once every MESSAGE_INTERVAL seconds
        """
        if not self.enabled:
            return

        if rate_limit:
            current_time = time.time()
            message_key = message[:50]  # Use first 50 chars as key to group similar messages

            last_time = self.message_timestamps.get(message_key, 0)
            if current_time - last_time < self.MESSAGE_INTERVAL:
                return  # Rate limited

            self.message_timestamps[message_key] = current_time

        console.print(f"[dim cyan][DEBUG][/dim cyan] {message}")


# Global debug instance
debug = Debug()
