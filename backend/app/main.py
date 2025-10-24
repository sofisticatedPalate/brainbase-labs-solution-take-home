from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import json
import logging
from .models import ChatRequest, ChatMessage
from .openai_service import generate_chat_response
from .custom_tools import (
    search_flights as amadeus_search_flights,
    price_flight_offer as amadeus_price_flight_offer,
    book_flight as amadeus_book_flight,
    search_hotels_by_city as amadeus_search_hotels_by_city,
    book_hotel as amadeus_book_hotel,
    search_rental_cars as amadeus_search_rental_cars,
    book_rental_car as amadeus_book_rental_car
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage for session data (keyed by websocket connection)
# Each session stores: flight_offers, last_priced_offer, hotel_offers, rental_car_offers
session_data = {}

# Define global system prompt
SYSTEM_PROMPT = """You are a helpful and friendly travel assistant for Based Airlines.
You can help users book flights, hotels, and rental cars.
Use the available tools to search for travel options.
If you need more information (like origin city, destination, or dates), you must ask the user for it before calling any tools.
Always confirm IATA codes with the user if they provide a city name (e.g., "Did you mean SFO for San Francisco?").
After getting search results, present them clearly to the user with numbers starting from 1.

**Flight Booking Flow:**
1. To book a flight, you MUST first use the `price_flight_offer` tool to confirm the price. You must use the flight number from the search results.
2. After pricing the flight, you MUST ask the user for their full name, date of birth (YYYY-MM-DD), gender (MALE/FEMALE), email address, and phone number.
3. Finally, use the `book_flight` tool with the priced offer and the traveler's complete information.
4. IMMEDIATELY after the `book_flight` tool returns successfully, you MUST:
   a. Confirm the booking details to the user (confirmation number, flight details, price)
   b. Ask: "Would you like to book a hotel at your destination?"
   c. Also ask: "Would you like to book a rental car?"
   These questions are MANDATORY after every successful flight booking.

**Hotel Booking Flow:**
1. Search for hotels using `search_hotels_by_city` with the IATA city code and check-in/check-out dates.
   - IMPORTANT: Use IATA city codes (e.g., PAR for Paris, LON for London, NYC for New York)
   - If you only have an airport code (e.g., JFK), derive the city code (JFK -> NYC, LAX -> LAX, SFO -> SFO)
   - Common conversions: JFK/LGA/EWR -> NYC, CDG/ORY -> PAR, LHR/LGW -> LON
2. NOTE: If you receive an error about city code not being recognized or API access:
   - Inform the user: "I apologize, but hotel search for [city] is currently unavailable in our test environment. The hotel booking API has limited city coverage or requires upgraded access. In a production environment, you would be able to search and book hotels at your destination."
   - Suggest trying other major cities (LON, PAR) if they want to see the feature work.
   - Offer to help with other travel arrangements.
3. If search works, present the hotel results clearly to the user with hotel numbers starting from 1, including name, price, and amenities.
4. Ask the user to select a hotel by number.
5. After selection, if you already have guest information from a previous flight booking, ask: "Should I use the same traveler information (Name: [firstname] [lastname], Email: [email])?"
6. If user confirms, use the existing information. If user declines or no previous information exists, ask for: guest first name, last name, and email.
7. Use the `book_hotel` tool with the selected hotel number and guest information.

**Rental Car Booking Flow:**
1. Search for rental cars using `search_rental_cars` with AIRPORT code (not city code), pick-up date/time, and drop-off date/time.
   - IMPORTANT: Use IATA airport codes (e.g., JFK, LAX, SFO, MIA)
   - NOT city codes (NYC won't work, use JFK or LGA instead)
   - If user mentions a city, ask which airport they prefer or use the main airport
2. NOTE: Rental car search may not be available with current API access. If you receive an error about "Resource not found" or API access:
   - Inform the user: "I apologize, but rental car bookings are currently unavailable through our test API. This feature requires upgraded API access. In a production environment, you would be able to search and book rental cars at your destination."
   - Offer to help with other travel arrangements instead.
3. If search works, present the rental car results clearly with car numbers starting from 1, including vehicle type, price, and company.
4. Ask the user to select a car by number.
5. After selection, if you already have traveler information from a previous flight booking, ask: "Should I use the same traveler information (Name: [firstname] [lastname], Email: [email])?"
6. If user confirms, use the existing information. If user declines or no previous information exists, ask for: traveler first name, last name, and email.
7. Use the `book_rental_car` tool with the selected car number and traveler information.

**Important Rules:**
- Do NOT invent traveler names, dates, or any other details.
- If a search returns no results or an error, explain this clearly to the user and suggest alternatives.
- Always confirm details before making a booking.
- Be helpful and guide users through the process step by step.

**Critical: After Successful Flight Booking:**
When you receive a response from `book_flight` with "success": True, you MUST:
1. Show the confirmation number and booking details to the user
2. IMMEDIATELY ask: "Great! Your flight is booked. Would you like to book a hotel at your destination? And would you also like a rental car?"
3. Wait for the user's response before proceeding

This upsell prompt is REQUIRED after every successful flight booking. Do not skip this step."""

# Define available functions/tools
AVAILABLE_FUNCTIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_flights",
            "description": "Search for flights between two locations on specified dates",
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {
                        "type": "string",
                        "description": "IATA code of the origin airport"
                    },
                    "destination": {
                        "type": "string",
                        "description": "IATA code of the destination airport"
                    },
                    "departure_date": {
                        "type": "string",
                        "description": "Departure date in YYYY-MM-DD format"
                    },
                    "return_date": {
                        "type": "string",
                        "description": "Return date in YYYY-MM-DD format (optional)"
                    },
                    "adults": {
                        "type": "integer",
                        "description": "Number of adult passengers"
                    }
                },
                "required": ["origin", "destination", "departure_date", "adults"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "price_flight_offer",
            "description": "Prices a single flight offer to confirm the price and terms before booking.",
            "parameters": {
                "type": "object",
                "properties": {
                    "flight_number": {
                        "type": "integer",
                        "description": "The flight number from the search results, starting from 1."
                    }
                },
                "required": ["flight_number"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "book_flight",
            "description": "Books a flight based on a priced offer and traveler information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "traveler_firstname": {
                        "type": "string",
                        "description": "First name of the traveler."
                    },
                    "traveler_lastname": {
                        "type": "string",
                        "description": "Last name of the traveler."
                    },
                    "traveler_dob": {
                        "type": "string",
                        "description": "Date of birth of the traveler in YYYY-MM-DD format."
                    },
                    "traveler_gender": {
                        "type": "string",
                        "description": "Gender of the traveler, either MALE or FEMALE."
                    },
                    "traveler_email": {
                        "type": "string",
                        "description": "Email address of the traveler."
                    },
                    "traveler_phone": {
                        "type": "string",
                        "description": "Phone number of the traveler, e.g., 4155551234."
                    }
                },
                "required": ["traveler_firstname", "traveler_lastname", "traveler_dob", "traveler_gender", "traveler_email", "traveler_phone"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_hotels_by_city",
            "description": "Search for hotels in a given city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city_code": {
                        "type": "string",
                        "description": "IATA code of the city to search for hotels in."
                    },
                    "check_in_date": {
                        "type": "string",
                        "description": "Check-in date in YYYY-MM-DD format."
                    },
                    "check_out_date": {
                        "type": "string",
                        "description": "Check-out date in YYYY-MM-DD format."
                    }
                },
                "required": ["city_code", "check_in_date", "check_out_date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "book_hotel",
            "description": "Books a hotel based on a hotel selection number from search results and guest information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "hotel_number": {
                        "type": "integer",
                        "description": "The hotel number from the search results, starting from 1."
                    },
                    "guest_firstname": {
                        "type": "string",
                        "description": "First name of the guest."
                    },
                    "guest_lastname": {
                        "type": "string",
                        "description": "Last name of the guest."
                    },
                    "guest_email": {
                        "type": "string",
                        "description": "Email address of the guest."
                    },
                    "guest_phone": {
                        "type": "string",
                        "description": "Phone number of the guest (optional)."
                    }
                },
                "required": ["hotel_number", "guest_firstname", "guest_lastname", "guest_email"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_rental_cars",
            "description": "Search for rental cars at a given location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "IATA code of the location to search for rental cars."
                    },
                    "pick_up_date": {
                        "type": "string",
                        "description": "Pick-up date in YYYY-MM-DD format."
                    },
                    "pick_up_time": {
                        "type": "string",
                        "description": "Pick-up time in HH:MM:SS format."
                    },
                    "drop_off_date": {
                        "type": "string",
                        "description": "Drop-off date in YYYY-MM-DD format."
                    },
                    "drop_off_time": {
                        "type": "string",
                        "description": "Drop-off time in HH:MM:SS format."
                    }
                },
                "required": ["location", "pick_up_date", "pick_up_time", "drop_off_date", "drop_off_time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "book_rental_car",
            "description": "Books a rental car based on a car selection number from search results and traveler information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "car_number": {
                        "type": "integer",
                        "description": "The car number from the search results, starting from 1."
                    },
                    "traveler_firstname": {
                        "type": "string",
                        "description": "First name of the traveler."
                    },
                    "traveler_lastname": {
                        "type": "string",
                        "description": "Last name of the traveler."
                    },
                    "traveler_email": {
                        "type": "string",
                        "description": "Email address of the traveler."
                    },
                    "traveler_phone": {
                        "type": "string",
                        "description": "Phone number of the traveler (optional)."
                    }
                },
                "required": ["car_number", "traveler_firstname", "traveler_lastname", "traveler_email"]
            }
        }
    }
]


