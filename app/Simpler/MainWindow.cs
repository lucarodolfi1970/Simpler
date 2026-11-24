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
using System.Windows.Threading;

namespace Simpler
{
    /// <summary>Main window: layout and startup. Behaviour lives in the other MainWindow.*.cs files.</summary>
    public sealed partial class MainWindow : Window
    {
        readonly EngineHost _host = new EngineHost();
        EngineClient? _api;
        SceneModel _scene = new SceneModel();
        string _selected = "";
        string? _projectPath;
        readonly string? _openAtStart;

        // header
        List<Button> _toolButtons = new List<Button>(), _qualityButtons = new List<Button>();
        Button _causticsButton = null!;
        TextBlock _projectLabel = null!;
        TextBlock _progressLabel = null!;
        Border _progressBar = null!, _progressTrack = null!;
        // panels
        StackPanel _treeRows = null!;
        ScrollViewer _treeScroll = null!;
        TextBox _treeSearch = null!;
        readonly TextBlock searchHint = new TextBlock();
        List<Button> _treeTypeButtons = new List<Button>();
        string _treeType = "";
        StackPanel _props = null!;
        WrapPanel _libraryTiles = null!;
        ScrollViewer? _libraryScroller;
        readonly Dictionary<string, Button> _libraryMenuButtons = new();

        // library: menu → tabs (label in Italian, translated where shown)
        // (1.78.1, Luca: «dobbiamo ripensare l'organizzazione della libreria») one menu per kind of thing; inside each the
        // same sources in the same order: Simpler (what comes with the program, read only), I miei (imported or saved by
        // the user, with folders) and Online (Poly Haven, ambientCG: downloaded at the first use). «La storia» is in the
        // File menu now (Simpler still opens on it); the search box can look in the whole library (tab "search").
        static readonly (string menu, string id, string label)[] LibraryMenus =
        {
            ("favorites", "favorites", "Preferiti"),
            ("models", "primitives", "Simpler"), ("models", "objects", "I miei"), ("models", "packmodels", "Pacchetti"), ("models", "phmodels", "Online · Poly Haven"),
            ("vegetation", "simplerplants", "Simpler"), ("vegetation", "myplants", "I miei"), ("vegetation", "packplants", "Pacchetti"),
            ("materials", "simplermats", "Simpler"), ("materials", "mymaterials", "I miei"), ("materials", "polyhaven", "Online · Poly Haven"),
            ("decals", "simplerdecals", "Simpler"), ("decals", "mydecals", "I miei"), ("decals", "acgdecals", "Online · ambientCG"),
            ("ecosystems", "simplereco", "Simpler"), ("ecosystems", "ecosystems", "I miei"),
            ("sky", "hdri", "HDRI e sfondi"),
            ("project", "scenes", "Scene"), ("project", "aioutputs", "Elaborazioni AI"),
        };

        /// <summary>The icon of a source in the library menus: a folder of its colour (Simpler red, I miei yellow, Pacchetti
        /// blue), a globe for what comes from the internet.</summary>
        static UIElement? SourceIcon(string label) => label switch
        {
            "Simpler" => Theme.Icon(Icons.Folder, Theme.C("#E5534B"), 15, 1.7),
            "I miei" => Theme.Icon(Icons.Folder, Theme.Warm, 15, 1.7),
            "Pacchetti" => Theme.Icon(Icons.Folder, Theme.C("#4C9DFF"), 15, 1.7),
            _ when label.StartsWith("Online") => Theme.Icon(Icons.Globe, Theme.TextMuted, 15, 1.7),
            _ => null,
        };

        static string MenuTitle(string menu) => menu switch
        {
            "models" => L.T("Modelli 3D") + " ▾", "materials" => L.T("Materiali") + " ▾",
            "decals" => (L.Lang == "en" ? "Decals" : "Decal") + " ▾", "hdri" => L.T("HDRI e sfondi"),
            "lights" => L.T("Luci"), "aioutputs" => L.T("Elaborazioni AI"), "story" => L.T("La storia"), "favorites" => L.T("Preferiti"), "ecosystems" => L.T("Ecosistemi") + " ▾",
            "sky" => L.T("HDRI e sfondi"), "vegetation" => L.T("Vegetazione") + " ▾", "project" => L.T("Progetto") + " ▾", _ => L.T("Scene"),
        };

        /// <summary>Opens a tab of the bottom library (the library comes into view if it was folded).</summary>
        void ShowLibraryTab(string id)
        {
            // a cut material or model is forgotten when the library shows another kind (no material into a model folder)
            var kind = id is "mymaterials" ? "material" : id is "objects" or "myplants" or "simplerplants" or "primitives" or "packplants" or "packmodels" ? "model"
                     : id is "ecosystems" or "simplereco" ? "eco" : "";
            if (_libClip != null && _libClip.Scope != kind) _libClip = null;
            _libraryTab = id;
            RenderLibrary();
        }
        Button _viewModeButton = null!;
        int _viewModeIndex = 1;
        static readonly (string label, string tip)[] ViewModes =
        {
            ("Sagome", "Vista d'argilla: ogni pezzo grigio opaco con i contorni disegnati, senza texture, luci né ombre. Più leggera per le scene pesanti e utile per giudicare le forme. Selezione, gizmo e copie funzionano come sempre."),
            ("Tempo reale", "Vista veloce per muoversi e comporre la scena"),
            ("Path tracing", "Anteprima fotorealistica: Cycles calcola il percorso fisico della luce (barra spaziatrice)"),
        };
        static readonly Geometry[] ViewModeIcons = { Icons.Mesh, Icons.Monitor, Icons.Camera };

        FrameworkElement ViewModeContent(int i)
        {
            var sp = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            var ic = Theme.Icon(ViewModeIcons[i], i == 2 ? Theme.C("#F2C14E") : Theme.Accent, 15, 1.7);
            ic.Margin = new Thickness(0, 0, 7, 0);
            sp.Children.Add(ic);
            sp.Children.Add(new TextBlock { Text = i == 2 ? "Path tracing" : L.T(ViewModes[i].label), FontSize = 13, VerticalAlignment = VerticalAlignment.Center });
            sp.Children.Add(new System.Windows.Shapes.Path
            {
                Data = Geometry.Parse("M0,0 L3.5,3.5 L7,0"), Stroke = Theme.B(Theme.TextMuted), StrokeThickness = 1.4, Margin = new Thickness(8, 1, 0, 0),
                StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round, VerticalAlignment = VerticalAlignment.Center,
            });
            return sp;
        }

        /// <summary>The view in use on the button (from SetRealistic: also the space bar and the other ways in).</summary>
        void ShowViewMode(int i)
        {
            if (_viewModeButton == null || i == _viewModeIndex && _viewModeButton.Content != null) { _viewModeIndex = i; return; }
            _viewModeIndex = i;
            _viewModeButton.Content = ViewModeContent(i);
        }

        void ShowViewModeMenu()
        {
            var m = new ContextMenu { PlacementTarget = _viewModeButton, Placement = System.Windows.Controls.Primitives.PlacementMode.Bottom };
            for (int i = 0; i < ViewModes.Length; i++)
            {
                var k = i;
                var item = new MenuItem
                {
                    Header = i == 2 ? "Path tracing" : L.T(ViewModes[i].label), ToolTip = L.T(ViewModes[i].tip),
                    Icon = Theme.Icon(ViewModeIcons[i], i == 2 ? Theme.C("#F2C14E") : Theme.Accent, 15, 1.7),
                    FontWeight = i == _viewModeIndex ? FontWeights.SemiBold : FontWeights.Normal,
                };
                item.Click += async (_, __) =>
                {
                    if (k == 2) { await SetRealistic(true); return; }
                    SetBoxMode(k == 0);
                    await SetRealistic(false);
                };
                m.Items.Add(item);
            }
            m.IsOpen = true;
        }
        Button _undoButton = null!, _redoButton = null!;
        List<Button> _speedButtons = new List<Button>();
        // status
        TextBlock _status = null!, _statusRight = null!, _statusJob = null!;

        string _tool = "move";
        string _engineLabel = "";
        string _quality = "alta";
        bool _caustics;
        string _libraryTab = "story";           // (Simpler opens on its story: why it exists, by whom, where to read more)
        JsonArray _materials = new JsonArray(), _environments = new JsonArray();

