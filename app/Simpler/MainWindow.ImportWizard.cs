using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace Simpler
{
    public sealed partial class MainWindow
    {
        LibraryImportWizard? _importWizard;

        /// <summary>Header "Importa ▾": the model into the scene, or many models straight into the library.</summary>
        void ShowImportMenu(FrameworkElement anchor)
        {
            var m = new ContextMenu { PlacementTarget = anchor, Placement = System.Windows.Controls.Primitives.PlacementMode.Bottom };
            var one = new MenuItem { Header = L.T("Importa un modello nella scena…"), InputGestureText = "Ctrl+I" };
            one.Click += async (_, __) => await ImportModel();
            var many = new MenuItem { Header = L.T("Importa modelli nella libreria…") };
            many.Click += (_, __) => ShowImportWizard();
            var plants = new MenuItem { Header = L.T("Importa vegetazione nella libreria…") };
            plants.Click += (_, __) => ShowImportWizard(true);
            var fix = new MenuItem { Header = L.T("Correggi materiali dei modelli…") };
            fix.Click += (_, __) => ShowMaterialFixWizard();
            m.Items.Add(one);
            m.Items.Add(many);
            m.Items.Add(plants);
            m.Items.Add(new Separator());          // importing above, looking after the library below
            m.Items.Add(fix);
            var stats = new MenuItem { Header = L.T("Statistiche e pulizia della libreria…") };
            stats.Click += (_, __) => ShowLibraryStats();
            m.Items.Add(stats);
            // (1.79.0, Luca: «li metterei insieme in una sezione del menu separata») the packs of models made for Simpler
            m.Items.Add(new Separator());
            var packs = new MenuItem { Header = L.T("Pacchetti…"), ToolTip = L.T("I pacchetti di modelli per Simpler: quelli installati, quelli nuovi e gli aggiornamenti") };
            packs.Click += async (_, __) => await ShowInstalledPacks();
            m.Items.Add(packs);
            var pack = new MenuItem { Header = L.T("Installa un pacchetto da file…"), ToolTip = L.T("Installa un pacchetto Simpler (.simplerpack) che hai già sul computer") };
            pack.Click += async (_, __) => await InstallPackAsk();
            m.Items.Add(pack);
            m.IsOpen = true;
        }

        void ShowImportWizard(bool veg = false)
        {
            if (_importWizard != null) { _importWizard.Show(); _importWizard.Activate(); WatchDialogLock(); return; }
            _importWizard = new LibraryImportWizard(this, veg) { Owner = this };
            _importWizard.Closed += (_, __) => _importWizard = null;
            _importWizard.Show();
            WatchDialogLock();
        }

        /// <summary>
        /// "Importa modelli nella libreria": several model files (FBX, glTF/GLB, OBJ, USD) straight into the model library,
        /// each with its destination folder. Every model is imported by the second Blender (the one of the previews):
        /// the scene and the 3D view are not touched. Textures looked for next to the file and copied, path-traced
        /// thumbnail. Models that already exist (same name, same folder): overwritten if asked, otherwise a question
        /// (overwrite, rename or skip).
        /// </summary>
        sealed class LibraryImportWizard : ThemedDialog
        {
            sealed class Row
            {
                public string Path = "";
                public TextBox Name = null!;
                public string Folder = "";
                public bool FolderSet;               // chosen for this row (the default does not change it any more)
                public Button FolderButton = null!;
                public TextBlock State = null!;
                public TextBlock Size = null!;       // the size of the model (measured before the import) and with its scale
                public TextBox FactorBox = null!;
                public double Factor = 1.0;          // the scale of this model (×1 = as in the file)
                public double[]? Probe;              // its size in the file, cm (null: not measured yet)
                public bool Probing, ProbeFailed;
                public FrameworkElement View = null!;
            }

            static readonly string[] Formats = { ".fbx", ".glb", ".gltf", ".obj", ".usd", ".usda", ".usdc", ".usdz" };
            readonly MainWindow _mw;
            readonly List<Row> _rows = new();
            readonly StackPanel _list = new();
            readonly TextBlock _empty;
            readonly Button _defaultFolder, _go, _close, _addFiles, _addFolder;
            readonly Toggle _overwriteToggle;
            readonly ProgressBar _bar;
            readonly TextBlock _status;
            string _folder = "";
            bool _overwrite, _running, _cancel;
            public bool Running => _running;        // (Simpler stays locked while it imports, even with the window hidden)
            static bool _split;
            static bool _merge;
            static string _pivot = "base";
            static double _scale = 1.0;           // for every model of the import (wrong units in the files)
            static bool _checkScale;              // a pause after every model: look at its size, change it, go on
            readonly TextBox _scaleBox;
            // (1.78.0) «Vegetazione»: each model imported becomes a plant (MainWindow.Vegetation: Fogliame on leaves and
            // wood, into Vegetazione/<kind>)
            bool _veg;
            readonly TextBlock _title, _intro;
            // the picture on the left: the models' one, or the plants' one (import_wizard_veg.jpg) for Vegetazione
            // (1.78.5, Luca: «cosa è questa approssimazione») stretched both ways: centred it took its own height (from the
            // width) and the tall pictures left white bands above and below; UniformToFill now covers the whole panel
            readonly Image _picture = new Image { Stretch = Stretch.UniformToFill, VerticalAlignment = VerticalAlignment.Stretch, HorizontalAlignment = HorizontalAlignment.Stretch };

            static BitmapImage? WizardPicture(string name)
            {
                try
                {
                    var file = System.IO.Path.Combine(AppContext.BaseDirectory, name);
                    if (!File.Exists(file)) return null;
                    var bmp = new BitmapImage();
                    bmp.BeginInit(); bmp.CacheOption = BitmapCacheOption.OnLoad; bmp.UriSource = new Uri(file); bmp.EndInit(); bmp.Freeze();
                    return bmp;
                }
                catch { return null; }
            }
            readonly Border _checkPanel = new() { Visibility = Visibility.Collapsed };
            TaskCompletionSource<bool>? _checkWait;

            public LibraryImportWizard(MainWindow mw, bool veg = false) : base(L.T("Importa modelli nella libreria"), 980)
            {
                _mw = mw;
                _veg = veg;
                Body.Margin = new Thickness(0, 0, 0, 0);
                var grid = new Grid();
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(300) });
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

                // ---- left: the picture and what the wizard does
                var left = new Grid { Margin = new Thickness(16, 0, 0, 16) };
                var pic = new Border { CornerRadius = new CornerRadius(12), ClipToBounds = true, Background = Theme.B("#F4F7FB") };
                pic.Child = _picture;
                left.Children.Add(pic);
                grid.Children.Add(left);

                // ---- right: files, destination, options, progress
                var right = new StackPanel { Margin = new Thickness(24, 0, 24, 20) };
                Grid.SetColumn(right, 1);
                grid.Children.Add(right);
                _title = Theme.Label("", 20, Theme.Text, FontWeights.SemiBold);
                right.Children.Add(_title);
                // what is imported: models, or plants (the same steps, then Fogliame on their materials)
                var kinds = Theme.Segmented(out var kindButtons,
                    (L.T("Modelli 3D"), L.T("Oggetti di ogni tipo: vanno in Modelli 3D")),
                    (L.T("Vegetazione"), L.T("Alberi, arbusti, erbe e fiori: le foglie e il legno ricevono il materiale Fogliame (con la stagione) e le piante vanno in Vegetazione, divise per tipo")));
                kinds.HorizontalAlignment = HorizontalAlignment.Left;
                kinds.Margin = new Thickness(0, 10, 0, 0);
                right.Children.Add(kinds);
                _intro = new TextBlock { TextWrapping = TextWrapping.Wrap, FontSize = 12.5, Foreground = Theme.B(Theme.TextMuted), LineHeight = 19, Margin = new Thickness(0, 8, 0, 16) };
                right.Children.Add(_intro);
                void SetKind(bool v)
                {
                    _veg = v;
                    Theme.SetSegment(kindButtons, v ? 1 : 0);
                    _picture.Source = WizardPicture(v ? "import_wizard_veg.jpg" : "import_wizard.jpg") ?? WizardPicture("import_wizard.jpg");
                    Title = v ? L.T("Importa vegetazione nella libreria") : L.T("Importa modelli nella libreria");
                    _title.Text = v ? L.T("Popola la libreria della vegetazione") : L.T("Popola la libreria dei modelli");
                    _intro.Text = v
                        ? L.T("Scegli i file delle piante (FBX, glTF/GLB, OBJ, USD) o un'intera cartella e premi Importa. Simpler le prepara una per una in background, senza toccare la scena: riconosce foglie e legno e dà loro il materiale Fogliame, con stagione e trasparenza. Le trovi in Vegetazione, divise per altezza; se una foglia è presa per legno: tasto destro, «Foglie e legno…».")
                        : L.T("Scegli uno o più file (FBX, glTF/GLB, OBJ, USD) o un'intera cartella, decidi in quale cartella della libreria va ognuno e premi Importa. Simpler li prepara uno per uno in background, senza toccare la scena: cerca le texture accanto ai file, le copia, salva il modello e ne fa la miniatura. Alla fine li trovi in Modelli 3D, pronti da trascinare nella vista.");
                    if (_defaultFolder != null && !_running)
                    {
                        _folder = StartFolder(v);
                        foreach (var r in _rows.Where(r => !r.FolderSet)) SetRowFolder(r, _folder, false);
                        UpdateChip(_defaultFolder, _folder);
                    }
                }
                kindButtons[0].Click += (_, __) => { if (!_running) SetKind(false); };
                kindButtons[1].Click += (_, __) => { if (!_running) SetKind(true); };

                right.Children.Add(Step("1", L.T("Modelli da importare")));
                var addRow = new WrapPanel { Margin = new Thickness(0, 8, 0, 8) };
                _addFiles = Theme.Button(Theme.IconText(Icons.Import, L.T("Aggiungi file…"), Theme.Accent, 14), Theme.Kind.Normal, L.T("Scegli uno o più file di modelli"));
                _addFiles.Click += (_, __) => AddFiles();
                _addFolder = Theme.Button(Theme.IconText(Icons.Folder, L.T("Aggiungi una cartella…"), Theme.Warm, 14), Theme.Kind.Normal,
                                          L.T("Tutti i modelli di una cartella e delle sue sottocartelle"));
                _addFolder.Margin = new Thickness(8, 0, 0, 0);
                _addFolder.Click += (_, __) => AddFolder();
                addRow.Children.Add(_addFiles);
                addRow.Children.Add(_addFolder);
                right.Children.Add(addRow);
                var listHost = new Grid();
                _empty = Theme.Label(L.T("Nessun modello scelto: aggiungi dei file o una cartella."), 12, Theme.TextFaint);
                _empty.HorizontalAlignment = HorizontalAlignment.Center;
                _empty.VerticalAlignment = VerticalAlignment.Center;
                listHost.Children.Add(_empty);
                listHost.Children.Add(new ScrollViewer { Content = _list, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Padding = new Thickness(0, 0, 4, 0) });
                right.Children.Add(new Border
                {
                    Child = listHost, Height = 230, Background = Theme.B(Theme.Inset), BorderBrush = Theme.B(Theme.Line), BorderThickness = new Thickness(1),
                    CornerRadius = new CornerRadius(8), Padding = new Thickness(6), Margin = new Thickness(0, 0, 0, 16),
                });

                right.Children.Add(Step("2", L.T("Cartella della libreria")));
                var dest = new DockPanel { Margin = new Thickness(0, 8, 0, 4) };
                var destLabel = Theme.Label(L.T("Per tutti i modelli:"), 12.5, Theme.TextSoft);
                destLabel.VerticalAlignment = VerticalAlignment.Center;
                destLabel.Margin = new Thickness(0, 0, 10, 0);
                DockPanel.SetDock(destLabel, Dock.Left);
                dest.Children.Add(destLabel);
                _defaultFolder = FolderChip("", f => { _folder = f; foreach (var r in _rows.Where(r => !r.FolderSet)) SetRowFolder(r, f, false); UpdateChip(_defaultFolder!, f); });
                _defaultFolder.HorizontalAlignment = HorizontalAlignment.Left;
                dest.Children.Add(_defaultFolder);
                right.Children.Add(dest);
                right.Children.Add(HintSmall(L.T("Puoi cambiare la cartella di un singolo modello dal pulsante cartella sulla sua riga; \"Nuova cartella…\" la crea dentro la libreria.")));
                _folder = StartFolder(_veg);
                UpdateChip(_defaultFolder, _folder);
                SetKind(_veg);

                right.Children.Add(Step("3", L.T("Importa")));
                _overwriteToggle = new Toggle(L.T("Sovrascrivi i modelli che esistono già (stesso nome nella stessa cartella)"), false,
                                              L.T("Se è spento, per ogni modello che esiste già Simpler chiede se sovrascriverlo, rinominarlo o saltarlo"));
                _overwriteToggle.Margin = new Thickness(0, 8, 0, 8);
                _overwriteToggle.Toggled += on => _overwrite = on;
                right.Children.Add(_overwriteToggle);
                // collections: one file with many objects (a pack of plants, of chairs...) -> one model per object
                var splitToggle = new Toggle(L.T("Ogni oggetto del file è un modello a sé (collezioni)"), _split,
                                             L.T("Per i file che contengono più modelli insieme (es. un pacchetto di piante): ogni oggetto principale del file, con i suoi pezzi, diventa un modello della libreria con il suo nome. Il numero di modelli si vede mentre il file viene aperto."));
                splitToggle.Margin = new Thickness(0, 0, 0, 8);
                splitToggle.Toggled += on => _split = on;
                right.Children.Add(splitToggle);
                // «collassa la gerarchia»: one object instead of the tree of its pieces (materials kept on their faces)
                _merge = Settings.Load().MergeOnImport;           // (the same choice as in the menu Importa)
                var mergeToggle = new Toggle(L.T("Unisci i pezzi in un solo oggetto"), _merge,
                                             L.T("Tutti i pezzi del modello diventano un solo oggetto, con tutti i suoi materiali al loro posto: albero della scena pulito, un clic per selezionarlo, vista più leggera. Non si potranno più selezionare o impostare i singoli pezzi (per esempio «Sempre asciutto» solo sugli interni di un'auto). I pezzi ripetuti molte volte (bulloni, sedie) restano copie, per non moltiplicare la memoria. Con «Ogni oggetto è un modello a sé» unisce ogni modello per conto suo"));
                mergeToggle.Margin = new Thickness(0, 0, 0, 8);
                mergeToggle.Toggled += on => { _merge = on; var st = Settings.Load(); st.MergeOnImport = on; st.Save(); };
                right.Children.Add(mergeToggle);
                var pivotRow = new DockPanel { Margin = new Thickness(0, 0, 0, 8) };
                var pivotLab = Theme.Label(L.T("Origine del modello"), 12.5, Theme.TextSoft);
                pivotLab.VerticalAlignment = VerticalAlignment.Center;
                pivotLab.Margin = new Thickness(0, 0, 12, 0);
                pivotRow.Children.Add(pivotLab);
                var pivots = Theme.Segmented(out var pivotButtons,
                    (L.T("Base"), L.T("Al centro della base, nel punto più basso: comodo per appoggiare i modelli (piante, persone, mobili)")),
                    (L.T("Centro"), L.T("Al centro 3D del modello")),
                    (L.T("Come nel file"), L.T("Dove l'aveva messa il programma che ha creato il file")));
                string[] pivotIds = { "base", "center", "keep" };
                Theme.SetSegment(pivotButtons, Array.IndexOf(pivotIds, _pivot));
                for (int pi = 0; pi < pivotButtons.Count; pi++)
                {
                    var idx = pi;
                    pivotButtons[pi].Click += (_, __) => { _pivot = pivotIds[idx]; Theme.SetSegment(pivotButtons, idx); };
                }
                pivots.HorizontalAlignment = HorizontalAlignment.Left;
                pivotRow.Children.Add(pivots);
                right.Children.Add(pivotRow);
                // scale: ×1 = as in the file; a model saved in the wrong units (a person 7 cm tall, a house of 30 km)
                var scaleRow = new DockPanel { Margin = new Thickness(0, 0, 0, 8) };
                var scaleLab = Theme.Label(L.T("Scala per tutti"), 12.5, Theme.TextSoft);
                scaleLab.VerticalAlignment = VerticalAlignment.Center;
                scaleLab.Margin = new Thickness(0, 0, 12, 0);
                scaleRow.Children.Add(scaleLab);
                var x = Theme.Label("×", 13, Theme.TextMuted);
                x.VerticalAlignment = VerticalAlignment.Center;
                x.Margin = new Thickness(0, 0, 4, 0);
                scaleRow.Children.Add(x);
                _scaleBox = Theme.Input(FormatFactor(_scale), true);
                _scaleBox.Width = 64;
                _scaleBox.ToolTip = L.T("Ogni modello viene ingrandito o rimpicciolito di questo fattore (1 = come nel file). Es. 100 per un file in metri letto come centimetri, 2,54 per i pollici");
                _scaleBox.LostFocus += (_, __) => SetScale(ParseFactor(_scaleBox.Text) ?? _scale);
                _scaleBox.KeyDown += (_, e) => { if (e.Key == Key.Enter) SetScale(ParseFactor(_scaleBox.Text) ?? _scale); };
                scaleRow.Children.Add(_scaleBox);
                var chips = FactorChips(f => SetScale(f));
                chips.Margin = new Thickness(8, 0, 0, 0);
                scaleRow.Children.Add(chips);
                right.Children.Add(scaleRow);
                var checkToggle = new Toggle(L.T("Controlla la scala dopo ogni modello"), _checkScale,
                    L.T("Dopo ogni modello importato Simpler si ferma: vedi la miniatura e le dimensioni, puoi cambiare la scala solo di quel modello e poi prosegui con il successivo"));
                checkToggle.Margin = new Thickness(0, 0, 0, 8);
                checkToggle.Toggled += on => _checkScale = on;
                right.Children.Add(checkToggle);
                right.Children.Add(_checkPanel);
                _bar = new ProgressBar { Height = 6, Minimum = 0, Maximum = 1, Value = 0, Foreground = Theme.B(Theme.Accent), Background = Theme.B("#1A2842"), BorderThickness = new Thickness(0), Margin = new Thickness(0, 4, 0, 6) };
                right.Children.Add(_bar);
                _status = Theme.Label("", 12, Theme.TextMuted);
                _status.TextTrimming = TextTrimming.CharacterEllipsis;
                right.Children.Add(_status);
                var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 14, 0, 0) };
                _close = Theme.Button(L.T("Chiudi"), Theme.Kind.Ghost);
                _close.Click += (_, __) => OnCloseButton();
                _go = Theme.Button(L.T("Importa"), Theme.Kind.Primary);
                _go.Margin = new Thickness(8, 0, 0, 0);
                _go.MinWidth = 150;
                _go.Click += async (_, __) => await Run();
                buttons.Children.Add(_close);
                buttons.Children.Add(_go);
                // (Luca: «serve una scroll bar verticale») with the scale check open the steps no longer fit on the screen:
                // the body scrolls, the buttons stay in sight at the bottom
                buttons.Margin = new Thickness(0, 10, 2, 0);
                Footer.Children.Add(buttons);
                Body.Children.Add(grid);
                EnableBodyScroll();
                Body.Margin = new Thickness(0, 0, 0, 0);
                Refresh();
                KeyDown += (_, e) => { if (e.Key == Key.Escape) OnCloseButton(); };
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

            static TextBlock HintSmall(string text) => new TextBlock { Text = text, TextWrapping = TextWrapping.Wrap, FontSize = 11.5, Foreground = Theme.B(Theme.TextFaint), Margin = new Thickness(0, 2, 0, 14) };

            protected override void OnCloseButton()
            {
                // (Luca: «si resta in un loop infinito») closed while it waits for the scale check: hidden, it waited for an
                // answer nobody could give, and Simpler stayed busy («… sta lavorando in background») - closing it now
                // is «Ferma l'importazione» (the models already imported stay in the library)
                if (_checkWait is { Task.IsCompleted: false } wait) wait.TrySetResult(false);
                if (_running)
                {
                    // the import goes on in the background; the window comes back from the Importa menu
                    Hide();
                    _mw.Status(L.T("Importazione nella libreria in corso in background…"));
                    return;
                }
                Close();
            }

            // ---------------------------------------------------------------- scale

            static readonly double[] QuickFactors = { 0.01, 0.1, 2.54, 10, 25.4, 100 };

            static string FormatFactor(double f) => f.ToString("0.####", System.Globalization.CultureInfo.CurrentCulture);

            static double? ParseFactor(string text)
            {
                var t = (text ?? "").Trim().TrimStart('×', 'x', 'X', '*').Trim().Replace(',', '.');
                return double.TryParse(t, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var v)
                       && v >= 1e-4 && v <= 1e4 ? v : null;
            }

            static WrapPanel FactorChips(Action<double> pick)
            {
                var w = new WrapPanel { VerticalAlignment = VerticalAlignment.Center };
                foreach (var f in new[] { 1.0 }.Concat(QuickFactors))
                {
                    var b = Theme.Button("×" + FormatFactor(f), Theme.Kind.Ghost, f == 1 ? L.T("Come nel file") : null);
                    b.MinHeight = 24; b.FontSize = 11.5; b.Padding = new Thickness(7, 0, 7, 0); b.Margin = new Thickness(0, 0, 4, 0);
                    b.Click += (_, __) => pick(f);
                    w.Children.Add(b);
                }
                return w;
            }

            void SetScale(double f)
            {
                _scale = f;
                _scaleBox.Text = FormatFactor(f);
                foreach (var r in _rows.Where(r => r.State.Text != "✓"))
                    r.FactorBox.Text = FormatFactor(f);          // (each row can then be changed on its own)
            }

            // sizes measured before the import, one file after the other (by the second Blender: the scene is not touched)
            bool _probing;
            async Task ProbeLoop()
            {
                if (_probing || _mw._api == null) return;
                _probing = true;
                try
                {
                    while (!_running)
                    {
                        var row = _rows.FirstOrDefault(r => r.Probe == null && !r.ProbeFailed);
                        if (row == null) break;
                        row.Probing = true;
                        try
                        {
                            var r = await _mw._api.Post("models/probe", new JsonObject { ["path"] = row.Path });
                            if ((int?)r["pending"] is int rid)
                            {
                                string state = "running";
                                for (int k = 0; k < 2400 && state == "running" && !_running; k++)
                                {
                                    await Task.Delay(250);
                                    try { state = (string?)(await _mw._api.Get($"material/preview/status?id={rid}"))["state"] ?? ""; } catch { state = ""; }
                                }
                                if (_running) break;               // the import started: it measures them itself
                                r = state == "done" ? await _mw._api.Post("models/probe", new JsonObject { ["path"] = row.Path }) : new JsonObject();
                            }
                            if (r["sizeCm"] is JsonArray a && a.Count == 3) row.Probe = a.Select(v => (double?)v ?? 0).ToArray();
                            else row.ProbeFailed = true;
                        }
                        catch { row.ProbeFailed = true; }
                        row.Probing = false;
                        ShowRowSize(row);
                    }
                }
                finally { _probing = false; }
            }

            /// <summary>Very small or very big for anything one puts in a scene: probably the wrong units.</summary>
            static bool Odd(double[] s) => s.Length == 3 && s.Max() > 0 && (s.Max() < 3 || s.Max() > 200000);

            void ShowRowSize(Row row)
            {
                if (row.State.Text == "✓") return;               // (imported: the library size is shown)
                if (row.Probe == null)
                {
                    row.Size.Text = row.ProbeFailed ? "–" : L.T("misuro…");
                    row.Size.ToolTip = row.ProbeFailed ? L.T("Dimensioni non lette: si vedranno dopo l'import") : null;
                    row.Size.Foreground = Theme.B(Theme.TextFaint);
                    return;
                }
                var p = row.Probe;
                var f = row.Factor;
                var scaled = p.Select(v => v * f).ToArray();
                bool changed = Math.Abs(f - 1) > 1e-9;
                row.Size.Text = changed ? L.F("alto {0} → {1}", Len(p[2]), Len(scaled[2])) : SizeText(p);
                row.Size.ToolTip = L.F("Nel file: {0}", SizeText(p)) + (changed ? "\n" + L.F("Con la scala ×{0}: {1}", FormatFactor(f), SizeText(scaled)) : "")
                                   + (Odd(scaled) ? "\n" + L.T("Sembra molto piccolo o molto grande: controlla la scala") : "");
                row.Size.Foreground = Theme.B(Odd(scaled) ? Theme.Warm : changed ? Theme.Accent : Theme.TextSoft);
            }

            /// <summary>cm as the user reads them: mm, cm, m or km.</summary>
            static string Len(double cm)
            {
                var c = System.Globalization.CultureInfo.CurrentCulture;
                if (cm < 1) return (cm * 10).ToString("0.#", c) + " mm";
                if (cm < 100) return cm.ToString("0.#", c) + " cm";
                if (cm < 100000) return (cm / 100).ToString("0.##", c) + " m";
                return (cm / 100000).ToString("0.##", c) + " km";
            }

            static string SizeText(double[] s) => s.Length == 3 && s.Any(v => v > 0)
                ? L.F("{0} × {1} · alto {2}", Len(s[0]), Len(s[1]), Len(s[2])) : "";

            List<JsonObject> ImportedModels(string id, string path) => _mw._models.OfType<JsonObject>()
                .Where(m => (string?)m["id"] == id || (_split && string.Equals((string?)m["source"], path, StringComparison.OrdinalIgnoreCase)))
                .ToList();

            static double[] SizeOf(JsonObject m) => (m["sizeCm"] as JsonArray)?.Select(v => (double?)v ?? 0).ToArray() ?? Array.Empty<double>();

            /// <summary>The pause after a model: its thumbnail and size, a factor for it alone, then on to the next one.
            /// Returns false when the user stops the import.</summary>
            async Task<bool> CheckScale(Row row, string name, string id)
            {
                var models = ImportedModels(id, row.Path);
                var panel = new StackPanel();
                var head = Theme.Label(models.Count == 1 ? L.F("Controlla la scala: {0}", name) : L.F("Controlla la scala: {0} ({1} modelli)", name, models.Count),
                                       13, Theme.Text, FontWeights.SemiBold);
                panel.Children.Add(head);
                var line = new DockPanel { Margin = new Thickness(0, 8, 0, 0) };
                var thumbFile = models.Count > 0 ? (string?)models[0]["thumb"] ?? "" : "";
                if (File.Exists(thumbFile))
                {
                    try
                    {
                        var bmp = new BitmapImage();
                        bmp.BeginInit(); bmp.CacheOption = BitmapCacheOption.OnLoad; bmp.CreateOptions = BitmapCreateOptions.IgnoreImageCache;
                        bmp.UriSource = new Uri(thumbFile); bmp.DecodePixelWidth = 128; bmp.EndInit(); bmp.Freeze();
                        var img = new Border { Width = 72, Height = 72, CornerRadius = new CornerRadius(8), ClipToBounds = true, Margin = new Thickness(0, 0, 12, 0),
                                               Child = new Image { Source = bmp, Stretch = Stretch.UniformToFill } };
                        DockPanel.SetDock(img, Dock.Left);
                        line.Children.Add(img);
                    }
                    catch { }
                }
                var info = new StackPanel();
                // the tallest model of the file stands for all (a collection: the factor goes to every one)
                var size = models.Select(SizeOf).Where(v => v.Length == 3 && v.Any(x => x > 0)).OrderByDescending(v => v[2]).FirstOrDefault()
                           ?? row.Probe?.Select(v => v * row.Factor).ToArray() ?? new double[] { 0, 0, 0 };
                var now = Theme.Label(SizeText(size) is var nowText && nowText != "" ? L.F("Ora: {0}", nowText) : L.T("Dimensioni non lette"), 12.5, Theme.TextSoft);
                info.Children.Add(now);
                var factorRow = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 6, 0, 0) };
                factorRow.Children.Add(new TextBlock { Text = "×", FontSize = 13, Foreground = Theme.B(Theme.TextMuted), VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 4, 0) });
                var box = Theme.Input("1", true);
                box.Width = 64;
                factorRow.Children.Add(box);
                var after = Theme.Label("", 12, Theme.Accent);
                void UpdateAfter()
                {
                    var f = ParseFactor(box.Text);
                    after.Text = f == null ? L.T("Fattore non valido") : Math.Abs(f.Value - 1) < 1e-9 ? L.T("Resta com'è")
                        : L.F("Diventerà: {0}", SizeText(size.Select(v => v * f.Value).ToArray()));
                }
                box.TextChanged += (_, __) => UpdateAfter();
                var chips = FactorChips(f => box.Text = FormatFactor(f));
                chips.Margin = new Thickness(8, 0, 0, 0);
                factorRow.Children.Add(chips);
                info.Children.Add(factorRow);
                after.Margin = new Thickness(0, 6, 0, 0);
                info.Children.Add(after);
                var forNext = new CheckBox { Content = L.T("Usa questo fattore anche per i prossimi modelli (senza più fermarsi)"), Foreground = Theme.B(Theme.TextMuted), Margin = new Thickness(0, 6, 0, 0) };
                info.Children.Add(forNext);
                line.Children.Add(info);
                panel.Children.Add(line);
                var btns = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 10, 0, 0) };
                var stop = Theme.Button(L.T("Ferma l'importazione"), Theme.Kind.Ghost, L.T("I modelli già importati restano nella libreria"));
                var go = Theme.Button(L.T("Prosegui"), Theme.Kind.Primary, L.T("Applica la scala (se cambiata) e passa al modello successivo"));
                go.Margin = new Thickness(8, 0, 0, 0);
                go.MinWidth = 120;
                btns.Children.Add(stop);
                btns.Children.Add(go);
                panel.Children.Add(btns);
                UpdateAfter();
                _checkPanel.Child = new Border
                {
                    Child = panel, Background = Theme.B(Theme.Raised), BorderBrush = Theme.B(Theme.Accent), BorderThickness = new Thickness(1),
                    CornerRadius = new CornerRadius(10), Padding = new Thickness(14), Margin = new Thickness(0, 4, 0, 10),
                };
                _checkPanel.Visibility = Visibility.Visible;
                _checkPanel.Dispatcher.BeginInvoke(() => _checkPanel.BringIntoView(), System.Windows.Threading.DispatcherPriority.Loaded);
                if (!IsVisible) Show();
                Activate();
                box.Focus(); box.SelectAll();
                _checkWait = new TaskCompletionSource<bool>();
                stop.Click += (_, __) => _checkWait?.TrySetResult(false);
                go.Click += (_, __) => { if (ParseFactor(box.Text) != null) _checkWait?.TrySetResult(true); };
                box.KeyDown += (_, e) => { if (e.Key == Key.Enter && ParseFactor(box.Text) != null) _checkWait?.TrySetResult(true); };
                var goOn = await _checkWait.Task;
                _checkPanel.Visibility = Visibility.Collapsed;
                _checkPanel.Child = null;
                if (!goOn) return false;
                var factor = ParseFactor(box.Text) ?? 1.0;
                if (forNext.IsChecked == true)
                {
                    _checkScale = false;
                    SetScale(_scale * factor);           // the next files: the global factor times this correction
                }
                if (Math.Abs(factor - 1) < 1e-9) return true;
                _status.Text = L.F("Scala ×{0}: {1}", FormatFactor(factor), name);
                try
                {
                    var r = await _mw._api!.Post("models/rescale", new JsonObject { ["id"] = id, ["source"] = _split ? row.Path : "", ["factor"] = factor });
                    foreach (var rid in (r["pending"] as JsonArray ?? new JsonArray()).Select(v => (int?)v ?? -1).Where(v => v >= 0))
                    {
                        for (int k = 0; k < 600; k++)
                        {
                            await Task.Delay(300);
                            JsonObject? st = null;
                            try { st = await _mw._api.Get($"material/preview/status?id={rid}"); } catch { }
                            var state = (string?)st?["state"] ?? "";
                            if (state != "running" && state != "") break;
                        }
                    }
                }
                catch (Exception ex) { _status.Text = ex.Message; }
                return true;
            }

            // ---------------------------------------------------------------- the list

            /// <summary>Files given by the program (Pack Studio: models converted for the import), as if chosen.</summary>
            internal void AddPaths(IEnumerable<string> paths)
            {
                foreach (var p in paths) AddPath(p);
                Refresh();
            }

            void AddFiles()
            {
                var dlg = new Microsoft.Win32.OpenFileDialog
                {
                    Multiselect = true, Title = L.T("Scegli i modelli da importare nella libreria"), InitialDirectory = _mw.StartFolder("model"),
                    Filter = L.T("Modelli 3D") + "|" + string.Join(";", Formats.Select(f => "*" + f)) + "|" + L.T("Tutti i file") + "|*.*",
                };
                if (dlg.ShowDialog(this) != true) return;
                _mw.Keep("model", dlg.FileName);
                foreach (var f in dlg.FileNames) AddPath(f);
                Refresh();
            }

            void AddFolder()
            {
                var dlg = new Microsoft.Win32.OpenFolderDialog { Title = L.T("Cartella con i modelli da importare (anche le sottocartelle)"), InitialDirectory = _mw.StartFolder("modelfolder") };
                if (dlg.ShowDialog(this) != true) return;
                _mw.Keep("modelfolder", dlg.FolderName, true);
                int n = 0;
                try
                {
                    foreach (var f in Directory.EnumerateFiles(dlg.FolderName, "*.*", SearchOption.AllDirectories))
                    {
                        if (!Formats.Contains(System.IO.Path.GetExtension(f).ToLowerInvariant())) continue;
                        if (AddPath(f)) n++;
                        if (n >= 500) break;
                    }
                }
                catch (Exception ex) { _status.Text = ex.Message; }
                if (n == 0) _status.Text = L.T("Nessun modello trovato in quella cartella");
                Refresh();
            }

            bool AddPath(string path)
            {
                if (_rows.Any(r => string.Equals(r.Path, path, StringComparison.OrdinalIgnoreCase))) return false;
                var row = new Row { Path = path, Folder = _folder };
                var grid = new Grid { Margin = new Thickness(0, 0, 0, 4) };
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(26) });
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(150) });
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(64) });
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(160) });
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(30) });
                row.State = new TextBlock { Text = System.IO.Path.GetExtension(path).TrimStart('.').ToUpperInvariant(), FontSize = 9.5, FontWeight = FontWeights.SemiBold,
                                            Foreground = Theme.B(Theme.TextFaint), VerticalAlignment = VerticalAlignment.Center };
                grid.Children.Add(row.State);
                row.Name = Theme.Input(System.IO.Path.GetFileNameWithoutExtension(path));
                row.Name.Margin = new Thickness(0, 0, 6, 0);
                row.Name.ToolTip = path;
                Grid.SetColumn(row.Name, 1);
                grid.Children.Add(row.Name);
                row.Size = new TextBlock { FontSize = 11, Foreground = Theme.B(Theme.TextFaint), VerticalAlignment = VerticalAlignment.Center,
                                           TextTrimming = TextTrimming.CharacterEllipsis, Margin = new Thickness(0, 0, 6, 0), Text = L.T("misuro…") };
                Grid.SetColumn(row.Size, 2);
                grid.Children.Add(row.Size);
                // the scale of this model: ×1 = as in the file
                var fx = new DockPanel { Margin = new Thickness(0, 0, 6, 0) };
                var xl = new TextBlock { Text = "×", FontSize = 12, Foreground = Theme.B(Theme.TextMuted), VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 3, 0) };
                fx.Children.Add(xl);
                row.Factor = _scale;
                row.FactorBox = Theme.Input(FormatFactor(_scale), true);
                row.FactorBox.Padding = new Thickness(4, 2, 4, 2);
                row.FactorBox.ToolTip = L.T("Scala di questo modello: 1 = come nel file, 25,4 = 25,4 volte più grande, 0,01 = cento volte più piccolo");
                row.FactorBox.TextChanged += (_, __) =>
                {
                    if (ParseFactor(row.FactorBox.Text) is double f) { row.Factor = f; row.FactorBox.BorderBrush = Theme.B(Theme.Line); }
                    else row.FactorBox.BorderBrush = Theme.B(Theme.Danger);
                    ShowRowSize(row);
                };
                fx.Children.Add(row.FactorBox);
                Grid.SetColumn(fx, 3);
                grid.Children.Add(fx);
                row.FolderButton = FolderChip(row.Folder, f => SetRowFolder(row, f, true));
                Grid.SetColumn(row.FolderButton, 4);
                grid.Children.Add(row.FolderButton);
                var rm = Theme.Button("×", Theme.Kind.Ghost, L.T("Togli dall'elenco"));
                rm.Padding = new Thickness(6, 0, 6, 0);
                rm.Click += (_, __) => { if (_running) return; _rows.Remove(row); _list.Children.Remove(grid); Refresh(); };
                Grid.SetColumn(rm, 5);
                grid.Children.Add(rm);
                row.View = grid;
                _rows.Add(row);
                _list.Children.Add(grid);
                _ = ProbeLoop();
                return true;
            }

            void SetRowFolder(Row r, string f, bool chosen)
            {
                r.Folder = f;
                r.FolderSet |= chosen;
                UpdateChip(r.FolderButton, f);
            }

            void Refresh()
            {
                _empty.Visibility = _rows.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
                _go.IsEnabled = !_running && _rows.Count > 0;
                _go.Content = _rows.Count <= 1 ? L.T("Importa") : L.F("Importa {0} modelli", _rows.Count);
            }

            // ---------------------------------------------------------------- folder chooser

            Button FolderChip(string folder, Action<string> chosen)
            {
                var b = Theme.Button("", Theme.Kind.Normal, L.T("Cartella della libreria dove va il modello"));
                b.MinHeight = 28; b.Height = 28; b.FontSize = 12; b.Padding = new Thickness(8, 0, 8, 0);
                b.HorizontalContentAlignment = HorizontalAlignment.Left;
                UpdateChip(b, folder);
                b.Tag = folder;
                b.Click += (_, __) => ShowFolderTree(b, (string?)b.Tag ?? "", f => { b.Tag = f; chosen(f); });
                return b;
            }

            /// <summary>(1.78.4, Luca: «non si può avere questa lista più chiara? e partire da dove si trova la libreria?»)
            /// The folders of the library as a tree: «Modelli 3D» and «Vegetazione» with their branches, folder icons,
            /// branches that open and close, opened on the folder chosen now (shown and highlighted). The Simpler folders
            /// are left out when they are locked (nothing can be put there).</summary>
            void ShowFolderTree(FrameworkElement anchor, string current, Action<string> chosen)
            {
                var popup = new System.Windows.Controls.Primitives.Popup
                {
                    PlacementTarget = anchor, Placement = System.Windows.Controls.Primitives.PlacementMode.Bottom, StaysOpen = false,
                    AllowsTransparency = true, VerticalOffset = 4,
                };
                bool hidden(string f) => _mw.ReadOnlyFolder(f);
                var folders = _mw._modelFolders.Where(f => !hidden(f)).ToList();
                var veg = _mw._vegRoot;
                List<string> kids(string parent) => folders
                    .Where(f => parent == "" ? !f.Contains('/') && f != veg : ParentFolder(f) == parent)
                    .OrderBy(f => f, StringComparer.CurrentCultureIgnoreCase).ToList();
                var open = new HashSet<string>(StringComparer.Ordinal) { current };
                for (var a = current; a != ""; a = ParentFolder(a)) open.Add(ParentFolder(a));
                if (Under(current, veg)) open.Add(veg); else open.Add("");
                var list = new StackPanel { Margin = new Thickness(4) };
                Border? currentRow = null;
                string pick = current;

                UIElement Node(string path, string label, int depth, bool root)
                {
                    var box = new StackPanel();
                    var children = kids(path);
                    var childBox = new StackPanel { Visibility = open.Contains(path) && children.Count > 0 ? Visibility.Visible : Visibility.Collapsed };
                    var row = new Grid { Margin = new Thickness(depth * 18, 0, 0, 0) };
                    row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(20) });
                    row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
                    row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                    if (children.Count > 0)
                    {
                        var chev = Theme.Icon(Icons.Chevron, Theme.TextMuted, 11, 1.8);
                        chev.RenderTransformOrigin = new Point(0.5, 0.5);
                        chev.RenderTransform = new RotateTransform(childBox.Visibility == Visibility.Visible ? 90 : 0);
                        var tog = new Border { Child = chev, Background = Brushes.Transparent, Cursor = Cursors.Hand, Width = 20, Height = 26,
                                               ToolTip = L.T("Apri o chiudi le sottocartelle") };
                        chev.HorizontalAlignment = HorizontalAlignment.Center; chev.VerticalAlignment = VerticalAlignment.Center;
                        tog.MouseLeftButtonUp += (_, e) =>
                        {
                            e.Handled = true;
                            var show = childBox.Visibility != Visibility.Visible;
                            childBox.Visibility = show ? Visibility.Visible : Visibility.Collapsed;
                            chev.RenderTransform = new RotateTransform(show ? 90 : 0);
                        };
                        row.Children.Add(tog);
                    }
                    var icon = Theme.Icon(root ? (Under(path, veg) ? Icons.Leaf : Icons.Mesh) : Icons.Folder, root ? Theme.Accent : Theme.Warm, 14, 1.6);
                    icon.Margin = new Thickness(0, 0, 8, 0);
                    icon.VerticalAlignment = VerticalAlignment.Center;
                    Grid.SetColumn(icon, 1);
                    row.Children.Add(icon);
                    var t = Theme.Label(label, root ? 13 : 12.5, path == current ? Theme.Text : Theme.TextSoft, root || path == current ? FontWeights.SemiBold : FontWeights.Normal);
                    t.VerticalAlignment = VerticalAlignment.Center;
                    t.TextTrimming = TextTrimming.CharacterEllipsis;
                    Grid.SetColumn(t, 2);
                    row.Children.Add(t);
                    var line = new Border { Child = row, Padding = new Thickness(4, 2, 8, 2), CornerRadius = new CornerRadius(6), Cursor = Cursors.Hand, MinHeight = 28,
                                            Background = path == current ? Theme.B(Theme.Selected) : Brushes.Transparent,
                                            ToolTip = path == "" ? L.T("Modelli 3D (cartella principale)") : path };
                    if (path == current) currentRow = line;
                    line.MouseEnter += (_, __) => { if (path != current) line.Background = Theme.B(Theme.Inset); };
                    line.MouseLeave += (_, __) => { if (path != current) line.Background = Brushes.Transparent; };
                    line.MouseLeftButtonUp += (_, __) => { popup.IsOpen = false; chosen(path); };
                    box.Children.Add(line);
                    foreach (var c in children) childBox.Children.Add(Node(c, FolderName(c), depth + 1, false));
                    box.Children.Add(childBox);
                    return box;
                }
                list.Children.Add(Node("", L.T("Modelli 3D"), 0, true));
                if (folders.Contains(veg)) list.Children.Add(Node(veg, L.T("Vegetazione"), 0, true));
                var scroll = new ScrollViewer { Content = list, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, MaxHeight = 420 };
                var add = Theme.Button(Theme.IconText(Icons.Plus, L.T("Nuova cartella qui…"), Theme.Accent, 13), Theme.Kind.Ghost,
                                       L.T("Crea una sottocartella dentro la cartella scelta ora"));
                add.HorizontalAlignment = HorizontalAlignment.Left;
                add.Margin = new Thickness(6, 4, 6, 6);
                add.Click += async (_, __) =>
                {
                    popup.IsOpen = false;
                    var p = await _mw.CreateFolder(pick, "model");
                    if (p != null) chosen(p);
                };
                var dock = new DockPanel();
                DockPanel.SetDock(add, Dock.Bottom);
                dock.Children.Add(add);
                dock.Children.Add(new Border { Height = 1, Background = Theme.B(Theme.Line), Margin = new Thickness(0, 2, 0, 0), VerticalAlignment = VerticalAlignment.Bottom });
                DockPanel.SetDock(dock.Children[1], Dock.Bottom);
                dock.Children.Add(scroll);
                popup.Child = new Border
                {
                    Child = dock, Width = Math.Max(360, anchor.ActualWidth), Background = Theme.B(Theme.Panel), BorderBrush = Theme.B(Theme.Line),
                    BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(8),
                };
                popup.Opened += (_, __) => currentRow?.BringIntoView();
                popup.IsOpen = true;
            }

            /// <summary>(1.78.4, Luca: «non si può partire da dove si trova la libreria?») the folder the library shows now
            /// (models or plants, yours or Simpler's), when it suits the kind of import; never a locked Simpler folder.</summary>
            string StartFolder(bool veg)
            {
                var f = _mw.ModelFolderShown();
                var vr = _mw._vegRoot;
                bool isVeg = Under(f, vr) || _mw.IsVegFolder(f);
                if (veg && !isVeg) f = vr;
                if (!veg && isVeg) f = "";
                if (f == PrimitiveFolder || Under(f, _mw.SimplerPrimitives) || _mw.ReadOnlyFolder(f))
                    f = veg ? vr : "";
                if (f != "" && !_mw._modelFolders.Contains(f)) f = veg ? vr : "";
                return f;
            }

            static void UpdateChip(Button b, string folder)
            {
                b.Tag = folder;
                var sp = Theme.IconText(Icons.Folder, folder == "" ? L.T("Modelli 3D") : folder.Replace("/", " / "), Theme.Warm, 13);
                b.Content = sp;
                b.ToolTip = folder == "" ? L.T("Modelli 3D (cartella principale)") : folder;
            }

            // ---------------------------------------------------------------- import

            async Task Run()
            {
                if (_running || _rows.Count == 0 || _mw._api == null) return;
                // conflicts first (same name in the same folder), so the import then runs without questions
                var plan = new List<(Row row, string name, string replace)>();
                string? always = _overwrite ? "overwrite" : null;
                var taken = _mw._models.OfType<JsonObject>()
                    .Select(m => (id: (string?)m["id"] ?? "", key: Slot((string?)m["folder"] ?? "", (string?)m["name"] ?? ""))).ToList();
                foreach (var r in _rows)
                {
                    var name = r.Name.Text.Trim();
                    if (name == "") name = System.IO.Path.GetFileNameWithoutExtension(r.Path);
                    var existing = taken.FirstOrDefault(t => t.key == Slot(r.Folder, name));
                    var replace = "";
                    if (!_split && (!string.IsNullOrEmpty(existing.id) || plan.Any(p => Slot(p.row.Folder, p.name) == Slot(r.Folder, name))))
                    {
                        var choice = always;
                        if (choice == null)
                        {
                            var (c, all) = ConflictDialog.Ask(this, name, r.Folder);
                            choice = c;
                            if (all) always = c;
                        }
                        if (choice == "skip") { r.State.Text = "–"; r.State.ToolTip = L.T("Saltato: esiste già"); continue; }
                        if (choice == "rename")
                        {
                            var n = 2;
                            while (taken.Any(t => t.key == Slot(r.Folder, $"{name} ({n})")) || plan.Any(p => Slot(p.row.Folder, p.name) == Slot(r.Folder, $"{name} ({n})"))) n++;
                            name = $"{name} ({n})";
                        }
                        else replace = existing.id ?? "";
                    }
                    plan.Add((r, name, replace));
                }
                if (plan.Count == 0) { _status.Text = L.T("Niente da importare"); return; }
                // sizes that look wrong (a person 7 cm tall, a chair 30 km wide): one question before starting
                var odd = plan.Where(p => p.row.Probe != null && Odd(p.row.Probe.Select(v => v * p.row.Factor).ToArray())).ToList();
                if (odd.Count > 0 && !_checkScale)
                {
                    var names = string.Join("\n", odd.Take(6).Select(p => "• " + p.name + "  (" + SizeText(p.row.Probe!.Select(v => v * p.row.Factor).ToArray()) + ")"))
                                + (odd.Count > 6 ? "\n…" : "");
                    var ans = Msg.Show(this, L.F("{0} modelli sembrano molto piccoli o molto grandi:", odd.Count) + "\n\n" + names + "\n\n" +
                                              L.T("Importarli così? (No = torna all'elenco per cambiare la scala nella colonna ×)"),
                                              L.T("Controlla la scala"), MessageBoxButton.YesNo, MessageBoxImage.Question);
                    if (ans != MessageBoxResult.Yes) { _status.Text = L.T("Cambia la scala nella colonna × e premi di nuovo Importa"); return; }
                }

                _running = true; _cancel = false;
                Refresh();
                _addFiles.IsEnabled = _addFolder.IsEnabled = false;
                int ok = 0, failed = 0;
                string lastFolder = "";
                for (int i = 0; i < plan.Count && !_cancel; i++)
                {
                    var (row, name, replace) = plan[i];
                    row.State.Text = "…";
                    row.State.Foreground = Theme.B(Theme.Accent);
                    _status.Text = L.F("{0} di {1}: {2}", i + 1, plan.Count, name);
                    _bar.Value = (double)i / plan.Count;
                    string error = "";
                    string lastId = "";
                    int parts = 1;
                    try
                    {
                        var r = await _mw._api.Post("models/import", new JsonObject
                        {
                            ["path"] = row.Path, ["name"] = name, ["folder"] = row.Folder, ["replace"] = _split ? "" : replace,
                            ["split"] = _split, ["pivot"] = _pivot, ["scale"] = row.Factor, ["merge"] = _merge,
                        });
                        var id = (string?)r["id"] ?? "";
                        lastId = id;
                        if ((int?)r["pending"] is int rid)
                        {
                            var t0 = DateTime.Now;
                            while (true)
                            {
                                await Task.Delay(400);
                                JsonObject? st = null;
                                try { st = await _mw._api.Get($"material/preview/status?id={rid}"); } catch { }
                                var state = (string?)st?["state"] ?? "";
                                var secs = (DateTime.Now - t0).TotalSeconds;
                                int done = (int?)st?["done"] ?? 0, total = (int?)st?["total"] ?? 0;
                                if (total > 0)
                                {
                                    // the file is open: its models are counted, the bar moves model by model
                                    parts = total;
                                    row.State.Text = $"{done}/{total}";
                                    var cur = (string?)st?["current"] ?? "";
                                    _status.Text = L.F("{0} di {1}: {2}", i + 1, plan.Count, name) +
                                                   (total > 1 ? " · " + L.F("modello {0} di {1}", Math.Min(done + 1, total), total) + (cur != "" ? ": " + cur : "") : "");
                                    _bar.Value = (i + Math.Min(0.98, (done + 0.5) / total)) / plan.Count;
                                }
                                else _bar.Value = (i + Math.Min(0.15, secs / 60.0)) / plan.Count;   // opening the file
                                if (state == "running" || state == "") { if (secs < 1800) continue; error = L.T("tempo scaduto"); break; }
                                if (state != "done") error = (string?)st?["error"] ?? state;
                                break;
                            }
                        }
                        if (error != "")
                            try { await _mw._api.Post("models/importfailed", new { id }); } catch { }
                    }
                    catch (Exception ex) { error = ex.Message; }
                    if (error == "")
                    {
                        ok += parts;
                        lastFolder = row.Folder;
                        row.State.Text = "✓";
                        row.State.Foreground = Theme.B("#4FD18B");
                        row.State.ToolTip = parts > 1 ? L.F("Importato: {0} modelli", parts) : L.T("Importato");
                    }
                    else
                    {
                        failed++;
                        row.State.Text = "✗";
                        row.State.Foreground = Theme.B(Theme.Danger);
                        row.State.ToolTip = error;
                        row.Name.ToolTip = row.Path + "\n" + error;
                    }
                    _bar.Value = (double)(i + 1) / plan.Count;
                    await _mw.ReloadModels();          // the tiles appear one by one in the library
                    if (error == "")
                    {
                        if (_checkScale)
                        {
                            if (!await CheckScale(row, name, lastId)) _cancel = true;
                            await _mw.ReloadModels();      // new size and thumbnail after a change of scale
                        }
                        var models = ImportedModels(lastId, row.Path);
                        if (_veg && models.Count > 0)
                        {
                            // the plant: Fogliame on its leaves and wood, into Vegetazione/<kind>
                            row.State.Text = "…";
                            row.State.Foreground = Theme.B(Theme.Accent);
                            _status.Text = L.F("{0}: riconosco foglie e legno…", name);
                            var vr = await _mw.MakeVegetation(models.Select(m => (string?)m["id"] ?? "").Where(x => x != "").ToList(), null, null, false);
                            row.State.Text = vr == null ? "!" : "✓";
                            row.State.Foreground = vr == null ? Theme.B(Theme.Warm) : Theme.B("#4FD18B");
                            if (vr != null)
                            {
                                row.State.ToolTip = L.F("Foglie: {0} · legno: {1}", vr.Value.leaves, vr.Value.wood);
                                lastFolder = vr.Value.folder != "" ? vr.Value.folder : lastFolder;
                            }
                            else row.State.ToolTip = L.T("Importato, ma foglie e legno non riconosciuti: tasto destro sulla pianta, «Converti in vegetazione…»");
                            await _mw.ReloadModels();
                            models = ImportedModels(lastId, row.Path);
                        }
                        if (models.Count == 1) row.Size.Text = SizeText(SizeOf(models[0]));
                        else if (models.Count > 1) row.Size.Text = L.F("{0} modelli", models.Count);
                        row.Size.ToolTip = row.Size.Text;
                    }
                }
                _running = false;
                _addFiles.IsEnabled = _addFolder.IsEnabled = true;
                var summary = failed == 0 ? L.F("Fatto: {0} modelli nella libreria", ok)
                                          : L.F("Fatto: {0} importati, {1} non riusciti (passa sulla ✗ per il motivo)", ok, failed);
                _status.Text = summary;
                _mw.Status(summary, failed > 0);
                // the done rows leave the list; the failed ones stay, to try again
                foreach (var p in plan.Where(p => p.row.State.Text == "✓").ToList())
                {
                    _rows.Remove(p.row);
                    _list.Children.Remove(p.row.View);
                }
                Refresh();
                if (_veg && lastFolder.StartsWith(_mw.SimplerPlants, StringComparison.Ordinal)) { _mw._vegSimFolder = lastFolder; _mw._libraryTab = "simplerplants"; }
                else if (_veg) { _mw._vegFolder = _mw.IsVegFolder(lastFolder) ? lastFolder : _mw._vegRoot; _mw._libraryTab = "myplants"; }
                else _mw._libraryTab = _mw.ModelTabFor(lastFolder, true);     // (1.78.4: a model imported into Simpler shows there)
                _mw.RenderLibrary();
                if (!IsVisible) Show();
            }

            static string Slot(string folder, string name) => (folder + "|" + name).ToLowerInvariant();
        }

        /// <summary>A model that already exists in the library: overwrite, rename or skip (and the same for the next ones).</summary>
        sealed class ConflictDialog : ThemedDialog
        {
            string _choice = "skip";
            readonly CheckBox _all;

            ConflictDialog(string name, string folder, bool saving = false) : base(L.T("Modello già presente"), 460)
            {
                var sp = Body;
                var t = new TextBlock
                {
                    Text = L.F("Nella cartella \"{0}\" c'è già un modello che si chiama \"{1}\". Cosa faccio?", folder == "" ? L.T("Modelli 3D") : folder, name),
                    TextWrapping = TextWrapping.Wrap, FontSize = 13, Foreground = Theme.B(Theme.TextSoft), Margin = new Thickness(0, 0, 0, 14),
                };
                sp.Children.Add(t);
                _all = new CheckBox { Content = L.T("Fai lo stesso per i prossimi"), Foreground = Theme.B(Theme.TextMuted), Margin = new Thickness(0, 0, 0, 16) };
                if (!saving) sp.Children.Add(_all);
                var b = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right };
                void Btn(string text, string choice, Theme.Kind kind, string tip)
                {
                    var x = Theme.Button(text, kind, tip);
                    x.Margin = new Thickness(8, 0, 0, 0);
                    x.Click += (_, __) => { _choice = choice; DialogResult = true; };
                    b.Children.Add(x);
                }
                Btn(saving ? L.T("Annulla") : L.T("Salta"), "skip", Theme.Kind.Ghost, saving ? L.T("Non salvare") : L.T("Non importare questo modello"));
                Btn(saving ? L.T("Salva come nuovo") : L.T("Rinomina"), "rename", Theme.Kind.Normal,
                    saving ? L.T("Salvalo accanto all'altro con un nome nuovo, es. \"Sedia (2)\"") : L.T("Importalo con un nome nuovo, es. \"Sedia (2)\""));
                Btn(L.T("Sovrascrivi"), "overwrite", Theme.Kind.Primary, L.T("Sostituisci il modello che c'è già"));
                sp.Children.Add(b);
            }

            protected override void OnCloseButton() => DialogResult = false;

            public static (string choice, bool all) Ask(Window owner, string name, string folder, bool saving = false)
            {
                var d = new ConflictDialog(name, folder, saving) { Owner = owner };
                var ok = d.ShowDialog() == true;
                return (ok ? d._choice : "skip", ok && d._all.IsChecked == true);
            }
        }
    }
}
