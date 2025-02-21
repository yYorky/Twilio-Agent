import asyncio
import websockets
import json
import logging
import os
import uuid
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

# Cartesia TTS WebSocket URL
CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY")
CARTESIA_TTS_WEBSOCKET_URL = (
    f"wss://api.cartesia.ai/tts/websocket?api_key={CARTESIA_API_KEY}"
    "&cartesia_version=2024-06-10"
)

async def text_to_speech(text: str, twilio_websocket, streamSid: str):
    """
    Convert text to speech using Cartesia TTS WebSocket and stream the audio to Twilio WebSocket.
    This version mimics the JS flow by forwarding the received payload as-is.
    """
    logging.info("🔗 Connecting to Cartesia TTS WebSocket...")
    async with websockets.connect(CARTESIA_TTS_WEBSOCKET_URL) as tts_ws:
        logging.info("✅ Connected to Cartesia TTS WebSocket.")

        context_id = f"context_{uuid.uuid4().hex}"
        tts_request = {
            "model_id": "sonic",
            "transcript": text,
            "voice": {
                "mode": "id",
                "id": "156fb8d2-335b-4950-9cb3-a2d33befec77"
            },
            "context_id": context_id,
            "output_format": {
                "container": "raw",
                "encoding": "pcm_mulaw",
                "sample_rate": 8000
            }
        }

        await tts_ws.send(json.dumps(tts_request))
        logging.info(f"🗣️ Sent text to TTS WebSocket: {text}")

        async for message in tts_ws:
            if isinstance(message, str):
                try:
                    data = json.loads(message)
                except Exception as e:
                    logging.error(f"Error parsing TTS message: {e}")
                    continue

                # logging.info(f"📜 Received metadata from Cartesia: {data}")

                if "error" in data:
                    logging.error(f"❌ Cartesia API Error: {data['error']}")
                    break

                if data.get("done", False):
                    logging.info("✅ TTS generation complete.")
                    break

                if "data" in data:
                    payload = data["data"]  # Expecting a Base64 string
                    if not streamSid:
                        # logging.error("❌ streamSid is missing. Cannot send audio to Twilio.")
                        continue

                    try:
                        # Use send_text (FastAPI WebSocket method) instead of send()
                        await twilio_websocket.send_text(json.dumps({
                            "event": "media",
                            "streamSid": streamSid,
                            "media": {
                                "payload": payload
                            }
                        }))
                        # logging.info("🎵 Forwarded audio chunk to Twilio.")
                    except Exception as e:
                        logging.error(f"❌ Failed to forward audio chunk: {e}")
            else:
                logging.warning("⚠️ Received non-text message from TTS WebSocket.")
        logging.info("🔚 TTS streaming completed.")