        public MainWindow(string? openAtStart, SplashWindow? splash = null)
        {
            _openAtStart = openAtStart;
            _splash = splash;
            Title = L.T("Simpler ") + SettingsDialog.Version;
            try
            {
                var ico = System.IO.Path.Combine(AppContext.BaseDirectory, "Simpler.ico");
                if (System.IO.File.Exists(ico)) Icon = System.Windows.Media.Imaging.BitmapFrame.Create(new Uri(ico));
            }
            catch { /* the exe icon is used anyway */ }
            Width = 1500; Height = 920;
            MinWidth = 1000; MinHeight = 640;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            if (_splash != null)
            {
                // prepared out of sight behind the splash screen (the 3D view needs a real window to start),
                // then shown maximized when everything is ready
                WindowStartupLocation = WindowStartupLocation.Manual;
                Left = -32000; Top = -32000;
                ShowInTaskbar = false;
                ShowActivated = false;
            }
            Background = Theme.B(Theme.Window);
            Foreground = Theme.B(Theme.Text);
            FontFamily = Theme.Sans;
            FontSize = 13;
            UseLayoutRounding = true;
            TextOptions.SetTextFormattingMode(this, TextFormattingMode.Display);

            Content = BuildLayout();
            Loaded += async (_, __) => await StartEngine();
            Loaded += (_, __) => DiagService.Schedule(this);      // (the question about the diagnostics, once; then the automatic check)
            HookNotesAutoClose();
            Closing += OnClosingAsk;
            // (each step said in the log: a session that does not end leaves its last line here - Luca: the engine was still
            // holding its log a long time after closing)
            Closed += (_, __) =>
            {
                AppLog.Write("closing: stopping the engine");
                try { _host.Dispose(); } catch (Exception ex) { AppLog.Write("closing: engine stop failed: " + ex.Message); }
                AppLog.Write("closing: engine stopped");
                try { DeleteAiSessionDir(); } catch { }
                DiagService.End();
                AppLog.Write("closed cleanly");
            };
            CleanAiSessions();
            PreviewMouseDown += (_, e) => { if (DialogBlocker() != null) { e.Handled = true; ShowBlocked(); } };
            PreviewMouseWheel += (_, e) => { if (DialogBlocker() != null) e.Handled = true; };
            PreviewKeyDown += (_, e) =>
            {
                if (DialogBlocker() == null || e.Key is Key.System or Key.LeftAlt or Key.RightAlt or Key.LeftCtrl or Key.RightCtrl
                                                     or Key.LeftShift or Key.RightShift or Key.LWin or Key.RWin) return;
                e.Handled = true;
                ShowBlocked();
            };
            PreviewKeyDown += OnKey;
        }

        // ================================================================ layout

