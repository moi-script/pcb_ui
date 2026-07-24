# Board Conveniences — Design

Date: 2026-07-24
Repos: `pcb_ui` (Next.js frontend), `pcb_reader` (FastAPI + MongoDB backend)

## Goal

Add four convenience features across the dashboard while keeping the minimal
"engineering instrument" aesthetic and avoiding new UI weight (no modal
library). Each feature is an independent slice that ends in its own commit,
pushed to both repos' GitHub remotes where touched.

## Decisions

- **Interaction style:** inline & lightweight. Delete = click-to-arm confirm.
  Rename = click-to-edit in place (Enter saves, Esc cancels). No modals.
- **Auth:** ownership is NOT checked on mutating endpoints today (any id works).
  Keep as-is for now — this is a known, accepted gap, documented here.

## Feature 1 — Delete a board (frontend only)

Backend `DELETE /board/{id}` and `api.deleteBoard` already exist; only wiring
is missing.

- **Projects grid** (`app/dashboard/projects/page.tsx`): each card gets a
  hover-revealed delete affordance. Click arms an inline "delete?" confirm;
  confirm calls `api.deleteBoard(id)` and removes the board from local state.
  The card is a `<Link>`, so the delete control must stop propagation /
  prevent navigation.
- **Project detail** (`app/dashboard/projects/[id]/page.tsx`): a small "Delete
  board" danger action. Confirm → `deleteBoard` → `router.push('/dashboard/projects')`.

## Feature 2 — Search + sort projects (frontend only)

On `app/dashboard/projects/page.tsx`, over the already-loaded board list:

- One search input filtering by `name` + `filename` (case-insensitive, client-side).
- One sort dropdown: **Newest** (`createdAt` desc, default), **Name A–Z**,
  **Most tracks** (`fcu + bcu` desc).
- No backend call. When the filter yields nothing, show a short "no matches"
  message; the existing empty-state copy stays for the zero-boards case.

## Feature 3 — Real board thumbnails (full-stack)

- **Backend** (`server.py`): `/boards/{email}` currently projects out `tracks`
  and `gcode`. Change the projection to drop only `gcode`, so list summaries
  include `tracks`. (`out_board` already emits `tracks` only when `full=True`;
  update the list path to pass tracks through.)
- **Frontend:** replace the static `BoardGlyph` (projects grid) and `BoardChip`
  (dashboard recent-boards rows) with the existing `PcbBoard` component
  rendering `b.tracks` — no animation, no toolpath overlay. Keep the glyph as a
  fallback when `tracks` is missing or empty.

## Feature 4 — Rename board & device alias (full-stack)

- **Backend** (`server.py`): two new endpoints
  - `PATCH /board/{board_id}` body `{name}` → update `name`, return updated board.
  - `PATCH /devices/{email}` body `{alias}` → update `alias`, return updated device.
  Validate non-empty, trim. Reuse existing ObjectId / not-found handling.
- **Frontend** (`lib/api.ts`): add `renameBoard(id, name)` and
  `renameDevice(email, alias)`.
- **UI:** inline click-to-edit on the board title `h1`
  (`projects/[id]/page.tsx`) and the device alias `h1` (`device/page.tsx`).
  Click → text input seeded with current value → Enter saves (calls API,
  updates local/session state) / Esc cancels / blur cancels. Empty input is
  rejected (revert to previous).

## Non-goals

- No ownership/auth enforcement (accepted gap above).
- No modal dialogs.
- No changes to the routing/G-code pipeline.

## Git plan

Order: 1 → 2 → 3 → 4. One commit per feature per repo it touches.
Push to `origin` on both repos after each commit. `pcb_ui` edits already share
a working tree with prior uncommitted work; those changes fold into the
relevant feature commits.
