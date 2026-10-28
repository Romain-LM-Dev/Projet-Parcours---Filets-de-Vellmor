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
signal generate_requested(params: Dictionary)

const W_IDX := 40
const W_NAME := 96
const W_HAMLET := 94
const W_ARCH := 130
const W_BOAT := 84
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
var _pending_generation := ""          # la vallée demandée au moteur, qu'on attend de recevoir
var _pending_since := 0                # l'instant (ms) où cette demande est partie
var _pending_params := {}              # villages, pêcheurs et graine de cette demande
var _regenerate := false               # les nombres ont encore changé pendant l'attente : on redemande dès qu'elle est servie
var _gen_timer: Timer                  # laisse finir de régler les nombres avant de demander la vallée

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
var opt_council: OptionButton
var chk_climate: CheckButton
var chk_patrol: CheckButton
var spin_events: SpinBox
var spin_luck: SpinBox
var spin_villages: SpinBox
var spin_fishers: SpinBox
var opt_fleet: OptionButton
var opt_genmode: OptionButton          # vallée paramétrée (nombres choisis) ou aléatoire (tout tiré de la graine)
var spin_lakes: SpinBox
var spin_patrols: SpinBox
var spin_hold: SpinBox                 # part du poisson d'un lac qu'un bateau peut prendre en une saison
var row_cap: Control                   # les deux lignes du lac unique (masquées quand on règle chaque lac à part)
var row_growth: Control
var row_travel: Control                # la route entre les lacs (avec plusieurs lacs seulement)
var spin_travel_days: SpinBox
var spin_travel_cost: SpinBox
var lakes_box: VBoxContainer           # une ligne par lac : son poisson, son stock de départ, son repeuplement
var lakes_state: Array = []            # les lacs de la vallée : {name, label, villages, capacity, cap_cat, n_cat, stock_ratio, growth_rate}
var lake_spins: Array = []
var btn_generate: Button
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


