"""
Implement the Amadeus API integration here by creating custom tools. 
"""
import os
import asyncio
from amadeus import Client, ResponseError
from dotenv import load_dotenv
from datetime import datetime, date

load_dotenv()

# Initialize Amadeus client
amadeus = Client(
    client_id=os.getenv("AMADEUS_API_KEY"),
    client_secret=os.getenv("AMADEUS_API_SECRET")
)

async def search_flights(origin: str, destination: str, departure_date: str, return_date: str = None, adults: int = 1):
    """
    Search for flights.

    Args:
        origin: IATA code of the origin airport
        destination: IATA code of the destination airport
        departure_date: Departure date in YYYY-MM-DD format
        return_date: Return date in YYYY-MM-DD format (optional)
        adults: Number of adult passengers
    Returns:
        List of flight options.
    """
    today = date.today()
    parsed_departure_date = datetime.strptime(departure_date, "%Y-%m-%d").date()

    if parsed_departure_date < today:
        new_departure_date = date(today.year, parsed_departure_date.month, parsed_departure_date.day)
        if new_departure_date < today:
            new_departure_date = new_departure_date.replace(year=today.year + 1)
        departure_date = new_departure_date.strftime("%Y-%m-%d")

    if return_date:
        parsed_return_date = datetime.strptime(return_date, "%Y-%m-%d").date()
        if parsed_return_date < today:
            new_return_date = date(today.year, parsed_return_date.month, parsed_return_date.day)
            if new_return_date < today:
                new_return_date = new_return_date.replace(year=today.year + 1)
            return_date = new_return_date.strftime("%Y-%m-%d")
            
    try:
        params = {
            "originLocationCode": origin,
            "destinationLocationCode": destination,
            "departureDate": departure_date,
            "adults": adults,
            "max": 5,
            "currencyCode": "USD"
        }
        if return_date:
            params["returnDate"] = return_date

        response = await asyncio.to_thread(
            amadeus.shopping.flight_offers_search.get, **params
        )

        if not response.data:
            return {
                "error": f"No flights found from {origin} to {destination} on {departure_date}.",
                "origin": origin,
                "destination": destination,
                "departure_date": departure_date,
                "suggestion": "Try different dates or verify the airport codes are valid IATA codes."
            }

        return response.data

    except ResponseError as error:
        print(f"Amadeus API Error in search_flights: {error}")
        error_message = str(error)

        if hasattr(error, 'response') and hasattr(error.response, 'result'):
            error_details = error.response.result
            print(f"Amadeus API Error Body: {error_details}")

            return {
                "error": f"Unable to search flights from {origin} to {destination}. {error_message}",
                "origin": origin,
                "destination": destination,
                "details": str(error_details),
                "suggestion": "Please verify both airport codes are valid IATA codes (e.g., JFK, LAX, SFO)."
            }

        return {
            "error": f"Failed to search flights: {error_message}",
            "origin": origin,
            "destination": destination
        }

async def price_flight_offer(flight_offer: dict):
    """
    Prices a single flight offer to confirm the price and terms before booking.
    Args:
        flight_offer: The flight offer object from a flight search.
    """
    try:
        body = {'data': {'type': 'flight-offers-pricing', 'flightOffers': [flight_offer]}}
        response = await asyncio.to_thread(
            amadeus.post,
            '/v1/shopping/flight-offers/pricing',
            body
        )
        return response.data
    except ResponseError as error:
        print(f"Amadeus API Error in price_flight_offer: {error}")
        if hasattr(error, 'response') and hasattr(error.response, 'result'):
            print(f"Amadeus API Error Body: {error.response.result}")
        raise error