def get_session_data(session_id):
    """Helper function to get or create session data"""
    if session_id not in session_data:
        session_data[session_id] = {
            'flight_offers': [],
            'last_priced_offer': None,
            'hotel_offers': [],
            'rental_car_offers': []
        }
    return session_data[session_id]


async def search_flights(session_id: str, origin: str, destination: str, departure_date: str, return_date: str = None, adults: int = 1):
    """
    Wrapper function to call the search_flights tool from custom_tools.py
    """
    session = get_session_data(session_id)
    response = await amadeus_search_flights(origin, destination, departure_date, return_date, adults)

    if isinstance(response, dict) and 'error' in response:
        return response

    session['flight_offers'] = response
    return response


async def price_flight_offer(session_id: str, flight_number: int):
    session = get_session_data(session_id)
    flight_offers = session['flight_offers']

    if not flight_offers:
        return {"error": "No flight search has been performed yet."}
    if flight_number < 1 or flight_number > len(flight_offers):
        return {"error": f"Invalid flight number. Please choose a number between 1 and {len(flight_offers)}."}

    flight_to_price = flight_offers[flight_number - 1]
    response = await amadeus_price_flight_offer(flight_to_price)

    if isinstance(response, dict) and 'error' in response:
        return response

    session['last_priced_offer'] = response['flightOffers'][0]
    return response


