"""Voix de la démo : un WAV par temps du scénario (docs/demo/voice/NN.wav) avec edge-tts (voix neuronale en ligne :
seul le texte de la narration part chez Microsoft). Donne la durée de chaque fichier.
    python narrate.py <chemin de ffmpeg>      (python avec le paquet edge-tts ; ffmpeg convertit le MP3 en WAV 44,1 kHz mono)"""
import asyncio, json, re, subprocess, sys, wave
from pathlib import Path

import edge_tts

here = Path(__file__).parent
sc = json.loads((here / "scenario.json").read_text(encoding="utf8"))
ffmpeg = sys.argv[1]
out = here / "voice"
out.mkdir(exist_ok=True)


def spoken(text: str) -> str:
    """Le texte tel que la voix doit le dire (`pron` : liaisons, sigles) ; le sous-titre garde le texte du scénario."""
    for pattern, say in sc.get("pron", []):
        text = re.sub(pattern, say, text)
    return text


async def main() -> None:
    v = sc["voice"]
    names = {x["ShortName"] for x in await edge_tts.list_voices()}
    name = v["name"] if v["name"] in names else v["fallback"]
    print("voix :", name)
    total = 0.0
    for i, b in enumerate(sc["beats"]):
        mp3, wav = out / f"{i:02d}.mp3", out / f"{i:02d}.wav"
        for essai in range(4):                       # le service répond parfois sans audio : on réessaie
            try:
                await edge_tts.Communicate(spoken(b["say"]), name, rate=v["rate"]).save(str(mp3))
                break
            except edge_tts.exceptions.NoAudioReceived:
                await asyncio.sleep(2)
        else:
            raise SystemExit(f"temps {i} : pas d'audio")
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(mp3), "-ar", "44100", "-ac", "1", str(wav)], check=True)
        mp3.unlink()
        with wave.open(str(wav)) as w:
            d = w.getnframes() / w.getframerate()
        total += d
        print(f"{i:02d}.wav  {d:.1f} s  (44100 Hz mono)")
    print(f"total {total:.1f} s")


asyncio.run(main())
