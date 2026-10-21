"""Final output: audio mix, frame-exact assembly, captions and chapters."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from manimatic.util import (ManimaticError, write_json, ffprobe_duration, fmt_time, read_json, require_ffmpeg, run,
                            say, slugify, warn, write_text)

SR = 48000


# ================================================================== mix

def _voice_chain(process: bool) -> str:
    if not process:
        return ""
    # Light touch only: rumble cut, gentle denoise, a little presence, mild compression.
    return ("highpass=f=80,afftdn=nr=8:nf=-40,equalizer=f=3200:t=q:w=1.2:g=1.5,"
            "acompressor=threshold=-20dB:ratio=2:attack=15:release=200:makeup=1.5,")


def measure_lufs(path: Path, start: float = 0.0, dur: float | None = None) -> float:
    """Integrated loudness (LUFS) of a file or a stretch of it; -70 if silent."""
    ff, _ = require_ffmpeg()
    cmd = [ff, "-hide_banner", "-nostats"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    if dur:
        cmd += ["-t", f"{dur:.3f}"]
    p = run(cmd + ["-i", str(path), "-af", "loudnorm=print_format=json", "-f", "null", "-"])
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr.decode("utf-8", "replace"), re.S)
    try:
        v = float(json.loads(m.group(0))["input_i"]) if m else -70.0
    except (ValueError, KeyError):
        v = -70.0
    return v if v > -70 else -70.0


def prepare_bed(proj, bed: Path, voice: Path) -> tuple[Path, float, dict]:
    """Cut the bed from ``[music] bed_start`` and choose its gain by loudness.

    The bed sits ``[music] bed_level`` LU relative to the voice (default -20) before ducking,
    whatever level the track was mastered at. ``bed_level_db`` (a fixed gain), if set, wins.
    """
    ff, _ = require_ffmpeg()
    start = float(proj.get("music", "bed_start") or 0.0)
    src = proj.work / "audio" / "bed_src.wav"
    src.parent.mkdir(parents=True, exist_ok=True)
    total = ffprobe_duration(bed)
    if start >= total - 1.0:
        raise ManimaticError(f"[music] bed_start = {start} is past the end of {bed.name} ({total:.1f} s).")
    run([ff, "-v", "error", "-y", "-ss", f"{start:.3f}", "-i", str(bed), "-ac", "2", "-ar", str(SR),
         "-c:a", "pcm_s16le", str(src)])
    fixed = proj.cfg.get("music", {}).get("bed_level_db")
    bed_lufs = measure_lufs(src)
    voice_lufs = measure_lufs(voice)
    if voice_lufs <= -69:            # silent draft voice: aim the mix as if speech were at -16 LUFS
        voice_lufs = -16.0
    if fixed is not None:
        gain = float(fixed)
        how = "fixed gain ([music] bed_level_db)"
    elif bed_lufs <= -69:
        gain = 0.0
        how = "bed is silent"
    else:
        gain = (voice_lufs + float(proj.get("music", "bed_level"))) - bed_lufs
        gain = max(-40.0, min(20.0, gain))
        how = f"bed {bed_lufs:.1f} LUFS -> {bed_lufs + gain:.1f} LUFS ({proj.get('music', 'bed_level')} LU vs voice {voice_lufs:.1f})"
    return src, gain, {"bed_lufs": round(bed_lufs, 2), "voice_lufs": round(voice_lufs, 2), "how": how,
                       "bed_start": start, "source": bed.name, "loop_len": round(total - start, 3)}


def mix(proj) -> Path:
    ff, _ = require_ffmpeg()
    idx = read_json(proj.work / "scenes.json")
    tl = read_json(proj.work / "timeline.json")
    if not idx or not tl:
        raise ManimaticError("Run `mm.py plan sync` first.")
    meta = idx["meta"]
    T = meta["total"]
    I = meta["voice_offset"]
    end_start = T - meta["end_card"]
    voice = proj.root / tl["voice"]
    if not voice.exists():
        raise ManimaticError(f"Voice track missing: {voice}. Re-run `mm.py cut` (or `mm.py draft`).")
    bed, intro, outro = proj.music_file("bed"), proj.music_file("intro"), proj.music_file("outro")
    inputs = ["-i", str(voice)]
    filt = []
    n = 1
    process = bool(proj.get("voice", "process"))
    ms = int(I * 1000)
    filt.append(f"[0:a]aresample={SR},aformat=channel_layouts=mono,{_voice_chain(process)}"
                f"pan=stereo|c0=c0|c1=c0,adelay={ms}|{ms},apad=whole_dur={T:.3f},atrim=0:{T:.3f}"
                + (",asplit=2[v][vkey]" if bed else "[v]"))
    mix_in = ["[v]"]
    if bed:
        # The bed plays under the voice and under any card without its own sting.
        b0 = I if intro else 0.0
        b1 = min(T, end_start + 1.5) if outro else T
        bed_len = max(1.0, b1 - b0)
        bed_src, gain_db, info = prepare_bed(proj, bed, voice)
        duck = float(proj.get("music", "duck_db"))
        ratio = max(2.0, min(20.0, 10 ** (duck / 20) * 2))
        bms = int(b0 * 1000)
        inputs += ["-stream_loop", "-1", "-i", str(bed_src)]
        filt.append(f"[{n}:a]aresample={SR},aformat=channel_layouts=stereo,atrim=0:{bed_len:.3f},asetpts=PTS-STARTPTS,"
                    f"volume={gain_db:.2f}dB,afade=t=in:st=0:d={1.5 if b0 > 0 else 0.6},"
                    f"afade=t=out:st={max(0, bed_len - 2.5):.3f}:d=2.5,"
                    f"adelay={bms}|{bms},apad=whole_dur={T:.3f},atrim=0:{T:.3f}[bedraw]")
        filt.append("[vkey]aformat=channel_layouts=stereo[key]")
        filt.append(f"[bedraw][key]sidechaincompress=threshold=0.015:ratio={ratio:.1f}:attack=25:release=400:makeup=1[bed]")
        mix_in.append("[bed]")
        n += 1
        write_json(proj.work / "audio" / "bed.json", {**info, "video_start": b0, "video_end": b0 + bed_len,
                                                      "gain_db": round(gain_db, 2)})
    if intro:
        inputs += ["-i", str(intro)]
        il = ffprobe_duration(intro)
        fade_st = max(0.0, I - 0.4) if il > I else max(0.0, il - 0.3)
        filt.append(f"[{n}:a]aresample={SR},aformat=channel_layouts=stereo,afade=t=out:st={fade_st:.3f}:d=0.8,"
                    f"apad=whole_dur={T:.3f},atrim=0:{T:.3f}[intro]")
        mix_in.append("[intro]")
        n += 1
    if outro:
        inputs += ["-i", str(outro)]
        oms = int(end_start * 1000)
        filt.append(f"[{n}:a]aresample={SR},aformat=channel_layouts=stereo,adelay={oms}|{oms},"
                    f"apad=whole_dur={T:.3f},atrim=0:{T:.3f}[outro]")
        mix_in.append("[outro]")
        n += 1
    if len(mix_in) > 1:
        filt.append("".join(mix_in) + f"amix=inputs={len(mix_in)}:normalize=0:dropout_transition=0,atrim=0:{T:.3f}[mix]")
    else:
        filt.append("[v]anull[mix]")
    raw = proj.work / "audio" / "mix_raw.wav"
    raw.parent.mkdir(parents=True, exist_ok=True)
    run([ff, "-v", "error", "-y", *inputs, "-filter_complex", ";".join(filt), "-map", "[mix]",
         "-c:a", "pcm_s24le", "-ar", str(SR), str(raw)])
    # two-pass loudness normalisation
    target = float(proj.get("music", "loudness_lufs"))
    tp = float(proj.get("music", "true_peak_db"))
    p = run([ff, "-hide_banner", "-i", str(raw), "-af", f"loudnorm=I={target}:TP={tp}:LRA=11:print_format=json",
             "-f", "null", "-"])
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr.decode("utf-8", "replace"), re.S)
    out = proj.work / "audio" / "mix.wav"
    if m:
        st = json.loads(m.group(0))
        if float(st.get("input_i", "-70")) > -60:
            af = (f"loudnorm=I={target}:TP={tp}:LRA=11:measured_I={st['input_i']}:measured_TP={st['input_tp']}:"
                  f"measured_LRA={st['input_lra']}:measured_thresh={st['input_thresh']}:offset={st['target_offset']}:"
                  f"linear=true")
            run([ff, "-v", "error", "-y", "-i", str(raw), "-af", af, "-ar", str(SR), "-c:a", "pcm_s24le", str(out)])
            say(f"Mixed audio: {fmt_time(T)}, normalised to {target} LUFS"
                + (f" (bed{' + intro' if intro else ''}{' + outro' if outro else ''})" if (bed or intro or outro) else ""))
            return out
    shutil.copyfile(raw, out)  # silent draft: nothing to normalise
    return out


# ================================================================== captions

def _wrap(text: str, max_chars: int, max_lines: int) -> list[str] | None:
    """Split ``text`` into at most ``max_lines`` lines of at most ``max_chars``, as evenly as
    possible. None if it can't be done (the caller then starts a new cue)."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return [text]
    words = text.split(" ")
    if max_lines < 2:
        return None
    best, best_score = None, 1e9
    for k in range(1, len(words)):
        a, b = " ".join(words[:k]), " ".join(words[k:])
        if len(a) <= max_chars and len(b) <= max_chars:
            score = abs(len(a) - len(b))
            if score < best_score:
                best, best_score = [a, b], score
    if best is None and max_lines > 2:
        for k in range(1, len(words)):
            head = " ".join(words[:k])
            if len(head) > max_chars:
                break
            rest = _wrap(" ".join(words[k:]), max_chars, max_lines - 1)
            if rest:
                return [head] + rest
    return best