        UIElement BuildLayout()
        {
            var root = new DockPanel();
            var header = BuildHeader();
            DockPanel.SetDock(header, Dock.Top);
            _lockHeader = header;
            root.Children.Add(header);
            var status = BuildStatus();
            DockPanel.SetDock(status, Dock.Bottom);
            root.Children.Add(status);
            var updates = BuildUpdateStrip();         // (1.78.4) a newer Simpler: above the status bar, hidden otherwise
            DockPanel.SetDock(updates, Dock.Bottom);
            root.Children.Add(updates);

            var body = new Grid();
            // side panels are resizable (drag the thin bars); widths are remembered
            var st = Settings.Load();
            var leftCol = new ColumnDefinition { Width = new GridLength(Math.Clamp(st.LeftPanelWidth, 220, 700)), MinWidth = 220, MaxWidth = 700 };
            var rightCol = new ColumnDefinition { Width = new GridLength(Math.Clamp(st.RightPanelWidth, 280, 700)), MinWidth = 280, MaxWidth = 700 };
            body.ColumnDefinitions.Add(leftCol);
            body.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            body.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star), MinWidth = 300 });
            body.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            body.ColumnDefinitions.Add(rightCol);
            foreach (var col in new[] { 1, 3 })
            {
                var split = new GridSplitter
                {
                    Width = 5, HorizontalAlignment = HorizontalAlignment.Stretch, VerticalAlignment = VerticalAlignment.Stretch,
                    Background = Theme.B(Theme.Line), ResizeBehavior = GridResizeBehavior.PreviousAndNext,
                    ResizeDirection = GridResizeDirection.Columns, ShowsPreview = false, Cursor = Cursors.SizeWE,
                    ToolTip = L.T("Trascina per ridimensionare il pannello"),
                };
                split.MouseEnter += (_, __) => split.Background = Theme.B(Theme.Accent);
                split.MouseLeave += (_, __) => split.Background = Theme.B(Theme.Line);
                split.DragCompleted += (_, __) =>
                {
                    var s2 = Settings.Load();
                    s2.LeftPanelWidth = leftCol.ActualWidth;
                    s2.RightPanelWidth = rightCol.ActualWidth;
                    s2.Save();
                };
                Grid.SetColumn(split, col);
                body.Children.Add(split);
            }

            var left = BuildTreePanel();
            _lockLeft = left;
            Grid.SetColumn(left, 0);
            body.Children.Add(left);

            var center = new Grid();
            // the library grows by whole rows of tiles (1, 2 or 3): drag its top edge, it clicks into place
            center.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star), MinHeight = 200 });
            center.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            center.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            _center = center;
            var vp = BuildViewport();
            center.Children.Add(vp);
            var libSplit = LibraryResizer();
            Grid.SetRow(libSplit, 1);
            center.Children.Add(libSplit);
            var lib = BuildLibrary();
            _lockLib = lib;
            Grid.SetRow(lib, 2);
            center.Children.Add(lib);
            Grid.SetColumn(center, 2);
            body.Children.Add(center);

            var right = BuildPropsPanel();
            _lockRight = right;
            Grid.SetColumn(right, 4);
            body.Children.Add(right);

            root.Children.Add(body);
            StudioLayout(root, body, header, left, right);
            return root;
        }

        // Hooks for a separate tool of the author built from these same sources (not part of Simpler): partial
        // methods without a body here, so the compiler removes the calls and Simpler is exactly as without them.
        partial void StudioMode(ref bool on);
        partial void StudioLayout(DockPanel root, Grid body, UIElement header, UIElement left, UIElement right);
        partial void StudioBeforeInsert(ref Func<Task>? before);
        partial void StudioAfterInsert(string id);
        partial void StudioInsertAt(ref JsonObject? at);
        partial void StudioKey(KeyEventArgs e);
        bool InStudio { get { bool on = false; StudioMode(ref on); return on; } }

        UIElement BuildHeader()
        {
            var bar = new DockPanel { Height = 58, Background = Theme.B(Theme.Panel), LastChildFill = false };
            var border = new Border { Child = bar, BorderBrush = Theme.B(Theme.Line), BorderThickness = new Thickness(0, 0, 0, 1) };

            var brand = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(16, 0, 18, 0), VerticalAlignment = VerticalAlignment.Center };
            var logo = new Grid { Width = 26, Height = 26 };
            logo.Children.Add(new System.Windows.Shapes.Ellipse { Stroke = Theme.B(Theme.Accent), StrokeThickness = 2 });
            logo.Children.Add(new System.Windows.Shapes.Ellipse { Fill = Theme.B(Theme.Warm), Width = 10, Height = 10 });
            brand.Children.Add(logo);
            brand.Children.Add(new TextBlock { Text = "Simpler", FontSize = 16, FontWeight = FontWeights.SemiBold, Margin = new Thickness(10, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center });
            bar.Children.Add(brand);

            var file = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            file.Children.Add(HeaderButton(Icons.New, L.T("Nuovo"), L.T("Nuova scena (Ctrl+N)"), async () => await NewProject()));
            // "Importa" is a menu (a model into the scene, many into the library, material fixes, library statistics):
            // the buttons that open a menu carry a small arrow; the others (Nuovo, Salva) act at once
            Button? importBtn = null;
            importBtn = HeaderButton(Icons.Import, "", L.T("Importa/Correggi: importa modelli (nella scena o nella libreria) e cura della libreria"), () => { ShowImportMenu(importBtn!); return Task.CompletedTask; });
            AddMenuArrow(importBtn);
            importBtn.Tag = "menu";
            file.Children.Add(importBtn);
            // "Apri" opens the file menu (open, save, save as, info, close); Salva stays next to it for quick saves
            Button? openBtn = null;
            openBtn = HeaderButton(Icons.Open, "", L.T("Apri, salva, informazioni e chiusura di Simpler"), () => { ShowFileMenu(openBtn!); return Task.CompletedTask; });
            AddMenuArrow(openBtn);
            openBtn.Tag = "menu";
            file.Children.Add(openBtn);
            file.Children.Add(HeaderButton(Icons.Save, "Salva", L.T("Salva progetto (Ctrl+S)"), async () => await SaveProject(false)));
            _undoButton = HistoryButton(Icons.Undo, L.T("Annulla (Ctrl+Z)"), async () => await Undo());
            _redoButton = HistoryButton(Icons.Redo, L.T("Ripeti (Ctrl+Y)"), async () => await Redo());
            _undoButton.Margin = new Thickness(10, 0, 0, 0);
            file.Children.Add(_undoButton);
            file.Children.Add(_redoButton);
            bar.Children.Add(file);

            _projectLabel = Theme.Label(L.T("Nuovo progetto"), 13, Theme.TextMuted);
            _projectLabel.Margin = new Thickness(12, 0, 16, 0);
            _projectLabel.MaxWidth = 260;
            bar.Children.Add(_projectLabel);

            // two gizmos: move and rotate together (arrows + arcs), and scale
            var tools = Theme.Segmented(out _toolButtons,
                (Theme.Icon(Icons.Move, null, 17), L.T("Sposta e ruota (W): frecce per spostare, archi per ruotare")),
                (Theme.Icon(Icons.Scale, null, 17), L.T("Scala (R)")));
            tools.VerticalAlignment = VerticalAlignment.Center;
            string[] toolIds = { "move", "scale" };
            for (int i = 0; i < _toolButtons.Count; i++)
            {
                var id = toolIds[i];
                _toolButtons[i].Padding = new Thickness(10, 0, 10, 0);
                _toolButtons[i].Click += (_, __) => SetTool(id);
            }
            bar.Children.Add(tools);
            // pivot placed by hand: the gizmo turns violet and moves alone (MainWindow.Pivot)
            _pivotButton = Theme.Button(Theme.Icon(Icons.Pivot, null, 17), Theme.Kind.Ghost,
                L.T("Sposta il pivot: il gizmo diventa viola e si sposta da solo, senza il modello; riclicca per fissarlo. Vale per tutto il modello (il padre della gerarchia)"));
            _pivotButton.Padding = new Thickness(10, 0, 10, 0);
            _pivotButton.Margin = new Thickness(6, 0, 0, 0);
            _pivotButton.VerticalAlignment = VerticalAlignment.Center;
            _pivotButton.Click += (_, __) => SetPivotEdit(!_pivotEdit);
            bar.Children.Add(_pivotButton);
            // (1.78.3, Luca: «le luci … avrebbero dignità di un pulsante con una lampadina gialla») the lights are not
            // a library: a button that opens the kinds of light, one click puts it in the middle of the view
            Button? lightsBtn = null;
            lightsBtn = Theme.Button(Theme.IconText(Icons.Light, "", Theme.C("#F2C14E"), 17), Theme.Kind.Ghost, L.T("Aggiungi una luce: scegli il tipo, va al centro della vista; oppure trascinala dal menu nella vista, dove la lasci"));
            lightsBtn.Padding = new Thickness(10, 0, 10, 0);
            lightsBtn.Margin = new Thickness(6, 0, 0, 0);
            lightsBtn.VerticalAlignment = VerticalAlignment.Center;
            lightsBtn.Click += (_, __) => ShowLightsMenu(lightsBtn!);
            AddMenuArrow(lightsBtn);
            bar.Children.Add(lightsBtn);

            var speeds = Theme.Segmented(out _speedButtons,
                (Theme.Icon(Icons.Ant, null, 17), L.T("Velocità rotellina: formica (passi piccolissimi, per i dettagli)")),
                (Theme.Icon(Icons.Walk, null, 17), L.T("Velocità rotellina: a piedi (passi piccoli)")),
                (Theme.Icon(Icons.Bike, null, 17), L.T("Velocità rotellina: bicicletta")),
                (Theme.Icon(Icons.Car, null, 17), L.T("Velocità rotellina: auto (passi lunghi)")));
            speeds.VerticalAlignment = VerticalAlignment.Center;
            speeds.Margin = new Thickness(8, 0, 0, 0);
            string[] speedIds = { "ant", "walk", "bike", "car" };
            for (int i = 0; i < _speedButtons.Count; i++)
            {
                var id = speedIds[i];
                _speedButtons[i].Padding = new Thickness(8, 0, 8, 0);
                _speedButtons[i].Click += (_, __) => SetNavSpeed(id);
            }
            Theme.SetSegment(_speedButtons, Math.Max(0, Array.IndexOf(speedIds, Settings.Load().NavSpeed)));
            foreach (var b in _speedButtons) b.Padding = new Thickness(8, 0, 8, 0);
            bar.Children.Add(speeds);

            // materials: how a material dropped in the view is applied, and the eyedropper (always at hand)
            var drop = DropModePicker();
            drop.VerticalAlignment = VerticalAlignment.Center;
            drop.Margin = new Thickness(12, 0, 0, 0);
            bar.Children.Add(drop);
            var dropper = Theme.Button(Theme.Icon(Icons.Eyedropper, Theme.Accent, 16), Theme.Kind.Ghost,
                L.T("Contagocce: clicca una superficie nella vista e si apre subito il suo materiale (Esc per annullare)"));
            dropper.Padding = new Thickness(8, 0, 8, 0);
            dropper.MinHeight = 30;
            dropper.Margin = new Thickness(4, 0, 0, 0);
            dropper.VerticalAlignment = VerticalAlignment.Center;
            dropper.Click += (_, __) => StartEyedropper();
            bar.Children.Add(dropper);
            // «Ridisegna la vista»: the real-time view made again from scratch (as when the project is opened), for a
            // view that looks incomplete; what the view had goes in app.log first
            var redraw = Theme.Button(Theme.Icon(Icons.Refresh, Theme.Danger, 16), Theme.Kind.Ghost,
                L.T("Ridisegna la vista: la vista in tempo reale viene rifatta da capo, come all'apertura del progetto. Usalo se sembra incompleta."));
            redraw.Padding = new Thickness(8, 0, 8, 0);
            redraw.MinHeight = 30;
            redraw.Margin = new Thickness(2, 0, 0, 0);
            redraw.VerticalAlignment = VerticalAlignment.Center;
            redraw.Click += async (_, __) => await RedrawView();
            bar.Children.Add(redraw);
            // «Libera memoria»: what the scene no longer uses out of memory (memory.py); a message says what and asks
            var purge = Theme.Button(Theme.Icon(Icons.Broom, Theme.Danger, 16), Theme.Kind.Ghost,
                L.T("Libera memoria: toglie dalla memoria gli oggetti eliminati tenuti per l'annulla e i materiali, le texture e le geometrie che nessun oggetto usa più. Prima ti dice cosa e quanto, e chiede conferma."));
            purge.Padding = new Thickness(8, 0, 8, 0);
            purge.MinHeight = 30;
            purge.Margin = new Thickness(2, 0, 0, 0);
            purge.VerticalAlignment = VerticalAlignment.Center;
            purge.Click += async (_, __) => await PurgeMemory();
            bar.Children.Add(purge);

            // (1.78.4, Luca: «recuperiamo spazio nella toolbar») the three kinds of view in one button: it shows the one
            // in use (Tempo reale at the start), its menu the three (Sagome, Tempo reale, Path tracing)
            _viewModeButton = Theme.Button(ViewModeContent(1), Theme.Kind.Ghost, L.T("Vista: Sagome, Tempo reale o Path tracing (barra spaziatrice: path tracing)"));
            _viewModeButton.Padding = new Thickness(10, 0, 10, 0);
            _viewModeButton.Margin = new Thickness(12, 0, 0, 0);
            _viewModeButton.VerticalAlignment = VerticalAlignment.Center;
            _viewModeButton.Click += (_, __) => ShowViewModeMenu();
            bar.Children.Add(_viewModeButton);

            // right side
            // (1.75.32) the AI video: a small button with the clapperboard, after «Render finale»; (1.76.60, Luca) orange
            // as every AI function, the clapperboard with the sparkles at its top right (Luca: «le stelline in alto a destra»); the AI picture before it
            _videoButton = Theme.Button(AiIcon(Icons.Clapper, true, Theme.AccentText), Theme.Kind.Ai, L.T("Video AI: un breve video tra due viste della scena (Krea)"));
            _videoButton.VerticalAlignment = VerticalAlignment.Center;
            _videoButton.Padding = new Thickness(0);
            _videoButton.Width = TopButtonWidth;
            _videoButton.Margin = new Thickness(6, 0, 16, 0);
            _videoButton.Click += async (_, __) => await ToggleVideoPanel();
            DockPanel.SetDock(_videoButton, Dock.Right);
            bar.Children.Add(_videoButton);

            // AI (the user's OpenAI key): (1.76.60, Luca: «sposta il tasto AI dopo quello del rendering») between Render
            // finale and Video AI, a small camera with the sparkles at its top right, orange when the key works
            _aiButton = Theme.Button(AiIcon(Icons.Camera, true, Theme.TextSoft), Theme.Kind.Ghost, null);
            _aiButton.VerticalAlignment = VerticalAlignment.Center;
            _aiButton.Padding = new Thickness(0);
            _aiButton.Width = TopButtonWidth;
            _aiButton.Margin = new Thickness(6, 0, 0, 0);
            _aiButton.Click += async (_, __) => await ToggleAiPanel();
            DockPanel.SetDock(_aiButton, Dock.Right);
            bar.Children.Add(_aiButton);

            // (1.76.60, Luca: «non scrivere render finale») the camera only, as the AI buttons beside it (the name in the tooltip)
            // (1.76.61) the same width and the same drawing as the AI buttons: the camera with a small sun (the light) at its
            // top right
            var render = Theme.Button(AiIcon(Icons.Camera, true, Theme.AccentText, Icons.Light), Theme.Kind.Primary, L.T("Render finale ad alta risoluzione"));
            render.Padding = new Thickness(0);
            render.Width = TopButtonWidth;
            render.Margin = new Thickness(10, 0, 0, 0);
            render.VerticalAlignment = VerticalAlignment.Center;
            render.Click += async (_, __) => await FinalRender();
            DockPanel.SetDock(render, Dock.Right);
            bar.Children.Add(render);

            // (1.75.3) close / open again every section of the visible panel: one orange double arrow here, before
            // the AI button (before, one in each panel)
            _foldButton = Theme.Button(Theme.Icon(Icons.ChevronsUp, AdvancedColor, 17), Theme.Kind.Ghost, null);
            _foldButton.VerticalAlignment = VerticalAlignment.Center;
            _foldButton.Padding = new Thickness(8, 0, 8, 0);
            _foldButton.Margin = new Thickness(6, 0, 0, 0);
            _foldButton.Click += (_, __) => FoldClick();
            _foldButton.MouseEnter += (_, __) => FoldFace();
            DockPanel.SetDock(_foldButton, Dock.Right);
            bar.Children.Add(_foldButton);
            FoldFace();

            // (1.76.32) the favourite commands: the heart (only them) and their presets, between SmartView and the arrows
            BuildFavButtons(bar);

            // (1.75.9) SmartView: orange, before the double arrow (MainWindow.SmartView.cs)
            BuildSmartButton(bar);

            _renderPanelButton = Theme.Button(Theme.IconText(Icons.Sliders, L.T("Rendering")), Theme.Kind.Ghost, L.T("Impostazioni di rendering: tempo reale e path tracing"));
            _renderPanelButton.VerticalAlignment = VerticalAlignment.Center;
            _renderPanelButton.Margin = new Thickness(6, 0, 0, 0);
            _renderPanelButton.Click += async (_, __) => await ToggleRenderPanel();
            DockPanel.SetDock(_renderPanelButton, Dock.Right);
            bar.Children.Add(_renderPanelButton);

            // Scatter and Ecosistemi: they open their panels on the right like the others (the brush was among the gizmo
            // tools, far from the panel it opens). The library menu Ecosistemi is for choosing and placing them
            _ecoPanelButton = Theme.Button(Theme.IconText(Icons.Grass, L.T("Ecosistemi")), Theme.Kind.Ghost,
                L.T("Ecosistemi: vegetazione composta una volta sul banco di prova e messa su qualunque superficie"));
            _ecoPanelButton.VerticalAlignment = VerticalAlignment.Center;
            _ecoPanelButton.Margin = new Thickness(6, 0, 0, 0);
            _ecoPanelButton.Click += async (_, __) => await ShowRightPanel(_rightPanel == "ecosystem" ? "" : "ecosystem");
            _scatterPanelButton = Theme.Button(Theme.IconText(Icons.Brush, L.T("Scatter")), Theme.Kind.Ghost,
                L.T("Scatter (B): dipingi modelli della libreria sulle superfici (erba, fiori, sassi, alberi), riempi un'area o mettili in fila"));
            _scatterPanelButton.VerticalAlignment = VerticalAlignment.Center;
            _scatterPanelButton.Margin = new Thickness(6, 0, 0, 0);
            _scatterPanelButton.Click += (_, __) => SetTool(Painting ? "move" : "paint");

            _ambiencePanelButton = Theme.Button(Theme.IconText(Icons.Globe, L.T("Ambiente")), Theme.Kind.Ghost, L.T("Cielo, sole, nuvole, foschia, notte e suolo"));
            _ambiencePanelButton.VerticalAlignment = VerticalAlignment.Center;
            _ambiencePanelButton.Margin = new Thickness(6, 0, 0, 0);
            _ambiencePanelButton.Click += async (_, __) => await ShowRightPanel(_rightPanel == "ambience" ? "" : "ambience");
            DockPanel.SetDock(_ecoPanelButton, Dock.Right);
            bar.Children.Add(_ecoPanelButton);
            DockPanel.SetDock(_scatterPanelButton, Dock.Right);
            bar.Children.Add(_scatterPanelButton);
            DockPanel.SetDock(_ambiencePanelButton, Dock.Right);
            bar.Children.Add(_ambiencePanelButton);

            // Paesaggio: what is around the scene to the horizon (the sea; later the terrains)
            _landscapePanelButton = Theme.Button(Theme.IconText(Mountain, L.T("Paesaggio")), Theme.Kind.Ghost, L.T("Mare fino all'orizzonte"));
            _landscapePanelButton.VerticalAlignment = VerticalAlignment.Center;
            _landscapePanelButton.Margin = new Thickness(6, 0, 0, 0);
            _landscapePanelButton.Click += async (_, __) => await ShowRightPanel(_rightPanel == "landscape" ? "" : "landscape");
            DockPanel.SetDock(_landscapePanelButton, Dock.Right);
            bar.Children.Add(_landscapePanelButton);

            _materialPanelButton = Theme.Button(Theme.IconText(Icons.MatStandard, L.T("Materiali")), Theme.Kind.Ghost,
                L.T("Parametri del materiale: dell'oggetto selezionato, oppure (senza selezione) del materiale bianco standard, da trascinare poi sugli oggetti"));
            _materialPanelButton.VerticalAlignment = VerticalAlignment.Center;
            _materialPanelButton.Margin = new Thickness(6, 0, 0, 0);
            _materialPanelButton.Click += async (_, __) => await ToggleMaterialPanel();
            DockPanel.SetDock(_materialPanelButton, Dock.Right);
            bar.Children.Add(_materialPanelButton);

            _cameraPanelButton = Theme.Button(Theme.IconText(Icons.Aperture, L.T("Fotocamera")), Theme.Kind.Ghost, L.T("Focale, profondità di campo, prospettiva e formato"));
            _cameraPanelButton.VerticalAlignment = VerticalAlignment.Center;
            _cameraPanelButton.Margin = new Thickness(6, 0, 0, 0);
            _cameraPanelButton.Click += async (_, __) => await ShowRightPanel(_rightPanel == "camera" ? "" : "camera");
            DockPanel.SetDock(_cameraPanelButton, Dock.Right);
            bar.Children.Add(_cameraPanelButton);

            _resourcesPanelButton = Theme.Button(Theme.IconText(ResourcesIcon, L.T("Risorse")), Theme.Kind.Ghost, L.T("Scheda video, processore e memoria: quanto sono usati"));
            _resourcesPanelButton.VerticalAlignment = VerticalAlignment.Center;
            _resourcesPanelButton.Margin = new Thickness(6, 0, 0, 0);
            _resourcesPanelButton.Click += async (_, __) => await ShowRightPanel(_rightPanel == "resources" ? "" : "resources");
            DockPanel.SetDock(_resourcesPanelButton, Dock.Right);
            bar.Children.Add(_resourcesPanelButton);

            var gear = Theme.Button(Theme.Icon(Icons.Gear, null, 17), Theme.Kind.Ghost, L.T("Impostazioni (lingua, navigazione, cartelle, versione, novità)"));
            gear.Padding = new Thickness(8, 0, 8, 0);
            gear.VerticalAlignment = VerticalAlignment.Center;
            gear.Click += (_, __) => ToggleSettingsPanel();
            DockPanel.SetDock(gear, Dock.Right);
            bar.Children.Add(gear);

            // the news of each version at one click (before: only from the settings)
            var help = Theme.Button(Theme.Icon(Icons.Help, null, 17), Theme.Kind.Ghost, L.T("Novità: cosa è cambiato in ogni versione"));
            help.Padding = new Thickness(8, 0, 8, 0);
            help.VerticalAlignment = VerticalAlignment.Center;
            help.Click += async (_, __) => { if (_rightPanel == "notes") await ShowRightPanel(""); else await ShowNotesPanel(); };
            _notesButton = help;
            DockPanel.SetDock(help, Dock.Right);
            bar.Children.Add(help);

            var progress = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(10, 0, 4, 0) };
            _progressTrack = new Border { Width = 120, Height = 6, CornerRadius = new CornerRadius(3), Background = Theme.B("#1A2842"), VerticalAlignment = VerticalAlignment.Center };
            _progressBar = new Border { Width = 0, Height = 6, CornerRadius = new CornerRadius(3), Background = Theme.B(Theme.Warm), HorizontalAlignment = HorizontalAlignment.Left };
            _progressTrack.Child = _progressBar;
            progress.Children.Add(_progressTrack);
            _progressLabel = new TextBlock { FontFamily = Theme.Mono, FontSize = 12, Foreground = Theme.B(Theme.TextSoft), Margin = new Thickness(10, 0, 0, 0), MinWidth = 90, VerticalAlignment = VerticalAlignment.Center };
            progress.Children.Add(_progressLabel);
            DockPanel.SetDock(progress, Dock.Right);
            // header progress and caustics button removed (1.0.1): the badge in the view shows the path tracing
            // progress and caustics live in the Rendering panel

            _causticsButton = Theme.Button(L.T("Caustiche"), Theme.Kind.Ghost, L.T("Caustiche nitide attraverso vetri e gemme"));
            _causticsButton.VerticalAlignment = VerticalAlignment.Center;
            _causticsButton.Margin = new Thickness(8, 0, 0, 0);
            _causticsButton.Click += async (_, __) => await SetCaustics(!_caustics);
            DockPanel.SetDock(_causticsButton, Dock.Right);


            // one menu for the quality of what the view shows: the shadows in real time, the quality in path tracing
            // (the two rows of buttons were too many for the bar: «Finale» was cut off)
            _qualityDrop = Theme.Button("", Theme.Kind.Ghost);
            _qualityDrop.VerticalAlignment = VerticalAlignment.Center;
            _qualityDrop.MinHeight = 30;
            _qualityDrop.Margin = new Thickness(6, 0, 0, 0);
            _qualityDrop.Click += (_, __) => OpenQualityMenu();
            DockPanel.SetDock(_qualityDrop, Dock.Right);
            bar.Children.Add(_qualityDrop);

            SetTool("move");
            UpdateQualityDrop();
            // a narrow window: the labels go away step by step (icons and tooltips stay), never the buttons
            _headerBar = bar;
            _headerSteps = new List<List<FrameworkElement>>
            {
                new() { LabelOf(_renderPanelButton), LabelOf(_scatterPanelButton), LabelOf(_ecoPanelButton), LabelOf(_ambiencePanelButton), LabelOf(_landscapePanelButton!), LabelOf(_materialPanelButton), LabelOf(_cameraPanelButton), LabelOf(_resourcesPanelButton) },
                // (Importa/Correggi and Apri: icon and chevron only, no label - 1.75.12)
                file.Children.OfType<Button>().Where(b => b.Tag as string != "menu").Select(LabelOf).ToList(),
                new() { _projectLabel, LabelOf(render) },
                new() { (FrameworkElement)brand.Children[1] },
            };
            _headerSteps.ForEach(l => l.RemoveAll(x => x == null));
            bar.SizeChanged += (_, __) => FitHeader();
            return border;
        }

        DockPanel? _headerBar;
        List<List<FrameworkElement>> _headerSteps = new();

        static FrameworkElement LabelOf(Button b) =>
            (b.Content as StackPanel)?.Children.OfType<TextBlock>().FirstOrDefault()!;

        /// <summary>Shows as many labels of the header as fit: when the buttons do not fit, the labels of the panel
        /// buttons go first, then those of the file buttons, then the project name and the brand.</summary>
        // (1.78.4, Luca: «i pulsanti sono più larghi del necessario») a button left with its icon only gets a narrow
        // padding and margin: its own (for text) would leave wide empty sides
        readonly Dictionary<Button, (Thickness pad, Thickness margin)> _headerRoomy = new();
        void ShowHeaderLabel(FrameworkElement e, bool on)
        {
            e.Visibility = on ? Visibility.Visible : Visibility.Collapsed;
            if ((e.Parent as FrameworkElement)?.Parent is not Button b || b.Content is not StackPanel) return;
            if (!_headerRoomy.ContainsKey(b)) _headerRoomy[b] = (b.Padding, b.Margin);
            var (pad, margin) = _headerRoomy[b];
            b.Padding = on ? pad : new Thickness(7, 0, 7, 0);
            b.Margin = on ? margin : new Thickness(Math.Min(margin.Left, 2), margin.Top, Math.Min(margin.Right, 2), margin.Bottom);
        }

        void FitHeader()
        {
            if (_headerBar == null || _headerBar.ActualWidth <= 0) return;
            foreach (UIElement c in _headerBar.Children)
                if (c is FrameworkElement fe && _headerWatched.Add(c)) fe.SizeChanged += (_, __) => QueueFitScale();
            foreach (var step in _headerSteps) foreach (var e in step) ShowHeaderLabel(e, true);
            double Need()
            {
                double w = 0;
                foreach (UIElement c in _headerBar.Children)
                {
                    if (c.Visibility == Visibility.Collapsed) continue;
                    c.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
                    w += c.DesiredSize.Width;
                }
                return w;
            }
            // (the bar may be drawn smaller, see FitHeaderScale: its own width is then larger than what the window gives)
            double cur = (_headerBar.LayoutTransform as ScaleTransform)?.ScaleX ?? 1;
            double avail = _headerBar.ActualWidth * cur;
            foreach (var step in _headerSteps)
            {
                if (Need() <= avail - 8) break;
                foreach (var e in step) ShowHeaderLabel(e, false);
            }
            QueueFitScale();
        }

        // (15/11, Luca, a laptop with the text of Windows at 125-150%: «i pulsanti dei pannelli si vedono solo in parte») with
        // every label gone the bar can still be too narrow: the buttons added last (Qualità, the help, the first panels) were
        // cut away. The whole bar is then drawn smaller, as much as needed, so every command stays in sight.
        // (first version, same day: it measured the buttons by itself and answered to their changes at once - a loop that
        // left no time to the mouse and to the start window, Simpler stood still; and its measure was too large, the bar
        // was made smaller on wide screens too.) Now it only READS the layout already made, a moment after it (a timer):
        // the panel gives each button the width it asks while there is room, so the sum of the widths equals the width of
        // the bar only when something is cut.
        readonly HashSet<UIElement> _headerWatched = new();
        System.Windows.Threading.DispatcherTimer? _headerScaleTimer;
        double _headerLogged = 1;
        void QueueFitScale()
        {
            if (_headerScaleTimer == null)
            {
                _headerScaleTimer = new System.Windows.Threading.DispatcherTimer(System.Windows.Threading.DispatcherPriority.Background) { Interval = TimeSpan.FromMilliseconds(150) };
                _headerScaleTimer.Tick += (_, __) => { _headerScaleTimer!.Stop(); try { FitHeaderScale(); } catch (Exception ex) { AppLog.Write("header: " + ex.Message); } };
            }
            _headerScaleTimer.Stop();
            _headerScaleTimer.Start();
        }

        void FitHeaderScale()
        {
            if (_headerBar == null || _headerBar.ActualWidth <= 0) return;
            double cur = (_headerBar.LayoutTransform as ScaleTransform)?.ScaleX ?? 1;
            double barW = _headerBar.ActualWidth, avail = barW * cur, sum = 0;
            foreach (UIElement c in _headerBar.Children)
                if (c.Visibility != Visibility.Collapsed) sum += c.DesiredSize.Width;
            double scale;
            if (sum >= barW - 0.5) scale = Math.Max(0.3, cur * 0.9);          // something is cut: a step smaller, then looked at again
            else scale = Math.Min(1, avail / (sum + 8));                       // everything is inside: as large as it can be
            if (Math.Abs(scale - cur) <= 0.01) return;
            _headerBar.LayoutTransform = scale < 0.995 ? new ScaleTransform(scale, scale) : Transform.Identity;
            if (sum < barW - 0.5 && Math.Abs(scale - _headerLogged) > 0.03)
            {
                _headerLogged = scale;
                AppLog.Write($"header: the buttons take {sum:0} of width, the window gives {avail:0}: bar drawn at {Math.Min(1, scale) * 100:0}%");
            }
            QueueFitScale();
        }

        Button HistoryButton(Geometry icon, string tip, Func<Task> onClick)
        {
            var b = Theme.Button(Theme.Icon(icon, null, 17), Theme.Kind.Ghost, tip);
            b.Padding = new Thickness(8, 0, 8, 0);
            b.IsEnabled = false;
            b.Opacity = 0.4;
            b.Click += async (_, __) => await onClick();
            return b;
        }

        static readonly Geometry MenuArrow = Geometry.Parse("M6 9l6 6 6-6");

        /// <summary>A small arrow after the icon (and label): this button opens a menu.</summary>
        /// <summary>A button that opens a menu: a small filled triangle after its icon and label (as in Office and Explorer).</summary>
        static void AddMenuArrow(Button b)
        {
            if (b.Content is not StackPanel sp || sp.Children.Count == 0) return;
            // (1.75.12) icon only, a small chevron at its lower right corner, in the padding of the button: the menu
            // is said without words and without making the button wider (the header was too narrow, Luca)
            var icon = sp.Children[0];
            sp.Children.Clear();
            var g = new Grid { ClipToBounds = false, VerticalAlignment = VerticalAlignment.Center };
            g.Children.Add(icon);
            g.Children.Add(new System.Windows.Shapes.Path
            {
                Data = Geometry.Parse("M0,0 L2.5,2.5 L5,0"), Stroke = Theme.B(Theme.TextMuted), StrokeThickness = 1.3,
                StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round, StrokeLineJoin = PenLineJoin.Round,
                Width = 6, Height = 4, Stretch = Stretch.None, HorizontalAlignment = HorizontalAlignment.Right,
                VerticalAlignment = VerticalAlignment.Bottom, Margin = new Thickness(0, 0, -7, -2), SnapsToDevicePixels = true,
                IsHitTestVisible = false,
            });
            b.Content = g;
        }

        Button HeaderButton(Geometry icon, string text, string tip, Func<Task> onClick)
        {
            var b = Theme.Button(Theme.IconText(icon, text == "" ? "" : L.T(text)), Theme.Kind.Ghost, tip);
            b.Padding = new Thickness(8, 0, 8, 0);         // (as close together as Annulla / Ripeti)
            b.Margin = new Thickness(0, 0, 2, 0);
            b.Click += async (_, __) => await onClick();
            return b;
        }

        UIElement BuildStatus()
        {
            var bar = new DockPanel { Height = 28, Background = Theme.B(Theme.Ground) };
            _statusRight = new TextBlock { Foreground = Theme.B(Theme.TextFaint), FontSize = 12, Margin = new Thickness(0, 0, 14, 0), VerticalAlignment = VerticalAlignment.Center };
            DockPanel.SetDock(_statusRight, Dock.Right);
            bar.Children.Add(_statusRight);
            // a long job in the background (the table of sky colours): its progress, next to the engine label
            _statusJob = new TextBlock { Foreground = Theme.B(Theme.Warm), FontSize = 12, Margin = new Thickness(0, 0, 18, 0), VerticalAlignment = VerticalAlignment.Center, Visibility = Visibility.Collapsed };
            DockPanel.SetDock(_statusJob, Dock.Right);
            bar.Children.Add(_statusJob);
            _status = new TextBlock { Foreground = Theme.B(Theme.TextMuted), FontSize = 12, Margin = new Thickness(14, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center, TextTrimming = TextTrimming.CharacterEllipsis };
            bar.Children.Add(_status);
            return new Border { Child = bar, BorderBrush = Theme.B(Theme.Line), BorderThickness = new Thickness(0, 1, 0, 0) };
        }

        UIElement BuildTreePanel()
        {
            var panel = new DockPanel { Background = Theme.B(Theme.Panel) };
            var head = new DockPanel { Margin = new Thickness(14, 14, 14, 10) };
            // (lights, primitives and empty groups are added from the library below: Luci, Modelli 3D > Primitive)
            head.Children.Add(Theme.Caption(L.T("Scena")));
            DockPanel.SetDock(head, Dock.Top);
            panel.Children.Add(head);


            _treeSearch = Theme.Input();
            _treeSearch.ToolTip = L.T("Cerca per nome. Usa % (o *) come jolly: frigo%, %lamp%, sedia_%_01");
            _treeSearch.TextChanged += (_, __) => { searchHint.Visibility = _treeSearch.Text == "" ? Visibility.Visible : Visibility.Collapsed; RenderTree(); };
            var searchBox = new Grid { Margin = new Thickness(14, 0, 14, 8) };
            searchBox.Children.Add(_treeSearch);
            searchHint.Text = L.T("Cerca…  (es. %frigo%)");
            searchHint.FontSize = 12;
            searchHint.Foreground = Theme.B(Theme.TextFaint);
            searchHint.IsHitTestVisible = false;
            searchHint.VerticalAlignment = VerticalAlignment.Center;
            searchHint.Margin = new Thickness(10, 0, 0, 0);
            searchBox.Children.Add(searchHint);
            DockPanel.SetDock(searchBox, Dock.Top);
            panel.Children.Add(searchBox);

            var types = Theme.Segmented(out _treeTypeButtons, (L.T("Tutto"), L.T("Mostra tutto")), (L.T("Modelli"), L.T("Solo oggetti 3D")), (L.T("Luci"), L.T("Solo luci")), (L.T("Gruppi"), L.T("Solo gruppi e file importati")));
            types.Margin = new Thickness(14, 0, 14, 10);
            types.HorizontalAlignment = HorizontalAlignment.Left;
            string[] typeIds = { "", "mesh", "light", "group" };
            for (int i = 0; i < _treeTypeButtons.Count; i++)
            {
                var id = typeIds[i];
                var idx = i;
                _treeTypeButtons[i].Padding = new Thickness(8, 0, 8, 0);
                _treeTypeButtons[i].FontSize = 12;
                _treeTypeButtons[i].Click += (_, __) =>
                {
                    _treeType = id;
                    Theme.SetSegment(_treeTypeButtons, idx);
                    foreach (var b in _treeTypeButtons) { b.Padding = new Thickness(8, 0, 8, 0); b.FontSize = 12; }
                    RenderTree();
                };
            }
            Theme.SetSegment(_treeTypeButtons, 0);
            foreach (var b in _treeTypeButtons) { b.Padding = new Thickness(8, 0, 8, 0); b.FontSize = 12; }
            // before the filters: fold / unfold the whole tree
            var foldAll = Theme.Button(Theme.Icon(Icons.ChevronsDown, null, 15), Theme.Kind.Ghost, null);
            foldAll.Padding = new Thickness(6, 0, 6, 0);
            foldAll.Margin = new Thickness(0, 0, 6, 0);
            foldAll.VerticalAlignment = VerticalAlignment.Stretch;
            void FoldFace()
            {
                bool any = _scene.ById.Values.Any(o => o.Children.Count > 0 && _expanded.Contains(o.Id));
                foldAll.Content = Theme.Icon(any ? Icons.ChevronsUp : Icons.ChevronsDown, null, 15);
                foldAll.ToolTip = any ? L.T("Comprimi tutto l'albero") : L.T("Espandi tutto l'albero");
            }
            foldAll.Click += (_, __) =>
            {
                bool any = _scene.ById.Values.Any(o => o.Children.Count > 0 && _expanded.Contains(o.Id));
                _expanded.Clear();
                _expandedInst.Clear();
                if (!any) foreach (var o in _scene.ById.Values.Where(o => o.Children.Count > 0)) _expanded.Add(o.Id);
                RenderTree();
                FoldFace();
            };
            foldAll.MouseEnter += (_, __) => FoldFace();     // (the tree may have been opened row by row meanwhile)
            FoldFace();
            types.Margin = new Thickness(0);
            var typesRow = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(14, 0, 14, 10), HorizontalAlignment = HorizontalAlignment.Left };
            typesRow.Children.Add(foldAll);
            typesRow.Children.Add(types);
            DockPanel.SetDock(typesRow, Dock.Top);
            panel.Children.Add(typesRow);

            // «Alleggerisci» at the bottom, always in sight (MainWindow.Lighten.cs)
            var lighten = BuildLightenBox();
            DockPanel.SetDock(lighten, Dock.Bottom);
            panel.Children.Add(lighten);

            _treeRows = new StackPanel { Margin = new Thickness(6, 0, 6, 12) };
            _treeScroll = new ScrollViewer { Content = _treeRows, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, AllowDrop = true, Background = Brushes.Transparent };
            _treeScroll.Drop += async (_, e) => await OnTreeDrop(e, "");
            // (15/11) the right button on the empty part of the tree: a new empty group
            // (Luca: «incolla … anche fuori dal gruppo dovrei poter fare incolla») and «Incolla» when something was copied:
            // the menu is filled when it opens, with what applies then
            var emptyMenu = new ContextMenu();
            emptyMenu.Opened += (_, __) =>
            {
                emptyMenu.Items.Clear();
                if (_clipboard.Count > 0)
                {
                    var paste = new MenuItem { Header = L.T("Incolla in cima all'albero…") };
                    paste.Click += async (ps, pe) => await PasteClipboard("");
                    emptyMenu.Items.Add(paste);
                    emptyMenu.Items.Add(new Separator());
                }
                var newGroup = new MenuItem { Header = L.T("Nuovo gruppo vuoto") };
                newGroup.Click += async (gs, ge) => await AddObject("group", "");
                emptyMenu.Items.Add(newGroup);
            };
            emptyMenu.Items.Add(new MenuItem { Header = L.T("Nuovo gruppo vuoto") });     // (a menu with no items does not open: replaced at once)
            _treeScroll.ContextMenu = emptyMenu;
            panel.Children.Add(_treeScroll);
            return new Border { Child = panel, BorderBrush = Theme.B(Theme.Line), BorderThickness = new Thickness(0, 0, 1, 0) };
        }

        StackPanel _propsTop = null!;

        UIElement BuildPropsPanel()
        {
            _props = new StackPanel();
            _propsTop = new StackPanel { Visibility = Visibility.Collapsed };     // fixed area above the scrolling part (material preview)
            var dock = new DockPanel();
            DockPanel.SetDock(_propsTop, Dock.Top);
            dock.Children.Add(_propsTop);
            dock.Children.Add(new ScrollViewer { Content = _props, VerticalScrollBarVisibility = ScrollBarVisibility.Auto });
            return new Border { Child = dock, Background = Theme.B(Theme.Panel), BorderBrush = Theme.B(Theme.Line), BorderThickness = new Thickness(1, 0, 0, 0) };
        }

        UIElement BuildLibrary()
        {
            var panel = new DockPanel { Background = Theme.B(Theme.Panel) };
            var tabs = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(14, 10, 14, 6) };
            // the menus by kind (models, materials, decals: from the internet or yours), then HDRI, lights, scenes, AI
            foreach (var menu in LibraryMenus.Select(m => m.menu).Distinct())
            {
                var b = Theme.Button(MenuTitle(menu), Theme.Kind.Ghost);
                b.MinHeight = 30;
                b.Margin = new Thickness(0, 0, 4, 0);
                var items = LibraryMenus.Where(m => m.menu == menu).ToList();
                if (items.Count == 1)
                    b.Click += (_, __) => ShowLibraryTab(items[0].id);
                else
                    b.Click += (_, __) =>
                    {
                        var cm = new ContextMenu { PlacementTarget = b, Placement = System.Windows.Controls.Primitives.PlacementMode.Bottom };
                        foreach (var it in items)
                        {
                            var mi = new MenuItem { Header = L.T(it.label), IsCheckable = false, FontWeight = it.id == _libraryTab ? FontWeights.SemiBold : FontWeights.Normal };
                            // (Luca: «rosse per simpler, gialle per mine e blu per package») the colours of their folders
                            var ic = SourceIcon(it.label);
                            if (ic != null) mi.Icon = ic;
                            var id = it.id;
                            mi.Click += (_, __) => ShowLibraryTab(id);
                            cm.Items.Add(mi);
                        }
                        cm.IsOpen = true;
                    };
                _libraryMenuButtons[menu] = b;
                tabs.Children.Add(b);
            }
            _librarySearch = Theme.Input("");
            _librarySearch.Width = 160;
            _librarySearch.Margin = new Thickness(10, 0, 0, 0);
            _librarySearch.ToolTip = L.T("Cerca nella libreria");
            _librarySearch.TextChanged += (_, __) =>
            {
                if (_searchSwitching) return;           // (another tab's own text put back: RenderLibrary is running)
                _searchByTab[_libraryTab] = _librarySearch.Text;
                if (_libraryTab is "materials" or "mymaterials" or "simplermats" or "search" or "polyhaven" or "objects" or "myplants" or "simplerplants" or "primitives" or "packplants" or "packmodels" or "phmodels" or "hdri" or "mydecals" or "simplerdecals" or "acgdecals") RenderLibrary();   // search looks inside every folder
                else FilterLibrary();
            };
            tabs.Children.Add(_librarySearch);
            // (1.78.4, Luca: «metti questa parte sopra al menu a sinistra, se no non si legge se le cartelle hanno molti
            // rami») the path of the folders on its own row above the menus, from the left, always the same height (the
            // 3D view does not change size from one section to another); a long path shows its end
            _libraryCrumbs = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center,
                                              Visibility = Visibility.Collapsed };
            _libraryCrumbScroll = new ScrollViewer { Content = _libraryCrumbs, HorizontalScrollBarVisibility = ScrollBarVisibility.Hidden,
                                                     VerticalScrollBarVisibility = ScrollBarVisibility.Disabled };
            var crumbRow = new Border { Height = 30, Margin = new Thickness(14, 8, 14, 0), Child = _libraryCrumbScroll };
            DockPanel.SetDock(crumbRow, Dock.Top);
            panel.Children.Add(crumbRow);
            tabs.Margin = new Thickness(14, 4, 14, 6);
            _libraryHint = Theme.Label(L.T("Seleziona un oggetto e clicca un materiale per applicarlo"), 12, Theme.TextFaint);
            _libraryHint.Margin = new Thickness(14, 0, 0, 0);
            _libraryHint.VerticalAlignment = VerticalAlignment.Center;
            tabs.Children.Add(_libraryHint);
            DockPanel.SetDock(tabs, Dock.Top);
            panel.Children.Add(tabs);
            _libraryTiles = new WrapPanel { Orientation = Orientation.Vertical, Margin = new Thickness(10, 0, 10, 10) };
            var st = Settings.Load();
            SetLibraryRows(st.LibraryRows > 0 ? st.LibraryRows : st.LibraryHeight >= 470 ? 3 : st.LibraryHeight >= 330 ? 2 : 1, save: false);
            _libraryScroller = new ScrollViewer { Content = _libraryTiles, HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, VerticalScrollBarVisibility = ScrollBarVisibility.Disabled };
            HookLibraryPaste();
            panel.Children.Add(_libraryScroller);
            return new Border { Child = panel };
        }

        // ================================================================ startup

        async Task StartEngine()
        {
            ShowBusy(L.T("Avvio del motore di render…"));
            var script = EngineHost.FindEngineScript();
            if (script == null)
            {
                Fatal(L.T("Non trovo la cartella 'engine' di Simpler.\nReinstalla Simpler o avvialo dalla sua cartella."));
                return;
            }
            var blender = EngineHost.FindBlender();
            if (blender == null)
            {
                RevealMain();
                Msg.Show(this, L.T("Simpler usa Blender 5.2 come motore di render.\nIndica dove si trova blender.exe."), "Simpler", MessageBoxButton.OK, MessageBoxImage.Information);
                var dlg = new Microsoft.Win32.OpenFileDialog { Filter = "Blender|blender.exe", Title = L.T("Seleziona blender.exe") };
                if (dlg.ShowDialog(this) != true) { Fatal(L.T("Senza Blender Simpler non può renderizzare.")); return; }
                blender = dlg.FileName;
                var s = Settings.Load(); s.BlenderPath = blender; s.Save();
            }
            try
            {
                SplashStatus(L.T("Avvio del motore di render…"));
                AppLog.Write("---- Simpler " + SettingsDialog.Version + " started");
                await _host.StartAsync(blender, script);
                AppLog.Write("engine started" + (_host.MemoryLimitBytes > 0 ? $" (memory limit {_host.MemoryLimitBytes / 1073741824.0:0.#} GB)" : ""));
                _host.Died += () => Dispatcher.BeginInvoke(new Action(OnEngineDied));
                EngineClient.TerrainBlend += ids => Dispatcher.BeginInvoke(new Action(async () => await PushZoneMaterials(ids)));
                EngineClient.OceanFollow += info => Dispatcher.BeginInvoke(new Action(() =>
                {
                    info.Remove("history");
                    _ambience["ocean"] = info;
                    if (_webReady) SendToWeb(new { type = "ocean", info = info.DeepClone() });
                    if (_rightPanel == "landscape") RenderProps();
                }));
                _api = new EngineClient(_host.Port);
                var ping = await _api.Get("ping");
                await PushSmartToEngine();          // (SmartView kept from the last time: the engine waits from the start)
                _engineLabel = $"Blender {(string?)ping["blender"]} · {DeviceLabel((string?)ping["device"])}";
                _statusRight.Text = _engineLabel;
                SetLibraryMaterials(await _api.Get("materials"));
                try { SetModels(await _api.Get("models")); } catch { /* the model library is not essential to start */ }
                _ = InitContentAsync();             // (cloud) the catalog of the contents in the cloud (cache at once, then the site)
                await LoadDecalRoot();
                try { await _api.Post("models/lock", new JsonObject { ["on"] = SimplerLocked }); } catch { }
                _environments = (await _api.Get("environments"))["environments"] as JsonArray ?? new JsonArray();
                RenderLibrary();
                if (!string.IsNullOrEmpty(_openAtStart) && File.Exists(_openAtStart))
                {
                    SplashStatus(L.F("Apertura di {0}…", Path.GetFileName(_openAtStart)));
                    await OpenProjectPath(_openAtStart);
                }
                SplashStatus(L.T("Preparazione della vista 3D…"));
                await RefreshScene();
                await StartViewer();
                // the app appears when the 3D view shows the scene (or after 10 minutes at most)
                await Task.WhenAny(_firstLoad.Task, Task.Delay(TimeSpan.FromMinutes(10)));
                HideBusy();
                AppLog.Write("main window shown");
                if (!InStudio) StartAutosave();
                StartWorkIndicator();
                StartSkyTableWatch();
                if (!InStudio) _ = TestAiKeyAtStart();
                if (!InStudio) StartVideoWatch();          // (1.75.43) videos asked to Krea before Simpler was closed
                RevealMain();
                if (!InStudio) ShowNotesOnFirstRun();
                if (!InStudio) StartUpdateCheck();         // (1.78.4) in the background, at most once a day
                Status(L.T("Pronto. Importa un modello o aggiungi oggetti dal pulsante +"));
            }
            catch (Exception ex)
            {
                Fatal(L.T("Il motore di render non è partito.") + L.T("\n\n") + ex.Message + L.T("\n\n") + L.F("Dettagli nel log: {0}", _host.LogPath));
            }
        }

        static string DeviceLabel(string? d) => d switch
        {
            "OPTIX" => L.T("GPU NVIDIA (OptiX)"),
            "CUDA" => "GPU NVIDIA (CUDA)",
            "HIP" => "GPU AMD",
            "ONEAPI" => L.T("GPU Intel"),
            _ => L.T("solo CPU"),
        };

        void ShowNotesOnFirstRun()
        {
            var s = Settings.Load();
            if (s.LastSeenVersion == SettingsDialog.Version) return;
            s.LastSeenVersion = SettingsDialog.Version;
            s.Save();
            Dispatcher.BeginInvoke(async () => await ShowNotesPanel());
        }

        void Fatal(string message)
        {
            RevealMain();
            ShowBusy(L.T("Motore non disponibile"));
            Msg.Show(this, message, "Simpler", MessageBoxButton.OK, MessageBoxImage.Error);
        }


        void Status(string text, bool error = false)
        {
            _status.Text = text;
            _status.Foreground = Theme.B(error ? Theme.Danger : Theme.TextMuted);
        }

        /// <summary>Runs an engine call and hands any error message to <paramref name="onError"/> (for errors the user must see).</summary>
        async Task RunOrError(Action<string> onError, Func<EngineClient, Task> action)
        {
            if (_api == null) { onError(L.T("Il motore di render non è avviato")); return; }
            try { await action(_api); }
            catch (EngineException ex) { onError(ex.Message); }
            catch (Exception ex) { onError(L.T("Errore di comunicazione con il motore: ") + ex.Message); }
        }

        /// <summary>Runs an engine call; engine errors go to the status bar instead of crashing.</summary>
        int _engineCalls;
        DateTime _engineCallStart;
        bool _engineDead;

        async Task Run(Func<EngineClient, Task> action)
        {
            if (_api == null || _engineDead) return;
            if (_engineCalls++ == 0) _engineCallStart = DateTime.UtcNow;
            try { await action(_api); }
            catch (EngineException ex) { Status(ex.Message, true); }
            catch (Exception ex) { Status(L.T("Errore di comunicazione con il motore: ") + ex.Message, true); }
            finally { _engineCalls--; }
        }

        /// <summary>Esc while the engine has been busy for a while on one request: it may be stuck in a computation
        /// Blender cannot interrupt (a huge remesh). It can be stopped: Simpler starts again.</summary>
        bool OfferEngineStop()
        {
            if (_engineCalls <= 0 || _engineDead) return false;
            var secs = (DateTime.UtcNow - _engineCallStart).TotalSeconds;
            if (secs < 4) return false;
            var q = L.F("Il motore di render è occupato da {0} secondi e non risponde.\n\nFermarlo? Simpler ripartirà e riaprirà l'ultimo progetto salvato: le modifiche non salvate andranno perse.", (int)secs);
            if (Msg.Show(this, q, "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Warning) != MessageBoxResult.Yes) return true;
            AppLog.Write($"engine stopped by the user after {secs:0} s");
            _host.Kill();
            return true;
        }

        /// <summary>Whether the engine's log ends with a crash of Blender (EXCEPTION_..., and the path of its
        /// report), rather than a stop for memory.</summary>
        (bool crashed, string? report) EngineCrashReport()
        {
            try
            {
                using var fs = new FileStream(_host.LogPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
                if (fs.Length > 65536) fs.Seek(-65536, SeekOrigin.End);
                using var sr = new StreamReader(fs);
                var tail = sr.ReadToEnd();
                if (!tail.Contains("EXCEPTION_") && !tail.Contains("Segmentation fault")) return (false, null);
                string? report = null;
                foreach (var line in tail.Split('\n'))
                    if (line.StartsWith("Writing: ") && line.TrimEnd().EndsWith(".crash.txt")) report = line.Substring(9).Trim();
                return (true, report);
            }
            catch { return (false, null); }
        }

        /// <summary>The engine stopped (out of memory, stopped with Esc, crash): Simpler starts again with the last saved project.</summary>
        void OnEngineDied()
        {
            if (_engineDead) return;
            _engineDead = true;
            AppLog.Write("engine ended unexpectedly");
            var limit = _host.MemoryLimitBytes > 0 ? L.F(" (limite {0} GB)", (_host.MemoryLimitBytes / 1073741824.0).ToString("0")) : "";
            // the engine's log says whether Blender crashed (an internal error, with its report) or was stopped:
            // the memory was not always the cause
            var (crashed, report) = EngineCrashReport();
            if (crashed) AppLog.Write("engine crash: Blender error" + (report != null ? ", report " + report : ""));
            var msg = (crashed
                    ? L.T("Il motore di render (Blender) si è interrotto per un errore interno: non per la memoria.") + (report != null ? L.F(" Il rapporto dell'errore è in «{0}».", report) : "") + L.T("\n\nSimpler riparte ora")
                    : L.F("Il motore di render si è fermato: probabilmente l'ultima operazione chiedeva più memoria di quella a disposizione{0}, ed è stato fermato per non bloccare il computer.\n\nSimpler riparte ora", limit))
                      + (_projectPath != null ? L.F(" e riapre «{0}» (l'ultimo salvataggio).", Path.GetFileNameWithoutExtension(_projectPath)) : ".");
            Msg.Show(this, msg, "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning);
            try
            {
                var psi = new System.Diagnostics.ProcessStartInfo(Environment.ProcessPath ?? "Simpler.exe") { UseShellExecute = false };
                if (_projectPath != null) psi.ArgumentList.Add(_projectPath);
                System.Diagnostics.Process.Start(psi);
            }
            catch { }
            _closeConfirmed = true;
            Application.Current.Shutdown();
        }

        // ================================================================ keyboard

        /// <summary>The element is the page of rodluc.com open in the view, or something inside its panel.</summary>
        bool InSitePage(object? o)
        {
            for (var d = o as DependencyObject; d != null; d = d is Visual || d is System.Windows.Media.Media3D.Visual3D ? VisualTreeHelper.GetParent(d) ?? LogicalTreeHelper.GetParent(d) : LogicalTreeHelper.GetParent(d))
                if (ReferenceEquals(d, _ideasPanel)) return true;
            return false;
        }

        void OnKey(object sender, KeyEventArgs e)
        {
            // (Luca: «Ctrl+C è stato fatto ma non copia») typing in the ideas page: every key belongs to the page
            // (Ctrl+C/V/Z, Delete, W/E/R...), not to the scene - it took Ctrl+V as a paste of objects
            // (Luca: «non lo hai risolto, devo poter incollare il testo!») the web view is a window of its own: WPF does not
            // see the focus inside it (IsKeyboardFocusWithin stays false), the keys it hands over come with the web view
            // itself as source - so the source and the focused element are looked at too
            if (_ideasPanel != null && (InSitePage(e.OriginalSource) || InSitePage(Keyboard.FocusedElement) || _ideasWeb?.IsKeyboardFocusWithin == true)) return;
            StudioKey(e);
            if (e.Handled) return;
            if (FinalRenderKey(e.Key == Key.System ? e.SystemKey : e.Key)) { e.Handled = e.Key != Key.System || e.SystemKey != Key.F4; return; }
            if (_saving)
            {
                // Esc would offer to stop the engine: in the middle of a save the file could stay incomplete
                if (e.Key == Key.Escape) Status(L.T("Salvataggio in corso: attendi la fine"));
                e.Handled = true;
                return;
            }
            if (Keyboard.FocusedElement is TextBox tb)
            {
                // Ctrl+Z / Ctrl+Y in the number box of a slider whose value was already taken (Enter or click away):
                // the undo of the app, not of the text (the focus stayed in the box and the step was never undone)
                bool ctrlKey = (Keyboard.Modifiers & ModifierKeys.Control) != 0;
                if (!(ctrlKey && (e.Key == Key.Z || e.Key == Key.Y) && tb.Tag is ValueSlider vs && !vs.Pending)) return;
                Keyboard.ClearFocus();
                FocusManager.SetFocusedElement(this, this);
            }
            if (e.Key == Key.Escape && OfferEngineStop()) { e.Handled = true; return; }
            if (BusyKey(e.Key == Key.Escape)) { e.Handled = true; return; }
            bool ctrl = (Keyboard.Modifiers & ModifierKeys.Control) != 0;
            switch (e.Key)
            {
                case Key.W when !ctrl: SetTool("move"); break;
                case Key.E when !ctrl: SetTool("rotate"); break;
                case Key.R when !ctrl: SetTool("scale"); break;
                case Key.B when !ctrl: SetTool(_tool == "paint" ? "move" : "paint"); break;
                case Key.F when !ctrl: _ = FrameSelection(); break;
                case Key.Delete: _ = DeleteSelected(); break;
                case Key.D when ctrl: _ = DuplicateSelected(); break;
                case Key.G when ctrl: _ = GroupSelected(); break;
                case Key.C when ctrl: CopySelected(); break;
                case Key.V when ctrl: _ = PasteClipboard(); break;
                case Key.S when ctrl && (Keyboard.Modifiers & ModifierKeys.Shift) != 0: _ = SaveProject(true); break;
                case Key.S when ctrl: _ = SaveProject(false); break;
                case Key.O when ctrl: _ = OpenProject(); break;
                case Key.N when ctrl: _ = NewProject(); break;
                case Key.I when ctrl: _ = ImportModel(); break;
                case Key.Escape when Painting: SetTool("move"); break;
                case Key.Escape: Select(""); break;
                case Key.F2 when _selected != "": BeginRename(_selected); break;
                case Key.Z when ctrl && (Keyboard.Modifiers & ModifierKeys.Shift) != 0: _ = Redo(); break;
                case Key.Z when ctrl: _ = Undo(); break;
                case Key.Y when ctrl: _ = Redo(); break;
                case Key.A when ctrl: SelectAll(); break;
                case Key.Space when !ctrl && Keyboard.FocusedElement is not Button: _ = SetRealistic(!_realistic); break;
                default: return;
            }
            e.Handled = true;
        }

        void SetNavSpeed(string id)
        {
            string[] ids = { "ant", "walk", "bike", "car" };
            Theme.SetSegment(_speedButtons, Math.Max(0, Array.IndexOf(ids, id)));
            foreach (var b in _speedButtons) b.Padding = new Thickness(8, 0, 8, 0);
            var s = Settings.Load(); s.NavSpeed = id; s.Save();
            SendToWeb(new { type = "speed", level = id });
        }

        void SetTool(string tool)
        {
            var was = _tool;
            _tool = tool == "rotate" ? "move" : tool;          // (E: the same gizmo, it rotates too)
            if (_tool == "paint" && !(_webReady)) _tool = "move";
            Theme.SetSegment(_toolButtons, _tool == "scale" ? 1 : _tool == "paint" ? -1 : 0);
            if (_scatterPanelButton != null) { Theme.Style(_scatterPanelButton, _tool == "paint" ? Theme.Kind.Segment : Theme.Kind.Ghost); FitHeader(); }
            foreach (var b in _toolButtons) b.Padding = new Thickness(10, 0, 10, 0);
            UpdateGizmo();
            if (_tool == "paint" && was != "paint")
            {
                // the brush starts on the distribution selected in the tree (its models come back in the panel)
                var sel = _selected != "" && _scene.ById.TryGetValue(_selected, out var so)
                    ? new[] { so }.Concat(_scene.Ancestors(so)).FirstOrDefault(x => x.Paint && x.Eco == "") : null;
                if (sel != null && sel.Id != _paintGroup) SwitchPaintGroup(sel.Id);
                else if (_paintGroup != "") _ = LoadPaintGroup(_scene.ById.ContainsKey(_paintGroup) ? _paintGroup : "");
            }
            if (_tool == "paint" || was == "paint") SendPaint();
            if (_tool == "paint" && _rightPanel != "paint") _ = ShowRightPanel("paint");
            else if (_tool != "paint" && was == "paint" && _rightPanel == "paint") _ = ShowRightPanel("");
        }
    }
}
