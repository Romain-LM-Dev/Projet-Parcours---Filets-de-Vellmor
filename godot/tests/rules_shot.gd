## Capture (fenêtre) : trois lacs, une réserve de rive, une réserve au large et un lac au repos.
##   godot --path godot -s res://tests/rules_shot.gd -- --out=C:/chemin/rules.png
extends SceneTree


func _initialize() -> void:
	var out := "user://rules.png"
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--out="):
			out = a.substr(6)
	var W = load("res://scripts/world_view.gd")
	var w = W.new()
	w.size = Vector2(1000, 700)
	root.add_child(w)
	await process_frame
	var names := ["Ostrel", "Bramois", "Tilque"]
	var lk := [{"name": "vellmor", "label": "Lac de Vellmor", "capacity": 60.0, "stock": 40.0, "villages": ["Ostrel"]},
		{"name": "orsane", "label": "Lac d'Orsane", "capacity": 60.0, "stock": 40.0, "villages": ["Bramois"]},
		{"name": "bremol", "label": "Lac de Brémol", "capacity": 60.0, "stock": 40.0, "villages": ["Tilque"]}]
	w.reset_world([], 100.0, 30.0, names, lk, {"size": 1.5, "grid": 45})
	w.on_event({"type": "season_start", "season": 1, "payload": {}})
	w.on_event({"type": "norm_adopted", "season": 1, "payload": {"scope": "valley", "kind": "reserve", "target": "Ostrel", "value": 1, "text": "rive d'Ostrel interdite à la pêche, 2 saisons", "effective_season": 2, "until_season": 3, "supporters": []}})
	w.on_event({"type": "norm_adopted", "season": 1, "payload": {"scope": "valley", "kind": "repos", "target": "orsane", "value": 1, "text": "Lac d'Orsane fermé, 2 saisons", "effective_season": 2, "until_season": 3, "supporters": []}})
	w.on_event({"type": "norm_adopted", "season": 1, "payload": {"scope": "valley", "kind": "reserve", "target": "large-bremol", "value": 1, "text": "large de Brémol interdit", "effective_season": 2, "until_season": 3, "supporters": []}})
	for i in 5:
		await process_frame
	await create_timer(0.5).timeout
	root.get_viewport().get_texture().get_image().save_png(out)
	quit()
