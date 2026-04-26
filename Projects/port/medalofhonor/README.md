# Medal of Honor PS1 to Saturn Port Workspace

This folder contains repeatable extraction tooling for the local PS1 dump in:

`Projects/port/[PS1] Medal of Honor (PT-BR) [Dublado e Traduzido]`

Run the extractor from this project:

```powershell
.\tools\extract_ps1_assets.ps1 -Clean
```

Generated assets are written to `artifacts/ps1_extract`.

After the RSC assets exist, extract the discovered `.gfx` models:

```powershell
.\tools\extract_gfx_models.ps1 -Clean
```

Generated OBJ models are written to `artifacts/ps1_extract/models/gfx_obj`.

Extract stage-cell geometry from `.TSP` files:

```powershell
.\tools\extract_tsp_models.ps1 -Clean
```

Generated stage OBJs are written to `artifacts/ps1_extract/models/tsp_obj`.

Current coverage:

- Unpacks every `.RSC` archive entry.
- Converts standalone `.TIM`, `.RSC` TIM entries, and sequential `.TAF` TIM chunks to PNG.
- Preserves `.TAF` non-TIM tails for later reverse engineering.
- Carves `.BSD` chunks from their offset tables.
- Catalogs `.STR` movies and `.VB`/`.VAB` audio data.
- Extracts ASCII strings from executable, overlay, script and selected resource files.
- Converts extracted `.gfx` model resources to Wavefront `.obj` with `.mtl` and triangle CSV sidecars.
- Converts `.TSP` stage cells to Wavefront `.obj` with material and triangle CSV sidecars.

The original PS1 source files are not modified.
