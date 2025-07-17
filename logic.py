# AI_logic/logic.py
# ==============================================================================
# AI "SPECIALIST" MICROSERVICE (UPGRADED WITH FULL BOOKING FLOW)
# This version can both check for availability and create appointments.
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

# --- Step 2: Flask App Initialization & Globals ---
app = Flask(__name__)
load_dotenv()
print("Flask app initialized and environment variables loaded.")

CHAT_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_log.json")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")
conversation_histories = {}

# --- Step 3: Tool Functions (Simulated) ---

def get_setmore_availability(service_name: str, date: str, client_api_key: str):
    """
    SIMULATED: This function would make a real API call to a booking service
    like Setmore to get available time slots for a given service and date.
    """
    print(f"--- SIMULATING: Checking Setmore availability for '{service_name}' on {date} ---")
    
    # In a real application, you would replace this with an actual `requests.get()` call
    # to the booking service's API, using the client_api_key for authentication.
    
    if "haircut" in service_name.lower():
        # Return the data as a JSON string, as the AI model expects.
        return json.dumps({"available_times": ["10:00 AM", "11:30 AM", "2:00 PM", "3:30 PM"]})
    else:
        return json.dumps({"available_times": ["9:00 AM", "4:00 PM"]})

def create_setmore_appointment(service_name: str, date: str, time: str, customer_name: str, client_api_key: str):
    """
    SIMULATED: This function would make a real API call to a booking service
    like Setmore to CREATE an appointment.
    """
    print(f"--- SIMULATING: Creating Setmore appointment for '{customer_name}' ---")
    print(f"    Service: {service_name}, Date: {date}, Time: {time}")
    
    # In a real application, you would make a `requests.post()` call here.
    # We will simulate a successful booking for testing.
    return json.dumps({
        "success": True,
        "confirmation_id": "BK-12345XYZ",
        "message": f"Successfully booked {service_name} for {customer_name} on {date} at {time}."
    })

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
                except json.JSONDecodeError: data = []
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
            creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(gac_json_str), scope)
        else:
            creds_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ananta-systems-ai-fc3b926f61b1.json')
            creds = ServiceAccountCredentials.from_json_keyfile_name(creds_file_path, scope)
        
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(spreadsheet_id)

        # Load Services
        for row in spreadsheet.worksheet('Services').get_all_records():
            service_name = str(row.get('Service', '')).strip().lower()
            if service_name:
                business_data['services'][service_name] = {'price': str(row.get('Price', '')), 'duration': str(row.get('Duration', ''))}

        # Load Config, including the booking API key
        for row in spreadsheet.worksheet('Config').get_all_records():
            key, value = str(row.get('Key', '')), str(row.get('Value', ''))
            if key:
                if key == 'booking_provider_api_key':
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
    return "\n".join([f"- {name.title()}: Price is {details['price']}" for name, details in sorted(service_dict.items())])

