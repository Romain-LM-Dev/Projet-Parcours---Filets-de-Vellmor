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

const HAMLET_POS := {
	"Ostrel": Vector2(0.14, 0.21), "Bramois": Vector2(0.86, 0.21),
	"Tilque": Vector2(0.86, 0.84), "Hennad": Vector2(0.14, 0.84),
}
const ELDER_POS := Vector2(0.5, 0.115)
const LAKE_C := Vector2(0.5, 0.535)
const LAKE_R := Vector2(0.29, 0.245)
const ROOM := Rect2(0.045, 0.105, 0.91, 0.85)
const RING_R := Vector2(0.33, 0.335)
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
var _proposal_author := {}

# temps et ambiance
var season_days := 30.0
var sim_time := 0.0
var light := 1.0
var phase := ""
var assembly_scope := ""            # "" | "valley" | "hamlet"
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
	over = _layer(Control.new())
	decor.draw.connect(func() -> void: _draw_decor(decor))
	under.draw.connect(func() -> void: _draw_under(under))
	shade.draw.connect(func() -> void: _draw_shade(shade))
	lights.draw.connect(func() -> void: _draw_lights(lights))
	over.draw.connect(func() -> void: _draw_over(over))
	resized.connect(_on_resized)
	_on_resized()


func _layer(c: Control) -> Control:
	c.set_anchors_preset(Control.PRESET_FULL_RECT)
	c.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(c)
	return c


func _on_resized() -> void:
	if size.x < 10:
		return
	mat.set_shader_parameter("lake_c", LAKE_C)
	mat.set_shader_parameter("lake_r", LAKE_R)
	mat.set_shader_parameter("px_size", size)
	_generate_decor()
	decor.queue_redraw()


# ================================================================== géométrie
static func lake_shape(th: float) -> float:
	return 1.0 + 0.06 * sin(3.0 * th + 1.0) + 0.04 * sin(5.0 * th + 2.0) + 0.03 * sin(7.0 * th + 0.5)


func lake_rn(n: Vector2) -> float:
	var d := (n - LAKE_C) / LAKE_R
	return d.length() / lake_shape(atan2(d.y, d.x))


func lake_point(th: float, rn: float) -> Vector2:
	return LAKE_C + Vector2(cos(th), sin(th)) * LAKE_R * lake_shape(th) * rn


func _px(n: Vector2) -> Vector2:
	return Vector2(n.x * size.x, n.y * size.y)


func _nm(p: Vector2) -> Vector2:
	return Vector2(p.x / max(size.x, 1.0), p.y / max(size.y, 1.0))


func _hamlet_angle(h: String) -> float:
	var d: Vector2 = (HAMLET_POS[h] - LAKE_C) / LAKE_R
	return atan2(d.y, d.x)


