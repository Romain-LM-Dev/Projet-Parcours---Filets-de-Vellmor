// Vallée de Vellmor, en vue isométrique : le sol est un losange (le carré [0,1]² des coordonnées de la partie, projeté) qui touche les
// quatre bords de la carte ; au-delà s'étend la forêt hors de la vallée. Prairie, grève et lacs se dessinent dans le sol, pas à l'écran.
// Les lacs viennent de leurs parcelles (`lake_mask`, une parcelle par texel, lissée : la même image que lit world_view.gd) : la rive
// passe là où l'eau vaut 0,5, le vert dit le poisson de chaque parcelle, l'alpha sa profondeur.
shader_type canvas_item;

uniform sampler2D lake_mask : filter_linear, repeat_disable;   // R : l'eau, G : le poisson, B : le lac, A : la profondeur
uniform int lake_n = 1;                              // nombre de lacs (1 à 4)
uniform int grid = 30;                               // la maille des lacs
uniform bool mesh = false;                           // touche G : les parcelles en filigrane
uniform vec2 px_size = vec2(1000.0, 800.0);
uniform vec2 iso_o = vec2(500.0, 0.0);               // le coin nord du sol
uniform vec2 iso_ab = vec2(500.0, 400.0);            // demi-largeur et demi-hauteur du losange
uniform float dry : hint_range(0.0, 1.0) = 0.0;      // sécheresse en cours
uniform float t_offset = 0.0;

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p) {
	vec2 i = floor(p);
	vec2 f = fract(p);
	vec2 u = f * f * (3.0 - 2.0 * f);
	return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x),
			   mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
}
float fbm(vec2 p) {
	float v = 0.0;
	float a = 0.5;
	for (int i = 0; i < 5; i++) { v += a * noise(p); p = p * 2.03 + 3.1; a *= 0.5; }
	return v;
}
// un point de l'écran (pixels du calque) → le sol
vec2 to_ground(vec2 s) {
	vec2 d = (s - iso_o) / iso_ab;
	return vec2((d.x + d.y) * 0.5, (d.y - d.x) * 0.5);
}
bool on_ground(vec2 g) { return g.x >= 0.0 && g.x <= 1.0 && g.y >= 0.0 && g.y <= 1.0; }

void fragment() {
	float T = TIME + t_offset;
	vec2 sp = UV * px_size;
	vec2 g = to_ground(sp);
	vec2 p = sp / 110.0;
	if (!on_ground(g)) {
		// hors de la vallée : une forêt dense, de plus en plus sombre en s'éloignant du sol
		vec3 col = mix(vec3(0.12, 0.22, 0.11), vec3(0.19, 0.31, 0.14), fbm(p * 0.8));
		float canopy = smoothstep(0.42, 0.62, fbm(sp / 24.0 + 7.0));
		col = mix(col, vec3(0.06, 0.14, 0.07), canopy * 0.85);
		col *= 0.72 + 0.25 * fbm(sp / 8.0);
		col = mix(col, vec3(0.45, 0.42, 0.25), dry * 0.35);
		float away = max(max(-g.x, g.x - 1.0), max(-g.y, g.y - 1.0));
		col *= mix(0.92, 0.55, smoothstep(0.0, 0.18, away));
		COLOR = vec4(col, 1.0);
	} else {
		vec4 m = texture(lake_mask, g);
		float wv = m.r + (fbm(g * 70.0) - 0.5) * 0.10;     // la rive ondule un peu
		float wob = (fbm(g * 25.0) - 0.5) * 0.05;

		// --- prairie : deux verts, taches d'herbe haute, fleurs
		float gr = fbm(p * 0.7);
		float g2 = fbm(p * 2.6 + 11.0);
		vec3 grass_lo = vec3(0.27, 0.43, 0.22);
		vec3 grass_hi = vec3(0.47, 0.62, 0.30);
		vec3 col = mix(grass_lo, grass_hi, smoothstep(0.25, 0.75, gr));
		col *= 0.90 + 0.14 * g2;
		vec3 straw = vec3(0.74, 0.66, 0.40) * (0.85 + 0.2 * gr);
		col = mix(col, straw, dry * 0.7);
		vec2 cell = floor(sp / 4.0);
		float fl = step(0.992, hash(cell));
		vec3 flower = mix(vec3(0.98, 0.93, 0.70), vec3(0.95, 0.70, 0.78), hash(cell + 7.0));
		col = mix(col, flower, fl * 0.55 * (1.0 - dry) * (1.0 - smoothstep(0.08, 0.22, wv)));

		// --- bords du sol : herbe plus sombre, comme des versants
		float edge = min(min(g.x, 1.0 - g.x), min(g.y, 1.0 - g.y)) * 340.0;
		col *= mix(0.66, 1.0, smoothstep(0.0, 70.0, edge + fbm(p * 1.5) * 34.0));

		// --- grève et sable mouillé
		vec3 sand = vec3(0.83, 0.75, 0.55);
		col = mix(col, sand * (0.94 + 0.08 * g2), smoothstep(0.24 + wob, 0.36 + wob, wv));
		col = mix(col, sand * 0.72, smoothstep(0.43, 0.5, wv));

		// --- eau
		if (wv > 0.48) {
			float depth = clamp(m.a * 0.85 + (wv - 0.5) * 0.9, 0.0, 1.0);
			// l'eau se trouble là où le poisson manque (le vert de l'image : celui de la parcelle)
			float h = smoothstep(0.12, 0.6, m.g);
			vec3 shallow = mix(vec3(0.58, 0.56, 0.38), vec3(0.47, 0.81, 0.77), h);
			vec3 deep = mix(vec3(0.27, 0.27, 0.18), vec3(0.09, 0.40, 0.55), h);
			vec3 w = mix(shallow, deep, smoothstep(0.0, 0.7, depth));
			float alg = smoothstep(0.55, 0.8, fbm(p * 1.3 + 4.0));
			w = mix(w, vec3(0.22, 0.27, 0.14), alg * (1.0 - h) * 0.6);
			vec2 q = p * 1.1;
			float n1 = fbm(q + vec2(T * 0.045, T * 0.03));
			float n2 = fbm(q * 2.2 - vec2(T * 0.035, -T * 0.05));
			float rip = smoothstep(0.52, 0.78, n1 * 0.6 + n2 * 0.5);
			w += rip * 0.06;
			float spark = pow(abs(sin(n2 * 9.0 + T * 0.7)), 24.0) * smoothstep(0.05, 0.35, depth);
			w += spark * 0.10;
			// écume du rivage
			float foam = 1.0 - smoothstep(0.5, 0.58, wv);
			float fnoise = noise(g * 160.0 + vec2(T * 0.7, 0.0));
			w = mix(w, vec3(0.93, 0.97, 0.96), foam * (0.35 + 0.55 * fnoise));
			col = mix(col, w, smoothstep(0.48, 0.51, wv));
		}
		// --- la maille des lacs, en filigrane
		if (mesh) {
			vec2 f = fract(g * float(grid));
			vec2 fw = fwidth(g * float(grid)) * 1.2;
			float line = 1.0 - min(smoothstep(0.0, fw.x, min(f.x, 1.0 - f.x)), smoothstep(0.0, fw.y, min(f.y, 1.0 - f.y)));
			col = mix(col, vec3(1.0), line * 0.18);
		}
		COLOR = vec4(col, 1.0);
	}
}
