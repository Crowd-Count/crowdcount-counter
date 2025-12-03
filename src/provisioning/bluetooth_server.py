#!/usr/bin/env python3
"""
Bluetooth Provisioning Server
BLE GATT server for receiving WiFi and Tailscale credentials
"""

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import threading
import time

# GATT UUIDs - these are fixed for all CrowdCount devices
SERVICE_UUID = 'e3e64d66-1db1-11ec-9621-0242ac130002'
AUTH_UUID = 'e3e64d67-1db1-11ec-9621-0242ac130002'
SSID_UUID = 'e3e64f08-1db1-11ec-9621-0242ac130002'
PASSWORD_UUID = 'e3e6515a-1db1-11ec-9621-0242ac130002'
TAILSCALE_KEY_UUID = 'e3e65276-1db1-11ec-9621-0242ac130002'
SERVER_IP_UUID = 'e3e65398-1db1-11ec-9621-0242ac130002'
STREAM_NAME_UUID = 'e3e654ba-1db1-11ec-9621-0242ac130002'

# BlueZ D-Bus constants
BLUEZ_SERVICE = 'org.bluez'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
GATT_SERVICE_IFACE = 'org.bluez.GattService1'
GATT_CHARACTERISTIC_IFACE = 'org.bluez.GattCharacteristic1'
LE_ADVERTISEMENT_IFACE = 'org.bluez.LEAdvertisement1'


class ProvisioningData:
    """Stores provisioning data received via BLE"""

    def __init__(self, device_identity, on_complete_callback):
        self.device_identity = device_identity
        self.on_complete = on_complete_callback

        # Authentication
        self.authenticated = False

        # WiFi credentials
        self.wifi_ssid = None
        self.wifi_password = None

        # Tailscale credentials
        self.tailscale_auth_key = None

        # Server configuration
        self.server_ip = None
        self.stream_name = None

    def set_auth_secret(self, secret):
        """Validate authentication secret"""
        if self.device_identity.validate_secret(secret):
            self.authenticated = True
            print("✓ Device authenticated via BLE")
            return True
        else:
            print("✗ Authentication failed - invalid secret")
            return False

    def set_wifi_ssid(self, ssid):
        """Set WiFi SSID"""
        if not self.authenticated:
            print("✗ Not authenticated - ignoring SSID")
            return
        self.wifi_ssid = ssid
        print(f"  Received WiFi SSID: {ssid}")
        self._check_complete()

    def set_wifi_password(self, password):
        """Set WiFi password"""
        if not self.authenticated:
            print("✗ Not authenticated - ignoring password")
            return
        self.wifi_password = password
        print(f"  Received WiFi password: {'*' * len(password)}")
        self._check_complete()

    def set_tailscale_key(self, key):
        """Set Tailscale auth key"""
        if not self.authenticated:
            print("✗ Not authenticated - ignoring Tailscale key")
            return
        self.tailscale_auth_key = key
        print(f"  Received Tailscale auth key")
        self._check_complete()

    def set_server_ip(self, ip):
        """Set server IP"""
        if not self.authenticated:
            print("✗ Not authenticated - ignoring server IP")
            return
        self.server_ip = ip
        print(f"  Received server IP: {ip}")
        self._check_complete()

    def set_stream_name(self, name):
        """Set stream name"""
        if not self.authenticated:
            print("✗ Not authenticated - ignoring stream name")
            return
        self.stream_name = name
        print(f"  Received stream name: {name}")
        self._check_complete()

    def _check_complete(self):
        """Check if all required data has been received"""
        if (self.authenticated and
            self.wifi_ssid and
            self.wifi_password and
            self.tailscale_auth_key and
            self.server_ip):

            print("✓ All provisioning data received!")
            # Trigger provisioning in a separate thread
            threading.Thread(target=self.on_complete, args=(self,), daemon=True).start()


class Characteristic(dbus.service.Object):
    """Base GATT Characteristic class"""

    def __init__(self, bus, index, uuid, flags, service):
        self.path = service.path + '/char' + str(index)
        self.bus = bus
        self.uuid = uuid
        self.flags = flags
        self.service = service
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_CHARACTERISTIC_IFACE: {
                'Service': dbus.ObjectPath(self.service.path),
                'UUID': dbus.String(self.uuid),
                'Flags': dbus.Array(self.flags, signature='s'),
                'Descriptors': dbus.Array([], signature='o')
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method('org.freedesktop.DBus.Properties',
                        in_signature='s',
                        out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != GATT_CHARACTERISTIC_IFACE:
            raise dbus.exceptions.DBusException(
                'org.freedesktop.DBus.Error.InvalidArgs',
                'Unknown interface')

        return self.get_properties()[GATT_CHARACTERISTIC_IFACE]

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE,
                        in_signature='a{sv}',
                        out_signature='ay')
    def ReadValue(self, options):
        print(f"ReadValue called on {self.uuid}")
        return []

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature='aya{sv}')
    def WriteValue(self, value, options):
        print(f"WriteValue called on {self.uuid}")


