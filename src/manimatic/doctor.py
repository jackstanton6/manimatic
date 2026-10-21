"""Environment checks and managed-environment installation.

Standard library only: this runs before the managed venv exists.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

HOME = os.environ.get("MANIMATIC_HOME") or os.path.join(os.path.expanduser("~"), ".manimatic")
VENV = os.path.join(HOME, "venv")

OS = "windows" if os.name == "nt" else ("mac" if sys.platform == "darwin" else "linux")

FIX = {
    "ffmpeg": {
        "windows": "winget install Gyan.FFmpeg   (then open a new terminal)",
        "mac": "brew install ffmpeg",
        "linux": "sudo apt install ffmpeg   (or your distro's package manager)",
    },
    "python313": {
        "windows": "winget install astral-sh.uv   (then: py -3 mm.py doctor --install; uv fetches Python 3.13 itself)",
        "mac": "brew install uv   (then: python3 mm.py doctor --install; uv fetches Python 3.13 itself)",
        "linux": "curl -LsSf https://astral.sh/uv/install.sh | sh   (then: python3 mm.py doctor --install)",
    },
    "gpu": {
        "windows": "Update your graphics driver (NVIDIA, AMD or Intel). ManimGX draws with DirectX 12 or Vulkan.",
        "mac": "Any Apple Silicon or recent Intel Mac has a GPU ManimGX can use (Metal).",
        "linux": "Install your GPU's Vulkan driver (NVIDIA proprietary driver; Mesa for AMD/Intel: sudo apt install mesa-vulkan-drivers)",
    },
    "latex": {
        "windows": "winget install MiKTeX.MiKTeX   (small; it fetches packages on the fly the first time Manim needs them)",
        "mac": ("brew install --cask basictex   (~100 MB), then in a NEW terminal:\n"
                "            sudo tlmgr update --self && sudo tlmgr install " + "{texpkgs}" + "   (~300 MB)\n"
                "            Full alternative: brew install --cask mactex-no-gui (~5 GB download, ~6 GB on disk)"),
        "linux": "sudo apt install texlive texlive-latex-extra cm-super dvisvgm   (Fedora: sudo dnf install texlive-scheme-medium)",
    },
    "manim_sys": {
        "windows": "No system libraries needed on Windows.",
        "mac": "brew install cairo pango pkg-config",
        "linux": "sudo apt install build-essential python3-dev libcairo2-dev libpango1.0-dev pkg-config",
    },
    "tts": {
        "windows": "Built in (Windows SAPI voices).",
        "mac": "Built in (macOS voices).",
        "linux": "sudo apt install espeak-ng   (needed only for draft mode with a voice)",
    },
    "tesseract": {
        "windows": "winget install UB-Mannheim.TesseractOCR   (better OCR than the built-in engine)",
        "mac": "brew install tesseract",
        "linux": "sudo apt install tesseract-ocr",
    },
    "pandoc": {
        "windows": "winget install JohnMacFarlane.Pandoc",
        "mac": "brew install pandoc",
        "linux": "sudo apt install pandoc",
    },
}


# The LaTeX packages Manim needs (the minimal set Manim's own Windows package installs).
TEX_PACKAGES = ["standalone", "preview", "doublestroke", "ms", "setspace", "rsfs", "relsize", "ragged2e",
                "fundus-calligra", "microtype", "wasysym", "physics", "dvisvgm", "jknapltx", "wasy", "cm-super",
                "babel-english"]
FIX["latex"]["mac"] = FIX["latex"]["mac"].replace("{texpkgs}", " ".join(TEX_PACKAGES))


def free_gb(path: str = HOME) -> float:
    try:
        target = path if os.path.exists(path) else os.path.expanduser("~")
        return shutil.disk_usage(target).free / 1e9
    except OSError:
        return -1.0


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    fix: str = ""
    required: bool = True
    extra: dict = field(default_factory=dict)


def _venv_python() -> str | None:
    p = os.path.join(VENV, "Scripts", "python.exe") if os.name == "nt" else os.path.join(VENV, "bin", "python")
    return p if os.path.exists(p) else None


def _cmd_version(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30).stdout
        return out.decode("utf-8", "replace").strip().splitlines()[0][:100] if out else ""
    except Exception:  # noqa: BLE001
        return ""


def _probe_python(py: str, code: str) -> dict:
    try:
        out = subprocess.run([py, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
        return json.loads(out.stdout.decode() or "{}")
    except Exception:  # noqa: BLE001
        return {}


PROBE = r"""
import json, importlib, sys
r = {"python": list(sys.version_info[:3])}
for m in ["manimgx", "manim", "ty", "PIL", "faster_whisper", "whisperx", "pyttsx3", "rapidfuzz", "pypdf", "pypdfium2", "numpy", "torch", "ctranslate2", "rapidocr", "rapidocr_onnxruntime"]:
    try:
        mod = importlib.import_module(m)
        r[m] = getattr(mod, "__version__", "yes")
    except Exception as e:
        r[m] = None
