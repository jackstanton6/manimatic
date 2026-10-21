# Manimatic: notes for continuing development

Manimatic is a Claude Code plugin (GPL-3.0-or-later) that turns a narrated maths script plus its voice recording into a 3Blue1Brown-style maths video, rendered with ManimGX (Manim CE's API on a GPU renderer; Manim CE remains as a fallback engine). The skills (`skills/*/SKILL.md`) tell Claude what to do; all real work happens in a cross-platform Python CLI (`mm.py` → `src/manimatic/`). Read `README.md` for the user's view and `reference/*.md` for the user-facing details. This file is for whoever works *on* the code.

## Status (v0.2.0, unreleased)
**0.2.0 moved rendering to ManimGX** (owner's decision, Oct 2026), after a spike: every formula in both scripts renders, the demo scene files render unchanged with frames matching Manim CE, and the owner benchmarked both engines on his machines (1080p60, demo + three Banach–Tarski-style scenes: RTX 5070 Ti desktop 10.5 s vs 445 s; M1 MacBook Air ~12× on 3D). In the dev sandbox (no GPU, 2 cores) ManimGX draws on the CPU via lavapipe at roughly Manim CE's speed, and point clouds are slower.

**0.1.x history:** a real 5-minute Banach–Tarski test run (real MP3, faster-whisper small.en) drove the second round of fixes (see CHANGELOG): room tone for gated recordings, audio and level checks, bed under cards, stable IDs, the approval gate, section-by-section build, subagents, contact sheets, constraints and doctor checks.

Verified in the dev sandbox (Linux, Python 3.13, CPU only):
- the full pipeline on the demo and on a noise-gated clip (mock transcription), with **both engines**: demo preview frame-exact, BT.709-tagged, last pictures held correctly
- all components render on both engines (`tests/test_render.py`); `screen_points` matches rendered pixels to < 1 px
- `doctor --install` recreating a Python 3.9 environment with 3.13, with and without `--with-manim-ce`
- type-checking scene files with ty (`lint`)
- `claude plugin validate .` (one expected warning: CLAUDE.md at the root is for developers)
- 38 pytest tests (render tests on both engines), also under a CP1252 locale (Windows' default encoding); 2 more (real faster-whisper tiny.en) are skipped here because the sandbox can't reach Hugging Face. The CI `asr` job runs them.

**Not yet verified, in priority order:**
1. **ManimGX through Manimatic on a real GPU.** The owner's benchmark used the spike's port; the final library (`lib/`) has only run on lavapipe here. Ask for a `build` of the demo on his desktop and Mac.
2. **The CI jobs.** The first push failed on CI design (setup-ffmpeg, Windows test encodings, RapidOCR on 3.13); all three are fixed but the jobs haven't run again yet.
3. **Windows** by hand.
4. **Long videos (~2 h).** `cut.py` keeps up to two source files in memory as int16 (~700 MB for a 2 h file); PLAN.md gets very large.

## Layout
```
mm.py                     launcher: re-execs into ~/.manimatic/venv (MANIMATIC_HOME) unless MANIMATIC_NO_VENV=1;
                          always puts this repo's src/ on PYTHONPATH (so the venv never needs reinstalling)
.claude-plugin/           plugin.json + marketplace.json (marketplace source "./")
skills/{start,plan,build,revise}/SKILL.md   use ${CLAUDE_PLUGIN_ROOT}/mm.py; no shell-specific syntax (Windows)
reference/*.md            loaded on demand by the skills: annotation syntax, component library, visual style, CLI, troubleshooting,
                          subagent-brief (the prompt for per-section subagents in long builds)
src/manimatic/
  cli.py                  argparse commands; ManimaticError -> clean message, exit 1
  project.py              project folder, manimatic.toml defaults (DEFAULTS), qualities, state.json
  doctor.py               stdlib-only env checks + managed-venv install (uv if present, else venv+pip)
  ingest/readers.py       md/txt/docx(comments, italics, highlights, headings)/pdf/tex/pandoc -> Para/Run
  ingest/annotations.py   annotation detection ([[ ]], labels, brackets, italics, comments...), kinds, hold_seconds()
  ingest/speech.py        spoken-form normalisation (numbers, LaTeX -> words); SHARED by script and transcript
  ingest/__init__.py      sentences -> lines L0001…, sections, annotation placement (line, token index / -1 = end)
  asr/__init__.py         faster-whisper | whisperx | mock (reads <audio>.words.json); cached per file hash
  audiocheck.py           verify_voice (re-transcribe the edited voice, diff with the script), check_levels (mix on cards/holds/pauses)
  align.py                takes per line (n-gram anchors + Smith-Waterman), last-complete-take selection, pickups,
                          classification of leftovers (retake/slate/flub/filler/adlib/minor)
  cut.py                  edited voice (room-tone fills, fades), pause shortening, holds, untranscribed-sound removal,
                          timeline.json (word times in the edited voice)
  draft.py                TTS (pyttsx3) or silent draft voice + timeline, honours holds
  refs.py, ocr.py         find/crop questions in PDFs/images (text layer, else OCR), word boxes, dark version
  plan.py                 PLAN.md render/parse/sync, scene timing (compute_times), per-scene slices
  anchors.py              anchor resolution (no Manim import: lint uses it)
  render.py               scaffold, lint (+ ty type check), cached render via worker processes, checks, frames, sheets
  render_worker.py        runs inside the managed Python: renders several scenes in one process (ManimGX or Manim CE),
                          one JSON line per scene start/end; for Manim CE it aliases manimatic.lib -> manimatic.lib_ce
  output.py               mix (ducking, stings, loudnorm), frame-exact assembly (VFR -> CFR, BT.709), captions, chapters, burn-in
  lib/                    what scene files import (ManimGX): theme (Typst text), components, ManimaticScene / ManimaticCameraScene /
                          Manimatic3DScene (own 3D projection: screen_points)
  lib_ce/                 the same library on Manim CE, for the fallback engine ([render] engine = "manim"); remove in 0.3
tools/                    make_demo_audio.py (espeak), make_gated_clip.py (espeak, noise-gated test clip), make_demo_exam.py (reportlab), make_demo_gif.py
tests/data/gated/         noise-gated clip + mock transcript + script (room-tone regression, real-ASR CI test)
constraints.txt           tested version ranges; doctor --install and CI install with -c constraints.txt
examples/demo/            complete, approved demo project (also the test fixture)
docs/demo.gif             README GIF (rebuild with tools/make_demo_gif.py)
```

## Data flow (all state is files in `<project>/.manimatic/`)
```
script/* --ingest--> script.json (+script.md)          overrides: annotation_overrides.json, spoken_overrides.json
audio/*  --transcribe--> asr/<stem>-<hash>.json, asr/manifest.json
         --align--> align.json (takes, decisions C/F/M ids, tokens, words)
         --cut-->   output/voice_edit.wav, timeline.json, cuts.md, sounds.json      overrides: cut_overrides.json
(or) draft --> output/voice_draft.wav, timeline.json (draft: true)
references/* --refs--> refs/refs.json, R01.png, R01_dark.png, R01.txt, R01.words.json, refs/ocr/*   overrides: ref_overrides.json
PLAN.md <--plan init/sync--> plan_settings.json, scenes.json (index, meta, chapters), scenes/<ID>.json (slices)
scenes/*.py --render--> render/<quality>/<ID>.mp4 (+hash json), checks/<ID>.json, logs/
           --assemble--> output/<slug>[.preview|.draft].mp4/.srt/.vtt/.chapters.txt[/.captioned.mp4]
```
User decisions live in the `*_overrides.json` files, keyed by stable keys, not ids, so they survive re-runs. PLAN.md ticks are written back into those files by `plan sync`.

IDs (C/F/M decisions, S sounds) come from `util.stable_id(work, prefix, key)` and are stored in `.manimatic/ids.json`, keyed like `"0:19.81:adlib"` (file index, start, kind). The same decision keeps its ID across re-runs; a new decision gets the next free number. Each PLAN.md item quotes its text, and `plan sync` ignores a tick whose quote no longer matches (`plan._text_matches`).

Other state: `audio_check.json` (`voice`, `levels`), `audio/bed.json` + `bed_src.wav` (the bed as mixed), `sheets/<ID>.png`, `checks/<ID>.json` (with `beats`), `plan_lines.json` (line texts at the last slice, for re-anchoring).

## Invariants (don't break these)
- **Shared normalisation.** Script and transcript go through the *same* normalisation in `speech.py`. Changing it changes alignment *and* the spoken form anchors resolve against: existing scene files use anchors like `"sixty"`, `"x squared"`.
- **PLAN.md round-trips.**
  - Lines starting with `> L`, `- Annotations:` and `- References:` are regenerated.
  - Everything else under a scene heading is preserved verbatim.
  - Scene headings are `### Sxx.y · L0001[–L0002][ · title]`.
  - `test_plan_keeps_user_edits` guards this.
- **Scenes partition the script by their first line.** Line ids shift when the script is edited, so `plan_sync` re-anchors scenes by the text of their first line (`scenes.json` → `first_text`).
- **Every scene ends on a whole frame.** Assembly pads or trims each clip to `round(end*fps) - round(start*fps)` frames, so audio can't drift. Filter order matters: `fps=` (make constant-rate) **then** `tpad=stop_mode=clone` (pad generously) **then** `trim`. Never trust the container duration for the pad (see gotchas).
- **One scene API, two engines.** Scene files say `from manimatic.lib import *` and must render on ManimGX and on the Manim CE fallback; keep `lib/` and `lib_ce/` in step until 0.3 (`tests/test_render.py` renders both).
- **Only reversible audio edits.** Every cut is listed (PLAN.md or cuts.md) and reversible. Ad-libs default to *keep*. Voice processing is off unless the user asks.
- **Cross-platform.**
  - Use pathlib and ffmpeg argument lists, never shell strings.
  - Skills contain no `&&`, pipes or bash-only syntax.
  - Subtitle burn-in runs ffmpeg with `cwd` set to the output folder, which avoids escaping Windows drive colons.
- **Scene audits never raise.** They run inside `play()` and must not break a render; failures go into `warnings`.

## Gotchas learned the hard way
- **Name clashes with the engines' `Scene`.** Avoid `duration` (Manim overwrites it, so we use `scene_duration`), `clear()` (ours is `clear_screen()`), `_fps` (ManimGX's frame-rate method: ours is `_mm_fps`), `time` (ManimGX's clock property, which `now` reads) and a method named `project` (our `self.project` is the project folder; the projection is `screen_points`). Both engines also have their own `wait_until(stop_condition)`, which ours overrides.
- **ManimGX writes variable-frame-rate MP4s.** A still stretch is one encoded frame; a clip ending on a still has its last packet seconds before the track's end, and `fps=` alone drops that tail. `extract_frames` selects frame numbers after `fps,tpad`, never `-ss` into the file.
- **ManimGX colour.** Clips are BT.601, tagged `smpte170m`; Manim CE clips are BT.601, untagged. `_normalise_clip` converts both to BT.709 and tags the output (`BT709` in output.py).
- **Private ManimGX API.** `Words`/`TextBlock` call `manimgx.mobjects.text._math` (its LaTeX→Typst converter) for inline maths, and doctor reads `manimgx._engine.adapter_info()`. That's why constraints pin ManimGX to 0.1.x; check both when upgrading.
- **`-shortest` drops frames.** The final mux used `-shortest` and lost the last ~3 frames; video and mix are the same length by construction, so it's gone.
- **Pillow 13 + Manim CE 0.22**: `Image.fromarray(np.zeros(...), mode="RGBA")` raises "Invalid mode for data type" on any image scene. Pillow stays below 13.
- **Windows encodings.** Python's default file encoding on Windows is cp1252, so every `read_text`/`write_text`/`open` (code *and* tests) passes `encoding="utf-8"`: PLAN.md is full of `·` and `–`. To reproduce Windows behaviour on Linux: `localedef -f CP1252 -i en_US /tmp/locales/en_US.CP1252`, then run pytest with `LOCPATH=/tmp/locales LC_ALL=en_US.CP1252`.
- **RapidOCR packages.** `rapidocr_onnxruntime` declares `Requires-Python <3.13` (uv ignores that upper bound, pip doesn't). We install `rapidocr` 3.x + `onnxruntime`; `ocr._rapid_results` accepts either package's output.
- **Images need a `Group`.** `ImageMobject` can't go in a `VGroup`; `ReferenceCard` is a `Group`.
- **`run_time=self.time_until(...)` inside `play_at(...)`** is evaluated *before* the wait, so the timing is wrong. Use `play_at(anchor, ..., until="word")`; `lint` rejects the bad pattern.
- **Frame rounding.** Manim CE rounds each animation up to whole frames (lib_ce allows one frame of tolerance); ManimGX samples exact times (lib allows half a frame).
- **Camera scenes.** The off-screen audit only runs while the camera is at home.
- **3D scenes.** The audit projects points with `screen_points` (Manim CE's orbit convention plus ManimGX's perspective: `x' = zoom·x_cam / (1 − z_cam/focal)`), and screen-fixed overlays are audited like 2D.
- **Holds at a scene boundary.** A hold *after* a scene's last line belongs to that scene. A hold *before* a scene's first line opens the next scene. Slices clamp a hold's `end` to the scene's end.
- **Whisper drops "um".** That's why `cut.py` looks for voiced energy inside pauses ("sounds", ids `S###`).
- **Crop edges.** The bottom edge searches *down* for a blank row before going up; going up cuts through diagrams. The top edge never reaches into the previous line or its figure.
- **RapidOCR word boxes.** RapidOCR returns lines, so word boxes come from ink segments aligned to the words by dynamic programming (`ocr._word_spans`).
- **Room tone.** Never pick it from "the quietest window anywhere": gated recordings have no long pauses, so that window contains word tails. `cut.pick_room_tone` uses gaps between ASR words with margins and an absolute ceiling, and returns zeros when nothing qualifies. Guarded by `test_room_tone_skips_word_tails` and the gated clip.
- **PyAV 19** removed an argument faster-whisper 1.2.1 passes to `av.open()`. `constraints.txt` keeps it below 19, and `doctor` decodes a real clip to catch the next break like it.
- **Mock transcripts of the edited voice** are sidecars (`voice_edit.wav.words.json`); the verify cache key includes the sidecar's hash.
- **Carried state between scenes.** Each scene renders in its own process, so the next scene rebuilds what it inherits from builder functions in the project's `scenes/common.py` (documented in component-library.md). A first-class `end_state` is on the roadmap.
- **ffmpeg memory.** A single filter graph trimming several segments from a 1080p60 source runs out of memory. Cut small clips first (see `make_demo_gif.py`).

## Working on it
```bash
MANIMATIC_NO_VENV=1 python -m pytest -q          # use a Python 3.13 dev env (pip install -e ".[dev,render,manim-ce,ocr,tts]" -c constraints.txt);
                                                 # render tests need manimgx (any GPU, or lavapipe on Linux); the fallback ones also LaTeX; tesseract or rapidocr for OCR;
                                                 # faster-whisper + network for the real-ASR tests, which are skipped otherwise; MANIMATIC_REQUIRE_ASR=1 makes them mandatory)
cp -r examples/demo /tmp/d && sed -i 's/^asr_backend = .*/asr_backend = "mock"/' /tmp/d/manimatic.toml
python mm.py -C /tmp/d prepare && python mm.py -C /tmp/d build --preview
```
- Regenerating the demo's recording needs espeak-ng. It writes `session.flac` and its `.words.json` mock transcript, with ums deliberately left out.
- When the demo changes, rebuild with `--burn` (music optional) and run `tools/make_demo_gif.py`.
- Keep `SKILL.md` files short, and put the most important instructions near the top, because only the start of a skill survives context compaction. Detail belongs in `reference/`.
- When adding a component: put it in `lib/components.py`, add it to `__all__`, document it in `reference/component-library.md`, and update the style rules in `reference/visual-style.md` if it changes conventions.

## Roadmap (agreed with the owner)
Next:
- the owner builds the demo on his GPU machines with 0.2.0; watch the first CI runs and fix what they find
- 0.3: remove the Manim CE fallback (`lib_ce/`, the `manim` branches in render_worker/doctor, the fallback CI job) if nothing needed it
- test a long video (stream the cut instead of loading whole files; split PLAN.md per section)
- run on Windows by hand
- first-class carried state: a scene declares `end_state()`, and the next scene can start from it without a hand-written builder in `common.py`
- ask ManimGX upstream for a public LaTeX→Typst helper (we use the private `_math`)

After that:
- `mm.py preview S03.2` (one scene with its audio); ManimGX can also play scenes in the browser, which could make this instant
- thumbnails
- Shorts (9:16 re-layout: ManimGX keeps the middle 8×8 square the same in both orientations)
- languages other than English
- per-section music
- handling paraphrased retakes better (currently they can both look incomplete)

Version policy: stay on 0.x while PLAN.md, `manimatic.toml` and the scene API may change. 1.0 means those are stable and real-recording alignment is proven on more than one voice.