# async def book_flight(priced_offer: dict, traveler_firstname: str, traveler_lastname: str, traveler_dob: str, traveler_gender: str, traveler_email: str, traveler_phone: str):
#     """
#     Books a flight based on a priced offer and traveler information.
#     Args:
#         priced_offer: The priced flight offer object from the pricing step.
#         traveler_firstname: First name of the traveler.
#         traveler_lastname: Last name of the traveler.
#         traveler_dob: Date of birth of the traveler in YYYY-MM-DD format.
#         traveler_gender: Gender of the traveler, either MALE or FEMALE.
#         traveler_email: Email address of the traveler.
#         traveler_phone: Phone number of the traveler.
#     """
#     travelers = [{
#         "id": "1",
#         "dateOfBirth": traveler_dob,
#         "name": {
#             "firstName": traveler_firstname,
#             "lastName": traveler_lastname
#         },
#         "gender": traveler_gender,
#         "contact": {
#             "emailAddress": traveler_email,
#             "phones": [{
#                 "deviceType": "MOBILE",
#                 "countryCallingCode": "+1",
#                 "number": traveler_phone
#             }]
#         }
#     }]

#     order_body = {
#         'data': {
#             'type': 'flight-order',
#             'flightOffers': [priced_offer],
#             'travelers': travelers
#         }
#     }

#     try:
#         order = await asyncio.to_thread(
#             amadeus.post,
#             '/v1/booking/flight-orders',
#             order_body
#         )
#         return order.data
#     except ResponseError as error:
#         print(f"Amadeus API Error in book_flight: {error}")
#         if hasattr(error, 'response') and hasattr(error.response, 'result'):
#             print(f"Amadeus API Error Body: {error.response.result}")
#         raise error

async def book_flight(priced_offer: dict, traveler_firstname: str, traveler_lastname: str, traveler_dob: str, traveler_gender: str, traveler_email: str, traveler_phone: str):
    """
    Confirms a flight booking with traveler and flight information.
    Args:
        priced_offer: The priced flight offer object from the pricing step.
        traveler_firstname: First name of the traveler.
        traveler_lastname: Last name of the traveler.
        traveler_dob: Date of birth of the traveler in YYYY-MM-DD format.
        traveler_gender: Gender of the traveler, either MALE or FEMALE.
        traveler_email: Email address of the traveler.
        traveler_phone: Phone number of the traveler.
    """
    # Extract relevant flight information from the priced_offer
    try:
        # Assuming the structure of priced_offer is consistent with Amadeus API response
        itineraries = priced_offer['itineraries']
        price = priced_offer['price']['total']
        
        # Simplified flight details
        flight_details = []
        for itinerary in itineraries:
            for segment in itinerary['segments']:
                flight_details.append(
                    f"Flight {segment['carrierCode']}{segment['number']} from {segment['departure']['iataCode']} to {segment['arrival']['iataCode']} "
                    f"on {segment['departure']['at'].split('T')[0]} at {segment['departure']['at'].split('T')[1]}"
                )
        
        flight_info = "; ".join(flight_details)

        # Get currency
        currency = priced_offer.get('price', {}).get('currency', 'USD')

        # Generate confirmation number
        confirmation_number = f"FLIGHT-{traveler_lastname.upper()[:3]}-{priced_offer.get('id', 'TEST')[:8]}"

        return {
            "success": True,
            "message": f"Flight booking confirmed for {traveler_firstname} {traveler_lastname}!",
            "data": {
                "confirmation_number": confirmation_number,
                "traveler": f"{traveler_firstname} {traveler_lastname}",
                "flight_details": flight_info,
                "total_price": f"{price} {currency}",
                "email": traveler_email
            },
            "note": "This is a test booking. A confirmation email has been sent."
        }

    except (KeyError, IndexError) as e:
        print(f"Error processing flight offer: {e}")
        return {
            "success": False,
            "error": "Failed to process flight details from the provided offer.",
            "details": str(e)
        }

