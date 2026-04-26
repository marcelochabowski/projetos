# Bench - Saturn limits

Benchmark simples para medir, na prática, **até onde o Saturn aguenta** com SaturnRingLib (SRL) em cenários controlados.

## O que mede

- FPS estimado por contagem de VBlank (`SRL::Core::OnVblank`)
- Carga de desenho no VDP1 em três cenários:
  - `SpriteFlood`: muitos sprites
  - `PolygonFlood`: muitos polígonos 2D
  - `Mixed`: mistura dos dois

O benchmark aumenta gradualmente a carga dentro de cada cenário e alterna cenário a cada ~5s.

## Como rodar

- Compile: `compile.bat`
- Limpar: `clean.bat`
- Executar no Mednafen (se existir no repo): `run_with_mednafen.bat`

## Observações

- O projeto espera um arquivo `TEST.TGA` no CD do sample (mesma ideia do `Samples/TestProject`).
- `FPS (est)` usa janela de 60 vblanks (pensado para NTSC). Se você estiver em PAL, a leitura fica menos precisa; dá pra ajustar para 50.
