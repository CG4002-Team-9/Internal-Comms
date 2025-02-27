'''
    Received the DATA packet and calculate bps and packet fragmentation
'''

import bluepy.btle as btle
from bluepy.btle import Peripheral, BTLEDisconnectError
from crc import Calculator, Crc8
import time
import struct
import numpy as np
import random
import os

crc8 = Calculator(Crc8.CCITT)
totalBytesRx = 0

MAC_ADDR = "F4:B8:5E:42:6D:2D"#"F4:B8:5E:42:67:1B"  # hand, 2
SERVICE_UUID = "0000dfb0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000dfb1-0000-1000-8000-00805f9b34fb"

# Packet Types
SYN = 'S'
ACK = 'A'
SHOOT = 'G'
DATA = 'D'
UPDATE = 'U'

updatePacket = {
    'seq': 0,
    'audio': 0,
    'reload': 0,
    'bullet': 6
}

shootPacket = {
    'seq': 0,
    'hit': 0,
    'bullet': 6
}

dataPacket = {
    'seq': 0,
    'accX': 0,
    'accY': 0,
    'accZ': 0,
    'gyrX': 0,
    'gyrY': 0,
    'gyrZ': 0 
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
                if (self.packetType == 'D' and (self.seqReceived % 10 == 0)):
                    print(" Received: ", self.packetType, " Seq: ", self.seqReceived)
                self.rxPacketBuffer = self.rxPacketBuffer[20:]           
            else:
                self.invalidPacketCounter += 1
                print("Checksum failed.")
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
            if (random.randint(0,10) == 9):
                print(">> [DROP] Send UPDATE to the beetle: ", updatePacket['seq'])
            else:
                self.beetleSerial.write(packet)
                print(">> Send UPDATE to the beetle: ", updatePacket['seq'])
            # wait for ACK + check ack seq
            if (self.device.waitForNotifications(5) and self.device.delegate.isRxPacketReady and not self.isHandshakeRequire):
                if (self.device.delegate.packetType ==  ACK and (self.device.delegate.seqReceived == updatePacket['seq'])):
                    print(">> Done update player")
                    print("_______________________________________________________________ ")
                    return
                elif (self.device.delegate.packetType ==  DATA): #if other data type will ignore
                    self.parseRxPacket() # update + send to server
        self.isHandshakeRequire = True

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

    def updateData(self):
        dataPacket['seq']  = self.device.delegate.seqReceived
        unpackFormat = "<hhhhhh" + str(5) + "s"
        dataPacket['accX'], dataPacket['accY'], dataPacket['accZ'], dataPacket['gyrX'], dataPacket['gyrY'], dataPacket['gyrZ'], padding = struct.unpack(unpackFormat, self.device.delegate.payload)
        #print( "    Updated ", dataPacket)

    def parseRxPacket(self):
        global totalBytesRx
        packetType = self.device.delegate.packetType
        seqReceived = self.device.delegate.seqReceived
        payload = self.device.delegate.payload

        if (packetType == DATA):
            self.isAllDataReceived = False
            self.updateData()
            self.device.delegate.packetCounter += 1

            if (dataPacket['seq'] == 1):
                self.start_time = time.time()
                totalBytesRx = 0
                self.device.delegate.fragmentedPacketCounter = 0
                self.device.delegate.packetCounter = 0
                
            if (dataPacket['seq'] == 100):
                self.isAllDataReceived = True
                end_time = time.time()
                print("_______________________________________________________________ ")
                print(end_time - self.start_time, "sec. Total Bytes: ", totalBytesRx)
                print(f'{(totalBytesRx * 8)/(end_time - self.start_time)} bps')
                print(f'{self.device.delegate.fragmentedPacketCounter} fragmented packets / {self.device.delegate.packetCounter} packets')
                f = open("stat.txt", "a")
                f.write(f'{(totalBytesRx * 8)/(end_time - self.start_time)} bps\n')
                f.write(f'{self.device.delegate.fragmentedPacketCounter} fragmented packets / {self.device.delegate.packetCounter} packets\n')
                f.close()
                print("_______________________________________________________________ ")
                
            # break when received the last packet, or timeout, or received other types of packet that's not data
            while (not self.isAllDataReceived and self.device.waitForNotifications(5) and self.device.delegate.isRxPacketReady): 
                if (self.device.delegate.packetType != DATA):
                    break
                
                self.updateData()

                if (dataPacket['seq'] == 100):
                    self.isAllDataReceived = True
                    end_time = time.time()
                    print("_______________________________________________________________ ")
                    print(end_time - self.start_time, "sec. Total Bytes: ", totalBytesRx)
                    print(f'{(totalBytesRx * 8)/(end_time - self.start_time)} bps')
                    print(f'{self.device.delegate.fragmentedPacketCounter} fragmented packets / {self.device.delegate.packetCounter} packets')
                    f = open("stat.txt", "a")
                    f.write(f'{(totalBytesRx * 8)/(end_time - self.start_time)} bps\n')
                    f.write(f'{self.device.delegate.fragmentedPacketCounter} fragmented packets / {self.device.delegate.packetCounter} packets\n')
                    f.close()
                    print("_______________________________________________________________ ")

        else:
            self.device.delegate.invalidPacketCounter += 1
            print(" Unpack: ", packetType, payload)
        
        return packetType

if __name__ == '__main__':
    # main program
    while True:
        ble1 = BLEConnection(MAC_ADDR, SERVICE_UUID, CHAR_UUID)
        ble1.establishConnection()
        ble1.isHandshakeRequire = True
        try:
            while True:
                ble1.isHandshakeRequire = ble1.isHandshakeRequire or (ble1.device.delegate.invalidPacketCounter >= 5)
                ble1.device.delegate.isRxPacketReady = False

                if (ble1.isHandshakeRequire):
                    ble1.isHandshakeRequire = not ble1.performHandShake()

                else: # if (no re-handshake needed)    
                    if(ble1.device.waitForNotifications(1) and ble1.device.delegate.isRxPacketReady):
                        ble1.parseRxPacket()

        except BTLEDisconnectError:
            pass
