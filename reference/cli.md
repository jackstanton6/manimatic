# Command reference

Run commands as `python3 mm.py <command>` (on Windows, `py -3 mm.py <command>`) from inside a project folder, or add `-C <folder>`.

## Setup
| Command | What it does |
|---|---|
| `doctor [--deep]` | Checks Python, ffmpeg, disk space, the managed environment (Python 3.13), ManimGX and the GPU it renders on, the type checker, and transcription, including decoding a real audio clip. `--deep` also downloads the tiny Whisper model and transcribes a sample |
| `doctor --install [--gpu cuda] [--whisperx] [--no-ocr] [--with-manim-ce] [--python P]` | Creates or updates `~/.manimatic/venv` with Python 3.13 (`MANIMATIC_HOME` overrides the location; an older environment is recreated). Installs the tested versions in `constraints.txt`. Includes RapidOCR for scanned references unless `--no-ocr` is given. `--with-manim-ce` adds the Manim CE fallback engine |
| `new <folder> [--title T]` | Creates a project |
| `status` | Shows what's done and the next step. Start every session with this |

## Planning
| Command | What it does |
|---|---|
| `prepare [--draft] [--force-transcribe] [--no-verify]` | Runs ingest, then transcribe, align and cut (or a draft voice), then the audio check of the edited voice, then refs, then PLAN.md (init, or a re-time). `--no-verify` skips the audio check |
| `ingest` | Reads the script and writes `.manimatic/script.json` and `script.md` |
| `annot list` / `annot set A012 annotation\|spoken` | Lists annotations, or flips one |
| `spoken L0012 "said form"` / `spoken L0012 --clear` | Overrides how a line is spoken (used for matching the audio) |
| `transcribe [--backend faster-whisper\|whisperx\|mock] [--model M] [--device cuda\|cpu] [--force]` | Transcribes the audio (cached) |
| `align` | Finds takes, retakes, flubs, fillers and ad-libs |
| `cut` | Writes `output/voice_edit.wav`, `.manimatic/timeline.json` and `cuts.md`, and refreshes PLAN.md |
| `cuts list` / `cuts set C004 [C005…] cut\|keep\|default` | Lists cut decisions, or changes them (re-cuts and refreshes PLAN.md). IDs are stable across re-runs |
| `check-audio [--voice] [--levels]` | Transcribes the edited voice and compares it with the script (ghost words, repeats, leftover fillers, missing words), and measures the mix on the cards, holds and pauses |
| `draft [--tts auto\|pyttsx3\|silent]` | Draft voice from the script |
| `refs` | Locates and crops referenced questions |
| `ref page <file> <n>` | Page image with a 10% grid, for choosing crops |
| `ref set R01 [--file F] [--page N] [--question 4 --part b] [--crop x0,y0,x1,y1] [--mode original\|retype] [--caption "…"]` | Fixes a reference |
| `plan init [--force]` / `plan sync` / `plan show` | PLAN.md lifecycle |
| `plan approve` / `plan unapprove` | Ticks or unticks the "Approve this plan" box. The final render is locked until it's ticked |

## Building
| Command | What it does |
|---|---|
| `scenes new [IDs] [--force]` | Scaffolds scene files |
| `scenes refresh` | Rewrites the timing docstring at the top of each scene file |
| `scenes info S01.2 …` | Prints a scene's words, times, annotations and plan |
| `lint [IDs] [--section S03]` | Checks that scene classes exist and anchors resolve, and type-checks the scene code (ManimGX engine). Warns about anchors that occur more than once in a scene |
| `render [-q 480p15\|1080p60\|1440p60\|4k] [--scenes …] [--section …] [-j N] [--force]` | Cached rendering. Each render process renders several scenes in turn; `-j` sets how many processes run at once |
| `check [-q Q] [--scenes …] [--section …]` | Automatic checks (off-screen, overlapping text, late animations). Writes frames for flagged scenes only |
| `sheet [IDs] [--section …] [-q Q]` | One contact-sheet image per scene, with a frame at every animation beat, labelled with its time and words. Written to `.manimatic/sheets/` |
| `frames S01.2 1.5 4.0 [-q Q]` | Extracts specific frames |
| `mix` | Voice plus music (ducked), stings and loudness normalisation. The bed's level is measured against the voice |
| `assemble [-q Q] [--burn/--no-burn] [--preview]` | Writes the video, captions and chapters to `output/`, then checks the mix levels. `--preview` implies 480p15 |
| `build [--preview] [-q Q] [--burn] [--force]` | lint, render, check and assemble in one go. The final build needs the plan approved (`--force` overrides). Previews of an unapproved plan carry a "DRAFT" corner label |

## Revising
| Command | What it does |
|---|---|
| `locate 2:13` | Shows the scene, its file, the time within it and the words being said at that point in the video |
| `log "message"` | Appends a line to `REVISIONS.md` |

## Music settings (`manimatic.toml`, `[music]`)
| Setting | What it does |
|---|---|
| `bed_level` (default `-20`) | Loudness of the bed relative to the voice, in LU. The bed is measured, so this works whatever the track's own level |
| `bed_level_db` | A fixed gain in dB instead of the measured level. Leave it commented out unless you need it |
| `bed_start` (seconds) | Where in the bed track to start. Use it to skip a quiet intro |
| `duck_db` | How far the bed drops under speech |

Music files must be named `bed.*`, `intro.*` and `outro.*`. Others are ignored and listed by `status` as `music_not_used`.

## Render settings (`manimatic.toml`, `[render]`)
| Setting | What it does |
|---|---|
| `engine` (default `"manimgx"`) | `"manimgx"` renders on the GPU with ManimGX. `"manim"` uses Manim CE instead (a fallback; needs `doctor --install --with-manim-ce` and LaTeX). The same scene files work with both |
| `jobs` (default `0`, automatic) | Render processes at once. Automatic is up to 4 for ManimGX (half the CPU cores), one per core for Manim CE |

