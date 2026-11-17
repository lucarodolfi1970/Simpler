using System.Collections.Generic;
using System;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;

namespace Simpler
{
    /// <summary>Properties panel (right) and material/environment library (bottom).</summary>
    public sealed partial class MainWindow
    {
        bool _propsWaiting;           // (1.79.0) a panel to make again once the slider in the hand is let go
        bool _propsHooked;

        /// <summary>force: the user asked for another panel (a click on its button): never held back.</summary>
        void RenderProps(bool force = false)
        {
            // (1.79.0, Luca: «sposto lo slider sotto e quello sopra cambia e torna a un valore precedente») never under
            // the mouse: a slider held, or a number being typed in a box - made when it is let go (ValueSlider)
            if (!force && ValueSlider.Interacting)
            {
                _propsWaiting = true;
                if (!_propsHooked) { _propsHooked = true; ValueSlider.InteractionEnded += PropsAfterInteraction; }
                return;
            }
            _propsWaiting = false;
            RenderPropsCore();
            EcoEditBar();            // (an ecosystem being changed on the bench: its saves in sight, whatever the panel)
            EcoSaveBar();            // (1.79.0: the scatters selected saved as an ecosystem from where they are)
            MakeFavorites();         // (1.76.32: the hearts and the filter, before the accordions take the rows)
            MakeAccordions();
        }

        async void PropsAfterInteraction()
        {
            if (!_propsWaiting) return;
            // what the slider just sent comes back first (its own panel refresh): only then, if still needed
            for (int i = 0; i < 600 && _engineCalls > 0; i++) await Task.Delay(50);
            if (_propsWaiting && !ValueSlider.Interacting) RenderProps();
        }

        void RenderPropsCore()
        {
            _props.Children.Clear();
            _propsTop.Children.Clear();
            _propsTop.Visibility = Visibility.Collapsed;
            if (_rightPanel == "ai") { RenderAiPanel(); return; }
            if (_rightPanel == "video") { RenderVideoPanel(); return; }
            if (_rightPanel == "paint") { RenderPaintPanel(); return; }
            if (_rightPanel == "ecosystem") { RenderEcosystemPanel(); return; }
            if (_rightPanel == "render") { RenderRenderPanel(); return; }
            if (_rightPanel == "camera") { RenderCameraPanel(); return; }
            if (_rightPanel == "ambience") { RenderAmbiencePanel(); return; }
            if (_rightPanel == "landscape") { RenderLandscapePanel(); return; }
            if (_rightPanel == "notes") { RenderNotesPanel(); return; }
            if (_rightPanel == "settings") { RenderSettingsPanel(); return; }
            if (_rightPanel == "resources") { RenderResourcesPanel(); return; }
            if (_rightPanel == "material") { RenderMaterialPanel(); return; }
            if (_rightPanel == "materials") { RenderSceneMaterialsPanel(); return; }
            if (_selected == "" || !_scene.ById.TryGetValue(_selected, out var o))
            {
                var empty = new StackPanel { Margin = new Thickness(16) };
                empty.Children.Add(Theme.Caption(L.T("Proprietà")));
                var t = Theme.Label(L.T("Seleziona un oggetto nell'albero o cliccandolo nella vista."), 13, Theme.TextFaint);
                t.TextWrapping = TextWrapping.Wrap;
                t.Margin = new Thickness(0, 10, 0, 0);
                empty.Children.Add(t);
                empty.Children.Add(Shortcuts());
                empty.Children.Add(FavPresetsList());      // (1.76.32: the presets of the favourite commands)
                _props.Children.Add(empty);
                return;
            }

            if (_selection.Count > 1) { RenderMultiProps(); return; }

            // header: name + type
            var head = new StackPanel();
            head.Children.Add(Theme.Caption(L.T("Proprietà")));
            var name = Theme.Input(o.Name);
            name.FontSize = 15;
            name.Margin = new Thickness(0, 8, 0, 4);
            async Task CommitName()
            {
                if (name.Text.Trim() == o.Name || name.Text.Trim() == "") return;
                await Run(async api => { await api.Post("rename", new { id = o.Id, name = name.Text.Trim() }); });
                await RefreshScene();
            }
            name.KeyDown += async (_, e) => { if (e.Key == Key.Enter) await CommitName(); };
            name.LostFocus += async (_, __) => await CommitName();
            head.Children.Add(name);
            var sub = o.KindLabel + (o.Source != "" && o.Kind == "file" ? " · " + System.IO.Path.GetFileName(o.Source) : "");
            head.Children.Add(Theme.Label(sub, 12, Theme.TextFaint));
            var actions = new WrapPanel { Margin = new Thickness(0, 10, 0, 0) };
            actions.Children.Add(SmallButton(Icons.Frame, L.T("Inquadra"), async () => await FrameSelection()));
            actions.Children.Add(SmallButton(Icons.Copy, L.T("Duplica"), async () => await DuplicateSelected()));
            actions.Children.Add(SmallButton(Icons.Trash, L.T("Elimina"), async () => await DeleteSelected()));
            if (o.IsMesh || o.Kind == "group" || o.Kind == "file")
            {
                var fix = SmallButton(Icons.Refresh, L.T("Correggi normali"), async () =>
                {
                    JsonObject? r = null;
                    await Run(async api => { r = await api.Post("normals", new JsonObject { ["ids"] = new JsonArray(_selection.Select(x => (JsonNode)x!).ToArray()) }); });
                    var n = (int?)r?["flipped"] ?? 0;
                    Status(n > 0 ? L.F("{0} facce girate verso l'esterno", n) : L.T("Tutte le facce erano già girate verso l'esterno"));
                    await RefreshScene();
                });
                fix.ToolTip = L.T("Gira verso l'esterno le facce rivolte all'interno: nel path tracing sono le facce nere o strane dietro vetri, tessuti, foglie. (Nella vista in tempo reale ogni faccia si vede già dai due lati.) Si annulla con Ctrl+Z");
                actions.Children.Add(fix);
            }
            head.Children.Add(actions);
            _props.Children.Add(Theme.Card(head, 16));

            // transform
            var tr = new StackPanel();
            tr.Children.Add(SectionTitle(L.T("Trasformazione")));
            tr.Children.Add(VectorRow(L.T("Posizione cm"), o.Location, "location", o.Id, 2));
            tr.Children.Add(VectorRow(L.T("Rotazione °"), o.Rotation, "rotation", o.Id, 1));
            tr.Children.Add(VectorRow(L.T("Scala"), o.Scale, "scale", o.Id, 3));
            if (o.IsMesh || o.Kind == "group" || o.Kind == "file") tr.Children.Add(SizeRow(o.Id));
            if (o.HasPivot)
            {
                var pr = new DockPanel { Margin = new Thickness(0, 4, 0, 0) };
                var reset = SmallButton(Icons.Undo, L.T("Pivot automatico"), async () => await SavePivot(o.Id, null));
                reset.ToolTip = L.T("Il gizmo torna dove dicono Centro, Base o Origine");
                DockPanel.SetDock(reset, Dock.Right);
                pr.Children.Add(reset);
                pr.Children.Add(Theme.Label(L.T("Pivot spostato a mano"), 12, Theme.TextMuted));
                tr.Children.Add(pr);
            }
            _props.Children.Add(Theme.Card(tr, 16));

            if (o.IsLight) _props.Children.Add(Theme.Card(LightSection(o), 16));
            if (o.Kind == "decal") _props.Children.Add(Theme.Card(DecalSection(o), 16));
            if (o.IsMesh || o.Kind == "group" || o.Kind == "file") _props.Children.Add(Theme.Card(MaterialSection(o), 16));
            if ((o.IsMesh || o.Kind == "group" || o.Kind == "file") && !o.Paint && o.PaintModel == "")
            {
                var sc = new StackPanel();
                sc.Children.Add(SectionTitle(L.T("Distribuisci")));
                var ex = new Toggle(L.T("Escludi da Area e Spaziatura"), o.NoScatter, L.T("Acceso: Area e Spaziatura non mettono niente su questo oggetto (e su quello che contiene): gli oggetti cadono sulla superficie sotto di esso"));
                ex.Toggled += async v =>
                {
                    await Run(async api => { await api.Post("noscatter", new JsonObject { ["ids"] = new JsonArray(_selection.Select(x => (JsonNode)x!).ToArray()), ["value"] = v }); });
                    await RefreshScene();
                    if (Painting && _paint.Mode != "brush") SendToWeb(new { type = "areaUpdate" });
                };
                sc.Children.Add(ex);
                _props.Children.Add(Theme.Card(sc, 16));
            }
            if (o.IsMesh || o.Kind == "group" || o.Kind == "file") WeatherCard(new List<SceneObject> { o });
        }