# ================================================================== décor
func _generate_decor() -> void:
	var rng := RandomNumberGenerator.new()
	rng.seed = 7411
	var houses: Array = []
	var docks := {}
	var paths: Array = []
	var elder_px := _px(ELDER_POS)
	for h in HAMLET_POS:
		var c := _px(HAMLET_POS[h])
		var n := 6
		for i in n:
			var ang := TAU * float(i) / float(n) + rng.randf_range(-0.25, 0.25) + 0.4
			var rad := rng.randf_range(62.0, 76.0)
			houses.append({"p": c + Vector2(cos(ang) * rad * 1.15, sin(ang) * rad * 0.9),
				"s": Vector2(rng.randf_range(24, 32), rng.randf_range(16, 21)), "rot": rng.randf_range(-0.5, 0.5),
				"roof": [Color("#b5583c"), Color("#8e6b52"), Color("#c49a55"), Color("#6f7584")][rng.randi() % 4],
				"seed": rng.randf()})
		var th := _hamlet_angle(h)
		var shore := lake_point(th, 1.02)
		var tip := lake_point(th, 0.84)
		docks[h] = {"shore": shore, "tip": tip, "th": th}
		paths.append(_curve(c, _px(shore), 0.12))
		paths.append(_curve(c, elder_px + Vector2(0, 26), -0.18 if c.x < elder_px.x else 0.18))
	houses.append({"p": elder_px + Vector2(-4, -6), "s": Vector2(46, 30), "rot": 0.0, "roof": Color("#7a4b34"),
		"seed": 0.5, "elder": true})
	# arbres : bosquets le long des versants et entre les hameaux, jamais sur l'eau, les places ou les chemins
	var trees: Array = []
	var tries := 0
	while trees.size() < 230 and tries < 6000:
		tries += 1
		var p := Vector2(rng.randf_range(-10, size.x + 10), rng.randf_range(-10, size.y + 10))
		var n_p := _nm(p)
		var edge: float = min(min(p.x, size.x - p.x), min(p.y, size.y - p.y))
		var keep := 1.0 if edge < 70 else (0.5 if edge < 140 else 0.12)
		if rng.randf() > keep:
			continue
		if lake_rn(n_p) < 1.22:
			continue
		var bad := false
		for h in HAMLET_POS:
			if p.distance_to(_px(HAMLET_POS[h])) < 105:
				bad = true
		if p.distance_to(elder_px) < 95:
			bad = true
		if not bad:
			for path in paths:
				for q in path:
					if p.distance_to(q) < 20:
						bad = true
						break
				if bad:
					break
		if bad:
			continue
		var pine := rng.randf() < 0.35
		trees.append({"p": p, "r": rng.randf_range(9, 17) * (0.85 if pine else 1.0), "pine": pine,
			"tone": rng.randf()})
	trees.sort_custom(func(a, b): return a["p"].y < b["p"].y)
	# roseaux sur la grève
	var reeds: Array = []
	for i in 70:
		var th := rng.randf_range(0, TAU)
		var near_dock := false
		for h in docks:
			if absf(angle_difference(th, docks[h]["th"])) < 0.12:
				near_dock = true
		if near_dock:
			continue
		reeds.append({"p": _px(lake_point(th, rng.randf_range(0.98, 1.05))), "n": rng.randi_range(3, 6),
			"seed": rng.randf()})
	var flies: Array = []
	for i in 36:
		var tr: Dictionary = trees[rng.randi() % max(trees.size(), 1)] if not trees.is_empty() else {"p": Vector2.ZERO}
		flies.append({"base": tr["p"] + Vector2(rng.randf_range(-30, 30), rng.randf_range(-30, 30)),
			"ph": rng.randf() * TAU, "sp": rng.randf_range(0.4, 1.0)})
	deco = {"trees": trees, "houses": houses, "docks": docks, "paths": paths, "reeds": reeds, "flies": flies}


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
	for h in HAMLET_POS:
		var c := _px(HAMLET_POS[h])
		_ellipse(ci, c, Vector2(58, 46), Color("#7d6844", 0.55))
		_ellipse(ci, c, Vector2(54, 42), Color("#c4a978"))
		_ellipse(ci, c + Vector2(-8, -6), Vector2(34, 24), Color(1, 1, 1, 0.06))
	var ep := _px(ELDER_POS)
	_ellipse(ci, ep + Vector2(0, 26), Vector2(70, 22), Color("#c4a978"))
	# pontons
	for h in deco["docks"]:
		var dk: Dictionary = deco["docks"][h]
		var a := _px(dk["shore"])
		var b := _px(dk["tip"])
		var dir := (b - a).normalized()
		var side := Vector2(-dir.y, dir.x) * 6.0
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
	# arbres (ombre, puis houppier en trois tons)
	for tr in deco["trees"]:
		var p: Vector2 = tr["p"]
		var r: float = tr["r"]
		_ellipse(ci, p + Vector2(r * 0.45, r * 0.55), Vector2(r * 1.05, r * 0.8), Color(0.05, 0.08, 0.03, 0.30))
		var tone: float = tr["tone"]
		if tr["pine"]:
			var dark := Color("#1f4029").lerp(Color("#2b5233"), tone)
			for k in 3:
				var rr := r * (1.0 - k * 0.27)
				_star(ci, p + Vector2(0, -k * 2.0), rr, dark.lightened(k * 0.10), 7)
		else:
			var base := Color("#2e5a2a").lerp(Color("#3f6e2c"), tone)
			ci.draw_circle(p, r, base)
			ci.draw_circle(p + Vector2(-r * 0.25, -r * 0.25), r * 0.72, base.lightened(0.12))
			ci.draw_circle(p + Vector2(-r * 0.38, -r * 0.42), r * 0.38, base.lightened(0.24))
	# maisons
	for hs in deco["houses"]:
		_house(ci, hs)
	# foyer de l'ancien
	var fp := _fire_pos()
	for i in 8:
		var a := TAU * i / 8.0
		ci.draw_circle(fp + Vector2(cos(a) * 9, sin(a) * 7), 3.0, Color("#77736c"))


