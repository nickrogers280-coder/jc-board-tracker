# JC Board Tracker

Interactive satellite map of every Jersey City Planning Board and Zoning Board of Adjustment application
filed since January 1, 2026 (case numbers P2026-* and Z2026-*). Same look and controls as the NJ Distress Map.

- `jc-board-tracker.html` - one file with the data built in; double-click to open.
- `index.html` + `data/map.json` - the same site as two files for GitHub Pages (upload both, keep the folder).
- `build.py` - rebuilds `data/map.json` and both pages from the raw pulls in `raw/`.

Sources: Jersey City Online Permitting & Licensing Portal (EnerGov) for cases; 2026 Planning and Zoning Board
agendas on Jersey City Open Data for applicant, attorney, zone and hearing dates; NJOGIS MOD-IV parcels for
location and tax records. Units, stories, parking and affordable counts are read from each application's
description, so check the city record before relying on a figure.
