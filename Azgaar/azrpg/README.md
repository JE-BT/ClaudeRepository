# azrpg

An RPG Maker–style game built from an Azgaar Fantasy Map Generator world. It is the sibling of
`azork`: the same world data and the same journey backbone, shown as a tile map you walk and sail.

## Use

The built game is a single HTML file with the world inside it. Open it in a browser; nothing else
is needed. `out/Pyeongak_rpg.html` is the Pyeongak test world.

To build a world (Python 3.10+, numpy, scipy, Pillow):

    cd Azgaar/azrpg
    python -m azrpg build Pyeongak            # -> out/Pyeongak_rpg.html
    python -m azrpg build Lania --map "Lania 2026-10-04-14-59.map"

The world folder (`Azgaar/<World>/`) needs a `.map` and a Cells GeoJSON export (Azgaar: Export >
GeoJSON > Cells). The newest `.map` is used unless `--map` is given; the Cells file is matched by
content, not name. The world's first journey becomes the story; without one the game is free roaming.

## Controls

Arrows/WASD move or steer · Space/Enter: go into a town, read a marker, hail a unit, go ashore or
board, look · F: autopilot along the plan's course (Shift+F fast) · R: rest, or carry out a stop at
sea · I: inspector · L/Shift+L: lens · M: world map (click for a waypoint) · J: journal · +/−: zoom
· Esc: menu · H: help. Touch screens get a pad and buttons.

## How the world is made

| Layer | Source | Kind |
|---|---|---|
| Tile size | The map's grid overlay (style `grid.options`: type, scale, offset); Pyeongak: square 1.25 px = 6.25 mi | data |
| Cell per tile | Cells GeoJSON polygons at the tile centre | data |
| Land and water | Azgaar's smoothed coast and lake outlines (`featurePaths` in the .map's SVG); disagreeing coast tiles take the nearest neighbouring cell of the right kind, so a tile's data always matches its look | data, reconciled |
| Elevation per tile | Bilinear between grid heights, small seeded noise on land | mixed |
| Temperature, precipitation | The grid cell under the tile (Azgaar's own cell-info rule) | data |
| Relief icons | The map's relief rules (height and temperature bands) applied per tile | mixed |
| Trees, grass, dunes | Each biome's icon list, weights and density | mixed |
| Rivers | Each river's cell sequence through cell centroids, with bends | mixed |
| Roads, trails, sea lanes | Route point lists | data |
| Towns | Burg group, walls, temple, port, shanty; roofs in the culture colour, flags in the state colour | data |
| Markers, regiments, fleets | Their positions, types and notes | data |
| Rural production | Azgaar's getCellProduction, modifiers included | mixed |
| Trade | Deals summed by burg and good | data |

Text is tagged in play: **data** (read from the files), **mixed** (a stated rule applied to data),
**new** (invented for the playthrough, such as the traveller, people's names and an inn's keeper).

## Seasons and light

The plan clock carries a day of the year, chosen on the title screen as the departure season at the
journey's origin (the four quarter days). Every tile then has its own season by latitude (southern
seasons run opposite; the tropics have wet and dry seasons), its own day length (from latitude and
the sun's declination; this drives the day–night tint and the boats' sailing hours) and a temperature
for today: the map's annual mean plus a seasonal swing that grows with latitude (0.3 °C per degree,
up to 18 °C, about half that at sea). The swing is a mixed rule; the mean is data.

## Travellers

Kinds are found in the map, not hard-coded: a native of the destination going home; a convert from
the origin; a stranger from each stop; a soldier of each state on the route that is at war; an envoy
between the origin and destination states (with their diplomatic stance); a trading factor carrying
a good the origin sells and the destination buys; a scholar of a library marker; someone who fled a
zone near the origin. Pick one or let chance decide; name, age, trade and home are generated. Each
kind brings a purse and a personal side story.

## Events and side stories

