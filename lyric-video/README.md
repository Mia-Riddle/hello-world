# 🎤 Lyric Video Maker (for DaVinci Resolve)

Turn a song into a synced lyric video, with your photos as illustrated,
slowly-moving background slides.

- **Have lyrics?** It lines your words up with the song.
- **No lyrics?** It listens to the song and writes them out for you.
- **Have photos?** It turns them into painted / comic / sketch-style slides that
  change on lyric lines.
- Then one click inside DaVinci Resolve builds the whole timeline.

You can also skip Resolve entirely and render a finished MP4.

---

## 1. One-time setup

1. Install **Python 3.10 or newer** from <https://www.python.org/downloads/>
   (on Windows tick **"Add Python to PATH"** during install).
2. Open a terminal (Mac: *Terminal*, Windows: *PowerShell*) in this
   `lyric-video` folder and run:

   ```
   pip install -r requirements.txt
   ```

The first time you transcribe, a speech model (~1 GB) downloads automatically
from GitHub into `lyric-video/models/`. That only happens once.

## 2. Sync the lyrics

```
python lyric_sync.py "path/to/MySong.m4a"
```

…or, if you have written lyrics (a `.txt` file, one on-screen line per line —
blank lines and labels like `[Chorus]` are ignored):

```
python lyric_sync.py "path/to/MySong.m4a" --lyrics "my_lyrics.txt"
```

This makes a folder next to the song called `MySong_lyric_video` with
`lyrics.json`, `lyrics.srt` and `lyrics.txt`.

> **Fixing words:** the computer won't hear every word perfectly when there's
> music behind the vocals. Open `lyrics.txt`, fix anything that's wrong (you can
> also split or join lines), save it, then run again with
> `--lyrics "MySong_lyric_video/lyrics.txt"`. The second run takes seconds
> because the song was only listened to once.

## 3. Make the photo slides (optional)

Put your photos in a folder, then:

```
python make_slides.py "path/to/MySong_lyric_video" --photos "path/to/my photos" --style painted
```

| `--style`  | look |
|------------|------|
| `painted`  | soft painted / watercolour (default) |
| `comic`    | bold outlines + flat colours |
| `sketch`   | coloured-pencil sketch |
| `photo`    | your photo untouched |

Photos are used in alphabetical order and spread across the song, each change
landing on the start of a lyric line. To choose exactly when each photo
appears, add a `slides.txt` inside your photos folder:

```
0:00 intro.jpg
0:45 beach.jpg
1:30 night-sky.png
```

## 4a. Build it in DaVinci Resolve

**Install the script (one time).** Copy `resolve/Lyric Video Builder.py` into:

| System  | Folder |
|---------|--------|
| Mac     | `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/` |
| Windows | `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\` |
| Linux   | `~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/` |

Restart Resolve.

**Use it.** Open a project, then **Workspace → Scripts → Lyric Video Builder**
and pick your `MySong_lyric_video` folder. You get a new timeline with:

- **V1** – your slides
- **V2** – the lyrics, one title per line
- **A1** – the song

**Make the lyrics look how you want:** drag a **Text+** title (Effects →
Titles) onto any timeline, style it (font, colour, glow, animation…), drag it
into the Media Pool and rename it **`Lyric Style`**. Run the script again and
every lyric line will copy that look. Without a `Lyric Style` clip the lyrics
come in as subtitles instead.

If nothing seems to happen, open **Workspace → Console** to see messages.
(If the folder picker doesn't appear, paste your folder path into
`PROJECT_FOLDER = ""` at the top of the script.)

## 4b. …or render an MP4 directly

```
python render_video.py "path/to/MySong_lyric_video"        # 720p preview
python render_video.py "path/to/MySong_lyric_video" --hd   # 1080p
```

Saves `lyric_video.mp4` inside the folder.

---

### How it works (for the curious)

- `whisper_onnx.py` – runs OpenAI's Whisper speech-recognition model (the
  ONNX version from the [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)
  project) and asks it for **timestamps**, so every phrase knows when it's sung.
- `lyric_sync.py` – if you gave lyrics, it matches your words to the words it
  heard (like a "spot the difference") and copies the timing over.
- `make_slides.py` – OpenCV filters for the illustrated look + a slow
  "Ken Burns" zoom/pan and cross-fades.
- `resolve/Lyric Video Builder.py` – talks to Resolve's scripting API to
  import everything and place it on a timeline.
