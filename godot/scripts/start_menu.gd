## Menu de démarrage : tout ce qu'on règle avant de lancer une partie.
##
##   gauche  — le monde : mode de temps, saisons, veillées, l'ancien, limite du stock du lac
##   centre  — l'IA (moteur, réflexion, vitesse au départ), puis les pêcheurs : prénom, hameau, archétype, expérience, avoir,
##             dette, cerveau (IA ou règles)
##   droite  — la vallée : où ils habitent (glisser un pêcheur d'un hameau à l'autre) et sa fiche
##
## Tout vient du catalogue envoyé par le moteur (archétypes, hameaux, composition de base, limites) :
## rien n'est recopié ici. Le moteur valide la demande ; ce menu ne fait que la construire.
extends Control

const MenuMap := preload("res://scripts/menu_map.gd")

signal start_requested(config: Dictionary)
signal cancelled

const W_IDX := 40
const W_NAME := 96
const W_HAMLET := 94
const W_ARCH := 146
const W_EXP := 58
const W_WEALTH := 70
const W_DEBT := 58
const W_BRAIN := 96
const W_DEL := 28

const BRAINS := [["IA · auto", "llm", "auto"], ["IA · grand", "llm", "grand"], ["IA · petit", "llm", "petit"],
	["Règles", "rule", "auto"]]

var catalog := {}
var fishers: Array = []
var selected := -1
var mode := "sync"
var capacity_auto := true             # tant que le joueur n'a pas fixé le stock du lac, il suit le nombre de pêcheurs
var speed_touched := false            # tant qu'il n'a pas choisi la vitesse, on propose celle qui convient au moteur d'IA
var reflection_touched := false       # de même pour la réflexion (les réflexes « open » demandent la réflexion adaptative)
var can_cancel := false
var engine_state := ""
var engine_detail := ""
var engine_online := true
var busy := false
var busy_since := 0

var _rows: Array = []                 # un dictionnaire de widgets par ligne
var _updating := false                # évite les boucles quand on règle un widget par code

var sheet: PanelContainer
var lbl_engine: Label
var mode_buttons := {}
var lbl_mode_desc: Label
var spin_seasons: SpinBox
var spin_seed: SpinBox
var spin_rounds: SpinBox
var spin_capacity: SpinBox
var btn_cap_auto: Button
var spin_growth: SpinBox
var btn_growth_default: Button
var chk_stop_empty: CheckButton
var lbl_cap_hint: Label
var opt_comm: OptionButton
var chk_visible: CheckButton
var opt_llm: OptionButton
var lbl_llm_desc: Label
var opt_reflection: OptionButton
var lbl_reflection_desc: Label
var lbl_async_warning: Label
var opt_speed: OptionButton
var lbl_speed_hint: Label
var chk_elder: CheckButton
var opt_elder: OptionButton
var rows_box: VBoxContainer
var lbl_count: Label
var lbl_lake: Label
var btn_add: Button
var map: Control
var detail: RichTextLabel
var lbl_error: Label
var btn_start: Button
var btn_cancel: Button


func _ready() -> void:
	visible = false
	mouse_filter = Control.MOUSE_FILTER_STOP
	_build()
	# Un contrôle masqué ne suit pas toujours le redimensionnement de son parent : on recale le menu à chaque affichage
	# et à chaque changement de taille de la fenêtre.
	_fit()
	if get_parent() is Control:
		(get_parent() as Control).resized.connect(_fit)


func _fit() -> void:
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)


# ------------------------------------------------------------------ construction
func _lbl(text: String, size: int = 13, kind: String = "ui", col: Color = Art.INK) -> Label:
	var l := Label.new()
	l.text = text
	l.add_theme_font_override("font", Art.font(kind))
	l.add_theme_font_size_override("font_size", size)
	l.add_theme_color_override("font_color", col)
	return l


func _section(text: String) -> Label:
	return _lbl(text.to_upper(), 10, "ui_black", Art.MUTED)


func _compact(le: LineEdit) -> void:
	for st in ["normal", "focus", "read_only"]:
		var sb := Art.box(Color("#0f1525"), 7, Art.LINE if st != "focus" else Color(Art.TALK, 0.6), 1)
		sb.content_margin_left = 7
		sb.content_margin_right = 5
		sb.content_margin_top = 3
		sb.content_margin_bottom = 3
		le.add_theme_stylebox_override(st, sb)
	le.add_theme_font_size_override("font_size", 13)
	le.add_theme_constant_override("minimum_character_width", 2)


func _spin(lo: float, hi: float, step: float, value: float, width: int) -> SpinBox:
	var sp := SpinBox.new()
	sp.min_value = lo
	sp.max_value = hi
	sp.step = step
	sp.set_value_no_signal(value)
	sp.custom_minimum_size = Vector2(width, 0)
	sp.select_all_on_focus = true
	_compact(sp.get_line_edit())
	return sp


func _option(items: Array, width: int = 0) -> OptionButton:
	var o := OptionButton.new()
	for it in items:
		o.add_item(str(it))
	o.add_theme_font_size_override("font_size", 13)
	if width > 0:
		o.custom_minimum_size = Vector2(width, 0)
	o.fit_to_longest_item = false
	o.clip_text = true
	o.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	return o


func _seg(text: String, group: ButtonGroup) -> Button:
	var b := Button.new()
	b.text = text
	b.toggle_mode = true
	b.button_group = group
	b.focus_mode = Control.FOCUS_NONE
	b.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var on := Art.box(Color(Art.TALK, 0.26), 9, Color(Art.TALK, 0.85), 1)
	on.content_margin_left = 12
	on.content_margin_right = 12
	on.content_margin_top = 6
	on.content_margin_bottom = 6
	b.add_theme_stylebox_override("pressed", on)
	b.add_theme_stylebox_override("hover_pressed", on)
	b.add_theme_color_override("font_pressed_color", Color.WHITE)
	b.add_theme_color_override("font_hover_pressed_color", Color.WHITE)
	return b


