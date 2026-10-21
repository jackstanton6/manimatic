# Changelog

## 0.2.0 (unreleased)
Rendering moves to [ManimGX](https://manimgx.academa.ai): Manim CE's API on a Rust/GPU renderer.

- **ManimGX is the default engine.** Measured on the bundled demo plus three Banach–Tarski-style scenes at 1080p60: 10.5 s instead of 445 s on an RTX 5070 Ti desktop, and about 12× faster on an M1 MacBook Air for the 3D and tree scenes. 3D scenes gain proper depth and lighting. Without a GPU, ManimGX draws on the CPU at roughly Manim CE's speed.
- **No LaTeX needed.** Maths is LaTeX converted to Typst inside ManimGX; every formula in the demo and Banach–Tarski scripts renders. `Words`/`TextBlock` are rebuilt on Typst: text prints as written (no escaping), with inline `$maths$`, accents, wrapping and line breaks.
- **Manim CE stays as a fallback** (`[render] engine = "manim"`, `doctor --install --with-manim-ce`). The same scene files render with both; the Manim CE library lives on as `manimatic.lib_ce`. Planned for removal in 0.3.
- **Several scenes per render process** (`manimatic.render_worker`): the GPU starts once per process instead of once per scene. A scene that crashes its process is reported and the rest carry on in a new one.
- **Type-checked scene code**: `lint` runs ty over the scene files; misspelt keywords, methods and names are errors before anything renders.
- **Variable-frame-rate clips handled**: ManimGX stores still stretches as one long frame. Assembly and frame extraction now convert to a constant rate first and hold the last picture, so every scene is still exactly its planned number of frames.
- **3D off-screen check** reimplemented for ManimGX (`screen_points`, checked against rendered pixels); `dot_cloud` is now a single GPU point cloud.
- **Doctor**: creates the managed environment with Python 3.13 (via uv if needed; older environments are recreated), reports which GPU ManimGX renders on, checks the type checker; LaTeX is checked only for the fallback.
- OCR uses `rapidocr` 3.x (models bundled), the successor of `rapidocr_onnxruntime`, which doesn't support Python 3.13; the old package still works where it's installed.
- CI: ffmpeg comes from each OS's package manager (the setup-ffmpeg action failed on downloads and on Apple Silicon runners); tests read and write files as UTF-8 explicitly, which fixes the Windows jobs; console output can't crash on characters a Windows code page lacks.
- Fixes found on the way: the final mux no longer drops the last frames (`-shortest`); the finished video is BT.709 and tagged so; a crash in `check` when reporting overlapping text; Manim CE + Pillow 13 broke image scenes (`Invalid mode for data type`), so Pillow stays below 13.

## 0.1.0 (unreleased)
First release.
- Claude Code plugin with `start`, `plan`, `build` and `revise` skills
- Script ingestion from .docx, .md, .txt, .pdf, .tex (others via pandoc), with automatic annotation detection
- Transcription with faster-whisper (CPU/CUDA) or WhisperX
- Alignment: last complete take, pickups, false starts, retake cues, slates, flubs, fillers (including untranscribed ones), pause shortening; ad-libs kept and flagged
- Editable PLAN.md with settings, audio edits, annotations, references and timed scenes
- References: locate and crop exam questions from PDFs and images; original (light-on-dark) or retyped modes
- Manim component library in the 3b1b dark style; `ManimaticScene` with word anchors and automatic layout/timing audits
- Parallel cached rendering, flagged-scene frame checks, frame-exact assembly
- Music bed with ducking, intro/outro stings, loudness normalisation to -14 LUFS
- SRT/VTT captions (optional burn-in), YouTube chapters (text + embedded)
- Draft mode with a text-to-speech scratch track
- Hold annotations (`[[hold 2s]]`, `[[pause]]`, `[[beat]]`): exact room-tone pauses that survive pause shortening, owned by the right scene, anchorable as `A###` / `A###.end`; honoured in draft mode
- `ManimaticCameraScene` (zoom/pan with `zoom_to`, `reset_camera`) and `Manimatic3DScene` (`set_view`, `move_view`, `orbit`, `fixed`), `Axes3D`, `MathSurface`; frame-aware audits (projected for 3D)
- OCR for scanned papers and photos (Tesseract, else RapidOCR), including word boxes for highlighting; images can be pointed at a question
- `clear_screen()` replaces the earlier `clear()` override (Manim uses `clear()` internally)
- README demo GIF and `tools/make_demo_gif.py`; CLAUDE.md for contributors

### From the first real test run (a 5-minute Banach–Tarski video, real recording, Whisper small.en)
Audio
- Room tone is taken from the quietest gap *between* transcribed words (with margins), not the quietest 1.5 s anywhere. Noise-gated recordings no longer get word tails ("ghost syllables") pasted into every shortened pause. Seamless looping with an equal-power crossfade.
- Audio check: `prepare` transcribes the edited voice and compares it with the script, reporting extra words, words in pauses or holds, repeats, leftover fillers and missing phrases with their video times (`check-audio --voice`, PLAN.md "Audio check").
- Level check after mixing: title and end cards, holds and long pauses must have sound; quiet stretches in the bed track are reported (`check-audio --levels`).
- The music bed now plays under the title and end cards when there's no sting there. Its level is measured (`[music] bed_level`, LU relative to the voice) instead of a fixed gain, and `bed_start` skips a quiet intro in the track. Misnamed music files are reported (`music_not_used`).

Plan and approval
- Cut, sound and annotation IDs are stable across re-runs (`.manimatic/ids.json`), and a PLAN.md tick whose quoted text no longer matches its ID is ignored with a warning instead of cutting something else.
- `cut` and `cuts set` refresh PLAN.md themselves; scene splits keep their IDs.
- An explicit "Approve this plan" checkbox in PLAN.md (`plan approve` / `plan unapprove`). The final render is locked until it's ticked; unapproved previews carry a "DRAFT · plan not approved" corner label; `status` shows a banner. The plan skill ends with an explicit approval question.
- Headings are confirmed automatically. Title and end card annotations belong to S00/S99.
- Spoken forms for "F2", "SO(3)", "SO3", "R3", `\mathbb{R}^3`.

Build
- Section-by-section build: lint, 480p render and checks per section while writing, and an early background final render once approved.
- Subagent mode for long videos (one Sonnet subagent per section, `reference/subagent-brief.md`) with a shared `scenes/common.py` contract.
- `--section` on `lint`, `render`, `check` and `sheet`; render workers default to one per CPU core.
- Contact sheets (`sheet`): one image per scene with a labelled frame at every animation beat.
- Glyph-level text overlap detection (fewer false alarms from bounding boxes); lint warns about anchors that occur more than once.
- `dot_cloud()` for 3D point sets (about 80× faster than `Dot3D`).
- `assemble --preview` implies 480p15; captions never exceed 42 characters per line.

Setup
- `constraints.txt` pins tested versions (PyAV below 19, which broke faster-whisper 1.2.1); `doctor` decodes a real clip, `doctor --deep` transcribes one with tiny.en.
- Small LaTeX option on macOS (BasicTeX + listed `tlmgr` packages), disk-space warning, a clear message on Python 3.9.
- CI: a real-transcription job (faster-whisper tiny.en) on a noise-gated clip and the demo, failing on ghost words in the edited voice.
