#!/usr/bin/env python

import asyncio
import os
from dotenv import load_dotenv
import aiomqtt

# Load environment variables from .env file
load_dotenv()

# Broker configurations
BROKER = os.getenv('BROKER')
BROKERUSER = os.getenv('BROKERUSER')
PASSWORD = os.getenv('PASSWORD')
MQTT_PORT = int(os.getenv('MQTT_PORT', '1883'))

# MQTT topic
MQTT_TOPIC_UPDATE_EVERYONE = 'update_everyone'

async def clear_retained_message():
    print('[DEBUG] Connecting to MQTT broker to clear retained message...')
    async with aiomqtt.Client(
        hostname=BROKER,
        port=MQTT_PORT,
        username=BROKERUSER,
        password=PASSWORD,
        identifier='clear_retained_message_script',
    ) as mqtt_client:
        print(f'[DEBUG] Connected to MQTT broker at {BROKER}:{MQTT_PORT}')
        # Publish an empty message with retain=True to clear the retained message
        await mqtt_client.publish(MQTT_TOPIC_UPDATE_EVERYONE, payload=None, qos=1, retain=True)
        print(f'[DEBUG] Cleared retained message on topic {MQTT_TOPIC_UPDATE_EVERYONE}')

if __name__ == '__main__':
    try:
        asyncio.run(clear_retained_message())
    except Exception as e:
        print(f'[ERROR] {e}')