def _hard_split(text: str, max_chars: int) -> list[str]:
    """Last resort for a single word longer than a line."""
    return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]


def build_cues(proj) -> list[dict]:
    tl = read_json(proj.work / "timeline.json")
    idx = read_json(proj.work / "scenes.json")
    if not tl or not idx:
        raise ManimaticError("Run `mm.py plan sync` first.")
    off = idx["meta"]["voice_offset"]
    max_chars = int(proj.get("captions", "max_chars"))
    max_lines = int(proj.get("captions", "max_lines"))
    max_cue = float(proj.get("captions", "max_cue"))
    words = [w for w in tl["words"] if w["d"].strip()]
    # Script words that were never heard (runs of zero-length, interpolated times) aren't captioned;
    # isolated ones are kept (usually a word the recogniser misheard).
    zero = [w["e"] - w["s"] <= 1e-3 for w in words]
    keep = []
    for k, w in enumerate(words):
        if zero[k]:
            a = k
            while a > 0 and zero[a - 1]:
                a -= 1
            b = k
            while b + 1 < len(words) and zero[b + 1]:
                b += 1
            if b - a + 1 >= 3 and not tl.get("draft"):
                continue
        keep.append(w)
    words = keep
    cues, cur = [], []

    def flush():
        if cur:
            text = " ".join(w["d"] for w in cur)
            text = re.sub(r"\s+([,.;:!?])", r"\1", text)
            cues.append({"start": cur[0]["s"] + off, "end": cur[-1]["e"] + off, "text": text})
        cur.clear()

    for w in words:
        if cur:
            text = " ".join(x["d"] for x in cur + [w])
            gap = w["s"] - cur[-1]["e"]
            sentence_end = re.search(r"[.!?]['\"”’)]?$", cur[-1]["d"]) is not None
            fits = _wrap(re.sub(r"\s+([,.;:!?])", r"\1", text), max_chars, max_lines) is not None
            if (not fits or w["e"] - cur[0]["s"] > max_cue or gap > 0.8 or
                    (sentence_end and cur[-1]["e"] - cur[0]["s"] > 1.0) or w.get("line") != cur[-1].get("line") and gap > 0.4):
                flush()
        cur.append(w)
    flush()
    for k, c in enumerate(cues):
        nxt = cues[k + 1]["start"] if k + 1 < len(cues) else c["end"] + 1.5
        c["end"] = min(max(c["end"] + 0.25, c["start"] + 1.0), nxt - 0.02)
        c["lines"] = _wrap(c["text"], max_chars, max_lines) or _hard_split(c["text"], max_chars)
    return cues


