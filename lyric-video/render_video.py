"""
render_video.py - render a finished lyric video MP4 (no editing app needed).

  python render_video.py "MySong_lyric_video"            (720p, quick preview)
  python render_video.py "MySong_lyric_video" --hd       (1080p)

Uses the slides from make_slides.py if you made them, otherwise a slowly
shifting colour background. Great for checking the timing before you open
DaVinci, or as a finished video on its own.
"""

import argparse
import json
import os
import textwrap

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FPS = 30
FADE = 0.25  # seconds for each line to fade in / out

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",       # macOS
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arialbd.ttf",                              # Windows
    "C:/Windows/Fonts/segoeuib.ttf",
    "/usr/share/fonts/opentype/inter/Inter-Bold.otf",            # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def get_font(path, size):
    for p in ([path] if path else []) + FONT_CANDIDATES:
        if p and os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def text_card(text, font, width, height):
    """One lyric line as a transparent image, with a soft shadow for readability."""
    rows = textwrap.wrap(text, width=30) or [text]
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    line_h = int(font.size * 1.25)
    y = int(height * 0.80) - line_h * len(rows) // 2
    for row in rows:
        w = draw.textlength(row, font=font)
        draw.text(((width - w) / 2, y), row, font=font, fill=(0, 0, 0, 200))
        y += line_h
    shadow = img.filter(ImageFilter.GaussianBlur(font.size // 6))
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    y = int(height * 0.80) - line_h * len(rows) // 2
    stroke = max(2, font.size // 22)
    for row in rows:
        w = draw.textlength(row, font=font)
        draw.text(((width - w) / 2, y), row, font=font, fill=(255, 255, 255, 255),
                  stroke_width=stroke, stroke_fill=(20, 20, 30, 255))
        y += line_h
    out = Image.alpha_composite(shadow, img)
    arr = np.asarray(out).astype(np.float32)
    return arr[..., :3][..., ::-1].copy(), arr[..., 3:] / 255.0  # BGR, alpha


class Backgrounds:
    def __init__(self, project, width, height):
        self.w, self.h = width, height
        self.slides = []
        path = os.path.join(project, "slides.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.slides = json.load(f)["slides"]
        self.current, self.frames, self.idx = None, None, -1
        yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
        self.yy, self.xx = yy / height, xx / width

    def frame(self, t):
        if self.slides:
            i = max(k for k, s in enumerate(self.slides) if s["start"] <= t + 1e-6) \
                if t >= self.slides[0]["start"] else 0
            if i != self.idx:
                self._open(i)
            local = int((t - self.slides[i]["start"]) * self.slides[i]["fps"])
            while self.pos <= local:
                try:
                    self.last = next(self.frames)
                    self.pos += 1
                except StopIteration:
                    break
            return self.last.copy()
        # Animated gradient: deep purple -> teal -> pink, slowly drifting.
        a = 0.5 + 0.5 * np.sin(t * 0.15 + self.xx * 2.0 + self.yy)
        b = 0.5 + 0.5 * np.sin(t * 0.11 + self.yy * 3.0 + 2.0)
        img = np.stack([90 + 120 * b, 30 + 80 * a, 70 + 90 * (1 - a)], axis=-1)  # BGR
        return img.astype(np.float32)

    def _open(self, i):
        import av
        import cv2
        self.idx = i
        container = av.open(self.slides[i]["file"])

        def gen():
            with container:
                for fr in container.decode(video=0):
                    img = fr.to_ndarray(format="bgr24")
                    if img.shape[1] != self.w:
                        img = cv2.resize(img, (self.w, self.h), interpolation=cv2.INTER_AREA)
                    yield img.astype(np.float32)
        self.frames, self.pos = gen(), 0
        self.last = np.zeros((self.h, self.w, 3), np.float32)


def main():
    p = argparse.ArgumentParser(description="Render a lyric video MP4.")
    p.add_argument("project", help="the *_lyric_video folder")
    p.add_argument("--hd", action="store_true", help="1920x1080 instead of 1280x720")
    p.add_argument("--font", help="path to a .ttf/.otf font to use")
    p.add_argument("--out", help="output file (default: <folder>/lyric_video.mp4)")
    args = p.parse_args()

    import av

    with open(os.path.join(args.project, "lyrics.json"), encoding="utf-8") as f:
        info = json.load(f)
    width, height = (1920, 1080) if args.hd else (1280, 720)
    font = get_font(args.font, int(height * 0.07))
    cards = [text_card(l["text"], font, width, height) for l in info["lines"]]
    lines = info["lines"]
    bg = Backgrounds(args.project, width, height)
    out_path = args.out or os.path.join(args.project, "lyric_video.mp4")
    n_frames = int(info["duration"] * FPS)

    with av.open(out_path, "w") as out, av.open(info["song"]) as song:
        v = out.add_stream("libx264" if "libx264" in av.codecs_available else "mpeg4", rate=FPS)
        v.width, v.height, v.pix_fmt = width, height, "yuv420p"
        if v.codec_context.name == "libx264":
            v.options = {"crf": "20", "preset": "veryfast"}
        a = out.add_stream("aac", rate=48000)
        a.layout = "stereo"
        resampler = av.AudioResampler(format="fltp", layout="stereo", rate=48000)
        audio_frames = song.decode(audio=0)
        audio_time = 0.0

        li = 0
        for k in range(n_frames):
            t = k / FPS
            img = bg.frame(t)
            while li + 1 < len(lines) and lines[li]["end"] <= t:
                li += 1
            line = lines[li] if lines else None
            if line and line["start"] <= t < line["end"]:
                alpha = min(1.0, (t - line["start"]) / FADE, (line["end"] - t) / FADE)
                rgb, mask = cards[li]
                rise = int((1 - alpha) * height * 0.015)
                if rise:
                    rgb, mask = np.roll(rgb, rise, axis=0), np.roll(mask, rise, axis=0)
                m = mask * alpha
                img = img * (1 - m) + rgb * m
            frame = av.VideoFrame.from_ndarray(np.clip(img, 0, 255).astype(np.uint8), format="bgr24")
            for pkt in v.encode(frame):
                out.mux(pkt)
            # keep audio roughly in step with video so the file interleaves nicely
            while audio_time < t + 1.0:
                try:
                    af = next(audio_frames)
                except StopIteration:
                    audio_time = float("inf")
                    break
                af.pts = None
                for rf in resampler.resample(af):
                    audio_time += rf.samples / 48000
                    for pkt in a.encode(rf):
                        out.mux(pkt)
            if k % (FPS * 10) == 0:
                print(f"\r  rendering {k / n_frames:4.0%}", end="", flush=True)
        for pkt in v.encode():
            out.mux(pkt)
        for pkt in a.encode():
            out.mux(pkt)
    print(f"\nSaved {out_path}")


if __name__ == "__main__":
    main()
