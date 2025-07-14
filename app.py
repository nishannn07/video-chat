from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import uuid
import logging
import os

logging.basicConfig(level=logging.INFO)

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a-very-secret-key')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# In-memory data stores
waiting_users = []
active_rooms = {}  # room_id -> {user1_sid, user2_sid}
user_to_room = {}  # user_sid -> room_id
# NEW: Store total connected clients to easily get a count
connected_clients = {} # sid -> True

def update_user_count():
    """Calculates and broadcasts the current number of connected users."""
    count = len(connected_clients)
    logging.info(f"Broadcasting user count: {count}")
    emit('user_count_update', {'count': count}, broadcast=True)

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def on_connect():
    user_id = request.sid
    # NEW: Add user to our connected list and update everyone
    connected_clients[user_id] = True
    logging.info(f'User connected: {user_id}. Total users: {len(connected_clients)}')
    update_user_count()

@socketio.on('disconnect')
def on_disconnect():
    user_id = request.sid
    
    # NEW: Remove user from our connected list and update everyone
    if user_id in connected_clients:
        del connected_clients[user_id]
    
    logging.info(f'User disconnected: {user_id}. Total users: {len(connected_clients)}')
    update_user_count()
    
    if user_id in waiting_users:
        waiting_users.remove(user_id)
        logging.info(f'Removed {user_id} from waiting queue.')

    if user_id in user_to_room:
        room_id = user_to_room[user_id]
        if room_id in active_rooms:
            other_user_id = next((uid for uid in active_rooms[room_id] if uid != user_id), None)
            if other_user_id:
                emit('user_disconnected', room=other_user_id)
                logging.info(f'Notified {other_user_id} of disconnection from room {room_id}.')
                if other_user_id in user_to_room:
                    del user_to_room[other_user_id]
            
            del active_rooms[room_id]
            logging.info(f'Cleaned up room: {room_id}')
        
        del user_to_room[user_id]

# ... (the rest of your app.py remains the same) ...

@socketio.on('find_stranger')
def find_stranger():
    user_id = request.sid
    logging.info(f'User {user_id} is looking for a stranger.')

    if user_id in user_to_room:
        logging.warning(f'User {user_id} tried to find a stranger while already in a room.')
        return

    if user_id not in waiting_users:
        waiting_users.append(user_id)

    if len(waiting_users) >= 2:
        partner_1_id = waiting_users.pop(0)
        partner_2_id = waiting_users.pop(0)
        
        room_id = str(uuid.uuid4())
        
        active_rooms[room_id] = {partner_1_id, partner_2_id}
        user_to_room[partner_1_id] = room_id
        user_to_room[partner_2_id] = room_id
        
        join_room(room_id, sid=partner_1_id)
        join_room(room_id, sid=partner_2_id)
        
        logging.info(f'Match found! Room: {room_id}, Users: {partner_1_id}, {partner_2_id}')
        
        emit('match_found', {'room_id': room_id}, room=room_id)
    else:
        emit('waiting_for_match')
        logging.info(f'User {user_id} is now waiting.')

@socketio.on('end_chat')
def end_chat():
    user_id = request.sid
    if user_id in user_to_room:
        room_id = user_to_room[user_id]
        logging.info(f'User {user_id} is ending chat in room {room_id}.')
        
        emit('chat_ended', room=room_id, include_self=True)
        
        if room_id in active_rooms:
            for uid in list(active_rooms[room_id]):
                if uid in user_to_room:
                    del user_to_room[uid]
                leave_room(room_id, sid=uid)
            del active_rooms[room_id]
            logging.info(f'Room {room_id} has been closed and cleaned up.')


def handle_webrtc_event(event_name, data):
    user_id = request.sid
    if user_id in user_to_room:
        room_id = user_to_room[user_id]
        emit(event_name, data, room=room_id, include_self=False)
        logging.info(f'Relaying "{event_name}" from {user_id} in room {room_id}')

@socketio.on('offer')
def handle_offer(data):
    handle_webrtc_event('offer', data)

@socketio.on('answer')
def handle_answer(data):
    handle_webrtc_event('answer', data)

@socketio.on('ice_candidate')
def handle_ice_candidate(data):
    handle_webrtc_event('ice_candidate', data)


if __name__ == '__main__':
    # Binds to all network interfaces, making it accessible on your local network
    socketio.run(app, host='0.0.0.0', port=5001, debug=True)