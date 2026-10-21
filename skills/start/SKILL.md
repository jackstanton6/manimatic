---
name: start
description: Set up Manimatic, which turns a narrated maths script plus its voice recording into a 3Blue1Brown-style Manim video. Checks and installs what it needs, then creates a video project. Use when the user wants to make a maths or Manim video from their script and audio, or asks to set up or install Manimatic.
argument-hint: "[project folder]"
allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/mm.py" *) Bash(py -3 "${CLAUDE_PLUGIN_ROOT}/mm.py" *)
---

# Manimatic: set up

**How to run Manimatic.** In this skill, `MM` means `python3 "${CLAUDE_PLUGIN_ROOT}/mm.py"` on macOS and Linux, and `py -3 "${CLAUDE_PLUGIN_ROOT}/mm.py"` on Windows. Run it inside the project folder, or add `-C <project folder>`. All state lives in files, so `MM status` always says where a project is up to and what comes next.

## 1. Check the environment
Run `MM doctor`.
- **Managed environment missing, failing or on an old Python:** tell the user that `MM doctor --install` creates a private Python 3.13 environment in `~/.manimatic/venv` and installs ManimGX (the renderer, which brings its own maths typesetting: no LaTeX needed), faster-whisper and a few libraries. That's roughly 1 GB, and the first transcription downloads a Whisper model: `small.en` is about 0.5 GB on CPU, `large-v3` about 3 GB on an NVIDIA GPU. Ask before running it.
  - If no Python 3.13 is found, the doctor prints how to install `uv`, which fetches Python 3.13 by itself.
  - If they have an NVIDIA GPU, add `--gpu cuda` to get the CUDA libraries for transcription. Add `--whisperx` only if they want sharper word timing and accept the PyTorch download.
- **ffmpeg missing:** pip can't install it. Show the exact fix line the doctor prints for their OS, and only run it if they agree, because it may need admin rights.
- **"Rendering on a GPU" unticked:** ManimGX found no GPU and draws on the CPU. It works, but renders are about as slow as Manim CE. Updating the graphics driver usually fixes it.
- **Manim CE fallback:** only if ManimGX can't run on their machine, `MM doctor --install --with-manim-ce` adds Manim CE, which also needs LaTeX (the doctor prints how; on macOS prefer the small BasicTeX option). Then set `[render] engine = "manim"` in the project's `manimatic.toml`.
- **"Transcription can decode audio" failing:** the Python packages don't work together. Run `MM doctor --install` again; it applies the tested versions from `constraints.txt`.
- Run `MM doctor` again until the required checks pass. Optional checks (pandoc, draft voice, OCR, GPU) can stay unticked.
- Optional, once: `MM doctor --deep` downloads the tiny Whisper model (~75 MB) and transcribes a sample clip. That proves the whole transcription stack works before a real recording depends on it.

## 2. Create the project
`MM new <folder> --title "<video title>"` creates:
```
script/      the script: .docx .md .txt .pdf .tex (others via pandoc)
audio/       the recording(s), any format; several files are joined in natural order
music/       optional: bed.*, intro.* (title-card sting), outro.* (end-card sting)
references/  optional: exam papers, textbook pages or images to show questions from
```
Copy any files the user already gave you into the right folders. Rename music to `bed.*` (plays under everything, including any card without a sting), `intro.*` (sting over the title card) and `outro.*` (sting over the end card). Files with other names are ignored, and `MM status` lists them under `music_not_used`. Keep exactly one file in `script/`.

## 3. Hand over
- **Script not written yet:** point them to `${CLAUDE_PLUGIN_ROOT}/reference/annotation-syntax.md`. The short version: write it as they'll say it, and put visual directions in `[[double brackets]]`, labels like `Visual:`, or comments.
- **Script ready but no recording yet:** offer draft mode. Plan and preview with a text-to-speech voice now, then re-time to the real recording later.
- **Script ready:** continue with the plan step (the `/manimatic:plan` skill).

Keep messages short and in plain words. The user is a video maker, not necessarily a programmer.