func _row(parent: Control, title: String, w: Control) -> void:
	var h := HBoxContainer.new()
	h.add_theme_constant_override("separation", 8)
	var l := _lbl(title, 13, "ui", Art.MUTED)
	l.custom_minimum_size = Vector2(86, 0)
	l.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	h.add_child(l)
	w.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	h.add_child(w)
	parent.add_child(h)


func _build() -> void:
	var dim := ColorRect.new()
	dim.color = Color(0.02, 0.03, 0.07, 0.86)
	dim.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(dim)
	var margin := MarginContainer.new()
	margin.set_anchors_preset(Control.PRESET_FULL_RECT)
	for side in ["left", "right", "top", "bottom"]:
		margin.add_theme_constant_override("margin_" + side, 12)
	add_child(margin)
	sheet = PanelContainer.new()
	sheet.add_theme_stylebox_override("panel", Art.box(Art.PANEL, 18, Color(1, 1, 1, 0.14), 1, 24))
	margin.add_child(sheet)
	var inner := MarginContainer.new()
	for side in ["left", "right"]:
		inner.add_theme_constant_override("margin_" + side, 22)
	inner.add_theme_constant_override("margin_top", 16)
	inner.add_theme_constant_override("margin_bottom", 14)
	sheet.add_child(inner)
	var root := VBoxContainer.new()
	root.add_theme_constant_override("separation", 12)
	inner.add_child(root)

	# --- en-tête
	var head := HBoxContainer.new()
	head.add_theme_constant_override("separation", 14)
	root.add_child(head)
	head.add_child(_lbl("Nouvelle partie", 30, "title", Color("#f3dca8")))
	var sub := _lbl("Choisissez les règles du monde, puis ceux qui l'habitent.", 16, "title_italic", Art.MUTED)
	sub.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	head.add_child(sub)
	var sp := Control.new()
	sp.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	head.add_child(sp)
	lbl_engine = _lbl("", 12, "ui_bold", Art.MUTED)
	lbl_engine.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	head.add_child(lbl_engine)

	# --- corps : trois colonnes
	var body := HBoxContainer.new()
	body.add_theme_constant_override("separation", 18)
	body.size_flags_vertical = Control.SIZE_EXPAND_FILL
	root.add_child(body)
	_build_left(body)
	_build_center(body)
	_build_right(body)

	# --- pied
	var foot := HBoxContainer.new()
	foot.add_theme_constant_override("separation", 12)
	root.add_child(foot)
	lbl_error = _lbl("", 13, "ui_bold", Art.ACCUSE)
	lbl_error.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	lbl_error.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	lbl_error.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	foot.add_child(lbl_error)
	var reset := Button.new()
	reset.text = "Tout réinitialiser"
	reset.focus_mode = Control.FOCUS_NONE
	reset.pressed.connect(reset_all)
	foot.add_child(reset)
	btn_cancel = Button.new()
	btn_cancel.text = "Annuler"
	btn_cancel.focus_mode = Control.FOCUS_NONE
	btn_cancel.pressed.connect(func() -> void: cancelled.emit())
	foot.add_child(btn_cancel)
	btn_start = Button.new()
	btn_start.text = "Démarrer la partie"
	btn_start.focus_mode = Control.FOCUS_NONE
	btn_start.add_theme_font_size_override("font_size", 16)
	var go := Art.box(Color("#1f6b45"), 10, Color(Art.SUPPORT, 0.7), 1)
	go.content_margin_left = 26
	go.content_margin_right = 26
	go.content_margin_top = 9
	go.content_margin_bottom = 9
	btn_start.add_theme_stylebox_override("normal", go)
	var go_h := go.duplicate() as StyleBoxFlat
	go_h.bg_color = Color("#27885a")
	btn_start.add_theme_stylebox_override("hover", go_h)
	var go_d := go.duplicate() as StyleBoxFlat
	go_d.bg_color = Color("#27402f")
	go_d.border_color = Color(1, 1, 1, 0.1)
	btn_start.add_theme_stylebox_override("disabled", go_d)
	btn_start.pressed.connect(_on_start)
	foot.add_child(btn_start)


