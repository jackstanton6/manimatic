---
name: build
description: Build a Manimatic video from its PLAN.md. Writes the Manim scene code timed to the narration section by section (in parallel subagents for long videos), renders and checks each section as it goes, starts the final 1080p60 render early, and assembles the video with music, captions and chapters. Use when a Manimatic plan is ready, or when the user asks to render, preview or export the video.
argument-hint: "[--preview | --final]"
allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/mm.py" *) Bash(py -3 "${CLAUDE_PLUGIN_ROOT}/mm.py" *)
---

# Manimatic: build

**How to run Manimatic.** In this skill, `MM` means `python3 "${CLAUDE_PLUGIN_ROOT}/mm.py"` (Windows: `py -3 "${CLAUDE_PLUGIN_ROOT}/mm.py"`). Run it inside the project folder or add `-C <folder>`.

**Ground rules (they apply all the way through):**
- The visuals come from PLAN.md. If the plan has to change (a scene split, a different idea), change PLAN.md first and run `MM plan sync`. Don't drift silently.
- Time everything to words with `wait_until`, `play_at` and `until=`. Never guess with `self.wait(n)`.
- Look at images only when you need them:
  - a contact sheet (`MM sheet`) for risky scenes;
  - the frames listed for flagged scenes;
  - anything the user asks about.

  Reading every frame of a long video wastes the user's tokens.
- The final render needs the plan approved. Previews don't.
- Scenes render with ManimGX, which has Manim CE's API (scene files start `from manimatic.lib import *`). Where it differs from Manim CE, and for text, follow "ManimGX notes" in `${CLAUDE_PLUGIN_ROOT}/reference/component-library.md`.

## 0. Start: check approval
Run `MM status`. If it starts with "⚠ PLAN NOT APPROVED", ask with AskUserQuestion (or in plain text if that's unavailable) **before writing any code**:
- **"Approve the plan"** → run `MM plan approve`.
- **"Preview first"** → carry on. Previews get a "DRAFT · plan not approved" corner label, and no final render starts.
- **"Back to the plan"** → stop and use `/manimatic:plan`.

## 1. Shared foundations (always the main agent)
1. Run `MM scenes new`. It scaffolds every missing scene file; the card scenes (S00, S99) come pre-filled.
2. Read the PLAN.md "Notes" and the Visual lines of all sections. Write `scenes/common.py` (`from common import *` in scenes) with everything that spans scenes:
   - the colour for each object or variable;
   - helper builders, such as a tree or a recurring diagram;
   - for each object that carries from one scene into the next, a function that builds it in its end state.

   Each scene renders separately, so the next scene rebuilds carried state from these functions. This is the shared contract that makes the video read as one piece. Write it *before* any scene.
3. Count the voice scenes. With **more than about 12** and the Agent tool available, use subagent mode (§2b). Otherwise write them yourself (§2a).

## 2a. Write, render and check section by section (single agent)
Do one section at a time, rendering as you go so mistakes surface early:
1. For each scene in the section, read its file. The docstring lists every line and word with its time from the scene start, plus annotations, references and the Visual plan. Write `construct()` using:
   - `${CLAUDE_PLUGIN_ROOT}/reference/component-library.md`: the API (scene classes, anchors, cards, references, maths, camera and 3D, `dot_cloud`);
   - `${CLAUDE_PLUGIN_ROOT}/reference/visual-style.md`: the conventions every scene follows, annotated or not.

   Pick the base class per scene: `ManimaticScene` (default), `ManimaticCameraScene` (zoom or pan) or `Manimatic3DScene` (3D). A hold (`hold 2s`) is a pause with no narration, so put a visual in it: `play_at("A007", ..., until="A007.end")`.
2. Run `MM lint --section S03`. It checks anchors and type-checks the scene code (a misspelt keyword or method is an error). Fix every problem, and every "occurs N times" warning (use `"word#2"` or `"L0012:word"`).
3. Run `MM render -q 480p15 --section S03`, then `MM check --section S03`. For each flagged scene, Read its listed frames, fix the code and re-render just that scene. "Late" usually means an animation is too long for the gap before its word: start earlier (`"word-0.8"`) or use `play_at("earlier", ..., until="word")`.
4. Review the risky scenes (3D, camera moves, big transforms, dense layouts) with `MM sheet S03.2`. That's one image with a frame at every beat. Skip sheets for simple scenes that passed the checks.
5. **Start the final render early.** If the plan is approved and the section is clean, run `MM render -q 1080p60 --section S03` in the background (`run_in_background`) and move on to the next section. Revisions re-render only the scenes they touch, so most of the final is done by the time the user signs off.

## 2b. Subagent mode (long videos)
After §1, start one subagent per section with the Agent tool, **model: sonnet**, several at once, using the brief in `${CLAUDE_PLUGIN_ROOT}/reference/subagent-brief.md`. Fill in the project folder, the section id, the `MM` command and any section-specific notes.
- Each subagent writes its section's scenes, loops through lint, a 480p render and `check` until clean, and replies in one or two lines: `S03.1–S03.5 rendered, 0 flags; deviations from plan: …`.
- **You never read their frames or logs.** Collect the reports. If a subagent got stuck, take that section yourself.
- Don't use Haiku for scene code. Pitfalls (3D overlays, empty TeX parts, ambiguous anchors) need the stronger model.
- When all sections report clean, start the early final renders (§2a step 5) and continue with §3.

## 3. Preview and review
1. Run `MM build --preview`. It renders whatever is missing at 480p15, runs the checks, mixes the audio and **checks the mix levels** (silent cards, holds or pauses where music is expected), then writes `output/<title>.preview.mp4`.
2. Fix what's flagged (`MM check`, `audio_issues` in the result, `MM status`), then rebuild.
3. If a render fails, read the end of `.manimatic/logs/<id>.480p15.log`. The usual causes are LaTeX that ManimGX can't convert (`TypstError`) and Python mistakes; see `${CLAUDE_PLUGIN_ROOT}/reference/troubleshooting.md`.
4. Give the user the preview. Their notes go through `/manimatic:revise`.

## 4. Final render
Do this once the user is happy with the preview and the plan is approved.
1. Run `MM build`. The default is 1080p60; use `-q 1440p60` or `-q 4k` if asked. Scenes already rendered early are reused. Run it in the background on long videos and check in on it.
2. Report the deliverables in `output/`:
   - `<title>.mp4`: video with mixed audio and embedded chapters;
   - `<title>.srt` and `.vtt`: captions;
   - `<title>.chapters.txt`: for the YouTube description;
   - `<title>.captioned.mp4`: only when "captions burned in" is on.
