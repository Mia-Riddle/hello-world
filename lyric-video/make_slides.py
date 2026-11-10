"""
make_slides.py - turn your photos into moving, illustrated slides that change
in time with the song.

  python make_slides.py "MySong_lyric_video" --photos "my photos" --style painted

Styles:  photo    - your photo as-is
         painted  - soft painted / watercolour look
         comic    - bold outlines + flat colours, like a comic illustration
         sketch   - pencil sketch with a little colour

Timing: by default the photos are spread evenly across the song, and every
change is nudged onto the start of a lyric line so it feels "on the beat".
To choose yourself, put a file called slides.txt in the photos folder:

    0:00 intro.jpg
    0:45 beach.jpg
    1:30 night-sky.png

Creates  <folder>/slides/slide_01.mp4 ...  and  <folder>/slides.json
"""

import argparse
import json
import os
import re

import cv2
import numpy as np

W, H, FPS = 1920, 1080, 30
CROSSFADE = 0.8  # seconds each slide blends into the next
PHOTO_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic")


# --------------------------------------------------------------------------
# Looks
# --------------------------------------------------------------------------
def stylize(img, style):
    if style == "photo":
        return img
    if style == "painted":
        smooth = cv2.edgePreservingFilter(img, flags=1, sigma_s=60, sigma_r=0.4)
        return cv2.stylization(smooth, sigma_s=60, sigma_r=0.45)
    if style == "comic":
        small = cv2.resize(img, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        for _ in range(4):
            small = cv2.bilateralFilter(small, 9, 60, 60)
        color = cv2.resize(small, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_LINEAR)
        # flatten colours into a few bands
        color = (color // 40) * 40 + 20
        gray = cv2.medianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), 7)
        edges = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 9, 4)
        return cv2.bitwise_and(color, color, mask=edges)
    if style == "sketch":
        _, colour_sketch = cv2.pencilSketch(img, sigma_s=50, sigma_r=0.07, shade_factor=0.06)
        return colour_sketch
    raise SystemExit(f"Unknown style '{style}'. Use photo, painted, comic or sketch.")


def load_photo(path):
    data = np.fromfile(path, dtype=np.uint8)  # works with any characters in the path
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        try:  # HEIC/odd formats via Pillow if available
            from PIL import Image, ImageOps
            pil = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
            img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
        except Exception:
            raise SystemExit(f"Couldn't open {path}")
    return img


def fill_frame(img, scale=1.15):
    """Fit the photo to 16:9 with room to move. Tall photos get a blurred backdrop."""
    tw, th = int(W * scale), int(H * scale)
    h, w = img.shape[:2]
    if w / h < 1.2:  # portrait / square: blurred copy behind, photo in front
        bg = cv2.resize(img, (tw, int(h * tw / w)))
        y = (bg.shape[0] - th) // 2
        bg = cv2.GaussianBlur(bg[max(0, y):max(0, y) + th], (0, 0), 30)
        bg = cv2.resize(bg, (tw, th))
        bg = (bg * 0.55).astype(np.uint8)
        fh = th
        fw = int(w * fh / h)
        fg = cv2.resize(img, (fw, fh), interpolation=cv2.INTER_AREA)
        x = (tw - fw) // 2
        bg[:, x:x + fw] = fg
        return bg
    s = max(tw / w, th / h)
    big = cv2.resize(img, (int(w * s) + 1, int(h * s) + 1), interpolation=cv2.INTER_AREA)
    y, x = (big.shape[0] - th) // 2, (big.shape[1] - tw) // 2
    return big[y:y + th, x:x + tw]


