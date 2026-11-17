using System;
using System.Collections.Generic;
using System.Globalization;
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
    public sealed partial class MainWindow
    {
        MaterialFixWizard? _matFixWizard;

        /// <summary>"Correggi materiali": the materials of many library models fixed at once (preselect: these models).</summary>
        void ShowMaterialFixWizard(IEnumerable<string>? preselect = null)
        {
            if (_matFixWizard != null) { _matFixWizard.Preselect(preselect); _matFixWizard.Show(); _matFixWizard.Activate(); WatchDialogLock(); return; }
            _matFixWizard = new MaterialFixWizard(this, preselect) { Owner = this };
            _matFixWizard.Closed += (_, __) => _matFixWizard = null;
            _matFixWizard.Show();
            WatchDialogLock();
        }

        /// <summary>
        /// The materials of the personal library models, corrected in bulk: 1. the models, 2. their materials read by a
        /// separate Blender and grouped (glass, fake glass, glass with a metal map, metal, glossy...), 3. the changes
        /// (set, multiply or add a channel, remove a map; presets), 4. applied in the background with a backup of every
        /// model (Ripristina puts the last correction back). Only the library: models already in a scene stay as they are.
        /// </summary>
        sealed class MaterialFixWizard : ThemedDialog
        {
            sealed class MatRow
            {
                public string Model = "", ModelName = "", Name = "", Category = "";
                public bool Advanced;
                public JsonObject Values = new();
                public CheckBox Check = null!;
                public FrameworkElement View = null!;
            }

            sealed class Op
            {
                public string Param = "roughness", Mode = "add";
                public TextBox Value = null!;
                public TextBlock Unit = null!;
                public Button ParamButton = null!, ModeButton = null!;
                public FrameworkElement View = null!;
            }

            // parameter id, label, modes ("set", "mul", "add", "remove", "none"), default value
            static readonly (string id, string label, string[] modes, string def)[] Params =
            {
                ("roughness", "Ruvidezza", new[] { "set", "mul", "add" }, "10"),
                ("metallic", "Metallo", new[] { "set", "mul", "add" }, "0"),
                ("specular", "Riflesso speculare", new[] { "set", "mul", "add" }, "50"),
                ("brightness", "Luminosità del colore", new[] { "set", "mul" }, "90"),
                ("saturation", "Saturazione del colore", new[] { "set", "mul" }, "90"),
                ("tint", "Colore (tinta)", new[] { "set" }, "#FFFFFF"),
                ("transmission", "Trasparenza (vetro)", new[] { "set" }, "100"),
                ("ior", "Indice di rifrazione", new[] { "set" }, "1,5"),
                ("thinOn", "Parete sottile: accesa", new[] { "none" }, ""),
                ("thinOff", "Parete sottile: spenta", new[] { "none" }, ""),
                ("coat", "Vernice trasparente (coat)", new[] { "set", "add" }, "20"),
                ("emission", "Emissione (nit)", new[] { "set", "mul" }, "0"),
                ("alphaOff", "Togli la trasparenza alfa", new[] { "none" }, ""),
                ("colorMap", "Togli la texture del colore", new[] { "remove" }, ""),
                ("roughnessMap", "Togli la texture di ruvidezza", new[] { "remove" }, ""),
                ("metallicMap", "Togli la texture di metallo", new[] { "remove" }, ""),
                ("normalMap", "Togli la normal map", new[] { "remove" }, ""),
                ("bumpMap", "Togli la mappa di rilievo", new[] { "remove" }, ""),
            };

            static readonly (string id, string label, Color color)[] Categories =
            {
                ("glass", "Vetri", Color.FromRgb(0x7F, 0xC8, 0xFF)),
                ("fakeglass", "Vetri finti (opachi)", Color.FromRgb(0xF2, 0xB5, 0x4B)),
                ("glassmetal", "Vetri con metallo", Color.FromRgb(0xFF, 0x7A, 0x7A)),
                ("metal", "Metalli", Color.FromRgb(0xC9, 0xD3, 0xE4)),
                ("glossy", "Lucidi (plastiche)", Color.FromRgb(0xB0, 0x8C, 0xFF)),
                ("emissive", "Emissivi", Color.FromRgb(0xFF, 0xE0, 0x6A)),
                ("textured", "Con texture", Color.FromRgb(0x5F, 0xC7, 0xB5)),
                ("plain", "Semplici", Color.FromRgb(0x9D, 0xAA, 0xC2)),
                ("advanced", "Avanzati (non modificabili)", Color.FromRgb(0x7C, 0x8B, 0xA6)),
            };

            readonly MainWindow _mw;
            readonly Dictionary<string, CheckBox> _modelChecks = new();
            readonly List<(string folder, CheckBox box)> _folderChecks = new();
            readonly StackPanel _modelList = new(), _matList = new(), _chips = new() { Orientation = Orientation.Horizontal }, _ops = new();
            readonly TextBlock _modelCount, _matCount, _status, _preview;
            readonly ProgressBar _bar;
            readonly ScrollViewer _opsScroll;
            readonly Button _scan, _apply, _restore, _close;
            readonly Toggle _backup;
            readonly FrameworkElement _step2, _step3;
            readonly List<MatRow> _rows = new();
            readonly List<Op> _opRows = new();
            string _filter = "";
            bool _busy, _updatingChecks, _backupOn = true;
            public bool Running => _busy;               // (closing Simpler waits for it)

            public MaterialFixWizard(MainWindow mw, IEnumerable<string>? preselect) : base(L.T("Correggi materiali dei modelli"), 960)
            {
                _mw = mw;
                _keepCentred = true;
                var sp = Body;
                var intro = new TextBlock
                {
                    Text = L.T("Corregge in un colpo solo i materiali di tanti modelli della tua libreria: per esempio le plastiche troppo lucide o i vetri finti dei modelli importati. Simpler legge i materiali in background, li raggruppa per tipo, tu scegli quali correggere e come; ogni modello viene salvato di nuovo con la sua miniatura. I modelli già messi nelle scene restano come sono."),
                    TextWrapping = TextWrapping.Wrap, FontSize = 12.5, Foreground = Theme.B(Theme.TextMuted), LineHeight = 19, Margin = new Thickness(0, 0, 0, 14),
                };
                sp.Children.Add(intro);

                // ---- 1. models
                sp.Children.Add(Step("1", L.T("Modelli da correggere")));
                var top1 = new DockPanel { Margin = new Thickness(0, 8, 0, 6) };
                var all = new CheckBox { Content = L.T("Tutta la libreria"), Foreground = Theme.B(Theme.TextSoft), VerticalAlignment = VerticalAlignment.Center };
                all.Checked += (_, __) => SetAllModels(true);
                all.Unchecked += (_, __) => SetAllModels(false);
                top1.Children.Add(all);
                _modelCount = Theme.Label("", 12, Theme.TextFaint);
                _modelCount.Margin = new Thickness(14, 0, 0, 0);
                _modelCount.VerticalAlignment = VerticalAlignment.Center;
                top1.Children.Add(_modelCount);
                sp.Children.Add(top1);
                sp.Children.Add(Box(_modelList, BoxHeight(0.58, 110, 230)));   // (1.78.4, Luca: the models list taller, the materials one shorter)
                _scan = Theme.Button(Theme.IconText(Icons.Sliders, L.T("Analizza i materiali"), Theme.Accent, 14), Theme.Kind.Normal,
                                     L.T("Un secondo Blender apre i modelli scelti e legge i loro materiali: la scena non viene toccata"));
                _scan.HorizontalAlignment = HorizontalAlignment.Left;
                _scan.Margin = new Thickness(0, 8, 0, 14);
                _scan.Click += async (_, __) => await Scan();
                sp.Children.Add(_scan);

                // ---- 2. materials
                var s2 = new StackPanel();
                s2.Children.Add(Step("2", L.T("Materiali da correggere")));
                s2.Children.Add(new ScrollViewer { Content = _chips, HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, VerticalScrollBarVisibility = ScrollBarVisibility.Disabled, Margin = new Thickness(0, 8, 0, 6) });
                var selRow = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 0, 0, 6) };
                var selAll = Theme.Button(L.T("Seleziona quelli mostrati"), Theme.Kind.Ghost);
                selAll.Click += (_, __) => { foreach (var r in Shown()) if (!r.Advanced) r.Check.IsChecked = true; UpdateCounts(); };
                var selNone = Theme.Button(L.T("Deseleziona tutti"), Theme.Kind.Ghost);
                selNone.Click += (_, __) => { foreach (var r in _rows) r.Check.IsChecked = false; UpdateCounts(); };
                selNone.Margin = new Thickness(6, 0, 0, 0);
                selRow.Children.Add(selAll);
                selRow.Children.Add(selNone);
                _matCount = Theme.Label("", 12, Theme.TextFaint);
                _matCount.Margin = new Thickness(14, 0, 0, 0);
                _matCount.VerticalAlignment = VerticalAlignment.Center;
                selRow.Children.Add(_matCount);
                s2.Children.Add(selRow);
                s2.Children.Add(Box(_matList, BoxHeight(0.42, 80, 130)));
                _step2 = s2;
                sp.Children.Add(s2);

                // ---- 3. changes
                var s3 = new StackPanel { Margin = new Thickness(0, 14, 0, 0) };
                s3.Children.Add(Step("3", L.T("Modifiche")));
                var presets = new WrapPanel { Margin = new Thickness(0, 8, 0, 8) };
                var pl = Theme.Label(L.T("Preset:"), 12.5, Theme.TextSoft);
                pl.VerticalAlignment = VerticalAlignment.Center;
                pl.Margin = new Thickness(0, 0, 8, 0);
                presets.Children.Add(pl);
                var p1 = Theme.Button(L.T("Meno plastica"), Theme.Kind.Normal, L.T("Sceglie i materiali lucidi e li rende un po' più ruvidi: riflessi più morbidi, meno effetto plastica"));
                p1.Click += (_, __) => Preset(new[] { "glossy" }, new[] { ("roughness", "add", "20") });
                var p2 = Theme.Button(L.T("Vetri veri"), Theme.Kind.Normal, L.T("Sceglie i vetri (anche quelli finti, fatti con l'opacità, e quelli con una mappa di metallo) e li rende vetri veri: trasparenti, lisci, senza metallo e senza le mappe del vecchio trucco"));
                p2.Margin = new Thickness(6, 0, 0, 0);
                p2.Click += (_, __) => Preset(new[] { "glass", "fakeglass", "glassmetal" }, new[]
                {
                    ("transmission", "set", "100"), ("roughness", "set", "0"), ("metallic", "set", "0"), ("ior", "set", "1,5"),
                    ("alphaOff", "none", ""), ("tint", "set", "#FFFFFF"), ("colorMap", "remove", ""), ("normalMap", "remove", ""),
                });
                presets.Children.Add(p1);
                presets.Children.Add(p2);
                s3.Children.Add(presets);
                // the list of changes scrolls by itself: however many changes, «Applica le modifiche» stays in the window
                _opsScroll = new ScrollViewer { Content = _ops, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Padding = new Thickness(0, 0, 4, 0),
                                                MaxHeight = 136 };          // (three changes, then it scrolls)
                s3.Children.Add(_opsScroll);
                var add = Theme.Button(Theme.IconText(Icons.Plus, L.T("Aggiungi una modifica"), Theme.Accent, 13), Theme.Kind.Ghost);
                add.HorizontalAlignment = HorizontalAlignment.Left;
                add.Click += (_, __) => { AddOp("roughness", "add", "10"); UpdatePreview(); _opsScroll.UpdateLayout(); _opsScroll.ScrollToEnd(); };
                s3.Children.Add(add);
                _preview = new TextBlock { TextWrapping = TextWrapping.Wrap, FontSize = 12, Foreground = Theme.B(Theme.TextSoft), Margin = new Thickness(0, 8, 0, 0) };
                s3.Children.Add(_preview);
                _step3 = s3;
                sp.Children.Add(s3);

                // ---- 4. apply
                var s4 = new StackPanel { Margin = new Thickness(0, 14, 0, 0) };
                s4.Children.Add(Step("4", L.T("Applica")));
                _backup = new Toggle(L.T("Copia di sicurezza dei modelli prima di correggerli"), true,
                                     L.T("Simpler tiene una copia di ogni modello com'era: «Ripristina» la rimette (si tengono le ultime 3 correzioni)"));
                _backup.Margin = new Thickness(0, 8, 0, 8);
                _backup.Toggled += on => _backupOn = on;
                s4.Children.Add(_backup);
                _bar = new ProgressBar { Height = 6, Minimum = 0, Maximum = 1, Value = 0, Foreground = Theme.B(Theme.Accent), Background = Theme.B("#1A2842"), BorderThickness = new Thickness(0), Margin = new Thickness(0, 4, 0, 6) };
                s4.Children.Add(_bar);
                _status = Theme.Label("", 12, Theme.TextMuted);
                _status.TextTrimming = TextTrimming.CharacterEllipsis;
                s4.Children.Add(_status);
                var buttons = new DockPanel { Margin = new Thickness(0, 14, 0, 0) };
                _restore = Theme.Button(Theme.IconText(Icons.Undo, L.T("Ripristina l'ultima correzione"), null, 14), Theme.Kind.Ghost);
                _restore.Visibility = Visibility.Collapsed;
                _restore.Click += async (_, __) => await Restore();
                buttons.Children.Add(_restore);
                var right = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right };
                _close = Theme.Button(L.T("Chiudi"), Theme.Kind.Ghost);
                _close.Click += (_, __) => OnCloseButton();
                _apply = Theme.Button(L.T("Applica le modifiche"), Theme.Kind.Primary);
                _apply.Margin = new Thickness(8, 0, 0, 0);
                _apply.MinWidth = 170;
                _apply.Click += async (_, __) => await Apply();
                right.Children.Add(_close);
                right.Children.Add(_apply);
                DockPanel.SetDock(right, Dock.Right);
                buttons.Children.Insert(0, right);
                s4.Children.Add(buttons);
                // step 4 (toggle, progress, buttons) stays at the bottom: steps 1-3 scroll when the window is as tall as
                // the screen, so «Applica le modifiche» is always in sight however many changes are added
                s4.Margin = new Thickness(0, 6, 0, 0);
                Footer.Children.Add(s4);
                EnableBodyScroll();

                FillModels();
                Preselect(preselect);
                SetEnabled(false);
                KeyDown += (_, e) => { if (e.Key == Key.Escape) OnCloseButton(); };
                Loaded += async (_, __) => await RefreshBackup();
            }

            static FrameworkElement Step(string n, string text)
            {
                var sp = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 4, 0, 0) };
                sp.Children.Add(new Border
                {
                    Width = 22, Height = 22, CornerRadius = new CornerRadius(11), Background = Theme.B(Theme.Segment), Margin = new Thickness(0, 0, 8, 0),
                    Child = new TextBlock { Text = n, FontSize = 12, FontWeight = FontWeights.SemiBold, Foreground = Theme.B(Theme.Text), HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center },
                });
                var t = Theme.Label(text, 14, Theme.Text, FontWeights.SemiBold);
                t.VerticalAlignment = VerticalAlignment.Center;
                sp.Children.Add(t);
                return sp;
            }

            /// <summary>The two lists share what the screen leaves after the fixed parts (~700 px): the window always fits.</summary>
            static double BoxHeight(double share, double min, double max) =>
                Math.Max(min, Math.Min(max, (SystemParameters.WorkArea.Height - 760) * share));   // (760: the rest of the window, with three changes)

            static Border Box(UIElement content, double height) => new()
            {
                Child = new ScrollViewer { Content = content, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Padding = new Thickness(0, 0, 4, 0) },
                Height = height, Background = Theme.B(Theme.Inset), BorderBrush = Theme.B(Theme.Line), BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(8), Padding = new Thickness(8, 6, 6, 6),
            };

            protected override void OnCloseButton()
            {
                if (_busy) { Hide(); _mw.Status(L.T("Correzione dei materiali in corso in background…")); return; }
                Close();
            }

            void SetEnabled(bool scanned)
            {
                _step2.IsEnabled = _step3.IsEnabled = scanned && !_busy;
                _step2.Opacity = _step3.Opacity = scanned ? 1 : 0.45;
                _apply.IsEnabled = scanned && !_busy;
                _scan.IsEnabled = !_busy;
            }

            // ---------------------------------------------------------------- 1. models

            void FillModels()
            {
                _modelList.Children.Clear();
                _modelChecks.Clear();
                _folderChecks.Clear();
                // (1.78.4) not the models of the locked Simpler parts: they are not changed
                var models = _mw._models.OfType<JsonObject>().Where(m => ((bool?)m["ready"] ?? true) && !_mw.ReadOnlyFolder((string?)m["folder"])).ToList();
                var folders = models.Select(m => (string?)m["folder"] ?? "").Distinct().OrderBy(f => f, StringComparer.CurrentCultureIgnoreCase).ToList();
                foreach (var f in folders)
                {
                    var fb = new CheckBox
                    {
                        Content = Theme.IconText(Icons.Folder, f == "" ? L.T("Modelli 3D") : f.Replace("/", " / "), Theme.Warm, 13),
                        Foreground = Theme.B(Theme.TextSoft), Margin = new Thickness(0, 4, 0, 2),
                    };
                    var folder = f;
                    fb.Checked += (_, __) => { if (!_updatingChecks) SetFolder(folder, true); };
                    fb.Unchecked += (_, __) => { if (!_updatingChecks) SetFolder(folder, false); };
                    _folderChecks.Add((f, fb));
                    _modelList.Children.Add(fb);
                    var wrap = new WrapPanel { Margin = new Thickness(24, 0, 0, 4) };
                    foreach (var m in models.Where(m => ((string?)m["folder"] ?? "") == f).OrderBy(m => (string?)m["name"], StringComparer.CurrentCultureIgnoreCase))
                    {
                        var id = (string?)m["id"] ?? "";
                        var cb = new CheckBox { Content = (string?)m["name"] ?? id, Foreground = Theme.B(Theme.TextMuted), Margin = new Thickness(0, 2, 16, 2), Tag = f };
                        cb.Checked += (_, __) => ModelsChanged();
                        cb.Unchecked += (_, __) => ModelsChanged();
                        _modelChecks[id] = cb;
                        wrap.Children.Add(cb);
                    }
                    _modelList.Children.Add(wrap);
                }
                if (models.Count == 0) _modelList.Children.Add(Theme.Label(L.T("La libreria dei modelli 3D è vuota."), 12, Theme.TextFaint));
                ModelsChanged();
            }

            public void Preselect(IEnumerable<string>? ids)
            {
                if (ids == null) return;
                foreach (var id in ids) if (_modelChecks.TryGetValue(id, out var cb)) cb.IsChecked = true;
            }

            void SetAllModels(bool on) { foreach (var cb in _modelChecks.Values) cb.IsChecked = on; }

            void SetFolder(string f, bool on)
            {
                foreach (var cb in _modelChecks.Values.Where(c => c.Tag is string t && (t == f || t.StartsWith(f + "/") || f == "" && t == ""))) cb.IsChecked = on;
            }

            List<string> ChosenModels() => _modelChecks.Where(kv => kv.Value.IsChecked == true).Select(kv => kv.Key).ToList();

            void ModelsChanged()
            {
                var n = ChosenModels().Count;
                _modelCount.Text = L.F("{0} modelli scelti", n);
                _scan.Content = Theme.IconText(Icons.Sliders, n <= 1 ? L.T("Analizza i materiali") : L.F("Analizza i materiali di {0} modelli", n), Theme.Accent, 14);
                _updatingChecks = true;
                foreach (var (f, box) in _folderChecks)
                {
                    var inside = _modelChecks.Values.Where(c => (string?)c.Tag == f).ToList();
                    box.IsChecked = inside.Count > 0 && inside.All(c => c.IsChecked == true);
                }
                _updatingChecks = false;
            }

            // ---------------------------------------------------------------- jobs

            async Task<JsonObject?> Wait(string what)
            {
                var api = _mw._api!;
                while (true)
                {
                    await Task.Delay(400);
                    JsonObject st;
                    try { st = await api.Get("matbulk/status"); } catch { continue; }
                    var state = (string?)st["state"] ?? "";
                    int done = (int?)st["done"] ?? 0, total = Math.Max(1, (int?)st["total"] ?? 1);
                    _bar.Value = (double)done / total;
                    var cur = (string?)st["current"] ?? "";
                    _status.Text = L.F("{0}: {1} di {2}", what, Math.Min(done + 1, total), total) + (cur != "" ? " · " + cur : "");
                    if (state == "running") continue;
                    _bar.Value = state == "done" ? 1 : 0;
                    if (state != "done") { _status.Text = (string?)st["error"] is string e && e != "" ? e : state; return null; }
                    return st;
                }
            }

            async Task Scan()
            {
                var ids = ChosenModels();
                if (ids.Count == 0 || _mw._api == null || _busy) { _status.Text = L.T("Scegli almeno un modello"); return; }
                _busy = true;
                SetEnabled(false);
                try
                {
                    await _mw._api.Post("matbulk/scan", new JsonObject { ["ids"] = new JsonArray(ids.Select(i => (JsonNode)i!).ToArray()) });
                    var st = await Wait(L.T("Lettura dei materiali"));
                    if (st?["result"]?["models"] is JsonArray models) FillMaterials(models);
                }
                catch (Exception ex) { _status.Text = ex.Message; }
                finally { _busy = false; SetEnabled(_rows.Count > 0); }
            }

            void FillMaterials(JsonArray models)
            {
                _rows.Clear();
                _matList.Children.Clear();
                int errors = 0;
                foreach (var m in models.OfType<JsonObject>())
                {
                    if (((string?)m["error"] ?? "") != "") errors++;
                    foreach (var x in (m["materials"] as JsonArray ?? new JsonArray()).OfType<JsonObject>())
                    {
                        var row = new MatRow
                        {
                            Model = (string?)m["id"] ?? "", ModelName = (string?)m["name"] ?? "", Name = (string?)x["name"] ?? "",
                            Category = (string?)x["category"] ?? "plain", Advanced = (bool?)x["advanced"] ?? false,
                            Values = x["values"] as JsonObject ?? new JsonObject(),
                        };
                        row.View = MaterialRow(row);
                        _rows.Add(row);
                        _matList.Children.Add(row.View);
                    }
                }
                BuildChips();
                ApplyFilter();
                _status.Text = L.F("Letti {0} materiali in {1} modelli", _rows.Count, models.Count) + (errors > 0 ? " · " + L.F("{0} modelli non letti", errors) : "");
            }

            FrameworkElement MaterialRow(MatRow r)
            {
                var v = r.Values;
                var g = new Grid { Margin = new Thickness(0, 1, 0, 1), Background = Brushes.Transparent, Cursor = Cursors.Hand };
                g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(24) });
                g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(24) });
                g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(260) });
                g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(150) });
                r.Check = new CheckBox { VerticalAlignment = VerticalAlignment.Center, IsEnabled = !r.Advanced };
                r.Check.Checked += (_, __) => UpdateCounts();
                r.Check.Unchecked += (_, __) => UpdateCounts();
                g.Children.Add(r.Check);
                Color sw;
                try { sw = (Color)ColorConverter.ConvertFromString((string?)v["color"] ?? "#CCCCCC"); } catch { sw = Colors.Gray; }
                var swatch = new Border
                {
                    Width = 16, Height = 16, CornerRadius = new CornerRadius(4), Background = new SolidColorBrush(sw), BorderBrush = Theme.B(Theme.LineStrong),
                    BorderThickness = new Thickness(1), VerticalAlignment = VerticalAlignment.Center,
                };
                Grid.SetColumn(swatch, 1);
                g.Children.Add(swatch);
                var name = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
                name.Children.Add(new TextBlock { Text = r.Name, Foreground = Theme.B(r.Advanced ? Theme.TextFaint : Theme.Text), FontSize = 12, TextTrimming = TextTrimming.CharacterEllipsis, MaxWidth = 150 });
                name.Children.Add(new TextBlock { Text = "  " + r.ModelName, Foreground = Theme.B(Theme.TextFaint), FontSize = 11, TextTrimming = TextTrimming.CharacterEllipsis, MaxWidth = 105 });
                Grid.SetColumn(name, 2);
                g.Children.Add(name);
                var c = CultureInfo.CurrentCulture;
                string N(string k) => ((double?)v[k] ?? 0).ToString("0.##", c);
                string P(string k) => (((double?)v[k] ?? 0) * 100).ToString("0", c) + "%";      // as in the editor
                var t = (double?)v["transmission"] ?? 0;
                var vals = L.F("ruvidezza {0}", (bool?)v["roughnessMap"] == true ? "▦" : P("roughness")) + " · " +
                           L.F("metallo {0}", (bool?)v["metallicMap"] == true ? "▦" : P("metallic")) +
                           (t > 0 ? " · " + L.F("trasparenza {0} · IOR {1}", P("transmission"), N("ior")) : "");
                var vt = new TextBlock { Text = vals, Foreground = Theme.B(Theme.TextMuted), FontSize = 11.5, VerticalAlignment = VerticalAlignment.Center, TextTrimming = TextTrimming.CharacterEllipsis };
                Grid.SetColumn(vt, 3);
                g.Children.Add(vt);
                var badges = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Center };
                void Badge(string key, string text, string tip)
                {
                    if ((bool?)v[key] != true) return;
                    badges.Children.Add(new Border
                    {
                        Background = Theme.B(Theme.Raised), CornerRadius = new CornerRadius(4), Padding = new Thickness(5, 0, 5, 1), Margin = new Thickness(3, 0, 0, 0), ToolTip = tip,
                        Child = new TextBlock { Text = text, FontSize = 10, Foreground = Theme.B(Theme.TextSoft) },
                    });
                }
                Badge("colorMap", "C", L.T("Texture del colore"));
                Badge("roughnessMap", "R", L.T("Texture di ruvidezza"));
                Badge("metallicMap", "M", L.T("Texture di metallo"));
                Badge("normalMap", "N", L.T("Normal map o rilievo"));
                Badge("alpha", "A", L.T("Trasparenza alfa (opacità)"));
                var cat = Categories.FirstOrDefault(k => k.id == r.Category);
                badges.Children.Add(new Border
                {
                    Background = new SolidColorBrush(Color.FromArgb(40, cat.color.R, cat.color.G, cat.color.B)), CornerRadius = new CornerRadius(4),
                    Padding = new Thickness(6, 0, 6, 1), Margin = new Thickness(6, 0, 0, 0),
                    Child = new TextBlock { Text = L.T(cat.label ?? ""), FontSize = 10, Foreground = new SolidColorBrush(cat.color) },
                });
                Grid.SetColumn(badges, 4);
                g.Children.Add(badges);
                g.ToolTip = r.Advanced ? L.T("Materiale avanzato (nodi che l'editor non sa leggere): non viene modificato") : r.Name + " · " + r.ModelName;
                g.MouseLeftButtonUp += (_, e) => { if (!r.Advanced && e.OriginalSource is not CheckBox) r.Check.IsChecked = r.Check.IsChecked != true; };
                return g;
            }

            void BuildChips()
            {
                _chips.Children.Clear();
                void Chip(string id, string label, int n)
                {
                    var b = Theme.Button($"{label} ({n})", id == _filter ? Theme.Kind.Segment : Theme.Kind.Ghost);
                    b.MinHeight = 26; b.FontSize = 12; b.Padding = new Thickness(9, 0, 9, 0); b.Margin = new Thickness(0, 0, 5, 0);
                    b.Click += (_, __) => { _filter = id; BuildChips(); ApplyFilter(); };
                    _chips.Children.Add(b);
                }
                Chip("", L.T("Tutti"), _rows.Count);
                foreach (var (id, label, _) in Categories)
                {
                    var n = _rows.Count(r => r.Category == id);
                    if (n > 0) Chip(id, L.T(label), n);
                }
            }

            IEnumerable<MatRow> Shown() => _rows.Where(r => _filter == "" || r.Category == _filter);

            void ApplyFilter()
            {
                foreach (var r in _rows) r.View.Visibility = _filter == "" || r.Category == _filter ? Visibility.Visible : Visibility.Collapsed;
                UpdateCounts();
            }

            List<MatRow> Chosen() => _rows.Where(r => r.Check.IsChecked == true && !r.Advanced).ToList();

            void UpdateCounts()
            {
                var ch = Chosen();
                _matCount.Text = L.F("{0} materiali scelti in {1} modelli", ch.Count, ch.Select(r => r.Model).Distinct().Count());
                UpdatePreview();
            }

            // ---------------------------------------------------------------- 3. changes

            static string ModeLabel(string m) => m switch
            {
                "set" => L.T("Imposta"), "mul" => L.T("Moltiplica ×"), "add" => L.T("Somma +"), "remove" => L.T("Togli"), _ => "",
            };

            void AddOp(string param, string mode, string value)
            {
                var op = new Op { Param = param, Mode = mode };
                var g = new Grid { Margin = new Thickness(0, 0, 0, 6) };
                g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(260) });
                g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(140) });
                g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(90) });
                g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(40) });
                g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(34) });
                op.ParamButton = Dropdown("", 250);
                op.ModeButton = Dropdown("", 130);
                Grid.SetColumn(op.ModeButton, 1);
                op.Value = Theme.Input(value, true);
                op.Value.Margin = new Thickness(0, 0, 6, 0);
                op.Value.TextChanged += (_, __) => UpdatePreview();
                Grid.SetColumn(op.Value, 2);
                op.Unit = new TextBlock { FontSize = 12, Foreground = Theme.B(Theme.TextMuted), VerticalAlignment = VerticalAlignment.Center };
                Grid.SetColumn(op.Unit, 3);
                g.Children.Add(op.Unit);
                var rm = Theme.Button("×", Theme.Kind.Ghost, L.T("Togli questa modifica"));
                rm.Padding = new Thickness(6, 0, 6, 0);
                rm.Click += (_, __) => { _opRows.Remove(op); _ops.Children.Remove(op.View); UpdatePreview(); };
                Grid.SetColumn(rm, 4);
                g.Children.Add(op.ParamButton);
                g.Children.Add(op.ModeButton);
                g.Children.Add(op.Value);
                g.Children.Add(rm);
                op.View = g;
                op.ParamButton.Click += (_, __) =>
                {
                    var menu = new ContextMenu { PlacementTarget = op.ParamButton, Placement = PlacementMode.Bottom };
                    foreach (var p in Params)
                    {
                        var mi = new MenuItem { Header = L.T(p.label) };
                        var pp = p;
                        mi.Click += (_, __) =>
                        {
                            op.Param = pp.id;
                            if (!pp.modes.Contains(op.Mode)) op.Mode = pp.modes[0];
                            op.Value.Text = pp.def;
                            RefreshOp(op);
                        };
                        menu.Items.Add(mi);
                    }
                    menu.IsOpen = true;
                };
                op.ModeButton.Click += (_, __) =>
                {
                    var modes = Params.First(p => p.id == op.Param).modes;
                    if (modes.Length <= 1) return;
                    var menu = new ContextMenu { PlacementTarget = op.ModeButton, Placement = PlacementMode.Bottom };
                    foreach (var m in modes)
                    {
                        var mi = new MenuItem { Header = ModeLabel(m) };
                        var mm = m;
                        mi.Click += (_, __) => { op.Mode = mm; op.Value.Text = DefaultValue(op.Param, mm); RefreshOp(op); };
                        menu.Items.Add(mi);
                    }
                    menu.IsOpen = true;
                };
                _opRows.Add(op);
                _ops.Children.Add(g);
                RefreshOp(op);
            }

            // channels the editor shows in % (0-100): the engine wants 0-1
            static bool IsPercent(string param) => param is "roughness" or "metallic" or "specular" or "transmission" or "coat" or "brightness" or "saturation";

            static string UnitOf(string param, string mode) =>
                mode == "mul" ? "×" : IsPercent(param) ? "%" : param == "emission" ? "nit" : "";

            static string DefaultValue(string param, string mode)
            {
                if (mode == "mul") return "1,5";
                if (mode == "add") return IsPercent(param) ? "10" : "0,1";
                return Params.First(p => p.id == param).def;
            }

            static Button Dropdown(string text, double width)
            {
                var b = Theme.Button(text, Theme.Kind.Normal);
                b.MinHeight = 28; b.Height = 28; b.FontSize = 12; b.Padding = new Thickness(8, 0, 8, 0); b.Margin = new Thickness(0, 0, 6, 0);
                b.HorizontalContentAlignment = HorizontalAlignment.Left;
                b.Width = width;
                return b;
            }

            void RefreshOp(Op op)
            {
                var p = Params.First(x => x.id == op.Param);
                op.ParamButton.Content = DropText(L.T(p.label), op.ParamButton.Width - 18);
                op.ModeButton.Content = DropText(ModeLabel(op.Mode), op.ModeButton.Width - 18);
                op.ModeButton.Visibility = op.Mode is "none" or "remove" ? Visibility.Hidden : Visibility.Visible;
                op.Value.Visibility = op.Mode is "none" or "remove" ? Visibility.Hidden : Visibility.Visible;
                op.Unit.Text = op.Mode is "none" or "remove" ? "" : UnitOf(op.Param, op.Mode);
                op.Value.ToolTip = op.Mode == "mul" ? L.T("Fattore: 1,5 = una volta e mezza, 0,5 = la metà")
                                 : IsPercent(op.Param) ? (op.Mode == "add" ? L.T("Punti percentuali da aggiungere (negativo = toglie)") : L.T("Percentuale: 0–100"))
                                 : null;
                UpdatePreview();
            }

            static FrameworkElement DropText(string text, double width)
            {
                var d = new DockPanel { LastChildFill = true, Width = width };      // (text on the left, chevron on the right)
                var ch = Theme.Icon(Icons.ChevronDown, Theme.TextMuted, 12, 1.8);
                DockPanel.SetDock(ch, Dock.Right);
                ch.Margin = new Thickness(6, 0, 0, 0);
                d.Children.Add(ch);
                d.Children.Add(new TextBlock { Text = text, TextTrimming = TextTrimming.CharacterEllipsis, VerticalAlignment = VerticalAlignment.Center });
                return d;
            }

            void Preset(string[] cats, (string param, string mode, string value)[] ops)
            {
                foreach (var r in _rows) r.Check.IsChecked = !r.Advanced && cats.Contains(r.Category);
                _filter = cats.Length == 1 ? cats[0] : "";
                BuildChips();
                ApplyFilter();
                _opRows.Clear();
                _ops.Children.Clear();
                foreach (var (p, m, v) in ops) AddOp(p, m, v);
                UpdatePreview();
            }

            static double? Num(string s) => double.TryParse((s ?? "").Trim().Replace(',', '.'), NumberStyles.Float, CultureInfo.InvariantCulture, out var v) ? v : null;

            /// <summary>The changes as the engine wants them, or an error to show.</summary>
            (JsonArray ops, string error) BuildOps()
            {
                var arr = new JsonArray();
                foreach (var op in _opRows)
                {
                    var label = L.T(Params.First(p => p.id == op.Param).label);
                    switch (op.Param)
                    {
                        case "thinOn": arr.Add(new JsonObject { ["param"] = "thin", ["mode"] = "set", ["value"] = true }); break;
                        case "thinOff": arr.Add(new JsonObject { ["param"] = "thin", ["mode"] = "set", ["value"] = false }); break;
                        case "alphaOff": arr.Add(new JsonObject { ["param"] = "alpha", ["mode"] = "set", ["value"] = false }); break;
                        case "tint":
                            var hex = op.Value.Text.Trim();
                            if (!System.Text.RegularExpressions.Regex.IsMatch(hex, "^#?[0-9A-Fa-f]{6}$")) return (arr, L.F("{0}: scrivi un colore come #FFFFFF", label));
                            arr.Add(new JsonObject { ["param"] = "tint", ["mode"] = "set", ["value"] = hex.StartsWith("#") ? hex : "#" + hex });
                            break;
                        default:
                            if (op.Mode == "remove") { arr.Add(new JsonObject { ["param"] = op.Param, ["mode"] = "remove" }); break; }
                            if (Num(op.Value.Text) is not double v) return (arr, L.F("{0}: valore non valido", label));
                            if (op.Mode != "mul" && IsPercent(op.Param)) v /= 100.0;       // 100% = 1
                            arr.Add(new JsonObject { ["param"] = op.Param, ["mode"] = op.Mode, ["value"] = v });
                            break;
                    }
                }
                return (arr, "");
            }

            void UpdatePreview()
            {
                var ch = Chosen();
                var (ops, err) = BuildOps();
                if (err != "") { _preview.Text = err; _preview.Foreground = Theme.B(Theme.Danger); return; }
                _preview.Foreground = Theme.B(Theme.TextSoft);
                if (ch.Count == 0 || ops.Count == 0)
                {
                    _preview.Text = ch.Count == 0 ? L.T("Scegli i materiali nel passo 2.") : L.T("Aggiungi almeno una modifica o scegli un preset.");
                    return;
                }
                var text = L.F("Verranno corretti {0} materiali in {1} modelli.", ch.Count, ch.Select(r => r.Model).Distinct().Count());
                // a channel that comes from a texture: multiply/add cannot change it (only "Imposta" replaces the texture)
                int mapped = 0;
                foreach (var op in _opRows.Where(o => o.Mode is "mul" or "add" && o.Param is "roughness" or "metallic"))
                    mapped += ch.Count(r => (bool?)r.Values[op.Param + "Map"] == true);
                if (mapped > 0) text += " " + L.F("{0} hanno una texture su ruvidezza o metallo: con Moltiplica o Somma restano come sono (Imposta sostituisce la texture con il valore).", mapped);
                _preview.Text = text;
            }

            // ---------------------------------------------------------------- 4. apply

            async Task Apply()
            {
                if (_busy || _mw._api == null) return;
                var ch = Chosen();
                var (ops, err) = BuildOps();
                if (err != "") { _status.Text = err; return; }
                if (ch.Count == 0 || ops.Count == 0) { _status.Text = L.T("Scegli i materiali e almeno una modifica"); return; }
                var nModels = ch.Select(r => r.Model).Distinct().Count();
                if (!_backupOn && Msg.Show(this, L.F("Correggere {0} materiali in {1} modelli senza copia di sicurezza? Non si potrà tornare indietro.", ch.Count, nModels),
                                              "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Warning) != MessageBoxResult.Yes) return;
                var items = new JsonArray();
                foreach (var g in ch.GroupBy(r => r.Model))
                    items.Add(new JsonObject { ["id"] = g.Key, ["materials"] = new JsonArray(g.Select(r => (JsonNode)r.Name!).ToArray()) });
                _busy = true;
                SetEnabled(true);
                try
                {
                    await _mw._api.Post("matbulk/apply", new JsonObject { ["items"] = items, ["ops"] = ops, ["backup"] = _backupOn });
                    var st = await Wait(L.T("Correzione"));
                    if (st?["result"]?["models"] is JsonArray res)
                    {
                        int changed = res.OfType<JsonObject>().Sum(x => (int?)x["changed"] ?? 0);
                        int errors = res.OfType<JsonObject>().Count(x => ((string?)x["error"] ?? "") != "");
                        int skipped = res.OfType<JsonObject>().Sum(x => (x["skipped"] as JsonArray)?.Count ?? 0);
                        var summary = L.F("Fatto: {0} materiali corretti in {1} modelli", changed, res.OfType<JsonObject>().Count(x => ((int?)x["changed"] ?? 0) > 0))
                                      + (skipped > 0 ? " · " + L.F("{0} lasciati com'erano (texture o materiale avanzato)", skipped) : "")
                                      + (errors > 0 ? " · " + L.F("{0} modelli non riusciti", errors) : "");
                        _status.Text = summary + " · " + L.T("le miniature si aggiornano in background");
                        _mw.Status(summary, errors > 0);
                        _ = RefreshLibrarySoon();
                        // the list shows the new values: read the same models again
                        await _mw._api.Post("matbulk/scan", new JsonObject { ["ids"] = new JsonArray(_rows.Select(r => r.Model).Distinct().Select(i => (JsonNode)i!).ToArray()) });
                        var keep = ch.Select(r => r.Model + "|" + r.Name).ToHashSet();
                        var st2 = await Wait(L.T("Lettura dei materiali"));
                        if (st2?["result"]?["models"] is JsonArray models)
                        {
                            FillMaterials(models);
                            foreach (var r in _rows) r.Check.IsChecked = keep.Contains(r.Model + "|" + r.Name);
                            _status.Text = summary;
                        }
                    }
                }
                catch (Exception ex) { _status.Text = ex.Message; }
                finally { _busy = false; SetEnabled(_rows.Count > 0); await RefreshBackup(); }
            }

            async Task RefreshLibrarySoon()
            {
                for (int i = 0; i < 6; i++) { await Task.Delay(5000); await _mw.ReloadModels(); }
            }

            async Task RefreshBackup()
            {
                if (_mw._api == null) return;
                try
                {
                    var st = await _mw._api.Get("matbulk/status");
                    if (st["backup"] is JsonObject b)
                    {
                        _restore.Content = Theme.IconText(Icons.Undo, L.F("Ripristina l'ultima correzione ({0}, {1} modelli)", (string?)b["when"] ?? "", (int?)b["count"] ?? 0), null, 14);
                        _restore.Tag = (string?)b["run"];
                        _restore.Visibility = Visibility.Visible;
                    }
                    else _restore.Visibility = Visibility.Collapsed;
                }
                catch { }
            }

            async Task Restore()
            {
                if (_busy || _mw._api == null || _restore.Tag is not string run) return;
                if (Msg.Show(this, L.T("Rimettere i modelli dell'ultima correzione come erano prima?"), "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
                try
                {
                    var r = await _mw._api.Post("matbulk/restore", new JsonObject { ["run"] = run });
                    _status.Text = L.F("Ripristinati {0} modelli · le miniature si aggiornano in background", (int?)r["restored"] ?? 0);
                    _ = RefreshLibrarySoon();
                }
                catch (Exception ex) { _status.Text = ex.Message; }
                await RefreshBackup();
            }
        }
    }
}
