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
    /// Ambiente (header button, panel on the right): physical sky and sun, clouds, haze, night sky, ground and
    /// automatic exposure (engine: ambience.py). Presets on top, then the details. Every change goes to the engine
    /// (one undo step) and to the real-time view (sky picture, haze, exposure).
    /// </summary>
    public sealed partial class MainWindow
    {
        JsonObject _ambience = new JsonObject();

        int _ambSeq;          // (1.79.0) changes sent: a reading asked before one of them does not overwrite its answer

        async Task LoadAmbience()
        {
            var seq = _ambSeq;
            await Run(async api => { var r = await api.Get("ambience"); if (seq == _ambSeq) _ambience = r; });
        }

        /// <summary>(Luca: «ho modificato size e coverage è tornato a 70») Every command that changes the ambience goes through
        /// here: its answer is the new state only if no later change has been sent (the engine answers in order but a slow one
        /// can arrive after a newer one), and a reading asked before it (LoadAmbience, RefreshScene) never overwrites it:
        /// those compare the number of changes sent when they started.</summary>
        async Task<JsonObject?> AmbWrite(string path, JsonObject body)
        {
            var mine = ++_ambSeq;
            // the panel shows at once what was sent: an answer thrown away because a newer change went out, or a reading that
            // comes from before it, can no longer bring the old value back (it was that, with the slider of the clouds)
            if (path == "ambience") OverlayAmbience(body);
            JsonObject? r = null;
            await Run(async api => { r = await api.Post(path, body); });
            if (r != null && mine == _ambSeq)
            {
                _ambience = r;
                if (path == "ambience") CheckAmbienceEcho(body, r);
            }
            return r;
        }

        void OverlayAmbience(JsonObject body)
        {
            if (_ambience["state"] is not JsonObject st) return;
            foreach (var g in body)
                if (g.Value is JsonObject part && g.Key != "hdri")
                {
                    if (st[g.Key] is not JsonObject dst) st[g.Key] = dst = new JsonObject();
                    foreach (var kv in part) dst[kv.Key] = kv.Value?.DeepClone();
                }
        }

        /// <summary>The engine's answer must hold the numbers that were sent (the preset and type changes bring their own);
        /// if not, the log says which one came back different.</summary>
        void CheckAmbienceEcho(JsonObject body, JsonObject answer)
        {
            if (body.ContainsKey("preset") || answer["state"] is not JsonObject st) return;
            foreach (var g in body)
                if (g.Value is JsonObject part && st[g.Key] is JsonObject got)
                    foreach (var kv in part)
                        if (kv.Value is JsonValue v && v.TryGetValue<double>(out var sent) && got[kv.Key] is JsonValue gv && gv.TryGetValue<double>(out var back)
                            && Math.Abs(sent - back) > 1e-6 * Math.Max(1, Math.Abs(sent)))
                            AppLog.Write($"ambience: the engine answered {g.Key}.{kv.Key} = {back} but {sent} was sent");
        }

        /// <summary>The ambience as it is now, to the real-time view (called after every refresh of the scene).</summary>
        void PushAmbienceToViewer()
        {
            SendToWeb(new { type = "ambience", info = _ambience.DeepClone() });
            PushToneToViewer();                  // (the fill light follows the automatic exposure)
        }

        async Task SetAmbience(JsonObject change)
        {
            // «Occupato» at once, until the view has its new sky and lights (a change to night or sunset took
            // seconds with nothing on screen: clicks went nowhere and it looked broken)
            // (1.79.0, Luca: «ho portato lo slider ... non è successo nulla») when the change leaves the app: with the
            // engine's SIMPLER_SLOW (waited ms) the log says where a change stopped
            AppLog.Write("ambience change sent: " + change.ToJsonString());
            SendToWeb(new { type = "busyNow", what = L.T("Cambio dell'ambiente") });
            using var busy = BeginBusy();
            await AmbWrite("ambience", change);
            await RefreshScene();              // the sun, the moon or the ground may have changed (and the view follows)
            if (_rightPanel == "ambience") RenderProps();
        }

        // the sun dome of the Ambiente (turned as the view) and the direction the view looks to: degrees clockwise
        // from +Y seen from above, as the north of the sun
        SunDome? _sunDome;
        double? _viewYawDeg;
        double ViewYaw()
        {
            if (_viewYawDeg is double y) return y;
            if (_renderSettings?["view"] is JsonObject v && v["position"] is JsonArray p && v["target"] is JsonArray t && p.Count >= 2 && t.Count >= 2)
                return YawOf(p, t);
            return 0;
        }
        static double YawOf(JsonArray pos, JsonArray target)
        {
            double dx = ((double?)target[0] ?? 0) - ((double?)pos[0] ?? 0), dy = ((double?)target[1] ?? 0) - ((double?)pos[1] ?? 0);
            if (Math.Abs(dx) + Math.Abs(dy) < 1e-9) return _lastYaw;
            return _lastYaw = (Math.Atan2(dx, dy) * 180 / Math.PI + 360) % 360;
        }
        static double _lastYaw;
        /// <summary>The view moved: the dome turns with it.</summary>
        void ViewMovedForDome(JsonObject msg)
        {
            if (msg["position"] is JsonArray p && msg["target"] is JsonArray t && p.Count >= 2 && t.Count >= 2)
            {
                _viewYawDeg = YawOf(p, t);
                if (_sunDome != null && _sunDome.IsVisible) _sunDome.SetViewYaw(_viewYawDeg.Value);
            }
        }

        static readonly Color NightColor = Color.FromRgb(0xA9, 0x9B, 0xFF);
        static readonly Color RainColor = Color.FromRgb(0x5A, 0xB4, 0xF0);
        static readonly Color SnowColor = Color.FromRgb(0xC8, 0xDC, 0xF0);

        // the brush of the puddles (Pioggia > Avanzate): painted on the surfaces in the view (viewer.js puddle)
        bool _puddleBrush;
        string _brushLayer = "rain";      // the same brush paints the snow (Neve > Avanzate > Pennello neve)
        string _puddleMode = "add";
        double _puddleRadius = 1.0;      // metres

        // the same brush sculpts the snow (Neve > Avanzate > Scolpisci la neve, layer "sculpt": snowsculpt.py)
        string _sculptMode = "steps";       // steps | tyres | dig | raise | smooth
        double _sculptRadius = 0.3, _sculptDepth = 0.08, _sculptSize = 1.0, _sculptGauge = 1.55, _sculptWidth = 0.2;

        // the dirt painted by hand (Materiale > Sporco > Avanzate, layer "dirt": dirtpaint.py): the same brush, on any surface
        string _dirtPreset = "uniforme";
        double _dirtRadius = 0.5, _dirtStrength = 1.0;

        /// <summary>Where the brush works: the Ambiente for puddles and snow, the material editor for the dirt, the
        /// Paesaggio for the terrain («Scultura»).</summary>
        bool BrushPanel() => _brushLayer == "dirt" ? _rightPanel == "material" : _brushLayer == "terrain" ? _rightPanel == "landscape" : _rightPanel == "ambience";

        bool _snowBrushSent;
        void SendPuddleBrush()
        {
            // (1.78.4) the engine knows when the snow brush is on: the mantle lighter while painting, after a pause
            var snowOn = _puddleBrush && BrushPanel() && _brushLayer == "snow";
            if (snowOn != _snowBrushSent && _api != null)
            {
                _snowBrushSent = snowOn;
                _ = _api.Post("snow/brushing", new JsonObject { ["on"] = snowOn }).ContinueWith(t => { }, TaskScheduler.Default);
            }
            SendPuddleBrushToView();
        }

        void SendPuddleBrushToView() =>
            SendToWeb(new
            {
                type = "puddleBrush", on = _puddleBrush && BrushPanel(), mode = _puddleMode, layer = _brushLayer,
                radius = _brushLayer == "sculpt" ? _sculptRadius : _brushLayer == "dirt" ? _dirtRadius : _brushLayer == "terrain" ? _tsRadius : _puddleRadius,
                sculpt = new { mode = _sculptMode, depth = _sculptDepth, size = _sculptSize, gauge = _sculptGauge, width = _sculptWidth },
                preset = _dirtPreset, strength = _dirtStrength,
                terrain = new { ids = TerrainZoneIds(), tool = _tsTool, strength = _tsStrength, soft = _tsSoft },
            });

        async Task SculptStroke(JsonObject msg)
        {
            var d = new JsonObject();
            foreach (var k in new[] { "points", "mode", "radius", "depth", "size", "gauge", "width" })
                if (msg[k] != null) d[k] = msg[k]!.DeepClone();
            await Run(async api => { await api.Post("rain/sculpt", d); });
            await LoadAmbience();
            if (_rightPanel == "ambience") RenderProps();
        }

        async Task PuddleStroke(JsonObject msg)
        {
            if ((string?)msg["layer"] == "dirt") { await DirtStroke(msg); return; }
            await Run(async api => { await api.Post("rain/paint", new JsonObject { ["points"] = msg["points"]?.DeepClone(), ["radius"] = msg["radius"]?.DeepClone(), ["mode"] = msg["mode"]?.DeepClone(), ["layer"] = msg["layer"]?.DeepClone() }); });
            await LoadAmbience();
            PushAmbienceToViewer();       // (painted puddles turn the rain on even at 0 / 0)
        }

        static string MoonPhaseName(double p)
        {
            p = ((p % 1) + 1) % 1;
            return p < 0.03 || p > 0.97 ? L.T("Luna nuova") : p < 0.22 ? L.T("Luna crescente") : p < 0.28 ? L.T("Primo quarto")
                 : p < 0.47 ? L.T("Gibbosa crescente") : p < 0.53 ? L.T("Luna piena") : p < 0.72 ? L.T("Gibbosa calante")
                 : p < 0.78 ? L.T("Ultimo quarto") : L.T("Luna calante");
        }

        bool _nightPolling;
        /// <summary>The stars and the moon are being downloaded (night.py): when they arrive the sky is built again.</summary>
        async Task PollNightDownload()
        {
            if (_nightPolling) return;
            _nightPolling = true;
            try
            {
                for (int i = 0; i < 900; i++)
                {
                    await Task.Delay(2000);
                    JsonObject? st = null;
                    try { st = await _api!.Get("ambience/night/status"); } catch { }
                    var state = (string?)st?["state"] ?? "";
                    if (state == "running")
                    {
                        if (_rightPanel == "ambience" && _ambience["night"] is JsonObject n) { n["fraction"] = st?["fraction"]?.DeepClone(); }
                        continue;
                    }
                    if (state == "done")
                    {
                        await AmbWrite("ambience/refresh", new JsonObject());
                        await RefreshScene();
                        if (_rightPanel == "ambience") RenderProps();
                        Status(L.T("Stelle e luna pronte"));
                    }
                    else if (state == "error") { await LoadAmbience(); if (_rightPanel == "ambience") RenderProps(); }
                    break;
                }
            }
            finally { _nightPolling = false; }
        }

        /// <summary>A preset of the Ambiente as a small tile: a sky swatch with its icon, the name below.</summary>
        static Border PresetTile(string id, string name, bool on, string? tip, Func<Task> click)
        {
            var (top, bottom, icon, ink) = id switch
            {
                "alba" => ("#46508E", "#F7A98A", Icons.Sunrise, "#FFE6D6"),
                "mattino" => ("#7FB6F2", "#FFD7A6", Icons.Sunrise, "#2A3550"),
                "giorno" => ("#2F7BEA", "#9FD0FF", Icons.Light, "#FFF3C4"),
                "pomeriggio" => ("#4A86D6", "#F3D79E", Icons.SunCloud, "#FFFFFF"),
                "ora_doro" => ("#6D78B4", "#F6A64A", Icons.GoldenHour, "#FFF1C9"),
                "tramonto" => ("#323A74", "#F0704A", Icons.Sunset, "#FFE0C2"),
                "crepuscolo" => ("#141B44", "#C0607A", Icons.Moon, "#FFD9E2"),
                "nuvoloso" => ("#7F8A9C", "#C5CCD6", Icons.Cloud, "#FFFFFF"),
                "nebbia" => ("#A9B1BB", "#E1E5EA", Icons.Fog, "#4A5465"),
                "notte" => ("#050A1C", "#1F2D5C", Icons.Moon, "#E6E0FF"),
                "studio" => ("#2C3038", "#7D848F", Icons.Studio, "#F2F4F8"),
                _ => ("#2E6B8F", "#8BC3A0", Icons.Image, "#FFFFFF"),
            };
            var sky = new LinearGradientBrush(Theme.C(top), Theme.C(bottom), 90);
            var swatch = new Border
            {
                Height = 34, CornerRadius = new CornerRadius(6), Background = sky,
                Child = Theme.Icon(icon, Theme.C(ink), 18, 1.7),
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
                Background = Theme.B(on ? Theme.Selected : Theme.Inset), ToolTip = tip ?? name,
            };
            tile.MouseEnter += (_, __) => { if (!on) tile.BorderBrush = Theme.B(Theme.LineStrong); };
            tile.MouseLeave += (_, __) => tile.BorderBrush = idle;
            tile.MouseLeftButtonUp += async (_, e) => { e.Handled = true; await click(); };
            return tile;
        }

        /// <summary>The colour of each ground, as a small dot in its button.</summary>
        static FrameworkElement GroundDot(string id)
        {
            if (id == "nessuno")
                return Theme.Icon(Icons.Close, Theme.TextFaint, 12, 1.8);
            var c = id switch { "piastrelle" => "#E6E3DD", "bianco" => "#EEF0F3", "prato" => "#5E9A3C", "terra" => "#8C6A48", "cemento" => "#A3A39E", _ => "#6F737A" };
            return new System.Windows.Shapes.Ellipse { Width = 12, Height = 12, Fill = Theme.B(c), Stroke = Theme.B(Theme.LineStrong), StrokeThickness = 1, VerticalAlignment = VerticalAlignment.Center };
        }

        /// <summary>The track of the hour slider: night, dawn, day, sunset, night.</summary>
        static Brush DayTrack()
        {
            var g = new LinearGradientBrush { StartPoint = new Point(0, 0), EndPoint = new Point(1, 0) };
            foreach (var (o, c) in new[] { (0.0, "#1A2147"), (0.21, "#2B3770"), (0.26, "#F08A4B"), (0.33, "#8EC5FF"), (0.5, "#4C9DFF"),
                                           (0.67, "#8EC5FF"), (0.74, "#F08A4B"), (0.79, "#2B3770"), (1.0, "#1A2147") })
                g.GradientStops.Add(new GradientStop(Theme.C(c), o));
            g.Freeze();
            return g;
        }

        /// <summary>The track of the day-of-the-year slider: winter, summer, winter.</summary>
        static Brush YearTrack()
        {
            var g = new LinearGradientBrush { StartPoint = new Point(0, 0), EndPoint = new Point(1, 0) };
            foreach (var (o, c) in new[] { (0.0, "#6FA8E8"), (0.25, "#7FCB8A"), (0.47, "#F2B54B"), (0.72, "#D98A4A"), (1.0, "#6FA8E8") })
                g.GradientStops.Add(new GradientStop(Theme.C(c), o));
            g.Freeze();
            return g;
        }

        void RenderAmbiencePanel()
        {
            var st = _ambience["state"] as JsonObject ?? new JsonObject();
            var sky = (string?)st["mode"] != "studio";
            JsonObject G(string k) => st[k] as JsonObject ?? new JsonObject();
            double D(string group, string k, double d) => (double?)G(group)[k] ?? d;

            var head = new StackPanel();
            var top = new DockPanel();
            var close = Theme.Button(L.T("Chiudi"), Theme.Kind.Ghost, L.T("Torna alle proprietà dell'oggetto"));
            close.Click += async (_, __) => await ShowRightPanel("");
            DockPanel.SetDock(close, Dock.Right);
            top.Children.Add(close);
            top.Children.Add(Theme.Caption(L.T("Ambiente")));
            head.Children.Add(top);
            head.Children.Add(HintSmall(L.T("Cielo fisico di Blender: sole, cielo, nuvole e foschia vanno d'accordo tra loro e con il path tracing.")));
            var presets = new UniformGrid { Columns = 3, Margin = new Thickness(0, 12, 0, 0) };
            var cur = (string?)st["preset"] ?? "";
            var mode = (string?)st["mode"] ?? "sky";
            foreach (var p in (_ambience["presets"] as JsonArray ?? new JsonArray()).OfType<JsonObject>())
            {
                var id = (string?)p["id"] ?? "";
                presets.Children.Add(PresetTile(id, (string?)p["name"] ?? id, id == cur && mode != "hdri", null,
                    async () => await SetAmbience(new JsonObject { ["preset"] = id })));
            }
            // a photographed sky (HDRI): chosen in the library (Poly Haven ▾ HDRI); the last one chosen comes back here
            var lastHdri = (string?)G("hdri")["id"] ?? "";
            presets.Children.Add(PresetTile("hdri", L.T("HDRI…"), mode == "hdri",
                L.T("Un cielo fotografato a 360° (HDRI) come sfondo e luce, con il suo sole trasformato in una luce Sole vera. Si sceglie nella libreria in basso"),
                async () =>
                {
                    if (mode != "hdri" && lastHdri != "") await SetAmbience(new JsonObject { ["hdri"] = new JsonObject { ["id"] = lastHdri } });
                    ShowLibraryTab("hdri");
                }));
            head.Children.Add(presets);
            _props.Children.Add(Theme.Card(head, 16));
            if (!sky)
            {
                var t = Theme.Label(L.T("Sfondo da studio: la luce viene dalle luci della scena. Scegli un ambiente qui sopra per il cielo all'aperto."), 12, Theme.TextFaint);
                t.TextWrapping = TextWrapping.Wrap;
                var c = new StackPanel();
                c.Children.Add(t);
                _props.Children.Add(Theme.Card(c, 16));
                return;
            }

            StackPanel Card(string title, Geometry icon, Color color)
            {
                var sp = new StackPanel();
                var t = SectionTitle(title);
                t.DataContext = (icon, color);          // MakeAccordions puts the icon in a small badge before the title
                sp.Children.Add(t);
                _props.Children.Add(Theme.Card(sp, 16));
                return sp;
            }
            ValueSlider S(StackPanel to, Geometry icon, Color ic, string label, string group, string key, double v, double min, double max, bool log, string fmt, string unit, string tip, Func<double, double>? map = null, Brush? track = null)
            {
                var sl = new ValueSlider(label, v, min, max, log, fmt, unit, track, tip).WithIcon(icon, ic);
                sl.Committed += async x => await SetAmbience(new JsonObject { [group] = new JsonObject { [key] = map != null ? map(x) : x } });
                // the sun follows the slider in the real-time view while it moves (light, shadows, disc): the sky
                // picture and the colours follow when the slider is let go
                if (group == "sun" && (string?)_ambience["sunId"] is string sid && sid != "")
                {
                    double vHour = D("sun", "hour", 12), vDay = D("sun", "day", 172), vLat = D("sun", "lat", 45.5), vNorth = D("sun", "north", 0);
                    double baseK = D("sun", "intensity", 1);
                    sl.Changing += x =>
                    {
                        var p = new JsonObject { ["hour"] = vHour, ["day"] = vDay, ["lat"] = vLat, ["north"] = vNorth };
                        if (key is "hour" or "day" or "lat" or "north") p[key] = map != null ? map(x) : x;
                        if (key == "intensity") p["k"] = baseK > 1e-6 ? (map != null ? map(x) : x) / baseK : 1.0;
                        if (key is "hour" or "day" or "lat" or "north" or "intensity")
                            SendToWeb(new { type = "lightPreview", id = sid, sun = p });
                    };
                }
                // the rain follows the slider in the real-time view while it moves (only numbers of the shader change)
                if (group is "rain" or "snow")
                    sl.Changing += x =>
                    {
                        var r = G("rain").DeepClone() as JsonObject ?? new JsonObject();
                        var sn = G("snow").DeepClone() as JsonObject ?? new JsonObject();
                        (group == "rain" ? r : sn)[key] = map != null ? map(x) : x;
                        SendToWeb(new { type = "rainPreview", mode = (string?)st["mode"] ?? "sky", rain = r, snow = sn });
                    };
                to.Children.Add(sl);
                return sl;
            }

            void AdvDone(AdvancedBox box, string group) =>
                box.Done((bool?)(_ambience["advChanged"] as JsonObject)?[group] ?? false,
                         async () => await SetAmbience(new JsonObject { ["resetAdvanced"] = group }));

            void Ground()
            {
                var gr = Card(L.T("Suolo"), Icons.Grass, Theme.AxisY);
                var curG = (string?)G("ground")["type"] ?? "piastrelle";
                var gw = new WrapPanel();
                foreach (var g in (_ambience["grounds"] as JsonArray ?? new JsonArray()).OfType<JsonObject>())
                {
                    var id = (string?)g["id"] ?? "";
                    var chip = new StackPanel { Orientation = Orientation.Horizontal };
                    chip.Children.Add(GroundDot(id));
                    chip.Children.Add(new TextBlock { Text = (string?)g["name"] ?? id, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(7, 0, 0, 0) });
                    var b = Theme.Button(chip, id == curG ? Theme.Kind.Segment : Theme.Kind.Ghost, null);
                    b.MinHeight = 28; b.FontSize = 12; b.Padding = new Thickness(10, 0, 10, 0); b.Margin = new Thickness(0, 0, 6, 6);
                    b.Click += async (_, __) => await SetAmbience(new JsonObject { ["ground"] = new JsonObject { ["type"] = id } });
                    gw.Children.Add(b);
                }
                gr.Children.Add(gw);
                gr.Children.Add(HintSmall(L.T("Un terreno fino all'orizzonte (oggetto «Suolo» nell'albero): puoi anche dargli un altro materiale.")));
            }
            void Rain()
            {
                // wet surfaces and puddles (rain.py): the same in the real-time view and in the path tracing
                var rc = Card(L.T("Pioggia"), Icons.Rain, RainColor);
                if (D("snow", "amount", 0) > 0)
                    rc.Children.Add(HintSmall(L.T("Sospesa mentre nevica: le impostazioni restano e tornano quando la neve è a zero.")));
                S(rc, Icons.WaterDrop, RainColor, L.T("Bagnato"), "rain", "wet", D("rain", "wet", 0) * 100, 0, 100, false, "0", "%",
                  L.T("Quanto sono bagnate le superfici: asfalto, pietra, legno e tessuti diventano più scuri e lucidi, metallo e vernici prendono un velo d'acqua. Oltre metà, sul terreno piano si forma un velo d'acqua continuo: al 100% è tutto lucido come dopo un acquazzone"), x => x / 100);
                S(rc, Icons.Puddle, RainColor, L.T("Pozzanghere"), "rain", "puddles", D("rain", "puddles", 0) * 100, 0, 100, false, "0", "%",
                  L.T("Quanta parte del terreno è coperta d'acqua: da qualche pozzanghera sparsa alla strada allagata"), x => x / 100);
                S(rc, Icons.Expand, RainColor, L.T("Dimensione pozzanghere"), "rain", "size", D("rain", "size", 0.5) * 100, 0, 100, false, "0", "%",
                  L.T("Pozzanghere piccole e fitte o grandi e distanti"), x => x / 100);
                S(rc, Icons.Eye, RainColor, L.T("Trasparenza dell'acqua"), "rain", "look", D("rain", "look", 0.3) * 100, 0, 100, false, "0", "%",
                  L.T("0% = specchio scuro, come acqua profonda che riflette cielo ed edifici · 100% = acqua bassa: si vede il fondo, il riflesso resta di taglio"), x => x / 100);
                rc.Children.Add(HintSmall(L.T("Le pozzanghere si formano sulle superfici piane rivolte verso l'alto; erba e alberi delle distribuzioni restano solo bagnati.")));
                var rainA = Advanced(rc, "rain");
                RainDrops(rainA.Body);
                S(rainA.Body, Icons.Move, RainColor, L.T("Sposta X"), "rain", "offX", D("rain", "offX", 0) * 100, -100, 100, false, "0", "%",
                  L.T("Sposta le pozzanghere lungo l'asse X, per toglierne una da dove non la vuoi"), x => x / 100);
                S(rainA.Body, Icons.Move, RainColor, L.T("Sposta Y"), "rain", "offY", D("rain", "offY", 0) * 100, -100, 100, false, "0", "%",
                  L.T("Sposta le pozzanghere lungo l'asse Y"), x => x / 100);
                S(rainA.Body, Icons.Soft, RainColor, L.T("Sfumatura bordi"), "rain", "soft", D("rain", "soft", 0.3) * 100, 0, 100, false, "0", "%",
                  L.T("Bordi delle pozzanghere netti (0%) o sfumati nel terreno bagnato (100%)"), x => x / 100);
                var outdoor = new Toggle(L.T("Solo all'aperto"), (bool?)G("rain")["outdoor"] ?? true,
                    L.T("Sotto tettoie, portici, balconi, auto e alberi resta asciutto, come con la pioggia vera. Spento: si bagna tutto, anche al coperto"));
                outdoor.Toggled += async v => await SetAmbience(new JsonObject { ["rain"] = new JsonObject { ["outdoor"] = v } });
                outdoor.Margin = new Thickness(0, 6, 0, 0);
                rainA.Body.Children.Add(outdoor);
                // the brush of the puddles: where you want them, or none where you do not
                var pb = new Toggle(L.T("Pennello pozzanghere"), _puddleBrush && _brushLayer == "rain",
                    L.T("Dipingi le pozzanghere sulla vista: tieni premuto il tasto sinistro e trascina. Maiusc (o «Togli») le toglie, anche quelle automatiche; [ e ] cambiano la grandezza, Esc smette. Una pozzanghera dipinta va anche sotto una tettoia; il tasto destro gira la vista come sempre"));
                pb.Toggled += v => { _puddleBrush = v; _brushLayer = "rain"; SendPuddleBrush(); RenderProps(); };
                pb.Margin = new Thickness(0, 10, 0, 0);
                rainA.Body.Children.Add(pb);
                if (_puddleBrush && _brushLayer == "rain")
                {
                    var seg = Theme.Segmented(out var segButtons, (L.T("Aggiungi"), L.T("Il pennello mette pozzanghere")), (L.T("Togli"), L.T("Il pennello toglie pozzanghere, anche quelle automatiche")));
                    seg.HorizontalAlignment = HorizontalAlignment.Left;
                    seg.Margin = new Thickness(0, 6, 0, 4);
                    Theme.SetSegment(segButtons, _puddleMode == "remove" ? 1 : 0);
                    for (int i = 0; i < segButtons.Count; i++)
                    {
                        var idx = i;
                        segButtons[i].Click += (_, __) => { _puddleMode = idx == 1 ? "remove" : "add"; Theme.SetSegment(segButtons, idx); SendPuddleBrush(); };
                    }
                    rainA.Body.Children.Add(seg);
                    var rs = new ValueSlider(L.T("Grandezza pennello"), _puddleRadius * 100, 10, 1000, true, "0", "cm", null,
                        L.T("Il raggio del pennello ([ e ] sulla vista)")).WithIcon(Icons.Brush, RainColor);
                    rs.Changing += x => { _puddleRadius = x / 100; SendPuddleBrush(); };
                    rs.Committed += x => { _puddleRadius = x / 100; SendPuddleBrush(); };
                    rainA.Body.Children.Add(rs);
                }
                if (_puddleBrush && _brushLayer == "rain")      // (only with the brush on: off, the box goes)
                    S(rainA.Body, Icons.Soft, RainColor, L.T("Sfumatura pennello"), "rain", "paintSoft", D("rain", "paintSoft", 0.5) * 100, 0, 100, false, "0", "%",
                      L.T("Bordi delle pozzanghere dipinte netti (0%) o sfumati nel terreno bagnato (100%). Vale per tutte, anche quelle già dipinte"), x => x / 100);
                if ((bool?)_ambience["rainPainted"] ?? false)
                {
                    var clr = SmallButton(Icons.Trash, L.T("Cancella le pozzanghere dipinte"), async () =>
                    {
                        await Run(async api => { await api.Post("rain/paint/clear", new JsonObject()); });
                        await LoadAmbience(); PushAmbienceToViewer(); RenderProps();
                    });
                    clr.HorizontalAlignment = HorizontalAlignment.Left;
                    clr.Margin = new Thickness(0, 6, 0, 0);
                    rainA.Body.Children.Add(clr);
                }
                AdvDone(rainA, "rain");
            }
            void Snow()
            {
                // snow on the surfaces (rain.py, the same materials): white where the surface faces up, patchy at
                // its edges, never under a shelter; while it snows the rain waits
                var sc = Card(L.T("Neve"), Icons.Snow, SnowColor);
                S(sc, Icons.Snow, SnowColor, L.T("Quantità"), "snow", "amount", D("snow", "amount", 0) * 100, 0, 100, false, "0", "%",
                  L.T("Da una spolverata a chiazze a tutto bianco. Si posa dove la superficie guarda verso l'alto (terreno, tetti, cornicioni, auto, alberi e prati delle distribuzioni) e non sotto tettoie, portici e alberi. Mentre nevica la pioggia è sospesa"), x => x / 100);
                S(sc, Icons.Expand, SnowColor, L.T("Spessore"), "snow", "depth", D("snow", "depth", 0.1) * 100, 0, 50, false, "0", "cm",
                  L.T("Lo strato di neve vero, con il suo spessore: su terreno, tetti, cornicioni e auto, arrotondato sui bordi. 0 = solo il bianco sulle superfici. Erba e alberi delle distribuzioni restano solo bianchi"), x => x / 100);
                var snowA = Advanced(sc, "snow");
                Snowfall(snowA.Body);
                S(snowA.Body, Icons.Expand, SnowColor, L.T("Sulle pareti"), "snow", "walls", D("snow", "walls", 0.3) * 100, 0, 100, false, "0", "%",
                  L.T("Quanto scende sulle superfici inclinate: 0% solo sul piano, 100% anche sulle pareti quasi verticali, come neve portata dal vento"), x => x / 100);
                S(snowA.Body, Icons.Soft, SnowColor, L.T("Sfumatura bordi"), "snow", "soft", D("snow", "soft", 0.3) * 100, 0, 100, false, "0", "%",
                  L.T("Bordi delle chiazze di neve netti (0%) o sfumati (100%)"), x => x / 100);
                S(snowA.Body, Icons.Move, SnowColor, L.T("Sposta X"), "snow", "offX", D("snow", "offX", 0) * 100, -100, 100, false, "0", "%",
                  L.T("Sposta le chiazze di neve lungo l'asse X"), x => x / 100);
                S(snowA.Body, Icons.Move, SnowColor, L.T("Sposta Y"), "snow", "offY", D("snow", "offY", 0) * 100, -100, 100, false, "0", "%",
                  L.T("Sposta le chiazze di neve lungo l'asse Y"), x => x / 100);
                S(snowA.Body, Icons.Clock, SnowColor, L.T("Neve vecchia"), "snow", "age", D("snow", "age", 0) * 100, 0, 100, false, "0", "%",
                  L.T("Neve caduta da giorni: il bianco si spegne, compaiono aloni di sporco sparsi, più marcati dove la neve si assottiglia e nelle tracce di passi e pneumatici, e la superficie diventa una crosta un po' più lucida. 0% = neve fresca. Cambia solo il colore della neve, il mantello non si ricalcola"), x => x / 100);
                if (D("snow", "depth", 0.1) > 0)
                {
                    // how fine the mantle is: Simpler keeps it within what the scene can carry (snow.limits) and says
                    // when it gets heavy
                    var det = D("snow", "detail", 0.5);
                    S(snowA.Body, Icons.Expand, SnowColor, L.T("Dettaglio del mantello"), "snow", "detail", det * 100, 0, 100, false, "0", "%",
                      L.T("Quanto è fine il mantello di neve: bordi più precisi su tetti, cornicioni e auto, ma più tempo per calcolarlo e più peso nella vista. Le celle si allargano da sole nelle scene grandi; Simpler non supera mai 4 milioni di vertici"), x => x / 100);
                    if (_ambience["snowMantle"] is JsonObject mm)
                    {
                        var cellCm = ((double?)mm["cell"] ?? 0) * 100;
                        var verts = (long?)mm["vertices"] ?? 0;
                        var secs = (double?)mm["secs"] ?? 0;
                        snowA.Body.Children.Add(HintSmall(L.F("Mantello attuale: celle di {0} cm, {1} vertici, calcolato in {2} s", cellCm.ToString("0.0"), verts.ToString("N0"), secs.ToString("0.0"))));
                        var copies = (long?)mm["copies"] ?? 0;
                        if (copies > 0)
                            snowA.Body.Children.Add(HintSmall(L.F("Distribuzioni: {0} copie con il mantello, da {1} forme (ogni forma si calcola una volta sola)", copies.ToString("N0"), ((long?)mm["scatter"] ?? 0).ToString())));
                        if ((bool?)mm["heavy"] ?? false)
                        {
                            var w = Theme.Label(L.T("Mantello pesante: la vista in tempo reale può rallentare e ogni modifica alla scena lo ricalcola. Abbassa il dettaglio se non ti serve."), 11.5, Theme.Warm);
                            w.TextWrapping = TextWrapping.Wrap; w.Margin = new Thickness(0, 4, 0, 0);
                            snowA.Body.Children.Add(w);
                        }
                    }
                    if (det > 0.75)
                    {
                        var w2 = Theme.Label(L.T("Dettaglio alto: in una scena grande il calcolo può durare decine di secondi e usare qualche GB di memoria."), 11.5, Theme.Warm);
                        w2.TextWrapping = TextWrapping.Wrap; w2.Margin = new Thickness(0, 4, 0, 0);
                        snowA.Body.Children.Add(w2);
                    }
                }
                var outdoorS = new Toggle(L.T("Solo all'aperto"), (bool?)G("snow")["outdoor"] ?? true,
                    L.T("Sotto tettoie, portici, balconi, auto e alberi non c'è neve. Spento: la neve va dappertutto, anche al coperto"));
                outdoorS.Toggled += async v => await SetAmbience(new JsonObject { ["snow"] = new JsonObject { ["outdoor"] = v } });
                outdoorS.Margin = new Thickness(0, 6, 0, 0);
                snowA.Body.Children.Add(outdoorS);
                // the brush of the snow: a path cleared, a heap against a wall (the same brush as the puddles)
                var snowOn = _puddleBrush && _brushLayer == "snow";
                var sb = new Toggle(L.T("Pennello neve"), snowOn,
                    L.T("Dipingi la neve sulla vista: tieni premuto il tasto sinistro e trascina. Maiusc (o «Togli») la toglie, anche quella automatica, con il suo spessore: un vialetto spalato, un marciapiede pulito. [ e ] cambiano la grandezza, Esc smette. La neve dipinta va anche sotto una tettoia e c'è anche con la Quantità a zero, se non piove"));
                sb.Toggled += v => { _puddleBrush = v; _brushLayer = "snow"; SendPuddleBrush(); RenderProps(); };
                sb.Margin = new Thickness(0, 10, 0, 0);
                snowA.Body.Children.Add(sb);
                if (snowOn && ((double?)_ambience["snow"]?["detail"] ?? 0.5) > 0.4 + 1e-6)
                    snowA.Body.Children.Add(HintSmall(L.T("Mentre il pennello è acceso il manto si calcola più leggero e dopo una breve pausa tra le pennellate: torna al dettaglio scelto quando lo spegni. Le immagini finali hanno sempre il dettaglio scelto.")));
                if (snowOn)
                {
                    var seg = Theme.Segmented(out var segButtons, (L.T("Aggiungi"), L.T("Il pennello mette neve")), (L.T("Togli"), L.T("Il pennello toglie la neve, anche quella automatica")));
                    seg.HorizontalAlignment = HorizontalAlignment.Left;
                    seg.Margin = new Thickness(0, 6, 0, 4);
                    Theme.SetSegment(segButtons, _puddleMode == "remove" ? 1 : 0);
                    for (int i = 0; i < segButtons.Count; i++)
                    {
                        var idx = i;
                        segButtons[i].Click += (_, __) => { _puddleMode = idx == 1 ? "remove" : "add"; Theme.SetSegment(segButtons, idx); SendPuddleBrush(); };
                    }
                    snowA.Body.Children.Add(seg);
                    var rs = new ValueSlider(L.T("Grandezza pennello"), _puddleRadius * 100, 10, 1000, true, "0", "cm", null,
                        L.T("Il raggio del pennello ([ e ] sulla vista)")).WithIcon(Icons.Brush, SnowColor);
                    rs.Changing += x => { _puddleRadius = x / 100; SendPuddleBrush(); };
                    rs.Committed += x => { _puddleRadius = x / 100; SendPuddleBrush(); };
                    snowA.Body.Children.Add(rs);
                }
                var snowPainted = (bool?)_ambience["snowPainted"] ?? false;
                if (snowOn)                                       // (only with the brush on: off, the box goes)
                    S(snowA.Body, Icons.Soft, SnowColor, L.T("Sfumatura pennello"), "snow", "paintSoft", D("snow", "paintSoft", 0.5) * 100, 0, 100, false, "0", "%",
                      L.T("Bordi della neve dipinta netti (0%) o sfumati (100%). Vale per tutta, anche quella già dipinta"), x => x / 100);
                if (snowPainted)
                {
                    var clr = SmallButton(Icons.Trash, L.T("Cancella la neve dipinta"), async () =>
                    {
                        await Run(async api => { await api.Post("rain/paint/clear", new JsonObject { ["layer"] = "snow" }); });
                        await LoadAmbience(); PushAmbienceToViewer(); RenderProps();
                    });
                    clr.HorizontalAlignment = HorizontalAlignment.Left;
                    clr.Margin = new Thickness(0, 6, 0, 0);
                    snowA.Body.Children.Add(clr);
                }
                if (D("snow", "depth", 0.1) > 0)
                    SculptControls(snowA.Body);
                AdvDone(snowA, "snow");
            }
            void Snowfall(StackPanel fc)
            {
                // the flakes that fall (snowfall.py), first in the Avanzate of the snow: real flakes in the frame of the
                // camera, with wind, eddies, patches and the smear of the movement; separate from the snow on the ground
                var head = Theme.IconText(Icons.Snow, L.T("Fiocchi che cadono"), SnowColor, 14);
                ((TextBlock)head.Children[1]).FontWeight = FontWeights.SemiBold;
                head.Margin = new Thickness(0, 2, 0, 8);
                fc.Children.Add(head);
                var on = (bool?)G("snow")["fall"] ?? false;
                var t = new Toggle(L.T("Nevica"), on,
                    L.T("Fiocchi veri nella scena, solo dove guarda la camera: spariscono dietro gli edifici, non ci sono sotto tettoie e portici, di notte si accendono nella luce dei lampioni, con la profondità di campo i più vicini diventano dischi sfocati. Si ricalcolano quando la camera si ferma. Indipendente dalla neve a terra"));
                t.Toggled += async v => await SetAmbience(new JsonObject { ["snow"] = new JsonObject { ["fall"] = v } });
                fc.Children.Add(t);
                WeatherPresetGrid(fc, "snow", G("snow"), on);
                var m = on ? ManualFold(fc, "snow") : null;
                if (on && m != null)
                {
                    S(m, Icons.Snow, SnowColor, L.T("Intensità"), "snow", "fallAmount", D("snow", "fallAmount", 0.5) * 100, 1, 100, false, "0", "%",
                      L.T("Da qualche fiocco a una bufera: quanti fiocchi per metro cubo. In lontananza diventano un velo"), x => x / 100);
                    S(m, Icons.Wind, SnowColor, L.T("Vento"), "snow", "fallWind", D("snow", "fallWind", 0.2) * 100, 0, 100, false, "0", "%",
                      L.T("Spinge i fiocchi di lato: 0% cadono dritti, 100% quasi orizzontali (circa 50 km/h)"), x => x / 100);
                    S(m, Icons.Compass, SnowColor, L.T("Direzione del vento"), "snow", "fallDir", D("snow", "fallDir", 0), 0, 360, false, "0", "°",
                      L.T("Verso dove soffia il vento: 0° = verso il nord della scena (asse Y), 90° = verso est (asse X)"));
                    S(m, Icons.Haze, SnowColor, L.T("Irregolarità"), "snow", "fallGust", D("snow", "fallGust", 0.4) * 100, 0, 100, false, "0", "%",
                      L.T("Raffiche e vortici: i fiocchi non vanno più tutti nella stessa direzione, alcuni volano veloci, altri quasi fermi, in mulinelli. 0% = tutti paralleli"), x => x / 100);
                    S(m, Icons.Cloud, SnowColor, L.T("Zone"), "snow", "fallZones", D("snow", "fallZones", 0.4) * 100, 0, 100, false, "0", "%",
                      L.T("La neve non è uguale dappertutto: cortine più fitte e spazi più radi, come nelle folate vere. 0% = uniforme"), x => x / 100);
                    S(m, Icons.Move, SnowColor, L.T("Mosso"), "snow", "fallBlur", D("snow", "fallBlur", 0.4) * 100, 0, 100, false, "0", "%",
                      L.T("Come una foto con tempo di scatto lento: ogni fiocco è una scia lungo il suo movimento, più lunga se va veloce (vento, raffiche). 0% = fiocchi fermi e nitidi; 100% = 1/30 di secondo"), x => x / 100);
                    S(m, Icons.Expand, SnowColor, L.T("Dimensione dei fiocchi"), "snow", "fallSize", D("snow", "fallSize", 0.5) * 100, 0, 100, false, "0", "%",
                      L.T("Da granelli fini (0%) a grossi fiocchi bagnati (100%)"), x => x / 100);
                    S(m, Icons.Horizon, SnowColor, L.T("Fin dove arrivano"), "snow", "fallFar", D("snow", "fallFar", 60), 10, 300, true, "0", "m",
                      L.T("Fin dove arrivano i fiocchi davanti alla camera. Più lontano = più velo e più fiocchi da calcolare"));
                    var again = SmallButton(Icons.Refresh, L.T("Altra disposizione"), async () =>
                        await SetAmbience(new JsonObject { ["snow"] = new JsonObject { ["fallSeed"] = (int)(D("snow", "fallSeed", 1)) + 1 } }));
                    again.HorizontalAlignment = HorizontalAlignment.Left;
                    again.Margin = new Thickness(0, 2, 0, 0);
                    m.Children.Add(again);
                    if (_ambience["snowFlakes"] is JsonObject fm)
                        m.Children.Add(HintSmall(L.F("Adesso: {0} fiocchi, calcolati in {1} s", ((long?)fm["count"] ?? 0).ToString("N0"), ((double?)fm["secs"] ?? 0).ToString("0.0"))));
                }
                // (a line between the flakes and the snow on the ground)
                fc.Children.Add(new Border { Height = 1, Background = Theme.B(Theme.Line), Margin = new Thickness(0, 10, 0, 12) });
            }
            void RainDrops(StackPanel fc)
            {
                // the drops that fall (raindrops.py), first in the Avanzate of the rain: real drops in the frame of the
                // camera, the splashes where they hit, the surfaces wet as the rain is strong
                var head = Theme.IconText(Icons.Rain, L.T("Gocce che cadono"), RainColor, 14);
                ((TextBlock)head.Children[1]).FontWeight = FontWeights.SemiBold;
                head.Margin = new Thickness(0, 2, 0, 8);
                fc.Children.Add(head);
                var on = (bool?)G("rain")["drop"] ?? false;
                var t = new Toggle(L.T("Piove"), on,
                    L.T("Gocce vere nella scena, solo dove guarda la camera: non sotto tettoie e alberi, di notte brillano nella luce dei lampioni. Si ricalcolano quando la camera si ferma"));
                t.Toggled += async v => await SetAmbience(new JsonObject { ["rain"] = new JsonObject { ["drop"] = v } });
                fc.Children.Add(t);
                // the presets: everything below set together (falling drops, splashes, rings, drops on the surfaces)
                WeatherPresetGrid(fc, "rain", G("rain"), on);
                var m = ManualFold(fc, "rain");
                if (m == null)
                {
                    fc.Children.Add(new Border { Height = 1, Background = Theme.B(Theme.Line), Margin = new Thickness(0, 4, 0, 12) });
                    return;
                }
                if (on)
                {
                    S(m, Icons.Rain, RainColor, L.T("Intensità"), "rain", "dropAmount", D("rain", "dropAmount", 0.5) * 100, 1, 100, false, "0", "%",
                      L.T("Da una pioggerella a un acquazzone: quante gocce per metro cubo"), x => x / 100);
                    S(m, Icons.Wind, RainColor, L.T("Vento"), "rain", "dropWind", D("rain", "dropWind", 0.15) * 100, 0, 100, false, "0", "%",
                      L.T("Inclina la pioggia: 0% cade dritta, 100% molto obliqua (circa 50 km/h)"), x => x / 100);
                    S(m, Icons.Compass, RainColor, L.T("Direzione del vento"), "rain", "dropDir", D("rain", "dropDir", 0), 0, 360, false, "0", "°",
                      L.T("Verso dove soffia il vento: 0° = nord della scena (asse Y), 90° = est (asse X)"));
                    S(m, Icons.Haze, RainColor, L.T("Irregolarità"), "rain", "dropGust", D("rain", "dropGust", 0.3) * 100, 0, 100, false, "0", "%",
                      L.T("Raffiche: l'inclinazione cambia da un punto all'altro. 0% = tutte parallele"), x => x / 100);
                    S(m, Icons.Expand, RainColor, L.T("Dimensione delle gocce"), "rain", "dropSize", D("rain", "dropSize", 0.5) * 100, 0, 100, false, "0", "%",
                      L.T("Da gocce fini a gocce grosse, che cadono più veloci"), x => x / 100);
                    S(m, Icons.Eye, RainColor, L.T("Trasparenza delle gocce"), "rain", "dropClear", D("rain", "dropClear", 0.5) * 100, 0, 100, false, "0", "%",
                      L.T("Sempre acqua: 0% = acqua che diffonde la luce, scie più visibili · 100% = acqua limpida, si vede dove la luce la colpisce"), x => x / 100);
                    S(m, Icons.Move, RainColor, L.T("Mosso"), "rain", "dropBlur", D("rain", "dropBlur", 0.6) * 100, 0, 100, false, "0", "%",
                      L.T("Tempo di scatto: ogni goccia è una scia lungo la sua caduta. 0% = gocce ferme · 100% = 1/30 di secondo"), x => x / 100);
                    S(m, Icons.Horizon, RainColor, L.T("Fin dove arrivano"), "rain", "dropFar", D("rain", "dropFar", 40), 10, 300, true, "0", "m",
                      L.T("Fin dove arrivano le gocce davanti alla camera: più lontano = più velo e più gocce da calcolare"));
                    var wt = new Toggle(L.T("Bagna le superfici"), (bool?)G("rain")["dropWet"] ?? true,
                        L.T("Le superfici scoperte si bagnano quanto è forte la pioggia (almeno quanto dice «Bagnato»)"));
                    wt.Toggled += async v => await SetAmbience(new JsonObject { ["rain"] = new JsonObject { ["dropWet"] = v } });
                    wt.Margin = new Thickness(0, 6, 0, 0);
                    m.Children.Add(wt);
                    var spOn = (bool?)G("rain")["splash"] ?? true;
                    var st = new Toggle(L.T("Schizzi"), spOn,
                        L.T("Piccole corone d'acqua dove le gocce colpiscono le superfici piane, vicino alla camera"));
                    st.Toggled += async v => await SetAmbience(new JsonObject { ["rain"] = new JsonObject { ["splash"] = v } });
                    st.Margin = new Thickness(0, 6, 0, 0);
                    m.Children.Add(st);
                    S(m, Icons.Puddle, RainColor, L.T("Cerchi nelle pozzanghere"), "rain", "puddleRings", D("rain", "puddleRings", 0.5) * 100, 0, 100, false, "0", "%",
                      L.T("I cerchi delle gocce sull'acqua delle pozzanghere e del velo sul terreno. 0% = nessuno"), x => x / 100);
                    if (spOn)
                        S(m, Icons.Puddle, RainColor, L.T("Quantità di schizzi"), "rain", "splashAmount", D("rain", "splashAmount", 0.5) * 100, 0, 100, false, "0", "%",
                          L.T("Quanti schizzi per metro quadro; crescono anche con l'intensità"), x => x / 100);
                    var again = SmallButton(Icons.Refresh, L.T("Altra disposizione"), async () =>
                        await SetAmbience(new JsonObject { ["rain"] = new JsonObject { ["dropSeed"] = (int)(D("rain", "dropSeed", 1)) + 1 } }));
                    again.HorizontalAlignment = HorizontalAlignment.Left;
                    again.Margin = new Thickness(0, 6, 0, 0);
                    m.Children.Add(again);
                    if (_ambience["rainDrops"] is JsonObject dm)
                        m.Children.Add(HintSmall(L.F("Adesso: {0} gocce e {1} schizzi, calcolati in {2} s", ((long?)dm["count"] ?? 0).ToString("N0"),
                            ((long?)dm["splashes"] ?? 0).ToString("N0"), ((double?)dm["secs"] ?? 0).ToString("0.0"))));
                }
                m.Children.Add(new Border { Height = 1, Background = Theme.B(Theme.Line), Margin = new Thickness(0, 10, 0, 12) });
                SurfaceDrops(m);
            }
            void SurfaceDrops(StackPanel fc)
            {
                // the drops lying on the surfaces (rain._drops_nodes): beads on what is smooth, runs down the sides,
                // drops on glass, a thin layer of water - while the surfaces are wet
                var head = Theme.IconText(Icons.WaterDrop, L.T("Gocce sulle superfici"), RainColor, 14);
                ((TextBlock)head.Children[1]).FontWeight = FontWeights.SemiBold;
                head.Margin = new Thickness(0, 2, 0, 8);
                fc.Children.Add(head);
                var on = (bool?)G("rain")["beads"] ?? true;
                var t = new Toggle(L.T("Gocce posate"), on,
                    L.T("Goccioline d'acqua sulle superfici lisce bagnate (carrozzerie, vetri, metalli), rivoli sui lati; non sotto i ripari. Per materiale: Riflessi e vernice → Avanzate → Con la pioggia. Nel path tracing costano fino a circa metà del tempo in più sulle superfici con le gocce; spente non costano nulla"));
                t.Toggled += async v => await SetAmbience(new JsonObject { ["rain"] = new JsonObject { ["beads"] = v } });
                fc.Children.Add(t);
                if (on)
                {
                    S(fc, Icons.WaterDrop, RainColor, L.T("Quantità"), "rain", "beadAmount", D("rain", "beadAmount", 0.5) * 100, 1, 100, false, "0", "%",
                      L.T("Quante gocce: da poche sparse a una superficie fitta"), x => x / 100);
                    S(fc, Icons.Expand, RainColor, L.T("Dimensione"), "rain", "beadSize", D("rain", "beadSize", 0.5) * 100, 0, 100, false, "0", "%",
                      L.T("Le gocce più grandi: da circa 5 mm a 25 mm"), x => x / 100);
                    S(fc, Icons.Expand, RainColor, L.T("Gocce grandi"), "rain", "beadBig", D("rain", "beadBig", 0.3) * 100, 0, 100, false, "0", "%",
                      L.T("Quante gocce grandi tra quelle piccole"), x => x / 100);
                    S(fc, Icons.Move, RainColor, L.T("Rivoli sulle pareti"), "rain", "beadRivul", D("rain", "beadRivul", 0.4) * 100, 0, 100, false, "0", "%",
                      L.T("Scie d'acqua che scendono sui lati e sulle superfici inclinate"), x => x / 100);
                }
                S(fc, Icons.Eye, RainColor, L.T("Velo d'acqua"), "rain", "beadFilm", D("rain", "beadFilm", 0.5) * 100, 0, 100, false, "0", "%",
                  L.T("Un sottile strato d'acqua lucido sui materiali lisci che non assorbono (vernici, metalli, plastiche)"), x => x / 100);
                fc.Children.Add(new Border { Height = 1, Background = Theme.B(Theme.Line), Margin = new Thickness(0, 10, 0, 12) });
            }
            void SculptControls(StackPanel body)
            {
                // footprints, tyre tracks, snow dug or heaped: on the mantle of the ground and of the big models (the
                // grid seen from above), made finer where it is sculpted
                var on = _puddleBrush && _brushLayer == "sculpt";
                var tg = new Toggle(L.T("Scolpisci la neve"), on,
                    L.T("Passi, tracce di pneumatici, neve spalata o ammucchiata, sullo strato di neve del terreno e dei tetti: tieni premuto il tasto sinistro e trascina lungo il percorso. Dove passi Simpler rende il mantello più fine (circa 1,5 cm), il resto resta leggero. [ e ] cambiano la grandezza, Esc smette; ogni tratto si annulla con Ctrl+Z e resta nel progetto"));
                tg.Toggled += v => { _puddleBrush = v; _brushLayer = "sculpt"; SendPuddleBrush(); RenderProps(); };
                tg.Margin = new Thickness(0, 10, 0, 0);
                body.Children.Add(tg);
                if (on)
                {
                    var modes = new[] { "steps", "tyres", "dig", "raise", "smooth" };
                    var seg = Theme.Segmented(out var bt,
                        (L.T("Passi"), L.T("Impronte di scarpe, a destra e a sinistra lungo il percorso, con il bordo di neve spostata")),
                        (L.T("Pneumatici"), L.T("Due solchi con il battistrada, alla distanza delle ruote, con la neve spinta ai lati")),
                        (L.T("Scava"), L.T("Toglie neve dove passi, come con una pala: più passate scavano di più, fino al terreno. Per togliere anche il bianco dal terreno scoperto usa «Pennello neve» con «Togli»")),
                        (L.T("Solleva"), L.T("Ammucchia neve dove passi: più passate la alzano di più")),
                        (L.T("Liscia"), L.T("Ammorbidisce quello che hai scolpito")));
                    seg.HorizontalAlignment = HorizontalAlignment.Left;
                    seg.Margin = new Thickness(0, 6, 0, 4);
                    Theme.SetSegment(bt, Math.Max(0, Array.IndexOf(modes, _sculptMode)));
                    for (int i = 0; i < bt.Count; i++)
                    {
                        var idx = i;
                        bt[i].Click += (_, __) => { _sculptMode = modes[idx]; SendPuddleBrush(); RenderProps(); };
                    }
                    body.Children.Add(seg);
                    ValueSlider Sl(Geometry icon, string label, double v, double min, double max, string unit, string tip, Action<double> set)
                    {
                        var sl = new ValueSlider(label, v, min, max, false, "0", unit, null, tip).WithIcon(icon, SnowColor);
                        sl.Changing += x => { set(x); SendPuddleBrush(); };
                        sl.Committed += x => { set(x); SendPuddleBrush(); };
                        body.Children.Add(sl);
                        return sl;
                    }
                    if (_sculptMode == "steps")
                        Sl(Icons.Walk, L.T("Grandezza impronte"), _sculptSize * 100, 50, 200, "%", L.T("100% = scarpa di un adulto, passo di 66 cm"), x => _sculptSize = x / 100);
                    if (_sculptMode == "tyres")
                    {
                        Sl(Icons.Car, L.T("Carreggiata"), _sculptGauge * 100, 30, 400, "cm", L.T("La distanza tra le due ruote, da centro a centro: un'auto 150-160 cm, un furgone 170-180"), x => _sculptGauge = x / 100);
                        Sl(Icons.Expand, L.T("Larghezza pneumatici"), _sculptWidth * 100, 5, 100, "cm", L.T("Quanto è largo ogni solco"), x => _sculptWidth = x / 100);
                    }
                    if (_sculptMode is "dig" or "raise" or "smooth")
                        Sl(Icons.Brush, L.T("Grandezza pennello"), _sculptRadius * 100, 3, 500, "cm", L.T("Il raggio del pennello ([ e ] sulla vista)"), x => _sculptRadius = x / 100);
                    if (_sculptMode is "steps" or "tyres")
                        Sl(Icons.Expand, L.T("Profondità"), _sculptDepth * 100, 1, 50, "cm", L.T("Quanto affondano nella neve. Sotto resta sempre un velo di neve pressata, più grigia"), x => _sculptDepth = x / 100);
                    if (_sculptMode is "dig" or "raise")
                        Sl(Icons.Expand, L.T("Forza"), _sculptDepth * 100, 1, 50, "cm", L.T("Quanta neve toglie o aggiunge a ogni passata, al centro del pennello"), x => _sculptDepth = x / 100);
                }
                if ((bool?)_ambience["snowSculpted"] ?? false)
                {
                    var clr = SmallButton(Icons.Trash, L.T("Cancella la neve scolpita"), async () =>
                    {
                        await Run(async api => { await api.Post("rain/sculpt/clear", new JsonObject()); });
                        await LoadAmbience(); RenderProps();
                    });
                    clr.HorizontalAlignment = HorizontalAlignment.Left;
                    clr.Margin = new Thickness(0, 6, 0, 0);
                    body.Children.Add(clr);
                }
            }
            void Exposure()
            {
                var ex = Card(L.T("Esposizione"), Icons.Aperture, Theme.TextSoft);
                var auto = new Toggle(L.T("Esposizione automatica"), (bool?)G("exposure")["auto"] ?? true,
                    L.T("Come una macchina fotografica: di notte e al tramonto l'immagine resta leggibile. Si somma all'esposizione delle impostazioni di rendering"));
                auto.Toggled += async v => await SetAmbience(new JsonObject { ["exposure"] = new JsonObject { ["auto"] = v } });
                ex.Children.Add(auto);
                var ev = (double?)_ambience["ev"] ?? 0;
                ex.Children.Add(HintSmall(L.F("Correzione automatica ora: {0} EV", (ev >= 0 ? "+" : "") + ev.ToString("0.0"))));
            }

            if (mode == "hdri")
            {
                var hc = Card(L.T("HDRI"), Icons.Image, Theme.Accent);
                var name = (string?)G("hdri")["name"] ?? (string?)G("hdri")["id"] ?? "";
                hc.Children.Add(Theme.Label(name, 13, Theme.Text));
                var choose = SmallButton(Icons.Globe, L.T("Scegli un altro HDRI"), async () => { ShowLibraryTab("hdri"); await Task.CompletedTask; });
                choose.HorizontalAlignment = HorizontalAlignment.Left;
                choose.Margin = new Thickness(0, 6, 0, 8);
                hc.Children.Add(choose);
                S(hc, Icons.Rotate, Theme.Accent, L.T("Rotazione"), "hdri", "rotation", D("hdri", "rotation", 0), 0, 360, false, "0", "°", L.T("Gira il cielo fotografato attorno alla scena: il sole gira con lui"));
                S(hc, Icons.Light, Theme.Warm, L.T("Intensità"), "hdri", "strength", D("hdri", "strength", 1) * 100, 0, 500, false, "0", "%", L.T("Luce del cielo e del sole dell'HDRI; 100% = come fotografato"), x => x / 100);
                var hasSun = _ambience["sun"] is JsonObject;
                var useSun = (bool?)G("hdri")["sun"] ?? true;
                var ts = new Toggle(L.T("Sole dall'HDRI"), useSun, L.T("Il sole della fotografia diventa una luce Sole vera (stessa direzione, colore e forza): ombre nette e pulite subito, invece del rumore di un punto piccolissimo e luminosissimo. Gira con la rotazione"));
                ts.Toggled += async v => await SetAmbience(new JsonObject { ["hdri"] = new JsonObject { ["sun"] = v } });
                hc.Children.Add(ts);
                if (useSun && !hasSun)
                    hc.Children.Add(HintSmall(L.T("In questo HDRI non c'è un sole netto (cielo coperto o interno): la luce viene tutta dalla fotografia.")));
                else if (useSun && _ambience["sun"] is JsonObject so)
                    hc.Children.Add(HintSmall(L.F("Sole trovato: {0}° sopra l'orizzonte", ((double?)so["elev"] ?? 0).ToString("0"))));
                Rain();
                Snow();
                Ground();
                Exposure();
                return;
            }

            // ---- sun
            var sun = Card(L.T("Sole"), Icons.Light, Theme.Warm);
            // the dome: the sun dragged where it should shine from (1.68.0); hour and north follow
            ValueSlider? northSl = null;
            var dome = new SunDome(D("sun", "hour", 12), D("sun", "north", 0), D("sun", "day", 172), D("sun", "lat", 45.5), ViewYaw());
            _sunDome = dome;
            sun.Children.Add(dome);
            var hourSl = S(sun, Icons.Clock, Theme.Warm, L.T("Ora"), "sun", "hour", D("sun", "hour", 12), 0, 24, false, "0.##", "", L.T("Ora solare del luogo: il sole, il colore della luce e il cielo cambiano insieme"), null, DayTrack());
            // the time as HH:mm (12.5 -> 12:30), typed the same way (also 12.30 or 12,30), in steps of 5 minutes
            hourSl.Display = h => { var m = (int)Math.Round(h * 60); return $"{Math.Min(24, m / 60):00}:{m % 60:00}"; };
            hourSl.Parse = t =>
            {
                t = t.Trim().Replace('.', ':').Replace(',', ':');
                var parts = t.Split(':');
                if (!int.TryParse(parts[0], out var hh)) return null;
                int mm = parts.Length > 1 && int.TryParse(parts[1], out var x) ? x : 0;
                return Math.Clamp(hh + mm / 60.0, 0, 24);
            };
            hourSl.Step = 5 / 60.0;
            hourSl.Refresh();
            S(sun, Icons.Light, Theme.Warm, L.T("Intensità"), "sun", "intensity", D("sun", "intensity", 1) * 100, 0, 300, false, "0", "%", L.T("100% = sole vero per l'atmosfera scelta"), x => x / 100);
            // the place and the date of the Avanzate decide whether the sun sets at all (the presets keep them)
            if (((double?)_ambience["sunMin"] ?? -90) > -0.5 || ((double?)_ambience["sunMax"] ?? 90) < 0.5)
            {
                var never = ((double?)_ambience["sunMin"] ?? -90) > -0.5;
                var w = Theme.Label(never
                    ? L.F("A latitudine {0}° e in questo giorno il sole non tramonta mai (sole di mezzanotte): niente notte e le luci «dal tramonto all'alba» restano spente. Per la notte cambia Latitudine o Giorno dell'anno nelle Avanzate.", D("sun", "lat", 45.5).ToString("0.#"))
                    : L.F("A latitudine {0}° e in questo giorno il sole non sorge mai (notte polare). Per il giorno cambia Latitudine o Giorno dell'anno nelle Avanzate.", D("sun", "lat", 45.5).ToString("0.#")), 11.5, Theme.Warm);
                w.TextWrapping = TextWrapping.Wrap; w.Margin = new Thickness(0, 4, 0, 4);
                sun.Children.Add(w);
            }
            var sunA = Advanced(sun, "sun");
            S(sunA.Body, Icons.Calendar, Theme.Warm, L.T("Giorno dell'anno"), "sun", "day", D("sun", "day", 172), 1, 365, false, "0", "", L.T("1 = 1 gennaio, 172 = 21 giugno, 355 = 21 dicembre"), x => Math.Round(x), YearTrack());
            S(sunA.Body, Icons.Globe, Theme.Warm, L.T("Latitudine"), "sun", "lat", D("sun", "lat", 45.5), -89, 89, false, "0.#", "°", L.T("Milano 45,5 · Roma 41,9 · Londra 51,5 · New York 40,7"));
            northSl = S(sunA.Body, Icons.Compass, Theme.Warm, L.T("Nord"), "sun", "north", D("sun", "north", 0), 0, 360, false, "0", "°", L.T("Dove punta il nord nella scena (gira il sole attorno alla scena)"));
            hourSl.Changing += h => dome.SetSun(h, northSl.Value);
            northSl.Changing += n => dome.SetSun(hourSl.Value, n);
            {
                var sid = (string?)_ambience["sunId"] ?? "";
                double day = D("sun", "day", 172), lat = D("sun", "lat", 45.5);
                dome.Moving += (h, n) =>
                {
                    hourSl.SetValue(h, false);
                    northSl.SetValue(n, false);
                    // the real-time view follows at once (light, shadows, sun disc: no new shaders); sky and path
                    // tracing when let go, as with the sliders
                    if (sid != "")
                        SendToWeb(new { type = "lightPreview", id = sid, sun = new JsonObject { ["hour"] = h, ["day"] = day, ["lat"] = lat, ["north"] = n } });
                };
                dome.Moved += async (h, n) => await SetAmbience(new JsonObject { ["sun"] = new JsonObject { ["hour"] = h, ["north"] = n } });
            }
            S(sunA.Body, Icons.SunSize, Theme.Warm, L.T("Dimensione"), "sun", "size", D("sun", "size", 0.545), 0.1, 10, true, "0.##", "°", L.T("Diametro del sole: 0,5° = vero, ombre nette; più grande = ombre più morbide"));
            AdvDone(sunA, "sun");

            // ---- sky
            var skyc = Card(L.T("Cielo"), Icons.Horizon, Theme.Accent);
            S(skyc, Icons.Haze, Theme.Accent, L.T("Foschia"), "sky", "aerosol", D("sky", "aerosol", 1) * 100, 0, 1000, false, "0", "%", L.T("Polvere e umidità nell'aria: cielo più bianco, sole più caldo e morbido, tramonti accesi"), x => x / 100);
            S(skyc, Icons.Horizon, Theme.Accent, L.T("Luce del cielo"), "sky", "ambient", D("sky", "ambient", 1) * 100, 0, 300, false, "0", "%", L.T("Quanto illumina il cielo (le ombre più chiare o più scure); 100% = fisico"), x => x / 100);
            var skyA = Advanced(skyc, "sky");
            S(skyA.Body, Icons.Wind, Theme.Accent, L.T("Aria"), "sky", "air", D("sky", "air", 1) * 100, 0, 500, false, "0", "%", L.T("Densità dell'aria: meno = cielo blu scuro come in alta quota, più = cielo pallido e tramonti più rossi"), x => x / 100);
            S(skyA.Body, Icons.Ozone, Theme.Accent, L.T("Ozono"), "sky", "ozone", D("sky", "ozone", 1) * 100, 0, 500, false, "0", "%", L.T("Il blu profondo sopra la testa e il blu del crepuscolo"), x => x / 100);
            S(skyA.Body, Icons.Relief, Theme.Accent, L.T("Altitudine"), "sky", "altitude", D("sky", "altitude", 100), 0, 8000, false, "0", "m", L.T("Quota del luogo sul mare: più in alto il cielo è più scuro e il sole più bianco"));
            SkyPhotoSection(skyA.Body, st);
            AdvDone(skyA, "sky");

            // ---- clouds
            var cl = Card(L.T("Nuvole"), Icons.Cloud, Theme.TextSoft);
            bool volClouds = (bool?)G("clouds")["volumetric"] ?? false;
            var vc = new Toggle(L.T("Nuvole volumetriche"), volClouds, L.T("Nuvole vere in 3D nel path tracing (vista ray-traced e render finale): luce del sole che le attraversa, bordi argentati controsole, ombre sul suolo, rosa e arancio all'alba e al tramonto. Più lente delle nuvole dipinte sul cielo: per questo è un interruttore. La vista in tempo reale mostra le nuvole dipinte"));
            vc.Toggled += async v => await SetAmbience(new JsonObject { ["clouds"] = new JsonObject { ["volumetric"] = v } });
            vc.Margin = new Thickness(0, 0, 0, 8);
            cl.Children.Add(vc);
            if (volClouds)
            {
                var curT = (string?)G("clouds")["type"] ?? "cumuli_piccoli";
                var tw = new WrapPanel { Margin = new Thickness(0, 0, 0, 6) };
                foreach (var (id, name, tip) in new[]
                {
                    ("cumuli_piccoli", L.T("Cumuli piccoli"), L.T("Bel tempo: batuffoli bianchi sparsi")),
                    ("cumuli_grandi", L.T("Cumuli grandi"), L.T("Grandi nuvole a cavolfiore, alte e luminose")),
                    ("altocumuli", L.T("Altocumuli"), L.T("Tanti piccoli fiocchi in alto, a banchi")),
                    ("cumulonembo", L.T("Cumulonembo"), L.T("Torri temporalesche altissime e scure alla base")),
                    ("strati", L.T("Strati"), L.T("Uno strato basso e grigio, quasi uniforme")),
                    ("nembostrati", L.T("Nembostrati"), L.T("Cielo coperto, spesso e scuro: pioggia")),
                })
                {
                    var b = Theme.Button(name, id == curT ? Theme.Kind.Segment : Theme.Kind.Ghost, tip);
                    b.MinHeight = 28; b.FontSize = 12; b.Padding = new Thickness(10, 0, 10, 0); b.Margin = new Thickness(0, 0, 6, 6);
                    var tid = id;
                    b.Click += async (_, __) => await SetAmbience(new JsonObject { ["clouds"] = new JsonObject { ["type"] = tid } });
                    tw.Children.Add(b);
                }
                cl.Children.Add(tw);
            }
            S(cl, Icons.Cloud, Theme.TextSoft, L.T("Copertura"), "clouds", "cover", D("clouds", "cover", 0.2) * 100, 0, 100, false, "0", "%", volClouds ? L.T("Da cielo sereno a coperto") : L.T("Da cielo sereno a coperto: più nuvole = sole più debole e ombre più morbide"), x => x / 100);
            S(cl, Icons.Expand, Theme.TextSoft, L.T("Grandezza"), "clouds", "scale", D("clouds", "scale", 0.5) * 100, 0, 100, false, "0", "%", L.T("Tante nuvole piccole o grandi banchi"), x => x / 100);
            if (!volClouds)
                S(cl, Icons.Soft, Theme.TextSoft, L.T("Morbidezza"), "clouds", "soft", D("clouds", "soft", 0.5) * 100, 0, 100, false, "0", "%", L.T("Bordi netti o sfumati"), x => x / 100);
            S(cl, Icons.Wind, Theme.TextSoft, L.T("Cirri"), "clouds", "cirrus", D("clouds", "cirrus", 0) * 100, 0, 100, false, "0", "%", L.T("Strisce sottili altissime (8–10 km), stirate dal vento: le ultime nuvole a restare rosa e arancio dopo il tramonto. Leggere, anche nella vista in tempo reale"), x => x / 100);
            if (volClouds)
            {
                // a second, higher layer (a switch: it costs time - the clouds are already most of the render)
                bool layer2 = (bool?)G("clouds")["layer2"] ?? false;
                var l2 = new Toggle(L.T("Secondo strato di nuvole"), layer2,
                    L.T("Un velo di nuvole più alto e leggero sopra il primo, come nei cieli coperti veri: masse scure sotto, strato chiaro e rotto sopra, squarci di luce tra i due"));
                l2.Toggled += async v => await SetAmbience(new JsonObject { ["clouds"] = new JsonObject { ["layer2"] = v } });
                l2.Margin = new Thickness(0, 6, 0, 0);
                cl.Children.Add(l2);
                if (layer2)
                {
                    var warn = Theme.Label(L.T("Due strati di nuvole volumetriche: la vista ray-traced e il render finale possono richiedere fino al doppio del tempo."), 11.5, Theme.Warm);
                    warn.TextWrapping = TextWrapping.Wrap;
                    warn.Margin = new Thickness(0, 2, 0, 6);
                    cl.Children.Add(warn);
                    S(cl, Icons.Cloud, Theme.TextSoft, L.T("Copertura strato alto"), "clouds", "layer2Cover", D("clouds", "layer2Cover", 0.5) * 100, 0, 100, false, "0", "%",
                      L.T("Quanto del cielo copre il velo più alto"), x => x / 100);
                }
            }
            var seedRow = new DockPanel { Margin = new Thickness(0, 4, 0, 0) };
            var dice = SmallButton(Icons.Refresh, L.T("Altre nuvole"), async () =>
                await SetAmbience(new JsonObject { ["clouds"] = new JsonObject { ["seed"] = Random.Shared.Next(1, 100000) } }));
            dice.ToolTip = L.T("Stesse regolazioni, nuvole disposte diversamente");
            dice.HorizontalAlignment = HorizontalAlignment.Left;
            seedRow.Children.Add(dice);
            cl.Children.Add(seedRow);
            if (volClouds)
            {
                var clA = Advanced(cl, "clouds");
                S(clA.Body, Icons.Relief, Theme.TextSoft, L.T("Altezza"), "clouds", "height", D("clouds", "height", 1200), 250, 4000, false, "0", "m", L.T("Quota della base delle nuvole sopra il suolo della scena"));
                S(clA.Body, Icons.Scale, Theme.TextSoft, L.T("Spessore"), "clouds", "thickness", D("clouds", "thickness", 700), 100, 6000, true, "0", "m", L.T("Dalla base alla cima: poche centinaia di metri per i cumuli piccoli, chilometri per i temporali"));
                S(clA.Body, Icons.Horizon, Theme.TextSoft, L.T("Base piatta"), "clouds", "flat", D("clouds", "flat", 0.75) * 100, 0, 100, false, "0", "%", L.T("La base dritta dei cumuli (alta) o nuvole tonde e sfumate anche sotto (bassa)"), x => x / 100);
                S(clA.Body, Icons.Soft, Theme.TextSoft, L.T("Sbuffi"), "clouds", "puff", D("clouds", "puff", 0.7) * 100, 0, 100, false, "0", "%", L.T("Bordi a cavolfiore (alto) o lisci e compatti (basso)"), x => x / 100);
                S(clA.Body, Icons.Haze, Theme.TextSoft, L.T("Densità"), "clouds", "density", D("clouds", "density", 0.45) * 100, 0, 100, false, "0", "%", L.T("Nuvole leggere e luminose o spesse e scure al centro"), x => x / 100);
                var shadows = new Toggle(L.T("Ombre delle nuvole"), (bool?)G("clouds")["shadows"] ?? true, L.T("Le nuvole fanno ombra sul suolo e sulla scena quando passano davanti al sole. Spento: sole pieno sotto un cielo nuvoloso"));
                shadows.Toggled += async v => await SetAmbience(new JsonObject { ["clouds"] = new JsonObject { ["shadows"] = v } });
                shadows.Margin = new Thickness(0, 6, 0, 0);
                clA.Body.Children.Add(shadows);
                AdvDone(clA, "clouds");
            }
            if (volClouds)
                cl.Children.Add(HintSmall(L.T("Le nuvole 3D si vedono nella vista ray-traced e nel render finale e rallentano un po' il calcolo; la vista in tempo reale mostra quelle dipinte.")));

            // ---- haze / fog
            var fog = Card(L.T("Foschia e nebbia"), Icons.Fog, Theme.Teal);
            var dens = D("fog", "density", 0.15);
            S(fog, Icons.Haze, Theme.Teal, L.T("Densità"), "fog", "density", dens * 100, 0, 100, false, "0", "%", L.T("Le cose lontane si perdono nell'aria: poca = profondità naturale, tanta = nebbia"), x => x / 100);
            // (1.79.2, Luca 15/11: «densità 0» and «260 m» together while the engine works) the visibility from the density shown,
            // with the engine's formula (ambience.fog_visibility, nothing under 0.5%), not the one of the engine's last answer
            var vis = (string?)st["mode"] == "hdri" || dens < 0.005 ? 0 : 40000.0 * Math.Pow(30.0 / 40000.0, dens);
            fog.Children.Add(HintSmall(vis > 0 ? L.F("Visibilità circa {0}", vis >= 1000 ? (vis / 1000).ToString("0.#") + " km" : Math.Round(vis) + " m") : L.T("Aria limpidissima")));
            // (1.75.49) presets of the fog alone (they leave the sky, the sun and the clouds as they are)
            var fp = new WrapPanel { Margin = new Thickness(0, 0, 0, 8) };
            foreach (var (name, tip, set) in FogPresets())
            {
                var b = Theme.Button(name, Theme.Kind.Ghost, tip);
                b.MinHeight = 26; b.FontSize = 11.5; b.Padding = new Thickness(8, 0, 8, 0); b.Margin = new Thickness(0, 0, 4, 4);
                var data = set;
                b.Click += async (_, __) => await SetAmbience(new JsonObject { ["fog"] = data.DeepClone() });
                fp.Children.Add(b);
            }
            fog.Children.Add(fp);
            // low fog: dense near the ground, thinning out upwards
            bool low = (bool?)G("fog")["low"] ?? false;
            var lowT = new Toggle(L.T("Nebbia bassa"), low, L.T("La nebbia è fitta vicino al suolo e si dirada salendo: la nebbia del mattino sulla campagna, la città immersa. Spento: la stessa a ogni altezza"));
            lowT.Toggled += async v => await SetAmbience(new JsonObject { ["fog"] = new JsonObject { ["low"] = v } });
            fog.Children.Add(lowT);
            if (low)
            {
                S(fog, Icons.Horizon, Theme.Teal, L.T("Altezza"), "fog", "height", D("fog", "height", 10), 0, 200, false, "0.#", "m", L.T("Fin dove la nebbia è fitta, in metri dal suolo (quota 0)"));
                S(fog, Icons.Fog, Theme.Teal, L.T("Sfumatura"), "fog", "falloff", D("fog", "falloff", 20), 0.5, 300, true, "0.#", "m", L.T("Quanti metri sopra l'altezza la nebbia impiega a diradarsi: poco = un banco netto, tanto = un passaggio morbido"));
                // (1.75.50) the second layer: a thin haze everywhere, above the low fog
                S(fog, Icons.Haze, Theme.Teal, L.T("Foschia sopra"), "fog", "haze2", D("fog", "haze2", 0) * 100, 0, 100, false, "0", "%", L.T("Una foschia leggera in tutta l'aria, sopra lo strato basso: le cose lontane si velano anche in alto, come in una mattina umida"), x => x / 100);
            }
            // colour: automatic (from the sky and the sun) or chosen (a tint at the same brightness)
            bool tint = (bool?)G("fog")["tint"] ?? false;
            var tintT = new Toggle(L.T("Colore scelto"), tint, L.T("Spento: il colore viene dal cielo e dal sole (bianco-azzurro di giorno, caldo al tramonto). Acceso: la nebbia prende il colore che scegli, con la stessa luminosità"));
            tintT.Toggled += async v => await SetAmbience(new JsonObject { ["fog"] = new JsonObject { ["tint"] = v } });
            fog.Children.Add(tintT);
            if (tint)
            {
                var srgb = (G("fog")["color"] as JsonArray)?.Select(x => (double?)x ?? 0.8).ToArray() ?? new[] { 0.80, 0.84, 0.90 };
                var cf = new ColorField(L.T("Colore"), srgb.Select(ColorField.ToLinear).ToArray(), L.T("Azzurrino per l'umidità, caldo per la polvere e lo smog, grigio-blu di notte"));
                cf.Committed += async c => await SetAmbience(new JsonObject { ["fog"] = new JsonObject { ["color"] = new JsonArray(c.Select(x => (JsonNode)JsonValue.Create(Math.Round(ColorField.ToSrgb(x), 4))!).ToArray()) } });
                fog.Children.Add(cf);
            }
            bool volFog = (bool?)G("fog")["volumetric"] ?? false;
            var vf = new Toggle(L.T("Nebbia volumetrica (raggi di luce)"), volFog, L.T("La nebbia diventa vera nella scena: raggi di sole tra alberi e finestre, alone attorno alle lampade, anche nel path tracing della vista. Molto più lenta della foschia normale (e con più rumore): per questo è un interruttore. Si vede bene con densità alta (visibilità sotto qualche centinaio di metri)"));
            vf.Toggled += async v => await SetAmbience(new JsonObject { ["fog"] = new JsonObject { ["volumetric"] = v } });
            var fogA = Advanced(fog, "fog");
            S(fogA.Body, Icons.Expand, Theme.TextSoft, L.T("Distanza d'inizio"), "fog", "start", D("fog", "start", 0), 0, 500, false, "0", "m", L.T("Le cose vicine restano nitide: la nebbia comincia a questa distanza dalla camera"));
            fogA.Body.Children.Add(vf);
            if (volFog)
            {
                // (1.75.50) only in the volumetric fog: patches, their size, the glow towards the lights
                S(fogA.Body, Icons.Cloud, Theme.TextSoft, L.T("Irregolarità"), "fog", "noise", D("fog", "noise", 0) * 100, 0, 100, false, "0", "%", L.T("Banchi, chiazze e sbuffi invece di un velo uniforme; con la nebbia bassa anche il bordo superiore ondeggia"), x => x / 100);
                S(fogA.Body, Icons.Expand, Theme.TextSoft, L.T("Grandezza delle chiazze"), "fog", "noiseScale", D("fog", "noiseScale", 25), 2, 200, true, "0", "m", L.T("Quanto sono grandi i banchi e le chiazze di nebbia"));
                S(fogA.Body, Icons.Light, Theme.Warm, L.T("Bagliore verso le luci"), "fog", "glow", D("fog", "glow", 0.6) * 100, 0, 100, false, "0", "%", L.T("Basso: la luce si diffonde uguale in ogni direzione (polvere, raggi ben visibili di lato). Alto: goccioline d'acqua vere, alone luminoso verso il sole e attorno alle lampade"), x => x / 100);
                fogA.Body.Children.Add(HintSmall(L.T("Irregolarità e bagliore si vedono nel path tracing e nel render finale; la vista in tempo reale mostra la nebbia uniforme.")));
            }
            if (volFog && vis > 400)
                fogA.Body.Children.Add(HintSmall(L.T("Con questa densità la nebbia è troppo leggera per vedere i raggi: alza la densità.")));
            AdvDone(fogA, "fog");

            // ---- rain and snow
            Rain();
            Snow();

            // ---- night
            var night = Card(L.T("Notte"), Icons.Moon, NightColor);
            S(night, Icons.Star, NightColor, L.T("Stelle"), "night", "stars", D("night", "stars", 0.1) * 100, 0, 300, false, "0", "%", L.T("Il cielo vero (NASA): le stelle dove sarebbero a quell'ora, in quel luogo e in quel giorno, con la Via Lattea. Si vedono quando il sole è sotto l'orizzonte"), x => x / 100);
            S(night, Icons.Moon, NightColor, L.T("Luce della luna"), "night", "moon", D("night", "moon", 1) * 100, 0, 300, false, "0", "%", L.T("La luce fredda e debole che la luna dà alla scena (segue anche la fase: un quarto illumina circa un decimo della luna piena)"), x => x / 100);
            var phase = D("night", "phase", 0.5);
            S(night, Icons.Moon, NightColor, L.T("Fase"), "night", "phase", phase * 100, 0, 100, false, "0", "%", L.T("0 = luna nuova · 25 = primo quarto · 50 = luna piena · 75 = ultimo quarto"), x => x / 100);
            night.Children.Add(HintSmall(MoonPhaseName(phase)));
            S(night, Icons.Expand, NightColor, L.T("Dimensione della luna"), "night", "moonSize", D("night", "moonSize", 4), 0.5, 8, false, "0.#", "×", L.T("1 = la misura vera nel cielo (mezzo grado): più grande per un effetto da cinema. La luce sulla scena non cambia"));
            var nst = _ambience["night"] as JsonObject;
            var dl = (string?)nst?["download"] ?? "";
            if (dl == "running")
            {
                var fr = (double?)nst?["fraction"];
                night.Children.Add(HintSmall(L.T("Sto scaricando le stelle e la luna della NASA (circa 35 MB, una volta sola)…") + (fr != null ? " " + Math.Round(fr.Value * 100) + "%" : "")));
                _ = PollNightDownload();
            }
            else if (dl == "error")
            {
                night.Children.Add(HintSmall(L.T("Non riesco a scaricare le stelle e la luna: ") + ((string?)nst?["error"] ?? "")));
                var retry = SmallButton(Icons.Refresh, L.T("Riprova"), async () => { await Run(async api => { await api.Post("ambience/refresh", new JsonObject()); }); await LoadAmbience(); await RefreshScene(); RenderProps(); });
                retry.HorizontalAlignment = HorizontalAlignment.Left;
                night.Children.Add(retry);
            }
            var nightA = Advanced(night, "night");
            S(nightA.Body, Icons.Light, NightColor, L.T("Luminosità del disco"), "night", "disc", D("night", "disc", 0.6) * 100, 0, 300, false, "0", "%", L.T("Quanto brilla il disco della luna nel cielo (non la luce sulla scena)"), x => x / 100);
            S(nightA.Body, Icons.Soft, NightColor, L.T("Alone"), "night", "halo", D("night", "halo", 0.6) * 100, 0, 300, false, "0", "%", L.T("Il bagliore attorno alla luna, come attraverso l'aria"), x => x / 100);
            bool auto = (bool?)G("night")["moonAuto"] ?? true;
            var at = new Toggle(L.T("Posizione automatica"), auto, L.T("La luna sta dalla parte opposta del sole, abbastanza alta. Spegnila per metterla dove vuoi nell'inquadratura"));
            at.Toggled += async v => await SetAmbience(new JsonObject { ["night"] = new JsonObject { ["moonAuto"] = v } });
            nightA.Body.Children.Add(at);
            if (!auto)
            {
                S(nightA.Body, Icons.Horizon, NightColor, L.T("Altezza"), "night", "moonElev", D("night", "moonElev", 35), -5, 89, false, "0.#", "°", L.T("Quanto è alta sull'orizzonte"));
                S(nightA.Body, Icons.Compass, NightColor, L.T("Direzione"), "night", "moonAz", D("night", "moonAz", 135), 0, 360, false, "0.#", "°", L.T("Da dove si vede: 0° nord, 90° est, 180° sud, 270° ovest (il nord è quello del sole)"));
            }
            AdvDone(nightA, "night");

            // ---- ground
            Ground();
            Exposure();
        }

        /// <summary>(1.75.49) The fog presets: only the fog (density, low fog, colour), the rest of the ambience stays.</summary>
        static System.Collections.Generic.IEnumerable<(string name, string tip, JsonObject set)> FogPresets()
        {
            JsonObject F(double d, bool low, double h, double fall, bool tint, double[]? col = null)
            {
                var o = new JsonObject { ["density"] = d, ["low"] = low, ["height"] = h, ["falloff"] = fall, ["tint"] = tint };
                if (col != null) o["color"] = new JsonArray(col.Select(x => (JsonNode)JsonValue.Create(x)!).ToArray());
                return o;
            }
            yield return (L.T("Nessuna"), L.T("Aria limpidissima"), F(0.0, false, 10, 20, false));
            yield return (L.T("Foschia leggera"), L.T("Le cose lontane si velano appena: profondità naturale"), F(0.2, false, 10, 20, false));
            yield return (L.T("Nebbia bassa"), L.T("Nebbia del mattino che resta vicino al suolo"), F(0.7, true, 3, 6, false));
            yield return (L.T("Banco di nebbia"), L.T("Una nebbia fitta fino a qualche decina di metri: gli edifici emergono"), F(0.85, true, 15, 25, false));
            yield return (L.T("Polvere calda"), L.T("Aria calda e polverosa o smog, color sabbia"), F(0.45, true, 60, 120, true, new[] { 0.85, 0.72, 0.55 }));
            yield return (L.T("Notte nebbiosa"), L.T("Nebbia grigio-blu per le scene di notte"), F(0.55, true, 8, 20, true, new[] { 0.62, 0.68, 0.80 }));
        }
    }
}
