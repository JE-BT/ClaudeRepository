# azrpg

azrpg turns a world made in [Azgaar's Fantasy Map Generator](https://azgaar.github.io/Fantasy-Map-Generator/)
into a tile-based role-playing game in the style of RPG Maker. You walk, sail and fly across the
map itself: every tile carries the map's biome, height, climate, state, culture, faith, rivers,
roads and markets, and you can read all of it as you go.

Current version: **Alpha 2**.

## Play

A built world is a single HTML file. Open it in a recent browser (Chrome, Firefox, Safari or Edge);
nothing else is needed, and games are saved in the browser.

Choose a mode on the title screen:

- **Journey** follows the journey saved in the map: its checkpoints, par times and tasks. Any route
  and any means will do; arriving at the last checkpoint completes the journey.
- **Sandbox** lets you explore the world from a town of your choice, in a changing world (markets,
  passenger lines, disease and war run on) or a fixed one.

Then choose a traveller. Each kind of traveller is drawn from the map: natives of the places on the
route, soldiers of states at war, envoys, traders, scholars, refugees, and the roles of the journey's
own type (a raider on a raid, a courtier on a royal progress).

### Keys

| Key | Action |
|---|---|
| Arrows / WASD | Walk, or steer your own boat or craft |
| Space / Enter | Act on what is here: enter a town, visit a place, hail a unit, board or go ashore, talk, look |
| F | Follow a path to your waypoint, or the planned course; aboard a booked ship, switch pace |
| P | Aboard a booked ship: hold, so time passes only when you act |
| R | Camp, anchor, wait, fish, forage, recover |
| I | Inspector: every map layer for the tile you stand on |
| L | Lens: colour the map by biome, height, effort on foot, temperature, rain, state, province, culture, religion, population, market, resource or zone |
| M | World map; click to set a waypoint, N to show the passenger lines you know |
| J | Journal: what you carry, checkpoints and reasons, side stories, leads, news, timetables |
| + / −, Esc, H | Zoom, menu, help |

Touch screens get an on-screen pad.

### What you will find

- **Travel.** Walking pace follows the ground; wide rivers need a bridge or a boat. Booked ships,
  coaches and wagons keep fixed timetables and their own itineraries. A hired boat is yours to
  steer, with a crew who draw wages, eat your food and call for stops; overruling them costs
  morale. Air journeys fly in the company's own craft, and teleport circles cross a leg at once.
- **Supplies and money.** Prices come from each town's market and the state's sales tax. Towns sell
  a share of their food each week, varying with the harvest and with famine. Hunger, fever and lack
  of sleep slow you and, in the end, bring you down.
- **A changing world.** Market stocks and prices move, passenger lines stop in war and quarantine,
  disease travels along the trade routes, and the wars already under way in the map are fought out.
  News travels about 60 miles a day and reaches you in towns.
- **Side stories.** Notice boards post errands drawn from the world: trade runs, relief for stricken
  towns, letters along alliances and enmities, dispatches and scouting for armies, strange places,
  offerings for faith seats. Rumours, sightings and libraries add leads.

### Tags

Text in the game is tagged: **data** is read from the map, **mixed** is a stated rule applied to
the map (an interpolated height, a price with tax), **new** is made up for the game (a traveller's
name, an innkeeper).

## Build a world

Requirements: Python 3.10 or later with `numpy`, `scipy` and `Pillow`.

From Azgaar's generator, save the map (`.map`) and export the cells (Export → GeoJSON → Cells). Put
both in a folder named after the world, next to this folder:

```
Azgaar/
  azrpg/            this project
  MyWorld/
    MyWorld 2026-10-08-12-00.map
    MyWorld Cells 2026-10-08-12-01.geojson
```

Then, from `azrpg/`:

```
python -m azrpg build MyWorld          # writes out/MyWorld_rpg.html
python -m azrpg build MyWorld --map "MyWorld 2026-10-08-12-00.map"
```

The newest `.map` is used unless `--map` is given. The Cells export is matched to the map by its
content, so its file name does not matter. Maps saved by Azgaar 1.153 and 1.154 are supported.

**Tile size.** Tiles follow the map's grid overlay (Style → Grid) when its cells are between 1 and
20 miles across; otherwise tiles are 5 miles square. A square overlay lines the game up exactly with
the map.

**Journeys.** The first journey in the map becomes the game's journey. See
[docs/JOURNEYS.md](docs/JOURNEYS.md) for how journeys are read and how to write your own.

## How the map becomes a game

| Layer | Source |
|---|---|
| Cell per tile | the Cells export, at each tile's centre |
| Land and water | the map's own coastline and lake outlines |
| Height per tile | the map's height grid, interpolated |
| Temperature, rain | the map's climate grid |
| Mountains, hills | the map's relief rules |
| Trees, grass, dunes | each biome's icons and density |
| Rivers | each river's course; boats use rivers above 40 m³/s, ships above 400 m³/s |
| Roads, trails, sea lanes | the map's routes |
| Towns, markers, armies, fleets | the map's burgs, markers and military |
| Production and trade | Azgaar's production formula and the map's trade deals |
| Journey | the map's journey: segments, transports, speeds, stays |

## Project layout

```
azrpg/      converter (Python): reads the map, builds tiles, writes the world pack and the HTML
engine/     the game (JavaScript), one module per file, joined in name order
  shell.html
  src/00_util.js … 18_carry.js
tests/      converter tests (Python) and game tests (Node)
docs/       journeys key, roadmap
```

## Tests

```
python -m unittest discover -s tests -t .           # converter; needs the Pyeongak world
node tests/text.js out/Pyeongak_rpg.html            # every screen's text, for writing faults
node tests/features.js out/Presia_rpg.html          # air legs, wild starts, carrying, alerts
node tests/play.js out/Pyeongak_rpg.html            # a scripted journey
node tests/browser.js out/Pyeongak_rpg.html         # the page in a simulated browser
```

The Node tests need `@napi-rs/canvas`, and the browser test also `jsdom`.

## Credits

Worlds come from Azgaar's Fantasy Map Generator. Name lists are Azgaar's namebases (MIT licence),
and names are generated with Azgaar's own method. Town maps and dwellings are not part of azrpg.
