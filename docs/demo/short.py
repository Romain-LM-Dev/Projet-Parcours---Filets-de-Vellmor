"""Vidéo courte (réseaux sociaux), verticale ou paysage, d'après short.json et la capture SANS sous-titre de la démo
(`--no-captions`, même minutage que FILETS-demo.mp4). Voix edge-tts (seul le texte part chez Microsoft), sous-titres mot à mot et titres
en ASS (libass), plans recadrés par ffmpeg (plans fixes, coupes franches : pas de zoom).
    python short.py <ffmpeg> <capture sans sous-titre .avi> [portrait|paysage]      (python avec le paquet edge-tts)"""
import asyncio
import json
import re
import subprocess
import sys
import wave
from pathlib import Path

import edge_tts

here = Path(__file__).parent
sc = json.loads((here / "short.json").read_text(encoding="utf8"))
ffmpeg, capture = sys.argv[1], str(Path(sys.argv[2]).resolve())
FMT = sys.argv[3] if len(sys.argv) > 3 else "portrait"
F = sc["formats"][FMT]
out = here / F["out"]
work = here / "voice" / "short"          # (docs/demo/voice/ n'est pas versionné)
work.mkdir(parents=True, exist_ok=True)
W, H = F["size"]
FPS = sc["fps"]
C = sc["colors"]
GAP = 0.15                               # souffle entre deux phrases


def run(cmd: list, cwd=None) -> None:
    subprocess.run([str(c) for c in cmd], check=True, cwd=cwd)


def ass_color(hex6: str) -> str:
    return f"&H00{hex6[4:6]}{hex6[2:4]}{hex6[0:2]}&"


def spoken(text: str) -> str:
    """Le texte tel que la voix doit le dire (`pron` : liaisons, sigles), le reste tel quel."""
    for pattern, say, _, _ in sc.get("pron", []):
        text = re.sub(pattern, say, text)
    return text


def regroup(words: list) -> list:
    """Les mots minutés de la voix, rendus au sous-titre (« zi-a » → « IA », « I » « A » « B » « D » → « IABD »)."""
    key = lambda s: re.sub(r"\W", "", s).upper()                                   # noqa: E731
    targets = {key(heard): show for _, _, heard, show in sc.get("pron", [])}
    out, i = [], 0
    while i < len(words):
        for j in range(min(len(words), i + 6), i, -1):                             # le plus long d'abord ; « I A » peut venir d'un bloc
            if key("".join(w[2] for w in words[i:j])) in targets:
                out.append((words[i][0], words[j - 1][1], targets[key("".join(w[2] for w in words[i:j]))]))
                i = j
                break
        else:
            out.append(words[i])
            i += 1
    return out


async def speak(i: int, text: str):
    """(wav, durée, mots [(début, fin, texte)]) d'une phrase ; le service répond parfois sans audio : on réessaie."""
    mp3, wav = work / f"{i:02d}.mp3", work / f"{i:02d}.wav"
    for _ in range(4):
        words, chunks = [], []
        try:
            com = edge_tts.Communicate(spoken(text), sc["voice"]["name"], rate=sc["voice"]["rate"], boundary="WordBoundary")
            async for ch in com.stream():
                if ch["type"] == "audio":
                    chunks.append(ch["data"])
                elif ch["type"] == "WordBoundary":
                    words.append((ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7, ch["text"]))
            break
        except edge_tts.exceptions.NoAudioReceived:
            await asyncio.sleep(2)
    else:
        raise SystemExit(f"pas de voix pour : {text}")
    mp3.write_bytes(b"".join(chunks))
    run([ffmpeg, "-y", "-loglevel", "error", "-i", mp3, "-ar", "48000", "-ac", "1", wav])
    with wave.open(str(wav)) as w:
        return wav, w.getnframes() / w.getframerate(), regroup(words)


def crop_of(c):
    return sc["crops"][c] if isinstance(c, str) else c


