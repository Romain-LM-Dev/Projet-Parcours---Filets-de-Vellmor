## Scène principale de FILETS : construit l'interface, tient l'état reconstruit à partir des
## événements (identique en direct et en rejeu) et envoie les injections.
##
## Arguments (après `--`) : --url=ws://127.0.0.1:8765   --selftest=SECONDES (imprime un bilan et quitte)
##   --autostart=SECONDES   lance la partie proposée par défaut dans le menu (essais automatiques)
##   --menu-shot=chemin.png capture le menu de démarrage une fois affiché
extends Control

const WS := preload("res://scripts/ws_client.gd")
const WorldView := preload("res://scripts/world_view.gd")
const Chart := preload("res://scripts/chart.gd")
const Legend := preload("res://scripts/legend.gd")
const StartMenu := preload("res://scripts/start_menu.gd")

## Les vitesses lentes comptent : en asynchrone, le temps du monde suit le temps réel, et une IA locale qui réfléchit 30 s
## agit alors 30 s plus tard dans le monde. Ralentir le monde lui laisse le temps de répondre avant la fin de la veillée.
const SPEEDS := [0.0625, 0.125, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0]

## Noms lisibles des incidents (le moteur les publie sous leur nom technique).
const INCIDENT_LABELS := {"out_of_role": "sortie de rôle", "unparseable": "réponse illisible", "no_response": "pas de réponse",
	"quota": "quota du fournisseur", "invalid_value": "valeur invalide", "assistant_posture": "posture d'assistant",
	"missed_window": "fenêtre ratée", "schema_violation": "schéma non respecté", "temporal_violation": "violation temporelle"}

var ws            # ws_client.gd
var world         # world_view.gd
var chart         # chart.gd
var menu          # start_menu.gd
var lbl_run: Label
var lbl_clock: Label
var lbl_status: Label
var ind_labels := {}
var feed: RichTextLabel
var narration: RichTextLabel    # le récit de chaque saison par l'ancien (onglet « Récit de l'ancien »)
var trust_view: RichTextLabel   # jauges de confiance, vraies prises et déclarations (onglet « Confiance »)
var trust_dirty := false
var feed_only_selected: CheckBox
var inspector: RichTextLabel
var rules_view: RichTextLabel
var tabs: TabContainer
var comm_opt: OptionButton
var vis_check: CheckButton
var legend: Control
var lbl_weather: Label          # le temps du jour sur le lac (voir `weather_days`)
var weather_days: Array = []    # le temps de chaque jour de pêche de la saison en cours (`season_start`)
var weather_season := 0
var lbl_patrol: Label           # la patrouille du lac : aucune, ou installée (et sa route de la saison)
var patrol_installed := false
var reps := {}                  # village -> pêcheur élu au conseil de la vallée
var rumor_edit: LineEdit

# état reconstruit
var run := {}
var agents := {}            # id -> fiche
var feed_lines: Array = []  # [{"text": bbcode, "ids": [..]}]
var proposals := {}
var norms: Array = []
var selected := ""
var inspector_dirty := false
var feed_dirty := false
var catching_up := 0
var t0_ms := 0
var n_events := 0
var n_indicators := 0
var last_sim_label := "—"
var selftest := -1.0
var shot_path := ""
var shots: Array = []          # --shots=4,9,15 --shotdir=/chemin : captures à ces secondes
var shot_dir := ""
var autostart := -1.0
var autostart_at := -1.0
var menu_shot := ""

# moteur et pilotage de la partie
var catalog := {}
var engine := {}                 # dernier état publié par le moteur (topic status)
var engine_seen_ms := 0          # quand il est arrivé (le moteur le répète toutes les 2 s)
var engine_state := ""
var ws_ok := false
var last_error := ""
var transport: PanelContainer
var btn_pause: Button
var btn_stop: Button
var btn_new: Button
var speed_buttons := {}
var mode_buttons := {}
var lbl_progress: Label
var lbl_pending: Label
var btn_slow: Button             # « Ralentir » : proposé quand une IA locale est trop lente pour le rythme du monde
var lbl_lost: Label
var lost_this_season := 0        # répliques et sorties perdues depuis le début de la saison
var slow_target := 0.25          # la vitesse que « Ralentir » demandera
var stop_armed_ms := 0
var end_overlay: Control
var end_title: Label
var end_text: Label
var end_new: Button


func _ready() -> void:
	t0_ms = Time.get_ticks_msec()
	_build_ui()
	ws = WS.new()
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--url="):
			ws.url = arg.substr(6)
		elif arg.begins_with("--selftest="):
			selftest = float(arg.substr(11))
		elif arg.begins_with("--shot="):
			shot_path = arg.substr(7)
		elif arg.begins_with("--shots="):
			for x in arg.substr(8).split(","):
				shots.append(float(x))
		elif arg.begins_with("--shotdir="):
			shot_dir = arg.substr(10)
		elif arg.begins_with("--autostart="):
			autostart = float(arg.substr(12))
		elif arg.begins_with("--menu-shot="):
			menu_shot = arg.substr(12)
	ws.process_priority = -100           # les messages sont lus avant tout le reste de l'image, détecteur de silence compris
	add_child(ws)
	ws.message.connect(_on_message)
	ws.status_changed.connect(func(t: String, ok: bool) -> void:
		ws_ok = ok
		lbl_status.text = ("●  " if ok else "○  ") + t
		lbl_status.add_theme_color_override("font_color", Art.SUPPORT if ok else Art.ACCUSE)
		if not ok:
			engine_state = ""
			engine = {}
			menu.set_engine("", false)
			_update_transport())


# ------------------------------------------------------------------ interface
var ind_sub := {}


func _pad(sb: StyleBoxFlat, h: float, v: float) -> StyleBoxFlat:
	sb.content_margin_left = h
	sb.content_margin_right = h
	sb.content_margin_top = v
	sb.content_margin_bottom = v
	return sb


func _make_theme() -> Theme:
	var th := Theme.new()
	th.default_font = Art.font("ui")
	th.default_font_size = 14
	th.set_color("font_color", "Label", Art.INK)
	for type in ["Button", "OptionButton"]:
		th.set_stylebox("normal", type, _pad(Art.box(Art.PANEL_2, 9, Art.LINE, 1), 12, 6))
		th.set_stylebox("hover", type, _pad(Art.box(Color("#26314d"), 9, Color(1, 1, 1, 0.16), 1), 12, 6))
		th.set_stylebox("pressed", type, _pad(Art.box(Color("#30406a"), 9, Color(1, 1, 1, 0.2), 1), 12, 6))
		th.set_stylebox("hover_pressed", type, _pad(Art.box(Color("#38497a"), 9, Color(1, 1, 1, 0.26), 1), 12, 6))
		th.set_stylebox("focus", type, StyleBoxEmpty.new())
		th.set_stylebox("disabled", type, _pad(Art.box(Art.PANEL, 9, Art.LINE, 1), 12, 6))
		th.set_color("font_color", type, Art.INK)
		th.set_color("font_hover_color", type, Color.WHITE)
		th.set_color("font_pressed_color", type, Color.WHITE)
		th.set_font("font", type, Art.font("ui_bold"))
	th.set_stylebox("normal", "LineEdit", _pad(Art.box(Color("#0f1525"), 9, Art.LINE, 1), 12, 6))
	th.set_stylebox("focus", "LineEdit", _pad(Art.box(Color("#0f1525"), 9, Color(Art.TALK, 0.6), 1), 12, 6))
	th.set_color("font_placeholder_color", "LineEdit", Color(Art.MUTED, 0.7))
	th.set_stylebox("panel", "PanelContainer", _pad(Art.box(Art.PANEL, 14, Art.LINE, 1), 14, 12))
	th.set_stylebox("panel", "PopupMenu", _pad(Art.box(Art.PANEL_2, 10, Art.LINE, 1, 8), 6, 6))
	th.set_stylebox("hover", "PopupMenu", Art.box(Color("#30406a"), 6))
	th.set_stylebox("panel", "TabContainer", _pad(Art.box(Art.PANEL, 14, Art.LINE, 1), 12, 10))
	th.set_stylebox("tab_selected", "TabContainer", _pad(Art.box(Art.PANEL, 10, Art.LINE, 1), 14, 6))
	th.set_stylebox("tab_unselected", "TabContainer", _pad(Art.box(Color(0, 0, 0, 0), 10), 14, 6))
	th.set_stylebox("tab_hovered", "TabContainer", _pad(Art.box(Color(1, 1, 1, 0.04), 10), 14, 6))
	th.set_stylebox("tabbar_background", "TabContainer", StyleBoxEmpty.new())
	th.set_color("font_selected_color", "TabContainer", Color.WHITE)
	th.set_color("font_unselected_color", "TabContainer", Art.MUTED)
	th.set_color("font_hovered_color", "TabContainer", Art.INK)
	th.set_font("font", "TabContainer", Art.font("ui_bold"))
	th.set_font("normal_font", "RichTextLabel", Art.font("ui"))
	th.set_font("bold_font", "RichTextLabel", Art.font("ui_bold"))
	th.set_font("italics_font", "RichTextLabel", Art.font("title_italic"))
	th.set_color("default_color", "RichTextLabel", Color("#d6dbea"))
	th.set_constant("line_separation", "RichTextLabel", 5)
	th.set_font_size("normal_font_size", "RichTextLabel", 13)
	th.set_font_size("bold_font_size", "RichTextLabel", 13)
	th.set_font_size("italics_font_size", "RichTextLabel", 15)
	for type in ["CheckBox", "CheckButton"]:
		th.set_color("font_color", type, Art.INK)
		th.set_color("font_hover_color", type, Color.WHITE)
		th.set_color("font_pressed_color", type, Art.INK)
		th.set_stylebox("focus", type, StyleBoxEmpty.new())
	for type in ["VScrollBar", "HScrollBar"]:
		th.set_stylebox("scroll", type, Art.box(Color(0, 0, 0, 0), 4))
		th.set_stylebox("grabber", type, Art.box(Color(1, 1, 1, 0.14), 4))
		th.set_stylebox("grabber_highlight", type, Art.box(Color(1, 1, 1, 0.24), 4))
		th.set_stylebox("grabber_pressed", type, Art.box(Color(1, 1, 1, 0.3), 4))
	th.set_constant("separation", "HSplitContainer", 12)
	th.set_icon("grabber", "HSplitContainer", ImageTexture.new())
	return th


