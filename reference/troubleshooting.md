# Troubleshooting

## Setup
| Symptom | Fix |
|---|---|
| `doctor` says ffmpeg is missing | Windows: `winget install Gyan.FFmpeg`, then open a new terminal. macOS: `brew install ffmpeg`. Linux: `sudo apt install ffmpeg` |
| "Managed environment (Python 3.13+)" fails | ManimGX needs Python 3.13. `mm.py doctor --install` creates the environment with it (an older environment is moved to `~/.manimatic/venv.old`). If no Python 3.13 is found, install `uv` (it fetches Python by itself) and run it again: Windows `winget install astral-sh.uv`, macOS `brew install uv`, Linux `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| "Rendering on a GPU" unticked | ManimGX found no GPU driver and draws on the CPU (correct, just slow). Update the graphics driver; on Linux install the Vulkan driver (`sudo apt install mesa-vulkan-drivers`, or NVIDIA's driver). Headless servers and CI have no GPU: expect Manim CE-like speed there |
| ManimGX can't run on this machine | Use the Manim CE fallback: `mm.py doctor --install --with-manim-ce`, install LaTeX (below), and set `[render] engine = "manim"` in `manimatic.toml` |
| LaTeX or dvisvgm is missing (Manim CE fallback only) | Windows: install MiKTeX and allow on-the-fly package installs. macOS (small, ~400 MB): `brew install --cask basictex`, then `sudo tlmgr install standalone preview doublestroke ms setspace rsfs relsize ragged2e fundus-calligra microtype wasysym physics dvisvgm jknapltx wasy cm-super babel-english`. Linux: `sudo apt install texlive texlive-latex-extra cm-super dvisvgm` |
| Manim CE fallback: `ValueError: Invalid mode for data type` on a scene with an image | Pillow 13 breaks images in Manim CE 0.22. `mm.py doctor --install --with-manim-ce` installs Pillow 12 |
| `doctor` warns about disk space | Renders and the Whisper models need a few GB. Free some space |
| "Transcription can decode audio" fails, or `open() got an unexpected keyword argument 'metadata_errors'` | The installed PyAV is too new for faster-whisper. Run `mm.py doctor --install` again: it applies `constraints.txt` (PyAV below 19) |
| "Manimatic needs Python 3.10 or newer" | macOS's built-in `python3` is 3.9. Install a newer Python (`brew install python@3.13`, or python.org) and run `mm.py` with it |
| You want proof transcription works before recording | `mm.py doctor --deep` downloads the tiny model and transcribes a sample clip |
| Manim CE (fallback) won't install on Linux or macOS (pycairo or manimpango build errors) | Linux: `sudo apt install build-essential python3-dev libcairo2-dev libpango1.0-dev pkg-config`. macOS: `brew install cairo pango pkg-config`. Then run `mm.py doctor --install --with-manim-ce` again |
| GPU not used for transcription | `mm.py doctor --install --gpu cuda`. This needs an NVIDIA driver supporting CUDA 12. Check with `nvidia-smi` |
| `python3` isn't found on Windows | Use `py -3 mm.py ...` |
| You want to start over | Delete `~/.manimatic/venv` and run `mm.py doctor --install` |

## Transcription and cuts
| Symptom | Fix |
|---|---|
| A line is "missing" but was said | The script's maths is probably spoken differently. Run `mm.py spoken L0012 "what you actually said"`, then `mm.py align` and `mm.py cut` |
| A retake was kept, or the wrong take was used | Check `.manimatic/cuts.md`. Restore or cut individual items with `mm.py cuts set C007 keep` or `cut` |
| An "um" survived | Whisper sometimes drops ums from its transcript. Untranscribed sounds in pauses are cut automatically. Inside a phrase with no pause, they may remain. Try `asr_model = "medium.en"` or the WhisperX backend |
| An ad-lib was cut | Ad-libs are only cut when ticked in PLAN.md, or when `[cuts] adlibs = "cut"` is set. A phrase that repeats script words can look like a false start: untick it in PLAN.md |
| Cuts sound abrupt | Raise `[cuts] pad_ms` (default 60) and `crossfade_ms` (default 15) |
| Pacing feels rushed | Raise `[cuts] sentence_pause`, `paragraph_pause` and `max_pause` |
| The audio check reports an "extra word" or a "sound in a hold" | A fragment of a cut word was left in, usually where a cut meets a pause. Look up the time in `.manimatic/cuts.md` and adjust the decision there with `mm.py cuts set`. Pauses are filled with room tone taken from the quietest gap *between* words, so this should be rare; report it if it isn't |
| The audio check reports a "repeated word" or "missing words" | Two takes overlap, or a take was cut that shouldn't have been. `cuts.md` lists the takes; `mm.py cuts set C00x keep\|cut` fixes it |
| A tick in PLAN.md was ignored with a warning | The item's ID now points at different text (the audio or script changed). Tick the item again where it now appears |
| Transcription is slow | On CPU the default is `small.en`. A 2-hour recording takes a while, but it's cached, so this only happens once per file |

## References
| Symptom | Fix |
|---|---|
| Question not found in a scanned paper | Scans are read with OCR. Check `mm.py doctor` lists an OCR engine. Tesseract (`winget install UB-Mannheim.TesseractOCR`, `brew install tesseract`, `sudo apt install tesseract-ocr`) is more accurate than the built-in RapidOCR. If the label still isn't read, use `mm.py ref page file.pdf N` and `mm.py ref set R01 --page N --crop x0,y0,x1,y1` |
| `word_box` misses a word in a scanned paper | OCR sometimes merges words ("Question4"). Use `card.region(...)` with fractions read off `mm.py ref page` instead |
| Force one OCR engine | `[references] ocr = "tesseract"` or `"rapidocr"` in `manimatic.toml` (`"off"` disables OCR) |
| The crop cuts off a diagram | Enlarge it with `--crop`. Values are fractions of the page, with y measured from the top |
| The dark style looks odd for a photo | Use `scene_reference(self, "R01", style="paper")` |

## Rendering
| Symptom | Fix |
|---|---|
| `TypstError: unknown command: \parbox` (or another `\command`) | ManimGX converts LaTeX to Typst, and some LaTeX doesn't convert: packages, `\def`/`\newcommand`, `\parbox`, text accents like `\"o`. Put prose in `Words()`/`TextBlock()` (plain text, `$maths$` inline) and write maths without custom macros |
| Text shows "amp" or "hash" where `&` or `#` should be | It went through `Tex()` with LaTeX escapes. Use `Words("Profit & loss")`: no escaping needed |
| Lint: `Argument \`…\` does not match any known parameter` or `has no attribute` | A misspelt keyword or method in the scene code. The line number is in the message |
| Lint warning: `No overload … matches arguments` | Often a method that can return nothing, like `get_part_by_tex`. Index the `{{ }}` parts instead (`eq[2]`). Warnings don't block the render |
| `LaTeX error` in the log (Manim CE fallback) | Text with special characters must go through `Words()`/`TextBlock()`. Inside `MathTex` use valid maths mode. `\text{}` needs words, and `%` must be `\%` |
| `'…' object has no attribute 'set_width'` | ManimGX has no `set_width`/`set_height`: use `scale_to_fit_width`/`scale_to_fit_height` |
| A render failed with "the render process crashed" | Several scenes render in one process; when one crashes the process, Manimatic restarts it for the rest. Read `.manimatic/logs/<scene>.<quality>.log`. If it's a GPU driver crash, try `[render] jobs = 1` |
| `Only values of type VMobject can be added` | Images (ImageMobject) must go in a `Group`, not a `VGroup` |
| Anchor not found (from lint) | Anchors use the *spoken* form: "sixty", not "60". The scene's docstring lists the exact words. Run `mm.py scenes refresh` after a re-time |
| A scene is flagged as "late" | An animation runs past the word it's anchored to. Shorten `run_time`, start earlier (`"word-0.8"`), or use `play_at(..., until="word")`. A `run_time=self.time_until(...)` written inside `play_at(...)` is measured *before* the wait, which is a common cause |
| A 3D scene is flagged off-screen | 3D objects are checked as the camera sees them. Shift the plot (`.shift(2 * IN)` moves it down on screen), shrink `x_length`/`z_length`, or zoom out (`set_view(..., zoom=0.8)`) |
| Zoomed-in camera scene: nothing flagged | Expected: the off-screen check only runs while the camera is at its home view |
| A pause I wanted was shortened | Mark it with `[[hold 2s]]` in the script, then `mm.py prepare` |
| A render is very slow | Check `mm.py doctor`: "Rendering on a GPU" unticked means ManimGX is drawing on the CPU. Previews render at 480p15. In 3D, use `self.dot_cloud(points)` rather than hundreds of `Dot3D`. `[render] jobs` sets how many render processes run at once (automatic by default) |
| A scene is flagged for overlapping text | Two pieces of text share glyphs on screen. Move one, or fade the first out before the second arrives |
| Lint warns an anchor "occurs N times" | A plain word anchors to its first occurrence in the scene. Use `"word#2"` for a later one, or `"L0012:word"` |
| The video drifts from the audio | It can't: each scene is trimmed or padded to its exact frame count when assembled. If something *looks* off, check the scene's anchors |

## Music and mix
| Symptom | Fix |
|---|---|
| The title or end card is silent | Without an `intro.*`/`outro.*` sting, the bed plays under the cards. If the bed track itself starts quietly, set `[music] bed_start` to skip its intro. The level check after `assemble` lists silent stretches |
| The music is too loud or too quiet | Change `[music] bed_level` (LU relative to the voice; default -20, so -16 is louder and -24 quieter). Then `mm.py assemble`; no re-render needed |
| The level check says the bed has quiet stretches | The track itself goes quiet there. Pick another `bed_start`, or another track |
| My music file isn't used | Name it `bed.*`, `intro.*` or `outro.*`. `mm.py status` lists unused files as `music_not_used` |

## Approval
| Symptom | Fix |
|---|---|
| "Plan not approved: final render locked" | Tick "Approve this plan" in PLAN.md and run `mm.py plan sync`, or run `mm.py plan approve`. Previews work without approval |
| A "DRAFT · plan not approved" label on the video | It's a preview of an unapproved plan. Approve the plan and build again |
