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
var sim := 0.0
var bi := -1                         # temps en cours
var narr_left := 0.0
var hold := 0.0                      # attente après la narration quand rate = 0
var elapsed := 0.0
var end_left := -1.0
var player: AudioStreamPlayer
var sub: Label
var title: ColorRect
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
	tl.text = "FILETS\nLa tragédie des communs au lac de Vellmor"
	tl.set_anchors_preset(Control.PRESET_FULL_RECT)
	tl.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	tl.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	tl.add_theme_font_size_override("font_size", 44)
	title.add_child(tl)
	layer.add_child(title)
	main.lbl_status.text = "démonstration"
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


## Phrases regroupées par morceaux d'au plus ~190 signes (deux lignes de sous-titre).
func _split(text: String) -> Array:
	var out: Array = []
	var cur := ""
	for sent in text.replace(". ", ".|").replace(" ; ", " ;|").split("|"):
		if cur != "" and cur.length() + sent.length() > 190:
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
func _place_band() -> void:
	var r: Rect2 = main.world.get_global_rect()
	band.position = Vector2(r.position.x + 16.0, r.end.y - 12.0 - band.size.y)
	band.size.x = r.size.x - 32.0


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
	hold = 0.5
	chunks = _split(str(b["say"]))
	narr_len = maxf(narr_left, 0.1)
	_show_chunk(0.0)
	band.visible = true


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
		band.custom_minimum_size.x = main.world.size.x - 32.0
		band.size.y = 0.0
		_place_band()
		_show_chunk(1.0 - maxf(narr_left, 0.0) / narr_len)
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
	var b: Dictionary = beats[bi]
	var nxt: float = float(beats[bi + 1]["t"]) if bi + 1 < beats.size() else INF
	var rate: float = float(b.get("rate", 0.0))
	if rate > 0.0:
		sim = minf(sim + rate * delta, nxt)
		_feed_until(sim)
	narr_left -= delta
	if narr_left <= 0.0:
		if rate <= 0.0:
			hold -= delta
		if (rate <= 0.0 and hold <= 0.0) or (rate > 0.0 and sim >= nxt):
			if bi + 1 >= beats.size():
				end_left = 2.0
				return
			sim = maxf(sim, nxt)
			_feed_until(sim)
			bi += 1
			_begin(beats[bi])
