#!/usr/bin/env python

import asyncio
import json
import os
from dotenv import load_dotenv
import aio_pika
import collections

from bluepy.btle import BTLEDisconnectError
import myBle

# Load environment variables from .env file
load_dotenv()

# Broker configurations
BROKER = os.getenv('BROKER')
BROKERUSER = os.getenv('BROKERUSER')
PASSWORD = os.getenv('PASSWORD')
RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', '5672'))

# RabbitMQ queues
UPDATE_GE_QUEUE = os.getenv('UPDATE_GE_QUEUE', 'update_ge_queue')

# RabbitMQ exchanges
UPDATE_EVERYONE_EXCHANGE = os.getenv('UPDATE_EVERYONE_EXCHANGE', 'update_everyone_exchange')

# Player ID this server is handling
PLAYER_ID = int(os.getenv('PLAYER_ID', '2'))
print(f'[DEBUG] Player ID: {PLAYER_ID}')

# BLE variables
MAC_ADDR = os.getenv(f'VEST_P{PLAYER_ID}')
print(f'[DEBUG] MAC Address: {MAC_ADDR}')

connectionStatus = {
    'isConnected': False,
}

updatePacket = {
    'seq': 0,
    'hp': 90,
    'shield_hp': 10,
    'action_type': 0, # 0: no action, 1: damaged, 2: shield deployed
}

connectionStatusQueue = collections.deque()
updatePacketQueue = collections.deque()

# BLE connection
class ExtendedBLEConnection(myBle.BLEConnection):
    async def run(self):
        while True:
            try: 
                self = ExtendedBLEConnection(MAC_ADDR, myBle.SERVICE_UUID, myBle.CHAR_UUID)
                self.establishConnection()
                self.isHandshakeRequire = True
                while True:
                    self.device.delegate.isRxPacketReady = False
                    if ((self.device.delegate.invalidPacketCounter >= 5) or self.isHandshakeRequire):
                        print(f"[BLE] >> Invalid Packet Counter Exceeded: {self.device.delegate.invalidPacketCounter}")
                        self.isHandshakeRequire = not self.performHandShake(seq=0,connectionStatus=connectionStatus, connectionStatusQueue=connectionStatusQueue)
                    else:
                        if (len(updatePacketQueue) > 0):
                            self.sendUPDATE(updatePacket, myUpdatePacket = updatePacketQueue.pop(), isVestUpdate=True)
                        if (self.device.waitForNotifications(0.1) and self.device.delegate.isRxPacketReady):
                            pass
                    await asyncio.sleep(0.1)

            except BTLEDisconnectError:
                print("[BLE] >> Disconnected.")
                if connectionStatus['isConnected']:
                    connectionStatus['isConnected'] = False
                    connectionStatusQueue.append(connectionStatus.copy())
                await asyncio.sleep(0.1)

# RabbitMQ server
class VestBeetleServer:
    def __init__(self):
        self.rabbitmq_connection = None
        self.channel = None
        self.should_run = True
        self.exchange = None
        self.update_queue = None

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
        self.exchange = await self.channel.declare_exchange(UPDATE_EVERYONE_EXCHANGE, aio_pika.ExchangeType.FANOUT, durable=True)
        self.update_queue = await self.channel.declare_queue('', exclusive=True)
        await self.update_queue.bind(self.exchange)
        print(f'[DEBUG] Connected to RabbitMQ broker at {BROKER}:{RABBITMQ_PORT}')
    
    async def send_connection_status(self):
        while self.should_run:
            toSend = len(connectionStatusQueue) > 0
            if toSend:
                myConnectionStatus = connectionStatusQueue.pop()
                message = {
                    "game_state": {
                        f"p{PLAYER_ID}": {
                            "vest_connected": myConnectionStatus['isConnected'],
                        }
                    },
                    "update": True,
                    "f": True
                }
                message_body = json.dumps(message).encode('utf-8')
                await self.channel.default_exchange.publish(
                    aio_pika.Message(body=message_body),
                    routing_key=UPDATE_GE_QUEUE,
                )
                print(f'[DEBUG] Published connection status to {UPDATE_GE_QUEUE}')
            await asyncio.sleep(0.1)
    
    async def consume_updates(self):
        async with self.update_queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process():
                    payload = message.body.decode('utf-8')
                    try:
                        data = json.loads(payload)
                        print(f'[DEBUG] Received RabbitMQ payload: {data}')
                        
                        toupdate = data.get('update', False)
                        if toupdate:
                            connectionStatusQueue.append(connectionStatus.copy())
                            
                        game_state = data.get('game_state', {})
                        action = data.get('action', None)
                        player_id_for_action = data.get('player_id', None)
                        player_key = f'p{PLAYER_ID}'
                        
                        hp = game_state.get(player_key, {}).get('hp', None)
                        shield_hp = game_state.get(player_key, {}).get('shield_hp', None)
                        
                        if hp is not None and shield_hp is not None:
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
                            updatePacketQueue.append(updatePacket.copy())
                    
                    except json.JSONDecodeError:
                        print(f'[ERROR] Invalid JSON payload: {payload}')
                    except Exception as e:
                        print(f'[ERROR] {e}')
            
    async def run(self):
        await self.setup_rabbitmq()

        await asyncio.gather(
            self.send_connection_status(),
            self.consume_updates(),
        )
            

async def main():
    await asyncio.gather(vest_beetle_server.run(),ble1.run())

if __name__ == '__main__':
    vest_beetle_server = VestBeetleServer()
    ble1 = ExtendedBLEConnection(MAC_ADDR, myBle.SERVICE_UUID, myBle.CHAR_UUID)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('[DEBUG] Vest Beetle Server stopped by user')
        vest_beetle_server.should_run = False
    except Exception as e:
        print(f'[ERROR] {e}')