import os
import json
import asyncio
import base64
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
from voice_assistant.api_key_manager import get_response_api_key, get_transcription_api_key
from voice_assistant.config import Config
from voice_assistant.audio import record_audio
from threading import Thread
import uvicorn
from twilio.rest import Client
from ngrok_tunnel import setup_ngrok_tunnel
import logging

# FastAPI instance
fastapi_app = FastAPI()

# 🔹 Global chat history dictionary for FastAPI
conversation_history = {}

# 🔹 Ensure chat history is initialized in Streamlit
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# Streamlit UI
st.title("AI Voice Assistant with Twilio and AI Models")
st.sidebar.header("Upload a PDF to train the AI")
uploaded_file = st.sidebar.file_uploader("Choose a PDF file", type=["pdf"])

# Process PDF if uploaded
if uploaded_file:
    pdf_path = f"temp_{uploaded_file.name}"
    with open(pdf_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    retriever = process_pdf(pdf_path)
    st.session_state.embeddings_initialized = True
    st.session_state.retriever = retriever
    st.sidebar.success("PDF processed successfully!")

# 🔹 Display Updated Chat History
st.markdown("### Chat History")
for message in st.session_state.chat_history:
    if message["role"] == "user":
        st.markdown(f"**You:** {message['content']}")
    elif message["role"] == "assistant":
        st.markdown(f"**Verbi:** {message['content']}")

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
    response.say("Connected to Verbi. You can speak now.")
    connect = Connect()
    connect.stream(url=f'wss://{request.url.hostname}/media-stream')
    response.append(connect)
    return Response(content=str(response), media_type="application/xml")

async def send_audio_to_twilio(websocket, streamSid, audio_path):
    """Send raw audio in small chunks to Twilio."""
    chunk_size = 4000
    
    if not os.path.exists(audio_path) or os.stat(audio_path).st_size == 0:
        logging.error(f"❌ Twilio-compatible audio file {audio_path} is missing or empty.")
        return

    with open(audio_path, "rb") as audio_file:
        while chunk := audio_file.read(chunk_size):
            await websocket.send_json({
                "event": "media",
                "streamSid": streamSid,
                "media": {"payload": base64.b64encode(chunk).decode('utf-8')}
            })
            await asyncio.sleep(0.1)

    logging.info("✅ Audio successfully sent to Twilio.")

@fastapi_app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    """
    Handles Twilio's media stream WebSocket connection.
    Uses the processed PDF as context when generating responses.
    """
    await websocket.accept()
    call_active = True  

    async def receive_from_twilio():
        nonlocal call_active
        while call_active:
            try:
                message = await websocket.receive_text()
                data = json.loads(message)

                if data["event"] == "media":
                    streamSid = data.get("streamSid", None)
                    if not streamSid:
                        logging.error("❌ Missing streamSid in Twilio media event!")
                        continue

                    # Initialize conversation history for this streamSid if not exists
                    if streamSid not in conversation_history:
                        conversation_history[streamSid] = []

                    recorded_path = record_audio(f"recorded_audio_{os.getpid()}.mp3")

                    if not recorded_path or os.stat(recorded_path).st_size == 0:
                        logging.error("❌ Recording failed or generated an empty file.")
                        continue

                    transcribed_text = transcribe_audio(Config.TRANSCRIPTION_MODEL, get_transcription_api_key(), recorded_path)

                    if not transcribed_text:
                        logging.error("❌ Transcription failed or returned empty text.")
                        continue

                    # 🔹 Append user message to FastAPI chat history
                    conversation_history[streamSid].append({"role": "user", "content": transcribed_text})

                    # Retrieve retriever from session_state (if PDF was uploaded)
                    retriever = st.session_state.get("retriever", None)

                    response = generate_response(
                        model=Config.RESPONSE_MODEL,
                        api_key=get_response_api_key(),
                        chat_history=[{"role": "user", "content": transcribed_text}],
                        retriever=retriever
                    )
                    
                    # 🔹 Extract response up to the second full stop
                    response = response.split(".")[1]

                    # 🔹 Append AI response to FastAPI chat history
                    conversation_history[streamSid].append({"role": "assistant", "content": response})

                    # Sync FastAPI history with Streamlit session state
                    st.session_state.chat_history = conversation_history[streamSid]

                    # 🔹 Trigger UI update
                    st.rerun()

                    await text_to_speech(response, websocket, streamSid)

                elif data["event"] == "stop":
                    logging.info("🚪 Call ended by user. Closing connection.")
                    call_active = False
                    await websocket.close()
                    break

            except WebSocketDisconnect:
                logging.info("🚪 Client disconnected, ending session.")
                break

    await receive_from_twilio()
    logging.info("🔚 WebSocket session closed.")

def start_fastapi():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    uvicorn.run(fastapi_app, host="0.0.0.0", port=5050)

if "fastapi_thread" not in st.session_state or not st.session_state["fastapi_thread"].is_alive():
    thread = Thread(target=start_fastapi, daemon=True)
    thread.start()
    st.session_state["fastapi_thread"] = thread

st.success("Server is running. Accepting WebSocket connections!")
