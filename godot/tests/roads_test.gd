## Test hors fenêtre de la carte : pour 1 à 8 villages, aucun chemin de terre ne traverse le lac, les maisons sont sur la terre et sur
## leurs lots, et les marches des villageois (de leur village vers l'anneau du conseil) contournent l'eau et les maisons ; la caméra
## zoome vers le pointeur et ne sort pas de la carte.
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
				if w.water_at(w._nm(q)) > 0.55:
					wet += 1
		check(wet == 0, "%d villages : %d points de chemin sur l'eau" % [n, wet])
		check(w.deco["houses"].size() >= 1 + 3 * n, "%d villages : des maisons autour de chaque place (%d)" % [n, w.deco["houses"].size()])
		var lots := {}
		for hs in w.deco["houses"]:
			check(not w.is_water(hs["n"]), "%d villages : une maison sur l'eau" % n)
			check(not lots.has(hs["lot"]), "%d villages : deux maisons sur le même lot" % n)
			lots[hs["lot"]] = true
			for st in hs["foot"]:
				check(w.walk.is_point_solid(st), "%d villages : le pied d'une maison est un obstacle" % n)
		for h in w.hamlet_pos:
			var start: Vector2 = w.hamlet_pos[h]
			for k in 12:
				var ang := TAU * float(k) / 12.0
				var target: Vector2 = w.LAKE_C + Vector2(cos(ang), sin(ang)) * w.RING_R
				var last := start
				var steps: Array = w._land_route(start, target)
				for i in steps.size():
					var step: Vector2 = steps[i]
					for j in 9:
						if w.water_at(last.lerp(step, float(j) / 8.0)) > 0.55:
							check(false, "%d villages : %s → anneau %d traverse le lac" % [n, h, k])
					if i < steps.size() - 1 and w.walk.is_point_solid(w._step_of(step)):
						check(false, "%d villages : %s → anneau %d passe dans une maison" % [n, h, k])
					last = step
	# la caméra : zoomer vers un point le garde sous le pointeur, et la carte couvre toujours le cadre
	var p := Vector2(300, 200)
	var under: Vector2 = (p - w.cam_off) / w.zoom
	w.zoom_at(p, 2.0)
	check(is_equal_approx(w.zoom, 2.0) and ((p - w.cam_off) / w.zoom).distance_to(under) < 0.01, "le zoom garde le point sous le pointeur")
	w.pan(Vector2(5000, 5000))
	check(w.cam_off.x <= 0.0 and w.cam_off.y <= 0.0, "on ne fait pas glisser la carte hors du cadre")
	w.pan(Vector2(-50000, -50000))
	check(w.cam_off.x >= w.size.x * (1.0 - w.zoom) - 0.01, "ni de l'autre côté")
	w.zoom_at(p, 0.01)
	check(is_equal_approx(w.zoom, 1.0) and w.cam_off == Vector2.ZERO, "au zoom 1, toute la vallée tient dans le cadre")
	print("ROADSTEST fails=%d" % fails)
	quit(1 if fails > 0 else 0)