func _row(parent: Control, title: String, w: Control) -> Control:
	var h := HBoxContainer.new()
	h.add_theme_constant_override("separation", 8)
	var l := _lbl(title, 13, "ui", Art.MUTED)
	l.custom_minimum_size = Vector2(86, 0)
	l.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	h.add_child(l)
	w.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	h.add_child(w)
	parent.add_child(h)
	return h


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
	spin_seed.tooltip_text = "Graine du hasard : la même graine et les mêmes réglages rejouent la même partie. Elle décide aussi de la vallée générée (la changer régénère les villages et les pêcheurs)."
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
	opt_council = _option([])
	opt_council.tooltip_text = "Au conseil de la vallée, un élu par village (choisi à chaque saison par ses pêcheurs) parle et vote pour tous ; les autres villageois n'y vont pas. Sans effet pour des veillées par village."
	_row(col, "Conseil", opt_council)
	spin_rounds = _spin(1, 3, 1, 2, 70)
	spin_rounds.tooltip_text = "Combien de fois chacun prend la parole pendant une veillée, à tour de rôle (synchrone). En asynchrone, chacun s'exprime une seule fois, de son côté."
	_row(col, "Tours de parole", spin_rounds)
	chk_visible = CheckButton.new()
	chk_visible.text = "Les déclarations à l'ancien sont lues à toute la vallée"
	chk_visible.tooltip_text = "Chaque pêcheur déclare sa prise à l'ancien, et peut mentir. Coché : toute la vallée connaît les déclarations ; sinon, le seul hameau. Les vraies prises, seuls vous et chaque pêcheur les connaissez."
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
	row_cap = _row(col, "Stock max", cap_box)
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
	row_growth = _row(col, "Repeuplement", growth_box)
	chk_stop_empty = CheckButton.new()
	chk_stop_empty.text = "Arrêter si le lac est vide"
	chk_stop_empty.button_pressed = true
	chk_stop_empty.focus_mode = Control.FOCUS_NONE
	chk_stop_empty.tooltip_text = "Un lac tombé à 0 ne se repeuple jamais : la partie s'arrête dès le dernier poisson pêché."
	col.add_child(chk_stop_empty)
	lakes_box = VBoxContainer.new()
	lakes_box.add_theme_constant_override("separation", 4)
	lakes_box.visible = false
	col.add_child(lakes_box)
	var travel := HBoxContainer.new()
	travel.add_theme_constant_override("separation", 6)
	spin_travel_days = _spin(0, 10, 0.1, 1.5, 70)
	spin_travel_days.tooltip_text = "Jours de route, à l'aller, pour traverser toute la carte d'un lac à l'autre. Un pêcheur qui va pêcher dans un autre lac que celui de son village passe plus de temps en route : sa sortie dure 1 + 2 × la route jours, et sa prise s'en ressent."
	spin_travel_cost = _spin(0, 1000, 1, 10, 70)
	spin_travel_cost.suffix = "écus"
	spin_travel_cost.tooltip_text = "Ce que la route coûte, par jour de mer, à chaque sortie (aller et retour)."
	for sp in [spin_travel_days, spin_travel_cost]:
		sp.value_changed.connect(func(_v: float) -> void:
			if not _updating:
				_refresh_all(false))
	travel.add_child(spin_travel_days)
	travel.add_child(_lbl("j", 12, "ui", Art.MUTED))
	travel.add_child(spin_travel_cost)
	travel.add_child(_lbl("/ jour de mer", 12, "ui", Art.MUTED))
	row_travel = _row(col, "Route", travel)
	row_travel.visible = false
	spin_hold = _spin(5, 100, 5, 50, 84)
	spin_hold.suffix = "%"
	spin_hold.tooltip_text = "Ce que le lac laisse prendre : un bateau rapporte au plus sa cale, et au plus cette part du poisson de son lac, partagée entre les bateaux du lac selon leur taille. Un lac qui se vide laisse donc prendre de moins en moins ; 100 % : tout le poisson est à portée."
	spin_hold.value_changed.connect(func(_v: float) -> void:
		if not _updating:
			_refresh_all(false))
	_row(col, "Part prenable", spin_hold)
	lbl_cap_hint = _lbl("", 12, "ui", Color(Art.MUTED, 0.95))
	lbl_cap_hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	lbl_cap_hint.custom_minimum_size = Vector2(276, 0)
	col.add_child(lbl_cap_hint)
	
	col.add_child(HSeparator.new())
	col.add_child(_section("Saisons et hasard"))
	chk_climate = CheckButton.new()
	chk_climate.text = "Saisons de l'année et événements"
	chk_climate.button_pressed = true
	chk_climate.focus_mode = Control.FOCUS_NONE
	chk_climate.tooltip_text = "Printemps, été, automne, hiver : la pêche rend plus ou moins, le lac se repeuple plus ou moins vite. Des événements s'y ajoutent (sécheresse, tempête, banc de poissons, algues, crue, maladie)."
	col.add_child(chk_climate)
	chk_patrol = CheckButton.new()
	chk_patrol.text = "Patrouille du lac"
	chk_patrol.button_pressed = true
	chk_patrol.focus_mode = Control.FOCUS_NONE
	chk_patrol.tooltip_text = "Le conseil de la vallée peut voter une patrouille, aux frais de chaque pêcheur. Son capitaine est une IA : il décide seul où aller d'après les soupçons et les indices que les villageois ont partagés, et mesure les barques qu'il croise. Décochée : pas de patrouille dans la partie."
	var patrol_row := HBoxContainer.new()
	patrol_row.add_theme_constant_override("separation", 8)
	patrol_row.add_child(chk_patrol)
	spin_patrols = _spin(1, 4, 1, 1, 56)
	spin_patrols.tooltip_text = "Nombre de patrouilles : chacune a son capitaine (une IA) et sa route, et coûte à chaque pêcheur. Les suivantes lisent la route des premières."
	spin_patrols.value_changed.connect(func(_v: float) -> void:
		if not _updating:
			_refresh_all(false))
	chk_patrol.toggled.connect(func(_on: bool) -> void: spin_patrols.editable = chk_patrol.button_pressed)
	patrol_row.add_child(_lbl("patrouilles", 12, "ui", Art.MUTED))
	patrol_row.add_child(spin_patrols)
	col.add_child(patrol_row)
	spin_events = _spin(0, 100, 5, 30, 84)
	spin_events.suffix = "%"
	spin_events.tooltip_text = "Chance qu'un événement survienne à chaque saison, à partir de la deuxième."
	_row(col, "Événements", spin_events)
	spin_luck = _spin(0, 60, 5, 40, 84)
	spin_luck.suffix = "%"
	spin_luck.tooltip_text = "La pêche n'est pas toujours bonne : chaque pêcheur a sa chance, qui change d'une sortie à l'autre et d'une saison à l'autre, en plus du temps et de la saison de l'année (0 : ni chance ni malchance, seul le temps compte)."
	_row(col, "Chance à la pêche", spin_luck)


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
	var gen0 := HBoxContainer.new()
	gen0.add_theme_constant_override("separation", 8)
	col.add_child(gen0)
	gen0.add_child(_lbl("Vallée", 12, "ui", Art.MUTED))
	opt_genmode = _option(["Paramétrée", "Aléatoire"], 128)
	opt_genmode.set_item_metadata(0, "params")
	opt_genmode.set_item_metadata(1, "random")
	opt_genmode.tooltip_text = "Paramétrée : vous choisissez le nombre de villages, de pêcheurs, de lacs et la flotte. Aléatoire : tout est tiré de la graine (villages, pêcheurs, flotte, lacs et leur poisson, patrouilles) ; le dé change de graine, donc de vallée. Vous pouvez ensuite retoucher chaque pêcheur et chaque lac."
	gen0.add_child(opt_genmode)
	gen0.add_child(_lbl("Lacs", 12, "ui", Art.MUTED))
	spin_lakes = _spin(1, 4, 1, 1, 56)
	spin_lakes.tooltip_text = "Nombre de lacs : les villages se partagent en blocs, chacun pêchant dans le lac de sa rive ; chaque lac a son poisson et son repeuplement. La vallée est régénérée dès que vous le changez (au moins un village par lac)."
	gen0.add_child(spin_lakes)
	var gen := HBoxContainer.new()
	gen.add_theme_constant_override("separation", 8)
	col.add_child(gen)
	gen.add_child(_lbl("Villages", 12, "ui", Art.MUTED))
	spin_villages = _spin(1, 8, 1, 4, 62)
	spin_villages.tooltip_text = "Nombre de villages autour du lac : la vallée est régénérée dès que vous le changez (au moins un pêcheur par village)."
	gen.add_child(spin_villages)
	gen.add_child(_lbl("Pêcheurs", 12, "ui", Art.MUTED))
	spin_fishers = _spin(1, 24, 1, 8, 62)
	spin_fishers.tooltip_text = "Nombre de pêcheurs : la vallée est régénérée dès que vous le changez."
	gen.add_child(spin_fishers)
	gen.add_child(_lbl("Flotte", 12, "ui", Art.MUTED))
	opt_fleet = _option([], 128)
	opt_fleet.tooltip_text = "Tailles des bateaux de la vallée générée : surtout des barques, un mélange, ou surtout des cotres. Chaque pêcheur reste réglable."
	gen.add_child(opt_fleet)
	btn_generate = Button.new()
	btn_generate.text = "Générer la vallée"
	btn_generate.focus_mode = Control.FOCUS_NONE
	btn_generate.tooltip_text = "Régénère les villages, les pêcheurs et leurs bateaux d'après ces nombres, la flotte et la graine : la même vallée pour les mêmes réglages. C'est fait aussi dès qu'on change l'un d'eux ; vous pouvez ensuite retoucher chaque pêcheur."
	btn_generate.pressed.connect(_on_generate)
	gen.add_child(btn_generate)
	# changer le nombre de villages ou de pêcheurs régénère la vallée, un instant après la dernière touche
	_gen_timer = Timer.new()
	_gen_timer.one_shot = true
	_gen_timer.wait_time = 0.5
	_gen_timer.timeout.connect(_on_generate)
	add_child(_gen_timer)
	spin_villages.value_changed.connect(_on_gen_spin.bind(true))
	spin_fishers.value_changed.connect(_on_gen_spin.bind(false))
	spin_seed.value_changed.connect(_on_gen_spin.bind(false))
	spin_lakes.value_changed.connect(_on_gen_spin.bind(false))
	opt_genmode.item_selected.connect(func(_i: int) -> void:
		_set_gen_enabled()
		_on_gen_spin(0.0, false))
	opt_fleet.item_selected.connect(func(_i: int) -> void: _on_gen_spin(0.0, false))
	# titres de colonnes, alignés sur les lignes
	var titles := HBoxContainer.new()
	titles.add_theme_constant_override("separation", 6)
	col.add_child(titles)
	var pad := Control.new()
	pad.custom_minimum_size = Vector2(8, 0)
	titles.add_child(pad)
	for t in [["", W_IDX], ["Prénom", W_NAME], ["Village", W_HAMLET], ["Archétype", W_ARCH], ["Bateau", W_BOAT], ["Expérience", W_EXP],
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
	col.add_child(_lbl("Glissez un pêcheur d'un village à l'autre.", 12, "ui", Color(Art.MUTED, 0.9)))
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
## Le catalogue sans la vallée : ses villages, ses pêcheurs et la demande qui l'a générée.
func _same_but_valley(a: Dictionary, b: Dictionary) -> bool:
	var x := a.duplicate()
	var y := b.duplicate()
	for k in ["hamlets", "base_population", "generation", "lakes"]:
		x.erase(k)
		y.erase(k)
	return JSON.stringify(x) == JSON.stringify(y)


func set_catalog(cat: Dictionary) -> void:
	# le moteur renvoie son catalogue avec chaque état : identique, on n'y touche pas (le joueur est peut-être en train
	# de régler sa partie) ; différent (autre moteur, autres options), on repart de ses valeurs par défaut
	if not catalog.is_empty() and JSON.stringify(cat) == JSON.stringify(catalog):
		return
	# seule la vallée a changé : on ne touche ni aux réglages ni à l'IA
	if not catalog.is_empty() and _same_but_valley(cat, catalog):
		var fresh: bool = JSON.stringify(cat.get("generation")) != JSON.stringify(catalog.get("generation"))
		catalog = cat
		if fresh and _pending_generation != "" and str(cat.get("generation", {}).get("id", "")) == _pending_generation:
			_pending_generation = ""
			btn_generate.disabled = false
			lbl_error.text = ""
			_apply_generation()
			reset_population()
			if _regenerate:
				_on_generate.call_deferred()
		return
	var first := true
	catalog = cat
	_updating = true
	opt_comm.clear()
	for c in cat.get("communications", []):
		opt_comm.add_item(str(c["label"]))
		opt_comm.set_item_metadata(opt_comm.item_count - 1, str(c["id"]))
	opt_council.clear()
	for c in cat.get("councils", []):
		opt_council.add_item(str(c["label"]))
		opt_council.set_item_metadata(opt_council.item_count - 1, str(c["id"]))
	opt_fleet.clear()
	for f in cat.get("fleets", []):
		opt_fleet.add_item(str(f["label"]))
		opt_fleet.set_item_metadata(opt_fleet.item_count - 1, str(f["id"]))
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
	var vill: Array = lim.get("villages", [1, 8])
	spin_villages.min_value = vill[0]
	spin_villages.max_value = vill[1]
	var fish: Array = lim.get("fishers", [1, 24])
	spin_fishers.min_value = fish[0]
	spin_fishers.max_value = fish[1]
	var nl: Array = lim.get("lakes", [1, 4])
	spin_lakes.min_value = nl[0]
	spin_lakes.max_value = nl[1]
	var np_: Array = lim.get("patrols", [0, 4])
	spin_patrols.max_value = np_[1]
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
	_select_meta(opt_council, str(d.get("council", "delegates")))
	_select_meta(opt_fleet, str(d.get("fleet", "mixte")))
	chk_climate.button_pressed = bool(d.get("climate", true))
	chk_patrol.button_pressed = bool(d.get("patrol", true))
	spin_events.value = roundf(float(d.get("event_rate", 0.3)) * 100.0)
	spin_luck.value = roundf(float(d.get("luck", 0.4)) * 100.0)
	spin_villages.value = int(d.get("villages", 4))
	spin_fishers.value = int(d.get("fishers", 8))
	spin_lakes.value = int(d.get("lakes", 1))
	spin_patrols.value = maxi(1, int(d.get("patrols", 1)))
	spin_patrols.editable = chk_patrol.button_pressed
	spin_hold.value = roundf(float(d.get("hold_fraction", 0.5)) * 100.0)
	spin_travel_days.value = float(d.get("travel_days", 1.5))
	spin_travel_cost.value = float(d.get("travel_cost", 10.0))
	opt_genmode.select(0)
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
	_set_gen_enabled()
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
	_load_lakes()
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


func _boat_index(id: String) -> int:
	var boats: Array = catalog.get("boats", [])
	for i in boats.size():
		if str(boats[i]["id"]) == id:
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
		"wealth": float(a["wealth"]), "debt_payment": float(a["debt_payment"]), "kind": "llm", "tier": "auto", "boat": "chaloupe"})
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
		var boat_labels: Array = []
		for bt in catalog.get("boats", []):
			boat_labels.append("%s · %s t" % [str(bt["label"]), _num(float(bt["capacity"]))])
		var opt_bt := _option(boat_labels, W_BOAT)
		if opt_bt.item_count > 0:           # (un moteur plus ancien n'envoie pas de bateaux)
			opt_bt.select(_boat_index(str(f.get("boat", "chaloupe"))))
		opt_bt.item_selected.connect(func(k: int) -> void:
			fishers[i]["boat"] = str((catalog.get("boats", []) as Array)[k]["id"])
			_refresh_all())
		h.add_child(opt_bt)
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
			"debt": sp_d, "boat": opt_bt, "brain": opt_b, "del": del})


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
	if (r["boat"] as OptionButton).item_count > 0:
		(r["boat"] as OptionButton).select(_boat_index(str(f.get("boat", "chaloupe"))))
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
	map.call("set_data", fishers, chk_elder.button_pressed, elder_kind, selected, int(d.get("large_model_min_experience", 15)), catalog.get("hamlets", []),
		catalog.get("lakes", []))
	var lim: Array = catalog.get("limits", {}).get("fishers", [1, 24])
	lbl_count.text = "%d" % fishers.size()
	_sync_generation()
	_refresh_lake()
	btn_add.disabled = fishers.size() >= int(lim[1])
	for r in _rows:
		(r["del"] as Button).disabled = fishers.size() <= 1
	if selected >= 0 and selected < fishers.size():
		var f: Dictionary = fishers[selected]
		var hc := Art.agent_color(f).lightened(0.2).to_html(false)
		var arch: Dictionary = _archetypes()[_arch_index(str(f["archetype"]))]
		var s := "[font=res://fonts/alegreya-latin-700-normal.woff2][font_size=20][color=#%s]%s[/color][/font_size][/font]  [color=#6f7896]F%02d[/color]\n" % [hc, str(f["first_name"]), selected + 1]
		s += "%s · village %s\n[color=#9ba1ba]%s[/color]\n\n" % [str(arch["label"]), str(f["hamlet"]), str(arch["summary"])]
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


