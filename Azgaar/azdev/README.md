# azdev

Moves an Azgaar world onto the full development scale (1–100) without turning it into a ladder. It
runs the model from *Development without a ladder* (v0.1) over the world's own geography, then hands
the result to the Generator in the forms it accepts: CSV uploads, a notes file, and a copy of the
`.map` whose settings record carries the new goods. A sibling of `azork`, `azrpg` and `azeuro`.

## Use

Python 3.10+ with numpy, scipy and scikit-learn (`pip install numpy scipy scikit-learn`).

    cd Azgaar/azdev
    python -m azdev info Batan                 # what the world holds; checks the development port
    python -m azdev build Batan                # full ensemble, writes out/Batan/
    python -m azdev build Batan --diagnose     # also runs failure checks F5 and F6 (about +70% time)
    python -m azdev build Batan --steps 4000   # a longer horizon: leading edges go deeper

Put the folder beside the other tools (`Azgaar/azdev/`); worlds are found in `Azgaar/<World>/`,
or pass `--root`. The world folder needs a `.map` saved by Generator **1.157 or later** (that is
when development began to be saved); the newest is used unless `--map` names one. Open and re-save
older maps in the current Generator first. Maps with a graph override (wrap tool) are refused.

A full build on Batan (96 communities, 21 runs of 2500 steps) takes about three and a half minutes on two
cores, six with `--diagnose`.

## What it writes, and the upload order

    out/<World>/
      0 Read me first.md          the steps below, filled in for this world
      1 <World> azdev.map         your map; only the settings record differs (goods, culture multipliers, era names)
      2 <World> Biomes.csv        biome Development offsets       (Tools → Biomes → upload)
      3 <World> Cultures.csv      culture Development and tags    (Tools → Cultures → upload)
      5 <World> States.csv        state form names, if any change (Tools → States → upload)
      6 <World> Notes.csv         each culture's profile           (Tools → Notes → Upload notes)
      <World> azdev report.html   what the run found and why
      summary.json

1. Save the open map. 2. Load `1 … azdev.map`. 3. Upload the Biomes CSV. 4. Upload the Cultures CSV.
5. **Tools → Development → Regenerate** (levels and offsets do nothing until this). 6. Upload the
States CSV (optional). 7. Upload the Notes CSV. 8. **Tools → Regenerate → Economy** with *Production*
ticked and **Restore goods unticked** (it would remove the new goods). 9. Save.

Every CSV holds only `Id`, the entity's current name (unchanged, so skipped) and the columns that change,
in the editors' own export format, so the Generator's upload preview shows exactly what will be set.
Culture tags keep the culture's existing tags. Notes are added below any existing note, inside a
`<div title="azdev">` block that a re-run replaces.

Only goods, multipliers and era names need the `.map`: the Generator cannot add goods, recipes or
per-culture multipliers by upload. The patched record re-serialises the original byte for byte apart
from those changes; every other field is copied untouched.

## How one number is made from many

The model has no development axis. Communities (culture × province) carry intensities of about a
hundred practices; axes, basins and flourishing profiles are computed afterwards. Azgaar still reads
one number per cell, so azdev projects onto it explicitly:

**development = depth of elaboration along a people's own path**: the tier of the most elaborate
practice it sustains (held at 0.3 counts in full; 0.1–0.3 lifts it part way). Every practice is
anchored to Azgaar's tiers (bronze casting 12, gunpowder 30, cannon 36) and the new practices run to
100 on several paths: industrial (steel 50 … fusion, orbital flight 100), agro-ecological (agroforestry
45 … living architecture 100), ceremonial (calendar and sky lore 45 … ancestral archives 100), maritime
(voyaging 40 … ocean commons 90), pastoral (felt and composite bows 40 … rangeland federations 80),
tribute (porcelain, registers 40 … great hydraulic works 60), medicine (herbal medicine 40 … living
reactors 90). Two peoples at 60 can be at 60 in different ways.

The scalar's four jobs in the Generator are then taken back from it:

| Azgaar job | What azdev does |
| --- | --- |
| which goods a cell can make (good tier) | each new good is made by one practice of the same tier; a culture's multiplier on it is 0 if the practice is unknown to it, low if only remembered |
| how much it makes (productivity = development / 30) | per good and culture, the multiplier replaces the scalar's generic gain with the depth and intensity of the practices that make that good |
| what states are called | tribal titles are fixed where development crosses 12; `--retitle basin` names every state after its capital's basin (listed forms only within the state's own government) |
| who trades first (√population × development) | cannot be changed by upload; the report's check P1 says whether development ranks with mobilisable capacity |

Each culture's level is set so that the Generator's own regenerated field averages the culture's
depth: azdev contains an exact port of `Development.generate()` and of the pack rebuild, and corrects
the levels against it twice. The pack rebuild triangulates with an exact port of the Generator's
Delaunator 5.1.0 (`delaunator.py`), because the order of a grid cell's neighbours decides how coastal
cells are split and numbered; scipy's triangulation gave the right neighbours in another order, which
swapped pack cells on split coasts. With it the port reproduces the saved field on every cell of Batan
(8,036) and Beres (4,627), and every pack cell's neighbours match the Cells GeoJSON in order. With the
earlier, inexact rebuild, the Generator's regenerated field after the uploads matched the prediction
on 99.4% of Batan's cells and on every culture's average.

Biome offsets (`--biome-offsets derived`, the default) come from the run: how much more or less
elaborate a culture's communities are by the biomes they live in, by ridge regression, ±6, only for
biomes with enough people to say. `keep` leaves them; `zero` removes them.

## The model in the code

