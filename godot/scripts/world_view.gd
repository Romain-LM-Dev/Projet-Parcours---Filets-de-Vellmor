## Vue de la vallée de Vellmor.
##
## Calques (du fond vers l'avant) :
##   terrain  — shader : prairie, grève, lac animé (couleur et herbiers selon le stock)
##   decor    — statique : chemins, places, pontons, roseaux, arbres, maisons
##   under    — poissons (leur nombre suit le stock), sillages, éclaboussures
##   shade    — lumière du jour : aube, crépuscule, nuit (la veillée se tient le soir)
##   lights   — lumières additives : fenêtres, feux, lanternes, lucioles, reflet de lune
##   over     — salle de la veillée, interactions, pions, bulles, bandeaux, HUD
##
## Les interactions restent au-dessus de la nuit : la lisibilité passe avant l'ambiance.
##   parole → courbe bleue + messager vers le destinataire (onde si « à tous ») + bulle
##   proposition → pastille dorée sur l'auteur ; soutien → courbe verte vers l'auteur
##   accusation → courbe rouge pulsée ; promesse tenue/trahie → étiquette au bilan
extends Control

signal agent_clicked(agent_id: String)

const DEFAULT_HAMLETS := ["Ostrel", "Bramois", "Tilque", "Hennad"]
## Les emplacements possibles des villages autour du lac (normalisés), et ceux que l'on prend selon leur nombre : les quatre coins
## pour la vallée de base, puis les flancs, puis le bas. Le haut au centre reste à l'ancien, le bas au centre à la jauge du lac.
const SLOTS := {
	"NW": Vector2(0.14, 0.25), "NE": Vector2(0.86, 0.25), "SE": Vector2(0.86, 0.84), "SW": Vector2(0.14, 0.84),
	"W": Vector2(0.08, 0.52), "E": Vector2(0.92, 0.52), "BL": Vector2(0.30, 0.89), "BR": Vector2(0.70, 0.89),
}
const LAYOUTS := {
	1: ["SW"], 2: ["NW", "SE"], 3: ["NW", "E", "SW"], 4: ["NW", "NE", "SE", "SW"], 5: ["NW", "NE", "SE", "SW", "W"],
	6: ["NW", "NE", "SE", "SW", "W", "E"], 7: ["NW", "NE", "SE", "SW", "W", "E", "BL"],
	8: ["NW", "NE", "SE", "SW", "W", "E", "BL", "BR"],
}
const ELDER_POS := Vector2(0.5, 0.115)
const LAKE_C := Vector2(0.5, 0.535)          # le centre de la carte, où se tient la salle du conseil (et le lac, s'il est seul)
const LAKE_R := Vector2(0.29, 0.245)
## Les lacs de la carte selon leur nombre (centre et rayons, normalisés) : un seul au centre (la vallée de base), puis deux côte à
## côte, trois, quatre. Leurs villages se placent autour d'eux (voir `layout`).
const MAX_LAKES := 4
const LAKE_BOXES := {
	1: [[Vector2(0.5, 0.535), Vector2(0.29, 0.245)]],
	2: [[Vector2(0.31, 0.56), Vector2(0.15, 0.21)], [Vector2(0.69, 0.56), Vector2(0.15, 0.21)]],
	3: [[Vector2(0.29, 0.42), Vector2(0.15, 0.13)], [Vector2(0.71, 0.42), Vector2(0.15, 0.13)], [Vector2(0.5, 0.69), Vector2(0.19, 0.115)]],
	4: [[Vector2(0.29, 0.42), Vector2(0.15, 0.115)], [Vector2(0.71, 0.42), Vector2(0.15, 0.115)],
		[Vector2(0.29, 0.72), Vector2(0.15, 0.115)], [Vector2(0.71, 0.72), Vector2(0.15, 0.115)]],
}
const ROOM := Rect2(0.045, 0.105, 0.91, 0.85)
const RING_R := Vector2(0.42, 0.42)          # l'anneau du conseil, dans le sol : il entoure le lac (plus grand en vue isométrique)
## La vue isométrique : le sol est le carré [0,1]² des coordonnées de la partie, projeté en losange (`_px`). Le losange touche les quatre
## bords de la carte ; au-delà, la forêt hors de la vallée : la carte remplit tout le cadre, et la caméra s'y promène (voir « caméra »).
const ISO_LAKE_K := {1: 1.2, 2: 1.12, 3: 1.1, 4: 1.1}      # les lacs, un peu plus grands dans le sol que sur le plan du menu
## Les mailles du monde, dans le sol. Les parcelles des lacs (celles du moteur, `lakes.GRID`) : chacune son poisson et sa chance.
## Les lots des maisons : une maison par lot, et c'est un obstacle. Les pas des personnages, bien plus fins : ils se faufilent entre
## les maisons et contournent l'eau ; les barques, elles, ne vont que sur l'eau.
## La vallée fait `world_k` largeurs de carte : lots et pas grandissent avec elle (`n_lots` = 24 par largeur, `n_steps` = 5 pas par lot),
## si bien que maisons, arbres et pions gardent leur taille à l'écran.
const LOTS_PER_W := 24
const ZOOM_MAX := 4.0
const MARGIN_K := 0.3               # la marge de forêt autour du losange, en cadres
const LAND_SPEED := 0.45
const WATER_SPEED := 0.30
const DUSK := Color("#ff7a3d")
const NIGHT := Color("#081028")

var terrain: ColorRect
var decor: Control
var under: Control
var shade: Control
var lights: Control
var over: Control
var mat: ShaderMaterial

var agents := {}
var order: Array = []
var stock_ratio := 1.0
var stock_t := 0.0
var capacity := 100.0
var collapsed := false
var selected := ""
var hovered := ""
var animate := true
var paused := false                 # partie en pause : tout est figé, et la carte le dit
var time_scale := 1.0               # vitesse des animations, calée sur celle de la partie (0 = figé)
var effects: Array = []
var bubbles := {}
var badges := {}
var rules: Array = []               # les règles en vigueur (norms_in_force, norm_adopted) : réserves et repos se voient sur la carte
var cur_season := 0
var _proposal_author := {}

# temps et ambiance
var season_days := 30.0
var sim_time := 0.0
var light := 1.0
var phase := ""
var assembly_scope := ""            # "" | "valley" | "hamlet"
var hamlet_pos := layout(DEFAULT_HAMLETS)    # où est chaque village autour du lac (voir layout)
var lakes: Array = iso_boxes(1, 1.5)     # les lacs : {c, r, name, label, capacity, ratio}
var iso_o := Vector2(500.0, 0.0)    # le coin nord du sol, à l'écran
var iso_a := 470.0                  # demi-largeur du losange
var iso_b := 270.0                  # demi-hauteur du losange
var iso_ex := Vector2(0.87, 0.49)   # l'axe x du sol, à l'écran (unitaire) ; l'axe y est son symétrique
# la caméra : le monde (sol, décor, pions) défile et se zoome dans `cam` ; `over` (bulles, cadrans, bandeaux) reste à l'écran
var cam: Control
var top: Control
var zoom := 1.0
var zoom_min := 1.0 / 1.5           # au plus petit zoom, toute la vallée tient dans le cadre
var cam_off := Vector2.ZERO
var council_c := LAKE_C             # le centre de la veillée de la vallée
var council_r := RING_R / 1.5       # le rayon de l'anneau du conseil, dans le sol
var elder_pos := ELDER_POS
var world_k := 1.5                  # la taille de la vallée, en largeurs de carte (run_start.map.size)
var PARCELS := 45                   # la maille des lacs (run_start.map.grid : 30 par largeur de carte)
var n_lots := 36                    # la maille des maisons (LOTS_PER_W × world_k)
var n_steps := 180                  # la maille des pas (5 par lot)
var world := Vector2(1000, 700)     # le calque du monde : la vallée plus sa marge de forêt, en pixels
var dragging := false
var glide := false                  # la caméra glisse vers `glide_to` (la veillée) jusqu'à ce que l'utilisateur la reprenne
var glide_to := Vector2.ZERO
var mini_drag := false              # un glisser sur la mini-carte
var show_mesh := false              # touche G : les trois mailles du monde
# les lacs en parcelles
var lake_cells: Array = []          # par lac : ses parcelles {c: Vector2i, luck, rel} (`rel` : son poisson, rapporté à celui du lac)
var parcel_lake := PackedInt32Array()   # PARCELS² : le lac de chaque parcelle (-1 : la terre)
var field := PackedFloat32Array()   # STEPS² : l'eau, de 0 à 1 (la rive à 0,5), lissée comme le shader la dessine
var mask_img: Image                 # PARCELS² : eau, poisson, lac, profondeur (agrandie pour le shader)
var walk := AStarGrid2D.new()       # les pas des personnages : ni l'eau ni les maisons
var sail := AStarGrid2D.new()       # les barques : l'eau seulement
var hamlet_lake := {}               # village -> indice de son lac
var patrol_routes := {}             # la route de chaque patrouille cette saison (capitaine -> étapes {zone, from_day, to_day})
var patrol_season := 0
var seats := 0                      # sièges occupés à la veillée (le conseil des élus, ou toute la vallée)
var hamlet_fires: Array = []        # hameaux qui tiennent veillée
var room_alpha := 0.0
var dry := 0.0
var t := 0.0
var banners: Array = []

# décor généré
var deco := {"trees": [], "houses": [], "docks": {}, "paths": [], "reeds": [], "flies": []}
var fish: Array = []
var wakes: Array = []
var splashes: Array = []


func _ready() -> void:
	clip_contents = true
	mouse_filter = Control.MOUSE_FILTER_STOP
	focus_mode = Control.FOCUS_CLICK
	cam = Control.new()
	cam.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(cam)
	terrain = ColorRect.new()
	mat = ShaderMaterial.new()
	mat.shader = load("res://shaders/valley.gdshader")
	terrain.material = mat
	_layer(terrain)
	decor = _layer(Control.new())
	under = _layer(Control.new())
	shade = _layer(Control.new())
	lights = _layer(Control.new())
	var add := CanvasItemMaterial.new()
	add.blend_mode = CanvasItemMaterial.BLEND_MODE_ADD
	lights.material = add
	top = _layer(Control.new())
	over = Control.new()
	over.set_anchors_preset(Control.PRESET_FULL_RECT)
	over.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(over)
	decor.draw.connect(func() -> void: _draw_decor(decor))
	under.draw.connect(func() -> void: _draw_under(under))
	shade.draw.connect(func() -> void: _draw_shade(shade))
	lights.draw.connect(func() -> void: _draw_lights(lights))
	top.draw.connect(func() -> void: _draw_top(top))
	over.draw.connect(func() -> void: _draw_over(over))
	resized.connect(_on_resized)
	_build_lakes()
	_on_resized()


## Un calque du monde : il suit la caméra.
func _layer(c: Control) -> Control:
	c.set_anchors_preset(Control.PRESET_FULL_RECT)
	c.mouse_filter = Control.MOUSE_FILTER_IGNORE
	cam.add_child(c)
	return c


func _on_resized() -> void:
	if size.x < 10:
		return
	var first := cam_off == Vector2.ZERO
	_layout_world()
	if first:
		_center_view()
	_apply_cam()
	_push_lakes()
	_generate_decor()
	decor.queue_redraw()


## La taille de la vallée a changé (ou le cadre) : mailles, géométrie iso, calques et shader.
func _set_world(k: float, grid: int = 30) -> void:
	world_k = clampf(k, 1.0, 4.0)
	PARCELS = clampi(grid, 10, 200)
	n_lots = maxi(8, roundi(LOTS_PER_W * world_k))
	n_steps = n_lots * 5
	if size.x > 10:
		_layout_world()


func _layout_world() -> void:
	_update_iso()
	cam.size = world
	mat.set_shader_parameter("px_size", world)
	mat.set_shader_parameter("iso_o", iso_o)
	mat.set_shader_parameter("iso_ab", Vector2(iso_a, iso_b))
	mat.set_shader_parameter("world_k", world_k)


## Le cadre sur le milieu de la vallée, au zoom 1.
func _center_view() -> void:
	glide = false
	zoom = 1.0
	cam_off = size * 0.5 - _px(Vector2(0.5, 0.5))
	_apply_cam()


# ================================================================== caméra
## Comme dans Age of Empires : la molette zoome vers le pointeur, le clic droit (ou celui du milieu) fait glisser la carte, les flèches
## et le bord de la carte la font défiler ; G montre les mailles, Origine recadre. Au zoom 1, toute la vallée tient dans le cadre.
func _apply_cam() -> void:
	zoom = clampf(zoom, zoom_min, ZOOM_MAX)
	# au zoom minimum, la vallée seule (rien de sa marge de forêt) : elle tient alors exactement dans le cadre
	var mt := size * MARGIN_K * clampf((zoom - zoom_min) / maxf(1.0 - zoom_min, 0.001), 0.0, 1.0)
	var org := size * MARGIN_K
	var lo := size - (org + Vector2(2.0 * iso_a, 2.0 * iso_b) + mt) * zoom
	var hi := -(org - mt) * zoom
	cam_off = cam_off.clamp(lo.min(hi), hi)
	if cam != null:
		cam.position = cam_off
		cam.scale = Vector2(zoom, zoom)


## Zoome de `factor` en gardant immobile le point du sol qui est sous `screen`.
func zoom_at(screen: Vector2, factor: float) -> void:
	glide = false
	var base := (screen - cam_off) / zoom
	zoom = clampf(zoom * factor, zoom_min, ZOOM_MAX)
	cam_off = screen - base * zoom
	_apply_cam()


func pan(by: Vector2) -> void:
	glide = false
	cam_off += by
	_apply_cam()


## Un point du sol → l'écran, à travers la caméra (les bulles, les clics).
func _scr(n: Vector2) -> Vector2:
	return cam_off + _px(n) * zoom


## La caméra glisse doucement jusqu'à centrer ce point du sol.
func glide_to_ground(n: Vector2) -> void:
	glide_to = size * 0.5 - _px(n) * zoom
	glide = true


## Les flèches et le bord de la carte (quand on a zoomé) la font défiler.
func _scroll(dt: float) -> void:
	if not is_visible_in_tree() or dt <= 0.0:
		return
	if glide:
		cam_off = cam_off.lerp(glide_to, 1.0 - exp(-2.5 * dt))
		_apply_cam()
		if cam_off.distance_to(glide_to) < 1.0:
			glide = false
	var dir := Vector2.ZERO
	var fo := get_viewport().gui_get_focus_owner()
	if not (fo is LineEdit or fo is TextEdit):
		if Input.is_key_pressed(KEY_LEFT):
			dir.x += 1.0
		if Input.is_key_pressed(KEY_RIGHT):
			dir.x -= 1.0
		if Input.is_key_pressed(KEY_UP):
			dir.y += 1.0
		if Input.is_key_pressed(KEY_DOWN):
			dir.y -= 1.0
	var m := get_local_mouse_position()
	if zoom > zoom_min + 0.001 and not dragging and DisplayServer.window_is_focused() and Rect2(Vector2.ZERO, size).has_point(m):
		if m.x < 8.0:
			dir.x += 1.0
		elif m.x > size.x - 8.0:
			dir.x -= 1.0
		if m.y < 8.0:
			dir.y += 1.0
		elif m.y > size.y - 8.0:
			dir.y -= 1.0
	if dir != Vector2.ZERO:
		pan(dir.normalized() * 900.0 * dt)


func _unhandled_input(event: InputEvent) -> void:
	var k := event as InputEventKey
	if k == null or not k.pressed or k.echo or not is_visible_in_tree():
		return
	var fo := get_viewport().gui_get_focus_owner()
	if fo is LineEdit or fo is TextEdit:
		return
	if k.keycode == KEY_G:
		show_mesh = not show_mesh
		terrain.material.set_shader_parameter("mesh", show_mesh)
	elif k.keycode == KEY_HOME:
		_center_view()