def background(top: str) -> Path:
    """Un fond fixe en dégradé vertical : la couleur `top` en haut, un bleu nuit très sombre en bas (une image, faite une fois)."""
    path = work / f"bg_{top}_{W}x{H}.png"
    if not path.exists():
        a, b = C[top], "0A1230"
        ch = lambda h, i: int(h[2 * i:2 * i + 2], 16)                     # noqa: E731
        expr = {c: f"{ch(a, i)}+({ch(b, i) - ch(a, i)})*Y/H" for i, c in enumerate("rgb")}
        run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=s={W}x{H}", "-vf",
             f"format=gbrp,geq=r='{expr['r']}':g='{expr['g']}':b='{expr['b']}'", "-frames:v", "1", "-update", "1", path])
    return path


def render_shot(k: int, s: dict | None, dur: float) -> Path:
    """Un plan de `dur` s : fond dégradé, la partie floutée et teintée de bleu nuit sur la zone `blur`, l'extrait net tenu dans la
    zone `fit` (plan fixe) ; sans `s` : le fond seul (carte de fin)."""
    path = work / f"shot{k:02d}.mp4"
    n = round(dur * FPS)
    bg = background("blue" if s is None else "night")
    if s is None:                                       # carte de fin : le fond, puis le logo de l'école sur une carte blanche
        cy, cw = F["end"]["logo"]
        pad, rad = cw // 12, cw // 20
        lw = cw - 2 * pad
        lh = round(lw * 652 / 1562 / 2) * 2                                  # (proportions du logo rendu)
        ch = lh + 2 * pad
        alpha = (f"if(gt(abs(X-W/2),W/2-{rad})*gt(abs(Y-H/2),H/2-{rad}),"
                 f"if(lte(hypot(abs(X-W/2)-(W/2-{rad}),abs(Y-H/2)-(H/2-{rad})),{rad}),255,0),255)")
        graph = (f"color=c=white:s={cw}x{ch}:r={FPS},format=rgba,geq=r=255:g=255:b=255:a='{alpha}'[card];"
                 f"[1:v]scale={lw}:{lh}:flags=lanczos[logo];[card][logo]overlay={pad}:{pad}:format=auto,"
                 f"fade=t=in:st=0.9:d=0.35:alpha=1[c];[0:v][c]overlay={(W - cw) // 2}:{cy - ch // 2}:shortest=1[v]")
        run([ffmpeg, "-y", "-loglevel", "error", "-loop", "1", "-framerate", FPS, "-i", bg, "-loop", "1", "-framerate", FPS,
             "-i", here / sc["end"]["logo"], "-filter_complex", graph, "-map", "[v]", "-frames:v", n, "-c:v", "libx264",
             "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p", path])
        return path
    x, y, w, h = crop_of(s["crop"])
    sp = float(s.get("speed", 1.0))
    if F.get("full"):
        return full_shot(path, n, s, (x, y, w, h), sp)
    fx, fy, fwm, fhm = F["fit"]
    bx, by, bw, bh = F["blur"]
    k_fit = min(fwm / w, fhm / h)                                    # l'extrait entier, le plus grand possible dans la zone
    fw, fh = round(w * k_fit / 2) * 2, round(h * k_fit / 2) * 2
    ox, oy = fx + (fwm - fw) // 2, fy + (fhm - fh) // 2
    graph = (f"[0:v]setpts=(PTS-STARTPTS)/{sp},fps={FPS},split=2[a][b];"
             f"[a]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},gblur=sigma=28,"
             f"eq=brightness=-0.2:saturation=0.7[z0];"
             f"color=c=0x{C['night']}:s={bw}x{bh}:r={FPS},format=rgba,colorchannelmixer=aa=0.45[tint];"
             f"[z0][tint]overlay=shortest=1[z];"
             f"[b]crop={w}:{h}:{x}:{y},scale={fw}:{fh}:flags=lanczos[f];"
             f"[1:v][z]overlay={bx}:{by}[bz];[bz][f]overlay={ox}:{oy}:shortest=1,"
             f"drawbox=x={ox}:y={oy - 8}:w={fw}:h=8:color=0x{C['green']}:t=fill,"
             f"drawbox=x={ox}:y={oy + fh}:w={fw}:h=8:color=0x{C['sky']}:t=fill[v]")
    run([ffmpeg, "-y", "-loglevel", "error", "-ss", f"{s['src']:.3f}", "-t", f"{dur * sp + 0.5:.3f}", "-i", capture,
         "-loop", "1", "-framerate", FPS, "-i", bg, "-filter_complex", graph, "-map", "[v]", "-frames:v", n, "-c:v", "libx264",
         "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p", "-r", FPS, path])
    return path


