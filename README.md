# TraceWorks — Web UI

A Next.js + TypeScript web app for the single-layer PCB pen-plotter pipeline in
`../pcb_reader`. It's the "product" side of the vision in that repo's DOCS.md:
upload a KiCad board, preview the toolpath in the browser, and stream it to a
FluidNC machine — paired to your account by **device ID**.

## Stack
- Next.js 15 (App Router) + React 19 + TypeScript
- Tailwind CSS v4 (custom "engineering instrument" theme — no gradient slop)
- Fonts: Space Grotesk (display/UI) + IBM Plex Mono (data)

## Run
```bash
npm install
npm run dev      # http://localhost:3000
npm run build
```

## Pages
| Route | What it is |
|-------|-----------|
| `/` | Marketing landing — pipeline, device-pairing story, hardware, pricing |
| `/signup`, `/login` | Account creation / sign-in (localStorage prototype auth) |
| `/connect` | **Device pairing** — enter the device ID, watch the FluidNC handshake, bind it to your account |
| `/dashboard` | Overview: paired device, boards, travel-saved stats |
| `/dashboard/projects` | Board workspace + `.kicad_pcb` upload |
| `/dashboard/projects/[id]` | Board detail: layer-toggle preview, route report, G-code, **stream-to-device with Check Mode** |
| `/dashboard/device` | Device identity, machine profile, unpair |

## Notes
- **Real geometry:** the board previews render the *actual* `labExam.kicad_pcb`
  traces (352 tracks, 143 F.Cu / 209 B.Cu, 32 nets), extracted via `pcb_read.py`
  and stored in `board_raw.json`.
- **Auth & device pairing are a client-side prototype** (`lib/auth.tsx`,
  localStorage). The demo device ID is `TW-3F9A-C210`. Swap the provider
  functions for a real API + backend when wiring up hardware.
- Numbers shown (92% less pen-up travel, 580 G-code lines, etc.) come from the
  real pipeline in `../pcb_reader/DOCS.md`.