## Ce que toutes les cales ensemble peuvent porter (t) : la somme des capacités des bateaux des pêcheurs.
func _holds() -> float:
	var cap := {}
	for b in catalog.get("boats", []):
		cap[str(b["id"])] = float(b["capacity"])
	var total := 0.0
	for f in fishers:
		total += float(cap.get(str(f.get("boat", "chaloupe")), 7.0))
	return total


func _is_random() -> bool:
	return opt_genmode != null and opt_genmode.selected == 1


## Règle-t-on chaque lac à part ? Dès qu'il y en a plusieurs, ou que la vallée est tirée au hasard (chaque lac a alors son stock de départ).
func _use_rows() -> bool:
	return lakes_state.size() > 1 or (_is_random() and not lakes_state.is_empty())


## Les villages, les pêcheurs et les lacs que le moteur vient de générer (et, en aléatoire, ce qu'il a tiré) remplacent les nombres du menu.
func _apply_generation() -> void:
	var g: Dictionary = catalog.get("generation", {})
	if g.is_empty():
		return
	var was := _updating
	_updating = true
	opt_genmode.select(1 if str(g.get("mode", "params")) == "random" else 0)
	spin_villages.set_value_no_signal(int(g.get("villages", spin_villages.value)))
	spin_fishers.set_value_no_signal(int(g.get("fishers", spin_fishers.value)))
	spin_lakes.set_value_no_signal(int(g.get("lakes", 1)))
	_select_meta(opt_fleet, str(g.get("fleet", "mixte")))
	if str(g.get("mode", "params")) == "random":       # tiré de la graine : les patrouilles aussi
		chk_patrol.button_pressed = int(g.get("patrols", 1)) > 0
		spin_patrols.set_value_no_signal(maxi(1, int(g.get("patrols", 1))))
		spin_patrols.editable = chk_patrol.button_pressed
	_updating = was
	_set_gen_enabled()


