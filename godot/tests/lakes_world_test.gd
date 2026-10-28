## Test hors fenêtre de la carte à plusieurs lacs : rejoue un run enregistré dans `main.gd` et vérifie que la carte pose les lacs et leurs
## villages, suit le niveau de chacun, montre une barque par patrouille, et dessine (jauges, noms, poissons) sans erreur.
##   godot --headless --path godot -s res://tests/lakes_world_test.gd -- --events=/chemin/events.jsonl
extends SceneTree

var fails := 0


func check(cond: bool, what: String) -> void:
	if not cond:
		fails += 1
		print("FAIL ", what)


func _initialize() -> void:
	var path := ""
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--events="):
			path = a.substr(9)
	var Main = load("res://scripts/main.gd")
	var m = Main.new()
	root.add_child(m)
	await process_frame
	await process_frame
	m.set_process(false)
	var events: Array = []
	for line in FileAccess.get_file_as_string(path).split("\n"):
		if line.strip_edges() != "":
			events.append(JSON.parse_string(line))
	var n_lakes := 0
	var last: Dictionary = {}
	var captains := {}
	var last_season := 0
	for ev in events:
		var p: Dictionary = ev["payload"]
		if ev["type"] == "run_start":
			n_lakes = (p["lakes"] as Array).size()
		elif ev["type"] == "lake_update" and p.has("lakes"):
			last = p["lakes"]
		elif ev["type"] == "patrol_route":
			if int(p["season"]) != last_season:
				captains.clear()
				last_season = int(p["season"])
			captains[str(p["captain"])] = true
		m._on_event(ev)
	var w = m.world
	check(n_lakes >= 2 and w.lakes.size() == n_lakes, "la carte pose les lacs de la partie (%d / %d)" % [w.lakes.size(), n_lakes])
	check(w.hamlet_pos.size() == (events[0]["payload"]["hamlets"] as Array).size(), "et tous les villages")
	for h in w.hamlet_pos:
		var q: Vector2 = w.hamlet_pos[h]
		check(q.x > 0.05 and q.x < 0.95 and q.y > 0.1 and q.y < 0.95, "le village %s est sur la carte : %s" % [h, q])
		check(w.lake_rn(q) > 1.0, "le village %s n'est pas dans l'eau (%s)" % [h, w.lake_rn(q)])
	for k in w.lakes.size():
		var name := str(w.lakes[k]["name"])
		var cap := float(w.lakes[k]["capacity"])
		check(last.has(name) and is_equal_approx(float(w.lakes[k]["ratio"]), float(last[name]) / cap), "le niveau du lac %s suit le moteur" % name)
	var villages_by_lake := {}
	for h in w.hamlet_lake:
		villages_by_lake[w.hamlet_lake[h]] = true
	check(villages_by_lake.size() == n_lakes, "chaque lac a au moins un village")
	check(w.patrol_routes.size() == captains.size() and captains.size() >= 2, "une route par patrouille (%d)" % w.patrol_routes.size())
	check(m.patrol_texts.size() == captains.size(), "l'interface garde la route de chaque patrouille (%d)" % m.patrol_texts.size())
	check(m.feed_lines.size() > 0, "le fil a des lignes")
	# toute la carte se dessine : poissons, jauges, noms, barques de patrouille
	w.sim_time = float(last_season - 1) * w.season_days + 5.0
	w.patrol_season = last_season
	w.queue_redraw()
	for layer in [w.decor, w.under, w.over, w.lights]:
		layer.queue_redraw()
	await process_frame
	await process_frame
	check(w.fish.size() > 0 and w.fish.all(func(f): return int(f["k"]) < w.lakes.size()), "des poissons dans chaque lac")
	# une barque de pêche est sur l'eau de SON lac
	for id in w.agents:
		var a: Dictionary = w.agents[id]
		if str(a["info"].get("role", "")) == "ancien":
			continue
		var spot: Vector2 = w._fishing_spot(a)
		check(w.lake_rn(spot) < 1.0 and w._lake_at(spot) == w._lake_of_hamlet(str(a["info"].get("hamlet", ""))),
			"%s pêche sur son lac" % str(a["info"].get("name", id)))
	# un pêcheur parti dans l'autre lac : sa route passe à terre jusqu'au bord du lac visé et se pose sur son eau
	w.size = Vector2(1000, 700)
	await process_frame
	w.animate = true
	var visitor := ""
	for id in w.agents:
		if str(w.agents[id]["info"].get("role", "")) != "ancien":
			visitor = str(id)
			break
	var target: int = (w._lake_of_hamlet(str(w.agents[visitor]["info"].get("hamlet", ""))) + 1) % w.lakes.size()
	w.on_event({"type": "catch", "sim_time": 1.0, "payload": {"agent": visitor, "zone": "large-" + str(w.lakes[target]["name"]),
		"away": true, "lake": str(w.lakes[target]["name"]), "landed": 1.0, "secret": false}})
	var trip: Array = w.agents[visitor]["path"]
	var wet := trip.filter(func(s): return w.lake_rn(s[0]) < 1.0 and w._lake_at(s[0]) == target)
	check(trip.size() >= 5 and wet.size() >= 1, "le pêcheur parti ailleurs marche jusqu'à l'autre lac et pêche sur son eau (%d étapes)" % trip.size())
	check(float(w.agents[visitor]["path"][0][1]) == 0.0 and trip[trip.size() - 1][0] == w.agents[visitor]["home"], "et rentre chez lui")
	print("LAKESWORLDTEST fails=%d lakes=%d" % [fails, n_lakes])
	quit(1 if fails else 0)