        /// <summary>«Pioggia e neve» of the selected objects (one or many): three states per switch - on for all, off for
        /// all, «multi» when they differ; a click sets it for all of them. These are values of the model: saved with
        /// it in the library and valid wherever it is used.</summary>
        void WeatherCard(List<SceneObject> objs)
        {
            if (objs.Count == 0) return;
            bool? Tri(Func<SceneObject, bool> f) { var n = objs.Count(f); return n == objs.Count ? true : n == 0 ? false : null; }
            var ids = new JsonArray(objs.Select(x => (JsonNode)x.Id!).ToArray());
            async Task Post(string path, JsonNode value, string? kind = null)
            {
                var body = new JsonObject { ["ids"] = ids.DeepClone(), ["value"] = value };
                if (kind != null) body["kind"] = kind;
                await Run(async api => { await api.Post(path, body); });
                await RefreshScene();
            }
            var rc = new StackPanel();
            rc.Children.Add(SectionTitle(L.T("Pioggia e neve")));
            var ra = Advanced(rc, "objrain");
            // «Sempre asciutto», separately for the rain and for the snow: a car can take the drops when it rains and
            // keep its glass free of snow when it snows
            var dry = new Toggle(L.T("Niente pioggia"), Tri(x => x.Dry), L.T("La pioggia non bagna questo oggetto (e quello che contiene): niente bagnato, pozzanghere e gocce, anche all'aperto. Per gli interni o per quello che deve restare com'è. Copre comunque quello che c'è sotto"));
            dry.Toggled += async v => await Post("rain/dry", v, "rain");
            ra.Body.Children.Add(dry);
            var nosnow = new Toggle(L.T("Niente neve"), Tri(x => x.NoSnow), L.T("Niente neve su questo oggetto (e su quello che contiene): né il bianco né il mantello, anche all'aperto. Per esempio i vetri e le parti di un'auto dove il mantello non sta bene. Copre comunque quello che c'è sotto"));
            nosnow.Toggled += async v => await Post("rain/dry", v, "snow");
            ra.Body.Children.Add(nosnow);
            var openS = Tri(x => x.NoShelter);
            var open = new Toggle(L.T("Non fa riparo"), openS, L.T("Quello che c'è sotto prende la pioggia come se l'oggetto non ci fosse: per le auto in movimento, che non asciugano la strada. Lascialo spento per un'auto parcheggiata da prima della pioggia, che sotto ha l'asfalto asciutto. L'oggetto stesso si bagna normalmente") + " " + L.T("Vale anche per la neve."));
            open.Toggled += async v => await Post("rain/noshelter", v);
            ra.Body.Children.Add(open);
            var nmS = Tri(x => x.NoMantle);
            var nm = new Toggle(L.T("Senza mantello"), nmS, L.T("Niente strato di neve con spessore su questo oggetto (e su quello che contiene): resta solo il bianco sulla superficie. Per gli oggetti dove il mantello non sta bene, come una pianta o un oggetto sottile"));
            nm.Toggled += async v => await Post("rain/nomantle", v);
            ra.Body.Children.Add(nm);
            // how the mantle is made (snow.py): on the shape (finer or as Simpler decides) or from above (lighter)
            if (nmS != true)
            {
                var detIds = new[] { "auto", "high", "low" };
                var seg = Theme.Segmented(out var segButtons,
                    (L.T("Auto"), L.T("Simpler decide: sulla forma per i modelli fino a 12 m (rocce, auto, panchine...), dall'alto per quelli più grandi, con il dettaglio in base alla grandezza")),
                    (L.T("Alto"), L.T("Mantello sulla forma del modello, più fine: per quello che si vede da vicino. Più pesante")),
                    (L.T("Basso"), L.T("Mantello dall'alto, come il terreno: leggero, adatto a superfici grandi e piatte o a modelli lontani")));
                seg.HorizontalAlignment = HorizontalAlignment.Left;
                seg.Margin = new Thickness(0, 6, 0, 2);
                var details = objs.Select(x => x.SnowDetail).Distinct().ToList();
                if (details.Count == 1) Theme.SetSegment(segButtons, Math.Max(0, Array.IndexOf(detIds, details[0])));
                else Theme.SetSegment(segButtons, -1);
                for (int i = 0; i < segButtons.Count; i++)
                {
                    var v = detIds[i];
                    segButtons[i].Click += async (_, __) => await Post("rain/snowdetail", v);
                }
                var lab = new DockPanel();
                if (details.Count > 1)
                {
                    var mt = Theme.Label(L.T("multi"), 10, Theme.Warm);
                    DockPanel.SetDock(mt, Dock.Right);
                    lab.Children.Add(mt);
                }
                lab.Children.Add(Theme.Label(L.T("Dettaglio neve"), 12, Theme.TextSoft));
                ra.Body.Children.Add(lab);
                ra.Body.Children.Add(seg);
            }
            var note = Theme.Label(L.T("Sono valori del modello: salvandolo in libreria restano con lui e valgono ovunque lo usi."), 11, Theme.TextFaint);
            note.TextWrapping = TextWrapping.Wrap;
            note.Margin = new Thickness(0, 8, 0, 0);
            ra.Body.Children.Add(note);
            ra.Done(objs.Any(x => x.Dry || x.NoSnow) || openS != false || nmS != false || objs.Any(x => x.SnowDetail != "auto"), null);
            _props.Children.Add(Theme.Card(rc, 16));
        }

