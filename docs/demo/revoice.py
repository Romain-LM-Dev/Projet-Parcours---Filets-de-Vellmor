"""Refaire la voix de quelques temps de la démo SANS recapturer la vidéo : chaque ancienne voix (docs/demo/voice/NN.wav, celle de la
vidéo) est retrouvée dans la bande son par corrélation, la nouvelle (narrate.py --only=… --out=<dossier>) est mise à la même durée
(atempo) et prend sa place ; l'image est copiée telle quelle. Les nouvelles voix remplacent ensuite les anciennes dans voice/.
    python revoice.py <ffmpeg> <dossier des nouvelles voix> 1 18 21      (python avec numpy)"""
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

here = Path(__file__).parent
ffmpeg, new_dir, beats = sys.argv[1], Path(sys.argv[2]), [int(b) for b in sys.argv[3:]]
video = here / "FILETS-demo.mp4"
RATE = 48000


def pcm(src, *af) -> np.ndarray:
    """Un son en mono 48 kHz, flottant."""
    out = subprocess.run([ffmpeg, "-loglevel", "error", "-i", str(src), *(["-af", ",".join(af)] if af else []), "-ac", "1",
                          "-ar", str(RATE), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.float32).copy()


def find(track: np.ndarray, clip: np.ndarray) -> int:
    """Où `clip` commence dans `track` (corrélation par FFT, sur le son ramené à 8 kHz), refusé si la ressemblance est faible."""
    k = RATE // 8000
    t, c = track[::k], clip[::k]
    n = 1 << int(np.ceil(np.log2(len(t) + len(c))))
    corr = np.fft.irfft(np.fft.rfft(t, n) * np.conj(np.fft.rfft(c, n)), n)[:len(t) - len(c)]
    at = int(np.argmax(corr)) * k
    seg = track[at:at + len(clip)]
    score = float(np.dot(seg, clip) / (np.linalg.norm(seg) * np.linalg.norm(clip) + 1e-9))
    assert score > 0.8, f"ancienne voix introuvable dans la vidéo (ressemblance {score:.2f})"
    return at


track = pcm(video)
for b in beats:
    old, new = pcm(here / "voice" / f"{b:02d}.wav"), here / "voice" / f"{b:02d}.wav"
    at = find(track, old)
    fresh = pcm(new_dir / f"{b:02d}.wav")
    fitted = pcm(new_dir / f"{b:02d}.wav", f"atempo={len(fresh) / len(old):.6f}")[:len(old)]   # même durée : l'image ne bouge pas
    fitted = np.pad(fitted, (0, len(old) - len(fitted)))
    print(f"temps {b:02d} : à {at / RATE:6.2f} s, {len(old) / RATE:.2f} s (nouvelle voix {len(fresh) / RATE:.2f} s, "
          f"tempo x{len(fresh) / len(old):.3f})")
    track[at:at + len(old)] = fitted
    np.clip(track, -1.0, 1.0, out=track)
raw = here / "voice" / "revoice.f32"
raw.write_bytes(track.astype(np.float32).tobytes())
tmp = here / "FILETS-demo.revoice.mp4"
subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(video), "-f", "f32le", "-ar", str(RATE), "-ac", "1", "-i", str(raw),
                "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-movflags", "+faststart",
                str(tmp)], check=True)
raw.unlink()
tmp.replace(video)
for b in beats:                     # la voix au tempo de la vidéo devient la référence (une prochaine capture garde le même minutage)
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(new_dir / f"{b:02d}.wav"), "-af",
                    f"atempo={len(pcm(new_dir / f'{b:02d}.wav')) / len(pcm(here / 'voice' / f'{b:02d}.wav')):.6f}",
                    "-ar", "44100", "-ac", "1", str(here / "voice" / f"{b:02d}.new.wav")], check=True)
    shutil.move(here / "voice" / f"{b:02d}.new.wav", here / "voice" / f"{b:02d}.wav")
print("écrit :", video)
