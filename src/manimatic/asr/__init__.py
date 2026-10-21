"""Speech recognition with word-level timestamps.

Backends:
  * ``faster-whisper`` (default; CPU or CUDA, all platforms)
  * ``whisperx``       (optional; forced alignment for sharper word boundaries, best on CUDA)
  * ``mock``           (reads ``<audio>.words.json`` next to the audio; for tests)

Each audio file is transcribed once and cached in ``.manimatic/asr/``.
"""
from __future__ import annotations

import glob
import os
import re
import sys
from collections import Counter
from pathlib import Path

from manimatic.util import ManimaticError, file_hash, read_json, say, warn, write_json

# Prompting with disfluencies nudges Whisper to transcribe ums/uhs instead of dropping them.
FILLER_PROMPT = "Umm, let me think like, hmm... Okay, here's what I'm, like, thinking. Uh, so, um, yeah."


def _prepare_cuda_libs() -> None:
    """Make pip-installed cuBLAS/cuDNN visible to CTranslate2 (Linux/Windows)."""
    try:
        import nvidia  # type: ignore  # namespace package from nvidia-* wheels
    except ImportError:
        return
    roots = list(getattr(nvidia, "__path__", []))
    if os.name == "nt":
        for r in roots:
            for d in glob.glob(os.path.join(r, "*", "bin")):
                try:
                    os.add_dll_directory(d)  # type: ignore[attr-defined]
                except OSError:
                    pass
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
    elif sys.platform.startswith("linux"):
        import ctypes

        for pat in ("cublas/lib/libcublasLt.so*", "cublas/lib/libcublas.so*", "cudnn/lib/libcudnn*.so*"):
            for r in roots:
                for lib in sorted(glob.glob(os.path.join(r, pat))):
                    try:
                        ctypes.CDLL(lib, mode=ctypes.RTLD_GLOBAL)
                    except OSError:
                        pass


def _cuda_available() -> bool:
    try:
        _prepare_cuda_libs()
        import ctranslate2  # type: ignore

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001
        return False


def resolve_settings(proj, backend: str | None = None, model: str | None = None, device: str | None = None) -> dict:
    backend = (backend or proj.get("audio", "asr_backend") or "auto").lower()
    device = (device or proj.get("audio", "device") or "auto").lower()
    model = model or proj.get("audio", "asr_model") or "auto"
    lang = proj.get("audio", "language") or "en"
    if device == "auto":
        device = "cuda" if _cuda_available() else "cpu"
    if backend == "auto":
        try:
            import whisperx  # type: ignore  # noqa: F401

            backend = "whisperx" if device == "cuda" else "faster-whisper"
        except Exception:  # noqa: BLE001
            backend = "faster-whisper"
    if model == "auto":
        model = "large-v3" if device == "cuda" else ("small.en" if lang == "en" else "small")
    return {"backend": backend, "model": model, "device": device, "language": lang}


def _vocab_prompt(proj) -> str:
    """Filler prompt + distinctive words from the script (helps names and jargon)."""
    script = read_json(proj.work / "script.json") or {}
    counts: Counter = Counter()
    for ln in script.get("lines", []):
        for m in re.finditer(r"\b[A-Z][a-z]{3,}\b", ln["text"]):
            counts[m.group(0)] += 1
    common = {"This", "That", "There", "These", "Those", "What", "When", "Where", "Which", "With", "Here", "Every",
              "Then", "Now", "Look", "Notice", "Let's", "Okay", "Well", "And", "But", "Because", "Since", "Some"}
    words = [w for w, _ in counts.most_common(40) if w not in common][:25]
    return FILLER_PROMPT + (" " + ", ".join(words) + "." if words else "")


def _fill_missing_times(words: list[dict]) -> list[dict]:
    """WhisperX leaves some tokens (numbers) without times: interpolate."""
    n = len(words)
    for i, w in enumerate(words):
        if w.get("s") is None or w.get("e") is None:
            prev_e = next((words[j]["e"] for j in range(i - 1, -1, -1) if words[j].get("e") is not None), 0.0)
            nxt_s = next((words[j]["s"] for j in range(i + 1, n) if words[j].get("s") is not None), prev_e + 0.3)
            w["s"] = w.get("s") if w.get("s") is not None else prev_e
            w["e"] = w.get("e") if w.get("e") is not None else max(w["s"] + 0.05, min(nxt_s, w["s"] + 0.4))
    return words