async def book_flight(session_id: str, traveler_firstname: str, traveler_lastname: str, traveler_dob: str, traveler_gender: str, traveler_email: str, traveler_phone: str):
    session = get_session_data(session_id)
    last_priced_offer = session['last_priced_offer']

    if not last_priced_offer:
        return {"error": "No flight has been priced yet. Please price a flight first."}
    return await amadeus_book_flight(last_priced_offer, traveler_firstname, traveler_lastname, traveler_dob, traveler_gender, traveler_email, traveler_phone)


async def search_hotels_by_city(session_id: str, city_code: str, check_in_date: str, check_out_date: str):
    session = get_session_data(session_id)
    response = await amadeus_search_hotels_by_city(city_code, check_in_date, check_out_date)

    if isinstance(response, dict) and 'error' in response:
        return response

    session['hotel_offers'] = response
    return response


async def book_hotel(session_id: str, hotel_number: int, guest_firstname: str, guest_lastname: str, guest_email: str, guest_phone: str = None):
    session = get_session_data(session_id)
    hotel_offers = session['hotel_offers']

    if not hotel_offers:
        return {"error": "No hotel search has been performed yet."}
    if hotel_number < 1 or hotel_number > len(hotel_offers):
        return {"error": f"Invalid hotel number. Please choose a number between 1 and {len(hotel_offers)}."}

    hotel_to_book = hotel_offers[hotel_number - 1]
    return await amadeus_book_hotel(hotel_to_book, guest_firstname, guest_lastname, guest_email, guest_phone)


