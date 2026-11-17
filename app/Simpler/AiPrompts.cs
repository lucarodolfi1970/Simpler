using System;
using System.Collections.Generic;
using System.Linq;

namespace Simpler
{
    /// <summary>
    /// The AI functions of Simpler and how their prompts are built. Ported from renderAI (prompt_options.php, Luca's
    /// tested web wizard): the options the user picks are short Italian labels, the prompt sent to OpenAI is English
    /// (more consistent results), and its clauses keep the order that was found to work - what must NOT change first,
    /// the user's final notes last and imperative (said earlier they were ignored).
    /// </summary>
    public static class AiPrompts
    {
        public sealed record Opt(string Key, string Label, string Fragment, int Tier = 0);

        // ---------------------------------------------------------------- render → photorealism (and day/night)

        public static readonly Opt[] RenderTypes =
        {
            new("archviz_exterior", "Architettura · esterni", "a photorealistic architectural exterior building visualization"),
            new("archviz_interior", "Architettura · interni", "a photorealistic architectural interior visualization"),
            new("interior_residential", "Interni residenziali", "a photorealistic cozy residential interior design rendering"),
            new("landscape", "Paesaggio naturale", "a photorealistic natural landscape environment"),
            new("cityscape", "Città", "a photorealistic urban cityscape environment"),
            new("product", "Prodotto", "a photorealistic studio product design visualization"),
            new("automotive", "Auto", "a photorealistic automotive rendering of the vehicle"),
            new("industrial", "Industriale / tecnico", "a photorealistic industrial or technical facility interior visualization"),
            new("cyberpunk", "Cyberpunk / fantascienza", "a cyberpunk science-fiction environment with neon-lit futuristic architecture"),
            new("fantasy", "Fantasy / concept art", "a cinematic fantasy concept-art environment"),
        };

        static readonly Dictionary<string, string> RenderTypeHints = new()
        {
            ["archviz_interior"] = "Pay particular attention to glazed partitions and interior windows: in the source model they may appear as empty frames, but they should be rendered as real glass with reflections and transparency.",
            ["archviz_exterior"] = "Building facade openings should be rendered as real glazing with sky reflections and visible depth, not as flat dark holes.",
            ["interior_residential"] = "Glazed doors and windows must read as real glass with reflections of the interior space.",
            ["product"] = "Render accurate material separation between different components of the product.",
            ["automotive"] = "Car windows and windshield must be rendered as real automotive glass with reflections; body paint should show accurate clearcoat reflections.",
        };

        public static readonly Opt[] TimeOfDay =
        {
            new("as_is", "Come nell'immagine", ""),
            new("dawn", "Alba", "early dawn lighting with soft warm sunrise light"),
            new("midday", "Mezzogiorno, sole pieno", "bright midday sunlight with clear, sharply defined shadows"),
            new("golden_hour", "Ora d'oro / tramonto", "golden hour sunset lighting with warm orange tones"),
            new("blue_hour", "Ora blu", "blue hour twilight lighting, cool ambient tones mixed with warm interior lights"),
            new("night_artificial", "Notte, luci artificiali", "nighttime scene lit primarily by artificial lighting, dramatic contrast"),
            new("overcast", "Cielo coperto", "soft overcast diffused daylight with flat, even lighting"),
        };

