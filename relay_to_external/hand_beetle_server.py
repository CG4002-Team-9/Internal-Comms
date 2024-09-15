#!/usr/bin/env python

import asyncio
import json
import os
import time
from dotenv import load_dotenv
import aio_pika
import aiomqtt

# Load environment variables from .env file
load_dotenv()

# Broker configurations
BROKER = os.getenv('BROKER')
USERNAME = os.getenv('USERNAME')
PASSWORD = os.getenv('PASSWORD')
RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', '5672'))
MQTT_PORT = int(os.getenv('MQTT_PORT', '1883'))

# RabbitMQ queues
AI_QUEUE = 'ai_queue'
UPDATE_GE_QUEUE = 'update_ge_queue'

# MQTT topic
MQTT_TOPIC_UPDATE_EVERYONE = 'update_everyone'

# Player ID this server is handling
PLAYER_ID = int(os.getenv('PLAYER_ID', '1'))  # Set via environment variable or default to 1

# Placeholder functions for Bluetooth communication
def get_imu_data():
    """
    TODO: Implement the function to read IMU data from the wearable via Bluetooth.
    Should return a tuple of (ax, ay, az) where each is a list of integers.
    """
    # Example data (simulate with random integers for now)
    import random
    ax = [random.randint(-32768, 32767) for _ in range(40)]
    ay = [random.randint(-32768, 32767) for _ in range(40)]
    az = [random.randint(-32768, 32767) for _ in range(40)]
    return ax, ay, az

def get_gun_action():
    """
    TODO: Implement the function to check if the gun has fired and whether it hit the target.
    Should return a dictionary with 'action', 'bullets', and 'hit' keys.
    """
    # Example data (simulate with random values for now)
    import random
    action_occurred = random.choice([True, False])
    if action_occurred:
        return {
            'action': 'gun',
            'bullets': random.randint(0, 6),
            'hit': random.choice([True, False])
        }
    else:
        return None

def update_bullets_on_wearable(bullets):
    """
    TODO: Implement the function to update the bullets count on the wearable via Bluetooth.
    """
    print(f'[DEBUG] Updating bullets on wearable: {bullets}')

class HandBeetleServer:
    def __init__(self):
        self.rabbitmq_connection = None
        self.channel = None
        self.mqtt_client = None
        self.should_run = True

    async def setup_rabbitmq(self):
        # Set up RabbitMQ connection using aio_pika
        print('[DEBUG] Connecting to RabbitMQ broker...')
        self.rabbitmq_connection = await aio_pika.connect_robust(
            host=BROKER,
            port=RABBITMQ_PORT,
            login=USERNAME,
            password=PASSWORD,
        )
        self.channel = await self.rabbitmq_connection.channel()
        # Declare the queues (they will be created if they don't exist)
        await self.channel.declare_queue(AI_QUEUE, durable=True)
        await self.channel.declare_queue(UPDATE_GE_QUEUE, durable=True)
        print(f'[DEBUG] Connected to RabbitMQ broker at {BROKER}:{RABBITMQ_PORT}')

    async def setup_mqtt(self):
        # Set up MQTT client using aiomqtt
        print('[DEBUG] Connecting to MQTT broker...')
        self.mqtt_client = aiomqtt.Client(
            hostname=BROKER,
            port=MQTT_PORT,
            username=USERNAME,
            password=PASSWORD,
        )
        await self.mqtt_client.connect()
        print(f'[DEBUG] Connected to MQTT broker at {BROKER}:{MQTT_PORT}')

    async def send_imu_data(self):
        while self.should_run:
            ax, ay, az = get_imu_data()
            length = len(ax)
            message = {
                'length': length,
                'ax': ax,
                'ay': ay,
                'az': az,
                'player_id': PLAYER_ID
            }
            message_body = json.dumps(message).encode('utf-8')
            await self.channel.default_exchange.publish(
                aio_pika.Message(body=message_body),
                routing_key=AI_QUEUE,
            )
            print(f'[DEBUG] Published IMU data to {AI_QUEUE}')
            await asyncio.sleep(0.1)  # Adjust sleep time as needed

    async def send_gun_action(self):
        while self.should_run:
            action_data = get_gun_action()
            if action_data:
                # Include player_id in the message
                action_data['player_id'] = PLAYER_ID
                message_body = json.dumps(action_data).encode('utf-8')
                await self.channel.default_exchange.publish(
                    aio_pika.Message(body=message_body),
                    routing_key=UPDATE_GE_QUEUE,
                )
                print(f'[DEBUG] Published gun action to {UPDATE_GE_QUEUE}: {action_data}')
            await asyncio.sleep(0.1)  # Adjust sleep time as needed

    async def process_mqtt_messages(self):
        async with self.mqtt_client.messages() as messages:
            await self.mqtt_client.subscribe(MQTT_TOPIC_UPDATE_EVERYONE, qos=2)
            print(f'[DEBUG] Subscribed to MQTT topic {MQTT_TOPIC_UPDATE_EVERYONE}')
            async for message in messages:
                payload = message.payload.decode('utf-8')
                data = json.loads(payload)
                # Extract bullets for the specific player
                if 'game_state' in data:
                    player_key = f'p{PLAYER_ID}'
                    if player_key in data['game_state']:
                        bullets = data['game_state'][player_key].get('bullets', None)
                        if bullets is not None:
                            update_bullets_on_wearable(bullets)
                # Acknowledge the message
                await message.ack()

    async def run(self):
        await self.setup_rabbitmq()
        await self.setup_mqtt()

        # Run tasks concurrently
        await asyncio.gather(
            self.send_imu_data(),
            self.send_gun_action(),
            self.process_mqtt_messages()
        )

if __name__ == '__main__':
    hand_beetle_server = HandBeetleServer()
    try:
        asyncio.run(hand_beetle_server.run())
    except KeyboardInterrupt:
        print('[DEBUG] Hand Beetle Server stopped by user')
        hand_beetle_server.should_run = False
    except Exception as e:
        print(f'[ERROR] {e}')
