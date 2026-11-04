## Direction artistique partagée : palette, polices, et dessin des pions.
## Une seule source pour la carte, la légende et l'interface, pour que les couleurs veuillent
## toujours dire la même chose.
class_name Art
extends RefCounted

# --- interface (nuit bleutée, papier crème pour les bulles)
const BG := Color("#0d1220")
const PANEL := Color("#141b2d")
const PANEL_2 := Color("#1b2439")
const LINE := Color(1, 1, 1, 0.08)
const INK := Color("#e9ecf5")
const MUTED := Color("#8f97b2")
const PAPER := Color("#fbf6ea")
const PAPER_INK := Color("#2a2420")

# --- interactions (mêmes couleurs partout : carte, fil, légende)
const TALK := Color("#7f95ff")
const SUPPORT := Color("#58d08a")
const ACCUSE := Color("#ff6a5c")
const PROPOSAL := Color("#f2b23a")
const PROMISE := Color("#e7c27a")
const INCIDENT := Color("#f39c4a")
const INJECT := Color("#ffd166")

# --- hameaux : un pêcheur a la couleur de son hameau ; l'ancien a la sienne
const HAMLET := {
	"Ostrel": Color("#5fa3e0"),
	"Bramois": Color("#f2864a"),
	"Tilque": Color("#b78fd6"),
	"Hennad": Color("#3fc4b0"),
	"Varenne": Color("#e0c04f"),
	"Corbel": Color("#e06f8f"),
	"Mirande": Color("#7fb069"),
	"Sauvet": Color("#c98bb9"),
	"Lormes": Color("#6fa8b8"),
	"Quéran": Color("#d9a066"),
	"Brevelle": Color("#9aa5e0"),
	"Dunac": Color("#a3c86a"),
}
const ELDER := Color("#e2bd6a")
# --- archétypes (écrits en toutes lettres dans l'inspecteur)
const ARCH_LABEL := {
	"ancienne_famille": "famille ancienne", "nouveau_venu": "nouveau venu",
	"taiseux": "taiseux", "beau_parleur": "beau parleur", "ancien": "l'ancien",
}

static var _fonts := {}


## Couleur d'un agent : celle de son hameau (`info` : la fiche de l'agent, avec `hamlet` et `role`).
static func agent_color(info: Dictionary) -> Color:
	if str(info.get("role", "")) == "ancien":
		return ELDER
	return hamlet_color(str(info.get("hamlet", "")))


## La couleur d'un village : celle de la table, ou une teinte tirée de son nom (un village inventé garde la même d'une partie à l'autre).
static func hamlet_color(name: String) -> Color:
	if HAMLET.has(name):
		return HAMLET[name]
	if name == "":
		return MUTED
	return Color.from_hsv(float(name.hash() % 360) / 360.0, 0.5, 0.88)


static func _load_font(files: Array) -> Font:
	var main: FontFile = null
	var fallbacks: Array[Font] = []
	for f in files:
		var path := "res://fonts/%s.woff2" % f
		if not ResourceLoader.exists(path):
			continue
		var res = load(path)
		if res == null:
			continue
		if main == null:
			main = res
		else:
			fallbacks.append(res)
	if main == null:
		return ThemeDB.fallback_font
	var fv := FontVariation.new()
	fv.base_font = main
	fv.fallbacks = fallbacks
	return fv


## ui | ui_bold | ui_black | title | title_italic
static func font(kind: String = "ui") -> Font:
	if _fonts.has(kind):
		return _fonts[kind]
	var f: Font
	match kind:
		"ui_bold":
			f = _load_font(["nunito-latin-700-normal", "nunito-latin-ext-700-normal"])
		"ui_black":
			f = _load_font(["nunito-latin-800-normal", "nunito-latin-ext-800-normal"])
		"title":
			f = _load_font(["alegreya-latin-700-normal", "alegreya-latin-ext-700-normal"])
		"title_regular":
			f = _load_font(["alegreya-latin-500-normal", "alegreya-latin-ext-500-normal"])
		"title_italic":
			f = _load_font(["alegreya-latin-500-italic", "alegreya-latin-ext-500-italic"])
		_:
			f = _load_font(["nunito-latin-400-normal", "nunito-latin-ext-400-normal"])
	_fonts[kind] = f
	return f


static func box(bg: Color, radius: int = 10, border: Color = Color(0, 0, 0, 0), border_w: int = 0,
		shadow: int = 0) -> StyleBoxFlat:
	var sb := StyleBoxFlat.new()
	sb.bg_color = bg
	sb.set_corner_radius_all(radius)
	sb.corner_detail = 6
	if border_w > 0:
		sb.border_color = border
		sb.set_border_width_all(border_w)
	if shadow > 0:
		sb.shadow_color = Color(0, 0, 0, 0.35 * bg.a)
		sb.shadow_size = shadow
		sb.shadow_offset = Vector2(0, 3)
	sb.anti_aliasing = true
	return sb