        UIElement Shortcuts()
        {
            var sp = new StackPanel { Margin = new Thickness(0, 24, 0, 0) };
            sp.Children.Add(Theme.Caption(L.T("Comandi rapidi")));
            foreach (var (k, d) in new[] {
                (L.T("Clic"), "seleziona"), (L.T("Tasto destro + trascina"), L.T("ruota la vista")), (L.T("Rotella / centrale"), L.T("zoom / sposta la vista")),
                ("W  E  R", L.T("sposta · ruota · scala")), ("F", L.T("inquadra selezione")), (L.T("Ctrl+D"), "duplica"), (L.T("Ctrl+C / V"), L.T("copia · incolla (istanze o copie)")), (L.T("Shift+trascina"), L.T("copie con il gizmo")), (L.T("Canc"), "elimina"), (L.T("Ctrl+I"), L.T("importa modello")) })
            {
                var row = new DockPanel { Margin = new Thickness(0, 8, 0, 0) };
                var key = new TextBlock { Text = k, FontFamily = Theme.Mono, FontSize = 12, Foreground = Theme.B(Theme.TextSoft), Width = 150 };
                row.Children.Add(key);
                row.Children.Add(Theme.Label(d, 12, Theme.TextFaint));
                sp.Children.Add(row);
            }
            return sp;
        }

        Button SmallButton(Geometry icon, string text, Func<Task> act)
        {
            var b = Theme.Button(Theme.IconText(icon, text, null, 14), Theme.Kind.Normal);
            b.MinHeight = 30;
            b.Padding = new Thickness(10, 0, 10, 0);
            b.Margin = new Thickness(0, 0, 6, 6);
            b.FontSize = 12;
            b.Click += async (_, __) => await act();
            return b;
        }

        /// <summary>A small square button with only an icon (the text is its tooltip).</summary>
        Button IconButton(Geometry icon, string tooltip, Func<Task> act)
        {
            var b = Theme.Button(Theme.Icon(icon, null, 15), Theme.Kind.Ghost, tooltip);
            b.Width = 30; b.Height = 30;
            b.Padding = new Thickness(0);
            b.Click += async (_, __) => await act();
            return b;
        }

