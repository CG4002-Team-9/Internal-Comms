#!/usr/bin/env python

import asyncio
import json
import os
import time
from dotenv import load_dotenv
import aio_pika

# Load environment variables from .env file
load_dotenv()

# Broker configurations
BROKER = os.getenv('BROKER')
BROKERUSER = os.getenv('BROKERUSER')
PASSWORD = os.getenv('PASSWORD')
RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', '5672'))

# RabbitMQ queue
UPDATE_GE_QUEUE = 'update_ge_queue'

# Player ID this server is handling
PLAYER_ID = int(os.getenv('PLAYER_ID', '1'))

# Placeholder function for Bluetooth communication
def get_soccer_action():
    """
    Simulate checking for a soccer action from the wearable.
    Replace this function with actual Bluetooth communication code.
    """
    import random
    action_occurred = random.choice([True, False])
    if action_occurred:
        return {
            'action': True,
            'player_id': PLAYER_ID,
            'action_type': 'soccer'
        }
    else:
        return None

class LegBeetleServer:
    def __init__(self):
        self.rabbitmq_connection = None
        self.channel = None
        self.should_run = True

    async def setup_rabbitmq(self):
        # Set up RabbitMQ connection using aio_pika
        print('[DEBUG] Connecting to RabbitMQ broker...')
        self.rabbitmq_connection = await aio_pika.connect_robust(
            host=BROKER,
            port=RABBITMQ_PORT,
            login=BROKERUSER,
            password=PASSWORD,
        )
        self.channel = await self.rabbitmq_connection.channel()
        # Declare the update_ge_queue
        await self.channel.declare_queue(UPDATE_GE_QUEUE, durable=True)
        print(f'[DEBUG] Connected to RabbitMQ broker at {BROKER}:{RABBITMQ_PORT}')

    async def send_soccer_action(self):
        while self.should_run:
            action_data = get_soccer_action()
            if action_data:
                message_body = json.dumps(action_data).encode('utf-8')
                await self.channel.default_exchange.publish(
                    aio_pika.Message(body=message_body),
                    routing_key=UPDATE_GE_QUEUE,
                )
                print(f'[DEBUG] Published soccer action to {UPDATE_GE_QUEUE}: {action_data}')
            await asyncio.sleep(0.1)  # Adjust sleep time as needed

    async def run(self):
        await self.setup_rabbitmq()
        # Start sending soccer actions
        await self.send_soccer_action()

if __name__ == '__main__':
    leg_beetle_server = LegBeetleServer()
    try:
        asyncio.run(leg_beetle_server.run())
    except KeyboardInterrupt:
        print('[DEBUG] Leg Beetle Server stopped by user')
        leg_beetle_server.should_run = False
    except Exception as e:
        print(f'[ERROR] {e}')