## Ellipse pleine ou anneau (un cercle écrasé : le sol vu en perspective).
static func _ell(ci: CanvasItem, c: Vector2, rx: float, ry: float, col: Color, w: float = 0.0) -> void:
	var pts := PackedVector2Array()
	for i in 17:
		pts.append(c + Vector2(cos(TAU * i / 16.0) * rx, sin(TAU * i / 16.0) * ry))
	if w > 0.0:
		ci.draw_polyline(pts, col, w, true)
	else:
		ci.draw_colored_polygon(pts, col)


## Un bonhomme. p = centre du corps (les pieds sont à p + 12*scale). Couleur du vêtement = hameau ; chapeau rond = IA,
## bonnet carré = agent à règles ; anneau doré au sol = grand modèle ; ancien = barbe blanche, manteau long, bâton ;
## rôle "patrouille" = uniforme sarcelle. pose : stand, walk, sit (veillée), row / net (dans une barque, buste seul).
## anim : le temps (balancement des bras et des jambes).
static func draw_token(ci: CanvasItem, p: Vector2, info: Dictionary, scale: float = 1.0, alpha: float = 1.0,
		selected: bool = false, pulse: float = 0.0, pose: String = "stand", anim: float = 0.0) -> void:
	var role := str(info.get("role", "pecheur"))
	var kind := str(info.get("kind", "llm"))
	var tier := str(info.get("tier", ""))
	var elder := role == "ancien"
	var patrol := role == "patrouille"
	var col := Color("#1f8f86") if patrol else agent_color(info)
	var u := scale * (1.12 if elder else 1.0)
	var boat := pose == "row" or pose == "net"
	var drop := (4.0 if pose == "sit" else 5.0 if boat else 0.0) * u
	var y0 := p.y + 12.0 * scale                          # le sol sous ses pieds
	var hip := y0 - 10.0 * u + drop
	var sh := hip - 9.0 * u                               # ligne des épaules
	var x := p.x
	var skin := Color("#f0cfa4", alpha)
	var dark := Color(col.darkened(0.45), alpha)
	var cc := Color(col, alpha)
	var sw := sin(anim * 9.0) * 3.2 * u if pose == "walk" else 0.0
	if not boat:
		_ell(ci, Vector2(x, y0), 8.0 * u, 3.0 * u, Color(0, 0, 0, 0.28 * alpha))
	if selected:
		_ell(ci, Vector2(x, y0), (11.0 + 1.5 * sin(pulse * 4.0)) * u, 4.4 * u, Color(1, 1, 1, 0.9 * alpha), 2.0)
		ci.draw_circle(Vector2(x, hip - 5.0 * u), 15.0 * u, Color(1, 1, 1, 0.07 * alpha))
	if tier == "grand" or elder:
		_ell(ci, Vector2(x, y0), 9.5 * u, 3.6 * u, Color(Color("#f6d878"), alpha), 1.8 * u)
	var leg := Color("#3a3f52", alpha) if not elder else dark
	# jambes
	if not boat:
		for sd in [-1.0, 1.0]:
			var foot := Vector2(x + sd * 2.4 * u, y0 - 0.5 * u + (-absf(sw) * 0.3 if sd * sw < 0.0 else 0.0))
			var top := Vector2(x + sd * 2.0 * u, hip)
			if pose == "sit":
				foot = Vector2(x + sd * 3.0 * u, hip + 4.0 * u)
			else:
				foot.y -= 0.0
				foot.x += sd * sw * 0.5
			ci.draw_line(top, foot, leg, 3.0 * u, true)
	# bâton de l'ancien
	if elder:
		ci.draw_line(Vector2(x + 8.0 * u, y0 + 0.5 * u), Vector2(x + 8.0 * u, sh - 4.0 * u), Color("#8a6238", alpha), 1.8 * u, true)
	# torse (l'ancien porte un long manteau)
	var hem := y0 - 2.0 * u if elder and pose != "sit" else hip + 1.0 * u
	var bw := 5.4 * u if elder else 4.4 * u
	var torso := PackedVector2Array([Vector2(x - 4.2 * u, sh), Vector2(x + 4.2 * u, sh), Vector2(x + bw, hem), Vector2(x - bw, hem)])
	ci.draw_colored_polygon(torso, cc)
	ci.draw_polyline(PackedVector2Array([torso[0], torso[3], torso[2], torso[1]]), Color(0.04, 0.05, 0.1, 0.55 * alpha), 1.0, true)
	if patrol:
		ci.draw_line(Vector2(x - 4.0 * u, sh + 0.5 * u), Vector2(x + 4.0 * u, hip), Color("#e9fff6", alpha), 1.8 * u, true)
	elif kind == "rule":                                   # signe sur la poitrine des agents à règles
		ci.draw_rect(Rect2(x - 1.5 * u, sh + 2.0 * u, 3.0 * u, 3.0 * u), Color(1, 1, 1, 0.9 * alpha), true)
	if tier == "grand" or elder:                           # ceinture dorée
		ci.draw_line(Vector2(x - bw, hip - 0.5 * u), Vector2(x + bw, hip - 0.5 * u), Color("#f6d878", alpha), 1.6 * u)
	# bras
	for sd in [-1.0, 1.0]:
		var sp := Vector2(x + sd * 4.6 * u, sh + 1.0 * u)
		var hand := Vector2(x + sd * 6.4 * u, sh + 8.5 * u)
		if pose == "walk":
			hand += Vector2(0, -sd * sw * 0.8)
		elif pose == "row":
			hand = Vector2(x + sd * 7.0 * u, sh + 5.0 * u + sin(anim * 4.0 + (0.0 if sd < 0.0 else PI)) * 3.0 * u)
		elif pose == "net":
			hand = Vector2(x + sd * 4.0 * u, sh - 2.0 * u - maxf(0.0, sin(anim * 3.0 + (0.0 if sd < 0.0 else 1.2))) * 5.0 * u)
		elif pose == "sit":
			hand = Vector2(x + sd * 4.5 * u, sh + 8.0 * u)
		ci.draw_line(sp, hand, cc if not elder else dark, 2.4 * u, true)
		ci.draw_circle(hand, 1.3 * u, skin)
	# tête
	var hc := Vector2(x, sh - 3.8 * u)
	if elder:
		ci.draw_colored_polygon(PackedVector2Array([hc + Vector2(-3.4, 1.0) * u, hc + Vector2(3.4, 1.0) * u, hc + Vector2(0, 7.0) * u]),
			Color("#f4f4f0", alpha))
	ci.draw_circle(hc, 4.0 * u, skin)
	if elder:
		ci.draw_arc(hc, 4.3 * u, PI, TAU, 10, Color("#f4f4f0", alpha), 2.2 * u, true)
	elif patrol or kind != "rule":                         # chapeau rond (casquette pour la patrouille)
		var cap := PackedVector2Array()
		for i in 9:
			cap.append(hc + Vector2(cos(PI + PI * i / 8.0) * 4.6, sin(PI + PI * i / 8.0) * 3.8 - 0.4) * u)
		ci.draw_colored_polygon(cap, dark if not patrol else Color("#0f4a47", alpha))
		ci.draw_line(hc + Vector2(-5.6, -0.4) * u, hc + Vector2(5.6, -0.4) * u, dark if not patrol else Color("#0f4a47", alpha), 1.6 * u)
	else:                                                  # bonnet carré
		ci.draw_rect(Rect2(hc + Vector2(-4.2, -5.0) * u, Vector2(8.4, 4.4) * u), dark, true)
	if tier == "grand" and not elder:                      # galon doré du chapeau
		ci.draw_line(hc + Vector2(-4.6, -1.0) * u, hc + Vector2(4.6, -1.0) * u, Color("#f6d878", alpha), 1.3 * u)


