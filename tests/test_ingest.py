import json
import zipfile

from manimatic.ingest import run_ingest, set_annotation_status, split_sentences
from manimatic.project import Project

MD = """# Why primes matter

[[title card: Why Primes Matter]]

Every whole number can be built from primes. [[equation: $60 = 2^2$ @ "built"]] That's the theorem, e.g. this one.

*Show a number line from 1 to 30.*

Look at 60 (well, mostly any number works). We split it apart (zoom in on the factor tree) until only primes are left.

Visual: show question 4b from exam2023.pdf

VO: Notice the word prime. <!-- highlight prime -->
"""


def make_project(tmp_path, name="script.md", content=MD):
    (tmp_path / "manimatic.toml").write_text("", encoding="utf-8")
    (tmp_path / "script").mkdir()
    if isinstance(content, bytes):
        (tmp_path / "script" / name).write_bytes(content)
    else:
        (tmp_path / "script" / name).write_text(content, encoding="utf-8")
    return Project(tmp_path)


def test_sentences_keep_abbreviations_and_math():
    s = split_sentences("This is e.g. fine. Then $3.5 = x$. Done! next lowercase. End")
    assert s == ["This is e.g. fine.", "Then $3.5 = x$.", "Done! next lowercase.", "End"]


def test_markdown_annotations(tmp_path):
    p = make_project(tmp_path)
    summary = run_ingest(p)
    data = json.loads((p.work / "script.json").read_text(encoding="utf-8"))
    anns = {a["id"]: a for a in data["annotations"]}
    by_src = {}
    for a in anns.values():
        by_src.setdefault(a["source"], []).append(a)
    assert {a["kind"] for a in by_src["explicit"]} == {"title", "equation"}
    eq = next(a for a in by_src["explicit"] if a["kind"] == "equation")
    line = next(ln for ln in data["lines"] if ln["id"] == eq["line"])
    assert line["tokens"][eq["at"]][0] == "built"          # @ "built" anchor
    assert by_src["italic"][0]["status"] == "annotation"
    assert by_src["parens"][0]["text"] == "zoom in on the factor tree"
    assert by_src["label"][0]["kind"] == "ref"
    assert by_src["note"][0]["text"] == "highlight prime"
    texts = [ln["text"] for ln in data["lines"]]
    assert "Look at 60 (well, mostly any number works)." in texts      # ordinary parentheses stay spoken
    assert "Notice the word prime." in texts                           # VO: label removed
    assert summary["sections"] == 1 and summary["references"] == 1


def test_flip_annotation_to_spoken(tmp_path):
    p = make_project(tmp_path)
    run_ingest(p)
    data = json.loads((p.work / "script.json").read_text(encoding="utf-8"))
    parens = next(a for a in data["annotations"] if a["source"] == "parens")
    set_annotation_status(p, parens["id"], "spoken")
    run_ingest(p)
    data = json.loads((p.work / "script.json").read_text(encoding="utf-8"))
    assert any("zoom in on the factor tree" in ln["text"] for ln in data["lines"])


def _docx(paragraphs):
    """Minimal .docx: paragraphs = [(style, [(text, italic, comment_text)])]."""
    W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body, comments, cid = [], [], 0
    for style, runs in paragraphs:
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        parts = []
        for text, italic, comment in runs:
            rpr = "<w:rPr><w:i/></w:rPr>" if italic else ""
            r = f'<w:r>{rpr}<w:t xml:space="preserve">{text}</w:t></w:r>'
            if comment:
                parts.append(f'<w:commentRangeStart w:id="{cid}"/>{r}<w:commentRangeEnd w:id="{cid}"/>')
                comments.append(f'<w:comment w:id="{cid}"><w:p><w:r><w:t>{comment}</w:t></w:r></w:p></w:comment>')
                cid += 1
            else:
                parts.append(r)
        body.append(f"<w:p>{ppr}{''.join(parts)}</w:p>")
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f"<w:document {W}><w:body>{''.join(body)}</w:body></w:document>")
        z.writestr("word/comments.xml", f"<w:comments {W}>{''.join(comments)}</w:comments>")
        z.writestr("word/styles.xml", f'<w:styles {W}><w:style w:styleId="Heading1"><w:name w:val="heading 1"/></w:style></w:styles>')
    return buf.getvalue()


def test_docx_comments_italics_headings(tmp_path):
    doc = _docx([
        ("Heading1", [("Primes", False, None)]),
        ("", [("Every number is built from ", False, None), ("primes", False, "highlight this word"), (".", False, None)]),
        ("", [("Show the factor tree of 60.", True, None)]),
        ("", [("That is the theorem.", False, None)]),
    ])
    p = make_project(tmp_path, "script.docx", doc)
    run_ingest(p)
    data = json.loads((p.work / "script.json").read_text(encoding="utf-8"))
    srcs = {a["source"]: a for a in data["annotations"]}
    assert srcs["heading"]["text"] == "Primes"
    assert srcs["comment"]["text"] == "highlight this word"
    assert srcs["italic"]["status"] == "annotation"
    assert [ln["text"] for ln in data["lines"]] == ["Every number is built from primes.", "That is the theorem."]
    assert data["sections"][0]["title"] == "Primes"


def test_end_of_paragraph_anchor_points_back(tmp_path):
    p = make_project(tmp_path, content="First we cut the ball. Then we reassemble it. [[diagram: pieces move @ \"reassemble\"]]\n\nNext paragraph.\n")
    run_ingest(p)
    data = json.loads((p.work / "script.json").read_text(encoding="utf-8"))
    a = next(x for x in data["annotations"] if x["source"] == "explicit")
    line = next(ln for ln in data["lines"] if ln["id"] == a["line"])
    assert line["tokens"][a["at"]][0] == "reassemble"
