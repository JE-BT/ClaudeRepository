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
