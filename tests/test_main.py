"""Tests for main module."""

import pytest
import threading
import time
from unittest.mock import Mock, patch, MagicMock
from src.kpf.main import (
    get_port_forward_args,
    get_watcher_args,
    run_port_forward,
    restart_event,
    shutdown_event
)


class TestArgumentParsing:
    """Test argument parsing functions."""
    
    def test_get_port_forward_args_valid(self):
        """Test get_port_forward_args with valid arguments."""
        args = ["svc/frontend", "8080:8080", "-n", "production"]
        result = get_port_forward_args(args)
        assert result == args
    
    def test_get_port_forward_args_empty(self):
        """Test get_port_forward_args with empty arguments."""
        with patch('sys.exit') as mock_exit:
            get_port_forward_args([])
            mock_exit.assert_called_once_with(1)
    
    def test_get_watcher_args_service_with_namespace(self):
        """Test get_watcher_args with service and namespace."""
        args = ["svc/frontend", "8080:8080", "-n", "production"]
        namespace, resource_name = get_watcher_args(args)
        
        assert namespace == "production"
        assert resource_name == "frontend"
    
    def test_get_watcher_args_service_default_namespace(self):
        """Test get_watcher_args with service but no namespace."""
        args = ["svc/api-service", "8080:8080"]
        namespace, resource_name = get_watcher_args(args)
        
        assert namespace == "default"
        assert resource_name == "api-service"
    
    def test_get_watcher_args_pod(self):
        """Test get_watcher_args with pod resource."""
        args = ["pod/my-pod", "3000:3000", "-n", "kube-system"]
        namespace, resource_name = get_watcher_args(args)
        
        assert namespace == "kube-system"
        assert resource_name == "my-pod"
    
    def test_get_watcher_args_deployment(self):
        """Test get_watcher_args with deployment resource."""
        args = ["deployment/my-deploy", "8080:8080"]
        namespace, resource_name = get_watcher_args(args)
        
        assert namespace == "default"
        assert resource_name == "my-deploy"
    
    def test_get_watcher_args_service_full_name(self):
        """Test get_watcher_args with full 'service' name."""
        args = ["service/web-service", "80:8080"]
        namespace, resource_name = get_watcher_args(args)
        
        assert namespace == "default"
        assert resource_name == "web-service"
    
    def test_get_watcher_args_no_resource(self):
        """Test get_watcher_args with no recognizable resource."""
        args = ["8080:8080", "-n", "production"]
        
        with patch('sys.exit') as mock_exit:
            get_watcher_args(args)
            mock_exit.assert_called_once_with(1)
    
    def test_get_watcher_args_namespace_at_end(self):
        """Test get_watcher_args with namespace flag at the end."""
        args = ["svc/backend", "9090:9090", "-n"]
        
        # Should handle incomplete -n flag gracefully
        namespace, resource_name = get_watcher_args(args)
        assert namespace == "default"  # Falls back to default
        assert resource_name == "backend"


class TestDebugMode:
    """Test debug functionality."""
    
    def test_debug_disabled_by_default(self):
        """Test that debug is disabled by default."""
        from src.kpf.main import _debug_enabled, debug
        
        # Initially should be disabled
        assert _debug_enabled is False
        
        # Debug prints should not output when disabled
        with patch('src.kpf.main.console.print') as mock_print:
            debug.print("test message")
            mock_print.assert_not_called()
    
    def test_debug_enabled(self):
        """Test debug when enabled."""
        with patch('src.kpf.main._debug_enabled', True), \
             patch('src.kpf.main.console.print') as mock_print:
            
            from src.kpf.main import debug
            debug.print("test debug message")
            
            mock_print.assert_called_once()
            args = mock_print.call_args[0]
            assert "test debug message" in args[0]
            assert "[DEBUG]" in args[0]


