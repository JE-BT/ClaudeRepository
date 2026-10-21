# azgaar_iso

An isometric, tile-by-tile view of a world made in Azgaar's Fantasy Map Generator, built from what
`azgaar_tiles.py export` writes. One Python file, standard library only (Python 3.9 or newer). The
result is one self-contained HTML page that opens in any current browser with WebGL 2.

## Quick start

    # 1. export the tiles with their interpolated surfaces
    python azgaar_tiles.py export Lania Bayfshear --radius 20 --worlds ClaudeRepository/Azgaar
    python azgaar_tiles.py export Lania --format gpkg --tiles light --surfaces --worlds ClaudeRepository/Azgaar

    # 2. build the page
    python azgaar_iso.py "Lania sheet CC4841"
    python azgaar_iso.py "Lania map.gpkg" -o lania.html

The page is written beside the export as `<export name> iso.html` unless `-o` names a file.

## What it reads

`EXPORT` is the base name of the GeoJSON layers (`"Lania sheet CC4841"` for the files
`Lania sheet CC4841 tiles.geojson`, `... centres.geojson` and so on), any one of those files, the folder
that holds them, or a GeoPackage written with `--format gpkg`. A folder with several exports in it
uses the newest.

| Layer | What the page takes from it |
|---|---|
| `centres` | every interpolated surface (height, temperature, precipitation, habitability, people, each good, output value, prices, trade through the tile) and the state, market and taxes at the centre |
| `tiles` | biome, province, culture and faith of the cell under the centre (`--tiles light`) or the clipped figures of the report (`--tiles full`), and the tile outline |
| `deals`, `routes` | trade, routed along the route network |
| `traffic`, `markets` | the load on each route segment; each market's centre and totals |
| `burgs`, `markers`, `units`, `rivers`, `borders`, `zones`, `journeys`, `stops`, `land`, `squares`, `blocks` | the overlays of the same names |

Either `centres` or `tiles` is enough to draw the tiles. With both, the two are joined by grid
reference: interpolated values come from `centres`, and any clipped figure that differs from the
interpolated one is kept beside it, labelled *(clipped)*. Without a `tiles` layer, the tile shape is
worked out from the spacing of the centres.

Large GeoJSON files are read one feature at a time, so a whole-map export never has to sit in memory
as one document. For whole maps the GeoPackage is still the better choice: it is smaller and quicker
to read.

Lon/lat exports (the default) are turned back into map distances using the lengths the `routes`,
`borders`, `journeys` or `rivers` layers carry, in that order; `--scale` sets the figure by hand.
Exports made with `--crs units` are already in map distances. Height and temperature units are read
from the pairs the centres carry (`elevation` with `elev_m`, `temp` with `temp_c`).

## The page

**Moving around.** Drag to move. Scroll or pinch to zoom. Right-drag (or Alt-drag) turns the view and
tilts it; two fingers turn it on a touch screen. The dial turns the view when dragged and steps it by
60° (hexes) or 90° (squares) when clicked. Keys: arrows or WASD move, `+` and `-` zoom, `Q` and `E`
turn (with Shift, one step of the grid), `[` and `]` tilt, `/` jumps to the search box, `Esc` closes
the panel.

**Tiles.** Each tile is a block raised to its interpolated height, with the sea flat at sea level and
lakes at their surface. The View section sets the relief (the vertical scale starts so that the
highest land, at the 99th percentile, stands about 1.6 tiles tall), height steps for a terraced look, the tilt,
shading of slopes (lit from the top left of the screen, whatever the heading) and light or dark
colours.

**Painting.** Any value the export carries can paint the tiles, grouped as Land, People, Realm,
Economy, Trade and Goods. Counts and values (people, goods, output, trade) use a log scale; price
indexes are shown above and below the average of all markets. The first choice, *Landscape*, is the
biome under each tile lightened with height, with the sea darkening with depth. In a list of
categories (states, cultures, faiths, markets, biomes, top goods), clicking one picks those tiles out.

