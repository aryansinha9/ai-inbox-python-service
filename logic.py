# ai-inbox-python-service/logic.py
# ==============================================================================
# FINAL PRODUCTION VERSION
# This version includes the fix for the OpenAI history bug.
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
from datetime import datetime

# --- Import the specific provider modules ---
from booking_providers import setmore, square

# --- Step 2: Flask App Initialization & Globals ---
app = Flask(__name__)
load_dotenv()
print("Flask app initialized and environment variables loaded.")

CHAT_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_log.json")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")
conversation_histories = {}

# --- Step 3: Master Router Functions ---

def get_availability_from_provider(provider: str, **kwargs):
    """Routes the availability check to the correct provider module."""
    if provider == 'setmore':
        return setmore.get_availability(**kwargs)
    elif provider == 'square':
        return square.get_availability(**kwargs)
    else:
        return json.dumps({"error": "This booking provider is not configured or supported."})

def create_appointment_with_provider(provider: str, **kwargs):
    """Routes the appointment creation to the correct provider module."""
    if provider == 'setmore':
        return setmore.create_appointment(**kwargs)
    elif provider == 'square':
        return square.create_appointment(**kwargs)
    else:
        return json.dumps({"error": "This booking provider is not configured or supported."})

# --- Step 4: Helper Functions ---

def save_message(entry):
    """Saves a single message entry to the chat log JSON file."""
    try:
        data = []
        if os.path.exists(CHAT_LOG_PATH):
            with open(CHAT_LOG_PATH, "r") as f:
                try: data = json.load(f)
                except json.JSONDecodeError: data = []
        if not isinstance(data, list): data = []
        data.append(entry)
        with open(CHAT_LOG_PATH, "w") as f: json.dump(data, f, indent=2)
    except Exception as e:
        print(f"ERROR saving message log: {e}")

def load_business_data(spreadsheet_id):
    """Loads business configuration and services from a Google Sheet."""
    business_data = {'services': {}, 'config': {}}
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

        for row in spreadsheet.worksheet('Services').get_all_records():
            service_name = str(row.get('Service', '')).strip().lower()
            if service_name: business_data['services'][service_name] = {'price': str(row.get('Price', '')), 'duration': str(row.get('Duration', ''))}

        for row in spreadsheet.worksheet('Config').get_all_records():
            key, value = str(row.get('Key', '')), str(row.get('Value', ''))
            if key: business_data['config'][key] = value
        
        print(f"Successfully loaded knowledge base from sheet {spreadsheet_id}")
        return business_data
    except Exception as e:
        print(f"\n--- ERROR loading Google Sheet data: {e} ---")
        return None

def initialize_openai():
    """Initializes and returns the OpenAI client."""
    try:
        client = openai.OpenAI(); print("OpenAI client initialized successfully."); return client
    except Exception as e: print(f"\n--- FATAL ERROR initializing OpenAI client: {e} ---"); sys.exit(1)

def format_services_for_prompt(service_dict):
    """Formats the service dictionary into a string for the AI prompt."""
    if not service_dict: return "No specific service details are loaded."
    return "\n".join([f"- {name.title()}: Price is {details['price']}" for name, details in sorted(service_dict.items())])

