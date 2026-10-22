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

Version 1.1 adds the pixel-art style, trees and other details, town icons and tile-by-tile zone fills.

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

**Style.** Under *Paint the tiles*, *Pixel art* (the default) or *Smooth*. The pixel-art style draws the tiles,
their details and the line layers at a fraction of the screen's resolution and scales them up by whole pixels;
*Pixel size* under *View* sets how many screen pixels make one art pixel (1 to 4). Town names, labels and the
panels stay sharp. When the tiles are smaller than a few art pixels (a whole map seen from far out), the tiles
themselves are drawn smooth, since pixels that small only shimmer. *Smooth* is the 1.0 look.

**Tiles.** Each tile is a block raised to its interpolated height, with the sea flat at sea level and
lakes at their surface. The View section sets the relief (the vertical scale starts so that the
highest land, at the 99th percentile, stands about 1.6 tiles tall), height steps for a terraced look, the tilt,
shading of slopes (lit from the top left of the screen, whatever the heading) and light or dark
colours.

**Trees, rocks and fields.** Each tile carries a few pixel-art details chosen from its biome: oaks and
small oaks in temperate forest, pines and firs in rainforest and taiga (snowy below −2 °C), palms and jungle
trees in the tropics, acacias and grass on the savanna, grass and flowers on grassland, cacti, dunes and rocks
in desert, reeds and puddles in wetland, rocks and ice on tundra and glacier. Land from 700 m gets hills,
from 1,100 m small peaks and from 1,500 m mountains, snow-capped above the snowline. The sea gets waves, or
icebergs where it is below −3 °C. Where the countryside is among the most crowded fifth of the land (by
`density`), trees give way to fields and haystacks. Details keep clear of towns, roads, trails, rivers and
journey stops. They stand on their tiles in the 3D view, so taller tiles in front hide them, and more of them
appear as you zoom in; *Trees and details* under *View* sets how many (0 to 2). On any paint other than the
landscape they are greyed so the colours of the data stay readable. Placement is fixed by the tile, so the same
export always looks the same. Without a biome column, the biome is worked out from temperature and rain.

**Painting.** Any value the export carries can paint the tiles, grouped as Land, People, Realm,
Economy, Trade and Goods. Counts and values (people, goods, output, trade) use a log scale; price
indexes are shown above and below the average of all markets. The first choice, *Landscape*, is the
biome under each tile lightened with height, with the sea darkening with depth. In the pixel-art style it uses
a game palette: the land is banded by height (hills from 300 m, highland from 700 m, bare rock from 1,200 m,
snow from 2,600 m or wherever it is colder than −6 °C above 1,200 m), the sea steps darker at 60, 250, 1,000
and 3,000 m, and each tile top has a ground pattern for its biome (grass flecks, forest floor, sand ripples,
snow, tundra, puddled wetland, wave crests, rock, and a patchwork of fields in crowded countryside). The
patterns sit on the map, not the screen, so they do not swim as the view moves. In a list of
categories (states, cultures, faiths, markets, biomes, top goods), clicking one picks those tiles out.

**Inspecting.** Clicking a tile opens everything known about it: its grid reference, any towns,
markers, regiments and journey stops in it, and every value in the export, tagged *data* when read
from the files and *mixed* when interpolated or clipped. Towns show their people, features, state,
culture, faith and market, what they sell and buy, and from or to whom. A market centre also shows
where the market's stock comes from (towns and other markets, by good, with the main sellers), what it
sells to towns and what it sends to other markets.

**Overlays.** Towns, town names, markers, regiments and fleets, rivers, roads, trails and sea routes, the coastline, state borders coloured by
the cooler of the two states' stances, state names, zones, journeys and their stops, the lettered
squares, the 10 by 10 blocks and the tile outlines. In the pixel-art style a town is drawn as buildings put
together from its size and features: a hut (a tent for nomadic peoples) for a hamlet, houses for villages and
towns, a long hall and houses for a city, and a castle flying the state's colour for a capital; a church for a
temple, a tower for a citadel, a wall in front for walls, a boat for a port, shacks for a shanty town, crates
for a plaza. Forts, monasteries, caravanserais and trading posts have buildings of their own. Larger towns are
placed first, and a smaller one whose buildings would sit mostly on another's waits for a closer zoom.
Regiments are banners and fleets ships, in their state's colour; markers sit in square badges. In the smooth
style towns are pins (taller for capitals and cities, a square head for walls, a blue ring for ports, a dark
centre for capitals, a gold diamond for market centres). On a sheet, lines are cut exactly where they cross
the sheet's edge.

**Zones** are filled tile by tile: a zone's outline is cut to each tile it crosses, tiles wholly inside are
filled whole, and each piece lies on its own tile's top. So a zone that runs off a sheet is filled only over
the sheet, its holes stay open, and tiles at different heights neither cancel each other's fill nor double it.
The fill is worked out the first time zones are shown.

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

Sizes on Lania (pointy hexes): the Bayfshear sheet (1,661 tiles at radius 20) makes a 0.3 MB page; the whole
map at Azgaar's own 5-mile hexes (293,942 tiles, from a GeoPackage) 6.9 MB in about 40 seconds, with about
181,000 trees, rocks and other details placed in the browser as the page opens. The sprites are about 10 kB of
the page.

## Notes

- Marker and regiment icons: Azgaar 1.154 and newer store an emoji as its code points (`glyph-1f333`,
  `glyph-1f3f4-200d-2620-fe0f`). `azgaar_tiles.py` 1.1 writes the emoji itself; the page turns the code points
  back into emoji for exports made with 1.0, so they need not be exported again. Image icons fall back to a dot.
- The pixel-art details are drawn on the graphics card in one call, after the tiles and with the same depth,
  and their placement is worked out once when the page opens.

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
