import bluepy.btle as btle
from bluepy.btle import Peripheral, BTLEDisconnectError
from crc import Calculator, Crc8
import time
import struct
import numpy as np
import random

glove_p1 = "F4:B8:5E:42:73:2A"
glove_p2 = "F4:B8:5E:42:67:1B"
vest_p2 = "F4:B8:5E:42:6D:2D"
leg_p2 = "F4:B8:5E:42:61:55"

MAC_ADDR = leg_p2#"F4:B8:5E:42:6D:2D"
SERVICE_UUID = "0000dfb0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000dfb1-0000-1000-8000-00805f9b34fb"
ACK_TIMEOUT = 0.2
CRC8 = Calculator(Crc8.CCITT)

# Packet Types
SYN = 'S'
SYNACK = 'C'
ACK = 'A'
UPDATE = 'U'

updatePacket = {    # ['U', seq, hp, shield, bullets, sound, ..., CRC]
    'seq': 0,
    'hp': 90,
    'shield_hp': 10
}

class MyDelegate(btle.DefaultDelegate):
    def __init__(self):
        btle.DefaultDelegate.__init__(self)
        self.rxPacketBuffer = b''
        self.payload = b''
        self.isRxPacketReady = False
        self.packetType = ''
        self.seqReceived = 0
        self.invalidPacketCounter = 0

    def handleNotification(self, cHandle, data):
        self.isRxPacketReady = False
        self.rxPacketBuffer += data

        if (len(self.rxPacketBuffer) >= 20):
            self.payload, crcReceived = struct.unpack("<19sB", self.rxPacketBuffer[:20])
            if (CRC8.verify(self.payload, crcReceived)):
                self.invalidPacketCounter = 0
                self.packetType, self.seqReceived, self.payload = struct.unpack("<cB17s", self.payload)
                self.packetType = chr(self.packetType[0])
                self.isRxPacketReady = True
                print(f"[BLE]  Received: {self.packetType} Seq: {self.seqReceived}")
                self.rxPacketBuffer = self.rxPacketBuffer[20:]
            else:
                print("[BLE]  Checksum failed.")
                self.invalidPacketCounter += 1
                self.rxPacketBuffer = b''
            return
        else:
            self.invalidPacketCounter += 1
            print("[BLE]  Fragmented Packet ", len(self.rxPacketBuffer))

class BLEConnection:
    def __init__(self, macAddr, serviceUUID, charUUID):
        self.macAddr = macAddr
        self.serviceUUID = serviceUUID
        self.charUUID = charUUID
        self.device = Peripheral()
        self.beetleSerial = None
        self.isAllDataReceived = False
        self.isHandshakeRequire = True
        self.isUpdateNeeded = False

    def establishConnection(self):
        print("[BLE] >> Searching and Connecting to the Beetle...")
        try:
            self.device.connect(self.macAddr)
        except BTLEDisconnectError:
            self.device.disconnect()
            self.device.connect(self.macAddr)

        self.device.setDelegate(MyDelegate())
        self.beetleSerial = self.device.getServiceByUUID(self.serviceUUID).getCharacteristics(self.charUUID)[0]
        print("[BLE] >> Connection is established.")
        return True

    def sendSYN(self, seq):
        print(f"[BLE] >> Send SYN: {seq}")
        packet = bytes(SYN, 'utf-8') + bytes([np.uint8(seq)]) + bytes([0] * 17)
        packet = packet + (bytes)([np.uint8(CRC8.checksum(packet))])
        self.beetleSerial.write(packet)
        
    def sendSYNACK(self, seq):
        print(f"[BLE] >> Send SYNACK: {seq}")
        packet = bytes(SYNACK, 'utf-8') + bytes([np.uint8(seq)]) + bytes([0] * 17)
        packet = packet + (bytes)([np.uint8(CRC8.checksum(packet))])
        self.beetleSerial.write(packet)

    def sendACK(self, seq):
        print(f"[BLE]    Send ACK: {seq}")
        packet = bytes(ACK, 'utf-8') + bytes([np.uint8(seq)]) + bytes([0] * 17)
        packet = packet + (bytes)([np.uint8(CRC8.checksum(packet))])
        self.beetleSerial.write(packet)
    
    def sendUPDATE(self):
        self.isUpdateNeeded = True
        for i in range(5):
            packet = bytes(UPDATE, 'utf-8') + bytes([np.uint8(updatePacket['seq']), np.uint8(updatePacket['hp']), np.uint8(updatePacket['shield_hp'])]) + bytes([0] * 15)
            packet = packet + (bytes)([np.uint8(CRC8.checksum(packet))])
            self.beetleSerial.write(packet)
            print(f"[BLE] >> Send UPDATE to the beetle: {updatePacket['seq']}")

            if (self.device.waitForNotifications(ACK_TIMEOUT) and self.device.delegate.isRxPacketReady and not self.isHandshakeRequire):
                if (self.device.delegate.packetType == SYNACK):
                    self.sendSYNACK(0)
                elif (self.device.delegate.packetType ==  ACK and (self.device.delegate.seqReceived == updatePacket['seq'])):
                    self.isUpdateNeeded = False
                    updatePacket['seq'] += 1
                    if (updatePacket['seq']) > 100:
                        updatePacket['seq'] = 0
                    print("[BLE] >> Done update player")
                    print("[BLE] _______________________________________________________________ ")
                    return
        self.isHandshakeRequire = True

    def performHandShake(self):
        print("[BLE] >> Performing Handshake...")
        self.sendSYN(0)
        if (self.device.waitForNotifications(ACK_TIMEOUT) and self.device.delegate.isRxPacketReady):
            if (self.device.delegate.packetType ==  SYNACK):
                self.sendSYNACK(0)
                self.isHandshakeRequire = False
                if (self.device.delegate.invalidPacketCounter >= 5):
                    self.device.delegate.invalidPacketCounter = 0
                print("[BLE] >> Handshake Done.")
                print("[BLE] _______________________________________________________________ ")
                return True
        print("[BLE] >> Handshake Failed.")
        return False
    
    def main(self):
        import time
        self.device.delegate.isRxPacketReady = False

        if ((self.device.delegate.invalidPacketCounter >= 5) or self.isHandshakeRequire):
            self.isHandshakeRequire = not self.performHandShake()
        else: 
            updatePacket['hp'] = random.randint(1,30)
            if (self.isUpdateNeeded or updatePacket['hp'] >= 18):
                self.sendUPDATE()
            time.sleep(random.randint(1,4))
            

if __name__ == '__main__':
    while True:
        try: 
            ble1 = BLEConnection(MAC_ADDR, SERVICE_UUID, CHAR_UUID)
            ble1.establishConnection()
            ble1.isHandshakeRequire = True
            while True:
                ble1.main()

        except BTLEDisconnectError:
            pass