        public static readonly Opt[] Haze =
        {
            new("none", "Nessuna", "no atmospheric haze"), new("light", "Leggera", "light atmospheric haze"),
            new("medium", "Media", "moderate atmospheric haze"), new("heavy", "Forte", "heavy atmospheric haze"),
        };
        public static readonly Opt[] Fog =
        {
            new("none", "Nessuna", "no fog"), new("light", "Leggera, a terra", "light ground fog"),
            new("medium", "Media", "moderate fog"), new("heavy", "Fitta", "dense fog"),
        };
        public static readonly Opt[] Gi =
        {
            new("balanced", "Equilibrata", "balanced, natural global illumination"), new("soft", "Morbida", "soft, gentle global illumination"),
            new("dramatic", "Drammatica", "dramatic, high-contrast global illumination"),
        };
        public static readonly Opt[] Shadows =
        {
            new("medium", "Medie", "medium-contrast shadows"), new("soft", "Morbide", "soft, diffused shadows"), new("hard", "Nette", "hard, sharply defined shadows"),
        };
        public static readonly Opt[] Reflections =
        {
            new("balanced", "Equilibrati", "balanced, realistic reflections"), new("subtle", "Discreti", "subtle, understated reflections"),
            new("strong", "Forti", "strong, glossy reflections"),
        };
        public static readonly Opt[] Styles =
        {
            new("standard", "Fotorealistico", "a clean, professional photographic style"),
            new("cinematic", "Cinematografico", "a cinematic color grade with rich contrast"),
            new("editorial", "Rivista", "an editorial magazine-style composition and grading"),
            new("hyperrealistic", "Iperrealistico + grana", "a hyperrealistic look with subtle film grain"),
        };
        public static readonly Opt[] Lenses =
        {
            new("standard", "Normale", "a standard focal length lens perspective"), new("wide", "Grandangolo", "a wide-angle lens perspective"),
            new("tiltshift", "Decentrabile (verticali dritte)", "an architectural tilt-shift lens look with corrected verticals"),
            new("tele", "Tele / sfocato", "a telephoto lens look with shallow depth of field and soft bokeh"),
        };
        // (Introduces new geometry: water - only on what is already visible)
        public static readonly Opt[] Materials =
        {
            new("glass", "Vetro", "Any thin rectangular frames, mullions, partitions or door openings must be rendered as clear architectural glass: physically correct transparency, visible reflections of the surrounding room on the glass surface, subtle green-tinted edges, and light refraction through the panes"),
            new("water", "Acqua", "Water surfaces must show realistic refraction, surface ripples and reflections", 1),
            new("mirror", "Specchi", "Mirrored surfaces must show sharp, physically accurate reflections of the room"),
            new("polished_metal", "Metallo lucido", "Metal elements must read as polished metal with anisotropic highlights and crisp reflections"),
            new("brushed_metal", "Metallo satinato", "Metal elements must read as brushed or satin metal with soft directional highlights"),
        };
        public static readonly Opt[] Seasons =
        {
            new("none", "Come nell'immagine", ""),
            new("spring", "Primavera", "early spring: deciduous trees and shrubs covered in fresh, bright, light-green new foliage, some still showing blossom; flowering plants in bloom; vivid green grass"),
            new("summer", "Estate", "high summer: dense, mature, deep-green foliage on every tree and shrub; lush thick grass; dry, sun-baked ground and paving; saturated, vivid colours"),
            new("autumn", "Autunno", "late autumn: the foliage of every deciduous tree and shrub turned to gold, amber, rust and deep red, with some branches already partly bare; fallen leaves scattered across the ground, lawns and paving"),
            new("winter", "Inverno", "deep winter: every deciduous tree, shrub and climbing plant COMPLETELY BARE, with no leaves left on any branch — only dark bare twigs and branch structure; snow lying on the ground, on roofs, on ledges, on steps, on outdoor furniture and on every upward-facing surface; any pool, pond, fountain or water surface frozen over or rimmed with ice, never liquid and blue; grass hidden under snow or dry and brown where it shows through; the pale, washed-out colours and cold cast of a freezing day"),
        };
        public static readonly Opt[] Weather =
        {
            new("none", "Come nell'immagine", ""),
            new("clear", "Sereno", "clear settled weather: an open blue sky with at most a few light clouds, crisp long-distance visibility and well-defined shadows"),
            new("rain", "Pioggia", "active rainfall: visible rain in the air, every horizontal surface wet and glistening, standing puddles that mirror the surroundings, materials darkened and saturated by water, an overcast sky and diffuse light with no hard shadows"),
            new("snow", "Neve che cade", "active snowfall: snowflakes clearly visible falling through the air, fresh snow settling and accumulating on every upward-facing surface, a flat white overcast sky, muted colours and soft shadowless light"),
        };

        // ---------------------------------------------------------------- staging

        public static readonly Opt[] StagingRooms =
        {
            new("living", "Soggiorno", "a living room"), new("bedroom", "Camera da letto", "a bedroom"),
            new("kitchen", "Cucina / pranzo", "a kitchen and dining area"), new("dining", "Sala da pranzo", "a dining room"),
            new("office", "Studio", "a home office"), new("kids", "Cameretta", "a children's bedroom"),
            new("bathroom", "Bagno", "a bathroom"), new("outdoor", "Terrazzo / esterno", "an outdoor terrace or balcony living space"),
        };
        public static readonly Opt[] StagingLevels =
        {
            new("moderate", "Medio", "a moderate level of furnishing: the key furniture plus a few well-chosen accessories (a rug, a plant, wall art)"),
            new("minimal", "Essenziale", "a minimal level of furnishing: only the essential pieces, showing the scale and function of the room without visual clutter"),
            new("full", "Completo", "complete styling: full furniture, textiles, decor, plants and accessories, magazine-ready"),
        };
        public static readonly Opt[] StagingStyles =
        {
            new("modern", "Moderno", "a modern contemporary furnishing style"),
            new("scandinavian", "Scandinavo", "a Scandinavian furnishing style with light woods and soft textiles"),
            new("japandi", "Japandi", "a Japandi furnishing style, warm minimalism"),
            new("classic", "Classico / elegante", "a classic, elegant furnishing style"),
            new("industrial", "Industriale", "an industrial furnishing style with metal, leather and dark wood"),
            new("farmhouse", "Rustico accogliente", "a cozy modern-farmhouse furnishing style"),
            new("luxury", "Lusso", "a high-end luxury furnishing style with refined materials"),
            new("coastal", "Marino", "a light, airy coastal furnishing style"),
        };
        public static readonly Opt[] Palettes =
        {
            new("none", "Decide l'AI", ""),
            new("neutral_warm", "Neutri caldi", "a warm neutral colour palette (beige, cream, warm wood tones)"),
            new("neutral_cool", "Neutri freddi", "a cool neutral colour palette (greys, off-whites, cool wood tones)"),
            new("earthy", "Terrosi", "an earthy colour palette (terracotta, olive green, natural clay tones)"),
            new("bold", "Accenti decisi", "a palette of confident bold accent colours over a neutral base"),
            new("monochrome", "Monocromo", "a sophisticated monochrome palette of blacks, whites and greys"),
        };