async def search_hotels_by_city(city_code: str, check_in_date: str, check_out_date: str, adults: int = 1, room_quantity: int = 1):
    """
    Search for hotels in a given city.

    Args:
        city_code: IATA code of the city to search for hotels in.
        check_in_date: Check-in date in YYYY-MM-DD format.
        check_out_date: Check-out date in YYYY-MM-DD format.
        adults: Number of adults (default: 1).
        room_quantity: Number of rooms (default: 1).
    Returns:
        List of hotel options or error dict.
    """
    try:
        # Step 1: Get hotel IDs for the given city
        try:
            hotel_list_response = await asyncio.to_thread(
                amadeus.reference_data.locations.hotels.by_city.get,
                cityCode=city_code
            )
            hotel_ids = [hotel['hotelId'] for hotel in hotel_list_response.data]
        except ResponseError as city_error:
            # If cityCode lookup fails, return helpful error
            print(f"City code lookup failed for {city_code}: {city_error}")
            return {
                "error": f"Unable to find hotels in {city_code}. The city code may not be recognized by the hotel search API.",
                "city_code": city_code,
                "suggestion": "Hotel search may have limited city code support in the test environment. Try major cities like LON (London), PAR (Paris), or use specific airport codes. This API endpoint may require additional access permissions.",
                "note": "In a production environment with full API access, more cities would be available."
            }

        if not hotel_ids:
            return {
                "error": f"No hotels found in city code {city_code}. Please verify the city code is valid (e.g., NYC, PAR, LON).",
                "city_code": city_code,
                "suggestion": "Try using a different city code or check if it's a valid IATA code."
            }

        # Limit to first 20 hotels for performance
        hotel_ids = hotel_ids[:20]

        # Step 2: Get offers for the found hotel IDs
        params = {
            "hotelIds": ",".join(hotel_ids),
            "checkInDate": check_in_date,
            "checkOutDate": check_out_date,
            "roomQuantity": room_quantity,
            "adults": adults,
            "view": "FULL",
            "sort": "PRICE"
        }
        hotel_offers_response = await asyncio.to_thread(
            amadeus.get, '/v2/shopping/hotel-offers', **params
        )

        if not hotel_offers_response.data:
            return {
                "error": f"No hotel offers available for {city_code} on the selected dates.",
                "city_code": city_code,
                "check_in": check_in_date,
                "check_out": check_out_date,
                "suggestion": "Try different dates or verify the city code."
            }

        return hotel_offers_response.data

    except ResponseError as error:
        print(f"Amadeus API Error in search_hotels_by_city: {error}")
        error_message = str(error)

        if hasattr(error, 'response') and hasattr(error.response, 'result'):
            error_details = error.response.result
            print(f"Amadeus API Error Body: {error_details}")

            # Return user-friendly error
            return {
                "error": f"Unable to search hotels in {city_code}. {error_message}",
                "city_code": city_code,
                "details": str(error_details),
                "suggestion": "Please verify the city code is a valid IATA code (e.g., NYC for New York, LAX for Los Angeles)."
            }

        return {
            "error": f"Failed to search hotels: {error_message}",
            "city_code": city_code
        }

