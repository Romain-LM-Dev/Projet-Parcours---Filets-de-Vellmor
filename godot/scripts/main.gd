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
var feed_only_selected: CheckBox
var inspector: RichTextLabel
var rules_view: RichTextLabel
var tabs: TabContainer
var comm_opt: OptionButton
var vis_check: CheckButton
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
	for item in [["toute la vallée", "valley"], ["par hameau", "hamlet"], ["interdite", "none"]]:
		comm_opt.add_item(item[0])
		comm_opt.set_item_metadata(comm_opt.item_count - 1, item[1])
	comm_opt.item_selected.connect(func(i: int) -> void:
		_send({"type": "set_communication", "value": comm_opt.get_item_metadata(i)}))
	bottom.add_child(comm_opt)
	vis_check = CheckButton.new()
	vis_check.text = "Prises visibles"
	vis_check.button_pressed = true
	vis_check.toggled.connect(func(on: bool) -> void: _send({"type": "set_visibility", "value": on}))
	bottom.add_child(vis_check)
	rumor_edit = LineEdit.new()
	rumor_edit.placeholder_text = "Faire courir une rumeur dans la vallée…"
	rumor_edit.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	rumor_edit.text_submitted.connect(func(_t: String) -> void: _rumor())
	bottom.add_child(rumor_edit)
	var rumor_btn := Button.new()
	rumor_btn.text = "Diffuser"
	rumor_btn.pressed.connect(_rumor)
	bottom.add_child(rumor_btn)
	bar_v.add_child(Legend.new())

	# --- menu de démarrage, par-dessus tout le reste
	menu = StartMenu.new()
	add_child(menu)
	menu.start_requested.connect(_on_menu_start)
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
			_feed("\n[center][font=res://fonts/alegreya-latin-700-normal.woff2][font_size=17][color=#f3dca8]Saison %d[/color][/font_size][/font]  [color=#8f97b2]· le lac compte %.1f t%s[/color][/center]" % [int(ev.get("season", 0)), float(p.get("stock", 0)), md], [])
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
			_feed(lab + _tag("PÊCHE", "#7fd0e8") + " %s ramène [b]%.1f t[/b]%s" % [_who(id), float(p.get("landed", 0)), gap], [id])
		"sale":
			var a = _agent(str(p.get("agent", "")))
			if a:
				a["wealth"] = float(p.get("wealth", 0))
		"assembly_start":
			_feed("\n" + lab + _tag("VEILLÉE", "#7f95ff") + " [b]%s[/b] se réunit" % _scope(str(p.get("scope", ""))).capitalize(), [])
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
				_feed(lab + _tag("TRAHISON", "#ff6a5c") + " %s avait promis %s t, a pêché [b][color=#ff8a7e]%.1f t[/color][/b]" % [_who(id),
					_num(p.get("promised", 0)), float(p.get("landed", 0))], [id])
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
					var comms := {"valley": "toute la vallée", "hamlet": "par hameau", "none": "interdite"}
					_feed(lab + _tag("COMMUNICATION", "#ffd166") + " les veillées se tiennent désormais : [b]%s[/b]" % comms.get(str(prm.get("value", "")), str(prm.get("value", ""))), [])
				"set_visibility":
					_feed(lab + _tag("PRISES", "#ffd166") + " les prises sont désormais [b]%s[/b]" % ("connues de tous" if bool(prm.get("value", true)) else "cachées"), [])
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
			"last_decision_label": "", "wealth": float(a.get("wealth", 0)), "incidents": 0}
	world.reset_world(p.get("agents", []), float(run["capacity"]), float(p.get("season_days", 30.0)))
	chart.reset()
	_reset_kpis()
	var sc: Dictionary = p.get("scenario", {})
	lbl_run.text = "%s   ·   mode %s   ·   %d pêcheurs%s" % [run["id"], run["mode"], int(p.get("population", {}).get("fishers", 0)),
		"   ·   REJEU" if run["replay"] else ""]
	for i in comm_opt.item_count:
		if comm_opt.get_item_metadata(i) == str(sc.get("communication", "valley")):
			comm_opt.select(i)
	vis_check.set_pressed_no_signal(bool(sc.get("catches_visible", true)))
	feed.clear()
	inspector.text = "Cliquez sur un pêcheur pour l'inspecter."
	_render_rules()


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


# ------------------------------------------------------------------ inspecteur (D2)
func _select(id: String) -> void:
	selected = id
	world.selected = id
	inspector_dirty = true
	feed_dirty = feed_only_selected.button_pressed
	tabs.current_tab = 1


func _render_inspector() -> void:
	var a = _agent(selected)
	if a == null:
		return
	var info: Dictionary = a["info"]
	var hc := Art.arch_color(str(info.get("archetype", ""))).lightened(0.2).to_html(false)
	var s := "[font=res://fonts/alegreya-latin-700-normal.woff2][font_size=22][color=#%s]%s[/color][/font_size][/font]  [color=#6f7896]%s[/color]\n" % [hc, _esc(str(info.get("name", selected))), selected]
	var kind := "agent à règles" if str(info.get("kind", "")) == "rule" else "agent LLM · modèle %s" % str(info.get("tier", ""))
	s += "%s · hameau %s · %s · %d ans de pêche\n" % [str(info.get("archetype_label", "")), str(info.get("hamlet", "")), kind,
		int(info.get("experience", 0))]
	if str(info.get("role", "")) != "ancien":
		s += "Avoir : [b]%.0f écus[/b] · dette : %.0f écus/saison · incidents : %d\n" % [float(a["wealth"]),
			float(info.get("debt_payment", 0)), int(a["incidents"])]
		var cs := PackedStringArray()
		for k in a["catches"]:
			cs.append("S%s %.1f t" % [k, float(a["catches"][k])])
		s += "Prises : %s\n" % (", ".join(cs) if not cs.is_empty() else "—")
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
	var col := Art.arch_color(str(a["info"].get("archetype", ""))).lightened(0.15)
	return "[b][color=#%s]%s[/color][/b] [color=#6f7896]%s[/color]" % [col.to_html(false), str(a["info"].get("name", id)).split(" ")[0], id]


func _tag(text: String, hex: String) -> String:
	return "[bgcolor=%s33][color=%s][font_size=10][b] %s [/b][/font_size][/color][/bgcolor]" % [hex, hex, text]


func _scope(s: String) -> String:
	return "toute la vallée" if s == "valley" else s.replace("hamlet:", "hameau de ")


func _num(v: Variant) -> String:
	var f := float(v)
	return str(int(f)) if is_equal_approx(f, round(f)) else "%.1f" % f


func _esc(s: String) -> String:
	return s.replace("[", "[lb]")


var _acc := 0.0


func _process(delta: float) -> void:
	lbl_clock.text = last_sim_label
	_acc += delta
	if _acc >= 0.2:
		_acc = 0.0
		if feed_dirty and catching_up == 0:
			feed_dirty = false
			_render_feed()
		if inspector_dirty and catching_up == 0:
			inspector_dirty = false
			_render_inspector()
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