# --- Step 5: Main AI Logic Function ---
def get_chatbot_response(user_id, user_prompt, business_data):
    """Gets a response from OpenAI, using tools for booking and availability checks."""
    global conversation_histories
    if user_id not in conversation_histories:
        conversation_histories[user_id] = []

    config = business_data.get('config', {})
    bot_personality = config.get('bot_personality', 'You are a helpful AI assistant.')
    service_info = format_services_for_prompt(business_data.get('services', {}))
    today = datetime.now().strftime('%Y-%m-%d')

    system_prompt = (
        f"{bot_personality}\n\nToday's date is {today}.\n\n"
        "--- Instructions ---\n"
        "1. Your primary goal is to help users book appointments. You MUST check for availability using the `check_availability` tool before you attempt to book using the `create_appointment` tool.\n"
        "2. You must collect all necessary information (service, date, time, customer name) before attempting to book.\n"
        "3. If the user asks a general question, answer using the business info provided below.\n\n"
        f"--- Business Information ---\n{service_info}\n"
    )
    
    tools = [
        {"type": "function", "function": {"name": "check_availability", "description": "Checks for available appointment slots.", "parameters": {"type": "object", "properties": {"service_name": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD"}}, "required": ["service_name", "date"]}}},
        {"type": "function", "function": {"name": "create_appointment", "description": "Books an appointment after availability is confirmed.", "parameters": {"type": "object", "properties": {"service_name": {"type": "string"}, "date": {"type": "string"}, "time": {"type": "string"}, "customer_name": {"type": "string"}}, "required": ["service_name", "date", "time", "customer_name"]}}}
    ]

    history = conversation_histories.get(user_id, [])
    history.append({"role": "user", "content": user_prompt})

    try:
        response = OPENAI_CLIENT.chat.completions.create(model="gpt-4-turbo", messages=[{"role": "system", "content": system_prompt}] + history, tools=tools, tool_choice="auto")
        response_message = response.choices[0].message
        tool_calls = response_message.tool_calls

        if tool_calls:
            history.append(response_message)
            available_functions = {"check_availability": get_setmore_availability, "create_appointment": create_setmore_appointment}
            
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_to_call = available_functions[function_name]
                args = json.loads(tool_call.function.arguments)
                
                print(f"[TOOL] Executing '{function_name}' with args: {args}")
                client_api_key = business_data.get('bookingIntegration', {}).get('apiKey', 'DUMMY_API_KEY')
                
                # Add the client_api_key to arguments for the actual function call
                args['client_api_key'] = client_api_key

                function_response = function_to_call(**args)
                history.append({"tool_call_id": tool_call.id, "role": "tool", "name": function_name, "content": function_response})

            print("[AI] Second call to OpenAI to formulate final response.")
            second_response = OPENAI_CLIENT.chat.completions.create(model="gpt-4-turbo", messages=history)
            final_response = second_response.choices[0].message.content
            history.append({"role": "assistant", "content": final_response})
            conversation_histories[user_id] = history[-10:]
            return final_response

        ai_response_content = response_message.content
        if ai_response_content:
            history.append({"role": "assistant", "content": ai_response_content})
            conversation_histories[user_id] = history[-10:]
            return ai_response_content.strip()
        else:
            return "How else can I help?"

    except Exception as e:
        print(f"Error during OpenAI call for user {user_id}: {e}")
        return "Sorry, I'm having trouble connecting right now. Please try again in a moment."

# --- Step 6: Instagram Messaging Function ---
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
        print(f"\n--- ERROR Sending Instagram Message: {e.response.text if e.response else e} ---")

# --- Step 7: Startup Initialization ---
print("--- Initializing Chatbot Services ---")
if not INTERNAL_API_KEY:
    print("FATAL ERROR: The INTERNAL_API_KEY environment variable is missing.")
    sys.exit(1)
OPENAI_CLIENT = initialize_openai()
print("--- Initialization Complete. AI Microservice is Ready and Waiting for API Calls. ---")

# --- Step 8: Flask Route ---
@app.route('/api/process-message', methods=['POST'])
def process_message_api():
    """Main entry point for processing messages."""
    if request.headers.get('X-Internal-API-Key') != INTERNAL_API_KEY:
        abort(401)

    data = request.get_json()
    user_id, msg, sheet_id, token = data.get('user_id'), data.get('message_text'), data.get('sheet_id'), data.get('page_access_token')

    if not all([user_id, msg, sheet_id, token]):
        return jsonify({"error": "Missing required data"}), 400

    print(f"--- Secure API call received for customer {user_id} using sheet {sheet_id} ---")
    
    business_data = load_business_data(sheet_id)
    if not business_data:
        return jsonify({"error": f"Failed to load data for sheet_id: {sheet_id}"}), 500

    bot_response = get_chatbot_response(user_id, msg, business_data)
    send_instagram_message(user_id, bot_response, token)
    save_message({"user_id": user_id, "direction": "incoming", "text": msg, "timestamp": time.time()})
    save_message({"user_id": user_id, "direction": "outgoing", "text": bot_response, "timestamp": time.time()})
    
    return jsonify({"status": "success", "reply_sent": bot_response}), 200

# --- Step 9: Main Execution ---
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    app.run(host='0.0.0.0', port=port, debug=True)