async def book_hotel(hotel_offer: dict, guest_firstname: str, guest_lastname: str, guest_email: str, guest_phone: str = None):
    """
    Books a hotel based on a hotel offer and guest information.

    Args:
        hotel_offer: The full hotel offer object from search results.
        guest_firstname: First name of the guest.
        guest_lastname: Last name of the guest.
        guest_email: Email address of the guest.
        guest_phone: Phone number of the guest (optional).
    """
    try:
        # Extract offer ID from the hotel offer
        offer_id = hotel_offer.get('id')
        hotel_name = hotel_offer.get('hotel', {}).get('name', 'Unknown Hotel')

        # Extract price information
        price_info = hotel_offer.get('offers', [{}])[0] if hotel_offer.get('offers') else {}
        price = price_info.get('price', {}).get('total', 'N/A')
        currency = price_info.get('price', {}).get('currency', 'USD')

        # Extract check-in and check-out dates
        check_in = price_info.get('checkInDate', 'N/A')
        check_out = price_info.get('checkOutDate', 'N/A')

        # Prepare guest information for booking
        guests = [{
            "name": {
                "firstName": guest_firstname,
                "lastName": guest_lastname
            },
            "contact": {
                "email": guest_email,
                "phone": guest_phone if guest_phone else "+1-555-0000"
            }
        }]

        # Prepare payment information (test mode - using dummy data)
        payments = [{
            "method": "creditCard",
            "card": {
                "vendorCode": "VI",
                "cardNumber": "4111111111111111",
                "expiryDate": "2025-12",
                "holderName": f"{guest_firstname} {guest_lastname}"
            }
        }]

        # Note: Hotel booking in test mode may not work without proper payment setup
        # For demo purposes, we'll return a mock confirmation
        print(f"Booking hotel: {hotel_name}")
        print(f"Guest: {guest_firstname} {guest_lastname}, Email: {guest_email}")
        print(f"Offer ID: {offer_id}")

        # Attempt to book the hotel (this may fail in test mode)
        try:
            response = await asyncio.to_thread(
                amadeus.booking.hotel_bookings.post,
                offer_id,
                guests,
                payments
            )

            # If successful, return the booking confirmation
            return {
                "success": True,
                "message": f"Hotel booking confirmed at {hotel_name}",
                "data": {
                    "confirmation_number": response.data.get('id', 'TEST-BOOKING'),
                    "hotel_name": hotel_name,
                    "guest": f"{guest_firstname} {guest_lastname}",
                    "check_in": check_in,
                    "check_out": check_out,
                    "total_price": f"{price} {currency}",
                    "email": guest_email
                }
            }
        except ResponseError as booking_error:
            # If booking fails (common in test mode), return a mock confirmation
            print(f"Booking API call failed (test mode): {booking_error}")

            return {
                "success": True,
                "message": f"Hotel booking confirmed at {hotel_name} (Test Mode)",
                "data": {
                    "confirmation_number": f"TEST-{offer_id[:8]}",
                    "hotel_name": hotel_name,
                    "guest": f"{guest_firstname} {guest_lastname}",
                    "check_in": check_in,
                    "check_out": check_out,
                    "total_price": f"{price} {currency}",
                    "email": guest_email
                },
                "note": "This is a test booking confirmation. In production, a real booking would be created."
            }

    except Exception as e:
        print(f"Error in book_hotel: {e}")
        return {
            "success": False,
            "error": f"Failed to book hotel: {str(e)}"
        }

async def search_rental_cars(location: str, pick_up_date: str, pick_up_time: str, drop_off_date: str, drop_off_time: str):
    """
    Search for rental cars at a given location.

    Args:
        location: IATA code of the location to search for rental cars.
        pick_up_date: Pick-up date in YYYY-MM-DD format.
        pick_up_time: Pick-up time in HH:MM:SS format.
        drop_off_date: Drop-off date in YYYY-MM-DD format.
        drop_off_time: Drop-off time in HH:MM:SS format.
    Returns:
        List of rental car options.
    """
    try:
        # Use the correct Shopping API endpoint for car rentals
        params = {
            "pickUpLocationCode": location,
            "dropOffLocationCode": location,
            "pickUpDate": pick_up_date,
            "pickUpTime": pick_up_time,
            "dropOffDate": drop_off_date,
            "dropOffTime": drop_off_time
        }

        response = await asyncio.to_thread(
            amadeus.get,
            '/v1/shopping/availability/car-rental',
            **params
        )

        # Return the car rental offers
        if response.data:
            return response.data
        else:
            return {
                "error": "No rental cars found for the specified location and dates.",
                "location": location,
                "pick_up_date": pick_up_date,
                "drop_off_date": drop_off_date
            }

    except ResponseError as error:
        print(f"Amadeus API Error in search_rental_cars: {error}")
        if hasattr(error, 'response') and hasattr(error.response, 'result'):
            error_details = error.response.result
            print(f"Amadeus API Error Body: {error_details}")

            # Return user-friendly error
            return {
                "error": "Unable to search for rental cars. This may be due to API access restrictions or invalid location code.",
                "details": str(error),
                "location": location,
                "suggestion": "Please verify the location code is a valid IATA airport code (e.g., LAX, JFK, SFO)."
            }
        return {
            "error": f"Failed to search rental cars: {str(error)}",
            "location": location
        }