# --- Step 5: Main AI Logic Function (with history fix) ---
def get_chatbot_response(user_id, user_prompt, business_data, booking_data):
    """Gets a response from OpenAI, using tools that are routed to the correct provider."""
    global conversation_histories
    if user_id not in conversation_histories: conversation_histories[user_id] = []

    config = business_data.get('config', {})
    service_info = format_services_for_prompt(business_data.get('services', {}))
    today = datetime.now().strftime('%Y-%m-%d')
    system_prompt = (
        f"You are an automated appointment booking assistant for a business named {config.get('business_name', 'our shop')}.\n"
        f"Today's date is {today}.\n\n"
        "--- PRIMARY GOAL & RULES ---\n"
        "1. Your main purpose is to help users check for available appointment times and book appointments using the provided tools.\n"
        "2. **CRITICAL RULE:** You MUST NOT answer questions about availability or attempt to book an appointment by making up text. You must use the `check_availability` tool to find open slots first, and then use the `create_appointment` tool to finalize a booking. If the user is vague, you must ask clarifying questions to get the parameters needed for the tools (like service name, date, time, and customer name).\n"
        "3. **FALLBACK BEHAVIOR:** If the user asks a general question NOT related to booking (e.g., 'What are your prices?'), then and only then should you answer using the 'Business Information' provided below.\n\n"
        f"--- Business Information for Fallback Questions ---\n{service_info}\n"
    )
    
    tools = [
        {"type": "function", "function": {"name": "check_availability", "description": "Checks for available appointment slots.", "parameters": {"type": "object", "properties": {"service_name": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD"}}, "required": ["service_name", "date"]}}},
        {"type": "function", "function": {"name": "create_appointment", "description": "Books an appointment after availability is confirmed.", "parameters": {"type": "object", "properties": {"service_name": {"type": "string"}, "date": {"type": "string"}, "time": {"type": "string"}, "customer_name": {"type": "string"}}, "required": ["service_name", "date", "time", "customer_name"]}}}
    ]

    # Use the long-term history, but build a temporary message list for this specific turn
    messages_for_this_turn = conversation_histories[user_id].copy()
    messages_for_this_turn.append({"role": "user", "content": user_prompt})

    try:
        response = OPENAI_CLIENT.chat.completions.create(
            model="gpt-4-turbo",
            messages=[{"role": "system", "content": system_prompt}] + messages_for_this_turn,
            tools=tools,
            tool_choice="auto"
        )
        response_message = response.choices[0].message
        tool_calls = response_message.tool_calls

        if tool_calls:
            # Append the AI's decision to call a tool to our temporary list
            messages_for_this_turn.append(response_message)
            
            available_functions = {
                "check_availability": get_availability_from_provider,
                "create_appointment": create_appointment_with_provider
            }

            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_to_call = available_functions.get(function_name)
                if not function_to_call: continue

                args = json.loads(tool_call.function.arguments)
                args['provider'] = booking_data.get('provider', 'none')
                args['client_api_key'] = booking_data.get('api_key')
                
                print(f"[ROUTER] Routing to provider '{args['provider']}' for function '{function_name}'")
                
                function_response = function_to_call(**args)
                messages_for_this_turn.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": function_response
                })
            
            second_response = OPENAI_CLIENT.chat.completions.create(
                model="gpt-4-turbo",
                messages=messages_for_this_turn
            )
            final_response = second_response.choices[0].message.content
            
            # Update the long-term history
            conversation_histories[user_id].append({"role": "user", "content": user_prompt})
            conversation_histories[user_id].append({"role": "assistant", "content": final_response})
            conversation_histories[user_id] = conversation_histories[user_id][-10:]  # Keep history concise
            return final_response

        # Fallback for non-tool responses
        ai_response_content = response_message.content
        if ai_response_content:
            conversation_histories[user_id].append({"role": "user", "content": user_prompt})
            conversation_histories[user_id].append({"role": "assistant", "content": ai_response_content})
            conversation_histories[user_id] = conversation_histories[user_id][-10:]
            return ai_response_content.strip()
        return "How else can I help?"

    except Exception as e:
        print(f"Error during OpenAI call for user {user_id}: {e}")
        return "Sorry, there was an error processing your request."

# --- Step 6: Instagram Messaging & Startup ---
def send_instagram_message(recipient_id, message_text, page_token):
    url = f"https://graph.facebook.com/v19.0/me/messages?access_token={page_token}"
    headers = {'Content-Type': 'application/json'}
    data = {
        "recipient": {"id": recipient_id},
        "message": {"text": message_text},
        "messaging_type": "RESPONSE"
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"ERROR Sending Instagram Message: {e}")

print("--- Initializing Chatbot Services ---")
if not INTERNAL_API_KEY:
    print("FATAL ERROR: INTERNAL_API_KEY is missing.")
    sys.exit(1)
OPENAI_CLIENT = initialize_openai()
print("--- Initialization Complete. AI Microservice is Ready. ---")

@app.route('/api/process-message', methods=['POST'])
def process_message_api():
    if request.headers.get('X-Internal-API-Key') != INTERNAL_API_KEY:
        abort(401)
    
    data = request.get_json()
    user_id = data.get('user_id')
    msg = data.get('message_text')
    sheet_id = data.get('sheet_id')
    token = data.get('page_access_token')
    booking_integration_data = data.get('booking_integration', {})
    
    if not all([user_id, msg, sheet_id, token]):
        return jsonify({"error": "Missing required data"}), 400
    
    business_data = load_business_data(sheet_id)
    if not business_data:
        return jsonify({"error": f"Failed to load data for sheet_id: {sheet_id}"}), 500
    
    bot_response = get_chatbot_response(user_id, msg, business_data, booking_integration_data)
    send_instagram_message(user_id, bot_response, token)
    
    save_message({
        "user_id": user_id,
        "direction": "incoming",
        "text": msg,
        "timestamp": time.time()
    })
    save_message({
        "user_id": user_id,
        "direction": "outgoing",
        "text": bot_response,
        "timestamp": time.time()
    })
    return jsonify({
        "status": "success",
        "reply_sent": bot_response
    }), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    app.run(host='0.0.0.0', port=port, debug=True)
