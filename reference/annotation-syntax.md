# Writing a script for Manimatic

Write the script the way you'll say it. Anything that's a *direction* rather than narration is an annotation. Manimatic finds annotations automatically and lists every guess in PLAN.md for you to confirm.

## Explicit annotations (always treated as directions)
```
Every whole number can be built from primes. [[equation: $60 = 2^2 \cdot 3 \cdot 5$ @ "built"]]
```
- `[[ ... ]]` anywhere is an annotation. It triggers at the next word, or at the word given with `@ "word"`.
- If a paragraph is *only* an annotation, it triggers at the start of the next spoken line.

## Detected automatically (you confirm them in PLAN.md)
| You write | Detected as |
|---|---|
| `Visual: …`, `Show: …`, `Title card: …`, `Section: …`, `Equation: …`, `Quote: …`, `Diagram: …`, `Ref: …` at the start of a paragraph | A direction |
| A whole paragraph in `[brackets]`, `{braces}` or `(parentheses)` | A direction |
| A whole paragraph in *italics* | A direction |
| A highlighted or coloured paragraph (Word) | A direction |
| Word comments, `<!-- HTML comments -->` (Markdown), `% comments` (LaTeX) | A direction, anchored where the comment is |
| Inline `[show the graph]`, `{zoom in}` | A direction |
| Inline `(highlight the 3)`, i.e. parentheses that start with a visual verb | A direction |
| Inline `(well, mostly)`, i.e. ordinary parentheses | Spoken |
| Headings (`#`, Word Heading styles, `\section`) | Section titles (not spoken), which become chapters. Confirmed automatically, so they aren't listed for review |
| `VO:`, `NARRATOR:` at the start of a line | Spoken (the label is removed) |

## Kinds of annotation
The first word sets the kind. Anything else is a general "visual" direction.
- `title card: Why Primes Matter` sets the opening title card.
- `end card: Thanks for watching` sets the end card.

  Card annotations belong to the card scenes (S00 and S99 in PLAN.md), not to the first or last voice scene.
- `section: Prime factorisation` starts a new section (and chapter).
- `equation: $...$` shows an equation.
- `transform: $a$ -> $b$` morphs one expression into another.
- `quote: "..." — Author` shows a quote card.
- `diagram: ...`, `graph: ...` or `number line: ...` draws a diagram or plot.
- `highlight: ...` emphasises something.
- `ref: exam2023.pdf, question 4b` shows a question from a reference document (see below).

## Holds (pauses for the visuals)
The audio edit shortens long pauses. When you want a pause, for example to let a graph draw or an equation sink in, mark it:
```
That's the fundamental theorem of arithmetic. [[hold 2s]]

[[pause]]            (1.5 s)
[[beat]]             (0.8 s)
We split it apart [[pause 1.5]] until only primes are left.
```
- A hold puts exactly that much silence in the edited voice, using your room tone. It replaces whatever pause was recorded there.
- If it's at the end of a sentence or paragraph, the hold comes after that line, and the scene showing that line owns the pause.
- If it's mid-sentence, the pause goes before the next word.
- If it's right after a heading, it opens the new section.
- `hold the equation on screen` (no number, more words after it) is treated as an ordinary visual direction, not a pause.
- Draft mode honours holds too.

## References
Put the documents in `references/`, then point at what you want:
```
[[ref: exam2023.pdf, question 4b]]
[[ref: textbook.pdf p.112, example 3]]
(show question 4b from the 2023 exam)
[[ref: worksheet.png]]
```
- File names can be loose ("the 2023 exam" matches `exam2023.pdf`). If `references/` holds only one file, you don't need to name it.
- Manimatic finds the question label in the PDF. It crops from that question to the next one, keeping the stem for a sub-part, and saves the crop plus its text.
- **Scanned papers and photos** work too. Pages with no text layer are read with OCR: Tesseract if installed, otherwise the built-in RapidOCR. Images can be pointed at a question as well: `[[ref: worksheet.png, question 3]]`. OCR text can contain small errors, so for `retype` mode check it against the image.
- In PLAN.md, choose `mode: original` (the crop, shown light-on-dark) or `mode: retype` (retyped as text and maths so it can be animated).
- Wrong crop? Run `mm.py ref page exam2023.pdf 3` to get the page with a grid. Then run `mm.py ref set R01 --page 3 --crop 0.1,0.2,0.9,0.55`.

## Maths in the script
Write maths as `$...$`. Manimatic works out how it's spoken (`$x^2$` becomes "x squared") so it can match your audio. If you say it differently, for example "x to the power of two", run `mm.py spoken L0012 "x to the power of two plus one"` so the line matches.