# ================================================================== géométrie
## Les lacs tels que la vue isométrique les pose : ceux du plan, agrandis.
static func iso_boxes(n: int, k: float = 1.0) -> Array:
	var out := lake_boxes(n, k)
	for lk in out:
		lk["r"] = lk["r"] * float(ISO_LAKE_K[clampi(n, 1, MAX_LAKES)])
	return out


static func lake_boxes(n: int, k: float = 1.0) -> Array:
	var out: Array = []
	for b in LAKE_BOXES[clampi(n, 1, MAX_LAKES)]:
		out.append({"c": b[0], "r": b[1] / k, "name": "", "label": "Lac de Vellmor", "capacity": 100.0, "ratio": 1.0})
	return out


## Où poser les villages (dans l'ordre donné, celui de la vallée). Avec un seul lac : la table du nombre de villages, de 1 à 8.
## Avec plusieurs : chaque village sur la rive extérieure de son lac (`lake_of` : village -> indice du lac), les villages d'un même lac
## répartis le long de cette rive.
static func layout(names: Array, lake_of: Dictionary = {}, n_lakes: int = 1, kscale: float = 1.0) -> Dictionary:
	var out := {}
	if n_lakes <= 1:
		var slots: Array = LAYOUTS[clampi(names.size(), 1, 8)]
		for i in names.size():
			out[str(names[i])] = SLOTS[slots[mini(i, slots.size() - 1)]]
		return out
	var boxes := lake_boxes(n_lakes)
	var by_lake := {}
	for h in names:
		var k := clampi(int(lake_of.get(str(h), 0)), 0, n_lakes - 1)
		if not by_lake.has(k):
			by_lake[k] = []
		by_lake[k].append(str(h))
	for k in by_lake:
		var hs: Array = by_lake[k]
		var c: Vector2 = boxes[k]["c"]
		var r: Vector2 = boxes[k]["r"] * kscale
		var outward := atan2(c.y - 0.55, c.x - 0.5) if absf(c.x - 0.5) + absf(c.y - 0.55) > 0.05 else PI / 2.0
		var step := minf(TAU / float(hs.size()), 2.0 if hs.size() == 2 else 1.65 if hs.size() == 3 else 1.3)
		for i in hs.size():
			var a := outward + (float(i) - float(hs.size() - 1) / 2.0) * step
			var p := c + Vector2(cos(a) * r.x * 1.55, sin(a) * r.y * 1.55)
			out[hs[i]] = Vector2(clampf(p.x, 0.15, 0.85), clampf(p.y, 0.29, 0.86))
	return out


static func lake_shape(th: float) -> float:
	return 1.0 + 0.06 * sin(3.0 * th + 1.0) + 0.04 * sin(5.0 * th + 2.0) + 0.03 * sin(7.0 * th + 0.5)


## L'eau en ce point du sol, de 0 (la terre) à 1 (le large) : la rive est à 0,5, exactement là où le shader la dessine.
func water_at(n: Vector2) -> float:
	if field.is_empty():
		return 0.0
	var x := n.x * n_steps - 0.5
	var y := n.y * n_steps - 0.5
	var x0 := clampi(int(floor(x)), 0, n_steps - 2)
	var y0 := clampi(int(floor(y)), 0, n_steps - 2)
	var fx := clampf(x - x0, 0.0, 1.0)
	var fy := clampf(y - y0, 0.0, 1.0)
	var a := lerpf(field[x0 * n_steps + y0], field[(x0 + 1) * n_steps + y0], fx)
	var b := lerpf(field[x0 * n_steps + y0 + 1], field[(x0 + 1) * n_steps + y0 + 1], fx)
	return lerpf(a, b, fy)


func is_water(n: Vector2) -> bool:
	return water_at(n) > 0.5


## Le lac de ce point (indice) : celui de sa parcelle, ou à défaut le plus proche.
func _lake_at(n: Vector2) -> int:
	var c := Vector2i(clampi(int(n.x * PARCELS), 0, PARCELS - 1), clampi(int(n.y * PARCELS), 0, PARCELS - 1))
	if not parcel_lake.is_empty() and parcel_lake[c.x * PARCELS + c.y] >= 0:
		return parcel_lake[c.x * PARCELS + c.y]
	var best := 0
	var bd := INF
	for i in lakes.size():
		var d: float = n.distance_squared_to(lakes[i]["c"])
		if d < bd:
			bd = d
			best = i
	return best


## Le centre d'une parcelle, dans le sol.
func _parcel_pos(c: Vector2i) -> Vector2:
	return (Vector2(c) + Vector2(0.5, 0.5)) / float(PARCELS)


## Les lacs, parcelle par parcelle : celles du moteur (`cells` de chaque lac), ou à défaut le gabarit de `lake_boxes` mis en parcelles.
## De là : le lac de chaque parcelle, le centre et l'étendue de chaque lac, le champ d'eau et l'image du shader.
func _build_lakes() -> void:
	parcel_lake = PackedInt32Array()
	parcel_lake.resize(PARCELS * PARCELS)
	parcel_lake.fill(-1)
	lake_cells.clear()
	for k in lakes.size():
		var list: Array = []
		var given: Array = lakes[k].get("cells", [])
		if given.is_empty():
			for i in PARCELS:
				for j in PARCELS:
					var d: Vector2 = (_parcel_pos(Vector2i(i, j)) - lakes[k]["c"]) / lakes[k]["r"]
					if d.length() < lake_shape(atan2(d.y, d.x)) and parcel_lake[i * PARCELS + j] < 0:
						list.append({"c": Vector2i(i, j), "luck": 1.0, "rel": 1.0})
		else:
			for c in given:
				list.append({"c": Vector2i(int(c[0]), int(c[1])), "luck": float(c[3]) if c.size() > 3 else 1.0, "rel": 1.0})
		for p in list:
			parcel_lake[p["c"].x * PARCELS + p["c"].y] = k
		lake_cells.append(list)
		if not list.is_empty():
			var lo := Vector2(INF, INF)
			var hi := Vector2(-INF, -INF)
			var sum := Vector2.ZERO
			for p in list:
				var q := _parcel_pos(p["c"])
				lo = lo.min(q)
				hi = hi.max(q)
				sum += q
			lakes[k]["c"] = sum / float(list.size())
			lakes[k]["r"] = (hi - lo) * 0.5 + Vector2.ONE * (0.5 / PARCELS)
	_update_council()
	_build_field()


## L'anneau du conseil entoure les lacs (au moins RING_R / taille du monde) ; la maison de l'ancien est au nord de l'anneau.
func _update_council() -> void:
	var ctr := Vector2.ZERO
	for lk in lakes:
		ctr += lk["c"]
	council_c = ctr / float(lakes.size()) if lakes.size() > 1 else (lakes[0]["c"] if not lakes.is_empty() else LAKE_C)
	council_r = RING_R / world_k
	for lk in lakes:
		council_r = council_r.max(((lk["c"] - council_c).abs() + lk["r"]) * 1.12)
	elder_pos = Vector2(council_c.x, maxf(council_c.y - council_r.y * 0.92, 0.04))


## L'image des lacs (une parcelle par pixel, agrandie et lissée) : R l'eau, G le poisson de la parcelle, B le lac, A la profondeur ; et
## le champ d'eau qu'en tire la carte (`water_at`), pour que barques, pions et maisons tombent juste par rapport au dessin.
func _build_field() -> void:
	var P := PARCELS
	var depth := PackedInt32Array()
	depth.resize(P * P)
	depth.fill(-1)
	var front: Array = []
	var dirs := [Vector2i(1, 0), Vector2i(-1, 0), Vector2i(0, 1), Vector2i(0, -1)]
	for i in P:
		for j in P:
			if parcel_lake[i * P + j] < 0:
				continue
			for d in dirs:
				var q: Vector2i = Vector2i(i, j) + d
				if q.x < 0 or q.y < 0 or q.x >= P or q.y >= P or parcel_lake[q.x * P + q.y] < 0:
					depth[i * P + j] = 0
					front.append(Vector2i(i, j))
					break
	while not front.is_empty():
		var nxt: Array = []
		for c in front:
			for d in dirs:
				var q: Vector2i = c + d
				if q.x >= 0 and q.y >= 0 and q.x < P and q.y < P and parcel_lake[q.x * P + q.y] >= 0 and depth[q.x * P + q.y] < 0:
					depth[q.x * P + q.y] = depth[c.x * P + c.y] + 1
					nxt.append(q)
		front = nxt
	var maxd := 1
	for v in depth:
		maxd = maxi(maxd, v)
	var rel := {}
	for k in lake_cells.size():
		for p in lake_cells[k]:
			rel[p["c"]] = clampf(float(p["rel"]) * _ratio(k), 0.0, 1.0)
	mask_img = Image.create(P, P, false, Image.FORMAT_RGBA8)
	for i in P:
		for j in P:
			# l'eau, lissée sur les parcelles voisines (un noyau 3 × 3) : la rive passe entre une parcelle d'eau et une de terre
			var w := 0.0
			for di in [-1, 0, 1]:
				for dj in [-1, 0, 1]:
					var a := clampi(i + di, 0, P - 1)
					var b := clampi(j + dj, 0, P - 1)
					if parcel_lake[a * P + b] >= 0:
						w += (4.0 if di == 0 and dj == 0 else (2.0 if di == 0 or dj == 0 else 1.0)) / 16.0
			var k := _lake_at(_parcel_pos(Vector2i(i, j)))
			mask_img.set_pixel(i, j, Color(w, float(rel.get(Vector2i(i, j), _ratio(k))), float(k) / 3.0,
				float(maxi(depth[i * P + j], 0)) / float(maxd)))
	var big := mask_img.duplicate() as Image
	big.resize(n_steps, n_steps, Image.INTERPOLATE_CUBIC)
	field = PackedFloat32Array()
	field.resize(n_steps * n_steps)
	for x in n_steps:
		for y in n_steps:
			field[x * n_steps + y] = clampf(big.get_pixel(x, y).r, 0.0, 1.0)
	if mat != null:
		mat.set_shader_parameter("lake_mask", ImageTexture.create_from_image(big))


## Le poisson a changé (une prise, un repeuplement) : seul le vert de l'image change, pas l'eau.
func _refresh_fish_layer() -> void:
	if mask_img == null or mat == null:
		return
	for k in lake_cells.size():
		for p in lake_cells[k]:
			var c: Color = mask_img.get_pixelv(p["c"])
			c.g = clampf(float(p["rel"]) * _ratio(k), 0.0, 1.0)
			mask_img.set_pixelv(p["c"], c)
	var big := mask_img.duplicate() as Image
	big.resize(n_steps, n_steps, Image.INTERPOLATE_CUBIC)
	mat.set_shader_parameter("lake_mask", ImageTexture.create_from_image(big))


func lake_point(th: float, rn: float, k: int = 0) -> Vector2:
	var lk: Dictionary = lakes[clampi(k, 0, lakes.size() - 1)]
	return lk["c"] + Vector2(cos(th), sin(th)) * lk["r"] * lake_shape(th) * rn


func _lake_of_hamlet(h: String) -> int:
	return clampi(int(hamlet_lake.get(h, 0)), 0, lakes.size() - 1)


## Le lac d'une zone de pêche : « large-Orsane » est le large du lac d'Orsane ; à défaut, `fallback`.
func _lake_named(zone: String, fallback: int) -> int:
	for i in lakes.size():
		if zone == "large-" + str(lakes[i].get("name", "")):
			return i
	return fallback


## Pousse les lacs au shader : leur nombre (l'image des parcelles, elle, part avec `_build_field`).
func _push_lakes() -> void:
	if mat == null:
		return
	mat.set_shader_parameter("lake_n", lakes.size())
	mat.set_shader_parameter("grid", PARCELS)
	mat.set_shader_parameter("mesh", show_mesh)


## Le niveau d'un lac (stock / capacité) : celui de la partie s'il est seul.
func _ratio(k: int) -> float:
	return stock_ratio if lakes.size() == 1 else float(lakes[k].get("ratio", 1.0))


## Un point du sol → l'écran.
func _px(n: Vector2) -> Vector2:
	return iso_o + Vector2((n.x - n.y) * iso_a, (n.x + n.y) * iso_b)


## Un point de l'écran → le sol.
func _nm(p: Vector2) -> Vector2:
	var d := p - iso_o
	var u := d.x / iso_a
	var w := d.y / iso_b
	return Vector2((u + w) * 0.5, (w - u) * 0.5)


## Une fraction du panneau → l'écran (la salle du conseil, les bulles : ce qui ne se pose pas sur le sol).
func _sp(n: Vector2) -> Vector2:
	return Vector2(n.x * size.x, n.y * size.y) + _px(council_c) - size * 0.5     # un cadre posé autour de l'anneau du conseil


func _update_iso() -> void:
	iso_a = size.x * 0.5 * world_k
	iso_b = maxf(size.y * 0.5, 80.0) * world_k
	var margin := size * MARGIN_K
	iso_o = Vector2(margin.x + iso_a, margin.y)
	world = Vector2(2.0 * iso_a, 2.0 * iso_b) + margin * 2.0
	zoom_min = clampf(minf(size.x / (2.0 * iso_a), size.y / (2.0 * iso_b)), 0.05, 1.0)
	iso_ex = Vector2(iso_a, iso_b).normalized()


## Une ellipse du sol (centre et rayons en coordonnées du sol), projetée à l'écran.
func _ground_ellipse(ci: CanvasItem, c: Vector2, r: Vector2, col: Color, n: int = 40) -> void:
	var pts := PackedVector2Array()
	for i in n:
		var a := TAU * float(i) / float(n)
		pts.append(_px(c + Vector2(cos(a) * r.x, sin(a) * r.y)))
	ci.draw_colored_polygon(pts, col)


# ================================================================== mailles et chemins
func _step_of(n: Vector2) -> Vector2i:
	return Vector2i(clampi(int(n.x * n_steps), 0, n_steps - 1), clampi(int(n.y * n_steps), 0, n_steps - 1))


func _step_pos(c: Vector2i) -> Vector2:
	return (Vector2(c) + Vector2(0.5, 0.5)) / float(n_steps)


func _lot_pos(c: Vector2i) -> Vector2:
	return (Vector2(c) + Vector2(0.5, 0.5)) / float(n_lots)


## Les pas des personnages (l'eau est un obstacle) et ceux des barques (la terre en est un) ; les maisons s'ajoutent ensuite.
func _build_grids() -> void:
	for g in [walk, sail]:
		g.region = Rect2i(0, 0, n_steps, n_steps)
		g.cell_size = Vector2.ONE
		g.diagonal_mode = AStarGrid2D.DIAGONAL_MODE_ONLY_IF_NO_OBSTACLES
		g.default_compute_heuristic = AStarGrid2D.HEURISTIC_OCTILE
		g.default_estimate_heuristic = AStarGrid2D.HEURISTIC_OCTILE
		g.update()
	for x in n_steps:
		for y in n_steps:
			var w := field[x * n_steps + y] if not field.is_empty() else 0.0
			walk.set_point_solid(Vector2i(x, y), w > 0.42)
			sail.set_point_solid(Vector2i(x, y), w < 0.62)


## Le pas libre le plus proche de `c` sur cette grille (-1, -1 : aucun à moins de dix pas).
func _free_step(c: Vector2i, g: AStarGrid2D) -> Vector2i:
	if not g.is_point_solid(c):
		return c
	for r in range(1, 11):
		var best := Vector2i(-1, -1)
		var bd := INF
		for dx in range(-r, r + 1):
			for dy in range(-r, r + 1):
				if maxi(absi(dx), absi(dy)) != r:
					continue
				var q := c + Vector2i(dx, dy)
				if g.is_in_boundsv(q) and not g.is_point_solid(q) and Vector2(dx, dy).length() < bd:
					bd = Vector2(dx, dy).length()
					best = q
		if best.x >= 0:
			return best
	return Vector2i(-1, -1)


