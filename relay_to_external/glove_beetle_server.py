#!/usr/bin/env python

import asyncio
import json
import os
from dotenv import load_dotenv
import aio_pika
import aiomqtt

from bluepy.btle import BTLEDisconnectError
from crc import Calculator, Crc8
import struct
from myBle import BLEConnection

# Load environment variables from .env file
load_dotenv()

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

connectionStatus = {
    'isConnected': False,
}

updatePacket = {        # ['U', seq, hp, shield, bullets, sound, ..., CRC]
    'seq': 0,
    'bullets': 6,
    'isReload': False,
}

connectionStatusQueue = []
updatePacketQueue = []

shootPacket = {
    'seq': 0,
    'hit': 0,
}

shootPacketQueue = []

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

dataPacketQueue = []

class ExtendedBLEConnection(BLEConnection):
    def appendImuData(self):
        dataPacket['seq']  = self.device.delegate.seqReceived
        unpackFormat = "<hhhhhh"
        ax, ay, az, gx, gy, gz = struct.unpack(unpackFormat, self.device.delegate.payload)
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
                shootPacket['seq']  = seqReceived
                unpackFormat = "<B" + str(PACKET_SIZE - 4) + "s"
                shootPacket['hit'], padding = struct.unpack(unpackFormat, payload)
                shootPacketQueue.append(shootPacket.copy())
        
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
                self = ExtendedBLEConnection(MAC_ADDR, SERVICE_UUID, CHAR_UUID)
                self.establishConnection()
                self.isHandshakeRequire = True
                while True:
                    self.device.delegate.isRxPacketReady = False
                    if ((self.device.delegate.invalidPacketCounter >= 5) or self.isHandshakeRequire):
                        self.isHandshakeRequire = not self.performHandShake(seq=shootPacket['seq'] + 1, connectionStatus=connectionStatus, connectionStatusQueue=connectionStatusQueue)
                    else:
                        if (len(updatePacketQueue) > 0):
                            self.sendUPDATE(updatePacket, myUpdatePacket = updatePacketQueue.pop(0), isGloveUpdate=True)
                        if (self.device.waitForNotifications(0.1) and self.device.delegate.isRxPacketReady):
                            self.parseRxPacket()
                    await asyncio.sleep(0.1)    
            except BTLEDisconnectError:
                print("[BLE] >> Disconnected.")
                if (connectionStatus['isConnected']):
                    connectionStatus['isConnected'] = False
                    connectionStatusQueue.append(connectionStatus.copy())
                await asyncio.sleep(0.1)

# Placeholder functions for Bluetooth communication
def get_imu_data():
    action_occurred = dataPacket['isAllImuReceived']
    if action_occurred:
        dataPacket['isAllImuReceived'] = False
        ax = dataPacket['ax'].copy()
        ay = dataPacket['ay'].copy()
        az = dataPacket['az'].copy()
        gx = dataPacket['gx'].copy()
        gy = dataPacket['gy'].copy()
        gz = dataPacket['gz'].copy()

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
    action_occurred = len(shootPacketQueue) > 0
    if action_occurred:
        myShootPacket = shootPacketQueue.pop(0)
        return {
            'action': True,
            'action_type': 'gun',
            'hit': myShootPacket['hit']
        }
    else:
        return None

class GloveBeetleServer:
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
                    'ax': ax,
                    'ay': ay,
                    'az': az,
                    'gx': gx,
                    'gy': gy,
                    'gz': gz,
                    'player_id': PLAYER_ID
                }
                print(f"[DEBUG] Length of IMU Data: {length}")
                print(f"[DEBUG] IMU Data: {message}")
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

    async def send_connection_status(self):
        while self.should_run:
            toSend = len(connectionStatusQueue) > 0
            if toSend:
                myConnectionStatus = connectionStatusQueue.pop(0)
                message = {
                    "game_state": {
                        f"p{PLAYER_ID}": {
                        "glove_connected": myConnectionStatus['isConnected'],
                        }
                    },
                    "update": True
                    }
                message_body = json.dumps(message).encode('utf-8')
                await self.channel.default_exchange.publish(
                    aio_pika.Message(body=message_body),
                    routing_key=UPDATE_GE_QUEUE,
                )
            await asyncio.sleep(0.1)
    
    async def process_mqtt_messages(self, mqtt_client):
        # Subscribe to MQTT topic
        await mqtt_client.subscribe(MQTT_TOPIC_UPDATE_EVERYONE, qos=2)
        print(f'[DEBUG] Subscribed to MQTT topic {MQTT_TOPIC_UPDATE_EVERYONE}')
        
        async for message in mqtt_client.messages:
            payload = message.payload.decode('utf-8')
            try:
                data = json.loads(payload)
                print(f'[DEBUG] Received MQTT message: {data}')
                game_state = data.get('game_state', {})
                action = data.get('action', None)
                player_id_for_action = data.get('player_id', None)
                player_key = f'p{PLAYER_ID}'
                bullets = game_state.get(player_key).get('bullets', None)
                
                if bullets is not None and bullets != updatePacket['bullets']:
                    updatePacket['bullets'] = bullets
                    if action is not None and player_id_for_action == PLAYER_ID and action == 'reload':
                        updatePacket['isReload'] = True
                        print(f'[DEBUG] Player {PLAYER_ID} is reloading')
                    else:
                        updatePacket['isReload'] = False
                    
                    updatePacketQueue.append(updatePacket.copy())
                
            except json.JSONDecodeError:
                print(f'[ERROR] Invalid JSON payload: {payload}')
            except Exception as e:
                print(f'[ERROR] {e}')
                
    async def run(self):
        await self.setup_rabbitmq()

        mqtt_client = None
        while True:  # Loop for reconnection attempts
            try:
                if mqtt_client:
                    mqtt_client = None
                    
                print('[DEBUG] Attempting MQTT connection...')
                mqtt_client = aiomqtt.Client(
                    hostname=BROKER,
                    port=MQTT_PORT,
                    username=BROKERUSER,
                    password=PASSWORD,
                    identifier=f'glove_beetle_server{PLAYER_ID}',
                    keepalive=60  # Increase the keepalive to ensure regular pings
                )
                
                async with mqtt_client:
                    print(f'[DEBUG] Connected to MQTT broker at {BROKER}:{MQTT_PORT}')
                    
                    await asyncio.gather(
                        self.send_imu_data(),
                        self.send_gun_action(),
                        self.process_mqtt_messages(mqtt_client),
                        self.send_connection_status(),
                    )
            except Exception as e:
                print(f'[ERROR] MQTT connection error: {e}')
                await asyncio.sleep(5)  # Delay before retrying the connection

async def main():
    await asyncio.gather(glove_beetle_server.run(), ble1.run())

if __name__ == '__main__':
    glove_beetle_server = GloveBeetleServer()
    ble1 = ExtendedBLEConnection(MAC_ADDR, SERVICE_UUID, CHAR_UUID)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('[DEBUG] Glove Beetle Server stopped by user')
        glove_beetle_server.should_run = False
    except Exception as e:
        print(f'[ERROR] {e}')
