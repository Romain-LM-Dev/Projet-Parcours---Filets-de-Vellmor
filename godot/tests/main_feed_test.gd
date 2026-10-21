## Test hors fenêtre de l'interface principale : rejoue un run enregistré dans `main.gd` comme le ferait le pont, puis vérifie ce
## que le joueur lit (répliques perdues, annonces, étiquettes de l'inspecteur) et le bouton « Ralentir ».
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
	var lost_reply := 0
	var lost_exit := 0
	var other_incidents := 0
	var last_season_lost := 0
	var announced := ""
	var rumor_decisions := 0
	var with_rumor := ""
	var narrations: Array = []
	for ev in events:
		var p: Dictionary = ev["payload"]
		match ev["type"]:
			"season_start":
				last_season_lost = 0
			"incident":
				if p["incident_type"] == "missed_window":
					last_season_lost += 1
					if p["handled_by"] == "réplique perdue":
						lost_reply += 1
					else:
						lost_exit += 1
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

	var texts: Array = []
	for l in m.feed_lines:
		texts.append(plain(str(l["text"])))
	var joined := "\n".join(PackedStringArray(texts))
	check(lost_reply + lost_exit > 0, "le run de test contient des fenêtres ratées")
	check(joined.count("RÉPLIQUE PERDUE") == lost_reply, "une ligne « RÉPLIQUE PERDUE » par réplique perdue (%d, trouvé %d)" % [lost_reply, joined.count("RÉPLIQUE PERDUE")])
	check(joined.count("SORTIE PERDUE") == lost_exit, "une ligne « SORTIE PERDUE » par sortie perdue (%d, trouvé %d)" % [lost_exit, joined.count("SORTIE PERDUE")])
	check(lost_reply + lost_exit == 0 or "l'IA réfléchissait encore" in joined, "la ligne dit pourquoi : l'IA réfléchissait encore")
	check("INCIDENT missed_window" not in joined and "missed_window" not in joined, "plus de jargon « missed_window » dans le fil")
	check(m.lost_this_season == last_season_lost, "le compteur de la saison compte les pertes de la dernière saison (%d, attendu %d)" % [m.lost_this_season, last_season_lost])
	check(announced != "" and "RUMEUR" in joined and ("« " + announced + " »") in joined, "l'annonce est écrite dans le fil : " + announced)
	check("INJECTION announcement" not in joined, "l'annonce n'apparaît plus comme du JSON brut")
	check(other_incidents == 0 or joined.count("INCIDENT") == other_incidents, "les autres incidents gardent la ligne « INCIDENT »")

	# le récit de l'ancien : un onglet à côté du fil, un récit par saison terminée, signalé dans le fil
	check(m.tabs.get_tab_title(1) == "Récit de l'ancien", "l'onglet « Récit de l'ancien » suit le fil : " + m.tabs.get_tab_title(1))
	check(narrations.size() > 0, "le run de test contient des récits de l'ancien")
	var told: String = m.narration.get_parsed_text()
	for n in narrations:
		check(("Saison %d" % int(n["season"])) in told and str(n["text"]).substr(0, 40) in told,
			"le récit de la saison %d est dans l'onglet" % int(n["season"]))
	check(joined.count("RÉCIT") == narrations.size(), "une ligne « RÉCIT » par récit dans le fil (%d)" % narrations.size())

	# l'inspecteur montre la rumeur parmi ce qui a été retrouvé pour décider
	check(rumor_decisions > 0, "des décisions ont retrouvé la rumeur (%d)" % rumor_decisions)
	if with_rumor != "":
		m._select(with_rumor)
		m._render_inspector()
		var seen: String = m.inspector.get_parsed_text()
		check("[rumeur]" in seen and announced.substr(0, 20) in seen, "l'inspecteur affiche « [rumeur] » et son texte")

	# bouton « Ralentir » : asynchrone + vraie IA + monde plus rapide que ce que le moteur d'IA peut suivre
	var base := {"state": "running", "controls": true, "mode": "async", "pending_mode": null, "speed": 1.0, "fast": false,
		"season": 1, "seasons": 3, "sim_label": "S1 · J1", "lobby": true, "ai": ["ollama"], "advised_speed": 0.25}
	var with := func(over: Dictionary) -> Dictionary:
		var d: Dictionary = base.duplicate()
		d.merge(over, true)
		return d
	m.lost_this_season = 0                  # les pertes du run rejoué ne comptent pas pour ces vérifications
	m.ws_ok = true
	m._on_status(base)
	check(m.btn_slow.visible and "× ¼" in m.btn_slow.text and m.slow_target == 0.25, "à × 1 avec Ollama en asynchrone : « Ralentir (× ¼) » : " + m.btn_slow.text)
	m._on_status(with.call({"speed": 0.25}))
	check(not m.btn_slow.visible, "à la vitesse conseillée : pas de bouton")
	m._on_status(with.call({"speed": 0.0625}))
	check(not m.btn_slow.visible, "plus lent que conseillé : pas de bouton")
	m._on_status(with.call({"fast": true}))
	check(m.btn_slow.visible, "vitesse maximale : bouton proposé")
	m._on_status(with.call({"mode": "sync"}))
	check(not m.btn_slow.visible, "en synchrone, la lenteur d'une IA ne coûte rien : pas de bouton")
	m._on_status(with.call({"ai": ["scripted"], "advised_speed": null}))
	check(not m.btn_slow.visible, "faux LLM : pas de bouton")
	# à la vitesse conseillée, mais l'IA perd encore des répliques : on propose la vitesse du dessous
	m.lost_this_season = 1
	m._on_status(with.call({"speed": 0.25}))
	check(not m.btn_slow.visible and m.lbl_lost.visible and "1 perdue" in m.lbl_lost.text, "une seule perte : pas de bouton, mais le compteur : " + m.lbl_lost.text)
	m.lost_this_season = 3
	m._on_status(with.call({"speed": 0.25}))
	check(m.btn_slow.visible and "× 1/8" in m.btn_slow.text and m.slow_target == 0.125, "trois pertes à la vitesse conseillée : « Ralentir (× 1/8) » : " + m.btn_slow.text)
	m._on_status(with.call({"speed": 0.0625}))
	check(not m.btn_slow.visible, "à la vitesse la plus lente : rien de plus lent à proposer")
	m._on_status(with.call({"mode": "sync", "speed": 0.25}))
	check(not m.btn_slow.visible, "en synchrone, aucune perte possible : pas de bouton")
	m.lost_this_season = 0
	m._on_status(with.call({"mode": "sync", "pending_mode": "async"}))
	check(m.btn_slow.visible, "passage annoncé en asynchrone : le bouton est déjà proposé")
	m._on_status(with.call({"state": "paused"}))
	check(m.btn_slow.visible, "en pause, comme les boutons de vitesse, « Ralentir » reste disponible")
	m._on_status(with.call({"state": "ended"}))
	check(not m.btn_slow.visible, "partie terminée : pas de bouton")
	check(m.speed_buttons.has(0.0625) and m.speed_buttons.has(0.125), "les vitesses × 1/16 et × 1/8 existent dans la barre")

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

	print("MAINFEEDTEST fails=%d lines=%d lost_reply=%d lost_exit=%d" % [fails, texts.size(), lost_reply, lost_exit])
	quit(1 if fails else 0)