## En aléatoire, les nombres de la vallée sont ceux qu'a tirés la graine : on ne les règle pas.
func _set_gen_enabled() -> void:
	var manual := not _is_random()
	spin_villages.editable = manual
	spin_fishers.editable = manual
	spin_lakes.editable = manual
	opt_fleet.disabled = not manual


## Les lacs du catalogue deviennent ceux du menu (stock auto : 12,5 t par pêcheur du lac, comme le moteur).
func _load_lakes() -> void:
	if lakes_box == null:
		return
	var by_village := {}
	for f in fishers:
		by_village[str(f["hamlet"])] = int(by_village.get(str(f["hamlet"]), 0)) + 1
	lakes_state = []
	for lk in catalog.get("lakes", []):
		var n := 0
		for v in lk.get("villages", []):
			n += int(by_village.get(str(v), 0))
		lakes_state.append({"name": str(lk["name"]), "label": str(lk["label"]), "villages": (lk["villages"] as Array).duplicate(),
			"capacity": float(lk["capacity"]), "cap_cat": float(lk["capacity"]), "n_cat": n,
			"stock_ratio": float(lk["initial_ratio"]), "growth_rate": float(lk["growth_rate"])})
	if _use_rows():
		capacity_auto = true
	_rebuild_lake_rows()