func _build_left(body: Control) -> void:
	var scroll := ScrollContainer.new()
	scroll.custom_minimum_size = Vector2(296, 0)
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	body.add_child(scroll)
	var col := VBoxContainer.new()
	col.add_theme_constant_override("separation", 9)
	col.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.add_child(col)

	col.add_child(_section("Le temps du monde"))
	var seg := HBoxContainer.new()
	seg.add_theme_constant_override("separation", 6)
	col.add_child(seg)
	var grp := ButtonGroup.new()
	for m in [["sync", "Synchrone"], ["async", "Asynchrone"]]:
		var b := _seg(m[1], grp)
		b.pressed.connect(func() -> void: _set_mode(m[0]))
		mode_buttons[m[0]] = b
		seg.add_child(b)
	lbl_mode_desc = _lbl("", 12, "ui", Color(Art.MUTED, 0.95))
	lbl_mode_desc.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	lbl_mode_desc.custom_minimum_size = Vector2(276, 0)
	col.add_child(lbl_mode_desc)
	# la mention « modifiable en cours de partie » est en bulle d'aide : la colonne est déjà haute
	for b in mode_buttons.values():
		(b as Button).tooltip_text = "Le mode pourra aussi être changé en cours de partie (dès la saison suivante)."
	lbl_mode_desc.tooltip_text = "Le mode pourra aussi être changé en cours de partie (dès la saison suivante)."
	lbl_mode_desc.mouse_filter = Control.MOUSE_FILTER_PASS

	col.add_child(HSeparator.new())
	col.add_child(_section("Durée et hasard"))
	spin_seasons = _spin(1, 50, 1, 10, 84)
	_row(col, "Saisons", spin_seasons)
	var seed_box := HBoxContainer.new()
	seed_box.add_theme_constant_override("separation", 6)
	spin_seed = _spin(0, 999999, 1, 42, 100)
	seed_box.add_child(spin_seed)
	var dice := Button.new()
	dice.text = "Au hasard"
	dice.focus_mode = Control.FOCUS_NONE
	dice.pressed.connect(func() -> void: spin_seed.value = randi() % 1000000)
	seed_box.add_child(dice)
	_row(col, "Graine", seed_box)

	col.add_child(HSeparator.new())
	col.add_child(_section("La vallée"))
	opt_comm = _option([])
	_row(col, "Veillées", opt_comm)
	spin_rounds = _spin(1, 3, 1, 2, 70)
	spin_rounds.tooltip_text = "Combien de fois chacun peut prendre la parole pendant une veillée"
	_row(col, "Tours de parole", spin_rounds)
	chk_visible = CheckButton.new()
	chk_visible.text = "Les prises sont connues de tous"
	chk_visible.button_pressed = true
	chk_visible.focus_mode = Control.FOCUS_NONE
	col.add_child(chk_visible)
	chk_elder = CheckButton.new()
	chk_elder.text = "Maître Oswin, l'ancien (arbitre)"
	chk_elder.button_pressed = true
	chk_elder.focus_mode = Control.FOCUS_NONE
	chk_elder.toggled.connect(func(_on: bool) -> void: _refresh_all())
	col.add_child(chk_elder)
	opt_elder = _option(["Cerveau : IA", "Cerveau : règles"])
	opt_elder.item_selected.connect(func(_i: int) -> void: _refresh_all())
	col.add_child(opt_elder)

	col.add_child(HSeparator.new())
	col.add_child(_section("Le lac"))
	var cap_box := HBoxContainer.new()
	cap_box.add_theme_constant_override("separation", 6)
	spin_capacity = _spin(10, 1000, 0.5, 100, 104)
	spin_capacity.suffix = "t"
	spin_capacity.tooltip_text = "Le stock du lac ne peut jamais dépasser cette valeur : c'est 100 % de la jauge. Il part de là."
	spin_capacity.value_changed.connect(func(_v: float) -> void:
		if not _updating:
			capacity_auto = false
			_refresh_all(false))
	cap_box.add_child(spin_capacity)
	btn_cap_auto = Button.new()
	btn_cap_auto.text = "Auto"
	btn_cap_auto.focus_mode = Control.FOCUS_NONE
	btn_cap_auto.pressed.connect(func() -> void:
		capacity_auto = true
		_refresh_all(false))
	cap_box.add_child(btn_cap_auto)
	_row(col, "Stock max", cap_box)
	var growth_box := HBoxContainer.new()
	growth_box.add_theme_constant_override("separation", 6)
	spin_growth = _spin(0.1, 2.0, 0.05, 1.0, 104)
	spin_growth.tooltip_text = "Taux de repeuplement r, par saison. Le lac se refait le plus vite à moitié plein : il y regagne " \
		+ "r × K / 4 tonnes (K = stock max). Plus r est petit, plus une pêche excessive se paie longtemps."
	spin_growth.value_changed.connect(func(_v: float) -> void:
		if not _updating:
			_refresh_all(false))
	growth_box.add_child(spin_growth)
	btn_growth_default = Button.new()
	btn_growth_default.text = "Normal"
	btn_growth_default.focus_mode = Control.FOCUS_NONE
	btn_growth_default.pressed.connect(func() -> void:
		spin_growth.value = float(catalog.get("defaults", {}).get("growth_rate", 1.0)))
	growth_box.add_child(btn_growth_default)
	_row(col, "Repeuplement", growth_box)
	chk_stop_empty = CheckButton.new()
	chk_stop_empty.text = "Arrêter si le lac est vide"
	chk_stop_empty.button_pressed = true
	chk_stop_empty.focus_mode = Control.FOCUS_NONE
	chk_stop_empty.tooltip_text = "Un lac tombé à 0 ne se repeuple jamais : la partie s'arrête dès le dernier poisson pêché."
	col.add_child(chk_stop_empty)
	lbl_cap_hint = _lbl("", 12, "ui", Color(Art.MUTED, 0.95))
	lbl_cap_hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	lbl_cap_hint.custom_minimum_size = Vector2(276, 0)
	col.add_child(lbl_cap_hint)


## Un choix d'IA avec son titre au-dessus : moteur, réflexion, vitesse tiennent sur une seule ligne, en haut de la colonne
## des pêcheurs (leur « cerveau » en dépend), à un endroit qu'on ne peut pas manquer.
func _ai_choice(title: String, opt: OptionButton, width: int) -> VBoxContainer:
	var v := VBoxContainer.new()
	v.add_theme_constant_override("separation", 3)
	v.add_child(_lbl(title.to_upper(), 10, "ui_black", Art.MUTED))
	opt.custom_minimum_size = Vector2(width, 0)
	v.add_child(opt)
	return v


func _note(col: Control, col_color: Color = Color(Art.MUTED, 0.95)) -> Label:
	var l := _lbl("", 12, "ui", col_color)
	l.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	l.custom_minimum_size = Vector2(300, 0)
	l.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	col.add_child(l)
	return l


