#!/usr/bin/env python

import asyncio
import json
import os
from dotenv import load_dotenv
import aio_pika
from bluepy.btle import BTLEDisconnectError
import struct
import myBle
import collections

# Load environment variables from .env file
load_dotenv()

# Broker configurations
BROKER = os.getenv('BROKER')
BROKERUSER = os.getenv('BROKERUSER')
PASSWORD = os.getenv('PASSWORD')
RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', '5672'))

# RabbitMQ queues
AI_QUEUE = os.getenv('AI_QUEUE', 'ai_queue')
UPDATE_GE_QUEUE = os.getenv('UPDATE_GE_QUEUE', 'update_ge_queue')

# RabbitMQ exchanges
UPDATE_EVERYONE_EXCHANGE = os.getenv('UPDATE_EVERYONE_EXCHANGE', 'update_everyone_exchange')

# Player ID this server is handling
PLAYER_ID = int(os.getenv('PLAYER_ID', '1'))
print(f'[DEBUG] Player ID: {PLAYER_ID}')

# BLE variables
MAC_ADDR = os.getenv(f'GLOVE_P{PLAYER_ID}')
print(f'[DEBUG] MAC Address: {MAC_ADDR}')
IMU_SAMPLES = 59

connectionStatus = {
    'isConnected': False,
}

updatePacket = {
    'seq': 0,
    'bullets': 6,
    'isReload': False,
}

connectionStatusQueue = collections.deque()
updatePacketQueue = collections.deque()

shootPacket = {
    'seq': 0,
    'hit': 0,
}

shootPacketQueue = collections.deque()

dataPacket = {
    'seq': 0,
    'ax': [0] * IMU_SAMPLES,
    'ay': [0] * IMU_SAMPLES,
    'az': [0] * IMU_SAMPLES,
    'gx': [0] * IMU_SAMPLES,
    'gy': [0] * IMU_SAMPLES,
    'gz': [0] * IMU_SAMPLES,
    'imuCounter': 0,
    'isAllImuReceived': False 
}

# BLE Connection
class ExtendedBLEConnection(myBle.BLEConnection):
    # Unpack IMU data and store in dataPacket
    def appendImuData(self):
        unpackFormat = "<hhhhhh"
        ax, ay, az, gx, gy, gz = struct.unpack(unpackFormat, self.device.delegate.payload)

        dataPacket['imuCounter'] += 1
        dataPacket['ax'][dataPacket['seq']] = ax
        dataPacket['ay'][dataPacket['seq']] = ay
        dataPacket['az'][dataPacket['seq']] = az
        dataPacket['gx'][dataPacket['seq']] = gx
        dataPacket['gy'][dataPacket['seq']] = gy
        dataPacket['gz'][dataPacket['seq']] = gz

    # Parse received packet
    def parseRxPacket(self):
        packetType = self.device.delegate.packetType
        seqReceived = self.device.delegate.seqReceived
        payload = self.device.delegate.payload

        # get the shoot data
        if (packetType == myBle.SHOOT):
            self.sendACK(seqReceived)
            if (shootPacket['seq'] != seqReceived):
                shootPacket['seq']  = seqReceived
                unpackFormat = "<B" + str(myBle.PACKET_SIZE - 4) + "s"
                shootPacket['hit'], padding = struct.unpack(unpackFormat, payload)
                shootPacketQueue.append(shootPacket.copy())
        
        elif (packetType == myBle.DATA):
            dataPacket['seq'] = self.device.delegate.seqReceived
            if (dataPacket['seq'] >= 5): # ignored those extra samples from previous set that stuck in buffer
                return
            
            self.appendImuData()

            # Check if all IMU data is received
            while (not dataPacket['isAllImuReceived'] and self.device.waitForNotifications(myBle.IMU_TIMEOUT)):
                # handle packet
                if (not self.device.delegate.isRxPacketReady): # in case of fragmentation
                    continue
                if (self.device.delegate.packetType != myBle.DATA): # receive other packet; eg. sHOOT
                    self.imuSeq = 0
                    print(f"[BLE] >> Recevied {self.device.delegate.packetType}. End of IMU data.")
                    self.parseRxPacket()
                    return

                # get the imu data
                dataPacket['seq'] = self.device.delegate.seqReceived
                if (dataPacket['seq'] <= IMU_SAMPLES - 1): # save IMU data
                    self.appendImuData()
                if (dataPacket['seq'] >= IMU_SAMPLES - 1): # all IMU data is received
                    dataPacket['isAllImuReceived'] = True

            # all IMU data is received
            dataPacket['isAllImuReceived'] = True
            self.imuSeq = 0
            print(f"[BLE] >> All IMU data is received.")
        
        # send SYNACK packet to finish the handshake
        elif (packetType == myBle.SYNACK):
            self.sendSYNACK(0)
        
        else:
            # invalid packet handling
            self.device.delegate.invalidPacketCounter += 1
            print(f"[BLE] Unpack: {packetType} {payload}")
        
        self.device.delegate.packetType = ''
        return packetType

    async def run(self):
        while True:
            try: 
                self = ExtendedBLEConnection(MAC_ADDR, myBle.SERVICE_UUID, myBle.CHAR_UUID)
                self.establishConnection()
                self.isHandshakeRequire = True
                while True:
                    self.device.delegate.isRxPacketReady = False
                    if ((self.device.delegate.invalidPacketCounter >= 5) or self.isHandshakeRequire):
                        self.isHandshakeRequire = not self.performHandShake(seq=shootPacket['seq'] + 1, connectionStatus=connectionStatus, connectionStatusQueue=connectionStatusQueue)
                    else:
                        if (len(updatePacketQueue) > 0):
                            self.sendUPDATE(updatePacket, myUpdatePacket = updatePacketQueue.pop(), isGloveUpdate=True)
                        if (self.device.waitForNotifications(0.1) and self.device.delegate.isRxPacketReady):
                            self.parseRxPacket()
                    await asyncio.sleep(0.1)

            except BTLEDisconnectError:
                print("[BLE] >> Disconnected.")
                if (connectionStatus['isConnected']):
                    connectionStatus['isConnected'] = False
                    connectionStatusQueue.append(connectionStatus.copy())
                await asyncio.sleep(0.1)