class AuthCharacteristic(Characteristic):
    """Authentication characteristic - client writes device secret"""

    def __init__(self, bus, index, service, provisioning_data):
        Characteristic.__init__(
            self, bus, index, AUTH_UUID, ['write'], service)
        self.provisioning_data = provisioning_data

    def WriteValue(self, value, options):
        secret = ''.join([chr(byte) for byte in value])
        self.provisioning_data.set_auth_secret(secret)


class WifiSSIDCharacteristic(Characteristic):
    """WiFi SSID characteristic"""

    def __init__(self, bus, index, service, provisioning_data):
        Characteristic.__init__(
            self, bus, index, SSID_UUID, ['write'], service)
        self.provisioning_data = provisioning_data

    def WriteValue(self, value, options):
        ssid = ''.join([chr(byte) for byte in value])
        self.provisioning_data.set_wifi_ssid(ssid)


class WifiPasswordCharacteristic(Characteristic):
    """WiFi password characteristic"""

    def __init__(self, bus, index, service, provisioning_data):
        Characteristic.__init__(
            self, bus, index, PASSWORD_UUID, ['write'], service)
        self.provisioning_data = provisioning_data

    def WriteValue(self, value, options):
        password = ''.join([chr(byte) for byte in value])
        self.provisioning_data.set_wifi_password(password)


class TailscaleKeyCharacteristic(Characteristic):
    """Tailscale auth key characteristic"""

    def __init__(self, bus, index, service, provisioning_data):
        Characteristic.__init__(
            self, bus, index, TAILSCALE_KEY_UUID, ['write'], service)
        self.provisioning_data = provisioning_data

    def WriteValue(self, value, options):
        key = ''.join([chr(byte) for byte in value])
        self.provisioning_data.set_tailscale_key(key)


class ServerIPCharacteristic(Characteristic):
    """Server IP characteristic"""

    def __init__(self, bus, index, service, provisioning_data):
        Characteristic.__init__(
            self, bus, index, SERVER_IP_UUID, ['write'], service)
        self.provisioning_data = provisioning_data

    def WriteValue(self, value, options):
        ip = ''.join([chr(byte) for byte in value])
        self.provisioning_data.set_server_ip(ip)


class StreamNameCharacteristic(Characteristic):
    """Stream name characteristic"""

    def __init__(self, bus, index, service, provisioning_data):
        Characteristic.__init__(
            self, bus, index, STREAM_NAME_UUID, ['write'], service)
        self.provisioning_data = provisioning_data

    def WriteValue(self, value, options):
        name = ''.join([chr(byte) for byte in value])
        self.provisioning_data.set_stream_name(name)