Markers and zones have scenes with choices. Choices cost hours (against the plan) and coin (🟡, the
symbol Azgaar uses for prices), change standing with faiths and states (which priests and the watch
remember), leave conditions (fever, hurt, a damaged vessel: each slows you until treated at a temple,
a healing spring, a port or by two days' rest) and open side stories in teal with goals at towns,
markers or units. Hazards (pirates, sea monsters, brigands, monsters, the walking dead) meet you when
you come within a few tiles; other sites wait for Space. Portals carry you to the other portals
(without your ship). Sighted places become leads in the journal; click one to set a waypoint.

## The plan is par (phase 3)

The map's journey is a line of checkpoints with par times and the plan's tasks (gold): book
passage, give alms, rest a night, anchor. You do them yourself, or not; you may skip a checkpoint by
going into a later town. A **booked ship** has a captain, an itinerary (the plan's direct ship, a
slower one calling on the way, others bound where this town's goods are bought) and a sailing time
that does not wait; as a passenger you cannot steer, the captain decides on hazards, and now and
then something happens aboard (the cook, dice, fellow passengers, fever, the captain's view of your
people). A **hired boat** is yours to steer, with a crew who draw wages each dawn, eat your stores,
call for anchor at sunset and shelter in storms, and mutiny if overruled too often. Courses run on
navigable water only (rivers by discharge: boats 40 m³/s, ships 400). Prices come from each town's
market; supplies run down daily; fishing and foraging (R) stretch them. The journal explains each
leg from the data and lists errands, leads and the record against par.

## The moving world (alpha 2)

One simulation, seeded from the world seed and advanced day by day with the game clock
(`engine/src/14_sim.js`, wired in `15_alpha2.js`). The map is the starting point and the momentum:

- **Markets**: each market's stock of each good moves with daily supply (burg production and rural
  output) against demand; food swings with the season at the market's latitude (harvest in autumn,
  the hungry gap in spring); disease, dearth and occupation cut supply; closed lines stop the trade
  flows (the map's deals). Prices follow stock. Towns spare only a share of their food for
  travellers, so what you can buy depends on the town, the season and what you bought before.
- **Lines**: fixed timetables you can learn. Trade runs between market centres (from the deals),
  coastal packets between neighbouring ports, the plan's own packets, and coaches and carriers'
  wagons between towns on the same land. A line stops running for war, bad relations (by road),
  occupation, quarantine or disaster at either end, and starts again when that ends.
- **Hazards**: disease spreads along the lines and burns out; eruptions, floods, faults and
  tsunamis end; empty granaries bring dearth, which eases when the stock recovers.
- **War**: the wars already under way move: regiments march on the enemy's nearest town, defenders
  move to meet them, battles are fought by strength, towns fall after a siege (a week, three for
  walls, a month for a capital with a citadel), peace comes with losses, time or conquest.
- **News**: everything that happens is news, heard in towns once it has had time to travel
  (60 miles a day). The journal keeps news, timetables and prices with the date you learned them;
  the world map draws the lines you know. Errands ask you to scout armies and report to the watch.

## Alpha 2.1

- **Modes**: Journey (if the map has one) or Sandbox (the same world, no journey; moving or still).
- **Journeys by archetype**: the map's journey type (Quest, Caravan, Pilgrimage, Military campaign,
  Embassy ...) frames the trip and the travellers. A leader named in the journey's title ("Culzan
  and the road through the forest") leads it. Stops are things to do: Gathering (meet the
  company), Rumours (listen; leads and the reasons for the next leg), Waiting for a ship (book),
  Resupply (market), Camp (camp there). The company crews a hired boat and gives advice (Space).
- **Travellers**: purses vary; each has a trait (long-legged, haggler, sea legs, hardy,
  well-connected). Lines from states hostile to your home refuse you or charge more.
- **Moving targets** are found by their last known position, then by tracks and news.
- **Camping** depends on the place (forest, water, cold, marsh, desert, weather, nearby danger).
- **Storms** grow more dangerous with distance from land; boats can be beached near shore, or sink.
- **Rivers**: crews call for a stop on rivers too (tie up at the bank); fords cost time by the
  river's size, and the largest need a bridge or a boat; rivers run on through lakes.
- **Portals** charge a fee and sometimes misfire (nothing, lost days, or somewhere remote).
- **Lines**: long-haul sailings along each named sea lane, calling at every port on it.

## The journey

The map's journey is the plan and is never changed. The plan clock starts on Day 1 at 06:00 (spring
equinox); modes under 24 hours a day depart at dawn and spread their hours over the day. Play is the
record: every step costs time (walking speed and biome move cost on land; vessel speed and the
latitude's wind band, ±10 %, at sea; on the plan's course a step is worth the course's own miles).
Boats with fewer than 24 hours a day anchor at night. The HUD and the journal show slippage.

The traveller is generated for each playthrough from the journey's own places and faiths (returning
home, convert, or a stranger from a stop along the way). The world stays the same; the traveller's
culture, faith and home shape how towns receive them (shared tongue, shared faith, and the
diplomatic stance between their home state and the town's).

## Layout

    azrpg/          Python converter (mapfile, cells, svgpaths, tilegrid, raster, pack, build)
    engine/src/     the browser engine, concatenated in name order into the HTML
    engine/shell.html
    tests/          python -m unittest discover -s tests -t . ; node tests/playthrough.js ; node tests/dom_smoke.js out/Pyeongak_rpg.html
    out/            built games

The node tests need `@napi-rs/canvas` (and `jsdom` for the DOM test); set `NODE_MODULES` or
`CANVAS_MODULE` if they are installed elsewhere.
