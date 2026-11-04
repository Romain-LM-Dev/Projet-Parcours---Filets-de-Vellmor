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

	check(m.chk_patrol.button_pressed and m.build_config()["patrol"] == true, "la patrouille est activée par défaut")
	check(m.opt_fleet.item_count == 3 and str(m.opt_fleet.get_item_metadata(m.opt_fleet.selected)) == "mixte", "trois flottes, « mixte » par défaut")

	# --- un seul mode de temps : plus de choix, et la vitesse de départ ne dépend plus du moteur d'IA
	var speed_is := func(v: float) -> bool:
		var s: Variant = m.opt_speed.get_item_metadata(m.opt_speed.selected)
		return typeof(s) == TYPE_FLOAT and is_equal_approx(s, v)
	var pick_llm := func(id: String) -> void:
		m._select_meta(m.opt_llm, id)
		m.opt_llm.item_selected.emit(m.opt_llm.selected)       # comme un clic du joueur
	check(not "mode_buttons" in m and not m.has_method("_set_mode"), "le menu n'a plus de choix Synchrone / Asynchrone")
	check(speed_is.call(1.0), "vitesse de départ × 1")
	pick_llm.call("ollama_fast")
	check(speed_is.call(1.0), "Ollama : pas de ralentissement imposé, l'horloge attend l'IA")
	m.reset_all()
	check(m.fishers.size() == 8 and not m.speed_touched, "Tout réinitialiser : retour aux réglages de départ")

	# --- réflexion proposée par le moteur d'IA : les réflexes open demandent la réflexion adaptative
	var reflection_is := func(v: String) -> bool: return str(m.opt_reflection.get_item_metadata(m.opt_reflection.selected)) == v
	pick_llm.call("ollama_open")
	check(reflection_is.call("adaptive") and m.build_config()["reflection"] == "adaptive", "réflexes open : réflexion adaptative")
	check("Système 1" in m.lbl_reflection_desc.text, "la description suit la réflexion proposée : " + m.lbl_reflection_desc.text)
	pick_llm.call("ollama_fast")
	check(reflection_is.call("rapide"), "retour à Ollama rapide : réflexion rapide")
	m._select_meta(m.opt_reflection, "complete")
	m.opt_reflection.item_selected.emit(m.opt_reflection.selected)     # le joueur choisit lui-même la réflexion
	pick_llm.call("ollama_open")
	check(reflection_is.call("complete"), "la réflexion choisie à la main n'est plus changée d'office")
	m.reset_all()
	check(reflection_is.call("rapide") and not m.reflection_touched, "Tout réinitialiser : réflexion de départ")

	# --- paramètres de la partie
	m.spin_seasons.value = 4
	m.spin_seed.value = 123
	m.opt_comm.select(1)
	m.chk_visible.button_pressed = false
	m._select_meta(m.opt_llm, "ollama")
	m.opt_speed.select(m.opt_speed.item_count - 1)
	m.chk_elder.button_pressed = true
	m.opt_elder.select(1)
	var cfg1: Dictionary = m.build_config()
	check(cfg1["mode"] == "unique" and cfg1["seasons"] == 4 and cfg1["seed"] == 123, "mode unique, saisons, graine")
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

	# --- les bateaux, le conseil, le climat et le hasard font partie de la demande
	check(final_cfg["population"]["fishers"].all(func(f): return str(f.get("boat", "")) in ["barque", "chaloupe", "cotre"]),
		"chaque fiche a son bateau")
	check(final_cfg["council"] == "delegates" and final_cfg["climate"] == true and is_equal_approx(final_cfg["event_rate"], 0.3)
		and is_equal_approx(final_cfg["luck"], 0.4), "par défaut : un élu par village, climat, 30 % d'événements, 40 % de hasard")
	m._rows[0]["boat"].item_selected.emit(2)
	check(m.fishers[0]["boat"] == "cotre", "le bateau se change dans la liste")
	m.chk_climate.button_pressed = false
	m.spin_luck.value = 0
	m._select_meta(m.opt_council, "all")
	var cfg_b: Dictionary = m.build_config()
	check(cfg_b["climate"] == false and cfg_b["luck"] == 0.0 and cfg_b["council"] == "all"
		and cfg_b["population"]["fishers"][0]["boat"] == "cotre", "le climat, le hasard et le conseil se règlent")
	m.chk_climate.button_pressed = true
	m.spin_luck.value = 25

	# --- générer la vallée : le menu la demande au moteur, qui répond par un catalogue dont seule la vallée change
	var asked := []
	m.generate_requested.connect(func(p: Dictionary) -> void: asked.append(p))
	m._gen_timer.stop()                    # (la graine changée plus haut a lancé une régénération : on la laisse de côté)
	m._refresh_all()
	check(m.spin_villages.value == 4 and m.spin_fishers.value == m.fishers.size(), "les nombres disent ce que contient la liste")
	m.spin_villages.value = 6
	m.spin_fishers.value = 12
	check(asked.is_empty() and not m._gen_timer.is_stopped(), "changer les nombres lance la demande, un instant après")
	await create_timer(0.8).timeout
	m._on_generate()                       # un clic de plus, en attendant, ne redemande rien
	check(asked.size() == 1 and asked[0]["villages"] == 6 and asked[0]["fishers"] == 12 and asked[0]["seed"] == int(m.spin_seed.value),
		"la demande de vallée porte les villages, les pêcheurs et la graine")
	check(m.btn_generate.disabled, "le bouton attend la vallée")
	var six: Array = cat["village_names"].slice(0, 6)
	var pop: Array = []
	for i in 12:
		pop.append({"first_name": "P%d" % i, "hamlet": six[i % 6], "archetype": "taiseux", "experience": 10, "wealth": 300.0,
			"debt_payment": 0.0, "kind": "llm", "tier": "auto", "boat": "barque"})
	var cat2: Dictionary = cat.duplicate(true)
	cat2["hamlets"] = six
	cat2["base_population"] = pop
	cat2["generation"] = {"id": asked[0]["id"], "villages": 6, "fishers": 12, "seed": asked[0]["seed"]}
	var rounds_before: float = m.spin_rounds.value
	m.set_catalog(cat2)
	check(m.fishers.size() == 12 and m._rows.size() == 12, "la vallée générée remplace les pêcheurs")
	var villages_seen := {}
	for f in m.fishers:
		villages_seen[f["hamlet"]] = true
	check(villages_seen.size() == 6 and m.map.hamlets.size() == 6, "six villages sur la carte du menu")
	check(m.spin_rounds.value == rounds_before and m.chk_climate.button_pressed and not m.btn_generate.disabled,
		"les réglages ne sont pas effacés, le bouton est libéré")
	var opts_h: OptionButton = m._rows[0]["hamlet"]
	check(opts_h.item_count == 6, "chaque pêcheur peut aller dans l'un des six villages")

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
