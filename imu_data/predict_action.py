import bluepy.btle as btle
from bluepy.btle import Peripheral, BTLEDisconnectError
from crc import Calculator, Crc8
import time
import struct
import numpy as np
import random
import csv
import tensorflow as tf
from sklearn.preprocessing import MinMaxScaler
import pickle
from sklearn.preprocessing import LabelEncoder

MAC_ADDR = "F4:B8:5E:42:73:2A"# glove 1 #"F4:B8:5E:42:61:55"  # "F4:B8:5E:42:67:1B"  # hand, 2
SERVICE_UUID = "0000dfb0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000dfb1-0000-1000-8000-00805f9b34fb"
IMU_TIMEOUT = 0.5
ACK_TIMEOUT = 0.5
CRC8 = Calculator(Crc8.CCITT)

# Packet Types
SYN = 'S'
SYNACK = 'C'
ACK = 'A'
SHOOT = 'G'
DATA = 'D'
UPDATE = 'U'

updatePacket = {
    'seq': 0,
    'bullet': 6
}

shootPacket = {
    'seq': 0,
    'hit': 0,
    'bullet': 6
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

# Load the trained model
model = tf.keras.models.load_model('gesture_model_real.h5')

# Load the saved LabelEncoder
with open('label_encoder.pkl', 'rb') as file:
    label_encoder = pickle.load(file)

# Define the scaler to scale between -1 and 1 (to maintain negative values)
scaler = MinMaxScaler(feature_range=(-1, 1))

# Fit the scaler with the 16-bit signed integer range (this only needs to be done once)
scaler.fit(np.array([-2**15, 2**15 - 1]).reshape(-1, 1))

# Function to pad or truncate the data to exactly 60 samples
def pad_or_truncate(array, target_length=60):
    if len(array) > target_length:
        return array[:target_length]
    elif len(array) < target_length:
        return array + [0] * (target_length - len(array))
    else:
        return array

# Replace get_imu_data with the prediction workflow
def get_imu_data():
    # Ensure each IMU data array has 60 elements
    ax_padded = pad_or_truncate(dataPacket["ax"])
    ay_padded = pad_or_truncate(dataPacket["ay"])
    az_padded = pad_or_truncate(dataPacket["az"])
    gx_padded = pad_or_truncate(dataPacket["gx"])
    gy_padded = pad_or_truncate(dataPacket["gy"])
    gz_padded = pad_or_truncate(dataPacket["gz"])
    
    # Concatenate all six arrays (ax, ay, az, gx, gy, gz)
    imu_data = ax_padded + ay_padded + az_padded + gx_padded + gy_padded + gz_padded
    print("IMU Data:", imu_data)  # Sanity check
    imu_data = np.array(imu_data).reshape(-1, 1)  # Reshape for the scaler
    
    # Scale the data
    scaled_imu_data = scaler.transform(imu_data).flatten()
    print("Scaled IMU Data:", scaled_imu_data)  # Sanity check
    
    # Reshape the data for the model (1 sample, 360 features)
    input_data = scaled_imu_data.reshape(1, -1, 1)  # Assuming your CNN expects (samples, time steps, channels)
    
    # Make prediction using the loaded TensorFlow model
    prediction = model.predict(input_data)
    
    # Print probabilities with 5 decimal places
    probabilities = prediction.flatten()
    print("Prediction probabilities:", [f"{prob:.5f}" for prob in probabilities])
    
    # Get the predicted class (as an index)
    predicted_class = np.argmax(prediction, axis=1)
    
    # Check if the highest probability is above the threshold
    max_probability = np.max(probabilities)
    if max_probability >= 0.94:
        # Decode the predicted class index back to the original label
        predicted_label = label_encoder.inverse_transform(predicted_class)
        print(f"Predicted label: {predicted_label[0]} with probability: {max_probability:.5f}")
    else:
        print("Ignored action (probability too low)")
    
    # Reset the dataPacket for the next IMU data collection
    dataPacket["ax"] = []
    dataPacket["ay"] = []
    dataPacket["az"] = []
    dataPacket["gx"] = []
    dataPacket["gy"] = []
    dataPacket["gz"] = []

# Example of how BLE data is processed, and how `get_imu_data()` is called after data reception
# This would remain the same in your script, but `get_imu_data()` is now handling live predictions

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
        self.isAllDataReceived = False
        self.isHandshakeRequire = True
        self.isUpdateNeeded = False
        self.imuSeq = 0
        self.isGunUpdate = False

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
    
    def sendUPDATE(self):
        self.isUpdateNeeded = True
        updatePacket['seq'] += 1
        for i in range(5):
            packet = bytes(UPDATE, 'utf-8') + bytes([0] * 2) +bytes([np.uint8(updatePacket['bullet'])]) + bytes([0] * 14)
            packet = packet + (bytes)([np.uint8(CRC8.checksum(packet))])
            self.beetleSerial.write(packet)
            print(f"[BLE] >> Send UPDATE to the beetle: {updatePacket['seq']}")

            # wait for ack and check the ack seq
            if (self.device.waitForNotifications(ACK_TIMEOUT) and self.device.delegate.isRxPacketReady and not self.isHandshakeRequire):
                if (self.device.delegate.packetType ==  ACK and (self.device.delegate.seqReceived == updatePacket['seq'])):
                    self.isUpdateNeeded = False
                    updatePacket['seq'] += 1
                    if (updatePacket['seq']) > 100:
                        updatePacket['seq'] = 0
                    print("[BLE] >> Done update player")
                    print("[BLE] _______________________________________________________________ ")
                    return
                elif (self.device.delegate.packetType ==  DATA):
                    self.parseRxPacket()
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

    def updateData(self):
        dataPacket['seq']  = self.device.delegate.seqReceived
        unpackFormat = "<hhhhhh" + str(5) + "s"
        ax, ay, az, gx, gy, gz, padding = struct.unpack(unpackFormat, self.device.delegate.payload)
        # dataPacket['ax'].append(ax)
        # dataPacket['ay'].append(ay)
        # dataPacket['az'].append(az)
        # dataPacket['gx'].append(gx)
        # dataPacket['gy'].append(gy)
        # dataPacket['gz'].append(gz)
        # print(ax, ay, az, gx, gy, gz)
        if dataPacket['seq'] == 0:
            self.imuSeq = 0
            dataPacket['ax'] = []
            dataPacket['ay'] = []
            dataPacket['az'] = []
            dataPacket['gx'] = []
            dataPacket['gy'] = []
            dataPacket['gz'] = []

        while (dataPacket['seq'] >= self.imuSeq):
            dataPacket['ax'].append(ax)
            dataPacket['ay'].append(ay)
            dataPacket['az'].append(az)
            dataPacket['gx'].append(gx)
            dataPacket['gy'].append(gy)
            dataPacket['gz'].append(gz)
            self.imuSeq += 1
        #print(f"    Updated {dataPacket}")

    def parseRxPacket(self):
        packetType = self.device.delegate.packetType
        seqReceived = self.device.delegate.seqReceived
        payload = self.device.delegate.payload

        if (packetType == SHOOT):
            self.sendACK(seqReceived)
            if (shootPacket['seq'] != seqReceived):
                shootPacket['seq']  = seqReceived
                unpackFormat = "<BB" + str(15) + "s"
                shootPacket['hit'], shootPacket['bullet'], padding = struct.unpack(unpackFormat, payload)
        elif (packetType == DATA):
            self.updateData()
            self.isAllDataReceived = False
            # break when received the last packet, or timeout, or received other types of packet that's not DATA
            while (not self.isAllDataReceived and self.device.waitForNotifications(IMU_TIMEOUT)):
                if (not self.device.delegate.isRxPacketReady): # in case of fragmentation
                    continue
                if (self.device.delegate.packetType != DATA):
                    break
                self.updateData()
                if (dataPacket['seq'] == 59):
                    self.isAllDataReceived = True
            # wait next data until timeout, make sure there is no empty data point
            if (dataPacket['seq'] != 59):
                dataPacket['seq'] = 59
                self.updateData()
            # all data is ready
            self.isAllDataReceived = True
            self.imuSeq = 0
            print(f"[BLE]    All IMU data is received.")
            #print(dataPacket)
            get_imu_data()
            print("[BLE] _______________________________________________________________ ")
        if (packetType == SYNACK):
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
            isUpdateNeed = not bool(random.randint(0,10)) and shootPacket['bullet'] == 0
            if (isUpdateNeed and (self.device.delegate.packetType != DATA or self.isAllDataReceived)):
                self.sendUPDATE()
            if(self.device.waitForNotifications(0.1) and self.device.delegate.isRxPacketReady):
                ble1.parseRxPacket()

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
