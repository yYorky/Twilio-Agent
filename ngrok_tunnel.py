import json
import subprocess
import logging
import time

logging.basicConfig(level=logging.INFO)

def setup_ngrok_tunnel(port):
    """
    Start an ngrok tunnel for the given port and return the public URL.
    """
    try:
        logging.info(f"🔄 Starting ngrok tunnel on port {port}...")

        # Start ngrok process in background
        subprocess.Popen(["C:\\ngrok\\ngrok.exe", "http", str(port)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        # Wait for ngrok to start
        time.sleep(5)

        # Get ngrok public URL from API
        result = subprocess.run(["curl", "-s", "http://localhost:4040/api/tunnels"], capture_output=True, text=True)
        
        # Log the response for debugging
        logging.info(f"ngrok API Response: {result.stdout}")

        # Parse JSON response
        tunnels = json.loads(result.stdout)
        
        if "tunnels" in tunnels and len(tunnels["tunnels"]) > 0:
            ngrok_url = tunnels["tunnels"][0]["public_url"]
            logging.info(f"✅ ngrok tunnel established: {ngrok_url}")
            return ngrok_url
        else:
            logging.error("❌ ngrok tunnel setup failed. No public URL found.")
            return None

    except Exception as e:
        logging.error(f"❌ Error in setting up ngrok tunnel: {str(e)}")
        return None
