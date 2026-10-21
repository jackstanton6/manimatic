---
name: revise
description: Apply the user's feedback on a Manimatic video preview or final render, such as "at 2:13 the equation is too small", "keep that ad-lib", "I hear a repeated word", re-recorded lines, or changes to music, captions or titles. Changes only what's needed and re-renders only affected scenes. Use when the user reviews a Manimatic video and asks for changes.
argument-hint: "[feedback]"
allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/mm.py" *) Bash(py -3 "${CLAUDE_PLUGIN_ROOT}/mm.py" *)
---

# Manimatic: revise

**How to run Manimatic.** In this skill, `MM` means `python3 "${CLAUDE_PLUGIN_ROOT}/mm.py"` (Windows: `py -3 "${CLAUDE_PLUGIN_ROOT}/mm.py"`). Run it inside the project folder or add `-C <folder>`. Start with `MM status`, and read `REVISIONS.md` if it exists.

## 1. Find where each note applies
- **A timestamped note:** run `MM locate 2:13`. It returns the scene, its file, the time within the scene and the words being said. Previews and the final video share the same timing.
- **A note without a timestamp** ("the factor tree looks cramped"): find the scene in PLAN.md's overview.
- **A sound problem** ("I hear 'pieces' twice", "the intro is silent"): run `MM check-audio`. It transcribes the edited voice against the script and measures the mix on the cards, holds and pauses, and usually names the cause and the time.

## 2. Make the change at the right level
| Kind of feedback | What to do |
|---|---|
| A visual detail in one scene | Edit that scene's file, then run `MM lint` |
| A different visual idea, or moving or splitting a scene | Edit PLAN.md (Visual lines, scene headings), then run `MM plan sync`, `MM scenes refresh` (updates the timing headers in the scene files) and `MM lint` |
| Keep or cut an ad-lib or a retake, or restore a filler | `MM cuts set C004 keep` (or `cut`, or `default`). It re-cuts and refreshes PLAN.md itself. Or tick/untick the item in PLAN.md and run `MM plan sync`. Scenes re-time automatically because they're anchored to words |
| A ghost word, repeat or missing words in the voice | `MM check-audio --voice` gives the time; `.manimatic/cuts.md` lists the edits around it. Fix with `MM cuts set …`, then check again |
| Re-recorded lines | Add the new file to `audio/` with a name that sorts last (e.g. `zz-pickups.wav`), then run `MM prepare`. The last complete take of each line wins, wherever it is |
| The script changed | Edit the script file, then run `MM prepare`. Scenes are re-anchored to their first lines, and anchors that no longer exist show up in `MM lint` |
| Title, subtitle, end card, burned-in captions, voice processing, quality | Edit the PLAN.md Settings, then run `MM plan sync` |
| Music | Replace files in `music/` (`bed.*`, `intro.*`, `outro.*`), then run `MM assemble`. No re-render needed |
| Music too loud or too quiet, or silent somewhere | `[music] bed_level` (LU relative to the voice, default -20), `duck_db`, or `bed_start` to skip a quiet intro in the track, all in `manimatic.toml`. Then run `MM assemble` and read its level check |
| A wrong reference crop | Run `MM ref page <file> <n>`, then `MM ref set Rxx --page N --crop …`, then `MM plan sync`, then re-render that scene |

Voice processing (light noise reduction, EQ and compression) stays off unless the user asks for it.

## 3. Re-render and report
1. Run `MM build --preview`, or `MM build` if they were reviewing the final. Only changed scenes re-render. For a scene whose look changed, check `MM sheet <id>` before showing the user.
2. Check any newly flagged scenes and audio issues as in the build skill.
3. Log every change: `MM log "2:13 S01.2: equation enlarged and moved up (user note)"`.
4. Reply with a short list of what changed, with timestamps, and the path of the new video.