        // ---------------------------------------------------------------- people

        public static readonly Opt[] PeopleDensity =
        {
            new("sparse", "Poche", "only two or three people in total, discreetly placed so the architecture remains the subject of the image"),
            new("moderate", "Alcune", "a handful of people, roughly four to seven, distributed naturally across different depths of the scene"),
            new("busy", "Animato", "a lively but not crowded population, roughly eight to twelve people, spread across foreground, middle ground and background"),
        };
        public static readonly Opt[] PeopleScenes =
        {
            new("auto", "Adatto alla scena", ""), new("office", "Ufficio", "a working office environment"),
            new("retail", "Negozio / showroom", "a retail or showroom space"), new("hospitality", "Ristorante / bar", "a restaurant, café or hospitality space"),
            new("residential", "Casa", "a lived-in domestic space"), new("public", "Pubblico / culturale", "a public or cultural building such as a library, museum or lobby"),
            new("urban", "Esterno urbano", "an urban outdoor space, street or plaza"), new("landscape", "Parco / giardino", "a park, garden or landscaped outdoor area"),
        };
        public static readonly Opt[] PeopleActivities =
        {
            new("auto", "Adatte allo spazio", ""), new("working", "Lavorano", "working, using laptops, reviewing drawings or meeting"),
            new("walking", "Camminano", "walking through the space, some in gentle motion"), new("talking", "Parlano", "standing or sitting in conversation with each other"),
            new("sitting", "Seduti, rilassati", "seated, relaxing, reading or having a drink"), new("browsing", "Guardano", "browsing, looking at displays or at the view"),
        };
        public static readonly Opt[] PeopleClothing =
        {
            new("auto", "Adatto allo spazio", ""), new("casual", "Casual", "relaxed everyday clothing"), new("smart", "Smart casual", "smart casual clothing"),
            new("business", "Business", "business attire"), new("summer", "Estivo", "light summer clothing"), new("winter", "Invernale", "warm layered winter clothing with coats"),
        };
        public static readonly Opt[] PeopleAges =
        {
            new("children", "Bambini", "young children"), new("teens", "Ragazzi", "teenagers"), new("adults", "Adulti", "adults"), new("seniors", "Anziani", "older adults"),
        };
        public static readonly Opt[] PeopleGrouping =
        {
            new("auto", "Misto", "a natural mix of individuals and small groups"), new("individuals", "Singoli", "mostly people on their own"),
            new("couples", "Coppie", "mostly pairs of people together"), new("families", "Famiglie", "family groups with children"),
            new("groups", "Gruppi", "small groups of colleagues or friends"),
        };
        public static readonly Opt[] PeopleRegions =
        {
            new("auto", "Adatto alla scena", ""), new("northern_europe", "Nord Europa", "a Northern European setting"),
            new("mediterranean", "Mediterraneo", "a Mediterranean setting"), new("north_america", "Nord America", "a North American setting"),
            new("latin_america", "America Latina", "a Latin American setting"), new("middle_east", "Medio Oriente", "a Middle Eastern setting"),
            new("east_asia", "Asia orientale", "an East Asian setting"), new("south_east_asia", "Asia meridionale e sud-orientale", "a South or Southeast Asian setting"),
            new("africa", "Africa", "a Sub-Saharan African setting"),
        };
        public static readonly Opt[] PeopleFaces =
        {
            new("discreet", "Discreti (consigliato)", ""), new("visible", "Volti visibili", ""),
        };