func _build_ai_strip(col: Control) -> void:
	col.add_child(_section("Intelligence artificielle et rythme"))
	var strip := HBoxContainer.new()
	strip.add_theme_constant_override("separation", 12)
	col.add_child(strip)
	opt_llm = _option([])
	opt_llm.item_selected.connect(func(i: int) -> void:
		_show_llm(i)
		_suggest_reflection()
		_suggest_speed())
	strip.add_child(_ai_choice("Moteur d'IA", opt_llm, 236))
	opt_reflection = _option([])
	opt_reflection.item_selected.connect(func(i: int) -> void:
		if not _updating:
			reflection_touched = true
		_show_reflection(i))
	strip.add_child(_ai_choice("Réflexion", opt_reflection, 130))
	opt_speed = _option([])
	opt_speed.tooltip_text = "Synchrone : rythme d'affichage. Asynchrone : le temps du monde suit le temps réel à cette vitesse, " \
		+ "donc une IA lente paraît moins lente quand on ralentit."
	opt_speed.item_selected.connect(func(_i: int) -> void:
		if not _updating:
			speed_touched = true
			_refresh_hints())
	strip.add_child(_ai_choice("Vitesse au départ", opt_speed, 190))
	lbl_llm_desc = _note(col)
	lbl_reflection_desc = _note(col)
	lbl_speed_hint = _note(col)
	lbl_async_warning = _note(col, Art.PROPOSAL)
	lbl_async_warning.visible = false


func _build_center(body: Control) -> void:
	var col := VBoxContainer.new()
	col.add_theme_constant_override("separation", 8)
	col.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body.add_child(col)
	_build_ai_strip(col)
	col.add_child(HSeparator.new())
	var head := HBoxContainer.new()
	head.add_theme_constant_override("separation", 10)
	col.add_child(head)
	head.add_child(_section("Les pêcheurs"))
	lbl_count = _lbl("", 12, "ui_bold", Art.INK)
	head.add_child(lbl_count)
	lbl_lake = _lbl("", 12, "ui", Art.MUTED)
	lbl_lake.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	lbl_lake.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	head.add_child(lbl_lake)
	var tools := HBoxContainer.new()
	tools.add_theme_constant_override("separation", 8)
	col.add_child(tools)
	btn_add = Button.new()
	btn_add.text = "+ Ajouter un pêcheur"
	btn_add.focus_mode = Control.FOCUS_NONE
	btn_add.pressed.connect(_add_fisher)
	tools.add_child(btn_add)
	var base := Button.new()
	base.text = "Composition de base"
	base.focus_mode = Control.FOCUS_NONE
	base.tooltip_text = "Reprend les pêcheurs que le jeu génère par défaut"
	base.pressed.connect(reset_population)
	tools.add_child(base)
	# titres de colonnes, alignés sur les lignes
	var titles := HBoxContainer.new()
	titles.add_theme_constant_override("separation", 6)
	col.add_child(titles)
	var pad := Control.new()
	pad.custom_minimum_size = Vector2(8, 0)
	titles.add_child(pad)
	for t in [["", W_IDX], ["Prénom", W_NAME], ["Hameau", W_HAMLET], ["Archétype", W_ARCH], ["Expérience", W_EXP],
			["Avoir (écus)", W_WEALTH], ["Dette/saison", W_DEBT], ["Cerveau", W_BRAIN]]:
		var l := _lbl(str(t[0]), 10, "ui_black", Art.MUTED)
		l.custom_minimum_size = Vector2(int(t[1]), 0)
		titles.add_child(l)
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	col.add_child(scroll)
	rows_box = VBoxContainer.new()
	rows_box.add_theme_constant_override("separation", 4)
	rows_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.add_child(rows_box)


func _build_right(body: Control) -> void:
	var col := VBoxContainer.new()
	col.custom_minimum_size = Vector2(346, 0)
	col.add_theme_constant_override("separation", 8)
	body.add_child(col)
	col.add_child(_section("Disposition dans la vallée"))
	col.add_child(_lbl("Glissez un pêcheur d'un hameau à l'autre.", 12, "ui", Color(Art.MUTED, 0.9)))
	var frame := AspectRatioContainer.new()
	frame.ratio = 1.28
	frame.custom_minimum_size = Vector2(0, 300)
	frame.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	col.add_child(frame)
	map = MenuMap.new()
	map.token_selected.connect(_select)
	map.token_moved.connect(func(i: int, h: String) -> void:
		fishers[i]["hamlet"] = h
		_row_sync(i)
		_refresh_all())
	frame.add_child(map)
	col.add_child(_section("Fiche"))
	detail = RichTextLabel.new()
	detail.bbcode_enabled = true
	detail.size_flags_vertical = Control.SIZE_EXPAND_FILL
	detail.fit_content = false
	col.add_child(detail)


# ------------------------------------------------------------------ catalogue
func set_catalog(cat: Dictionary) -> void:
	# le moteur renvoie son catalogue avec chaque état : identique, on n'y touche pas (le joueur est peut-être en train
	# de régler sa partie) ; différent (autre moteur, autres options), on repart de ses valeurs par défaut
	if not catalog.is_empty() and JSON.stringify(cat) == JSON.stringify(catalog):
		return
	var first := true
	catalog = cat
	_updating = true
	opt_comm.clear()
	for c in cat.get("communications", []):
		opt_comm.add_item(str(c["label"]))
		opt_comm.set_item_metadata(opt_comm.item_count - 1, str(c["id"]))
	opt_llm.clear()
	for o in cat.get("llm_options", []):
		opt_llm.add_item(str(o["label"]))
		opt_llm.set_item_metadata(opt_llm.item_count - 1, str(o["id"]))
	opt_reflection.clear()
	for r in cat.get("reflections", []):
		opt_reflection.add_item(str(r["label"]))
		opt_reflection.set_item_metadata(opt_reflection.item_count - 1, str(r["id"]))
	opt_speed.clear()
	for s in cat.get("speeds", []):
		opt_speed.add_item(_speed_text(float(s)))
		opt_speed.set_item_metadata(opt_speed.item_count - 1, float(s))
	opt_speed.add_item("Maximale (sans attente)")
	opt_speed.set_item_metadata(opt_speed.item_count - 1, "max")
	var lim: Dictionary = cat.get("limits", {})
	var seasons: Array = lim.get("seasons", [1, 50])
	spin_seasons.min_value = seasons[0]
	spin_seasons.max_value = seasons[1]
	var rounds: Array = lim.get("assembly_rounds", [1, 3])
	spin_rounds.min_value = rounds[0]
	spin_rounds.max_value = rounds[1]
	var caps: Array = lim.get("capacity", [10, 1000])
	spin_capacity.min_value = caps[0]
	spin_capacity.max_value = caps[1]
	var rates: Array = lim.get("growth_rate", [0.1, 2.0])
	spin_growth.min_value = rates[0]
	spin_growth.max_value = rates[1]
	_updating = false
	if first:
		reset_all()
	else:
		_refresh_all()


