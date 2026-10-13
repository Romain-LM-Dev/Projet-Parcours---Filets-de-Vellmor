## Aperçu de la vallée dans le menu de démarrage : les hameaux, le lac et les pêcheurs tels qu'ils seront placés.
## Un pêcheur se glisse d'un hameau à l'autre ; le clic le sélectionne. Mêmes pions que dans le jeu (Art.draw_token).
extends Control

const WV := preload("res://scripts/world_view.gd")

signal token_selected(index: int)
signal token_moved(index: int, hamlet: String)

var fishers: Array = []
var elder_on := true
var elder_kind := "llm"
var selected := -1
var large_min := 15

var _hover := -1
var _drag := -1
var _drag_pos := Vector2.ZERO
var _drag_target := ""
var _t := 0.0


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_STOP
	clip_contents = true
	custom_minimum_size = Vector2(300, 250)


func set_data(list: Array, elder: bool, elder_k: String, sel: int, large: int) -> void:
	fishers = list
	elder_on = elder
	elder_kind = elder_k
	selected = sel
	large_min = large
	queue_redraw()


func _process(delta: float) -> void:
	if is_visible_in_tree():
		_t += delta
		queue_redraw()


func _px(n: Vector2) -> Vector2:
	return Vector2(n.x * size.x, n.y * size.y)


func _tier_of(f: Dictionary) -> String:
	if str(f.get("kind", "llm")) == "rule":
		return ""
	var t := str(f.get("tier", "auto"))
	if t == "grand" or t == "petit":
		return t
	return "grand" if int(f.get("experience", 0)) >= large_min else "petit"


## Position (en pixels) de chaque pêcheur : une couronne autour de son hameau, deux au-delà de six.
func token_positions() -> Array:
	var per := {}
	for f in fishers:
		per[str(f["hamlet"])] = int(per.get(str(f["hamlet"]), 0)) + 1
	var seen := {}
	var out: Array = []
	var base := minf(size.x * 0.062, 30.0)
	for f in fishers:
		var h := str(f["hamlet"])
		var k: int = seen.get(h, 0)
		seen[h] = k + 1
		var n: int = per[h]
		var inner: int = mini(n, 6)
		var ring := 1.0
		var slot := k
		var count := inner
		if k >= 6:
			ring = 1.9
			slot = k - 6
			count = n - 6
		var ang := -PI / 2.0 + TAU * float(slot) / float(maxi(count, 1)) + (0.5 if ring == 1.0 else 0.25)
		out.append(_px(WV.HAMLET_POS[h]) + Vector2(cos(ang), sin(ang)) * base * ring)
	return out


func _pick(pos: Vector2) -> int:
	var best := -1
	var bd := 17.0
	var pts := token_positions()
	for i in pts.size():
		var d: float = pts[i].distance_to(pos)
		if d < bd:
			bd = d
			best = i
	return best


func _nearest_hamlet(pos: Vector2) -> String:
	var best := ""
	var bd := INF
	for h in WV.HAMLET_POS:
		var d: float = _px(WV.HAMLET_POS[h]).distance_to(pos)
		if d < bd:
			bd = d
			best = str(h)
	return best


func _gui_input(event: InputEvent) -> void:
	var mm := event as InputEventMouseMotion
	if mm:
		if _drag >= 0:
			_drag_pos = mm.position
			_drag_target = _nearest_hamlet(mm.position)
		else:
			var h := _pick(mm.position)
			if h != _hover:
				_hover = h
				mouse_default_cursor_shape = Control.CURSOR_DRAG if h >= 0 else Control.CURSOR_ARROW
				tooltip_text = "" if h < 0 else "%s — %s\nGlissez pour changer de hameau" % [str(fishers[h]["first_name"]),
					str(fishers[h]["archetype"]).replace("_", " ")]
		return
	var mb := event as InputEventMouseButton
	if mb and mb.button_index == MOUSE_BUTTON_LEFT:
		if mb.pressed:
			var i := _pick(mb.position)
			if i >= 0:
				_drag = i
				_drag_pos = mb.position
				_drag_target = str(fishers[i]["hamlet"])
				token_selected.emit(i)
		elif _drag >= 0:
			var i := _drag
			var target := _nearest_hamlet(mb.position)
			_drag = -1
			if target != "" and target != str(fishers[i]["hamlet"]) and Rect2(Vector2.ZERO, size).has_point(mb.position):
				token_moved.emit(i, target)