        const string PeopleAnatomy = "ANATOMY — CRITICAL: every person must be anatomically correct and completely believable. Exactly two arms, two legs, five fingers per hand, correct joint articulation and natural body proportions. Absolutely no extra or missing limbs, no fused or malformed hands, no distorted or asymmetric faces, no duplicated identical people, no figures merging into each other or into the furniture. Poses must be relaxed and natural, the kind a candid photograph would capture — never stiff, never symmetrically posed, never looking at the camera as if posing for a portrait.";
        const string PeopleIntegration = "INTEGRATION — CRITICAL: the people must look photographed in this exact space, not pasted onto it. Scale them correctly against the architecture and furniture (door handles at hip height, worktops at waist height, seated figures sinking realistically into cushions). Every figure must make convincing contact with the floor or seat, with grounded contact shadows that match the direction, softness and colour temperature of the existing light in the image. Match the photograph's depth of field: people further away are slightly softer, and anyone in motion may show subtle natural motion blur. Match the grain, colour grading and white balance of the original image exactly. No glowing outlines, no cut-out edges, no lighting that contradicts the scene.";

        // ---------------------------------------------------------------- enhance

        public static readonly Opt[] EnhanceSubjects =
        {
            new("auto", "Riconosci da solo", ""), new("architecture", "Architettura / esterni", "an architectural exterior"),
            new("interior", "Interni", "an interior space"), new("landscape", "Paesaggio / natura", "a landscape or nature photograph"),
            new("product", "Prodotto", "a product photograph"), new("portrait", "Persone", "a photograph of people"),
            new("vehicle", "Veicolo", "a vehicle photograph"), new("action", "Sport / azione", "a sports or action photograph"),
        };
        public static readonly Opt[] EnhanceStrength =
        {
            new("standard", "Standard", "Recover a substantial amount of genuine detail and clarity across the whole image, while keeping every element recognisably the same."),
            new("faithful", "Fedele", "Stay as close to the original as physically possible: recover detail and remove softness, but change nothing else. When in doubt, leave it as it is."),
            new("cinematic", "Cinematografico", "Push the result to the quality of a professional cinematic capture: maximum genuine micro-detail, deep and clean tonality, crisp separation between planes — but strictly without restyling the scene or changing its mood."),
        };
        public static readonly Opt[] EnhanceFocus =
        {
            new("materials", "Materiali e tessuti", "fabric weave and stitching, stone, wood and metal grain"),
            new("vegetation", "Vegetazione", "individual leaves, veins, blades of grass and bark texture"),
            new("glass", "Vetri e riflessi", "believable reflections, refraction and highlights on glass, water and polished surfaces"),
            new("distance", "Sfondo e lontananze", "distant background elements, which must become legible instead of mushy"),
            new("faces", "Volti e pelle", "skin pores, eyelashes, individual hair strands and natural skin texture"),
        };
        const string EnhancePreservation = "ABSOLUTE PRESERVATION — this outranks every other instruction: keep the subjects' identity, facial structure, apparent age, expression and pose exactly as they are; keep clothing, accessories, objects, materials, colours, lighting direction and colour temperature, background, perspective, framing, crop and composition identical to the original. Do not add, remove, move, replace or restyle anything. Do not recompose, re-crop, straighten or zoom. Reproduce any text, signage, numbers or lettering exactly as written in the original, character for character. This is the same photograph, only seen with far better optics.";
        const string EnhanceForbidden = "FORBIDDEN — these ruin the result and must never appear: plastic, waxy or airbrushed skin; beautified, slimmed or rejuvenated faces; altered facial features or identity; over-sharpening halos and edge outlines; HDR-style glow; boosted or shifted saturation; invented objects, people, windows or decorations; altered or re-written text; a different crop or camera position.";

        // ---------------------------------------------------------------- camera angle

        public static readonly Opt[] CameraAngles =
        {
            new("wider", "Allarga l'inquadratura", "Keep the camera exactly where it is and widen the field of view, as if stepping back with a wider lens. Everything already visible must stay in the same relative position and perspective; simply reveal more of the surroundings at the edges — more sky, more ground, more of the neighbouring context — extending the scene outwards in a way consistent with what is already shown.", 1),
            new("closer", "Avvicinati", "Keep the same viewpoint and move the camera closer to the main subject, tightening the framing on it. The perspective and the angle stay the same: this is a closer, more detailed view of the same shot, showing materials and finishes at a larger scale.", 1),
            new("three_quarter", "Di tre quarti (spigolo)", "Move the camera to a three-quarter position so that the corner of the building faces the viewer and two facades are visible at once, one in full and one in perspective. Keep the same distance, the same eye height and the same lighting.", 2),
            new("eye_level", "Ad altezza d'occhi", "Lower the camera to the eye level of a person standing on the street in front of the scene, looking slightly upward. Keep the same direction of view and the same lighting; the scene simply gains the presence of a real pedestrian viewpoint.", 2),
            new("drone", "Dall'alto (drone)", "Raise the camera high above the scene, looking down at roughly 45 degrees as a drone would. The roof, the surrounding plot and the layout of the site become visible while the facades stay readable. Keep the same lighting and the same season.", 2),
            new("low_angle", "Dal basso, cinematografica", "Drop the camera close to the ground and tilt it upward, so the subject towers over the viewer with strong converging vertical lines. Cinematic, dramatic framing, same lighting conditions.", 2),
            new("side", "Di lato", "Move the camera around to view the subject from the side, roughly 90 degrees from the original viewpoint. Invent the side facade in a way that is fully consistent with the architectural language, the materials, the floor heights and the window rhythm already visible in the original image.", 3),
            new("rear", "Da dietro", "Move the camera around to the opposite side and show the subject from behind. Invent the rear elevation so that it is plainly the same building: same materials, same floor heights, same architectural vocabulary and detailing.", 3),
            new("top_down", "Dall'alto in pianta", "Place the camera directly overhead looking straight down, a plan-like aerial view. Invent the roof and the site layout consistently with the footprint and the volumes visible in the original image.", 3),
        };

