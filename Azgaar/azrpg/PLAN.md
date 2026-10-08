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

## Decisions (2026-10-07, after the first playtest)

7. **Wind stays at ±10 %.**
8. **Marker and zone events with consequences** come next (done in phase 2).
9. **Seasons and light by latitude**, from a departure season chosen at the start.
10. **More traveller kinds, chosen from a menu**, with "let chance decide".

## Decisions (2026-10-07, third playtest)

11. **The plan is par, not a driver**: checkpoints, tasks done by the player, skipping allowed.
12. **Ships are booked** (captain, itinerary, sailing time, fare); **boats are hired** (crew, wages,
    calls at sunset and in storms, morale, mutiny). Trades that can, may work a passage.
13. **Prices tied to market data; supplies and money management.**
14. **Rumours become teal leads; errands come from zones, trade, diplomacy, wars, markers, faith.**
15. **Weather** from precipitation, season and latitude.
16. **Season stays as it is** (winter legs run long; sailing on at night is the player's choice).
17. **Fishing (data grounds) and foraging (biome, food output, season)**; a little shipboard life
    for passengers, rate to be tuned in playtests (`AZ.SHIP_EVENTS.rate`, now 0.18 a day).

## Decisions (2026-10-07, alpha wrap-up)

18. Passenger time is the player's: F switches normal and fast days, P holds the ship; resting,
    sleeping and talking aboard let the ship sail on by the hours spent.
19. Water dropped for now; food only. Money rounded to 2 decimals everywhere.
20. Goods trading between markets (stock, regional prices, sales tax, merchants buy at 85 %,
    prices move 4 % a unit and recover).
21. Fever runs its course (grave on day 3, collapse on day 6) unless treated; sleep matters
    (tired at 18 h awake, exhausted at 30, asleep where you stand at 44).
22. Mutiny is negotiable: three strikes (bonus, a promised port, or face them down).
23. Walkable towns only if Watabou exports can be automated; otherwise not for now.
24. Errand deadlines stay as they are.

## Decisions (2026-10-08, alpha 2)

25. Economy moves first, then hazards, then war; all three are in.
26. The simulation runs live in the browser.
27. The player knows what news has reached them; scouting armies is a source of errands.
28. Fully seeded from the world seed.
29. Passenger networks (packets, trade runs, coaches, carriers' wagons) with fixed timetables that
    run or stop as the world changes.
30. Food for sale limited by the town's market stock, its size and the season.

## Alpha 2 (done)

Simulation of markets, lines, hazards and wars; timetables at harbours and coach offices; wagons
and coaches as rides; news that travels; army-scouting errands; harbours within a short walk only;
marked places in or beside a town reachable from its menu; known lines on the world map.

## Open after alpha 2

- Lenses still show the true state; only news is limited by distance.
- Visible traffic (the vehicles of the lines moving on the map).
- New lines opening as the world changes (now: a fixed set that runs or stops).
- Borders: towns fall and are given back at peace; provinces do not yet change hands.

## Phase 3 (done)

Water-only courses and harbours; checkpoints and par; booked ships and hired boats; crew calls,
morale and mutiny; prices, stores, hunger, thirst and collapse; weather; notice-board errands and
leads; route reasons; fishing and foraging; shipboard events. Tests: a scripted pilgrimage as a
trading factor (books the plan's ship, hires a boat, restocks, reaches Chelhazpo), and a browser
smoke test through title, walking, harbour, voyage, journal and a marker scene.

## Phase 2 (done)

Walking bug fixed. Seasons, daylight and today's temperature by latitude. Fourteen traveller kinds on
Pyeongak, all found in the data, with a selection screen. Events for 30 marker types and 11 zone
types; purse, standing, conditions, flags; side stories with steps at towns, markers and units;
leads in the journal. Tests now walk on land, take event choices and run every traveller kind.

## Phase 1 (done)

Converter, tile rasters, procedural pixel art, chunked renderer, lenses, inspector, world map,
journey plan and record, autopilot, town scenes, rumours by distance, traveller generation,
save in the browser, tests.

## Next: a moving world (see the design note in chat, 2026-10-07)

## Open for later phases

- Walkable town maps (from burg features, or from Watabou files where present).
- Travellers and traders moving on roads and sea lanes; hailing ships.
- Weather from precipitation and season; seasonal snow on the ground.
- Ledger export of a playthrough (keep, discard or fork, as in azork).
- Optional battles, if wanted.