class ProvisioningService(dbus.service.Object):
    """Main GATT service for provisioning"""

    PATH_BASE = '/org/bluez/crowdcount/service'

    def __init__(self, bus, index, provisioning_data):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.uuid = SERVICE_UUID
        self.primary = True
        self.characteristics = []
        dbus.service.Object.__init__(self, bus, self.path)

        # Add characteristics
        self.add_characteristic(AuthCharacteristic(bus, 0, self, provisioning_data))
        self.add_characteristic(WifiSSIDCharacteristic(bus, 1, self, provisioning_data))
        self.add_characteristic(WifiPasswordCharacteristic(bus, 2, self, provisioning_data))
        self.add_characteristic(TailscaleKeyCharacteristic(bus, 3, self, provisioning_data))
        self.add_characteristic(ServerIPCharacteristic(bus, 4, self, provisioning_data))
        self.add_characteristic(StreamNameCharacteristic(bus, 5, self, provisioning_data))

    def add_characteristic(self, characteristic):
        self.characteristics.append(characteristic)

    def get_properties(self):
        return {
            GATT_SERVICE_IFACE: {
                'UUID': dbus.String(self.uuid),
                'Primary': dbus.Boolean(self.primary),
                'Characteristics': dbus.Array(
                    [dbus.ObjectPath(char.path) for char in self.characteristics],
                    signature='o')
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method('org.freedesktop.DBus.Properties',
                        in_signature='s',
                        out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != GATT_SERVICE_IFACE:
            raise dbus.exceptions.DBusException(
                'org.freedesktop.DBus.Error.InvalidArgs',
                'Unknown interface')

        return self.get_properties()[GATT_SERVICE_IFACE]


class Application(dbus.service.Object):
    """GATT Application"""

    def __init__(self, bus, provisioning_data):
        self.path = '/'
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)

        # Add provisioning service
        self.add_service(ProvisioningService(bus, 0, provisioning_data))

    def add_service(self, service):
        self.services.append(service)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method('org.freedesktop.DBus.ObjectManager',
                        out_signature='a{oa{sa{sv}}}')
    def GetManagedObjects(self):
        response = {}

        for service in self.services:
            response[service.get_path()] = service.get_properties()
            for char in service.characteristics:
                response[char.get_path()] = char.get_properties()

        return response


class Advertisement(dbus.service.Object):
    """BLE Advertisement"""

    PATH_BASE = '/org/bluez/crowdcount/advertisement'

    def __init__(self, bus, index, device_name):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.ad_type = 'peripheral'
        self.service_uuids = [SERVICE_UUID]
        self.local_name = device_name
        self.include_tx_power = True
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        properties = dict()
        properties['Type'] = self.ad_type
        if self.service_uuids is not None:
            properties['ServiceUUIDs'] = dbus.Array(self.service_uuids, signature='s')
        if self.local_name is not None:
            properties['LocalName'] = dbus.String(self.local_name)
        if self.include_tx_power:
            properties['Includes'] = dbus.Array(["tx-power"], signature='s')
        return {LE_ADVERTISEMENT_IFACE: properties}

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(LE_ADVERTISEMENT_IFACE, in_signature='', out_signature='')
    def Release(self):
        print("Advertisement released")

    @dbus.service.method('org.freedesktop.DBus.Properties',
                        in_signature='s',
                        out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != LE_ADVERTISEMENT_IFACE:
            raise dbus.exceptions.DBusException(
                'org.freedesktop.DBus.Error.InvalidArgs',
                'Unknown interface')
        return self.get_properties()[LE_ADVERTISEMENT_IFACE]


class BluetoothProvisioningServer:
    """Main Bluetooth provisioning server"""

    def __init__(self, device_identity, on_complete_callback):
        self.device_identity = device_identity
        self.on_complete = on_complete_callback
        self.mainloop = None

        # Initialize D-Bus
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()

        # Create provisioning data container
        self.provisioning_data = ProvisioningData(device_identity, on_complete_callback)

    def find_adapter(self):
        """Find Bluetooth adapter"""
        remote_om = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE, '/'),
                                   'org.freedesktop.DBus.ObjectManager')
        objects = remote_om.GetManagedObjects()

        for o, props in objects.items():
            if GATT_MANAGER_IFACE in props.keys():
                return o

        return None

    def start(self):
        """Start the Bluetooth provisioning server"""
        print(f"🔵 Starting Bluetooth provisioning server")
        print(f"   Device name: {self.device_identity.get_bluetooth_name()}")

        # Find adapter
        adapter_path = self.find_adapter()
        if not adapter_path:
            print("✗ No Bluetooth adapter found")
            return False

        # Get GATT and advertising managers
        adapter = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE, adapter_path),
                                'org.freedesktop.DBus.Properties')

        # Try to power on adapter (ignore if already powered)
        try:
            adapter.Set('org.bluez.Adapter1', 'Powered', dbus.Boolean(True))
        except dbus.exceptions.DBusException as e:
            print(f"⚠ Bluetooth adapter power warning: {e}")
            print("   Continuing anyway...")

        gatt_manager = dbus.Interface(
            self.bus.get_object(BLUEZ_SERVICE, adapter_path),
            GATT_MANAGER_IFACE)

        ad_manager = dbus.Interface(
            self.bus.get_object(BLUEZ_SERVICE, adapter_path),
            LE_ADVERTISING_MANAGER_IFACE)

        # Register GATT application
        app = Application(self.bus, self.provisioning_data)
        gatt_manager.RegisterApplication(app.get_path(), {},
                                        reply_handler=self._register_app_cb,
                                        error_handler=self._register_app_error_cb)

        # Register advertisement
        adv = Advertisement(self.bus, 0, self.device_identity.get_bluetooth_name())
        ad_manager.RegisterAdvertisement(adv.get_path(), {},
                                        reply_handler=self._register_ad_cb,
                                        error_handler=self._register_ad_error_cb)

        print("✓ Bluetooth server started")
        print("   Waiting for mobile app to connect...")

        # Run main loop
        self.mainloop = GLib.MainLoop()
        try:
            self.mainloop.run()
        except KeyboardInterrupt:
            print("\n⚠ Provisioning cancelled by user")

        return True

    def stop(self):
        """Stop the Bluetooth server"""
        if self.mainloop:
            print("🔵 Stopping Bluetooth server")
            self.mainloop.quit()

    def _register_app_cb(self):
        print("✓ GATT application registered")

    def _register_app_error_cb(self, error):
        print(f"✗ Failed to register GATT application: {error}")
        if self.mainloop:
            self.mainloop.quit()

    def _register_ad_cb(self):
        print("✓ Advertisement registered")

    def _register_ad_error_cb(self, error):
        print(f"⚠ Failed to register advertisement: {error}")
        print("  GATT server is still running - device may be discoverable without advertisement")
        # Don't quit - GATT server is still functional


if __name__ == "__main__":
    # Test the Bluetooth server
    from device_identity import DeviceIdentity

    def test_callback(data):
        print("\n📦 Provisioning complete!")
        print(f"   WiFi: {data.wifi_ssid}")
        print(f"   Server: {data.server_ip}")
        time.sleep(2)
        server.stop()

    identity = DeviceIdentity()
    server = BluetoothProvisioningServer(identity, test_callback)
    server.start()
