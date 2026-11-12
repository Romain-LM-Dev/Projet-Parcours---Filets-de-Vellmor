"""Vidéo courte verticale (réseaux sociaux) : docs/demo/FILETS-short.mp4, d'après short.json et la capture SANS sous-titre de la
démo (`--no-captions`, même minutage que FILETS-demo.mp4). Voix edge-tts (seul le texte part chez Microsoft), sous-titres mot à mot
et titres en ASS (libass), plans recadrés et zoomés par ffmpeg.
    python short.py <ffmpeg> <capture sans sous-titre .avi> [sortie.mp4]      (python avec le paquet edge-tts)"""
import asyncio
import json
import subprocess
import sys
import wave
from pathlib import Path

import edge_tts

here = Path(__file__).parent
sc = json.loads((here / "short.json").read_text(encoding="utf8"))
ffmpeg, capture = sys.argv[1], str(Path(sys.argv[2]).resolve())
out = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else here / "FILETS-short.mp4"
work = here / "voice" / "short"          # (docs/demo/voice/ n'est pas versionné)
work.mkdir(parents=True, exist_ok=True)
W, H = sc["size"]
FPS = sc["fps"]
C = sc["colors"]
GAP = 0.15                               # souffle entre deux phrases
ZONE = (470, 900)                        # zone des images de la partie : haut, hauteur


def run(cmd: list, cwd=None) -> None:
    subprocess.run([str(c) for c in cmd], check=True, cwd=cwd)


def ass_color(hex6: str) -> str:
    return f"&H00{hex6[4:6]}{hex6[2:4]}{hex6[0:2]}&"


async def speak(i: int, text: str):
    """(wav, durée, mots [(début, fin, texte)]) d'une phrase ; le service répond parfois sans audio : on réessaie."""
    mp3, wav = work / f"{i:02d}.mp3", work / f"{i:02d}.wav"
    for _ in range(4):
        words, chunks = [], []
        try:
            com = edge_tts.Communicate(text, sc["voice"]["name"], rate=sc["voice"]["rate"], boundary="WordBoundary")
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
        return wav, w.getnframes() / w.getframerate(), words


def crop_of(c):
    return sc["crops"][c] if isinstance(c, str) else c


def background(top: str) -> Path:
    """Un fond fixe en dégradé vertical : la couleur `top` en haut, un bleu nuit très sombre en bas (une image, faite une fois)."""
    path = work / f"bg_{top}.png"
    if not path.exists():
        a, b = C[top], "0A1230"
        ch = lambda h, i: int(h[2 * i:2 * i + 2], 16)                     # noqa: E731
        expr = {c: f"{ch(a, i)}+({ch(b, i) - ch(a, i)})*Y/H" for i, c in enumerate("rgb")}
        run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=s={W}x{H}", "-vf",
             f"format=gbrp,geq=r='{expr['r']}':g='{expr['g']}':b='{expr['b']}'", "-frames:v", "1", "-update", "1", path])
    return path


