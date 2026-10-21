# Demo: Why Primes Matter

This is a small, complete Manimatic project: a script, a recording, an exam paper, an approved `PLAN.md` and finished scene files.

The recording (`audio/session.flac`, a synthetic voice) is deliberately messy. It contains:
- a slate ("okay recording")
- a false start, an um, and an ad-lib
- a flubbed line followed by "sorry, let me say that again"
- an out-of-order pickup of line two at the very end

Manimatic should cut all of these except the ad-lib, which it keeps and flags in PLAN.md.

It also shows:
- a `[[hold 1.5s]]` after line two, which the opening scene fills by pulsing the prime factors
- a camera zoom on the factor tree (`scenes/s01_3.py` uses `ManimaticCameraScene`)
- an exam question cropped from `references/exam2023.pdf`, with words highlighted inside it

## Try it
```bash
cd examples/demo
python3 ../../mm.py prepare          # transcribe, cut, find the exam question, re-time PLAN.md
python3 ../../mm.py build --preview  # 480p preview in output/
python3 ../../mm.py build            # final 1080p60 video, captions, chapters
```
Or open the folder in Claude Code and ask it to build the video.

- **Transcription:** real Whisper transcription downloads a model the first time. To skip that, set `asr_backend = "mock"` in `manimatic.toml`, which uses the bundled `session.flac.words.json` instead.
- **Music:** add `music/bed.*`, `music/intro.*` and `music/outro.*` to hear the ducking and the stings.
