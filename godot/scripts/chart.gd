## Courbes par saison : stock / capacité (aire bleue), indice de norme partagée (or),
## part des promesses tenues (vert). Pointillés : moitié du lac, là où il se repeuple le plus vite.
extends Control

var stock: Array = []
var norm: Array = []
var kept: Array = []
var live_stock := -1.0
var lakes: Dictionary = {}      # (plusieurs lacs) nom -> sa part de capacité par saison

const C_LAKES := [Color("#4fb3d9"), Color("#8f8cff"), Color("#3fd0c9"), Color("#d98cf2")]

const C_STOCK := Color("#4fb3d9")
const C_NORM := Color("#f2b23a")
const C_KEPT := Color("#58d08a")


func reset() -> void:
	stock.clear()
	norm.clear()
	kept.clear()
	lakes.clear()
	live_stock = -1.0
	queue_redraw()


## Une valeur par saison, rangée à sa place : un indicateur reçu deux fois (service relancé, rejeu) remplace
## le précédent au lieu de s'ajouter à la courbe.
func set_season(season: int, v: Dictionary) -> void:
	var i := maxi(season, 1) - 1
	while stock.size() <= i:
		stock.append(-1.0)
		norm.append(-1.0)
		kept.append(-1.0)
	stock[i] = float(v.get("stock_ratio", 0.0))
	var lv: Dictionary = v.get("lakes", {})
	for n in lv:
		if not lakes.has(n):
			lakes[n] = []
		while lakes[n].size() <= i:
			lakes[n].append(-1.0)
		lakes[n][i] = float(lv[n].get("stock_ratio", 0.0))
	norm[i] = float(v.get("norm_index", 0.0))
	var k: Variant = v.get("promise_kept_rate")
	kept[i] = -1.0 if k == null else float(k)
	queue_redraw()


func set_live(ratio: float) -> void:
	live_stock = ratio
	queue_redraw()


func _draw() -> void:
	var f := Art.font("ui")
	var fb := Art.font("ui_bold")
	var r := Rect2(Vector2(34, 30), size - Vector2(46, 52))
	var lx := 8.0
	var legend: Array = [["stock du lac", C_STOCK]] if lakes.is_empty() else []
	var li := 0
	for n in lakes:
		legend.append([str(n), C_LAKES[li % C_LAKES.size()]])
		li += 1
	legend += [["indice de norme", C_NORM], ["promesses tenues", C_KEPT]]
	for item in legend:
		draw_rect(Rect2(Vector2(lx, 9), Vector2(10, 10)), item[1], true)
		draw_string(fb, Vector2(lx + 15, 18), item[0], HORIZONTAL_ALIGNMENT_LEFT, -1, 11, Art.MUTED)
		lx += 30 + fb.get_string_size(item[0], HORIZONTAL_ALIGNMENT_LEFT, -1, 11).x
	for g in [0.0, 0.5, 1.0]:
		var y: float = r.position.y + r.size.y * (1.0 - g)
		draw_line(Vector2(r.position.x, y), Vector2(r.end.x, y), Color(1, 1, 1, 0.06), 1.0)
		draw_string(f, Vector2(2, y + 4), "%d%%" % int(g * 100), HORIZONTAL_ALIGNMENT_RIGHT, 28, 10, Art.MUTED)
	var ymid := r.position.y + r.size.y * 0.5
	draw_dashed_line(Vector2(r.position.x, ymid), Vector2(r.end.x, ymid), Color(1, 1, 1, 0.28), 1.0, 5.0)
	var n: int = max(stock.size() + 1, 6)
	# aire du stock
	var pts := _points(stock, r, n)
	if pts.size() >= 2:
		var poly := PackedVector2Array(pts)
		poly.append(Vector2(pts[pts.size() - 1].x, r.end.y))
		poly.append(Vector2(pts[0].x, r.end.y))
		draw_colored_polygon(poly, Color(C_STOCK, 0.16))
	if lakes.is_empty():
		_series(stock, r, n, C_STOCK, 2.5)
	li = 0
	for name in lakes:
		_series(lakes[name], r, n, C_LAKES[li % C_LAKES.size()], 2.2)
		li += 1
	_series(norm, r, n, C_NORM, 2.0)
	_series(kept, r, n, C_KEPT, 2.0)
	if live_stock >= 0.0 and lakes.is_empty():
		var x: float = r.position.x + r.size.x * float(stock.size()) / float(n - 1)
		var y: float = r.position.y + r.size.y * (1.0 - clamp(live_stock, 0.0, 1.0))
		draw_circle(Vector2(x, y), 6.0, Color(C_STOCK, 0.25))
		draw_circle(Vector2(x, y), 3.5, C_STOCK)
	for i in max(stock.size(), 1):
		var x: float = r.position.x + r.size.x * float(i) / float(n - 1)
		draw_string(f, Vector2(x - 12, size.y - 6), "S%d" % (i + 1), HORIZONTAL_ALIGNMENT_CENTER, 24, 10, Art.MUTED)


func _points(vals: Array, r: Rect2, n: int) -> PackedVector2Array:
	var pts := PackedVector2Array()
	for i in vals.size():
		var v: float = vals[i]
		if v < 0.0:
			continue
		pts.append(Vector2(r.position.x + r.size.x * float(i) / float(n - 1), r.position.y + r.size.y * (1.0 - clamp(v, 0.0, 1.0))))
	return pts


func _series(vals: Array, r: Rect2, n: int, col: Color, w: float) -> void:
	var pts := _points(vals, r, n)
	if pts.size() >= 2:
		draw_polyline(pts, col, w, true)
	for q in pts:
		draw_circle(q, 3.6, Art.PANEL)
		draw_circle(q, 2.6, col)