func reset_all() -> void:
	if catalog.is_empty():
		return
	var d: Dictionary = catalog.get("defaults", {})
	_updating = true
	_set_mode(str(d.get("mode", "sync")))
	spin_seasons.value = int(d.get("seasons", 10))
	spin_seed.value = int(d.get("seed", 42))
	spin_rounds.value = int(d.get("assembly_rounds", 2))
	_select_meta(opt_comm, str(d.get("communication", "valley")))
	chk_visible.button_pressed = bool(d.get("catches_visible", true))
	_select_meta(opt_llm, str(d.get("llm", "scripted")))
	_select_meta(opt_reflection, str(d.get("reflection", "rapide")))
	chk_elder.button_pressed = bool(d.get("elder", true))
	opt_elder.select(0 if str(d.get("elder_kind", "llm")) == "llm" else 1)
	capacity_auto = d.get("capacity") == null
	if not capacity_auto:
		spin_capacity.value = float(d["capacity"])
	spin_growth.value = float(d.get("growth_rate", 1.0))
	chk_stop_empty.button_pressed = bool(d.get("stop_on_extinction", true))
	speed_touched = false
	reflection_touched = false
	_updating = false
	_show_llm(opt_llm.selected)
	_suggest_reflection()
	_show_reflection(opt_reflection.selected)
	_suggest_speed()
	reset_population()


func reset_population() -> void:
	fishers = []
	for s in catalog.get("base_population", []):
		fishers.append((s as Dictionary).duplicate(true))
	selected = -1
	_rebuild_rows()
	_refresh_all()


func _select_meta(o: OptionButton, meta: Variant) -> void:
	for i in o.item_count:
		if _same(o.get_item_metadata(i), meta):
			o.select(i)
			return


## Égalité sans erreur entre types différents (la liste des vitesses mêle des nombres et le mot « max »).
func _same(a: Variant, b: Variant) -> bool:
	var num_a := typeof(a) == TYPE_FLOAT or typeof(a) == TYPE_INT
	var num_b := typeof(b) == TYPE_FLOAT or typeof(b) == TYPE_INT
	if num_a and num_b:
		return is_equal_approx(float(a), float(b))
	return typeof(a) == typeof(b) and a == b


func _speed_text(s: float) -> String:
	if is_equal_approx(s, 0.0625):
		return "× 1/16"
	if is_equal_approx(s, 0.125):
		return "× 1/8"
	if is_equal_approx(s, 0.25):
		return "× ¼"
	if is_equal_approx(s, 0.5):
		return "× ½"
	return "× %d" % int(s) if is_equal_approx(s, round(s)) else "× %.2f" % s


func _llm_option() -> Dictionary:
	var opts: Array = catalog.get("llm_options", [])
	var i := opt_llm.selected
	return opts[i] if i >= 0 and i < opts.size() else {}


func _show_llm(i: int) -> void:
	var opts: Array = catalog.get("llm_options", [])
	lbl_llm_desc.text = str(opts[i]["detail"]) if i >= 0 and i < opts.size() else ""


func _show_reflection(i: int) -> void:
	var opts: Array = catalog.get("reflections", [])
	lbl_reflection_desc.text = str(opts[i]["detail"]) if i >= 0 and i < opts.size() else ""


## Un moteur d'IA peut demander sa réflexion (le catalogue la donne : `reflection`) : les réflexes d'un modèle de décision
## « open » ne servent qu'en réflexion adaptative. Tant que le joueur n'a pas choisi la sienne, on la propose.
func _suggest_reflection() -> void:
	if catalog.is_empty() or opt_reflection == null or reflection_touched:
		return
	var r := str(_llm_option().get("reflection", catalog.get("defaults", {}).get("reflection", "rapide")))
	var was := _updating
	_updating = true
	_select_meta(opt_reflection, r)
	_updating = was
	_show_reflection(opt_reflection.selected)


func _set_mode(m: String) -> void:
	mode = m
	for k in mode_buttons:
		(mode_buttons[k] as Button).set_pressed_no_signal(k == m)
	for md in catalog.get("modes", []):
		if str(md["id"]) == m:
			lbl_mode_desc.text = str(md["detail"])
	if not _updating:
		_suggest_speed()


## En asynchrone, le temps du monde suit le temps réel : pendant qu'une IA locale réfléchit, la veillée avance et peut se
## fermer sans elle. Il faut alors ralentir le monde. Tant que le joueur n'a pas choisi sa vitesse, on propose celle
## qui convient au moteur d'IA choisi (le catalogue la donne : `async_speed`).
func _recommended_speed() -> float:
	var default_speed := float(catalog.get("defaults", {}).get("speed", 1.0))
	if mode != "async":
		return default_speed
	var o := _llm_option()
	return float(o.get("async_speed", default_speed)) if not o.is_empty() else default_speed


func _suggest_speed() -> void:
	if catalog.is_empty() or opt_speed == null:
		return
	if not speed_touched:
		var was := _updating
		_updating = true
		_select_meta(opt_speed, _recommended_speed())
		_updating = was
	_refresh_hints()


