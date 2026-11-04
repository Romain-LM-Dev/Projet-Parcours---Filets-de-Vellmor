## Test hors fenêtre de l'interface principale : rejoue un run enregistré dans `main.gd` comme le ferait le pont, puis vérifie ce
## que le joueur lit (aucune fenêtre ratée, annonces, étiquettes de l'inspecteur) et la bulle « … » des agents qui réfléchissent.
##   godot --headless --path godot -s res://tests/main_feed_test.gd -- --events=/chemin/events.jsonl
extends SceneTree

var fails := 0


func check(cond: bool, what: String) -> void:
	if not cond:
		fails += 1
		print("FAIL ", what)


func plain(bbcode: String) -> String:
	var rx := RegEx.new()
	rx.compile("\\[[^\\]]*\\]")
	return rx.sub(bbcode, "", true)


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
	var absent_checked := 0
	var bad_absent := 0
	var missed := 0
	var other_incidents := 0
	var announced := ""
	var rumor_decisions := 0
	var with_rumor := ""
	var narrations: Array = []
	for ev in events:
		var p: Dictionary = ev["payload"]
		match ev["type"]:
			"incident":
				if p["incident_type"] == "missed_window":
					missed += 1
				else:
					other_incidents += 1
			"injection":
				if p["injection_type"] == "announcement":
					announced = str(p["params"].get("text", ""))
			"decision":
				for r in p.get("retrieved", []):
					if r["source"] == "rumor":
						rumor_decisions += 1
						if with_rumor == "":
							with_rumor = str(p["agent"])
			"narration":
				narrations.append(p)
		m._on_message("events", ev)
		if ev["type"] == "assembly_start" and p.has("delegates") and str(p.get("scope", "")) == "valley":
			absent_checked += 1
			for aid in m.world.agents:             # au conseil des élus, les autres villageois ne sont pas dans la salle
				if bool(m.world.agents[aid].get("absent", false)) == p["participants"].has(aid):
					bad_absent += 1

	var texts: Array = []
	for l in m.feed_lines:
		texts.append(plain(str(l["text"])))
	var joined := "\n".join(PackedStringArray(texts))
	check(missed == 0, "aucune fenêtre ratée : une IA lente est attendue, rien n'est perdu (%d)" % missed)
	check("PERDUE" not in joined and "missed_window" not in joined, "ni « perdue » ni jargon dans le fil")
	check(announced != "" and "RUMEUR" in joined and ("« " + announced + " »") in joined, "l'annonce est écrite dans le fil : " + announced)
	check("INJECTION announcement" not in joined, "l'annonce n'apparaît plus comme du JSON brut")
	check(other_incidents == 0 or joined.count("INCIDENT") == other_incidents, "les autres incidents gardent la ligne « INCIDENT »")

	# le récit de l'ancien : un onglet à côté du fil, un récit par saison terminée, signalé dans le fil
	check(m.tabs.get_tab_title(1) == "Récit du narrateur", "l'onglet « Récit du narrateur » suit le fil : " + m.tabs.get_tab_title(1))
	check(narrations.size() > 0, "le run de test contient des récits de l'ancien")
	var told: String = m.narration.get_parsed_text()
	for n in narrations:
		check(("Saison %d" % int(n["season"])) in told and str(n["text"]).substr(0, 40) in told,
			"le récit de la saison %d est dans l'onglet" % int(n["season"]))
	check(joined.count("RÉCIT") == narrations.size(), "une ligne « RÉCIT » par récit dans le fil (%d)" % narrations.size())

	# prises secrètes : un mensonge se lit dans le fil (seuls le menteur et le joueur le savent), sa découverte aussi ;
	# la jauge de confiance de chacun suit la confiance publiée par le moteur
	var lies := 0
	var found := 0
	var clues := 0
	var votes := 0
	var strong := 0
	var reputations := {}
	var world_events := 0
	var councils := 0
	var routes := 0
	var elections := 0
	for ev in events:
		var p: Dictionary = ev["payload"]
		if ev["type"] == "report" and float(p["landed"]) - float(p["declared"]) > 0.05:
			lies += 1
		elif ev["type"] == "lie_discovered":
			found += 1
		elif ev["type"] == "clue":
			clues += 1
		elif ev["type"] == "sanction_result":
			votes += 1
		elif ev["type"] == "world_event":
			world_events += 1
		elif ev["type"] == "assembly_start" and p.has("delegates"):
			councils += 1
		elif ev["type"] == "patrol_route":
			routes += 1
		elif ev["type"] == "election":
			elections += 1
		elif ev["type"] == "trust":
			reputations[str(p["subject"])] = float(p["reputation"])
			if absf(float(p.get("delta", 0.0))) >= 0.2:
				strong += 1
	check(joined.count("VOTE X") == votes, "une ligne « VOTE » par proposition d'exclure ou de réautoriser (%d)" % votes)
	check(joined.count("CONFIANCE") == strong, "une ligne « CONFIANCE » par jugement marqué d'un agent (%d, trouvé %d)" % [strong, joined.count("CONFIANCE")])
	var established := joined.count("MENSONGE ÉTABLI")
	check(established + joined.count("PRIS EN CACHETTE") + joined.count("ACCUSÉ À TORT") == found, "une ligne par mensonge établi par l'ancien (%d)" % found)
	check(joined.count("MENSONGE") - established == lies, "une ligne « MENSONGE » par déclaration mensongère (%d)" % lies)
	check(joined.count("INDICE") == clues, "une ligne « INDICE » par indice (%d, trouvé %d)" % [clues, joined.count("INDICE")])
	check(world_events > 0 and joined.count("ÉVÉNEMENT") == world_events, "une ligne « ÉVÉNEMENT » par événement du climat (%d)" % world_events)
	check(councils > 0 and joined.count("CONSEIL") == councils, "une ligne « CONSEIL » par séance du conseil des élus (%d)" % councils)
	check(routes > 0 and joined.count("le capitaine fait route vers") == routes, "une ligne « PATROUILLE » par route de la patrouille (%d)" % routes)
	check(elections > 0 and "ÉLU" in joined and m.reps.size() == 4, "les élus des quatre villages sont notés : " + str(m.reps))
	# le temps de la saison : dit dans le fil au début de chaque saison, jour par jour dans la barre du bas
	var skies := 0
	for ev in events:
		if ev["type"] == "season_start" and ev["payload"].get("conditions", {}).get("climate") != null:
			skies += 1
	check(skies > 0 and joined.count("Temps de la pêche") == skies, "une ligne « Temps de la pêche » par saison (%d)" % skies)
	check(m.weather_days.size() == 20, "le temps de chaque jour de pêche est connu de l'interface (%d)" % m.weather_days.size())
	m.world.sim_time = float(m.weather_season - 1) * m.world.season_days + 3.0
	m._show_weather()
	check(m.lbl_weather.text == "Temps : " + str(m.weather_days[3]), "la barre du bas dit le temps du jour : " + m.lbl_weather.text)
	check(joined.count("(visait") > 0, "une prise loin de la prise visée le dit dans le fil")
	check(m.lbl_patrol.text.begins_with("Patrouille"), "la barre d'intervention dit où en est la patrouille du lac : " + m.lbl_patrol.text)
	check(m.world.hamlet_pos.size() == 4, "la carte pose les quatre villages de la vallée de base")
	check(not reputations.is_empty(), "le run de test fait bouger la confiance")
	# l'onglet Confiance : la moyenne des autres, ou la confiance qu'un personnage accorde aux autres
	m._set_trust_mode("avg")
	check("moyenne" in m.trust_view.get_parsed_text(), "par défaut : la confiance moyenne des autres")
	var watcher: String = str(m.agents.keys()[0])
	m.trust_observer = watcher
	m._set_trust_mode("from")
	var seen_text: String = m.trust_view.get_parsed_text()
	check("accorde aux autres" in seen_text and m.trust_who.visible and m.trust_who.item_count == m.agents.size(), "vue par un personnage : " + seen_text.substr(0, 90))
	check(not (str(m.agents[watcher]["info"].get("name", "")).split(" ")[0] + "  ") in seen_text.substr(seen_text.find("PÊCHEUR")), "le personnage observé n'est pas dans sa propre liste")
	m._set_trust_mode("avg")                   # la suite lit la moyenne des autres
	check(absent_checked > 0 and bad_absent == 0, "au conseil, les absents sont les seuls à ne pas siéger (%d séances, %d erreurs)" % [absent_checked, bad_absent])
	check(m.tabs.get_tab_title(2) == "Confiance", "l'onglet « Confiance » suit le récit : " + m.tabs.get_tab_title(2))
	m._render_trust()
	var gauges: String = m.trust_view.get_parsed_text()
	for id in reputations:
		check(is_equal_approx(float(m.agents[id]["reputation"]), reputations[id]), "la jauge de %s suit la confiance publiée" % id)
		check(("%d %%" % roundi(reputations[id] * 100.0)) in gauges, "la jauge de %s est affichée" % id)

	# l'inspecteur montre la rumeur parmi ce qui a été retrouvé pour décider
	check(rumor_decisions > 0, "des décisions ont retrouvé la rumeur (%d)" % rumor_decisions)
	if with_rumor != "":
		m._select(with_rumor)
		check(m.tabs.current_tab == m.inspector.get_index(), "choisir un pêcheur ouvre l'onglet « Agent »")
		m._render_inspector()
		var seen: String = m.inspector.get_parsed_text()
		check("[rumeur]" in seen and announced.substr(0, 20) in seen, "l'inspecteur affiche « [rumeur] » et son texte")

	# réflexion : la bulle apparaît pour l'agent listé dans status.thinking, puis disparaît ; l'horloge de la carte s'arrête
	var who: String = str(m.agents.keys()[0])
	var base := {"state": "running", "controls": true, "speed": 1.0, "fast": false, "season": 1, "seasons": 3,
		"sim_label": "S1 · J1", "lobby": true, "ai": ["ollama"], "thinking": []}
	var with := func(over: Dictionary) -> Dictionary:
		var d: Dictionary = base.duplicate()
		d.merge(over, true)
		return d
	m.ws_ok = true
	m._on_status(base)
	check(m.world.thinking.is_empty() and m.lbl_thinking.text == "" and m.world.time_scale > 0.0, "personne ne réfléchit : rien d'affiché, la carte vit")
	m._on_status(with.call({"thinking": [who, "inconnu"]}))
	check(m.world.thinking.has(who) and m.lbl_thinking.text == "2 en réflexion", "la bulle et la ligne apparaissent : " + m.lbl_thinking.text)
	check(m.world.time_scale == 0.0, "pendant la réflexion, la carte est figée (pas de marche)")
	m._on_status(base)
	check(m.world.thinking.is_empty() and m.lbl_thinking.text == "" and m.world.time_scale > 0.0, "la bulle disparaît, la carte repart")
	check(not m.speed_buttons.is_empty() and not m.has_method("_update_slow_hint"), "plus de bouton « Ralentir » ni de choix de mode")

	# fin de partie quand le lac est à sec : la ligne du fil, puis l'écran de fin le disent
	var before: int = m.feed_lines.size()
	m._on_event({"type": "run_end", "season": 3, "sim_label": "S3 · J18 03:46", "payload": {"reason": "extinction", "seasons_completed": 3}})
	var tail: Array = []
	for l in m.feed_lines.slice(before):
		tail.append(plain(str(l["text"])))
	var tail_text := "\n".join(PackedStringArray(tail))
	check("LAC À SEC" in tail_text and "plus un seul poisson" in tail_text, "le fil annonce le lac à sec : " + tail_text)
	check("le lac est à sec" in tail_text, "la ligne de fin dit pourquoi : " + tail_text)
	m._on_status(with.call({"state": "running"}))          # une nouvelle partie, puis sa fin
	m._on_status(with.call({"state": "ended", "end_reason": "extinction", "paused": false}))
	check(m.end_overlay.visible and m.end_title.text == "Partie terminée", "l'écran de fin s'affiche : " + m.end_title.text)
	check("à sec" in m.end_text.text and "ne se repeuple jamais" in m.end_text.text, "l'écran de fin explique : " + m.end_text.text)

	print("MAINFEEDTEST fails=%d lines=%d missed=%d" % [fails, texts.size(), missed])
	quit(1 if fails else 0)
