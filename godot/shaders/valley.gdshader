// Vallée de Vellmor : prairie, grève et lac animé, en un seul passage.
// La forme du lac est la même fonction que lake_shape() dans world_view.gd,
// pour que barques et poissons restent exactement sur l'eau.
shader_type canvas_item;

uniform vec2 lake_c = vec2(0.5, 0.53);
uniform vec2 lake_r = vec2(0.30, 0.25);
uniform vec2 px_size = vec2(1000.0, 800.0);
uniform float health : hint_range(0.0, 1.0) = 1.0;   // stock / capacité
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
float lake_shape(float th) {
	return 1.0 + 0.06 * sin(3.0 * th + 1.0) + 0.04 * sin(5.0 * th + 2.0) + 0.03 * sin(7.0 * th + 0.5);
}

void fragment() {
	float T = TIME + t_offset;
	vec2 uv = UV;
	vec2 p = uv * px_size / 110.0;
	vec2 d = (uv - lake_c) / lake_r;
	float th = atan(d.y, d.x);
	float rn = length(d) / lake_shape(th);

	// --- prairie : deux verts, taches d'herbe haute, fleurs
	float g = fbm(p * 0.7);
	float g2 = fbm(p * 2.6 + 11.0);
	vec3 grass_lo = vec3(0.27, 0.43, 0.22);
	vec3 grass_hi = vec3(0.47, 0.62, 0.30);
	vec3 col = mix(grass_lo, grass_hi, smoothstep(0.25, 0.75, g));
	col *= 0.90 + 0.14 * g2;
	vec3 straw = vec3(0.74, 0.66, 0.40) * (0.85 + 0.2 * g);
	col = mix(col, straw, dry * 0.7);
	vec2 cell = floor(uv * px_size / 4.0);
	float fl = step(0.992, hash(cell));
	vec3 flower = mix(vec3(0.98, 0.93, 0.70), vec3(0.95, 0.70, 0.78), hash(cell + 7.0));
	col = mix(col, flower, fl * 0.55 * (1.0 - dry) * smoothstep(1.25, 1.4, rn));

	// --- versants de la vallée : bords plus sombres
	vec2 e = min(uv, 1.0 - uv) * px_size;
	float edge = min(e.x, e.y);
	col *= mix(0.62, 1.0, smoothstep(0.0, 90.0, edge + fbm(p * 1.5) * 40.0));

	// --- grève et sable mouillé
	float wob = (fbm(vec2(th * 3.0, 1.0)) - 0.5) * 0.05;
	vec3 sand = vec3(0.83, 0.75, 0.55);
	col = mix(col, sand * (0.94 + 0.08 * g2), smoothstep(1.13 + wob, 1.04 + wob, rn));
	col = mix(col, sand * 0.72, smoothstep(1.035, 1.0, rn));

	// --- eau
	if (rn < 1.01) {
		float depth = clamp(1.0 - rn, 0.0, 1.0);
		// l'eau ne se trouble qu'en dessous de la moitié du stock
		float h = smoothstep(0.12, 0.6, health);
		vec3 shallow = mix(vec3(0.58, 0.56, 0.38), vec3(0.47, 0.81, 0.77), h);
		vec3 deep = mix(vec3(0.27, 0.27, 0.18), vec3(0.09, 0.40, 0.55), h);
		vec3 w = mix(shallow, deep, smoothstep(0.0, 0.6, depth));
		// herbiers sombres quand le lac s'appauvrit
		float alg = smoothstep(0.55, 0.8, fbm(p * 1.3 + 4.0));
		w = mix(w, vec3(0.22, 0.27, 0.14), alg * (1.0 - h) * 0.6);
		// risées et reflets
		vec2 q = p * 1.1;
		float n1 = fbm(q + vec2(T * 0.045, T * 0.03));
		float n2 = fbm(q * 2.2 - vec2(T * 0.035, -T * 0.05));
		float rip = smoothstep(0.52, 0.78, n1 * 0.6 + n2 * 0.5);
		w += rip * 0.06;
		float spark = pow(abs(sin(n2 * 9.0 + T * 0.7)), 24.0) * smoothstep(0.05, 0.35, depth);
		w += spark * 0.10;
		// écume du rivage
		float foam = smoothstep(0.07, 0.0, depth);
		float fnoise = noise(vec2(th * 14.0, T * 0.7));
		w = mix(w, vec3(0.93, 0.97, 0.96), foam * (0.35 + 0.55 * fnoise));
		col = mix(col, w, smoothstep(1.01, 0.995, rn));
	}
	COLOR = vec4(col, 1.0);
}