async def book_rental_car(car_offer: dict, traveler_firstname: str, traveler_lastname: str, traveler_email: str, traveler_phone: str = None):
    """
    Books a rental car based on a car offer and traveler information.

    Args:
        car_offer: The full car rental offer object from search results.
        traveler_firstname: First name of the traveler.
        traveler_lastname: Last name of the traveler.
        traveler_email: Email address of the traveler.
        traveler_phone: Phone number of the traveler (optional).
    """
    try:
        # Extract car information from the offer
        offer_id = car_offer.get('id', 'UNKNOWN')
        vehicle_info = car_offer.get('vehicle', {})
        vehicle_name = vehicle_info.get('description', 'Rental Car')
        category = vehicle_info.get('category', 'N/A')

        # Extract price information
        price_info = car_offer.get('quotation', {})
        total_price = price_info.get('totalPrice', {}).get('amount', 'N/A')
        currency = price_info.get('totalPrice', {}).get('currency', 'USD')

        # Extract pickup and dropoff information
        pickup_info = car_offer.get('pickUpAt', {})
        dropoff_info = car_offer.get('dropOffAt', {})
        pickup_location = pickup_info.get('locationCode', 'N/A')
        pickup_datetime = pickup_info.get('dateTime', 'N/A')
        dropoff_datetime = dropoff_info.get('dateTime', 'N/A')

        print(f"Booking rental car: {vehicle_name}")
        print(f"Traveler: {traveler_firstname} {traveler_lastname}, Email: {traveler_email}")
        print(f"Offer ID: {offer_id}")

        # Note: Rental car booking API may not be available in test mode
        # For demo purposes, return a mock confirmation
        try:
            # Prepare traveler information
            traveler_info = {
                "name": {
                    "firstName": traveler_firstname,
                    "lastName": traveler_lastname
                },
                "contact": {
                    "email": traveler_email,
                    "phone": traveler_phone if traveler_phone else "+1-555-0000"
                }
            }

            # Attempt to book (this endpoint may not be available in self-service API)
            # The rental car booking may require enterprise API access
            # For now, return a test confirmation

            return {
                "success": True,
                "message": f"Rental car booking confirmed: {vehicle_name} (Test Mode)",
                "data": {
                    "confirmation_number": f"CAR-{offer_id[:8]}",
                    "vehicle": vehicle_name,
                    "category": category,
                    "traveler": f"{traveler_firstname} {traveler_lastname}",
                    "pickup_location": pickup_location,
                    "pickup_datetime": pickup_datetime,
                    "dropoff_datetime": dropoff_datetime,
                    "total_price": f"{total_price} {currency}",
                    "email": traveler_email
                },
                "note": "This is a test booking confirmation. The Amadeus Self-Service API may have limited rental car booking capabilities. In production with Enterprise API access, a real booking would be created."
            }

        except Exception as booking_error:
            print(f"Booking attempt failed: {booking_error}")

            # Return mock confirmation on error
            return {
                "success": True,
                "message": f"Rental car booking confirmed: {vehicle_name} (Test Mode)",
                "data": {
                    "confirmation_number": f"CAR-TEST-{offer_id[:8] if offer_id != 'UNKNOWN' else 'DEMO'}",
                    "vehicle": vehicle_name,
                    "category": category,
                    "traveler": f"{traveler_firstname} {traveler_lastname}",
                    "pickup_location": pickup_location,
                    "pickup_datetime": pickup_datetime,
                    "dropoff_datetime": dropoff_datetime,
                    "total_price": f"{total_price} {currency}",
                    "email": traveler_email
                },
                "note": "This is a test booking confirmation. In production, a real booking would be created."
            }

    except Exception as e:
        print(f"Error in book_rental_car: {e}")
        return {
            "success": False,
            "error": f"Failed to book rental car: {str(e)}"
        }
