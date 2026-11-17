using System;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;

namespace Simpler
{
    /// <summary>
    /// Paesaggio (header button, panel on the right): what is around the scene down to the horizon. For now the sea
    /// (engine: ocean.py, Blender's Ocean modifier): presets on top, then height, wind, crests, direction, foam,
    /// colour and level; the rest of the modifier in the Avanzate. Its state comes with the Ambiente
    /// (_ambience["ocean"]: no call of its own); every change is one undo step and goes to the real-time view.
    /// </summary>
    public sealed partial class MainWindow
    {
        Button? _landscapePanelButton;
        static readonly Color SeaColor = Color.FromRgb(0x3F, 0xA7, 0xD6);

        JsonObject Ocean() => _ambience["ocean"] as JsonObject ?? new JsonObject();

        async Task SetOcean(JsonObject change)
        {
            SendToWeb(new { type = "busyNow", what = L.T("Oceano") });
            using var busy = BeginBusy();
            JsonObject? r = null;
            await Run(async api => { r = await api.Post("landscape/ocean", change); });
            if (r == null) return;
            if (r["history"] is JsonObject h) { UpdateHistory(h); r.Remove("history"); }
            _ambience["ocean"] = r;
            if (_webReady) SendToWeb(new { type = "ocean", info = r.DeepClone() });
            if (_rightPanel == "landscape") RenderProps();
        }

        /// <summary>A preset of the sea as a small tile: its water and waves, the name below.</summary>
        static Border OceanTile(string id, string name, bool on, Func<Task> click)
        {
            var (top, bottom) = id switch
            {
                "calmo" => ("#9CCBE6", "#2F7FA8"),
                "brezza" => ("#7FB8DC", "#1F6E99"),
                "mosso" => ("#5E9CC8", "#16577E"),
                "burrasca" => ("#7D8C94", "#2B3A40"),
                "lunga" => ("#4B86B8", "#0E3A5C"),
                "tropicale" => ("#8FE3DA", "#1C9C9A"),
                "nordico" => ("#7E949C", "#1F343A"),
                "lago" => ("#9DB59A", "#3D5A44"),
                _ => ("#5E9CC8", "#16577E"),
            };
            var swatch = new Border
            {
                Height = 34, CornerRadius = new CornerRadius(6), Background = new LinearGradientBrush(Theme.C(top), Theme.C(bottom), 90),
                Child = Theme.Icon(id is "calmo" or "lago" ? WavesSoft : Waves, Theme.C("#FFFFFF"), 18, 1.7),
            };
            var label = new TextBlock
            {
                Text = name, FontSize = 11, Margin = new Thickness(0, 5, 0, 0), TextAlignment = TextAlignment.Center,
                TextTrimming = TextTrimming.CharacterEllipsis, Foreground = Theme.B(on ? Theme.Text : Theme.TextMuted),
                FontWeight = on ? FontWeights.SemiBold : FontWeights.Normal,
            };
            var sp = new StackPanel();
            sp.Children.Add(swatch);
            sp.Children.Add(label);
            var idle = Theme.B(on ? Theme.Accent : Theme.Line);
            var tile = new Border
            {
                Child = sp, Padding = new Thickness(4), Margin = new Thickness(0, 0, 6, 6), CornerRadius = new CornerRadius(9),
                BorderThickness = new Thickness(on ? 1.5 : 1), BorderBrush = idle, Cursor = Cursors.Hand,
                Background = Theme.B(on ? Theme.Selected : Theme.Inset), ToolTip = name,
            };
            tile.MouseEnter += (_, __) => { if (!on) tile.BorderBrush = Theme.B(Theme.LineStrong); };
            tile.MouseLeave += (_, __) => tile.BorderBrush = idle;
            tile.MouseLeftButtonUp += async (_, e) => { e.Handled = true; await click(); };
            return tile;
        }

