## Client WebSocket vers le pont FILETS (ws_bridge.py).
## Reçoit {"topic": ..., "data": ...}, envoie les commandes d'injection en JSON.
extends Node

signal message(topic: String, data: Dictionary)
signal status_changed(text: String, connected: bool)

var url := "ws://127.0.0.1:8765"
var _ws := WebSocketPeer.new()
var _state := -1
var _retry := 0.0
const MAX_PER_FRAME := 3000


func _ready() -> void:
	_open()


func _open() -> void:
	_ws = WebSocketPeer.new()
	_ws.inbound_buffer_size = 1 << 23
	_ws.max_queued_packets = 1 << 17
	var err := _ws.connect_to_url(url)
	if err != OK:
		status_changed.emit("connexion impossible (%s)" % error_string(err), false)


func _process(delta: float) -> void:
	_ws.poll()
	var st := _ws.get_ready_state()
	if st != _state:
		_state = st
		match st:
			WebSocketPeer.STATE_OPEN:
				status_changed.emit("connecté · " + url, true)
			WebSocketPeer.STATE_CONNECTING:
				status_changed.emit("connexion à " + url + "…", false)
			WebSocketPeer.STATE_CLOSED:
				status_changed.emit("déconnecté · nouvel essai…", false)
	if st == WebSocketPeer.STATE_OPEN:
		var n := 0
		while _ws.get_available_packet_count() > 0 and n < MAX_PER_FRAME:
			var raw := _ws.get_packet().get_string_from_utf8()
			var parsed: Variant = JSON.parse_string(raw)
			if typeof(parsed) == TYPE_DICTIONARY:
				var d: Dictionary = parsed
				var payload: Variant = d.get("data", {})
				if typeof(payload) == TYPE_DICTIONARY:
					message.emit(str(d.get("topic", "")), payload)
			n += 1
	elif st == WebSocketPeer.STATE_CLOSED:
		_retry -= delta
		if _retry <= 0.0:
			_retry = 2.0
			_open()


func send(cmd: Dictionary) -> bool:
	if _ws.get_ready_state() != WebSocketPeer.STATE_OPEN:
		return false
	_ws.send_text(JSON.stringify(cmd))
	return true


func pending() -> int:
	return _ws.get_available_packet_count()
