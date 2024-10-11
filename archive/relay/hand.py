import bluepy.btle as btle
from bluepy.btle import Peripheral, BTLEDisconnectError
from crc import Calculator, Crc8
import struct
import numpy as np
import random

glove_p1 = "F4:B8:5E:42:73:2A"
glove_p2 = "F4:B8:5E:42:67:1B"
vest_p2 = "F4:B8:5E:42:6D:2D"
leg_p2 = "F4:B8:5E:42:61:55"

MAC_ADDR = leg_p2
SERVICE_UUID = "0000dfb0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000dfb1-0000-1000-8000-00805f9b34fb"
IMU_TIMEOUT = 0.5
ACK_TIMEOUT = 0.2
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
    'bullets': 6
}

shootPacket = {
    'seq': 0,
    'hit': 0,
    'bullets': 6
}

dataPacket = {
    'seq': 0,
    'ax': [],
    'ay': [],
    'az': [],
    'gx': [],
    'gy': [],
    'gz': [] 
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

        # handle fragmentation
        if (len(self.rxPacketBuffer) >= 20):
            self.payload, crcReceived = struct.unpack("<19sB", self.rxPacketBuffer[:20])
            # handle CRC
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
        self.isAllImuReceived = False
        self.isHandshakeRequire = True
        self.isUpdateNeeded = False
        self.imuSeq = 0
        self.isGunUpdate = False

    # search for beetle and connect
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

    def sendACK(self, seq):
        print(f"[BLE]    Send ACK: {seq}")
        packet = bytes(ACK, 'utf-8') + bytes([np.uint8(seq)]) + bytes([0] * 17)
        packet = packet + (bytes)([np.uint8(CRC8.checksum(packet))])
        self.beetleSerial.write(packet)
    
    # send server update
    def sendUPDATE(self, bullets):
        self.isUpdateNeeded = True
        seq = updatePacket['seq'] 
        for i in range(5):
            packet = bytes(UPDATE, 'utf-8') + bytes([np.uint8(seq)]) + bytes([0] * 2) + bytes([np.uint8(bullets)]) + bytes([0] * 14)
            packet = packet + (bytes)([np.uint8(CRC8.checksum(packet))])
            self.beetleSerial.write(packet)
            print(f"[BLE] >> Send UPDATE to the beetle: {seq}")

            # wait for ack and check the ack seq
            if (self.device.waitForNotifications(ACK_TIMEOUT) and self.device.delegate.isRxPacketReady and not self.isHandshakeRequire):
                # successfully update
                if (self.device.delegate.packetType ==  ACK and (self.device.delegate.seqReceived == seq)):
                    self.isUpdateNeeded = False
                    seq += 1
                    if (seq) > 100:
                        seq = 0
                    updatePacket['seq'] = seq
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
            # successfully handshake
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

        if (dataPacket['seq'] == 0):
            dataPacket["ax"].clear()
            dataPacket["ay"].clear()
            dataPacket["az"].clear()
            dataPacket["gx"].clear()
            dataPacket["gy"].clear()
            dataPacket["gz"].clear()

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
                self.isGunUpdate = True
                shootPacket['seq']  = seqReceived
                unpackFormat = "<BB" + str(15) + "s"
                shootPacket['hit'], shootPacket['bullets'], padding = struct.unpack(unpackFormat, payload)
        
        elif (packetType == DATA):
            self.appendImuData()
            self.isAllImuReceived = False

            # break when received the last packet, or timeout, or received other types of packet that's not DATA
            while (not self.isAllImuReceived and self.device.waitForNotifications(IMU_TIMEOUT)):
                if (not self.device.delegate.isRxPacketReady): # in case of fragmentation
                    continue
                if (self.device.delegate.packetType != DATA):
                    break
                
                self.appendImuData()

                if (dataPacket['seq'] == 59):
                    self.isAllImuReceived = True

            # if wait the next data until timeout, append the data
            if (dataPacket['seq'] != 59):
                dataPacket['seq'] = 59
                self.appendImuData()

            # all data is ready
            self.isAllImuReceived = True
            self.imuSeq = 0
            print(f"[BLE] >> All IMU data is received.")
            print("[BLE] _______________________________________________________________ ")
            #get_imu_data()
        
        elif (packetType == SYNACK):
            self.sendSYNACK(0)
        
        else:
            self.device.delegate.invalidPacketCounter += 1
            print(f" Unpack: {packetType} {payload}")
        
        self.device.delegate.packetType = ''
        return packetType

    def main(self):
        self.device.delegate.isRxPacketReady = False
        # re-handshake if needed
        if ((self.device.delegate.invalidPacketCounter >= 5) or self.isHandshakeRequire):
            self.isHandshakeRequire = not self.performHandShake()
        else: 
            # send update if needed
            isUpdateNeed = not bool(random.randint(0,6)) and shootPacket['bullets'] == 0
            if (isUpdateNeed and (self.device.delegate.packetType != DATA or self.isAllImuReceived)):
                self.sendUPDATE(updatePacket['bullets'])
            
            # wait for any update from beetle
            if(self.device.waitForNotifications(0.1) and self.device.delegate.isRxPacketReady):
                ble1.parseRxPacket()

# Placeholder functions for Bluetooth communication
def get_imu_data():
    action_occurred = ble1.isAllImuReceived
    if action_occurred:
        ble1.isAllImuReceived = False
        ax = dataPacket['ax']
        ay = dataPacket['ay']
        az = dataPacket['az']
        gx = dataPacket['gx']
        gy = dataPacket['gy']
        gz = dataPacket['gz']

        # either clear here or appendImuData()
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
    action_occurred = ble1.isGunUpdate
    if action_occurred:
        ble1.isGunUpdate = False
        print(f"[BLE] >> Relay Gun Action")
        return {
            'action': True,
            'action_type': 'gun',
            'hit': shootPacket['hit']
        }
    else:
        return None
    
if __name__ == '__main__':
    # main program
    while True:
        try: 
            ble1 = BLEConnection(MAC_ADDR, SERVICE_UUID, CHAR_UUID)
            ble1.establishConnection()
            ble1.isHandshakeRequire = True
            while True:
                ble1.main()

        except BTLEDisconnectError:
            pass
