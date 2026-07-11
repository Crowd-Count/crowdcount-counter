#!/usr/bin/env python3
"""
CrowdCount First-Boot Configuration

Runs once on first boot as a systemd one-shot service.
Reads /boot/firmware/device-identity.conf and:
  - Sets OS hostname to DEVICE_ID
  - Sets 'counter' user password to DEVICE_PASSWORD
  - Creates marker file so it never runs again

Must run before crowdcount-main.service.
"""

import configparser
import subprocess
import sys
import os
import logging

IDENTITY_PATHS = [
    "/boot/firmware/device-identity.conf",
    "/boot/device-identity.conf",
]
MARKER_FILE = "/boot/firmware/.firstboot-done"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [firstboot] %(message)s",
)
log = logging.getLogger("firstboot")


def find_identity_file():
    for path in IDENTITY_PATHS:
        if os.path.isfile(path):
            return path
    return None


def read_identity(path):
    config = configparser.ConfigParser()
    config.read(path)
    return dict(config["DEFAULT"])


def set_hostname(hostname):
    log.info("Setting hostname to: %s", hostname)
    subprocess.run(["hostnamectl", "set-hostname", hostname], check=True)

    # Also update /etc/hosts so sudo doesn't complain
    hosts_path = "/etc/hosts"
    try:
        with open(hosts_path, "r") as f:
            lines = f.readlines()
        with open(hosts_path, "w") as f:
            for line in lines:
                if "127.0.1.1" in line:
                    f.write(f"127.0.1.1\t{hostname}\n")
                else:
                    f.write(line)
    except Exception as e:
        log.warning("Could not update /etc/hosts: %s", e)

    # Restart NetworkManager so it re-sends the new hostname in DHCP requests.
    # Without this, the router sees the old master image hostname.
    try:
        subprocess.run(
            ["systemctl", "restart", "NetworkManager"], capture_output=True, timeout=10
        )
        log.info("Restarted NetworkManager with new hostname")
    except Exception as e:
        log.warning("Could not restart NetworkManager: %s", e)


def reset_tailscale_identity():
    """Reset Tailscale node identity so this cloned device registers as a new node.

    The master image has Tailscale authenticated with its own node key.
    Every clone shares that key — Tailscale thinks they're all the same machine.
    Only the last one to connect stays online. Logging out clears the node key
    so crowdcount-main.py can do a fresh `tailscale up` and get a unique identity.
    """
    log.info("Resetting Tailscale identity (cloned image → new node)...")
    try:
        # Stop tailscaled so we can safely clear state
        subprocess.run(
            ["systemctl", "stop", "tailscaled"], capture_output=True, timeout=10
        )

        # Remove all Tailscale state — node keys, machine keys, cached certs
        import shutil

        ts_state = "/var/lib/tailscale"
        if os.path.isdir(ts_state):
            for entry in os.listdir(ts_state):
                entry_path = os.path.join(ts_state, entry)
                try:
                    if os.path.isfile(entry_path):
                        os.remove(entry_path)
                    elif os.path.isdir(entry_path):
                        shutil.rmtree(entry_path)
                except Exception as e:
                    log.warning("Could not remove %s: %s", entry_path, e)
            log.info("Cleared Tailscale state directory")

        # Restart tailscaled with fresh state
        subprocess.run(
            ["systemctl", "start", "tailscaled"], capture_output=True, timeout=10
        )
        log.info(
            "Tailscale identity reset complete — will re-authenticate in crowdcount-main"
        )

    except FileNotFoundError:
        log.warning("tailscale/systemctl not found — skipping Tailscale reset")
    except Exception as e:
        log.warning("Could not reset Tailscale identity: %s", e)


