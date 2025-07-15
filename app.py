from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
import uuid
import logging
import os

# --- Basic Flask App Setup ---
logging.basicConfig(level=logging.INFO)
app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-12345')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# --- In-Memory Data Stores ---
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
    API endpoint to provide STUN/TURN servers for WebRTC connections.
    Uses reliable public servers that work consistently.
    """
    # Use multiple reliable public STUN/TURN servers
    ice_servers = [
        {"urls": "stun:stun.l.google.com:19302"},
        {"urls": "stun:stun1.l.google.com:19302"},
        {"urls": "stun:stun2.l.google.com:19302"},
        {"urls": "stun:stun3.l.google.com:19302"},
        {"urls": "stun:stun4.l.google.com:19302"},
        # Free TURN servers for users behind NAT
        {
            "urls": "turn:openrelay.metered.ca:80",
            "username": "openrelayproject",
            "credential": "openrelayproject"
        },
        {
            "urls": "turn:openrelay.metered.ca:443",
            "username": "openrelayproject", 
            "credential": "openrelayproject"
        },
        {
            "urls": "turn:openrelay.metered.ca:443?transport=tcp",
            "username": "openrelayproject",
            "credential": "openrelayproject"
        }
    ]
    
    logging.info("Providing ICE servers for WebRTC connection")
    return jsonify(ice_servers)

@app.route('/health')
def health_check():
    """Health check endpoint for monitoring"""
    return jsonify({
        'status': 'healthy',
        'connected_users': len(connected_clients),
        'active_rooms': len(active_rooms),
        'waiting_users': len(waiting_users)
    })

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
    logging.info("Starting Flask-SocketIO server for local development.")
    socketio.run(app, host='0.0.0.0', port=5001, debug=True)
