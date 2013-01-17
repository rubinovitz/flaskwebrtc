import os
from werkzeug import SharedDataMiddleware
from flask import Flask, request, Response, render_template
import datetime
import logging
import os
import random
import re
import json
import jinja2
from socketio import socketio_manage
from socketio import socketio_manage
from socketio.namespace import BaseNamespace
from socketio.mixins import RoomsMixin, BroadcastMixin
import redis 
from Room import *

app = Flask(__name__)

# Set the channel token expiration to 30 min, instead 120 min by default.
TOKEN_TIMEOUT = 30

def generate_random(len):
	word = ''
	for i in range(len):
		word += random.choice('0123456789')
	return word

def sanitize(key):
	return re.sub('[^a-zA-Z0-9\-]', '-', key)

def handle_message(room, user, message):
	message_obj = json.loads(message)
	other_user = room.get_other_user(user)
	room_key = room.key().id_or_name();
	if message_obj['type'] == 'tokenRequest':
		token = create_channel(room, user, TOKEN_TIMEOUT)
		channel.send_message(make_client_id(room, user),
												 json.dumps({"type":"tokenResponse", "token": token}))

	if message_obj['type'] == 'bye':
		room.remove_user(user)
		logging.info('User ' + user + ' quit from room ' + room_key)
		logging.info('Room ' + room_key + ' has state ' + str(room))
	if other_user:
		# special case the loopback scenario
		if message_obj['type'] == 'offer' and other_user == user:
			message = message.replace("\"offer\"", "\"answer\"")
			message = message.replace("a=ice-options:google-ice\\r\\n", "")
		on_message(room, other_user, message)

def get_saved_messages(client_id):
	return Message.gql("WHERE client_id = :id", id=client_id)

def delete_saved_messages(client_id):
	messages = get_saved_messages(client_id)
	for message in messages:
		message.delete()
		logging.info('Deleted the saved message for ' + client_id)

def send_saved_messages(client_id):
	messages = get_saved_messages(client_id)
	for message in messages:
		channel.send_message(client_id, message.msg)
		logging.info('Delivered saved message to ' + client_id);
		message.delete()

def on_message(room, user, message):
	client_id = make_client_id(room, user)
	if room.is_connected(user):
		channel.send_message(client_id, message)
		logging.info('Delivered message to user ' + user);
	else:
		new_message = Message(id = client_id, msg = message)
		new_message.put()
		logging.info('Saved message for user ' + user)

def append_url_arguments(request, link):
	for argument in request.arguments():
		if argument != 'r':
			link += '&' + argument + '=' + request.get(argument)
	return link


# This database is to store the messages from the sender client when the
# receiver client is not ready to receive the messages.
# Use TextProperty instead of StringProperty for msg because
# the session description can be more than 500 characters.

@app.route('/_ah/channel/connected/', methods=["POST","GET"])
def connectPage():
		key = request.args['from']
		room_key, user = key.split('/')
		room = Room.get_by_key_name(room_key)
		# Check if room has user in case that disconnect message comes before
		# connect message with unknown reason, observed with local AppEngine SDK.
		if room and room.has_user(user):
			room.set_connected(user)
			send_saved_messages(make_client_id(room, user))
			logging.info('User ' + user + ' connected to room ' + room_key)
		else:
			logging.warning('Unexpected Connect Message to room ' + room_key)

@app.route('/_ah/channel/disconnected/', methods=['GET','POST'])
def post():
		key = request.args['from']
		room_key, user = key.split('/')
		room = Room.get_by_key_name(room_key)
		if room and room.has_user(user):
			other_user = room.get_other_user(user)
			room.remove_user(user)
			logging.info('User ' + user + ' removed from room ' + room_key)
			logging.info('Room ' + room_key + ' has state ' + str(room))
			if other_user:
				channel.send_message(make_client_id(room, other_user), '{"type":"bye"}')
				logging.info('Sent BYE to ' + other_user)
		logging.warning('User ' + user + ' disconnected from room ' + room_key)


@app.route('/')
def index():
	return render_template('index.html')



@app.route('/room/<roomName>/')
def enterRoom(roomName):
	print 'inside room'
	rooms = redis.StrictRedis(host='localhost', port=6379, db=0) #keyvalue store of ('room name', [list of occupants])
	print rooms
	stun_server = os.getenv('stunServer')
	user = None
	initiator = 0
	print 'before redis'
	try:
		numberOfOccs = rooms.llen(roomName) # number of users in room
	except:
		print 'first call'
	try:
		print numberOfOccs
	except:
		print 'second call'
	print 'after redis'
	if numberOfOccs == 1: # if someone is already in the room
		user = generate_random(8) # generate usernumber
		rooms.lpush(roomName, user) # add user to room
		initiator = 0
		print 'one occs'
	if numberOfOccs == 0: # if room doesn't exist yet
		# generate new room
		print 'zero occs'
		user = generate_random(8)
		try:
			rooms.lpush(roomName, user) # push user to room
		except:
			print 'cannot push user into room'
		initiator = 1
	room_link = 'http://localhost:5000/room/' + roomName
	
	return render_template('index.html',me = user,room_key='test',room_link= room_link,initiator=initiator)
@app.route('/socket.io/<path:remaining>')
def socketio(remaining):
    try:
        socketio_manage(request.environ, {'/roomsocket': RoomNamespace}, request)
    except:
        app.logger.error("Exception while handling socketio connection",
                         exc_info=True)
    return "out"

# store static files on server for now
app.wsgi_app = SharedDataMiddleware(app.wsgi_app, {
'/': os.path.join(os.path.dirname(__file__), 'static')
})

if __name__ == '__main__':
	app.run(DEBUG=True)
