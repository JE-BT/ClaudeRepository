# azgaar_tiles

Grid references and tile data reports for worlds made in Azgaar's Fantasy Map Generator.
One Python file, standard library only (Python 3.9 or newer).

## What it does

| Command | Output |
|---|---|
| `info WORLD` | the files loaded, the grid, and how references work |
| `map WORLD` | an overview SVG: coastline, biomes, borders, rivers, towns, OS-style grid lines and lettered squares |
| `sheet WORLD PLACE` | a zoomed SVG with every tile outlined and numbered |
| `find WORLD TEXT` | grid references for burgs, markers, states, provinces, rivers, routes, zones, units, journeys, cultures and faiths |
| `report WORLD PLACE` | a LaTeX report (dndbook class) with every piece of data for one tile; `--pdf`, `--json` |
| `export WORLD [PLACE]` | GIS layers of the whole map, or of a sheet round a place, as GeoJSON or a GeoPackage |

`WORLD` is a `.map` file, a folder holding one, or a world name found under `--worlds`
(default `./Azgaar` and the current folder). The newest `.map` in the folder is used unless
`--map` names one. `PLACE` is a grid reference, a place name, `px:X,Y` or `ll:LON,LAT`.

    python azgaar_tiles.py info Lania --worlds ClaudeRepository/Azgaar
    python azgaar_tiles.py map Lania --worlds ClaudeRepository/Azgaar
    python azgaar_tiles.py find Lania Khara --worlds ClaudeRepository/Azgaar
    python azgaar_tiles.py sheet Lania "CC 48 41" --radius 15 --worlds ClaudeRepository/Azgaar
    python azgaar_tiles.py report Lania Bayfshear --pdf --worlds ClaudeRepository/Azgaar
    python azgaar_tiles.py export Lania Bayfshear --format gpkg --worlds ClaudeRepository/Azgaar
    python azgaar_tiles.py export Lania --format gpkg --tiles light --worlds ClaudeRepository/Azgaar
    python azgaar_tiles.py export Lania --format gpkg --surfaces --worlds ClaudeRepository/Azgaar

## Files a world needs

Version 1.1 reads marker and regiment icons from Azgaar 1.154 and newer, which stores an emoji as its code
points (`glyph-1f333` for 🌳); every output now shows the emoji itself, and the `units` layer has an `icon` column.

- the `.map` save (Azgaar 1.153 or newer)
- the Cells GeoJSON export (Azgaar: Menu > Export > GeoJSON > Cells). The `.map` keeps no cell
  outlines, so every areal figure depends on it. It is matched to the map by content, so its date
  and name may differ.
- optional: emblem PNGs (`... Emblem <Burg> ....png`) and Watabou town plans (`<burg>.json`) in the
  same folder are picked up by the report.

## Grid references

The tiles are Azgaar's own grid overlay (Style > Grid), rebuilt from the map's saved style, so they
sit on the lines Azgaar draws. Square, pointy-top hex, flat-top hex and 45-degree square overlays are
read directly; the other pattern types are stood in for by the nearest of these. `--grid square|hex|flathex|diamond`
with `--size` (in map units) sets a grid of your own.

References follow the Ordnance Survey pattern:

- Two letters name a square of 100 x 100 tiles. The first counts squares eastward, the second
  northward, from the south-west corner of the map. I is skipped.
- Digits give eastings before northings inside the square.

| Reference | Meaning |
|---|---|
| `CC 48 41` | one tile: 48 columns east, 41 rows north of square CC's south-west corner |
| `CC 4 4` | the 10 x 10 block holding CC 40 40 to CC 49 49 |
| `CC 483 414` | a point, to a tenth of a tile width and of a row |

Spaces are optional (`CC4841`). Worlds wider than 25 squares use squares of 1,000 tiles and three
figures each way.

## How the figures are made

- **Areal data** (population, culture, faith, state, province, biome, zones, rural production):
  each cell outline is clipped against the tile, and the cell's value is counted by the part inside.
  Burgs count in full when their point lies in the tile.
- **Elevation, temperature, precipitation**: Azgaar's climate grid, read under sample points the way
  Azgaar's cell panel reads it, and compared with the surroundings, province, state, latitude band
  and world.
- **Borders**: shared cell edges where two states, provinces, cultures, faiths, market regions or
  biomes meet, clipped to the tile. State borders carry both sides' diplomatic stances, their
  campaigns and the war chronicle; culture and faith borders their lineage; market borders the
  trade between the two markets.
- **Rivers, routes, journeys**: the length inside the tile and its share of the whole. Rivers use
  their drawn course where the map's SVG keeps it, otherwise a line through their cells. Routes
  name the nearest burg along them on each side. Journeys give the plan's clock on entering and
  leaving the tile.
- **Journey times** follow Azgaar: speeds are stored in km/h, halved off road, and every full travel
  day counts as 24 hours. `--speeds-as-map-units` reads the speed figures as map units per hour.
- **Trade**: rural output by Azgaar's cell-production rule, urban output from each burg's production
  record; each good's share of its state, market region and world output, with market prices,
  stock and flows.

Report values are tagged **(data)** when read from the files and **(mixed)** when a stated rule is
applied to them.

## GIS export

`export` writes the reference grid and the map's own layers for QGIS, ArcGIS or any GDAL tool.
With a place it exports a sheet (the tiles within `--radius` of it, default 12); without one, the
whole map.

