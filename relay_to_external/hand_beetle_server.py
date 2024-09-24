#!/usr/bin/env python

import asyncio
import json
import os
import time
from dotenv import load_dotenv
import aio_pika
import aiomqtt

import bluepy.btle as btle
from bluepy.btle import Peripheral, BTLEDisconnectError
from crc import Calculator, Crc8
import time
import struct
import numpy as np

# Load environment variables from .env file
load_dotenv()

# Broker configurations
BROKER = os.getenv('BROKER')
BROKERUSER = os.getenv('BROKERUSER')
PASSWORD = os.getenv('PASSWORD')
RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', '5672'))
MQTT_PORT = int(os.getenv('MQTT_PORT', '1883'))

# RabbitMQ queues
AI_QUEUE = 'ai_queue'
UPDATE_GE_QUEUE = 'update_ge_queue'

# MQTT topic
MQTT_TOPIC_UPDATE_EVERYONE = 'update_everyone'

# Player ID this server is handling
PLAYER_ID = int(os.getenv('PLAYER_ID', '2'))

# BLE
glove_p1 = "F4:B8:5E:42:73:2A"
glove_p2 = "F4:B8:5E:42:67:1B"
vest_p2 = "F4:B8:5E:42:6D:2D"
leg_p2 = "F4:B8:5E:42:61:55"

MAC_ADDR = leg_p2
SERVICE_UUID = "0000dfb0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000dfb1-0000-1000-8000-00805f9b34fb"
IMU_TIMEOUT = 0.5
ACK_TIMEOUT = 1
CRC8 = Calculator(Crc8.CCITT)

# Packet Types
SYN = 'S'
SYNACK = 'C'
ACK = 'A'
SHOOT = 'G'
DATA = 'D'
UPDATE = 'U'

updatePacket = {        # ['U', seq, hp, shield, bullets, sound, ..., CRC]
    'seq': 0,
    'bullets': 6,
    'isUpdateNeeded': False
}

shootPacket = {
    'seq': 0,
    'hit': 0,
    'bullets': 6,
    'isGunUpdate': False
}