static func pill(ci: CanvasItem, pos: Vector2, text: String, bg: Color, fg: Color, size: int = 11,
		kind: String = "ui_bold", centered: bool = false) -> Rect2:
	var f := font(kind)
	var w := f.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, size).x + 12.0
	var h := size + 8.0
	var rect := Rect2(pos - (Vector2(w / 2.0, 0) if centered else Vector2.ZERO), Vector2(w, h))
	box(bg, int(h / 2.0)).draw(ci.get_canvas_item(), rect)
	ci.draw_string(f, rect.position + Vector2(6, h - 5.5), text, HORIZONTAL_ALIGNMENT_LEFT, -1, size, fg)
	return rect


static func radial_texture() -> GradientTexture2D:
	if _fonts.has("__radial"):
		return _fonts["__radial"]
	var g := Gradient.new()
	g.set_color(0, Color(1, 1, 1, 1))
	g.set_color(1, Color(1, 1, 1, 0))
	g.add_point(0.35, Color(1, 1, 1, 0.45))
	var t := GradientTexture2D.new()
	t.gradient = g
	t.fill = GradientTexture2D.FILL_RADIAL
	t.fill_from = Vector2(0.5, 0.5)
	t.fill_to = Vector2(1.0, 0.5)
	t.width = 128
	t.height = 128
	_fonts["__radial"] = t
	return t


static func glow(ci: CanvasItem, p: Vector2, radius: float, col: Color) -> void:
	ci.draw_texture_rect(radial_texture(), Rect2(p - Vector2(radius, radius), Vector2(radius, radius) * 2.0), false, col)
