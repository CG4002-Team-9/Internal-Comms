import bluepy.btle as btle

def test_bluepy():
    try:
        # Create a scanner object
        scanner = btle.Scanner()
        
        # Start scanning for devices
        devices = scanner.scan(10.0)  # Scan for 10 seconds
        
        # Print discovered devices
        for device in devices:
            print(f"Device {device.addr} ({device.addrType}), RSSI={device.rssi} dB")
        
        print("Bluepy is working correctly.")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    test_bluepy()