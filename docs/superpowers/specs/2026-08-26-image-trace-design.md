# Image → Centerline → G-code — Design

Date: 2026-08-26
Repos: `pcb_ui` (Next.js frontend), `pcb_reader` (FastAPI backend)
Reference (read-only, never modified): `C:\cnc_line_backend\cnc_1line_tracer-main`

## Goal

Accept a raster image of a layout — a photo of a board, exported artwork, a
scan — and turn it into a plotted result on the machine, using the same
preview, board list, and streaming path that `.kicad_pcb` uploads already use.

Today `POST /route` decodes the upload as UTF-8 and parses it as a KiCad
s-expression; anything else fails with `400 Could not parse this file`. This
adds a second entry point that produces the *same* stored board document, so
everything downstream — thumbnails, the projects grid, the detail page, rename,
delete, and print streaming — works with no changes.

## Architecture

```
Uploader (web) ──image──▶ POST /trace ──▶ tracer/              ──▶ build_board_from_strokes
                                          prep → skeletonize        (same document shape
  existing preview ◀── tracks ─────────    → walk graph               as /route produces)
  existing stream  ◀── gcode  ─────────    → smooth/simplify/spline
```

The tracing core is **vendored** into `pcb_reader/tracer/` as pure functions.
The reference project is a CLI: it reads `input\`, writes `output\`, and prints
reports. None of that survives the lift — the server needs bytes in, strokes
out, with no filesystem and no `argparse`.

## Decisions

- **Vendor, do not import.** `C:\cnc_line_backend\cnc_1line_tracer-main` sits
  outside both repos, is not a package, and is not to be touched. Copy the
  algorithmic modules in and keep them importable and testable on their own.
- **Strokes are the stored primitive, tracks are derived.** A traced polyline
  is one continuous pen-down path. Storing it as a list of 2-point `Track`s and
  rebuilding it later would be lossy and fragile (see *Why not reuse
  optimize_order* below). The board document gains a `strokes` field; the
  existing `tracks` field is derived from it purely so `PcbBoard.tsx`,
  thumbnails, and the layer preview keep working untouched.
- **Physical size is a required input, not a guess.** An image has pixels; a
  machine has millimetres. There is no DPI worth trusting in a photo. The user
  gives the longest edge in mm, exactly as the reference tool's `--size` does.
- **Centerline is the default; outline is offered.** For a pen drawing a line,
  centerline is right. For **etch resist on copper**, a centerline down a wide
  trace under-covers it — the resist will not protect the full trace width.
  That is a real physical failure, so the UI names the choice rather than
  hiding it. Hatched filling is out of scope (see Non-goals).
- **Reuse the existing print path.** `/trace` stores G-code on the board the
  way `/route` does. `POST /print` already streams `board["gcode"]` to the
  ESP32 and needs no change at all.

## Components

### 1. Vendored tracer — `pcb_reader/tracer/`

Copied unchanged in algorithm, stripped of CLI and file I/O:

| File | Source | What it keeps |
|---|---|---|
| `centerline.py` | `tools/centerline.py` | `skeleton_mask`, `skeleton_to_polylines`, `to_mm`, `smooth`, `simplify`, `splinify`, `drop_short`, `outline_to_polylines`, `trace` |
| `prep.py` | `tools/prep_image.py` | `otsu`, `choose_threshold`, `bridge_ink`, `despeckle`, `reduce_colors`, `remove_small_blobs`, `prepare` |
| `cv_image.py` | `tools/cv_image.py` | `pcb()` and the adaptive-threshold path |
| `emit.py` | new | strokes → G-code (see 3) |

`prepare()` currently takes a **path**. It gains a sibling taking an
already-loaded `PIL.Image`, and the path version becomes a thin wrapper. Same
for `cv_image.pcb()`. Nothing else changes — the algorithms are sound, and
re-deriving them would only introduce bugs.

New pip deps in `pcb_reader/requirements.txt`: `numpy`, `pillow`,
`scikit-image`, `opencv-python`.

**Preserve these four properties.** They are the difference between a clean
trace and a bad one, and each is easy to destroy while refactoring:

1. `bridge_ink` runs **before** skeletonization. Growing ink first is what
   makes a gappy scanned line come through as one stroke instead of a dash.
2. The order is **thin → smooth → simplify → spline**. Splining before
   simplifying gets the curve thrown away again by the simplifier.
3. `smooth()` pins endpoints (and wraps closed loops) so strokes still meet at
   junctions. Unpinned smoothing pulls strokes apart at every junction.
4. `splinify` uses **centripetal** Catmull-Rom (alpha=0.5) and tests flatness
   at 0.25/0.5/0.75. A skeleton's control points are very unevenly spaced,
   where uniform Catmull-Rom cusps; a midpoint-only flatness test silently
   skips S-shaped spans.

### 2. Trace endpoint — `pcb_reader/server.py`

`POST /trace` — multipart form:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `file` | image | — | png/jpg/bmp/webp |
| `email` | str | — | owner, as `/route` |
| `size_mm` | float | 50 | longest edge; `0` fills the bed |
| `mode` | str | `centerline` | or `outline` |
| `preset` | str | `line` | `line` or `pcb` |
| `threshold` | int? | auto | Otsu + faint-line soften when absent |
| `invert` | bool | false | white-on-black art |

`preset=pcb` applies the reference tool's `--pcb` retune: OpenCV adaptive
threshold (global Otsu cannot cope with uneven lighting across a board),
`smooth=0` to keep real corners sharp, `simplify=0.005`, `min_stroke=0.05` to
keep pad marks, `bridge=1` so genuine gaps between traces are not welded shut,
`draw_feed=600`.

Guards, all returning `400` with a readable message:

- reject non-image content types before decoding
- an image whose long edge exceeds `max_px` (2000) is **downscaled, never
  rejected** — the reference tool already does this
- if tracing yields **zero strokes**, say so and name the likely fix (invert,
  or a different threshold). Silent empty output is the most confusing possible
  failure.
- ink coverage above 35% → succeed, but attach a warning to the response;
  centerline tracing wants thin lines on white

Response: the same `out_board(board, full=True)` document `/route` returns, so
`Uploader` can navigate to `/dashboard/projects/{id}` unchanged.

### 3. Stroke G-code — `pcb_reader/tracer/emit.py`

`generate_from_strokes(strokes, cfg) -> list[str]`.

**Why not reuse `optimize_order` / `generate_gcode`.** Those take 2-point track
pairs and reorder them greedily. Fed the segments of a splined polyline they
would be O(n²) over thousands of segments, and correctness would rest on the
accident that consecutive segments sit zero distance apart. Ordering belongs at
**stroke** level — hundreds of items, and pen-down continuity is structural
rather than emergent.

- greedy nearest-neighbour over stroke **endpoints**, with endpoint flipping,
  starting from a chosen corner — mirrors `optimize_order`'s existing behaviour
- pen up (`G0 Z{pen_up}`) between strokes, pen down (`G1 Z{pen_down} F{z_feed}`)
  to draw, `G1 X.. Y.. F{draw_feed}` along the stroke
- ends with `G0 Z{pen_up}` then `G0 X0 Y0`
- reuses `CONFIG` from `pcb_gcode.py` for feeds and Z heights, so a traced job
  and a routed job plot identically

Also `emit_frame(bbox, cfg)` — the bounding box, pen up. The reference project
runs this before every job to check placement, it costs nothing, and it is the
cheapest way to avoid drawing off the edge of the work. Stored as
`board["frameGcode"]`.

### 4. Board document — `pcb_reader/server.py`

`build_board_from_strokes(strokes, name, filename, source)`:

- translate to origin, compute `width`/`height` from the stroke bounds
- `strokes`: `[[[x, y], ...], ...]` — authoritative, rounded to 3 dp
- `tracks`: derived, one per consecutive point pair, `net="trace"`,
  `layer="F.Cu"`, `w` = the pen width from `CONFIG`. **Derived for rendering
  only** — never the source for G-code.
- `source: "image"` (vs `"kicad"`) so the UI can label it, and so a re-trace
  knows the original parameters
- `traceParams`: the request fields above, stored verbatim, so a board can be
  re-traced with one changed knob instead of re-uploaded
- report fields the detail page already renders: `gcodeLines`, `drawMoves`,
  `travelMoves`, `penUpBefore`, `penUpAfter`, `estMinutes`, `size`
- `fcu` = stroke count, `bcu` = 0, `nets` = 1 — honest values for a
  single-layer pen job, so the existing stat tiles read sensibly

A derived-track count in the thousands is expected. `PcbBoard.tsx` renders one
`<line>` per track, so the detail preview must be checked against a real traced
board before this is called done. If it is slow, the fix is rendering `strokes`
as one `<polyline>` each — both faster and more correct.

### 5. Frontend — `pcb_ui`

- `lib/api.ts`: `Board` gains `strokes?: number[][][]`,
  `source?: "kicad" | "image"`, `traceParams?: TraceParams`,
  `frameGcode?: string`. New `api.trace(file, email, params): Promise<Board>`.
- `components/Uploader.tsx`: `accept` widens to include images. On an image
  pick, reveal a small options panel — size in mm (required), centerline vs
  outline, line vs PCB preset — then call `api.trace` instead of `api.route`.
  The panel appears **only** for images, so the `.kicad_pcb` flow is untouched.
- `app/dashboard/projects/[id]/page.tsx`: when `source === "image"`, show the
  trace parameters and a **Re-trace** control that re-posts with adjusted
  values. Getting a trace right is iterative — threshold and size are guesses
  until you see the result — and re-uploading the file each time is the main
  friction in the reference tool's workflow.
- Layer toggles are meaningless for a single-layer traced board; hide them when
  `source === "image"` rather than showing a dead control.

### 6. Tests — `pcb_reader/tests/`

The reference project ships 97 tests; 96 pass. The one failure
(`test_prep_image.py::test_auto_threshold_pulls_faint_linework_above_the_cut`,
expects 210, gets 195) is a brittle fixture assertion about the soften
heuristic, not a tracing defect. **Port the suite, and fix that assertion to
compute its expected value the way `choose_threshold` does instead of
hard-coding it.**

New tests beyond the ported ones:

- a synthetic image of a known line → exactly one stroke, correct length in mm
  within tolerance
- a filled disc → centerline gives a short spidery skeleton, outline gives one
  closed loop. The mode difference made concrete.
- a two-stroke image → G-code contains exactly two pen-down/pen-up pairs
- `size_mm` scaling: a 100 px square at `size_mm=50` spans 50 mm
- blank / all-black images → 400 with the actionable message, not a stack trace
- `emit_frame` bbox matches the stroke bounds

## Non-goals

- **Hatching / area fill.** Needed for real etch resist on wide traces; a
  separate piece of work with its own geometry problems.
- **Tool-radius offsetting.** This is a pen. There is no radius to offset by —
  which is exactly why the reference project dropped jscut.
- **Multi-layer.** A traced image is one layer.
- **Drill files, pads, netlist recovery.** Tracing recovers geometry, not
  electrical meaning.
- **Replacing the KiCad path.** `/route` stays exactly as it is.
- **Touching `C:\cnc_line_backend\cnc_1line_tracer-main`.** Read-only reference.

## Superseded during implementation

- **Derived `tracks` were removed.** This spec had a traced board store its
  strokes flattened into two-point `Track`s so `PcbBoard.tsx` could render it
  untouched. `PcbBoard` was instead taught to draw strokes as polylines, which
  is truer (a stroke *is* one path), ~60× fewer SVG elements, and makes the
  pen-up overlay exact. The flattened copy then became 1.69 MB of a 2.67 MB
  document that nothing read, so it is gone. Strokes are the only geometry.
- **Size is applied to the finished strokes**, not derived from the bitmap.
  The cleaner crops with a 4 px pad and thinning tapers stroke ends, so a
  bitmap-derived scale made `size_mm` mean "the cropped bitmap's longest edge"
  — about 9% larger than the ink actually drawn.
- **The boards list sends a decimated `thumbStrokes` set**, not full geometry.
  This was not foreseen: a grid of four traced boards was a 4.3 MB response to
  draw four postage stamps. Now 99 KB.
- **Re-trace keeps the source image in GridFS.** The spec assumed re-posting
  the file; keeping it means one click instead of a re-upload per attempt.

## Open decisions

1. **Which backend this lands in.** Written against the current committed
   system: `pcb_reader` FastAPI + MongoDB, accounts, ESP32 bridge. The unstarted
   `2026-08-25-machine-control-slice-1` plan deletes accounts and the dashboard
   and rebuilds around direct USB serial. This spec is compatible with either —
   the tracer is pure functions and the endpoint is thin — but section 5 assumes
   the dashboard exists. If the CNC-workbench direction wins, sections 1–4
   survive unchanged and section 5 is rewritten.
2. **Centerline vs outline default for PCB work.** Speccing `centerline` as the
   default because it is right for pen drawing. If the real use is etch resist,
   the honest default is `outline` plus hatching — and hatching does not exist
   yet.

## Git plan

1. `feat: vendor centerline tracer into pcb_reader` — sections 1 and 6 (ported
   tests green, including the fixed assertion)
2. `feat: stroke g-code emitter and frame output` — section 3
3. `feat: POST /trace endpoint` — sections 2 and 4
4. `feat: image upload and re-trace in the web app` — section 5
5. `docs: image tracing in README` — the two-server run instructions gain the
   image path and the size-in-mm requirement