def _faster_whisper(path: Path, st: dict, prompt: str) -> list[dict]:
    from faster_whisper import WhisperModel  # type: ignore

    compute = "float16" if st["device"] == "cuda" else "int8"
    try:
        model = WhisperModel(st["model"], device=st["device"], compute_type=compute)
    except Exception as e:  # noqa: BLE001
        if st["device"] == "cuda":
            warn(f"Couldn't use the GPU ({e}); falling back to CPU.")
            st["device"] = "cpu"
            model = WhisperModel(st["model"], device="cpu", compute_type="int8")
        else:
            raise
    segments, info = model.transcribe(
        str(path), language=st["language"], word_timestamps=True, vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300}, initial_prompt=prompt,
        condition_on_previous_text=False, beam_size=5,
    )
    words: list[dict] = []
    last_report = 0.0
    total = getattr(info, "duration", 0) or 0
    for seg in segments:
        for w in seg.words or []:
            words.append({"w": w.word.strip(), "s": float(w.start), "e": float(w.end), "p": float(w.probability)})
        if seg.end - last_report > 120:
            last_report = seg.end
            pct = f" ({100 * seg.end / total:.0f}%)" if total else ""
            say(f"    … {seg.end / 60:.1f} min transcribed{pct}")
    return words


def _whisperx(path: Path, st: dict, prompt: str) -> list[dict]:
    import whisperx  # type: ignore

    compute = "float16" if st["device"] == "cuda" else "int8"
    model = whisperx.load_model(st["model"], st["device"], compute_type=compute, language=st["language"],
                                asr_options={"initial_prompt": prompt})
    audio = whisperx.load_audio(str(path))
    result = model.transcribe(audio, batch_size=16 if st["device"] == "cuda" else 4, language=st["language"])
    align_model, meta = whisperx.load_align_model(language_code=st["language"], device=st["device"])
    result = whisperx.align(result["segments"], align_model, meta, audio, st["device"], return_char_alignments=False)
    words = []
    for seg in result["segments"]:
        for w in seg.get("words", []):
            words.append({"w": str(w.get("word", "")).strip(), "s": w.get("start"), "e": w.get("end"),
                          "p": float(w.get("score", 0.9) or 0.9)})
    return _fill_missing_times(words)


def _mock(path: Path, st: dict, prompt: str) -> list[dict]:
    side = path.with_name(path.name + ".words.json")
    if not side.exists():
        raise ManimaticError(f"mock backend needs {side.name} next to {path.name}")
    data = read_json(side)
    return [{"w": d["w"], "s": float(d["s"]), "e": float(d["e"]), "p": float(d.get("p", 0.95))} for d in data]


BACKENDS = {"faster-whisper": _faster_whisper, "whisperx": _whisperx, "mock": _mock}


def transcribe_all(proj, backend: str | None = None, model: str | None = None, device: str | None = None,
                   force: bool = False) -> dict:
    from manimatic.util import ffprobe_duration

    files = proj.audio_files()
    if not files:
        raise ManimaticError(f"No audio found in {proj.audio_dir}. Add your recording(s), or use draft mode.")
    st = resolve_settings(proj, backend, model, device)
    if st["backend"] not in BACKENDS:
        raise ManimaticError(f"Unknown ASR backend '{st['backend']}'. Use faster-whisper, whisperx or mock.")
    if st["language"] != "en":
        warn("Manimatic v1 is tuned for English; other languages may align poorly.")
    prompt = _vocab_prompt(proj)
    out_dir = proj.work / "asr"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    say(f"Transcribing {len(files)} file(s) with {st['backend']} ({st['model']}, {st['device']})")
    for f in files:
        h = file_hash(f)[:12]
        cache = out_dir / f"{f.stem}-{h}.json"
        cached = read_json(cache)
        if cached and not force and cached.get("backend") == st["backend"] and \
                (cached.get("model") == st["model"] or st["backend"] == "mock"):
            say(f"  {f.name}: cached ({len(cached['words'])} words)")
        else:
            say(f"  {f.name}: transcribing…")
            try:
                words = BACKENDS[st["backend"]](f, dict(st), prompt)
            except ImportError as e:
                raise ManimaticError(f"{st['backend']} isn't installed ({e}). Run `mm.py doctor --install`.") from e
            words = [w for w in words if w["w"]]
            cached = {"file": f.name, "hash": h, "backend": st["backend"], "model": st["model"],
                      "device": st["device"], "duration": ffprobe_duration(f), "words": words}
            write_json(cache, cached)
            say(f"  {f.name}: {len(words)} words")
        manifest.append({"file": f.name, "path": str(f.relative_to(proj.root)), "cache": cache.name,
                         "duration": cached["duration"], "hash": h})
    write_json(out_dir / "manifest.json", {"settings": st, "files": manifest})
    proj.set_state(transcribed=True, draft=False)
    return {"settings": st, "files": manifest}
