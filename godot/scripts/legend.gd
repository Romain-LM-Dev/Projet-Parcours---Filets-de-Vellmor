## Légende dessinée avec les mêmes fonctions que la carte : ce qu'on voit ici est exactement
## ce qu'on voit sur le lac.
extends Control


func _ready() -> void:
	custom_minimum_size = Vector2(0, 34)


func _draw() -> void:
	var f := Art.font("ui")
	var x := 10.0
	var y := size.y / 2.0
	for arch in ["ancienne_famille", "nouveau_venu", "taiseux", "beau_parleur", "ancien"]:
		Art.draw_token(self, Vector2(x + 9, y), {"archetype": arch, "role": "ancien" if arch == "ancien" else "pecheur",
			"kind": "llm", "tier": "petit", "name": " "}, 0.7)
		var lbl: String = Art.ARCH_LABEL[arch]
		draw_string(f, Vector2(x + 22, y + 4), lbl, HORIZONTAL_ALIGNMENT_LEFT, -1, 12, Art.MUTED)
		x += 30 + f.get_string_size(lbl, HORIZONTAL_ALIGNMENT_LEFT, -1, 12).x
	x += 10
	draw_line(Vector2(x, 8), Vector2(x, size.y - 8), Art.LINE, 1.0)
	x += 14
	var kinds := [[{"kind": "llm", "tier": "grand"}, "grand modèle"], [{"kind": "llm", "tier": "petit"}, "petit modèle"],
		[{"kind": "rule", "tier": ""}, "agent à règles"]]
	for k in kinds:
		var info: Dictionary = k[0].duplicate()
		info["archetype"] = "x"
		info["name"] = " "
		Art.draw_token(self, Vector2(x + 9, y), info, 0.7)
		draw_string(f, Vector2(x + 22, y + 4), k[1], HORIZONTAL_ALIGNMENT_LEFT, -1, 12, Art.MUTED)
		x += 30 + f.get_string_size(k[1], HORIZONTAL_ALIGNMENT_LEFT, -1, 12).x
	x += 10
	draw_line(Vector2(x, 8), Vector2(x, size.y - 8), Art.LINE, 1.0)
	x += 14
	for k in [[Art.TALK, "parole"], [Art.SUPPORT, "soutien"], [Art.ACCUSE, "accusation"], [Art.PROPOSAL, "proposition"]]:
		draw_line(Vector2(x, y), Vector2(x + 22, y), k[0], 3.0, true)
		draw_circle(Vector2(x + 22, y), 3.0, k[0])
		draw_string(f, Vector2(x + 30, y + 4), k[1], HORIZONTAL_ALIGNMENT_LEFT, -1, 12, Art.MUTED)
		x += 44 + f.get_string_size(k[1], HORIZONTAL_ALIGNMENT_LEFT, -1, 12).x