`model.py` carries every term of the spec's equations: practice intensities with feasibility
(smooth Liebig minimum), coupling (mechanical from the recipes, plus each scenario's theory), attended
benefit net of capture, adoption cost reduced by memory, imitation by information conductance,
innovation and recall, noise; stocks with production, inputs, decay, consumption, trade and capture;
land that recovers and is built up or run down; population; attention that drifts to what is made and
jumps on stress past a threshold that is higher for what is little watched; memory that fades more
slowly where memory practices are strong; and one capture relation (appropriability × reach ×
asymmetry × no exit). Capture is booked by form (tribute, raiding, debt, displacement, and within
communities ritual monopoly and household capture). The seven scenarios S1–S7 are in
`data/scenarios.json`; continuous parameters are drawn per run.

### Changes to the spec, all marked in the code

These were needed to get a calibrated, non-degenerate run and are value-laden in their own right.

- **Basins** are clusters of how a community differs from the rest of its world in the same run.
  What a whole run shares is the scenario's institutional layer, reported per scenario. Clustering
  raw states found mostly the theories, not the places.
- **Upkeep**: every practice pays a small cost each step whatever is remembered (otherwise a
  remembered practice with any support saturates).
- **Complexity overhead** (Tainter): holding many elaborate practices costs food.
- **Wants grow with attention**: an attended stock's target rises with attention. This is what
  drives elaboration; without it satisfied communities have no reason to change.
- **Ripeness** (Kauffman): once a practice's prerequisites are held at twice their minimum, its
  adoption barrier falls by up to 70%. Memory practices also make learning cheaper.
- **Reach and memory** are worth something in themselves (mobility, communication and memory weights
  add to benefit); the stock accounts otherwise miss them.
- **Attention floor**: benefits count at 0.15 + 0.85 × attention, so a stock is never wholly unseen.
- **Felt norms** for non-subsistence stocks come from what a people makes or remembers making.
- **Calibration**: the benefit scale is set at the first step so the present map is near balance.
- **Abandonment**: a practice that can no longer be supplied is given up (the spec freezes it).
- **Elaboration pays**: deeper practices yield more of what they make (× 1 + tier/40).
- Population moves only within 0.8–1.25 of its present size (the Generator's population is not changed).
- Simplified: no internal groups (ritual monopoly and household capture are proxies); no migration;
  trade is diffusion along cost distance; information distance is material distance with a range that
  grows with communication practices.

### Calibration status

Provisional, tuned on Batan only. On Batan every check passes except **F6 (no feedback)**: fixing
attention barely moves the basins, so there the basins are carried by geography and coupling, not by
the attention loop. Basins are robust across all seven scenarios (F4), geography matters (F5: about
half the communities change basin when affordances are dealt out at random), no ladder or best
society emerges (F1, F3, P2), and development does not rank with capacity for violence (F2, P1).
The leading edge moves slowly: at 1500 steps most communities sit at 40–50; at 2500–4000 steps some
reach 70–90 (ocean commons, engines) while others stay. A longer `--steps` deepens the world.

The knobs are the constants at the top of `model.py`, the ranges in `data/scenarios.json`, and the
catalogue. To try your own catalogue, copy `azdev/data/` and pass `--catalogue <folder>`.

## The catalogue (where the value judgements sit)

    data/stocks.json     26 stocks: property vectors (storability, transportability, legibility,
                         divisibility, excludability, renewability), need groups, wear
    data/practices.json  97 practices: tier, labour, requirements, yields, inputs, land effects,
                         memory/communication/mobility, capacity weights, the Azgaar goods they make
    data/goods_new.json  40 goods to add (2 below tier 36 that fill gaps: root crops, fermented milk),
                         with recipes by name, aliases for older catalogues, demand coverage, emoji icons
    data/scenarios.json  the scenario ensemble and parameter ranges
    data/basins.json     names for basins, matched after the fact by practice hint words
    data/names.json      era names from 40 up, and state titles by basin and government

New goods' values are worked out from their recipes at the map's own prices. A recipe whose
ingredient the map lacks is dropped; a good with none left is skipped and listed.

## Options

    --steps N               run length (2500); one step is a few years
    --seeds N               runs per scenario (3)
    --scenarios S1,S5       a subset of the ensemble
    --start origins         start from first foragers instead of the map as it is
    --depth-stat 75         set levels from a more favourable history than the median run (50)
    --target-max N          probe longer horizons until the leading edge reaches N (cap --max-steps)
    --biome-offsets MODE    derived | keep | zero
    --retitle MODE          fix | basin | none
    --no-rebase             leave existing goods' culture multipliers alone
    --no-base-goods         add nothing below tier 36
    --keep-eras             keep the era names
    --diagnose              run F5 (geography shuffled) and F6 (attention fixed)
    --workers N             parallel processes

## Checked in the Generator

The Batan package was loaded into the Generator (1.158, run locally, headless) and taken through every
step above: the map loads with 111 goods and the new era names, both CSV previews apply, the culture
levels and biome offsets match the files, the notes land, the regenerated development field matches
azdev's prediction on 99.4% of cells (every culture's average to the decimal; this was before the pack
rebuild was made exact, see above), and the economy runs
without errors, with about a quarter of burg output in the new goods (ritual regalia, shell valuables,
star charts, remedies, voyaging canoes, fermented milk).

## Tests

    AZDEV_TEST_MAP="Azgaar/Batan/Batan 2026-11-11-19-43.map" python -m pytest tests

The Delaunator test runs without a map (its expected output comes from the JavaScript library). If a
`<World> Cells ….geojson` from the same save sits beside the map, the rebuilt pack's neighbours are
checked against it cell by cell.
