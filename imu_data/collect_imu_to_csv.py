#!/usr/bin/env python

import os
from dotenv import load_dotenv

import bluepy.btle as btle
from bluepy.btle import Peripheral, BTLEDisconnectError
from crc import Calculator, Crc8
import struct
import numpy as np

import csv

# Load environment variables from .env file
load_dotenv()

NAME_OF_ACTION = "logout"

# Broker configurations
BROKER = os.getenv('BROKER')
BROKERUSER = os.getenv('BROKERUSER')
PASSWORD = os.getenv('PASSWORD')
RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', '5672'))
MQTT_PORT = int(os.getenv('MQTT_PORT', '1883'))

# RabbitMQ queues
AI_QUEUE = os.getenv('AI_QUEUE', 'ai_queue')
UPDATE_GE_QUEUE = os.getenv('UPDATE_GE_QUEUE', 'update_ge_queue')

# MQTT topic
MQTT_TOPIC_UPDATE_EVERYONE = os.getenv('MQTT_TOPIC_UPDATE_EVERYONE', 'update_everyone')

# Player ID this server is handling
PLAYER_ID = int(os.getenv('PLAYER_ID', '1'))
print(f'[DEBUG] Player ID: {PLAYER_ID}')

# BLE
MAC_ADDR = os.getenv(f'GLOVE_P{PLAYER_ID}')
print(f'[DEBUG] MAC Address: {MAC_ADDR}')
SERVICE_UUID = "0000dfb0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000dfb1-0000-1000-8000-00805f9b34fb"
IMU_TIMEOUT = 0.5
ACK_TIMEOUT = 0.5
HANDSHAKE_TIMEOUT = 2
CRC8 = Calculator(Crc8.CCITT)
PACKET_SIZE = 15
DATASIZE = 60

# Packet Types
SYN = 'S'
SYNACK = 'C'
ACK = 'A'
SHOOT = 'G'
DATA = 'D'
UPDATE = 'U'

connectionStatus = {
    'isConnected': False,
}

connectionStatusQueue = []

updatePacket = {        # ['U', seq, hp, shield, bullets, sound, ..., CRC]
    'seq': 0,
    'bullets': 6,
    'isReload': False,
}

updatePacketQueue = []

shootPacket = {
    'seq': 0,
    'hit': 0,
}

shootPacketQueue = []

dataPacket = {
    'seq': 0,
    'ax': [0] * DATASIZE,
    'ay': [0] * DATASIZE,
    'az': [0] * DATASIZE,
    'gx': [0] * DATASIZE,
    'gy': [0] * DATASIZE,
    'gz': [0] * DATASIZE,
    'imuCounter': 0,
    'isAllImuReceived': False 
}

dataPacketQueue = []

