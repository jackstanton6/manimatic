# Visual conventions (3b1b dark)

These rules apply to every scene. Annotated stretches follow what the annotation asks for, *in this style*. Unannotated stretches get visuals Claude chooses, following the same rules, so the whole video reads as one piece. When annotations already set a pattern (say, every new term is written in yellow), continue that pattern in unannotated scenes.

## The look
- A black background with white text. Text is set in New Computer Modern (the LaTeX font, via `Words`/`TextBlock`), never a sans-serif font.
- Colour carries meaning, so use it consistently for the whole video:
  - `ACCENT` (yellow) is "look here now".
  - Each variable or object keeps its colour throughout. The first is `PRIMARY` (blue) and the second is `SECONDARY` (teal).
  - Never use colour as decoration.
- Use few objects, generous space, and centred composition. Keep everything inside `SAFE_W` × `SAFE_H`.
- Don't use logos, stock imagery, emoji or drop shadows.
- Don't copy 3Blue1Brown's characters, intro or branding. The style is the goal, not the brand.

## Timing: visuals follow the voice
- Every visual change lands on the word it illustrates. Use `wait_until("word")` or `play_at`, never guessed `wait(n)` values.
- An animation should *finish* as the key word is said. For a one-second write that should complete on "five", start at `"five-0.8"`, or use `self.play_at("three", Write(eq), until="five")`.
- Use `FAST` (0.6 s) for small changes, `NORMAL` (1 s) for most things and `SLOW` (1.6 s) for big reveals. If several things appear at once, stagger them with `LaggedStart`.
- Leave about a second of stillness after a big reveal. Don't animate continuously.
- No scene should be static for more than about 6 seconds of narration. Highlight the term being discussed, or add the next element.
- Holds (`[[hold 2s]]`) are moments with no narration, so they belong to the picture. Put the big reveal in them (`play_at("A007", ..., until="A007.end")`). Don't leave a hold static.

## Camera and 3D
- Use a moving camera (`ManimaticCameraScene`) when one detail of a larger picture needs attention and the context matters: zoom in, then zoom back out. Don't use it as a substitute for laying things out.
- Use 3D (`Manimatic3DScene`) only when the third dimension carries the idea: surfaces, solids, vectors in space. Keep labels and equations screen-fixed (`self.fixed`) so they stay readable.
- Camera moves are slow and smooth (`SLOW` or longer). A gentle `orbit(0.1–0.2)` during narration helps show depth; stop it before pointing at something specific.
- For point sets use `self.dot_cloud(points)` (one GPU point cloud), never hundreds of `Dot3D`. Without a GPU, 3D renders slowly: keep surface `resolution` modest.

## Building understanding
- Show the object before you name it. Introduce symbols only once the viewer has seen what they stand for.
- Keep context on screen: transform the old into the new (`TransformMatchingTex`, `ReplacementTransform`) rather than clearing and redrawing.
- When the narration says "this", "here" or "notice", there must be something to look at. Use an `emphasize`, `highlight_box`, `underline` or `Callout`.
- For derivations, use one line at a time. Morph matching terms, and colour the term that changes.
- Number lines, axes and planes are context, so draw them in `MUTED` or `FAINT`. The data on them goes in colour.

## Scene transitions
- Within a section, carry objects across scenes where you can: start the next scene with the last state of the previous one. Each scene renders on its own, so build carried objects with functions in `scenes/common.py` that return them in their end state, and call the same function at the start of the next scene.
- At a new section, clear the screen (`self.clear_screen()`). Optionally show a `SectionCard` for 2 to 3 seconds when the narration pauses, or keep a `TitleBar` in the corner.
- Between unrelated scenes, fade out with `self.clear_screen(0.5)` just before the scene ends.

## References (exam questions etc.)
- `original` mode: show the cropped question with `scene_reference(self, "R01")` (the dark style by default), with its caption. Point at the parts being discussed (highlight boxes over regions of `card.image`).
- `retype` mode: rebuild the question with `QuestionBlock` or `Words`/`Eq`, so parts can be revealed, highlighted or transformed line by line. Keep the wording exactly as in `.manimatic/refs/Rxx.txt`.
- Keep a reference on screen while the narration discusses it. Shrink it and move it to a corner (`.animate.scale(0.5).to_corner(UR)`) if the working needs space.

## Cards
- **Title card (S00):** the title, a thin rule and a subtitle in `MUTED`, timed to the intro sting.
- **End card (S99):** the end title and its lines, timed to the outro sting.
- **Quotes:** `QuoteCard`, held while the quote is read.