func _refresh_hints() -> void:
	if lbl_speed_hint == null or catalog.is_empty() or opt_speed.selected < 0:
		return
	var o := _llm_option()
	var real_ai := not o.is_empty() and str(o["id"]) != "scripted"
	lbl_async_warning.text = ""
	lbl_async_warning.visible = false
	if mode != "async" or not real_ai:
		lbl_speed_hint.text = "Modifiable à tout moment pendant la partie."
		return
	var rec := _recommended_speed()
	var cur: Variant = opt_speed.get_item_metadata(opt_speed.selected)
	lbl_speed_hint.text = "Conseillée avec ce moteur en asynchrone : %s." % _speed_text(rec)
	if cur is String or float(cur) > rec + 0.0001:
		lbl_async_warning.text = ("En asynchrone, le monde continue d'avancer pendant que l'IA réfléchit. À cette vitesse, "
			+ "une IA locale ratera souvent sa pêche ou sa veillée (« réplique perdue »). Ralentissez le monde, ou "
			+ "choisissez le mode synchrone.")
		lbl_async_warning.visible = true


# ------------------------------------------------------------------ pêcheurs
func _archetypes() -> Array:
	return catalog.get("archetypes", [])


func _arch_index(id: String) -> int:
	var a := _archetypes()
	for i in a.size():
		if str(a[i]["id"]) == id:
			return i
	return 0


func _brain_index(f: Dictionary) -> int:
	for i in BRAINS.size():
		if BRAINS[i][1] == str(f["kind"]) and (BRAINS[i][1] == "rule" or BRAINS[i][2] == str(f["tier"])):
			return i
	return 0


func _add_fisher() -> void:
	var lim: Array = catalog.get("limits", {}).get("fishers", [1, 24])
	if fishers.size() >= int(lim[1]):
		return
	var counts := {}
	for h in catalog.get("hamlets", []):
		counts[str(h)] = 0
	for f in fishers:
		counts[str(f["hamlet"])] = int(counts.get(str(f["hamlet"]), 0)) + 1
	var hamlet := ""
	for h in catalog.get("hamlets", []):
		if hamlet == "" or counts[str(h)] < counts[hamlet]:
			hamlet = str(h)
	var n := fishers.size()
	var archs := _archetypes()
	var a: Dictionary = archs[(n + n / 4) % archs.size()]
	var used := {}
	for f in fishers:
		used[str(f["first_name"])] = true
	var first := "Pêcheur %d" % (n + 1)
	for nm in catalog.get("first_names", []):
		if not used.has(str(nm)):
			first = str(nm)
			break
	fishers.append({"first_name": first, "hamlet": hamlet, "archetype": str(a["id"]), "experience": int(a["experience"]),
		"wealth": float(a["wealth"]), "debt_payment": float(a["debt_payment"]), "kind": "llm", "tier": "auto"})
	_rebuild_rows()
	_select(fishers.size() - 1)
	_refresh_all()


func _remove_fisher(i: int) -> void:
	if fishers.size() <= 1:
		return
	fishers.remove_at(i)
	if selected >= fishers.size():
		selected = fishers.size() - 1
	_rebuild_rows()
	_refresh_all()


func _rebuild_rows() -> void:
	for c in rows_box.get_children():
		rows_box.remove_child(c)
		c.queue_free()
	_rows.clear()
	var hamlets: Array = catalog.get("hamlets", [])
	var arch_labels: Array = []
	for a in _archetypes():
		arch_labels.append(str(Art.ARCH_LABEL.get(str(a["id"]), a["label"])))
	var lim: Dictionary = catalog.get("limits", {})
	for i in fishers.size():
		var f: Dictionary = fishers[i]
		var panel := PanelContainer.new()
		panel.add_theme_stylebox_override("panel", _row_style(false))
		rows_box.add_child(panel)
		var h := HBoxContainer.new()
		h.add_theme_constant_override("separation", 6)
		panel.add_child(h)
		var idx := Button.new()
		idx.text = "F%02d" % (i + 1)
		idx.flat = true
		idx.focus_mode = Control.FOCUS_NONE
		idx.custom_minimum_size = Vector2(W_IDX, 0)
		idx.add_theme_font_override("font", Art.font("ui_black"))
		idx.add_theme_font_size_override("font_size", 12)
		idx.pressed.connect(_select.bind(i))
		h.add_child(idx)
		var name_edit := LineEdit.new()
		name_edit.text = str(f["first_name"])
		name_edit.max_length = 14
		name_edit.custom_minimum_size = Vector2(W_NAME, 0)
		_compact(name_edit)
		name_edit.text_changed.connect(func(t: String) -> void:
			fishers[i]["first_name"] = t.strip_edges()
			_refresh_all(false))
		name_edit.focus_entered.connect(_select.bind(i))
		h.add_child(name_edit)
		var opt_h := _option(hamlets, W_HAMLET)
		opt_h.select(maxi(0, hamlets.find(str(f["hamlet"]))))
		opt_h.item_selected.connect(func(k: int) -> void:
			fishers[i]["hamlet"] = str(hamlets[k])
			_refresh_all())
		h.add_child(opt_h)
		var opt_a := _option(arch_labels, W_ARCH)
		opt_a.select(_arch_index(str(f["archetype"])))
		opt_a.item_selected.connect(func(k: int) -> void: _on_archetype(i, k))
		h.add_child(opt_a)
		var sp_e := _spin(float(lim.get("experience", [0, 60])[0]), float(lim.get("experience", [0, 60])[1]), 1,
			float(f["experience"]), W_EXP)
		sp_e.value_changed.connect(func(v: float) -> void:
			fishers[i]["experience"] = int(v)
			_refresh_all(false))
		h.add_child(sp_e)
		var sp_w := _spin(float(lim.get("wealth", [0, 5000])[0]), float(lim.get("wealth", [0, 5000])[1]), 10,
			float(f["wealth"]), W_WEALTH)
		sp_w.value_changed.connect(func(v: float) -> void: fishers[i]["wealth"] = v)
		h.add_child(sp_w)
		var sp_d := _spin(float(lim.get("debt_payment", [0, 500])[0]), float(lim.get("debt_payment", [0, 500])[1]), 10,
			float(f["debt_payment"]), W_DEBT)
		sp_d.value_changed.connect(func(v: float) -> void: fishers[i]["debt_payment"] = v)
		h.add_child(sp_d)
		var brain_labels: Array = []
		for b in BRAINS:
			brain_labels.append(b[0])
		var opt_b := _option(brain_labels, W_BRAIN)
		opt_b.select(_brain_index(f))
		opt_b.item_selected.connect(func(k: int) -> void:
			fishers[i]["kind"] = BRAINS[k][1]
			fishers[i]["tier"] = BRAINS[k][2]
			_refresh_all())
		h.add_child(opt_b)
		var del := Button.new()
		del.text = "×"
		del.focus_mode = Control.FOCUS_NONE
		del.custom_minimum_size = Vector2(W_DEL, 0)
		del.tooltip_text = "Retirer ce pêcheur"
		del.pressed.connect(_remove_fisher.bind(i))
		h.add_child(del)
		_rows.append({"panel": panel, "name": name_edit, "hamlet": opt_h, "arch": opt_a, "exp": sp_e, "wealth": sp_w,
			"debt": sp_d, "brain": opt_b, "del": del})


