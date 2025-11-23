# Bluetooth UUIDs for CrowdCount Provisioning

These UUIDs are **fixed** for all CrowdCount devices and should be hardcoded in the iOS app.

## Service UUID

```
e3e64d66-1db1-11ec-9621-0242ac130002
```

## Characteristic UUIDs

### Authentication Characteristic
```
UUID: e3e64d67-1db1-11ec-9621-0242ac130002
Type: Write
Description: Device secret for authentication (from QR code)
```

### WiFi SSID Characteristic
```
UUID: e3e64f08-1db1-11ec-9621-0242ac130002
Type: Write
Description: WiFi network name
```

### WiFi Password Characteristic
```
UUID: e3e6515a-1db1-11ec-9621-0242ac130002
Type: Write
Description: WiFi password
```

### Tailscale Auth Key Characteristic
```
UUID: e3e65276-1db1-11ec-9621-0242ac130002
Type: Write
Description: Tailscale authentication key
```

### Server IP Characteristic
```
UUID: e3e65398-1db1-11ec-9621-0242ac130002
Type: Write
Description: MediaMTX server IP address (Tailscale IP)
```

### Stream Name Characteristic (Optional)
```
UUID: e3e654ba-1db1-11ec-9621-0242ac130002
Type: Write
Description: Optional custom stream name (defaults to device ID)
```

## Provisioning Sequence

1. **Scan QR Code**: Get `device_id` and `device_secret`
2. **Discover Device**: Scan for BLE device named `CrowdCount-{device_id}`
3. **Connect**: Establish BLE connection
4. **Authenticate**: Write `device_secret` to Auth characteristic
5. **Send Credentials**: Write to other characteristics:
   - WiFi SSID
   - WiFi Password
   - Tailscale Auth Key
   - Server IP
   - Stream Name (optional)
6. **Wait**: Device configures network (~30 seconds)
7. **Verify**: Check device appears online in server

## Swift Code Example

```swift
// Service and Characteristic UUIDs
let serviceUUID = CBUUID(string: "e3e64d66-1db1-11ec-9621-0242ac130002")
let authUUID = CBUUID(string: "e3e64d67-1db1-11ec-9621-0242ac130002")
let ssidUUID = CBUUID(string: "e3e64f08-1db1-11ec-9621-0242ac130002")
let passwordUUID = CBUUID(string: "e3e6515a-1db1-11ec-9621-0242ac130002")
let tailscaleKeyUUID = CBUUID(string: "e3e65276-1db1-11ec-9621-0242ac130002")
let serverIPUUID = CBUUID(string: "e3e65398-1db1-11ec-9621-0242ac130002")
let streamNameUUID = CBUUID(string: "e3e654ba-1db1-11ec-9621-0242ac130002")

// Scan for device
centralManager.scanForPeripherals(withServices: [serviceUUID])

// After discovering and connecting, authenticate
let secretData = deviceSecret.data(using: .utf8)!
peripheral.writeValue(secretData, for: authCharacteristic, type: .withResponse)

// Then send credentials
peripheral.writeValue(ssidData, for: ssidCharacteristic, type: .withResponse)
peripheral.writeValue(passwordData, for: passwordCharacteristic, type: .withResponse)
// ... etc
```

## Notes

- All UUIDs are **version 1 UUIDs** (time-based)
- These UUIDs are **NOT** the standard Bluetooth SIG UUIDs
- They are custom UUIDs generated specifically for CrowdCount
- **Do not change** these UUIDs in production - they are fixed across all devices
- The old system used API calls to fetch UUIDs - this new system has them hardcoded for simplicity
