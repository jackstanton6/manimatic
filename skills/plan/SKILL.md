---
name: plan
description: Plan a Manimatic video. Transcribes and edits the voice recording (keeps the last take of each line, cuts flubs, ums and long pauses, flags ad-libs), checks the edited audio against the script, finds referenced exam questions, and writes PLAN.md with timed scenes and a visual plan, then asks the user to approve it. Use after the Manimatic project has a script (and ideally audio), or when the user asks to (re)plan, re-time or re-cut a Manimatic video.
argument-hint: "[--draft]"
allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/mm.py" *) Bash(py -3 "${CLAUDE_PLUGIN_ROOT}/mm.py" *)
---

# Manimatic: plan

**How to run Manimatic.** In this skill, `MM` means `python3 "${CLAUDE_PLUGIN_ROOT}/mm.py"` (Windows: `py -3 "${CLAUDE_PLUGIN_ROOT}/mm.py"`). Run it inside the project folder or add `-C <folder>`. Always start with `MM status`.

**Do the whole plan in one pass.** Prepare, check the machine's work, fix what you can, and draft every Visual line. Then present a single review that ends with the approval question (step 5). Don't report back after each step.

**Ground rules (they apply all the way through):**
- PLAN.md is the shared source of truth. The user may edit it at any time, so re-read it before acting on it, and run `MM plan sync` after any edit, yours or theirs.
- Never hand-edit the regenerated lines in PLAN.md: lines starting with `> L`, `- Annotations:` or `- References:`. Never hand-edit anything in `.manimatic/` either; use the `MM` commands.
- Ad-libs are kept unless the user says otherwise. Decide each one with them; don't cut ad-libs on your own judgement.
- The final render is locked until the plan is approved: the "Approve this plan" box in PLAN.md is ticked, or `MM plan approve` has been run. Only the user can approve.

## 1. Prepare
Run `MM prepare`, or `MM prepare --draft` if there's no recording yet. In order, it:
1. ingests the script;
2. transcribes the audio (cached);
3. aligns it with the script and cuts it;
4. **transcribes the edited voice and compares it with the script** (the audio check);
5. finds references;
6. writes or re-times PLAN.md.

Re-running it after the script, audio or references change is safe: your PLAN.md edits are kept.

## 2. Check the machine's work (don't stop to report yet)
1. **Script splitting:** read `.manimatic/script.md`.
   - If a direction was read as spoken text, or the other way round, run `MM annot set A012 annotation|spoken`.
   - If a line is incomplete or missing although it was said, the maths was usually spoken differently from how it's written. Run `MM spoken L0012 "how it was said"`, then `MM align` and `MM cut`.
   - `prepare` already maps symbols Whisper writes as "F2", "SO3" or "R3" to their spoken forms.
2. **Audio:**
   - Read the "Audio check" section of PLAN.md, or `MM status`. Every ghost word, repeat, leftover filler or missing phrase is listed with its time. Find the cause in `.manimatic/cuts.md` and fix it with `MM cuts set <ID> cut|keep`.
   - Be suspicious of a "retake" that's really new content, and of a missing line that was actually said.
   - `MM cut` and `MM cuts set` refresh PLAN.md themselves. Cut IDs are stable, and a tick whose text no longer matches its ID is ignored with a warning.
3. **Music:** if `MM status` lists `music_not_used`, those files are misnamed. Tell the user they should be named `bed.*`, `intro.*` or `outro.*`.
4. **References:** for every `Rxx`, open `.manimatic/refs/Rxx.png` with Read and confirm it's exactly the requested question.
   - Scanned papers and photos are read with OCR (the method says "OCR"), and their `.txt` can contain misreadings.
   - If a crop is wrong, run `MM ref page <file> <page>`, view the page with its grid, then run `MM ref set Rxx --page N --crop x0,y0,x1,y1`.
   - If a reference wasn't found, add it to the review as a question for the user.

## 3. Write the visual plan
Fill in the `- Visual:` line of **every** scene in PLAN.md, the unannotated ones included, following `${CLAUDE_PLUGIN_ROOT}/reference/visual-style.md`. Be concrete enough that someone else could build it, and make the timed beats sub-bullets:
```
### S01.2 · L0003–L0004  [...]
> L0003 ...
- Visual: number line 1–30 in MUTED; primes pop in as yellow dots.
  - at "sixty": the dots appear (LaggedStart)
  - at "works": the label "primes up to 30" fades in above
```
- **Scenes:** each scene is a `### Sxx.y · L0012` heading and runs from that line to the next scene's first line. Split or merge scenes by adding or removing headings; new ids just need to be unique. Aim for 5–30 s per scene, and put a boundary wherever the picture changes completely.
- **Sections** (`## S02 · Title`) become YouTube chapters. Headings in the script are taken as section titles automatically.
- **Cards:** S00 is the title card and S99 the end card. `[[title card: …]]` and `[[end card: …]]` in the script belong to them, not to the first or last scene. Edit their Visual lines and the Settings (title, subtitle, end card title and lines).
- **Shared look:** in the "Notes" section, write down the decisions that span the whole video: one colour per object or variable, recurring layouts, and which objects carry from scene to scene. The build follows them (and so do subagents, for long videos).
- **Long videos:** work one section at a time. `MM scenes info S03.2` prints a single scene's words and times without reading everything.

Then run `MM plan sync`.

## 4. One review message
Keep it short. Include:
- total length, number of scenes and sections;
- **every ad-lib**, quoted, and whether it's currently kept;
- anything the audio check still flags, and lines that are incomplete, missing or using a pickup take;
- spots where a pause would help a visual land, suggesting a `[[hold 2s]]` (the edit otherwise shortens long pauses);
- low-confidence annotations (italics, parentheses, highlights) to confirm;
- the reference crops (show the images);
- one line per section describing the visuals;
- where to listen to the edit (`output/voice_edit.wav`), and that they can edit PLAN.md directly.

## 5. Ask for approval, explicitly
End with a multiple-choice question using AskUserQuestion (if it isn't available, ask the same thing in plain text):
- **"Approve the plan"** → run `MM plan approve`, then continue with `/manimatic:build`.
- **"I have changes"** → apply them: ticks, `MM cuts set …`, Visual lines, settings. Then run `MM plan sync`, summarise what changed, and ask again.
- **"Preview first"** → continue with `/manimatic:build` for a preview only. Previews of an unapproved plan carry a "DRAFT · plan not approved" corner label, and the final render stays locked.

Never treat "looks good" about something else as approval of the plan. Ask.