func _label(text: String, size: int = 14, kind: String = "ui", col: Color = Art.INK) -> Label:
	var l := Label.new()
	l.text = text
	l.add_theme_font_override("font", Art.font(kind))
	l.add_theme_font_size_override("font_size", size)
	l.add_theme_color_override("font_color", col)
	return l


func _card(accent: Color = Color(0, 0, 0, 0)) -> PanelContainer:
	var pc := PanelContainer.new()
	var sb := _pad(Art.box(Art.PANEL, 12, Art.LINE, 1), 12, 9)
	if accent.a > 0:
		sb.border_color = Color(accent, 0.55)
		sb.border_width_top = 3
	pc.add_theme_stylebox_override("panel", sb)
	return pc


## Bouton d'un groupe de choix (vitesse, mode) : le choix actif est en bleu, comme les liens de parole.
func _seg(text: String) -> Button:
	var b := Button.new()
	b.text = text
	b.toggle_mode = true
	b.focus_mode = Control.FOCUS_NONE
	var on := _pad(Art.box(Color(Art.TALK, 0.26), 9, Color(Art.TALK, 0.85), 1), 11, 5)
	b.add_theme_stylebox_override("pressed", on)
	b.add_theme_stylebox_override("hover_pressed", on)
	b.add_theme_color_override("font_pressed_color", Color.WHITE)
	b.add_theme_color_override("font_hover_pressed_color", Color.WHITE)
	for st in ["normal", "hover"]:
		var sb := _pad(Art.box(Art.PANEL_2 if st == "normal" else Color("#26314d"), 9, Art.LINE, 1), 11, 5)
		b.add_theme_stylebox_override(st, sb)
	return b


func _kpi(parent: Control, key: String, title: String, sub: String, accent: Color, big: bool) -> void:
	var pc := _card(accent if big else Color(0, 0, 0, 0))
	pc.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	parent.add_child(pc)
	var vb := VBoxContainer.new()
	vb.add_theme_constant_override("separation", 0 if big else -2)
	pc.add_child(vb)
	vb.add_child(_label(title.to_upper(), 10, "ui_black", Art.MUTED))
	var v := _label("—", 28 if big else 17, "title" if big else "ui_bold", accent.lightened(0.25) if big else Art.INK)
	vb.add_child(v)
	ind_labels[key] = v
	if sub != "":
		var sl := _label(sub, 11, "ui", Color(Art.MUTED, 0.85))
		vb.add_child(sl)
		ind_sub[key] = sl


func _build_ui() -> void:
	theme = _make_theme()
	var bg := ColorRect.new()
	bg.color = Art.BG
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(bg)
	var margin := MarginContainer.new()
	margin.set_anchors_preset(Control.PRESET_FULL_RECT)
	for side in ["left", "right", "top", "bottom"]:
		margin.add_theme_constant_override("margin_" + side, 12)
	add_child(margin)
	var root := VBoxContainer.new()
	root.add_theme_constant_override("separation", 10)
	margin.add_child(root)

	# --- en-tête
	var top := HBoxContainer.new()
	top.add_theme_constant_override("separation", 12)
	root.add_child(top)
	var title := _label("FILETS", 30, "title", Color("#f3dca8"))
	top.add_child(title)
	var subtitle := _label("la tragédie des communs au lac de Vellmor", 17, "title_italic", Art.MUTED)
	subtitle.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	top.add_child(subtitle)
	var sp := Control.new()
	sp.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	top.add_child(sp)
	lbl_run = _label("en attente d'un run…", 12, "ui_bold", Art.MUTED)
	lbl_run.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	top.add_child(lbl_run)
	lbl_clock = _label("", 12, "ui_bold", Art.MUTED)     # l'horloge est sur la carte ; conservé pour compatibilité
	lbl_clock.visible = false
	top.add_child(lbl_clock)
	var status_box := PanelContainer.new()
	status_box.add_theme_stylebox_override("panel", _pad(Art.box(Art.PANEL_2, 14, Art.LINE, 1), 12, 4))
	status_box.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	top.add_child(status_box)
	lbl_status = _label("connexion…", 12, "ui_bold", Art.MUTED)
	status_box.add_child(lbl_status)

	# --- barre de pilotage : pause, vitesse, mode (affichée quand le moteur la propose)
	transport = PanelContainer.new()
	transport.add_theme_stylebox_override("panel", _pad(Art.box(Art.PANEL, 14, Art.LINE, 1), 12, 6))
	transport.visible = false
	root.add_child(transport)
	var tr := HBoxContainer.new()
	tr.add_theme_constant_override("separation", 8)
	transport.add_child(tr)
	btn_pause = Button.new()
	btn_pause.text = "Pause"
	btn_pause.focus_mode = Control.FOCUS_NONE
	btn_pause.custom_minimum_size = Vector2(118, 0)
	btn_pause.tooltip_text = "Espace"
	btn_pause.pressed.connect(_toggle_pause)
	tr.add_child(btn_pause)
	tr.add_child(VSeparator.new())
	var l_speed := _label("VITESSE ×", 10, "ui_black", Art.MUTED)
	l_speed.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	l_speed.tooltip_text = "Synchrone : rythme d'affichage. Asynchrone : le monde suit le temps réel à cette vitesse, " \
		+ "donc une IA lente paraît moins lente quand on ralentit."
	tr.add_child(l_speed)
	var speed_group := ButtonGroup.new()
	for s in SPEEDS:
		var b := _seg(_speed_label(s))
		b.button_group = speed_group
		b.pressed.connect(func() -> void: _send({"type": "set_speed", "value": s}))
		speed_buttons[s] = b
		tr.add_child(b)
	var b_max := _seg("Max")
	b_max.button_group = speed_group
	b_max.tooltip_text = "Aucune attente d'affichage : la partie va aussi vite que possible"
	b_max.pressed.connect(func() -> void: _send({"type": "set_speed", "value": "max"}))
	speed_buttons["max"] = b_max
	tr.add_child(b_max)
	tr.add_child(VSeparator.new())
	var l_mode := _label("TEMPS", 10, "ui_black", Art.MUTED)
	l_mode.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	tr.add_child(l_mode)
	var mode_group := ButtonGroup.new()
	for m in [["sync", "Synchrone"], ["async", "Asynchrone"]]:
		var b := _seg(m[1])
		b.button_group = mode_group
		b.tooltip_text = "Le changement s'applique au début de la saison suivante"
		b.pressed.connect(func() -> void: _send({"type": "set_mode", "value": m[0]}))
		mode_buttons[m[0]] = b
		tr.add_child(b)
	lbl_pending = _label("", 12, "ui_bold", Art.PROPOSAL)
	lbl_pending.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	tr.add_child(lbl_pending)
	lbl_lost = _label("", 12, "ui_bold", Art.INCIDENT)
	lbl_lost.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	lbl_lost.visible = false
	tr.add_child(lbl_lost)
	btn_slow = Button.new()
	btn_slow.focus_mode = Control.FOCUS_NONE
	btn_slow.visible = false
	var slow_sb := _pad(Art.box(Color("#3a2414"), 9, Color(Art.INCIDENT, 0.6), 1), 11, 5)
	btn_slow.add_theme_stylebox_override("normal", slow_sb)
	btn_slow.add_theme_stylebox_override("hover", _pad(Art.box(Color("#4d2f18"), 9, Color(Art.INCIDENT, 0.9), 1), 11, 5))
	btn_slow.add_theme_color_override("font_color", Color("#ffc08a"))
	btn_slow.pressed.connect(func() -> void: _send({"type": "set_speed", "value": slow_target}))
	tr.add_child(btn_slow)
	var tr_sp := Control.new()
	tr_sp.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	tr.add_child(tr_sp)
	lbl_progress = _label("", 13, "ui_bold", Art.INK)
	lbl_progress.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	tr.add_child(lbl_progress)
	btn_stop = Button.new()
	btn_stop.text = "Arrêter la partie"
	btn_stop.focus_mode = Control.FOCUS_NONE
	btn_stop.pressed.connect(_on_stop_pressed)
	tr.add_child(btn_stop)
	btn_new = Button.new()
	btn_new.text = "Nouvelle partie"
	btn_new.focus_mode = Control.FOCUS_NONE
	btn_new.pressed.connect(func() -> void: menu.open(true))
	tr.add_child(btn_new)

	# --- centre : carte | tableau de bord
	var mid := HSplitContainer.new()
	mid.size_flags_vertical = Control.SIZE_EXPAND_FILL
	root.add_child(mid)
	var map_frame := PanelContainer.new()
	map_frame.add_theme_stylebox_override("panel", Art.box(Color("#0a0f1a"), 6, Color(1, 1, 1, 0.12), 1, 12))
	map_frame.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	map_frame.size_flags_stretch_ratio = 1.7
	mid.add_child(map_frame)
	world = WorldView.new()
	world.custom_minimum_size = Vector2(680, 520)
	world.agent_clicked.connect(_select)
	map_frame.add_child(world)
	# fin de partie : une carte par-dessus la vallée, qui laisse passer les clics ailleurs
	end_overlay = CenterContainer.new()
	end_overlay.mouse_filter = Control.MOUSE_FILTER_IGNORE
	end_overlay.visible = false
	map_frame.add_child(end_overlay)
	var end_card := PanelContainer.new()
	end_card.add_theme_stylebox_override("panel", _pad(Art.box(Color(0.05, 0.07, 0.12, 0.95), 18, Color(Art.PROMISE, 0.6), 1, 24), 30, 22))
	end_overlay.add_child(end_card)
	var end_v := VBoxContainer.new()
	end_v.add_theme_constant_override("separation", 8)
	end_card.add_child(end_v)
	end_title = _label("Partie terminée", 28, "title", Color("#f3dca8"))
	end_title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	end_v.add_child(end_title)
	end_text = _label("", 14, "ui", Art.INK)
	end_text.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	end_v.add_child(end_text)
	var end_buttons := HBoxContainer.new()
	end_buttons.alignment = BoxContainer.ALIGNMENT_CENTER
	end_buttons.add_theme_constant_override("separation", 10)
	end_v.add_child(end_buttons)
	end_new = Button.new()
	end_new.text = "Nouvelle partie"
	end_new.focus_mode = Control.FOCUS_NONE
	end_new.pressed.connect(func() -> void: menu.open(true))
	end_buttons.add_child(end_new)
	var end_look := Button.new()
	end_look.text = "Revoir la partie"
	end_look.focus_mode = Control.FOCUS_NONE
	end_look.pressed.connect(func() -> void: end_overlay.visible = false)
	end_buttons.add_child(end_look)

	var right := VBoxContainer.new()
	right.custom_minimum_size = Vector2(500, 0)
	right.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	right.add_theme_constant_override("separation", 10)
	mid.add_child(right)
	var kpis := HBoxContainer.new()
	kpis.add_theme_constant_override("separation", 10)
	right.add_child(kpis)
	_kpi(kpis, "stock", "Stock du lac", "repeuplement max à 50 %", Color("#4fb3d9"), true)
	_kpi(kpis, "norme", "Norme partagée", "accord × conformité", Art.PROPOSAL, true)
	_kpi(kpis, "promesses", "Promesses tenues", "écart moyen —", Art.SUPPORT, true)
	var grid := GridContainer.new()
	grid.columns = 3
	grid.add_theme_constant_override("h_separation", 10)
	grid.add_theme_constant_override("v_separation", 10)
	right.add_child(grid)
	for k in [["accord", "Accord déclaré", "pêcheurs pour la règle"], ["conformite", "Conformité", "pêcheurs qui la respectent"],
			["cv", "Dispersion des prises", "écart-type ÷ moyenne"],
			["incidents", "Incidents LLM", ""], ["llm", "Appels LLM", ""], ["tokens", "Tokens", ""],
			["violations", "Violations temporelles", ""], ["obsolescence", "Obsolescence moy.", "lac vu ≠ lac réel"],
			["ecart", "Écart promis/pêché", "tonnes par pêcheur"]]:
		_kpi(grid, k[0], k[1], k[2], Color(0, 0, 0, 0), false)
	var chart_card := _card()
	chart_card.custom_minimum_size = Vector2(0, 180)
	right.add_child(chart_card)
	chart = Chart.new()
	chart_card.add_child(chart)

	tabs = TabContainer.new()
	tabs.size_flags_vertical = Control.SIZE_EXPAND_FILL
	right.add_child(tabs)
	var feed_box := VBoxContainer.new()
	feed_box.name = "Interactions"
	tabs.add_child(feed_box)
	feed_only_selected = CheckBox.new()
	feed_only_selected.text = "Seulement l'agent sélectionné"
	feed_only_selected.add_theme_font_size_override("font_size", 12)
	feed_only_selected.toggled.connect(func(_on: bool) -> void: feed_dirty = true)
	feed_box.add_child(feed_only_selected)
	feed = _rich()
	feed.scroll_following = true
	feed_box.add_child(feed)
	narration = _rich()
	narration.name = "Récit de l'ancien"
	narration.scroll_following = true
	tabs.add_child(narration)
	trust_view = _rich()
	trust_view.name = "Confiance"
	tabs.add_child(trust_view)
	inspector = _rich()
	inspector.name = "Agent"
	tabs.add_child(inspector)
	rules_view = _rich()
	rules_view.name = "Règles"
	tabs.add_child(rules_view)

	# --- barre d'intervention
	var bar := PanelContainer.new()
	bar.add_theme_stylebox_override("panel", _pad(Art.box(Art.PANEL, 14, Art.LINE, 1), 14, 8))
	root.add_child(bar)
	var bar_v := VBoxContainer.new()
	bar_v.add_theme_constant_override("separation", 6)
	bar.add_child(bar_v)
	var bottom := HBoxContainer.new()
	bottom.add_theme_constant_override("separation", 10)
	bar_v.add_child(bottom)
	var lab := _label("INTERVENIR", 10, "ui_black", Art.MUTED)
	lab.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	bottom.add_child(lab)
	var drought := Button.new()
	drought.text = "Sécheresse  ·  stock ÷ 2"
	drought.add_theme_stylebox_override("normal", _pad(Art.box(Color("#3a2414"), 9, Color(Art.INCIDENT, 0.5), 1), 12, 6))
	drought.add_theme_stylebox_override("hover", _pad(Art.box(Color("#4d2f18"), 9, Color(Art.INCIDENT, 0.8), 1), 12, 6))
	drought.add_theme_color_override("font_color", Color("#ffc08a"))
	drought.pressed.connect(func() -> void: _send({"type": "drought", "factor": 0.5}))
	bottom.add_child(drought)
	var lc := _label("Communication", 13, "ui", Art.MUTED)
	lc.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	bottom.add_child(lc)
	comm_opt = OptionButton.new()
	for item in [["conseil de la vallée", "valley"], ["par village", "hamlet"], ["interdite", "none"]]:
		comm_opt.add_item(item[0])
		comm_opt.set_item_metadata(comm_opt.item_count - 1, item[1])
	comm_opt.item_selected.connect(func(i: int) -> void:
		_send({"type": "set_communication", "value": comm_opt.get_item_metadata(i)}))
	bottom.add_child(comm_opt)
	vis_check = CheckButton.new()
	vis_check.text = "Déclarations publiques"
	vis_check.tooltip_text = "Les déclarations faites à l'ancien sont lues à toute la vallée (sinon : au seul hameau). Les vraies prises, seuls vous et chaque pêcheur les connaissez."
	vis_check.button_pressed = true
	vis_check.toggled.connect(func(on: bool) -> void: _send({"type": "set_visibility", "value": on}))
	bottom.add_child(vis_check)
	lbl_patrol = _label("Patrouille : aucune", 13, "ui", Art.MUTED)
	lbl_patrol.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	lbl_patrol.tooltip_text = "Le conseil de la vallée peut voter une patrouille du lac, aux frais de chaque pêcheur : elle visite quelques zones par saison et mesure les barques qu'elle croise. L'ancien l'envoie là où il se méfie ; les pêcheurs ne savent pas où elle passera."
	bottom.add_child(lbl_patrol)
	lbl_weather = _label("", 13, "ui", Art.MUTED)
	lbl_weather.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	lbl_weather.tooltip_text = "Le temps sur le lac, le même pour tous les pêcheurs : un jour agité ou de tempête rapporte bien moins, surtout aux petits bateaux. Chaque pêcheur sort plusieurs fois par saison."
	bottom.add_child(lbl_weather)
	rumor_edit = LineEdit.new()
	rumor_edit.placeholder_text = "Faire courir une rumeur dans la vallée…"
	rumor_edit.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	rumor_edit.text_submitted.connect(func(_t: String) -> void: _rumor())
	bottom.add_child(rumor_edit)
	var rumor_btn := Button.new()
	rumor_btn.text = "Diffuser"
	rumor_btn.pressed.connect(_rumor)
	bottom.add_child(rumor_btn)
	legend = Legend.new()
	bar_v.add_child(legend)

	# --- menu de démarrage, par-dessus tout le reste
	menu = StartMenu.new()
	add_child(menu)
	menu.start_requested.connect(_on_menu_start)
	menu.generate_requested.connect(_on_menu_generate)
	menu.cancelled.connect(func() -> void: menu.close())