func _house(ci: CanvasItem, hs: Dictionary) -> void:
	var p: Vector2 = hs["p"]
	var s: Vector2 = hs["s"]
	var rot: float = hs["rot"]
	var roof: Color = hs["roof"]
	var ax := Vector2(cos(rot), sin(rot))
	var ay := Vector2(-ax.y, ax.x)
	var hx := ax * s.x * 0.5
	var hy := ay * s.y * 0.5
	var sh := Vector2(5, 6)
	ci.draw_colored_polygon(PackedVector2Array([p - hx - hy + sh, p + hx - hy + sh, p + hx + hy + sh, p - hx + hy + sh]),
		Color(0, 0, 0, 0.28))
	ci.draw_colored_polygon(PackedVector2Array([p - hx - hy, p + hx - hy, p + hx, p - hx]), roof.lightened(0.12))
	ci.draw_colored_polygon(PackedVector2Array([p - hx, p + hx, p + hx + hy, p - hx + hy]), roof.darkened(0.18))
	ci.draw_line(p - hx, p + hx, roof.darkened(0.35), 1.5, true)
	var ch := p + hx * 0.5 - hy * 0.55
	ci.draw_rect(Rect2(ch - Vector2(2.5, 2.5), Vector2(5, 5)), Color("#4b3a32"), true)
	if hs.get("elder", false):
		ci.draw_line(p - hx - hy, p + hx - hy, roof.lightened(0.3), 1.0)


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
	return _px(ELDER_POS) + Vector2(56, 22)


# ================================================================== état
func reset_world(agent_list: Array, cap: float, days: float = 30.0) -> void:
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
	stock_ratio = 1.0
	dry = 0.0
	assembly_scope = ""
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
			home = ELDER_POS + Vector2(0.0, 0.045)
		else:
			var k: int = idx.get(h, 0)
			idx[h] = k + 1
			var n: int = per_hamlet[h]
			# une couronne autour du hameau ; au-delà de six habitants, une deuxième couronne plus large
			var ring := 1.0
			var slot := k
			var count: int = mini(n, 6)
			if k >= 6:
				ring = 1.9
				slot = k - 6
				count = n - 6
			var ang := -PI / 2.0 + TAU * float(slot) / float(max(count, 1)) + (0.5 if ring == 1.0 else 0.25)
			home = HAMLET_POS.get(h, Vector2(0.5, 0.5)) + Vector2(cos(ang) * 0.027, sin(ang) * 0.032) * ring
		agents[id] = {"id": id, "info": a, "home": home, "pos": home, "path": [], "hold": 0.0, "heading": 0.0,
			"wake_t": 0.0, "fishing": 0.0}
		order.append(id)
	fish.clear()
	_sync_fish(true)


func remember_proposal(pid: String, author: String) -> void:
	_proposal_author[pid] = author


