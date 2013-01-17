#!/usr/bin/python2.4
#
# Copyright 2011 Google Inc. All Rights Reserved.

# pylint: disable-msg=C6310

"""WebRTC Demo

This module demonstrates the WebRTC API by implementing a simple video chat app.
"""

import datetime
import logging
import os
import random
import re
import json
import jinja2
import webapp2
from google.appengine.api import channel
from google.appengine.ext import db

jinja_environment = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)))
# Set the channel token expiration to 30 min, instead 120 min by default.
TOKEN_TIMEOUT = 30

def generate_random(len):
  word = ''
  for i in range(len):
    word += random.choice('0123456789')
  return word

def sanitize(key):
  return re.sub('[^a-zA-Z0-9\-]', '-', key)

def make_client_id(room, user):
  return room.key().id_or_name() + '/' + user

def make_pc_config(stun_server, turn_server, ts_pwd):
  servers = []
  if turn_server:
    turn_config = 'turn:{}'.format(turn_server)
    servers.append({'url':turn_config, 'credential':ts_pwd})
  if stun_server:
    stun_config = 'stun:{}'.format(stun_server)
  else:
    stun_config = 'stun:' + 'stun.l.google.com:19302'
  servers.append({'url':stun_config})
  return {'iceServers':servers}

def create_channel(room, user, duration_minutes):
  client_id = make_client_id(room, user)
  return channel.create_channel(client_id, duration_minutes)

def handle_message(room, user, message):
  message_obj = json.loads(message)
  other_user = room.get_other_user(user)
  room_key = room.key().id_or_name();
  if message_obj['type'] == 'tokenRequest':
    token = create_channel(room, user, TOKEN_TIMEOUT)
    channel.send_message(make_client_id(room, user),
                         json.dumps({"type":"tokenResponse", "token": token}))
    return

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

def make_constraints(hd_video):
  constraints = { 'optional': [], 'mandatory': {} }
  # Demo 16:9 video with media constraints.
  if hd_video.lower() == 'true':
    # Demo with WHD by setting size with 1280x720.
    constraints['mandatory']['minHeight'] = 720
    constraints['mandatory']['minWidth'] = 1280
    # Disabled for now due to weird stretching behavior on Mac. 
    #else:
    # Demo with WVGA by setting Aspect Ration;
    #constraints['mandatory']['maxAspectRatio'] = 1.778
    #constraints['mandatory']['minAspectRatio'] = 1.777

  return constraints

def append_url_arguments(request, link):
  for argument in request.arguments():
    if argument != 'r':
      link += '&' + argument + '=' + request.get(argument)
  return link

# This database is to store the messages from the sender client when the
# receiver client is not ready to receive the messages.
# Use TextProperty instead of StringProperty for msg because
# the session description can be more than 500 characters.
class Message(db.Model):
  token = db.StringProperty()
  msg = db.TextProperty()

class Room(db.Model):
  """All the data we store for a room"""
  user1 = db.StringProperty()
  user2 = db.StringProperty()
  user1_connected = db.BooleanProperty(default=False)
  user2_connected = db.BooleanProperty(default=False)

  def __str__(self):
    str = '['
    if self.user1:
      str += "%s-%r" % (self.user1, self.user1_connected)
    if self.user2:
      str += "%s-%r" % (self.user2, self.user2_connected)
    str += ']'
    return str

  def get_occupancy(self):
    occupancy = 0
    if self.user1:
      occupancy += 1
    if self.user2:
      occupancy += 1
    return occupancy

  def get_other_user(self, user):
    if user == self.user1:
      return self.user2
    elif user == self.user2:
      return self.user1
    else:
      return None

  def has_user(self, user):
    return (user and (user == self.user1 or user == self.user2))

  def add_user(self, user):
    if not self.user1:
      self.user1 = user
    elif not self.user2:
      self.user2 = user
    else:
      raise RuntimeError('room is full')
    self.put()

  def remove_user(self, user):
    delete_saved_messages(make_client_id(self, user))
    if user == self.user2:
      self.user2 = None
    if user == self.user1:
      if self.user2:
        self.user1 = self.user2
        self.user2 = None
      else:
        self.user1 = None
    if self.get_occupancy() > 0:
      self.put()
    else:
      self.delete()

  def set_connected(self, user):
    if user == self.user1:
      self.user1_connected = True
    if user == self.user2:
      self.user2_connected = True
    self.put()

  def is_connected(self, user):
    if user == self.user1:
      return self.user1_connected
    if user == self.user2:
      return self.user2_connected