# ------------------------------------------------------------------ pilotage de la partie
func _speed_label(s: float) -> String:
	if is_equal_approx(s, 0.0625):
		return "1/16"
	if is_equal_approx(s, 0.125):
		return "1/8"
	if is_equal_approx(s, 0.25):
		return "¼"
	if is_equal_approx(s, 0.5):
		return "½"
	return str(int(s))


func _controllable() -> bool:
	return ws_ok and bool(engine.get("controls", false)) and (engine_state == "running" or engine_state == "paused")


func _toggle_pause() -> void:
	if _controllable():
		_send({"type": "resume" if engine_state == "paused" else "pause"})


## Arrêter est irréversible : un premier clic arme le bouton, un second (dans les 3 s) confirme.
func _on_stop_pressed() -> void:
	var now := Time.get_ticks_msec()
	if stop_armed_ms > 0 and now - stop_armed_ms < 3000:
		stop_armed_ms = 0
		_send({"type": "stop"})
	else:
		stop_armed_ms = now
	_update_transport()


func _on_menu_start(cfg: Dictionary) -> void:
	if not ws.send({"type": "start_game", "config": cfg}):
		menu.show_error("Pas de connexion au moteur : lancez-le (python -m filets serve) puis réessayez.")


func _on_menu_generate(params: Dictionary) -> void:
	if not ws.send({"type": "generate_world", "config": params}):
		menu.show_error("Pas de connexion au moteur : lancez-le (python -m filets serve) puis réessayez.")


func _on_status(s: Dictionary) -> void:
	engine = s
	engine_seen_ms = Time.get_ticks_msec()
	var st := str(s.get("state", ""))
	var err := "" if s.get("error") == null else str(s.get("error"))
	world.paused = st == "paused"
	if st == "paused":
		world.time_scale = 0.0
	elif bool(s.get("fast", false)):
		world.time_scale = 3.0
	else:
		world.time_scale = clampf(float(s.get("speed", 1.0)), 0.5, 3.0)
	menu.set_engine(st, true, "" if s.get("detail") == null else str(s.get("detail")))
	if st != engine_state:
		engine_state = st
		stop_armed_ms = 0
		match st:
			"idle":
				menu.open(not run.is_empty())
				if err != "":
					menu.show_error(err)
					last_error = err
			"running", "paused":
				menu.close()
				end_overlay.visible = false
			"ended":
				menu.close()       # un client arrivé après la fin : la partie d'abord, le menu sur demande
				_show_end(s)
	if err != "" and err != last_error and menu.visible:
		menu.show_error(err)       # un refus du moteur (une vallée impossible…) qui ne change pas son état
	last_error = err
	_update_transport()


var end_status := {}


func _show_end(s: Dictionary) -> void:
	end_status = s
	end_new.visible = bool(s.get("lobby", false))
	_refresh_end_text()
	end_overlay.visible = true


## Le texte dépend des indicateurs, qui arrivent après l'état chez un client venu après la fin : on le rafraîchit.
func _refresh_end_text() -> void:
	if end_status.is_empty():
		return
	var reasons := {"completed": "Toutes les saisons ont été jouées.", "stop": "La partie a été arrêtée.",
		"collapse": "Le lac s'est effondré : la partie s'arrête.",
		"extinction": "Le lac est à sec : il n'y a plus un seul poisson, et un lac vide ne se repeuple jamais."}
	var why := str(end_status.get("end_reason", ""))
	end_title.text = "Partie terminée" if why != "stop" else "Partie arrêtée"
	end_text.text = "%s\n%s · stock final %s" % [reasons.get(why, why), str(end_status.get("sim_label", "")),
		ind_labels["stock"].text]


