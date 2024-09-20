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
BROKERUSER = os.getenv('BROKERUSER')
PASSWORD = os.getenv('PASSWORD')
RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', '5672'))
MQTT_PORT = int(os.getenv('MQTT_PORT', '1883'))

# RabbitMQ queues
AI_QUEUE = 'ai_queue'
UPDATE_GE_QUEUE = 'update_ge_queue'

# MQTT topic
MQTT_TOPIC_UPDATE_EVERYONE = 'update_everyone'

# Player ID this server is handling
PLAYER_ID = int(os.getenv('PLAYER_ID', '1'))

# Placeholder functions for Bluetooth communication
def get_imu_data():
    import random
    ax = [random.randint(-32768, 32767) for _ in range(40)]
    ay = [random.randint(-32768, 32767) for _ in range(40)]
    az = [random.randint(-32768, 32767) for _ in range(40)]
    return ax, ay, az

def get_gun_action():
    import random
    action_occurred = random.choice([True, False])
    if action_occurred:
        return {
            'action': True,
            'action_type': 'gun',
            'hit': random.choice([True, False])
        }
    else:
        return None

def update_bullets_on_wearable(bullets):
    print(f'[DEBUG] Updating bullets on wearable: {bullets}')

class HandBeetleServer:
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

    async def process_mqtt_messages(self, mqtt_client):
        # Subscribe to MQTT topic
        await mqtt_client.subscribe(MQTT_TOPIC_UPDATE_EVERYONE, qos=2)
        print(f'[DEBUG] Subscribed to MQTT topic {MQTT_TOPIC_UPDATE_EVERYONE}')
        
        async for message in mqtt_client.messages:
            payload = message.payload.decode('utf-8')
            try:
                data = json.loads(payload)
                if 'game_state' in data:
                    player_key = f'p{PLAYER_ID}'
                    if player_key in data['game_state']:
                        bullets = data['game_state'][player_key].get('bullets', None)
                        if bullets is not None:
                            update_bullets_on_wearable(bullets)
            except json.JSONDecodeError:
                print(f'[ERROR] Invalid JSON payload: {payload}')
                
    async def run(self):
        await self.setup_rabbitmq()
        async with aiomqtt.Client(
            hostname=BROKER,
            port=MQTT_PORT,
            username=BROKERUSER,
            password=PASSWORD,
            indetifier=f'hand_beetle_server{PLAYER_ID}',
        ) as mqtt_client:
            await asyncio.gather(
                self.send_imu_data(),
                self.send_gun_action(),
                self.process_mqtt_messages(mqtt_client)
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
