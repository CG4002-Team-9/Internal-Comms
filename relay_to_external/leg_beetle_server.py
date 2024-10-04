#!/usr/bin/env python

import asyncio
import json
import os
from dotenv import load_dotenv
import aio_pika

from bluepy.btle import BTLEDisconnectError
from crc import Calculator, Crc8
from myBle import BLEConnection

# Load environment variables from .env file
load_dotenv()

# Broker configurations
BROKER = os.getenv('BROKER')
BROKERUSER = os.getenv('BROKERUSER')
PASSWORD = os.getenv('PASSWORD')
RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', '5672'))

# RabbitMQ queue
UPDATE_GE_QUEUE = os.getenv('UPDATE_GE_QUEUE', 'update_ge_queue')

# Player ID this server is handling
PLAYER_ID = int(os.getenv('PLAYER_ID', '1'))
print(f'[DEBUG] Player ID: {PLAYER_ID}')

# BLE
MAC_ADDR = os.getenv(f'LEG_P{PLAYER_ID}')
SERVICE_UUID = os.getenv('SERVICE_UUID')
CHAR_UUID = os.getenv('CHAR_UUID')
PACKET_SIZE = int(os.getenv('PACKET_SIZE'))
ACK_TIMEOUT = float(os.getenv('ACK_TIMEOUT'))
HANDSHAKE_TIMEOUT = float(os.getenv('HANDSHAKE_TIMEOUT'))
CRC8 = Calculator(Crc8.CCITT)

# Packet Types
SYN = os.getenv('SYN')
SYNACK = os.getenv('SYNACK')
ACK = os.getenv('ACK')
KICK = os.getenv('KICK')

connectionStatus = {
    'isConnected': False,
}
connectionStatusQueue = []

kickPacket = {
    'seq': 0,
    'isKickUpdate': False
}
kickPacketQueue = []

class ExtendedBLEConnection(BLEConnection):
    def parseRxPacket(self):
        packetType = self.device.delegate.packetType
        seqReceived = self.device.delegate.seqReceived
        payload = self.device.delegate.payload
            
        if (packetType == KICK):
            self.sendACK(seqReceived)
            if (kickPacket['seq'] != seqReceived):
                kickPacket['seq']  = seqReceived
                print(f"[BLE]     Updated {kickPacket}")
                kickPacketQueue.append(kickPacket.copy())
                print("[BLE] _______________________________________________________________ ")
        
        elif (packetType == SYNACK):
            self.sendSYNACK(0)
        
        else:
            self.device.delegate.invalidPacketCounter += 1
            print(f"[BLE] Unpack: {packetType} {payload}")

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
                        self.isHandshakeRequire = not self.performHandShake(seq=kickPacket['seq'] + 1,connectionStatus=connectionStatus, connectionStatusQueue=connectionStatusQueue)
                    else:
                        if(self.device.waitForNotifications(0.1) and self.device.delegate.isRxPacketReady):
                            self.parseRxPacket()
                        await asyncio.sleep(0.1)
            except BTLEDisconnectError:
                print("[BLE] >> Disconnected.")
                if (connectionStatus['isConnected']):
                    connectionStatus['isConnected'] = False
                    connectionStatusQueue.append(connectionStatus.copy())
                await asyncio.sleep(0.1)
                
# Placeholder function for Bluetooth communication
def get_soccer_action():
    """
    Simulate checking for a soccer action from the wearable.
    Replace this function with actual Bluetooth communication code.
    """
    action_occurred = len(kickPacketQueue) > 0
    if action_occurred:
        myKickPacket = kickPacketQueue.pop(0)
        return {
            'action': True,
            'player_id': PLAYER_ID,
            'action_type': 'soccer'
        }
    else:
        return None

class LegBeetleServer:
    def __init__(self):
        self.rabbitmq_connection = None
        self.channel = None
        self.should_run = True

    async def setup_rabbitmq(self):
        # Set up RabbitMQ connection using aio_pika
        print('[DEBUG] Connecting to RabbitMQ broker...')
        self.rabbitmq_connection = await aio_pika.connect_robust(
            host=BROKER,
            port=RABBITMQ_PORT,
            login=BROKERUSER,
            password=PASSWORD,
        )
        self.channel = await self.rabbitmq_connection.channel()
        # Declare the update_ge_queue
        await self.channel.declare_queue(UPDATE_GE_QUEUE, durable=True)
        print(f'[DEBUG] Connected to RabbitMQ broker at {BROKER}:{RABBITMQ_PORT}')

    async def send_connection_status(self):
        while self.should_run:
            toSend = len(connectionStatusQueue) > 0
            if toSend:
                myConnectionStatus = connectionStatusQueue.pop(0)
                message = {
                    "game_state": {
                        f"p{PLAYER_ID}": {
                            "leg_connected": myConnectionStatus['isConnected'],
                        }
                    },
                    "update": True
                }
                message_body = json.dumps(message).encode('utf-8')
                await self.channel.default_exchange.publish(
                    aio_pika.Message(body=message_body),
                    routing_key=UPDATE_GE_QUEUE,
                )
                print(f'[DEBUG] Published connection status to {UPDATE_GE_QUEUE}')
            await asyncio.sleep(0.1)
    
    async def send_soccer_action(self):
        while self.should_run:
            action_data = get_soccer_action()
            if action_data:
                message_body = json.dumps(action_data).encode('utf-8')
                await self.channel.default_exchange.publish(
                    aio_pika.Message(body=message_body),
                    routing_key=UPDATE_GE_QUEUE,
                )
                print(f'[DEBUG] Published soccer action to {UPDATE_GE_QUEUE}: {action_data}')
            await asyncio.sleep(0.1)  # Adjust sleep time as needed

    async def run(self):
        await self.setup_rabbitmq()
        await asyncio.gather(self.send_soccer_action(), self.send_connection_status())

async def main():
    await asyncio.gather(leg_beetle_server.run(), ble1.run())

if __name__ == '__main__':
    leg_beetle_server = LegBeetleServer()
    ble1 = ExtendedBLEConnection(MAC_ADDR, SERVICE_UUID, CHAR_UUID)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('[DEBUG] Leg Beetle Server stopped by user')
        leg_beetle_server.should_run = False
    except Exception as e:
        print(f'[ERROR] {e}')