def render_shot(k: int, s: dict | None, dur: float) -> Path:
    """Un plan de `dur` s, 1080x1920 : fond dégradé, l'image de la partie recadrée (entrée en léger zoom, puis poussée lente) ;
    sans `s` : le fond seul (carte de fin)."""
    path = work / f"shot{k:02d}.mp4"
    n = round(dur * FPS)
    bg = background("blue" if s is None else "night")
    if s is None:
        run([ffmpeg, "-y", "-loglevel", "error", "-loop", "1", "-framerate", FPS, "-i", bg, "-frames:v", n, "-c:v", "libx264",
             "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p", path])
        return path
    x, y, w, h = crop_of(s["crop"])
    sp, z1 = float(s.get("speed", 1.0)), float(s.get("zoom", 1.08))
    fw, fh = W, round(h * W / w / 2) * 2
    if fh > ZONE[1]:
        fh, fw = ZONE[1], round(w * ZONE[1] / h / 2) * 2
    ox, oy = (W - fw) // 2, ZONE[0] + (ZONE[1] - fh) // 2
    z = f"if(lt(on,5),1.12-0.024*on,1+{z1 - 1:.4f}*(on-5)/{max(n - 5, 1)})"
    zw, zh = W, ZONE[1]
    # derrière l'extrait, toute la zone : la même image de jeu, floutée et assombrie (pas de vide autour d'une bande de texte)
    graph = (f"[0:v]setpts=(PTS-STARTPTS)/{sp},fps={FPS},split=2[a][b];"
             f"[a]scale=-2:{zh},crop={zw}:{zh},gblur=sigma=28,eq=brightness=-0.18:saturation=0.75[z];"
             f"[b]crop={w}:{h}:{x}:{y},scale={fw}:{fh}:flags=lanczos,"
             f"zoompan=z='{z}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={fw}x{fh}:fps={FPS}[f];"
             f"[1:v][z]overlay=0:{ZONE[0]}[bz];[bz][f]overlay={ox}:{oy}:shortest=1,"
             f"drawbox=x={ox}:y={oy - 8}:w={fw}:h=8:color=0x{C['green']}:t=fill,"
             f"drawbox=x={ox}:y={oy + fh}:w={fw}:h=8:color=0x{C['sky']}:t=fill[v]")
    run([ffmpeg, "-y", "-loglevel", "error", "-ss", f"{s['src']:.3f}", "-t", f"{dur * sp + 0.5:.3f}", "-i", capture,
         "-loop", "1", "-framerate", FPS, "-i", bg, "-filter_complex", graph, "-map", "[v]", "-frames:v", n, "-c:v", "libx264", "-crf", "18",
         "-preset", "fast", "-pix_fmt", "yuv420p", "-r", FPS, path])
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
    """Sous-titres mot à mot : des groupes de 4 mots au plus, le mot dit en vert et un peu plus gros."""
    groups, cur = [], []
    for wd in words:
        cur.append(wd)
        if len(cur) == 4 or len(" ".join(x[2] for x in cur)) > 22:
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
    t, plan, events = 0.0, [], []                     # plan : (plan, durée) ; events : lignes ASS
    starts = []
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
    print(f"durée {total:.1f} s, {len(plan)} plans")

    paths = [render_shot(k, s, d) for k, (s, d) in enumerate(plan)]
    (work / "list.txt").write_text("".join(f"file '{p.name}'\n" for p in paths), encoding="utf8")
    run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "full.mp4"], cwd=work)

    # la carte de fin, l'en-tête et la barre de progression
    e0, ed = starts[-1], total - starts[-1]
    end = sc["end"]["lines"]
    pop = "\\fscx125\\fscy125\\t({a},{b},\\fscx100\\fscy100)"
    events += [
        f"Dialogue: 3,{ts(e0)},{ts(total)},End,,0,0,0,,{{\\an5\\pos(540,700)\\fad(80,0){pop.format(a=0, b=180)}}}{end[0]}",
        f"Dialogue: 3,{ts(e0 + 0.25)},{ts(total)},End,,0,0,0,,{{\\an5\\pos(540,900)\\fs250\\c{ass_color(C['green'])}\\fad(60,0)"
        f"{pop.format(a=0, b=200)}}}{end[1]}",
        f"Dialogue: 3,{ts(e0 + 0.7)},{ts(total)},Small,,0,0,0,,{{\\an5\\pos(540,1110)\\fad(150,0)}}{end[2]}",
        f"Dialogue: 3,{ts(e0 + 1.1)},{ts(total)},Small,,0,0,0,,{{\\an5\\pos(540,1290)\\fs76\\c{ass_color(C['sky'])}\\fad(150,0)}}{end[3]}",
    ]
    for i, col in enumerate((C["green"], C["teal"], C["sky"])):          # trois bandes de couleur, en haut à gauche et à la fin
        events.append(f"Dialogue: 0,{ts(0)},{ts(e0)},Bar,,0,0,0,,{{\\an7\\pos({60 + i * 34},64)\\c{ass_color(col)}\\p1}}"
                      f"m 0 60 l 22 0 44 0 22 60{{\\p0}}")
        events.append(f"Dialogue: 0,{ts(e0)},{ts(total)},Bar,,0,0,0,,{{\\an7\\pos({420 + i * 90},1450)\\c{ass_color(col)}\\fad(200,0)\\p1}}"
                      f"m 0 120 l 45 0 90 0 45 120{{\\p0}}")
    events.append(f"Dialogue: 0,{ts(0)},{ts(e0)},Tag,,0,0,0,,{{\\an7\\pos(180,66)}}FILETS")
    events.append(f"Dialogue: 0,{ts(0)},{ts(e0)},Tag,,0,0,0,,{{\\an9\\pos(1020,66)\\c{ass_color(C['sky'])}}}#IABD")
    events.append(f"Dialogue: 4,{ts(0)},{ts(total)},Bar,,0,0,0,,{{\\an7\\pos(0,1900)\\c{ass_color(C['green'])}"
                  f"\\clip(0,1890,0,1920)\\t(0,{round(total * 1000)},\\clip(0,1890,{W},1920))\\p1}}m 0 0 l {W} 0 {W} 20 0 20{{\\p0}}")
    white, dark = ass_color(C["white"]), "&H00301A0A&"
    styles = [
        f"Style: Title,Segoe UI Black,96,{white},{white},{dark},&H78000000,0,0,0,0,100,100,0,0,1,0,7,8,60,60,190,1",
        f"Style: Cap,Segoe UI Black,74,{white},{white},{dark},&H96000000,0,0,0,0,100,100,0,0,1,6,3,2,70,70,330,1",
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

    run([ffmpeg, "-y", "-loglevel", "error", "-i", "full.mp4", "-i", "mix.wav", "-vf", "ass=short.ass:fontsdir=/Windows/Fonts",   # (le disque courant : « C\: » ne s'échappe pas bien)
         "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",          # le niveau des réseaux sociaux (-14 LUFS)
         "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
         "-movflags", "+faststart", "-shortest", out], cwd=work)
    print("écrit :", out)


asyncio.run(main())
