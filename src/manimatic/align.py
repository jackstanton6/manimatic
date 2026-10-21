"""Script <-> transcript alignment, retake selection and cut classification.

1. Every script line (sentence) is searched for in the transcript stream (all audio
   files in order) with n-gram anchoring + Smith-Waterman local alignment, giving
   every *take* of that line.
2. Takes are chosen walking backwards through the script, picking the *latest
   complete* take that ends before the next line's chosen take. That keeps the
   last take of any retake and handles repeated sentences.
3. A pickup pass swaps in a later out-of-order take (e.g. re-recorded at the end of
   the session) when it isn't used by any other line.
4. Everything not inside a chosen take is classified: earlier takes / false starts,
   retake cues ("let me say that again"), slates, flubs, fillers -> cut; anything
   else is an ad-lib -> kept and flagged for the user to decide.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from manimatic.ingest.speech import FILLERS, normalize_asr_word
from manimatic.util import ManimaticError, read_json, stable_id, write_json

try:
    from rapidfuzz.fuzz import ratio as _ratio
except ImportError:  # pragma: no cover
    from difflib import SequenceMatcher

    def _ratio(a, b):
        return SequenceMatcher(None, a, b).ratio() * 100

CUE_RES = [re.compile(p) for p in [
    r"\blet me (try|do|say|start|redo|take) (that|this|it|the|again)", r"\b(one|once) more time\b",
    r"\bstart (that|this|it) (again|over)\b", r"\bstart again\b", r"\bfrom the top\b", r"\bscratch that\b",
    r"\b(cut|delete|lose) (that|this)\b", r"\bre ?do\b", r"\bre ?take\b", r"\bpick ?up\b", r"\btake (two|three|four|five|\d+)\b",
    r"\bi (messed|screwed|mucked|stuffed) (that|it) up\b", r"\bsorry\b", r"\bhang on\b", r"\bwait\b",
    r"\bthat was (bad|wrong|terrible)\b", r"\bagain\b$", r"^again\b", r"\bum let me\b", r"\boops\b", r"\bwhoops\b",
]]
SLATE_WORDS = {"recording", "record", "test", "testing", "take", "okay", "ok", "alright", "ready", "rolling", "start",
               "stop", "check", "mic", "one", "two", "three", "go", "right", "so", "and", "thats", "it", "done", "end"}


# ------------------------------------------------------------------ data

@dataclass
class ATok:
    t: str        # normalised token
    w: int        # index into the global word list
    s: float
    e: float


@dataclass
class Take:
    line: int                 # index into lines
    i0: int                   # first ASR token index
    i1: int                   # last ASR token index (inclusive)
    score: float
    coverage: float
    complete: bool
    pairs: list[tuple[int, int]] = field(default_factory=list)  # (script tok idx, asr tok idx)


def _sim(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if len(a) < 3 or len(b) < 3:
        return 0.0
    return _ratio(a, b) / 100.0


def load_stream(proj) -> tuple[list[dict], list[ATok], list[dict]]:
    """Global word list and token stream over all audio files (in order)."""
    man = read_json(proj.work / "asr" / "manifest.json")
    if not man:
        raise ManimaticError("No transcript yet. Run `mm.py transcribe` (or draft mode).")
    words: list[dict] = []
    toks: list[ATok] = []
    for fi, f in enumerate(man["files"]):
        data = read_json(proj.work / "asr" / f["cache"])
        for w in data["words"]:
            wi = len(words)
            nt = normalize_asr_word(w["w"])
            words.append({"w": w["w"], "s": w["s"], "e": w["e"], "p": w.get("p", 0.9), "file": fi, "toks": nt})
            if not nt:
                continue
            span = (w["e"] - w["s"]) / len(nt)
            for k, t in enumerate(nt):
                toks.append(ATok(t, wi, w["s"] + k * span, w["s"] + (k + 1) * span))
    return words, toks, man["files"]


# ------------------------------------------------------------------ local alignment

MATCH, PARTIAL, MISMATCH, DEL, INS = 2.0, 0.5, -1.0, -1.0, -0.7


def local_align(T: list[str], A: list[str]) -> tuple[float, int, int, list[tuple[int, int, float]]]:
    """Smith-Waterman. Returns (score, a_start, a_end_inclusive, [(t_idx, a_idx, sim)])."""
    m, n = len(T), len(A)
    if m == 0 or n == 0:
        return 0.0, -1, -1, []
    H = [[0.0] * (n + 1) for _ in range(m + 1)]
    P = [[0] * (n + 1) for _ in range(m + 1)]  # 0 stop, 1 diag, 2 up (del), 3 left (ins)
    best, bi, bj = 0.0, 0, 0
    for i in range(1, m + 1):
        ti = T[i - 1]
        Hi, Hp, Pi = H[i], H[i - 1], P[i]
        for j in range(1, n + 1):
            aj = A[j - 1]
            s = _sim(ti, aj)
            d = Hp[j - 1] + (MATCH if s >= 0.85 else PARTIAL if s >= 0.6 else MISMATCH)
            u = Hp[j] + DEL
            l_ = Hi[j - 1] + (0.0 if aj in FILLERS else INS)
            v, p = 0.0, 0
            if d > v:
                v, p = d, 1
            if u > v:
                v, p = u, 2
            if l_ > v:
                v, p = l_, 3
            Hi[j], Pi[j] = v, p
            if v > best:
                best, bi, bj = v, i, j
    pairs: list[tuple[int, int, float]] = []
    i, j = bi, bj
    a_end = bj - 1
    a_start = a_end
    while i > 0 and j > 0 and P[i][j] != 0:
        p = P[i][j]
        if p == 1:
            s = _sim(T[i - 1], A[j - 1])
            if s >= 0.6:
                pairs.append((i - 1, j - 1, s))
            a_start = j - 1
            i, j = i - 1, j - 1
        elif p == 2:
            i -= 1
        else:
            a_start = j - 1
            j -= 1
    pairs.reverse()
    if pairs:
        a_start = min(a_start, pairs[0][1])
    return best, a_start, a_end, pairs


def _candidates(line_idx: int, T: list[str], A: list[str], bigrams: dict, unigrams: dict) -> list[Take]:
    m = len(T)
    n = len(A)
    est: list[int] = []
    if m >= 2:
        bgs = [(a, (T[a], T[a + 1])) for a in range(m - 1)]
        hits = [(a, bigrams.get(bg, [])) for a, bg in bgs]
        rare = [h for h in hits if 0 < len(h[1]) <= 40]
        use = rare if rare else [h for h in hits if h[1]]
        for a, ps in use:
            est += [p - a for p in ps]
    if not est:
        for a, t in enumerate(T):
            ps = unigrams.get(t, [])
            if 0 < len(ps) <= 60:
                est += [p - a for p in ps]
    if not est:
        return []
    est.sort()
    tol = max(4, m // 3)
    clusters: list[list[int]] = [[est[0]]]
    for x in est[1:]:
        if x - clusters[-1][-1] <= tol:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    takes: list[Take] = []
    min_support = 2 if m >= 6 else 1
    for c in clusters:
        if len(c) < min_support and len(clusters) > 1:
            continue
        lo = max(0, c[0] - 4)
        hi = min(n, c[-1] + m + 6)
        W = list(A[lo:hi])
        for _ in range(6):  # several takes can sit in one window (back-to-back retakes)
            score, a0, a1, pairs = local_align(T, W)
            good = [p for p in pairs if p[2] >= 0.6]
            cov = len({p[0] for p in good}) / m
            if score < max(2.0, 1.2 * min(m, 4)) or cov < 0.34 or not good:
                break
            ts = [p[0] for p in good]
            complete = cov >= 0.7 and min(ts) <= max(1, int(0.15 * m)) and max(ts) >= m - 1 - max(1, int(0.15 * m))
            takes.append(Take(line_idx, lo + a0, lo + a1, score, cov, complete,
                              [(p[0], lo + p[1]) for p in good]))
            for k in range(a0, a1 + 1):
                W[k] = "\x00"
    # dedupe identical spans
    seen, out = set(), []
    for t in sorted(takes, key=lambda t: (t.i0, -t.score)):
        if (t.i0, t.i1) not in seen:
            seen.add((t.i0, t.i1))
            out.append(t)
    return out


# ------------------------------------------------------------------ selection

def choose_takes(cands: list[list[Take]]) -> tuple[list[Take | None], list[str]]:
    n = len(cands)
    chosen: list[Take | None] = [None] * n
    status = ["missing"] * n
    limit = 10**12
    for li in range(n - 1, -1, -1):
        ok = [t for t in cands[li] if t.i1 < limit]
        comp = [t for t in ok if t.complete]
        if comp:
            pick = max(comp, key=lambda t: (t.i0, t.score))
            status[li] = "ok"
        elif ok:
            pick = max(ok, key=lambda t: (t.coverage, t.i0))
            status[li] = "incomplete"
        else:
            continue
        chosen[li] = pick
        limit = pick.i0
    return chosen, status


def pickup_pass(cands: list[list[Take]], chosen: list[Take | None], status: list[str]) -> list[int]:
    used = set()
    for t in chosen:
        if t:
            used.update(range(t.i0, t.i1 + 1))
    swapped = []
    for li, t in enumerate(chosen):
        if not t:
            later = [c for c in cands[li] if c.complete and not (set(range(c.i0, c.i1 + 1)) & used)]
            if later:
                pick = max(later, key=lambda c: c.i0)
                chosen[li], status[li] = pick, "pickup"
                used.update(range(pick.i0, pick.i1 + 1))
                swapped.append(li)
            continue
        later = [c for c in cands[li] if c.complete and c.i0 > t.i1 and c.score >= 0.9 * t.score
                 and not (set(range(c.i0, c.i1 + 1)) & used)]
        if later:
            pick = max(later, key=lambda c: c.i0)
            used.difference_update(range(t.i0, t.i1 + 1))
            chosen[li], status[li] = pick, "pickup"
            used.update(range(pick.i0, pick.i1 + 1))
            swapped.append(li)
    return swapped


# ------------------------------------------------------------------ classification

def _is_cue(text: str) -> bool:
    return any(r.search(text) for r in CUE_RES)


def classify_runs(toks: list[ATok], words: list[dict], chosen: list[Take | None], lines_T: list[list[str]],
                  script_bigrams: set) -> list[dict]:
    n = len(toks)
    owner = [-1] * n            # line index owning the token (inside a chosen take span)
    matched = [False] * n
    for li, t in enumerate(chosen):
        if t:
            for k in range(t.i0, t.i1 + 1):
                owner[k] = li
            for _, a in t.pairs:
                matched[a] = True
    take_starts = sorted((t.i0, li) for li, t in enumerate(chosen) if t)
    first_take = take_starts[0][0] if take_starts else n
    last_take_end = max((t.i1 for t in chosen if t), default=-1)

    def nearest_lines(k: int) -> list[int]:
        before = [li for i0, li in take_starts if i0 <= k]
        after = [li for i0, li in take_starts if i0 > k]
        base = (before[-1] if before else (after[0] if after else 0))
        return [x for x in range(base - 2, base + 4) if 0 <= x < len(lines_T)]

    items: list[dict] = []
    k = 0
    while k < n:
        inside = owner[k] >= 0
        if inside and matched[k]:
            k += 1
            continue
        j = k
        while j + 1 < n and (owner[j + 1] >= 0) == inside and not (inside and matched[j + 1]) and \
                (not inside or owner[j + 1] == owner[k]) and words[toks[j + 1].w]["file"] == words[toks[k].w]["file"]:
            wj, wn = words[toks[j].w], words[toks[j + 1].w]
            if toks[j].w != toks[j + 1].w and (wn["s"] - wj["e"] > 0.5 or re.search(r"[.?!]$", wj["w"])):
                break  # a pause or sentence end separates different things (e.g. an ad-lib, then a flub)
            j += 1
        run = [toks[x].t for x in range(k, j + 1)]
        text = " ".join(run)
        kind, reason, ref = "adlib", "", None
        content = [t for t in run if t not in FILLERS]
        prev_t = toks[k - 1].t if k > 0 else ""
        next_t = toks[j + 1].t if j + 1 < n else ""
        if not content:
            kind, reason = "filler", "filler word"
        elif _is_cue(text):
            kind, reason = "retake", "retake cue"
        elif not inside and (j < first_take or k > last_take_end) and len(run) <= 14 and \
                sum(t in SLATE_WORDS for t in content) >= max(1, len(content) // 2):
            kind, reason = "slate", "before the first / after the last line"
        else:
            bg = sum((run[x], run[x + 1]) in script_bigrams for x in range(len(run) - 1))
            near = [owner[k]] if inside else nearest_lines(k)
            best_line, best_ov = None, 0.0
            for li in near:
                T = set(lines_T[li])
                ov = sum(t in T for t in content) / max(1, len(content))
                if ov > best_ov:
                    best_line, best_ov = li, ov
            stutter = len(content) <= 2 and (
                any(c == prev_t or c == next_t for c in content) or
                any(len(c) >= 2 and next_t.startswith(c) and c != next_t for c in content))
            low_conf = all(words[toks[x].w].get("p", 0.9) < 0.4 for x in range(k, j + 1))
            if stutter:
                kind, reason = "flub", "stutter / cut-off word"
            elif not inside and (bg >= 2 or (bg >= 1 and len(content) <= 5) or (best_ov >= 0.6 and len(content) >= 2)):
                kind, reason, ref = "retake", "earlier take / false start", best_line
            elif inside and best_ov >= 0.75 and len(content) >= 2 and bg >= 1:
                kind, reason, ref = "retake", "restart inside the line", best_line
            elif len(content) <= 2 and low_conf:
                kind, reason = "flub", "unclear word"
            elif inside and len(content) == 1:
                kind, reason = "minor", "extra word inside the line"
            else:
                kind, reason = "adlib", "not in the script"
                ref = owner[k] if inside else None
        items.append({"kind": kind, "reason": reason, "t0": k, "t1": j, "inside": inside,
                      "line_ref": ref, "text": " ".join(words[x]["w"] for x in sorted({toks[y].w for y in range(k, j + 1)}))})
        k = j + 1
    return items


# ------------------------------------------------------------------ main entry

def run_align(proj) -> dict:
    script = read_json(proj.work / "script.json")
    if not script:
        raise ManimaticError("Run `mm.py ingest` first.")
    words, toks, files = load_stream(proj)
    if not toks:
        raise ManimaticError("The transcript is empty. Check the audio files.")
    lines = script["lines"]
    lines_T = [[t[0] for t in ln["tokens"]] for ln in lines]
    A = [t.t for t in toks]
    bigrams: dict = defaultdict(list)
    unigrams: dict = defaultdict(list)
    for i, a in enumerate(A):
        unigrams[a].append(i)
        if i + 1 < len(A):
            bigrams[(a, A[i + 1])].append(i)
    cands = [_candidates(li, T, A, bigrams, unigrams) for li, T in enumerate(lines_T)]
    chosen, status = choose_takes(cands)
    pickups = pickup_pass(cands, chosen, status)
    script_bigrams = {(T[x], T[x + 1]) for T in lines_T for x in range(len(T) - 1)}
    items = classify_runs(toks, words, chosen, lines_T, script_bigrams)

    cfg = proj.cfg["cuts"]
    default_cut = {"retake": bool(cfg.get("retakes", True)), "slate": True, "flub": bool(cfg.get("flubs", True)),
                   "filler": bool(cfg.get("fillers", True)), "adlib": cfg.get("adlibs", "keep") == "cut",
                   "minor": False}
    decisions = []
    prefix = {"retake": "C", "slate": "C", "flub": "C", "adlib": "C", "filler": "F", "minor": "M"}
    for it in items:
        w0, w1 = toks[it["t0"]].w, toks[it["t1"]].w
        fi = words[w0]["file"]
        key = f"{fi}:{words[w0]['s']:.2f}:{it['kind']}"
        did = stable_id(proj.work, prefix[it["kind"]], key)
        decisions.append({
            "id": did, "kind": it["kind"], "reason": it["reason"], "file": fi, "file_name": files[fi]["file"],
            "w0": w0, "w1": w1, "start": round(words[w0]["s"], 3), "end": round(words[w1]["e"], 3),
            "text": it["text"], "inside": it["inside"],
            "line_ref": lines[it["line_ref"]]["id"] if it["line_ref"] is not None else None,
            "default": "cut" if default_cut.get(it["kind"], False) else "keep",
            "key": key,
        })
    takes_out = []
    for li, t in enumerate(chosen):
        entry = {"line": lines[li]["id"], "status": status[li], "n_takes": len(cands[li])}
        if t:
            entry.update({"t0": t.i0, "t1": t.i1, "w0": toks[t.i0].w, "w1": toks[t.i1].w,
                          "file": words[toks[t.i0].w]["file"], "start": round(toks[t.i0].s, 3),
                          "end": round(toks[t.i1].e, 3), "coverage": round(t.coverage, 2),
                          "pairs": [[a, b] for a, b in t.pairs]})
            entry["earlier_takes"] = sum(1 for c in cands[li] if c.i1 < t.i0 and c.coverage >= 0.5)
        takes_out.append(entry)
    result = {"takes": takes_out, "decisions": decisions,
              "tokens": [[t.t, t.w, round(t.s, 3), round(t.e, 3)] for t in toks],
              "words": [{k: w[k] for k in ("w", "s", "e", "p", "file")} for w in words],
              "files": files, "pickups": [lines[i]["id"] for i in pickups]}
    write_json(proj.work / "align.json", result, indent=None)
    summary = {
        "lines": len(lines),
        "ok": sum(1 for s in status if s == "ok"),
        "incomplete": [lines[i]["id"] for i, s in enumerate(status) if s == "incomplete"],
        "missing": [lines[i]["id"] for i, s in enumerate(status) if s == "missing"],
        "pickups": result["pickups"],
        "lines_with_retakes": sum(1 for t in takes_out if t.get("earlier_takes")),
        "counts": {k: sum(1 for d in decisions if d["kind"] == k) for k in ("retake", "slate", "flub", "filler", "adlib", "minor")},
    }
    proj.set_state(aligned=True)
    return summary
