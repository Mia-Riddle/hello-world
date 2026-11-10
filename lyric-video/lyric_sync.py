"""
lyric_sync.py - turn a song into timed lyric lines for a lyric video.

  * Have lyrics?   python lyric_sync.py song.m4a --lyrics my_lyrics.txt
  * No lyrics?     python lyric_sync.py song.m4a
                   (it listens to the song and writes the words for you)

It creates a folder next to the song (e.g. "MySong_lyric_video") with:
  lyrics.json   - the timed lines (the DaVinci script reads this)
  lyrics.srt    - the same thing as a subtitle file (drag into any editor)
  lyrics.txt    - just the words, one line per lyric. Fix any mistakes in
                  this file, then run again with  --lyrics <that file>  to
                  re-sync your corrected words (fast: the song is only
                  listened to once and the result is saved).
"""

import argparse
import difflib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def srt_time(seconds):
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def normalize(word):
    return re.sub(r"[^\w']", "", word.lower()).replace("'", "")


def read_lyrics(path):
    with open(path, encoding="utf-8") as f:
        lines = [ln.strip() for ln in f]
    out = []
    for ln in lines:
        # Ignore blank lines and section labels like [Chorus] or (Verse 2)
        if not ln or re.fullmatch(r"[\[(].*[\])]", ln):
            continue
        # "Say what (x2)" -> the line twice
        m = re.search(r"\s*[\[(]\s*x\s*(\d+)\s*[\])]\s*$", ln, re.I)
        repeat = int(m.group(1)) if m else 1
        out += [ln[:m.start()].strip() if m else ln] * repeat
    return out


def words_with_times(segments):
    """Spread each phrase's time across its words (by length) -> [(word, start, end)]."""
    out = []
    for seg in segments:
        words = seg["text"].split()
        if not words:
            continue
        weights = [len(w) + 1 for w in words]
        total = sum(weights)
        t = seg["start"]
        span = seg["end"] - seg["start"]
        for w, wt in zip(words, weights):
            d = span * wt / total
            out.append((w, t, t + d))
            t += d
    return out


# --------------------------------------------------------------------------
# Building on-screen lines
# --------------------------------------------------------------------------
def lines_from_transcript(segments, max_words):
    """No lyrics given: cut the transcript into short, readable lines."""
    lines = []
    for seg in segments:
        words = words_with_times([seg])
        chunk = []
        for i, (w, s, e) in enumerate(words):
            chunk.append((w, s, e))
            ends_phrase = w[-1] in ",.?!;:"
            if len(chunk) >= max_words or (ends_phrase and len(chunk) >= 3) or i == len(words) - 1:
                # Avoid leaving a lonely 1-2 word line at the end of a phrase.
                remaining = len(words) - 1 - i
                if 0 < remaining < 3 and not ends_phrase:
                    continue
                lines.append({"start": chunk[0][1], "end": chunk[-1][2],
                              "text": " ".join(c[0] for c in chunk).strip(" ,;:")})
                chunk = []
    return lines


def lines_from_lyrics(lyric_lines, segments):
    """Lyrics given: line them up against what the song actually sounds like."""
    heard = words_with_times(segments)
    heard_norm = [normalize(w) for w, _, _ in heard]

    lyric_words = []  # (line_index, normalized word)
    for li, line in enumerate(lyric_lines):
        for w in line.split():
            n = normalize(w)
            if n:
                lyric_words.append((li, n))

    matcher = difflib.SequenceMatcher(None, [w for _, w in lyric_words], heard_norm, autojunk=False)
    match_for = {}
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            match_for[block.a + k] = block.b + k

    # Each lyric word gets a time: matched words use the real time,
    # unmatched ones are interpolated between their matched neighbours.
    times = [None] * len(lyric_words)
    for a, b in match_for.items():
        times[a] = (heard[b][1], heard[b][2])
    known = [i for i, t in enumerate(times) if t]
    if not known:
        raise SystemExit("Couldn't match any of your lyrics to the song. "
                         "Is it the right lyrics file / song?")
    for i in range(len(times)):
        if times[i]:
            continue
        prev = max((k for k in known if k < i), default=None)
        nxt = min((k for k in known if k > i), default=None)
        if prev is None:
            t = times[nxt][0] - 0.4 * (nxt - i)
        elif nxt is None:
            t = times[prev][1] + 0.4 * (i - prev)
        else:
            frac = (i - prev) / (nxt - prev)
            t = times[prev][1] + frac * (times[nxt][0] - times[prev][1])
        times[i] = (max(0.0, t), max(0.0, t) + 0.3)

    lines = []
    for li, text in enumerate(lyric_lines):
        idx = [i for i, (l, _) in enumerate(lyric_words) if l == li]
        if not idx:
            continue
        lines.append({"start": times[idx[0]][0], "end": times[idx[-1]][1], "text": text})
    # Every line keeps its own moment on screen, even if it was sung too fast
    # (or too quietly) for the computer to hear it separately.
    for prev, line in zip(lines, lines[1:]):
        if line["start"] < prev["start"] + 0.5:
            line["start"] = prev["start"] + 0.5
            line["end"] = max(line["end"], line["start"] + 0.5)
    matched = len(match_for) / max(1, len(lyric_words))
    return lines, matched


