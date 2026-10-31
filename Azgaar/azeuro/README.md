# azeuro

A merchant-commission Eurogame built from an Azgaar Fantasy Map Generator world. It is the third
sibling after `azork` (text adventure) and `azrpg` (tile RPG): the same world files, turned into a
print-and-play or screentop.gg component set.

## Use

Python 3.10+ with Pillow, cairosvg, shapely, scipy and numpy
(`pip install pillow cairosvg shapely scipy numpy`).

    cd Azgaar/azeuro
    python -m azeuro build Batan                     # everything, SVG and PNG -> out/Batan/
    python -m azeuro build Batan --formats svg       # vector only (fast)
    python -m azeuro build Lania --only board,budget # just some parts
    python -m azeuro info Batan                      # summary, nothing drawn

The world folder (`Azgaar/<World>/`) needs a `.map`; the newest is used unless `--map` names one.
A Cells GeoJSON export in the same folder (matched by content) adds the biome tint, the history
zones and, if the save has no states layer, the state territories. Without it the board is still
complete. `--only` writes a manifest of the parts it built, so finish with a full build.

The bundled Barlow fonts (SIL Open Font License, `azeuro/fonts/OFL.txt`) are registered with
fontconfig on the first PNG run, so PNGs match the SVGs. SVGs name the fonts; install Barlow and
Barlow Condensed to view them exactly.

## Output

    out/<World>/
      board/<World>_board.svg|png        the game board with its legend strip
      commissions/<State>/...            one front per card, plus <State>_back
      events/event_NNN, event_back
      infrastructure/land|sea|air|wild, infrastructure_back
      budget/house_N_<Town>              one budget board per player colour
      tokens/plus50_marker
      sheets/                            sprite sheets for screentop.gg (see below)
      manifest.csv                       every image with its deck, count and a note
      cards.json                         all card data (commissions, events, stops, links, stars)
      summary.json, REPORT.md            what was built and why

Sizes (CSS px at 96 px/in; PNG at `--dpi`, default 300): commission 88.9 x 63.5 mm (landscape
poker), event 70 x 121 mm (tarot), infrastructure 63.5 x 88.9 mm (poker), budget board A4
landscape, +50 marker 19 mm. No bleed. Card PNGs are 256-colour (`--full-colour` to change).

## Sprite sheets for screentop.gg

Every build also writes `sheets/`: same-size faces packed on a plain grid (no margins, no
gutters, row by row from the top left, unused cells transparent), at most `--sheet-max` (4096) px
on each side, cards rasterised at `--sheet-dpi` (200). With the defaults a sheet holds 40
commission cards (5 x 8 at 700 x 500), 28 event cards (7 x 4 at 550 x 950) or 40 infrastructure
cards (8 x 5 at 500 x 700).

    commissions_<State>[_N].png   that state's deck in deck order
    commissions_<State>_back.png  its back, same cell size
    events[_N].png, event_back.png
    infrastructure[_N].png        the whole infrastructure deck, every copy laid out
    infrastructure_faces.png      the four faces once each, if you set counts in screentop instead
    infrastructure_back.png
    tokens_plus50.png             one marker per copy
    <World>_board.png             the board scaled to fit 4096 px
    budget_house_N_<Town>.png     each budget board, scaled to fit 4096 px

`sheets/sheets.csv` gives each sheet's columns, rows, card count, cell size and card order (the
card order matches the file names in `commissions/`, `events/` and so on). A last sheet that is
not full has blank cells at the end; set the card count in screentop to the number in the CSV.
`--no-sheets` skips them.

## How the world becomes a game

**Stops.** Every market's central burg (commissions run between markets), every capital, every
fort, and every burg the map names as an air site. Then burgs of Azgaar's size class "city",
largest first, kept only if at least `--spacing` (x map width, default 0.016) from every stop
already kept. Maps without a "city" group use the top decile by population.

**Links.** Azgaar's route graph is split by mode: sea routes are sea, roads and trails are land.
Each mode is contracted with a network Voronoi: every route cell belongs to its nearest stop
along the routes, and two stops are linked where their territories touch. Links never pass
through a third stop, and a route can change mode only at a stop. Stops that cannot reach the
rest are joined by adding the burgs where the cheapest connection changes mode.

**Neutral stations.** The largest stops, spread at least 15% of the map width apart (default:
half the number of states, 3 to 6).

**Air sites.** Burgs at the ends of air-domain journey legs and next to portal markers. If the map
has fewer than two, the largest stops spread at least 12% of the map width apart (default:
states / 2 + 2, 4 to 7), sharing at most `--air-overlap` (default 1) with the neutral stations.

**Event stars.** Each marker is snapped to the nearest link: green on land, blue at sea. Markers
further than `--remote` (x map width, default 0.015) from every link stay where they are as
white (air) stars. Campaign markers (type `party`) are left out.

**Commissions.** One card per market-to-market deal, filed in the seller state's deck (export)
and again in the buyer state's deck (import); deals within one state are filed once. Deals in
unclaimed land go only to the claimed side (`--neutral-deck` makes a deck for them). Decks smaller
than `--min-deck` (6) are padded with numbered copies; the deal code on every card lets players
enforce the rule that no two active commissions share a deal.

    income = round(k x stops x tier), k = 0.75, clamped to 2..20
    stops  = stops on the fewest-stops land/sea route between the two market towns (both ends),
             else via air sites, else straight-line distance / median link length + 1
    tier   = deal value (units x price) by quartile: small 1, standard 1.25, large 1.5, major 2
    split  = most / second / third stations, about 55 / 30 / 15 percent; ties go to the declarer

**Events.** Every marker gives one text for each colour its type suits (a bridge: land and sea; a
volcano: air; a mine: land and air), written for that marker by name. Generic names ("Dungeon",
"Pirates") are located by the nearest stop. Each colour has its own risk profile so the mix of a
player's stars matters: land is small and slightly negative (45% positive), sea swings large
both ways (50%), air is mostly good (70%) with rare heavy losses. The deck size defaults to the
largest colour pool, so every marker text is used; shorter colours are filled with the markers'
other-polarity texts, then generic events. The manifest lists each card's three sources and
polarities, to help choose a smaller set.

**Houses.** One per player colour, rooted in the richest exporting market of a different state:
two specialty goods (+1 income), an infrastructure charter (sky: air +4; shipwrights: sea +1;
carters: land +0 in the home state) and one extra card when drawing that state's commissions.

**Infrastructure deck.** Scarcity follows cost: land `--infra-land` (50), sea 50/2, air 50/5,
plus wilds at `--wild-share` (12%) of the deck.

## Options

Run `python -m azeuro --help` for the full list: network (`--spacing --neutral --air --air-overlap
--remote`), commissions (`--income-k --income-min --income-max --min-deck --min-value
--max-per-state --neutral-deck`), events and houses (`--events --seed --players --colours`),
infrastructure (`--infra-land --wild-share`) and output (`--formats --dpi --board-width --only
--jobs --full-colour --no-sheets --sheet-dpi --sheet-max`).
