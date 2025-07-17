# ai-inbox-python-service/booking_providers/setmore.py
# ==============================================================================
# FINAL PRODUCTION-READY SETMORE INTEGRATION MODULE
# This version includes flexible time parsing.
# ==============================================================================

import requests
import json
from datetime import datetime, timedelta

BASE_URL = "https://developer.setmore.com/api/v1"

# --- INTERNAL HELPER FUNCTIONS (Unchanged) ---

def _get_access_token(refresh_token: str):
    # ... (this function is already correct)
    print("[SETORE_API] Getting new access token...")
    if not refresh_token or refresh_token == 'DUMMY_API_KEY': return None
    url = f"{BASE_URL}/o/oauth2/token?refreshToken={refresh_token}"
    try:
        response = requests.get(url); response.raise_for_status()
        access_token = response.json().get("data", {}).get("token", {}).get("access_token")
        if access_token: print("[SETORE_API] Successfully obtained access token."); return access_token
    except requests.exceptions.RequestException as e: print(f"[SETORE_API_ERROR] Failed to get access token: {e}")
    return None

def _get_service_details(service_name: str, access_token: str):
    # ... (this function is already correct)
    print(f"[SETORE_API] Getting details for service: '{service_name}'")
    url = f"{BASE_URL}/bookingapi/services"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        response = requests.get(url, headers=headers); response.raise_for_status()
        services = response.json().get("data", {}).get("services", [])
        for service in services:
            if service_name.lower() in service.get("service_name", "").lower():
                return {"key": service["key"], "duration": service.get("duration", 30)}
    except requests.exceptions.RequestException as e: print(f"[SETORE_API_ERROR] Failed to get service details: {e}")
    return None

def _get_staff_key(access_token: str):
    # ... (this function is already correct)
    print("[SETORE_API] Getting first available staff key...")
    url = f"{BASE_URL}/bookingapi/staffs"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        response = requests.get(url, headers=headers); response.raise_for_status()
        staffs = response.json().get("data", {}).get("staffs", [])
        if staffs: return staffs[0]["key"]
    except requests.exceptions.RequestException as e: print(f"[SETORE_API_ERROR] Failed to get staff key: {e}")
    return None

def _get_or_create_customer_key(customer_name: str, access_token: str):
    # ... (this function is already correct)
    print(f"[SETORE_API] Creating customer profile for: '{customer_name}'")
    url = f"{BASE_URL}/bookingapi/customer/create"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    name_parts = customer_name.strip().split()
    payload = {"first_name": name_parts[0], "last_name": name_parts[-1] if len(name_parts) > 1 else ""}
    try:
        response = requests.post(url, headers=headers, json=payload); response.raise_for_status()
        return response.json().get("data", {}).get("customer", {}).get("key")
    except requests.exceptions.RequestException as e: print(f"[SETORE_API_ERROR] Failed to create customer: {e}")
    return None

# --- PUBLIC-FACING TOOL FUNCTIONS ---

def get_availability(service_name: str, date: str, client_api_key: str, **kwargs):
    # ... (this function is already correct)
    access_token = _get_access_token(client_api_key)
    if not access_token: return json.dumps({"error": "Authentication failed."})
    service_details = _get_service_details(service_name, access_token)
    staff_key = _get_staff_key(access_token)
    if not all([service_details, staff_key]): return json.dumps({"error": "Could not find service or staff details."})
    url = f"{BASE_URL}/bookingapi/slots"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    try:
        formatted_date = datetime.strptime(date, '%Y-%m-%d').strftime('%d/%m/%Y')
        payload = {"staff_key": staff_key, "service_key": service_details["key"], "selected_date": formatted_date}
        response = requests.post(url, headers=headers, json=payload); response.raise_for_status()
        slots = response.json().get("data", [])
        if not slots: return json.dumps({"message": "I'm sorry, there are no available time slots for that service on that day."})
        return json.dumps({"provider": "Setmore", "available_times": slots})
    except Exception as e:
        print(f"[SETORE_API_ERROR] Failed to get slots: {e}")
        return json.dumps({"error": "An error occurred while checking for available slots."})

def create_appointment(service_name: str, date: str, time: str, customer_name: str, client_api_key: str, **kwargs):
    """Creates a real appointment in the Setmore calendar with flexible time parsing."""
    access_token = _get_access_token(client_api_key)
    if not access_token: return json.dumps({"error": "Authentication failed."})

    service_details = _get_service_details(service_name, access_token)
    staff_key = _get_staff_key(access_token)
    customer_key = _get_or_create_customer_key(customer_name, access_token)

    if not all([service_details, staff_key, customer_key]):
        return json.dumps({"error": "Could not retrieve all necessary details to book."})

    url = f"{BASE_URL}/bookingapi/appointment/create"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    
    try:
        # --- THIS IS THE CORRECTED TIME PARSING LOGIC ---
        start_dt_str = f"{date} {time}"
        start_dt = None
        try:
            # First, try to parse the time as 12-hour AM/PM format
            start_dt = datetime.strptime(start_dt_str, '%Y-%m-%d %I:%M %p')
        except ValueError:
            # If that fails, it's likely a 24-hour format
            start_dt = datetime.strptime(start_dt_str, '%Y-%m-%d %H:%M')
        
        end_dt = start_dt + timedelta(minutes=service_details["duration"])
        
        payload = {
            "staff_key": staff_key,
            "service_key": service_details["key"],
            "customer_key": customer_key,
            "start_time": start_dt.strftime('%Y-%m-%dT%H:%M'),
            "end_time": end_dt.strftime('%Y-%m-%dT%H:%M'),
            "comment": "Booked via AI Inbox"
        }
        
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        
        return json.dumps({"success": True, "provider": "Setmore", "confirmation": f"Booking confirmed for {service_name} at {time}."})
    except Exception as e:
        print(f"[SETORE_API_ERROR] Failed to create appointment: {e}")
        return json.dumps({"error": "I was unable to finalize the booking in the calendar. Please contact the business directly."})