def ken_burns(canvas, t, index):
    """Slow zoom + drift. t goes 0 -> 1 over the slide. Direction alternates."""
    ch, cw = canvas.shape[:2]
    ease = t * t * (3 - 2 * t)
    zoom_in = index % 2 == 0
    base = W / cw  # scale that would show the whole (oversized) canvas
    z = base * (1.03 + 0.10 * (ease if zoom_in else 1 - ease))
    view_w, view_h = W / z, H / z
    max_dx, max_dy = (cw - view_w) / 2, (ch - view_h) / 2
    drift = [(-1, 0), (1, 0), (0, -1), (0, 1)][index % 4]
    cx = cw / 2 + drift[0] * max_dx * (ease - 0.5)
    cy = ch / 2 + drift[1] * max_dy * (ease - 0.5)
    m = np.array([[z, 0, W / 2 - z * cx], [0, z, H / 2 - z * cy]], dtype=np.float32)
    return cv2.warpAffine(canvas, m, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


# --------------------------------------------------------------------------
# Timing
# --------------------------------------------------------------------------
def parse_time(text):
    parts = [float(p) for p in text.split(":")]
    secs = 0.0
    for p in parts:
        secs = secs * 60 + p
    return secs


def plan(photos_dir, lyrics, duration):
    manual = os.path.join(photos_dir, "slides.txt")
    if os.path.exists(manual):
        plan = []
        with open(manual, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"\s*([\d:.]+)\s+(.+?)\s*$", line)
                if m:
                    plan.append((parse_time(m.group(1)), os.path.join(photos_dir, m.group(2))))
        plan.sort()
        if not plan:
            raise SystemExit("slides.txt is empty or not in the '0:45 photo.jpg' format.")
        plan[0] = (0.0, plan[0][1])
        return plan

    photos = sorted(f for f in os.listdir(photos_dir) if f.lower().endswith(PHOTO_EXT))
    if not photos:
        raise SystemExit(f"No photos found in {photos_dir}")
    starts = [l["start"] for l in lyrics] if lyrics else []
    slot = duration / len(photos)
    plan = []
    for i, name in enumerate(photos):
        t = i * slot
        if i and starts:  # snap to the nearest lyric line if one is close
            near = min(starts, key=lambda s: abs(s - t))
            if abs(near - t) < slot * 0.35:
                t = near
        plan.append((round(t, 2), os.path.join(photos_dir, name)))
    return plan


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------
def write_clip(path, frames_fn, n_frames):
    import av
    with av.open(path, "w") as out:
        codec = "libx264" if "libx264" in av.codecs_available else "mpeg4"
        stream = out.add_stream(codec, rate=FPS)
        stream.width, stream.height, stream.pix_fmt = W, H, "yuv420p"
        if codec == "libx264":
            stream.options = {"crf": "18", "preset": "medium"}
        else:
            stream.bit_rate = 20_000_000
        for i in range(n_frames):
            frame = av.VideoFrame.from_ndarray(frames_fn(i), format="bgr24")
            for pkt in stream.encode(frame):
                out.mux(pkt)
        for pkt in stream.encode():
            out.mux(pkt)


def main():
    p = argparse.ArgumentParser(description="Make illustrated photo slides for a lyric video.")
    p.add_argument("project", help="the *_lyric_video folder made by lyric_sync.py")
    p.add_argument("--photos", required=True, help="folder with your photos")
    p.add_argument("--style", default="painted", help="photo, painted, comic or sketch")
    args = p.parse_args()

    with open(os.path.join(args.project, "lyrics.json"), encoding="utf-8") as f:
        info = json.load(f)
    duration = info["duration"]
    schedule = plan(args.photos, info["lines"], duration)
    out_dir = os.path.join(args.project, "slides")
    os.makedirs(out_dir, exist_ok=True)

    print(f"Preparing {len(schedule)} photos in '{args.style}' style...")
    canvases = [fill_frame(stylize(load_photo(path), args.style)) for _, path in schedule]

    slides = []
    for i, (start, path) in enumerate(schedule):
        end = schedule[i + 1][0] if i + 1 < len(schedule) else duration
        n = max(1, int(round((end - start) * FPS)))
        fade = int(CROSSFADE * FPS) if i + 1 < len(schedule) else 0
        nxt_first = ken_burns(canvases[i + 1], 0.0, i + 1) if fade else None

        def frame(k, i=i, n=n, fade=fade, nxt_first=nxt_first):
            img = ken_burns(canvases[i], k / max(1, n - 1), i)
            if fade and k >= n - fade:  # blend into the next slide's first frame
                a = (k - (n - fade) + 1) / fade
                img = cv2.addWeighted(img, 1 - a, nxt_first, a, 0)
            if i == 0 and k < FPS:      # fade up from black at the very start
                img = (img * (k / FPS)).astype(np.uint8)
            if not fade and k >= n - FPS:  # fade out at the very end
                img = (img * ((n - 1 - k) / FPS)).astype(np.uint8)
            return img

        clip = os.path.join(out_dir, f"slide_{i + 1:02d}.mp4")
        print(f"  slide {i + 1}/{len(schedule)}: {os.path.basename(path)}  "
              f"{int(start // 60)}:{start % 60:04.1f} -> {int(end // 60)}:{end % 60:04.1f}")
        write_clip(clip, frame, n)
        slides.append({"file": os.path.abspath(clip), "photo": os.path.abspath(path),
                       "start": start, "end": round(end, 2), "frames": n, "fps": FPS})

    with open(os.path.join(args.project, "slides.json"), "w", encoding="utf-8") as f:
        json.dump({"fps": FPS, "width": W, "height": H, "slides": slides}, f, indent=2)
    print(f"Done! Slides are in {out_dir}")


if __name__ == "__main__":
    main()