def _ts(t: float, sep: str) -> str:
    t = max(0.0, t)
    h, rem = divmod(int(round(t * 1000)), 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def write_captions(proj, base: Path) -> tuple[Path, Path]:
    cues = build_cues(proj)
    srt = ["\n".join([str(i), f"{_ts(c['start'], ',')} --> {_ts(c['end'], ',')}", *c["lines"], ""])
           for i, c in enumerate(cues, 1)]
    vtt = ["WEBVTT", ""] + ["\n".join([f"{_ts(c['start'], '.')} --> {_ts(c['end'], '.')}", *c["lines"], ""]) for c in cues]
    sp, vp = base.parent / (base.name + ".srt"), base.parent / (base.name + ".vtt")
    write_text(sp, "\n".join(srt))
    write_text(vp, "\n".join(vtt))
    return sp, vp


# ================================================================== chapters

def chapters(proj) -> list[dict]:
    idx = read_json(proj.work / "scenes.json")
    total = idx["meta"]["total"]
    ch = [dict(c) for c in idx["chapters"]]
    ch[0]["start"] = 0.0
    merged: list[dict] = []
    for k, c in enumerate(ch):
        end = ch[k + 1]["start"] if k + 1 < len(ch) else total
        if merged and end - c["start"] < 10.0:
            continue  # YouTube: every chapter must be at least 10 s; fold short ones into the previous
        merged.append(c)
    for k, c in enumerate(merged):
        c["end"] = merged[k + 1]["start"] if k + 1 < len(merged) else total
    if merged and merged[0]["end"] - merged[0]["start"] < 10.0 and len(merged) > 1:
        merged[1]["start"] = 0.0
        merged.pop(0)
    return merged


def write_chapters(proj, base: Path) -> tuple[Path, Path, list[dict]]:
    ch = chapters(proj)
    txt = "\n".join(f"{fmt_time(c['start'], False).split('.')[0]} {c['title']}" for c in ch) + "\n"
    tp = base.parent / (base.name + ".chapters.txt")
    write_text(tp, txt)
    meta = [";FFMETADATA1", f"title={proj.title}"]
    for c in ch:
        meta += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(c['start'] * 1000)}", f"END={int(c['end'] * 1000)}",
                 f"title={c['title']}"]
    mp = proj.work / "chapters.ffmeta"
    write_text(mp, "\n".join(meta) + "\n")
    if len(ch) < 3:
        warn(f"Only {len(ch)} chapter(s): YouTube needs at least 3 (each 10 s+) to show chapters.")
    return tp, mp, ch


