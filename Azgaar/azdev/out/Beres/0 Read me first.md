# Beres: moving to the full development scale

Made by azdev on 2026-11-25. Do the steps in this order: development must be regenerated before the economy, and the goods must be in the map before production runs.

1. Save the map you have open (**Save → Save to machine**). Uploads change the map at once and cannot be undone.
2. **Load** `1 Beres azdev.map` (**Load → Load from machine**). It is your map with only its settings record changed: 40 goods added, every good's culture multipliers set from the run, and the era names from 40 up renamed. Your goods now also carry over to new maps in this browser; *Tools → Regenerate → Economy → Restore goods* brings the defaults back.
3. **Tools → Biomes**, upload `2 Beres Biomes.csv` (the upload button beside the download button). Check the preview: only the Development column changes. Apply.
4. **Tools → Cultures**, upload `3 Beres Cultures.csv`. The preview lists each culture's new Development level and its tags. Apply.
5. **Tools → Development** (Shift + X), press **Regenerate**. Culture levels and biome offsets do nothing until this is pressed. Painted development is replaced.
6. **Tools → Notes → Upload notes from PC**, `6 Beres Notes.csv`. Each culture gets its profile from the run, added below any note it already has.
7. **Tools → Regenerate → Economy**. Leave **Restore goods** unticked (it would remove the new goods); keep **Production** ticked. Tick **Deposits** too only if you want deposits re-placed.
8. Check the result: *Tools → Development* for the eras, the *Goods* layer for who makes the new goods, a culture's note for its profile. Then save the map.

## What each file changes

| File | Changes | How |
| --- | --- | --- |
| `1 Beres azdev.map` | goods catalogue, culture multipliers on goods, era names | Load |
| `2 Beres Biomes.csv` | biome Development offsets | Biomes editor upload |
| `3 Beres Cultures.csv` | culture Development levels, tags | Cultures editor upload |
| `6 Beres Notes.csv` | culture (and retitled state) notes | Notes editor upload |
| `Beres azdev report.html` | what the run found and why | open in a browser |