func _row_style(sel: bool) -> StyleBoxFlat:
	var sb := Art.box(Color(Art.TALK, 0.13) if sel else Color(1, 1, 1, 0.03), 9, Color(Art.TALK, 0.55) if sel else Color(0, 0, 0, 0), 1 if sel else 0)
	sb.content_margin_left = 8
	sb.content_margin_right = 6
	sb.content_margin_top = 3
	sb.content_margin_bottom = 3
	return sb


func _on_archetype(i: int, k: int) -> void:
	var a: Dictionary = _archetypes()[k]
	var f: Dictionary = fishers[i]
	f["archetype"] = str(a["id"])
	# l'archétype fixe un profil de départ : les trois chiffres suivent, et restent modifiables ensuite
	f["experience"] = int(a["experience"])
	f["wealth"] = float(a["wealth"])
	f["debt_payment"] = float(a["debt_payment"])
	_row_sync(i)
	_refresh_all()


func _row_sync(i: int) -> void:
	if i < 0 or i >= _rows.size():
		return
	var f: Dictionary = fishers[i]
	var r: Dictionary = _rows[i]
	(r["hamlet"] as OptionButton).select(maxi(0, (catalog.get("hamlets", []) as Array).find(str(f["hamlet"]))))
	(r["arch"] as OptionButton).select(_arch_index(str(f["archetype"])))
	(r["exp"] as SpinBox).set_value_no_signal(float(f["experience"]))
	(r["wealth"] as SpinBox).set_value_no_signal(float(f["wealth"]))
	(r["debt"] as SpinBox).set_value_no_signal(float(f["debt_payment"]))


func _select(i: int) -> void:
	selected = i
	for k in _rows.size():
		(_rows[k]["panel"] as PanelContainer).add_theme_stylebox_override("panel", _row_style(k == i))
	_refresh_all(false)


func _tier_text(f: Dictionary) -> String:
	if str(f["kind"]) == "rule":
		return "agent à règles : aucune IA, une règle fixe selon l'archétype"
	var large := int(catalog.get("defaults", {}).get("large_model_min_experience", 15))
	var t := str(f["tier"])
	if t == "auto":
		t = "grand" if int(f["experience"]) >= large else "petit"
		return "IA · modèle %s (choisi selon l'expérience : grand à partir de %d ans)" % [t, large]
	return "IA · modèle %s (choisi à la main)" % t


func _refresh_all(_full: bool = true) -> void:
	if catalog.is_empty() or map == null:
		return
	var d: Dictionary = catalog.get("defaults", {})
	var elder_kind := "llm" if opt_elder.selected == 0 else "rule"
	opt_elder.disabled = not chk_elder.button_pressed
	map.call("set_data", fishers, chk_elder.button_pressed, elder_kind, selected, int(d.get("large_model_min_experience", 15)))
	var lim: Array = catalog.get("limits", {}).get("fishers", [1, 24])
	lbl_count.text = "%d" % fishers.size()
	_refresh_lake()
	btn_add.disabled = fishers.size() >= int(lim[1])
	for r in _rows:
		(r["del"] as Button).disabled = fishers.size() <= 1
	if selected >= 0 and selected < fishers.size():
		var f: Dictionary = fishers[selected]
		var hc := Art.agent_color(f).lightened(0.2).to_html(false)
		var arch: Dictionary = _archetypes()[_arch_index(str(f["archetype"]))]
		var s := "[font=res://fonts/alegreya-latin-700-normal.woff2][font_size=20][color=#%s]%s[/color][/font_size][/font]  [color=#6f7896]F%02d[/color]\n" % [hc, str(f["first_name"]), selected + 1]
		s += "%s · hameau %s\n[color=#9ba1ba]%s[/color]\n\n" % [str(arch["label"]), str(f["hamlet"]), str(arch["summary"])]
		s += "%d ans de pêche · %s écus · dette %s écus/saison\n%s" % [int(f["experience"]), _num(float(f["wealth"])),
			_num(float(f["debt_payment"])), _tier_text(f)]
		detail.text = s
	else:
		detail.text = "[color=#8f97b2]Cliquez sur un pêcheur (dans la liste ou sur la carte) pour voir sa fiche.[/color]"


func _num(v: float) -> String:
	return str(int(v)) if is_equal_approx(v, round(v)) else "%.1f" % v


## Stock maximal du lac : choisi par le joueur, sinon 12,5 t par pêcheur (il suit alors le nombre de pêcheurs).
func lake_capacity() -> float:
	return spin_capacity.value


