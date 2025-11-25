#!/usr/bin/env python3
"""
CrowdCount Main Orchestrator
Manages device startup: provisions if no WiFi, streams if connected
"""

import os
import sys
import time
import subprocess
import signal
from pathlib import Path

# Paths
SCRIPT_DIR = Path(__file__).parent
PROVISIONING_DIR = SCRIPT_DIR / "src" / "provisioning"
STREAM_DIR = SCRIPT_DIR / "src" / "counter-stream"

PROVISIONED_FLAGS = [
    Path("/boot/firmware/provisioned"),
    Path("/boot/provisioned")
]

DEVICE_CONFIG = STREAM_DIR / "device-info.conf"


class CrowdCountMain:
    """Main orchestrator for CrowdCount device"""

    def __init__(self):
        self.running = True
        self.current_process = None

    def check_wifi_connected(self):
        """Check if WiFi is currently connected"""
        try:
            result = subprocess.run(
                ['iwgetid'],
                capture_output=True,
                timeout=5
            )
            connected = result.returncode == 0

            if connected:
                # Get SSID for display
                try:
                    ssid = subprocess.run(
                        ['iwgetid', '-r'],
                        capture_output=True,
                        timeout=5,
                        text=True
                    ).stdout.strip()
                    return True, ssid
                except:
                    return True, "unknown"

            return False, None
        except Exception as e:
            print(f"⚠ Error checking WiFi: {e}")
            return False, None

    def is_provisioned(self):
        """Check if device has been provisioned"""
        return any(flag.exists() for flag in PROVISIONED_FLAGS)

    def has_device_config(self):
        """Check if device configuration exists"""
        return DEVICE_CONFIG.exists()

    def run_provisioning(self):
        """Run the provisioning process"""
        print("\n" + "="*60)
        print("STARTING PROVISIONING MODE")
        print("="*60)
        print("Device is not connected to WiFi")
        print("Starting Bluetooth provisioning...")
        print("="*60 + "\n")

        provision_script = PROVISIONING_DIR / "provision_manager.py"

        try:
            # Run provisioning as a subprocess
            self.current_process = subprocess.Popen(
                [sys.executable, str(provision_script)],
                cwd=str(PROVISIONING_DIR)
            )

            # Wait for provisioning to complete
            return_code = self.current_process.wait()
            self.current_process = None

            if return_code == 0:
                print("\n✓ Provisioning completed successfully")
                return True
            else:
                print(f"\n⚠ Provisioning exited with code {return_code}")
                return False

        except Exception as e:
            print(f"\n✗ Error running provisioning: {e}")
            self.current_process = None
            return False

    def run_streaming(self):
        """Run the streaming process"""
        print("\n" + "="*60)
        print("STARTING STREAMING MODE")
        print("="*60)
        print("Device is connected and provisioned")
        print("Starting camera stream...")
        print("="*60 + "\n")

        stream_script = STREAM_DIR / "start_stream.sh"

        try:
            # Run streaming as a subprocess
            self.current_process = subprocess.Popen(
                ['/bin/bash', str(stream_script)],
                cwd=str(STREAM_DIR)
            )

            # Wait for streaming to complete (runs indefinitely)
            return_code = self.current_process.wait()
            self.current_process = None

            if return_code == 0:
                print("\n✓ Streaming stopped normally")
                return True
            else:
                print(f"\n⚠ Streaming exited with code {return_code}")
                return False

        except Exception as e:
            print(f"\n✗ Error running streaming: {e}")
            self.current_process = None
            return False

    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(sig, frame):
            print("\n⚠ Received shutdown signal")
            self.running = False

            if self.current_process:
                print("Stopping current process...")
                try:
                    self.current_process.terminate()
                    self.current_process.wait(timeout=5)
                except:
                    self.current_process.kill()

            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    def run(self):
        """Main orchestration loop"""
        self.setup_signal_handlers()

        print("\n" + "="*60)
        print("CROWDCOUNT DEVICE STARTUP")
        print("="*60)
        print(f"Working Directory: {SCRIPT_DIR}")
        print("="*60 + "\n")

        # Main decision loop
        while self.running:
            # Check WiFi status
            wifi_connected, ssid = self.check_wifi_connected()
            is_provisioned = self.is_provisioned()
            has_config = self.has_device_config()

            print(f"Status Check:")
            print(f"  WiFi Connected: {wifi_connected} {f'({ssid})' if ssid else ''}")
            print(f"  Provisioned: {is_provisioned}")
            print(f"  Config Exists: {has_config}")
            print()

            # Decision logic
            if not wifi_connected:
                # No WiFi → provision
                print("Decision: Device needs provisioning (no WiFi)")
                success = self.run_provisioning()

                if success:
                    # After provisioning, recheck and potentially start streaming
                    print("\nRechecking status after provisioning...")
                    time.sleep(2)
                    continue
                else:
                    # Provisioning failed, wait and retry
                    print("\nProvisioning failed. Retrying in 30 seconds...")
                    time.sleep(30)
                    continue

            elif wifi_connected and is_provisioned and has_config:
                # Connected and ready → stream
                print("Decision: Starting streaming")
                success = self.run_streaming()

                if not success:
                    # Streaming failed, wait and retry
                    print("\nStreaming failed. Retrying in 10 seconds...")
                    time.sleep(10)
                    continue
                else:
                    # Streaming stopped normally (shouldn't happen)
                    print("\nStreaming stopped. Restarting in 10 seconds...")
                    time.sleep(10)
                    continue

            else:
                # Connected but not fully provisioned
                print("Decision: WiFi connected but device not fully provisioned")
                print("Starting provisioning to complete setup...")
                success = self.run_provisioning()

                if success:
                    print("\nSetup complete. Rechecking status...")
                    time.sleep(2)
                    continue
                else:
                    print("\nSetup failed. Retrying in 30 seconds...")
                    time.sleep(30)
                    continue


def main():
    """Entry point"""
    main_orchestrator = CrowdCountMain()
    main_orchestrator.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