func _rebuild_lake_rows() -> void:
	for c in lakes_box.get_children():
		c.queue_free()
	lake_spins = []
	if not _use_rows():
		return
	var head := HBoxContainer.new()
	head.add_theme_constant_override("separation", 6)
	for t in [["", 110], ["Stock max", 84], ["Au départ", 70], ["Repeuplement", 70]]:
		var l := _lbl(str(t[0]).to_upper(), 9, "ui_black", Art.MUTED)
		l.custom_minimum_size = Vector2(int(t[1]), 0)
		head.add_child(l)
	lakes_box.add_child(head)
	for k in lakes_state.size():
		var lk: Dictionary = lakes_state[k]
		var h := HBoxContainer.new()
		h.add_theme_constant_override("separation", 6)
		var l := _lbl(str(lk["label"]), 12, "ui_bold", Art.INK)
		l.custom_minimum_size = Vector2(110, 0)
		l.tooltip_text = "Villages de ce lac : " + ", ".join(PackedStringArray(lk["villages"]))
		h.add_child(l)
		var sc := _spin(10, 1000, 0.5, float(lk["capacity"]), 84)
		sc.suffix = "t"
		sc.tooltip_text = "Le poisson de ce lac quand il est plein (tonnes). Auto : 12,5 t par pêcheur du lac."
		var ss := _spin(5, 100, 5, float(lk["stock_ratio"]) * 100.0, 70)
		ss.suffix = "%"
		ss.tooltip_text = "Part du lac pleine au départ."
		var sg := _spin(0.1, 2.0, 0.05, float(lk["growth_rate"]), 70)
		sg.tooltip_text = "Taux de repeuplement r de ce lac, par saison."
		sc.value_changed.connect(func(v: float) -> void:
			if not _updating:
				lakes_state[k]["capacity"] = v
				capacity_auto = false
				_refresh_all(false))
		ss.value_changed.connect(func(v: float) -> void:
			if not _updating:
				lakes_state[k]["stock_ratio"] = v / 100.0
				_refresh_all(false))
		sg.value_changed.connect(func(v: float) -> void:
			if not _updating:
				lakes_state[k]["growth_rate"] = v
				_refresh_all(false))
		h.add_child(sc)
		h.add_child(ss)
		h.add_child(sg)
		lakes_box.add_child(h)
		lake_spins.append({"cap": sc, "stock": ss, "growth": sg})