func on_event(ev: Dictionary) -> void:
	var ty: String = str(ev.get("type", ""))
	var p: Dictionary = ev.get("payload", {})
	sim_time = float(ev.get("sim_time", sim_time))
	match ty:
		"season_start":
			dry = max(0.0, dry - 0.5)
			var md := "" if not p.has("mode") else (" · asynchrone" if str(p["mode"]) == "async" else " · synchrone")
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
			_sync_fish(not animate)
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
				if animate:
					var h := str(a["info"].get("hamlet", ""))
					var dk: Dictionary = deco["docks"].get(h, {})
					var spot := _fishing_spot(a)
					if dk.is_empty():
						a["path"] = [[spot, 1.4], [a["home"], 0.0]]
					else:
						a["path"] = [[dk["shore"], 0.0], [dk["tip"], 0.0], [spot, 1.6], [dk["tip"], 0.0],
							[dk["shore"], 0.0], [a["home"], 0.0]]
					a["landed"] = float(p.get("landed", 0.0))
		"assembly_start":
			var scope: String = str(p.get("scope", "valley"))
			var parts: Array = p.get("participants", [])
			if scope == "valley":
				assembly_scope = "valley"
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
				for i in ids.size():
					var ang := -PI / 2.0 + TAU * float(i) / float(max(ids.size(), 1))
					_move(ids[i], LAKE_C + Vector2(cos(ang), sin(ang)) * RING_R)
			else:
				assembly_scope = "hamlet"
				var h := scope.substr(7)
				if not hamlet_fires.has(h):
					hamlet_fires.append(h)
				if hamlet_fires.size() == 1:
					_banner("Veillées dans les hameaux", "Chacun parle chez soi", Art.TALK)
				var c: Vector2 = HAMLET_POS.get(h, LAKE_C)
				for i in parts.size():
					var ang := -PI / 2.0 + TAU * float(i) / float(max(parts.size(), 1))
					_move(str(parts[i]), c + Vector2(cos(ang) * 0.05, sin(ang) * 0.06))
		"assembly_end":
			var scope2 := str(p.get("scope", "valley"))
			if p.get("adopted_proposal") == null and scope2 == "valley":
				_banner("Pas d'accord ce soir", "Aucune règle n'a réuni la moitié des pêcheurs", Art.MUTED)
			if scope2 == "valley":
				assembly_scope = ""
			else:
				hamlet_fires.erase(scope2.substr(7))
				if hamlet_fires.is_empty():
					assembly_scope = ""
			badges.clear()
			for id in agents:
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
			badges[str(p.get("author", ""))] = "%s · %s t" % [str(p.get("proposal_id", "")), _num(p.get("quota", 0))]
		"support":
			var author := str(_proposal_author.get(str(p.get("proposal_id", "")), ""))
			var who: String = str(p.get("agent", ""))
			if author != "" and author != who:
				_link(who, author, Art.SUPPORT, 1.8, 4.0, "support")
		"accusation":
			_link(str(p.get("accuser", "")), str(p.get("accused", "")), Art.ACCUSE, 3.5, 7.0, "accuse")
			_mark(str(p.get("accused", "")), "accusé", Art.ACCUSE, 7.0)
		"norm_adopted":
			_banner("Règle adoptée", "%s t par pêcheur dès la saison %d · %d soutiens" % [_num(p.get("quota", 0)),
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
		a["path"] = [[target, 0.0, speed]]
	else:
		a["pos"] = target
		a["path"] = []


func _fishing_spot(a: Dictionary) -> Vector2:
	# chaque pêcheur a son coin, du côté de son hameau : les barques ne se superposent pas
	var h := str(a["info"].get("hamlet", ""))
	var th: float = _hamlet_angle(h) if HAMLET_POS.has(h) else randf() * TAU
	var k := order.find(a["id"])
	var slot := float(k % 3) - 1.0
	var depth := 0.38 + 0.2 * float((k / 3) % 2)
	return lake_point(th + slot * 0.42 + randf_range(-0.08, 0.08), depth + randf_range(-0.05, 0.05))


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
	var target := 0 if collapsed and stock_ratio < 0.05 else int(round(clamp(stock_ratio, 0.0, 1.0) * 42.0))
	var alive := fish.filter(func(f): return not f["dying"])
	while alive.size() < target:
		var th := randf() * TAU
		var f := {"d": Vector2(cos(th), sin(th)) * randf_range(0.1, 0.8), "ang": randf() * TAU, "sp": randf_range(0.05, 0.12),
			"a": 1.0 if instant else 0.0, "dying": false, "len": randf_range(7.0, 11.0), "wig": randf() * TAU}
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


func _update_fish(dt: float) -> void:
	for f in fish:
		f["a"] = clamp(float(f["a"]) + (-dt * 0.8 if f["dying"] else dt * 0.6), 0.0, 1.0)
		f["ang"] = float(f["ang"]) + randf_range(-1.6, 1.6) * dt
		var d: Vector2 = f["d"]
		var th := atan2(d.y, d.x)
		var rn := d.length() / lake_shape(th)
		if rn > 0.78:
			var to_c := atan2(-d.y, -d.x)
			f["ang"] = lerp_angle(float(f["ang"]), to_c, dt * 2.5)
		var v := Vector2(cos(f["ang"]), sin(f["ang"])) * float(f["sp"])
		f["d"] = d + v * dt
		f["wig"] = float(f["wig"]) + dt * 9.0
	fish = fish.filter(func(f): return not (f["dying"] and f["a"] <= 0.0))
	if stock_ratio > 0.3 and randf() < dt * 0.5 * stock_ratio and not fish.is_empty():
		var f: Dictionary = fish[randi() % fish.size()]
		splashes.append({"p": LAKE_C + f["d"] * LAKE_R, "ttl": 1.0, "max": 1.0, "r": 10.0})


# ================================================================== animation
func _process(delta: float) -> void:
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
	mat.set_shader_parameter("health", clampf(stock_ratio, 0.0, 1.0))
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
		var on_water := lake_rn(pos) < 0.97
		var mult: float = float(path[0][2]) if path[0].size() > 2 else 1.0
		var step := (WATER_SPEED if on_water else LAND_SPEED) * delta * mult
		var dvec := target_p - pos
		if dvec.length() > 0.0001:
			a["heading"] = lerp_angle(float(a["heading"]), atan2(dvec.y * size.y, dvec.x * size.x), delta * 8.0)
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
	over.queue_redraw()


func _gui_input(event: InputEvent) -> void:
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
	var bd := 20.0
	for id in agents:
		var d := _px(agents[id]["pos"]).distance_to(pos)
		if d < bd:
			bd = d
			best = id
	return best


# ================================================================== dessin dynamique
func _draw_under(ci: CanvasItem) -> void:
	for w in wakes:
		var a: float = float(w["ttl"]) / float(w["max"])
		var p := _px(w["p"])
		var side := Vector2(-sin(w["h"]), cos(w["h"])) * (4.0 + (1.0 - a) * 9.0)
		ci.draw_circle(p + side, 1.6 * a + 0.6, Color(1, 1, 1, 0.35 * a))
		ci.draw_circle(p - side, 1.6 * a + 0.6, Color(1, 1, 1, 0.35 * a))
	for f in fish:
		var p := _px(LAKE_C + f["d"] * LAKE_R)
		var ang: float = f["ang"]
		var L: float = f["len"]
		var dir := Vector2(cos(ang), sin(ang))
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
		ci.draw_arc(p, r, 0, TAU, 28, Color(1, 1, 1, 0.55 * a), 1.4, true)
		ci.draw_arc(p, r * 0.55, 0, TAU, 20, Color(1, 1, 1, 0.35 * a), 1.0, true)


func _darkness() -> float:
	return clamp(1.0 - light, 0.0, 1.0)


func _draw_shade(ci: CanvasItem) -> void:
	var dk := _darkness()
	var dusk: float = clamp(1.0 - absf(light - 0.5) * 2.2, 0.0, 1.0)
	if dusk > 0.01:
		ci.draw_rect(Rect2(Vector2.ZERO, size), Color(DUSK, 0.16 * dusk), true)
	if dk > 0.01:
		ci.draw_rect(Rect2(Vector2.ZERO, size), Color(NIGHT, 0.62 * smoothstep(0.15, 1.0, dk)), true)


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
		Art.glow(ci, _px(HAMLET_POS[h]), 95.0, Color(1.0, 0.5, 0.18, 0.55 * dk * ff))
	# reflet de lune sur le lac
	var mp := _px(LAKE_C + Vector2(0.10, -0.07))
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
	ci.draw_rect(Rect2(Vector2.ZERO, size), Color(0.02, 0.03, 0.07, 0.45 * a), true)
	var r := Rect2(_px(ROOM.position), Vector2(ROOM.size.x * size.x, ROOM.size.y * size.y))
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
	var c := _px(LAKE_C)
	var rr := Vector2(RING_R.x * size.x, RING_R.y * size.y)
	_ellipse(ci, c, rr * 1.12, Color(Color("#6e2a26"), 0.95 * a), 64)
	_ellipse(ci, c, rr * 1.06, Color(Color("#8c3a31"), 0.95 * a), 64)
	var ring := PackedVector2Array()
	for i in 65:
		var ang := TAU * i / 64.0
		ring.append(c + Vector2(cos(ang) * rr.x * 0.95, sin(ang) * rr.y * 0.95))
	ci.draw_polyline(ring, Color(Color("#d8a957"), 0.55 * a), 2.0, true)
	_ellipse(ci, c, rr * 0.55, Color(Color("#7a302a"), 0.9 * a), 48)
	Art.glow(ci, c, rr.x * 0.95, Color(1.0, 0.55, 0.2, 0.30 * a))
	for i in 10:
		var ang := TAU * i / 10.0
		ci.draw_circle(c + Vector2(cos(ang) * 20, sin(ang) * 16), 5.0, Color(Color("#6f6a64"), a))
	_draw_fire(ci, c - Vector2(0, 4), 1.8 * a)
	# coussins aux places de la veillée
	var n_seats := agents.size()
	for i in n_seats:
		var ang := -PI / 2.0 + TAU * float(i) / float(max(n_seats, 1))
		var sp := _px(LAKE_C + Vector2(cos(ang), sin(ang)) * RING_R)
		_ellipse(ci, sp + Vector2(0, 3), Vector2(19, 15), Color(Color("#2a1a12"), 0.55 * a))
		_ellipse(ci, sp, Vector2(18, 14), Color(Color("#b0823f"), 0.9 * a))
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


func _draw_boat(ci: CanvasItem, p: Vector2, heading: float, col: Color, fishing: float) -> void:
	var dir := Vector2(cos(heading), sin(heading))
	var side := Vector2(-dir.y, dir.x)
	var L := 21.0
	var W := 8.5
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
	by_y.sort_custom(func(x, y): return float(agents[x]["pos"].y) < float(agents[y]["pos"].y))
	for id in by_y:
		var a: Dictionary = agents[id]
		var p := _px(a["pos"])
		var info: Dictionary = a["info"]
		var on_water := lake_rn(a["pos"]) < 0.97 and assembly_scope != "valley"
		if on_water:
			_draw_boat(ci, p, float(a["heading"]), Art.arch_color(str(info.get("archetype", ""))), float(a["fishing"]))
		Art.draw_token(ci, p - (Vector2(0, 7) if on_water else Vector2.ZERO), info, 0.78 if on_water else 1.0, 1.0,
			id == selected, t)
		var first := str(info.get("name", id)).split(" ")[0]
		var lbl := first if id != hovered else "%s · %s" % [str(info.get("name", id)), str(info.get("archetype_label", ""))]
		var fs := 11
		var tw := f.get_string_size(lbl, HORIZONTAL_ALIGNMENT_LEFT, -1, fs).x + 10
		var lr := Rect2(p + Vector2(-tw / 2.0, 15), Vector2(tw, fs + 6))
		Art.box(Color(0.05, 0.07, 0.12, 0.72 if id != hovered else 0.92), 8).draw(ci.get_canvas_item(), lr)
		ci.draw_string(f, lr.position + Vector2(5, fs + 1.5), lbl, HORIZONTAL_ALIGNMENT_LEFT, -1, fs,
			Art.INK if id != selected else Color("#ffffff"))
		if badges.has(id):
			Art.pill(ci, p + Vector2(15, -26), badges[id], Art.PROPOSAL, Color("#2a1d05"), 11)


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
		var rt := Rect2(_px(ROOM.position), Vector2(ROOM.size.x * size.x, 70))
		placed.append(Rect2(rt.position + Vector2(rt.size.x * 0.25, 10), Vector2(rt.size.x * 0.5, 60)))
	var ids := bubbles.keys()
	ids.sort_custom(func(x, y): return float(bubbles[x]["born"]) < float(bubbles[y]["born"]))
	for id in ids:
		if not agents.has(id):
			continue
		var b: Dictionary = bubbles[id]
		var a: float = clamp(float(b["ttl"]) / 0.6, 0.0, 1.0) * clamp((t - float(b["born"])) / 0.2, 0.0, 1.0)
		var pb := _px(agents[id]["pos"])
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
			var inward := (_px(LAKE_C) - pb).normalized()
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
		var col := Art.arch_color(str(info.get("archetype", "")))
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
	for h in HAMLET_POS:
		var c := _px(HAMLET_POS[h]) + Vector2(0, -96)
		var w := tf.get_string_size(h, HORIZONTAL_ALIGNMENT_LEFT, -1, 17).x + 24
		var r := Rect2(c - Vector2(w / 2, 0), Vector2(w, 26))
		Art.box(Color(0.10, 0.08, 0.06, 0.72 * sa), 6, Color(Color("#d8bf8c"), 0.5 * sa), 1).draw(ci.get_canvas_item(), r)
		ci.draw_string(tf, r.position + Vector2(12, 19), h, HORIZONTAL_ALIGNMENT_LEFT, -1, 17, Color(Color("#f3e3bd"), sa))
	var ep := _px(ELDER_POS) + Vector2(0, -50)
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
		var pr := Rect2(Vector2(size.x - 146, 16), Vector2(130, 40))
		Art.box(Color(0.05, 0.07, 0.12, 0.92), 14, Color(Art.PROPOSAL, 0.8), 1, 10).draw(ci.get_canvas_item(), pr)
		ci.draw_rect(Rect2(pr.position + Vector2(16, 12), Vector2(5, 16)), Art.PROPOSAL, true)
		ci.draw_rect(Rect2(pr.position + Vector2(26, 12), Vector2(5, 16)), Art.PROPOSAL, true)
		ci.draw_string(tf, pr.position + Vector2(42, 27), "En pause", HORIZONTAL_ALIGNMENT_LEFT, -1, 18, Art.INK)
	# jauge du lac
	var gw := 330.0
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
	# bandeau
	if not banners.is_empty():
		var bn: Dictionary = banners[0]
		var life: float = float(bn["max"]) - float(bn["ttl"])
		var a: float = clamp(life / 0.3, 0.0, 1.0) * clamp(float(bn["ttl"]) / 0.5, 0.0, 1.0)
		var col: Color = bn["col"]
		var tw: float = max(tf.get_string_size(bn["title"], HORIZONTAL_ALIGNMENT_LEFT, -1, 28).x,
			f.get_string_size(bn["sub"], HORIZONTAL_ALIGNMENT_LEFT, -1, 14).x) + 60
		var br := Rect2(Vector2(size.x / 2 - tw / 2, 18 - (1.0 - a) * 10.0), Vector2(tw, 66))
		Art.box(Color(0.05, 0.07, 0.12, 0.9 * a), 16, Color(col, 0.7 * a), 1, 14).draw(ci.get_canvas_item(), br)
		ci.draw_rect(Rect2(br.position + Vector2(24, 62), Vector2(tw - 48, 2)), Color(col, 0.8 * a), true)
		ci.draw_string(tf, br.position + Vector2(0, 34), bn["title"], HORIZONTAL_ALIGNMENT_CENTER, tw, 28, Color(col.lightened(0.3), a))
		ci.draw_string(f, br.position + Vector2(0, 54), bn["sub"], HORIZONTAL_ALIGNMENT_CENTER, tw, 14, Color(Art.INK, 0.85 * a))


func _draw_over(ci: CanvasItem) -> void:
	_draw_signs(ci)
	_draw_room(ci)
	for h in hamlet_fires:
		_draw_fire(ci, _px(HAMLET_POS[h]), 1.2)
	if room_alpha < 0.5:
		_draw_fire(ci, _fire_pos(), 0.9 * (0.4 + 0.6 * _darkness()))
	_draw_links(ci)
	_draw_tokens(ci)
	_draw_marks(ci)
	_draw_bubbles(ci)
	_draw_hud(ci)