def tidy(lines, song_length, lead_in=0.15, hold=1.5):
    """Show each line slightly early and keep it up until the next one starts."""
    lines = sorted(lines, key=lambda l: l["start"])
    for i, line in enumerate(lines):
        line["start"] = max(0.0, line["start"] - lead_in)
        nxt = lines[i + 1]["start"] - lead_in if i + 1 < len(lines) else song_length
        line["end"] = min(max(line["end"] + hold, line["start"] + 1.0), nxt, song_length)
        line["start"], line["end"] = round(line["start"], 2), round(line["end"], 2)
    return [l for l in lines if l["end"] > l["start"]]


def write_outputs(lines, out_dir, song_path, song_length, language, source):
    os.makedirs(out_dir, exist_ok=True)
    data = {
        "song": os.path.abspath(song_path),
        "duration": round(song_length, 2),
        "language": language,
        "source": source,
        "lines": lines,
    }
    with open(os.path.join(out_dir, "lyrics.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    with open(os.path.join(out_dir, "lyrics.srt"), "w", encoding="utf-8") as f:
        for i, l in enumerate(lines, 1):
            f.write(f"{i}\n{srt_time(l['start'])} --> {srt_time(l['end'])}\n{l['text']}\n\n")
    with open(os.path.join(out_dir, "lyrics.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(l["text"] for l in lines) + "\n")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description="Sync lyrics to a song (or transcribe it).")
    p.add_argument("song", help="the song file (m4a, mp3, wav, ...)")
    p.add_argument("--lyrics", help="a .txt file with your lyrics, one line per on-screen line")
    p.add_argument("--out", help="output folder (default: <song name>_lyric_video next to the song)")
    p.add_argument("--model", default="medium",
                   help="speech model: tiny, base, small, medium (default), or e.g. small.en")
    p.add_argument("--language", help="language code like en, es, ja (default: detect)")
    p.add_argument("--max-words", type=int, default=8,
                   help="longest line when transcribing without lyrics (default 8)")
    p.add_argument("--retranscribe", action="store_true",
                   help="ignore the saved transcript and listen to the song again")
    args = p.parse_args()

    song = os.path.abspath(args.song)
    name = os.path.splitext(os.path.basename(song))[0]
    out_dir = os.path.abspath(args.out or os.path.join(os.path.dirname(song), f"{name}_lyric_video"))
    os.makedirs(out_dir, exist_ok=True)
    cache = os.path.join(out_dir, "transcript.json")

    import whisper_onnx

    audio = whisper_onnx.load_audio(song)
    song_length = len(audio) / whisper_onnx.SAMPLE_RATE

    if os.path.exists(cache) and not args.retranscribe:
        print("Using the saved transcript (add --retranscribe to listen again).")
        with open(cache, encoding="utf-8") as f:
            saved = json.load(f)
        language, segments = saved["language"], saved["segments"]
    else:
        folder = whisper_onnx.ensure_model(args.model, os.path.join(HERE, "models"))
        model = whisper_onnx.Whisper(folder)
        prompt = None
        if args.lyrics:  # hearing the real words first helps with spelling/names
            prompt = " ".join(read_lyrics(args.lyrics))[:400]
        print(f"Listening to the song ({song_length / 60:.1f} min). This takes a while...")
        started = time.time()

        def progress(frac):
            spent = time.time() - started
            left = spent / frac - spent if frac > 0 else 0
            print(f"\r  {frac:4.0%}  (about {left / 60:.0f} min left)   ", end="", flush=True)

        language, segments = model.transcribe_audio(audio, args.language, prompt, progress)
        print()
        with open(cache, "w", encoding="utf-8") as f:
            json.dump({"language": language, "segments": segments}, f, indent=1, ensure_ascii=False)

    if args.lyrics:
        lines, matched = lines_from_lyrics(read_lyrics(args.lyrics), segments)
        print(f"Matched {matched:.0%} of your lyric words to what the song sounds like.")
        if matched < 0.4:
            print("  (That's low - lines may be off. Check the result in the preview.)")
        source = "lyrics"
    else:
        lines = lines_from_transcript(segments, args.max_words)
        source = "transcript"

    lines = tidy(lines, song_length)
    write_outputs(lines, out_dir, song, song_length, language, source)
    print(f"\n{len(lines)} lyric lines written to: {out_dir}")
    for l in lines[:5]:
        print(f"  {srt_time(l['start'])[3:8]}  {l['text']}")
    if len(lines) > 5:
        print("  ...")
    if source == "transcript":
        print("\nTip: fix any wrong words in lyrics.txt, then run again with "
              f'--lyrics "{os.path.join(out_dir, "lyrics.txt")}"')


if __name__ == "__main__":
    main()
