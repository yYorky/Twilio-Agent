import os
import json
import asyncio
import streamlit as st
import websockets
import re
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import Response
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect
from voice_assistant.response_generation import generate_response
from voice_assistant.transcription import transcribe_audio
from voice_assistant.text_to_speech import text_to_speech
from voice_assistant.api_key_manager import get_response_api_key, get_transcription_api_key
from voice_assistant.config import Config
from voice_assistant.audio import record_audio
from threading import Thread
import uvicorn
from ngrok_tunnel import setup_ngrok_tunnel
from pdf_processing import process_pdf
from twilio.rest import Client
import logging

# FastAPI instance
fastapi_app = FastAPI()

# 🔹 Global conversation state
conversation_history = {}
response_tracker = {}
chat_history_global = {}


# 🔹 Ensure chat history is initialized in Streamlit
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# Streamlit UI
st.title("AI Voice Assistant with Twilio and AI Models")
st.sidebar.header("Upload a PDF to train the AI")
uploaded_file = st.sidebar.file_uploader("Choose a PDF file", type=["pdf"])

# Global variable to store retriever
retriever_global = None  

# Process PDF if uploaded
if uploaded_file:
    pdf_path = f"temp_{uploaded_file.name}"
    with open(pdf_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    retriever_global = process_pdf(pdf_path)  # Store retriever globally
    st.session_state.retriever = retriever_global  # Keep for Streamlit UI

    st.session_state.embeddings_initialized = True
    st.sidebar.success("PDF processed successfully!")


# 🔹 Display Updated Chat History
st.markdown("### Chat History")
for message in chat_history_global.get("latest", []):  # Fetch latest conversation
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
    """Handles incoming call and immediately starts AI-generated greeting."""
    response = VoiceResponse()
    
    # Connect to Twilio's WebSocket media stream
    connect = Connect()
    connect.stream(url=f'wss://{request.url.hostname}/media-stream')
    response.append(connect)
    
    return Response(content=str(response), media_type="application/xml")

@fastapi_app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    """
    Handles Twilio's media stream WebSocket connection.
    Implements:
    1. AI immediately starts the conversation with a greeting **after** Twilio sends `streamSid`.
    2. User can interrupt AI mid-speech.
    3. Call ends if the user says 'Goodbye'.
    """
    await websocket.accept()
    call_active = True
    latest_media_timestamp = 0
    last_assistant_item = None
    stream_sid = None

    async def receive_from_twilio():
        """Handles incoming media and speech detection."""
        nonlocal latest_media_timestamp, last_assistant_item, stream_sid, call_active

        while call_active:
            try:
                message = await websocket.receive_text()
                data = json.loads(message)

                if data["event"] == "start":
                    stream_sid = data["start"]["streamSid"]
                    logging.info(f"✅ Received streamSid: {stream_sid}")

                    # 🔹 Now that we have the streamSid, send AI intro
                    await send_ai_intro()

                elif data["event"] == "media":
                    if not stream_sid:
                        logging.error("❌ Missing streamSid in Twilio media event!")
                        continue

                    latest_media_timestamp = int(data["media"]["timestamp"])

                    # Record & Transcribe Audio
                    recorded_path = record_audio(f"recorded_audio_{os.getpid()}.mp3")
                    transcribed_text = transcribe_audio(Config.TRANSCRIPTION_MODEL, get_transcription_api_key(), recorded_path)

                    if not transcribed_text:
                        logging.error("❌ Transcription failed or returned empty text.")
                        continue

                    chat_history_global.setdefault(stream_sid, []).append({"role": "user", "content": transcribed_text})

                    # 🔹 Check if user wants to end the call
                    if any(phrase in transcribed_text.lower() for phrase in ["goodbye", "bye", "exit", "end call"]):
                        logging.info("👋 User requested to end the call.")
                        
                        # Wait for TTS to complete before ending the call
                        if tts_processing:
                            logging.info("⏳ Waiting for TTS to finish before ending call...")
                            await tts_processing  # Ensure the TTS task is awaited fully

                        await end_call()
                        break

                    # 🔹 Interrupt AI if it's speaking
                    if last_assistant_item:
                        logging.info("🔴 Interrupting AI response due to user speech.")
                        await truncate_ai_response()

                    # 🔹 Retrieve relevant context from the uploaded PDF
                    retrieved_docs = retriever_global.invoke(transcribed_text) if retriever_global else []

                    context = "\n".join([doc.page_content for doc in retrieved_docs])

                    # 🔹 System prompt to enforce PDF-based responses
                    system_prompt = """You are an Verbi, an AI assistant providing answers based on a document uploaded by the user.
                    Only use the document's content to answer questions and do not generate information outside the provided context.
                    If the answer is not in the document, reply with 'I don't know'."""

                    # 🔹 Construct LLM prompt
                    prompt = f"{system_prompt}\n\nDocument Context:\n{context}\n\nUser's Question: {transcribed_text}"

                    # 🔹 Generate AI response using RAG
                    response = generate_response(
                        model=Config.RESPONSE_MODEL,
                        api_key=get_response_api_key(),
                        chat_history=[{"role": "system", "content": prompt}]
                    )

                    

                    # Extract first two sentences robustly
                    sentences = re.split(r'(?<=[.!?])\s+', response)  # Split at sentence boundaries
                    response = " ".join(sentences[:2]).strip()  # Keep only first two sentences


                    # Append AI response to chat history
                    if stream_sid not in conversation_history:
                        conversation_history[stream_sid] = []  # Initialize empty list for new calls

                    conversation_history[stream_sid].append({"role": "assistant", "content": response})

                    
                    if "chat_history" not in st.session_state:
                        st.session_state.chat_history = []

                    st.session_state.chat_history.append({"role": "assistant", "content": response})

                    st.rerun()  # Ensures Streamlit UI updates

                    await text_to_speech(response, websocket, stream_sid)

                elif data["event"] == "input_audio_buffer.speech_started":
                    logging.info("🎤 Detected user speaking while AI is responding. Interrupting response.")
                    
                    # Stop TTS immediately
                    await websocket.send_json({"type": "tts.stop"})
                    
                    # Truncate AI response
                    await truncate_ai_response()

                    logging.info("✅ AI speech stopped due to user interruption.")


                elif data["event"] == "stop":
                    logging.info("🚪 Call ended by user. Closing connection.")

                    # Check if WebSocket is still open before closing
                    if websocket.client_state == websockets.protocol.State.OPEN:
                        await websocket.close()
                    
                    break


            except WebSocketDisconnect:
                logging.info("🚪 Client disconnected, ending session.")
                break

    async def send_ai_intro():
        """Generates and sends AI introduction message after receiving `streamSid`."""
        if not stream_sid:
            logging.error("❌ streamSid is missing. Cannot send AI intro.")
            return

        system_prompt = """You are Verbi, an AI voice assistant that provides responses based on a document uploaded by the user.
        Your goal is to assist the user by answering questions using only the information in the document."""

        # intro_message = """Hello! I am Verbi, your AI assistant. My role is to help you by answering questions based on the document you've uploaded.
        # Please introduce yourself so I can assist you better."""
        
        intro_message = """You are Verbi, an AI voice assistant that provides responses based on a document uploaded by the user."""


        # If a PDF has been uploaded, add more context
        if "retriever" in st.session_state:
            intro_message += " Feel free to ask me anything related to the document."

        # 🔹 Generate AI-generated greeting (ensuring it follows the system prompt)
        greeting = generate_response(
            model=Config.RESPONSE_MODEL,
            api_key=get_response_api_key(),
            chat_history=[{"role": "system", "content": system_prompt}, {"role": "user", "content": intro_message}]
        )

        # Extract first two sentences robustly
        sentences = re.split(r'(?<=[.!?])\s+', greeting)  # Split at sentence boundaries
        greeting = " ".join(sentences[:2]).strip()  # Keep only first two sentences
        
        await text_to_speech(greeting, websocket, stream_sid)
        logging.info("✅ AI intro sent.")

    async def truncate_ai_response():
        nonlocal last_assistant_item
        if last_assistant_item:
            truncate_event = {
                "type": "conversation.item.truncate",
                "item_id": last_assistant_item,
                "content_index": 0,
                "audio_end_ms": latest_media_timestamp
            }
            await websocket.send_json(truncate_event)

            # Stop the AI from continuing to talk
            await websocket.send_json({"type": "tts.stop"})
            
            last_assistant_item = None
            logging.info("✅ AI response truncated and TTS stopped.")


    async def end_call():
        """Ends the call when the user says 'Goodbye'."""
        logging.info("📞 Sending hangup event to Twilio.")

        # Ensure WebSocket is still active before attempting to close
        if not websocket.client_state == websockets.protocol.State.OPEN:
            logging.warning("❗ WebSocket is already closed. Skipping hangup.")
            return

        await websocket.send_json({
            "event": "hangup",
            "streamSid": stream_sid
        })

        await websocket.close()
        logging.info("🔚 Call has ended.")

    # 🔹 Start receiving from Twilio
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