def saveImuToCSV():
    if (dataPacket['imuCounter'] > 30):
        with open(f"{NAME_OF_ACTION}_{PLAYER_ID}.csv", "a") as f:
            csv_writer = csv.writer(f)
            csv_writer.writerow([str(dataPacket["ax"]),str(dataPacket["ay"]),str(dataPacket["az"]),str(dataPacket["gx"]),str(dataPacket["gy"]),str(dataPacket["gz"])])

    print(f'>> Saved IMU to {NAME_OF_ACTION}.csv')
    dataPacket['ax'] = [0] * DATASIZE
    dataPacket['ay'] = [0] * DATASIZE
    dataPacket['az'] = [0] * DATASIZE
    dataPacket['gx'] = [0] * DATASIZE
    dataPacket['gy'] = [0] * DATASIZE
    dataPacket['gz'] = [0] * DATASIZE
    dataPacket['isAllImuReceived'] = False
    dataPacket['imuCounter'] = 0  

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
        print(packet)
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
    
    def sendUPDATE(self):
        print("[BLE] >> Sending UPDATE...")
        myUpdatePacket = updatePacketQueue.pop(0)
        print(f"[BLE] >> Update Packet: {myUpdatePacket}")
        for i in range(5):
            packet = bytes(UPDATE, 'utf-8') + bytes([np.uint8(updatePacket['seq'] )]) + bytes([0] * 3) + bytes([np.uint8(myUpdatePacket['bullets'])]) + bytes([np.uint8(myUpdatePacket['isReload'])]) + bytes([0] * (PACKET_SIZE - 8))
            packet = packet + (bytes)([np.uint8(CRC8.checksum(packet))])
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
        self.isHandshakeRequire = True

    def performHandShake(self):
        print("[BLE] >> Performing Handshake...")
        self.sendSYN(0)
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

    def appendImuData(self):
        unpackFormat = "<hhhhhh"
        ax, ay, az, gx, gy, gz = struct.unpack(unpackFormat, self.device.delegate.payload)
        print(f"[BLE]    Received {ax}, {ay}, {az}, {gx}, {gy}, {gz}")
        dataPacket['imuCounter'] += 1
        dataPacket['ax'][dataPacket['seq']] = ax
        dataPacket['ay'][dataPacket['seq']] = ay
        dataPacket['az'][dataPacket['seq']] = az
        dataPacket['gx'][dataPacket['seq']] = gx
        dataPacket['gy'][dataPacket['seq']] = gy
        dataPacket['gz'][dataPacket['seq']] = gz


    def parseRxPacket(self):
        packetType = self.device.delegate.packetType
        seqReceived = self.device.delegate.seqReceived
        payload = self.device.delegate.payload

        if (packetType == SHOOT):
            self.sendACK(seqReceived)
            if (shootPacket['seq'] != seqReceived):
                shootPacket['seq']  = seqReceived
                unpackFormat = "<B" + str(PACKET_SIZE - 4) + "s"
                shootPacket['hit'], padding = struct.unpack(unpackFormat, payload)
                shootPacketQueue.append(shootPacket.copy())
        
        elif (packetType == DATA):
            if (dataPacket['isAllImuReceived']):
                return
            dataPacket['seq']  = self.device.delegate.seqReceived
            self.appendImuData()

            # break when received the last packet, or timeout, or received other types of packet that's not DATA
            while (not dataPacket['isAllImuReceived'] and self.device.waitForNotifications(IMU_TIMEOUT)):
                if (not self.device.delegate.isRxPacketReady): # in case of fragmentation
                    continue
                if (self.device.delegate.packetType != DATA):
                    break
                
                dataPacket['seq']  = self.device.delegate.seqReceived
                self.appendImuData()

                if (dataPacket['seq'] >= DATASIZE - 1):
                    dataPacket['isAllImuReceived'] = True

            # all data is ready
            dataPacket['isAllImuReceived'] = True
            print(f"[BLE] >> All IMU data is received.")
            saveImuToCSV()
            
        elif (packetType == SYNACK):
            self.sendSYNACK(0)
        
        else:
            self.device.delegate.invalidPacketCounter += 1
            print(f"[BLE] Unpack: {packetType} {payload}")
        
        self.device.delegate.packetType = ''
        return packetType

    def run(self):
        while True: # BLE loop
            try: 
                self = BLEConnection(MAC_ADDR, SERVICE_UUID, CHAR_UUID)
                self.establishConnection()
                self.isHandshakeRequire = True
                while True:
                    self.device.delegate.isRxPacketReady = False
                    if ((self.device.delegate.invalidPacketCounter >= 5) or self.isHandshakeRequire):
                        self.isHandshakeRequire = not self.performHandShake()
                    else:
                        if (len(updatePacketQueue) > 0):
                            self.sendUPDATE()
                        if (self.device.waitForNotifications(0.1) and self.device.delegate.isRxPacketReady):
                            self.parseRxPacket()
            except BTLEDisconnectError:
                print("[BLE] >> Disconnected.")
                if (connectionStatus['isConnected']):
                    connectionStatus['isConnected'] = False
                    connectionStatusQueue.append(connectionStatus.copy())

# Placeholder functions for Bluetooth communication
def get_imu_data():
    action_occurred = dataPacket['isAllImuReceived'] and dataPacket['imuCounter'] > 30
    
    ax = dataPacket['ax'].copy()
    ay = dataPacket['ay'].copy()
    az = dataPacket['az'].copy()
    gx = dataPacket['gx'].copy()
    gy = dataPacket['gy'].copy()
    gz = dataPacket['gz'].copy()
    # Reset all back to 0
    dataPacket['ax'] = [0] * DATASIZE
    dataPacket['ay'] = [0] * DATASIZE
    dataPacket['az'] = [0] * DATASIZE
    dataPacket['gx'] = [0] * DATASIZE
    dataPacket['gy'] = [0] * DATASIZE
    dataPacket['gz'] = [0] * DATASIZE
    dataPacket['isAllImuReceived'] = False
    dataPacket['imuCounter'] = 0
    
    if action_occurred:
        print(f"[BLE] >> Relay IMU Data to Server")
        return ax, ay, az, gx, gy, gz
    else:
        return None

if __name__ == '__main__':
    ble1 = BLEConnection(MAC_ADDR, SERVICE_UUID, CHAR_UUID)
    try:
        ble1.run()
    except KeyboardInterrupt:
        print('[DEBUG] Glove Beetle Server stopped by user')
    except Exception as e:
        print(f'[ERROR] {e}')
