'''
  ltr:
  - seq number
  - CRC
  - update the packet structure
  - separate vest, hand, leg
  - re-handshake when too many checksum wrong or ACK missing
  - (for consideration) : reset one of the beetle, (ble is not disconnected but all the data hold on beetle is reset)
  - resend bullet data when reestablish connection
  - pass data to ultra96


  curr:
  - handshake + re-handshake when disconnect
  - ack timeout, resend
  - can handle fragmentation
  - support kick, shoot, update, data, syn, ack
  - sending random data
'''

import bluepy.btle as btle
from bluepy.btle import Peripheral, BTLEDisconnectError
import time
import struct
import random

MAC_ADDR = "F4:B8:5E:42:67:1B"
SERVICE_UUID = "0000dfb0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000dfb1-0000-1000-8000-00805f9b34fb"

# Packet Types
SYN = 'S'
ACK = 'A'
SHOOT = 'G'
DATA = 'D'
KICK = 'K'
UPDATE = 'U'

beetleID = 2 #dont really need this?

updatePacket = {
    'deviceID': beetleID,
    'audio': 0,
    'reload': 0,
    'bullet': 6
}

shootPacket = {
    'deviceID': beetleID,
    'hit': 0,
    'bullet': 6
}

dataPacket = {
    'deviceID': beetleID,
    'accX': 0,
    'accY': 0,
    'accZ': 0,
    'gyrX': 0,
    'gyrY': 0,
    'gyrZ': 0 
}

kickPacket = {
    'deviceID': beetleID
    #'kick': 0
}

class MyDelegate(btle.DefaultDelegate):
    def __init__(self):
        btle.DefaultDelegate.__init__(self)
        self.rxPacketBuffer = b''
        self.packetType = ''
        
    def handleNotification(self, cHandle, data):
        global isRxPacketReady
        global rxPacketToProcess
        #print("    Packet Receive : ", data)
        self.rxPacketBuffer += data
        #print(">> Data : ", data)

        if (len(self.rxPacketBuffer) == 20):                        # TODO: checksum
            # can set flag that have packet to process
            rxPacketToProcess = b''
            rxPacketToProcess = self.rxPacketBuffer
            self.packetType = chr(rxPacketToProcess[0])
            print(" Received: ", self.packetType)
            
            isRxPacketReady = True
            self.rxPacketBuffer = b''

        elif (len(self.rxPacketBuffer) > 20):
            self.rxPacketBuffer = b''   #reset the buffer
        else:
            print(" Fragmented Packet ", len(self.rxPacketBuffer))
            isRxPacketReady = False
            # wait for the second part of packet
            # too many fragmanetaion fault -> rehandshake
    
    '''def updatePacketType(self):    #change to just readh the first char
        global rxPacketToProcess

        packetType = self.rxPacketBuffer[0]
        print(">> Received : ", packetType)
        
        return packetType'''

        