        static TextBlock SectionTitle(string text)
        {
            var t = Theme.Label(text, 13, Theme.TextSoft, FontWeights.SemiBold);
            t.Margin = new Thickness(0, 0, 0, 10);
            t.Tag = "section";      // becomes an accordion header (see MakeAccordions)
            return t;
        }

        /// <summary>How big the piece is (with what it contains), along its own axes: a car of a few centimetres
        /// instead of metres - a file with the wrong units - shows at once. Read from the engine after the panel is drawn.</summary>
        UIElement SizeRow(string id)
        {
            var g = new Grid { Margin = new Thickness(0, 2, 0, 4) };
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(86) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            g.Children.Add(Theme.Label(L.T("Dimensioni"), 12, Theme.TextMuted));
            var val = Theme.Label("…", 12.5, Theme.TextSoft);
            val.ToolTip = L.T("Larghezza × profondità × altezza del modello, lungo i suoi assi (con la scala)");
            Grid.SetColumn(val, 1);
            g.Children.Add(val);
            // (1.75.56) and its triangles (copies counted), when it has a surface - Luca
            g.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            g.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            var triL = Theme.Label(L.T("Triangoli"), 12, Theme.TextMuted);
            var triV = Theme.Label("", 12.5, Theme.TextSoft);
            triV.ToolTip = L.T("Triangoli del modello come viene disegnato (le copie contano). Per alleggerirlo: tasto destro, «Ottimizza poligoni…»");
            triL.Margin = triV.Margin = new Thickness(0, 6, 0, 0);
            Grid.SetRow(triL, 1); Grid.SetRow(triV, 1); Grid.SetColumn(triV, 1);
            triL.Visibility = triV.Visibility = Visibility.Collapsed;
            g.Children.Add(triL); g.Children.Add(triV);
            async Task Load()
            {
                JsonObject? r = null;
                try { if (_api != null) r = await _api.Get("size?id=" + Uri.EscapeDataString(id)); } catch { }
                if ((long?)r?["triangles"] is long t && t > 0)
                {
                    triV.Text = t.ToString("N0", System.Globalization.CultureInfo.CurrentCulture);
                    triL.Visibility = triV.Visibility = Visibility.Visible;
                }
                if (r?["size"] is not JsonArray a || a.Count < 3) { val.Text = "–"; return; }
                double[] m = { (double?)a[0] ?? 0, (double?)a[1] ?? 0, (double?)a[2] ?? 0 };
                double mx = Math.Max(m[0], Math.Max(m[1], m[2]));
                (double k, string unit, int dec) = mx >= 1 ? (1.0, "m", 2) : mx >= 0.01 ? (100.0, "cm", 1) : (1000.0, "mm", 1);
                val.Text = string.Join(" × ", m.Select(x => Num.F(x * k, dec))) + " " + unit;
            }
            _ = Load();
            return g;
        }