## Les étapes (dans le sol) d'un trajet de `a` à `b` sur une grille : les pas libres, un sur deux, puis `b`.
func _route(a: Vector2, b: Vector2, g: AStarGrid2D) -> Array:
	var s := _free_step(_step_of(a), g)
	var e := _free_step(_step_of(b), g)
	if s.x < 0 or e.x < 0:
		return [b]
	var ids := g.get_id_path(s, e)
	if ids.is_empty():
		return [b]
	var out: Array = []
	for i in range(2, ids.size() - 1, 2):
		out.append(_step_pos(ids[i]))
	out.append(b)
	return out


## Une marche à terre : elle contourne l'eau et les maisons.
func _land_route(a: Vector2, b: Vector2) -> Array:
	return _route(a, b, walk)


## Un point d'eau franche près de `p` (une barque n'accoste pas la rive).
func _snap_water(p: Vector2) -> Vector2:
	if water_at(p) > 0.62:
		return p
	var c := _free_step(_step_of(p), sail)
	return p if c.x < 0 else _step_pos(c)


## Le ponton d'un village sur le lac `k` : la parcelle du lac la plus proche de lui, la rive dans sa direction, et le bout du ponton
## sur l'eau franche.
func _dock(k: int, from: Vector2) -> Dictionary:
	var best: Vector2 = lakes[clampi(k, 0, lakes.size() - 1)]["c"]
	var bd := INF
	if k < lake_cells.size():
		for p in lake_cells[k]:
			var q := _parcel_pos(p["c"])
			if water_at(q) > 0.6 and q.distance_squared_to(from) < bd:
				bd = q.distance_squared_to(from)
				best = q
	var dir := (from - best).normalized()
	var shore := best
	for i in 80:
		shore = best + dir * (float(i) * 0.003)
		if water_at(shore) < 0.4:
			break
	var tip := shore
	for i in 40:
		tip = shore - dir * (0.03 / world_k + float(i) * 0.003)
		if water_at(tip) > 0.66:
			break
	return {"shore": shore, "tip": tip, "k": k}


## Une maison sur son lot : sa taille suit celle d'un lot à l'écran, son pied (les pas qu'elle occupe) est un obstacle.
func _house_at(lot: Vector2i, rng: RandomNumberGenerator, elder: bool) -> Dictionary:
	var axis := Vector2(iso_a, iso_b).length()
	var L := axis / float(n_lots)
	var n := _lot_pos(lot)
	var s := Vector2(L * 0.8, L * 0.6) if elder else Vector2(L * rng.randf_range(0.36, 0.44), L * rng.randf_range(0.27, 0.34))
	var half := s / axis
	var foot: Array = []
	for x in range(int((n.x - half.x) * n_steps), int((n.x + half.x) * n_steps) + 1):
		for y in range(int((n.y - half.y) * n_steps), int((n.y + half.y) * n_steps) + 1):
			if x >= 0 and y >= 0 and x < n_steps and y < n_steps:
				foot.append(Vector2i(x, y))
	return {"kind": "house", "p": _px(n), "n": n, "lot": lot, "s": s, "h": L * (0.57 if elder else rng.randf_range(0.33, 0.46)),
		"roof": Color("#7a4b34") if elder else [Color("#b5583c"), Color("#8e6b52"), Color("#c49a55"), Color("#6f7584")][rng.randi() % 4],
		"wall": Color("#d8c7a0") if elder else [Color("#d8c7a0"), Color("#cdb892"), Color("#e0d2b0")][rng.randi() % 3],
		"seed": 0.5 if elder else rng.randf(), "elder": elder, "foot": foot}


## Un lot où bâtir : sur le sol, loin de l'eau, et personne n'y habite (le pion d'un villageois s'y tient).
func _lot_free(lot: Vector2i, homes: Array) -> bool:
	var n := _lot_pos(lot)
	if n.x < 0.03 or n.y < 0.03 or n.x > 0.97 or n.y > 0.97:
		return false
	for d in [Vector2.ZERO, Vector2(0.5, 0.5), Vector2(-0.5, 0.5), Vector2(0.5, -0.5), Vector2(-0.5, -0.5)]:
		if water_at(n + d / float(n_lots)) > 0.3:
			return false
	for h in homes:
		if (h - n).abs().x < 0.8 / n_lots and (h - n).abs().y < 0.8 / n_lots:
			return false
	return true


# ================================================================== décor
func _generate_decor() -> void:
	var rng := RandomNumberGenerator.new()
	rng.seed = 7411
	_build_grids()
	var homes: Array = []
	for id in agents:
		homes.append(agents[id]["home"])
	homes.append(elder_pos + Vector2(0.035, 0.035) / world_k)
	# les maisons, chacune sur son lot autour de la place de son village ; celle de l'ancien sur le sien
	var houses: Array = [_house_at(Vector2i(int(elder_pos.x * n_lots), int(elder_pos.y * n_lots)), rng, true)]
	var used := {houses[0]["lot"]: true}
	for h in hamlet_pos:
		var c: Vector2 = hamlet_pos[h]
		var ci := Vector2i(int(c.x * n_lots), int(c.y * n_lots))
		var lots: Array = []
		var reach := ceili(0.14 / world_k * n_lots) + 1
		for di in range(-reach, reach + 1):
			for dj in range(-reach, reach + 1):
				var lot := ci + Vector2i(di, dj)
				var d := _lot_pos(lot).distance_to(c)
				if d >= 0.065 / world_k and d <= 0.14 / world_k and not used.has(lot) and _lot_free(lot, homes):
					lots.append(lot)
		var turn := rng.randf() * TAU
		lots.sort_custom(func(x, y): return fposmod((_lot_pos(x) - c).angle() + turn, TAU) < fposmod((_lot_pos(y) - c).angle() + turn, TAU))
		for i in mini(6, lots.size()):
			var lot: Vector2i = lots[int(float(i) * float(lots.size()) / float(mini(6, lots.size())))]
			used[lot] = true
			houses.append(_house_at(lot, rng, false))
	for hs in houses:
		for st in hs["foot"]:
			walk.set_point_solid(st, true)
	# les pontons, puis les chemins de terre (ils contournent l'eau et les maisons)
	var docks := {}
	var paths: Array = []
	for h in hamlet_pos:
		docks[h] = _dock(_lake_of_hamlet(h), hamlet_pos[h])
		paths.append(_road_px(hamlet_pos[h], docks[h]["shore"]))
		paths.append(_road_px(hamlet_pos[h], elder_pos + Vector2(0.03, 0.045) / world_k))
	var elder_px := _px(elder_pos)
	# arbres : bosquets le long des versants et entre les hameaux, jamais sur l'eau, les places, les maisons ou les chemins
	var near_path := {}                                 # les points des chemins, rangés par case de 20 px
	for path in paths:
		for q in path:
			var key := Vector2i(int(floorf(q.x / 20.0)), int(floorf(q.y / 20.0)))
			if not near_path.has(key):
				near_path[key] = []
			near_path[key].append(q)
	var trees: Array = []
	var tries := 0
	var area := world_k * world_k                      # le décor suit la surface du monde
	while trees.size() < int(230.0 * area) and tries < int(6000.0 * area):
		tries += 1
		# un point du sol, loin ou près du bord, ou dans la bande de collines au-delà
		var n_p := Vector2(rng.randf_range(-0.10, 1.10), rng.randf_range(-0.10, 1.10))
		var p := _px(n_p)
		var edge: float = min(min(n_p.x, 1.0 - n_p.x), min(n_p.y, 1.0 - n_p.y))
		var keep := 1.0 if edge < 0.12 else (0.5 if edge < 0.2 else (0.2 if edge < 0.3 else 0.08))
		if rng.randf() > keep:
			continue
		if edge >= 0.0 and (water_at(n_p) > 0.1 or walk.is_point_solid(_step_of(n_p))):
			continue
		var bad := _screen_near(p, elder_px, 100.0)
		for h in hamlet_pos:
			if _screen_near(p, _px(hamlet_pos[h]), 120.0):
				bad = true
		if not bad:
			var cp := Vector2i(int(floorf(p.x / 20.0)), int(floorf(p.y / 20.0)))
			for dx in range(-1, 2):
				for dy in range(-1, 2):
					for q in near_path.get(cp + Vector2i(dx, dy), []):
						if p.distance_to(q) < 20:
							bad = true
		if bad:
			continue
		var pine := rng.randf() < 0.35
		trees.append({"kind": "tree", "p": p, "r": rng.randf_range(9, 17) * (0.85 if pine else 1.0), "pine": pine,
			"tone": rng.randf()})
	# roseaux sur la grève, loin des pontons
	var reeds: Array = []
	for i in int(70.0 * area):
		var k := rng.randi() % lakes.size()
		if k >= lake_cells.size() or lake_cells[k].is_empty():
			continue
		var cp := _parcel_pos(lake_cells[k][rng.randi() % lake_cells[k].size()]["c"])
		var dir := Vector2.from_angle(rng.randf_range(0.0, TAU))
		var q := cp
		for st in 120:
			q = cp + dir * float(st) * 0.003
			if water_at(q) < 0.5:
				break
		q += dir * rng.randf_range(-0.004, 0.008)
		var near_dock := false
		for h in docks:
			if q.distance_to(docks[h]["shore"]) < 0.035:
				near_dock = true
		if not near_dock:
			reeds.append({"p": _px(q), "n": rng.randi_range(3, 6), "seed": rng.randf()})
	var flies: Array = []
	for i in int(36.0 * area):
		var tr: Dictionary = trees[rng.randi() % max(trees.size(), 1)] if not trees.is_empty() else {"p": Vector2.ZERO}
		flies.append({"base": tr["p"] + Vector2(rng.randf_range(-30, 30), rng.randf_range(-30, 30)),
			"ph": rng.randf() * TAU, "sp": rng.randf_range(0.4, 1.0)})
	# arbres et maisons se dressent sur le sol : du plus loin (haut de l'écran) au plus proche, pour que les uns cachent les autres
	var stand: Array = trees + houses
	stand.sort_custom(func(a, b): return a["p"].y < b["p"].y)
	deco = {"trees": trees, "houses": houses, "stand": stand, "docks": docks, "paths": paths, "reeds": reeds, "flies": flies}


## Ces deux points de l'écran sont-ils proches l'un de l'autre, sur le sol (un cercle du sol est une ellipse écrasée à l'écran) ?
func _screen_near(a: Vector2, b: Vector2, radius: float) -> bool:
	var d := a - b
	return Vector2(d.x, d.y * 1.7).length() < radius


## Un chemin de terre (en pixels) : la marche de `a` à `b`, adoucie.
func _road_px(a: Vector2, b: Vector2) -> PackedVector2Array:
	var pts := PackedVector2Array([_px(a)])
	for q in _land_route(a, b):
		pts.append(_px(q))
	for it in 2:                                   # Chaikin : on coupe les coins
		var sm := PackedVector2Array([pts[0]])
		for i in pts.size() - 1:
			sm.append(pts[i].lerp(pts[i + 1], 0.25))
			sm.append(pts[i].lerp(pts[i + 1], 0.75))
		sm.append(pts[pts.size() - 1])
		pts = sm
	return pts


func _curve(a: Vector2, b: Vector2, bend: float, n: int = 24) -> PackedVector2Array:
	var mid := (a + b) * 0.5
	var dir := (b - a)
	var ctrl := mid + Vector2(-dir.y, dir.x) * bend
	var pts := PackedVector2Array()
	for i in n + 1:
		var u := float(i) / float(n)
		pts.append(a.lerp(ctrl, u).lerp(ctrl.lerp(b, u), u))
	return pts


func _draw_decor(ci: CanvasItem) -> void:
	# chemins de terre
	for path in deco["paths"]:
		ci.draw_polyline(path, Color("#6b5a3a", 0.55), 11.0, true)
		ci.draw_polyline(path, Color("#b89c6a", 0.85), 7.0, true)
	# places des hameaux et devant l'ancien
	for h in hamlet_pos:
		var c := _px(hamlet_pos[h])
		_ellipse(ci, c + Vector2(0, 4), Vector2(78, 40), Color("#6b5a3a", 0.45))
		_ellipse(ci, c, Vector2(74, 37), Color("#7d6844", 0.55))
		_ellipse(ci, c, Vector2(70, 34), Color("#c4a978"))
		_ellipse(ci, c + Vector2(-8, -4), Vector2(42, 18), Color(1, 1, 1, 0.06))
	var ep := _px(elder_pos)
	_ellipse(ci, ep + Vector2(0, 22), Vector2(86, 30), Color("#c4a978"))
	# pontons
	for h in deco["docks"]:
		var dk: Dictionary = deco["docks"][h]
		var a := _px(dk["shore"])
		var b := _px(dk["tip"])
		var dir := (b - a).normalized()
		var gdir: Vector2 = (dk["tip"] - dk["shore"]).normalized()
		var side := _px(Vector2(-gdir.y, gdir.x) * 0.011) - iso_o             # la largeur du ponton, prise dans le sol
		ci.draw_colored_polygon(PackedVector2Array([a + side + Vector2(2, 3), b + side + Vector2(2, 3),
			b - side + Vector2(2, 3), a - side + Vector2(2, 3)]), Color(0, 0, 0, 0.25))
		ci.draw_colored_polygon(PackedVector2Array([a + side, b + side, b - side, a - side]), Color("#8a6440"))
		var L := a.distance_to(b)
		var k := 0.0
		while k < L:
			var q := a + dir * k
			ci.draw_line(q + side, q - side, Color("#5e4129"), 1.0)
			k += 5.0
		for s in [-1.0, 1.0]:
			ci.draw_circle(b + side * s, 2.2, Color("#4a3320"))
			ci.draw_circle(a.lerp(b, 0.5) + side * s, 2.0, Color("#4a3320"))
	# roseaux
	for rd in deco["reeds"]:
		var p: Vector2 = rd["p"]
		for i in int(rd["n"]):
			var ang: float = -PI / 2 + (float(i) - float(rd["n"]) / 2.0) * 0.28 + (float(rd["seed"]) - 0.5) * 0.4
			ci.draw_line(p + Vector2(i * 1.5 - 3, 0), p + Vector2(i * 1.5 - 3, 0) + Vector2(cos(ang), sin(ang)) * 9.0,
				Color("#566b2c"), 1.4, true)
		ci.draw_circle(p + Vector2(0, -8), 1.6, Color("#7b5a2c"))
	# arbres et maisons, du plus loin au plus proche
	for it in deco["stand"]:
		if it["kind"] == "tree":
			_tree(ci, it)
		else:
			_house(ci, it)
	# foyer de l'ancien
	var fp := _fire_pos()
	for i in 8:
		var a := TAU * i / 8.0
		ci.draw_circle(fp + Vector2(cos(a) * 9, sin(a) * 7), 3.0, Color("#77736c"))


