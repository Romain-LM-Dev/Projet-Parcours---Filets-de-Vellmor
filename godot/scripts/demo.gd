## Lecteur de la vidéo de démonstration : rejoue un journal dans `main._on_event` au rythme du scénario (temps de VIDÉO, pas
## d'horloge réelle), pilote la caméra, les mailles, l'onglet et l'inspecteur, lit la voix et affiche le sous-titre.
##   godot --path godot -- --demo=/chemin/scenario.json     (avec --write-movie pour enregistrer)
extends Node

const TITLE_S := 3.0
const CAM_S := 1.3

var main
var beats: Array = []
var events: Array = []
var next_ev := 0
var inds: Array = []                 # indicateurs (cartes KPI, courbes), rejoués au même temps simulé
var next_ind := 0
var chunks: Array = []               # le sous-titre découpé en phrases (deux lignes au plus chacun)
var band: PanelContainer
var narr_len := 1.0
var bi := -1                         # temps en cours
var narr_left := 0.0
var bt := 0.0                        # horloge du temps en cours (secondes de vidéo)
var dur := 0.0                       # durée à l'écran : voix + hold
var t_end := 0.0                     # fin de la portion de partie couverte par ce temps
var sched: Array = []                # [instant de lecture, 0 événement | 1 indicateur, indice], dans l'ordre
var sched_i := 0
var pace: Dictionary = {}
var elapsed := 0.0
var end_left := -1.0
var player: AudioStreamPlayer
var sub: Label
var title: ColorRect
var title_label: Label
var end_lines: Array = []
var cam_t := 1.0
var cam_from := Vector2.ZERO         # (zoom, _) de départ
var cam_off_from := Vector2.ZERO
var cam_to_zoom := 1.0
var cam_to_ground := Vector2(0.5, 0.5)
var base_dir := ""