**Inspecting.** Clicking a tile opens everything known about it: its grid reference, any towns,
markers, regiments and journey stops in it, and every value in the export, tagged *data* when read
from the files and *mixed* when interpolated or clipped. Towns show their people, features, state,
culture, faith and market, what they sell and buy, and from or to whom. A market centre also shows
where the market's stock comes from (towns and other markets, by good, with the main sellers), what it
sells to towns and what it sends to other markets.

**Overlays.** Towns (pins: taller for capitals and cities, a square head for walls, a blue ring for
ports, a dark centre for capitals, a gold diamond for market centres), town names, markers,
regiments and fleets, rivers, roads, trails and sea routes, the coastline, state borders coloured by
the cooler of the two states' stances, state names, zones, journeys and their stops, the lettered
squares, the 10 by 10 blocks and the tile outlines. On a sheet, overlays stop at the edge of the tiles.

**Trade.** *Animate trade* sets goods moving from seller to buyer, one dot per good per path, with a
short tail behind it and a size that grows with value. Goods follow the route network by least cost,
with the same costs `azgaar_tiles.py` uses (roads 1, trails 1.3, sea routes 0.5 per unit length, 2 to
reach the network from a town off it), or fly as arcs. Deals can be filtered by good, by kind
(markets selling to towns, towns stocking markets, trade between markets) and by place: clicking a
town pin, or *Show ... trade* in the panel, follows one town or one market. *Load on each route
segment* draws the `traffic` layer, with widths by value and colours by the main good.

**Search.** Towns, markers, regiments, states, provinces, cultures, faiths, zones and grid references
(`CC 48 41`, `CC4841`, or a point reference such as `CC 483 414`). A realm or category flies to its
tiles and picks them out.

## Options

| Option | Effect |
|---|---|
| `-o FILE` | the HTML file to write |
| `--title TEXT` | the world name on the page (default: the export's name up to "sheet" or "map") |
| `--unit UNIT` | the map's distance unit, when a lon/lat export cannot say (default `mi`) |
| `--scale K` | map units per degree for lon/lat exports |
| `--max-deals N` | keep only the N largest deals by value |
| `--no-compress` | store the data uncompressed: about twice the size, for browsers without `DecompressionStream` |

## How the data is stored

Tile positions are 32-bit floats. Each numeric field is stored in 16 bits over its own range (on a
log scale for counts and values), which keeps four significant figures; text fields are stored as
codes into a list. Everything is gzipped and base64-encoded inside the page, and unpacked in the
browser. Legends use the 1st to 99th percentile of each field so a few extreme tiles do not wash out
the colours; the full range is printed under the legend.

Sizes on Lania (pointy hexes): the Bayfshear sheet (613 tiles) makes a 0.2 MB page; the whole map at
10-mile hexes (73,764 tiles) 2.1 MB in about 10 seconds; the whole map at Azgaar's own 5-mile hexes
(293,942 tiles, from a GeoPackage) 6.8 MB in about 40 seconds with under 400 MB of memory.

## Notes

- The page draws every tile on the graphics card in one call and redraws the tiles only when the view
  or the paint changes; the moving goods have a canvas of their own. Picking reads a hidden image of
  tile numbers, also redrawn only when the view changes. The pages were tested in Chromium with a
  software renderer; a graphics card will be much faster.
- Routed lengths agree with the `routed_len` that `azgaar_tiles.py` writes for each deal: on Lania the
  median ratio is 1.00, and 90% of deals fall between 0.70 and 1.31. The differences come from where a
  town off the network joins it.
- On a sheet, deals reach places beyond its edge. Routes are exported whole, so many of those deals
  still route; the rest are drawn straight.
- `azgaar_tiles.py` 1.0 gives some sea tiles at the map's edge impossible depths (around −6 × 10¹⁷ m):
  its sea rule `(h - 20) / h * 50` in `World.height_m` is applied to interpolated heights just above
  zero. The page sets aside depths beyond 11 km, draws those tiles as the deepest sea, and says so
  under *View*. Applying the sea rule only from `h >= 1` (and −990 m below that) removes the problem
  at its source.
