#!/usr/bin/env python
"""
Lyric Video Builder - a DaVinci Resolve script.

Run it from inside Resolve:  Workspace > Scripts > Lyric Video Builder

It asks for the "<song>_lyric_video" folder made by lyric_sync.py and builds
a new timeline with:
  V1  your illustrated photo slides (if you made them with make_slides.py)
  V2  one Text+ title per lyric line, timed to the song
  A1  the song

Want your own font / colour / animation for the lyrics?
  1. In the Edit page, drag a Text+ title from Effects > Titles onto any
     timeline, style it however you like (font, size, glow, animation...).
  2. Drag that title from the timeline into the Media Pool.
  3. Rename the Media Pool clip to:  Lyric Style
Every lyric line will then be a copy of your styled title. Without a
"Lyric Style" clip, the lyrics are added as subtitles instead (still synced,
and you can style them in the Inspector).

Messages are shown in Workspace > Console.
"""

import json
import os

TEMPLATE_NAME = "Lyric Style"
# If the folder picker doesn't appear on your system, paste the folder path here:
PROJECT_FOLDER = ""


def log(msg):
    print("[Lyric Video] " + msg)


def get_resolve():
    try:
        return resolve  # noqa: F821  (provided by Resolve when run from its menu)
    except NameError:
        pass
    try:
        return bmd.scriptapp("Resolve")  # noqa: F821
    except NameError:
        import DaVinciResolveScript as dvr  # running from a terminal (Studio)
        return dvr.scriptapp("Resolve")


def pick_folder(res):
    if PROJECT_FOLDER:
        return PROJECT_FOLDER
    try:
        fu = res.Fusion()
        path = fu.RequestDir("", {"FReqS_Title": "Choose your  _lyric_video  folder"})
        if path:
            return str(path)
    except Exception as e:
        log("Folder picker unavailable (%s)." % e)
    return None


def all_clips(folder):
    for clip in folder.GetClipList() or []:
        yield clip
    for sub in folder.GetSubFolderList() or []:
        for clip in all_clips(sub):
            yield clip


def find_template(media_pool):
    for clip in all_clips(media_pool.GetRootFolder()):
        if clip.GetName().strip().lower() == TEMPLATE_NAME.lower():
            return clip
    return None


def unique_timeline_name(project, base):
    names = {project.GetTimelineByIndex(i).GetName()
             for i in range(1, project.GetTimelineCount() + 1)}
    name, n = base, 2
    while name in names:
        name, n = "%s %d" % (base, n), n + 1
    return name


def set_text(item, text):
    comp = item.GetFusionCompByIndex(1)
    if not comp:
        return False
    tools = comp.GetToolList(False, "TextPlus") or {}
    for tool in tools.values():
        tool.SetInput("StyledText", text)
    return bool(tools)


def main():
    res = get_resolve()
    project = res.GetProjectManager().GetCurrentProject()
    if not project:
        log("Open or create a project first.")
        return

    folder = pick_folder(res)
    if not folder:
        log("No folder chosen. (Tip: set PROJECT_FOLDER at the top of this script.)")
        return
    lyrics_path = os.path.join(folder, "lyrics.json")
    if not os.path.exists(lyrics_path):
        log("No lyrics.json in %s - run lyric_sync.py first." % folder)
        return
    with open(lyrics_path, encoding="utf-8") as f:
        lyrics = json.load(f)
    slides = []
    slides_path = os.path.join(folder, "slides.json")
    if os.path.exists(slides_path):
        with open(slides_path, encoding="utf-8") as f:
            slides_info = json.load(f)
        slides = slides_info["slides"]
        # A brand-new project can be switched to match the slides.
        if project.GetTimelineCount() == 0:
            project.SetSetting("timelineFrameRate", str(slides_info["fps"]))
            project.SetSetting("timelineResolutionWidth", str(slides_info["width"]))
            project.SetSetting("timelineResolutionHeight", str(slides_info["height"]))

    song_name = os.path.splitext(os.path.basename(lyrics["song"]))[0]
    media_pool = project.GetMediaPool()
    template = find_template(media_pool)

    # Put everything in its own bin.
    bin_ = media_pool.AddSubFolder(media_pool.GetRootFolder(), "Lyric Video - " + song_name)
    if bin_:
        media_pool.SetCurrentFolder(bin_)

    song_items = media_pool.ImportMedia([lyrics["song"]])
    if not song_items:
        log("Couldn't import the song: %s" % lyrics["song"])
        return
    slide_items = media_pool.ImportMedia([s["file"] for s in slides]) if slides else []

    timeline = media_pool.CreateEmptyTimeline(unique_timeline_name(project, song_name + " - Lyric Video"))
    project.SetCurrentTimeline(timeline)
    fps = float(timeline.GetSetting("timelineFrameRate") or project.GetSetting("timelineFrameRate") or 24)
    start = timeline.GetStartFrame()
    while timeline.GetTrackCount("video") < 2:
        timeline.AddTrack("video")

    def at(seconds):
        return start + int(round(seconds * fps))

    # --- V1: photo slides ---------------------------------------------------
    if slide_items:
        by_path = {}
        for item in slide_items:
            by_path[os.path.normcase(item.GetClipProperty("File Path"))] = item
        infos = []
        for s in slides:
            item = by_path.get(os.path.normcase(s["file"]))
            if not item:
                continue
            length = at(s["end"]) - at(s["start"])  # in timeline frames
            src_frames = int(round(length * s["fps"] / fps))
            infos.append({"mediaPoolItem": item, "startFrame": 0,
                          "endFrame": max(0, min(s["frames"], src_frames) - 1),
                          "trackIndex": 1, "recordFrame": at(s["start"]), "mediaType": 1})
        placed = media_pool.AppendToTimeline(infos) or []
        log("Added %d photo slides." % len(placed))
    else:
        log("No slides.json found - skipping photos (run make_slides.py to add them).")

    # --- A1: the song -------------------------------------------------------
    media_pool.AppendToTimeline([{"mediaPoolItem": song_items[0], "trackIndex": 1,
                                  "recordFrame": start, "mediaType": 2}])

    # --- V2: lyrics ---------------------------------------------------------
    lines = lyrics["lines"]
    if template:
        infos = []
        for line in lines:
            length = max(1, at(line["end"]) - at(line["start"]))
            infos.append({"mediaPoolItem": template, "startFrame": 0, "endFrame": length - 1,
                          "trackIndex": 2, "recordFrame": at(line["start"])})
        items = media_pool.AppendToTimeline(infos) or []
        ok = sum(1 for item, line in zip(items, lines) if set_text(item, line["text"]))
        log("Added %d lyric titles using your '%s' style." % (ok, TEMPLATE_NAME))
    else:
        srt = os.path.join(folder, "lyrics.srt")
        timeline.AddTrack("subtitle")
        subs = media_pool.ImportMedia([srt]) or []
        placed = media_pool.AppendToTimeline([{"mediaPoolItem": subs[0], "recordFrame": start}]) if subs else None
        if placed:
            log("Added the lyrics as subtitles. (Make a Text+ clip named '%s' in the "
                "Media Pool for fancier lyrics.)" % TEMPLATE_NAME)
        else:
            log("Couldn't place subtitles automatically. Drag lyrics.srt from the Media Pool "
                "onto the timeline at 00:00, or use File > Import > Subtitle.")

    log("Done! Timeline '%s' is ready." % timeline.GetName())


main()