func _update_transport() -> void:
	var st := engine_state
	var has := ws_ok and not engine.is_empty() and bool(engine.get("controls", false))
	transport.visible = has and st != "idle"
	if not has:
		return
	var live := st == "running" or st == "paused"
	btn_pause.disabled = not live
	btn_pause.text = "Reprendre" if st == "paused" else "Pause"
	var fast := bool(engine.get("fast", false))
	var speed := float(engine.get("speed", 1.0))
	for k in speed_buttons:
		var b: Button = speed_buttons[k]
		b.disabled = not live
		var on: bool = fast if str(k) == "max" else (not fast and absf(float(k) - speed) < 0.001)
		b.set_pressed_no_signal(on)
	var cur := str(engine.get("mode", ""))
	var pend := "" if engine.get("pending_mode") == null else str(engine.get("pending_mode"))
	for k in mode_buttons:
		var b: Button = mode_buttons[k]
		b.disabled = not live
		b.set_pressed_no_signal(k == (pend if pend != "" else cur))
	lbl_pending.text = "" if pend == "" else "→ %s dès la saison suivante" % ("asynchrone" if pend == "async" else "synchrone")
	_update_slow_hint(live, fast, speed, pend if pend != "" else cur)
	if live:
		lbl_progress.text = "Saison %d / %d  ·  %s" % [int(engine.get("season", 0)), int(engine.get("seasons", 0)), str(engine.get("sim_label", ""))]
		if engine.get("detail") != null:        # asynchrone : le temps est suspendu, le monde attend des IA
			lbl_progress.text += "  ·  " + str(engine.get("detail"))
	elif st == "starting":
		lbl_progress.text = "Préparation…" if engine.get("detail") == null else str(engine.get("detail"))
	else:
		lbl_progress.text = ""
	btn_stop.visible = live
	btn_stop.text = "Confirmer l'arrêt ?" if stop_armed_ms > 0 else "Arrêter la partie"
	btn_new.visible = st == "ended" and bool(engine.get("lobby", false))


## Asynchrone + vraie IA (locale ou distante) + monde plus rapide que ce que le moteur d'IA peut suivre : les IA ratent leur
## fenêtre (« réplique perdue »). Le moteur publie la vitesse qui convient (`advised_speed`) ; on propose de s'y mettre d'un clic.
## Si, même à cette vitesse, au moins deux répliques ou sorties se perdent dans la saison, on propose la vitesse du dessous.
func _update_slow_hint(live: bool, fast: bool, speed: float, mode: String) -> void:
	var adv: Variant = engine.get("advised_speed")
	var real_ai := false
	var ais: Variant = engine.get("ai")
	if ais is Array:
		for p in ais:
			if str(p) != "scripted":
				real_ai = true
	var target := -1.0
	var still_losing := false
	if adv != null and (fast or speed > float(adv) + 0.0001):
		target = float(adv)
	elif lost_this_season >= 2 and not fast:
		still_losing = true
		for s in SPEEDS:                       # croissantes : on garde la plus grande vitesse inférieure à la vitesse actuelle
			if float(s) < speed - 0.0001:
				target = float(s)
	var show: bool = live and mode == "async" and real_ai and target > 0.0
	btn_slow.visible = show
	lbl_lost.visible = live and lost_this_season > 0
	if lost_this_season > 0:
		lbl_lost.text = "%d perdue%s cette saison" % [lost_this_season, "s" if lost_this_season > 1 else ""]
	if show:
		btn_slow.text = "Ralentir (× %s)" % _speed_label(target)
		slow_target = target
		if still_losing:
			btn_slow.tooltip_text = ("Encore %d répliques ou sorties perdues cette saison : l'IA réfléchit plus longtemps que ce "
				+ "que le monde lui laisse. × %s lui donne plus de temps.") % [lost_this_season, _speed_label(target)]
		else:
			btn_slow.tooltip_text = ("En asynchrone, le monde continue d'avancer pendant que l'IA réfléchit : à cette vitesse, elle "
				+ "rate souvent sa pêche ou sa veillée (« réplique perdue »). × %s laisse à l'IA le temps de répondre.") % _speed_label(target)


func _unhandled_key_input(event: InputEvent) -> void:
	var k := event as InputEventKey
	if k and k.pressed and not k.echo and k.keycode == KEY_SPACE and not menu.visible and _controllable():
		_toggle_pause()
		get_viewport().set_input_as_handled()


func _rumor() -> void:
	if rumor_edit.text.strip_edges() != "":
		_send({"type": "announcement", "text": rumor_edit.text.strip_edges()})
		rumor_edit.text = ""


func _rich() -> RichTextLabel:
	var r := RichTextLabel.new()
	r.bbcode_enabled = true
	r.size_flags_vertical = Control.SIZE_EXPAND_FILL
	r.selection_enabled = true
	return r


func _ind_title(k: String) -> String:
	return {"stock": "Stock", "norme": "Indice de norme", "accord": "Accord", "conformite": "Conformité",
		"promesses": "Promesses tenues", "ecart": "Écart promesse", "cv": "Dispersion prises",
		"incidents": "Incidents", "llm": "Appels LLM", "tokens": "Tokens", "violations": "Violations temporelles",
		"obsolescence": "Obsolescence moy."}.get(k, k)


func _send(cmd: Dictionary) -> void:
	if not ws.send(cmd):
		_feed("[color=#ff6a5c]Injection impossible : pas de connexion au pont.[/color]", [])


# ------------------------------------------------------------------ messages
func _on_message(topic: String, data: Dictionary) -> void:
	if topic == "catalog":              # hors historique : ne compte pas dans le rattrapage
		catalog = data
		menu.set_catalog(data)
		# pas encore d'état du moteur : on montre le menu en attendant qu'il s'annonce (s'il y a déjà une partie
		# en cours, son état arrive juste après et referme le menu dans la même image)
		if engine_state == "" and run.is_empty():
			menu.open(false)
		return
	if topic == "status":
		_on_status(data)
		return
	if topic == "hello":
		catching_up = int(data.get("buffered", 0))
		world.animate = catching_up == 0
		return
	if catching_up > 0:
		catching_up -= 1
		if catching_up == 0:
			world.animate = true
	if topic == "indicators":
		n_indicators += 1
		_on_indicator(data)
	elif topic == "events":
		n_events += 1
		_on_event(data)


