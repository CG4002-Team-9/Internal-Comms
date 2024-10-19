#!/usr/bin/env python

import asyncio
import json
import os
import threading
import tkinter as tk
from tkinter import ttk
from dotenv import load_dotenv
import aio_pika

# Load environment variables from .env file
load_dotenv()

# RabbitMQ configuration
BROKER = os.getenv('BROKER')
BROKERUSER = os.getenv('BROKERUSER')
PASSWORD = os.getenv('PASSWORD')
RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', '5672'))
UPDATE_PREDICTIONS_EXCHANGE = os.getenv("UPDATE_PREDICTIONS_EXCHANGE", "update_predictions_exchange")

class PredictionWindow:
    def __init__(self, root):
        self.root = root
        self.root.overrideredirect(True)  # Remove window borders
        self.root.configure(bg='#2e2e2e')  # Dark background for sleek look

        # Set window size (Increased the size for better readability)
        window_width = 800
        window_height = 500

        # Get screen width and height
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()

        # Calculate position x, y to center the window
        x = (screen_width // 2) - (window_width // 2)
        y = (screen_height // 2) - (window_height // 2)

        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")

        # Make window stay on top
        self.root.attributes("-topmost", True)

        # Styling
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TLabel", foreground="#ffffff", background="#2e2e2e", font=("Helvetica", 16))  # Increased font size
        style.configure("Header.TLabel", font=("Helvetica", 20, "bold"))  # Increased header font size

        # Create labels with more padding
        self.header_label = ttk.Label(root, text="Action Prediction", style="Header.TLabel")
        self.header_label.pack(pady=15)  # Added more padding

        self.player_id_label = ttk.Label(root, text="Player ID: N/A")
        self.player_id_label.pack(pady=10)  # Increased padding between labels

        self.action_type_label = ttk.Label(root, text="Action Type: N/A")
        self.action_type_label.pack(pady=10)

        self.confidence_label = ttk.Label(root, text="Confidence: N/A")
        self.confidence_label.pack(pady=10)

        # Add a close button (optional, since window is borderless)
        self.close_button = ttk.Button(root, text="Close", command=self.root.destroy)
        self.close_button.pack(pady=20)  # Added padding to close button

    def update_prediction(self, player_id, action_type, confidence):
        self.player_id_label.config(text=f"Player ID: {player_id}")
        self.action_type_label.config(text=f"Action Type: {action_type}")
        self.confidence_label.config(text=f"Confidence: {confidence:.2f}")

class RabbitMQConsumer:
    def __init__(self, window):
        self.window = window
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.start_loop, daemon=True)
        self.thread.start()

    def start_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.consume_messages())

    async def consume_messages(self):
        try:
            connection = await aio_pika.connect_robust(
                host=BROKER,
                port=RABBITMQ_PORT,
                login=BROKERUSER,
                password=PASSWORD,
            )
            channel = await connection.channel()
            exchange = await channel.declare_exchange(
                UPDATE_PREDICTIONS_EXCHANGE, aio_pika.ExchangeType.FANOUT, durable=True
            )
            queue = await channel.declare_queue('', exclusive=True)
            await queue.bind(exchange)

            print('[DEBUG] Connected to RabbitMQ and bound to exchange.')

            async with queue.iterator() as queue_iter:
                async for message in queue_iter:
                    async with message.process():
                        try:
                            data = json.loads(message.body.decode('utf-8'))
                            player_id = data.get('player_id', 'N/A')
                            action_type = data.get('action_type', 'N/A')
                            confidence = data.get('confidence', 0.0)

                            # Update the Tkinter window in the main thread
                            self.window.root.after(0, self.window.update_prediction, player_id, action_type, confidence)

                        except json.JSONDecodeError as e:
                            print(f'[ERROR] Failed to decode JSON: {e}')
                        except Exception as e:
                            print(f'[ERROR] Unexpected error: {e}')

        except Exception as e:
            print(f'[ERROR] Failed to connect to RabbitMQ: {e}')

def main():
    # Initialize Tkinter
    root = tk.Tk()
    prediction_window = PredictionWindow(root)

    # Start RabbitMQ consumer
    consumer = RabbitMQConsumer(prediction_window)

    # Run Tkinter main loop
    root.mainloop()

if __name__ == '__main__':
    main()