# Functions to get data from BLE and send to RabbitMQ
def get_imu_data():
    action_occurred = dataPacket['isAllImuReceived'] and dataPacket['imuCounter'] > (IMU_SAMPLES - 5)
    ax = dataPacket['ax'].copy()
    ay = dataPacket['ay'].copy()
    az = dataPacket['az'].copy()
    gx = dataPacket['gx'].copy()
    gy = dataPacket['gy'].copy()
    gz = dataPacket['gz'].copy()
    dataPacket['ax'] = [0] * IMU_SAMPLES
    dataPacket['ay'] = [0] * IMU_SAMPLES
    dataPacket['az'] = [0] * IMU_SAMPLES
    dataPacket['gx'] = [0] * IMU_SAMPLES
    dataPacket['gy'] = [0] * IMU_SAMPLES
    dataPacket['gz'] = [0] * IMU_SAMPLES
    dataPacket['isAllImuReceived'] = False
    dataPacket['imuCounter'] = 0

    if action_occurred:
        print(f"[BLE] >> Relay IMU Data to Server")
        return ax, ay, az, gx, gy, gz
    else:
        return None

def get_gun_action():
    action_occurred = len(shootPacketQueue) > 0
    if action_occurred:
        myShootPacket = shootPacketQueue.pop()
        return {
            'action': True,
            'action_type': 'gun',
            'hit': myShootPacket['hit']
        }
    else:
        return None

# RabbitMQ server
class GloveBeetleServer:
    def __init__(self):
        self.rabbitmq_connection = None
        self.channel = None
        self.exchange = None
        self.update_queue = None
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
        # DECLARE EXCHANGE STUFF
        self.exchange = await self.channel.declare_exchange(UPDATE_EVERYONE_EXCHANGE, aio_pika.ExchangeType.FANOUT, durable=True)
        self.update_queue = await self.channel.declare_queue('', exclusive=True)
        await self.update_queue.bind(self.exchange)
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
                    'player_id': PLAYER_ID,
                    'imu_device': 'glove'
                }
                print(f"[DEBUG] Length of IMU Data: {length}")
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
                myConnectionStatus = connectionStatusQueue.pop()
                message = {
                    "game_state": {
                        f"p{PLAYER_ID}": {
                        "glove_connected": myConnectionStatus['isConnected'],
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
                    print(f'[DEBUG] Received update: {payload}')
                    try:
                        data = json.loads(payload)
                        game_state = data.get('game_state', {})
                        
                        toupdate = data.get('update', False)
                        if toupdate:
                            connectionStatusQueue.append(connectionStatus.copy())
                        
                        
                        action = data.get('action', None)
                        player_id_for_action = data.get('player_id', None)
                        player_key = f'p{PLAYER_ID}'
                        bullets = game_state.get(player_key).get('bullets', None)
                        
                        if bullets is not None:
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
        
        await asyncio.gather(
            self.send_imu_data(),
            self.send_gun_action(),
            self.send_connection_status(),
            self.consume_updates(),
        )

async def main():
    await asyncio.gather(glove_beetle_server.run(), ble1.run())

if __name__ == '__main__':
    glove_beetle_server = GloveBeetleServer()
    ble1 = ExtendedBLEConnection(MAC_ADDR, myBle.SERVICE_UUID, myBle.CHAR_UUID)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('[DEBUG] Glove Beetle Server stopped by user')
        glove_beetle_server.should_run = False
    except Exception as e:
        print(f'[ERROR] {e}')