def setup_root_ssh_keys():
    """Copy counter user's SSH keys to root so the updater service (which runs as root) can git pull."""
    root_ssh_dir = "/root/.ssh"
    counter_ssh_dir = "/home/counter/.ssh"

    os.makedirs(root_ssh_dir, mode=0o700, exist_ok=True)

    # Copy deploy key
    deploy_key = os.path.join(counter_ssh_dir, "crowdcount_deploy")
    if os.path.isfile(deploy_key):
        import shutil

        shutil.copy2(deploy_key, os.path.join(root_ssh_dir, "crowdcount_deploy"))
        os.chmod(os.path.join(root_ssh_dir, "crowdcount_deploy"), 0o600)
        log.info("Copied deploy key to root")
    else:
        log.warning("No deploy key found at %s", deploy_key)
        return

    # Copy SSH config
    ssh_config = os.path.join(counter_ssh_dir, "config")
    if os.path.isfile(ssh_config):
        shutil.copy2(ssh_config, os.path.join(root_ssh_dir, "config"))
        os.chmod(os.path.join(root_ssh_dir, "config"), 0o600)
        log.info("Copied SSH config to root")

    # Add GitHub to known_hosts
    known_hosts = os.path.join(root_ssh_dir, "known_hosts")
    try:
        result = subprocess.run(
            ["ssh-keyscan", "github.com"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.stdout:
            with open(known_hosts, "a") as f:
                f.write(result.stdout)
            os.chmod(known_hosts, 0o600)
            log.info("Added GitHub to root known_hosts")
    except Exception as e:
        log.warning("Could not scan GitHub host keys: %s", e)


def set_password(username, password):
    log.info("Setting password for user: %s", username)
    subprocess.run(
        ["chpasswd"],
        input=f"{username}:{password}\n",
        text=True,
        check=True,
    )


def create_marker():
    try:
        with open(MARKER_FILE, "w") as f:
            f.write("First boot completed\n")
        log.info("Marker created: %s", MARKER_FILE)
    except Exception as e:
        log.warning("Could not create marker file: %s", e)


def main():
    # Check if already ran
    if os.path.isfile(MARKER_FILE):
        log.info("Marker file exists (%s) — skipping first boot.", MARKER_FILE)
        return 0

    # Find identity file
    identity_path = find_identity_file()
    if not identity_path:
        log.error("No device-identity.conf found at: %s", IDENTITY_PATHS)
        log.error("Skipping first-boot configuration.")
        return 1

    log.info("Reading identity from: %s", identity_path)
    identity = read_identity(identity_path)

    device_id = identity.get("device_id", "").strip()
    device_password = identity.get("device_password", "").strip()

    if not device_id:
        log.error("DEVICE_ID not found in identity file.")
        return 1

    # Clear any WiFi credentials or provisioning state leaked from master image.
    # Defense-in-depth: manufacturing cleanup should catch these, but firstboot
    # catches anything missed so clones don't skip provisioning or auto-connect
    # to the master's WiFi.
    for stale_file in [
        "/boot/firmware/wifi-credentials.conf",
        "/boot/wifi-credentials.conf",
        "/boot/firmware/provisioned",
        "/boot/provisioned",
    ]:
        if os.path.isfile(stale_file):
            os.remove(stale_file)
            log.info("Cleared stale file from master image: %s", stale_file)

    # Reset Tailscale identity so this device registers as a NEW node.
    # The master image has Tailscale authenticated — all clones share the same
    # node key in /var/lib/tailscale/. Without this reset, only the last device
    # to boot would work (Tailscale sees them as the same machine).
    reset_tailscale_identity()

    # Set hostname (OS + Tailscale)
    try:
        set_hostname(device_id)
        log.info("Hostname set to: %s", device_id)
    except Exception as e:
        log.error("Failed to set hostname: %s", e)
        return 1

    # Copy SSH keys to root for updater service
    setup_root_ssh_keys()

    # Set password
    if device_password:
        try:
            set_password("counter", device_password)
            log.info("Password set for user 'counter'.")
        except Exception as e:
            log.error("Failed to set password: %s", e)
            return 1
    else:
        log.warning("DEVICE_PASSWORD not set — keeping default password.")

    # Mark as done
    create_marker()

    log.info("First-boot configuration complete for %s.", device_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
