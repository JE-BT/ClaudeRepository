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
      commissions/<Trade>/...            one front per card, plus <Trade>_back
      decrees/decree_NNN_<kind>, decree_back
      reference/reading_a_decree         table reference card (one per player)
      reference/decree_anatomy           annotated decree for the rules
      infrastructure/land|sea|air|wild, infrastructure_back
      budget/house_N_<Town>              one budget board per player colour
      tokens/plus50_marker
      sheets/                            sprite sheets for screentop.gg (see below)
      manifest.csv                       every image with its deck, count and a note
      cards.json                         all card data (commissions, decrees, stops, links, stars)
      summary.json, REPORT.md            what was built and why

Sizes (CSS px at 96 px/in; PNG at `--dpi`, default 300): commission 88.9 x 63.5 mm (landscape
poker), decree and reference 70 x 121 mm (tarot), infrastructure 63.5 x 88.9 mm (poker), budget board A4
landscape, +50 marker 19 mm. No bleed. Card PNGs are 256-colour (`--full-colour` to change).

## Sprite sheets for screentop.gg

Every build also writes `sheets/`: same-size faces packed on a plain grid (no margins, no
gutters, row by row from the top left, unused cells transparent), at most `--sheet-max` (4096) px
on each side, cards rasterised at `--sheet-dpi` (200). With the defaults a sheet holds 40
commission cards (5 x 8 at 700 x 500), 28 decree cards (7 x 4 at 550 x 950) or 40 infrastructure
cards (8 x 5 at 500 x 700).

    commissions_<Trade>[_N].png   that trade's deck in deck order
    commissions_<Trade>_back.png  its back, same cell size
    decrees[_N].png, decree_back.png
    reference.png                 the decree reference card, one per player
    decree_anatomy.png            the annotated decree, scaled to fit 4096 px
    infrastructure[_N].png        the whole infrastructure deck, every copy laid out
    infrastructure_faces.png      the four faces once each, if you set counts in screentop instead
    infrastructure_back.png
    tokens_plus50.png             one marker per copy
    <World>_board.png             the board scaled to fit 4096 px
    budget_house_N_<Town>.png     each budget board, scaled to fit 4096 px

`sheets/sheets.csv` gives each sheet's columns, rows, card count, cell size and card order (the
card order matches the file names in `commissions/`, `decrees/` and so on). A last sheet that is
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

**Favour stars.** Each marker is snapped to the nearest link and marked with a gold star. Markers
further than `--remote` (x map width, default 0.015) from every link stay where they are and can
be access by flying a route between air infrastructures that passes nearby. Campaign markers 
(type `party`) are left out.

**Commissions.** One card per market-to-market deal, filed by trade: Provisions, Luxuries, Metals &
arms, Building, Livestock and Slaves (`goods.py` groups Azgaar's goods by their unit and tags, so
any world works). Every deal appears once. Deals with a market in unclaimed land stay in their trade
deck and show "Free lands" for that side. `--no-slaves` leaves the slave trade out entirely.

    income = round(k x stops x tier), k = 0.75, clamped to 2..20
    stops  = stops on the fewest-stops land/sea route between the two market towns (both ends),
             else via air sites, else straight-line distance / median link length + 1
    tier   = deal value (units x price) by quartile: small 1, standard 1.25, large 1.5, major 2
    split  = most / second / third stations, about 55 / 30 / 15 percent

**Decrees.** Proclamations by state rulers, built from the world's history and markers. Every card
has the same parts: issuer (ruler title from the state's form) and treasury class; title and cause;
an affected area visible on the board (a state, named stops or named links); an optional on-reveal
effect; one edict that applies every round; three petitions at 1, 3 and 5 stars; and a line for
when the decree lapses. Sources:

    ongoing campaigns            War, one card per belligerent: levy on routes, gold for arms routes
    campaigns ended <= 2 years   Aftermath: gold for Building routes through the state
    embargoes, 30% tariffs       Embargo (closure, or a levy at a chokepoint), customs levy
    zones                        Invasion, Rebels, Proselytism, Crusade, Disease, Flood, Tsunami, ...
    markers                      Disorder (brigands, pirates, monsters...), Faith (sacred sites),
                                 Enterprise (mines, bridges, inns, libraries...), Court & festival
    theocracies                  sumptuary levy on Luxuries routes
    the slave trade              a league of the largest state that trades no slaves and its allies,
                                 and a revolt where most slave routes run

A closure is only used where most affected routes have a land or sea detour; at a chokepoint the
same decree charges a levy. Sources that touch fewer than about 1% of routes are dropped, and the
deck (`--decrees`, default 30) is balanced across families and states.

Money on decrees is always marked: a gold coin is gold, once; a yellow chip moves the income track; a
red chip moves the expense track. Gold appears in a petition only when its benefit is shared by
every player (marked SHARED); the issuer's treasury sets the price: rich 2, modest 4, poor 6 gold at
five stars. A five-star petition settles the decree: the petitioner keeps the card and gains +2
income (+3 if the decree touches 20% or more of routes).

**Houses.** One per player colour, rooted in the richest exporting market of a different state:
two home trades (the market's largest export trades, never Slaves), which open for less
(`--home-overhead`); an infrastructure charter (sky: air +4; shipwrights: sea +1; carters: land +0
in the home state); and the patronage of one decree family (War, Disaster, Disorder, Faith,
Enterprise, Court & festival), whose decrees the house petitions for one star less. Patronages are
dealt so no two houses share one, matched to the families the home state issues most.

**Budget boards.** A 20-station yard in rows of five (first row free, then upkeep discs 1, 2, 3);
the round and turn summary; settle accounts with the debt boxes (`--debt-rounds`: rounds in a row a
player may end below 0 gold before they are out); infrastructure costs; and the trades panel, where
opening a trade costs `--overhead` (default 30 gold, or `--overhead-mode expense` for a standing
cost on the expense track). `--petitions round` moves petitions to the start of the round, with
decrees and accounts, so every money matter is settled at once.

**Infrastructure deck.** Scarcity follows cost: land `--infra-land` (50), sea 50/2, air 50/5,
plus wilds at `--wild-share` (12%) of the deck.

## Options

Run `python -m azeuro --help` for the full list: network (`--spacing --neutral --air --air-overlap
--remote`), commissions (`--income-k --income-min --income-max --min-value --max-per-trade
--no-slaves --freight`), decrees (`--decrees --seed`), houses and budget boards (`--players
--colours --goal --start-gold --stations --overhead --home-overhead --overhead-mode --debt-rounds
--petitions --draw`), infrastructure (`--infra-land --wild-share`) and output (`--formats --dpi
--board-width --only --jobs --full-colour --no-sheets --sheet-dpi --sheet-max`).
