#!/usr/bin/env python

import asyncio
import json
import os
from dotenv import load_dotenv
import aio_pika
from bluepy.btle import BTLEDisconnectError
import struct
import myBle

# Load environment variables from .env file
load_dotenv()

# Broker configurations
BROKER = os.getenv('BROKER')
BROKERUSER = os.getenv('BROKERUSER')
PASSWORD = os.getenv('PASSWORD')
RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', '5672'))

# RabbitMQ queue
AI_QUEUE = os.getenv('AI_QUEUE', 'ai_queue')
UPDATE_GE_QUEUE = os.getenv('UPDATE_GE_QUEUE', 'update_ge_queue')

# Player ID this server is handling
PLAYER_ID = int(os.getenv('PLAYER_ID', '1'))
print(f'[DEBUG] Player ID: {PLAYER_ID}')

# BLE
MAC_ADDR = os.getenv(f'LEG_P{PLAYER_ID}')
IMU_SAMPLES = 60

connectionStatus = {
    'isConnected': False,
}
connectionStatusQueue = []

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

dataPacketQueue = []

class ExtendedBLEConnection(myBle.BLEConnection):
    def appendImuData(self):
        unpackFormat = "<hhhhhh"
        ax, ay, az, gx, gy, gz = struct.unpack(unpackFormat, self.device.delegate.payload)
        print(f"[BLE]    Saved {ax}, {ay}, {az}, {gx}, {gy}, {gz}")

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
            
        if (packetType == myBle.DATA):
            dataPacket['seq'] = self.device.delegate.seqReceived
            if (dataPacket['seq'] >= 5): # ignored those samples that stuck in buffer
                return
            
            self.appendImuData()
            
            while (not dataPacket['isAllImuReceived'] and self.device.waitForNotifications(myBle.IMU_TIMEOUT)):
                if (not self.device.delegate.isRxPacketReady): # in case of fragmentation
                    continue
                if (self.device.delegate.packetType != myBle.DATA):
                    break

                dataPacket['seq'] = self.device.delegate.seqReceived
                if (dataPacket['seq'] <= IMU_SAMPLES - 1):  # ignored extra samples
                    self.appendImuData()
                if (dataPacket['seq'] >= IMU_SAMPLES - 1):
                    dataPacket['isAllImuReceived'] = True

            dataPacket['isAllImuReceived'] = True
            self.imuSeq = 0
            print(f"[BLE] >> All IMU data is received.")
            
        elif (packetType == myBle.SYNACK):
            self.sendSYNACK(0)
        
        else:
            self.device.delegate.invalidPacketCounter += 1
            print(f"[BLE] Unpack: {packetType} {payload}")
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
                        self.isHandshakeRequire = not self.performHandShake(seq=0,connectionStatus=connectionStatus, connectionStatusQueue=connectionStatusQueue)
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

# Placeholder functions for Bluetooth communication
def get_imu_data():
    action_occurred = dataPacket['isAllImuReceived'] and dataPacket['imuCounter'] > 30
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

class LegBeetleServer:
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
                    'player_id': PLAYER_ID,
                    'imu_device': 'leg'
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
    
    async def run(self):
        await self.setup_rabbitmq()

        await asyncio.gather(
            self.send_imu_data(),
            self.send_connection_status(),
        )

async def main():
    await asyncio.gather(leg_beetle_server.run(), ble1.run())

if __name__ == '__main__':
    leg_beetle_server = LegBeetleServer()
    ble1 = ExtendedBLEConnection(MAC_ADDR, myBle.SERVICE_UUID, myBle.CHAR_UUID)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('[DEBUG] Leg Beetle Server stopped by user')
        leg_beetle_server.should_run = False
    except Exception as e:
        print(f'[ERROR] {e}')