class TestRunPortForward:
    """Test run_port_forward function."""
    
    def setUp(self):
        """Reset threading events before each test."""
        restart_event.clear()
        shutdown_event.clear()
    
    def tearDown(self):
        """Clean up threading events after each test."""
        restart_event.clear()
        shutdown_event.clear()
    
    @patch('src.kpf.main.threading.Thread')
    @patch('src.kpf.main.get_watcher_args')
    def test_run_port_forward_basic(self, mock_get_watcher, mock_thread):
        """Test basic run_port_forward execution."""
        mock_get_watcher.return_value = ("default", "test-service")
        
        # Mock threads
        mock_pf_thread = Mock()
        mock_ew_thread = Mock()
        mock_pf_thread.is_alive.return_value = True
        mock_ew_thread.is_alive.return_value = True
        
        mock_thread.side_effect = [mock_pf_thread, mock_ew_thread]
        
        args = ["svc/test-service", "8080:8080"]
        
        # Mock the main loop to exit quickly
        with patch('time.sleep', side_effect=[None, KeyboardInterrupt]):
            with pytest.raises(KeyboardInterrupt):
                run_port_forward(args)
        
        # Verify threads were created and started
        assert mock_thread.call_count == 2
        mock_pf_thread.start.assert_called_once()
        mock_ew_thread.start.assert_called_once()
        mock_pf_thread.join.assert_called_once()
        mock_ew_thread.join.assert_called_once()
    
    @patch('src.kpf.main.threading.Thread')
    @patch('src.kpf.main.get_watcher_args')
    def test_run_port_forward_debug_mode(self, mock_get_watcher, mock_thread):
        """Test run_port_forward with debug mode enabled."""
        mock_get_watcher.return_value = ("default", "test-service")
        
        # Mock threads that exit immediately
        mock_pf_thread = Mock()
        mock_ew_thread = Mock()
        mock_pf_thread.is_alive.return_value = False
        mock_ew_thread.is_alive.return_value = False
        
        mock_thread.side_effect = [mock_pf_thread, mock_ew_thread]
        
        args = ["svc/test-service", "8080:8080"]
        
        with patch('src.kpf.main.console.print') as mock_print:
            run_port_forward(args, debug_mode=True)
        
        # Verify debug messages were printed
        debug_calls = [call for call in mock_print.call_args_list 
                      if '[DEBUG]' in str(call)]
        assert len(debug_calls) > 0
    
    @patch('src.kpf.main.threading.Thread')
    @patch('src.kpf.main.get_watcher_args')
    def test_run_port_forward_keyboard_interrupt(self, mock_get_watcher, mock_thread):
        """Test run_port_forward handling keyboard interrupt."""
        mock_get_watcher.return_value = ("default", "test-service")
        
        # Mock threads
        mock_pf_thread = Mock()
        mock_ew_thread = Mock()
        mock_pf_thread.is_alive.return_value = True
        mock_ew_thread.is_alive.return_value = True
        
        mock_thread.side_effect = [mock_pf_thread, mock_ew_thread]
        
        args = ["svc/test-service", "8080:8080"]
        
        # Simulate KeyboardInterrupt in main loop
        with patch('time.sleep', side_effect=KeyboardInterrupt):
            run_port_forward(args)
        
        # Verify graceful shutdown
        mock_pf_thread.join.assert_called_once()
        mock_ew_thread.join.assert_called_once()


class TestPortForwardThread:
    """Test port-forward thread functionality."""
    
    def test_port_forward_thread_args_parsing(self):
        """Test that port-forward thread receives correct arguments."""
        from src.kpf.main import port_forward_thread
        
        args = ["svc/test", "8080:8080", "-n", "default"]
        
        with patch('subprocess.Popen') as mock_popen:
            mock_process = Mock()
            mock_popen.return_value = mock_process
            
            # Set shutdown event to exit quickly
            shutdown_event.set()
            
            port_forward_thread(args)
            
            # Verify kubectl port-forward was called with correct args
            mock_popen.assert_called_once()
            call_args = mock_popen.call_args[0][0]
            assert call_args == ["kubectl", "port-forward"] + args
        
        shutdown_event.clear()


class TestEndpointWatcherThread:
    """Test endpoint watcher thread functionality."""
    
    def test_endpoint_watcher_thread_args(self):
        """Test that endpoint watcher thread uses correct kubectl command."""
        from src.kpf.main import endpoint_watcher_thread
        
        namespace = "production"
        resource_name = "my-service"
        
        with patch('subprocess.Popen') as mock_popen:
            mock_process = Mock()
            mock_process.stdout = iter([])  # Empty output
            mock_popen.return_value = mock_process
            
            # Set shutdown event to exit quickly
            shutdown_event.set()
            
            endpoint_watcher_thread(namespace, resource_name)
            
            # Verify kubectl get ep command was called correctly
            mock_popen.assert_called_once()
            call_args = mock_popen.call_args[0][0]
            expected_cmd = [
                "kubectl", "get", "--no-headers", "ep", "-w", 
                "-n", namespace, resource_name
            ]
            assert call_args == expected_cmd
        
        shutdown_event.clear()
    
    def test_endpoint_watcher_restart_event(self):
        """Test that endpoint watcher sets restart event on changes."""
        from src.kpf.main import endpoint_watcher_thread
        
        namespace = "default"
        resource_name = "test-service"
        
        # Mock subprocess output with endpoint changes
        mock_lines = [
            "HEADER LINE",  # First line should be ignored
            "test-service   10.0.0.1:8080   1m",  # This should trigger restart
        ]
        
        with patch('subprocess.Popen') as mock_popen:
            mock_process = Mock()
            mock_process.stdout = iter(mock_lines)
            mock_popen.return_value = mock_process
            
            # Clear restart event initially
            restart_event.clear()
            
            # Run in separate thread to avoid blocking
            thread = threading.Thread(
                target=endpoint_watcher_thread,
                args=(namespace, resource_name)
            )
            thread.start()
            
            # Wait a bit for processing
            time.sleep(0.1)
            
            # Stop the thread
            shutdown_event.set()
            thread.join(timeout=1)
            
            # Verify restart event was set
            assert restart_event.is_set()
        
        # Clean up
        restart_event.clear()
        shutdown_event.clear()