        UIElement VectorRow(string label, double[] values, string field, string id, int decimals)
        {
            var g = new Grid { Margin = new Thickness(0, 0, 0, 8) };
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(86) });
            for (int i = 0; i < 3; i++) g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            var l = Theme.Label(label, 12, Theme.TextMuted);
            g.Children.Add(l);
            var boxes = new TextBox[3];
            Color[] axis = { Theme.AxisX, Theme.AxisY, Theme.AxisZ };
            for (int i = 0; i < 3; i++)
            {
                var box = Theme.Input(Num.F(values[i], decimals), true);
                box.Margin = new Thickness(i == 0 ? 0 : 4, 0, 0, 0);
                box.BorderBrush = Theme.B(Color.FromArgb(110, axis[i].R, axis[i].G, axis[i].B));
                boxes[i] = box;
                Grid.SetColumn(box, i + 1);
                g.Children.Add(box);
            }
            async Task Commit()
            {
                var v = new double[3];
                for (int i = 0; i < 3; i++) if (!Num.TryParse(boxes[i].Text, out v[i])) { Status(L.T("Valore non valido"), true); return; }
                if (v.SequenceEqual(values)) return;
                await Run(async api => { await api.Post("transform", new JsonObject { ["id"] = id, [field] = new JsonArray(v[0], v[1], v[2]) }); });
                await RefreshScene();
            }
            foreach (var b in boxes)
            {
                b.KeyDown += async (_, e) => { if (e.Key == Key.Enter) await Commit(); };
                b.LostFocus += async (_, __) => await Commit();
            }
            return g;
        }

        void RenderMultiProps()
        {
            var objs = TopLevelSelection();
            var head = new StackPanel();
            head.Children.Add(Theme.Caption(L.T("Proprietà")));
            var title = Theme.Label(L.F("{0} oggetti selezionati", _selection.Count), 15, Theme.Text, FontWeights.SemiBold);
            title.Margin = new Thickness(0, 8, 0, 6);
            head.Children.Add(title);
            foreach (var id in _selection.Take(8))
                if (_scene.ById.TryGetValue(id, out var so))
                {
                    var n = Theme.Label("• " + so.Name, 12, id == _selected ? Theme.Warm : Theme.TextSoft);
                    n.Margin = new Thickness(0, 0, 0, 2);
                    head.Children.Add(n);
                }
            if (_selection.Count > 8) head.Children.Add(Theme.Label(L.F("… e altri {0}", _selection.Count - 8), 12, Theme.TextFaint));
            var actions = new WrapPanel { Margin = new Thickness(0, 10, 0, 0) };
            actions.Children.Add(SmallButton(Icons.Frame, L.T("Inquadra"), async () => await FrameSelection()));
            actions.Children.Add(SmallButton(Icons.Copy, L.T("Duplica"), async () => await DuplicateSelected()));
            actions.Children.Add(SmallButton(Icons.Trash, L.T("Elimina"), async () => await DeleteSelected()));
            head.Children.Add(actions);
            var hint = Theme.Label(L.T("Sposta, ruota e scala nella vista: la selezione si muove come un oggetto unico, attorno al centro comune. ") +
                                   L.T("Con più oggetti la scala è sempre uniforme, così le proporzioni restano intatte."), 12, Theme.TextFaint);
            hint.TextWrapping = TextWrapping.Wrap;
            hint.Margin = new Thickness(0, 8, 0, 0);
            head.Children.Add(hint);
            _props.Children.Add(Theme.Card(head, 16));

            var mat = new StackPanel();
            mat.Children.Add(SectionTitle(L.T("Materiale")));
            var mh = Theme.Label(L.T("Clicca un materiale nella libreria in basso per applicarlo a tutta la selezione."), 12, Theme.TextFaint);
            mh.TextWrapping = TextWrapping.Wrap;
            mat.Children.Add(mh);
            _props.Children.Add(Theme.Card(mat, 16));
            // rain and snow for all the selected objects at once (the parts of a model too)
            WeatherCard(_selection.Select(id => _scene.ById.TryGetValue(id, out var so) ? so : null)
                                  .Where(x => x != null && (x.IsMesh || x.Kind == "group" || x.Kind == "file")).Select(x => x!).ToList());
        }

        static readonly (string id, string label, string tip)[] LightKinds =
        {
            ("point", L.T("Omni"), L.T("Luce puntiforme: illumina in tutte le direzioni (lampadina)")),
            ("spot", L.T("Spot"), L.T("Faretto: cono di luce orientabile")),
            ("area", L.T("Area"), L.T("Pannello luminoso: luce morbida da studio (softbox)")),
            ("sun", L.T("Sole"), L.T("Luce solare: raggi paralleli, conta solo la direzione")),
        };

        UIElement LightSection(SceneObject o)
        {
            var sp = new StackPanel();
            sp.Children.Add(SectionTitle(L.T("Luce")));
            var LD = o.Light!;
            if ((bool?)LD["ambience"] ?? false)
            {
                // the sun (or the moon) of the Ambiente: colour and strength come from the sky
                var ambNote = new DockPanel { Margin = new Thickness(0, 0, 0, 12) };
                var open = SmallButton(Icons.Globe, L.T("Apri Ambiente"), async () => await ShowRightPanel("ambience"));
                DockPanel.SetDock(open, Dock.Right);
                ambNote.Children.Add(open);
                var t = Theme.Label(L.T("Guidata dall'Ambiente: colore e intensità seguono il cielo e l'ora."), 12, Theme.TextFaint);
                t.TextWrapping = TextWrapping.Wrap;
                ambNote.Children.Add(t);
                sp.Children.Add(ambNote);
            }

            var seg = Theme.Segmented(out var typeButtons, LightKinds.Select(k => ((object)k.label, (string?)k.tip)).ToArray());
            seg.HorizontalAlignment = HorizontalAlignment.Left;
            seg.Margin = new Thickness(0, 0, 0, 14);
            Theme.SetSegment(typeButtons, Math.Max(0, Array.FindIndex(LightKinds, k => k.id == o.Kind)));
            for (int i = 0; i < typeButtons.Count; i++)
            {
                var kind = LightKinds[i].id;
                typeButtons[i].Click += async (_, __) =>
                {
                    if (kind == o.Kind) return;
                    await Run(async api => { await api.Post("light", new { id = o.Id, type = kind }); });
                    await RefreshScene();
                };
            }
            sp.Children.Add(seg);

            void Preview(string key, double v) => SendToWeb(new { type = "lightPreview", id = o.Id, light = new JsonObject { [key] = v } });
            async Task Commit(JsonObject body)
            {
                body["id"] = o.Id;
                await Run(async api => { await api.Post("light", body); });
                await RefreshScene();
            }
            ValueSlider Slider(string label, string key, double value, double min, double max, bool log, string fmt, string unit,
                               string tip, double scale = 1, Brush? track = null)
            {
                var s = new ValueSlider(label, value * scale, min, max, log, fmt, unit, track, tip);
                s.Changing += v => Preview(key, v / scale);
                s.Committed += async v => await Commit(new JsonObject { [key] = v / scale });
                sp.Children.Add(s);
                return s;
            }
            double D(string key, double def) => (double?)LD[key] ?? def;

            if (o.Kind != "sun" && !((bool?)LD["ambience"] ?? false))
            {
                // switches (engine dusk.py): Accesa wins over everything; Dal tramonto all'alba = on only at evening
                // and at night, by the hour of the Ambiente
                bool isOn = (bool?)LD["on"] ?? true, isDusk = (bool?)LD["dusk"] ?? false, lit = (bool?)LD["lit"] ?? true;
                var onT = new Toggle(L.T("Accesa"), isOn, L.T("Spenta: non illumina, qualunque sia l'ora (vale più di «Dal tramonto all'alba»)"));
                onT.Toggled += async v => await Commit(new JsonObject { ["on"] = v });
                sp.Children.Add(onT);
                var duskT = new Toggle(L.T("Dal tramonto all'alba"), isDusk,
                    L.T("Si accende da sola solo la sera e di notte, secondo l'ora dell'Ambiente: luci delle case, lampioni, insegne. Di giorno resta spenta"));
                duskT.Toggled += async v => await Commit(new JsonObject { ["dusk"] = v });
                duskT.IsEnabled = isOn;
                sp.Children.Add(duskT);
                if (isOn && isDusk)
                {
                    var st = Theme.Label(lit ? L.T("Adesso è accesa: è sera o notte nell'Ambiente.") : L.T("Adesso è spenta: è giorno nell'Ambiente."), 11.5, Theme.TextFaint);
                    st.Margin = new Thickness(0, 0, 0, 10);
                    st.TextWrapping = TextWrapping.Wrap;
                    sp.Children.Add(st);
                }
            }

            if (o.Kind == "sun")
                Slider(L.T("Intensità"), "power", D("power", 4), 0.05, 50, true, "0.##", L.T("W/m²"), L.T("Irraggiamento del sole: 3-6 per una giornata limpida"));
            else
                Slider(L.T("Potenza"), "power", D("power", 300), 1, 20000, true, "0", "W", L.T("Potenza della luce (scala logaritmica)"));

            var kelvin = D("kelvin", 0);
            Slider(L.T("Temperatura"), "kelvin", kelvin > 0 ? kelvin : 6500, 1500, 12000, false, "0", "K",
                   L.T("1800 K candela · 2700 K lampadina calda · 4000 K neutra · 5500 K sole · 6500 K luce diurna · 9000 K cielo"),
                   1, KelvinBrush());

            if (o.Kind != "sun")
            {
                // colour of the lamp (it tints the temperature: white = only the temperature)
                var colArr = LD["color"] as JsonArray;
                var lin = colArr != null && colArr.Count >= 3 ? new[] { (double?)colArr[0] ?? 1, (double?)colArr[1] ?? 1, (double?)colArr[2] ?? 1 } : new[] { 1.0, 1.0, 1.0 };
                var cf = new ColorField(L.T("Colore"), lin, L.T("Colore della luce: bianco = solo la temperatura qui sopra; un colore la tinge (gelatina colorata)"));
                cf.Committed += async v => await Commit(new JsonObject { ["color"] = new JsonArray(v[0], v[1], v[2]) });
                sp.Children.Add(cf);
                // reach: the light fades to nothing at this distance (0 = physical)
                Slider(L.T("Raggio d'azione"), "range", D("range", 0), 0, 100, false, "0.#", "m",
                       L.T("Fin dove arriva la luce: oltre questa distanza si spegne del tutto, sfumando. 0 = luce fisica (si attenua con il quadrato della distanza, senza limite). Utile per tenere una lampada solo nella sua stanza"));
            }
            if (o.Kind == "spot")
            {
                // picture projected through the cone (projector, gobo, coloured patterns)
                var gobo = (string?)LD["gobo"] ?? "";
                var gr = new DockPanel { Margin = new Thickness(0, 0, 0, 10) };
                var gl = Theme.Label(L.T("Proiezione"), 12, Theme.TextMuted);
                gl.Width = 96;
                DockPanel.SetDock(gl, Dock.Left);
                gr.Children.Add(gl);
                if (gobo != "")
                {
                    var rm = Theme.Button(L.T("Togli"), Theme.Kind.Ghost, L.T("Torna alla luce normale"));
                    rm.MinHeight = 26; rm.FontSize = 11.5; rm.Padding = new Thickness(8, 0, 8, 0);
                    rm.Click += async (_, __) => await Commit(new JsonObject { ["gobo"] = "" });
                    DockPanel.SetDock(rm, Dock.Right);
                    gr.Children.Add(rm);
                }
                var pick = Theme.Button(gobo != "" ? System.IO.Path.GetFileName(gobo) : L.T("Scegli un'immagine…"), Theme.Kind.Normal,
                    L.T("Come un proiettore: l'immagine (colorata o in bianco e nero, es. una finestra, foglie, un logo) viene proiettata dal cono della luce sulle superfici. L'altezza dell'immagine riempie il cono"));
                pick.MinHeight = 26; pick.FontSize = 11.5; pick.Padding = new Thickness(8, 0, 8, 0);
                pick.HorizontalContentAlignment = HorizontalAlignment.Left;
                pick.Click += async (_, __) =>
                {
                    var dlg = new Microsoft.Win32.OpenFileDialog { Filter = L.T("Immagini|*.png;*.jpg;*.jpeg;*.tif;*.tiff;*.bmp;*.exr;*.hdr;*.webp"), InitialDirectory = StartFolder("image") };
                    if (dlg.ShowDialog(this) != true) return;
                    Keep("image", dlg.FileName);
                    await Commit(new JsonObject { ["gobo"] = dlg.FileName });
                };
                gr.Children.Add(pick);
                sp.Children.Add(gr);
            }
            if (o.Kind == "spot")
            {
                Slider(L.T("Apertura cono"), "coneAngle", D("coneAngle", 45), 1, 170, false, "0.#", "°", L.T("Ampiezza del fascio di luce"));
                Slider(L.T("Sfumatura bordo"), "blend", D("blend", 0.25), 0, 100, false, "0", "%", L.T("0% = bordo del cono netto · 100% = bordo molto sfumato"), 100);
            }
            if (o.Kind == "point" || o.Kind == "spot")
                Slider(L.T("Dimensione"), "radius", D("radius", 5), 0, 100, false, "0.#", "cm",
                       L.T("Dimensione della sorgente: piccola = ombre nette, grande = ombre morbide"));
            if (o.Kind == "area")
            {
                Slider(L.T("Larghezza"), "width", D("width", 50), 1, 1000, true, "0.#", "cm", L.T("Più grande = luce e ombre più morbide"));
                Slider(L.T("Altezza"), "height", D("height", 50), 1, 1000, true, "0.#", "cm", L.T("Più grande = luce e ombre più morbide"));
                var shapes = Theme.Segmented(out var shapeButtons, (L.T("Rettangolo"), (string?)null), (L.T("Disco"), (string?)null));
                shapes.HorizontalAlignment = HorizontalAlignment.Left;
                shapes.Margin = new Thickness(96, 0, 0, 12);
                var disk = (string?)LD["shape"] is "DISK" or "ELLIPSE";
                Theme.SetSegment(shapeButtons, disk ? 1 : 0);
                shapeButtons[0].Click += async (_, __) => await Commit(new JsonObject { ["shape"] = "RECTANGLE" });
                shapeButtons[1].Click += async (_, __) => await Commit(new JsonObject { ["shape"] = "ELLIPSE" });
                sp.Children.Add(shapes);
            }
            if (o.Kind == "sun")
                Slider(L.T("Morbidezza ombre"), "angle", D("angle", 0.53), 0, 15, false, "0.##", "°", L.T("Diametro apparente del sole: 0.5° = ombre nette, valori alti = cielo velato"));
            if (o.Kind == "sun") SunSliders(sp, o, LD);

            var shadow = new Toggle(L.T("Proietta ombre"), (bool?)LD["shadow"] ?? true, L.T("Disattiva per una luce di riempimento che non crea ombre"));
            shadow.Toggled += async v => await Commit(new JsonObject { ["shadow"] = v });
            sp.Children.Add(shadow);
            var refl = new Toggle(L.T("Visibile nei riflessi"), (bool?)LD["reflections"] ?? true, L.T("Se spento la luce illumina ma non compare come riflesso sulle superfici lucide"));
            refl.Toggled += async v => await Commit(new JsonObject { ["reflections"] = v });
            sp.Children.Add(refl);
            if (o.Kind == "area")
            {
                var cam = new Toggle(L.T("Visibile in camera"), (bool?)LD["visibleCamera"] ?? false, L.T("Acceso: si vede la superficie luminosa (strisce LED, pannelli). Spento: illumina ma non compare nell'immagine"));
                cam.Toggled += async v => await Commit(new JsonObject { ["visibleCamera"] = v });
                sp.Children.Add(cam);
            }

            var note = Theme.Label(o.Kind == "sun" ? "" : D("range", 0) > 0
                ? L.T("La luce si spegne del tutto al raggio d'azione: utile per tenerla locale (non è fisico: vicino alla lampada resta uguale).")
                : L.T("Cycles calcola l'attenuazione fisica con la distanza (legge dell'inverso del quadrato): per una luce più locale avvicinala e riduci la potenza, o dai un raggio d'azione."), 11, Theme.TextFaint);
            note.TextWrapping = TextWrapping.Wrap;
            note.Margin = new Thickness(0, 4, 0, 0);
            sp.Children.Add(note);
            return sp;
        }

        static readonly string[] MonthShort = { "gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic" };
        static readonly int[] MonthStart = { 1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335 };

        /// <summary>The sun placed by time of day and north (and date, latitude): no need to turn it with the gizmo.</summary>
        void SunSliders(StackPanel sp, SceneObject o, JsonObject LD)
        {
            var sun = LD["sun"] as JsonObject ?? new JsonObject();
            var cur = new Dictionary<string, double>
            {
                ["hour"] = (double?)sun["hour"] ?? 10.5, ["north"] = (double?)sun["north"] ?? 0,
                ["day"] = (double?)sun["day"] ?? 172, ["lat"] = (double?)sun["lat"] ?? 45.5,
            };
            var head = Theme.Label(L.T("Posizione del sole"), 12, Theme.TextSoft, FontWeights.SemiBold);
            head.Margin = new Thickness(0, 6, 0, 8);
            sp.Children.Add(head);
            if (!((bool?)LD["sunSet"] ?? false))
            {
                var hint = Theme.Label(L.T("Muovi un cursore e il sole si mette nella posizione di quell'ora (la rotazione fatta a mano viene sostituita)."), 11, Theme.TextFaint);
                hint.TextWrapping = TextWrapping.Wrap;
                hint.Margin = new Thickness(0, 0, 0, 8);
                sp.Children.Add(hint);
            }
            JsonObject Body() => new JsonObject { ["hour"] = cur["hour"], ["north"] = cur["north"], ["day"] = cur["day"], ["lat"] = cur["lat"] };
            ValueSlider Add(string label, string key, double min, double max, double step, string unit, string tip, Brush? track,
                            Func<double, string>? show = null, Func<string, double?>? parse = null)
            {
                var s = new ValueSlider(label, cur[key], min, max, false, "0", unit, track, tip) { Step = step, Display = show, Parse = parse };
                s.Refresh();
                s.Changing += v => { cur[key] = v; SendToWeb(new { type = "lightPreview", id = o.Id, sun = Body() }); };
                s.Committed += async v =>
                {
                    cur[key] = v;
                    await Run(async api => { await api.Post("light", new JsonObject { ["id"] = o.Id, ["sun"] = Body() }); });
                    await RefreshScene();
                };
                sp.Children.Add(s);
                return s;
            }
            static string Hm(double h) { var m = (int)Math.Round(h * 60); return $"{Math.Min(24, m / 60):00}:{m % 60:00}"; }
            static double? ParseHm(string t)
            {
                t = t.Trim().Replace('.', ':').Replace(',', ':');
                var parts = t.Split(':');
                if (!int.TryParse(parts[0], out var h)) return null;
                int mm = parts.Length > 1 && int.TryParse(parts[1], out var x) ? x : 0;
                return h + mm / 60.0;
            }
            Add(L.T("Ora del giorno"), "hour", 0, 24, 5 / 60.0, "", L.T("Ora solare: 12:00 = sole a sud, nel punto più alto. Prima dell'alba e dopo il tramonto il sole si spegne."),
                DayBrush(), Hm, ParseHm);
            Add(L.T("Nord"), "north", 0, 360, 1, "°", L.T("Dove sta il nord nella scena: 0° = lungo l'asse verde (Y), 90° = lungo l'asse rosso (X)"), null,
                v => v.ToString("0.##"), t => Num.TryParse(t.Replace("°", ""), out var v) ? ((v % 360) + 360) % 360 : null);
            Add(L.T("Data"), "day", 1, 365, 1, "", L.T("Giorno dell'anno: d'estate il sole sale più in alto, d'inverno resta basso"), null,
                v => { int d = (int)Math.Round(v); int m = Array.FindLastIndex(MonthStart, s0 => s0 <= d); return $"{d - MonthStart[m] + 1} {L.T(MonthShort[m])}"; },
                t =>
                {
                    var parts = t.Trim().Split(' ', StringSplitOptions.RemoveEmptyEntries);
                    if (parts.Length < 2 || !int.TryParse(parts[0], out var dd)) return null;
                    int m = Array.FindIndex(MonthShort, x => parts[1].ToLowerInvariant().StartsWith(x) || parts[1].ToLowerInvariant().StartsWith(L.T(x).ToLowerInvariant()));
                    return m < 0 ? null : Math.Clamp(MonthStart[m] + dd - 1, 1, 365);
                });
            Add(L.T("Latitudine"), "lat", -60, 70, 0.5, "°", L.T("Dove si trova la scena: Milano 45,5° · Roma 41,9° · Palermo 38,1° · Londra 51,5° (negativi: emisfero sud)"), null,
                v => v.ToString("0.##"), t => Num.TryParse(t.Replace("°", ""), out var v) ? v : null);
        }

        /// <summary>Night - dawn - day - dusk - night along the 24 hours.</summary>
        static Brush DayBrush()
        {
            var b = new LinearGradientBrush { StartPoint = new Point(0, 0), EndPoint = new Point(1, 0) };
            foreach (var (h, hex) in new[] { (0.0, "#2A1D4E"), (4.5, "#3B2463"), (6.0, "#C2456B"), (7.5, "#F39A3A"), (10.0, "#F7CF3C"),
                                             (12.0, "#FBE36A"), (14.0, "#F7CF3C"), (17.0, "#F39A3A"), (19.0, "#C2456B"), (20.5, "#3B2463"), (24.0, "#2A1D4E") })
                b.GradientStops.Add(new GradientStop(Theme.C(hex), h / 24.0));
            b.Freeze();
            return b;
        }

        static Brush KelvinBrush()
        {
            var b = new LinearGradientBrush { StartPoint = new Point(0, 0), EndPoint = new Point(1, 0) };
            foreach (var (k, hex) in new[] { (1500, "#FF7A10"), (3000, "#FFB46B"), (5000, "#FFE4CE"), (6500, "#FFF9FD"), (9000, "#D9E3FF"), (12000, "#C3D1FF") })
                b.GradientStops.Add(new GradientStop(Theme.C(hex), (k - 1500) / 10500.0));
            b.Freeze();
            return b;
        }

        UIElement NumberRow(string label, double value, Func<double, object> body)
        {
            var row = new DockPanel { Margin = new Thickness(0, 0, 0, 8) };
            var l = Theme.Label(label, 12, Theme.TextMuted);
            l.Width = 130;
            row.Children.Add(l);
            var box = Theme.Input(Num.F(value, 2), true);
            async Task Commit()
            {
                if (!Num.TryParse(box.Text, out var v)) { Status(L.T("Valore non valido"), true); return; }
                if (Math.Abs(v - value) < 1e-9) return;
                await Run(async api => { await api.Post("light", body(v)); });
                await RefreshScene();
            }
            box.KeyDown += async (_, e) => { if (e.Key == Key.Enter) await Commit(); };
            box.LostFocus += async (_, __) => await Commit();
            row.Children.Add(box);
            return row;
        }

        // ================================================================ library

        static string EnvSwatch(string id) => id switch
        {
            "studio_morbido" => "#8A93A3",
            "studio_contrasto" => "#3A4256",
            "esterno_giorno" => "#7FB3E6",
            _ => "#1B2233",
        };

        async Task ApplyMaterial(string id, string label)
        {
            if (_selection.Count == 0) { Status(L.T("Seleziona prima un oggetto (o un gruppo) a cui applicare il materiale"), true); return; }
            if (IsBusy) return;
            using var busy = BeginBusy();
            _reloadOrigin = "action";
            await Run(async api =>
            {
                var r = await api.Post("material/assign", new { ids = _selection.ToArray(), material = id });
                Status(L.F("{0} applicato a {1} superfici", label, (int?)r["assigned"] ?? 0));
            });
            await RefreshScene();
        }
    }
}