| Layer | Geometry | Holds |
|---|---|---|
| `tiles` | polygon | one row per tile: reference, square, eastings and northings; `--tiles full` adds the report's clipped figures (land share, people, density, main state, province, culture, faith and biome with their shares, elevation, temperature, precipitation, zones, burgs, markers, rivers, routes and journeys crossing, state border length, output value, top good); `--tiles light` reads the cell under the centre only |
| `squares`, `blocks` | polygon | the lettered 100 x 100 squares and the 10 x 10 blocks, traced along the tile edges |
| `land` | multipolygon | Azgaar's drawn coastlines and lakes |
| `zones` | multipolygon | each zone, dissolved from its cells |
| `borders` | multiline | state borders, with each side's stance toward the other and their campaigns |
| `rivers`, `routes` | line | drawn or cell courses, discharge, lengths, the burgs along each route |
| `journeys`, `stops` | line, point | each segment and stay, with transport, speed and the plan's clock (Azgaar's rule) |
| `burgs`, `markers`, `units` | point | names, grid and point references, and their main attributes (markers and regiments with their emoji icon) |
| `centres` | point | the interpolated surfaces at every tile centre (see below) |
| `deals`, `traffic`, `markets` | line, line, point | trade as recorded, its load on the route network, and the markets (see below) |

- `--format geojson` (default) writes one `.geojson` file per layer; `--format gpkg` writes one
  GeoPackage holding every layer. The GeoPackage is written with Python's own sqlite3 and opens
  directly in QGIS. For the whole map with a tiles layer (Lania: 294,000 hexes), use the GeoPackage.
- `--crs lonlat` (default) uses the longitude and latitude Azgaar writes in its own GeoJSON exports
  (EPSG:4326 axes), so these layers lie exactly on Azgaar's Cells, Burgs, Routes, Rivers and Markers
  exports. Distances measured on them follow Earth's ellipsoid, not the world's scale.
- `--crs units` gives eastings and northings in the map's distance unit from the map's south-west
  corner, so a GIS measures lengths and areas in the world's own miles. The GeoPackage stores this as
  a local grid; GeoJSON has no slot for it, so set the layer to an unknown planar CRS by hand.
- `--layers tiles,blocks,burgs` limits the export to some layers.
- Azgaar's drawn coastlines are smoothed curves and occasionally cross themselves at narrow
  straits; QGIS's *Fix geometries* tool cleans them. Every other layer is written valid.

### Interpolated surfaces (`centres` layer)

With `--surfaces` (on by default for a sheet, off for the whole map) the export evaluates a set of
continuous surfaces at every tile centre and writes them to a `centres` point layer. The same values
are added to the `tiles` layer with an `i_` prefix. Values are point estimates at the centre; values
for the tile (people, goods, output) are the centre's density times the tile's area. Halving the
tile size (`--size`, or a finer overlay in Azgaar) doubles the resolution: the surfaces themselves
do not depend on the grid.

| Value | Kind in the data | How it is interpolated |
|---|---|---|
| height (`h`, `elevation`, `elev_m`) | mean of a grid cell | Gaussian kernel over the climate grid, land and sea fitted apart so the coast stays a hard edge; six residual passes bring each grid cell's mean back to its value |
| temperature (`temp_c`, `temp`) | mean of a grid cell | interpolated as sea-level temperature, then lowered by Azgaar's lapse rate (6.5 °C per km) at the interpolated height |
| precipitation (`prec_mm`) | mean of a grid cell | kernel with residual passes |
| suitability | per cell | Azgaar's own rule, evaluated locally: habitability blended across neighbouring cells, the river term fading with distance from the river, the coast bonus fading from the shore, and the height penalty at the interpolated height |
| people (`density`, `rural`) | sum per cell | dasymetric: a density surface blended across neighbouring cells, weighted by local suitability against that of the cells around and by nearness to roads and trails; three smoothing passes (after Tobler's pycnophylactic method) even out steps at cell borders, and a last rescale keeps every cell's total |
| rural goods (`g_<good>`, `rural_value`) | sum per cell | the people weights times each good's biome yield blended across neighbouring cells (wood rises toward forest), smoothed and rescaled the same way; a cell's bonus good follows its people, as Azgaar scales it with population; output of water cells (fish) gathers near the shore |
| town output (`urban_value`), `output_value` | per burg | town output stays at its burg, as in the data; `output_value` is rural plus town output in coin at base value |
| prices (`price_index`, `food_index`) | per market | each market's prices relative to the mean of all markets, blended by distance to the market centres (`own_market_weight` above 1 favours a point's own market and puts steps at market borders) |
| trade through the tile (`trade_value`, `trade_deals`, `trade_top`) | per deal | every deal routed along the route network by least cost; the value of the distinct deals whose route crosses the tile |
| `state`, `sales_tax`, `poll_tax`, `treasury`, `alert`, `market`, `urban` | as is | read from the cell, state, market and burgs at the centre |

The constants behind these rules (kernel widths, the reach of roads, rivers and coasts, the road
bonus, smoothing passes, route costs and the price blend) are in `SURFACE_RULES` at the top of the
surfaces section of the script. On Lania, people and goods integrated over finer samples return each cell's totals to
within about 2% on average, and heights and temperatures on all-land tiles agree with the grid's
values (120 ft and 20.9 °C against 118 ft and 20.9 °C round Khara).

### Trade layers

| Layer | Geometry | Holds |
|---|---|---|
| `deals` | line | every deal as in the data, a straight line from seller to buyer (burg or market centre): good, units, price, value, tax, and the length of its route on the network |
| `traffic` | line | each route segment carrying trade, with the value, units and number of deals routed over it and its main good |
| `markets` | point | each market centre: burgs and cells served, value traded out and in, price indexes |

## LaTeX

The report uses the dndbook class from the D&D 5e LaTeX template
(github.com/rpgtex/DND-5e-LaTeX-Template) and compiles with pdfLaTeX. `--a4` switches the paper
size; `--title-page` adds the title page and contents.
