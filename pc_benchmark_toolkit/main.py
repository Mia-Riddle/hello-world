"""Interactive entry point. Run with: python main.py

No flags to memorize -- just pick a number from the menu.
"""
from __future__ import annotations

import sys
from pathlib import Path

from pc_benchmark import benchmarks, build_store, catalog, scanner, scoring, workload, xlsx_export

RESOLUTIONS = ["1080p", "1440p", "4k", "5k", "6k", "8k"]
CODECS = {
    "1": ("h264_h265_long_gop", "H.264 / H.265 (long-GOP) -- typical mirrorless/DSLR footage"),
    "2": ("prores_dnxhr", "ProRes / DNxHR -- intermediate or high-end camera codec"),
    "3": ("raw_braw_red", "RAW -- BRAW / RED / ARRIRAW"),
}
GRADING = {"1": "light", "2": "moderate", "3": "heavy"}
STATUS_LABEL = {"GOOD": "PASS", "WARN": "WARN", "BAD": "FAIL", "INFO": "INFO"}


def ask(prompt, choices=None, default=None):
    while True:
        raw = input(prompt).strip()
        if not raw and default is not None:
            return default
        if choices is None or raw in choices:
            return raw
        print(f"  Please enter one of: {', '.join(choices)}")


def ask_workflow() -> workload.WorkflowAnswers:
    print("\nA few questions about what you're actually editing right now:\n")
    print("Resolution: " + ", ".join(RESOLUTIONS))
    resolution = ask("> ", choices=RESOLUTIONS, default="4k")

    print("\nFootage codec:")
    for k, (_, label) in CODECS.items():
        print(f"  {k}) {label}")
    codec_choice = ask("> ", choices=list(CODECS.keys()), default="1")
    codec = CODECS[codec_choice][0]

    streams_raw = ask("\nHow many camera angles are you syncing/editing at once (1 if single-cam)? > ", default="1")
    try:
        streams = max(1, int(streams_raw))
    except ValueError:
        streams = 1

    print("\nHow heavy is your grading/effects work?")
    print("  1) Light -- basic color correction")
    print("  2) Moderate -- secondary color, LUTs, light noise reduction")
    print("  3) Heavy -- heavy noise reduction, retiming, Fusion/heavy effects")
    grading_choice = ask("> ", choices=list(GRADING.keys()), default="2")

    return workload.WorkflowAnswers(
        resolution=resolution, codec=codec, multicam_streams=streams,
        grading_intensity=GRADING[grading_choice],
    )


def print_snapshot(snap):
    print("\n--- Detected hardware ---")
    print(f"OS:      {snap.os_name}")
    ghz = f", {snap.cpu_max_ghz}GHz max" if snap.cpu_max_ghz else ""
    print(f"CPU:     {snap.cpu_name} ({snap.physical_cores}c/{snap.logical_cores}t{ghz})")
    print(f"RAM:     {snap.ram_total_gb} GB")
    vram = f" -- {snap.gpu_vram_gb}GB VRAM" if snap.gpu_vram_gb else " -- VRAM unknown"
    print(f"GPU:     {snap.gpu_name}{vram}")
    print("Drives:")
    for d in snap.disks:
        print(f"  {d.device} ({d.mountpoint}) -- {d.total_gb} GB, {d.fstype}")


def maybe_fill_gpu_vram(snap):
    if snap.gpu_vram_gb is not None:
        return
    print(f"\nCouldn't auto-detect VRAM for '{snap.gpu_name}'.")
    raw = ask("Enter VRAM in GB (or press Enter to skip): > ", default="")
    if raw:
        try:
            snap.gpu_vram_gb = float(raw)
        except ValueError:
            print("  Not a number, skipping.")


def print_evaluation(evaluation):
    print("\n--- How your PC stacks up against THIS workflow ---")
    for v in evaluation.verdicts:
        print(f"[{STATUS_LABEL[v.status.value]}] {v.category}: {v.summary}")
        print(f"        {v.detail}")


def print_suggestions(suggestions):
    if not suggestions:
        print("\nNo bottlenecks found for this workflow -- nothing to buy right now.")
        return
    print("\n--- Suggested upgrades ---")
    for s in suggestions:
        print(f"\n{s.category}: {s.part_name} (~${s.price_usd:.0f})")
        print(f"  Why: {s.reason}")
        if s.note:
            print(f"  Note: {s.note}")
        for store, url in s.shop_links.items():
            print(f"  {store}: {url}")
    print(f"\nEstimated total: ${catalog.total_cost(suggestions):.2f}  (verify current prices before buying)")


