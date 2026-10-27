## Test hors fenêtre de la génération de la vallée, contre un vrai moteur : le joueur règle « Villages » et « Pêcheurs » dans le menu,
## l'interface demande la vallée au moteur et affiche la nouvelle carte ; si le moteur refuse, l'erreur est lisible.
##   godot --headless --path godot -s res://tests/generate_test.gd -- --url=ws://127.0.0.1:PORT
extends SceneTree

var fails := 0


func check(cond: bool, what: String) -> void:
	if not cond:
		fails += 1
		print("FAIL ", what)


## Attend (jusqu'à `secs` secondes) que la condition soit vraie.
func until(cond: Callable, secs: float) -> bool:
	var t := 0.0
	while not cond.call() and t < secs:
		await create_timer(0.1).timeout
		t += 0.1
	return cond.call()


func distinct_villages(menu) -> int:
	var seen := {}
	for f in menu.fishers:
		seen[str(f["hamlet"])] = true
	return seen.size()


func _initialize() -> void:
	var Main = load("res://scripts/main.gd")
	var m = Main.new()
	root.add_child(m)
	await process_frame
	var menu = m.menu
	var got: bool = await until(func() -> bool: return not menu.catalog.is_empty() and menu.visible, 25.0)
	check(got, "le menu reçoit le catalogue du moteur et s'ouvre")
	if not got:
		print("GENERATETEST fails=%d" % (fails + 0))
		quit(1)
		return
	check(menu.catalog["hamlets"].size() == 4 and menu.fishers.size() == 8, "au départ : quatre villages, huit pêcheurs")

	# --- le joueur règle le nombre de villages, sans cliquer sur rien d'autre
	menu.spin_villages.value = 6
	var six: bool = await until(func() -> bool: return menu.catalog["hamlets"].size() == 6 and menu.fishers.size() == 8, 10.0)
	check(six, "six villages après avoir réglé « Villages » sur 6")
	check(distinct_villages(menu) == 6 and menu.map.hamlets.size() == 6, "les huit pêcheurs sont répartis dans six villages, sur la carte aussi")
	check(menu.spin_villages.value == 6 and menu.spin_fishers.value == menu.fishers.size() and not menu.btn_generate.disabled,
		"les nombres disent ce que contient la vallée, le bouton est libre")
	var cfg: Dictionary = menu.build_config()
	var asked := {}
	for f in cfg["population"]["fishers"]:
		asked[str(f["hamlet"])] = true
	check(asked.size() == 6, "la demande de partie porte les six villages")

	# --- moins de pêcheurs que de villages : on suit le nombre qu'on vient de toucher
	menu.spin_fishers.value = 3
	check(menu.spin_villages.value == 3, "trois pêcheurs : pas plus de trois villages")
	var three: bool = await until(func() -> bool: return menu.catalog["hamlets"].size() == 3 and menu.fishers.size() == 3, 10.0)
	check(three and distinct_villages(menu) == 3, "trois villages, un pêcheur chacun")

	# --- le moteur refuse : l'erreur se lit et le bouton se libère
	m._on_menu_generate({"villages": 9, "fishers": 12, "seed": 42, "id": "refus"})
	var refused: bool = await until(func() -> bool: return menu.lbl_error.text != "", 10.0)
	check(refused and "villages" in menu.lbl_error.text and not menu.btn_generate.disabled,
		"un refus du moteur s'affiche : " + menu.lbl_error.text)

	# --- une vallée valable efface l'erreur
	menu.spin_villages.value = 2
	var two: bool = await until(func() -> bool: return menu.catalog["hamlets"].size() == 2 and menu.lbl_error.text == "", 10.0)
	check(two, "deux villages, l'erreur disparaît")
	# --- la flotte : 24 pêcheurs aux gros bateaux, puis aux petits
	menu.spin_fishers.value = 24
	for fleet in ["gros", "petits"]:
		for i in menu.opt_fleet.item_count:
			if str(menu.opt_fleet.get_item_metadata(i)) == fleet:
				menu.opt_fleet.select(i)
				menu.opt_fleet.item_selected.emit(i)
		var done: bool = await until(func() -> bool: return str(menu.catalog.get("generation", {}).get("fleet", "")) == fleet and menu.fishers.size() == 24, 10.0)
		var boat := "cotre" if fleet == "gros" else "barque"
		var n := 0
		for f in menu.fishers:
			if f["boat"] == boat:
				n += 1
		check(done and n >= 8, "flotte « %s » : au moins huit %s sur 24 (%d)" % [fleet, boat, n])
	print("GENERATETEST fails=%d villages=%d fishers=%d" % [fails, menu.catalog["hamlets"].size(), menu.fishers.size()])
	quit(1 if fails > 0 else 0)