## Un arbre qui se dresse sur le sol : son ombre, son tronc, son houppier (rond, ou étagé pour un pin).
func _tree(ci: CanvasItem, tr: Dictionary) -> void:
	var p: Vector2 = tr["p"]
	var r: float = tr["r"]
	var tone: float = tr["tone"]
	_ellipse(ci, p + Vector2(r * 0.35, 1.0), Vector2(r * 1.1, r * 0.42), Color(0.05, 0.08, 0.03, 0.34))
	if tr["pine"]:
		var dark := Color("#1f4029").lerp(Color("#2b5233"), tone)
		ci.draw_line(p, p + Vector2(0, -r * 0.5), Color("#4a3320"), 2.4)
		for k in 3:
			var rr := r * (1.15 - k * 0.3)
			var base_y := -r * (0.3 + k * 0.62)
			var col := dark.lightened(k * 0.10)
			ci.draw_colored_polygon(PackedVector2Array([p + Vector2(-rr, base_y), p + Vector2(rr, base_y), p + Vector2(0, base_y - rr * 1.5)]), col)
			ci.draw_colored_polygon(PackedVector2Array([p + Vector2(0, base_y - rr * 1.5), p + Vector2(rr, base_y), p + Vector2(rr * 0.1, base_y)]),
				col.darkened(0.16))
	else:
		var base := Color("#2e5a2a").lerp(Color("#3f6e2c"), tone)
		ci.draw_line(p, p + Vector2(0, -r * 1.0), Color("#4a3320"), 3.0)
		var c := p + Vector2(0, -r * 1.55)
		ci.draw_circle(c + Vector2(r * 0.12, r * 0.14), r, base.darkened(0.2))
		ci.draw_circle(c, r, base)
		ci.draw_circle(c + Vector2(-r * 0.25, -r * 0.28), r * 0.7, base.lightened(0.12))
		ci.draw_circle(c + Vector2(-r * 0.4, -r * 0.45), r * 0.36, base.lightened(0.24))


## Une maison en boîte isométrique : son ombre, deux murs (celui de gauche à l'ombre), un toit à deux pans dont le pignon regarde à droite.
func _house(ci: CanvasItem, hs: Dictionary) -> void:
	var p: Vector2 = hs["p"]
	var s: Vector2 = hs["s"]
	var roof: Color = hs["roof"]
	var wall: Color = hs["wall"]
	var hgt: float = hs["h"]
	var ex := iso_ex * s.x
	var ey := Vector2(-iso_ex.x, iso_ex.y) * s.y
	var up := Vector2(0, -hgt)
	var p0 := p - ex - ey            # les quatre coins du pied : nord, est, sud, ouest
	var p1 := p + ex - ey
	var p2 := p + ex + ey
	var p3 := p - ex + ey
	ci.draw_colored_polygon(PackedVector2Array([p0 + Vector2(7, 3), p1 + Vector2(7, 3), p2 + Vector2(7, 3), p3 + Vector2(7, 3)]),
		Color(0, 0, 0, 0.26))
	ci.draw_colored_polygon(PackedVector2Array([p3, p2, p2 + up, p3 + up]), wall.darkened(0.30))         # mur de gauche (sud-ouest)
	ci.draw_colored_polygon(PackedVector2Array([p2, p1, p1 + up, p2 + up]), wall.darkened(0.08))         # mur de droite (sud-est)
	var ridge := Vector2(0, -hgt - maxf(s.y * 0.95, 8.0))
	var r0 := p - ex + ridge                                                                         # le faîte, d'un pignon à l'autre
	var r1 := p + ex + ridge
	ci.draw_colored_polygon(PackedVector2Array([p1 + up, p2 + up, r1]), wall.darkened(0.02))             # le pignon, à droite
	ci.draw_colored_polygon(PackedVector2Array([p3 + up, p2 + up, r1, r0]), roof.darkened(0.14))           # pan de devant
	ci.draw_line(p3 + up, p2 + up, roof.darkened(0.45), 1.6, true)                                       # la gouttière
	ci.draw_line(r0, r1, roof.lightened(0.25), 1.6, true)
	ci.draw_line(p2 + up, r1, roof.darkened(0.4), 1.2, true)
	var door := p2 + (p3 - p2) * 0.5
	ci.draw_colored_polygon(PackedVector2Array([door, door + (p2 - p3).normalized() * 4.5, door + (p2 - p3).normalized() * 4.5 + Vector2(0, -8),
		door + Vector2(0, -8)]), Color("#4b3a32"))
	if hs.get("elder", false):                       # la maison de l'ancien : une cheminée, un fanion
		var ch := p + ex * 0.5 - ey * 0.1 + Vector2(0, -hgt - s.y * 1.2)
		ci.draw_rect(Rect2(ch - Vector2(3, 9), Vector2(6, 10)), Color("#6b5a52"), true)
		ci.draw_line(r0, r0 + Vector2(0, -14), Color("#3a2a20"), 1.4)
		ci.draw_colored_polygon(PackedVector2Array([r0 + Vector2(0, -14), r0 + Vector2(10, -11), r0 + Vector2(0, -8)]), Color("#e2bd6a"))


func _ellipse(ci: CanvasItem, c: Vector2, r: Vector2, col: Color, n: int = 28) -> void:
	var pts := PackedVector2Array()
	for i in n:
		var a := TAU * i / n
		pts.append(c + Vector2(cos(a) * r.x, sin(a) * r.y))
	ci.draw_colored_polygon(pts, col)


func _star(ci: CanvasItem, c: Vector2, r: float, col: Color, n: int) -> void:
	var pts := PackedVector2Array()
	for i in n * 2:
		var a := TAU * i / (n * 2) - PI / 2
		var rr := r if i % 2 == 0 else r * 0.62
		pts.append(c + Vector2(cos(a), sin(a)) * rr)
	ci.draw_colored_polygon(pts, col)


func _fire_pos() -> Vector2:
	return _px(elder_pos) + Vector2(56, 22)


# ================================================================== état
## `map` : ce que le moteur a posé (run_start) : la place de chaque village dans le sol (`hamlets`) ; les parcelles des lacs sont dans
## `lake_info` (`cells`). Sans eux (un vieux journal), la carte les tire de ses gabarits.
func reset_world(agent_list: Array, cap: float, days: float = 30.0, hamlets: Array = [], lake_info: Array = [],
		map: Dictionary = {}) -> void:
	_set_world(float(map.get("size", 1.5)), int(map.get("grid", 30)))
	lakes = iso_boxes(clampi(lake_info.size(), 1, MAX_LAKES), world_k)
	hamlet_lake = {}
	for k in mini(lake_info.size(), MAX_LAKES):
		var li: Dictionary = lake_info[k]
		lakes[k]["name"] = str(li.get("name", ""))
		lakes[k]["label"] = str(li.get("label", "Lac de Vellmor"))
		lakes[k]["capacity"] = float(li.get("capacity", 100.0))
		lakes[k]["ratio"] = float(li.get("stock", 0.0)) / maxf(float(li.get("capacity", 1.0)), 0.001)
		lakes[k]["cells"] = li.get("cells", [])
		for v in li.get("villages", []):
			hamlet_lake[str(v)] = k
	var names: Array = hamlets if not hamlets.is_empty() else DEFAULT_HAMLETS
	hamlet_pos = layout(names, hamlet_lake, lakes.size(), float(ISO_LAKE_K[clampi(lakes.size(), 1, MAX_LAKES)]) / world_k)
	var placed: Dictionary = map.get("hamlets", {})
	for h in placed:
		if hamlet_pos.has(str(h)):
			hamlet_pos[str(h)] = Vector2(float(placed[h][0]), float(placed[h][1]))
	rules.clear()
	agents.clear()
	order.clear()
	effects.clear()
	bubbles.clear()
	badges.clear()
	banners.clear()
	_proposal_author.clear()
	capacity = cap
	season_days = days
	collapsed = false
	stock_ratio = float(lakes[0]["ratio"]) if lake_info.size() == 1 else 1.0
	_build_lakes()
	dry = 0.0
	assembly_scope = ""
	patrol_routes.clear()
	patrol_season = 0
	seats = 0
	hamlet_fires.clear()
	var per_hamlet := {}
	for a in agent_list:
		var h: String = str(a.get("hamlet", "Bramois"))
		per_hamlet[h] = int(per_hamlet.get(h, 0)) + 1
	var idx := {}
	for a in agent_list:
		var id: String = str(a["id"])
		var h: String = str(a.get("hamlet", "Bramois"))
		var home: Vector2
		if str(a.get("role", "")) == "ancien":
			home = elder_pos + Vector2(0.035, 0.035) / world_k
		else:
			var k: int = idx.get(h, 0)
			idx[h] = k + 1
			var n: int = per_hamlet[h]
			# une couronne autour du hameau, plus large dès quatre habitants (leurs noms se chevauchaient) ; au-delà de six
			# habitants, une deuxième couronne plus large
			var ring := 1.0
			var slot := k
			var count: int = mini(n, 6)
			if k >= 6:
				ring = 1.9
				slot = k - 6
				count = n - 6
			var ang := -PI / 2.0 + TAU * float(slot) / float(max(count, 1)) + (0.5 if ring == 1.0 else 0.25)
			var wide := 1.0 if (n <= 3 or ring > 1.0) else 1.85
			home = hamlet_pos.get(h, Vector2(0.5, 0.5)) + Vector2(cos(ang) * 0.05 * wide, sin(ang) * 0.05 * (1.0 + (wide - 1.0) * 0.6)) * ring / world_k
		agents[id] = {"id": id, "info": a, "home": home, "pos": home, "path": [], "hold": 0.0, "heading": 0.0,
			"wake_t": 0.0, "fishing": 0.0}
		order.append(id)
	fish.clear()
	_sync_fish(true)
	if size.x > 10:
		_push_lakes()
		_generate_decor()                # les villages ont changé de place : maisons, pontons et chemins aussi
		decor.queue_redraw()
		_center_view()
		if "--minzoom" in OS.get_cmdline_user_args():       # capture : toute la vallée
			zoom_at(size * 0.5, 0.001)


## L'élu d'un village : un astre doré au-dessus de son pion (un seul par village).
func set_rep(hamlet: String, id: String) -> void:
	for k in agents:
		if str(agents[k]["info"].get("hamlet", "")) == hamlet:
			agents[k]["rep"] = (k == id)


func remember_proposal(pid: String, author: String) -> void:
	_proposal_author[pid] = author


func on_event(ev: Dictionary) -> void:
	var ty: String = str(ev.get("type", ""))
	var p: Dictionary = ev.get("payload", {})
	sim_time = float(ev.get("sim_time", sim_time))
	cur_season = int(ev.get("season", cur_season))
	match ty:
		"season_start":
			dry = max(0.0, dry - 0.5)
			var md := "" if not p.has("mode") else (" · asynchrone" if str(p["mode"]) == "async" else " · synchrone")
			var cond: Dictionary = p.get("conditions", {})
			if cond.get("climate") != null:
				md = " · %s%s" % [str(cond["climate"]), md]
			_banner("Saison %d" % int(ev.get("season", 0)), "Le lac compte %.0f tonnes%s" % [float(p.get("stock", 0)), md], Art.PROMISE)
		"phase":
			var nm := str(p.get("name", ""))
			var st := str(p.get("state", ""))
			if nm == "fishing" and st == "open":
				phase = "Pêche"
				_banner("Ouverture de la pêche", "Chacun décide de sa prise", Color("#7fd0e8"))
			elif nm == "fishing" and st == "close":
				phase = "Au village"
			elif nm == "assembly" and st == "open":
				phase = "Veillée"
			elif nm == "assembly" and st == "close":
				phase = "Au village"
			elif nm == "regrowth":
				phase = "Repeuplement"
		"lake_update":
			stock_t = float(p.get("stock", 0.0))
			stock_ratio = stock_t / max(capacity, 0.001)
			for k in lakes.size():
				var held: Variant = p.get("lakes", {}).get(str(lakes[k].get("name", "")))
				if held != null:
					lakes[k]["ratio"] = float(held) / maxf(float(lakes[k]["capacity"]), 0.001)
			_sync_fish(not animate)
			_refresh_fish_layer()
		"lake_cells":
			# le poisson de chaque parcelle, après le repeuplement : l'eau garde la trace des coins trop pêchés
			for k in lakes.size():
				var fills: Array = p.get("lakes", {}).get(str(lakes[k].get("name", "")), [])
				if fills.size() == lake_cells[k].size():
					for i in fills.size():
						lake_cells[k][i]["rel"] = float(fills[i]) / maxf(_ratio(k), 0.001)
			_refresh_fish_layer()
		"lake_collapsed":
			collapsed = true
			_banner("Le lac s'effondre", "Il ne se repeuplera presque plus", Art.ACCUSE)
		"injection":
			var it := str(p.get("injection_type", ""))
			if it == "drought":
				dry = 1.0
				_banner("Sécheresse", "Le niveau baisse, les frayères sont à sec", Art.INCIDENT)
			elif it == "announcement":
				_banner("Une rumeur court", _short(str(p.get("params", {}).get("text", "")), 70), Art.INJECT)
			elif it == "set_communication":
				_banner("Communication modifiée", str(p.get("params", {}).get("value", "")), Art.INJECT)
			elif it == "set_mode":
				var asynchronous := str(p.get("params", {}).get("value", "")) == "async"
				_banner("Changement de mode", "%s dès la saison suivante" % ("Asynchrone" if asynchronous else "Synchrone"),
					Art.INJECT)
		"catch":
			var id: String = str(p.get("agent", ""))
			if agents.has(id):
				var a: Dictionary = agents[id]
				if bool(p.get("secret", false)):
					_mark(id, "en cachette", Color("#ff8a5c"), 3.5)       # vu du joueur seul
				if animate:
					var h := str(a["info"].get("hamlet", ""))
					var dk: Dictionary = deco["docks"].get(h, {})
					var spot := _fishing_spot(a, str(p.get("zone", "")), p.get("cell"))
					var to_lake := _lake_named(str(p.get("zone", "")), -1)
					if bool(p.get("away", false)) and to_lake >= 0 and not dk.is_empty():
						# parti dans un autre lac : il marche jusqu'à sa rive (le ponton le plus proche de chez lui), y prend une barque
						_mark(id, "loin de chez lui", Color("#e2bd6a"), 4.0)
						a["path"] = _trip(a, _dock(to_lake, dk["shore"]), spot)
					elif dk.is_empty():
						a["path"] = [[spot, 1.4], [a["home"], 0.0]]
					else:
						a["path"] = _trip(a, dk, spot)
					a["landed"] = float(p.get("landed", 0.0))
		"patrol_route":
			if int(p.get("season", 0)) != patrol_season:
				patrol_routes.clear()                  # une nouvelle saison : les routes de la précédente ne comptent plus
			patrol_routes[str(p.get("captain", "PAT"))] = p.get("legs", [])
			patrol_season = int(p.get("season", 0))
			_banner("La patrouille prend la mer", "Elle visite quelques zones du lac cette saison", Color("#7fe0c8"))
		"patrol":
			if str(p.get("state", "")) == "lifted":
				_banner("Patrouille retirée", "Dès la saison %d" % int(p.get("effective_season", 0)), Art.MUTED)
			else:
				_banner("Patrouille votée", "Elle sort dès la saison %d" % int(p.get("effective_season", 0)), Color("#7fe0c8"))
		"election":
			set_rep(str(p.get("hamlet", "")), str(p.get("representative", "")))
		"world_event":
			_banner(str(p.get("label", "")).capitalize(), _short(str(p.get("text", "")), 90), Art.INCIDENT)
			if str(p.get("kind", "")) == "secheresse":
				dry = 1.0
		"ban":
			var id: String = str(p.get("agent", ""))
			if agents.has(id):
				agents[id]["banned"] = bool(p.get("banned", false))
				_mark(id, "interdit de pêche" if agents[id]["banned"] else "de nouveau libre",
					Art.ACCUSE if agents[id]["banned"] else Color("#58d08a"), 4.0)
		"assembly_start":
			var scope: String = str(p.get("scope", "valley"))
			var parts: Array = p.get("participants", [])
			if scope == "valley":
				assembly_scope = "valley"
				if p.has("delegates"):
					_banner("Veillée chez l'ancien", "Le conseil des élus se réunit", Art.TALK)
				else:
					_banner("Veillée chez l'ancien", "Toute la vallée est réunie", Art.TALK)
				var ids: Array = []
				for x in parts:
					var sx := str(x)
					if not agents.has(sx):
						continue
					if str(agents[sx]["info"].get("role", "")) == "ancien":
						ids.push_front(sx)
					else:
						ids.append(sx)
				for aid in agents:                   # les villageois qui n'y siègent pas restent chez eux : on ne les montre pas dans la salle
					agents[aid]["absent"] = not ids.has(str(aid))
				seats = ids.size()
				glide_to_ground(council_c)
				for i in ids.size():
					var ang := -PI / 2.0 + TAU * float(i) / float(max(ids.size(), 1))
					_move(ids[i], council_c + Vector2(cos(ang), sin(ang)) * council_r)
			else:
				assembly_scope = "hamlet"
				var h := scope.substr(7)
				if not hamlet_fires.has(h):
					hamlet_fires.append(h)
				if hamlet_fires.size() == 1:
					_banner("Veillées dans les hameaux", "Chacun parle chez soi", Art.TALK)
				var c: Vector2 = hamlet_pos.get(h, council_c)
				if hamlet_fires.size() == 1:
					glide_to_ground(c)
				for i in parts.size():
					var ang := -PI / 2.0 + TAU * float(i) / float(max(parts.size(), 1))
					_move(str(parts[i]), c + Vector2(cos(ang) * 0.08, sin(ang) * 0.09) / world_k)
		"assembly_end":
			var scope2 := str(p.get("scope", "valley"))
			if p.get("adopted_proposal") == null and scope2 == "valley":
				_banner("Pas d'accord ce soir", "Aucune règle n'a réuni la moitié des pêcheurs", Art.MUTED)
			if scope2 == "valley":
				assembly_scope = ""
				seats = 0
			else:
				hamlet_fires.erase(scope2.substr(7))
				if hamlet_fires.is_empty():
					assembly_scope = ""
			badges.clear()
			for id in agents:
				agents[id]["absent"] = false
				_move(id, agents[id]["home"])
			bubbles.clear()
			effects = effects.filter(func(e): return e["kind"] != "link" and e["kind"] != "wave")
			banners = banners.filter(func(b): return not str(b["title"]).begins_with("Veillée"))
		"utterance":
			var sp: String = str(p.get("speaker", ""))
			var to: String = str(p.get("to", "tous"))
			if animate:
				bubbles[sp] = {"text": _short(str(p.get("text", "")), 120), "ttl": 6.0, "to": to, "born": t}
			if to != "tous" and agents.has(to):
				_link(sp, to, Art.TALK, 2.2, 4.5, "talk")
			elif animate:
				effects.append({"kind": "wave", "a": sp, "ttl": 1.8, "max": 1.8})
		"proposal":
			badges[str(p.get("author", ""))] = "%s · %s" % [str(p.get("proposal_id", "")), _short(str(p.get("text", "")), 30)] \
				if str(p.get("text", "")) != "" else "%s · %s t" % [str(p.get("proposal_id", "")), _num(p.get("quota", 0))]
		"season_end":
			if p.has("norms_in_force"):
				rules = (p["norms_in_force"] as Array).duplicate()
		"support":
			var author := str(_proposal_author.get(str(p.get("proposal_id", "")), ""))
			var who: String = str(p.get("agent", ""))
			if author != "" and author != who:
				_link(who, author, Art.SUPPORT, 1.8, 4.0, "support")
		"accusation":
			_link(str(p.get("accuser", "")), str(p.get("accused", "")), Art.ACCUSE, 3.5, 7.0, "accuse")
			_mark(str(p.get("accused", "")), "accusé", Art.ACCUSE, 7.0)
		"norm_adopted":
			_set_rule(p)
			_banner("Règle adoptée", "%s dès la saison %d · %d soutiens" % [
				_short(str(p.get("text", "")), 70) if str(p.get("text", "")) != "" else "%s t par pêcheur" % _num(p.get("quota", 0)),
				int(p.get("effective_season", 0)), p.get("supporters", []).size()], Art.SUPPORT)
			for s in p.get("supporters", []):
				_mark(str(s), "pour", Art.SUPPORT, 4.5)
		"promise_outcome":
			if bool(p.get("kept", true)):
				_mark(str(p.get("agent", "")), "parole tenue", Art.SUPPORT, 5.0)
			else:
				_mark(str(p.get("agent", "")), "promesse trahie", Art.ACCUSE, 8.0)
		"incident":
			# une fenêtre ratée (l'IA réfléchissait encore) se dit clairement : « réplique perdue », « sortie perdue »
			var missed: bool = str(p.get("incident_type", "")) == "missed_window"
			_mark(str(p.get("agent", "")), str(p.get("handled_by", "incident")) if missed else "incident", Art.INCIDENT, 4.0)
		"run_end":
			if str(p.get("reason", "")) == "extinction":
				_banner("Le lac est à sec", "Plus un seul poisson : un lac vide ne se repeuple jamais", Art.ACCUSE)
			else:
				_banner("Fin du run", str(p.get("reason", "")), Art.PROMISE)