        static readonly Geometry Waves = MakeGeometry("M2 8c2.5-2.5 4.5-2.5 7 0s4.5 2.5 7 0 4.5-2.5 6 -1 M2 13c2.5-2.5 4.5-2.5 7 0s4.5 2.5 7 0 4.5-2.5 6-1 M2 18c2.5-2.5 4.5-2.5 7 0s4.5 2.5 7 0 4.5-2.5 6-1");
        static readonly Geometry WavesSoft = MakeGeometry("M2 10c3-1.5 5-1.5 7 0s4 1.5 7 0 4-1.5 6 0 M2 15c3-1.5 5-1.5 7 0s4 1.5 7 0 4-1.5 6 0");
        static readonly Geometry Mountain = MakeGeometry("M2 20 9 8l4 6 3-4 6 10z M7.5 10.5l1.5 1.5 1.5-1.5");

        /// <summary>The colour of the water as a small dot: from the deep colour to the crests.</summary>
        static FrameworkElement WaterDot(JsonObject c)
        {
            Color Lin(JsonArray? a, double k)
            {
                byte Ch(int i)
                {
                    var v = Math.Clamp(((double?)a?[i] ?? 0) * k, 0, 1);
                    var s = v <= 0.0031308 ? v * 12.92 : 1.055 * Math.Pow(v, 1 / 2.4) - 0.055;
                    return (byte)Math.Round(Math.Clamp(s, 0, 1) * 255);
                }
                return Color.FromRgb(Ch(0), Ch(1), Ch(2));
            }
            var fill = new LinearGradientBrush(Lin(c["crest"] as JsonArray, 3), Lin(c["deep"] as JsonArray, 3), 90);
            return new System.Windows.Shapes.Ellipse { Width = 12, Height = 12, Fill = fill, Stroke = Theme.B(Theme.LineStrong), StrokeThickness = 1, VerticalAlignment = VerticalAlignment.Center };
        }

