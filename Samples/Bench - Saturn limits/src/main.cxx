#include <srl.hpp>

using namespace SRL::Types;
using namespace SRL::Math::Types;

namespace
{
    volatile uint32_t gVblankCounter = 0;

    void OnVblankCounter()
    {
        gVblankCounter++;
    }

    struct FpsMeter
    {
        uint32_t lastVblank = 0;
        uint32_t frames = 0;
        uint32_t lastFps = 0;

        void Begin()
        {
            lastVblank = gVblankCounter;
            frames = 0;
            lastFps = 0;
        }

        void Tick()
        {
            frames++;

            // NTSC: ~60 vblanks por segundo; PAL: ~50.
            // Aqui a gente mede em "janelas" de 60 vblanks (aprox. 1s no NTSC).
            const uint32_t v = gVblankCounter;
            const uint32_t elapsed = v - lastVblank;
            if (elapsed >= 60)
            {
                lastFps = (frames * 60) / elapsed;
                frames = 0;
                lastVblank = v;
            }
        }
    };

    enum class Scenario : uint8_t
    {
        SpriteFlood = 0,
        PolygonFlood = 1,
        Mixed = 2,
        Count
    };

    const char* ScenarioName(Scenario s)
    {
        switch (s)
        {
        case Scenario::SpriteFlood: return "SpriteFlood";
        case Scenario::PolygonFlood: return "PolygonFlood";
        case Scenario::Mixed: return "Mixed";
        default: return "?";
        }
    }

    void DrawSpriteFlood(int32_t textureIndex, uint32_t spriteCount)
    {
        // Grade simples de sprites; a carga aqui é mais "VDP1 draw/list".
        const int16_t startX = -150;
        const int16_t startY = -90;
        const int16_t stepX = 16;
        const int16_t stepY = 16;

        uint32_t drawn = 0;
        for (int16_t y = 0; y < 15 && drawn < spriteCount; y++)
        {
            for (int16_t x = 0; x < 20 && drawn < spriteCount; x++)
            {
                const int16_t px = startX + x * stepX;
                const int16_t py = startY + y * stepY;
                SRL::Scene2D::DrawSprite(textureIndex, Vector3D(px, py, 500.0));
                drawn++;
            }
        }

        // Se o usuário pedir mais sprites do que cabem na grade, empilha no centro.
        while (drawn < spriteCount)
        {
            SRL::Scene2D::DrawSprite(textureIndex, Vector3D(0.0, 0.0, 500.0));
            drawn++;
        }
    }

    void DrawPolygonFlood(uint32_t polygonCount)
    {
        // Polígonos 2D (quads/tri via DrawPolygon). Objetivo: estressar VDP1 primitive list.
        // Mantém tamanhos pequenos para aumentar contagem.
        Vector2D quad[4] = {
            Vector2D(-4.0, -4.0),
            Vector2D( 4.0, -4.0),
            Vector2D( 4.0,  4.0),
            Vector2D(-4.0,  4.0)
        };

        for (uint32_t i = 0; i < polygonCount; i++)
        {
            const int16_t x = static_cast<int16_t>((i * 7) % 320) - 160;
            const int16_t y = static_cast<int16_t>((i * 13) % 240) - 120;

            Vector2D moved[4] = {
                quad[0] + Vector2D(x, y),
                quad[1] + Vector2D(x, y),
                quad[2] + Vector2D(x, y),
                quad[3] + Vector2D(x, y)
            };

            // Alterna preenchido/borda pra variar comando.
            const bool filled = (i & 1) == 0;
            SRL::Scene2D::DrawPolygon(moved, filled, HighColor::Colors::White, 500.0);
        }
    }
}

int main()
{
    SRL::Core::Initialize(HighColor::Colors::Black);

    // VBlank counter
    SRL::Core::OnVblank += OnVblankCounter;

    // Textura pequena (se não existir, o build vai falhar). Use a mesma do TestProject.
    SRL::Bitmap::TGA* tga = new SRL::Bitmap::TGA("TEST.TGA");
    int32_t textureIndex = SRL::VDP1::TryLoadTexture(tga);
    delete tga;

    Scenario scenario = Scenario::SpriteFlood;

    // Controles simples por frame: alterna cenário a cada ~5s
    const uint32_t scenarioDurationVblanks = 60 * 5;
    uint32_t scenarioStartVblank = gVblankCounter;

    // Parâmetros iniciais; vão subir até "quebrar" o FPS e aí você ajusta.
    uint32_t spriteCount = 200;
    uint32_t polygonCount = 800;

    FpsMeter fps;
    fps.Begin();

    while (1)
    {
        fps.Tick();

        // Rotação automática de cenário por tempo
        if ((gVblankCounter - scenarioStartVblank) >= scenarioDurationVblanks)
        {
            scenarioStartVblank = gVblankCounter;
            scenario = static_cast<Scenario>((static_cast<uint8_t>(scenario) + 1) % static_cast<uint8_t>(Scenario::Count));

            // Reinicia contador de FPS pra não misturar janelas
            fps.Begin();
        }

        // Ramp leve de carga dentro do cenário (pra você ver o ponto onde cai)
        if ((gVblankCounter & 31) == 0)
        {
            if (scenario == Scenario::SpriteFlood) spriteCount += 20;
            if (scenario == Scenario::PolygonFlood) polygonCount += 50;
            if (scenario == Scenario::Mixed) { spriteCount += 10; polygonCount += 25; }
        }

        // HUD
        SRL::Debug::Print(1, 1, "Bench - Saturn limits");
        SRL::Debug::Print(1, 3, "Scenario: %s", ScenarioName(scenario));
        SRL::Debug::Print(1, 4, "FPS (est): %d   ", fps.lastFps);
        SRL::Debug::Print(1, 6, "Sprites:  %d   ", spriteCount);
        SRL::Debug::Print(1, 7, "Polygons: %d   ", polygonCount);
        SRL::Debug::Print(1, 9, "Troca auto a cada ~5s");

        // Desenho
        switch (scenario)
        {
        case Scenario::SpriteFlood:
            DrawSpriteFlood(textureIndex, spriteCount);
            break;
        case Scenario::PolygonFlood:
            DrawPolygonFlood(polygonCount);
            break;
        case Scenario::Mixed:
            DrawSpriteFlood(textureIndex, spriteCount);
            DrawPolygonFlood(polygonCount);
            break;
        default:
            break;
        }

        SRL::Core::Synchronize();
    }

    return 0;
}
