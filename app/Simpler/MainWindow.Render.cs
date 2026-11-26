using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace Simpler
{
    /// <summary>"Rendering" panel in the right sidebar: real-time view options and the full path tracing configuration.</summary>
    public sealed partial class MainWindow
    {
        string _rightPanel = "";                 // "" = object properties, "render", "camera"
        bool _renderPanel => _rightPanel == "render";
        Button _renderPanelButton = null!, _cameraPanelButton = null!, _ambiencePanelButton = null!, _materialPanelButton = null!;
        Button? _scatterPanelButton, _ecoPanelButton;
        JsonObject _renderSettings = new JsonObject();

        async Task ToggleRenderPanel()
        {
            await ShowRightPanel(_rightPanel == "render" ? "" : "render");
        }

        async Task ShowRightPanel(string which)
        {
            _rightPanel = which;
            if (_puddleBrush && !BrushPanel()) { _puddleBrush = false; SendPuddleBrush(); }
            if (which != "paint" && Painting) { _tool = "move"; Theme.SetSegment(_toolButtons, 0); UpdateGizmo(); SendPaint(); }
            if (_scatterPanelButton != null) Theme.Style(_scatterPanelButton, which == "paint" ? Theme.Kind.Segment : Theme.Kind.Ghost);
            if (_ecoPanelButton != null) Theme.Style(_ecoPanelButton, which == "ecosystem" ? Theme.Kind.Segment : Theme.Kind.Ghost);
            Theme.Style(_renderPanelButton, which == "render" ? Theme.Kind.Segment : Theme.Kind.Ghost);
            Theme.Style(_cameraPanelButton, which == "camera" ? Theme.Kind.Segment : Theme.Kind.Ghost);
            Theme.Style(_ambiencePanelButton, which == "ambience" ? Theme.Kind.Segment : Theme.Kind.Ghost);
            if (_landscapePanelButton != null) Theme.Style(_landscapePanelButton, which == "landscape" ? Theme.Kind.Segment : Theme.Kind.Ghost);
            Theme.Style(_materialPanelButton, which is "material" or "materials" ? Theme.Kind.Segment : Theme.Kind.Ghost);
            Theme.Style(_resourcesPanelButton, which == "resources" ? Theme.Kind.Segment : Theme.Kind.Ghost);
            FitHeader();                // (Style gives back the wide padding: icon-only buttons narrow again)
            if (which != "resources") _resourcesTimer?.Stop();
            if (which == "render" || which == "camera") await LoadRenderSettings();
            if (which == "ambience") { await LoadAmbience(); await LoadSkyRefs(); }
            if (which == "landscape") { await LoadAmbience(); await LoadTerrain(); }      // (the sea comes with the Ambiente: ocean.py)
            if (which == "ecosystem") await LoadEcoInfo();
            if (which == "video") await LoadVideoFrames();
            RenderProps(true);          // (15/11: the panel the user asked for is always shown - never held back by a slider «in use»)
        }

        int _rsSeq;          // (Luca: «i cursori tornano al valore precedente») changes sent: an older reading does not overwrite their answer

        /// <summary>Every change of the render settings goes through here: its answer is the new state only if no later change was
        /// sent, and a reading asked before one of them (LoadRenderSettings) never overwrites it.</summary>
        async Task<JsonObject?> RsPost(object body)
        {
            var mine = ++_rsSeq;
            // (as AmbWrite) the settings show at once what was sent: an answer thrown away for a newer change cannot bring a value back
            if (System.Text.Json.JsonSerializer.SerializeToNode(body) is JsonObject sent)
                foreach (var kv in sent) _renderSettings[kv.Key] = kv.Value?.DeepClone();
            JsonObject? r = null;
            await Run(async api => { r = await api.Post("settings", body); });
            if (r != null && mine == _rsSeq) _renderSettings = r;
            return r;
        }

        async Task LoadRenderSettings()
        {
            var rs = _rsSeq;
            await Run(async api => { var r = await api.Get("settings"); if (rs == _rsSeq) _renderSettings = r; });
            _caustics = (bool?)_renderSettings["caustics"] ?? _caustics;
            var q = (string?)_renderSettings["quality"] ?? "alta";
            _quality = q;
            UpdateQualityDrop();
            PushToneToViewer();
            PushFxToViewer();
        }

        /// <summary>Shadows / highlights to the 3D view (the real-time view applies them in its shader; the path tracing
        /// frame comes already toned from the engine).</summary>
        void PushToneToViewer()
        {
            var cfg = _renderSettings["config"] as JsonObject;
            double s = Math.Clamp((double?)cfg?["toneShadows"] ?? 0, 0, 1), h = Math.Clamp((double?)cfg?["toneHighlights"] ?? 0, 0, 1);
            bool vivid = (string?)cfg?["colorRender"] == "vivid";
            if (_webReady) SendToWeb(new { type = "tone", s, h, vivid });
            double fill = Math.Clamp((double?)cfg?["fill"] ?? 0, 0, 1), autoEv = (double?)_ambience?["ev"] ?? 0;
            if (_webReady) SendToWeb(new { type = "fill", fraction = fill, ev = autoEv });
        }

        async Task SetConfig(string key, JsonNode value)
        {
            await RsPost(new JsonObject { ["config"] = new JsonObject { [key] = value } });
            if (key is "exposure" or "meterExposure") { await LoadAmbience(); PushAmbienceToViewer(); }       // the real-time view follows the exposure
            if (key is "toneShadows" or "toneHighlights" or "fill" or "colorRender") PushToneToViewer();
            if (key.StartsWith("fx")) PushFxToViewer();
            var q = (string?)_renderSettings["quality"] ?? "";
            _quality = q;
            UpdateQualityDrop();
            RenderProps();
        }

        void RenderRenderPanel()
        {
            var cfg = _renderSettings["config"] as JsonObject ?? new JsonObject();
            double C(string k, double def) => (double?)cfg[k] ?? def;
            bool B(string k, bool def = true) => (bool?)cfg[k] ?? def;
            var defs = _renderSettings["defaults"] as JsonObject ?? new JsonObject();
            // a value of the "Avanzate" boxes not at the default of the quality preset (or at the one given)
            bool Changed(string k, JsonNode? expected = null)
            {
                var cur = cfg[k]; var def = expected ?? defs[k];
                if (cur == null || def == null) return false;
                if (cur is JsonValue cv && def is JsonValue dv && cv.TryGetValue<double>(out var a) && dv.TryGetValue<double>(out var b)) return Diff(a, b);
                return cur.ToJsonString() != def.ToJsonString();
            }
            Func<Task> Reset(params string[] keys) => async () =>
            {
                var c = new JsonObject();
                foreach (var k in keys) if (defs[k] != null) c[k] = defs[k]!.DeepClone();
                await RsPost(new JsonObject { ["config"] = c });
                await LoadRenderSettings();
                RenderProps();
            };

            // ---- header
            var head = new StackPanel();
            var top = new DockPanel();
            var close = Theme.Button(L.T("Chiudi"), Theme.Kind.Ghost, L.T("Torna alle proprietà dell'oggetto"));
            close.Click += async (_, __) => await ShowRightPanel("");
            DockPanel.SetDock(close, Dock.Right);
            top.Children.Add(close);
            top.Children.Add(Theme.Caption(L.T("Rendering")));
            head.Children.Add(top);
            var dev = Theme.Label(L.F("Motore: Cycles path tracing · {0}", DeviceLabel(_renderSettings["device"]?.ToString())), 12, Theme.TextFaint);
            dev.Margin = new Thickness(0, 6, 0, 0);
            head.Children.Add(dev);
            _props.Children.Add(Theme.Card(head, 16));

            // ---- real-time view
            var rt = new StackPanel();
            rt.Children.Add(SectionTitle(L.T("Vista in tempo reale")));
            rt.Children.Add(Hint(L.T("Serve per muoversi e comporre la scena: è un'anteprima veloce, non il risultato finale.")));
            var shadowIds = new[] { "off", "media", "alta", "ultra" };
            var shadows = Theme.Segmented(out var shadowButtons, (L.T("No"), L.T("Ombre spente: massima fluidità")), (L.T("Media"), L.T("Mappa ombre 1024")), (L.T("Alta"), L.T("Mappa ombre 2048")), (L.T("Ultra"), L.T("Mappa ombre 4096: più nitide, più pesanti")));
            var curShadow = Math.Max(0, Array.IndexOf(shadowIds, Settings.Load().ViewerShadows));
            Theme.SetSegment(shadowButtons, curShadow);
            for (int i = 0; i < shadowButtons.Count; i++)
            {
                var id = shadowIds[i];
                var idx = i;
                shadowButtons[i].Click += (_, __) =>
                {
                    Theme.SetSegment(shadowButtons, idx);
                    var s = Settings.Load(); s.ViewerShadows = id; s.Save();
                    SendToWeb(new { type = "shadows", level = id });
                    UpdateQualityDrop();
                };
            }
            rt.Children.Add(Row(L.T("Ombre"), shadows));
            // texture size in the real-time view: smaller = faster export, less memory (huge models)
            var rtTexIds = new[] { 0, 1024, 2048, -1 };
            var rtTex = Theme.Segmented(out var rtTexButtons,
                (L.T("Auto"), L.T("2K, oppure 1K quando il modello ha moltissime texture")),
                ("1K", L.T("Texture a 1024 pixel: vista leggera anche con modelli enormi")),
                ("2K", L.T("Texture a 2048 pixel")),
                (L.T("Piene"), L.T("Texture originali: più lento da preparare e più memoria")));
            Theme.SetSegment(rtTexButtons, Array.IndexOf(rtTexIds, (int)C("realtimeTextures", 0)));
            for (int i = 0; i < rtTexButtons.Count; i++)
            {
                var v = rtTexIds[i];
                rtTexButtons[i].Click += async (_, __) =>
                {
                    await RsPost(new JsonObject { ["config"] = new JsonObject { ["realtimeTextures"] = v } });
                    await LoadRenderSettings();
                    RenderProps();
                    ForcePreviewReload("texture size of the view changed");
                    await RefreshScene();
                };
            }
            rt.Children.Add(Row(L.T("Texture"), rtTex));
            _props.Children.Add(Theme.Card(rt, 16));

            // ---- path tracing quality
            var q = new StackPanel();
            q.Children.Add(SectionTitle(L.T("Path tracing · qualità")));
            var presetIds = new[] { "bozza", "alta", "finale" };
            var presets = Theme.Segmented(out var presetButtons, (L.T("Bozza"), L.T("Veloce, per controllare luci e inquadratura")), (L.T("Alta"), L.T("Ottima per il web")), (L.T("Finale"), L.T("Massima qualità")));
            Theme.SetSegment(presetButtons, Array.IndexOf(presetIds, _quality));
            for (int i = 0; i < presetButtons.Count; i++)
            {
                var id = presetIds[i];
                presetButtons[i].Click += async (_, __) => { await SetQuality(id); await LoadRenderSettings(); RenderProps(); };
            }
            q.Children.Add(Row(L.T("Preset"), presets));
            if (_quality == "personalizzata")
                q.Children.Add(Hint(L.T("Impostazioni personalizzate: scegli un preset per ripartire da valori standard.")));
            q.Children.Add(Switch(L.T("Riduzione rumore (denoiser)"), "denoise", B("denoise"), L.T("Denoiser OptiX/OpenImageDenoise: immagine pulita con meno campioni")));
            var qa = Advanced(q, "quality");
            qa.Body.Children.Add(Slider(L.T("Campioni render"), "samples", C("samples", 512), 16, 16384, true, "0", null,
                L.T("Quanti raggi per pixel nel render finale: più campioni = meno rumore, più tempo")));
            qa.Body.Children.Add(Slider(L.T("Campioni anteprima"), "viewportSamples", C("viewportSamples", 256), 16, 4096, true, "0", null,
                L.T("Campioni dell'anteprima path tracing nella vista")));
            qa.Body.Children.Add(Slider(L.T("Soglia rumore"), "noiseThreshold", C("noiseThreshold", 0.01), 0.001, 0.1, true, "0.###", null,
                L.T("Campionamento adattivo: smette di calcolare i pixel già puliti. Più bassa = più pulito e più lento")));
            qa.Done(Changed("samples") || Changed("viewportSamples") || Changed("noiseThreshold"), Reset("samples", "viewportSamples", "noiseThreshold"));
            // huge scenes: smaller textures on the GPU for the path-tracing view only (the final render keeps them full)
            var texIds = new[] { -1, 0, 4096, 2048, 1024 };
            var texSeg = Theme.Segmented(out var texButtons,
                (L.T("Auto"), L.T("Copie a 2048 pixel delle texture grandi, preparate una volta e riusate; 1024 se sono moltissime")),
                (L.T("Piene"), L.T("Texture alla risoluzione originale: lento e molta memoria GPU con i modelli grandi")),
                ("4K", L.T("Texture ridotte a 4096 pixel nell'anteprima")),
                ("2K", L.T("Texture ridotte a 2048 pixel: scene grandi più leggere sulla GPU")),
                ("1K", L.T("Texture ridotte a 1024 pixel: per scene enormi")));
            Theme.SetSegment(texButtons, Array.IndexOf(texIds, (int)C("textureLimit", -1)));
            for (int ti = 0; ti < texButtons.Count; ti++)
            {
                var lim = texIds[ti];
                texButtons[ti].Click += async (_, __) =>
                {
                    await RsPost(new JsonObject { ["config"] = new JsonObject { ["textureLimit"] = lim } });
                    await LoadRenderSettings();
                    RenderProps();
                };
            }
            q.Children.Add(Row(L.T("Texture anteprima"), texSeg));
            q.Children.Add(Hint(L.T("Solo per la vista path tracing: le texture grandi vengono ridotte una volta sola e tenute in una cache, così l'anteprima parte in fretta e usa poca memoria GPU. Il render finale usa sempre le texture originali.")));
            _props.Children.Add(Theme.Card(q, 16));

            // ---- global illumination
            var gi = new StackPanel();
            gi.Children.Add(SectionTitle(L.T("Illuminazione globale e rimbalzi")));
            gi.Children.Add(Hint(L.T("Quante volte la luce può rimbalzare. Gli interni chiedono più rimbalzi diffusi, vetri e gemme più rifrazioni.")));
            var ga = Advanced(gi, "gi");
            ga.Body.Children.Add(Slider(L.T("Totali"), "bounces", C("bounces", 16), 0, 64, false, "0", null, L.T("Limite massimo di rimbalzi per raggio")));
            ga.Body.Children.Add(Slider(L.T("Diffusi (GI)"), "diffuse", C("diffuse", 4), 0, 32, false, "0", null, L.T("Luce che rimbalza tra pareti e superfici opache: illuminazione indiretta")));
            ga.Body.Children.Add(Slider(L.T("Riflessi"), "glossy", C("glossy", 8), 0, 64, false, "0", null, L.T("Riflessi di riflessi: metalli e specchi")));
            ga.Body.Children.Add(Slider(L.T("Rifrazioni"), "transmission", C("transmission", 16), 0, 64, false, "0", null, L.T("Passaggi attraverso vetro, acqua, gemme")));
            ga.Body.Children.Add(Slider(L.T("Trasparenze"), "transparent", C("transparent", 16), 0, 128, false, "0", null, L.T("Superfici con trasparenza alfa sovrapposte (foglie, tessuti)")));
            ga.Body.Children.Add(Slider(L.T("Volumi"), "volume", C("volume", 0), 0, 16, false, "0", null, L.T("Nebbia e fumo")));
            if (C("bounces", 16) < C("transmission", 16))
                ga.Body.Children.Add(Hint(L.T("Totali sotto le Rifrazioni: con vetro o acqua nella scena il path tracing usa comunque almeno le Rifrazioni, altrimenti vetro e acqua diventerebbero neri.")));
            if (C("diffuse", 4) == 0)
                ga.Body.Children.Add(Hint(L.T("Diffusi a 0: niente luce indiretta, le zone in ombra (e il fondale in ombra sotto l'acqua) restano nere.")));
            ga.Body.Children.Add(Switch(L.T("GI veloce (approssimata)"), "fastGI", B("fastGI", false), L.T("Sostituisce i rimbalzi lontani con ambient occlusion: più veloce, meno fedele")));
            if (B("fastGI", false))
                ga.Body.Children.Add(Slider(L.T("Rimbalzi AO"), "aoBounces", C("aoBounces", 1), 0, 8, false, "0", null, L.T("Rimbalzi calcolati davvero prima dell'approssimazione")));
            ga.Done(new[] { "bounces", "diffuse", "glossy", "transmission", "transparent", "volume", "fastGI", "aoBounces" }.Any(k => Changed(k)),
                    Reset("bounces", "diffuse", "glossy", "transmission", "transparent", "volume", "fastGI", "aoBounces"));
            _props.Children.Add(Theme.Card(gi, 16));

            // ---- caustics, reflections, fireflies
            var cr = new StackPanel();
            cr.Children.Add(SectionTitle(L.T("Caustiche, riflessi e rifrazioni")));
            // one clear switch: off / on. (19/11, Luca: «facciamo la 1 perché così confonde e basta») «Normali» is gone: it
            // left only the caustics Cycles finds by itself, invisible with small lights (spot, point, sun) - the same
            // picture as «Spente». «Attive» is the old «Nitide». mode keeps 0 / 2 for the code below.
            bool refl = B("causticsReflective"), refr = B("causticsRefractive");
            int mode = _caustics ? 2 : 0;
            var cmodes = Theme.Segmented(out var cButtons,
                (L.T("Spente"), L.T("Nessuna caustica: render più veloce e pulito")),
                (L.T("Attive"), L.T("Vetri, gemme, metalli lucidi e acqua concentrano la luce sulle superfici intorno")));
            Theme.SetSegment(cButtons, mode == 2 ? 1 : 0);
            for (int ci = 0; ci < cButtons.Count; ci++)
            {
                var m = ci == 1 ? 2 : 0;
                cButtons[ci].Click += async (_, __) =>
                {
                    await RsPost(new JsonObject
                    {
                        // path-traced caustics are exactly what "filtro riflessi" and "limite luce indiretta" remove:
                        // with caustics on they are released, with caustics off they go back to clean defaults
                        ["config"] = new JsonObject
                        {
                            ["causticsReflective"] = m > 0, ["causticsRefractive"] = m > 0,
                            ["blurGlossy"] = m > 0 ? 0.0 : 0.5, ["clampIndirect"] = m > 0 ? 0.0 : 10.0,
                        },
                    });
                    await LoadRenderSettings();
                    await SetCaustics(m == 2, m);
                    RenderProps();
                };
            }
            cr.Children.Add(Row(L.T("Caustiche"), cmodes));
            // (19/11, Luca: «continuo a non capire a cosa servono») what is on, said plainly and in sight: the two
            // kinds of caustics and the light of the water; the three sliders that only clean the path tracing apart
            if (mode > 0)
            {
                cr.Children.Add(Switch(L.T("Caustiche riflesse"), "causticsReflective", refl, L.T("La luce riflessa dai metalli lucidi e dall'esterno dei vetri. Spento: nessuna caustica riflessa, neanche quelle nitide")));
                cr.Children.Add(Switch(L.T("Caustiche rifratte"), "causticsRefractive", refr, L.T("La luce che attraversa vetro, gemme e acqua. Spento: la luce li attraversa dritta, senza disegni, anche con le caustiche nitide")));
            }
            // light reflected by the waves of water onto walls and the underside of bridges (engine refcaustics.py)
            bool rcOn = B("causticsReflected", false);
            cr.Children.Add(Switch(L.T("Luce riflessa dall'acqua"), "causticsReflected", rcOn,
                L.T("Il riflesso di sole e luci sulle onde disegna il reticolo di luce sui muri vicini, sotto i ponti e sul fondo; con le caustiche Nitide anche la luce delle lampade sott'acqua che esce sulle pareti e sul soffitto. Solo acqua con onde vere, solo path tracing. Il reticolo si forma con onde ampie (da 50 cm in su) e superfici chiare")));
            if (rcOn)
            {
                var rcHint = (TextBlock)Hint(RefCausticsText(_renderSettings["refCaustics"]));
                cr.Children.Add(rcHint);
                _ = WatchRefCaustics(rcHint);
            }
            if (mode == 2)
                cr.Children.Add(Hint(L.T("Attive: la luce di bicchieri, bottiglie e metalli lucidi è seguita partendo dalla luce stessa; quella di gemme, vetri pieni e acqua è calcolata dal path tracing. Ogni modello può esserne escluso: Proprietà ▸ Caustiche ▸ Genera caustiche.")));
            var ca = Advanced(cr, "caustics");
            ca.Body.Children.Add(Theme.Label(L.T("Pulizia del rumore"), 12, Theme.TextSoft, FontWeights.SemiBold));
            ca.Body.Children.Add(Hint(L.T("Questi tre cursori puliscono l'immagine del path tracing e non toccano le caustiche nitide di vetro, metallo e acqua. Con le caustiche accese il filtro riflessi e il limite della luce indiretta partono da 0: l'immagine può richiedere più campioni per essere pulita.")));
            ca.Body.Children.Add(Slider(L.T("Filtro riflessi"), "blurGlossy", C("blurGlossy", 0.5), 0, 2, false, "0.##", null,
                L.T("Ammorbidisce leggermente i riflessi indiretti per ridurre il rumore (0 = esatto)")));
            ca.Body.Children.Add(Slider(L.T("Limite luce diretta"), "clampDirect", C("clampDirect", 0), 0, 100, false, "0.#", null,
                L.T("0 = nessun limite. Taglia i picchi della luce diretta")));
            ca.Body.Children.Add(Slider(L.T("Limite luce indiretta"), "clampIndirect", C("clampIndirect", 10), 0, 100, false, "0.#", null,
                L.T("Elimina i puntini luminosi (fireflies). 0 = nessun limite, valori bassi = immagine più pulita ma meno brillante")));
            {
                JsonNode? On(bool v) => JsonValue.Create(v);
                bool ch = (mode > 0 && (!refl || !refr)) || B("causticsReflected", false) || Changed("clampDirect")
                          || (mode > 0 ? Changed("blurGlossy", JsonValue.Create(0.0)) || Changed("clampIndirect", JsonValue.Create(0.0))
                                       : Changed("blurGlossy") || Changed("clampIndirect"));
                ca.Done(ch, async () =>
                {
                    var c = new JsonObject
                    {
                        ["causticsReflective"] = On(mode > 0), ["causticsRefractive"] = On(mode > 0), ["causticsReflected"] = On(false),
                        ["clampDirect"] = defs["clampDirect"]?.DeepClone() ?? 0.0,
                        ["blurGlossy"] = mode > 0 ? 0.0 : defs["blurGlossy"]?.DeepClone() ?? 0.5,
                        ["clampIndirect"] = mode > 0 ? 0.0 : defs["clampIndirect"]?.DeepClone() ?? 10.0,
                    };
                    await RsPost(new JsonObject { ["config"] = c });
                    await LoadRenderSettings();
                    RenderProps();
                });
            }
            _props.Children.Add(Theme.Card(cr, 16));

            // ---- colour
            var col = new StackPanel();
            col.Children.Add(SectionTitle(L.T("Colore ed esposizione")));
            col.Children.Add(Slider(L.T("Esposizione"), "exposure", C("exposure", 0), -5, 5, false, "0.##", "EV", L.T("Più luminoso / più scuro, come il tempo di scatto")));
            col.Children.Add(Switch(L.T("Esposizione sull'inquadratura"), "meterExposure", (bool?)cfg["meterExposure"] ?? true,
                L.T("Come l'esposimetro di una macchina fotografica: misura la luce di ciò che la camera inquadra e apre l'esposizione nelle scene in ombra (bosco, sottoportici, interni). Non scurisce mai, al massimo +6 stop, di notte non interviene. La misura viene dalla vista path tracing e dal render finale; la vista in tempo reale usa l'ultima misura. L'Esposizione qui sopra si somma")));
            col.Children.Add(PctSlider(L.T("Luce di riempimento"), "fill", C("fill", 0),
                L.T("Luce vera aggiunta alla scena, come il pannello riflettente del fotografo: arriva morbida dalla camera, un po' dall'alto, e illumina ciò che inquadri (controluce, sottobosco, interni). Non fa riflessi sulle superfici lucide e non si vede. 100% = un grigio medio ben esposto; 20–40% per un riempimento naturale")));
            col.Children.Add(PctSlider(L.T("Schiarisci ombre"), "toneShadows", C("toneShadows", 0),
                L.T("Come il cursore Ombre di un programma di fotoritocco: alza solo i toni scuri (controluce, sottobosco, interni), senza toccare i medi e le luci. Subito, senza ricalcolare; vale anche per il render finale")));
            col.Children.Add(PctSlider(L.T("Recupera luci"), "toneHighlights", C("toneHighlights", 0),
                L.T("Abbassa solo i toni chiarissimi (cielo, finestre, sole) senza scurire il resto. Subito, senza ricalcolare; vale anche per il render finale")));
            bool vividOn = (string?)cfg["colorRender"] == "vivid";
            col.Children.Add(Theme.Label(L.T("Resa colore"), 12, Theme.TextMuted));
            var crSeg = Theme.Segmented(out var crButtons,
                (L.T("Naturale"), L.T("AgX: colori morbidi, le luci fortissime sfumano verso il bianco come in una pellicola")),
                (L.T("Vivida"), L.T("Khronos PBR Neutral: i colori molto luminosi restano saturi - tramonti, albe, luci colorate. Senza i toni di AgX")));
            crSeg.HorizontalAlignment = HorizontalAlignment.Left;
            crSeg.Margin = new Thickness(0, 2, 0, 10);
            Theme.SetSegment(crButtons, vividOn ? 1 : 0);
            crButtons[0].Click += async (_, __) => await SetConfig("colorRender", "natural");
            crButtons[1].Click += async (_, __) => await SetConfig("colorRender", "vivid");
            col.Children.Add(crSeg);
            var looks = (_renderSettings["looks"] as JsonArray)?.Select(n => (string?)n ?? "").ToList() ?? new List<string>();
            var cur = (string?)cfg["look"] ?? "";
            var wrap = new WrapPanel { Margin = new Thickness(0, 2, 0, 0) };
            foreach (var look in looks)
            {
                var label = look == "None" ? L.T("Nessuno") : look.Replace("AgX - ", "")
                    .Replace("Very Low Contrast", L.T("Contrasto minimo")).Replace("Medium Low Contrast", L.T("Contrasto medio-basso"))
                    .Replace("Low Contrast", L.T("Contrasto basso")).Replace("Base Contrast", L.T("Contrasto base"))
                    .Replace("Medium High Contrast", L.T("Contrasto medio-alto")).Replace("Very High Contrast", L.T("Contrasto massimo"))
                    .Replace("High Contrast", L.T("Contrasto alto")).Replace("Punchy", L.T("Vivace"));
                var b = Theme.Button(label, look == cur ? Theme.Kind.Segment : Theme.Kind.Ghost);
                b.MinHeight = 28;
                b.FontSize = 12;
                b.Margin = new Thickness(0, 0, 4, 4);
                var l = look;
                b.Click += async (_, __) => await SetConfig("look", l);
                wrap.Children.Add(b);
            }
            // the colour of the camera (contrast... look) and one «Avanzate» with the lens effects and the AgX tone
            AddCameraFx(col, vividOn ? null : body =>
            {
                var tl = Theme.Label(L.T("Tono (AgX)"), 12, Theme.TextMuted);
                tl.Margin = new Thickness(0, 6, 0, 0);
                body.Children.Add(tl);
                body.Children.Add(wrap);
            }, !vividOn && Changed("look"), vividOn ? null : Reset("look"));
            _props.Children.Add(Theme.Card(col, 16));

            // ---------------------------------------------------------------- local helpers
            UIElement Slider(string label, string key, double value, double min, double max, bool log, string fmt, string? unit, string tip)
            {
                var s = new ValueSlider(label, value, min, max, log, fmt, unit, null, tip);
                bool integer = fmt == "0";
                s.Committed += async v => await SetConfig(key, integer ? JsonValue.Create((int)Math.Round(v)) : JsonValue.Create(v));
                return s;
            }
            UIElement PctSlider(string label, string key, double value, string tip)
            {
                var s = new ValueSlider(label, value * 100, 0, 100, false, "0", "%", null, tip);
                s.Committed += async v => await SetConfig(key, JsonValue.Create(Math.Round(v, 2) / 100.0));
                return s;
            }
            UIElement Switch(string label, string key, bool value, string tip)
            {
                var t = new Toggle(label, value, tip);
                t.Toggled += async v => await SetConfig(key, JsonValue.Create(v));
                return t;
            }
        }

        static UIElement Row(string label, UIElement control)
        {
            var g = new DockPanel { Margin = new Thickness(0, 0, 0, 12) };
            var l = Theme.Label(label, 12, Theme.TextMuted);
            l.Width = 96;
            l.VerticalAlignment = VerticalAlignment.Center;
            g.Children.Add(l);
            if (control is FrameworkElement fe) fe.HorizontalAlignment = HorizontalAlignment.Left;
            g.Children.Add(control);
            return g;
        }

        static string RefCausticsText(JsonNode? info)
        {
            var state = (string?)info?["state"] ?? "";
            if (state == "nothing") return L.T("Nessuna acqua con onde vere sotto il sole nella scena.");
            if (state == "error") return L.T("Non è stato possibile calcolarla su questa scena: il path tracing prosegue senza.") + " (" + ((string?)info?["error"] ?? "") + ")";
            if (state != "on") return L.T("Calcolata alla prossima immagine path tracing.");
            double sec = (double?)info?["seconds"] ?? 0;
            long rays = (long?)info?["rays"] ?? 0;
            int rec = (int?)info?["receivers"] ?? 0;
            return string.Format(L.T("Ultimo calcolo: {0} s, {1} raggi, {2} superfici illuminate. Si ricalcola solo quando cambiano sole, acqua o oggetti vicini."),
                sec.ToString("0.0#"), rays.ToString("N0"), rec);
        }

        // the time of the calculation appears in the panel as soon as the engine has done it (a few seconds)
        async Task WatchRefCaustics(TextBlock hint)
        {
            var before = (double?)_renderSettings["refCaustics"]?["when"] ?? 0;
            for (int i = 0; i < 30; i++)
            {
                await Task.Delay(1500);
                if (_api == null || (i > 0 && !hint.IsLoaded)) return;      // (panel closed or rebuilt)
                JsonNode? s = null;
                try { s = await _api.Get("settings"); } catch { return; }
                var info = s?["refCaustics"];
                hint.Text = RefCausticsText(info);
                if (((double?)info?["when"] ?? 0) != before || (string?)info?["state"] == "nothing") return;
            }
        }

        static UIElement Hint(string text)
        {
            var t = Theme.Label(text, 12, Theme.TextFaint);
            t.TextWrapping = TextWrapping.Wrap;
            t.Margin = new Thickness(0, 0, 0, 12);
            return t;
        }
    }
}