func _on_event(ev: Dictionary) -> void:
	var t: String = str(ev.get("type", ""))
	var p: Dictionary = ev.get("payload", {})
	last_sim_label = str(ev.get("sim_label", last_sim_label))
	if t == "run_start":
		_reset(ev)
	world.on_event(ev)
	var lab := "[color=#6f7896][font_size=11]%s[/font_size][/color]  " % last_sim_label
	match t:
		"season_start":
			lost_this_season = 0
			var md := "" if not p.has("mode") else ("  · asynchrone" if str(p["mode"]) == "async" else "  · synchrone")
			var cond: Dictionary = p.get("conditions", {})
			weather_days = cond.get("days", []) if cond.get("climate") != null else []
			weather_season = int(ev.get("season", 0))
			if cond.get("climate") != null:
				md = "  · %s%s" % [str(cond["climate"]), md]
			_feed("\n[center][font=res://fonts/alegreya-latin-700-normal.woff2][font_size=17][color=#f3dca8]Saison %d[/color][/font_size][/font]  [color=#8f97b2]· le lac compte %.1f t%s[/color][/center]" % [int(ev.get("season", 0)), float(p.get("stock", 0)), md], [])
			if not weather_days.is_empty():
				_feed("[center][color=#6f7896][font_size=12]%s[/font_size][/color][/center]" % _sky_text(weather_days), [])
		"catch":
			var id := str(p.get("agent", ""))
			var a = _agent(id)
			if a:
				var s := str(int(ev.get("season", 0)))
				a["catches"][s] = float(a["catches"].get(s, 0.0)) + float(p.get("landed", 0))
			var gap := ""
			if absf(float(p.get("stock_at_action", 0)) - float(p.get("stock_at_horizon", 0))) > 0.5:
				gap = "  [color=#6f7896](lac vu à %.0f t, %.0f t au départ)[/color]" % [float(p.get("stock_at_horizon", 0)),
					float(p.get("stock_at_action", 0))]
			if bool(p.get("secret", false)):
				var zone := str(p.get("zone", ""))
				_feed(lab + _tag("EN CACHETTE", "#ff8a5c") + " %s, interdit de pêche, sort %s et ramène [b]%.1f t[/b]  [color=#6f7896](seuls lui et vous le savez)[/color]" % [
					_who(id), "au large" if zone == "large" else "du côté de " + zone, float(p.get("landed", 0))], [id])
			else:
				var aim := ""
				if p.has("yield") and absf(float(p.get("yield", 1.0)) - 1.0) >= 0.15 and float(p.get("requested", 0)) > 0.0:
					var yv := float(p.get("yield", 1.0))
					aim = "  [color=%s](visait %s t : %s pêche%s)[/color]" % ["#ff8a7e" if yv < 1.0 else "#58d08a", _num(p.get("requested", 0)), _day_word(yv),
						_weather_note(p.get("outings", []))]
				_feed(lab + _tag("PÊCHE", "#7fd0e8") + " %s ramène [b]%.1f t[/b]%s%s" % [_who(id), float(p.get("landed", 0)), aim, gap], [id])
		"report":
			# la déclaration à l'ancien : les autres ne connaissent qu'elle ; un mensonge n'est visible que d'ici
			var id := str(p.get("agent", ""))
			var a = _agent(id)
			var landed := float(p.get("landed", 0))
			var said := float(p.get("declared", 0))
			if a:
				a["declared"][str(int(ev.get("season", 0)))] = said
				trust_dirty = true
			if landed - said > 0.05:
				_feed(lab + _tag("MENSONGE", "#ff8a5c") + " %s déclare [b]%s t[/b] à l'ancien, en a pêché [b][color=#ff8a7e]%s t[/color][/b]  [color=#6f7896](seuls lui et vous le savez)[/color]" % [
					_who(id), _num(said), _num(landed)], [id])
		"lie_discovered":
			# l'ancien tient un mensonge (ou une sortie en cachette) pour établi sur des indices ; le joueur voit s'il se trompe
			var id := str(p.get("agent", ""))
			var a = _agent(id)
			if a:
				a["lies_found"] = int(a["lies_found"]) + 1
				trust_dirty = true
			var how: String = {"patrouille": "la patrouille l'a mesuré", "temoins": "des voisins l'ont vu", "indices": "les indices concordent"}.get(str(p.get("how", "")), "")
			var est := ("environ %s t" % _num(p.get("estimated"))) if p.get("estimated") != null else "une quantité inconnue"
			var wit := PackedStringArray()
			for w in p.get("witnesses", []):
				wit.append(_who(str(w)))
			var what := ("%s, interdit de pêche, pris à pêcher en cachette : %s" % [_who(id), est]) if bool(p.get("secret", false)) \
				else ("%s a déclaré %s t, la vallée établit %s" % [_who(id), _num(p.get("declared", 0)), est])
			_feed(lab + _tag("ACCUSÉ À TORT" if bool(p.get("wrongful", false)) else ("PRIS EN CACHETTE" if bool(p.get("secret", false)) else "MENSONGE ÉTABLI"), "#ff6a5c")
				+ " %s · %s%s  [color=#6f7896](vraie prise : %s t)[/color]" % [what, how, (" (" + ", ".join(wit) + ")") if not wit.is_empty() else "", _num(p.get("landed", 0))], [id])
		"clue":
			var sub := str(p.get("subject", ""))
			var obs := str(p.get("observer")) if p.get("observer") != null else ""
			var kind := str(p.get("kind", ""))
			var said := "" if p.get("declared") == null else " (déclaré %s t)" % _num(p.get("declared"))
			var txt := ""
			match kind:
				"patrouille":
					txt = "la patrouille mesure environ [b]%s t[/b] dans la barque de %s%s" % [_num(p.get("estimate", 0)), _who(sub), said]
				"temoin":
					txt = "%s a vu la barque de %s rentrer avec environ [b]%s t[/b]%s" % [_who(obs), _who(sub), _num(p.get("estimate", 0)), said]
				"depart":
					txt = "%s a vu la barque de %s, interdit de pêche, partir à l'aube" % [_who(obs), _who(sub)]
				_:
					txt = "%s trouve que %s vit bien pour ce qu'il déclare%s" % [_who(obs), _who(sub), said]
			var kept := "" if bool(p.get("public", true)) else "  [color=#6f7896](il le garde pour lui : seuls lui et vous le savez)[/color]"
			_feed(lab + _tag("INDICE" if bool(p.get("public", true)) else "INDICE GARDÉ", "#7fe0c8") + " " + txt + kept, [sub, obs])
		"lake_audit":
			var col := "#ff8a7e" if bool(p.get("significant", false)) else "#8f97b2"
			_feed(lab + _tag("COMPTES", "#7fe0c8") + " [color=%s]la pêche a fait perdre environ %s t au lac ; les déclarations en expliquent %s t[/color]" % [
				col, _num(p.get("drop", 0)), _num(p.get("declared", 0))], [])
		"ban":
			var id := str(p.get("agent", ""))
			var a = _agent(id)
			if a:
				a["banned"] = bool(p.get("banned", false))
				trust_dirty = true
			if bool(p.get("banned", false)):
				_feed(lab + _tag("INTERDIT DE PÊCHE", "#ff6a5c") + " la vallée a voté l'exclusion de %s : il ne peut plus pêcher qu'en cachette  [color=#6f7896](réputation %d %%)[/color]" % [_who(id), roundi(float(p.get("reputation", 0)) * 100.0)], [id])
			else:
				_feed(lab + _tag("RÉAUTORISÉ", "#58d08a") + " la vallée a voté de laisser %s pêcher à nouveau  [color=#6f7896](réputation %d %%)[/color]" % [_who(id), roundi(float(p.get("reputation", 0)) * 100.0)], [id])
		"sanction_proposal":
			var target := str(p.get("target", ""))
			var author := str(p.get("author", ""))
			var act := str(p.get("action", ""))
			if act == "patrouille" or act == "fin_patrouille":
				_feed(lab + _tag("PATROUILLE", "#7fe0c8") + " %s propose %s la patrouille du lac [b](%s)[/b]" % [
					_who(author), "d'installer" if act == "patrouille" else "de retirer", str(p.get("proposal_id", ""))], [author])
			else:
				var excl := act == "exclure"
				_feed(lab + _tag("EXCLUSION" if excl else "RÉAUTORISATION", "#ff8a5c" if excl else "#58d08a") + " %s propose %s %s [b](%s)[/b]" % [
					_who(author), "d'interdire de pêche" if excl else "de laisser pêcher à nouveau", _who(target), str(p.get("proposal_id", ""))], [author, target])
		"sanction_result":
			var target := str(p.get("target", ""))
			var act := str(p.get("action", ""))
			var ok := bool(p.get("adopted", false))
			var what: String = {"exclure": "exclusion de %s", "reautoriser": "réautorisation de %s", "patrouille": "installation de la patrouille",
				"fin_patrouille": "retrait de la patrouille"}.get(act, act)
			if what.contains("%s"):
				what = what % _who(target)
			_feed(lab + _tag("VOTE " + str(p.get("proposal_id", "")), "#58d08a" if ok else "#8f97b2") + " %s %s : %d pour, %d contre, sur %d votants" % [
				what, "[b]adoptée[/b]" if ok else "rejetée",
				p.get("for", []).size(), p.get("against", []).size(), int(p.get("voters", 0))], [target] if target != "" else [])
		"patrol_route":
			# la route de la patrouille cette saison : le joueur la voit, les pêcheurs ne la connaissent pas
			var zs := PackedStringArray()
			for leg in p.get("legs", []):
				zs.append("le large" if str(leg.get("zone", "")) == "large" else str(leg.get("zone", "")))
			lbl_patrol.text = "Patrouille : en route vers " + " → ".join(zs)
			_feed(lab + _tag("PATROUILLE", "#7fe0c8") + " l'ancien l'envoie vers [b]%s[/b]  [color=#6f7896](les pêcheurs ne savent pas où elle passera)[/color]" % " → ".join(zs), [])
		"patrol":
			var on := str(p.get("state", "")) == "installed"
			patrol_installed = on
			lbl_patrol.text = "Patrouille : dès la saison %d" % int(p.get("effective_season", 0)) if on else "Patrouille : aucune"
			_feed(lab + _tag("PATROUILLE", "#7fe0c8") + " le conseil [b]%s[/b] la patrouille du lac dès la saison %d  [color=#6f7896](%d écus par pêcheur et par saison)[/color]" % [
				"installe" if on else "retire", int(p.get("effective_season", 0)), int(p.get("cost", 0))], [])
		"election":
			# l'élu d'un village ; on ne le dit que s'il change (ou à la première saison)
			var rep := str(p.get("representative", ""))
			var hm := str(p.get("hamlet", ""))
			reps[hm] = rep
			if p.get("incumbent") == null or str(p.get("incumbent")) != rep:
				_feed(lab + _tag("ÉLU", "#e2bd6a") + " %s représente [b]%s[/b] au conseil  [color=#6f7896](%d voix sur %d)[/color]" % [
					_who(rep), hm, int(p.get("votes", {}).get(rep, 0)), int(p.get("voters", 0))], [rep])
		"world_event":
			_feed(lab + _tag("ÉVÉNEMENT", "#f39c4a") + " [b]%s[/b] : %s  [color=#6f7896](jusqu'à la saison %d)[/color]" % [
				str(p.get("label", "")), _esc(str(p.get("text", ""))), int(p.get("until", 0))], [])
		"trust":
			var a = _agent(str(p.get("subject", "")))
			if a:
				a["reputation"] = float(p.get("reputation", 0.5))
				var vals: Dictionary = p.get("values", {})
				for o in vals:
					a["trust_from"][str(o)] = float(vals[o])
				trust_dirty = true
			# un jugement marqué (au moins 0,2) : c'est l'agent qui a décidé ce que l'acte changeait pour lui
			var d := float(p.get("delta", 0.0))
			if absf(d) >= 0.2 and p.get("by") != null:
				var by := str(p.get("by"))
				var sub := str(p.get("subject", ""))
				_feed(lab + _tag("CONFIANCE", "#b78fd6") + " %s %s %s [color=%s](%+.1f)[/color]" % [_who(by),
					"retire de sa confiance à" if d < 0 else "accorde davantage sa confiance à", _who(sub),
					"#ff8a7e" if d < 0 else "#58d08a", d], [by, sub])
		"sale":
			var a = _agent(str(p.get("agent", "")))
			if a:
				a["wealth"] = float(p.get("wealth", 0))
		"assembly_start":
			if p.has("delegates"):
				var who_sits := PackedStringArray()
				for h in p["delegates"]:
					who_sits.append("%s (%s)" % [_who(str(p["delegates"][h])), str(h)])
				_feed("\n" + lab + _tag("CONSEIL", "#7f95ff") + " le conseil de la vallée se réunit : " + ", ".join(who_sits) + "  [color=#6f7896](les autres villageois n'y vont pas)[/color]", [])
			else:
				_feed("\n" + lab + _tag("VEILLÉE", "#7f95ff") + " [b]%s[/b] se réunit" % _scope(str(p.get("scope", ""))).capitalize(), [])
		"narration":
			var season := int(p.get("season", 0))
			var how := "" if str(p.get("source", "")) == "ancien" else "  [color=#6f7896][font_size=11](d'après les faits)[/font_size][/color]"
			narration.append_text("[font=res://fonts/alegreya-latin-700-normal.woff2][font_size=17][color=#e2bd6a]Saison %d[/color][/font_size][/font]%s\n[i]%s[/i]\n\n" % [season, how, _esc(str(p.get("text", "")))])
			_feed(lab + _tag("RÉCIT", "#e2bd6a") + " l'ancien raconte la saison %d  [color=#6f7896](onglet « Récit de l'ancien »)[/color]" % season, [])
		"utterance":
			var sp := str(p.get("speaker", ""))
			var to := str(p.get("to", "tous"))
			var dest := " [color=#6f7896]→ tous[/color]" if to == "tous" else " [color=#7f95ff]→[/color] " + _who(to)
			_feed(lab + "%s%s  [i]« %s »[/i]" % [_who(sp), dest, _esc(str(p.get("text", "")))], [sp, to])
		"proposal":
			var pid := str(p.get("proposal_id", ""))
			proposals[pid] = {"author": str(p.get("author", "")), "quota": float(p.get("quota", 0)), "supporters": [],
				"scope": str(p.get("scope", ""))}
			world.remember_proposal(pid, str(p.get("author", "")))
			_feed(lab + _tag("PROPOSITION", "#f2b23a") + " %s propose [b]%s[/b] : [b]%s t[/b] par pêcheur" % [_who(str(p.get("author", ""))), pid,
				_num(p.get("quota", 0))], [str(p.get("author", ""))])
			_render_rules()
		"support":
			var pid := str(p.get("proposal_id", ""))
			var who := str(p.get("agent", ""))
			for k in proposals:
				proposals[k]["supporters"].erase(who)
			if proposals.has(pid):
				proposals[pid]["supporters"].append(who)
				if who != proposals[pid]["author"]:
					_feed(lab + _tag("SOUTIEN", "#58d08a") + " %s soutient [b]%s[/b]" % [_who(who), pid], [who])
			_render_rules()
		"promise":
			var a = _agent(str(p.get("agent", "")))
			if a:
				var fs := int(p.get("for_season", 0))
				a["promises"] = a["promises"].filter(func(x): return int(x["season"]) != fs)
				a["promises"].append({"season": fs, "amount": float(p.get("amount", 0)), "landed": null, "kept": null})
			_feed(lab + _tag("PROMESSE", "#e7c27a") + " %s promet [b]≤ %s t[/b] pour la saison %d" % [_who(str(p.get("agent", ""))), _num(p.get("amount", 0)),
				int(p.get("for_season", 0))], [str(p.get("agent", ""))])
		"promise_outcome":
			var id := str(p.get("agent", ""))
			var a = _agent(id)
			if a:
				for pr in a["promises"]:
					if int(pr["season"]) == int(p.get("season", 0)):
						pr["landed"] = float(p.get("landed", 0))
						pr["kept"] = bool(p.get("kept", true))
			if not bool(p.get("kept", true)):
				# la vraie prise trahit la promesse ; la vallée, elle, ne le sait que si la déclaration le dit (ou si le mensonge a éclaté)
				var hidden := "  [color=#6f7896](la vallée l'ignore : il a déclaré %s t)[/color]" % _num(p.get("declared", 0)) if bool(p.get("known_kept", false)) else ""
				_feed(lab + _tag("TRAHISON", "#ff6a5c") + " %s avait promis %s t, a pêché [b][color=#ff8a7e]%.1f t[/color][/b]%s" % [_who(id),
					_num(p.get("promised", 0)), float(p.get("landed", 0)), hidden], [id])
		"accusation":
			_feed(lab + _tag("ACCUSATION", "#ff6a5c") + " %s accuse %s d'avoir trop pêché" % [_who(str(p.get("accuser", ""))),
				_who(str(p.get("accused", "")))], [str(p.get("accuser", "")), str(p.get("accused", ""))])
		"norm_adopted":
			norms.append(p)
			_feed(lab + _tag("RÈGLE ADOPTÉE", "#58d08a") + " [b][color=#9ef0bd]%s : %s t par pêcheur dès la saison %d[/color][/b] · %d soutiens" % [
				_scope(str(p.get("scope", ""))), _num(p.get("quota", 0)), int(p.get("effective_season", 0)),
				p.get("supporters", []).size()], p.get("supporters", []))
			_render_rules()
		"assembly_end":
			if p.get("adopted_proposal") == null:
				_feed(lab + _tag("SANS ACCORD", "#8f97b2") + " [color=#8f97b2]fin de veillée (%s), aucune règle adoptée[/color]" % _scope(str(p.get("scope", ""))), [])
			proposals.clear()
			_render_rules()
		"memory_write":
			var a = _agent(str(p.get("agent", "")))
			if a:
				a["memories"].append({"label": last_sim_label, "text": str(p.get("text", "")), "pinned": bool(p.get("pinned", false)),
					"kind": str(p.get("kind", ""))})
				if a["memories"].size() > 60:
					a["memories"].pop_front()
		"decision":
			var a = _agent(str(p.get("agent", "")))
			if a:
				a["last_decision"] = p
				a["last_decision_label"] = last_sim_label
		"incident":
			var id := str(p.get("agent", ""))
			var a = _agent(id)
			if a:
				a["incidents"] = int(a["incidents"]) + 1
			var itype := str(p.get("incident_type", ""))
			if itype == "missed_window":
				# pas une erreur : la fenêtre s'est fermée pendant que l'IA réfléchissait encore
				lost_this_season += 1
				var gone := str(p.get("handled_by", "")).to_upper()
				_feed(lab + _tag(gone, "#f39c4a") + " %s [color=#c9a07a]%s[/color]" % [_who(id), _esc(str(p.get("detail", "")))], [id])
				_update_transport()
			else:
				_feed(lab + _tag("INCIDENT", "#f39c4a") + " [color=#c9a07a]%s · %s → %s[/color]" % [INCIDENT_LABELS.get(itype, itype),
					_who(id), _esc(str(p.get("handled_by", "")))], [id])
		"injection":
			var it := str(p.get("injection_type", ""))
			var prm: Dictionary = p.get("params", {})
			match it:
				"announcement":
					_feed(lab + _tag("RUMEUR", "#ffd166") + " [i]« %s »[/i]  [color=#8f97b2]les IA en tiendront compte pendant deux saisons[/color]" % _esc(str(prm.get("text", ""))), [])
				"drought":
					_feed(lab + _tag("SÉCHERESSE", "#f39c4a") + " le stock du lac est divisé par %s" % _num(1.0 / maxf(float(prm.get("factor", 0.5)), 0.001)), [])
				"set_communication":
					var comms := {"valley": "conseil de la vallée", "hamlet": "par village", "none": "interdite"}
					_feed(lab + _tag("COMMUNICATION", "#ffd166") + " les veillées se tiennent désormais : [b]%s[/b]" % comms.get(str(prm.get("value", "")), str(prm.get("value", ""))), [])
				"set_visibility":
					_feed(lab + _tag("DÉCLARATIONS", "#ffd166") + " les déclarations à l'ancien sont désormais [b]%s[/b]" % ("lues à toute la vallée" if bool(prm.get("value", true)) else "connues du seul village"), [])
				"pause":
					_feed(lab + _tag("PAUSE", "#ffd166") + " la partie est en pause", [])
				"resume":
					_feed(lab + _tag("REPRISE", "#ffd166") + " la partie reprend", [])
				"set_speed":
					var v: Variant = prm.get("value")
					_feed(lab + _tag("VITESSE", "#ffd166") + (" vitesse maximale" if v is String else " vitesse × %s" % _num(v)), [])
				"set_mode":
					_feed(lab + _tag("TEMPS", "#ffd166") + " passage en mode [b]%s[/b] à la saison suivante" % ("asynchrone" if str(prm.get("value")) == "async" else "synchrone"), [])
				"stop":
					_feed(lab + _tag("ARRÊT", "#ff6a5c") + " arrêt de la partie demandé", [])
				_:
					_feed(lab + _tag("INJECTION", "#ffd166") + " [b]%s[/b] %s" % [it, _esc(JSON.stringify(prm))], [])
		"lake_update":
			chart.set_live(float(p.get("stock", 0)) / max(float(run.get("capacity", 1.0)), 0.001))
		"lake_collapsed":
			_feed(lab + _tag("EFFONDREMENT", "#ff6a5c") + " [b]le lac s'effondre[/b]", [])
		"season_end":
			var w: Dictionary = p.get("wealth", {})
			for id in w:
				var a = _agent(str(id))
				if a:
					a["wealth"] = float(w[id])
			var rep: Dictionary = p.get("reputation", {})
			for id in rep:
				var a = _agent(str(id))
				if a:
					a["reputation"] = float(rep[id])
			trust_dirty = true
		"run_end":
			var why := str(p.get("reason", ""))
			if why == "extinction":
				_feed(lab + _tag("LAC À SEC", "#ff6a5c") + " [b]plus un seul poisson : la partie s'arrête[/b]", [])
			var wording := {"extinction": "le lac est à sec", "completed": "toutes les saisons jouées", "stop": "arrêt demandé",
				"collapse": "le lac s'est effondré"}
			_feed("\n[center][color=#f3dca8]Fin du run · %s[/color][/center]" % wording.get(why, why), [])
	if selected != "" and (str(p.get("agent", "")) == selected or str(p.get("speaker", "")) == selected):
		inspector_dirty = true