class BLEConnection:
    def __init__(self, macAddr, serviceUUID, charUUID):
        self.macAddr = macAddr
        self.serviceUUID = serviceUUID
        self.charUUID = charUUID
        self.device = None
        self.beetleSerial = None            # beetleSerial.write(bytes)

    def establishConnection(self):
        print("Searching and Connecting to the Beetle...")
        self.device = Peripheral()
        try:
            self.device.connect(self.macAddr)
        except BTLEDisconnectError:
            self.device.disconnect()
            self.device.connect(self.macAddr)

        self.device.setDelegate(MyDelegate())
        self.beetleSerial = self.device.getServiceByUUID(self.serviceUUID).getCharacteristics(self.charUUID)[0]
        print(">> Connection is established.")
        return True

    def sendSYN(self):
        self.beetleSerial.write(bytes(SYN + 19*'0', encoding="utf-8"))

    def sendACK(self):
        self.beetleSerial.write(bytes(ACK + 19*'0', encoding="utf-8"))
    
    def sendUPDATE(self):
        global isRxPacketReady
        while True: # Keep sending until ACK received
            self.beetleSerial.write(bytes(UPDATE + str(updatePacket['deviceID']) + str(updatePacket['audio']) + str(updatePacket['reload']) + str(updatePacket['bullet']) + 15*'0', encoding="utf-8"))
            print("Send UPDATE to the beetle")

            if (self.device.waitForNotifications(5) and isRxPacketReady):   # if no rehandshake need
                packetTypeReceived = self.device.delegate.packetType
                if (packetTypeReceived ==  ACK):
                    #print(">> Received ACK from the beetle")
                    print(">> Done update player")
                    return
                elif (packetTypeReceived ==  DATA): #if other data type will ignore
                    self.parseRxPacket() #update + send to server
        

    def performHandShake(self):
        global isHandshakeRequired
        global isRxPacketReady
        print("Performing Handshake...")
        print(">> Send SYN to the beetle")
        self.sendSYN()
        if (self.device.waitForNotifications(5) and isRxPacketReady):
            if (self.device.delegate.packetType ==  ACK):
                #print(">> Received ACK from the beetle")
                print(">> Send ACK to the beetle")
                self.sendACK()
                isHandshakeRequired = False
                print(">> Handshake Done.")
                return True
        print(">> Handshake Failed.")
        return False

    def parseRxPacket(self):    # TODO: check seq num, if invalid, the discard
        global rxPacketToProcess
        global dataCount
        global isAllDataReceived
        unpackFormat = "<c" + str(19) + "s"
        packetType, payload = struct.unpack(unpackFormat,rxPacketToProcess)
        packetType = packetType.decode(encoding="utf-8")

        if (packetType == SHOOT):
            unpackFormat = "<bbb" + str(16) + "s"
            shootPacket['deviceID'],shootPacket['hit'], shootPacket['bullet'], padding = struct.unpack(unpackFormat, payload)       # need beetleID?
            print( "    Updated ", shootPacket)
            self.sendACK()
        elif (packetType == DATA):
            isAllDataReceived = False
            dataCount += 1
            unpackFormat = "<bhhhhhh" + str(6) + "s"
            dataPacket['deviceID'],dataPacket['accX'], dataPacket['accY'], dataPacket['accZ'], dataPacket['gyrX'], dataPacket['gyrY'], dataPacket['gyrZ'], padding = struct.unpack(unpackFormat, payload)       # need beetleID?
            print( "    Updated ", dataPacket)
            # if all data received (check by seq), isAllDataReceived = true
            if (dataCount == 40):
                dataCount = 0
                isAllDataReceived = True
            
        elif (packetType == KICK):
            print( "    Updated ", kickPacket)
            self.sendACK()
        else:
            print(" Unpack: ", packetType, payload)
        
        return packetType

isHandshakeRequired = True
isRxPacketReady = False
rxPacketToProcess = b''
# put inside the class ltr
dataCount = 0
isAllDataReceived = False

if __name__ == '__main__':
    # main program
    while True:
        ble1 = BLEConnection(MAC_ADDR, SERVICE_UUID, CHAR_UUID)
        ble1.establishConnection()
        isHandshakeRequired = True
        try:
            while True:
                isRxPacketReady = False
                if (isHandshakeRequired):
                    isHandshakeRequired = not ble1.performHandShake()
                else: # if (no re-handshake needed)    
                    if(ble1.device.waitForNotifications(1) and isRxPacketReady):
                        prevPacketType = ble1.parseRxPacket()

                    isUpdateNeed = not bool(random.randint(0,5))
                    if (isUpdateNeed and (prevPacketType != DATA or isAllDataReceived)):
                        updatePacket['audio'] = random.randint(1,4)
                        ble1.sendUPDATE()

        except BTLEDisconnectError:
            pass
             # to next while loop, reestablish again
            #ble1.establishConnection()