def do_export(session):
    builds = build_store.list_builds()
    data = None
    if builds and ask(f"\nExport your most recently saved build ('{builds[0].stem}')? (y/n) > ",
                       choices=["y", "n"], default="y") == "y":
        data = build_store.load_build(builds[0])
    elif "evaluation" in session:
        name = ask("Name for this export: > ", default="My PC")
        path = build_store.save_build(
            name, session["snapshot"], session["bench"], session["answers"],
            session["req"], session["evaluation"], session["suggestions"],
        )
        data = build_store.load_build(path)
    else:
        print("Nothing to export yet -- run option 3 first, or save a build (5).")
        return
    out_name = ask("Output filename: > ", default="pc_budget_report.xlsx")
    out_path = xlsx_export.export_build_to_xlsx(data, out_name)
    print(f"Exported to {out_path}")


def main():
    session = {}

    while True:
        print("\n===== PC Editing Readiness & Budget Tool =====")
        print("1) Scan my PC hardware")
        print("2) Run benchmark tests (needs a scan first)")
        print("3) Tell it about my editing workflow + see the verdict")
        print("4) See upgrade suggestions + total cost")
        print("5) Save this build")
        print("6) Export a budget spreadsheet (.xlsx)")
        print("7) Load a previously saved build")
        print("0) Exit")
        choice = input("> ").strip()

        if choice == "1":
            session["snapshot"] = scanner.scan_hardware()
            print_snapshot(session["snapshot"])
            maybe_fill_gpu_vram(session["snapshot"])

        elif choice == "2":
            if "snapshot" not in session:
                print("Scan your PC first (option 1).")
                continue
            target = ask("\nWhich folder should the disk test write to? "
                          "(point this at your footage/scratch disk) > ", default=str(Path.cwd()))
            print("Running benchmarks (a few seconds)...")
            session["bench"] = benchmarks.run_all_benchmarks(target)
            b = session["bench"]
            print(f"CPU hashing: {b.cpu_hash_mb_per_sec} MB/s | RAM copy: {b.ram_copy_gb_per_sec} GB/s | "
                  f"Disk write: {b.disk_write_mb_per_sec} MB/s | Disk read: {b.disk_read_mb_per_sec} MB/s")

        elif choice == "3":
            if "snapshot" not in session or "bench" not in session:
                print("Run a scan (1) and benchmark (2) first.")
                continue
            answers = ask_workflow()
            req = workload.compute_requirements(answers)
            evaluation = scoring.evaluate(session["snapshot"], session["bench"], req)
            print("\n--- Why these targets ---")
            for line in req.demand_explanation:
                print(f"  - {line}")
            print_evaluation(evaluation)
            session["answers"], session["req"], session["evaluation"] = answers, req, evaluation
            session["suggestions"] = catalog.suggest_upgrades(evaluation, session["snapshot"], req)

        elif choice == "4":
            if "suggestions" not in session:
                print("Run option 3 first so there's something to evaluate.")
                continue
            print_suggestions(session["suggestions"])

        elif choice == "5":
            if "evaluation" not in session:
                print("Run option 3 first.")
                continue
            name = ask("\nName this build (e.g. 'My Desktop - Sept 2026'): > ", default="My PC")
            path = build_store.save_build(
                name, session["snapshot"], session["bench"], session["answers"],
                session["req"], session["evaluation"], session["suggestions"],
            )
            print(f"Saved to {path}")

        elif choice == "6":
            do_export(session)

        elif choice == "7":
            builds = build_store.list_builds()
            if not builds:
                print("No saved builds yet.")
                continue
            for i, b in enumerate(builds):
                print(f"  {i}) {b.name}")
            idx = ask("Pick a number: > ", choices=[str(i) for i in range(len(builds))], default="0")
            data = build_store.load_build(builds[int(idx)])
            print(f"\nLoaded '{data['name']}' (saved {data['saved_at']})")
            for v in data["evaluation"]:
                print(f"[{STATUS_LABEL[v['status']]}] {v['category']}: {v['summary']}")

        elif choice == "0":
            print("Bye!")
            sys.exit(0)

        else:
            print("Not a valid option.")


if __name__ == "__main__":
    main()
