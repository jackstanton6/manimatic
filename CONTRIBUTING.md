# Contributing

Thanks for helping! Manimatic is a Claude Code plugin with a plain-Python core. Working with Claude Code? `CLAUDE.md` has the architecture, invariants and current status.

## Layout
- `skills/*/SKILL.md`: what Claude does at each stage. Keep them short; detail lives in `reference/`.
- `src/manimatic/`: the CLI (`cli.py`) and pipeline: `ingest/` (readers, annotations, spoken forms), `asr/`, `align.py`, `cut.py`, `draft.py`, `refs.py`, `plan.py`, `render.py`, `output.py`.
- `src/manimatic/lib/`: the scene library on ManimGX (components and `ManimaticScene`); `lib_ce/` is the same on Manim CE, for the fallback engine. `render_worker.py` renders scenes with either.
- `examples/demo/`: a small complete project, also used by tests.
- `tools/make_demo_audio.py`: regenerates the demo recording (needs espeak-ng). `tools/make_gated_clip.py` regenerates the noise-gated test clip in `tests/data/gated/`.

## Dev setup
```bash
uv venv -p 3.13 .venv && . .venv/bin/activate      # ManimGX needs Python 3.13+. Windows: .venv\Scripts\activate
uv pip install -e ".[dev,render,manim-ce,asr,tts,ocr]" -c constraints.txt   # manim-ce: the fallback engine (needs LaTeX)
pytest                      # the real-Whisper tests are skipped unless tiny.en can be downloaded
```
Run the CLI from the repo with `python3 mm.py ...`. Set `MANIMATIC_NO_VENV=1` to use your current environment instead of `~/.manimatic/venv`.

## Guidelines
- Everything must work on Windows, macOS and Linux. Use `pathlib`, no shell-specific commands, and call ffmpeg via argument lists.
- Keep the user in control: anything destructive to their audio (cuts) must be listed in PLAN.md and reversible.
- New components go in `lib/components.py` (and `lib_ce/components.py` while the fallback exists) with an entry in `reference/component-library.md`. `tests/test_render.py` renders them on both engines.
- Add a test for alignment or cut changes. Edge cases in real recordings are the hard part, so anonymised transcripts (`*.words.json`) that break things are very welcome as test fixtures.
- The `asr` CI job runs real faster-whisper (tiny.en) and fails on ghost words in the edited voice. If you change `cut.py` or `align.py`, make sure it stays green.
- Bump versions in `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `pyproject.toml` and `src/manimatic/__init__.py` together, and add a CHANGELOG entry.