func _banner(title: String, sub: String, col: Color) -> void:
	if not animate:
		return
	# un bandeau nouveau écourte le précédent : il doit toujours parler de ce qui se passe maintenant
	if not banners.is_empty():
		banners[0]["ttl"] = min(float(banners[0]["ttl"]), 0.5)
	banners.append({"title": title, "sub": sub, "col": col, "ttl": 2.6, "max": 2.6, "born": t})
	while banners.size() > 2:
		banners.pop_front()


func _move(id: String, target: Vector2, speed: float = 3.0) -> void:
	if not agents.has(id):
		return
	var a: Dictionary = agents[id]
	a["hold"] = 0.0
	if animate:
		a["path"] = _land_route(a["pos"], target).map(func(p: Vector2) -> Array: return [p, 0.0, speed])
	else:
		a["pos"] = target
		a["path"] = []


## Où va la barque : la parcelle que le moteur a donnée (`cell`, sa maille), sinon un coin de sa rive (au large : une parcelle profonde).
func _fishing_spot(a: Dictionary, zone: String = "", cell: Variant = null) -> Vector2:
	if cell is Array and (cell as Array).size() == 2:
		var q := _parcel_pos(Vector2i(int(cell[0]), int(cell[1]))) + Vector2(randf_range(-0.35, 0.35), randf_range(-0.35, 0.35)) / PARCELS
		return _snap_water(q)
	var h := zone if hamlet_pos.has(zone) else str(a["info"].get("hamlet", ""))
	var k := _lake_of_hamlet(h) if not zone.begins_with("large") else _lake_named(zone, _lake_of_hamlet(str(a["info"].get("hamlet", ""))))
	var cells: Array = lake_cells[k] if k < lake_cells.size() else []
	if cells.is_empty():
		return _snap_water(lakes[k]["c"])
	var from: Vector2 = lakes[k]["c"] if zone.begins_with("large") else hamlet_pos.get(h, lakes[k]["c"])
	var near := cells.duplicate()
	near.sort_custom(func(x, y): return _parcel_pos(x["c"]).distance_squared_to(from) < _parcel_pos(y["c"]).distance_squared_to(from))
	var pick: Dictionary = near[(order.find(a["id"]) * 7 + randi() % 3) % maxi(1, near.size() / 3)]
	return _snap_water(_parcel_pos(pick["c"]) + Vector2(randf_range(-0.3, 0.3), randf_range(-0.3, 0.3)) / PARCELS)


## Une sortie de pêche : à pied jusqu'au ponton, en barque jusqu'au coin (on y reste un peu), et retour.
func _trip(a: Dictionary, dk: Dictionary, spot: Vector2) -> Array:
	var out: Array = []
	for q in _land_route(a["pos"], dk["shore"]):
		out.append([q, 0.0])
	out.append([dk["tip"], 0.0])
	for q in _route(dk["tip"], spot, sail):
		out.append([q, 0.0])
	out[out.size() - 1][1] = 1.6
	for q in _route(spot, dk["tip"], sail):
		out.append([q, 0.0])
	out.append([dk["shore"], 0.0])
	for q in _land_route(dk["shore"], a["home"]):
		out.append([q, 0.0])
	return out


## La patrouille du lac : elle visite les zones de sa route l'une après l'autre (jours depuis le début de la saison), au centre du
## lac pour « large », devant la rive du village sinon ; entre deux zones, elle fait route.
func _zone_pos(zone: String) -> Vector2:
	if zone.begins_with("large") or not deco["docks"].has(zone):
		return _snap_water(lakes[_lake_named(zone, 0)]["c"])
	var dk: Dictionary = deco["docks"][zone]
	return _snap_water(dk["tip"].lerp(lakes[int(dk["k"])]["c"], 0.35))


func _patrol_pos(legs: Array, idx: int = 0) -> Vector2:
	var day := sim_time - float(patrol_season - 1) * season_days
	var k := 0
	for i in legs.size():
		if day >= float(legs[i]["from_day"]):
			k = i
	var leg: Dictionary = legs[k]
	var here := _zone_pos(str(leg["zone"]))
	var span := maxf(float(leg["to_day"]) - float(leg["from_day"]), 0.01)
	var u := clampf((day - float(leg["from_day"])) / span, 0.0, 1.0)
	if k > 0 and u < 0.25:
		here = _zone_pos(str(legs[k - 1]["zone"])).lerp(here, smoothstep(0.0, 0.25, u))
	return here + Vector2(cos(t * 0.7 + float(idx)) * 0.012, sin(t * 0.9 + float(idx)) * 0.014)


func _draw_patrol(ci: CanvasItem) -> void:
	if patrol_routes.is_empty() or int(floor(sim_time / maxf(season_days, 1.0))) + 1 != patrol_season:
		return
	var idx := 0
	for captain in patrol_routes:
		var legs: Array = patrol_routes[captain]
		if not legs.is_empty():
			_draw_patrol_boat(ci, _px(_patrol_pos(legs, idx)), idx)
		idx += 1


func _draw_patrol_boat(ci: CanvasItem, p: Vector2, idx: int) -> void:
	var col := Color("#7fe0c8")
	ci.draw_arc(p, 38.0, 0, TAU, 40, Color(col, 0.30), 1.2, true)
	var sweep := fmod(t * 1.2, TAU)
	ci.draw_arc(p, 30.0, sweep - 0.7, sweep, 12, Color(col, 0.30), 6.0, true)
	var dir := Vector2(1, 0).rotated(sin(t * 0.5) * 0.4)
	var side := Vector2(-dir.y, dir.x)
	var hull := PackedVector2Array([p + dir * 17.0, p + dir * 6.0 + side * 7.0, p - dir * 14.0 + side * 6.0, p - dir * 16.0,
		p - dir * 14.0 - side * 6.0, p + dir * 6.0 - side * 7.0])
	ci.draw_colored_polygon(hull, Color("#1f6f6a"))
	ci.draw_colored_polygon(PackedVector2Array([p - dir * 2.0 - side * 1.0, p - dir * 2.0 - side * 16.0, p + dir * 8.0 - side * 1.0]),
		Color("#e9fff6"))
	ci.draw_line(p - dir * 2.0, p - dir * 2.0 - side * 18.0, Color("#0b1f1a"), 1.4)
	ci.draw_colored_polygon(PackedVector2Array([p - dir * 2.0 - side * 18.0, p - dir * 2.0 - side * 24.0 + dir * 4.0,
		p - dir * 2.0 - side * 24.0 - dir * 4.0]), Color("#ff6a5c"))
	Art.pill(ci, p + Vector2(-26, 26), "patrouille" if patrol_routes.size() < 2 else "patrouille %d" % (idx + 1), Color(col, 0.9),
		Color("#0b1f1a"), 10, "ui_black")


func _link(a: String, b: String, col: Color, width: float, ttl: float, kind: String) -> void:
	if not agents.has(a) or not agents.has(b) or not animate:
		return
	effects.append({"kind": "link", "style": kind, "a": a, "b": b, "col": col, "w": width, "ttl": ttl, "max": ttl,
		"bend": randf_range(0.12, 0.22) * (1.0 if randf() < 0.5 else -1.0)})


func _mark(id: String, txt: String, col: Color, ttl: float) -> void:
	if not agents.has(id) or not animate:
		return
	effects = effects.filter(func(e): return not (e["kind"] == "mark" and e["a"] == id))
	effects.append({"kind": "mark", "a": id, "txt": txt, "col": col, "ttl": ttl, "max": ttl})


func _short(s: String, n: int) -> String:
	return s if s.length() <= n else s.substr(0, n - 1) + "…"


func _num(v: Variant) -> String:
	var f := float(v)
	return str(int(f)) if is_equal_approx(f, round(f)) else "%.1f" % f


# ================================================================== poissons
func _sync_fish(instant: bool) -> void:
	var area := 0
	for k in lake_cells.size():
		area += lake_cells[k].size()
	for k in lakes.size():
		var cells: Array = lake_cells[k] if k < lake_cells.size() else []
		var ratio := _ratio(k)
		var share := float(cells.size()) / float(maxi(area, 1))
		var target := 0 if (collapsed or lakes.size() > 1) and ratio < 0.05 else int(round(clamp(ratio, 0.0, 1.0) * 42.0 * share))
		var alive := fish.filter(func(f): return int(f["k"]) == k and not f["dying"])
		var tries := 0
		while alive.size() < target and not cells.is_empty() and tries < 200:
			tries += 1
			var q := _parcel_pos(cells[randi() % cells.size()]["c"]) + Vector2(randf_range(-0.4, 0.4), randf_range(-0.4, 0.4)) / PARCELS
			if water_at(q) < 0.65:
				continue
			var f := {"p": q, "ang": randf() * TAU, "sp": randf_range(0.012, 0.03), "a": 1.0 if instant else 0.0, "dying": false,
				"len": randf_range(7.0, 11.0), "wig": randf() * TAU, "k": k}
			fish.append(f)
			alive.append(f)
		var extra := alive.size() - target
		for f in alive:
			if extra <= 0:
				break
			f["dying"] = true
			if instant:
				f["a"] = 0.0
			extra -= 1
	fish = fish.filter(func(f): return not (f["dying"] and f["a"] <= 0.0))
	_push_lakes()


func _update_fish(dt: float) -> void:
	for f in fish:
		f["a"] = clamp(float(f["a"]) + (-dt * 0.8 if f["dying"] else dt * 0.6), 0.0, 1.0)
		f["ang"] = float(f["ang"]) + randf_range(-1.6, 1.6) * dt
		var v := Vector2(cos(f["ang"]), sin(f["ang"])) * float(f["sp"]) / world_k
		var nxt: Vector2 = f["p"] + v * dt
		if water_at(nxt) < 0.65 or _lake_at(nxt) != int(f["k"]):
			f["ang"] = float(f["ang"]) + PI * randf_range(0.6, 1.4)         # la rive : il fait demi-tour
		else:
			f["p"] = nxt
		f["wig"] = float(f["wig"]) + dt * 9.0
	fish = fish.filter(func(f): return not (f["dying"] and f["a"] <= 0.0))
	if stock_ratio > 0.3 and randf() < dt * 0.5 * stock_ratio and not fish.is_empty():
		var f: Dictionary = fish[randi() % fish.size()]
		splashes.append({"p": f["p"], "ttl": 1.0, "max": 1.0, "r": 10.0})


