import bluepy.btle as btle
from bluepy.btle import Peripheral, BTLEDisconnectError
from crc import Calculator, Crc8
import struct
import numpy as np

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

SERVICE_UUID = os.getenv('SERVICE_UUID')
CHAR_UUID = os.getenv('CHAR_UUID')
PACKET_SIZE = int(os.getenv('PACKET_SIZE'))
IMU_TIMEOUT = float(os.getenv('IMU_TIMEOUT'))
ACK_TIMEOUT = float(os.getenv('ACK_TIMEOUT'))
HANDSHAKE_TIMEOUT = float(os.getenv('HANDSHAKE_TIMEOUT'))
CRC8 = Calculator(Crc8.CCITT)

# Packet Types
SYN = os.getenv('SYN')
SYNACK = os.getenv('SYNACK')
ACK = os.getenv('ACK')
SHOOT = os.getenv('SHOOT')
DATA = os.getenv('DATA')
UPDATE = os.getenv('UPDATE')
KICK = os.getenv('KICK')

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

        if (len(self.rxPacketBuffer) >= PACKET_SIZE):
            self.payload, crcReceived = struct.unpack(f"<{PACKET_SIZE - 1}sB", self.rxPacketBuffer[:PACKET_SIZE])
            if (CRC8.verify(self.payload, crcReceived)):
                self.invalidPacketCounter = 0
                self.packetType, self.seqReceived, self.payload = struct.unpack(f"<cB{PACKET_SIZE - 3}s", self.payload)
                self.packetType = chr(self.packetType[0])
                self.isRxPacketReady = True
                print(f"[BLE]  Received: {self.packetType} Seq: {self.seqReceived}")
                self.rxPacketBuffer = self.rxPacketBuffer[PACKET_SIZE:]
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
        self.isHandshakeRequire = True

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
        packet = bytes(SYN, 'utf-8') + bytes([np.uint8(seq)]) + bytes([0] * (PACKET_SIZE - 3))
        packet = packet + (bytes)([np.uint8(CRC8.checksum(packet))])
        self.beetleSerial.write(packet)
        
    def sendSYNACK(self, seq):
        print(f"[BLE] >> Send SYNACK: {seq}")
        packet = bytes(SYNACK, 'utf-8') + bytes([np.uint8(seq)]) + bytes([0] * (PACKET_SIZE - 3))
        packet = packet + (bytes)([np.uint8(CRC8.checksum(packet))])
        self.beetleSerial.write(packet)

    def sendACK(self, seq):
        print(f"[BLE]    Send ACK: {seq}")
        packet = bytes(ACK, 'utf-8') + bytes([np.uint8(seq)]) + bytes([0] * (PACKET_SIZE - 3))
        packet = packet + (bytes)([np.uint8(CRC8.checksum(packet))])
        self.beetleSerial.write(packet)

    def performHandShake(self, seq, connectionStatus, connectionStatusQueue):
        print("[BLE] >> Performing Handshake...")
        self.sendSYN(seq)
        if (self.device.waitForNotifications(HANDSHAKE_TIMEOUT) and self.device.delegate.isRxPacketReady):
            if (self.device.delegate.packetType ==  SYNACK):
                self.sendSYNACK(0)
                self.isHandshakeRequire = False
                if (self.device.delegate.invalidPacketCounter >= 5):
                    self.device.delegate.invalidPacketCounter = 0
                print("[BLE] >> Handshake Done.")
                print("[BLE] _______________________________________________________________ ")
                if (not connectionStatus['isConnected']):
                    connectionStatus['isConnected'] = True
                    connectionStatusQueue.append(connectionStatus.copy())
                return True
        print("[BLE] >> Handshake Failed.")
        return False
    
    def sendUPDATE(self, updatePacket, myUpdatePacket, isVestUpdate=False, isGloveUpdate=False):
        print("[BLE] >> Sending UPDATE...")
        print(f"[BLE] >> Update Packet: {myUpdatePacket}")

        if (isVestUpdate):
            packet = bytes(UPDATE, 'utf-8') + bytes([np.uint8(updatePacket['seq']), np.uint8(myUpdatePacket['hp']), np.uint8(myUpdatePacket['shield_hp']), np.uint8(myUpdatePacket['action_type'])]) + bytes([0] * (PACKET_SIZE - 6))
        elif (isGloveUpdate):
            packet = bytes(UPDATE, 'utf-8') + bytes([np.uint8(updatePacket['seq'])]) + bytes([0] * 3) + bytes([np.uint8(myUpdatePacket['bullets']), np.uint8(myUpdatePacket['isReload'])]) + bytes([0] * (PACKET_SIZE - 8))
        else:
            print("[BLE] >> UPDATE Failed.")
            
        packet = packet + (bytes)([np.uint8(CRC8.checksum(packet))])
        
        for i in range(5):
            self.beetleSerial.write(packet)
            print(f"[BLE] >> Send UPDATE to the beetle: {updatePacket['seq']}")

            if (self.device.waitForNotifications(ACK_TIMEOUT) and self.device.delegate.isRxPacketReady and not self.isHandshakeRequire):
                if (self.device.delegate.packetType == SYNACK):
                    self.sendSYNACK(0)
                elif (self.device.delegate.packetType ==  ACK and (self.device.delegate.seqReceived == updatePacket['seq'])):
                    updatePacket['seq'] += 1
                    updatePacket['seq'] %= 100
                    print("[BLE] >> Done update player")
                    print("[BLE] _______________________________________________________________ ")
                    return
                # if recevied data instead of ACK, collect the data first
                elif (self.device.delegate.packetType == DATA):
                    self.parseRxPacket()
            elif (self.isHandshakeRequire):
                break

        # after 5 attempts of sending update
        print("[BLE] >> Update Failed.")
        self.isHandshakeRequire = True
    
    def parseRxPacket(self):
        pass

    def run(self):
        pass
