#!/usr/bin/env python

import os
from dotenv import load_dotenv

import bluepy.btle as btle
from bluepy.btle import Peripheral, BTLEDisconnectError
from crc import Calculator, Crc8
import struct
import numpy as np

import csv

import tensorflow as tf
from sklearn.preprocessing import MinMaxScaler
import pickle
from sklearn.preprocessing import LabelEncoder

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
DEVICE = "LEG"
MAC_ADDR = os.getenv(f'{DEVICE}_P{PLAYER_ID}')
print(f'[DEBUG] MAC Address: {MAC_ADDR}')
SERVICE_UUID = "0000dfb0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000dfb1-0000-1000-8000-00805f9b34fb"
IMU_TIMEOUT = 0.5
ACK_TIMEOUT = 0.5
HANDSHAKE_TIMEOUT = 2
CRC8 = Calculator(Crc8.CCITT)
PACKET_SIZE = 15
DATASIZE = 40

# Packet Types
SYN = 'S'
SYNACK = 'C'
ACK = 'A'
SHOOT = 'G'
DATA = 'D'
UPDATE = 'U'

connectionStatus = {
    'isConnected': False,
}

connectionStatusQueue = []

updatePacket = {        # ['U', seq, hp, shield, bullets, sound, ..., CRC]
    'seq': 0,
    'bullets': 6,
    'isReload': False,
}

updatePacketQueue = []

shootPacket = {
    'seq': 0,
    'hit': 0,
}

shootPacketQueue = []

dataPacket = {
    'seq': 0,
    'ax': [0] * DATASIZE,
    'ay': [0] * DATASIZE,
    'az': [0] * DATASIZE,
    'gx': [0] * DATASIZE,
    'gy': [0] * DATASIZE,
    'gz': [0] * DATASIZE,
    'imuCounter': 0,
    'isAllImuReceived': False 
}

dataPacketQueue = []

model = tf.keras.models.load_model('gesture_model_real_leg.h5')

# Define the scaler to scale between -1 and 1 (to maintain negative values)
scaler = MinMaxScaler(feature_range=(-1, 1))

# Fit the scaler with the 16-bit signed integer range (this only needs to be done once)
scaler.fit(np.array([-2**15, 2**15 - 1]).reshape(-1, 1))


with open('label_encoder_leg.pkl', 'rb') as file:
    label_encoder = pickle.load(file)

# Function to pad or truncate the data to exactly 60 samples
def pad_or_truncate(array, target_length=DATASIZE):
    if len(array) > target_length:
        return array[:target_length]
    elif len(array) < target_length:
        return array + [0] * (target_length - len(array))
    else:
        return array


import tkinter as tk
import threading
import time

# Global variable to set the size of the overlay
OVERLAY_WIDTH = 700
OVERLAY_HEIGHT = 200
BORDER_RADIUS = 100  # Adjust to make the corners more or less rounded
TRANSPARENCY_LEVEL = 0  # Adjust for semi-transparency

def round_rectangle(canvas, x1, y1, x2, y2, radius=25, **kwargs):
    """Draw a rounded rectangle on the given canvas."""
    points = [
        (x1 + radius, y1),
        (x2 - radius, y1),
        (x2, y1),
        (x2, y1 + radius),
        (x2, y2 - radius),
        (x2, y2),
        (x2 - radius, y2),
        (x1 + radius, y2),
        (x1, y2),
        (x1, y2 - radius),
        (x1, y1 + radius),
        (x1, y1)
    ]
    
    return canvas.create_polygon(points, smooth=True, **kwargs)

def show_overlay(predicted_action, duration=2):
    """Display a temporary, pill-shaped overlay showing the predicted action with transparency on Linux."""
    root = tk.Tk()
    root.overrideredirect(True)  # Remove window borders
    root.attributes("-topmost", True)  # Keep on top of other windows
    root.attributes('-alpha', TRANSPARENCY_LEVEL)  # Set transparency level
    
    # Set the geometry of the window to be centered
    root.geometry(f"{OVERLAY_WIDTH}x{OVERLAY_HEIGHT}+{root.winfo_screenwidth()//2 - OVERLAY_WIDTH//2}+{root.winfo_screenheight()//2 - OVERLAY_HEIGHT//2}")
    
    # Create a canvas to draw the pill-shaped background
    canvas = tk.Canvas(root, width=OVERLAY_WIDTH, height=OVERLAY_HEIGHT, highlightthickness=0, bg="black")
    canvas.pack(fill="both", expand=True)
    
    # Draw a rounded rectangle as the pill shape background
    round_rectangle(canvas, 0, 0, OVERLAY_WIDTH, OVERLAY_HEIGHT, radius=BORDER_RADIUS, fill="black")
    
    # Create a label with a bigger font that fills the window (centered in the pill shape)
    label = tk.Label(canvas, text=predicted_action, font=("Arial", int(OVERLAY_HEIGHT * 0.2), "bold"), fg="white", bg="black")
    label.place(relx=0.5, rely=0.5, anchor="center")

    # Close the overlay after a delay using tkinter's after method
    root.after(duration * 1000, root.destroy)

    # Start the Tkinter main loop (this should stay in the main thread)
    root.mainloop()