const KPI_SUB := {"stock": "repeuplement max à 50 %", "norme": "accord × conformité", "promesses": "écart moyen —",
	"accord": "pêcheurs pour la règle", "conformite": "pêcheurs qui la respectent", "cv": "écart-type ÷ moyenne",
	"obsolescence": "lac vu ≠ lac réel", "ecart": "tonnes par pêcheur"}


func _reset_kpis() -> void:
	for k in ind_labels:
		ind_labels[k].text = "—"
	for k in KPI_SUB:
		if ind_sub.has(k):
			ind_sub[k].text = KPI_SUB[k]


func _on_indicator(msg: Dictionary) -> void:
	# un indicateur d'une autre partie (relecture d'un ancien run, service relancé) ne s'affiche jamais dans celle-ci
	if not run.is_empty() and str(msg.get("run_id", "")) != str(run.get("id", "")):
		return
	var p: Dictionary = msg.get("payload", {})
	var v: Dictionary = p.get("values", {})
	ind_labels["stock"].text = "%.0f %%" % (float(v.get("stock_ratio", 0)) * 100.0)
	ind_sub["stock"].text = "%.0f t sur %.0f · repeuplement max à 50 %%" % [float(v.get("stock", 0)), float(run.get("capacity", 0))]
	ind_labels["incidents"].text = str(int(v.get("incidents_total", 0)))
	ind_labels["llm"].text = str(int(v.get("llm_calls", 0)))
	ind_labels["tokens"].text = str(int(v.get("llm_tokens", 0)))
	ind_labels["violations"].text = str(int(v.get("temporal_violations", 0)))
	ind_labels["obsolescence"].text = "%.1f %%" % (float(v.get("mean_staleness_ratio", 0)) * 100.0)
	if str(p.get("trigger", "")) == "season_end":
		ind_labels["norme"].text = "%.2f" % float(v.get("norm_index", 0))
		ind_labels["accord"].text = "%.0f %%" % (float(v.get("norm_agreement", 0)) * 100.0)
		ind_labels["conformite"].text = "%.0f %%" % (float(v.get("norm_compliance", 0)) * 100.0)
		var k: Variant = v.get("promise_kept_rate")
		ind_labels["promesses"].text = "—" if k == null else "%.0f %%" % (float(k) * 100.0)
		ind_labels["ecart"].text = "%+.1f t" % float(v.get("promise_gap_t", 0))
		ind_sub["promesses"].text = "%d tenues sur %d · écart moyen %+.1f t" % [int(v.get("promises_kept", 0)),
			int(v.get("promises", 0)), float(v.get("promise_gap_t", 0))]
		ind_sub["norme"].text = "accord %.0f %% × conformité %.0f %%" % [float(v.get("norm_agreement", 0)) * 100.0,
			float(v.get("norm_compliance", 0)) * 100.0]
		ind_sub["accord"].text = "%d sur %d pêcheurs pour la règle" % [int(v.get("norm_supporters", 0)), int(v.get("fishers", 0))]
		ind_sub["conformite"].text = "%d sur %d la respectent" % [int(v.get("norm_compliers", 0)), int(v.get("norm_concerned", 0))]
		ind_labels["cv"].text = "%.2f" % float(v.get("catch_cv", 0))
		chart.set_season(int(v.get("season", 0)), v)


