# AI_logic/logic.py
# ==============================================================================
# AI "SPECIALIST" MICROSERVICE (UPGRADED WITH FUNCTION CALLING)
# This application can now use external tools to get real-time information.
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
from datetime import datetime, timedelta

# --- Step 2: Flask App Initialization & Load Environment Variables ---
app = Flask(__name__)
load_dotenv()
print("Flask app initialized and environment variables loaded.")

# --- Step 3: Global Constants & Initializations ---
CHAT_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_log.json")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")
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
    """Loads business configuration and services from a given Google Sheet ID."""
    business_data = {'services': {}, 'config': {}, 'bookingIntegration': {}}
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets.readonly']
        gac_json_str = os.getenv("GSPREAD_SERVICE_ACCOUNT_JSON")
        
        if gac_json_str:
            gac_json_dict = json.loads(gac_json_str)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(gac_json_dict, scope)
        else:
            creds_file_name = 'ananta-systems-ai-fc3b926f61b1.json'
            creds_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), creds_file_name)
            creds = ServiceAccountCredentials.from_json_keyfile_name(creds_file_path, scope)
        
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(spreadsheet_id)

        # Load Services
        services_sheet = spreadsheet.worksheet('Services')
        services_records = services_sheet.get_all_records()
        for row in services_records:
            service_name = str(row.get('Service', '')).strip().lower()
            if service_name:
                business_data['services'][service_name] = {
                    'price': str(row.get('Price', '')).strip(),
                    'duration': str(row.get('Duration', '')).strip()
                }

        # Load Config
        config_sheet = spreadsheet.worksheet('Config')
        config_records = config_sheet.get_all_records()
        for row in config_records:
            key = str(row.get('Key', '')).strip()
            value = str(row.get('Value', '')).strip()
            if key:
                if key == 'booking_provider_api_key': # Load booking API key securely
                    business_data['bookingIntegration']['apiKey'] = value
                else:
                    business_data['config'][key] = value

        print(f"Successfully loaded data for sheet {spreadsheet_id}")
        return business_data
    except Exception as e:
        print(f"\n--- ERROR loading Google Sheet data for sheet ID {spreadsheet_id}: {e} ---")
        return None

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

# --- NEW: The function that will actually get data from the booking service ---
def get_setmore_availability(service_name: str, date: str, client_api_key: str):
    """
    Makes a REAL API call to Setmore to get available time slots.
    NOTE: This is a SIMULATED function. You will need to replace the logic
    inside with actual API calls based on Setmore's documentation.
    """
    print(f"--- SIMULATING: Checking Setmore availability for '{service_name}' on {date} ---")
    
    # In a real application, you would make an authenticated API call here.
    # For now, we'll return a hardcoded list for testing purposes.
    if "haircut" in service_name.lower():
        return json.dumps({
            "available_times": ["10:00 AM", "11:30 AM", "2:00 PM", "3:30 PM"]
        })
    else:
        return json.dumps({
            "available_times": ["9:00 AM", "4:00 PM"]
        })