func _draw() -> void:
	var f := Art.font("ui_bold")
	var fr := Art.font("ui")
	Art.box(Color("#2c4a2a"), 12, Color(1, 1, 1, 0.1), 1).draw(get_canvas_item(), Rect2(Vector2.ZERO, size))
	# lac
	var lake := PackedVector2Array()
	for i in 64:
		var th := TAU * float(i) / 64.0
		lake.append(_px(WV.LAKE_C + Vector2(cos(th), sin(th)) * WV.LAKE_R * WV.lake_shape(th)))
	draw_colored_polygon(lake, Color("#2d6f86"))
	draw_polyline(lake + PackedVector2Array([lake[0]]), Color("#7fc4d6", 0.55), 2.0, true)
	draw_string(Art.font("title_italic"), _px(WV.LAKE_C) + Vector2(-44, 5), "Lac de Vellmor", HORIZONTAL_ALIGNMENT_CENTER, 88, 13,
		Color(1, 1, 1, 0.55))
	# hameaux
	var counts := {}
	for fi in fishers:
		counts[str(fi["hamlet"])] = int(counts.get(str(fi["hamlet"]), 0)) + 1
	for h in WV.HAMLET_POS:
		var c := _px(WV.HAMLET_POS[h])
		var target := _drag >= 0 and _drag_target == str(h)
		_ellipse(c, Vector2(size.x * 0.115, size.y * 0.115), Color("#c4a978", 0.9) if not target else Color("#e2c889"))
		if target:
			draw_arc(c, size.x * 0.125, 0, TAU, 40, Color(Art.PROPOSAL, 0.9), 2.5, true)
		var n: int = counts.get(str(h), 0)
		var label := "%s · %d" % [str(h), n]
		var w := f.get_string_size(label, HORIZONTAL_ALIGNMENT_LEFT, -1, 12).x + 14
		var r := Rect2(c + Vector2(-w / 2.0, -size.y * 0.115 - 22), Vector2(w, 18))
		Art.box(Color(0.08, 0.06, 0.04, 0.75), 6).draw(get_canvas_item(), r)
		draw_string(f, r.position + Vector2(7, 13), label, HORIZONTAL_ALIGNMENT_LEFT, -1, 12, Color("#f3e3bd"))
	# l'ancien
	if elder_on:
		var ep := _px(WV.ELDER_POS)
		draw_rect(Rect2(ep + Vector2(-17, -12), Vector2(34, 22)), Color("#7a4b34"), true)
		draw_rect(Rect2(ep + Vector2(-17, -12), Vector2(34, 6)), Color("#9a6a4c"), true)
		Art.draw_token(self, ep + Vector2(0, 20), {"role": "ancien", "archetype": "ancien", "kind": elder_kind,
			"tier": "grand", "name": "O"}, 0.8)
		draw_string(fr, ep + Vector2(-40, 44), "l'ancien", HORIZONTAL_ALIGNMENT_CENTER, 80, 11, Color("#f3e3bd", 0.8))
	# pêcheurs
	var pts := token_positions()
	for i in pts.size():
		if i == _drag:
			continue
		_token(i, pts[i], i == selected)
	if _drag >= 0:
		_token(_drag, _drag_pos, true, 0.9)
	if fishers.is_empty():
		draw_string(fr, Vector2(0, size.y * 0.5), "aucun pêcheur", HORIZONTAL_ALIGNMENT_CENTER, size.x, 14, Art.MUTED)


func _token(i: int, p: Vector2, sel: bool, alpha: float = 1.0) -> void:
	var fi: Dictionary = fishers[i]
	var info := {"role": "pecheur", "archetype": fi["archetype"], "kind": fi["kind"], "tier": _tier_of(fi),
		"name": str(fi["first_name"])}
	Art.draw_token(self, p, info, 0.82, alpha, sel, _t)
	if sel or i == _hover:
		var nm := str(fi["first_name"])
		var fb := Art.font("ui_bold")
		var tw := fb.get_string_size(nm, HORIZONTAL_ALIGNMENT_LEFT, -1, 11).x + 10
		var lr := Rect2(p + Vector2(-tw / 2.0, 14), Vector2(tw, 17))
		Art.box(Color(0.05, 0.07, 0.12, 0.88), 8).draw(get_canvas_item(), lr)
		draw_string(fb, lr.position + Vector2(5, 12.5), nm, HORIZONTAL_ALIGNMENT_LEFT, -1, 11, Color.WHITE)


func _ellipse(c: Vector2, r: Vector2, col: Color, n: int = 28) -> void:
	var pts := PackedVector2Array()
	for i in n:
		var a := TAU * float(i) / float(n)
		pts.append(c + Vector2(cos(a) * r.x, sin(a) * r.y))
	draw_colored_polygon(pts, col)
