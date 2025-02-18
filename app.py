import os
import json
import asyncio
import base64
import tempfile
import streamlit as st
import websockets
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import Response
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect
from pdf_processing import process_pdf
from voice_assistant.response_generation import generate_response
from voice_assistant.transcription import transcribe_audio
from voice_assistant.text_to_speech import text_to_speech
from voice_assistant.api_key_manager import get_response_api_key, get_transcription_api_key, get_tts_api_key
from voice_assistant.config import Config
from threading import Thread
import uvicorn
from twilio.rest import Client
from ngrok_tunnel import setup_ngrok_tunnel
from voice_assistant.audio import record_audio
import time
import logging
import subprocess

# FastAPI instance for WebSocket handling
fastapi_app = FastAPI()

# Streamlit UI
st.title("AI Voice Assistant with Twilio and AI Models")
st.sidebar.header("Upload a PDF to train the AI")
uploaded_file = st.sidebar.file_uploader("Choose a PDF file", type=["pdf"])

retriever = None
if uploaded_file is not None:
    pdf_path = f"temp_{uploaded_file.name}"
    with open(pdf_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    retriever = process_pdf(pdf_path)
    st.sidebar.success("PDF processed successfully!")

# Twilio call initiation
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
DESTINATION_PHONE_NUMBER = os.getenv("DESTINATION_PHONE_NUMBER")

# Setup ngrok tunnel
NGROK_URL = setup_ngrok_tunnel(5050)

def initiate_call():
    if not NGROK_URL:
        st.error("Ngrok tunnel could not be established.")
        return
    
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    call = client.calls.create(
        to=DESTINATION_PHONE_NUMBER,
        from_=TWILIO_PHONE_NUMBER,
        url=f"{NGROK_URL}/incoming-call",
        method="GET"
    )
    st.success(f"Call initiated to {DESTINATION_PHONE_NUMBER}. Call SID: {call.sid}")

st.button("Call AI Assistant", on_click=initiate_call)

@fastapi_app.get("/")
async def index():
    return Response(content="Twilio AI Voice Assistant is running!", media_type="text/plain")

@fastapi_app.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    response = VoiceResponse()
    response.say("Connecting you to the AI assistant.")
    response.pause(length=1)
    response.say("You can start talking now.")
    host = request.url.hostname
    connect = Connect()
    connect.stream(url=f'wss://{host}/media-stream')
    response.append(connect)
    return Response(content=str(response), media_type="application/xml; charset=utf-8")

@fastapi_app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    await websocket.accept()
    call_active = True  # Keep the call open until the caller hangs up
    
    async def receive_from_twilio():
        nonlocal call_active
        while call_active:
            try:
                message = await websocket.receive_text()
                data = json.loads(message)
                
                if data['event'] == 'media':
                    audio_file_path = f"recorded_audio_{os.getpid()}.mp3"
                    recorded_path = record_audio(audio_file_path)
                    
                    if recorded_path:
                        transcribed_text = transcribe_audio(Config.TRANSCRIPTION_MODEL, get_transcription_api_key(), recorded_path)
                        response = generate_response(Config.RESPONSE_MODEL, get_response_api_key(), [{"role": "user", "content": transcribed_text}])
                        
                        if retriever:
                            context = retriever.get_relevant_documents(transcribed_text)
                            response = generate_response(Config.RESPONSE_MODEL, get_response_api_key(), [{"role": "system", "content": str(context)}, {"role": "user", "content": transcribed_text}])
                        
                        # Generate speech file in Twilio-compatible format (PCM μ-law 8kHz)
                        audio_response_path = f"response_{os.getpid()}.wav"
                        text_to_speech(Config.TTS_MODEL, get_tts_api_key(), response, audio_response_path)
                        
                        twilio_audio_path = audio_response_path.replace(".wav", "_twilio.wav")
                        subprocess.run([
                            "ffmpeg", "-i", audio_response_path,
                            "-ar", "8000", "-ac", "1", "-codec:a", "pcm_mulaw", twilio_audio_path
                        ], check=True)
                        
                        retries = 5
                        while retries > 0 and not os.path.exists(twilio_audio_path):
                            time.sleep(1)
                            retries -= 1
                        
                        if os.path.exists(twilio_audio_path):
                            logging.info(f"Generated speech file for Twilio: {twilio_audio_path}")
                            with open(twilio_audio_path, "rb") as audio_file:
                                encoded_audio = base64.b64encode(audio_file.read()).decode('utf-8')
                                await websocket.send_json({"event": "media", "streamSid": data['streamSid'], "media": {"payload": encoded_audio}})
                        else:
                            logging.error("Failed to generate speech file for Twilio.")
                elif data['event'] == 'stop':
                    call_active = False  # Caller hung up
            except WebSocketDisconnect:
                logging.info("Client disconnected. Ending call session.")
                call_active = False
                break
    
    await receive_from_twilio()

# Start FastAPI in a separate thread

def start_fastapi():
    try:
        uvicorn.run(fastapi_app, host="0.0.0.0", port=5050)
    except Exception as e:
        st.warning("FastAPI server is already running.")

if "fastapi_thread" not in st.session_state:
    thread = Thread(target=start_fastapi, daemon=True)
    thread.start()
    st.session_state["fastapi_thread"] = thread

st.success("Server is running. Accepting WebSocket connections!")
