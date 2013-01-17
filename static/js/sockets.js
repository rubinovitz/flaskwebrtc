$(function() {
				
	var WEB_SOCKET_SWF_LOCATION = '/static/js/socketio/WebSocketMainswf';
		
	var socket = io.connect('/roomsocket'); // connect to roomNamespace


	socket.on('connect', function (socket) {
		console.log('sockets connected');
		maybeStart();
	});
});