        // ---------------------------------------------------------------- replace

        public static readonly Opt[] ReplaceActions =
        {
            new("remove", "Togli", ""), new("describe", "Sostituisci con una descrizione", ""), new("image", "Sostituisci con un oggetto (foto)", ""),
        };
        public static readonly Opt[] ReplaceBlends =
        {
            new("precise", "Solo l'area scelta", ""), new("reworked", "Rielabora tutta l'immagine", ""),
        };

        // ---------------------------------------------------------------- the functions

        public sealed record Function(string Key, string Name, string Desc, string Card);

        public static readonly Function[] Functions =
        {
            new("render", "Render → Fotorealismo", "Trasforma la vista o il render in una foto realistica", "card-render.jpg"),
            new("enhance", "Migliora", "Più dettaglio e nitidezza, senza cambiare l'immagine", "card-enhance.jpg"),
            new("variants", "Giorno, notte e stagioni", "La stessa vista all'alba, di notte, d'inverno, con la pioggia…", "card-variants.jpg"),
            new("people", "Aggiungi persone", "Persone realistiche, adatte allo spazio e alla luce", "card-people.jpg"),
            new("staging", "Arreda", "Mobili e oggetti in una stanza vuota, nello stile che scegli", "card-staging.jpg"),
            new("camera", "Cambia inquadratura", "La stessa scena più larga, più vicina o da un altro punto di vista", "card-camera.jpg"),
            new("replace", "Sostituisci", "Togli o cambia una cosa: disegni un rettangolo attorno", "card-replace.jpg"),
        };

        public static Opt Find(Opt[] list, string? key) => list.FirstOrDefault(o => o.Key == key) ?? list[0];

        static string F(Opt[] list, IDictionary<string, string> sel, string key, string def) =>
            Find(list, sel.TryGetValue(key, out var v) ? v : def).Fragment;

        static void Notes(List<string> parts, IDictionary<string, string> sel, string lead)
        {
            if (!sel.TryGetValue("notes", out var n) || string.IsNullOrWhiteSpace(n)) return;
            n = n.Trim();
            if (n.Length > 600) n = n[..600];
            parts.Add(lead + n);
        }

        /// <summary>The prompt of a function from the user's choices (keys as in the panel).</summary>
        public static string Build(string fn, IDictionary<string, string> sel, ISet<string> multi)
        {
            return fn switch
            {
                "enhance" => Enhance(sel, multi),
                "people" => People(sel, multi),
                "staging" => Staging(sel),
                "camera" => Camera(sel),
                "replace" => Replace(sel),
                _ => Render(sel, multi, fn == "variants"),
            };
        }

