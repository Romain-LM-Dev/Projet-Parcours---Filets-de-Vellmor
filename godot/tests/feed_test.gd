## Test hors réseau : rejoue un fichier d'événements dans la vue et vérifie l'état visuel.
##   godot --headless --path godot -s res://tests/feed_test.gd -- --events=/chemin/events.jsonl
extends SceneTree


func _initialize() -> void:
	var path := ""
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--events="):
			path = a.substr(9)
	var WV = load("res://scripts/world_view.gd")
	var w = WV.new()
	w.size = Vector2(1000, 800)
	root.add_child(w)
	w.animate = true
	var f := FileAccess.open(path, FileAccess.READ)
	var fails := 0
	var n := 0
	while not f.eof_reached():
		var line := f.get_line()
		if line.strip_edges() == "":
			continue
		var ev: Dictionary = JSON.parse_string(line)
		var p: Dictionary = ev["payload"]
		if ev["type"] == "run_start":
			w.reset_world(p["agents"], float(p["lake"]["capacity"]), float(p["season_days"]))
		w.on_event(ev)
		n += 1
		if ev["type"] == "assembly_end" and w.assembly_scope != "":
			print("FAIL assembly_scope after end: ", w.assembly_scope, " seq ", ev["seq"])
			fails += 1
		if ev["type"] == "assembly_start" and str(p["scope"]) == "valley" and w.assembly_scope != "valley":
			print("FAIL start")
			fails += 1
	print("FEEDTEST events=%d fails=%d scope=%s fish=%d" % [n, fails, w.assembly_scope, w.fish.size()])
	quit(1 if fails else 0)
