import json
import logging
import asyncio
import websockets
from chat_handler import process_voice_query  # Import Verbi's AI handler
from voice_assistant.transcription import transcribe_audio
from voice_assistant.response_generation import generate_response
from voice_assistant.text_to_speech import text_to_speech
from voice_assistant.api_key_manager import get_transcription_api_key, get_response_api_key, get_tts_api_key

async def handle_twilio_connection(websocket, path, retriever):
    """
    Handles Twilio WebSocket connection.
    Receives user speech, transcribes it, generates a response, and sends AI-generated speech back.
    """
    try:
        logging.info("🔗 Twilio WebSocket connection established.")
        stream_sid = None

        async for message in websocket:
            msg = json.loads(message)
            logging.info(f"📥 Received Twilio message: {msg}")  # Debugging log

            if msg.get("event") == "start":
                stream_sid = msg["start"]["streamSid"]
                logging.info(f"🟢 Stream started: {stream_sid}")

                # 🎤 Get AI-generated greeting message from chat_handler
                greeting_text = process_voice_query(is_first_message=True)
                logging.info(f"🤖 AI Greeting: {greeting_text}")

                # 🗣️ Convert AI Greeting to Speech using Cartesia
                tts_api_key = get_tts_api_key()
                text_to_speech("cartesia", tts_api_key, greeting_text, "greeting.mp3")

                # Send greeting to Twilio WebSocket
                await websocket.send(json.dumps({"text": greeting_text}))
                logging.info("📤 Sent AI-generated greeting audio to Twilio.")

            elif msg.get("event") == "media":
                # 🔊 Convert user speech to text
                user_audio = msg["media"]["payload"]
                transcription_api_key = get_transcription_api_key()
                user_text = transcribe_audio("groq", transcription_api_key, user_audio)

                logging.info(f"🎤 User Speech Transcribed: {user_text}")

                # 🤖 Generate AI Response
                response_api_key = get_response_api_key()
                ai_response = generate_response("groq", response_api_key, [{"role": "user", "content": user_text}])

                logging.info(f"🤖 AI Response: {ai_response}")

                # 🗣️ Convert AI Response to Speech using Cartesia
                text_to_speech("cartesia", tts_api_key, ai_response, "response.mp3")

                # Send AI-generated speech to Twilio WebSocket
                await websocket.send(json.dumps({"text": ai_response}))
                logging.info("📤 Sent AI-generated speech to Twilio.")

            elif msg.get("event") == "stop":
                logging.info("🔴 Call ended.")
                break

            # 🔄 Send keepalive messages to prevent disconnection
            await asyncio.sleep(5)
            await websocket.send(json.dumps({"event": "keepalive"}))
            logging.info("🔄 Sent keepalive message to Twilio.")

    except Exception as e:
        logging.error(f"⚠️ Error handling Twilio WebSocket: {e}")



async def setup_twilio_websocket(process_voice_query, retriever, tts_websocket):
    """
    Sets up Twilio WebSocket Server.
    """
    server = await websockets.serve(
        lambda ws, path: handle_twilio_connection(ws, path, process_voice_query, retriever, tts_websocket),
        "0.0.0.0",
        8001
    )
    logging.info("Twilio WebSocket server is running.")
    return server