class ConnectPage(webapp2.RequestHandler):
  def post(self):
    key = self.request.get('from')
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


class DisconnectPage(webapp2.RequestHandler):
  def post(self):
    key = self.request.get('from')
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


class MessagePage(webapp2.RequestHandler):
  def post(self):
    message = self.request.body
    room_key = self.request.get('r')
    user = self.request.get('u')
    room = Room.get_by_key_name(room_key)
    if room:
      handle_message(room, user, message)
    else:
      logging.warning('Unknown room ' + room_key)

class MainPage(webapp2.RequestHandler):
  """The main UI page, renders the 'index.html' template."""

  def get(self):
    """Renders the main page. When this page is shown, we create a new
    channel to push asynchronous updates to the client."""
    room_key = sanitize(self.request.get('r'))
    debug = self.request.get('debug')
    unittest = self.request.get('unittest')
    stun_server = self.request.get('ss')
    turn_server = self.request.get('ts')
    hd_video = self.request.get('hd')
    ts_pwd = self.request.get('tp')

    if unittest:
      # Always create a new room for the unit tests.
      room_key = generate_random(8)

    if not room_key:
      room_key = generate_random(8)
      redirect = '/?r=' + room_key
      redirect = append_url_arguments(self.request, redirect)
      self.redirect(redirect)
      logging.info('Redirecting visitor to base URL to ' + redirect)
      return

    user = None
    initiator = 0
    room = Room.get_by_key_name(room_key)
    if not room and debug != "full":
      # New room.
      user = generate_random(8)
      room = Room(key_name = room_key)
      room.add_user(user)
      if debug != 'loopback':
        initiator = 0
      else:
        room.add_user(user)
        initiator = 1
    elif room and room.get_occupancy() == 1 and debug != 'full':
      # 1 occupant.
      user = generate_random(8)
      room.add_user(user)
      initiator = 1
    else:
      # 2 occupants (full).
      template = jinja_environment.get_template('full.html')
      self.response.out.write(template.render({ 'room_key': room_key }))
      logging.info('Room ' + room_key + ' is full')
      return

    room_link = 'https://apprtc.appspot.com/?r=' + room_key
    room_link = append_url_arguments(self.request, room_link)
    token = create_channel(room, user, TOKEN_TIMEOUT)
    pc_config = make_pc_config(stun_server, turn_server, ts_pwd)
    media_constraints = make_constraints(hd_video)
    template_values = {'token': token,
                       'token_timeout': TOKEN_TIMEOUT*60,
                       'me': user,
                       'room_key': room_key,
                       'room_link': room_link,
                       'initiator': initiator,
                       'pc_config': json.dumps(pc_config),
                       'media_constraints': json.dumps(media_constraints)
                      }
    if unittest:
      target_page = 'test/test_' + unittest + '.html'
    else:
      target_page = 'index.html'

    template = jinja_environment.get_template(target_page)
    self.response.out.write(template.render(template_values))
    logging.info('User ' + user + ' added to room ' + room_key)
    logging.info('Room ' + room_key + ' has state ' + str(room))


app = webapp2.WSGIApplication([
    ('/', MainPage),
    ('/message', MessagePage),
    ('/_ah/channel/connected/', ConnectPage),
    ('/_ah/channel/disconnected/', DisconnectPage)
  ], debug=True)
