# Sample seed output

Run `quill-mock bootstrap && quill-mock tick --feeder <name> --count 1 --dry-run`
to reproduce. Below are representative samples for AI Lead review.

## Sample RFI (rfi.new)

```
RFI RFI-BLDG2-6718 — Computer Room Air Conditioners — electrical clarification

Building: BLDG2 (level L3, gridline G-3)
Discipline: electrical
Drawing reference: BLDG2-E580
Spec reference: 23 81 23 Computer Room Air Conditioners
Submitted by: Ryan Torres (Project Engineer) — Sentry Access Systems
Priority: normal

QUESTION
Confirm rebar lap length at column G-3; field measured 40" but spec calls for 56".

CONTEXT
Issue surfaced during inspection walk. Production at risk if unresolved by 2026-05-11.

PROPOSED RESOLUTION
Field verify and document — confirm by EOR.

ATTACHMENTS
- BLDG2-E580.pdf (excerpt)
```

> **Realism note:** the question bank rotates independent of the spec
> section / discipline, so you'll occasionally see rebar text under a
> CRAH spec. Triage agents should still classify by spec_section, which
> is authoritative here. A v2 of the feeder will harmonize template
> selection with the spec.

## Sample DFR (dfr.new)

```
DAILY FIELD REPORT — 2026-07-15 — BLDG1
Superintendent: Ricardo Alvarez
Weather: scattered showers | High 62°F | Low 28°F | Wind 8 mph
Crew on site: 223 (drywall, rebar, concrete, commissioning, controls, earthwork)
Hours worked: 1765

WORK COMPLETED TODAY
- Completed BLDG1 mat foundation pour (77.7%)
- Completed BLDG1 CRAH unit set (37.8%)
- Completed BLDG1 mat foundation pour (43.6%)

PRODUCTION QUANTITIES
- BLDG1 CRAH unit set (A1204): 125 of 331 EA (37.8% complete)
- BLDG1 mat foundation pour (A1839): 108 of 139 CY (77.7% complete)
- BLDG1 mat foundation pour (A1767): 119 of 273 TON (43.6% complete)

DELAYS / IMPEDIMENTS
- Fuel delivery for generator commissioning slipped to tomorrow.

SAFETY
- Pre-task plans signed: 223
- Near-misses: 1
- Recordable incidents: 0

VISITORS / DELIVERIES
- No site visitors of note.

LOOK-AHEAD (next 3 days)
- Tomorrow: continue BLDG1 CRAH unit set
- Next 48h: prep for inspection on fire-stop
- Watch: weather forecast — rain Thursday PM
```

> **Realism note:** weather lows occasionally land below freezing in
> July (model is uniform across the year). Acceptable for synth — fix
> in v2 if it confuses an agent.

## Sample vendor email (procurement.update)

```
From: PM, ASCO <pm@asco.com>
To: procurement@quill-mock.com
Subject: [PO-2026-1011] Manufacturing Started
Date: Fri, 08 May 2026 01:29

Hello procurement,

This is an update on PO-2026-1011 (Generator paralleling switchgear, qty 4).

Mfg release issued. Production now in our queue.
Ship date remains 2027-02-20.

Best regards,
PM, ASCO
ASCO
```

## Project bootstrap (project.json)

```
QPB1 — Quill Pilot Build 1
$10B / 1.7 GW / 4 buildings (BLDG1-4)
Construction starts: 2026-06-23
Substantial completion: 2028-12-22
Long-lead POs: 30 (transformers, switchgear, UPS, gensets, chillers...)
Spec sections: 12 (03 30 00, 21 13 13, 23 64 16, 26 13 13, 26 32 13, ...)
Subcontractors: 25 (Atlas Concrete, Helios Steel, Trinity Mech, Volt Power, ...)
Hyperscaler reps: 5 (Marcus Doyle, Priya Raman, Ethan Cho, Sara Lindqvist, Trevor Wallace)
```
