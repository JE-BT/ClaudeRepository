# azrpg plan

## Decisions (2026-10-07)

1. **Browser engine, Python converter.** One standalone HTML per world; Python builds the pack.
2. **Tiles follow the map's grid overlay.** Pyeongak: 6.25-mile squares, lined up with Azgaar.
3. **Autopilot along the plan's course**, with the helm available at any time.
4. **Towns as menu scenes** for the first playtest (harbourmaster, innkeeper, merchant, priest,
   watch, townsfolk, notice board, and the gold stage action). Walkable towns later.
5. **The world is constant; the traveller is generated per playthrough** and shapes interactions
   (returning Rake, foreign convert, or a stranger from a stop along the route).
6. **No combat for now.** Pirates, monsters and zones are sightings, warnings and time costs.

## Phase 1 (done)

Converter, tile rasters, procedural pixel art, chunked renderer, lenses, inspector, world map,
journey plan and record, autopilot, town scenes, rumours by distance, traveller generation,
save in the browser, tests.

## Open for later phases

- Walkable town maps (from burg features, or from Watabou files where present).
- Travellers and traders moving on roads and sea lanes; hailing ships.
- Events at markers and zones with consequences beyond time (detours, delays, side stories in teal).
- Season and start date; weather from precipitation.
- Ledger export of a playthrough (keep, discard or fork, as in azork).
- Optional battles, if wanted.