        static string Render(IDictionary<string, string> sel, ISet<string> multi, bool variants)
        {
            var type = F(RenderTypes, sel, "render_type", "archviz_exterior");
            var time = F(TimeOfDay, sel, "time", "as_is");
            var atmo = new[] { F(Haze, sel, "haze", "none"), F(Fog, sel, "fog", "none"), sel.ContainsKey("volumetric") ? "visible volumetric light rays" : "" }
                .Where(s => s != "").ToList();
            var parts = new List<string>
            {
                variants ? "Render this image as an exceptionally high-quality, photorealistic image of the same scene in different conditions."
                         : "Transform this 3D render preview into an exceptionally high-quality, photorealistic image.",
                $"Subject: {type}.",
            };
            parts.Add(time != "" ? $"Lighting: {time}." : "Lighting: keep the time of day, the direction and the colour of the light of the input image.");
            parts.Add("Atmosphere: " + string.Join(", ", atmo) + ".");
            parts.Add($"Global illumination: {F(Gi, sel, "gi", "balanced")}.");
            if (sel.ContainsKey("caustics")) parts.Add("Visible light caustics through glass or water surfaces.");
            parts.Add($"Shadows: {F(Shadows, sel, "shadows", "medium")}.");
            parts.Add($"Reflections: {F(Reflections, sel, "reflections", "balanced")}.");
            parts.Add($"Overall style: {F(Styles, sel, "style", "standard")}, viewed with {F(Lenses, sel, "lens", "standard")}.");
            var surf = Materials.Where(m => multi.Contains("mat:" + m.Key) && m.Tier == 0).Select(m => m.Fragment).ToList();
            var risky = Materials.Where(m => multi.Contains("mat:" + m.Key) && m.Tier == 1).Select(m => m.Fragment).ToList();
            if (surf.Count > 0)
                parts.Add("The following materials ARE present in this scene, even in places where the source render shows a surface as flat, empty, or without visible material cues (this is common for glass and reflective panels in early-stage 3D previews). Trust this declaration over what the raw preview visually suggests: " + string.Join("; ", surf) + ".");
            if (risky.Count > 0)
                parts.Add("The following elements are present in this scene — apply their properties only to objects already visible in the original composition, without introducing new objects that were not part of the original scene: " + string.Join("; ", risky) + ".");
            if (sel.TryGetValue("render_type", out var rt) && RenderTypeHints.TryGetValue(rt, out var hint)) parts.Add(hint);
            parts.Add("Preserve the exact composition, camera angle, object placement, proportions and geometry shown in the input image; only enhance realism, textures, lighting, materials and atmosphere. Do not add, remove or relocate structural elements.");
            var season = F(Seasons, sel, "season", "none");
            var weather = F(Weather, sel, "weather", "none");
            var sw = new[] { season, weather }.Where(s => s != "").ToList();
            if (sw.Count > 0)
                parts.Add("SEASON AND WEATHER — THIS IS A REQUIRED TRANSFORMATION, NOT AN OPTIONAL MOOD: the finished image must unmistakably read as " + string.Join(", and ", sw) + ". "
                    + "Apply it consistently to the ground, vegetation, water, sky and every outdoor surface, including whatever is visible through windows and openings. "
                    + "The time-of-day lighting specified earlier still governs the direction, height and warmth of the light: the season changes WHAT the light falls on, not the hour of the day. "
                    + "This seasonal and weather dressing is a change of SURFACES, VEGETATION, SKY and LIGHT, not of structure: it does not conflict with the preservation rule above, which governs buildings, terrain shape, object placement and camera. "
                    + "Adding snow cover, stripping leaves from deciduous plants, freezing a water surface or wetting paving are all REQUIRED here and must not be treated as adding or removing elements. A result that could pass for any other season has failed this instruction.");
            parts.Add("PEOPLE AND CHARACTERS: if the input image contains people or characters, treat each of them as a fixed subject. Keep every person's exact position, pose, gesture, gaze direction, body orientation, framing, age, build, hairstyle, clothing and accessories precisely as in the input. Upgrade ONLY their rendering quality: photorealistic skin, hair, eyes and fabric. Never replace a person with a different one, never turn them around, never add or remove people.");
            Notes(parts, sel, "FINAL INSTRUCTIONS FROM THE AUTHOR — these are deliberate creative choices and MUST be applied to the result (they refine the rendering, but never move, add or remove structural elements): ");
            return string.Join(" ", parts);
        }

        static string Staging(IDictionary<string, string> sel)
        {
            var parts = new List<string> { "This is a photograph of a real room. Virtually stage it as " + F(StagingRooms, sel, "room", "living") + "." };
            if (sel.ContainsKey("remove_existing"))
                parts.Add("First, remove all existing furniture, loose objects and clutter from the room, realistically reconstructing the floor, walls and any surfaces they were covering. Then furnish the emptied room from scratch.");
            parts.Add("Furnishing level: " + F(StagingLevels, sel, "level", "moderate") + ".");
            var pal = F(Palettes, sel, "palette", "none");
            parts.Add("Furnishing style: " + F(StagingStyles, sel, "style", "modern") + (pal != "" ? ", with " + pal : "") + ".");
            parts.Add("CRITICAL CONSTRAINTS — the architecture of the photograph is untouchable: keep the walls, floors, ceiling, windows, doors, radiators, light fixtures, the view outside the windows, the camera position, perspective and lens character EXACTLY as in the original photograph. Do not repaint walls, do not change flooring, do not move or resize openings. Only add furniture and decor.");
            parts.Add("Every added piece of furniture must be realistically scaled to the room, obey the photograph's perspective, sit convincingly on the floor, and cast soft shadows consistent with the existing light direction of the photo.");
            Notes(parts, sel, "FINAL INSTRUCTIONS FROM THE AUTHOR — these are deliberate creative choices and MUST be applied to the result (they refine the rendering, but never move, add or remove structural elements): ");
            return string.Join(" ", parts);
        }

