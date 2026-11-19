"""Замер распознавания речи: скорость и точность Whisper-моделей на наборе голосовых.

    python scripts/stt_bench.py <папка> [--models base,small] [--threads 2] [--beam 1] [--model-dir DIR]

В папке пары NAME.ogg + NAME.txt (эталонный текст). Для каждой модели печатает время загрузки,
время распознавания каждого файла, RTF (время / длительность записи; меньше 1 значит быстрее реального времени)
и WER (доля ошибочных слов). Запускать на целевом сервере, в контейнере с теми же лимитами, что у бота.
"""

import argparse
import asyncio
import os
import re
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import av  # noqa: E402

from src.adapters.stt.whisper import WhisperTranscriber  # noqa: E402


def words(text: str) -> list[str]:
    return re.findall(r"[\w']+", text.lower().replace("ё", "е"))


def wer(ref: str, hyp: str) -> float:
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hw in enumerate(h, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (rw != hw))
    return d[len(h)] / max(1, len(r))


def duration(path: Path) -> float:
    with av.open(str(path)) as c:
        return float(c.duration / av.time_base)


async def bench(model: str, files: list[Path], threads: int, beam: int, model_dir: str) -> None:
    t = WhisperTranscriber(model, threads, model_dir, beam_size=beam)
    load0 = os.getloadavg()[0]
    t0 = time.time()
    await t.transcribe(files[0].read_bytes(), "audio/ogg")  # прогрев: загрузка модели + первый файл
    print(f"\n== {model} | потоков {threads} | beam {beam} | загрузка+прогрев {time.time() - t0:.1f}с | load avg {load0:.1f}")
    print(f"{'файл':<10}{'длит.':>7}{'время':>8}{'RTF':>7}{'WER':>7}  текст")
    tot_t = tot_d = 0.0
    for f in files:
        audio, ref = f.read_bytes(), f.with_suffix(".txt").read_text(encoding="utf-8")
        d = duration(f)
        t0 = time.time()
        hyp = await t.transcribe(audio, "audio/ogg")
        dt = time.time() - t0
        tot_t, tot_d = tot_t + dt, tot_d + d
        print(f"{f.stem:<10}{d:>6.1f}с{dt:>7.1f}с{dt / d:>7.2f}{wer(ref, hyp):>7.0%}  {hyp[:70]}")
    print(f"итого: RTF {tot_t / tot_d:.2f} | пик памяти процесса {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024 if sys.platform == 'darwin' else 1024):.0f} МБ")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--models", default="base,small")
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--beam", type=int, default=1)
    ap.add_argument("--model-dir", default="data/whisper")
    a = ap.parse_args()
    files = sorted(Path(a.dir).glob("*.ogg"))
    if not files:
        raise SystemExit(f"нет *.ogg в {a.dir}")
    for m in a.models.split(","):
        asyncio.run(bench(m.strip(), files, a.threads, a.beam, a.model_dir))


if __name__ == "__main__":
    main()
