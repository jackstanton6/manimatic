"""Spoken-form normalisation shared by the script and the transcript.

Both sides go through the same functions, so "60", "sixty" and "$60$" all become
["sixty"], and "$x^2$" becomes ["x", "squared"]. The exact convention matters less
than applying it identically to both sides; the aligner is fuzzy anyway.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
        "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
SCALES = [(10**12, "trillion"), (10**9, "billion"), (10**6, "million"), (1000, "thousand")]
ORD_IRREG = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth",
             "nine": "ninth", "twelve": "twelfth"}

GREEK = ["alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta", "eta", "theta", "vartheta",
         "iota", "kappa", "lambda", "mu", "nu", "xi", "omicron", "pi", "varpi", "rho", "varrho", "sigma",
         "varsigma", "tau", "upsilon", "phi", "varphi", "chi", "psi", "omega"]
GREEK_UNI = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε", "zeta": "ζ",
    "eta": "η", "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν",
    "xi": "ξ", "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ", "varphi": "φ",
    "chi": "χ", "psi": "ψ", "omega": "ω", "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ",
    "Pi": "Π", "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}
UNI_GREEK = {v: k.lower() for k, v in GREEK_UNI.items()}

SYMBOL_WORDS = {
    "&": ["and"], "%": ["percent"], "+": ["plus"], "=": ["equals"], "×": ["times"], "·": ["times"],
    "÷": ["divided", "by"], "±": ["plus", "or", "minus"], "≈": ["approximately"], "≠": ["not", "equal", "to"],
    "≤": ["less", "than", "or", "equal", "to"], "≥": ["greater", "than", "or", "equal", "to"], "<": ["less", "than"],
    ">": ["greater", "than"], "√": ["square", "root", "of"], "∞": ["infinity"], "°": ["degrees"], "→": ["to"],
    "∑": ["sum"], "∫": ["integral"], "∏": ["product"], "π": ["pi"], "θ": ["theta"],
}
SUPERSCRIPTS = {"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9", "ⁿ": "n"}
TO_SUPER = {v: k for k, v in SUPERSCRIPTS.items()}
FILLERS = {"um", "umm", "uh", "uhh", "uhm", "er", "erm", "ah", "eh", "hmm", "hm", "mm", "mhm", "ahh"}


# ------------------------------------------------------------------ numbers

def int_to_words(n: int) -> list[str]:
    if n < 0:
        return ["minus"] + int_to_words(-n)
    if n < 20:
        return [ONES[n]]
    if n < 100:
        t, o = divmod(n, 10)
        return [TENS[t]] + ([ONES[o]] if o else [])
    if n < 1000:
        h, r = divmod(n, 100)
        return [ONES[h], "hundred"] + (int_to_words(r) if r else [])
    for size, name in SCALES:
        if n >= size:
            q, r = divmod(n, size)
            return int_to_words(q) + [name] + (int_to_words(r) if r else [])
    return [str(n)]


def number_to_words(s: str) -> list[str]:
    """'1,234.5' -> one thousand two hundred thirty four point five."""
    s = s.replace(",", "")
    neg = s.startswith("-")
    s = s.lstrip("-+")
    if not s:
        return []
    if "." in s:
        a, b = s.split(".", 1)
        out = (int_to_words(int(a)) if a else ["zero"]) + ["point"] + [ONES[int(d)] for d in b if d.isdigit()]
    else:
        if len(s) > 15:
            out = [ONES[int(d)] for d in s]
        else:
            out = int_to_words(int(s))
    return (["minus"] if neg else []) + out


def ordinal_words(n: int) -> list[str]:
    w = int_to_words(n)
    last = w[-1]
    if last in ORD_IRREG:
        w[-1] = ORD_IRREG[last]
    elif last.endswith("y"):
        w[-1] = last[:-1] + "ieth"
    else:
        w[-1] = last + "th"
    return w


# ------------------------------------------------------------------ LaTeX

_TEX_CMD_WORDS = {
    "cdot": ["times"], "times": ["times"], "div": ["divided", "by"], "pm": ["plus", "or", "minus"],
    "mp": ["minus", "or", "plus"], "le": ["less", "than", "or", "equal", "to"], "leq": ["less", "than", "or", "equal", "to"],
    "ge": ["greater", "than", "or", "equal", "to"], "geq": ["greater", "than", "or", "equal", "to"],
    "ne": ["not", "equal", "to"], "neq": ["not", "equal", "to"], "approx": ["approximately"], "sim": ["approximately"],
    "equiv": ["is", "equivalent", "to"], "to": ["to"], "rightarrow": ["to"], "Rightarrow": ["implies"],
    "implies": ["implies"], "iff": ["if", "and", "only", "if"], "infty": ["infinity"], "sum": ["sum"],
    "prod": ["product"], "int": ["integral"], "oint": ["integral"], "lim": ["limit"], "partial": ["partial"],
    "nabla": ["del"], "in": ["in"], "notin": ["not", "in"], "subset": ["subset"], "subseteq": ["subset"],
    "cup": ["union"], "cap": ["intersect"], "forall": ["for", "all"], "exists": ["there", "exists"],
    "cdots": ["dot", "dot", "dot"], "ldots": ["dot", "dot", "dot"], "dots": ["dot", "dot", "dot"],
    "sin": ["sine"], "cos": ["cosine"], "tan": ["tan"], "log": ["log"], "ln": ["natural", "log"],
    "exp": ["exp"], "det": ["determinant"], "max": ["max"], "min": ["min"], "gcd": ["gcd"], "mod": ["mod"],
    "bmod": ["mod"], "pmod": ["mod"], "circ": ["degrees"], "angle": ["angle"], "perp": ["perpendicular", "to"],
    "parallel": ["parallel", "to"], "mid": ["divides"], "neg": ["not"], "land": ["and"], "lor": ["or"],
    "emptyset": ["empty", "set"], "varnothing": ["empty", "set"], "hbar": ["h", "bar"], "ell": ["l"],
}
_TEX_IGNORE = {"left", "right", "big", "Big", "bigg", "Bigg", "displaystyle", "textstyle", ",", ";", ":", "!",
               "quad", "qquad", "limits", "nolimits", "middle", " ", "bigl", "bigr", "Bigl", "Bigr", "colon"}
_TEX_FONT = {"mathbb", "mathbf", "mathcal", "mathrm", "mathit", "mathsf", "mathfrak", "boldsymbol", "bm",
             "operatorname", "vec", "hat", "bar", "overline", "tilde", "dot", "ddot", "underline", "mathscr"}
_TEX_TEXT = {"text", "textrm", "textit", "textbf", "mbox", "textnormal"}


def _tex_tokens(s: str) -> list[str]:
    toks, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\":
            m = re.match(r"\\([A-Za-z]+|.)", s[i:])
            toks.append("\\" + m.group(1))
            i += len(m.group(0))
        elif c.isspace():
            i += 1
        elif c.isdigit() or (c == "." and i + 1 < len(s) and s[i + 1].isdigit()):
            m = re.match(r"\d*\.?\d+", s[i:])
            toks.append(m.group(0))
            i += len(m.group(0))
        else:
            toks.append(c)
            i += 1
    return toks


class _TexSpeaker:
    def __init__(self, tex: str):
        self.t = _tex_tokens(tex)
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def group(self) -> list[str]:
        """Read one argument: {...} or a single token."""
        tok = self.peek()
        if tok is None:
            return []
        if tok == "{":
            self.take()
            out = []
            while self.peek() not in (None, "}"):
                out += self.atom()
            self.take()
            return out
        return self.atom()

    def raw_group(self) -> str:
        if self.peek() != "{":
            return self.take() or ""
        self.take()
        depth, parts = 1, []
        while self.peek() is not None:
            tok = self.take()
            if tok == "{":
                depth += 1
            elif tok == "}":
                depth -= 1
                if depth == 0:
                    break
            parts.append(tok[1:] if tok.startswith("\\") else tok)
        return " ".join(parts)

    def power(self) -> list[str]:
        g = self.group()
        if g == ["two"]:
            return ["squared"]
        if g == ["three"]:
            return ["cubed"]
        if g == ["minus", "one"]:
            return ["inverse"]
        return ["to", "the"] + g

    def atom(self) -> list[str]:
        tok = self.take()
        if tok is None:
            return []
        if tok == "{":
            out = []
            while self.peek() not in (None, "}"):
                out += self.atom()
            self.take()
            return out
        if tok == "}":
            return []
        if tok == "^":
            return self.power()
        if tok == "_":
            return self.group()
        if tok[0].isdigit() or tok[0] == ".":
            return number_to_words(tok)
        if tok.startswith("\\"):
            name = tok[1:]
            if name in ("frac", "dfrac", "tfrac", "cfrac"):
                a, b = self.group(), self.group()
                return a + ["over"] + b
            if name == "sqrt":
                n = []
                if self.peek() == "[":
                    self.take()
                    while self.peek() not in (None, "]"):
                        n += self.atom()
                    self.take()
                body = self.group()
                if n == ["three"]:
                    return ["cube", "root", "of"] + body
                if len(n) == 1 and n[0] in ONES:
                    return ordinal_words(ONES.index(n[0])) + ["root", "of"] + body
                if n:
                    return n + ["th", "root", "of"] + body
                return ["square", "root", "of"] + body
            if name in ("binom", "choose"):
                a, b = self.group(), self.group()
                return a + ["choose"] + b
            if name in _TEX_TEXT:
                return words_of(self.raw_group())
            if name in _TEX_FONT:
                g = self.group()
                # \mathbb{R}^3 is said "R three", not "R cubed"
                if name == "mathbb" and self.peek() == "^":
                    save = self.i
                    self.take()
                    p = self.group()
                    if p and all(w in ONES for w in p):
                        return g + p
                    self.i = save
                return g
            if name in GREEK or name.lower() in GREEK:
                return [name.lower().replace("var", "")]
            if name in _TEX_CMD_WORDS:
                return list(_TEX_CMD_WORDS[name])
            if name in _TEX_IGNORE:
                return []
            if name in ("begin", "end"):
                self.raw_group()
                return []
            if name in ("\\",):
                return []
            return [name.lower()] if name.isalpha() and len(name) > 1 else []
        if tok == "=":
            return ["equals"]
        if tok == "+":
            return ["plus"]
        if tok == "-":
            return ["minus"]
        if tok == "<":
            return ["less", "than"]
        if tok == ">":
            return ["greater", "than"]
        if tok == "/":
            return ["over"]
        if tok == "!":
            return ["factorial"]
        if tok == "'":
            return ["prime"]
        if tok.isalpha():
            return [tok.lower()]
        if tok in SYMBOL_WORDS:
            return list(SYMBOL_WORDS[tok])
        return []

    def speak(self) -> list[str]:
        out = []
        while self.peek() is not None:
            out += self.atom()
        return out


def latex_to_speech(tex: str) -> list[str]:
    try:
        return _TexSpeaker(tex).speak()
    except Exception:  # noqa: BLE001 - malformed TeX: fall back to letters/digits
        return words_of(re.sub(r"\\[A-Za-z]+", " ", tex))


def latex_to_unicode(tex: str) -> str:
    """Readable plain-text rendering of simple TeX, for captions."""
    s = tex
    s = re.sub(r"\\(?:d|t|c)?frac\{([^{}]*)\}\{([^{}]*)\}", r"(\1)/(\2)", s)
    s = re.sub(r"\(([A-Za-z0-9])\)", r"\1", s)
    s = re.sub(r"\\sqrt\{([^{}]*)\}", r"√(\1)", s)
    s = re.sub(r"√\(([A-Za-z0-9])\)", r"√\1", s)
    s = re.sub(r"\\(?:text|textrm|mathrm|mathbf|mathbb|mathcal|operatorname|textit)\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\^\{?(-?[0-9n]+)\}?", lambda m: "".join(TO_SUPER.get(c, "⁻" if c == "-" else c) for c in m.group(1)), s)
    s = re.sub(r"_\{([^{}]*)\}", r"\1", s)
    s = s.replace("_", "")
    reps = {r"\cdot": "·", r"\times": "×", r"\div": "÷", r"\pm": "±", r"\leq": "≤", r"\le": "≤", r"\geq": "≥",
            r"\ge": "≥", r"\neq": "≠", r"\ne": "≠", r"\approx": "≈", r"\infty": "∞", r"\to": "→", r"\rightarrow": "→",
            r"\sum": "∑", r"\int": "∫", r"\prod": "∏", r"\cdots": "⋯", r"\ldots": "…", r"\dots": "…", r"\in": "∈",
            r"\left": "", r"\right": "", r"\,": " ", r"\;": " ", r"\quad": "  ", r"\!": ""}
    for k in sorted(reps, key=len, reverse=True):
        s = s.replace(k, reps[k])
    s = re.sub(r"\\([A-Za-z]+)", lambda m: GREEK_UNI.get(m.group(1), m.group(1)), s)
    s = s.replace("{", "").replace("}", "")
    s = re.sub(r"\s*([=+<>≤≥≠≈×÷±])\s*", r" \1 ", s)
    return re.sub(r"\s+", " ", s).strip()


# ------------------------------------------------------------------ plain words

def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    return s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-")


def words_of(text: str) -> list[str]:
    """Spoken tokens of one plain-text chunk (no $math$)."""
    out: list[str] = []
    # letters with unicode superscripts: x² -> x squared (before NFKC folds ² into 2)
    text = re.sub(r"([A-Za-z0-9)])([⁰¹²³⁴⁵⁶⁷⁸⁹ⁿ]+)",
                  lambda m: m.group(1) + " ^" + "".join(SUPERSCRIPTS[c] for c in m.group(2)) + " ", text)
    text = _fold(text)
    for raw in re.split(r"\s+", text):
        if raw:
            out += _word_tokens(raw)
    return out


ABBREV_SPOKEN = {"e.g": ["for", "example"], "eg": ["for", "example"], "i.e": ["that", "is"], "ie": ["that", "is"],
                 "etc": ["et", "cetera"], "vs": ["versus"], "approx": ["approximately"], "w.r.t": ["with", "respect", "to"]}


def _word_tokens(raw: str) -> list[str]:
    low = raw.lower().strip("\"'()[]{},;:!?…")
    if low.rstrip(".") in ABBREV_SPOKEN and "." in raw:
        return list(ABBREV_SPOKEN[low.rstrip(".")])
    w = raw.strip("\"'()[]{}.,;:!?…")
    if not w:
        return [x for c in raw for x in SYMBOL_WORDS.get(c, [])]
    if w.startswith("^"):
        n = w[1:]
        if n == "2":
            return ["squared"]
        if n == "3":
            return ["cubed"]
        return ["to", "the"] + (number_to_words(n) if n.isdigit() else [n.lower()])
    out: list[str] = []
    for part in re.split(r"(?<=[A-Za-z0-9%])[-/](?=[A-Za-z0-9$])", w):
        out += _part_tokens(part)
    return out


def _part_tokens(part: str) -> list[str]:
    if not part:
        return []
    m = re.fullmatch(r"(\d+)(st|nd|rd|th)", part, re.I)
    if m:
        return ordinal_words(int(m.group(1)))
    m = re.fullmatch(r"([-+]?[\d,]*\.?\d+)(%?)", part)
    if m and re.search(r"\d", m.group(1)):
        return number_to_words(m.group(1)) + (["percent"] if m.group(2) else [])
    m = re.fullmatch(r"\$(\d[\d,]*\.?\d*)", part)  # currency $5 (only reaches here if not math)
    if m:
        return number_to_words(m.group(1)) + ["dollars"]
    if part in SYMBOL_WORDS:
        return list(SYMBOL_WORDS[part])
    if part in UNI_GREEK:
        return [UNI_GREEK[part]]
    m = re.fullmatch(r"([A-Za-z]{1,3})\((\d{1,2})\)?", part)  # SO(3) -> s o three (outer strip may eat the ")")
    if m:
        part = m.group(1) + m.group(2)
    m = re.fullmatch(r"([A-Za-z]{1,3})(\d{1,2})", part)  # F2 -> f two, SO3 -> s o three, R3 -> r three
    if m:
        letters = m.group(1)
        ls = list(letters.lower()) if letters.isupper() or len(letters) == 1 else [letters.lower()]
        return ls + number_to_words(m.group(2))
    m = re.fullmatch(r"(\d+)([A-Za-z]+)", part)  # 2x -> two x
    if m:
        return number_to_words(m.group(1)) + [m.group(2).lower()]
    if re.search(r"[+=×·÷<>]", part):  # symbols glued to words, e.g. a+b
        out: list[str] = []
        for piece in re.split(r"([+=×·÷<>])", part):
            if piece in SYMBOL_WORDS:
                out += SYMBOL_WORDS[piece]
            elif piece:
                out += _part_tokens(piece)
        return out
    if part.startswith("^"):
        return _word_tokens(part)
    cleaned = re.sub(r"[^\w']", "", part).replace("'", "").replace("_", "").lower()
    return [cleaned] if cleaned else []


MATH_RE = re.compile(r"(\$\$.+?\$\$|\$[^$]+?\$|\\\(.+?\\\)|\\\[.+?\\\])", re.S)


def strip_math_delims(m: str) -> str:
    if m.startswith("$$"):
        return m[2:-2]
    if m.startswith("$"):
        return m[1:-1]
    return m[2:-2]


@dataclass
class Tok:
    s: str          # spoken token
    d: str          # display text carried by this token ("" for continuation tokens)
    math: bool = False


def tokenize_display(text: str) -> list[Tok]:
    """Spoken tokens of a script sentence, each carrying its display text for captions."""
    toks: list[Tok] = []
    for chunk in MATH_RE.split(text):
        if not chunk:
            continue
        if MATH_RE.fullmatch(chunk):
            tex = strip_math_delims(chunk)
            spoken = latex_to_speech(tex)
            disp = latex_to_unicode(tex)
            for k, s in enumerate(spoken):
                toks.append(Tok(s, disp if k == 0 else "", True))
            if not spoken and toks:
                toks[-1].d += " " + disp
            continue
        for raw in re.split(r"\s+", chunk):
            if not raw:
                continue
            spoken = words_of(raw)
            if not spoken:
                if toks:
                    toks[-1].d = (toks[-1].d + " " + raw).strip() if toks[-1].d else toks[-1].d
                continue
            for k, s in enumerate(spoken):
                toks.append(Tok(s, raw if k == 0 else ""))
    return toks


def normalize_asr_word(word: str) -> list[str]:
    """One recognised word -> spoken tokens (may be several, e.g. '60%')."""
    w = word.strip()
    if not w:
        return []
    if MATH_RE.search(w):
        return [t.s for t in tokenize_display(w)]
    return words_of(w)


def spoken_text(text: str) -> str:
    return " ".join(t.s for t in tokenize_display(text))
