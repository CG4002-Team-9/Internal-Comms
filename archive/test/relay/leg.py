import bluepy.btle as btle
from bluepy.btle import Peripheral, BTLEDisconnectError
from crc import Calculator, Crc8
import time
import struct
import numpy as np
import random

crc8 = Calculator(Crc8.CCITT)
totalBytesRx = 0

MAC_ADDR = "F4:B8:5E:42:61:55"  # leg, 3
SERVICE_UUID = "0000dfb0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000dfb1-0000-1000-8000-00805f9b34fb"

# Packet Types
SYN = 'S'
ACK = 'A'
KICK = 'K'

kickPacket = {
    'seq': 0
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
        self.fragmentedPacketCounter = 0
        self.packetCounter = 0

    def handleNotification(self, cHandle, data):
        global totalBytesRx
        if (self.invalidPacketCounter >= 5):
            self.invalidPacketCounter = 0

        self.packetCounter += 1
        self.isRxPacketReady = False
        self.rxPacketBuffer += data
        totalBytesRx += len(data)

        # check fragmentation + checksum
        if (len(self.rxPacketBuffer) >= 20):
            self.payload, crcReceived = struct.unpack("<19sB", self.rxPacketBuffer[:20])

            if (crc8.verify(self.payload, crcReceived)):
                self.invalidPacketCounter = 0
                self.packetType, self.seqReceived, self.payload = struct.unpack("<cB17s", self.payload)
                self.packetType = chr(self.packetType[0])
                self.isRxPacketReady = True
                print(" Received: ", self.packetType, " Seq: ", self.seqReceived)
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
            self.device.disconnect()
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

    def performHandShake(self):
        print(">> Performing Handshake...")
        print(">> Send SYN to the beetle")
        self.sendSYN(0)
        if (self.device.waitForNotifications(5) and self.device.delegate.isRxPacketReady):
            if (self.device.delegate.packetType ==  ACK):
                self.sendACK(0)
                self.isHandshakeRequire = False
                print(">> Handshake Done.")
                print("_______________________________________________________________ ")
                return True
        print(">> Handshake Failed.")
        return False

    def parseRxPacket(self):
        global totalBytesRx

        packetType = self.device.delegate.packetType
        seqReceived = self.device.delegate.seqReceived
        payload = self.device.delegate.payload
            
        if (packetType == KICK):
            if (random.randint(0,10) != 2):
                self.sendACK(seqReceived)
                if (kickPacket['seq'] != seqReceived):
                    kickPacket['seq']  = seqReceived
                    print(f"    Updated {kickPacket}")
                    print("_______________________________________________________________ ")

                if (kickPacket['seq'] == 1):
                    self.start_time = time.time()
                    totalBytesRx = 0
                    self.device.delegate.fragmentedPacketCounter = 0
                    self.device.delegate.packetCounter = 0
                
                if (kickPacket['seq'] == 100):
                    end_time = time.time()
                    #print("_______________________________________________________________ ")
                    print(end_time - self.start_time, "sec. Total Bytes: ", totalBytesRx)
                    print(f'{(totalBytesRx * 8)/(end_time - self.start_time)} bps')
                    print(f'{self.device.delegate.fragmentedPacketCounter} fragmented packets / {self.device.delegate.packetCounter} packets')
                    f = open("LegStat.txt", "a")
                    f.write(f'{end_time - self.start_time} sec. ')
                    f.write(f'{(totalBytesRx * 8)/(end_time - self.start_time)} bps\t')
                    f.write(f'{self.device.delegate.fragmentedPacketCounter} fragmented packets / {self.device.delegate.packetCounter} packets\n')
                    f.close()
                    print("_______________________________________________________________ ")

        else:
            self.device.delegate.invalidPacketCounter += 1
            print(f" Unpack: {packetType} {payload}")

        return packetType

    def main(self):
        self.device.delegate.isRxPacketReady = False

        # re-handshake if needed
        if ((self.device.delegate.invalidPacketCounter >= 5) or self.isHandshakeRequire):
            self.isHandshakeRequire = not self.performHandShake()
        else: 
            if(self.device.waitForNotifications(1) and self.device.delegate.isRxPacketReady):
                ble1.parseRxPacket()

if __name__ == '__main__':
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