async def search_rental_cars(session_id: str, location: str, pick_up_date: str, pick_up_time: str, drop_off_date: str, drop_off_time: str):
    session = get_session_data(session_id)
    response = await amadeus_search_rental_cars(location, pick_up_date, pick_up_time, drop_off_date, drop_off_time)

    if isinstance(response, dict) and 'error' in response:
        return response

    session['rental_car_offers'] = response
    return response


async def book_rental_car(session_id: str, car_number: int, traveler_firstname: str, traveler_lastname: str, traveler_email: str, traveler_phone: str = None):
    session = get_session_data(session_id)
    rental_car_offers = session['rental_car_offers']

    if not rental_car_offers:
        return {"error": "No rental car search has been performed yet."}
    if car_number < 1 or car_number > len(rental_car_offers):
        return {"error": f"Invalid car number. Please choose a number between 1 and {len(rental_car_offers)}."}

    car_to_book = rental_car_offers[car_number - 1]
    return await amadeus_book_rental_car(car_to_book, traveler_firstname, traveler_lastname, traveler_email, traveler_phone)


# Map function names to their implementations
FUNCTION_MAP = {
    "search_flights": search_flights,
    "price_flight_offer": price_flight_offer,
    "book_flight": book_flight,
    "search_hotels_by_city": search_hotels_by_city,
    "book_hotel": book_hotel,
    "search_rental_cars": search_rental_cars,
    "book_rental_car": book_rental_car
}


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)


manager = ConnectionManager()


@app.get("/")
async def root():
    return {"message": "Welcome to the Chat API"}


