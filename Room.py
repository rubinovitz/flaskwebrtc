import os	
from socketio import socketio_manage
from socketio.namespace import BaseNamespace
from socketio.mixins import RoomsMixin, BroadcastMixin
from gevent import monkey

monkey.patch_all()

class RoomNamespace(BaseNamespace, RoomsMixin, BroadcastMixin):
	"""
	socket handling for rooms
	"""
	def initialize(self):
		print "Socketio session started"

	def log(self, message):
		self.logger.info("[{0}] {1}".format(self.socket.sessid, message))
						   