# Update the predict_action function to show the overlay without threading
def predict_action():
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
    if max_probability >= 0:
        # Decode the predicted class index back to the original label
        predicted_label = label_encoder.inverse_transform(predicted_class)
        predicted_action = f"{predicted_label[0]} ({max_probability:.5f})"
        print(f"Predicted label: {predicted_label[0]} with probability: {max_probability:.5f}")
        
        # Show the predicted action in an overlay
        show_overlay(predicted_action)
    else:
        print("Ignored action (probability too low)")
    
    # Reset the dataPacket for the next IMU data collection
    dataPacket['ax'] = [0] * DATASIZE
    dataPacket['ay'] = [0] * DATASIZE
    dataPacket['az'] = [0] * DATASIZE
    dataPacket['gx'] = [0] * DATASIZE
    dataPacket['gy'] = [0] * DATASIZE
    dataPacket['gz'] = [0] * DATASIZE
    dataPacket['isAllImuReceived'] = False
    dataPacket['imuCounter'] = 0

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

        if (len(self.rxPacketBuffer) >= PACKET_SIZE):
            self.payload, crcReceived = struct.unpack(f"<{PACKET_SIZE - 1}sB", self.rxPacketBuffer[:PACKET_SIZE])
            if (CRC8.verify(self.payload, crcReceived)):
                self.invalidPacketCounter = 0
                self.packetType, self.seqReceived, self.payload = struct.unpack(f"<cB{PACKET_SIZE - 3}s", self.payload)
                self.packetType = chr(self.packetType[0])
                self.isRxPacketReady = True
                print(f"[BLE]  Received: {self.packetType} Seq: {self.seqReceived}")
                self.rxPacketBuffer = self.rxPacketBuffer[PACKET_SIZE:]
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
        packet = bytes(SYN, 'utf-8') + bytes([np.uint8(seq)]) + bytes([0] * (PACKET_SIZE - 3))
        packet = packet + (bytes)([np.uint8(CRC8.checksum(packet))])
        print(packet)
        self.beetleSerial.write(packet)
        
    def sendSYNACK(self, seq):
        print(f"[BLE] >> Send SYNACK: {seq}")
        packet = bytes(SYNACK, 'utf-8') + bytes([np.uint8(seq)]) + bytes([0] * (PACKET_SIZE - 3))
        packet = packet + (bytes)([np.uint8(CRC8.checksum(packet))])
        self.beetleSerial.write(packet)

    def sendACK(self, seq):
        print(f"[BLE]    Send ACK: {seq}")
        packet = bytes(ACK, 'utf-8') + bytes([np.uint8(seq)]) + bytes([0] * (PACKET_SIZE - 3))
        packet = packet + (bytes)([np.uint8(CRC8.checksum(packet))])
        self.beetleSerial.write(packet)
    
    def sendUPDATE(self):
        print("[BLE] >> Sending UPDATE...")
        myUpdatePacket = updatePacketQueue.pop(0)
        print(f"[BLE] >> Update Packet: {myUpdatePacket}")
        for i in range(5):
            packet = bytes(UPDATE, 'utf-8') + bytes([np.uint8(updatePacket['seq'] )]) + bytes([0] * 3) + bytes([np.uint8(myUpdatePacket['bullets'])]) + bytes([np.uint8(myUpdatePacket['isReload'])]) + bytes([0] * (PACKET_SIZE - 8))
            packet = packet + (bytes)([np.uint8(CRC8.checksum(packet))])
            self.beetleSerial.write(packet)
            print(f"[BLE] >> Send UPDATE to the beetle: {updatePacket['seq']}")

            if (self.device.waitForNotifications(ACK_TIMEOUT) and self.device.delegate.isRxPacketReady and not self.isHandshakeRequire):
                if (self.device.delegate.packetType == SYNACK):
                    self.sendSYNACK(0)
                elif (self.device.delegate.packetType ==  ACK and (self.device.delegate.seqReceived == updatePacket['seq'])):
                    updatePacket['seq'] += 1
                    updatePacket['seq'] %= 100
                    print("[BLE] >> Done update player")
                    print("[BLE] _______________________________________________________________ ")
                    return 
                # if recevied data instead of ACK, collect the data first
                elif (self.device.delegate.packetType == DATA):
                    self.parseRxPacket()

            elif (self.isHandshakeRequire):
                break
        # after 5 attempts of sending update
        self.isHandshakeRequire = True

    def performHandShake(self):
        print("[BLE] >> Performing Handshake...")
        self.sendSYN(0)
        if (self.device.waitForNotifications(HANDSHAKE_TIMEOUT) and self.device.delegate.isRxPacketReady):
            if (self.device.delegate.packetType ==  SYNACK):
                self.sendSYNACK(0)
                self.isHandshakeRequire = False
                if (self.device.delegate.invalidPacketCounter >= 5):
                    self.device.delegate.invalidPacketCounter = 0
                print("[BLE] >> Handshake Done.")
                print("[BLE] _______________________________________________________________ ")
                if (not connectionStatus['isConnected']):
                    connectionStatus['isConnected'] = True
                    connectionStatusQueue.append(connectionStatus.copy())
                return True
        print("[BLE] >> Handshake Failed.")
        return False

    def appendImuData(self):
        if dataPacket['seq'] >= DATASIZE - 1:
            return

        unpackFormat = "<hhhhhh"
        ax, ay, az, gx, gy, gz = struct.unpack(unpackFormat, self.device.delegate.payload)
        print(f"[BLE]    Received {ax}, {ay}, {az}, {gx}, {gy}, {gz}")
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

        if (packetType == SHOOT):
            self.sendACK(seqReceived)
        
        elif (packetType == DATA):
            dataPacket['seq']  = self.device.delegate.seqReceived
            if (dataPacket['seq'] >= 5):
                return
            self.appendImuData()

            # break when received the last packet, or timeout, or received other types of packet that's not DATA
            while (not dataPacket['isAllImuReceived'] and self.device.waitForNotifications(IMU_TIMEOUT)):
                if (not self.device.delegate.isRxPacketReady): # in case of fragmentation
                    continue
                if (self.device.delegate.packetType != DATA):
                    break
                
                dataPacket['seq']  = self.device.delegate.seqReceived
                self.appendImuData()

                if (dataPacket['seq'] >= DATASIZE - 1):
                    dataPacket['isAllImuReceived'] = True

            # all data is ready
            dataPacket['isAllImuReceived'] = True
            print(f"[BLE] >> All IMU data is received.")
            predict_action()
            
        elif (packetType == SYNACK):
            self.sendSYNACK(0)
        
        else:
            self.device.delegate.invalidPacketCounter += 1
            print(f"[BLE] Unpack: {packetType} {payload}")
        
        self.device.delegate.packetType = ''
        return packetType

    def run(self):
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
                        if (len(updatePacketQueue) > 0):
                            self.sendUPDATE()
                        if (self.device.waitForNotifications(0.1) and self.device.delegate.isRxPacketReady):
                            self.parseRxPacket()
            except BTLEDisconnectError:
                print("[BLE] >> Disconnected.")
                if (connectionStatus['isConnected']):
                    connectionStatus['isConnected'] = False
                    connectionStatusQueue.append(connectionStatus.copy())