# ================================================================== animation
func _process(delta: float) -> void:
	_scroll(delta)               # la caméra bouge même en pause
	delta *= time_scale          # en pause tout s'arrête (bulles, barques, poissons), en accéléré tout va plus vite
	t += delta
	# lumière : heure simulée, et soirée forcée pendant la veillée
	var hour := fposmod(sim_time, 1.0) * 24.0
	var target := smoothstep(4.5, 7.5, hour) - smoothstep(17.5, 20.5, hour)
	if assembly_scope != "":
		target = min(target, 0.12)
	light = move_toward(light, target, delta * 2.0) if animate else target
	room_alpha = move_toward(room_alpha, 1.0 if assembly_scope == "valley" else 0.0, delta * (3.5 if animate else 100.0))
	dry = max(0.0, dry - delta * 0.004)
	_push_lakes()
	mat.set_shader_parameter("dry", dry)
	# déplacements
	for id in agents:
		var a: Dictionary = agents[id]
		var path: Array = a["path"]
		if path.is_empty():
			a["fishing"] = max(0.0, float(a["fishing"]) - delta)
			continue
		if float(a["hold"]) > 0.0:
			a["hold"] = float(a["hold"]) - delta
			a["fishing"] = 1.0
			if randf() < delta * 2.0:
				splashes.append({"p": a["pos"] + Vector2(randf_range(-0.01, 0.01), randf_range(-0.01, 0.01)),
					"ttl": 0.9, "max": 0.9, "r": 7.0})
			continue
		var target_p: Vector2 = path[0][0]
		var pos: Vector2 = a["pos"]
		var on_water := is_water(pos)
		var mult: float = float(path[0][2]) if path[0].size() > 2 else 1.0
		var step := (WATER_SPEED if on_water else LAND_SPEED) * delta * mult / world_k      # la même vitesse à l'écran
		var dvec := target_p - pos
		if dvec.length() > 0.0001:
			var sdv := _px(target_p) - _px(pos)           # le cap se lit à l'écran (la barque est écrasée de 0,62 : voir `_draw_boat`)
			a["heading"] = lerp_angle(float(a["heading"]), atan2(sdv.y / 0.62, sdv.x), delta * 8.0)
		if dvec.length() <= step:
			a["pos"] = target_p
			a["hold"] = float(path[0][1])
			path.pop_front()
			if float(a["hold"]) > 0.0:
				splashes.append({"p": target_p, "ttl": 1.4, "max": 1.4, "r": 18.0})
				if a.has("landed"):
					effects.append({"kind": "float", "a": id, "txt": "+%.1f t" % float(a["landed"]), "col": Art.PAPER,
						"ttl": 2.4, "max": 2.4})
		else:
			a["pos"] = pos + dvec.normalized() * step
		if on_water:
			a["wake_t"] = float(a["wake_t"]) + delta
			if float(a["wake_t"]) > 0.07:
				a["wake_t"] = 0.0
				wakes.append({"p": a["pos"], "ttl": 1.3, "max": 1.3, "h": float(a["heading"])})
	for arr in [effects, wakes, splashes, banners]:
		for e in arr:
			e["ttl"] = float(e["ttl"]) - delta
	effects = effects.filter(func(e): return e["ttl"] > 0.0)
	wakes = wakes.filter(func(e): return e["ttl"] > 0.0)
	splashes = splashes.filter(func(e): return e["ttl"] > 0.0)
	while not banners.is_empty() and (float(banners[0]["ttl"]) <= 0.0 or t - float(banners[0]["born"]) > 4.0):
		banners.pop_front()
	for k in banners.size():
		if k > 0:
			banners[k]["ttl"] = float(banners[k]["max"])   # seul le premier bandeau s'écoule
	for id in bubbles.keys():
		bubbles[id]["ttl"] = float(bubbles[id]["ttl"]) - delta
		if float(bubbles[id]["ttl"]) <= 0.0:
			bubbles.erase(id)
	_update_fish(delta)
	under.queue_redraw()
	shade.queue_redraw()
	lights.queue_redraw()
	top.queue_redraw()
	over.queue_redraw()


func _gui_input(event: InputEvent) -> void:
	var mb0 := event as InputEventMouseButton
	# la mini-carte : un clic ou un glisser centre la vue
	if mb0 and mb0.button_index == MOUSE_BUTTON_LEFT:
		mini_drag = mb0.pressed and _mini_rect().has_point(mb0.position)
		if mini_drag:
			_mini_goto(mb0.position)
			accept_event()
			return
	if event is InputEventMouseMotion and mini_drag:
		_mini_goto((event as InputEventMouseMotion).position)
		accept_event()
		return
	if mb0 and mb0.pressed and (mb0.button_index == MOUSE_BUTTON_WHEEL_UP or mb0.button_index == MOUSE_BUTTON_WHEEL_DOWN):
		zoom_at(mb0.position, 1.15 if mb0.button_index == MOUSE_BUTTON_WHEEL_UP else 1.0 / 1.15)
		accept_event()
		return
	if mb0 and (mb0.button_index == MOUSE_BUTTON_RIGHT or mb0.button_index == MOUSE_BUTTON_MIDDLE):
		dragging = mb0.pressed
		accept_event()
		return
	if event is InputEventMouseMotion and dragging:
		pan((event as InputEventMouseMotion).relative)
		return
	if event is InputEventMouseMotion:
		var h := _pick((event as InputEventMouseMotion).position)
		if h != hovered:
			hovered = h
			mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND if h != "" else Control.CURSOR_ARROW
	var mb := event as InputEventMouseButton
	if mb and mb.pressed and mb.button_index == MOUSE_BUTTON_LEFT:
		var best := _pick(mb.position)
		if best != "":
			agent_clicked.emit(best)


func _pick(pos: Vector2) -> String:
	var best := ""
	var bd := 20.0 * zoom
	for id in agents:
		var d := (_scr(agents[id]["pos"]) + Vector2(0, -9) * zoom).distance_to(pos)
		if d < bd:
			bd = d
			best = id
	return best


# ================================================================== dessin dynamique
## Une règle adoptée remplace celle de même portée, type et cible.
func _set_rule(n: Dictionary) -> void:
	for i in rules.size():
		var o: Dictionary = rules[i]
		if str(o.get("scope", "")) == str(n.get("scope", "")) and str(o.get("kind", "quota")) == str(n.get("kind", "quota")) \
				and str(o.get("target", "")) == str(n.get("target", "")):
			rules[i] = n
			return
	rules.append(n)


## Les réserves (zone hachurée, bouées et étiquette) et les lacs au repos (eau voilée, étiquette), tant que la règle court.
func _draw_rules(ci: CanvasItem) -> void:
	for r in rules:
		var kind := str(r.get("kind", "quota"))
		if kind != "reserve" and kind != "repos":
			continue
		if r.get("until_season") != null and int(r["until_season"]) < cur_season:
			continue
		var tg := str(r.get("target", ""))
		var c := Vector2.ZERO
		var rad := Vector2(0.05, 0.05) / world_k * 1.5
		var lbl := "réserve"
		var col := Color("#ffb347")
		if kind == "repos":
			var k := 0
			for i in lakes.size():
				if str(lakes[i].get("name", "")) == tg:
					k = i
			c = lakes[k]["c"]
			rad = lakes[k]["r"] * 1.05
			lbl = "au repos"
			col = Color("#9fc4e8")
			_ground_ellipse(ci, c, rad, Color(0.62, 0.72, 0.85, 0.30), 48)
		elif deco["docks"].has(tg):
			c = deco["docks"][tg]["tip"]
		else:
			var k := _lake_named(tg, 0)
			c = lakes[k]["c"]
			rad = lakes[k]["r"] * 0.55
			_ground_ellipse(ci, c, rad, Color(col, 0.10), 40)
		if kind == "reserve" and deco["docks"].has(tg):
			_ground_ellipse(ci, c, rad, Color(col, 0.16), 32)
		# le contour en balises : une bouée tous les quinze degrés
		for i in 24:
			var a := TAU * float(i) / 24.0
			var q := _px(c + Vector2(cos(a) * rad.x, sin(a) * rad.y))
			if kind == "repos" and i % 2 == 1:
				continue
			ci.draw_circle(q, 3.0, Color(col, 0.95))
			ci.draw_circle(q, 1.5, Color(1, 1, 1, 0.9))
		if kind == "reserve":              # des hachures dans la zone
			for i in range(-4, 5):
				var d := float(i) / 4.0
				var a0 := _px(c + Vector2(d - 0.45, d + 0.45) * rad * 0.7)
				var b0 := _px(c + Vector2(d + 0.45, d - 0.45) * rad * 0.7)
				ci.draw_line(a0, b0, Color(col, 0.55), 1.5)
		Art.pill(ci, _px(c) + Vector2(0, -14), lbl, Color(0.08, 0.1, 0.16, 0.85), col, 11, "ui_bold", true)


func _draw_under(ci: CanvasItem) -> void:
	_draw_rules(ci)
	if lakes.size() > 1:
		for lk in lakes:
			ci.draw_string(Art.font("title_italic"), _px(lk["c"]) + Vector2(-70, 5), str(lk["label"]), HORIZONTAL_ALIGNMENT_CENTER, 140,
				15, Color(1, 1, 1, 0.38))
	for w in wakes:
		var a: float = float(w["ttl"]) / float(w["max"])
		var p := _px(w["p"])
		var side := Vector2(-sin(w["h"]), cos(w["h"]) * 0.62) * (4.0 + (1.0 - a) * 9.0)
		ci.draw_circle(p + side, 1.6 * a + 0.6, Color(1, 1, 1, 0.35 * a))
		ci.draw_circle(p - side, 1.6 * a + 0.6, Color(1, 1, 1, 0.35 * a))
	for f in fish:
		var p := _px(f["p"])
		var ang: float = f["ang"]
		var L: float = f["len"]
		var gd := Vector2(cos(ang), sin(ang))                                            # le sens du poisson dans le sol, puis à l'écran
		var dir := Vector2((gd.x - gd.y) * iso_a, (gd.x + gd.y) * iso_b).normalized()
		var side := Vector2(-dir.y, dir.x)
		var wig := sin(f["wig"]) * 0.35
		var col := Color(0.03, 0.12, 0.16, 0.42 * float(f["a"]))
		var body := PackedVector2Array()
		for i in 10:
			var u := float(i) / 9.0 * TAU
			body.append(p + dir * cos(u) * L * 0.5 + side * sin(u) * L * 0.18)
		ci.draw_colored_polygon(body, col)
		var tb := p - dir * L * 0.45
		var td := dir.rotated(wig)
		var ts := Vector2(-td.y, td.x)
		ci.draw_colored_polygon(PackedVector2Array([tb, tb - td * L * 0.35 + ts * L * 0.22, tb - td * L * 0.35 - ts * L * 0.22]), col)
	for s in splashes:
		var a: float = float(s["ttl"]) / float(s["max"])
		var p := _px(s["p"])
		var r: float = float(s["r"]) * (1.15 - a)
		ci.draw_set_transform(p, 0.0, Vector2(1.0, 0.55))            # un rond sur l'eau, vu en perspective
		ci.draw_arc(Vector2.ZERO, r, 0, TAU, 28, Color(1, 1, 1, 0.55 * a), 1.4, true)
		ci.draw_arc(Vector2.ZERO, r * 0.55, 0, TAU, 20, Color(1, 1, 1, 0.35 * a), 1.0, true)
		ci.draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)
	_draw_patrol(ci)


func _darkness() -> float:
	return clamp(1.0 - light, 0.0, 1.0)


func _draw_shade(ci: CanvasItem) -> void:
	var dk := _darkness()
	var dusk: float = clamp(1.0 - absf(light - 0.5) * 2.2, 0.0, 1.0)
	if dusk > 0.01:
		ci.draw_rect(Rect2(Vector2.ZERO, world), Color(DUSK, 0.16 * dusk), true)
	if dk > 0.01:
		ci.draw_rect(Rect2(Vector2.ZERO, world), Color(NIGHT, 0.62 * smoothstep(0.15, 1.0, dk)), true)


func _draw_lights(ci: CanvasItem) -> void:
	var dk := smoothstep(0.25, 0.9, _darkness())
	if dk <= 0.01:
		return
	for hs in deco["houses"]:
		var fl := 0.85 + 0.15 * sin(t * 3.0 + float(hs["seed"]) * 20.0)
		Art.glow(ci, hs["p"], 34.0 if not hs.get("elder", false) else 60.0, Color(1.0, 0.62, 0.28, 0.42 * dk * fl))
	for h in deco["docks"]:
		Art.glow(ci, _px(deco["docks"][h]["tip"]), 26.0, Color(1.0, 0.75, 0.4, 0.45 * dk))
	var ff := 0.8 + 0.2 * sin(t * 11.0) * sin(t * 7.3)
	Art.glow(ci, _fire_pos(), 80.0, Color(1.0, 0.5, 0.18, 0.55 * dk * ff))
	for h in hamlet_fires:
		Art.glow(ci, _px(hamlet_pos[h]), 95.0, Color(1.0, 0.5, 0.18, 0.55 * dk * ff))
	# reflet de lune sur le lac
	var mp := _px(council_c + Vector2(0.10, -0.07) / world_k)
	ci.draw_set_transform(mp, -0.35, Vector2(1.8, 0.55))
	Art.glow(ci, Vector2.ZERO, 70.0, Color(0.55, 0.65, 0.9, 0.22 * dk))
	ci.draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)
	for f in deco["flies"]:
		var ph: float = float(f["ph"]) + t * float(f["sp"])
		var p: Vector2 = f["base"] + Vector2(sin(ph * 1.3) * 18.0, cos(ph) * 14.0)
		var tw := 0.5 + 0.5 * sin(ph * 5.0)
		Art.glow(ci, p, 6.0, Color(0.85, 1.0, 0.5, 0.75 * dk * tw))


func _draw_fire(ci: CanvasItem, p: Vector2, s: float) -> void:
	var f1 := 1.0 + 0.12 * sin(t * 13.0) + 0.08 * sin(t * 21.0)
	for layer in [[Color("#e2461f"), 1.0], [Color("#ff9a2e"), 0.7], [Color("#ffe08a"), 0.4]]:
		var col: Color = layer[0]
		var k: float = layer[1] * s
		var pts := PackedVector2Array()
		for i in 12:
			var a := TAU * i / 12.0
			var r: float = 6.0 * k * (1.0 + 0.6 * maxf(0.0, -sin(a))) * (f1 if sin(a) < 0 else 1.0)
			pts.append(p + Vector2(cos(a) * 5.5 * k, sin(a) * r))
		ci.draw_colored_polygon(pts, col)


func _draw_room(ci: CanvasItem) -> void:
	var a := room_alpha
	if a <= 0.01:
		return
	ci.draw_rect(Rect2(Vector2.ZERO, world), Color(0.02, 0.03, 0.07, 0.45 * a), true)
	var r := Rect2(_sp(ROOM.position), Vector2(ROOM.size.x * size.x, ROOM.size.y * size.y))
	var sb := Art.box(Color(Color("#4a3123"), 0.96 * a), 26, Color(Color("#22150e"), a), 6, 24)
	sb.draw(ci.get_canvas_item(), r)
	# plancher
	var y := r.position.y + 14.0
	var row := 0
	while y < r.end.y - 10.0:
		ci.draw_line(Vector2(r.position.x + 10, y), Vector2(r.end.x - 10, y), Color(0, 0, 0, 0.22 * a), 1.0)
		var x := r.position.x + 30.0 + fmod(row * 97.0, 160.0)
		while x < r.end.x - 20:
			ci.draw_line(Vector2(x, y), Vector2(x, y + 22), Color(0, 0, 0, 0.18 * a), 1.0)
			x += 160.0
		y += 22.0
		row += 1
	# tapis, foyer
	var c := _px(council_c)
	_ground_ellipse(ci, council_c, council_r * 1.12, Color(Color("#6e2a26"), 0.95 * a), 64)         # le tapis, posé sur le sol
	_ground_ellipse(ci, council_c, council_r * 1.06, Color(Color("#8c3a31"), 0.95 * a), 64)
	var ring := PackedVector2Array()
	for i in 65:
		var ang := TAU * i / 64.0
		ring.append(_px(council_c + Vector2(cos(ang) * council_r.x * 0.95, sin(ang) * council_r.y * 0.95)))
	ci.draw_polyline(ring, Color(Color("#d8a957"), 0.55 * a), 2.0, true)
	_ground_ellipse(ci, council_c, council_r * 0.55, Color(Color("#7a302a"), 0.9 * a), 48)
	Art.glow(ci, c, council_r.x * iso_a * 0.9, Color(1.0, 0.55, 0.2, 0.30 * a))
	for i in 10:
		var ang := TAU * i / 10.0
		ci.draw_circle(c + Vector2(cos(ang) * 22, sin(ang) * 11), 5.0, Color(Color("#6f6a64"), a))
	_draw_fire(ci, c - Vector2(0, 4), 1.8 * a)
	# coussins aux places de la veillée
	var n_seats := seats if seats > 0 else agents.size()
	for i in n_seats:
		var ang := -PI / 2.0 + TAU * float(i) / float(max(n_seats, 1))
		var sp := _px(council_c + Vector2(cos(ang), sin(ang)) * council_r)
		_ellipse(ci, sp + Vector2(0, 3), Vector2(19, 10), Color(Color("#2a1a12"), 0.55 * a))
		_ellipse(ci, sp, Vector2(18, 9), Color(Color("#b0823f"), 0.9 * a))
	var away := 0
	for aid in agents:
		if bool(agents[aid].get("absent", false)) and str(agents[aid]["info"].get("role", "")) != "ancien":
			away += 1
	if away > 0:
		ci.draw_string(Art.font("ui"), Vector2(r.position.x + 26, r.end.y - 18), "%d villageois attendent chez eux" % away,
			HORIZONTAL_ALIGNMENT_LEFT, 250, 13, Color(Color("#d8bf8c"), 0.85 * a))
	var title := "Veillée chez Maître Oswin"
	var tf := Art.font("title")
	ci.draw_string(tf, Vector2(r.position.x, r.position.y + 40), title, HORIZONTAL_ALIGNMENT_CENTER, r.size.x, 24,
		Color(Color("#f3dca8"), a))
	ci.draw_string(Art.font("title_italic"), Vector2(r.position.x, r.position.y + 62),
		"« La parole se donne le soir, le poisson se prend le matin. »", HORIZONTAL_ALIGNMENT_CENTER, r.size.x, 14,
		Color(Color("#d8bf8c"), 0.8 * a))