# --- The Main AI Logic Function (Heavily Upgraded) ---
def get_chatbot_response(user_id, user_prompt, business_data):
    """Gets a response from OpenAI, now with the ability to use tools."""
    global conversation_histories
    if user_id not in conversation_histories:
        conversation_histories[user_id] = []

    # Dynamically build the system prompt
    config = business_data.get('config', {})
    bot_personality = config.get('bot_personality', 'You are a helpful AI assistant for a business.')
    special_instructions = config.get('special_instructions', '')
    service_info_for_prompt = format_services_for_prompt(business_data.get('services', {}))
    
    # Get today's date to provide context to the AI
    today = datetime.now().strftime('%Y-%m-%d')
    system_prompt = (
        f"{bot_personality}\n\n"
        f"Today's date is {today}.\n\n"
        f"Your goal is to answer customer questions or assist with booking based on the tools and information provided.\n\n"
        f"--- Business Information ---\n"
        f"Services Offered:\n{service_info_for_prompt}\n"
        f"\n--- Instructions ---\n"
        f"1. If the user wants to book an appointment or check availability, use the provided tools.\n"
        f"2. For all other questions, answer using only the 'Business Information' provided.\n"
        f"3. Do not make up information. If you cannot answer, say so politely.\n"
        f"4. SPECIAL INSTRUCTION FROM THE BUSINESS OWNER: {special_instructions}\n"
    )

    # Define the "toolbox" for the AI
    tools = [
        {
            "type": "function",
            "function": {
                "name": "check_availability",
                "description": "Use this function to check for available appointment time slots for a specific service on a given date.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "service_name": {"type": "string", "description": "The name of the service the user is asking about, e.g., 'mens haircut', 'consultation'."},
                        "date": {"type": "string", "description": "The desired date for the appointment, in YYYY-MM-DD format."}
                    },
                    "required": ["service_name", "date"]
                }
            }
        }
    ]

    # Append the user's new message to the history
    history = conversation_histories[user_id]
    history.append({"role": "user", "content": user_prompt})

    try:
        # FIRST AI CALL: Check if a tool needs to be used
        print("[AI] First call to OpenAI to check for tool usage.")
        response = OPENAI_CLIENT.chat.completions.create(
            model="gpt-4-turbo",
            messages=[{"role": "system", "content": system_prompt}] + history,
            tools=tools,
            tool_choice="auto"
        )
        response_message = response.choices[0].message
        tool_calls = response_message.tool_calls

        # If the AI wants to use a tool, execute it
        if tool_calls:
            print(f"[AI] Tool call detected: {tool_calls[0].function.name}")
            tool_call = tool_calls[0]
            function_name = tool_call.function.name
            
            if function_name == "check_availability":
                args = json.loads(tool_call.function.arguments)
                service_name = args.get("service_name")
                date = args.get("date")

                print(f"[TOOL] Executing 'check_availability' with args: {args}")
                client_api_key = business_data.get('bookingIntegration', {}).get('apiKey', 'DUMMY_API_KEY')
                function_response = get_setmore_availability(service_name, date, client_api_key)
                
                print(f"[TOOL] Function returned: {function_response}")

                # Append the AI's decision and the tool's result to the history
                history.append(response_message)
                history.append({"tool_call_id": tool_call.id, "role": "tool", "name": function_name, "content": function_response})

                # SECOND AI CALL: Formulate a final, human-friendly response
                print("[AI] Second call to OpenAI to formulate final response.")
                second_response = OPENAI_CLIENT.chat.completions.create(model="gpt-4-turbo", messages=history)
                final_response = second_response.choices[0].message.content
                
                history.append({"role": "assistant", "content": final_response})
                conversation_histories[user_id] = history[-10:] # Keep history concise
                return final_response

        # If no tool was called, proceed as normal
        print("[AI] No tool call needed. Generating a standard text response.")
        ai_response_content = response_message.content
        if ai_response_content:
            history.append({"role": "assistant", "content": ai_response_content})
            conversation_histories[user_id] = history[-10:]
            return ai_response_content.strip()
        else:
            return "How else can I help?"

    except Exception as e:
        print(f"Error during OpenAI call for user {user_id}: {e}")
        return "Sorry, I'm having trouble connecting to my brain right now. Please try again in a moment."

def send_instagram_message(recipient_id, message_text, page_token):
    """Sends a message back to the user on Instagram."""
    print(f"--- Attempting to send message to {recipient_id} ---")
    url = f"https://graph.facebook.com/v19.0/me/messages?access_token={page_token}"
    headers = {'Content-Type': 'application/json'}
    data = {"recipient": {"id": recipient_id}, "message": {"text": message_text}, "messaging_type": "RESPONSE"}
    
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        print(f"--- Successfully sent message to {recipient_id} ---")
    except requests.exceptions.RequestException as e:
        print(f"\n--- ERROR Sending Instagram Message to {recipient_id}: {e.response.text if e.response else e} ---")

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
    """Main entry point for processing messages."""
    request_key = request.headers.get('X-Internal-API-Key')
    if not request_key or request_key != INTERNAL_API_KEY:
        abort(401)

    data = request.get_json()
    user_id, message_text, sheet_id, page_access_token = data.get('user_id'), data.get('message_text'), data.get('sheet_id'), data.get('page_access_token')

    if not all([user_id, message_text, sheet_id, page_access_token]):
        return jsonify({"error": "Missing required data"}), 400

    print(f"--- Secure API call received for customer {user_id} using sheet {sheet_id} ---")
    
    business_data = load_business_data(sheet_id)
    if not business_data:
        return jsonify({"error": f"Failed to load data for sheet_id: {sheet_id}"}), 500

    bot_response = get_chatbot_response(user_id, message_text, business_data)

    send_instagram_message(user_id, bot_response, page_access_token)

    save_message({"user_id": user_id, "direction": "incoming", "text": message_text, "timestamp": time.time()})
    save_message({"user_id": user_id, "direction": "outgoing", "text": bot_response, "timestamp": time.time()})
    
    return jsonify({"status": "success", "reply_sent": bot_response}), 200

# --- Step 7: Main Execution ---
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    app.run(host='0.0.0.0', port=port, debug=True)