func _auto_capacity() -> float:
	var d: Dictionary = catalog.get("defaults", {})
	var caps: Array = catalog.get("limits", {}).get("capacity", [10, 1000])
	return clampf(float(d.get("capacity_per_fisher", 12.5)) * fishers.size(), float(caps[0]), float(caps[1]))


func _refresh_lake() -> void:
	var d: Dictionary = catalog.get("defaults", {})
	var auto_cap := _auto_capacity()
	if capacity_auto:
		var was := _updating
		_updating = true
		spin_capacity.set_value_no_signal(auto_cap)
		_updating = was
	var cap := spin_capacity.value
	var rate := spin_growth.value
	var yield_max := rate * cap / 4.0
	# une sortie rapporte au plus la capacité du lac / (2 × pêcheurs) : à eux tous, la moitié du lac au plus
	var reach := minf(float(d.get("boat_capacity", 10.0)) * fishers.size(), cap / 2.0)
	btn_cap_auto.disabled = capacity_auto
	btn_growth_default.disabled = is_equal_approx(rate, float(d.get("growth_rate", 1.0)))
	lbl_lake.text = "lac de %s t · rendement durable max %s t par saison" % [_num(cap), _num(yield_max)]
	var how := "Auto : %s t par pêcheur." % _num(float(d.get("capacity_per_fisher", 12.5))) if capacity_auto \
		else "Choisi à la main (auto : %s t)." % _num(auto_cap)
	lbl_cap_hint.text = ("%s Le lac part plein et ne dépasse jamais ce stock. À moitié plein, il regagne au mieux %s t par "
		+ "saison ; %d barques peuvent en ramener jusqu'à %s t.") % [how, _num(yield_max), fishers.size(), _num(reach)]


# ------------------------------------------------------------------ envoi
func build_config() -> Dictionary:
	var list: Array = []
	for f in fishers:
		list.append({"first_name": str(f["first_name"]), "hamlet": str(f["hamlet"]), "archetype": str(f["archetype"]),
			"experience": int(f["experience"]), "wealth": float(f["wealth"]), "debt_payment": float(f["debt_payment"]),
			"kind": str(f["kind"]), "tier": str(f["tier"])})
	return {
		"mode": mode, "seasons": int(spin_seasons.value), "seed": int(spin_seed.value),
		"communication": str(opt_comm.get_item_metadata(opt_comm.selected)), "catches_visible": chk_visible.button_pressed,
		"assembly_rounds": int(spin_rounds.value),
		"llm": str(opt_llm.get_item_metadata(opt_llm.selected)), "speed": opt_speed.get_item_metadata(opt_speed.selected),
		"reflection": str(opt_reflection.get_item_metadata(opt_reflection.selected)),
		# `null` : le moteur calcule 12,5 t par pêcheur ; sinon, la limite du stock choisie par le joueur
		"lake": {"capacity": null if capacity_auto else float(spin_capacity.value), "growth_rate": float(spin_growth.value)},
		"stop_on_extinction": chk_stop_empty.button_pressed,
		"population": {"elder": chk_elder.button_pressed, "elder_kind": "llm" if opt_elder.selected == 0 else "rule",
			"fishers": list},
	}


func _on_start() -> void:
	if busy or catalog.is_empty():
		return
	for f in fishers:
		if str(f["first_name"]).strip_edges() == "":
			show_error("Chaque pêcheur a besoin d'un prénom.")
			return
	busy = true
	busy_since = Time.get_ticks_msec()
	lbl_error.text = ""
	_update_state()
	start_requested.emit(build_config())


# ------------------------------------------------------------------ état du moteur
func open(cancelable: bool) -> void:
	can_cancel = cancelable
	visible = true
	_fit()
	_update_state()


func close() -> void:
	visible = false
	busy = false


func show_error(text: String) -> void:
	lbl_error.text = text
	busy = false
	_update_state()


func set_engine(state: String, online: bool, detail: String = "") -> void:
	engine_state = state
	engine_online = online
	engine_detail = detail
	if state == "starting":
		busy = true          # la préparation est en cours, même si le clic vient d'ailleurs
	_update_state()


func _update_state() -> void:
	if lbl_engine == null:
		return
	var can_go := engine_online and (engine_state == "idle" or engine_state == "ended")
	var starting := engine_state == "starting" or busy
	btn_start.disabled = not can_go or starting or catalog.is_empty()
	btn_start.text = "Préparation de la partie…" if starting else "Démarrer la partie"
	btn_cancel.visible = can_cancel and not starting
	if not engine_online:
		lbl_engine.text = "○  moteur injoignable"
		lbl_engine.add_theme_color_override("font_color", Art.ACCUSE)
	elif starting:
		# ce que fait le moteur (« Chargement du modèle qwen2.5:7b… ») : un modèle local met parfois une minute à se charger
		lbl_engine.text = "●  " + (engine_detail if engine_detail != "" else "le moteur prépare la partie…")
		lbl_engine.add_theme_color_override("font_color", Art.PROPOSAL)
	elif engine_state == "":
		lbl_engine.text = "○  en attente du moteur…"
		lbl_engine.add_theme_color_override("font_color", Art.PROPOSAL)
	elif can_go:
		lbl_engine.text = "●  moteur prêt"
		lbl_engine.add_theme_color_override("font_color", Art.SUPPORT)
	else:
		lbl_engine.text = "○  une partie est en cours"
		lbl_engine.add_theme_color_override("font_color", Art.MUTED)


func _process(_delta: float) -> void:
	# pas de réponse du tout au bout de 12 s : le moteur est peut-être arrêté. Mais s'il a répondu « je prépare »
	# (chargement d'un modèle local, parfois long), on attend sa réponse suivante.
	if busy and engine_state != "starting" and Time.get_ticks_msec() - busy_since > 12000:
		show_error("Le moteur n'a pas répondu. Vérifiez qu'il tourne (python -m filets serve), puis réessayez.")