func _bez_pts(pa: Vector2, pb: Vector2, bend: float, n: int = 22) -> PackedVector2Array:
	return _curve(pa, pb, bend, n)


func _draw_links(ci: CanvasItem) -> void:
	for e in effects:
		var a: float = clamp(float(e["ttl"]) / float(e["max"]), 0.0, 1.0)
		if e["kind"] == "link" and agents.has(e["a"]) and agents.has(e["b"]):
			var pa := _px(agents[e["a"]]["pos"])
			var pb := _px(agents[e["b"]]["pos"])
			var dir := (pb - pa).normalized()
			pa += dir * 14.0
			pb -= dir * 16.0
			var pts := _bez_pts(pa, pb, float(e["bend"]))
			var col: Color = e["col"]
			var w: float = e["w"]
			var life := 1.0 - a
			if e["style"] == "accuse":
				w += 1.5 * sin(t * 10.0)
			if e["style"] == "support":
				for i in range(0, pts.size() - 1, 2):
					ci.draw_line(pts[i], pts[i + 1], Color(col, 0.9 * a), w, true)
			else:
				ci.draw_polyline(pts, Color(col, 0.25 * a), w + 4.0, true)
				ci.draw_polyline(pts, Color(col, 0.9 * a), w, true)
			# pointe
			var tip := pts[pts.size() - 1]
			var tdir := (tip - pts[pts.size() - 3]).normalized()
			var side := Vector2(-tdir.y, tdir.x) * (5.0 + w)
			ci.draw_colored_polygon(PackedVector2Array([tip + tdir * 6.0, tip - tdir * 5.0 + side, tip - tdir * 5.0 - side]),
				Color(col, a))
			# messager qui voyage le long du lien
			var u: float = clamp(life / 0.35, 0.0, 1.0)
			if u < 1.0:
				var k := int(u * (pts.size() - 1))
				var q := pts[k]
				Art.glow(ci, q, 14.0, Color(col, 0.8))
				ci.draw_circle(q, 3.5, Color(1, 1, 1, 0.95))
		elif e["kind"] == "wave" and agents.has(e["a"]):
			var pw := _px(agents[e["a"]]["pos"])
			for k in 2:
				var aa: float = clamp(a * 1.4 - k * 0.3, 0.0, 1.0)
				ci.draw_arc(pw, 16.0 + (1.0 - a) * (46.0 + k * 22.0), 0, TAU, 48, Color(Art.TALK, aa * 0.7), 2.0, true)


const BOAT_SCALE := {"barque": 0.78, "chaloupe": 1.0, "cotre": 1.3}


func _draw_boat(ci: CanvasItem, origin: Vector2, heading: float, col: Color, fishing: float, k: float = 1.0) -> void:
	ci.draw_set_transform(origin, 0.0, Vector2(1.0, 0.62))                # la barque est un plan sur l'eau : écrasée comme le sol
	_draw_boat_local(ci, heading, col, fishing, k)
	ci.draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)


func _draw_boat_local(ci: CanvasItem, heading: float, col: Color, fishing: float, k: float) -> void:
	var p := Vector2.ZERO
	var dir := Vector2(cos(heading), sin(heading))
	var side := Vector2(-dir.y, dir.x)
	var L := 21.0 * k
	var W := 8.5 * k
	var hull := PackedVector2Array([p + dir * L, p + dir * L * 0.4 + side * W, p - dir * L * 0.8 + side * W * 0.85,
		p - dir * L * 0.9, p - dir * L * 0.8 - side * W * 0.85, p + dir * L * 0.4 - side * W])
	var shadow := PackedVector2Array()
	for q in hull:
		shadow.append(q + Vector2(2, 3))
	ci.draw_colored_polygon(shadow, Color(0, 0, 0, 0.3))
	ci.draw_colored_polygon(hull, Color("#7b5434"))
	var inner := PackedVector2Array()
	for q in hull:
		inner.append(p + (q - p) * 0.72)
	ci.draw_colored_polygon(inner, Color("#a87a4c"))
	ci.draw_line(p + side * W * 0.7, p - side * W * 0.7, Color("#6a4529"), 1.5)
	if fishing > 0.0:
		var c := p - dir * 6.0 + side * 16.0
		var tt := t * 2.0
		for i in 6:
			var a := TAU * i / 6.0 + tt * 0.3
			ci.draw_circle(c + Vector2(cos(a), sin(a)) * 9.0, 1.4, Color(1, 1, 1, 0.7 * fishing))
		ci.draw_arc(c, 9.0, 0, TAU, 24, Color(1, 1, 1, 0.35 * fishing), 1.0, true)
		ci.draw_line(p - dir * 4.0, c + Vector2(-9, 0).rotated(heading), Color(1, 1, 1, 0.4 * fishing), 1.0)


func _draw_tokens(ci: CanvasItem) -> void:
	var f := Art.font("ui_bold")
	var by_y := order.duplicate()
	by_y.sort_custom(func(x, y): return _px(agents[x]["pos"]).y < _px(agents[y]["pos"]).y)
	for id in by_y:
		var a: Dictionary = agents[id]
		var p := _px(a["pos"])
		var info: Dictionary = a["info"]
		if assembly_scope == "valley" and bool(a.get("absent", false)):
			continue
		var on_water := is_water(a["pos"]) and assembly_scope != "valley"
		if on_water:
			_draw_boat(ci, p, float(a["heading"]), Art.agent_color(info), float(a["fishing"]),
				float(BOAT_SCALE.get(str(info.get("boat", "chaloupe")), 1.0)))
		else:                                   # à terre, le pion se tient debout : son ombre est sur le sol
			_ellipse(ci, p + Vector2(2, 1), Vector2(12, 5), Color(0, 0, 0, 0.28))
		var stand := Vector2(0, -7) if on_water else Vector2(0, -10)
		Art.draw_token(ci, p + stand, info, 0.78 if on_water else 1.0, 1.0, id == selected, t)
		if bool(a.get("rep", false)):           # l'élu de son village au conseil : un astre doré
			_star(ci, p + stand + Vector2(0, -24 if not on_water else -22), 6.5, Color("#f2c14e"), 5)
		if bool(a.get("banned", false)):        # interdit de pêche : un anneau barré rouge
			var q := p + stand
			ci.draw_arc(q, 15.0, 0, TAU, 28, Art.ACCUSE, 2.2, true)
			ci.draw_line(q + Vector2(-10, -10), q + Vector2(10, 10), Art.ACCUSE, 2.2, true)
		var first := str(info.get("name", id)).split(" ")[0]
		var lbl := first if id != hovered else "%s · %s" % [str(info.get("name", id)), str(info.get("archetype_label", ""))]
		var fs := 11
		var tw := f.get_string_size(lbl, HORIZONTAL_ALIGNMENT_LEFT, -1, fs).x + 10
		var lr := Rect2(p + Vector2(-tw / 2.0, 7), Vector2(tw, fs + 6))
		Art.box(Color(0.05, 0.07, 0.12, 0.72 if id != hovered else 0.92), 8).draw(ci.get_canvas_item(), lr)
		ci.draw_string(f, lr.position + Vector2(5, fs + 1.5), lbl, HORIZONTAL_ALIGNMENT_LEFT, -1, fs,
			Art.INK if id != selected else Color("#ffffff"))
		if badges.has(id):
			Art.pill(ci, p + Vector2(15, -34), badges[id], Art.PROPOSAL, Color("#2a1d05"), 11)


func _draw_marks(ci: CanvasItem) -> void:
	var f := Art.font("ui_black")
	for e in effects:
		if not agents.has(e["a"]):
			continue
		var a: float = clamp(float(e["ttl"]) / float(e["max"]), 0.0, 1.0)
		var pm := _px(agents[e["a"]]["pos"])
		if e["kind"] == "mark":
			var pop: float = 1.0 + 0.25 * max(0.0, 1.0 - (1.0 - a) * float(e["max"]) * 4.0)
			var col: Color = e["col"]
			Art.pill(ci, pm + Vector2(-14, -40) * pop, e["txt"], Color(col, 0.95 * a), Color(Color("#10131c"), a), 11, "ui_black")
		elif e["kind"] == "float":
			var y := -22.0 - (1.0 - a) * 26.0
			ci.draw_string(f, pm + Vector2(-31, y + 1), e["txt"], HORIZONTAL_ALIGNMENT_CENTER, 60, 13, Color(0, 0, 0, 0.5 * a))
			ci.draw_string(f, pm + Vector2(-30, y), e["txt"], HORIZONTAL_ALIGNMENT_CENTER, 60, 13, Color(Color("#fff3c4"), a))


func _draw_bubbles(ci: CanvasItem) -> void:
	var f := Art.font("ui")
	var fb := Art.font("ui_black")
	var placed: Array = []
	if room_alpha > 0.5:     # le titre de la salle reste lisible
		var rt := Rect2(cam_off + _sp(ROOM.position) * zoom, Vector2(ROOM.size.x * size.x, 70) * zoom)
		placed.append(Rect2(rt.position + Vector2(rt.size.x * 0.25, 10), Vector2(rt.size.x * 0.5, 60)))
	var ids := bubbles.keys()
	ids.sort_custom(func(x, y): return float(bubbles[x]["born"]) < float(bubbles[y]["born"]))
	for id in ids:
		if not agents.has(id):
			continue
		var b: Dictionary = bubbles[id]
		var a: float = clamp(float(b["ttl"]) / 0.6, 0.0, 1.0) * clamp((t - float(b["born"])) / 0.2, 0.0, 1.0)
		var pb := _scr(agents[id]["pos"]) + Vector2(0, -10) * zoom
		var info: Dictionary = agents[id]["info"]
		var w := 196.0
		var fs := 12
		var head := str(info.get("name", id)).split(" ")[0]
		var to := str(b["to"])
		head += "  →  " + (str(agents[to]["info"].get("name", to)).split(" ")[0] if agents.has(to) else "tous")
		var sz := f.get_multiline_string_size(b["text"], HORIZONTAL_ALIGNMENT_LEFT, w, fs)
		var bs := Vector2(w + 18, sz.y + 30)
		var cands := [Vector2(-bs.x / 2, -bs.y - 30), Vector2(-bs.x / 2, 40), Vector2(24, -bs.y / 2),
			Vector2(-bs.x - 24, -bs.y / 2), Vector2(18, -bs.y - 18), Vector2(-bs.x - 18, -bs.y - 18),
			Vector2(18, 26), Vector2(-bs.x - 18, 26)]
		# vers l'intérieur du cercle d'abord pendant la veillée, pour garder le bord libre
		if assembly_scope == "valley":
			var inward := (_scr(council_c) - pb).normalized()
			cands.sort_custom(func(x, y): return (x + bs / 2).normalized().dot(inward) > (y + bs / 2).normalized().dot(inward))
		# position qui chevauche le moins les bulles déjà posées (zéro si possible)
		var rect := Rect2(pb + cands[0], bs)
		var best_cost := INF
		for off in cands:
			var r := Rect2(pb + off, bs)
			var cost := 0.0
			if r.position.x < 4 or r.position.y < 70 or r.end.x > size.x - 4 or r.end.y > size.y - 64:
				cost += 1e6
			for q in placed:
				var inter: Rect2 = r.grow(4).intersection(q)
				cost += inter.get_area()
			if cost < best_cost:
				best_cost = cost
				rect = r
			if cost == 0.0:
				break
		rect.position.x = clamp(rect.position.x, 4.0, size.x - rect.size.x - 4.0)
		rect.position.y = clamp(rect.position.y, 4.0, size.y - rect.size.y - 4.0)
		placed.append(rect)
		var col := Art.agent_color(info)
		# queue de la bulle
		var anchor := Vector2(clamp(pb.x, rect.position.x + 14, rect.end.x - 14), clamp(pb.y, rect.position.y + 10, rect.end.y - 10))
		var tdir := (pb - anchor).normalized()
		var side := Vector2(-tdir.y, tdir.x) * 7.0
		ci.draw_colored_polygon(PackedVector2Array([anchor + side, anchor - side, pb - tdir * 14.0]), Color(Art.PAPER, 0.97 * a))
		Art.box(Color(Art.PAPER, 0.97 * a), 10, Color(col, a), 0, 8).draw(ci.get_canvas_item(), rect)
		ci.draw_rect(Rect2(rect.position + Vector2(0, 8), Vector2(3, rect.size.y - 16)), Color(col, a), true)
		ci.draw_string(fb, rect.position + Vector2(10, 17), head, HORIZONTAL_ALIGNMENT_LEFT, w, 11, Color(col.darkened(0.35), a))
		ci.draw_multiline_string(f, rect.position + Vector2(10, 33), b["text"], HORIZONTAL_ALIGNMENT_LEFT, w, fs, -1,
			Color(Art.PAPER_INK, a))


func _draw_signs(ci: CanvasItem) -> void:
	var sa := 1.0 - room_alpha
	if sa <= 0.01:
		return
	var tf := Art.font("title")
	for h in hamlet_pos:
		var c := _px(hamlet_pos[h]) + Vector2(0, -96)
		var w := tf.get_string_size(h, HORIZONTAL_ALIGNMENT_LEFT, -1, 17).x + 24
		var r := Rect2(c - Vector2(w / 2, 0), Vector2(w, 26))
		Art.box(Color(0.10, 0.08, 0.06, 0.72 * sa), 6, Color(Art.HAMLET.get(h, Color("#d8bf8c")), 0.95 * sa), 2).draw(ci.get_canvas_item(), r)
		ci.draw_string(tf, r.position + Vector2(12, 19), h, HORIZONTAL_ALIGNMENT_LEFT, -1, 17, Color(Color("#f3e3bd"), sa))
	var ep := _px(elder_pos) + Vector2(0, -50)
	var lbl := "Chez l'ancien"
	var w2 := tf.get_string_size(lbl, HORIZONTAL_ALIGNMENT_LEFT, -1, 15).x + 22
	var r2 := Rect2(ep - Vector2(w2 / 2, 0), Vector2(w2, 24))
	Art.box(Color(0.10, 0.08, 0.06, 0.72 * sa), 6, Color(Color("#d8bf8c"), 0.5 * sa), 1).draw(ci.get_canvas_item(), r2)
	ci.draw_string(tf, r2.position + Vector2(11, 18), lbl, HORIZONTAL_ALIGNMENT_LEFT, -1, 15, Color(Color("#f3e3bd"), sa))