        void RenderLandscapePanel()
        {
            var oc = Ocean();
            var on = (bool?)oc["on"] ?? false;
            var st = oc["settings"] as JsonObject ?? new JsonObject();
            double D(string k, double d) => (double?)st[k] ?? d;
            string S(string k, string d) => (string?)st[k] ?? d;

            var head = new StackPanel();
            var top = new DockPanel();
            var close = Theme.Button(L.T("Chiudi"), Theme.Kind.Ghost, L.T("Torna alle proprietà dell'oggetto"));
            close.Click += async (_, __) => await ShowRightPanel("");
            DockPanel.SetDock(close, Dock.Right);
            top.Children.Add(close);
            top.Children.Add(Theme.Caption(L.T("Paesaggio")));
            head.Children.Add(top);
            head.Children.Add(HintSmall(L.T("Quello che circonda la scena fino all'orizzonte, uguale nella vista e nel path tracing.")));
            _props.Children.Add(Theme.Card(head, 16));
            RenderTerrainCard();                // (1.76.0) MainWindow.Terrain.cs
            RenderScreeCard();                  // (1.76.22) MainWindow.Scree.cs

            var card = new StackPanel();
            var title = SectionTitle(L.T("Oceano"));
            title.DataContext = (Waves, SeaColor);
            card.Children.Add(title);
            _props.Children.Add(Theme.Card(card, 16));
            if (!on)
            {
                card.Children.Add(HintSmall(L.T("Un mare vero fino all'orizzonte: onde simulate come quelle reali, con creste, schiuma e il cielo riflesso.")));
                var add = Theme.Button(Theme.IconText(Waves, L.T("Aggiungi il mare"), null, 14), Theme.Kind.Primary, L.T("Mette il mare intorno alla scena, con le onde «Mosso». Poi scegli il tipo di mare qui sotto"));
                add.MinHeight = 32; add.HorizontalAlignment = HorizontalAlignment.Left; add.Margin = new Thickness(0, 8, 0, 0);
                add.Click += async (_, __) => await SetOcean(new JsonObject { ["preset"] = "mosso" });
                card.Children.Add(add);
                return;
            }

            var presets = new UniformGrid { Columns = 4, Margin = new Thickness(0, 4, 0, 4) };
            var cur = S("preset", "");
            foreach (var p in (oc["presets"] as JsonArray ?? new JsonArray()).OfType<JsonObject>())
            {
                var id = (string?)p["id"] ?? "";
                presets.Children.Add(OceanTile(id, (string?)p["name"] ?? id, id == cur, async () => await SetOcean(new JsonObject { ["preset"] = id })));
            }
            card.Children.Add(presets);

            ValueSlider Sl(StackPanel to, Geometry icon, string label, string key, double v, double min, double max, bool log, string fmt, string unit, string tip, Func<double, double>? map = null)
            {
                var sl = new ValueSlider(label, v, min, max, log, fmt, unit, null, tip).WithIcon(icon, SeaColor);
                sl.Committed += async x => await SetOcean(new JsonObject { ["settings"] = new JsonObject { [key] = map != null ? map(x) : x } });
                to.Children.Add(sl);
                return sl;
            }
            Sl(card, Icons.Expand, L.T("Altezza onde"), "height", D("height", 1.2), 0, 8, false, "0.00", "m",
               L.T("L'altezza delle onde dalla gola alla cresta, come la dicono i bollettini del mare"));
            Sl(card, Icons.Wind, L.T("Vento"), "wind", D("wind", 10), 1, 30, false, "0", "m/s",
               L.T("Più vento, onde più lunghe e distanti tra loro; poco vento, onde corte e fitte. L'altezza resta quella scelta sopra"));
            Sl(card, Waves, L.T("Creste"), "chop", D("chop", 1.2) * 100, 0, 200, false, "0", "%",
               L.T("Quanto sono appuntite le creste: 0% onde tonde e lisce, oltre 100% creste aguzze che si rompono"), x => x / 100);
            Sl(card, Icons.Compass, L.T("Direzione"), "direction", D("direction", 0), 0, 360, false, "0", "°",
               L.T("Verso dove vanno le onde. Conta di più con l'«Allineamento» alto (Avanzate)"));
            Sl(card, Icons.Cloud, L.T("Schiuma"), "foam", D("foam", 0.35) * 100, 0, 100, false, "0", "%",
               L.T("La schiuma bianca dove le creste si rompono: da nessuna a mare in tempesta"), x => x / 100);
            // (1.76.16) with a terrain the sea goes to its foot, often hundreds of metres down: the range follows
            double lvNow = D("level", 0);
            Sl(card, Icons.Horizon, L.T("Livello del mare"), "level", lvNow, Math.Min(-20, Math.Floor(lvNow / 50) * 50 - 50), Math.Max(20, Math.Ceiling(lvNow / 50) * 50 + 50), false, "0.00", "m",
               L.T("L'altezza della superficie del mare rispetto allo zero della scena"));

            var colors = new WrapPanel { Margin = new Thickness(0, 6, 0, 0) };
            var curC = S("color", "mediterraneo");
            foreach (var c in (oc["colors"] as JsonArray ?? new JsonArray()).OfType<JsonObject>())
            {
                var id = (string?)c["id"] ?? "";
                var chip = new StackPanel { Orientation = Orientation.Horizontal };
                chip.Children.Add(WaterDot(c));
                chip.Children.Add(new TextBlock { Text = (string?)c["name"] ?? id, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(7, 0, 0, 0) });
                var b = Theme.Button(chip, id == curC ? Theme.Kind.Segment : Theme.Kind.Ghost, L.T("Il colore dell'acqua: quello del fondo e quello, più chiaro, delle creste"));
                b.MinHeight = 28; b.FontSize = 12; b.Padding = new Thickness(10, 0, 10, 0); b.Margin = new Thickness(0, 0, 6, 6);
                b.Click += async (_, __) => await SetOcean(new JsonObject { ["settings"] = new JsonObject { ["color"] = id } });
                colors.Children.Add(b);
            }
            card.Children.Add(colors);

            var row = new WrapPanel { Margin = new Thickness(0, 4, 0, 0) };
            var seed = SmallButton(Icons.Refresh, L.T("Seme casuale"), async () => await SetOcean(new JsonObject { ["randomSeed"] = true }));
            seed.ToolTip = L.T("Le stesse onde in un'altra disposizione");
            seed.Margin = new Thickness(0, 0, 6, 0);
            row.Children.Add(seed);
            var del = SmallButton(Icons.Trash, L.T("Togli il mare"), async () => await SetOcean(new JsonObject { ["on"] = false }));
            row.Children.Add(del);
            card.Children.Add(row);

            if ((bool?)oc["groundCovers"] ?? false)
            {
                var w = Theme.Label(L.T("C'è anche il suolo dell'Ambiente: spunta tra le onde e copre il mare se è più in alto."), 11.5, Theme.Warm);
                w.TextWrapping = TextWrapping.Wrap; w.Margin = new Thickness(0, 10, 0, 4);
                card.Children.Add(w);
                var noGround = SmallButton(Icons.Grass, L.T("Togli il suolo"), async () =>
                {
                    await SetAmbience(new JsonObject { ["ground"] = new JsonObject { ["type"] = "nessuno" } });
                    if (_rightPanel == "landscape") RenderProps();
                });
                noGround.HorizontalAlignment = HorizontalAlignment.Left;
                card.Children.Add(noGround);
            }

            // the rest of the modifier
            var adv = Advanced(card, "ocean");
            if (_terrain != null)
            {
                var foot = new Toggle(L.T("Al piede del terreno"), (bool?)st["levelAuto"] ?? false,
                    L.T("Il livello del mare segue il terreno: al suo bordo più basso, così il terreno emerge tutto dal mare. Si spegne da solo se muovi «Livello del mare»"));
                foot.Toggled += async v => await SetOcean(new JsonObject { ["settings"] = new JsonObject { ["levelAuto"] = v } });
                adv.Body.Children.Add(foot);
            }
            var spec = S("spectrum", "turbulent");
            var specHead = Theme.Label(L.T("Tipo di mare"), 12, Theme.TextMuted);
            specHead.Margin = new Thickness(0, 2, 0, 4);
            adv.Body.Children.Add(specHead);
            var specs = new WrapPanel();
            foreach (var x in (oc["spectra"] as JsonArray ?? new JsonArray()).OfType<JsonObject>())
            {
                var id = (string?)x["id"] ?? "";
                var tip = id switch
                {
                    "turbulent" => L.T("Mare giovane e caotico, onde di ogni lunghezza (spettro di Phillips)"),
                    "established" => L.T("Mare formato dopo ore di vento costante (spettro di Pierson-Moskowitz)"),
                    "sharp" => L.T("Come il formato, con il picco più marcato e la distanza del vento sul mare (spettro JONSWAP)"),
                    _ => L.T("Acqua poco profonda: le onde sentono il fondo (spettro TMA)"),
                };
                var b = Theme.Button((string?)x["name"] ?? id, id == spec ? Theme.Kind.Segment : Theme.Kind.Ghost, tip);
                b.MinHeight = 28; b.FontSize = 12; b.Padding = new Thickness(10, 0, 10, 0); b.Margin = new Thickness(0, 0, 6, 6);
                b.Click += async (_, __) => await SetOcean(new JsonObject { ["settings"] = new JsonObject { ["spectrum"] = id } });
                specs.Children.Add(b);
            }
            adv.Body.Children.Add(specs);
            Sl(adv.Body, Icons.Move, L.T("Allineamento"), "align", D("align", 0) * 100, 0, 100, false, "0", "%",
               L.T("0% onde in tutte le direzioni, 100% tutte parallele nella «Direzione»"), x => x / 100);
            Sl(adv.Body, Icons.Soft, L.T("Onda più piccola"), "smallest", D("smallest", 0.01) * 100, 0.1, 200, true, "0.0", "cm",
               L.T("Le onde più corte di così non ci sono: alzalo per una superficie più liscia"), x => x / 100);
            Sl(adv.Body, Icons.Soft, L.T("Smorzamento"), "damping", D("damping", 0.5) * 100, 0, 100, false, "0", "%",
               L.T("Quanto si spengono le onde che vanno contro il vento"), x => x / 100);
            Sl(adv.Body, Icons.ChevronsDown, L.T("Profondità del fondale"), "depth", D("depth", 200), 1, 250, true, "0.0", "m",
               L.T("In acqua bassa le onde si accorciano e si alzano"));
            if (spec is "sharp" or "shallow")
            {
                Sl(adv.Body, Icons.Wind, L.T("Distanza del vento sul mare"), "fetch", D("fetch", 100), 0.1, 1000, true, "0.0", "km",
                   L.T("Per quanto mare il vento soffia senza ostacoli: poco, onde corte e giovani; tanto, onde lunghe da mare aperto"));
                // (1.76.37) «Picchi» taken off the panel: tools/slider_audit.py found it changes nothing - Blender's
                // Ocean modifier ignores its «sharpen peak» (checked: the surface identical from 0 to 1). The value is
                // still kept and read, should a later Blender use it
            }
            Sl(adv.Body, Icons.Clock, L.T("Istante"), "time", D("time", 1), 0, 100, false, "0.0", "s",
               L.T("Il momento fotografato: le onde avanzano come qualche secondo dopo"));
            Sl(adv.Body, Icons.WaterDrop, L.T("Increspature"), "ripples", D("ripples", 0.35) * 100, 0, 100, false, "0", "%",
               L.T("Onde corte: al 35% quelle del mare vero; meno, più liscio e a specchio"), x => x / 100);

            FrameworkElement Seg(string label, string key, string val, (string id, string name, string tip)[] items)
            {
                var sp = new StackPanel { Margin = new Thickness(0, 8, 0, 0) };
                var l = Theme.Label(label, 12, Theme.TextMuted);
                l.Margin = new Thickness(0, 0, 0, 4);
                sp.Children.Add(l);
                var seg = Theme.Segmented(out var bs, items.Select(i => ((object)i.name, (string?)i.tip)).ToArray());
                seg.HorizontalAlignment = HorizontalAlignment.Left;
                Theme.SetSegment(bs, Math.Max(0, Array.FindIndex(items, i => i.id == val)));
                for (int i = 0; i < bs.Count; i++)
                {
                    var id = items[i].id;
                    bs[i].Click += async (_, __) => await SetOcean(new JsonObject { ["settings"] = new JsonObject { [key] = id } });
                }
                sp.Children.Add(seg);
                return sp;
            }
            adv.Body.Children.Add(Seg(L.T("Dettaglio"), "detail", S("detail", "media"), new[]
            {
                ("bassa", L.T("Basso"), L.T("Punti del mare più radi nella zona delle onde vere (uno ogni 1,5 m almeno): vista più leggera e render più rapido, onde da vicino un po' più morbide")),
                ("media", L.T("Medio"), L.T("Un punto ogni metro almeno nella zona delle onde vere: il giusto per la maggior parte delle scene")),
                ("alta", L.T("Alto"), L.T("Un punto ogni 75 cm e il doppio della suddivisione nel render: onde più fini da vicino, più memoria e più tempo per il render")),
            }));
            // (1.76.39, Luca: «io non uso sempre e solo la fotocamera? a cosa serve l'altra opzione?») where the sea has
            // its true waves: following the view (new) or fixed on the scene
            var where = Seg(L.T("Onde vere"), "center", S("center", "scena"), new[]
            {
                ("camera", L.T("Segue l'inquadratura"), L.T("Il mare ha onde vere, in forma, solo in una zona (da 60 a 500 m di lato, più grande se la camera è alta); fuori è piatto e le onde sono solo disegnate dalla luce. Qui la zona sta dove guardi: quando la camera si ferma su un punto fuori dalla zona, il mare si ricalcola lì in pochi secondi (con «Occupato»); finché resti dentro non succede nulla, e prima del render finale lo controlla comunque. Il punto giusto per quasi tutte le immagini, e quello che serve per l'«Acqua mossa sul bordo» di un oggetto lontano dal centro della scena")),
                ("scena", L.T("Ferma sulla scena"), L.T("La zona con le onde vere copre gli oggetti della scena (fino a circa 1 km) e non si sposta mai: giri la camera dove vuoi intorno al soggetto e il mare non si ricalcola, con le onde e la schiuma negli stessi punti in tutte le inquadrature e i fotogrammi di un video. Con un terreno grande il centro è quello del terreno: un oggetto lontano da lì resta nella parte piatta")),
            });
            where.ToolTip = L.T("Dove il mare ha le onde vere (in forma) invece che solo disegnate: dove guardi, o fermo sulla scena");
            adv.Body.Children.Add(where);
            var pts = (long?)oc["points"] ?? 0;
            if (pts > 0)
                adv.Body.Children.Add(HintSmall(L.F("Superficie nella vista: {0} punti; le onde si ripetono ogni {1} m", pts.ToString("N0"), ((double?)oc["spatial"] ?? 0).ToString("0"))));
            adv.Done((bool?)oc["advChanged"] ?? false, async () => await SetOcean(new JsonObject { ["resetAdvanced"] = true }));

            // the coast: the sea near what it touches (ocean.py, _COAST): waves that feel the bottom and break, foam
            // of the surf and around the rocks, clear shallow water, the shore wet up to where the waves run
            var cc = new StackPanel();
            var ct = SectionTitle(L.T("Costa"));
            ct.DataContext = (Icons.Puddle, SeaColor);
            cc.Children.Add(ct);
            _props.Children.Add(Theme.Card(cc, 16));
            var coastOn = (bool?)st["coast"] ?? true;
            var coastT = new Toggle(L.T("Spiagge e scogli"), coastOn,
                L.T("Il mare sente quello che tocca: sopra un fondale che sale le onde si abbassano e si rompono in una fascia di schiuma, intorno a scogli e piloni c'è un anello di schiuma, l'acqua bassa è trasparente e la riva è bagnata fin dove arrivano le onde. Vale per gli oggetti della scena che arrivano al livello del mare (non il suolo dell'Ambiente)"));
            coastT.Toggled += async v => await SetOcean(new JsonObject { ["settings"] = new JsonObject { ["coast"] = v } });
            cc.Children.Add(coastT);
            if (coastOn)
            {
                Sl(cc, Icons.Cloud, L.T("Schiuma della costa"), "coastFoam", D("coastFoam", 1) * 100, 0, 200, false, "0", "%",
                   L.T("La schiuma dei frangenti, quella intorno agli scogli e le righe lasciate dalle onde sulla riva"), x => x / 100);
                var clear = new Toggle(L.T("Acqua bassa trasparente"), (bool?)st["shallow"] ?? true,
                    L.T("Dove l'acqua è bassa si vede il fondo, con il colore che vira verso il blu man mano che si fa profonda. Nel path tracing è acqua vera (rifrazione e assorbimento): costa un po' di più, solo vicino alla costa"));
                clear.Toggled += async v => await SetOcean(new JsonObject { ["settings"] = new JsonObject { ["shallow"] = v } });
                clear.Margin = new Thickness(0, 6, 0, 0);
                cc.Children.Add(clear);
                var cadv = Advanced(cc, "coast");
                Sl(cadv.Body, Icons.Eye, L.T("Limpidezza"), "clarity", D("clarity", 1) * 100, 10, 400, true, "0", "%",
                   L.T("Fino a che profondità si vede il fondo. 100% = quella tipica del colore dell'acqua scelto (tropicale più limpida, torbido meno)"), x => x / 100);
                Sl(cadv.Body, Icons.WaterDrop, L.T("Fascia bagnata"), "wetBand", D("wetBand", 1) * 100, 0, 300, false, "0", "%",
                   L.T("Fin dove la riva e gli scogli sono bagnati sopra il livello del mare: 100% = dove arrivano le onde di questa altezza, 0% = asciutti"), x => x / 100);
                // (1.76.33, Luca: «il bordo che tocca l'acqua è troppo netto») how much the water moves against what it touches
                Sl(cadv.Body, Icons.Wind, L.T("Acqua mossa sul bordo"), "edgeMove", D("edgeMove", 1) * 100, 0, 300, false, "0", "%",
                   L.T("Quanto l'acqua si muove contro gli scogli e gli oggetti che tocca: la linea dove li incontra ondeggia invece di essere un taglio netto. Si vede nel path tracing; 0% = taglio netto"), x => x / 100);
                cadv.Done((bool?)oc["coastAdvChanged"] ?? false, async () => await SetOcean(new JsonObject { ["resetCoast"] = true }));
                if (oc["coastInfo"] is JsonObject ci)
                {
                    var nObj = (long?)ci["objects"] ?? 0;
                    cc.Children.Add(HintSmall(nObj == 0
                        ? L.T("Nessun oggetto della scena arriva al livello del mare: la costa comparirà quando ce ne sarà uno (una spiaggia, uno scoglio, un molo).")
                        : L.F("Costa misurata su {0} oggetti in {1} s; si aggiorna da sola quando li sposti o li modifichi.", nObj.ToString(), ((double?)ci["secs"] ?? 0).ToString("0.0"))));
                }
            }
        }
    }
}
