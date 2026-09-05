# PC Editing Readiness & Budget Tool

A personal alternative to sites like UserBenchmark. It doesn't compare your
PC to a mystery global database or push you toward whatever a site gets
affiliate commission on. Instead it:

1. **Scans** your actual CPU, RAM, GPU, and drives.
2. **Benchmarks** them with a few quick, honest local tests (no upload, ever).
3. Asks about **your actual editing workflow** (resolution, codec, multicam,
   grading intensity -- e.g. "documentary, 4K H.265 from a mirrorless
   camera, single cam, moderate grading") and computes what that workflow
   actually needs, using transparent formulas you can open and read.
4. Tells you which parts are holding you back and **why**, in plain numbers.
5. Suggests **specific upgrade parts with prices** from an editable catalog,
   and totals the cost.
6. **Saves builds** over time so you can track progress after an upgrade.
7. **Exports an aesthetic budget spreadsheet (.xlsx)** you can actually plan
   a purchase from.

Everything runs locally on your machine. Nothing is uploaded anywhere.

## Setup (first time only)

You'll need Python 3.9+. From this folder (`pc_benchmark_toolkit/`), run:

```
pip install -r requirements.txt
```

## Running it

```
python main.py
```

You'll get a numbered menu -- just type a number and press Enter. A typical
first run looks like: `1` (scan) → `2` (benchmark) → `3` (answer a few
questions about your documentary edit) → `4` (see what to buy) → `5` (save
this build) → `6` (export the spreadsheet).

### What each option does

- **1) Scan my PC hardware** -- detects CPU, RAM, drives, and (best-effort)
  GPU. GPU VRAM can't always be auto-detected without vendor tools or admin
  rights -- if it says "unknown," you'll be asked to type it in (check your
  GPU's box, receipt, or `Task Manager > Performance > GPU` on Windows /
  `About This Mac > System Report` on macOS).
- **2) Run benchmark tests** -- runs a ~2-3 second CPU test, a memory
  bandwidth test, and a disk speed test. The disk test writes a temporary
  ~512MB file to a folder you choose and deletes it immediately afterward --
  point it at your actual footage/scratch drive, not just your OS drive,
  since that's the number that actually matters for editing.
- **3) Tell it about my editing workflow** -- a few quick questions
  (resolution, codec, camera angles, grading intensity). This is where the
  tool is tailored specifically to *your* documentary, not a generic score.
  It prints exactly why it landed on each target, then a PASS/WARN/FAIL per
  component.
- **4) See upgrade suggestions + total cost** -- for anything that WARNed or
  FAILed, it picks the cheapest catalog part that clears the target, and
  gives you shopping search links (not a single guessed product page, so the
  link stays useful even if a specific listing changes).
- **5) Save this build** -- writes a timestamped JSON snapshot to
  `saved_builds/`. Do this before and after an upgrade to see the difference
  in benchmark numbers over time.
- **6) Export a budget spreadsheet** -- produces a 3-tab `.xlsx`: a Summary
  (pass/fail at a glance + total cost), your Current Build spec sheet, and
  an Upgrade Budget sheet with a "Buy?" Yes/No dropdown per row and a live
  total formula.
- **7) Load a previously saved build** -- see an older scan's verdicts again.

## Making it your own

This tool is deliberately not a black box -- that's the whole point, given
the reputation UserBenchmark has picked up. Two files are meant to be edited:

- `pc_benchmark/data/workload_rules.json` -- the formulas that turn "4K,
  H.265, 1 camera, moderate grading" into concrete thread/RAM/VRAM/storage
  targets. If your real-world experience disagrees with a verdict, the
  numbers to adjust are here, not hidden in code.
- `pc_benchmark/data/parts_catalog.json` -- the upgrade parts and prices it
  suggests from. Prices are ballpark estimates as of the `last_verified`
  date in that file -- edit them to match current prices, or add/remove
  parts entirely. It's just JSON.

## Running the tests

```
pytest
```

These test the scoring/requirements math directly (not your specific
hardware), so they'll pass on any machine.

## Notes

- GPU compute performance (as opposed to VRAM capacity) isn't precisely
  benchmarked here -- that needs vendor SDKs (CUDA/OpenCL) this tool
  intentionally avoids depending on, to stay lightweight and cross-platform.
  VRAM capacity is used as the practical stand-in, since running out of it
  is what actually causes dropped effects/crashes in NLEs.
- The CPU/RAM benchmark numbers (MB/s hashing, GB/s memory copy) don't have
  a universal "good" threshold the way storage speed does (storage is
  checked against real footage bitrate math). Treat them as your own
  baseline to compare against after a future upgrade, not an absolute score.