func _draw_hud(ci: CanvasItem) -> void:
	var f := Art.font("ui")
	var fb := Art.font("ui_bold")
	var tf := Art.font("title")
	# horloge
	var season := int(floor(sim_time / max(season_days, 1.0))) + 1
	var day_f := sim_time - (season - 1) * season_days
	var day := int(day_f)
	var minutes := int(fposmod(sim_time, 1.0) * 1440.0)
	var card := Rect2(Vector2(14, 14), Vector2(236, 58))
	Art.box(Color(0.05, 0.07, 0.12, 0.82), 14, Art.LINE, 1, 10).draw(ci.get_canvas_item(), card)
	var ic := card.position + Vector2(29, 29)
	if light > 0.45:
		for i in 8:
			var a := TAU * i / 8.0 + t * 0.2
			ci.draw_line(ic + Vector2(cos(a), sin(a)) * 13.0, ic + Vector2(cos(a), sin(a)) * 17.0, Color("#ffd166"), 2.0, true)
		ci.draw_circle(ic, 10.0, Color("#ffd166"))
	else:
		ci.draw_circle(ic, 11.0, Color("#e8ecff"))
		ci.draw_circle(ic + Vector2(5, -4), 9.5, Color(0.05, 0.07, 0.12))
	ci.draw_string(tf, card.position + Vector2(54, 27), "Saison %d · Jour %d" % [season, day], HORIZONTAL_ALIGNMENT_LEFT, -1, 19,
		Art.INK)
	ci.draw_string(fb, card.position + Vector2(55, 47), "%02d:%02d" % [minutes / 60, minutes % 60], HORIZONTAL_ALIGNMENT_LEFT, -1, 12,
		Art.MUTED)
	if phase != "":
		var pc := Art.TALK if phase == "Veillée" else (Color("#7fd0e8") if phase == "Pêche" else Art.MUTED)
		Art.pill(ci, card.position + Vector2(100, 34), phase, Color(pc, 0.22), pc, 11)
	if paused:
		ci.draw_rect(Rect2(Vector2.ZERO, size), Color(0.03, 0.04, 0.09, 0.28), true)
		var pr := Rect2(Vector2(size.x - 146 - (354.0 if lakes.size() > 1 else 0.0), 16), Vector2(130, 40))
		Art.box(Color(0.05, 0.07, 0.12, 0.92), 14, Color(Art.PROPOSAL, 0.8), 1, 10).draw(ci.get_canvas_item(), pr)
		ci.draw_rect(Rect2(pr.position + Vector2(16, 12), Vector2(5, 16)), Art.PROPOSAL, true)
		ci.draw_rect(Rect2(pr.position + Vector2(26, 12), Vector2(5, 16)), Art.PROPOSAL, true)
		ci.draw_string(tf, pr.position + Vector2(42, 27), "En pause", HORIZONTAL_ALIGNMENT_LEFT, -1, 18, Art.INK)
	# jauge du lac
	var gw := 330.0
	if lakes.size() > 1:
		_draw_lake_gauges(ci, gw)
		_draw_banner(ci)
		return
	var g := Rect2(Vector2(size.x / 2 - gw / 2, size.y - 60), Vector2(gw, 48))
	Art.box(Color(0.05, 0.07, 0.12, 0.84), 14, Art.LINE, 1, 10).draw(ci.get_canvas_item(), g)
	ci.draw_string(tf, g.position + Vector2(14, 21), "Lac de Vellmor", HORIZONTAL_ALIGNMENT_LEFT, -1, 16, Art.INK)
	var txt := "%.0f / %.0f t" % [stock_t, capacity]
	if collapsed:
		txt = "effondré · " + txt
	ci.draw_string(fb, g.position + Vector2(0, 20), txt, HORIZONTAL_ALIGNMENT_RIGHT, gw - 14, 13,
		Art.ACCUSE if collapsed else Art.INK)
	var bar := Rect2(g.position + Vector2(14, 30), Vector2(gw - 28, 8))
	Art.box(Color(1, 1, 1, 0.08), 4).draw(ci.get_canvas_item(), bar)
	var hc := Color("#8a7a4c").lerp(Color("#3fb6c9"), clamp(stock_ratio * 1.2, 0.0, 1.0))
	var fillw: float = bar.size.x * clamp(stock_ratio, 0.0, 1.0)
	if fillw > 2:
		Art.box(hc, 4).draw(ci.get_canvas_item(), Rect2(bar.position, Vector2(fillw, bar.size.y)))
	var mx := bar.position.x + bar.size.x * 0.5
	ci.draw_line(Vector2(mx, bar.position.y - 3), Vector2(mx, bar.end.y + 3), Color(1, 1, 1, 0.75), 1.5)
	ci.draw_string(f, Vector2(mx + 4, bar.position.y - 2), "moitié", HORIZONTAL_ALIGNMENT_LEFT, -1, 9, Color(1, 1, 1, 0.55))
	_draw_banner(ci)


## Plusieurs lacs : une ligne par lac (son nom, ses tonnes, sa barre), au bas de la carte.
func _draw_lake_gauges(ci: CanvasItem, gw: float) -> void:
	var f := Art.font("ui")
	var fb := Art.font("ui_bold")
	var n := lakes.size()
	var g := Rect2(Vector2(size.x - gw - 14, 14), Vector2(gw, 14 + 22 * n))
	Art.box(Color(0.05, 0.07, 0.12, 0.84), 14, Art.LINE, 1, 10).draw(ci.get_canvas_item(), g)
	for k in n:
		var lk: Dictionary = lakes[k]
		var y := g.position.y + 8 + 22 * k
		var ratio := _ratio(k)
		ci.draw_string(fb, Vector2(g.position.x + 14, y + 11), str(lk["label"]), HORIZONTAL_ALIGNMENT_LEFT, -1, 12, Art.INK)
		ci.draw_string(f, Vector2(g.position.x, y + 11), "%.0f / %.0f t" % [ratio * float(lk["capacity"]), float(lk["capacity"])],
			HORIZONTAL_ALIGNMENT_RIGHT, gw - 14, 11, Art.ACCUSE if ratio < 0.05 else Art.MUTED)
		var bar := Rect2(Vector2(g.position.x + 14, y + 15), Vector2(gw - 28, 6))
		Art.box(Color(1, 1, 1, 0.08), 3).draw(ci.get_canvas_item(), bar)
		var fillw: float = bar.size.x * clamp(ratio, 0.0, 1.0)
		if fillw > 2:
			Art.box(Color("#8a7a4c").lerp(Color("#3fb6c9"), clamp(ratio * 1.2, 0.0, 1.0)), 3).draw(ci.get_canvas_item(),
				Rect2(bar.position, Vector2(fillw, bar.size.y)))
		var mx := bar.position.x + bar.size.x * 0.5
		ci.draw_line(Vector2(mx, bar.position.y - 2), Vector2(mx, bar.end.y + 2), Color(1, 1, 1, 0.6), 1.2)


func _draw_banner(ci: CanvasItem) -> void:
	var f := Art.font("ui")
	var tf := Art.font("title")
	if not banners.is_empty():
		var bn: Dictionary = banners[0]
		var life: float = float(bn["max"]) - float(bn["ttl"])
		var a: float = clamp(life / 0.3, 0.0, 1.0) * clamp(float(bn["ttl"]) / 0.5, 0.0, 1.0)
		var col: Color = bn["col"]
		var tw: float = max(tf.get_string_size(bn["title"], HORIZONTAL_ALIGNMENT_LEFT, -1, 28).x,
			f.get_string_size(bn["sub"], HORIZONTAL_ALIGNMENT_LEFT, -1, 14).x) + 60
		var bx := size.x / 2 - tw / 2
		if lakes.size() > 1:               # jamais sur les jauges des lacs (haut droite)
			bx = clampf(bx, 262.0, size.x - 354.0 - 10.0 - tw)
		var br := Rect2(Vector2(bx, 18 - (1.0 - a) * 10.0), Vector2(tw, 66))
		Art.box(Color(0.05, 0.07, 0.12, 0.9 * a), 16, Color(col, 0.7 * a), 1, 14).draw(ci.get_canvas_item(), br)
		ci.draw_rect(Rect2(br.position + Vector2(24, 62), Vector2(tw - 48, 2)), Color(col, 0.8 * a), true)
		ci.draw_string(tf, br.position + Vector2(0, 34), bn["title"], HORIZONTAL_ALIGNMENT_CENTER, tw, 28, Color(col.lightened(0.3), a))
		ci.draw_string(f, br.position + Vector2(0, 54), bn["sub"], HORIZONTAL_ALIGNMENT_CENTER, tw, 14, Color(Art.INK, 0.85 * a))


## Le dessus du monde (il suit la caméra) : panneaux, salle de la veillée, feux, liens, pions, étiquettes ; et les mailles (touche G).
func _draw_top(ci: CanvasItem) -> void:
	_draw_mesh(ci)
	_draw_signs(ci)
	_draw_room(ci)
	for h in hamlet_fires:
		_draw_fire(ci, _px(hamlet_pos[h]), 1.2)
	if room_alpha < 0.5:
		_draw_fire(ci, _fire_pos(), 0.9 * (0.4 + 0.6 * _darkness()))
	_draw_links(ci)
	_draw_tokens(ci)
	_draw_marks(ci)


## À l'écran, par-dessus : les bulles (lisibles quel que soit le zoom), les cadrans, les bandeaux.
func _draw_over(ci: CanvasItem) -> void:
	_draw_bubbles(ci)
	_draw_hud(ci)
	_draw_mini(ci)
	var f := Art.font("ui")
	var lines := ["molette : zoom  ·  clic droit : glisser", "flèches : défiler  ·  G : mailles  ·  Origine : recadrer"]
	if show_mesh:
		lines = ["Mailles du monde (G pour les cacher) :", "personnages : %d × %d pas" % [n_steps, n_steps],
			"maisons : %d × %d lots, obstacles en rouge" % [n_lots, n_lots], "lacs : %d × %d parcelles" % [PARCELS, PARCELS],
			"chance d'une parcelle : vert bon coin, rouge mauvais"]
	for i in lines.size():
		var y := size.y - 14.0 - 15.0 * float(lines.size() - 1 - i)
		ci.draw_string(f, Vector2(15, y + 1), lines[i], HORIZONTAL_ALIGNMENT_LEFT, -1, 11, Color(0, 0, 0, 0.6))
		ci.draw_string(f, Vector2(14, y), lines[i], HORIZONTAL_ALIGNMENT_LEFT, -1, 11, Color(1, 1, 1, 0.75))


## La mini-carte, en bas à droite de l'écran : le losange de la vallée, à l'échelle k.
func _mini_rect() -> Rect2:
	var w := clampf(size.x * 0.17, 130.0, 230.0)
	var h := w * iso_b / iso_a
	return Rect2(size.x - w - 14.0, size.y - h - 14.0, w, h)


## Un point du monde (pixels du calque) → la mini-carte.
func _mini_pt(p: Vector2, r: Rect2) -> Vector2:
	return r.position + (p - (iso_o - Vector2(iso_a, 0.0))) * (r.size.x / (2.0 * iso_a))


func _mini_goto(pos: Vector2) -> void:
	glide = false
	var r := _mini_rect()
	var wp := (pos - r.position) * (2.0 * iso_a / r.size.x) + iso_o - Vector2(iso_a, 0.0)
	cam_off = size * 0.5 - wp * zoom
	_apply_cam()


func _draw_mini(ci: CanvasItem) -> void:
	var r := _mini_rect()
	var gp := PackedVector2Array([_mini_pt(_px(Vector2(0, 0)), r), _mini_pt(_px(Vector2(1, 0)), r), _mini_pt(_px(Vector2(1, 1)), r),
		_mini_pt(_px(Vector2(0, 1)), r)])
	ci.draw_rect(r.grow(5.0), Color(0.05, 0.07, 0.05, 0.55), true)
	ci.draw_colored_polygon(gp, Color(0.30, 0.45, 0.24))
	for i in PARCELS:
		for j in PARCELS:
			if not parcel_lake.is_empty() and parcel_lake[i * PARCELS + j] >= 0:
				var c := Vector2(i, j) / float(PARCELS)
				ci.draw_colored_polygon(PackedVector2Array([_mini_pt(_px(c), r), _mini_pt(_px(c + Vector2(1, 0) / PARCELS), r),
					_mini_pt(_px(c + Vector2(1, 1) / PARCELS), r), _mini_pt(_px(c + Vector2(0, 1) / PARCELS), r)]), Color(0.25, 0.55, 0.72))
	ci.draw_polyline(gp + PackedVector2Array([gp[0]]), Color(0.9, 0.85, 0.6, 0.7), 1.0)
	for h in hamlet_pos:
		ci.draw_circle(_mini_pt(_px(hamlet_pos[h]), r), 3.5, Color(Art.HAMLET.get(h, Color("#d8bf8c"))).lightened(0.2))
	for id in agents:
		ci.draw_circle(_mini_pt(_px(agents[id]["pos"]), r), 1.8, Art.agent_color(agents[id]["info"]))
	var v := Rect2(_mini_pt(-cam_off / zoom, r), size / zoom * (r.size.x / (2.0 * iso_a)))
	var vc := v.intersection(r)
	if vc.size.x > 0.0 and vc.size.y > 0.0:
		ci.draw_rect(vc, Color(1, 1, 1, 0.9), false, 1.5)


## Un carré de la maille (coin `c`, côté `side`, dans le sol), projeté en losange.
func _cell_poly(c: Vector2, side: float) -> PackedVector2Array:
	return PackedVector2Array([_px(c), _px(c + Vector2(side, 0)), _px(c + Vector2(side, side)), _px(c + Vector2(0, side))])


## Les trois mailles : les pas des personnages (fins), les lots des maisons (les maisons, obstacles, en rouge), les parcelles des lacs
## (leur chance : vert pour un bon coin, rouge pour un mauvais).
func _draw_mesh(ci: CanvasItem) -> void:
	if not show_mesh:
		return
	for i in n_steps + 1:
		var u := float(i) / float(n_steps)
		ci.draw_line(_px(Vector2(u, 0)), _px(Vector2(u, 1)), Color(1, 1, 1, 0.05), 1.0)
		ci.draw_line(_px(Vector2(0, u)), _px(Vector2(1, u)), Color(1, 1, 1, 0.05), 1.0)
	for i in n_lots + 1:
		var u := float(i) / float(n_lots)
		ci.draw_line(_px(Vector2(u, 0)), _px(Vector2(u, 1)), Color(1, 0.85, 0.5, 0.22), 1.2)
		ci.draw_line(_px(Vector2(0, u)), _px(Vector2(1, u)), Color(1, 0.85, 0.5, 0.22), 1.2)
	for hs in deco["houses"]:
		for st in hs["foot"]:
			ci.draw_colored_polygon(_cell_poly(Vector2(st) / float(n_steps), 1.0 / n_steps), Color(1, 0.3, 0.2, 0.35))
	for k in lake_cells.size():
		for p in lake_cells[k]:
			var luck := clampf((float(p["luck"]) - 0.7) / 0.6, 0.0, 1.0)
			var poly := _cell_poly(Vector2(p["c"]) / float(PARCELS), 1.0 / PARCELS)
			ci.draw_colored_polygon(poly, Color(Color("#e0584a").lerp(Color("#4fd27a"), luck), 0.30))
			poly.append(poly[0])
			ci.draw_polyline(poly, Color(1, 1, 1, 0.22), 1.0)
