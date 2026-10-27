## Test hors fenêtre de la carte : pour 1 à 8 villages, aucun chemin de terre ne traverse le lac, et les marches des villageois
## (de leur village vers l'anneau du conseil) le contournent.
##   godot --headless --path godot -s res://tests/roads_test.gd
extends SceneTree

var fails := 0


func check(cond: bool, what: String) -> void:
	if not cond:
		fails += 1
		print("FAIL ", what)


func _initialize() -> void:
	var W = load("res://scripts/world_view.gd")
	var w = W.new()
	w.size = Vector2(1100, 760)
	root.add_child(w)
	await process_frame
	var names := ["Ostrel", "Bramois", "Tilque", "Hennad", "Varenne", "Corbel", "Mirande", "Sauvet"]
	for n in range(1, 9):
		w.hamlet_pos = W.layout(names.slice(0, n))
		w._generate_decor()
		var wet := 0
		for path in w.deco["paths"]:
			for q in path:
				if w.lake_rn(w._nm(q)) < 0.99:
					wet += 1
		check(wet == 0, "%d villages : %d points de chemin sur l'eau" % [n, wet])
		for h in w.hamlet_pos:
			var start: Vector2 = w.hamlet_pos[h]
			for k in 12:
				var ang := TAU * float(k) / 12.0
				var target: Vector2 = w.LAKE_C + Vector2(cos(ang), sin(ang)) * w.RING_R
				var last := start
				for step in w._land_route(start, target):
					for i in 9:
						if w.lake_rn(last.lerp(step, float(i) / 8.0)) < 0.99:
							check(false, "%d villages : %s → anneau %d traverse le lac" % [n, h, k])
					last = step
	print("ROADSTEST fails=%d" % fails)
	quit(1 if fails > 0 else 0)
