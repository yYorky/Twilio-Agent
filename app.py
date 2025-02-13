import streamlit as st
import openai  # Using Groq LLM via OpenAI-compatible API
import os
import json
import requests
import time
import dotenv
from twilio.rest import Client
from fastapi import FastAPI
from starlette.websockets import WebSocket
import uvicorn
from threading import Thread
from pyngrok import ngrok
import psutil

# Load environment variables
dotenv.load_dotenv()
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
NGROK_AUTH_TOKEN = os.getenv("NGROK_AUTH_TOKEN")

# Initialize Twilio Client
client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# FastAPI for WebSocket Server
app = FastAPI()

@app.websocket("/twilio")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        response = generate_response(data)  # AI-generated response
        audio_data = convert_text_to_speech(response)
        await websocket.send_bytes(audio_data)

# Function to check if Uvicorn is already running
def is_uvicorn_running():
    for process in psutil.process_iter(attrs=['pid', 'name']):
        if process.info['name'] and "uvicorn" in process.info['name']:
            return True
    return False

# Function to start FastAPI server
def start_uvicorn_server():
    if not is_uvicorn_running():
        def run():
            uvicorn.run(app, host="0.0.0.0", port=8000)
        server_thread = Thread(target=run, daemon=True)
        server_thread.start()
    else:
        print("Uvicorn server is already running.")

# Function to start a new ngrok tunnel
def start_ngrok_tunnel():
    ngrok.set_auth_token(NGROK_AUTH_TOKEN)
    
    # Close existing tunnels before starting a new one
    for tunnel in ngrok.get_tunnels():
        ngrok.disconnect(tunnel.public_url)
    
    public_url = ngrok.connect(8000, "http").public_url
    twilio_websocket_url = public_url.replace("http://", "wss://") + "/twilio"
    print(f"Twilio WebSocket URL: {twilio_websocket_url}")
    return twilio_websocket_url

# Start Uvicorn and ngrok only once
start_uvicorn_server()
twilio_websocket_url = start_ngrok_tunnel()

# Function to get AI-generated response
def generate_response(user_input):
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
    payload = {
        "model": "llama3-8b-8192", 
        "messages": [
            {"role": "system", "content": "You are a helpful AI assistant for phone calls. Your main objective is to assist the user in scheduling a meeting appointment by speaking with them clearly and efficiently."},
            {"role": "user", "content": user_input}
        ]
    }
    response = requests.post("https://api.groq.com/chat/completions", headers=headers, json=payload)
    return response.json()["choices"][0]["message"]["content"]

# Function to convert AI-generated text to speech
def convert_text_to_speech(text):
    url = "https://api.cartesia.ai/tts/websocket"
    headers = {"Authorization": f"Bearer {CARTESIA_API_KEY}"}
    payload = {"text": text, "voice": "sonic-english", "format": "pcm"}
    response = requests.post(url, headers=headers, json=payload)
    return response.content

# Function to initiate Twilio call
def start_call(to_number, twilio_websocket_url):
    call = client.calls.create(
        twiml=f'<Response><Connect><Stream url="{twilio_websocket_url}"/></Connect></Response>',
        to=to_number,
        from_=TWILIO_PHONE_NUMBER
    )
    return call.sid

# Streamlit UI
st.title("AI-Powered Phone Call Agent")
to_number = st.text_input("Enter recipient's phone number:")
message = st.text_area("Enter the initial message:")
if st.button("Start Call"):
    call_sid = start_call(to_number, twilio_websocket_url)
    st.success(f"Call initiated! Call SID: {call_sid}")
