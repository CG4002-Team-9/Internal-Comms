import bluepy.btle as btle
from bluepy.btle import Peripheral, BTLEDisconnectError
from crc import Calculator, Crc8
import time
import struct
import numpy as np
import random

crc8 = Calculator(Crc8.CCITT)

MAC_ADDR = "F4:B8:5E:42:6D:2D"  #vest, 1
SERVICE_UUID = "0000dfb0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000dfb1-0000-1000-8000-00805f9b34fb"

# Packet Types
SYN = 'S'
ACK = 'A'
UPDATE = 'U'

updatePacket = {
    'seq': 0,
    'audio': 0,
    'reload': 0,
    'bullet': 6
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
        self.packetCounter = 0 # to be used with invalidpacketconter, reset the above value every 5 packets

    def handleNotification(self, cHandle, data):
        if (self.packetCounter == 5):
            self.packetCounter = 0
            self.invalidPacketCounter = 0
        
        self.packetCounter += 1
        self.rxPacketBuffer += data

        # check fragmentation + checksum
        if (len(self.rxPacketBuffer) == 20):
            self.payload, crcReceived = struct.unpack("<19sB", self.rxPacketBuffer)

            if (crc8.verify(self.payload, crcReceived)):
                self.packetType, self.seqReceived, self.payload = struct.unpack("<cB17s", self.payload)
                self.packetType = chr(self.packetType[0])
                self.isRxPacketReady = True
                print(" Received: ", self.packetType, " Seq: ", self.seqReceived)
                
            else:
                self.invalidPacketCounter += 1
                print("Checksum failed.")

            self.rxPacketBuffer = b''
            return

        elif (len(self.rxPacketBuffer) > 20):
            self.rxPacketBuffer = b''   

        else:
            self.invalidPacketCounter += 1
            print(" Fragmented Packet ", len(self.rxPacketBuffer))
            self.isRxPacketReady = False

class BLEConnection:
    def __init__(self, macAddr, serviceUUID, charUUID):
        self.macAddr = macAddr
        self.serviceUUID = serviceUUID
        self.charUUID = charUUID
        self.device = Peripheral()
        self.beetleSerial = None
        self.isAllDataReceived = False
        self.isHandshakeRequire = True

    def establishConnection(self):
        print(">> Searching and Connecting to the Beetle...")
        try:
            self.device.connect(self.macAddr)
        except BTLEDisconnectError:
            self.device.disconnect()
            self.device.connect(self.macAddr)

        self.device.setDelegate(MyDelegate())
        self.beetleSerial = self.device.getServiceByUUID(self.serviceUUID).getCharacteristics(self.charUUID)[0]
        print(">> Connection is established.")
        return True

    def sendSYN(self, seq):
        packet = bytes(SYN, 'utf-8') + bytes([np.uint8(seq)]) + bytes([0] * 17)
        packet = packet + (bytes)([np.uint8(crc8.checksum(packet))])
        self.beetleSerial.write(packet)

    def sendACK(self, seq):
        print("    Send ACK: ", seq)
        packet = bytes(ACK, 'utf-8') + bytes([np.uint8(seq)]) + bytes([0] * 17)
        packet = packet + (bytes)([np.uint8(crc8.checksum(packet))])
        self.beetleSerial.write(packet)
    
    def sendUPDATE(self):
        updatePacket['seq'] += 1
        for i in range(5): # Keep sending until ACK
            packet = bytes(UPDATE, 'utf-8') + bytes([np.uint8(updatePacket['seq']),
                                            np.uint8(updatePacket['audio']),
                                            np.uint8(updatePacket['reload']),
                                            np.uint8(updatePacket['bullet'])]) + bytes([0] * 14)
            packet = packet + (bytes)([np.uint8(crc8.checksum(packet))])
            self.beetleSerial.write(packet)
            print(">> Send UPDATE to the beetle: ", updatePacket['seq'])

            # wait for ACK + check ack seq
            if (self.device.waitForNotifications(5) and self.device.delegate.isRxPacketReady and not self.isHandshakeRequire):
                if (self.device.delegate.packetType ==  ACK and (self.device.delegate.seqReceived == updatePacket['seq'])):
                    print(">> Done update player")
                    return            
            else:
                self.device.delegate.invalidPacketCounter += 1

    def performHandShake(self):
        print(">> Performing Handshake...")
        print(">> Send SYN to the beetle")
        self.sendSYN(0)
        if (self.device.waitForNotifications(5) and self.device.delegate.isRxPacketReady):
            if (self.device.delegate.packetType ==  ACK):
                self.sendACK(0)
                self.isHandshakeRequire = False
                print(">> Handshake Done.")
                return True
        print(">> Handshake Failed.")
        return False

if __name__ == '__main__':
    # main program
    while True:
        ble1 = BLEConnection(MAC_ADDR, SERVICE_UUID, CHAR_UUID)
        ble1.establishConnection()
        ble1.isHandshakeRequire = True
        try:
            while True:
                ble1.isHandshakeRequire = (ble1.device.delegate.invalidPacketCounter == 5) or ble1.isHandshakeRequire
                ble1.device.delegate.isRxPacketReady = False

                if (ble1.isHandshakeRequire):
                    ble1.isHandshakeRequire = not ble1.performHandShake()

                else: # if (no re-handshake needed)    
                    isUpdateNeed = random.randint(0,5)
                    if (isUpdateNeed == 4):
                        updatePacket['audio'] = random.randint(1,4)
                        ble1.sendUPDATE()
                    time.sleep(isUpdateNeed)

        except BTLEDisconnectError:
            pass