# ================================================================== assemble

# The finished video is BT.709 and says so (what YouTube and players assume for HD). ManimGX
# writes BT.601 (tagged); Manim CE writes BT.601 (untagged): each clip is converted on the way in.
BT709 = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]

def _normalise_clip(proj, src: Path, frames: int, fps: int, w: int, h: int, qname: str) -> Path:
    """Make a scene clip exactly ``frames`` frames at a constant ``fps``.

    ManimGX writes variable-frame-rate video (a still stretch is one long frame) and ends with
    one extra closing frame, so the frame rate is made constant *first* (``fps``), then the clip
    is padded by repeating its last picture (``tpad``) and cut to length (``trim``)."""
    ff, _ = require_ffmpeg()
    out = proj.work / "render" / qname / "norm" / src.name
    out.parent.mkdir(parents=True, exist_ok=True)
    # The container's duration can't be trusted for the pad: ManimGX ends a clip on a still picture
    # that is stored as one frame plus the track's length, which fps= doesn't extend. Pad generously
    # and let trim cut the clip to its exact length.
    pad = frames / fps + 1.0
    run([ff, "-v", "error", "-y", "-i", str(src), "-vf", f"fps={fps},tpad=stop_mode=clone:stop_duration={pad:.3f},"
         f"trim=end_frame={frames},setpts=PTS-STARTPTS,"
         f"scale={w}:{h}:in_color_matrix=auto:out_color_matrix=bt709:out_range=tv", "-frames:v", str(frames),
         "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-profile:v", "high", *BT709,
         "-r", str(fps), "-an", str(out)])
    return out


