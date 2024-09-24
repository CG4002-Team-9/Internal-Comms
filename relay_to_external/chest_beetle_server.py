#!/usr/bin/env python

import asyncio
import json
import os
from dotenv import load_dotenv
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
MQTT_PORT = int(os.getenv('MQTT_PORT', '1883'))

# MQTT topic
MQTT_TOPIC_UPDATE_EVERYONE = 'update_everyone'

# Player ID this server is handling
PLAYER_ID = int(os.getenv('PLAYER_ID', '2'))

# BLE
chest_p1 = ""
chest_p2 = "F4:B8:5E:42:6D:2D"
leg_p2 = "F4:B8:5E:42:61:55"
MAC_ADDR = leg_p2
SERVICE_UUID = "0000dfb0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000dfb1-0000-1000-8000-00805f9b34fb"
ACK_TIMEOUT = 0.2
CRC8 = Calculator(Crc8.CCITT)

# Packet Types
SYN = 'S'
SYNACK = 'C'
ACK = 'A'
UPDATE = 'U'

updatePacket = {    # ['U', seq, hp, shield, bullets, sound, ..., CRC]
    'seq': 0,
    'hp': 90,
    'shield_hp': 10,
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
        # self.isUpdateNeeded = False

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
        # self.isUpdateNeeded = True
        for i in range(5):
            packet = bytes(UPDATE, 'utf-8') + bytes([np.uint8(updatePacket['seq']), np.uint8(updatePacket['hp']), np.uint8(updatePacket['shield_hp'])]) + bytes([0] * 15)
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
                        await asyncio.sleep(0.1)
                        #await asyncio.sleep(5)
                        #updatePacket['isUpdateNeeded'] = True

            except BTLEDisconnectError:
                pass

class ChestBeetleServer:
    def __init__(self):
        self.should_run = True

    async def process_mqtt_messages(self, mqtt_client):
        # Subscribe to MQTT topic
        await mqtt_client.subscribe(MQTT_TOPIC_UPDATE_EVERYONE, qos=2)
        print(f'[DEBUG] Subscribed to MQTT topic {MQTT_TOPIC_UPDATE_EVERYONE}')
        
        async for message in mqtt_client.messages:
            payload = message.payload.decode('utf-8')
            try:
                data = json.loads(payload)
                # Extract HP and shield info for the specific player
                if 'game_state' in data:
                    player_key = f'p{PLAYER_ID}'
                    if player_key in data['game_state']:
                        hp = data['game_state'][player_key].get('hp', None)
                        shield_hp = data['game_state'][player_key].get('shield_hp', None)
                        if hp is not None and shield_hp is not None:
                            print(f'[DEBUG] Updating wearable - HP: {hp}, Shield HP: {shield_hp}')
                            updatePacket['hp'] = hp
                            updatePacket['shield_hp'] = shield_hp
                            updatePacket['isUpdateNeeded'] = True
                            #ble1.sendUPDATE() <-- this might not work, so use the above flag instead
            except json.JSONDecodeError:
                print(f'[ERROR] Invalid JSON payload: {payload}')

    async def run(self):
        print('[DEBUG] Connecting to MQTT broker...')
        async with aiomqtt.Client(
            hostname=BROKER,
            port=MQTT_PORT,
            username=BROKERUSER,
            password=PASSWORD,
            identifier=f'chest_beetle_server{PLAYER_ID}',
        ) as mqtt_client:
            print(f'[DEBUG] Connected to MQTT broker at {BROKER}:{MQTT_PORT}')
            await self.process_mqtt_messages(mqtt_client)

async def main():
    await asyncio.gather(chest_beetle_server.run(), ble1.run())

if __name__ == '__main__':
    chest_beetle_server = ChestBeetleServer()
    #mac_addr = f'MAC_ADDR_{PLAYER_ID}'
    ble1 = BLEConnection(MAC_ADDR, SERVICE_UUID, CHAR_UUID)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('[DEBUG] Chest Beetle Server stopped by user')
        chest_beetle_server.should_run = False
    except Exception as e:
        print(f'[ERROR] {e}')