func _reset(ev: Dictionary) -> void:
	var p: Dictionary = ev.get("payload", {})
	run = {"id": str(ev.get("run_id", "")), "mode": str(p.get("mode", "")), "capacity": float(p.get("lake", {}).get("capacity", 100)),
		"replay": bool(ev.get("replay", false))}
	agents.clear()
	feed_lines.clear()
	proposals.clear()
	norms.clear()
	lost_this_season = 0
	selected = ""
	for a in p.get("agents", []):
		agents[str(a["id"])] = {"info": a, "catches": {}, "promises": [], "memories": [], "last_decision": {},
			"last_decision_label": "", "wealth": float(a.get("wealth", 0)), "incidents": 0,
			"declared": {}, "reputation": 0.5, "trust_from": {}, "lies_found": 0, "banned": false}
	world.reset_world(p.get("agents", []), float(run["capacity"]), float(p.get("season_days", 30.0)), p.get("hamlets", []))
	legend.set_villages(p.get("hamlets", []))
	chart.reset()
	_reset_kpis()
	var sc: Dictionary = p.get("scenario", {})
	lbl_run.text = "%s   ·   mode %s   ·   %d pêcheurs%s" % [run["id"], run["mode"], int(p.get("population", {}).get("fishers", 0)),
		"   ·   REJEU" if run["replay"] else ""]
	for i in comm_opt.item_count:
		if comm_opt.get_item_metadata(i) == str(sc.get("communication", "valley")):
			comm_opt.select(i)
	vis_check.set_pressed_no_signal(bool(sc.get("catches_visible", true)))
	patrol_installed = false              # une nouvelle partie : pas de patrouille tant que le conseil n'en vote pas
	reps.clear()
	lbl_patrol.text = "Patrouille : aucune"
	weather_days = []
	lbl_weather.text = ""
	feed.clear()
	narration.clear()
	narration.append_text("[color=#8f97b2]À la fin de chaque saison, l'ancien raconte ici ce que la vallée a vécu.[/color]\n\n")
	inspector.text = "Cliquez sur un pêcheur pour l'inspecter."
	_render_rules()
	_render_trust()


# ------------------------------------------------------------------ fil des interactions
func _feed(text: String, ids: Array) -> void:
	feed_lines.append({"text": text, "ids": ids})
	if feed_lines.size() > 1500:
		feed_lines = feed_lines.slice(feed_lines.size() - 1200)
		feed_dirty = true
	if catching_up > 0:
		feed_dirty = true
		return
	if feed_only_selected.button_pressed and selected != "" and not ids.has(selected):
		return
	feed.append_text(text + "\n")


func _render_feed() -> void:
	feed.clear()
	var only := feed_only_selected.button_pressed and selected != ""
	var lines := PackedStringArray()
	for l in feed_lines.slice(max(0, feed_lines.size() - 600)):
		if only and not l["ids"].has(selected):
			continue
		lines.append(l["text"])
	feed.append_text("\n".join(lines) + "\n")


func _render_rules() -> void:
	var s := "[color=#f3dca8][b]PROPOSITIONS SUR LA TABLE[/b][/color]\n"
	if proposals.is_empty():
		s += "[color=#8f97b2]aucune[/color]\n"
	for pid in proposals:
		var pr: Dictionary = proposals[pid]
		s += "%s · %s t · par %s · soutiens : %s\n" % [pid, _num(pr["quota"]), _who(pr["author"]),
			", ".join(PackedStringArray(pr["supporters"])) if not pr["supporters"].is_empty() else "aucun"]
	s += "\n[color=#f3dca8][b]RÈGLES ADOPTÉES[/b][/color] [color=#6f7896](historique)[/color]\n"
	if norms.is_empty():
		s += "[color=#8f97b2]aucune[/color]\n"
	for n in norms:
		s += "%s t par pêcheur · %s · dès la saison %d · soutenue par %s\n" % [_num(n.get("quota", 0)), _scope(str(n.get("scope", ""))),
			int(n.get("effective_season", 0)), ", ".join(PackedStringArray(n.get("supporters", [])))]
	rules_view.text = s


## Une jauge en texte : vingt espaces sur fond coloré (la police du projet n'a pas de caractère « bloc »), la part pleine
## colorée selon le niveau de confiance.
static func trust_bar(v: float) -> String:
	var n := clampi(roundi(v * 20.0), 0, 20)
	var col := "#58d08a" if v >= 0.6 else ("#e7c27a" if v >= 0.4 else ("#f39c4a" if v >= 0.25 else "#ff6a5c"))
	var full := ("[bgcolor=%s]%s[/bgcolor]" % [col, " ".repeat(n)]) if n > 0 else ""
	var empty := ("[bgcolor=#3a4058]%s[/bgcolor]" % " ".repeat(20 - n)) if n < 20 else ""
	return "%s%s  [b]%d %%[/b]" % [full, empty, roundi(v * 100.0)]


func _render_trust() -> void:
	var s := "[color=#f3dca8][b]CONFIANCE[/b][/color] [color=#6f7896]· la confiance moyenne que les autres accordent à chacun[/color]\n"
	s += "[color=#8f97b2][font_size=12]La vallée ne connaît que les déclarations faites à l'ancien ; les vraies prises, seuls vous et chaque pêcheur les connaissez.[/font_size][/color]\n\n"
	var ids: Array = agents.keys().filter(func(k): return str(agents[k]["info"].get("role", "")) == "pecheur")
	ids.sort_custom(func(x, y): return float(agents[x]["reputation"]) > float(agents[y]["reputation"]))
	var head := "[color=#6f7896][font_size=11]%s[/font_size][/color]"
	s += "[table=5][cell]%s[/cell][cell]%s[/cell][cell]%s[/cell][cell]%s[/cell][cell]%s[/cell]" % [head % "PÊCHEUR", head % "CONFIANCE",
		head % "PÊCHÉ", head % "DÉCLARÉ", head % "MENSONGES"]
	for id in ids:
		var a: Dictionary = agents[id]
		var landed_txt := "—"
		var said_txt := "—"
		var seasons: Array = a["catches"].keys()
		if not seasons.is_empty():
			seasons.sort_custom(func(x, y): return int(x) < int(y))
			var k: String = seasons[-1]                  # la dernière saison où il a pêché
			var landed := float(a["catches"][k])
			landed_txt = "S%s  [b]%s t[/b]" % [k, _num(landed)]
			if a["declared"].has(k):
				var said := float(a["declared"][k])
				said_txt = ("[color=#ff8a7e][b]%s t[/b] (ment)[/color]" % _num(said)) if landed - said > 0.05 else ("%s t" % _num(said))
		var lies := int(a["lies_found"])
		var who := _who(id) + (" [color=#ff6a5c][font_size=10]INTERDIT[/font_size][/color]" if bool(a["banned"]) else "")
		s += "[cell]%s  [/cell][cell]%s  [/cell][cell]%s  [/cell][cell]%s  [/cell][cell]%s[/cell]" % [who, trust_bar(float(a["reputation"])),
			landed_txt, said_txt, ("[color=#ff6a5c]%d[/color]" % lies) if lies > 0 else "—"]
	s += "[/table]"
	trust_view.text = s


# ------------------------------------------------------------------ inspecteur (D2)
func _select(id: String) -> void:
	selected = id
	world.selected = id
	inspector_dirty = true
	feed_dirty = feed_only_selected.button_pressed
	tabs.current_tab = inspector.get_index()