# Placeholder functions for Bluetooth communication
def get_imu_data():
    action_occurred = dataPacket['isAllImuReceived'] and dataPacket['imuCounter'] > 30
    
    ax = dataPacket['ax'].copy()
    ay = dataPacket['ay'].copy()
    az = dataPacket['az'].copy()
    gx = dataPacket['gx'].copy()
    gy = dataPacket['gy'].copy()
    gz = dataPacket['gz'].copy()
    # Reset all back to 0
    dataPacket['ax'] = [0] * DATASIZE
    dataPacket['ay'] = [0] * DATASIZE
    dataPacket['az'] = [0] * DATASIZE
    dataPacket['gx'] = [0] * DATASIZE
    dataPacket['gy'] = [0] * DATASIZE
    dataPacket['gz'] = [0] * DATASIZE
    dataPacket['isAllImuReceived'] = False
    dataPacket['imuCounter'] = 0
    
    if action_occurred:
        print(f"[BLE] >> Relay IMU Data to Server")
        return ax, ay, az, gx, gy, gz
    else:
        return None

if __name__ == '__main__':
    ble1 = BLEConnection(MAC_ADDR, SERVICE_UUID, CHAR_UUID)
    try:
        ble1.run()
    except KeyboardInterrupt:
        print('[DEBUG] Glove Beetle Server stopped by user')