func start(m, path: String) -> void:
	main = m
	if path.begins_with("res://"):
		path = ProjectSettings.globalize_path(path)
	base_dir = path.get_base_dir()
	var sc: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(path))
	beats = sc["beats"]
	pace = sc["pace"]
	end_lines = sc.get("end", [])
	var run_path: String = str(sc["run"])
	if not FileAccess.file_exists(run_path):
		run_path = base_dir.path_join("../..").path_join(run_path).simplify_path()
	for line in FileAccess.get_file_as_string(run_path).split("\n"):
		if line.strip_edges() != "":
			events.append(JSON.parse_string(line))
	var ipath := run_path.get_base_dir().path_join("indicators.jsonl")
	if FileAccess.file_exists(ipath):
		for line in FileAccess.get_file_as_string(ipath).split("
"):
			if line.strip_edges() != "":
				inds.append(JSON.parse_string(line))
	player = AudioStreamPlayer.new()
	add_child(player)
	var layer := CanvasLayer.new()
	layer.layer = 100
	add_child(layer)
	band = PanelContainer.new()
	var sb := StyleBoxFlat.new()
	sb.bg_color = Color(0, 0, 0, 0.72)
	sb.set_corner_radius_all(10)
	sb.set_content_margin_all(12)
	band.add_theme_stylebox_override("panel", sb)
	band.mouse_filter = Control.MOUSE_FILTER_IGNORE
	layer.add_child(band)
	sub = Label.new()
	sub.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	sub.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	sub.add_theme_font_size_override("font_size", 20)
	sub.add_theme_color_override("font_color", Color.WHITE)
	band.add_child(sub)
	band.visible = false
	title = ColorRect.new()
	title.color = Color("#0b1020")
	title.set_anchors_preset(Control.PRESET_FULL_RECT)
	var tl := Label.new()
	tl.text = "%s\n%s" % [sc.get("title", ""), sc.get("subtitle", "")]
	title_label = tl
	tl.set_anchors_preset(Control.PRESET_FULL_RECT)
	tl.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	tl.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	tl.add_theme_font_size_override("font_size", 44)
	title.add_child(tl)
	layer.add_child(title)
	main.lbl_status.text = "démonstration"
	main.lbl_subtitle.text = sc.get("subtitle", "")
	main.world.time_scale = 1.0


## Émet tous les événements dont `sim_time` est atteint.
func _feed_until(t: float) -> void:
	while next_ev < events.size() and float(events[next_ev].get("sim_time", 0.0)) <= t + 1e-6:
		main._on_event(events[next_ev])
		next_ev += 1
	while next_ind < inds.size() and float(inds[next_ind].get("sim_time", 0.0)) <= t + 1e-6:
		main._on_indicator(inds[next_ind])
		next_ind += 1


func _ground(target: String) -> Vector2:
	var w = main.world
	var kind := target.get_slice(":", 0)
	var nm := target.get_slice(":", 1)
	if kind == "village" and w.hamlet_pos.has(nm):
		return w.hamlet_pos[nm]
	if kind == "lake":
		for lk in w.lakes:
			if str(lk.get("name", "")) == nm or str(lk.get("label", "")) == nm:
				return lk["c"]
	return Vector2(0.5, 0.5)


## Phrases regroupées par morceaux d'au plus ~150 signes (deux lignes de sous-titre).
func _split(text: String) -> Array:
	var out: Array = []
	var cur := ""
	for sent in text.replace(". ", ".|").replace(" ; ", " ;|").split("|"):
		if cur != "" and cur.length() + sent.length() > 150:
			out.append(cur)
			cur = ""
		cur += ("" if cur == "" else " ") + sent
	out.append(cur)
	return out


## Montre le morceau qui correspond à l'avancée `f` (0..1) de la narration, en proportion de sa longueur.
func _show_chunk(f: float) -> void:
	var total := 0
	for c in chunks:
		total += c.length()
	var acc := 0.0
	for c in chunks:
		acc += float(c.length()) / total
		if f <= acc:
			sub.text = c
			return
	sub.text = chunks[-1]


## Le bandeau reste au bas de la carte, au-dessus de la barre du bas.
func _band_w() -> float:
	return main.world.size.x - clampf(main.world.size.x * 0.17, 130.0, 230.0) - 56.0   # largeur de la mini-carte : world_view._mini_rect


func _place_band() -> void:
	var r: Rect2 = main.world.get_global_rect()
	band.position = Vector2(r.position.x + 16.0, r.end.y - 96.0 - band.size.y)   # au-dessus de la légende
	band.size.x = _band_w()                                                      # à gauche de la mini-carte


## Répartit la durée du temps (voix + hold) entre les événements visibles de la portion [t, t suivant] : chacun pèse `pace[type]`
## (0 si absent), chaque jour simulé pèse `per_day` ; l'horloge de lecture avance d'événement en événement. Deux temps au même t :
## partie figée. Une réplique reste au moins 2,5 s à l'écran (la durée s'allonge sinon).
func _schedule(b: Dictionary) -> void:
	var t0 := float(b["t"])
	t_end = t0
	if bi + 1 < beats.size():
		t_end = float(beats[bi + 1]["t"])
	else:
		t_end = float(events[-1].get("sim_time", t0))
	dur = narr_left + float(b.get("hold", 0.0))
	bt = 0.0
	sched = []
	sched_i = 0
	if t_end <= t0:
		return
	var per_day: float = float(pace.get("per_day", 0.0))
	var items: Array = []                # [sim_time, genre, indice]
	var a := next_ev
	var c := next_ind
	while true:
		var ta: float = float(events[a].get("sim_time", 0.0)) if a < events.size() else INF
		var tc: float = float(inds[c].get("sim_time", 0.0)) if c < inds.size() else INF
		if minf(ta, tc) > t_end + 1e-6:
			break
		if ta <= tc:
			items.append([ta, 0, a])
			a += 1
		else:
			items.append([tc, 1, c])
			c += 1
	next_ev = a
	next_ind = c
	var w := 0.0
	var s := t0
	var utter := 0
	var marks: Array = []
	for it in items:
		w += (it[0] - s) * per_day
		s = it[0]
		marks.append(w)
		if it[1] == 0:
			var ty := str(events[it[2]].get("type", ""))
			w += float(pace.get(ty, 0.0))
			utter += 1 if ty == "utterance" else 0
	w += (t_end - s) * per_day
	var scale := dur / maxf(w, 1e-6)
	if utter > 0:
		scale = maxf(scale, 2.5 / float(pace.get("utterance", 3.0)))
		dur = maxf(dur, w * scale)
	for k in items.size():
		sched.append([marks[k] * scale, items[k][1], items[k][2]])
	print("DEMO temps %d : t %.2f -> %.2f, %d éléments, %.1f s à l'écran, %.2f s par unité de poids" % [bi, t0, t_end, items.size(), dur, scale])


func _begin(b: Dictionary) -> void:
	var w = main.world
	var cam := str(b.get("camera", ""))
	if cam != "":
		cam_from = Vector2(w.zoom, 0.0)
		cam_off_from = w.cam_off
		cam_t = 0.0
		w.glide = false
		cam_to_ground = Vector2(0.5, 0.5)
		if cam == "overview":
			cam_to_zoom = w.zoom_min
		elif cam == "fit":
			cam_to_zoom = 1.0
		else:
			cam_to_zoom = 2.2
			cam_to_ground = _ground(cam)
	if b.has("mesh"):
		w.show_mesh = bool(b["mesh"])
		w.mat.set_shader_parameter("mesh", w.show_mesh)
	if b.has("tab"):
		for i in main.tabs.get_tab_count():
			if main.tabs.get_tab_title(i) == str(b["tab"]):
				main.tabs.current_tab = i
	if b.has("inspect"):
		w.agent_clicked.emit(str(b["inspect"]))
		main.tabs.current_tab = main.inspector.get_index()
	var wav := base_dir.path_join("voice/%02d.wav" % bi)
	player.stream = AudioStreamWAV.load_from_file(wav)
	player.play()
	narr_left = player.stream.get_length()
	_schedule(b)
	chunks = _split(str(b["say"]))
	narr_len = maxf(narr_left, 0.1)
	_show_chunk(0.0)
	band.visible = not OS.get_cmdline_user_args().has("--no-captions")   # sans sous-titre : images pour un autre montage


func _step_cam(delta: float) -> void:
	if cam_t >= 1.0:
		return
	var w = main.world
	cam_t = minf(cam_t + delta / CAM_S, 1.0)
	var k := smoothstep(0.0, 1.0, cam_t)
	w.zoom = lerpf(cam_from.x, cam_to_zoom, k)
	var goal: Vector2 = w.size * 0.5 - w._px(cam_to_ground) * cam_to_zoom
	w.cam_off = cam_off_from.lerp(goal, k)
	w._apply_cam()


func _process(delta: float) -> void:
	_step_cam(delta)
	if band != null and band.visible:
		band.custom_minimum_size.x = _band_w()
		band.size.y = 0.0
		_place_band()
		_show_chunk(minf(bt / narr_len, 1.0))
	elapsed += delta
	if end_left >= 0.0:
		end_left -= delta
		if end_left < 0.0:
			get_tree().quit()
		return
	if bi < 0:
		_feed_until(0.0)
		if elapsed < TITLE_S:
			return
		title.visible = false
		bi = 0
		_begin(beats[0])
		return
	bt += delta
	while sched_i < sched.size() and sched[sched_i][0] <= bt:
		var e: Array = sched[sched_i]
		if e[1] == 0:
			main._on_event(events[e[2]])
		else:
			main._on_indicator(inds[e[2]])
		sched_i += 1
	if bt >= dur:
		_feed_until(t_end)               # tout ce qui reste de la portion
		if bi + 1 >= beats.size():
			end_left = 3.0                # carte de fin
			band.visible = false
			title_label.text = "
".join(PackedStringArray(end_lines))
			title.visible = true
			return
		bi += 1
		_begin(beats[bi])
