import os
import json
import asyncio
import streamlit as st
import websockets
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import Response
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect
from twilio.rest import Client
from voice_assistant.response_generation import generate_response
from voice_assistant.transcription import transcribe_audio
from voice_assistant.text_to_speech import text_to_speech
from voice_assistant.api_key_manager import get_response_api_key, get_transcription_api_key
from voice_assistant.config import Config
from voice_assistant.audio import record_audio
from threading import Thread
import uvicorn
from ngrok_tunnel import setup_ngrok_tunnel
import logging

# FastAPI instance
fastapi_app = FastAPI()

st.title("AI Voice Assistant with Twilio")

# Initialize chat history in Streamlit UI
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []


# Sidebar for response length control
response_length = st.sidebar.slider("Response Length", min_value=1, max_value=5, value=1)  # Controls response verbosity

# Ensure chat history is initialized
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# Global variable for chat history in FastAPI
global_chat_history = []

# System prompt input
system_prompt = st.text_area("System Prompt", "You are Verbi, an AI assistant. Engage in a helpful and engaging conversation with the user.")

# Display chat history
st.markdown("### Chat History")
if "chat_history" in st.session_state:
    for message in st.session_state.chat_history:
        role_prefix = "**You:**" if message["role"] == "user" else "**Verbi:**"
        st.write(f"{role_prefix} {message['content']}")
else:
    st.info("No chat history yet. Start a conversation!")
    
# Copy the global chat history into Streamlit's session state
st.session_state.chat_history = global_chat_history

# Twilio credentials
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
    connect = Connect()
    connect.stream(url=f'wss://{request.url.hostname}/media-stream')
    response.append(connect)
    return Response(content=str(response), media_type="application/xml")

@fastapi_app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    await websocket.accept()
    stream_sid = None

    global_chat_history = []  # Define a global variable for chat history

    async def receive_from_twilio():
        nonlocal stream_sid
        try:
            while True:
                message = await websocket.receive_text()
                data = json.loads(message)

                if data["event"] == "start":
                    stream_sid = data["start"]["streamSid"]
                    await send_ai_intro()
                elif data["event"] == "media":
                    recording_dir = "recordings"
                    os.makedirs(recording_dir, exist_ok=True)
                    recorded_file = record_audio(os.path.join(recording_dir, f"recorded_audio_{os.getpid()}.mp3"))
                    transcribed_text = transcribe_audio(Config.TRANSCRIPTION_MODEL, get_transcription_api_key(), recorded_file)

                    if not transcribed_text:
                        continue

                    global_chat_history.append({"role": "user", "content": transcribed_text})

                    response = generate_response(
                        model=Config.RESPONSE_MODEL,
                        api_key=get_response_api_key(),
                        chat_history=[{"role": "system", "content": system_prompt},
                                    {"role": "user", "content": transcribed_text}]
                    )
                    response = " ".join(response.split()[:response_length * 10])

                    global_chat_history.append({"role": "assistant", "content": response})

                    st.session_state.chat_history = list(global_chat_history)
                    await text_to_speech(response, websocket, stream_sid)
                    st.rerun()
                elif data["event"] == "stop":
                    logging.info("User ended the call.")
                    await websocket.close()
                    break
        except WebSocketDisconnect:
            logging.info("User disconnected.")

    async def send_ai_intro():
        if not stream_sid:
            return
        
        intro_message = "Hello! I am Verbi, your AI assistant. How can I help you today?"
        await text_to_speech(intro_message, websocket, stream_sid)
    
    await receive_from_twilio()

def start_fastapi():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    uvicorn.run(fastapi_app, host="0.0.0.0", port=5050)

if "fastapi_thread" not in st.session_state or not st.session_state["fastapi_thread"].is_alive():
    thread = Thread(target=start_fastapi, daemon=True)
    thread.start()
    st.session_state["fastapi_thread"] = thread

st.success("Server is running. Accepting WebSocket connections!")
