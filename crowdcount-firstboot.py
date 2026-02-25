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


def set_tailscale_hostname(hostname):
    log.info("Setting Tailscale hostname to: %s", hostname)
    try:
        subprocess.run(["tailscale", "set", "--hostname", hostname], check=True)
    except FileNotFoundError:
        log.warning("tailscale command not found — skipping Tailscale hostname")
    except Exception as e:
        log.warning("Could not set Tailscale hostname: %s", e)


def set_password(username, password):
    log.info("Setting password for user: %s", username)
    proc = subprocess.run(
        ["chpasswd"],
        input=f"{username}:{password}\n",
        text=True,
        check=True,
    )


def create_marker():
    try:
        with open(MARKER_FILE, "w") as f:
            f.write(f"First boot completed\n")
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

    # Set hostname (OS + Tailscale)
    try:
        set_hostname(device_id)
        log.info("Hostname set to: %s", device_id)
    except Exception as e:
        log.error("Failed to set hostname: %s", e)
        return 1

    set_tailscale_hostname(device_id)

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