## Le stock de chaque lac, tant qu'il est « auto » : celui du moteur, au prorata des pêcheurs du lac (il suit la liste des pêcheurs).
func _lake_capacity(k: int) -> float:
	var lk: Dictionary = lakes_state[k]
	if not capacity_auto:
		return float(lk["capacity"])
	var n := 0
	for f in fishers:
		if (lk["villages"] as Array).has(str(f["hamlet"])):
			n += 1
	var per := float(lk["cap_cat"]) / float(lk["n_cat"]) if int(lk["n_cat"]) > 0 else float(catalog.get("defaults", {}).get("capacity_per_fisher", 12.5))
	var caps: Array = catalog.get("limits", {}).get("capacity", [10, 1000])
	return clampf(per * float(n), float(caps[0]), float(caps[1]))


func _refresh_lake() -> void:
	var d: Dictionary = catalog.get("defaults", {})
	var rows := _use_rows()
	row_cap.visible = not rows
	row_growth.visible = not rows
	btn_cap_auto.disabled = capacity_auto
	lakes_box.visible = rows
	row_travel.visible = lakes_state.size() > 1
	if rows:
		_refresh_lake_rows(d)
		return
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
	var reach := minf(_holds(), cap / 2.0)
	btn_cap_auto.disabled = capacity_auto
	btn_growth_default.disabled = is_equal_approx(rate, float(d.get("growth_rate", 1.0)))
	lbl_lake.text = "lac de %s t · rendement durable max %s t par saison" % [_num(cap), _num(yield_max)]
	var how := "Auto : %s t par pêcheur." % _num(float(d.get("capacity_per_fisher", 12.5))) if capacity_auto \
		else "Choisi à la main (auto : %s t)." % _num(auto_cap)
	lbl_cap_hint.text = ("%s Le lac part plein et ne dépasse jamais ce stock. À moitié plein, il regagne au mieux %s t par "
		+ "saison ; %d bateaux peuvent en ramener jusqu'à %s t (au plus %d %% du poisson du lac, partagé selon leur cale).") % [
		how, _num(yield_max), fishers.size(), _num(minf(_holds(), cap * spin_hold.value / 100.0)), int(spin_hold.value)]


