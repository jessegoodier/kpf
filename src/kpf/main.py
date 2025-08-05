#!/usr/bin/env python3

import re
import subprocess
import sys
import threading
import time

restart_event = threading.Event()
shutdown_event = threading.Event()


def get_port_forward_args(args):
    """
    Parses command-line arguments to extract the port-forward arguments.
    """
    if not args:
        print("Usage: python kpf.py <kubectl port-forward args>")
        sys.exit(1)
    return args


def get_watcher_args(port_forward_args):
    """
    Parses port-forward arguments to determine the namespace and resource name
    for the endpoint watcher command.
    Example: `['svc/frontend', '9090:9090', '-n', 'kubecost']` -> namespace='kubecost', resource_name='frontend'
    """
    namespace = "default"
    resource_name = None

    # Find namespace
    try:
        n_index = port_forward_args.index("-n")
        if n_index + 1 < len(port_forward_args):
            namespace = port_forward_args[n_index + 1]
    except ValueError:
        # '-n' flag not found, use default namespace
        pass

    # Find resource name (e.g., 'svc/frontend')
    for arg in port_forward_args:
        # Use regex to match patterns like 'svc/my-service' or 'pod/my-pod'
        match = re.match(r"(svc|service|pod|deploy|deployment)\/(.+)", arg)
        if match:
            # The resource name is the second group in the regex match
            resource_name = match.group(2)
            break

    if not resource_name:
        print("Could not determine resource name for endpoint watcher.")
        sys.exit(1)

    return namespace, resource_name


def port_forward_thread(args):
    """
    This thread runs the kubectl port-forward command.
    It listens for the `restart_event` and restarts the process when it's set.
    """
    proc = None
    while not shutdown_event.is_set():
        try:
            print(f"\n[Port-Forwarder] Starting: kubectl port-forward {' '.join(args)}")
            proc = subprocess.Popen(
                ["kubectl", "port-forward"] + args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            # Wait for either a restart signal or a shutdown signal
            # The timeout prevents blocking forever and allows the loop to check for shutdown_event
            while not restart_event.is_set() and not shutdown_event.is_set():
                time.sleep(1)

            if proc:
                print("[Port-Forwarder] Restarting process...")
                proc.terminate()  # Gracefully terminate the process
                proc.wait(timeout=5)  # Wait for it to shut down
                if proc.poll() is None:
                    proc.kill()  # Force kill if it's still running
                    print("[Port-Forwarder] Process was forcefully killed.")
                proc = None

            restart_event.clear()  # Reset the event for the next cycle

        except Exception as e:
            print(f"[Port-Forwarder] An error occurred: {e}")
            if proc:
                proc.kill()
            shutdown_event.set()
            return

    if proc:
        proc.kill()


def endpoint_watcher_thread(namespace, resource_name):
    """
    This thread watches the specified endpoint for changes.
    When a change is detected, it sets the `restart_event`.
    """
    while not shutdown_event.is_set():
        try:
            print(
                f"[Watcher] Starting to watch endpoint changes for '{resource_name}' in namespace '{namespace}'..."
            )
            command = ["kubectl", "get", "ep", "-w", "-n", namespace, resource_name]

            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
            )

            # The `for` loop will block and yield lines as they are produced
            # by the subprocess's stdout.
            is_first_line = True
            for line in proc.stdout:
                if shutdown_event.is_set():
                    break

                # The first line is the table header, which we should ignore.
                if is_first_line:
                    is_first_line = False
                    continue

                print(
                    f"[Watcher] Endpoint change detected! Triggering port-forward restart."
                )
                restart_event.set()

            # If the subprocess finishes, we should break out and restart the watcher
            # This handles cases where the kubectl process itself might terminate.
            proc.wait()

        except Exception as e:
            print(f"[Watcher] An error occurred: {e}")
            shutdown_event.set()
            return

    if proc:
        proc.kill()


def run_port_forward(port_forward_args):
    """
    The main function to orchestrate the two threads.
    """
    print("kpf: Kubectl Port-Forward Restarter Utility")

    # Get watcher arguments from the port-forwarding args
    namespace, resource_name = get_watcher_args(port_forward_args)

    print(f"Port-forward arguments: {port_forward_args}")
    print(
        f"Endpoint watcher target: namespace={namespace}, resource_name={resource_name}"
    )

    # Create and start the two threads
    pf_t = threading.Thread(target=port_forward_thread, args=(port_forward_args,))
    ew_t = threading.Thread(
        target=endpoint_watcher_thread,
        args=(
            namespace,
            resource_name,
        ),
    )

    pf_t.start()
    ew_t.start()

    try:
        # Keep the main thread alive while the other threads are running
        while pf_t.is_alive() and ew_t.is_alive():
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[Main] Ctrl+C detected. Shutting down gracefully...")

    finally:
        # Signal a graceful shutdown
        shutdown_event.set()

        # Wait for both threads to finish
        pf_t.join()
        ew_t.join()
        print("[Main] All threads have shut down. Exiting.")


def main():
    """Legacy main function for backward compatibility."""
    port_forward_args = get_port_forward_args(sys.argv[1:])
    run_port_forward(port_forward_args)


if __name__ == "__main__":
    main()