def _corner_label(proj, src: Path, text: str, w: int, h: int, qname: str) -> Path:
    """Burn a small corner label into the picture (drawn with Pillow: no font setup needed)."""
    from PIL import Image, ImageDraw, ImageFont

    size = max(12, int(h * 0.028))
    try:
        font = ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        font = ImageFont.load_default()
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    l, t, r, b = probe.textbbox((0, 0), text, font=font)
    pad = max(4, size // 3)
    img = Image.new("RGBA", (r - l + 2 * pad, b - t + 2 * pad), (0, 0, 0, 150))
    ImageDraw.Draw(img).text((pad - l, pad - t), text, font=font, fill=(255, 210, 90, 255))
    png = proj.work / "render" / qname / "label.png"
    img.save(png)
    out = src.with_name("video_labelled.mp4")
    m = max(8, int(h * 0.02))
    ff, _ = require_ffmpeg()
    run([ff, "-v", "error", "-y", "-i", str(src), "-i", str(png), "-filter_complex", f"overlay=W-w-{m}:{m}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", *BT709, str(out)])
    return out


def assemble(proj, quality: str | None = None, burn: bool | None = None, preview: bool = False) -> dict:
    ff, _ = require_ffmpeg()
    idx = read_json(proj.work / "scenes.json")
    if not idx:
        raise ManimaticError("Run `mm.py plan sync` first.")
    if preview and not quality:
        quality = "480p15"            # a preview is always the fast quality unless asked otherwise
    qname, _, w, h, fps = proj.quality(quality)
    rdir = proj.work / "render" / qname
    missing = [s["id"] for s in idx["scenes"] if not (rdir / f"{s['id']}.mp4").exists()]
    if missing:
        raise ManimaticError(f"Not rendered at {qname} yet: {', '.join(missing)}. Run `mm.py render --quality {qname}`.")
    clips = []
    for s in idx["scenes"]:
        frames = round(s["end"] * fps) - round(s["start"] * fps)
        clips.append(_normalise_clip(proj, rdir / f"{s['id']}.mp4", frames, fps, w, h, qname))
    lst = proj.work / "render" / qname / "concat.txt"
    def q(path) -> str:  # ffmpeg concat quoting (paths may contain apostrophes)
        return "'" + path.resolve().as_posix().replace("'", "'\\''") + "'"

    write_text(lst, "".join(f"file {q(c)}\n" for c in clips))
    video_only = proj.work / "render" / qname / "video_only.mp4"
    run([ff, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(video_only)])
    label = None
    if idx.get("status") != "approved":
        label = "DRAFT · plan not approved"
    elif idx.get("draft"):
        label = "DRAFT · text-to-speech voice"
    if label:
        video_only = _corner_label(proj, video_only, label, w, h, qname)
    audio = mix(proj)
    from manimatic.audiocheck import check_levels

    try:
        levels = check_levels(proj, audio)
    except Exception as e:  # noqa: BLE001
        levels = {"ok": True, "issues": [], "error": str(e)}
    slug = slugify(proj.title)
    suffix = ".preview" if preview else (".draft" if idx.get("draft") else "")
    base = proj.output_dir / f"{slug}{suffix}"
    proj.output_dir.mkdir(parents=True, exist_ok=True)
    srt, vtt = write_captions(proj, base)
    chap_txt, chap_meta, ch = write_chapters(proj, base)
    final = base.parent / (base.name + ".mp4")
    run([ff, "-v", "error", "-y", "-i", str(video_only), "-i", str(audio), "-i", str(chap_meta),
         "-map", "0:v", "-map", "1:a", "-map_metadata", "2", "-map_chapters", "2",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "320k", "-ar", str(SR), "-movflags", "+faststart",
         str(final)])   # no -shortest: it drops the last few frames; video and mix are the same length
    result = {"video": str(final.relative_to(proj.root)), "captions": [str(srt.relative_to(proj.root)),
              str(vtt.relative_to(proj.root))], "chapters": str(chap_txt.relative_to(proj.root)),
              "duration": ffprobe_duration(final), "quality": qname,
              "audio_issues": [f"{i['what']}: {i['kind']}" for i in levels.get("issues", []) if i["kind"] != "silent (no music)"]}
    burn = proj.get("captions", "burn_in") if burn is None else burn
    if burn:
        burned = base.parent / (base.name + ".captioned.mp4")
        style = "FontName=Latin Modern Roman,FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=1,Outline=1.2,Shadow=0,MarginV=36"
        # run from the output folder so the subtitle path needs no escaping (Windows drive colons)
        run([ff, "-v", "error", "-y", "-i", final.name, "-vf", f"subtitles={srt.name}:force_style='{style}'",
             "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", *BT709, "-c:a", "copy",
             "-movflags", "+faststart", burned.name], cwd=str(final.parent))
        result["captioned"] = str(burned.relative_to(proj.root))
    proj.set_state(assembled=result)
    say(f"Video: {result['video']} ({fmt_time(result['duration'])}, {qname})")
    return result