## Plusieurs lacs (ou une vallée aléatoire) : la ligne de chacun, et ce que tous ensemble peuvent donner.
func _refresh_lake_rows(d: Dictionary) -> void:
	var was := _updating
	_updating = true
	var total := 0.0
	var yield_max := 0.0
	for k in lakes_state.size():
		var cap := _lake_capacity(k)
		lakes_state[k]["capacity"] = cap
		total += cap
		yield_max += float(lakes_state[k]["growth_rate"]) * cap / 4.0
		if k < lake_spins.size():
			(lake_spins[k]["cap"] as SpinBox).set_value_no_signal(cap)
			(lake_spins[k]["stock"] as SpinBox).set_value_no_signal(roundf(float(lakes_state[k]["stock_ratio"]) * 100.0))
			(lake_spins[k]["growth"] as SpinBox).set_value_no_signal(float(lakes_state[k]["growth_rate"]))
	_updating = was
	btn_cap_auto.disabled = capacity_auto
	lbl_lake.text = "%d lac%s · %s t de poisson · rendement durable max %s t par saison" % [lakes_state.size(),
		"s" if lakes_state.size() > 1 else "", _num(total), _num(yield_max)]
	lbl_cap_hint.text = ("%s Chaque lac part de son stock et se repeuple à son rythme ; les bateaux d'un lac ne peuvent en ramener "
		+ "que %d %% du poisson qu'il contient, partagé selon leur cale.") % [
		"Stock auto : 12,5 t par pêcheur du lac (modifiable lac par lac)." if capacity_auto else "Stock choisi à la main.",
		int(spin_hold.value)]


# ------------------------------------------------------------------ envoi
## Le nombre de villages ou de pêcheurs a changé : un pêcheur au moins par village (le nombre qu'on vient de toucher l'emporte
## sur l'autre), puis la vallée est régénérée.
func _on_gen_spin(_v: float, villages_touched: bool) -> void:
	if _updating or catalog.is_empty():
		return
	if spin_villages.value > spin_fishers.value:
		if villages_touched:
			spin_fishers.set_value_no_signal(spin_villages.value)
		else:
			spin_villages.set_value_no_signal(spin_fishers.value)
	_gen_timer.start()


