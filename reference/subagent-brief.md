# Subagent brief: build one section

The build skill uses this for long videos: one Sonnet subagent per section, started after the main agent has written `scenes/common.py`. Copy the brief below into the Agent tool's prompt and fill in the `<…>` parts. The subagent starts with no context, so the brief has to stand on its own.

---

You're building one section of a Manim video with Manimatic. Work only on section **<S03>** in the project at **<absolute project path>**. The command is `<python3 "/path/to/plugin/mm.py">` (called `MM` below), always with `-C "<project path>"`.

**Read first:**
1. `<plugin>/reference/component-library.md`: the scene API (anchors, components, camera and 3D).
2. `<plugin>/reference/visual-style.md`: the house style.
3. `<project>/scenes/common.py`: the shared colours, helpers and carried-state builders. **Use them; don't redefine colours or helpers.** If you need a new shared helper, put it in your own scene file and mention it in your report.
4. The PLAN.md section `## <S03> · …` and its Notes, for what each scene should show.

**Then, for each scene file in this section (`scenes/s03_*.py`):**
1. Read the docstring at the top. It lists every word with its time, the annotations (including holds), references and the plan. Write `construct()`.
   - Time everything to words: `wait_until`, `play_at`, `until=`. Never use `self.wait(n)` guesses.
   - A plain word anchor resolves to its first occurrence in the scene. Use `"word#2"` or `"L0012:word"` for a later one.
   - Start each scene from the end state of the previous one using the builders in `common.py`.
   - In 3D, pin text with `self.fixed(...)`. Use `self.dot_cloud(...)` for many points, never hundreds of `Dot3D`.
2. When all the section's scenes are written, loop until clean:
   - `MM lint --section <S03>`: fix every problem and every ambiguous-anchor warning.
   - `MM render -q 480p15 --section <S03>`: on a failure, read the end of `.manimatic/logs/<id>.480p15.log`.
   - `MM check --section <S03>`: for each flagged scene, Read the listed frame images, fix it, and re-render that scene only (`--scenes S03.2`).
3. For 3D, camera-move or dense scenes, look at `MM sheet <id>` once and fix anything that's clearly wrong.

**Don't** edit PLAN.md, other sections' scenes, `common.py` or anything in `.manimatic/`, and don't run `build` or `assemble`.

**Reply with one or two lines only**, for example:
`S03.1–S03.5 rendered at 480p, 0 flags. Deviations from plan: S03.3 shows the tree from the left (more room for the label).`
If you couldn't get a scene clean, say which one and what's wrong, in one line.
