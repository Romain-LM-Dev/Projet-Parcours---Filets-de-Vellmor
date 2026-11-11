# Diagrammes de classes de l'interface Godot (sans simplification)

L'interface Godot 4.7 ne décide de rien : elle affiche ce que le moteur Python publie et lui envoie les ordres du joueur. Elle tient en neuf scripts GDScript (`godot/scripts/`). En GDScript, un script est une classe : `extends` donne l'héritage, `preload(...)` puis `.new()` fait qu'un script en crée un autre (composition : l'objet créé vit et meurt avec son propriétaire), et les appels `Art.xxx(...)` sont des appels statiques (dépendance, rien n'est possédé).

Conventions de lecture : `+` = attribut ou méthode publique, `-` = privée (nom commençant par `_`). Dans les sections 3 à 11, chaque script est détaillé avec toutes ses variables, constantes, signaux et fonctions (les noms en majuscules sont des constantes `const`). `Control`, `Node` et `RefCounted` sont des classes du moteur Godot, pas du projet.

## 1. Qui possède qui

Ce diagramme montre l'héritage des scripts vers les classes Godot et la propriété : `Main` (la scène principale) crée la carte, la courbe, la légende, le menu et le client WebSocket (et, en mode vidéo seulement, le lecteur de démonstration `Demo`, qui rejoue un journal) ; le menu crée à son tour sa mini-carte. Les flèches pointillées étiquetées « signal » vont de l'émetteur vers celui qui l'écoute : c'est ainsi que le menu et la carte remontent les actions du joueur à `Main`.

```mermaid
classDiagram
    direction TB
    class Control {
        <<Godot>>
    }
    class Node {
        <<Godot>>
    }
    class Main {
        +ws
        +world
        +chart
        +menu
        +legend
        +run
        +agents
        -_on_message(topic, data)
        -_on_event(ev)
        -_on_status(s)
        -_send(cmd)
        -_toggle_pause()
        -_rumor()
        -_select(id)
    }
    class WsClient {
        +url
        +signal message(topic, data)
        +signal status_changed(text, connected)
        -_open()
        -_process(delta)
        +send(cmd) bool
        +pending() int
    }
    class WorldView {
        +agents
        +selected
        +animate
        +paused
        +thinking
        +signal agent_clicked(agent_id)
        +reset_world(agent_list, cap)
        +on_event(ev)
        +zoom_at(screen, factor)
    }
    class Chart {
        +stock
        +norm
        +kept
        +reset()
        +set_season(season, v)
        +set_live(ratio)
    }
    class Demo {
        +main
        +beats
        +events
        +start(m, path)
    }
    class Legend {
        +villages
        +set_villages(names)
    }
    class StartMenu {
        +catalog
        +fishers
        +map
        +signal start_requested(config)
        +signal generate_requested(params)
        +signal cancelled
        +set_catalog(cat)
        +build_config() Dictionary
        +open(cancelable)
        +close()
    }
    class MenuMap {
        +fishers
        +hamlets
        +selected
        +signal token_selected(index)
        +signal token_moved(index, hamlet)
        +set_data(list, elder)
        +token_positions()
    }
    Control <|-- Main
    Control <|-- WorldView
    Control <|-- Chart
    Control <|-- Legend
    Control <|-- StartMenu
    Control <|-- MenuMap
    Node <|-- WsClient
    Node <|-- Demo
    Main *-- WsClient : "ws (preload, add_child)"
    Main *-- Demo : "d (option --demo, add_child)"
    Demo o-- Main : "main (start)"
    Main *-- WorldView : "world"
    Main *-- Chart : "chart"
    Main *-- Legend : "legend"
    Main *-- StartMenu : "menu"
    StartMenu *-- MenuMap : "map"
    MenuMap ..> WorldView : "constante DEFAULT_HAMLETS"
    WsClient ..> Main : "signal message, status_changed"
    WorldView ..> Main : "signal agent_clicked"
    StartMenu ..> Main : "signal start_requested, generate_requested, cancelled"
    MenuMap ..> StartMenu : "signal token_selected, token_moved"
```

Dans le code :
- `godot/scripts/main.gd:8` (`extends Control`), `:10-15` (les six `preload`, dont `Demo`), `:25` (attribut `ws`).
- `godot/scripts/main.gd:111` et `:136-137` (création de `ws`, `add_child(ws)`, `ws.message.connect(_on_message)`) ; `:386` (`WorldView.new()`) ; `:447` (`Chart.new()`) ; `:557` (`Legend.new()`) ; `:561` (`StartMenu.new()`) ; `:148` (`Demo.new()`, seulement avec `--demo=`).
- `godot/scripts/main.gd:388` (`world.agent_clicked.connect(_select)`), `:563-565` (`menu.start_requested`, `menu.generate_requested`, `menu.cancelled`).
- `godot/scripts/demo.gd:4` (`extends Node`), `:39` (`start(m, path)`, appelée par `Main` avec lui-même).
- `godot/scripts/ws_client.gd:3` (`extends Node`), `:5-6` (signaux), `:58` (`send`), `:65` (`pending`).
- `godot/scripts/world_view.gd:15` (`extends Control`), `:17` (signal), `:1076` (`reset_world`), `:1168` (`on_event`), `:273` (`zoom_at`).
- `godot/scripts/chart.gd:3` (`extends Control`), `:18` (`reset`), `:29` (`set_season`), `:49` (`set_live`) ; `godot/scripts/legend.gd:3`, `:8` (`set_villages`).
- `godot/scripts/start_menu.gd:10` (`extends Control`), `:12` (`preload` de `MenuMap`), `:14-16` (signaux), `:624` (`map = MenuMap.new()`), `:650` (`set_catalog`), `:1377` (`build_config`), `:1417` (`open`), `:1424` (`close`).
- `godot/scripts/menu_map.gd:3` (`extends Control`), `:5` (`preload` de `world_view.gd`, alias `WV`), `:7-8` (signaux), `:31` (`set_data`), `:63` (`token_positions`).

## 2. Dépendances statiques : `Art` et le shader de la vallée

`Art` n'est jamais instanciée : toutes les classes d'affichage appellent ses fonctions statiques. `WorldView` possède en plus un `ShaderMaterial` (attribut `mat`) construit sur le shader `valley.gdshader` : ce shader dessine le sol (eau, poissons, sécheresse, mailles) et reçoit ses `uniform` depuis `WorldView`. Les membres complets de `Art` et du shader sont donnés aux sections 3 et 11.

```mermaid
classDiagram
    direction LR
    class RefCounted {
        <<Godot>>
    }
    class ShaderMaterial {
        <<Godot>>
    }
    class Art
    class Valley {
        <<shader>>
    }
    class Main
    class WorldView
    class StartMenu
    class MenuMap
    class Chart
    class Legend
    RefCounted <|-- Art
    Main ..> Art : "thème, couleurs, polices"
    WorldView ..> Art : "pions, bulles, lueurs"
    StartMenu ..> Art : "style des boutons"
    MenuMap ..> Art : "draw_token"
    Chart ..> Art : "couleurs"
    Legend ..> Art : "couleurs, pions"
    WorldView o-- ShaderMaterial : "mat"
    ShaderMaterial ..> Valley : "shader"
```

Dans le code :
- `godot/scripts/art.gd:4-5` (`class_name Art`, `extends RefCounted`).
- `godot/scripts/world_view.gd:68` (`var mat: ShaderMaterial`), `:155-159` (création du matériau, `terrain` est le `ColorRect` qui le porte).
- Occurrences de `Art.` (mesurées) : `world_view.gd` 98, `main.gd` 66, `start_menu.gd` 37, `menu_map.gd` 12, `legend.gd` 9, `chart.gd` 6.

## 3. `Art` (art.gd)

### 3.1 Constantes et fonctions statiques

Palette de l'interface, couleurs d'interaction, couleurs des hameaux, polices et dessin des pions : une seule source pour toute l'interface.

```mermaid
classDiagram
    class Art {
        +BG : Color
        +PANEL : Color
        +PANEL_2 : Color
        +LINE : Color
        +INK : Color
        +MUTED : Color
        +PAPER : Color
        +PAPER_INK : Color
        +TALK : Color
        +SUPPORT : Color
        +ACCUSE : Color
        +PROPOSAL : Color
        +PROMISE : Color
        +INCIDENT : Color
        +INJECT : Color
        +HAMLET : Dictionary
        +ELDER : Color
        +ARCH_LABEL : Dictionary
        -_fonts : Dictionary
        +static agent_color(info: Dictionary) Color
        +static hamlet_color(name: String) Color
        -static _load_font(files: Array) Font
        +static font(kind: String) Font
        +static box(bg: Color, radius: int, border: Color, border_w: int, shadow: int) StyleBoxFlat
        -static _ell(ci: CanvasItem, c: Vector2, rx: float, ry: float, col: Color, w: float)
        +static draw_token(ci: CanvasItem, p: Vector2, info: Dictionary, scale: float, alpha: float, selected: bool, pulse: float, pose: String, anim: float)
        +static pill(ci: CanvasItem, pos: Vector2, text: String, bg: Color, fg: Color, size: int, kind: String, centered: bool) Rect2
        +static radial_texture() GradientTexture2D
        +static glow(ci: CanvasItem, p: Vector2, radius: float, col: Color)
    }
    RefCounted <|-- Art
    class RefCounted {
        <<Godot>>
    }
```

Dans le code :
- `godot/scripts/art.gd` fonctions (10) : `agent_color` :52, `hamlet_color` :59, `_load_font` :67, `font` :90, `box` :111, `_ell` :129, `draw_token` :143, `pill` :230, `radial_texture` :241, `glow` :259.
- `godot/scripts/art.gd` variables (1) : `_fonts` :48.
- `godot/scripts/art.gd` constantes (18) : `BG` :8, `PANEL` :9, `PANEL_2` :10, `LINE` :11, `INK` :12, `MUTED` :13, `PAPER` :14, `PAPER_INK` :15, `TALK` :18, `SUPPORT` :19, `ACCUSE` :20, `PROPOSAL` :21, `PROMISE` :22, `INCIDENT` :23, `INJECT` :24, `HAMLET` :27, `ELDER` :41, `ARCH_LABEL` :43.

## 4. `WsClient` (ws_client.gd)

### 4.1 Le client WebSocket

Se connecte au pont, lit au plus `MAX_PER_FRAME` paquets par image, émet un signal par message et retente toutes les 2 s si la connexion tombe.

```mermaid
classDiagram
    class WsClient {
        +signal message(topic: String, data: Dictionary)
        +signal status_changed(text: String, connected: bool)
        +MAX_PER_FRAME : int
        +url : String
        -_ws : WebSocketPeer
        -_state : int
        -_retry : float
        -_ready()
        -_open()
        -_process(delta: float)
        +send(cmd: Dictionary) bool
        +pending() int
    }
    Node <|-- WsClient
    class Node {
        <<Godot>>
    }
```

Dans le code :
- `godot/scripts/ws_client.gd` fonctions (5) : `_ready` :15, `_open` :19, `_process` :28, `send` :58, `pending` :65.
- `godot/scripts/ws_client.gd` variables (4) : `url` :8, `_ws` :9, `_state` :10, `_retry` :11.
- `godot/scripts/ws_client.gd` constantes (1) : `MAX_PER_FRAME` :12.
- `godot/scripts/ws_client.gd` signaux (2) : `message` :5, `status_changed` :6.

## 5. `Chart` (chart.gd) et `Legend` (legend.gd)

### 5.1 Chart : les courbes par saison

Dessine le stock (aire), l'indice de norme et la part des promesses tenues, saison par saison.

```mermaid
classDiagram
    class Chart {
        +C_LAKES : Array
        +C_STOCK : Color
        +C_NORM : Color
        +C_KEPT : Color
        +stock : Array
        +norm : Array
        +kept : Array
        +live_stock : float
        +lakes : Dictionary
        +reset()
        +set_season(season: int, v: Dictionary)
        +set_live(ratio: float)
        -_draw()
        -_points(vals: Array, r: Rect2, n: int) PackedVector2Array
        -_series(vals: Array, r: Rect2, n: int, col: Color, w: float)
    }
    Control <|-- Chart
    class Control {
        <<Godot>>
    }
```

Dans le code :
- `godot/scripts/chart.gd` fonctions (6) : `reset` :18, `set_season` :29, `set_live` :49, `_draw` :54, `_points` :101, `_series` :111.
- `godot/scripts/chart.gd` variables (5) : `stock` :5, `norm` :6, `kept` :7, `live_stock` :8, `lakes` :9.
- `godot/scripts/chart.gd` constantes (4) : `C_LAKES` :11, `C_STOCK` :13, `C_NORM` :14, `C_KEPT` :15.

### 5.2 Legend : la légende de la carte

Légende dessinée avec les mêmes fonctions que la carte.

```mermaid
classDiagram
    class Legend {
        +villages : Array
        +set_villages(names: Array)
        -_ready()
        -_draw()
    }
    Control <|-- Legend
    class Control {
        <<Godot>>
    }
```

Dans le code :
- `godot/scripts/legend.gd` fonctions (3) : `set_villages` :8, `_ready` :13, `_draw` :17.
- `godot/scripts/legend.gd` variables (1) : `villages` :5.

## 6. `MenuMap` (menu_map.gd)

### 6.1 L'aperçu de la vallée dans le menu

Les hameaux, le lac et les pêcheurs tels qu'ils seront placés ; un pion se glisse d'un hameau à l'autre, le clic le sélectionne.

```mermaid
classDiagram
    class MenuMap {
        +signal token_selected(index: int)
        +signal token_moved(index: int, hamlet: String)
        +WV : Script
        +fishers : Array
        +hamlets : Array
        +lakes : Array
        +elder_on : bool
        +elder_kind : String
        +selected : int
        +large_min : int
        -_hover : int
        -_drag : int
        -_drag_pos : Vector2
        -_drag_target : String
        -_t : float
        -_ready()
        +set_data(list: Array, elder: bool, elder_k: String, sel: int, large: int, villages: Array, lake_list: Array)
        -_process(delta: float)
        -_px(n: Vector2) Vector2
        -_tier_of(f: Dictionary) String
        +token_positions() Array
        -_pick(pos: Vector2) int
        -_lake_of() Dictionary
        -_boxes() Array
        -_pos() Dictionary
        -_nearest_hamlet(pos: Vector2) String
        -_gui_input(event: InputEvent)
        -_draw()
        -_token(i: int, p: Vector2, sel: bool, alpha: float)
        -_ellipse(c: Vector2, r: Vector2, col: Color, n: int)
    }
    Control <|-- MenuMap
    class Control {
        <<Godot>>
    }
```

Dans le code :
- `godot/scripts/menu_map.gd` fonctions (15) : `_ready` :25, `set_data` :31, `_process` :43, `_px` :49, `_tier_of` :53, `token_positions` :63, `_pick` :88, `_lake_of` :100, `_boxes` :108, `_pos` :112, `_nearest_hamlet` :116, `_gui_input` :127, `_draw` :158, `_token` :212, `_ellipse` :226.
- `godot/scripts/menu_map.gd` variables (12) : `fishers` :10, `hamlets` :11, `lakes` :12, `elder_on` :13, `elder_kind` :14, `selected` :15, `large_min` :16, `_hover` :18, `_drag` :19, `_drag_pos` :20, `_drag_target` :21, `_t` :22.
- `godot/scripts/menu_map.gd` constantes (1) : `WV` :5.
- `godot/scripts/menu_map.gd` signaux (2) : `token_selected` :7, `token_moved` :8.

## 7. `Main` (main.gd)

### 7.1 Constantes, signaux et variables

Tout l'état de la scène principale : widgets gardés, état reconstruit des événements, options de ligne de commande de test.

```mermaid
classDiagram
    class Main {
        +WS : Script
        +WorldView : Script
        +Chart : Script
        +Legend : Script
        +StartMenu : Script
        +Demo : Script
        +SPEEDS : Array
        +INCIDENT_LABELS : Dictionary
        +BREACH_WORD : Dictionary
        +KPI_SUB : Dictionary
        +ws : Variant
        +world : Variant
        +chart : Variant
        +menu : Variant
        +lbl_run : Label
        +lbl_clock : Label
        +lbl_status : Label
        +ind_labels : Dictionary
        +feed : RichTextLabel
        +narration : RichTextLabel
        +trust_view : RichTextLabel
        +trust_dirty : bool
        +trust_mode : String
        +trust_observer : String
        +trust_who : OptionButton
        +feed_only_selected : CheckBox
        +inspector : RichTextLabel
        +rules_view : RichTextLabel
        +tabs : TabContainer
        +comm_opt : OptionButton
        +vis_check : CheckButton
        +legend : Control
        +lbl_weather : Label
        +weather_days : Array
        +weather_season : int
        +lbl_patrol : Label
        +patrol_texts : Dictionary
        +lake_labels : Dictionary
        +patrol_text_season : int
        +patrol_installed : bool
        +reps : Dictionary
        +rumor_edit : LineEdit
        +run : Dictionary
        +agents : Dictionary
        +feed_lines : Array
        +proposals : Dictionary
        +norms : Array
        +norms_now : Array
        +selected : String
        +inspector_dirty : bool
        +feed_dirty : bool
        +catching_up : int
        +t0_ms : int
        +n_events : int
        +n_indicators : int
        +last_sim_label : String
        +selftest : float
        +shot_path : String
        +demo_path : String
        +shots : Array
        +shot_dir : String
        +autostart : float
        +view_zoom : float
        +view_mesh : bool
        +autostart_at : float
        +menu_shot : String
        +catalog : Dictionary
        +engine : Dictionary
        +engine_seen_ms : int
        +engine_state : String
        +ws_ok : bool
        +last_error : String
        +transport : PanelContainer
        +btn_pause : Button
        +btn_stop : Button
        +btn_stop_top : Button
        +stop_dlg : ConfirmationDialog
        +btn_new : Button
        +speed_buttons : Dictionary
        +lbl_progress : Label
        +lbl_thinking : Label
        +end_overlay : Control
        +end_title : Label
        +end_text : Label
        +end_new : Button
        +ind_sub : Dictionary
        +ind_title : Dictionary
        +end_status : Dictionary
        +feed_groups : Dictionary
        -_acc : float
    }
    Control <|-- Main
    class Control {
        <<Godot>>
    }
```

Dans le code :
- `godot/scripts/main.gd` variables (80) : `ws` :25, `world` :26, `chart` :27, `menu` :28, `lbl_run` :29, `lbl_clock` :30, `lbl_status` :31, `ind_labels` :32, `feed` :33, `narration` :34, `trust_view` :35, `trust_dirty` :36, `trust_mode` :37, `trust_observer` :38, `trust_who` :39, `feed_only_selected` :40, `inspector` :41, `rules_view` :42, `tabs` :43, `comm_opt` :44, `vis_check` :45, `legend` :46, `lbl_weather` :47, `weather_days` :48, `weather_season` :49, `lbl_patrol` :50, `patrol_texts` :51, `lake_labels` :52, `patrol_text_season` :53, `patrol_installed` :54, `reps` :55, `rumor_edit` :56, `run` :59, `agents` :60, `feed_lines` :61, `proposals` :62, `norms` :63, `norms_now` :64, `selected` :67, `inspector_dirty` :68, `feed_dirty` :69, `catching_up` :70, `t0_ms` :71, `n_events` :72, `n_indicators` :73, `last_sim_label` :74, `selftest` :75, `shot_path` :76, `demo_path` :77, `shots` :78, `shot_dir` :79, `autostart` :80, `view_zoom` :81, `view_mesh` :82, `autostart_at` :83, `menu_shot` :84, `catalog` :87, `engine` :88, `engine_seen_ms` :89, `engine_state` :90, `ws_ok` :91, `last_error` :92, `transport` :93, `btn_pause` :94, `btn_stop` :95, `btn_stop_top` :96, `stop_dlg` :97, `btn_new` :98, `speed_buttons` :99, `lbl_progress` :100, `lbl_thinking` :101, `end_overlay` :102, `end_title` :103, `end_text` :104, `end_new` :105, `ind_sub` :156, `ind_title` :157, `end_status` :653, `feed_groups` :1263, `_acc` :1632.
- `godot/scripts/main.gd` constantes (10) : `WS` :10, `WorldView` :11, `Chart` :12, `Legend` :13, `StartMenu` :14, `Demo` :15, `SPEEDS` :18, `INCIDENT_LABELS` :21, `BREACH_WORD` :65, `KPI_SUB` :1151.

### 7.2 Les nœuds Godot gardés par `Main`

Les widgets créés par le code (`.new()`) et conservés dans une variable : `Main` en est propriétaire (agrégation). Les autres nœuds (conteneurs intermédiaires, séparateurs) sont ajoutés à l'arbre sans être gardés.

```mermaid
classDiagram
    direction LR
    class Main
    class Label {
        <<Godot>>
    }
    class RichTextLabel {
        <<Godot>>
    }
    class OptionButton {
        <<Godot>>
    }
    class CheckBox {
        <<Godot>>
    }
    class TabContainer {
        <<Godot>>
    }
    class CheckButton {
        <<Godot>>
    }
    class Control {
        <<Godot>>
    }
    class LineEdit {
        <<Godot>>
    }
    class PanelContainer {
        <<Godot>>
    }
    class Button {
        <<Godot>>
    }
    class ConfirmationDialog {
        <<Godot>>
    }
    Main o-- Label : "lbl_run, lbl_clock, lbl_status, lbl_weather, lbl_patrol, lbl_progress, lbl_thinking, end_title, end_text (9)"
    Main o-- RichTextLabel : "feed, narration, trust_view, inspector, rules_view (5)"
    Main o-- OptionButton : "trust_who, comm_opt (2)"
    Main o-- CheckBox : "feed_only_selected (1)"
    Main o-- TabContainer : "tabs (1)"
    Main o-- CheckButton : "vis_check (1)"
    Main o-- Control : "legend, end_overlay (2)"
    Main o-- LineEdit : "rumor_edit (1)"
    Main o-- PanelContainer : "transport (1)"
    Main o-- Button : "btn_pause, btn_stop, btn_stop_top, btn_new, end_new (5)"
    Main o-- ConfirmationDialog : "stop_dlg (1)"
```

Dans le code :
- `godot/scripts/main.gd` : Label `lbl_run` :29, `lbl_clock` :30, `lbl_status` :31, `lbl_weather` :47, `lbl_patrol` :50, `lbl_progress` :100, `lbl_thinking` :101, `end_title` :103, `end_text` :104; RichTextLabel `feed` :33, `narration` :34, `trust_view` :35, `inspector` :41, `rules_view` :42; OptionButton `trust_who` :39, `comm_opt` :44; CheckBox `feed_only_selected` :40; TabContainer `tabs` :43; CheckButton `vis_check` :45; Control `legend` :46, `end_overlay` :102; LineEdit `rumor_edit` :56; PanelContainer `transport` :93; Button `btn_pause` :94, `btn_stop` :95, `btn_stop_top` :96, `btn_new` :98, `end_new` :105; ConfirmationDialog `stop_dlg` :97.

### 7.3 Initialisation et construction de l'interface

Les fonctions de `Main` de cette zone du fichier (les en-têtes de section du script délimitent les zones).

```mermaid
classDiagram
    class Main {
        -_ready()
        -_pad(sb: StyleBoxFlat, h: float, v: float) StyleBoxFlat
        -_make_theme() Theme
        -_label(text: String, size: int, kind: String, col: Color) Label
        -_card(accent: Color) PanelContainer
        -_seg(text: String) Button
        -_kpi(parent: Control, key: String, title: String, sub: String, accent: Color, big: bool)
        -_build_ui()
    }
    Control <|-- Main
```

Dans le code :
- `godot/scripts/main.gd` fonctions (8) : `_ready` :108, `_pad` :160, `_make_theme` :168, `_label` :222, `_card` :231, `_seg` :242, `_kpi` :258, `_build_ui` :282.

### 7.4 Pilotage de la partie (pause, vitesse, arrêt, menu)

Les fonctions de `Main` de cette zone du fichier (les en-têtes de section du script délimitent les zones).

```mermaid
classDiagram
    class Main {
        -_speed_label(s: float) String
        -_controllable() bool
        -_toggle_pause()
        -_on_stop_pressed()
        -_on_menu_start(cfg: Dictionary)
        -_on_menu_generate(params: Dictionary)
        -_on_status(s: Dictionary)
        -_show_end(s: Dictionary)
        -_refresh_end_text()
        -_update_transport()
        -_unhandled_key_input(event: InputEvent)
        -_rumor()
        -_rich() RichTextLabel
        -_ind_title(k: String) String
        -_send(cmd: Dictionary)
    }
    Control <|-- Main
```

Dans le code :
- `godot/scripts/main.gd` fonctions (15) : `_speed_label` :583, `_controllable` :595, `_toggle_pause` :599, `_on_stop_pressed` :605, `_on_menu_start` :609, `_on_menu_generate` :614, `_on_status` :619, `_show_end` :656, `_refresh_end_text` :664, `_update_transport` :676, `_unhandled_key_input` :706, `_rumor` :713, `_rich` :719, `_ind_title` :727, `_send` :734.

### 7.5 Messages reçus du moteur et événements

Les fonctions de `Main` de cette zone du fichier (les en-têtes de section du script délimitent les zones).

```mermaid
classDiagram
    class Main {
        -_on_message(topic: String, data: Dictionary)
        -_on_event(ev: Dictionary)
        -_reset_kpis()
        -_on_indicator(msg: Dictionary)
        -_reset(ev: Dictionary)
    }
    Control <|-- Main
```

Dans le code :
- `godot/scripts/main.gd` fonctions (5) : `_on_message` :740, `_on_event` :768, `_reset_kpis` :1156, `_on_indicator` :1165, `_reset` :1204.

### 7.6 Fil des interactions, règles, confiance

Les fonctions de `Main` de cette zone du fichier (les en-têtes de section du script délimitent les zones).

```mermaid
classDiagram
    class Main {
        -_feed(text: String, ids: Array)
        -_group(key: String, init: Dictionary) Dictionary
        -_feed_group(key: String, text: String, ids: Array)
        -_render_feed()
        -_render_rules()
        -_rule_text(p: Dictionary) String
        -_breach_text(b: Array) String
        -_set_norm_now(n: Dictionary)
        -_norm_card()
        +static trust_bar(v: float) String
        -_set_trust_mode(mode: String)
        -_fill_trust_who()
        -_render_trust()
    }
    Control <|-- Main
```

Dans le code :
- `godot/scripts/main.gd` fonctions (13) : `_feed` :1250, `_group` :1266, `_feed_group` :1275, `_render_feed` :1288, `_render_rules` :1299, `_rule_text` :1334, `_breach_text` :1341, `_set_norm_now` :1349, `_norm_card` :1360, `trust_bar` :1373, `_set_trust_mode` :1381, `_fill_trust_who` :1388, `_render_trust` :1400.

### 7.7 Inspecteur d'agent

Les fonctions de `Main` de cette zone du fichier (les en-têtes de section du script délimitent les zones).

```mermaid
classDiagram
    class Main {
        -_select(id: String)
        -_render_inspector()
    }
    Control <|-- Main
```

Dans le code :
- `godot/scripts/main.gd` fonctions (2) : `_select` :1438, `_render_inspector` :1448.

### 7.8 Utilitaires et boucle d'image

Les fonctions de `Main` de cette zone du fichier (les en-têtes de section du script délimitent les zones).

```mermaid
classDiagram
    class Main {
        -_agent(id: String) Variant
        -_who(id: String) String
        -_tag(text: String, hex: String) String
        -_show_weather()
        -_sky_text(days: Array) String
        -_weather_note(outings: Array) String
        -_day_word(f: float) String
        -_scope(s: String) String
        -_scope_rank(s: String) int
        -_assembly_of(p: Dictionary) String
        -_num(v: Variant) String
        -_esc(s: String) String
        -_process(delta: float)
        -_selftest_report()
    }
    Control <|-- Main
```

Dans le code :
- `godot/scripts/main.gd` fonctions (14) : `_agent` :1541, `_who` :1545, `_tag` :1555, `_show_weather` :1560, `_sky_text` :1574, `_weather_note` :1586, `_day_word` :1602, `_scope` :1606, `_scope_rank` :1614, `_assembly_of` :1619, `_num` :1623, `_esc` :1628, `_process` :1635, `_selftest_report` :1703.

## 8. `StartMenu` (start_menu.gd)

### 8.1 Constantes, signaux et variables

L'état du menu de démarrage : réglages, lignes de pêcheurs, lacs, état du moteur.

```mermaid
classDiagram
    class StartMenu {
        +signal start_requested(config: Dictionary)
        +signal cancelled()
        +signal generate_requested(params: Dictionary)
        +MenuMap : Script
        +W_IDX : int
        +W_NAME : int
        +W_HAMLET : int
        +W_ARCH : int
        +W_BOAT : int
        +W_EXP : int
        +W_WEALTH : int
        +W_DEBT : int
        +W_BRAIN : int
        +W_DEL : int
        +BRAINS : Array
        +catalog : Dictionary
        +fishers : Array
        +selected : int
        +capacity_auto : bool
        +speed_touched : bool
        +reflection_touched : bool
        +can_cancel : bool
        +engine_state : String
        +engine_detail : String
        +engine_online : bool
        +busy : bool
        +busy_since : int
        -_rows : Array
        -_updating : bool
        -_pending_generation : String
        -_pending_since : int
        -_pending_params : Dictionary
        -_regenerate : bool
        -_gen_timer : Timer
        +sheet : PanelContainer
        +lbl_engine : Label
        +spin_seasons : SpinBox
        +spin_seed : SpinBox
        +spin_rounds : SpinBox
        +spin_capacity : SpinBox
        +btn_cap_auto : Button
        +spin_growth : SpinBox
        +btn_growth_default : Button
        +chk_stop_empty : CheckButton
        +lbl_cap_hint : Label
        +opt_comm : OptionButton
        +opt_council : OptionButton
        +chk_climate : CheckButton
        +chk_patrol : CheckButton
        +spin_events : SpinBox
        +spin_luck : SpinBox
        +spin_villages : SpinBox
        +spin_fishers : SpinBox
        +opt_fleet : OptionButton
        +btn_other : Button
        +opt_genmode : OptionButton
        +spin_lakes : SpinBox
        +spin_patrols : SpinBox
        +spin_hold : SpinBox
        +row_cap : Control
        +row_growth : Control
        +row_travel : Control
        +spin_travel_days : SpinBox
        +spin_travel_cost : SpinBox
        +lakes_box : VBoxContainer
        +lakes_state : Array
        +lake_spins : Array
        +btn_generate : Button
        +chk_visible : CheckButton
        +opt_llm : OptionButton
        +lbl_llm_desc : Label
        +opt_reflection : OptionButton
        +lbl_reflection_desc : Label
        +opt_speed : OptionButton
        +lbl_speed_hint : Label
        +chk_elder : CheckButton
        +opt_elder : OptionButton
        +rows_box : VBoxContainer
        +lbl_count : Label
        +lbl_lake : Label
        +btn_add : Button
        +map : Control
        +detail : RichTextLabel
        +lbl_error : Label
        +btn_start : Button
        +btn_cancel : Button
    }
    Control <|-- StartMenu
    class Control {
        <<Godot>>
    }
```

Dans le code :
- `godot/scripts/start_menu.gd` variables (71) : `catalog` :32, `fishers` :33, `selected` :34, `capacity_auto` :35, `speed_touched` :36, `reflection_touched` :37, `can_cancel` :38, `engine_state` :39, `engine_detail` :40, `engine_online` :41, `busy` :42, `busy_since` :43, `_rows` :45, `_updating` :46, `_pending_generation` :47, `_pending_since` :48, `_pending_params` :49, `_regenerate` :50, `_gen_timer` :51, `sheet` :53, `lbl_engine` :54, `spin_seasons` :55, `spin_seed` :56, `spin_rounds` :57, `spin_capacity` :58, `btn_cap_auto` :59, `spin_growth` :60, `btn_growth_default` :61, `chk_stop_empty` :62, `lbl_cap_hint` :63, `opt_comm` :64, `opt_council` :65, `chk_climate` :66, `chk_patrol` :67, `spin_events` :68, `spin_luck` :69, `spin_villages` :70, `spin_fishers` :71, `opt_fleet` :72, `btn_other` :73, `opt_genmode` :74, `spin_lakes` :75, `spin_patrols` :76, `spin_hold` :77, `row_cap` :78, `row_growth` :79, `row_travel` :80, `spin_travel_days` :81, `spin_travel_cost` :82, `lakes_box` :83, `lakes_state` :84, `lake_spins` :85, `btn_generate` :86, `chk_visible` :87, `opt_llm` :88, `lbl_llm_desc` :89, `opt_reflection` :90, `lbl_reflection_desc` :91, `opt_speed` :92, `lbl_speed_hint` :93, `chk_elder` :94, `opt_elder` :95, `rows_box` :96, `lbl_count` :97, `lbl_lake` :98, `btn_add` :99, `map` :100, `detail` :101, `lbl_error` :102, `btn_start` :103, `btn_cancel` :104.
- `godot/scripts/start_menu.gd` constantes (12) : `MenuMap` :12, `W_IDX` :18, `W_NAME` :19, `W_HAMLET` :20, `W_ARCH` :21, `W_BOAT` :22, `W_EXP` :23, `W_WEALTH` :24, `W_DEBT` :25, `W_BRAIN` :26, `W_DEL` :27, `BRAINS` :29.
- `godot/scripts/start_menu.gd` signaux (3) : `start_requested` :14, `cancelled` :15, `generate_requested` :16.

### 8.2 Les nœuds Godot gardés par `StartMenu`

Les champs, listes et boutons du menu conservés dans une variable (agrégation).

```mermaid
classDiagram
    direction LR
    class StartMenu
    class Timer {
        <<Godot>>
    }
    class PanelContainer {
        <<Godot>>
    }
    class Label {
        <<Godot>>
    }
    class SpinBox {
        <<Godot>>
    }
    class Button {
        <<Godot>>
    }
    class CheckButton {
        <<Godot>>
    }
    class OptionButton {
        <<Godot>>
    }
    class Control {
        <<Godot>>
    }
    class VBoxContainer {
        <<Godot>>
    }
    class RichTextLabel {
        <<Godot>>
    }
    StartMenu o-- Timer : "_gen_timer (1)"
    StartMenu o-- PanelContainer : "sheet (1)"
    StartMenu o-- Label : "lbl_engine, lbl_cap_hint, lbl_llm_desc, lbl_reflection_desc, lbl_speed_hint, lbl_count, lbl_lake, lbl_error (8)"
    StartMenu o-- SpinBox : "spin_seasons, spin_seed, spin_rounds, spin_capacity, spin_growth, spin_events, spin_luck, spin_villages, spin_fishers, spin_lakes, spin_patrols, spin_hold, spin_travel_days, spin_travel_cost (14)"
    StartMenu o-- Button : "btn_cap_auto, btn_growth_default, btn_other, btn_generate, btn_add, btn_start, btn_cancel (7)"
    StartMenu o-- CheckButton : "chk_stop_empty, chk_climate, chk_patrol, chk_visible, chk_elder (5)"
    StartMenu o-- OptionButton : "opt_comm, opt_council, opt_fleet, opt_genmode, opt_llm, opt_reflection, opt_speed, opt_elder (8)"
    StartMenu o-- Control : "row_cap, row_growth, row_travel, map (4)"
    StartMenu o-- VBoxContainer : "lakes_box, rows_box (2)"
    StartMenu o-- RichTextLabel : "detail (1)"
```

Dans le code :
- `godot/scripts/start_menu.gd` : Timer `_gen_timer` :51; PanelContainer `sheet` :53; Label `lbl_engine` :54, `lbl_cap_hint` :63, `lbl_llm_desc` :89, `lbl_reflection_desc` :91, `lbl_speed_hint` :93, `lbl_count` :97, `lbl_lake` :98, `lbl_error` :102; SpinBox `spin_seasons` :55, `spin_seed` :56, `spin_rounds` :57, `spin_capacity` :58, `spin_growth` :60, `spin_events` :68, `spin_luck` :69, `spin_villages` :70, `spin_fishers` :71, `spin_lakes` :75, `spin_patrols` :76, `spin_hold` :77, `spin_travel_days` :81, `spin_travel_cost` :82; Button `btn_cap_auto` :59, `btn_growth_default` :61, `btn_other` :73, `btn_generate` :86, `btn_add` :99, `btn_start` :103, `btn_cancel` :104; CheckButton `chk_stop_empty` :62, `chk_climate` :66, `chk_patrol` :67, `chk_visible` :87, `chk_elder` :94; OptionButton `opt_comm` :64, `opt_council` :65, `opt_fleet` :72, `opt_genmode` :74, `opt_llm` :88, `opt_reflection` :90, `opt_speed` :92, `opt_elder` :95; Control `row_cap` :78, `row_growth` :79, `row_travel` :80, `map` :100; VBoxContainer `lakes_box` :83, `rows_box` :96; RichTextLabel `detail` :101.

### 8.3 Construction de l'interface

Les fonctions de `StartMenu` de cette zone du fichier.

```mermaid
classDiagram
    class StartMenu {
        -_ready()
        -_fit()
        -_lbl(text: String, size: int, kind: String, col: Color) Label
        -_section(text: String) Label
        -_compact(le: LineEdit)
        -_spin(lo: float, hi: float, step: float, value: float, width: int) SpinBox
        -_option(items: Array, width: int) OptionButton
        -_seg(text: String, group: ButtonGroup) Button
        -_row(parent: Control, title: String, w: Control) Control
        -_build()
        -_build_left(body: Control)
        -_ai_choice(title: String, opt: OptionButton, width: int) VBoxContainer
        -_note(col: Control, col_color: Color) Label
        -_build_ai_strip(col: Control)
        -_build_center(body: Control)
        -_build_right(body: Control)
    }
    Control <|-- StartMenu
```

Dans le code :
- `godot/scripts/start_menu.gd` fonctions (16) : `_ready` :107, `_fit` :118, `_lbl` :123, `_section` :132, `_compact` :136, `_spin` :148, `_option` :160, `_seg` :173, `_row` :192, `_build` :205, `_build_left` :292, `_ai_choice` :455, `_note` :464, `_build_ai_strip` :473, `_build_center` :503, `_build_right` :612.

### 8.4 Catalogue et réinitialisation

Les fonctions de `StartMenu` de cette zone du fichier.

```mermaid
classDiagram
    class StartMenu {
        -_same_but_valley(a: Dictionary, b: Dictionary) bool
        +set_catalog(cat: Dictionary)
        +reset_all()
        +reset_population()
        -_select_meta(o: OptionButton, meta: Variant)
        -_same(a: Variant, b: Variant) bool
        -_speed_text(s: float) String
        -_llm_option() Dictionary
        -_show_llm(i: int)
        -_show_reflection(i: int)
        -_suggest_reflection()
        -_recommended_speed() float
        -_suggest_speed()
        -_refresh_hints()
    }
    Control <|-- StartMenu
```

Dans le code :
- `godot/scripts/start_menu.gd` fonctions (14) : `_same_but_valley` :641, `set_catalog` :650, `reset_all` :728, `reset_population` :773, `_select_meta` :783, `_same` :791, `_speed_text` :799, `_llm_option` :811, `_show_llm` :817, `_show_reflection` :822, `_suggest_reflection` :829, `_recommended_speed` :840, `_suggest_speed` :844, `_refresh_hints` :855.

### 8.5 Pêcheurs, lacs et génération

Les fonctions de `StartMenu` de cette zone du fichier.

```mermaid
classDiagram
    class StartMenu {
        -_archetypes() Array
        -_arch_index(id: String) int
        -_boat_index(id: String) int
        -_brain_index(f: Dictionary) int
        -_add_fisher()
        -_remove_fisher(i: int)
        -_rebuild_rows()
        -_row_style(sel: bool) StyleBoxFlat
        -_on_archetype(i: int, k: int)
        -_row_sync(i: int)
        -_select(i: int)
        -_tier_text(f: Dictionary) String
        -_refresh_all(_full: bool)
        -_num(v: float) String
        +lake_capacity() float
        -_auto_capacity() float
        -_holds() float
        -_is_random() bool
        -_use_rows() bool
        -_apply_generation()
        -_set_gen_enabled()
        -_load_lakes()
        -_rebuild_lake_rows()
        -_lake_capacity(k: int) float
        -_refresh_lake()
        -_refresh_lake_rows(d: Dictionary)
    }
    Control <|-- StartMenu
```

Dans le code :
- `godot/scripts/start_menu.gd` fonctions (26) : `_archetypes` :863, `_arch_index` :867, `_boat_index` :875, `_brain_index` :883, `_add_fisher` :890, `_remove_fisher` :921, `_rebuild_rows` :931, `_row_style` :1023, `_on_archetype` :1032, `_row_sync` :1044, `_select` :1058, `_tier_text` :1065, `_refresh_all` :1076, `_num` :1104, `lake_capacity` :1109, `_auto_capacity` :1113, `_holds` :1120, `_is_random` :1130, `_use_rows` :1135, `_apply_generation` :1140, `_set_gen_enabled` :1160, `_load_lakes` :1171, `_rebuild_lake_rows` :1190, `_lake_capacity` :1240, `_refresh_lake` :1253, `_refresh_lake_rows` :1286.

### 8.6 Envoi de la configuration

Les fonctions de `StartMenu` de cette zone du fichier.

```mermaid
classDiagram
    class StartMenu {
        -_on_gen_spin(_v: float, villages_touched: bool)
        -_sync_generation()
        -_fleet_id() String
        -_on_generate()
        -_lake_request() Dictionary
        +build_config() Dictionary
        -_on_start()
    }
    Control <|-- StartMenu
```

Dans le code :
- `godot/scripts/start_menu.gd` fonctions (7) : `_on_gen_spin` :1313, `_sync_generation` :1325, `_fleet_id` :1332, `_on_generate` :1336, `_lake_request` :1358, `build_config` :1377, `_on_start` :1402.

### 8.7 État du moteur et ouverture

Les fonctions de `StartMenu` de cette zone du fichier.

```mermaid
classDiagram
    class StartMenu {
        +open(cancelable: bool)
        +close()
        +show_error(text: String)
        +set_engine(state: String, online: bool, detail: String)
        -_update_state()
        -_process(_delta: float)
    }
    Control <|-- StartMenu
```

Dans le code :
- `godot/scripts/start_menu.gd` fonctions (6) : `open` :1417, `close` :1424, `show_error` :1429, `set_engine` :1438, `_update_state` :1447, `_process` :1473.

## 9. `WorldView` (world_view.gd) : la carte de la vallée

### 9.1 Constantes et signal

Constantes de mise en page (hameaux, lacs, anneau du conseil, zoom, vitesses) et le signal `agent_clicked`.

```mermaid
classDiagram
    class WorldView {
        +signal agent_clicked(agent_id: String)
        +DEFAULT_HAMLETS : Array
        +SLOTS : Dictionary
        +LAYOUTS : Dictionary
        +ELDER_POS : Vector2
        +LAKE_C : Vector2
        +LAKE_R : Vector2
        +MAX_LAKES : int
        +LAKE_BOXES : Dictionary
        +ROOM : Rect2
        +RING_R : Vector2
        +ISO_LAKE_K : Dictionary
        +LOTS_PER_W : int
        +ZOOM_MAX : float
        +MARGIN_K : float
        +LAND_SPEED : float
        +WATER_SPEED : float
        +DUSK : Color
        +NIGHT : Color
        +BOAT_SCALE : Dictionary
    }
    Control <|-- WorldView
```

Dans le code :
- `godot/scripts/world_view.gd` constantes (19) : `DEFAULT_HAMLETS` :19, `SLOTS` :22, `LAYOUTS` :26, `ELDER_POS` :31, `LAKE_C` :32, `LAKE_R` :33, `MAX_LAKES` :36, `LAKE_BOXES` :37, `ROOM` :44, `RING_R` :45, `ISO_LAKE_K` :48, `LOTS_PER_W` :54, `ZOOM_MAX` :55, `MARGIN_K` :56, `LAND_SPEED` :57, `WATER_SPEED` :58, `DUSK` :59, `NIGHT` :60, `BOAT_SCALE` :1975.
- `godot/scripts/world_view.gd` signaux (1) : `agent_clicked` :17.

### 9.2 Variables

L'état de la carte : couches, personnages, caméra, lacs, mailles, patrouille, salon, effets.

```mermaid
classDiagram
    class WorldView {
        +terrain : ColorRect
        +decor : Control
        +under : Control
        +shade : Control
        +lights : Control
        +over : Control
        +mat : ShaderMaterial
        +agents : Dictionary
        +order : Array
        +stock_ratio : float
        +stock_t : float
        +capacity : float
        +collapsed : bool
        +selected : String
        +hovered : String
        +animate : bool
        +seen_outing : bool
        +paused : bool
        +thinking : Array
        +time_scale : float
        +effects : Array
        +bubbles : Dictionary
        +badges : Dictionary
        +rules : Array
        +cur_season : int
        -_proposal_author : Dictionary
        +season_days : float
        +sim_time : float
        +light : float
        +phase : String
        +assembly_scope : String
        +hamlet_pos : Variant
        +lakes : Array
        +iso_o : Vector2
        +iso_a : float
        +iso_b : float
        +iso_sq : float
        +iso_ex : Vector2
        +cam : Control
        +top : Control
        +zoom : float
        +zoom_min : float
        +cam_off : Vector2
        +council_c : Variant
        +council_r : Variant
        +elder_pos : Variant
        +world_k : float
        +PARCELS : int
        +n_lots : int
        +n_steps : int
        +world : Vector2
        +dragging : bool
        +glide : bool
        +glide_to : Vector2
        +mini_drag : bool
        +show_mesh : bool
        +lake_cells : Array
        +parcel_lake : PackedInt32Array
        +field : PackedFloat32Array
        +mask_img : Image
        +walk : AStarGrid2D
        +sail : AStarGrid2D
        +hamlet_lake : Dictionary
        +patrol_routes : Dictionary
        +patrol_season : int
        +salon_ids : Array
        +salon : Control
        +btn_salon_min : Button
        +btn_salon_open : Button
        -_salon_draw : bool
        +hamlet_fires : Array
        +dry : float
        +t : float
        +banners : Array
        +deco : Dictionary
        +fish : Array
        +wakes : Array
        +splashes : Array
    }
    Control <|-- WorldView
```

Dans le code :
- `godot/scripts/world_view.gd` variables (78) : `terrain` :62, `decor` :63, `under` :64, `shade` :65, `lights` :66, `over` :67, `mat` :68, `agents` :70, `order` :71, `stock_ratio` :72, `stock_t` :73, `capacity` :74, `collapsed` :75, `selected` :76, `hovered` :77, `animate` :78, `seen_outing` :79, `paused` :80, `thinking` :81, `time_scale` :82, `effects` :83, `bubbles` :84, `badges` :85, `rules` :86, `cur_season` :87, `_proposal_author` :88, `season_days` :91, `sim_time` :92, `light` :93, `phase` :94, `assembly_scope` :95, `hamlet_pos` :96, `lakes` :97, `iso_o` :98, `iso_a` :99, `iso_b` :100, `iso_sq` :101, `iso_ex` :102, `cam` :104, `top` :105, `zoom` :106, `zoom_min` :107, `cam_off` :108, `council_c` :109, `council_r` :110, `elder_pos` :111, `world_k` :112, `PARCELS` :113, `n_lots` :114, `n_steps` :115, `world` :116, `dragging` :117, `glide` :118, `glide_to` :119, `mini_drag` :120, `show_mesh` :121, `lake_cells` :123, `parcel_lake` :124, `field` :125, `mask_img` :126, `walk` :127, `sail` :128, `hamlet_lake` :129, `patrol_routes` :130, `patrol_season` :131, `salon_ids` :132, `salon` :133, `btn_salon_min` :134, `btn_salon_open` :135, `_salon_draw` :136, `hamlet_fires` :137, `dry` :138, `t` :139, `banners` :140, `deco` :143, `fish` :144, `wakes` :145, `splashes` :146.

### 9.3 Les nœuds Godot gardés par `WorldView`

Les couches et widgets créés par le code et gardés dans une variable.

```mermaid
classDiagram
    direction LR
    class WorldView
    class ColorRect {
        <<Godot>>
    }
    class Control {
        <<Godot>>
    }
    class ShaderMaterial {
        <<Godot>>
    }
    class Image {
        <<Godot>>
    }
    class Button {
        <<Godot>>
    }
    WorldView o-- ColorRect : "terrain (1)"
    WorldView o-- Control : "decor, under, shade, lights, over, cam, top, salon (8)"
    WorldView o-- ShaderMaterial : "mat (1)"
    WorldView o-- Image : "mask_img (1)"
    WorldView o-- Button : "btn_salon_min, btn_salon_open (2)"
```

Dans le code :
- `godot/scripts/world_view.gd` : ColorRect `terrain` :62; Control `decor` :63, `under` :64, `shade` :65, `lights` :66, `over` :67, `cam` :104, `top` :105, `salon` :133; ShaderMaterial `mat` :68; Image `mask_img` :126; Button `btn_salon_min` :134, `btn_salon_open` :135.

### 9.4 Caméra, mise en page, entrées

Création des couches, ajustement de la caméra (zoom, déplacement, glissement) et touches.

```mermaid
classDiagram
    class WorldView {
        -_ready()
        -_layer(c: Control) Control
        -_on_resized()
        -_set_world(k: float, grid: int)
        -_layout_world()
        -_center_view()
        -_apply_cam()
        +zoom_at(screen: Vector2, factor: float)
        +pan(by: Vector2)
        -_scr(n: Vector2) Vector2
        +glide_to_ground(n: Vector2)
        -_scroll(dt: float)
        -_unhandled_input(event: InputEvent)
        +static iso_boxes(n: int, k: float) Array
        +static lake_boxes(n: int, k: float) Array
        +static layout(names: Array, lake_of: Dictionary, n_lakes: int, kscale: float) Dictionary
        +static lake_shape(th: float) float
    }
    Control <|-- WorldView
```

Dans le code :
- `godot/scripts/world_view.gd` fonctions (17) : `_ready` :149, `_layer` :202, `_on_resized` :209, `_set_world` :228, `_layout_world` :237, `_center_view` :247, `_apply_cam` :257, `zoom_at` :273, `pan` :281, `_scr` :288, `glide_to_ground` :293, `_scroll` :299, `_unhandled_input` :332, `iso_boxes` :352, `lake_boxes` :359, `layout` :369, `lake_shape` :396.

### 9.5 Lacs, eau et champ d'eau

Où est l'eau, quel lac, les parcelles, le masque envoyé au shader, les hameaux et leurs lacs.

```mermaid
classDiagram
    class WorldView {
        +water_at(n: Vector2) float
        +is_water(n: Vector2) bool
        -_lake_at(n: Vector2) int
        -_parcel_pos(c: Vector2i) Vector2
        -_build_lakes()
        -_update_council()
        -_build_field()
        -_refresh_fish_layer()
        +lake_point(th: float, rn: float, k: int) Vector2
        -_lake_of_hamlet(h: String) int
        -_lake_named(zone: String, fallback: int) int
        -_push_lakes()
        -_ratio(k: int) float
        -_px(n: Vector2) Vector2
        -_nm(p: Vector2) Vector2
    }
    Control <|-- WorldView
```

Dans le code :
- `godot/scripts/world_view.gd` fonctions (15) : `water_at` :401, `is_water` :415, `_lake_at` :420, `_parcel_pos` :435, `_build_lakes` :441, `_update_council` :477, `_build_field` :490, `_refresh_fish_layer` :549, `lake_point` :562, `_lake_of_hamlet` :567, `_lake_named` :572, `_push_lakes` :580, `_ratio` :589, `_px` :594, `_nm` :599.

### 9.6 Salon de la veillée et isométrie

Le rectangle du salon, les places assises, la projection isométrique.

```mermaid
classDiagram
    class WorldView {
        -_salon_rect() Rect2
        -_seat(id: String) Vector2
        -_apt(id: String) Vector2
        -_salon_on() bool
        +set_salon(on: bool)
        -_update_iso()
        -_ground_ellipse(ci: CanvasItem, c: Vector2, r: Vector2, col: Color, n: int)
    }
    Control <|-- WorldView
```

Dans le code :
- `godot/scripts/world_view.gd` fonctions (7) : `_salon_rect` :607, `_seat` :612, `_apt` :622, `_salon_on` :626, `set_salon` :631, `_update_iso` :639, `_ground_ellipse` :650.

### 9.7 Mailles et chemins

Les trois mailles (parcelles, lots, pas), les grilles A* pour les marcheurs et les barques, les appontements.

```mermaid
classDiagram
    class WorldView {
        -_step_of(n: Vector2) Vector2i
        -_step_pos(c: Vector2i) Vector2
        -_lot_pos(c: Vector2i) Vector2
        -_build_grids()
        -_free_step(c: Vector2i, g: AStarGrid2D) Vector2i
        -_route(a: Vector2, b: Vector2, g: AStarGrid2D) Array
        -_land_route(a: Vector2, b: Vector2) Array
        -_snap_water(p: Vector2) Vector2
        -_dock(k: int, from: Vector2) Dictionary
    }
    Control <|-- WorldView
```

Dans le code :
- `godot/scripts/world_view.gd` fonctions (9) : `_step_of` :659, `_step_pos` :663, `_lot_pos` :667, `_build_grids` :672, `_free_step` :688, `_route` :708, `_land_route` :724, `_snap_water` :729, `_dock` :738.

### 9.8 Décor

Maisons, arbres, chemins, ponts : génération et dessin.

```mermaid
classDiagram
    class WorldView {
        -_house_at(lot: Vector2i, rng: RandomNumberGenerator, elder: bool) Dictionary
        -_lot_free(lot: Vector2i, homes: Array) bool
        -_generate_decor()
        -_screen_near(a: Vector2, b: Vector2, radius: float) bool
        -_road_px(a: Vector2, b: Vector2) PackedVector2Array
        -_curve(a: Vector2, b: Vector2, bend: float, n: int) PackedVector2Array
        -_draw_decor(ci: CanvasItem)
        -_tree(ci: CanvasItem, tr: Dictionary)
        -_house(ci: CanvasItem, hs: Dictionary)
        -_ellipse(ci: CanvasItem, c: Vector2, r: Vector2, col: Color, n: int)
        -_star(ci: CanvasItem, c: Vector2, r: float, col: Color, n: int)
        -_fire_pos() Vector2
    }
    Control <|-- WorldView
```

Dans le code :
- `godot/scripts/world_view.gd` fonctions (12) : `_house_at` :762, `_lot_free` :780, `_generate_decor` :794, `_screen_near` :903, `_road_px` :909, `_curve` :923, `_draw_decor` :934, `_tree` :990, `_house` :1016, `_ellipse` :1052, `_star` :1060, `_fire_pos` :1069.

### 9.9 État du monde et événements

Remise à zéro à `run_start`, représentants, propositions, et `on_event` qui anime la carte.

```mermaid
classDiagram
    class WorldView {
        +reset_world(agent_list: Array, cap: float, days: float, hamlets: Array, lake_info: Array, map: Dictionary)
        +set_rep(hamlet: String, id: String)
        +remember_proposal(pid: String, author: String)
        +on_event(ev: Dictionary)
    }
    Control <|-- WorldView
```

Dans le code :
- `godot/scripts/world_view.gd` fonctions (4) : `reset_world` :1076, `set_rep` :1158, `remember_proposal` :1164, `on_event` :1168.

### 9.10 Bandeaux, déplacements, trajets, patrouille

Bandeaux, déplacement des personnages, trajets de pêche, route de la patrouille, liens et marques, poissons.

```mermaid
classDiagram
    class WorldView {
        -_banner(title: String, sub: String, col: Color)
        -_move(id: String, target: Vector2, speed: float)
        -_fishing_spot(a: Dictionary, zone: String, cell: Variant) Vector2
        -_trip(a: Dictionary, dk: Dictionary, spot: Vector2) Array
        -_zone_pos(zone: String) Vector2
        -_patrol_pos(legs: Array, idx: int) Vector2
        -_draw_patrol(ci: CanvasItem)
        -_draw_patrol_boat(ci: CanvasItem, p: Vector2, idx: int)
        -_link(a: String, b: String, col: Color, width: float, ttl: float, kind: String)
        -_mark(id: String, txt: String, col: Color, ttl: float)
        -_short(s: String, n: int) String
        -_num(v: Variant) String
        -_sync_fish(instant: bool)
        -_update_fish(dt: float)
    }
    Control <|-- WorldView
```

Dans le code :
- `godot/scripts/world_view.gd` fonctions (14) : `_banner` :1385, `_move` :1396, `_fishing_spot` :1409, `_trip` :1426, `_zone_pos` :1444, `_patrol_pos` :1451, `_draw_patrol` :1466, `_draw_patrol_boat` :1477, `_link` :1497, `_mark` :1504, `_short` :1511, `_num` :1515, `_sync_fish` :1521, `_update_fish` :1553.

### 9.11 Boucle d'image, clics, règles

`_process`, clic et survol, règles en vigueur et leur dessin.

```mermaid
classDiagram
    class WorldView {
        -_process(delta: float)
        -_gui_input(event: InputEvent)
        -_pick(pos: Vector2) String
        -_set_rule(n: Dictionary)
        -_draw_rules(ci: CanvasItem)
        -_draw_lake_rules(ci: CanvasItem)
    }
    Control <|-- WorldView
```

Dans le code :
- `godot/scripts/world_view.gd` fonctions (6) : `_process` :1571, `_gui_input` :1648, `_pick` :1684, `_set_rule` :1697, `_draw_rules` :1708, `_draw_lake_rules` :1757.

### 9.12 Dessin : sol, lumière, feu, salon, liens, barques, pions

Les couches de dessin du sol au pion.

```mermaid
classDiagram
    class WorldView {
        -_draw_under(ci: CanvasItem)
        -_darkness() float
        -_draw_shade(ci: CanvasItem)
        -_draw_lights(ci: CanvasItem)
        -_draw_fire(ci: CanvasItem, p: Vector2, s: float)
        -_draw_salon(ci: CanvasItem)
        -_bez_pts(pa: Vector2, pb: Vector2, bend: float, n: int) PackedVector2Array
        -_draw_links(ci: CanvasItem)
        -_draw_boat(ci: CanvasItem, origin: Vector2, heading: float, col: Color, fishing: float, k: float)
        -_draw_boat_local(ci: CanvasItem, heading: float, col: Color, fishing: float, k: float)
        -_lbl_hit(r: Rect2, placed: Array) bool
        -_draw_tokens(ci: CanvasItem)
    }
    Control <|-- WorldView
```

Dans le code :
- `godot/scripts/world_view.gd` fonctions (12) : `_draw_under` :1769, `_darkness` :1811, `_draw_shade` :1815, `_draw_lights` :1824, `_draw_fire` :1849, `_draw_salon` :1864, `_bez_pts` :1928, `_draw_links` :1932, `_draw_boat` :1978, `_draw_boat_local` :1984, `_lbl_hit` :2012, `_draw_tokens` :2019.

### 9.13 Dessin : marques, bulles, panneaux, HUD, bandeau, mini-carte, mailles

Les couches de dessin du dessus et la mini-carte.

```mermaid
classDiagram
    class WorldView {
        +set_thinking(ids: Array)
        -_draw_marks(ci: CanvasItem)
        -_draw_bubbles(ci: CanvasItem, reserved: Array)
        -_draw_signs(ci: CanvasItem)
        -_draw_hud(ci: CanvasItem)
        -_draw_lake_gauges(ci: CanvasItem, gw: float)
        -_draw_banner(ci: CanvasItem)
        -_draw_top(ci: CanvasItem)
        -_draw_over(ci: CanvasItem)
        -_mini_rect() Rect2
        -_mini_pt(p: Vector2, r: Rect2) Vector2
        -_mini_goto(pos: Vector2)
        -_draw_mini(ci: CanvasItem)
        -_cell_poly(c: Vector2, side: float) PackedVector2Array
        -_draw_mesh(ci: CanvasItem)
    }
    Control <|-- WorldView
```

Dans le code :
- `godot/scripts/world_view.gd` fonctions (15) : `set_thinking` :2067, `_draw_marks` :2073, `_draw_bubbles` :2095, `_draw_signs` :2154, `_draw_hud` :2171, `_draw_lake_gauges` :2232, `_draw_banner` :2255, `_draw_top` :2281, `_draw_over` :2293, `_mini_rect` :2311, `_mini_pt` :2318, `_mini_goto` :2322, `_draw_mini` :2330, `_cell_poly` :2354, `_draw_mesh` :2360.

## 10. `Demo` (demo.gd) : le lecteur de la vidéo de démonstration

### 10.1 Variables, constantes et fonctions

Lancé par `Main` seulement avec `--demo=scénario.json` : rejoue un journal dans `main._on_event` au rythme du scénario (temps de vidéo), pilote la caméra, les mailles, l'onglet et l'inspecteur, lit la voix et affiche le sous-titre. En mode démo, `Main` ne se connecte pas au moteur.

```mermaid
classDiagram
    class Demo {
        +TITLE_S : float
        +CAM_S : float
        +main : Variant
        +beats : Array
        +events : Array
        +next_ev : int
        +inds : Array
        +next_ind : int
        +chunks : Array
        +band : PanelContainer
        +narr_len : float
        +bi : int
        +narr_left : float
        +bt : float
        +dur : float
        +t_end : float
        +sched : Array
        +sched_i : int
        +pace : Dictionary
        +elapsed : float
        +end_left : float
        +player : AudioStreamPlayer
        +sub : Label
        +title : ColorRect
        +cam_t : float
        +cam_from : Vector2
        +cam_off_from : Vector2
        +cam_to_zoom : float
        +cam_to_ground : Vector2
        +base_dir : String
        +start(m, path: String)
        -_feed_until(t: float)
        -_ground(target: String) Vector2
        -_split(text: String) Array
        -_show_chunk(f: float)
        -_place_band()
        -_schedule(b: Dictionary)
        -_begin(b: Dictionary)
        -_step_cam(delta: float)
        -_process(delta: float)
    }
    Node <|-- Demo
    class Node {
        <<Godot>>
    }
    class Main
    Demo o-- Main : main
```

Dans le code :
- `godot/scripts/demo.gd` fonctions (10) : `start` :39, `_feed_until` :95, `_ground` :104, `_split` :118, `_show_chunk` :131, `_place_band` :145, `_schedule` :154, `_begin` :206, `_step_cam` :243, `_process` :255.
- `godot/scripts/demo.gd` variables (28) : `main` :9, `beats` :10, `events` :11, `next_ev` :12, `inds` :13, `next_ind` :14, `chunks` :15, `band` :16, `narr_len` :17, `bi` :18, `narr_left` :19, `bt` :20, `dur` :21, `t_end` :22, `sched` :23, `sched_i` :24, `pace` :25, `elapsed` :26, `end_left` :27, `player` :28, `sub` :29, `title` :30, `cam_t` :31, `cam_from` :32, `cam_off_from` :33, `cam_to_zoom` :34, `cam_to_ground` :35, `base_dir` :36.
- `godot/scripts/demo.gd` constantes (2) : `TITLE_S` :6, `CAM_S` :7.

## 11. Le shader `valley.gdshader`

Le shader est un élément du diagramme (stéréotype `<<shader>>`) : ses `uniform` sont les paramètres que `WorldView` lui envoie (`mat.set_shader_parameter`), ses fonctions sont les fonctions GLSL de Godot. `fragment()` calcule la couleur de chaque pixel du sol.

```mermaid
classDiagram
    class Valley {
        <<shader>>
        +uniform lake_mask : sampler2D
        +uniform lake_n : int
        +uniform grid : int
        +uniform mesh : bool
        +uniform px_size : vec2
        +uniform iso_o : vec2
        +uniform iso_ab : vec2
        +uniform world_k : float
        +uniform dry : float
        +uniform t_offset : float
        +hash(vec2 p) float
        +noise(vec2 p) float
        +fbm(vec2 p) float
        +to_ground(vec2 s) vec2
        +on_ground(vec2 g) bool
        +fragment() void
    }
    class WorldView
    WorldView ..> Valley : "set_shader_parameter"
```

Dans le code :
- `godot/shaders/valley.gdshader` uniforms (10) : `lake_mask` :8, `lake_n` :9, `grid` :10, `mesh` :11, `px_size` :12, `iso_o` :13, `iso_ab` :14, `world_k` :15, `dry` :16, `t_offset` :17.
- Fonctions (6) : `hash` :19, `noise` :20, `fbm` :27, `to_ground` :34, `on_ground` :38, `fragment` :40.

## 12. Couverture : fonctions du code et des diagrammes

Comptage mécanique : les `func` nommées de chaque script (en début de ligne, `static` compris) contre les méthodes écrites dans les diagrammes des sections 3 à 10. Les fonctions anonymes (`func() -> void:` passées à `connect`) ne sont pas des méthodes et ne sont pas comptées. Les scripts de test de `godot/tests/` ne font pas partie de ces diagrammes.

| Script | `func` dans le code | fonctions dans les diagrammes | variables (code / diagrammes) | constantes (code / diagrammes) | signaux (code / diagrammes) |
|---|---|---|---|---|---|
| `art.gd` | 10 | 10 | 1 / 1 | 18 / 18 | 0 / 0 |
| `chart.gd` | 6 | 6 | 5 / 5 | 4 / 4 | 0 / 0 |
| `demo.gd` | 10 | 10 | 28 / 28 | 2 / 2 | 0 / 0 |
| `legend.gd` | 3 | 3 | 1 / 1 | 0 / 0 | 0 / 0 |
| `main.gd` | 57 | 57 | 80 / 80 | 10 / 10 | 0 / 0 |
| `menu_map.gd` | 15 | 15 | 12 / 12 | 1 / 1 | 2 / 2 |
| `start_menu.gd` | 69 | 69 | 71 / 71 | 12 / 12 | 3 / 3 |
| `world_view.gd` | 111 | 111 | 78 / 78 | 19 / 19 | 1 / 1 |
| `ws_client.gd` | 5 | 5 | 4 / 4 | 1 / 1 | 2 / 2 |
| Total | 286 | 286 | | | |