## Les nombres « Villages » et « Pêcheurs » disent toujours ce que la liste contient (sauf pendant qu'on les règle).
func _sync_generation() -> void:
	if _pending_generation != "" or _regenerate or not _gen_timer.is_stopped():
		return
	spin_fishers.set_value_no_signal(fishers.size())
	spin_villages.set_value_no_signal(catalog.get("hamlets", []).size())


func _fleet_id() -> String:
	return str(opt_fleet.get_item_metadata(opt_fleet.selected)) if opt_fleet.item_count > 0 else "mixte"


func _on_generate() -> void:
	if catalog.is_empty():
		return
	if spin_lakes.value > spin_villages.value and not _is_random():
		spin_lakes.set_value_no_signal(spin_villages.value)
	var params := {"villages": int(spin_villages.value), "fishers": int(spin_fishers.value), "seed": int(spin_seed.value),
		"fleet": _fleet_id(), "lakes": int(spin_lakes.value), "patrols": int(spin_patrols.value) if chk_patrol.button_pressed else 0,
		"mode": "random" if _is_random() else "params"}
	if _pending_generation != "" and Time.get_ticks_msec() - _pending_since < 5000:
		_regenerate = params != _pending_params       # une demande est en route : si les nombres ont changé, on y revient (au-delà de 5 s, on la croit perdue)
		return
	_regenerate = false
	_pending_params = params
	_pending_since = Time.get_ticks_msec()
	_pending_generation = "g%d" % _pending_since
	btn_generate.disabled = true
	lbl_error.text = ""
	generate_requested.emit(params.merged({"id": _pending_generation}))


## Le ou les lacs de la demande : le lac unique comme avant ; plusieurs lacs (ou une vallée aléatoire), chacun avec son poisson, son
## stock de départ, son repeuplement et ses villages (ceux où il reste un pêcheur ; un lac sans village n'existe pas).
func _lake_request() -> Dictionary:
	if not _use_rows():
		return {"capacity": null if capacity_auto else float(spin_capacity.value), "growth_rate": float(spin_growth.value)}
	var present := {}
	for f in fishers:
		present[str(f["hamlet"])] = true
	var out: Array = []
	for k in lakes_state.size():
		var lk: Dictionary = lakes_state[k]
		var vs: Array = []
		for v in lk["villages"]:
			if present.has(str(v)):
				vs.append(str(v))
		if not vs.is_empty():
			out.append({"name": str(lk["name"]), "capacity": _lake_capacity(k), "stock_ratio": float(lk["stock_ratio"]),
				"growth_rate": float(lk["growth_rate"]), "villages": vs})
	return {"lakes": out}


func build_config() -> Dictionary:
	var list: Array = []
	for f in fishers:
		list.append({"first_name": str(f["first_name"]), "hamlet": str(f["hamlet"]), "archetype": str(f["archetype"]),
			"experience": int(f["experience"]), "wealth": float(f["wealth"]), "debt_payment": float(f["debt_payment"]),
			"kind": str(f["kind"]), "tier": str(f["tier"]), "boat": str(f.get("boat", "chaloupe"))})
	return {
		"mode": mode, "seasons": int(spin_seasons.value), "seed": int(spin_seed.value),
		"communication": str(opt_comm.get_item_metadata(opt_comm.selected)), "catches_visible": chk_visible.button_pressed,
		"assembly_rounds": int(spin_rounds.value),
		"council": str(opt_council.get_item_metadata(opt_council.selected)), "climate": chk_climate.button_pressed, "patrol": chk_patrol.button_pressed,
		"event_rate": float(spin_events.value) / 100.0, "luck": float(spin_luck.value) / 100.0,
		"llm": str(opt_llm.get_item_metadata(opt_llm.selected)), "speed": opt_speed.get_item_metadata(opt_speed.selected),
		"reflection": str(opt_reflection.get_item_metadata(opt_reflection.selected)),
		# `null` : le moteur calcule 12,5 t par pêcheur ; sinon, la limite du stock choisie par le joueur
		"lake": _lake_request(),
		"patrols": int(spin_patrols.value) if chk_patrol.button_pressed else 0,
		"hold_fraction": float(spin_hold.value) / 100.0,
		"travel_days": float(spin_travel_days.value), "travel_cost": float(spin_travel_cost.value),
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
	_pending_generation = ""
	_regenerate = false
	btn_generate.disabled = false
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