        static string People(IDictionary<string, string> sel, ISet<string> multi)
        {
            var parts = new List<string> { "This is a finished architectural render or photograph of an empty space. Populate it with realistic people, keeping everything else identical." };
            var scene = F(PeopleScenes, sel, "scene", "auto");
            if (scene != "") parts.Add("Treat the space as " + scene + ".");
            parts.Add("Number of people: " + F(PeopleDensity, sel, "density", "moderate") + ".");
            var ages = PeopleAges.Where(a => multi.Contains("age:" + a.Key)).Select(a => a.Fragment).ToList();
            parts.Add(ages.Count > 0 ? "Age range — include " + string.Join(", ", ages) + ". Show only these age groups." : "Age range: a natural mix of ages appropriate to this kind of space.");
            parts.Add("Grouping: " + F(PeopleGrouping, sel, "grouping", "auto") + ".");
            var act = F(PeopleActivities, sel, "activity", "auto");
            parts.Add(act != "" ? "The people are " + act + "." : "The people are doing whatever naturally suits this kind of space.");
            var cl = F(PeopleClothing, sel, "clothing", "auto");
            if (cl != "") parts.Add("Clothing: " + cl + ".");
            var reg = F(PeopleRegions, sel, "region", "auto");
            parts.Add(reg != "" ? "The building is in " + reg + ": the people, their clothing and their appearance should plausibly reflect the local population of that region."
                                : "The people should plausibly belong to the location suggested by the image itself.");
            parts.Add("Show a natural, realistic variety of people — different heights, builds, ages and appearances, as in a real candid photograph of this kind of place.");
            if (sel.ContainsKey("accessibility"))
                parts.Add("Inclusivity: include at least one person using a mobility aid (a wheelchair or a walking frame) and, where the space suits it, a pushchair. Depict them naturally taking part in the life of the space, never isolated or staged as the subject of the image, and make sure their equipment is drawn correctly.");
            if (sel.TryGetValue("faces", out var f) && f == "visible")
                parts.Add("Faces may be visible and in focus, with natural relaxed expressions. All people must be entirely fictional and must not resemble any real, identifiable person.");
            else
                parts.Add("Keep the people discreet, as architectural staffage: seen from behind, in three-quarter view or in gentle movement, with faces mostly turned away, small in the frame or softly out of focus. The architecture, not the people, is the subject of the image. All people must be entirely fictional.");
            parts.Add("CRITICAL CONSTRAINTS — the existing image is untouchable: keep the architecture, walls, floors, ceilings, windows, doors, furniture, decor, materials, the view outside the windows, the lighting, the camera position, the perspective, the framing and the lens character EXACTLY as in the original. Do not restyle, recolour, relight, crop or redraw anything. Do not add, remove or move any object. The ONLY change is the addition of people.");
            parts.Add(PeopleAnatomy);
            parts.Add(PeopleIntegration);
            parts.Add("The result must be indistinguishable from a professional architectural photograph of this space with real people in it.");
            Notes(parts, sel, "FINAL INSTRUCTIONS FROM THE AUTHOR — these are deliberate creative choices and MUST be applied to the result: ");
            return string.Join(" ", parts);
        }

        static string Enhance(IDictionary<string, string> sel, ISet<string> multi)
        {
            var parts = new List<string> { "Ultra-premium professional image enhancement of the attached image." };
            var subject = F(EnhanceSubjects, sel, "subject", "auto");
            if (subject != "") parts.Add("The image is " + subject + ".");
            parts.Add("Regenerate it at the highest possible level of genuine detail, clarity and micro-texture, as if the same scene had been captured with professional equipment, a sharper lens and a much larger sensor.");
            parts.Add(F(EnhanceStrength, sel, "strength", "standard"));
            var focus = EnhanceFocus.Where(x => multi.Contains("focus:" + x.Key)).Select(x => x.Fragment).ToList();
            parts.Add(focus.Count > 0 ? "Pay particular attention to recovering: " + string.Join("; ", focus) + "."
                                      : "Recover detail everywhere it belongs: skin and hair, vegetation, fabrics, stone and metal surfaces, reflections, and distant background elements.");
            parts.Add("Also clean up compression artefacts, sensor noise, chromatic aberration, banding and softness — without erasing genuine texture and without smoothing surfaces flat.");
            parts.Add(EnhancePreservation);
            parts.Add(EnhanceForbidden);
            parts.Add("The result must look like the original photograph reshot with far better equipment: unmistakably the same image, dramatically more detailed.");
            Notes(parts, sel, "FINAL INSTRUCTIONS FROM THE AUTHOR — these are deliberate creative choices and MUST be applied to the result: ");
            return string.Join(" ", parts);
        }

