from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from twilio.rest import Client
import uuid
import logging
import os

# --- Basic Flask App Setup ---
logging.basicConfig(level=logging.INFO)
app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a-very-secret-key-for-dev')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# --- Twilio Configuration ---
# Securely loads credentials from environment variables set in the hosting platform (e.g., Render).
# The application will not expose these keys in the code.
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')

# --- In-Memory Data Stores ---
# These track users and rooms. For a larger app, you might use a database like Redis.
waiting_users = []
active_rooms = {}  # room_id -> {user1_sid, user2_sid}
user_to_room = {}  # user_sid -> room_id
connected_clients = {} # sid -> True

def update_user_count():
    """Calculates and broadcasts the current number of connected users to everyone."""
    count = len(connected_clients)
    logging.info(f"Broadcasting user count: {count}")
    emit('user_count_update', {'count': count}, broadcast=True)

# --- HTTP Routes ---
@app.route('/')
def index():
    """Serves the main index.html page."""
    return render_template('index.html')

@app.route('/api/get-ice-servers')
def get_ice_servers():
    """
    API endpoint to fetch STUN/TURN server credentials from Twilio.
    This is called by the frontend to ensure reliable P2P connections.
    """
    # Check if Twilio credentials are provided in the environment.
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        logging.warning("Twilio credentials not set. Using fallback STUN server.")
        # Provide a public STUN server as a fallback.
        return jsonify([{"urls": "stun:stun.l.google.com:19302"}])
        
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        # Fetch a fresh token from Twilio. This includes a list of STUN and TURN servers.
        token = client.tokens.create()
        logging.info("Successfully fetched ICE servers from Twilio.")
        return jsonify(token.ice_servers)
    except Exception as e:
        logging.error(f"Failed to fetch ICE servers from Twilio: {e}")
        # Provide a public STUN server as a fallback if the API call fails.
        return jsonify([{"urls": "stun:stun.l.google.com:19302"}])

# --- SocketIO Event Handlers ---
@socketio.on('connect')
def on_connect():
    """Handles a new user connecting to the server."""
    user_id = request.sid
    connected_clients[user_id] = True
    logging.info(f'User connected: {user_id}. Total users: {len(connected_clients)}')
    update_user_count()

@socketio.on('disconnect')
def on_disconnect():
    """Handles a user disconnecting and cleans up their state."""
    user_id = request.sid
    
    if user_id in connected_clients:
        del connected_clients[user_id]
    
    logging.info(f'User disconnected: {user_id}. Total users: {len(connected_clients)}')
    update_user_count()
    
    if user_id in waiting_users:
        waiting_users.remove(user_id)
    
    if user_id in user_to_room:
        room_id = user_to_room[user_id]
        if room_id in active_rooms:
            # Find the other user in the room and notify them of the disconnect.
            other_user_id = next((uid for uid in active_rooms[room_id] if uid != user_id), None)
            if other_user_id:
                emit('user_disconnected', room=other_user_id)
                if other_user_id in user_to_room:
                    del user_to_room[other_user_id]
            
            # Clean up the room.
            del active_rooms[room_id]
        
        del user_to_room[user_id]

@socketio.on('find_stranger')
def find_stranger():
    """Matches two waiting users into a private chat room."""
    user_id = request.sid
    if user_id in user_to_room:
        return

    if user_id not in waiting_users:
        waiting_users.append(user_id)

    if len(waiting_users) >= 2:
        p1_id = waiting_users.pop(0)
        p2_id = waiting_users.pop(0)
        
        room_id = str(uuid.uuid4())
        active_rooms[room_id] = {p1_id, p2_id}
        user_to_room[p1_id] = room_id
        user_to_room[p2_id] = room_id
        
        join_room(room_id, sid=p1_id)
        join_room(room_id, sid=p2_id)
        
        logging.info(f'Match found! Room: {room_id}, Users: {p1_id}, {p2_id}')
        emit('match_found', {'room_id': room_id}, room=room_id)
    else:
        emit('waiting_for_match')

@socketio.on('end_chat')
def end_chat():
    """Handles a user manually ending a chat and cleans up the room."""
    user_id = request.sid
    if user_id in user_to_room:
        room_id = user_to_room[user_id]
        emit('chat_ended', room=room_id, include_self=True)
        
        if room_id in active_rooms:
            for uid in list(active_rooms[room_id]):
                if uid in user_to_room:
                    del user_to_room[uid]
                leave_room(room_id, sid=uid)
            del active_rooms[room_id]

# --- WebRTC Signaling Relays ---
# These handlers simply relay WebRTC signals (offer, answer, candidates)
# from one user to the other user in their private room.
def handle_webrtc_event(event_name, data):
    user_id = request.sid
    if user_id in user_to_room:
        room_id = user_to_room[user_id]
        emit(event_name, data, room=room_id, include_self=False)

@socketio.on('offer')
def handle_offer(data):
    handle_webrtc_event('offer', data)

@socketio.on('answer')
def handle_answer(data):
    handle_webrtc_event('answer', data)

@socketio.on('ice_candidate')
def handle_ice_candidate(data):
    handle_webrtc_event('ice_candidate', data)

# --- Main Entry Point ---
if __name__ == '__main__':
    # This block is for local development only.
    # The 'host' parameter makes the server accessible on your local network.
    logging.info("Starting Flask-SocketIO server for local development.")
    socketio.run(app, host='0.0.0.0', port=5001, debug=True)