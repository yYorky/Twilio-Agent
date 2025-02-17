import streamlit as st
import asyncio
import logging
from pdf_processing import process_pdf
from call_manager import start_call
from twilio_ws import setup_twilio_websocket
from cartesia_ws import connect_to_tts_websocket, send_tts_message
from chat_handler import process_voice_query
from ngrok_tunnel import setup_ngrok_tunnel  # Auto-starts ngrok

# Set up logging
logging.basicConfig(level=logging.INFO)

st.set_page_config(page_title="Verbi Voice Assistant", layout="wide")

st.sidebar.title("Upload PDF for Verbi Assistant")
uploaded_file = st.sidebar.file_uploader("Upload a PDF", type="pdf")

if uploaded_file:
    with st.spinner("Processing document..."):
        with open("temp.pdf", "wb") as f:
            f.write(uploaded_file.getbuffer())
        retriever = process_pdf("temp.pdf")
        st.session_state.retriever = retriever
        st.success("Document is ready for conversation!")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

phone_number = st.text_input("Enter your phone number:")

def run_async(coro):
    """
    Runs an async function inside a new event loop.
    Prevents 'RuntimeError: There is no current event loop'.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

async def handle_twilio_call():
    """
    Initializes Twilio WebSocket, Cartesia TTS, and starts the call.
    """
    try:
        st.info("🔄 Initializing Verbi voice assistant...")

        # Step 1: Auto-start ngrok
        logging.info("[1/4] Setting up ngrok tunnel...")
        ngrok_url = setup_ngrok_tunnel(8001)
        if not ngrok_url:
            st.error("❌ ngrok failed to start. Check logs for details.")
            return
        logging.info(f"[1/4] ✅ ngrok tunnel established: {ngrok_url}")

        # Step 2: Start Twilio WebSocket Server
        logging.info("[2/4] Starting Twilio WebSocket Server...")
        tts_websocket = await connect_to_tts_websocket()
        await send_tts_message(tts_websocket, "Hello! This is Verbi. Your AI assistant is ready to chat.")
        twilio_server = await setup_twilio_websocket(process_voice_query, st.session_state.retriever, tts_websocket)
        logging.info("[2/4] ✅ Twilio WebSocket Server Started!")

        # Step 3: Initiate the Twilio call
        logging.info("[3/4] Initiating Twilio Call...")
        call_sid = start_call(ngrok_url, phone_number)

        if call_sid:
            st.success(f"✅ Call initiated successfully! Call SID: {call_sid}")
            logging.info(f"[3/4] ✅ Call initiated: {call_sid}")
        else:
            st.error("❌ Failed to start the call. Check Twilio API logs.")
            logging.error("[3/4] ❌ Twilio call failed!")

        await twilio_server.wait_closed()

    except Exception as e:
        st.error(f"❌ Error in initiating call: {str(e)}")
        logging.error(f"❌ Error in initiating call: {str(e)}")

if st.button("Call Verbi"):
    if not phone_number:
        st.error("❌ Please enter a valid phone number.")
    else:
        run_async(handle_twilio_call())  # Runs the async call setup
