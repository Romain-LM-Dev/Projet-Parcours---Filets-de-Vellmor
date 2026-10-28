## Test hors fenêtre du menu à plusieurs lacs : un lac par ligne (poisson, stock de départ, repeuplement), les patrouilles, la part prenable,
## la vallée aléatoire. Imprime la demande qui serait envoyée au moteur (`tests/test_godot_menu.py` la fait valider par le moteur Python).
##   godot --headless --path godot -s res://tests/lakes_menu_test.gd -- --catalog=/chemin/catalog.json
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
	await process_frame
	m.set_catalog(cat)

	# --- trois lacs : une ligne chacun, les deux lignes du lac unique disparaissent
	check(m.lakes_state.size() == 3 and m.lake_spins.size() == 3, "trois lacs, trois lignes (%d)" % m.lakes_state.size())
	check(m.lakes_box.visible and not m.row_cap.visible and not m.row_growth.visible, "chaque lac se règle à part")
	check(int(m.spin_lakes.value) == 3 and m.opt_genmode.selected == 0, "le menu dit 3 lacs, vallée paramétrée")
	check("3 lacs" in m.lbl_lake.text, "le résumé compte les lacs : " + m.lbl_lake.text)
	var cfg: Dictionary = m.build_config()
	var lakes: Array = cfg["lake"]["lakes"]
	check(lakes.size() == 3 and not cfg["lake"].has("capacity"), "la demande décrit les trois lacs")
	var villages := []
	for k in lakes:
		villages.append_array(k["villages"])
	check(villages.size() == (cat["hamlets"] as Array).size(), "chaque village est rattaché à un lac, une fois")
	var total := 0.0
	for k in lakes:
		total += float(k["capacity"])
	check(is_equal_approx(total, 12.5 * m.fishers.size()), "stock auto : 12,5 t par pêcheur en tout (%s)" % total)

	# --- régler un lac : le stock passe à la main, les autres lacs gardent leur valeur
	m.lake_spins[1]["cap"].value = 80.0
	m.lake_spins[0]["stock"].value = 50.0
	m.lake_spins[2]["growth"].value = 0.6
	cfg = m.build_config()
	check(not m.capacity_auto and cfg["lake"]["lakes"][1]["capacity"] == 80.0, "stock du deuxième lac : 80 t")
	check(is_equal_approx(cfg["lake"]["lakes"][0]["stock_ratio"], 0.5), "le premier lac part à moitié plein")
	check(is_equal_approx(cfg["lake"]["lakes"][2]["growth_rate"], 0.6), "le troisième se repeuple à 0,6")

	# --- les patrouilles et la part prenable
	m.chk_patrol.button_pressed = true
	m.spin_patrols.value = 3
	check(m.build_config()["patrols"] == 3 and m.spin_patrols.editable, "trois patrouilles")
	m.chk_patrol.button_pressed = false
	check(m.build_config()["patrols"] == 0 and not m.spin_patrols.editable, "décochée : aucune patrouille, nombre grisé")
	m.chk_patrol.button_pressed = true
	m.spin_hold.value = 70
	check(is_equal_approx(m.build_config()["hold_fraction"], 0.7), "part prenable : 70 %")
	check("70 %" in m.lbl_cap_hint.text, "l'aide la cite : " + m.lbl_cap_hint.text)

	# --- la route entre les lacs : visible avec plusieurs lacs, et dans la demande
	check(m.row_travel.visible and is_equal_approx(m.spin_travel_days.value, 1.5) and m.spin_travel_cost.value == 10.0,
		"la route entre les lacs : 1,5 jour pour traverser la carte, 10 écus par jour de mer")
	m.spin_travel_days.value = 2.0
	m.spin_travel_cost.value = 25
	check(m.build_config()["travel_days"] == 2.0 and m.build_config()["travel_cost"] == 25.0, "la demande porte la route")

	# --- un lac dont plus aucun village n'a de pêcheur n'existe pas dans la demande
	var gone: Array = m.lakes_state[0]["villages"]
	var elsewhere: String = str(m.lakes_state[1]["villages"][0])
	for f in m.fishers:
		if gone.has(str(f["hamlet"])):
			f["hamlet"] = elsewhere
	check(m.build_config()["lake"]["lakes"].size() == 2, "deux lacs restent quand le premier n'a plus de pêcheur")
	m.reset_population()

	# --- aléatoire : les nombres de la vallée se grisent, la demande dit « random » et laisse la graine décider
	var asked := []
	m.generate_requested.connect(func(p: Dictionary) -> void: asked.append(p))
	m.opt_genmode.select(1)
	m._set_gen_enabled()
	check(not m.spin_villages.editable and not m.spin_fishers.editable and not m.spin_lakes.editable and m.opt_fleet.disabled,
		"vallée aléatoire : villages, pêcheurs, lacs et flotte viennent de la graine")
	m._on_generate()
	check(asked.size() == 1 and asked[0]["mode"] == "random" and asked[0].has("seed") and asked[0]["lakes"] == 3,
		"la demande de vallée dit « random » : " + JSON.stringify(asked))
	m.opt_genmode.select(0)
	m._set_gen_enabled()
	check(m.spin_villages.editable and m.spin_lakes.editable and not m.opt_fleet.disabled, "paramétrée : tout se règle de nouveau")

	# --- le moteur répond (une vallée aléatoire : 2 lacs, 1 patrouille) : le menu reprend ce qu'il a tiré
	var drawn: Dictionary = cat.duplicate(true)
	drawn["lakes"] = [cat["lakes"][0], cat["lakes"][1]]
	drawn["lakes"][0]["villages"] = (cat["lakes"][0]["villages"] as Array) + (cat["lakes"][2]["villages"] as Array)
	drawn["generation"] = {"id": m._pending_generation, "villages": 6, "fishers": cat["base_population"].size(), "seed": 9,
		"fleet": "gros", "lakes": 2, "patrols": 2, "mode": "random"}
	m.set_catalog(drawn)
	check(m.opt_genmode.selected == 1 and int(m.spin_lakes.value) == 2 and int(m.spin_patrols.value) == 2 and m.chk_patrol.button_pressed,
		"le menu reprend la vallée tirée (2 lacs, 2 patrouilles)")
	check(m.lakes_state.size() == 2 and m.lake_spins.size() == 2, "deux lignes de lac")

	print("LAKESMENUTEST fails=%d lakes=%d" % [fails, lakes.size()])
	print("CONFIG:" + JSON.stringify(cfg))
	quit(1 if fails else 0)
