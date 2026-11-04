## Test de la scène de la veillée de la vallée (à part, à l'écran) : elle s'ouvre à `assembly_start`, se réduit (Échap) et se rouvre,
## les pions restent chez eux, elle se ferme à `assembly_end`. Avec une fenêtre et --out=chemin.png, il enregistre aussi une capture.
##   godot --path godot -s res://tests/salon_test.gd -- --out=C:/chemin/salon.png
extends SceneTree

var fails := 0


func check(cond: bool, what: String) -> void:
	if not cond:
		fails += 1
		print("FAIL ", what)


func _initialize() -> void:
	var out := ""
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--out="):
			out = a.substr(6)
	var W = load("res://scripts/world_view.gd")
	var w = W.new()
	w.size = Vector2(1000, 700)
	root.add_child(w)
	await process_frame
	var hs := ["Ostrel", "Bramois", "Tilque", "Hennad"]
	var ag: Array = [{"id": "A00", "name": "Maître Oswin", "hamlet": "Ostrel", "role": "ancien", "archetype": "ancienne_famille"}]
	for i in 7:
		ag.append({"id": "A%02d" % (i + 1), "name": "Villageois%d" % i, "hamlet": hs[i % 4], "role": "pecheur", "archetype": "beau_parleur"})
	w.reset_world(ag, 100.0, 30.0, hs, [], {"size": 1.5, "grid": 45})
	var homes := {}
	for id in w.agents:
		homes[id] = w.agents[id]["pos"]
	var ids: Array = []
	for a in ag:
		ids.append(a["id"])
	w.on_event({"type": "assembly_start", "season": 1, "payload": {"scope": "valley", "participants": ids}})
	check(w.assembly_scope == "valley" and w._salon_on(), "la scène s'ouvre avec la veillée de la vallée")
	check(not w.btn_salon_open.visible, "pas de bouton « rouvrir » tant que la scène est ouverte")
	check(w.salon_ids[0] == "A00", "l'ancien est assis en premier")
	w.on_event({"type": "utterance", "season": 1, "payload": {"speaker": "A01", "to": "A03", "text": "Le lac se vide : il faut une règle pour tous, dès cette saison."}})
	w.on_event({"type": "utterance", "season": 1, "payload": {"speaker": "A00", "to": "tous", "text": "Écoutons chacun avant de voter."}})
	w.on_event({"type": "utterance", "season": 1, "payload": {"speaker": "A05", "to": "A02", "text": "Je n'y crois pas."}})
	w.on_event({"type": "proposal", "season": 1, "payload": {"author": "A01", "proposal_id": "P1", "text": "pêche limitée à 4 t"}})
	w.on_event({"type": "accusation", "season": 1, "payload": {"accuser": "A02", "accused": "A04"}})
	for i in 4:
		await process_frame
	var inside := true
	for id in w.salon_ids:
		inside = inside and w._salon_rect().has_point(w._seat(id))
	check(inside, "tous les sièges tombent dans le cadre de la scène")
	for id in w.agents:
		check(w.agents[id]["pos"] == homes[id] and w.agents[id]["path"].is_empty(), "%s reste chez lui sur la carte" % id)
	if out != "":
		await create_timer(0.8).timeout
		root.get_viewport().get_texture().get_image().save_png(out)
	w.set_salon(false)
	check(not w._salon_on() and w.btn_salon_open.visible, "réduite : la carte se voit, le bouton rouvre la scène")
	w.btn_salon_open.pressed.emit()
	check(w._salon_on(), "le bouton rouvre la scène")
	var esc := InputEventKey.new()
	esc.keycode = KEY_ESCAPE
	esc.pressed = true
	w._unhandled_input(esc)
	check(not w._salon_on(), "Échap réduit la scène")
	w.set_salon(true)
	w.on_event({"type": "assembly_end", "season": 1, "payload": {"scope": "valley", "adopted_proposal": null}})
	check(not w._salon_on() and not w.btn_salon_open.visible and w.assembly_scope == "", "à assembly_end tout se ferme")
	print("SALONTEST fails=%d" % fails)
	quit(1 if fails else 0)
