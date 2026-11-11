## Test hors fenêtre du lecteur de démo : le scénario se charge et les temps s'enchaînent jusqu'à la carte de fin (temps de vidéo
## simulé par grands pas, sans capture).   godot --headless --path godot -s res://tests/demo_test.gd
extends SceneTree

var fails := 0


func check(cond: bool, what: String) -> void:
	if not cond:
		fails += 1
		print("FAIL ", what)


func _initialize() -> void:
	var root_dir := ProjectSettings.globalize_path("res://").path_join("..")
	var Main = load("res://scripts/main.gd")
	var m = Main.new()
	root.add_child(m)
	await process_frame
	await process_frame
	m.set_process(false)
	var d = load("res://scripts/demo.gd").new()
	root.add_child(d)
	d.start(m, root_dir.path_join("docs/demo/scenario.json").simplify_path())
	check(d.beats.size() > 5 and d.events.size() > 100, "le scénario et le journal sont chargés (%d temps, %d événements)" % [d.beats.size(), d.events.size()])
	var seen := {}
	var steps := 0
	while d.end_left < 0.0 and steps < 5000:
		d._process(0.25)
		if d.bi >= 0:
			seen[d.bi] = true
		steps += 1
	check(d.end_left >= 0.0, "la lecture arrive à la fin (%d pas)" % steps)
	check(seen.size() == d.beats.size(), "tous les temps ont été joués (%d sur %d)" % [seen.size(), d.beats.size()])
	check(d.next_ev == d.events.size() and d.next_ind == d.inds.size(), "tous les événements et indicateurs sont rejoués")
	check("tragédie" not in d.main.lbl_subtitle.text, "bandeau : " + d.main.lbl_subtitle.text)
	check(d.title.visible and d.title_label.text != "" and "tragédie" not in d.title_label.text, "carte de fin : " + d.title_label.text)
	print("DEMOTEST fails=%d temps=%d pas=%d" % [fails, seen.size(), steps])
	quit(1 if fails else 0)