def full_shot(path: Path, n: int, s: dict, c: tuple, sp: float) -> Path:
    """Plan plein cadre (paysage) : l'écran du jeu à sa résolution, zoomé au plus de `zmax` sur la zone `c` (une image
    nette plutôt qu'un petit bout agrandi), la zone entourée de vert si elle ne remplit pas l'image."""
    x, y, w, h = c
    sw, sh = 1920, 1080                                                    # la capture
    vw = min(sw, max(w * 1.25, h * 1.25 * W / H, sw / F["zmax"]))
    vw = round(vw / 2) * 2
    vh = round(vw * H / W / 2) * 2
    vx = int(min(max(x + w / 2 - vw / 2, 0), sw - vw))
    vy = int(min(max(y + h / 2 - vh / 2, 0), sh - vh))
    k = W / vw
    box = ""
    if w * h < 0.6 * vw * vh:                                              # la zone dont on parle, entourée de vert
        t = 6
        box = (f",drawbox=x={round((x - vx) * k) - t}:y={round((y - vy) * k) - t}:w={round(w * k) + 2 * t}:"
               f"h={round(h * k) + 2 * t}:color=0x{C['green']}:t={t}")
    graph = f"[0:v]setpts=(PTS-STARTPTS)/{sp},fps={FPS},crop={vw}:{vh}:{vx}:{vy},scale={W}:{H}:flags=lanczos{box}[v]"
    run([ffmpeg, "-y", "-loglevel", "error", "-ss", f"{s['src']:.3f}", "-t", f"{n / FPS * sp + 0.5:.3f}", "-i", capture,
         "-filter_complex", graph, "-map", "[v]", "-frames:v", n, "-c:v", "libx264", "-crf", "18", "-preset", "fast",
         "-pix_fmt", "yuv420p", "-r", FPS, path])
    return path


def ts(t: float) -> str:
    cs = round(t * 100)
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def title_text(t: str) -> str:
    """« 16 PÊCHEURS. *0 HUMAIN.* » : le passage entre * en vert ; entrée en grossissant."""
    parts = t.split("*")
    body = "".join(p if i % 2 == 0 else f"{{\\c{ass_color(C['green'])}}}{p}{{\\c{ass_color(C['white'])}}}" for i, p in enumerate(parts))
    return "{\\fad(60,0)\\fscx118\\fscy118\\t(0,160,\\fscx100\\fscy100)}" + body


def captions(words: list, t0: float, t_end: float) -> list[str]:
    """Sous-titres mot à mot : des groupes de 4 mots au plus (ou `cap` caractères), le mot dit en vert et un peu plus gros."""
    groups, cur = [], []
    for wd in words:
        cur.append(wd)
        if len(cur) == 4 or len(" ".join(x[2] for x in cur)) > F["cap"][2]:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    lines = []
    for g, grp in enumerate(groups):
        g_end = groups[g + 1][0][0] + t0 if g + 1 < len(groups) else t_end
        for i, (start, _, _) in enumerate(grp):
            end = grp[i + 1][0] + t0 if i + 1 < len(grp) else g_end
            txt = " ".join((f"{{\\c{ass_color(C['green'])}\\fscx108\\fscy108}}{x[2]}{{\\c{ass_color(C['white'])}\\fscx100\\fscy100}}"
                            if j == i else x[2]) for j, x in enumerate(grp))
            lines.append(f"Dialogue: 1,{ts(start + t0)},{ts(end)},Cap,,0,0,0,,{txt}")
    return lines


