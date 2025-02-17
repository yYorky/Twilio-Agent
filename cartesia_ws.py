import asyncio
import websockets
import json
import os
import logging
from voice_assistant.config import Config

TTS_WEBSOCKET_URL = f"wss://api.cartesia.ai/tts/websocket?api_key={Config.CARTESIA_API_KEY}&cartesia_version=2024-06-10"
model_id = 'sonic-english'
voice_id = "156fb8d2-335b-4950-9cb3-a2d33befec77"

async def connect_to_tts_websocket():
    """
    Connect to the Cartesia TTS WebSocket and return the WebSocket object.
    """
    try:
        logging.info("Connecting to Cartesia TTS WebSocket...")
        tts_websocket = await websockets.connect(TTS_WEBSOCKET_URL)
        logging.info("Connected to TTS WebSocket.")
        return tts_websocket
    except Exception as e:
        logging.error(f"TTS WebSocket connection failed: {e}")
        raise

async def send_tts_message(tts_websocket, message):
    logging.info(f"🔊 Sending message to Cartesia TTS: {message}")  # <-- ADD THIS LOG
    text_message = {
        'model_id': model_id,
        'transcript': message,
        'voice': {'mode': 'id', 'id': voice_id},
        'output_format': {'container': 'raw', 'encoding': 'pcm_mulaw', 'sample_rate': 8000}
    }
    await tts_websocket.send(json.dumps(text_message))