try:
    import ctranslate2
    r["ct2_cuda"] = ctranslate2.get_cuda_device_count()
except Exception:
    r["ct2_cuda"] = 0
try:
    import torch
    r["torch_cuda"] = bool(torch.cuda.is_available())
except Exception:
    r["torch_cuda"] = False
try:
    from manimgx import _engine           # private, but the only way to ask which GPU ManimGX uses
    r["gx_adapter"] = _engine.adapter_info()
except Exception:
    r["gx_adapter"] = None
try:
    import pyttsx3
    e = pyttsx3.init()
    r["tts_voices"] = len(e.getProperty("voices") or [])
except Exception as e:
    r["tts_voices"] = 0
print(json.dumps(r))
"""


def gpu_info() -> dict:
    info = {"kind": "none", "name": ""}
    smi = shutil.which("nvidia-smi")
    if smi:
        name = _cmd_version([smi, "--query-gpu=name", "--format=csv,noheader"])
        if name and "fail" not in name.lower():
            info = {"kind": "cuda", "name": name}
    elif sys.platform == "darwin" and platform.machine() == "arm64":
        info = {"kind": "apple", "name": "Apple Silicon (transcription runs on CPU)"}
    return info


def _tesseract() -> str | None:
    p = shutil.which("tesseract")
    if p:
        return p
    if os.name == "nt":
        for c in (r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
            if os.path.exists(c):
                return c
    return None


def run_checks(deep: bool = False) -> list[Check]:
    checks: list[Check] = []
    v = sys.version_info
    checks.append(Check("Python >= 3.10", v >= (3, 10), f"{platform.python_implementation()} {platform.python_version()} ({sys.executable})",
                        "Install Python 3.10+ from python.org"))
    for tool in ("ffmpeg", "ffprobe"):
        p = shutil.which(tool)
        checks.append(Check(tool, bool(p), _cmd_version([p, "-version"]) if p else "not found", FIX["ffmpeg"][OS]))
    gb = free_gb()
    if 0 <= gb < 4:
        checks.append(Check("Free disk space", False, f"{gb:.1f} GB free",
                            "renders and the Whisper models need a few GB: free some space", required=False))
    checks.append(Check("pandoc (optional: .odt/.rtf/.html scripts)", bool(shutil.which("pandoc")),
                        shutil.which("pandoc") or "not found", FIX["pandoc"][OS], required=False))

    g = gpu_info()
    checks.append(Check("GPU (transcription)", True, f"{g['kind']}: {g['name'] or 'none (CPU transcription)'}",
                        required=False, extra=g))

    vp = _venv_python()
    r = _probe_python(vp, PROBE) if vp else {}
    pyv = tuple(r.get("python") or (0, 0, 0))
    env_ok = bool(vp) and pyv >= (3, 13)
    detail = f"{vp} (Python {'.'.join(map(str, pyv))})" if vp else f"missing ({VENV})"
    checks.append(Check("Managed environment (Python 3.13+)", env_ok, detail,
                        "python3 mm.py doctor --install   (creates it, or recreates an older one, with Python 3.13)"))
    if vp:
        checks.append(Check("ManimGX (renderer)", bool(r.get("manimgx")), str(r.get("manimgx") or "not importable"),
                            "python3 mm.py doctor --install"))
        ad = r.get("gx_adapter") or {}
        if r.get("manimgx"):
            on_cpu = str(ad.get("device_type", "")).lower() == "cpu" or not ad
            checks.append(Check("Rendering on a GPU", not on_cpu,
                                (f"{ad.get('name', '?')} via {ad.get('backend', '?')}" if ad else "no adapter found")
                                + ("  (drawing on the CPU: works, but about as slow as Manim CE)" if on_cpu else ""),
                                FIX["gpu"][OS], required=False))
        checks.append(Check("Type checker for scene code (ty)", bool(r.get("ty")), str(r.get("ty") or "missing"),
                            "python3 mm.py doctor --install", required=False))
        for mod, label in (("numpy", "numpy"), ("rapidfuzz", "rapidfuzz"), ("pypdf", "pypdf"), ("pypdfium2", "pypdfium2 (references)")):
            checks.append(Check(label, bool(r.get(mod)), str(r.get(mod) or "missing"), "python3 mm.py doctor --install"))
        fw, wx = r.get("faster_whisper"), r.get("whisperx")
        checks.append(Check("Transcription (faster-whisper)", bool(fw or wx), f"faster-whisper {fw}, whisperx {wx}",
                            "python3 mm.py doctor --install"))
        if fw:
            ok, detail = decode_check(vp)
            checks.append(Check("Transcription can decode audio", ok, detail,
                                "python3 mm.py doctor --install   (re-applies the tested versions from constraints.txt)"))
        if g["kind"] == "cuda":
            cuda_ok = bool(r.get("ct2_cuda")) or bool(r.get("torch_cuda"))
            checks.append(Check("CUDA transcription", cuda_ok,
                                f"ctranslate2 sees {r.get('ct2_cuda', 0)} GPU(s); torch cuda={r.get('torch_cuda')}",
                                "python3 mm.py doctor --install --gpu   (installs cuBLAS/cuDNN wheels)", required=False))
        tess = _tesseract()
        rapid = bool(r.get("rapidocr") or r.get("rapidocr_onnxruntime"))
        ocr_detail = "tesseract" if tess else ("RapidOCR (built-in)" if rapid else "none")
        checks.append(Check("OCR for scanned references", bool(tess or rapid), ocr_detail,
                            "python3 mm.py doctor --install   (adds RapidOCR); for best results also: " + FIX["tesseract"][OS],
                            required=False))
        if deep and fw:
            checks.append(deep_check(vp))
        checks.append(Check("Draft-mode voice (pyttsx3)", bool(r.get("pyttsx3")) and r.get("tts_voices", 0) > 0,
                            f"pyttsx3 {r.get('pyttsx3')}, {r.get('tts_voices', 0)} voices",
                            FIX["tts"][OS] + "; drafts still work silently without it", required=False))
        # The Manim CE fallback ([render] engine = "manim") is optional: only report on it if it's there.
        if r.get("manim"):
            lp, dp = shutil.which("latex"), shutil.which("dvisvgm")
            checks.append(Check("Manim CE fallback: LaTeX", bool(lp and dp), f"latex {lp or 'missing'}, dvisvgm {dp or 'missing'}",
                                FIX["latex"][OS], required=False))
            pil = str(r.get("PIL") or "0")
            old_pil = int(pil.split(".")[0] or 0) < 13
            checks.append(Check("Manim CE fallback: Pillow < 13", old_pil, f"Pillow {pil}",
                                "python3 mm.py doctor --install --with-manim-ce   (Pillow 13 breaks images in Manim CE 0.22)",
                                required=False))
    return checks


REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLE = os.path.join(REPO, "examples", "demo", "audio", "session.flac")

DECODE_PROBE = r"""
import sys, json
from faster_whisper import decode_audio
a = decode_audio(sys.argv[1])
print(json.dumps({"seconds": round(len(a) / 16000, 2)}))
"""

DEEP_PROBE = r"""
import sys, json, time
from faster_whisper import WhisperModel
t = time.time()
m = WhisperModel("tiny.en", device="cpu", compute_type="int8")
segs, info = m.transcribe(sys.argv[1], language="en", word_timestamps=True, vad_filter=True)
words = [w.word.strip() for s in segs for w in (s.words or [])][:12]
print(json.dumps({"words": words, "seconds": round(time.time() - t, 1)}))
"""


def decode_check(py: str) -> tuple[bool, str]:
    """Decode a real file the way transcription does (catches broken PyAV / ffmpeg libraries)."""
    if not os.path.exists(SAMPLE):
        return True, "skipped (sample clip not found)"
    try:
        out = subprocess.run([py, "-c", DECODE_PROBE, SAMPLE], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    except Exception as e:  # noqa: BLE001
        return False, f"probe failed: {e}"
    if out.returncode != 0:
        last = (out.stderr.decode("utf-8", "replace").strip().splitlines() or ["?"])[-1]
        return False, f"decoding failed: {last[:160]}"
    return True, "decoded the sample clip " + out.stdout.decode().strip()


def deep_check(py: str) -> Check:
    """Download the tiny model (~75 MB) and transcribe the sample: proves the whole stack works."""
    if not os.path.exists(SAMPLE):
        return Check("Transcribe a sample (tiny.en)", True, "skipped (sample clip not found)", required=False)
    out = subprocess.run([py, "-c", DEEP_PROBE, SAMPLE], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900)
    if out.returncode != 0:
        last = (out.stderr.decode("utf-8", "replace").strip().splitlines() or ["?"])[-1]
        net = any(k in last.lower() for k in ("connection", "resolve", "huggingface", "offline", "timed out"))
        return Check("Transcribe a sample (tiny.en)", False, last[:200],
                     "check your internet connection (models download from Hugging Face)" if net else
                     "python3 mm.py doctor --install", required=not net)
    r = json.loads(out.stdout.decode() or "{}")
    return Check("Transcribe a sample (tiny.en)", bool(r.get("words")),
                 f"heard: {' '.join(r.get('words', []))} … ({r.get('seconds')} s)", required=False)


def print_report(checks: list[Check], as_json: bool = False) -> int:
    if as_json:
        print(json.dumps([c.__dict__ for c in checks], indent=1))
    else:
        print(f"Manimatic doctor  ({OS}, home: {HOME})")
        for c in checks:
            mark = "OK " if c.ok else ("!! " if c.required else "-- ")
            print(f"  {mark} {c.name}: {c.detail}")
            if not c.ok and c.fix:
                print(f"       fix: {c.fix}")
    bad = [c for c in checks if c.required and not c.ok]
    if not as_json:
        print("\nAll required checks passed." if not bad else f"\n{len(bad)} required check(s) failing.")
    return 1 if bad else 0


# ------------------------------------------------------------------- install

def _run(cmd: list[str]) -> None:
    print("  $ " + " ".join(cmd), flush=True)
    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise SystemExit(f"Install step failed: {' '.join(cmd)}")


def _find_python313(base_python: str | None, uv: str | None) -> str | None:
    """An interpreter for the managed environment: Python 3.13+ (ManimGX needs it)."""
    cands = [base_python] if base_python else []
    cands += [sys.executable, shutil.which("python3.14"), shutil.which("python3.13")]
    if os.name == "nt" and shutil.which("py"):
        for v in ("3.14", "3.13"):
            out = _cmd_version(["py", f"-{v}", "-c", "import sys; print(sys.executable)"])
            if out and os.path.exists(out):
                cands.append(out)
    for c in cands:
        if not c:
            continue
        v = _cmd_version([c, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"])
        try:
            if tuple(int(x) for x in v.split(".")) >= (3, 13):
                return c
        except ValueError:
            continue
    return None


def install(gpu: str = "auto", whisperx: bool = False, base_python: str | None = None, ocr: bool = True,
            deep: bool = False, with_manim_ce: bool = False) -> int:
    os.makedirs(HOME, exist_ok=True)
    uv = shutil.which("uv")
    vp = _venv_python()
    if vp:
        pv = _probe_python(vp, "import json, sys; print(json.dumps({'v': list(sys.version_info[:2])}))").get("v", [0, 0])
        if tuple(pv) < (3, 13):
            old = VENV + ".old"
            print(f"The managed environment uses Python {pv[0]}.{pv[1]}; ManimGX needs 3.13. Recreating it "
                  f"(the old one is moved to {old} and can be deleted).")
            if os.path.exists(old):
                shutil.rmtree(old, ignore_errors=True)
            os.replace(VENV, old)
            vp = None
    if not vp:
        base = _find_python313(base_python, uv)
        site = ["--system-site-packages"] if base_python else []   # --python: reuse that Python's packages
        if base:
            print(f"Creating the managed environment in {VENV} with {base}")
            if uv:
                _run([uv, "venv", *site, "--python", base, VENV])
            else:
                _run([base, "-m", "venv", *site, VENV])
        elif uv:
            print(f"Creating the managed environment in {VENV} (uv downloads Python 3.13)")
            _run([uv, "venv", "--python", "3.13", VENV])
        else:
            raise SystemExit("ManimGX needs Python 3.13 or newer, and none was found.\n"
                             f"  Easiest: install uv, which fetches Python 3.13 by itself: {FIX['python313'][OS]}\n"
                             "  Or install Python 3.13 from python.org and run this again.")
    vp = _venv_python()
    assert vp, "venv creation failed"

    constraints = os.path.join(REPO, "constraints.txt")
    cflag = ["-c", constraints] if os.path.exists(constraints) else []

    def pip(*pkgs: str) -> None:
        if uv:
            _run([uv, "pip", "install", "--python", vp, *cflag, *pkgs])
        else:
            _run([vp, "-m", "pip", "install", "--upgrade", *cflag, *pkgs])

    if not uv:
        _run([vp, "-m", "pip", "install", "--upgrade", "pip"])
    pkgs = ["manimgx", "ty", "numpy>=1.24", "rapidfuzz>=3.0", "pypdf>=4.0", "pypdfium2>=4.30", "pillow>=9",
            "faster-whisper>=1.0", "av<19", "pyttsx3>=2.90"]
    pip(*pkgs)
    if with_manim_ce:
        print(f"Installing the Manim CE fallback (also needs LaTeX: {FIX['latex'][OS].splitlines()[0]})")
        try:
            pip("manim>=0.19", "pillow<13")
        except SystemExit:
            print(f"  Manim CE couldn't be installed. It needs: {FIX['manim_sys'][OS]}")

    use_gpu = gpu == "cuda" or (gpu == "auto" and gpu_info()["kind"] == "cuda")
    if use_gpu and OS in ("linux", "windows"):
        print("NVIDIA GPU detected: installing CUDA 12 runtime libraries for faster-whisper")
        pip("nvidia-cublas-cu12", "nvidia-cudnn-cu12>=9,<10")
    if whisperx:
        print("Installing WhisperX (large download: PyTorch)")
        pip("whisperx>=3.1")
    if ocr:
        print("Installing RapidOCR (OCR for scanned exam papers and images; about 100 MB)")
        try:
            pip("rapidocr>=3.0", "onnxruntime>=1.17")
        except SystemExit:
            print("  RapidOCR couldn't be installed on this platform; install Tesseract instead: " + FIX["tesseract"][OS])
    print("\nDone. Re-checking:\n")
    return print_report(run_checks(deep=deep))
