# azork

Azgaar Fantasy Map Generator worlds as Zork-style text adventures. Standard-library Python 3.10+,
no installs. See PLAN.md for decisions and progress.

## Layout

```
ClaudeRepository/
  Azgaar/                 worlds: <World>.map, Cells GeoJSON, Watabou JSON, <World>_ledger.md
    Lania/content/        content pack: world.json, manifest.json
  azork/                  this project
    azork/                the package
    tests/                python -m unittest
    tools/                maintenance scripts (vendor_namebases.py)
```

## Commands (run from this folder)

```
python -m azork worlds
python -m azork inspect Lania     # files found and how Watabou files were placed
python -m azork plan Lania        # the journey plan as a travel table, plus faster options
python -m azork setup Lania       # files required before the story is generated (exit 1 if any missing)
python -m azork setup Lania --all # also the places that can be generated on demand
python -m azork validate Lania    # load every file
python -m azork play Lania --list # scenes that can be played
python -m azork play Lania --scene dwelling:house_on_the_hill
python -m azork play Lania --scene dungeon:5
python -m azork place Lania house_on_the_hill.json --burg Bayfshear --best   # place a dwelling
python -m unittest -v             # checks against Lania data, ledger canon and the engine
```

## Credits

Namebases and the name, link and file-format logic are ported from Azgaar's Fantasy Map
Generator (MIT licence). Town, village, dwelling and dungeon files come from Watabou's generators.