@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    # Generate a unique session ID for this WebSocket connection
    session_id = str(id(websocket))
    logger.info(f"New WebSocket connection with session ID: {session_id}")

    try:
        while True:
            data = await websocket.receive_text()
            data_json = json.loads(data)

            logger.info(f"Received WebSocket message: {data[:100]}...")  # Log the first 100 chars
            
            # Convert the received data to our models
            messages = []
            for msg in data_json.get("messages", []):
                # Handle different message structures
                try:
                    # Create a dictionary with only the fields that exist in the message
                    message_data = {"role": msg["role"]}
                    
                    # Add content if it exists
                    if "content" in msg:
                        # Check if content is a nested dictionary with its own content field
                        if isinstance(msg["content"], dict) and "content" in msg["content"]:
                            message_data["content"] = msg["content"]["content"]
                        else:
                            message_data["content"] = msg["content"]
                    else:
                        message_data["content"] = None
                    
                    # Add tool_calls if they exist
                    if "tool_calls" in msg:
                        message_data["tool_calls"] = msg["tool_calls"]
                    
                    # Add tool_call_id if it exists
                    if "tool_call_id" in msg:
                        message_data["tool_call_id"] = msg["tool_call_id"]
                    
                    # Create the ChatMessage with the appropriate fields
                    chat_message = ChatMessage(**message_data)
                    messages.append(chat_message)
                except Exception as e:
                    logger.error(f"Error creating ChatMessage: {str(e)}, message data: {msg}")
                    raise
            
            # Remove any existing system prompt and add the server-side one
            messages = [msg for msg in messages if msg.role != "system"]
            messages.insert(0, ChatMessage(role="system", content=SYSTEM_PROMPT))
            
            # Create the chat request with tools
            chat_request = ChatRequest(
                messages=messages,
                model=data_json.get("model", "gpt-3.5-turbo"),
                temperature=data_json.get("temperature", 0.7),
                tools=AVAILABLE_FUNCTIONS  # Add tools to the request
            )
            
            # Log the request being sent to OpenAI
            logger.info(f"Sending request to OpenAI with tools: {len(AVAILABLE_FUNCTIONS)} tools included")
            
            # Send acknowledgment that message. I will now create the new content for `main.py` and use the `replace` tool to update the file. was received
            await websocket.send_json({
                "type": "message_received",
                "message": "Processing your request..."
            })
            
            # Generate response from OpenAI
            response = await generate_chat_response(chat_request)
            
            # Log the raw response for debugging
            logger.info(f"Raw response from OpenAI: {response}")
            
            # Check if the response contains a function call
            if response.get("tool_calls"):
                logger.info(f"Response contains tool calls: {response['tool_calls']}")
                
                # Create a new list of messages for the follow-up request
                follow_up_messages = messages.copy()  # Start with the original messages
                
                # Add the assistant response with tool_calls
                assistant_message_dict = {
                    "role": "assistant",
                    "content": response.get("content"),
                    "tool_calls": response.get("tool_calls")
                }
                follow_up_messages.append(ChatMessage(**assistant_message_dict))
                
                # Process each tool call
                for tool_call in response.get("tool_calls", []):
                    try:
                        function_name = tool_call["function"]["name"]
                        function_args = json.loads(tool_call["function"]["arguments"])

                        logger.info(f"Executing function: {function_name} with args: {function_args}")

                        # Execute the function if it exists in our map
                        if function_name in FUNCTION_MAP:
                            # Inject session_id as the first parameter for all functions
                            function_response = await FUNCTION_MAP[function_name](session_id, **function_args)
                            
                            # Add the tool response
                            tool_message_dict = {
                                "role": "tool",
                                "content": json.dumps(function_response),
                                "tool_call_id": tool_call["id"]
                            }
                            follow_up_messages.append(ChatMessage(**tool_message_dict))
                    except Exception as e:
                        logger.error(f"Error executing function {function_name}: {str(e)}")
                        # Add an error message as the tool response
                        tool_message_dict = {
                            "role": "tool",
                            "content": json.dumps({"error": str(e)}),
                            "tool_call_id": tool_call["id"]
                        }
                        follow_up_messages.append(ChatMessage(**tool_message_dict))
                
                # Create a new request with the updated messages
                follow_up_request = ChatRequest(
                    messages=follow_up_messages,
                    model=chat_request.model,
                    temperature=chat_request.temperature,
                    tools=chat_request.tools
                )
                
                # Get a new response with the function results
                try:
                    logger.info("Sending follow-up request with tool results")
                    response = await generate_chat_response(follow_up_request)
                except Exception as e:
                    logger.error(f"Error getting final response after tool calls: {str(e)}")
                    response = {"content": f"I'm sorry, I encountered an error processing your request. {str(e)}"}
            
            logger.info("Sending response back to client")
            
            # Send the response back to the client with a consistent format
            # Make sure we're sending just the content string, not a nested object
            content = response.get("content", "")
            if content is None:
                content = ""
            
            # Log what we're sending to help debug
            logger.info(f"Sending message to client: {content[:100]}...")
            
            await websocket.send_json({
                "type": "chat_response",
                "message": content,  # Send just the content string
                "role": "assistant"
            })
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected, cleaning up session: {session_id}")
        manager.disconnect(websocket)
        # Clean up session data to prevent memory leaks
        if session_id in session_data:
            del session_data[session_id]
    except Exception as e:
        logger.error(f"Error in WebSocket handler: {str(e)}", exc_info=True)
        # Clean up session on error
        if session_id in session_data:
            del session_data[session_id]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)

