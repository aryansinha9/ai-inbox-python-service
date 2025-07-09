# AI_logic/logic.py
# ==============================================================================
# AI "SPECIALIST" MICROSERVICE
# This application's sole purpose is to receive a secure API call,
# process a message using OpenAI and Google Sheets, and send a reply.
# ==============================================================================

# --- Step 1: Imports ---
import openai
import gspread
import time
import os
import sys
import json
import requests
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, request, abort, jsonify

# --- Step 2: Flask App Initialization & Load Environment Variables ---
app = Flask(__name__)
load_dotenv()
print("Flask app initialized and environment variables loaded.")

# --- Step 3: Global Constants & Initializations ---

# Path for the chat log JSON file
CHAT_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_log.json")

# --- NEW ---: Secret key to secure our internal API
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")

# This is a cache for conversation histories, not a global state for business data
conversation_histories = {}

# --- Step 4: Helper Functions ---

def save_message(entry):
    """Saves a single message entry to the chat log JSON file."""
    try:
        data = []
        if os.path.exists(CHAT_LOG_PATH):
            with open(CHAT_LOG_PATH, "r") as f:
                try:
                    data = json.load(f)
                    if not isinstance(data, list): data = []
                except json.JSONDecodeError:
                    data = []
        data.append(entry)
        with open(CHAT_LOG_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"ERROR saving message log: {e}")

def load_business_data(spreadsheet_id):
    """
    Loads business configuration and services from a given Google Sheet ID.
    Assumes two tabs in the sheet: 'Services' and 'Config'.
    """
    business_data = {'services': {}, 'config': {}}
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets.readonly']
        # IMPORTANT: Ensure your Google service account JSON key file is in the same directory
        creds_file_name = 'ananta-systems-ai-fc3b926f61b1.json' 
        creds_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), creds_file_name)
        creds = ServiceAccountCredentials.from_json_keyfile_name(creds_file_path, scope)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(spreadsheet_id)

        # 1. Load Services from the 'Services' tab
        services_sheet = spreadsheet.worksheet('Services')
        services_records = services_sheet.get_all_records()
        for row in services_records:
            service_name = str(row.get('Service', '')).strip().lower()
            if service_name:
                business_data['services'][service_name] = {
                    'price': str(row.get('Price', '')).strip(),
                    'duration': str(row.get('Duration', '')).strip()
                }

        # 2. Load Config from the 'Config' tab
        config_sheet = spreadsheet.worksheet('Config')
        config_records = config_sheet.get_all_records()
        for row in config_records:
            key = str(row.get('Key', '')).strip()
            value = str(row.get('Value', '')).strip()
            if key:
                business_data['config'][key] = value

        print(f"Successfully loaded data for sheet {spreadsheet_id}: {len(business_data['services'])} services, {len(business_data['config'])} config items.")
        return business_data

    except Exception as e:
        print(f"\n--- ERROR loading Google Sheet data for sheet ID {spreadsheet_id}: {e} ---")
        return None # Return None on failure

def initialize_openai():
    """Initializes and returns the OpenAI client."""
    try:
        client = openai.OpenAI()
        print("OpenAI client initialized successfully.")
        return client
    except Exception as e:
        print(f"\n--- FATAL ERROR initializing OpenAI client: {e} ---")
        sys.exit(1)

def format_services_for_prompt(service_dict):
    """Formats the service dictionary into a string for the AI prompt."""
    if not service_dict: return "No specific service details are loaded."
    lines = [f"- {name.title()}: Price is {details['price']}, Takes about {details['duration']}" for name, details in sorted(service_dict.items())]
    return "\n".join(lines)

# AI_logic/logic.py