async def main() -> None:
    voices = [await speak(i, ln["say"]) for i, ln in enumerate(sc["lines"])]
    t, plan, events, starts = 0.0, [], [], []          # plan : (plan, durée) ; events : lignes ASS
    for ln, (wav, vdur, words) in zip(sc["lines"], voices):
        assert words, f"aucun mot minuté : {ln['say']}"
        dur = vdur + (sc["end"]["hold"] if ln.get("end") else GAP)
        starts.append(t)
        if ln.get("end"):
            plan.append((None, dur))
        else:
            shots = ln["shots"]
            plan += [(s, dur / len(shots)) for s in shots]
            events.append(f"Dialogue: 2,{ts(t)},{ts(t + dur)},Title,,0,0,0,,{title_text(ln['title'])}")
            events += captions(words, t, t + dur)
        t += dur
    total = t
    assert total <= 60.0, f"la vidéo dure {total:.1f} s : plus d'une minute"
    print(f"{FMT} : durée {total:.1f} s, {len(plan)} plans")

    paths = [render_shot(k, s, d) for k, (s, d) in enumerate(plan)]
    (work / "list.txt").write_text("".join(f"file '{p.name}'\n" for p in paths), encoding="utf8")
    run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "full.mp4"], cwd=work)

    # la carte de fin, l'en-tête et la barre de progression
    e0, cx = starts[-1], W // 2
    end, ey = sc["end"]["lines"], F["end"]["y"]
    pop = "\\fscx125\\fscy125\\t({a},{b},\\fscx100\\fscy100)"
    events += [
        f"Dialogue: 3,{ts(e0)},{ts(total)},End,,0,0,0,,{{\\an5\\pos({cx},{ey[0]})\\fad(80,0){pop.format(a=0, b=180)}}}{end[0]}",
        f"Dialogue: 3,{ts(e0 + 0.25)},{ts(total)},End,,0,0,0,,{{\\an5\\pos({cx},{ey[1]})\\fs{F['end']['big']}"
        f"\\c{ass_color(C['green'])}\\fad(60,0){pop.format(a=0, b=200)}}}{end[1]}",
        f"Dialogue: 3,{ts(e0 + 0.6)},{ts(total)},Small,,0,0,0,,{{\\an5\\pos({cx},{ey[2]})\\fad(150,0)}}{end[2]}",
    ]                                                                   # (puis le logo de l'école, posé par render_shot)
    ty = F["tag_y"]
    if not F.get("full"):                         # (plein cadre : l'en-tête du jeu est à l'image, on ne le double pas)
        for i, col in enumerate((C["green"], C["teal"], C["sky"])):      # trois bandes de couleur, en haut à gauche
            events.append(f"Dialogue: 0,{ts(0)},{ts(e0)},Bar,,0,0,0,,{{\\an7\\pos({60 + i * 34},{ty - 2})\\c{ass_color(col)}\\p1}}"
                          f"m 0 60 l 22 0 44 0 22 60{{\\p0}}")
        events.append(f"Dialogue: 0,{ts(0)},{ts(e0)},Tag,,0,0,0,,{{\\an7\\pos(180,{ty})}}FILETS")
        events.append(f"Dialogue: 0,{ts(0)},{ts(e0)},Tag,,0,0,0,,{{\\an9\\pos({W - 60},{ty})\\c{ass_color(C['sky'])}}}#IABD")
    py, ph = F["progress"]
    events.append(f"Dialogue: 4,{ts(0)},{ts(total)},Bar,,0,0,0,,{{\\an7\\pos(0,{py})\\c{ass_color(C['green'])}"
                  f"\\clip(0,{py - 10},0,{H})\\t(0,{round(total * 1000)},\\clip(0,{py - 10},{W},{H}))\\p1}}m 0 0 l {W} 0 {W} {ph} 0 {ph}{{\\p0}}")
    white, dark = ass_color(C["white"]), "&H00301A0A&"
    (ts_, tm), (cs_, cm, _) = F["title"], F["cap"]
    if F.get("full"):            # plein cadre : titre et sous-titres sur des bandeaux (BorderStyle 3 : boîte de la couleur OutlineColour)
        title_style = f"&H30{ass_color(C['night'])[4:]},&H00000000,0,0,0,0,100,100,0,0,3,18,0,8,60,60,{tm},1"
        cap_style = f"&H50000000&,&H00000000,0,0,0,0,100,100,0,0,3,12,0,2,70,70,{cm},1"
    else:
        title_style = f"{dark},&H78000000,0,0,0,0,100,100,0,0,1,0,7,8,60,60,{tm},1"
        cap_style = f"{dark},&H96000000,0,0,0,0,100,100,0,0,1,6,3,2,70,70,{cm},1"
    styles = [
        f"Style: Title,Segoe UI Black,{ts_},{white},{white},{title_style}",
        f"Style: Cap,Segoe UI Black,{cs_},{white},{white},{cap_style}",
        f"Style: End,Segoe UI Black,110,{white},{white},{dark},&H78000000,0,0,0,0,100,100,0,0,1,0,8,5,40,40,0,1",
        f"Style: Small,Segoe UI Semibold,56,{white},{white},{dark},&H78000000,0,0,0,0,100,100,0,0,1,0,4,5,60,60,0,1",
        f"Style: Tag,Segoe UI Black,48,{white},{white},{dark},&H00000000,0,0,0,0,100,100,2,0,1,0,0,7,0,0,0,1",
        f"Style: Bar,Segoe UI,20,{white},{white},{white},&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
    ]
    ass = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
           "[V4+ Styles]", "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
           "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, "
           "Encoding", *styles, "", "[Events]",
           "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text", *events]
    (work / "short.ass").write_text("\n".join(ass) + "\n", encoding="utf8")

    # la voix, et un souffle discret à chaque coupe
    run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anoisesrc=d=0.32:c=pink:a=0.6:r=48000", "-af",
         "highpass=f=700,lowpass=f=5000,afade=t=in:d=0.12,afade=t=out:st=0.12:d=0.2,volume=0.35", "-ac", "1", "whoosh.wav"], cwd=work)
    cuts, acc = [], 0.0
    for _, d in plan[:-1]:
        acc += d
        cuts.append(acc)
    inputs, graph, labels = [], [], []
    for i, ((wav, _, _), st) in enumerate(zip(voices, starts)):
        inputs += ["-i", wav.name]
        graph.append(f"[{i}:a]adelay={round(st * 1000)}:all=1[v{i}]")
        labels.append(f"[v{i}]")
    for j, ct in enumerate(cuts):
        k = len(voices) + j
        inputs += ["-i", "whoosh.wav"]
        graph.append(f"[{k}:a]adelay={max(round(ct * 1000) - 120, 0)}:all=1[w{j}]")
        labels.append(f"[w{j}]")
    graph.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=longest,apad,atrim=0:{total:.3f}[a]")
    run([ffmpeg, "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(graph), "-map", "[a]", "-ar", "48000", "mix.wav"],
        cwd=work)

    run([ffmpeg, "-y", "-loglevel", "error", "-i", "full.mp4", "-i", "mix.wav",
         "-vf", "ass=short.ass:fontsdir=/Windows/Fonts",          # (le disque courant : « C\: » ne s'échappe pas bien)
         "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",                  # le niveau des réseaux sociaux (-14 LUFS)
         "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
         "-movflags", "+faststart", "-shortest", out], cwd=work)
    print("écrit :", out)


if __name__ == "__main__":
    assert regroup([(0, 1, "des"), (1, 2, "zia"), (2, 3, "I"), (3, 4, "A"), (4, 5, "B"), (5, 6, "D"), (6, 7, "rag")]) == \
        [(0, 1, "des"), (1, 2, "IA"), (2, 6, "IABD"), (6, 7, "RAG")]
    asyncio.run(main())
