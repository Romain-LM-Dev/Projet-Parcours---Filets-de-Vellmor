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

# --- archétypes
const ARCH := {
	"ancienne_famille": Color("#5fa3e0"),
	"nouveau_venu": Color("#f2864a"),
	"taiseux": Color("#b78fd6"),
	"beau_parleur": Color("#3fc4b0"),
	"ancien": Color("#e2bd6a"),
}
const ARCH_LABEL := {
	"ancienne_famille": "famille ancienne", "nouveau_venu": "nouveau venu",
	"taiseux": "taiseux", "beau_parleur": "beau parleur", "ancien": "l'ancien",
}

static var _fonts := {}


static func arch_color(arch: String) -> Color:
	return ARCH.get(arch, MUTED)


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


## Pion d'un agent. Forme = nature de l'agent (rond = LLM, carré arrondi = agent à règles),
## anneau = taille du modèle (épais doré = grand, fin = petit), couleur = archétype.
static func draw_token(ci: CanvasItem, p: Vector2, info: Dictionary, scale: float = 1.0, alpha: float = 1.0,
		selected: bool = false, pulse: float = 0.0) -> void:
	var role := str(info.get("role", "pecheur"))
	var arch := str(info.get("archetype", ""))
	var kind := str(info.get("kind", "llm"))
	var tier := str(info.get("tier", ""))
	var col := arch_color(arch)
	var r := (13.0 if role == "ancien" else 11.0) * scale
	# ombre portée
	ci.draw_circle(p + Vector2(1.5, 2.5) * scale, r + 2.0 * scale, Color(0, 0, 0, 0.30 * alpha))
	if selected:
		var halo := r + (7.0 + 2.0 * sin(pulse * 4.0)) * scale
		ci.draw_arc(p, halo, 0, TAU, 48, Color(1, 1, 1, 0.85 * alpha), 2.0 * scale, true)
		ci.draw_circle(p, halo, Color(1, 1, 1, 0.08 * alpha))
	var ring_col := Color("#f6e3a8") if tier == "grand" or role == "ancien" else Color("#f4f1ea")
	var ring_w := (3.2 if tier == "grand" or role == "ancien" else 1.6) * scale
	if kind == "rule":
		var rr := Rect2(p - Vector2(r, r), Vector2(r, r) * 2.0)
		var sb := box(Color(col, alpha), int(5 * scale), Color(Color("#d9dce6"), alpha), int(max(2.0, 2.4 * scale)))
		sb.draw(ci.get_canvas_item(), rr)
		ci.draw_rect(Rect2(p - Vector2(3, 3) * scale, Vector2(6, 6) * scale), Color(1, 1, 1, 0.9 * alpha), true)
	else:
		ci.draw_circle(p, r + ring_w * 0.5, Color(ring_col, alpha))
		ci.draw_circle(p, r - ring_w * 0.5, Color(col, alpha))
		# reflet
		ci.draw_circle(p + Vector2(-r * 0.3, -r * 0.35), r * 0.28, Color(1, 1, 1, 0.22 * alpha))
		var letter := str(info.get("name", "?")).substr(0, 1)
		var f := font("ui_black")
		var fs := int(11 * scale) if role != "ancien" else int(13 * scale)
		ci.draw_string(f, p + Vector2(-r, fs * 0.36), letter, HORIZONTAL_ALIGNMENT_CENTER, r * 2.0, fs,
			Color(Color("#10131c"), 0.75 * alpha))


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
