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
        self.packetCounter = 0
        self.fragmentedPacketCounter = 0

    def handleNotification(self, cHandle, data):
        global totalBytesRx

        if (self.invalidPacketCounter >= 5):
            self.invalidPacketCounter = 0

        self.isRxPacketReady = False
        self.rxPacketBuffer += data
        self.packetCounter += 1
        totalBytesRx += len(data)

        if (len(self.rxPacketBuffer) >= 20):
            self.payload, crcReceived = struct.unpack("<19sB", self.rxPacketBuffer[:20])

            if (crc8.verify(self.payload, crcReceived)):
                self.invalidPacketCounter = 0
                self.packetType, self.seqReceived, self.payload = struct.unpack("<cB17s", self.payload)
                self.packetType = chr(self.packetType[0])
                self.isRxPacketReady = True
                print(f" Received: {self.packetType} Seq: {self.seqReceived}")
                self.rxPacketBuffer = self.rxPacketBuffer[20:]
            else:
                print("Checksum failed.")
                self.invalidPacketCounter += 1
                self.rxPacketBuffer = b''
            return
        else:
            self.invalidPacketCounter += 1
            self.fragmentedPacketCounter += 1
            print(" Fragmented Packet ", len(self.rxPacketBuffer))

class BLEConnection:
    def __init__(self, macAddr, serviceUUID, charUUID):
        self.macAddr = macAddr
        self.serviceUUID = serviceUUID
        self.charUUID = charUUID
        self.device = Peripheral()
        self.beetleSerial = None
        self.isAllDataReceived = False
        self.isHandshakeRequire = True
        self.start_time = time.time()

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
        print(f"    Send ACK: {seq}")
        packet = bytes(ACK, 'utf-8') + bytes([np.uint8(seq)]) + bytes([0] * 17)
        packet = packet + (bytes)([np.uint8(crc8.checksum(packet))])
        self.beetleSerial.write(packet)
    
    def sendUPDATE(self):
        global totalBytesRx

        updatePacket['seq'] += 1
        if (updatePacket['seq'] == 101):
            updatePacket['seq'] = 1
        
        if (updatePacket['seq'] == 1):
            self.device.delegate.packetCounter = 0
            totalBytesRx = 0
            self.device.delegate.fragmentedPacketCounter = 0
            self.device.delegate.packetCounter = 0
            self.start_time = time.time()

        for i in range(5):
            self.device.delegate.packetCounter += 1
            packet = bytes(UPDATE, 'utf-8') + bytes([np.uint8(updatePacket['seq']),
                                            np.uint8(updatePacket['audio']),
                                            np.uint8(updatePacket['reload']),
                                            np.uint8(updatePacket['bullet'])]) + bytes([0] * 14)
            # corrupted packet
            if (random.randint(0,11) == 9):
                packet = packet + (bytes)(np.uint8(updatePacket['seq']))
            else:
                packet = packet + (bytes)([np.uint8(crc8.checksum(packet))])
            
            # drop a packet
            if (random.randint(0,11) == 9):
                print(">> Send UPDATE to the beetle:", updatePacket['seq'])
            else:
                self.beetleSerial.write(packet)
                print(f">> Send UPDATE to the beetle: {updatePacket['seq']}")

            if (self.device.waitForNotifications(0.1) and self.device.delegate.isRxPacketReady and not self.isHandshakeRequire):
                if (self.device.delegate.packetType ==  ACK and (self.device.delegate.seqReceived == updatePacket['seq'])):
                    if (updatePacket['seq'] == 100):
                        end_time = time.time()
                    print(">> Done update player")
                    print("_______________________________________________________________ ")

                    if (updatePacket['seq'] == 100):
                        print("_______________________________________________________________ ")
                        print(end_time - self.start_time, "sec. Total Bytes: ", self.device.delegate.packetCounter * 20)
                        print(f'{(self.device.delegate.packetCounter * 20 * 8)/(end_time - self.start_time)} bps')
                        print(f'{self.device.delegate.fragmentedPacketCounter} fragmented packets / {self.device.delegate.packetCounter} packets')
                        f = open("VestStat.txt", "a")
                        f.write(f'{end_time - self.start_time} sec. ')
                        f.write(f'{(self.device.delegate.packetCounter * 20 * 8)/(end_time - self.start_time)} bps\t')
                        f.write(f'{self.device.delegate.fragmentedPacketCounter} fragmented packets / {self.device.delegate.packetCounter} packets\n')
                        f.close()
                        print("_______________________________________________________________ ")
                    return
        self.isHandshakeRequire = True

    def performHandShake(self):
        print(">> Performing Handshake...")
        print(">> Send SYN to the beetle")
        self.sendSYN(0)
        if (self.device.waitForNotifications(0.1) and self.device.delegate.isRxPacketReady):
            if (self.device.delegate.packetType ==  ACK):
                self.sendACK(0)
                self.isHandshakeRequire = False
                print(">> Handshake Done.")
                print("_______________________________________________________________ ")
                return True
        print(">> Handshake Failed.")
        return False
    
    def main(self):
        global previous_time
        current_time = time.time()
        self.device.delegate.isRxPacketReady = False

        # re-handshake if needed
        if ((self.device.delegate.invalidPacketCounter >= 5) or self.isHandshakeRequire):
            self.isHandshakeRequire = not self.performHandShake()
        else: 
            #isUpdateNeed = updatePacket['audio']
            #if (current_time - previous_time >= isUpdateNeed):
            #if (isUpdateNeed):
            updatePacket['audio'] = random.randint(1,6)
            ble1.sendUPDATE()
            previous_time = current_time

previous_time = 0
totalBytesRx = 0

if __name__ == '__main__':
    # main program
    while True:
        try: 
            ble1 = BLEConnection(MAC_ADDR, SERVICE_UUID, CHAR_UUID)
            ble1.establishConnection()
            ble1.isHandshakeRequire = True
            #try:
            while True:
                ble1.main()

           # except BTLEDisconnectError:
                #pass
        except BTLEDisconnectError:
            pass
