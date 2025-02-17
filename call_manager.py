import os
from twilio.rest import Client
from dotenv import load_dotenv
import logging

# Load environment variables from the .env file
load_dotenv()

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

def start_call(ngrok_url, to_number):
    """
    Start a Twilio call and connect it to the WebSocket.
    """
    try:
        if not ngrok_url:
            raise ValueError("ngrok URL is not available!")

        # Twilio should first play an intro message, then connect WebSocket
        twiml = f"""
        <Response>
            <Say voice="Polly.Joanna">Hello! This is Verbi, your AI assistant. Please ask your question.</Say>
            <Pause length="3"/>
            <Connect>
                <Stream url="{ngrok_url}/twilio"/>
            </Connect>
        </Response>
        """

        logging.info(f"📞 Initiating call to {to_number} with Twilio WebSocket: {ngrok_url}/twilio")
        call = client.calls.create(
            twiml=twiml,
            to=to_number,
            from_=TWILIO_PHONE_NUMBER
        )

        return call.sid
    except Exception as e:
        logging.error(f"❌ Failed to start call: {e}")
        return None
