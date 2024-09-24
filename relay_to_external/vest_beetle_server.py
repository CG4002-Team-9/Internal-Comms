#!/usr/bin/env python

import asyncio
import json
import os
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
UPDATE_GE_QUEUE = os.getenv('UPDATE_GE_QUEUE', 'update_ge_queue')

# MQTT topic
MQTT_TOPIC_UPDATE_EVERYONE = os.getenv('MQTT_TOPIC_UPDATE_EVERYONE', 'update_everyone')

# Player ID this server is handling
PLAYER_ID = int(os.getenv('PLAYER_ID', '2'))

# BLE
MAC_ADDR = os.getenv(f'VEST_P{PLAYER_ID}')
print(f'[DEBUG] MAC Address: {MAC_ADDR}')
SERVICE_UUID = "0000dfb0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000dfb1-0000-1000-8000-00805f9b34fb"
ACK_TIMEOUT = 0.5
CRC8 = Calculator(Crc8.CCITT)

# Packet Types
SYN = 'S'
SYNACK = 'C'
ACK = 'A'
UPDATE = 'U'

connectionStatus = {
    'isConnected': False,
    'toSendConnectionStatus': False
}

updatePacket = {    # ['U', seq, hp, shield, bullets, sound, ..., CRC]
    'seq': 0,
    'hp': 90,
    'shield_hp': 10,
    'action_type': 0, # 0: no action, 1: damaged, 2: shield deployed
    'isUpdateNeeded': False
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

#    def sendACK(self, seq):
#        print(f"[BLE]    Send ACK: {seq}")
#        packet = bytes(ACK, 'utf-8') + bytes([np.uint8(seq)]) + bytes([0] * 17)
#        packet = packet + (bytes)([np.uint8(CRC8.checksum(packet))])
#        self.beetleSerial.write(packet)
    
    def sendUPDATE(self):
        print("[BLE] >> Sending UPDATE...")
        print(f"[BLE] >> Update Packet: {updatePacket}")
        for i in range(5):
            packet = bytes(UPDATE, 'utf-8') + bytes([np.uint8(updatePacket['seq']), np.uint8(updatePacket['hp']), np.uint8(updatePacket['shield_hp']), np.uint8(updatePacket['action_type'])]) + bytes([0] * 14)
            packet = packet + (bytes)([np.uint8(CRC8.checksum(packet))])
            self.beetleSerial.write(packet)
            print(f"[BLE] >> Send UPDATE to the beetle: {updatePacket['seq']}")

            if (self.device.waitForNotifications(ACK_TIMEOUT) and self.device.delegate.isRxPacketReady and not self.isHandshakeRequire):
                if (self.device.delegate.packetType == SYNACK):
                    self.sendSYNACK(0)
                elif (self.device.delegate.packetType ==  ACK and (self.device.delegate.seqReceived == updatePacket['seq'])):
                    updatePacket['isUpdateNeeded'] = False
                    updatePacket['seq'] += 1
                    updatePacket['seq'] %= 100
                    print("[BLE] >> Done update player")
                    print("[BLE] _______________________________________________________________ ")
                    return
            elif (self.isHandshakeRequire):
                break
        print("[BLE] >> Update Failed.")
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
                connectionStatus['isConnected'] = True
                connectionStatus['toSendConnectionStatus'] = True
                return True
        print("[BLE] >> Handshake Failed.")
        return False
    
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
                            pass
                    await asyncio.sleep(0.1)

            except BTLEDisconnectError:
                print("[BLE] >> Disconnected.")
                connectionStatus['isConnected'] = False
                connectionStatus['toSendConnectionStatus'] = True
                await asyncio.sleep(0.1)

class VestBeetleServer:
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
        await self.channel.declare_queue(UPDATE_GE_QUEUE, durable=True)
        print(f'[DEBUG] Connected to RabbitMQ broker at {BROKER}:{RABBITMQ_PORT}')
    
    async def send_connection_status(self):
        while self.should_run:
            toSend = connectionStatus['toSendConnectionStatus']
            if toSend:
                message = {
                    "game_state": {
                        f"p{PLAYER_ID}": {
                            "vest_connected": connectionStatus['isConnected'],
                        }
                    },
                    "update": True
                }
                message_body = json.dumps(message).encode('utf-8')
                await self.channel.default_exchange.publish(
                    aio_pika.Message(body=message_body),
                    routing_key=UPDATE_GE_QUEUE,
                )
                connectionStatus['toSendConnectionStatus'] = False
                print(f'[DEBUG] Published connection status to {UPDATE_GE_QUEUE}')
            await asyncio.sleep(0.1)
    
    async def process_mqtt_messages(self, mqtt_client):
        # Subscribe to MQTT topic
        await mqtt_client.subscribe(MQTT_TOPIC_UPDATE_EVERYONE, qos=2)
        print(f'[DEBUG] Subscribed to MQTT topic {MQTT_TOPIC_UPDATE_EVERYONE}')
        
        async for message in mqtt_client.messages:
            payload = message.payload.decode('utf-8')
            try:
                data = json.loads(payload)
                # Extract HP and shield info for the specific player
                print(f'[DEBUG] Received MQTT payload: {data}')
                game_state = data.get('game_state', {})
                action = data.get('action', None)
                player_id_for_action = data.get('player_id', None)
                player_key = f'p{PLAYER_ID}'
                
                hp = game_state.get(player_key, {}).get('hp', None)
                shield_hp = game_state.get(player_key, {}).get('shield_hp', None)
                
                updatePacket['hp'] = hp
                updatePacket['shield_hp'] = shield_hp
                gotHit = game_state.get(f'p{player_id_for_action}', {}).get('opponent_hit', False) or game_state.get(f'p{player_id_for_action}', {}).get('opponent_shield_hit', False)
                
                if action is None:
                    updatePacket['action_type'] = 0
                else:
                    if player_id_for_action == PLAYER_ID and action == 'shield': 
                        updatePacket['action_type'] = 2
                    elif player_id_for_action != PLAYER_ID and gotHit:
                        updatePacket['action_type'] = 1
                updatePacket['isUpdateNeeded'] = True
            
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
                    identifier=f'vest_beetle_server{PLAYER_ID}',
                    keepalive=60
                )
                
                async with mqtt_client:
                    print(f'[DEBUG] Connected to MQTT broker at {BROKER}:{MQTT_PORT}')
                    
                    await asyncio.gather(
                        self.process_mqtt_messages(mqtt_client),
                        self.send_connection_status(),
                    )
            except Exception as e:
                print(f'[ERROR] MQTT connection error: {e}')
                await asyncio.sleep(5)  # Delay before retrying the connection
            

async def main():
    await asyncio.gather(ble1.run(), vest_beetle_server.run() )

if __name__ == '__main__':
    vest_beetle_server = VestBeetleServer()
    ble1 = BLEConnection(MAC_ADDR, SERVICE_UUID, CHAR_UUID)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('[DEBUG] Vest Beetle Server stopped by user')
        vest_beetle_server.should_run = False
    except Exception as e:
        print(f'[ERROR] {e}')