dataPacket = {
    'seq': 0,
    'ax': [],
    'ay': [],
    'az': [],
    'gx': [],
    'gy': [],
    'gz': [],
    'isAllImuReceived': False 
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
        self.isHandshakeRequire = True
        self.imuSeq = 0
        #self.isUpdateNeeded = False
        #self.isAllImuReceived = False
        #self.isGunUpdate = False

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
        print(packet)
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
        # self.isUpdateNeeded = True
        for i in range(5):
            packet = bytes(UPDATE, 'utf-8') + bytes([np.uint8(updatePacket['seq'] )]) + bytes([0] * 2) + bytes([np.uint8(updatePacket['bullets'])]) + bytes([0] * 14)
            packet = packet + (bytes)([np.uint8(CRC8.checksum(packet))])
            self.beetleSerial.write(packet)
            print(f"[BLE] >> Send UPDATE to the beetle: {updatePacket['seq']}")

            if (self.device.waitForNotifications(ACK_TIMEOUT) and self.device.delegate.isRxPacketReady and not self.isHandshakeRequire):
                if (self.device.delegate.packetType == SYNACK):
                    self.sendSYNACK(0)
                elif (self.device.delegate.packetType ==  ACK and (self.device.delegate.seqReceived == updatePacket['seq'])):
                    updatePacket['isUpdateNeeded'] = False
                    updatePacket['seq'] += 1
                    if (updatePacket['seq']) > 100:
                        updatePacket['seq'] = 0
                    print("[BLE] >> Done update player")
                    print("[BLE] _______________________________________________________________ ")
                    return 
                # if recevied data instead of ACK, collect the data first
                elif (self.device.delegate.packetType ==  DATA):
                    self.parseRxPacket()

            elif (self.isHandshakeRequire):
                break
        # after 5 attempts of sending update
        self.isHandshakeRequire = True

    def performHandShake(self):
        print("[BLE] >> Performing Handshake...")
        self.sendSYN(shootPacket['seq'] + 1)
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

    def appendImuData(self):
        dataPacket['seq']  = self.device.delegate.seqReceived
        unpackFormat = "<hhhhhh" + str(5) + "s"
        ax, ay, az, gx, gy, gz, padding = struct.unpack(unpackFormat, self.device.delegate.payload)
        while (dataPacket['seq'] >= self.imuSeq):
            dataPacket['ax'].append(ax)
            dataPacket['ay'].append(ay)
            dataPacket['az'].append(az)
            dataPacket['gx'].append(gx)
            dataPacket['gy'].append(gy)
            dataPacket['gz'].append(gz)
            self.imuSeq += 1
        #print(f"[BLE]    Updated {ax}, {ay}, {az}, {gx}, {gy}, {gz}}")

    def parseRxPacket(self):
        packetType = self.device.delegate.packetType
        seqReceived = self.device.delegate.seqReceived
        payload = self.device.delegate.payload

        if (packetType == SHOOT):
            self.sendACK(seqReceived)
            if (shootPacket['seq'] != seqReceived):
                shootPacket['isGunUpdate']= True
                shootPacket['seq']  = seqReceived
                unpackFormat = "<BB" + str(15) + "s"
                shootPacket['hit'], shootPacket['bullets'], padding = struct.unpack(unpackFormat, payload)
        
        elif (packetType == DATA):
            self.appendImuData()
            dataPacket['isAllImuReceived'] = False

            # break when received the last packet, or timeout, or received other types of packet that's not DATA
            while (not dataPacket['isAllImuReceived'] and self.device.waitForNotifications(IMU_TIMEOUT)):
                if (not self.device.delegate.isRxPacketReady): # in case of fragmentation
                    continue
                if (self.device.delegate.packetType != DATA):
                    break
                
                self.appendImuData()

                if (dataPacket['seq'] == 59):
                    dataPacket['isAllImuReceived'] = True

            # if wait the next data until timeout, append the data
            if (dataPacket['seq'] != 59):
                dataPacket['seq'] = 59
                self.appendImuData()

            # all data is ready
            dataPacket['isAllImuReceived'] = True
            self.imuSeq = 0
            print(f"[BLE] >> All IMU data is received.")
            
        elif (packetType == SYNACK):
            self.sendSYNACK(0)
        
        else:
            self.device.delegate.invalidPacketCounter += 1
            print(f"[BLE] Unpack: {packetType} {payload}")
        
        self.device.delegate.packetType = ''
        return packetType

    async def run(self):
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
                        if (updatePacket['isUpdateNeeded']):
                            self.sendUPDATE()
                        if (self.device.waitForNotifications(0.1) and self.device.delegate.isRxPacketReady):
                            self.parseRxPacket()
                        await asyncio.sleep(0.1)
                        # updatePacket['isUpdateNeeded'] = True
            except BTLEDisconnectError:
                pass

# Placeholder functions for Bluetooth communication
def get_imu_data():
    action_occurred = dataPacket['isAllImuReceived']
    if action_occurred:
        #print(dataPacket)
        dataPacket['isAllImuReceived'] = False
        ax = dataPacket['ax']
        ay = dataPacket['ay']
        az = dataPacket['az']
        gx = dataPacket['gx']
        gy = dataPacket['gy']
        gz = dataPacket['gz']

        dataPacket["ax"].clear()
        dataPacket["ay"].clear()
        dataPacket["az"].clear()
        dataPacket["gx"].clear()
        dataPacket["gy"].clear()
        dataPacket["gz"].clear()
        print(f"[BLE] >> Relay IMU Data to Server")
        return ax, ay, az, gx, gy, gz
    else:
        return None

def get_gun_action():
    action_occurred = shootPacket['isGunUpdate']
    if action_occurred:
        shootPacket['isGunUpdate'] = False
        return {
            'action': True,
            'action_type': 'gun',
            'hit': shootPacket['hit']
        }
    else:
        return None

class HandBeetleServer:
    def __init__(self):
        self.rabbitmq_connection = None
        self.channel = None
        self.should_run = True

    async def setup_rabbitmq(self):
        print('[DEBUG] Connecting to RabbitMQ broker...')
        self.rabbitmq_connection = await aio_pika.connect_robust(
            host=BROKER,
            port=RABBITMQ_PORT,
            login=BROKERUSER,
            password=PASSWORD,
        )
        self.channel = await self.rabbitmq_connection.channel()
        await self.channel.declare_queue(AI_QUEUE, durable=True)
        await self.channel.declare_queue(UPDATE_GE_QUEUE, durable=True)
        print(f'[DEBUG] Connected to RabbitMQ broker at {BROKER}:{RABBITMQ_PORT}')

    async def send_imu_data(self):
        while self.should_run:
            imu_data = get_imu_data()
            if imu_data is not None:
                ax, ay, az, gx, gy, gz = imu_data
                length = len(ax)
                message = {
                    'length': length,
                    'ax': ax,
                    'ay': ay,
                    'az': az,
                    'gx': gx,
                    'gy': gy,
                    'gz': gz,
                    'player_id': PLAYER_ID
                }
                message_body = json.dumps(message).encode('utf-8')
                await self.channel.default_exchange.publish(
                    aio_pika.Message(body=message_body),
                    routing_key=AI_QUEUE,
                )
                print(f'[DEBUG] Published IMU data to {AI_QUEUE}')
            await asyncio.sleep(0.1)

    async def send_gun_action(self):
        while self.should_run:
            action_data = get_gun_action()
            
            if action_data:
                action_data['player_id'] = PLAYER_ID
                message_body = json.dumps(action_data).encode('utf-8')
                await self.channel.default_exchange.publish(
                    aio_pika.Message(body=message_body),
                    routing_key=UPDATE_GE_QUEUE,
                )
                print(f'[DEBUG] Published gun action to {UPDATE_GE_QUEUE}: {action_data}')
            await asyncio.sleep(0.1)

    async def process_mqtt_messages(self, mqtt_client):
        # Subscribe to MQTT topic
        await mqtt_client.subscribe(MQTT_TOPIC_UPDATE_EVERYONE, qos=2)
        print(f'[DEBUG] Subscribed to MQTT topic {MQTT_TOPIC_UPDATE_EVERYONE}')
        
        async for message in mqtt_client.messages:
            payload = message.payload.decode('utf-8')
            try:
                data = json.loads(payload)
                if 'game_state' in data:
                    player_key = f'p{PLAYER_ID}'
                    if player_key in data['game_state']:
                        bullets = data['game_state'][player_key].get('bullets', None)
                        if bullets is not None:
                            print(f'[DEBUG] Updating bullets on wearable: {bullets}')
                            updatePacket['bullet'] = bullets
                            updatePacket['isUpdateNeeded'] = True
                            # ble1.sendUPDATE()
            except json.JSONDecodeError:
                print(f'[ERROR] Invalid JSON payload: {payload}')
                
    async def run(self):
        await self.setup_rabbitmq()
        async with aiomqtt.Client(
            hostname=BROKER,
            port=MQTT_PORT,
            username=BROKERUSER,
            password=PASSWORD,
            identifier=f'hand_beetle_server{PLAYER_ID}',
        ) as mqtt_client:
            await asyncio.gather(
                self.send_imu_data(),
                self.send_gun_action(),
                self.process_mqtt_messages(mqtt_client)
            )

async def main():
    await asyncio.gather(hand_beetle_server.run(), ble1.run())

if __name__ == '__main__':
    hand_beetle_server = HandBeetleServer()
    #mac_addr = f'MAC_ADDR_{PLAYER_ID}'
    ble1 = BLEConnection(MAC_ADDR, SERVICE_UUID, CHAR_UUID)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('[DEBUG] Hand Beetle Server stopped by user')
        hand_beetle_server.should_run = False
    except Exception as e:
        print(f'[ERROR] {e}')