func _render_inspector() -> void:
	var a = _agent(selected)
	if a == null:
		return
	var info: Dictionary = a["info"]
	var hc := Art.agent_color(info).lightened(0.2).to_html(false)
	var s := "[font=res://fonts/alegreya-latin-700-normal.woff2][font_size=22][color=#%s]%s[/color][/font_size][/font]  [color=#6f7896]%s[/color]\n" % [hc, _esc(str(info.get("name", selected))), selected]
	var kind := "agent à règles" if str(info.get("kind", "")) == "rule" else "agent LLM · modèle %s" % str(info.get("tier", ""))
	var boat := "" if str(info.get("boat", "")) == "" else " · " + str(info.get("boat", ""))
	var seat := " · [color=#e2bd6a]élu au conseil[/color]" if reps.get(str(info.get("hamlet", ""))) == selected else ""
	s += "%s · village %s · %s · %d ans de pêche%s%s\n" % [str(info.get("archetype_label", "")), str(info.get("hamlet", "")), kind,
		int(info.get("experience", 0)), boat, seat]
	if str(info.get("role", "")) != "ancien":
		s += "Avoir : [b]%.0f écus[/b] · dette : %.0f écus/saison · incidents : %d\n" % [float(a["wealth"]),
			float(info.get("debt_payment", 0)), int(a["incidents"])]
		var cs := PackedStringArray()
		for k in a["catches"]:
			var landed := float(a["catches"][k])
			var said := float(a["declared"].get(k, landed))
			cs.append("S%s %.1f t" % [k, landed] + (" [color=#ff8a7e](déclaré %.1f)[/color]" % said if landed - said > 0.05 else ""))
		s += "Prises : %s\n" % (", ".join(cs) if not cs.is_empty() else "—")
		var low := PackedStringArray()
		var tf: Dictionary = a["trust_from"]
		s += "Confiance des autres : %s%s\n" % [trust_bar(float(a["reputation"])),
			"  [color=#ff6a5c][b]interdit de pêche[/b] jusqu'à 50 %[/color]" if bool(a["banned"]) else ""]
		for o in tf:
			if float(tf[o]) < 0.4:
				low.append(_who(str(o)))
		if not low.is_empty():
			s += "Se méfient de lui : %s\n" % ", ".join(low)
		var ps := PackedStringArray()
		for pr in a["promises"]:
			var res := "en attente"
			if pr["kept"] != null:
				res = ("[color=#58d08a]tenue[/color]" if pr["kept"] else "[color=#ff6a5c]trahie[/color]") + " (%.1f t)" % float(pr["landed"])
			ps.append("S%d ≤ %s t : %s" % [int(pr["season"]), _num(pr["amount"]), res])
		s += "Promesses : %s\n" % (" · ".join(ps) if not ps.is_empty() else "—")
	var d: Dictionary = a["last_decision"]
	if not d.is_empty():
		s += "\n[color=#f3dca8][b]DERNIÈRE DÉCISION[/b][/color] (%s, %s)\n" % [str(a["last_decision_label"]), "prise" if str(d.get("decision_type", "")) == "catch" else "parole"]
		if d.get("value") != null:
			s += "Valeur : [b]%s t[/b] · " % _num(d.get("value"))
		s += "information connue jusqu'à t = %.2f j" % float(d.get("info_horizon", 0))
		if bool(d.get("fallback", false)):
			s += " · [color=#f39c4a]repli sur règle[/color]"
		if bool(d.get("out_of_role", false)):
			s += " · [color=#ff6a5c]sortie de rôle[/color]"
		s += "\n"
		if d.get("rule") != null:
			s += "Règle appliquée : %s\n" % _esc(str(d.get("rule")))
		if str(info.get("kind", "")) != "rule":
			s += "Justification : [i]%s[/i]\n" % _esc(str(d.get("justification", "")))
		var obs: Dictionary = d.get("observed", {})
		s += "Stock estimé : %s t (réel : %s t) · quota connu : %s\n" % [_num(obs.get("stock_estimate", 0)), _num(obs.get("stock_true", 0)),
			"aucun" if obs.get("quota") == null else _num(obs.get("quota")) + " t"]
		s += "[color=#f3dca8][b]RETROUVÉ POUR DÉCIDER[/b][/color]\n"
		for r in d.get("retrieved", []):
			var tag: String = str({"pinned": "[engagement]", "memory": "[souvenir]", "corpus": "[archive]",
				"rumor": "[rumeur]"}.get(str(r.get("source", "")), ""))
			s += "  · [color=#9ba1ba]%s[/color] %s\n" % [tag, _esc(str(r.get("text", "")))]
	s += "\n[color=#f3dca8][b]MÉMOIRE[/b][/color] [color=#6f7896](plus récents d'abord)[/color]\n"
	var mem: Array = a["memories"]
	for i in range(mem.size() - 1, max(-1, mem.size() - 26), -1):
		var m: Dictionary = mem[i]
		s += "  %s[color=#9ba1ba]%s[/color] %s\n" % ["[color=#d9b56c]épinglé[/color] " if m["pinned"] else "", m["label"], _esc(m["text"])]
	inspector.text = s


# ------------------------------------------------------------------ utilitaires
func _agent(id: String) -> Variant:
	return agents.get(id)


func _who(id: String) -> String:
	if id == "tous":
		return "tous"
	var a = _agent(id)
	if a == null:
		return id
	var col := Art.agent_color(a["info"]).lightened(0.15)
	return "[b][color=#%s]%s[/color][/b] [color=#6f7896]%s[/color]" % [col.to_html(false), str(a["info"].get("name", id)).split(" ")[0], id]


func _tag(text: String, hex: String) -> String:
	return "[bgcolor=%s33][color=%s][font_size=10][b] %s [/b][/font_size][/color][/bgcolor]" % [hex, hex, text]


## Le temps d'aujourd'hui sur le lac (tant que la pêche est ouverte), à côté de la patrouille.
func _show_weather() -> void:
	var day := int(floor(world.sim_time - float(weather_season - 1) * world.season_days))
	var txt := ""
	var col := Art.MUTED
	if weather_season > 0 and day >= 0 and day < weather_days.size():
		var w := str(weather_days[day])
		txt = "Temps : " + w
		col = Art.ACCUSE if w == "tempête" else (Art.PROPOSAL if w == "agité" else Art.MUTED)
	if lbl_weather.text != txt:
		lbl_weather.text = txt
		lbl_weather.add_theme_color_override("font_color", col)


## Le temps de la saison, jour par jour : « Temps de la pêche : 7 calmes · 9 ordinaires · 3 agités · 1 de tempête ».
func _sky_text(days: Array) -> String:
	var n := {}
	for w in days:
		n[str(w)] = int(n.get(str(w), 0)) + 1
	var parts := PackedStringArray()
	for w in [["calme", "calmes"], ["ordinaire", "ordinaires"], ["agité", "agités"], ["tempête", "de tempête"]]:
		if n.has(w[0]):
			parts.append("%d %s" % [n[w[0]], w[1]])
	return "Temps de la pêche : " + " · ".join(parts)


## Le mauvais temps qu'ont essuyé ses sorties : « ; 2 sorties dans la tempête » (rien si le temps était clément).
func _weather_note(outings: Array) -> String:
	var storm := 0
	var rough := 0
	for o in outings:
		match str(o.get("weather", "")):
			"tempête":
				storm += 1
			"agité":
				rough += 1
	if storm > 0:
		return " ; %d sortie%s dans la tempête" % [storm, "s" if storm > 1 else ""]
	if rough > 0:
		return " ; %d par temps agité" % rough
	return ""


func _day_word(f: float) -> String:
	return "très mauvaise" if f < 0.6 else ("mauvaise" if f < 0.85 else ("ordinaire" if f < 1.15 else ("bonne" if f < 1.4 else "excellente")))


func _scope(s: String) -> String:
	return "toute la vallée" if s == "valley" else s.replace("hamlet:", "village de ")


func _num(v: Variant) -> String:
	var f := float(v)
	return str(int(f)) if is_equal_approx(f, round(f)) else "%.1f" % f


func _esc(s: String) -> String:
	return s.replace("[", "[lb]")


var _acc := 0.0


func _process(delta: float) -> void:
	lbl_clock.text = last_sim_label
	_show_weather()
	_acc += delta
	if _acc >= 0.2:
		_acc = 0.0
		if feed_dirty and catching_up == 0:
			feed_dirty = false
			_render_feed()
		if inspector_dirty and catching_up == 0:
			inspector_dirty = false
			_render_inspector()
		if trust_dirty and catching_up == 0:
			trust_dirty = false
			_render_trust()
			inspector_dirty = selected != ""
		# Le moteur répète son état toutes les 2 s (y compris pendant qu'il charge un modèle) : muet depuis 8 s, il ne répond
		# plus. On ne conclut jamais tant que des messages attendent d'être lus (à-coup d'affichage de Godot lui-même).
		# En préparation, le moteur charge peut-être un modèle (de 20 s à plus d'une minute) : on lui laisse 150 s.
		var silence_limit := 150000 if engine_state == "starting" else 8000
		if engine_seen_ms > 0 and not engine.is_empty() and ws.pending() == 0 \
				and Time.get_ticks_msec() - engine_seen_ms > silence_limit:
			engine = {}
			engine_state = ""
			menu.set_engine("", false)
			_update_transport()
		if stop_armed_ms > 0 and Time.get_ticks_msec() - stop_armed_ms >= 3000:
			stop_armed_ms = 0
			_update_transport()
		if end_overlay.visible:
			_refresh_end_text()
	var el := (Time.get_ticks_msec() - t0_ms) / 1000.0
	if autostart >= 0.0 and not catalog.is_empty() and (engine_state == "idle" or engine_state == "ended"):
		if autostart_at < 0.0:
			autostart_at = el + autostart
			if not menu.visible:
				menu.open(true)          # après une partie terminée : le chemin « Nouvelle partie »
		elif el >= autostart_at:
			autostart = -1.0
			menu._on_start()
	if menu_shot != "" and menu.visible and not catalog.is_empty() and el > 3.0:
		var shot := menu_shot
		menu_shot = ""
		await get_tree().process_frame
		await get_tree().process_frame
		get_viewport().get_texture().get_image().save_png(shot)
		print("MENUSHOT ", shot)
	if not shots.is_empty() and el > float(shots[0]):
		var sec: float = shots.pop_front()
		get_viewport().get_texture().get_image().save_png("%s/shot_%05.1f.png" % [shot_dir, sec])
		print("SHOT %.1f %s" % [sec, last_sim_label])
		if shots.is_empty():
			get_tree().quit()
	if selftest > 0.0 and el > selftest:
		selftest = -1.0
		_selftest_report()
		if shot_path != "":
			await get_tree().process_frame
			await get_tree().process_frame
			get_viewport().get_texture().get_image().save_png(shot_path)
		get_tree().quit()


func _selftest_report() -> void:
	var first := ""
	for id in agents:
		if str(agents[id]["info"].get("role", "")) == "pecheur":
			first = id
			break
	print("SELFTEST events=%d indicators=%d agents=%d feed=%d norms=%d clock=%s run=%s" % [n_events, n_indicators,
		agents.size(), feed_lines.size(), norms.size(), last_sim_label, str(run.get("id", ""))])
	if first != "":
		_select(first)
		_render_inspector()
		print("SELFTEST inspector_chars=%d memories=%d" % [inspector.get_parsed_text().length(), agents[first]["memories"].size()])
	print("SELFTEST stock=%s norme=%s promesses=%s" % [ind_labels["stock"].text, ind_labels["norme"].text,
		ind_labels["promesses"].text])
	print("SELFTEST layout main=%s menu=%s sheet=%s menu_visible=%s transport=%s" % [size, menu.size, menu.sheet.size,
		menu.visible, transport.visible])
	print("SELFTEST send=%s" % str(ws.send({"type": "announcement", "text": "test depuis Godot"})))
