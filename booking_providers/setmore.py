# ai-inbox-python-service/booking_providers/setmore.py
# ==============================================================================
# REAL, PRODUCTION-READY SETMORE INTEGRATION MODULE
# This module uses the official Setmore API to perform real actions.
# ==============================================================================

import requests
import json
from datetime import datetime, timedelta

BASE_URL = "https://developer.setmore.com/api/v1"

# --- INTERNAL HELPER FUNCTIONS ---

def _get_access_token(refresh_token: str):
    """Exchanges a client's refresh token for a short-lived access token."""
    print("[SETORE_API] Getting new access token...")
    if not refresh_token or refresh_token == 'DUMMY_API_KEY':
        print("[SETORE_API_ERROR] Invalid or missing refresh token.")
        return None
    
    url = f"{BASE_URL}/o/oauth2/token?refreshToken={refresh_token}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        access_token = data.get("data", {}).get("token", {}).get("access_token")
        if not access_token:
            print("[SETORE_API_ERROR] Access token not found in Setmore's response.")
            return None
        print("[SETORE_API] Successfully obtained access token.")
        return access_token
    except requests.exceptions.RequestException as e:
        print(f"[SETORE_API_ERROR] Failed to get access token: {e}")
        return None

def _get_service_details(service_name: str, access_token: str):
    """Finds the key and duration for a given service name."""
    print(f"[SETORE_API] Getting details for service: '{service_name}'")
    url = f"{BASE_URL}/bookingapi/services"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        services = response.json().get("data", {}).get("services", [])
        for service in services:
            if service_name.lower() in service.get("service_name", "").lower():
                print(f"[SETORE_API] Found service match: {service['key']}")
                return {"key": service["key"], "duration": service.get("duration", 30)}
        print(f"[SETORE_API_ERROR] No service found matching '{service_name}'")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[SETORE_API_ERROR] Failed to get service details: {e}")
        return None

def _get_staff_key(access_token: str):
    """Gets the key of the first available staff member."""
    print("[SETORE_API] Getting first available staff key...")
    url = f"{BASE_URL}/bookingapi/staffs"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        staffs = response.json().get("data", {}).get("staffs", [])
        if staffs:
            print(f"[SETORE_API] Found staff key: {staffs[0]['key']}")
            return staffs[0]["key"]
        print("[SETORE_API_ERROR] No staff members found for this account.")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[SETORE_API_ERROR] Failed to get staff key: {e}")
        return None

def _get_or_create_customer_key(customer_name: str, access_token: str):
    """Creates a new customer profile and returns their key."""
    print(f"[SETORE_API] Creating customer profile for: '{customer_name}'")
    url = f"{BASE_URL}/bookingapi/customer/create"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    
    name_parts = customer_name.strip().split()
    first_name = name_parts[0]
    last_name = name_parts[-1] if len(name_parts) > 1 else ""
    
    payload = {"first_name": first_name, "last_name": last_name}
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        customer_data = response.json().get("data", {}).get("customer", {})
        customer_key = customer_data.get("key")
        if customer_key:
            print(f"[SETORE_API] Successfully created customer, key: {customer_key}")
            return customer_key
        return None
    except requests.exceptions.RequestException as e:
        print(f"[SETORE_API_ERROR] Failed to create customer: {e}")
        return None

# --- PUBLIC-FACING TOOL FUNCTIONS ---

def get_availability(service_name: str, date: str, client_api_key: str, **kwargs):
    """Gets available time slots by making a real API call to Setmore."""
    access_token = _get_access_token(client_api_key)
    if not access_token: return json.dumps({"error": "Authentication with booking provider failed."})

    service_details = _get_service_details(service_name, access_token)
    staff_key = _get_staff_key(access_token)
    
    if not all([service_details, staff_key]):
        return json.dumps({"error": "Could not find the requested service or available staff in the booking system."})

    url = f"{BASE_URL}/bookingapi/slots"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    
    try:
        formatted_date = datetime.strptime(date, '%Y-%m-%d').strftime('%d/%m/%Y')
        payload = {"staff_key": staff_key, "service_key": service_details["key"], "selected_date": formatted_date}
        
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        slots = response.json().get("data", [])
        if not slots:
             return json.dumps({"message": "I'm sorry, there are no available time slots for that service on that day."})
        return json.dumps({"provider": "Setmore", "available_times": slots})
    except Exception as e:
        print(f"[SETORE_API_ERROR] Failed to get slots: {e}")
        return json.dumps({"error": "An error occurred while checking for available slots."})

def create_appointment(service_name: str, date: str, time: str, customer_name: str, client_api_key: str, **kwargs):
    """Creates a real appointment in the Setmore calendar."""
    access_token = _get_access_token(client_api_key)
    if not access_token: return json.dumps({"error": "Authentication with booking provider failed."})

    service_details = _get_service_details(service_name, access_token)
    staff_key = _get_staff_key(access_token)
    customer_key = _get_or_create_customer_key(customer_name, access_token)

    if not all([service_details, staff_key, customer_key]):
        return json.dumps({"error": "Could not retrieve all necessary details to book. Please check the service name."})

    url = f"{BASE_URL}/bookingapi/appointment/create"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    
    try:
        # Combine date and time and format for the API
        start_dt_str = f"{date} {time}"
        start_dt = datetime.strptime(start_dt_str, '%Y-%m-%d %I:%M %p')
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
