## Test hors fenêtre de la carte : pour 1 à 8 villages, aucun chemin de terre ne traverse le lac, les maisons sont sur la terre et sur
## leurs lots, et les marches des villageois (de leur village vers l'anneau du conseil) contournent l'eau et les maisons ; la caméra
## zoome vers le pointeur et ne sort pas du monde (la vallée, `map.size` largeurs de carte) ; au zoom minimum, toute la vallée tient dans le
## cadre ; les mailles des maisons et des pas grandissent avec le monde ; `_generate_decor` reste rapide pour la plus grande vallée.
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
				var target: Vector2 = w.council_c + Vector2(cos(ang), sin(ang)) * w.council_r
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
	# la caméra : zoomer vers un point le garde sous le pointeur, et le monde couvre toujours le cadre
	var p := Vector2(300, 200)
	w.zoom_at(p, 2.0)
	var under: Vector2 = (p - w.cam_off) / w.zoom
	w.zoom_at(p, 1.5)
	check(((p - w.cam_off) / w.zoom).distance_to(under) < 0.01, "le zoom garde le point sous le pointeur")
	w.pan(Vector2(5000, 5000))
	check(w.cam_off.x <= 0.0 and w.cam_off.y <= 0.0, "on ne fait pas glisser la carte hors du monde")
	w.pan(Vector2(-500000, -500000))
	check(w.cam_off.x >= w.size.x - w.world.x * w.zoom - 0.01 and w.cam_off.y >= w.size.y - w.world.y * w.zoom - 0.01, "ni de l'autre côté")
	w.zoom_at(p, 0.001)
	check(is_equal_approx(w.zoom, w.zoom_min) and is_equal_approx(w.zoom_min, 1.0 / w.world_k), "zoom minimum = 1 / taille du monde")
	var tl: Vector2 = w._scr(Vector2(0.5, 0.0))
	var br: Vector2 = w._scr(Vector2(0.5, 1.0))
	var lf: Vector2 = w._scr(Vector2(0.0, 1.0))
	var rt: Vector2 = w._scr(Vector2(1.0, 0.0))
	var all_in := true
	for q in [tl, br, lf, rt]:
		all_in = all_in and Rect2(-Vector2.ONE, w.size + Vector2(2, 2)).has_point(q)
	check(all_in, "au zoom minimum, les quatre coins de la vallée sont dans le cadre")
	# mailles proportionnelles à la taille du monde, pas ×5 par lot ; zoom 1 centré sur la vallée à l'ouverture
	for k in [1.0, 1.5, 2.6]:
		w.reset_world([], 100.0, 30.0, [], [], {"size": k})
		check(is_equal_approx(w.world_k, k) and w.n_lots == roundi(24.0 * k) and w.n_steps == w.n_lots * 5, "mailles pour size %s" % k)
		check(w.n_steps % w.n_lots == 0, "STEPS divisible par LOTS")
		check(w.zoom == 1.0 and (w._scr(Vector2(0.5, 0.5)) - w.size * 0.5).length() < 1.0, "zoom 1 centré sur la vallée (size %s)" % k)
		check(absf(w.iso_a - w.size.x * 0.5 * k) < 0.01, "le sol mesure %s largeurs de cadre" % k)
		check(absf(w.iso_b - w.iso_a / 2.0) < 0.01, "dimétrie 2:1 (size %s)" % k)
	w.size = Vector2(700, 900)
	w.reset_world([], 100.0, 30.0, [], [], {"size": 1.5})
	check(absf(w.iso_b - w.iso_a / 2.0) < 0.01, "dimétrie 2:1 aussi dans une fenêtre haute")
	var t0 := Time.get_ticks_usec()
	w._generate_decor()
	var dt := float(Time.get_ticks_usec() - t0) / 1.0e6
	print("DECOR size 2.6 : %.3f s, %d arbres, %d roseaux, %d lucioles" % [dt, w.deco["trees"].size(), w.deco["reeds"].size(), w.deco["flies"].size()])
	check(dt < 0.3, "_generate_decor < 0.3 s pour size 2.6 (%.3f s)" % dt)
	print("ROADSTEST fails=%d" % fails)
	quit(1 if fails > 0 else 0)