def get_chatbot_response(user_id, user_prompt, business_data):
    """
    --- UPGRADED ---
    Gets a response from OpenAI based on the DYNAMIC business data.
    """
    global conversation_histories
    if user_id not in conversation_histories:
        conversation_histories[user_id] = []

    # --- DYNAMICALLY PULL CONFIGURATION ---
    config = business_data.get('config', {})
    
    # Get general info with defaults
    booking_link = config.get('booking_link', 'the booking link provided by the business')
    contact_info = config.get('contact_info', 'the business directly')
    handoff_code = config.get('handoff_code', "I'll let a human representative handle that.")

    # --- NEW: Get custom personality and instructions ---
    bot_personality = config.get(
        'bot_personality', 
        'You are a helpful AI assistant for a business.' # The default personality
    )
    special_instructions = config.get('special_instructions', '') # Default is no special instructions
    upsell_prompt = config.get('upsell_prompt', '') # Default is no upsell

    service_info_for_prompt = format_services_for_prompt(business_data.get('services', {}))

    # --- THE NEW, DYNAMICALLY BUILT SYSTEM PROMPT ---
    system_prompt = (
        f"{bot_personality}\n\n" # Use the client's custom personality
        f"Your goal is to answer customer questions based ONLY on the information provided below.\n\n"
        f"--- Business Information ---\n"
        f"Booking Link: {booking_link}\n"
        f"Primary Contact: {contact_info}\n"
        f"Services Offered:\n{service_info_for_prompt}\n"
        f"\n--- Instructions ---\n"
        f"1. Answer questions using ONLY the 'Business Information' provided.\n"
        f"2. **CRITICAL RULE:** If you cannot answer from the info provided (e.g., asking for appointment times), you MUST reply with ONLY the phrase: {handoff_code}\n"
        f"3. Do not make up information.\n"
        # --- ADD THE CUSTOM INSTRUCTIONS ---
        f"4. SPECIAL INSTRUCTION FROM THE BUSINESS OWNER: {special_instructions}\n"
        f"5. UPSELL INSTRUCTION: {upsell_prompt}"
    )

    history = conversation_histories[user_id]
    history.append({"role": "user", "content": user_prompt})

    try:
        # The rest of the function remains exactly the same...
        response = OPENAI_CLIENT.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "system", "content": system_prompt}] + history,
            max_tokens=150,
            temperature=0.7 # Maybe slightly more creative for different personalities
        )
        ai_response_content = response.choices[0].message.content.strip()
        history.append({"role": "assistant", "content": ai_response_content})
        conversation_histories[user_id] = history[-10:]
        return ai_response_content
    except Exception as e:
        print(f"Error during OpenAI call for user {user_id}: {e}")
        return handoff_code

# --- MODIFIED to accept a client-specific token ---
def send_instagram_message(recipient_id, message_text, page_token):
    """Sends a message back to the user on Instagram using the provided page_token."""
    print(f"--- Attempting to send message to {recipient_id} using a client-specific token ---")
    
    # Use the token passed in from the Node.js server
    url = f"https://graph.facebook.com/v19.0/me/messages?access_token={page_token}"
    headers = {'Content-Type': 'application/json'}
    data = {"recipient": {"id": recipient_id}, "message": {"text": message_text}, "messaging_type": "RESPONSE"}
    
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        print(f"--- Successfully sent message to {recipient_id} (Status: {response.status_code}) ---")
    except requests.exceptions.RequestException as e:
        error_details = e.response.text if e.response else str(e)
        print(f"\n--- ERROR Sending Instagram Message to {recipient_id}: {error_details} ---")


# --- Step 5: Run Startup Initialization ---
print("--- Initializing Chatbot Services ---")
if not INTERNAL_API_KEY:
    print("FATAL ERROR: The INTERNAL_API_KEY environment variable is missing.")
    sys.exit(1)
OPENAI_CLIENT = initialize_openai()
print("--- Initialization Complete. AI Microservice is Ready and Waiting for API Calls. ---")


# --- Step 6: The Upgraded Internal API Route ---
@app.route('/api/process-message', methods=['POST'])
def process_message_api():
    """
    This is the main entry point. It expects a secure call from our Node.js "CEO" server
    and receives all necessary data dynamically.
    """
    # 1. Check for the secret internal API key
    request_key = request.headers.get('X-Internal-API-Key')
    if not request_key or request_key != INTERNAL_API_KEY:
        print("ERROR: Unauthorized API call attempt.")
        abort(401)

    # 2. Get the dynamic data from the request body
    data = request.get_json()
    user_id = data.get('user_id') # The customer's ID
    message_text = data.get('message_text')
    sheet_id = data.get('sheet_id') # The client's specific Google Sheet
    page_access_token = data.get('page_access_token') # The client's specific Page Token

    if not all([user_id, message_text, sheet_id, page_access_token]):
        return jsonify({"error": "Missing required data: user_id, message_text, sheet_id, page_access_token"}), 400

    print(f"--- Secure API call received for customer {user_id} using sheet {sheet_id} ---")
    
    # 3. Load the specific business's data from Google Sheets
    business_data = load_business_data(sheet_id)
    if not business_data:
        error_msg = f"Failed to load data for sheet_id: {sheet_id}"
        print(error_msg)
        return jsonify({"error": error_msg}), 500

    # 4. Get the AI's response using the loaded data
    bot_response = get_chatbot_response(user_id, message_text, business_data)

    # 5. Send the response back to the user on Instagram using the client's token
    send_instagram_message(user_id, bot_response, page_access_token)

    # 6. Log the interaction
    save_message({"user_id": user_id, "direction": "incoming", "text": message_text, "timestamp": time.time()})
    save_message({"user_id": user_id, "direction": "outgoing", "text": bot_response, "timestamp": time.time()})
    
    # 7. Return a success message to the calling Node.js server
    return jsonify({"status": "success", "reply_sent": bot_response}), 200

# --- Step 7: Main Execution ---
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    # debug=False is recommended for production
    app.run(host='0.0.0.0', port=port, debug=True)