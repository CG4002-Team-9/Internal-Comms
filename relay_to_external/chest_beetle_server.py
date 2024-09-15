#!/usr/bin/env python

import asyncio
import json
import os
from dotenv import load_dotenv
import aiomqtt

# Load environment variables from .env file
load_dotenv()

# Broker configurations
BROKER = os.getenv('BROKER')
USERNAME = os.getenv('USERNAME')
PASSWORD = os.getenv('PASSWORD')
MQTT_PORT = int(os.getenv('MQTT_PORT', '1883'))

# MQTT topic
MQTT_TOPIC_UPDATE_EVERYONE = 'update_everyone'

# Player ID this server is handling
PLAYER_ID = int(os.getenv('PLAYER_ID', '1'))  # Set via environment variable or default to 1

# Placeholder function for Bluetooth communication
def update_hp_and_shield_on_wearable(hp, shield_hp):
    """
    TODO: Implement the function to update HP and shield info on the wearable via Bluetooth.
    """
    print(f'[DEBUG] Updating wearable - HP: {hp}, Shield HP: {shield_hp}')

class ChestBeetleServer:
    def __init__(self):
        self.mqtt_client = None
        self.should_run = True

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

    async def process_mqtt_messages(self):
        async with self.mqtt_client.messages() as messages:
            await self.mqtt_client.subscribe(MQTT_TOPIC_UPDATE_EVERYONE, qos=2)
            print(f'[DEBUG] Subscribed to MQTT topic {MQTT_TOPIC_UPDATE_EVERYONE}')
            async for message in messages:
                payload = message.payload.decode('utf-8')
                data = json.loads(payload)
                # Extract HP and shield info for the specific player
                if 'game_state' in data:
                    player_key = f'p{PLAYER_ID}'
                    if player_key in data['game_state']:
                        hp = data['game_state'][player_key].get('hp', None)
                        shield_hp = data['game_state'][player_key].get('shield_hp', None)
                        if hp is not None and shield_hp is not None:
                            update_hp_and_shield_on_wearable(hp, shield_hp)
                # Acknowledge the message
                await message.ack()

    async def run(self):
        await self.setup_mqtt()
        await self.process_mqtt_messages()

if __name__ == '__main__':
    chest_beetle_server = ChestBeetleServer()
    try:
        asyncio.run(chest_beetle_server.run())
    except KeyboardInterrupt:
        print('[DEBUG] Chest Beetle Server stopped by user')
        chest_beetle_server.should_run = False
    except Exception as e:
        print(f'[ERROR] {e}')
