# ai-inbox-python-service/booking_providers/square.py
import json

def get_availability(service_name: str, date: str, client_api_key: str):
    """SIMULATED: Makes an API call to Square Appointments to get availability."""
    print(f"--- Calling SQUARE API for availability for service: {service_name} ---")
    # Square's API is different, so the logic here would be unique.
    # It might return times in a different format.
    return json.dumps({"provider": "Square", "available_times": ["09:45:00", "13:15:00", "16:00:00"]})

def create_appointment(service_name: str, date: str, time: str, customer_name: str, client_api_key: str):
    """SIMULATED: Makes an API call to Square to CREATE a booking."""
    print(f"--- Calling SQUARE API to create booking for {customer_name} ---")
    # The payload and endpoint for Square would be completely different from Setmore.
    return json.dumps({
        "success": True, 
        "provider": "Square",
        "confirmation_id": "SQ-BOOKING-ID-789"
    })