        static string Camera(IDictionary<string, string> sel)
        {
            var a = Find(CameraAngles, sel.TryGetValue("angle", out var k) ? k : "three_quarter");
            var parts = new List<string>
            {
                "Re-render the scene shown in the uploaded image from a different camera position.",
                "THE SUBJECT MUST NOT CHANGE: it is the same building, the same interior, the same objects. Keep identical architecture, volumes, proportions, number of floors, window layout and rhythm, materials, colours, finishes, vegetation and surroundings. Keep the same time of day, the same weather and the same quality of light. Only the position of the camera changes.",
                a.Fragment,
            };
            if (a.Tier >= 2)
                parts.Add("Where the new viewpoint reveals parts of the scene not visible in the original image, deduce them from what IS visible — continue the same materials, the same floor lines, the same window spacing and the same detailing. Never introduce a different architectural style.");
            parts.Add("Photorealistic architectural photography, consistent perspective, correct vertical lines, professional quality.");
            Notes(parts, sel, "FINAL INSTRUCTIONS FROM THE AUTHOR — apply them to the framing and the rendering, never to the subject itself, which must stay identical: ");
            return string.Join(" ", parts);
        }

        static string Replace(IDictionary<string, string> sel)
        {
            var action = sel.TryGetValue("action", out var ac) ? ac : "remove";
            var desc = sel.TryGetValue("description", out var d) ? d.Trim() : "";
            var context = sel.TryGetValue("context", out var c) ? c.Trim() : "";
            var parts = new List<string> { "Edit ONLY the area marked by the mask in the first image. Everything outside the masked area must stay exactly as it is: same furniture, same architecture, same materials, same framing, same lighting." };
            if (action == "remove")
                parts.Add("Remove completely whatever occupies the masked area, and rebuild what would realistically be behind and beneath it: continue the floor, the wall, the ground or the surface that surrounds the area, matching its material, its pattern, its perspective lines and its colour exactly. Continue any shadow, reflection or skirting that passes through the area. Leave no trace of the removed object: no ghost, no leftover shadow, no blurred patch.");
            else if (action == "image")
            {
                parts.Add("Replace whatever occupies the masked area with the object shown in the SECOND image provided. Keep that object's design, shape, colour, material and proportions faithful to the reference.");
                parts.Add("Treat the second image as a reference of a REAL THREE-DIMENSIONAL object, not as a flat cut-out to paste. Place it in the scene at whatever orientation the position requires — against a wall, in a corner, angled to the room — with correct foreshortening for this camera, even when that means showing the object from a different angle than the reference photograph.");
                parts.Add("Where the required viewpoint exposes surfaces the reference photograph does not show — a side, the back, the top, the far end — reconstruct them yourself, plausibly and consistently with the visible design: same materials and colours, same construction logic, same proportions and thickness, symmetry where the object is clearly symmetrical. If the reference already shows the object from an angle that suits its position in the scene, keep that view as it is.");
                parts.Add("Reconstructing hidden surfaces does NOT mean redesigning the object: it must remain recognisably the same model, with the same silhouette, the same colour scheme, the same materials, the same number and arrangement of its parts.");
                parts.Add("Integrate it as if it had been photographed in this scene: match the perspective and the eye level of the room, sit it correctly on the floor or surface with a believable contact shadow, scale it plausibly against the surrounding furniture and against the architecture (door and window heights, skirting, ceiling), and relight it with the same light direction, colour temperature and softness as the rest of the image.");
                if (desc != "") parts.Add("Additional direction: " + desc);
            }
            else
            {
                parts.Add("Replace whatever occupies the masked area with: " + (desc != "" ? desc : "a suitable object of the same kind") + ".");
                parts.Add("Integrate it as if it had been photographed in this scene: correct perspective and eye level, believable contact shadow on the floor or surface, plausible scale against the surrounding furniture, and the same light direction, colour temperature and softness as the rest of the image.");
            }
            if (context != "") parts.Add("What is in that area right now: " + context);
            if (sel.TryGetValue("blend", out var b) && b == "reworked")
                parts.Add("CRITICAL: reproduce everything outside the masked area as faithfully as you possibly can. Same room, same furniture in the same positions, same wall and floor materials, same tile pattern and alignment, same window, same objects on every surface, same camera position and framing, same lighting and shadows, same colours. Treat the rest of the picture as something to copy, not to reinterpret: the only part you are free to change is inside the masked area.");
            else
                parts.Add("STRICT SPATIAL ALIGNMENT: only part of this output will be blended back into the original image, so the output must be perfectly aligned with the input — identical framing, no cropping, no zooming, no shifting, every element at exactly the same position and scale as in the input image.");
            parts.Add("Photorealistic, seamless, no visible edit boundary.");
            Notes(parts, sel, "FINAL INSTRUCTIONS FROM THE AUTHOR — they apply ONLY to what goes inside the masked area and to how it is integrated; everything outside the mask stays untouched regardless: ");
            return string.Join(" ", parts);
        }
    }
}
