## Test hors fenêtre du menu de démarrage : manipule les widgets comme le ferait le joueur, puis imprime la demande
## qui serait envoyée au moteur. `tests/test_godot_menu.py` la fait valider par le moteur Python.
##   godot --headless --path godot -s res://tests/menu_test.gd -- --catalog=/chemin/catalog.json
extends SceneTree

var fails := 0


func check(cond: bool, what: String) -> void:
	if not cond:
		fails += 1
		print("FAIL ", what)


func _initialize() -> void:
	var path := ""
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--catalog="):
			path = a.substr(10)
	var cat: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(path))
	var Menu = load("res://scripts/start_menu.gd")
	var m = Menu.new()
	root.add_child(m)
	await process_frame           # `_ready` (construction des widgets) n'a lieu qu'à la première image
	m.set_catalog(cat)

	# --- composition de base : celle du moteur, huit pêcheurs, deux par hameau
	check(m.fishers.size() == 8, "composition de base : 8 pêcheurs")
	check(m._rows.size() == 8, "une ligne par pêcheur")
	var per := {}
	for f in m.fishers:
		per[f["hamlet"]] = int(per.get(f["hamlet"], 0)) + 1
	check(per.size() == 4 and per.values().all(func(n): return n == 2), "deux pêcheurs par hameau")
	check(m.fishers.all(func(f): return f["kind"] == "llm" and f["tier"] == "auto"), "composition de base : tous en IA auto")
	check(m._rows.all(func(r): return r["brain"].selected == 0), "la liste affiche « IA · auto » partout")
	var cfg0: Dictionary = m.build_config()
	check(cfg0["population"]["fishers"].size() == 8, "demande : 8 fiches")
	check(typeof(cfg0["seasons"]) == TYPE_INT and typeof(cfg0["seed"]) == TYPE_INT, "saisons et graine sont des entiers")
	check(typeof(cfg0["population"]["fishers"][0]["experience"]) == TYPE_INT, "expérience entière")
	check(cfg0["lake"]["capacity"] == null and cfg0["reflection"] == "rapide" and cfg0["assembly_rounds"] == 2,
		"par défaut : stock du lac automatique, réflexion rapide, deux tours de parole")

	# --- vitesse conseillée : en asynchrone avec une vraie IA, le monde doit ralentir pour lui laisser le temps de répondre
	var speed_is := func(v: float) -> bool:
		var s: Variant = m.opt_speed.get_item_metadata(m.opt_speed.selected)
		return typeof(s) == TYPE_FLOAT and is_equal_approx(s, v)
	var pick_llm := func(id: String) -> void:
		m._select_meta(m.opt_llm, id)
		m.opt_llm.item_selected.emit(m.opt_llm.selected)       # comme un clic du joueur
	m._set_mode("sync")
	check(speed_is.call(1.0) and not m.lbl_async_warning.visible, "synchrone : × 1, aucun avertissement")
	pick_llm.call("ollama_fast")
	check(speed_is.call(1.0) and not m.lbl_async_warning.visible, "synchrone + Ollama : pas de ralentissement imposé")
	m._set_mode("async")
	check(speed_is.call(0.25), "asynchrone + Ollama rapide : vitesse conseillée × ¼")
	check(not m.lbl_async_warning.visible and "× ¼" in m.lbl_speed_hint.text, "à la vitesse conseillée : pas d'avertissement, conseil affiché")
	var one := 0
	for i in m.opt_speed.item_count:
		if typeof(m.opt_speed.get_item_metadata(i)) == TYPE_FLOAT and is_equal_approx(m.opt_speed.get_item_metadata(i), 1.0):
			one = i
	m.opt_speed.select(one)
	m.opt_speed.item_selected.emit(one)          # le joueur choisit lui-même la vitesse
	check(m.lbl_async_warning.visible and "réplique perdue" in m.lbl_async_warning.text, "trop vite pour une IA locale : avertissement")
	pick_llm.call("ollama")
	check(speed_is.call(1.0), "la vitesse choisie à la main n'est plus changée d'office")
	m._set_mode("sync")
	check(not m.lbl_async_warning.visible, "synchrone : plus d'avertissement")
	m.reset_all()
	m._set_mode("async")
	pick_llm.call("ollama")
	check(speed_is.call(0.125), "moteur 7B : vitesse conseillée × 1/8")
	pick_llm.call("scripted")
	check(speed_is.call(1.0) and not m.lbl_async_warning.visible, "faux LLM : aucune contrainte de vitesse")
	m.reset_all()
	check(m.fishers.size() == 8 and not m.speed_touched, "Tout réinitialiser : retour aux réglages de départ")

	# --- paramètres de la partie
	m._set_mode("async")
	check(m.mode == "async" and m.mode_buttons["async"].button_pressed and not m.mode_buttons["sync"].button_pressed, "mode asynchrone")
	m._set_mode("sync")
	check(m.build_config()["mode"] == "sync", "retour en synchrone")
	m._set_mode("async")
	m.spin_seasons.value = 4
	m.spin_seed.value = 123
	m.opt_comm.select(1)
	m.chk_visible.button_pressed = false
	m._select_meta(m.opt_llm, "ollama")
	m.opt_speed.select(m.opt_speed.item_count - 1)
	m.chk_elder.button_pressed = true
	m.opt_elder.select(1)
	var cfg1: Dictionary = m.build_config()
	check(cfg1["mode"] == "async" and cfg1["seasons"] == 4 and cfg1["seed"] == 123, "mode, saisons, graine")
	check(cfg1["communication"] == "hamlet" and cfg1["catches_visible"] == false, "veillées par hameau, prises cachées")
	check(cfg1["llm"] == "ollama" and cfg1["speed"] == "max", "Ollama, vitesse maximale")
	check(cfg1["population"]["elder"] == true and cfg1["population"]["elder_kind"] == "rule", "ancien à règles")

	# --- ajouter des pêcheurs : le plus petit hameau d'abord, archétypes qui tournent, prénoms jamais en double
	for i in 3:
		m._add_fisher()
	check(m.fishers.size() == 11 and m._rows.size() == 11, "11 pêcheurs après 3 ajouts")
	var names := {}
	for f in m.fishers:
		names[f["first_name"]] = true
	check(names.size() == 11, "prénoms tous différents")
	per.clear()
	for f in m.fishers:
		per[f["hamlet"]] = int(per.get(f["hamlet"], 0)) + 1
	check(per.values().max() - per.values().min() <= 1, "hameaux équilibrés après ajouts")
	check(m.selected == 10, "le nouveau pêcheur est sélectionné")
	check("lac de 137.5" in m.lbl_lake.text or "lac de 137,5" in m.lbl_lake.text, "la capacité du lac suit le nombre : " + m.lbl_lake.text)

	# --- limite du stock du lac : automatique (12,5 t par pêcheur) tant qu'on n'y touche pas, puis fixée à la main
	check(m.capacity_auto and m.spin_capacity.value == 137.5 and m.build_config()["lake"]["capacity"] == null,
		"stock du lac automatique : 137,5 t, demande « null »")
	check(m.btn_cap_auto.disabled, "le bouton Auto est inactif quand on est déjà en automatique")
	m.spin_capacity.value = 60.0
	check(not m.capacity_auto and m.build_config()["lake"]["capacity"] == 60.0, "stock du lac choisi à la main : 60 t")
	check("lac de 60 t" in m.lbl_lake.text and "durable max 15 t" in m.lbl_lake.text, "l'en-tête suit le choix : " + m.lbl_lake.text)
	check("Choisi à la main" in m.lbl_cap_hint.text and not m.btn_cap_auto.disabled, "l'aide dit que c'est un choix : " + m.lbl_cap_hint.text)
	m._add_fisher()
	check(m.spin_capacity.value == 60.0, "ajouter un pêcheur ne change plus le stock choisi à la main")
	m._remove_fisher(m.fishers.size() - 1)
	m.spin_capacity.value = 1.0
	check(m.spin_capacity.value == 10.0, "limite basse du stock : 10 t")
	m.btn_cap_auto.pressed.emit()
	check(m.capacity_auto and m.spin_capacity.value == 137.5 and m.build_config()["lake"]["capacity"] == null,
		"Auto : retour à 12,5 t par pêcheur")

	# --- taux de repeuplement du lac : r = 1 par défaut ; le rendement durable maximal (r × K / 4) suit
	check(m.spin_growth.value == 1.0 and m.btn_growth_default.disabled, "repeuplement normal par défaut : r = 1")
	check(m.build_config()["lake"]["growth_rate"] == 1.0, "la demande porte le taux : 1")
	m.spin_capacity.value = 60.0
	m.spin_growth.value = 0.5
	check(m.build_config()["lake"]["growth_rate"] == 0.5 and not m.btn_growth_default.disabled, "repeuplement choisi : r = 0,5")
	check("durable max 7.5 t" in m.lbl_lake.text, "r = 0,5 sur 60 t : 7,5 t par saison au mieux : " + m.lbl_lake.text)
	check("7.5 t par saison" in m.lbl_cap_hint.text, "l'aide cite le rendement qui suit le taux : " + m.lbl_cap_hint.text)
	m.spin_growth.value = 5.0
	check(m.spin_growth.value == 2.0, "au plus r = 2")
	m.spin_growth.value = 0.0
	check(m.spin_growth.value == 0.1, "au moins r = 0,1")
	m.btn_growth_default.pressed.emit()
	check(m.spin_growth.value == 1.0 and m.btn_growth_default.disabled, "Normal : retour à r = 1")
	m.btn_cap_auto.pressed.emit()

	# --- arrêt à l'extinction du lac : activé par défaut, décochable
	check(m.chk_stop_empty.button_pressed and m.build_config()["stop_on_extinction"] == true, "arrêt si le lac est vide : actif par défaut")
	m.chk_stop_empty.button_pressed = false
	check(m.build_config()["stop_on_extinction"] == false, "arrêt si le lac est vide : décoché")
	m.chk_stop_empty.button_pressed = true

	# --- réflexion des IA et tours de parole
	m._select_meta(m.opt_reflection, "complete")
	m.opt_reflection.item_selected.emit(m.opt_reflection.selected)
	m.spin_rounds.value = 3
	var cfg_r: Dictionary = m.build_config()
	check(cfg_r["reflection"] == "complete" and cfg_r["assembly_rounds"] == 3, "réflexion complète, 3 tours de parole")
	check("Réponses libres" in m.lbl_reflection_desc.text, "la description de la réflexion suit : " + m.lbl_reflection_desc.text)
	m.spin_rounds.value = 9
	check(m.spin_rounds.value == 3.0, "au plus 3 tours de parole")
	m._select_meta(m.opt_reflection, "rapide")

	# --- changer d'archétype : les trois chiffres suivent l'archétype
	var nouveau := 1
	for a in cat["archetypes"]:
		if a["id"] == "nouveau_venu":
			nouveau = cat["archetypes"].find(a)
	m._rows[2]["arch"].select(nouveau)
	m._rows[2]["arch"].item_selected.emit(nouveau)
	check(m.fishers[2]["archetype"] == "nouveau_venu" and float(m.fishers[2]["debt_payment"]) == 120.0, "archétype nouveau venu : dette 120")
	check(m._rows[2]["debt"].value == 120.0, "la case dette est à jour")

	# --- cerveau : règles, IA grand, IA petit
	m._rows[0]["brain"].item_selected.emit(3)
	check(m.fishers[0]["kind"] == "rule", "pêcheur 0 à règles")
	m._rows[1]["brain"].item_selected.emit(1)
	check(m.fishers[1]["kind"] == "llm" and m.fishers[1]["tier"] == "grand", "pêcheur 1 : IA grand modèle")

	# --- déplacer un pêcheur sur la carte
	m.map.token_moved.emit(3, "Hennad")
	check(m.fishers[3]["hamlet"] == "Hennad", "déplacé à Hennad")
	check(m._rows[3]["hamlet"].selected == cat["hamlets"].find("Hennad"), "la liste suit la carte")

	# --- renommer
	m._rows[4]["name"].text_changed.emit("  Zélie ")
	check(m.fishers[4]["first_name"] == "Zélie", "prénom nettoyé")

	# --- retirer
	m._remove_fisher(0)
	check(m.fishers.size() == 10 and m._rows.size() == 10, "10 pêcheurs après un retrait")
	check(m.rows_box.get_child_count() == 10, "les anciennes lignes ont disparu de l'arbre")

	# --- limites
	while m.fishers.size() < 24:
		m._add_fisher()
	check(m.btn_add.disabled, "ajout bloqué à 24")
	m._add_fisher()
	check(m.fishers.size() == 24, "jamais plus de 24")
	while m.fishers.size() > 1:
		m._remove_fisher(0)
	check(m.fishers.size() == 1 and m._rows[0]["del"].disabled, "on ne retire pas le dernier pêcheur")

	# --- composition de base : retour exact au point de départ ; la demande finale est un cas varié
	m.reset_population()
	check(m.fishers.size() == 8, "composition de base rétablie")
	check(JSON.stringify(m.fishers) == JSON.stringify(cat["base_population"]), "identique à celle du moteur")
	m._add_fisher()
	m._rows[1]["brain"].item_selected.emit(2)
	m._rows[5]["brain"].item_selected.emit(3)
	m.map.token_moved.emit(2, "Tilque")
	m.spin_capacity.value = 140.0                 # une demande variée : limite du stock, réflexion et tours de parole choisis
	m.spin_growth.value = 0.8
	m._select_meta(m.opt_reflection, "complete")
	m.spin_rounds.value = 3
	var final_cfg: Dictionary = m.build_config()
	check(final_cfg["lake"]["capacity"] == 140.0 and final_cfg["reflection"] == "complete" and final_cfg["assembly_rounds"] == 3,
		"demande finale : stock 140 t, réflexion complète, 3 tours")
	check(is_equal_approx(final_cfg["lake"]["growth_rate"], 0.8) and final_cfg["stop_on_extinction"] == true,
		"demande finale : repeuplement 0,8, arrêt si le lac est vide")

	# --- état du moteur : le bouton Démarrer suit
	m.set_engine("idle", true)
	m.open(false)
	check(not m.btn_start.disabled, "Démarrer actif quand le moteur est prêt")
	m.set_engine("running", true)
	check(m.btn_start.disabled, "Démarrer inactif pendant une partie")
	m.set_engine("idle", false)
	check(m.btn_start.disabled, "Démarrer inactif si le moteur est injoignable")
	m.set_engine("starting", true, "Chargement du modèle qwen2.5:7b (1/2)…")
	check("Chargement du modèle qwen2.5:7b" in m.lbl_engine.text, "le menu dit ce que fait le moteur : " + m.lbl_engine.text)
	check("injoignable" not in m.lbl_engine.text and m.btn_start.disabled, "pendant la préparation : ni injoignable, ni Démarrer")
	m.close()                    # la partie démarre : le menu se referme (et n'est plus « occupé »)
	m.open(false)
	m.set_engine("idle", true)
	var sent := []
	m.start_requested.connect(func(c: Dictionary) -> void: sent.append(c))
	m._on_start()
	m._on_start()
	check(sent.size() == 1, "un double clic n'envoie qu'une demande")
	check(m.btn_start.disabled, "Démarrer inactif pendant la préparation")
	m.show_error("refusé")
	check(not m.btn_start.disabled and m.lbl_error.text == "refusé", "l'erreur du moteur réactive le bouton")

	print("MENUTEST fails=%d fishers=%d" % [fails, final_cfg["population"]["fishers"].size()])
	print("CONFIG:" + JSON.stringify(final_cfg))
	quit(1 if fails else 0)
