using System;
using System.Collections.Generic;
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
    /// <summary>Camera effects (engine: post.py, luts.py; view: viewer.js FX): colour (contrast, saturation, white
    /// balance, tint, look/LUT) in the «Colore ed esposizione» card, the lens and film effects in its «Avanzate».
    /// All on the finished picture: no new render; the real-time view follows the sliders while they move.</summary>
    public sealed partial class MainWindow
    {
        static readonly string[] FxKeys = { "fxTemp", "fxTint", "fxContrast", "fxSaturation", "fxLut", "fxLutAmount", "fxBloom",
                                            "fxVignette", "fxCA", "fxGrain", "fxGrainSize", "fxSharpen" };
        static Geometry MakeGeometry(string d) { var g = Geometry.Parse(d); g.Freeze(); return g; }

        JsonObject? _luts;          // GET luts: Simpler's looks, the imported ones, the favourites

        /// <summary>The camera effects to the real-time view (the path tracing frame comes already done by the engine).
        /// over: values being dragged, not yet sent to the engine.</summary>
        void PushFxToViewer(string? overKey = null, double overValue = 0)
        {
            if (!_webReady) return;
            var cfg = _renderSettings["config"] as JsonObject;
            double D(string k, double def) => k == overKey ? overValue : (double?)cfg?[k] ?? def;
            SendToWeb(new
            {
                type = "fx", temp = D("fxTemp", 6500), tint = D("fxTint", 0), contrast = D("fxContrast", 0), saturation = D("fxSaturation", 1),
                lut = (string?)cfg?["fxLut"] ?? "", lutAmount = D("fxLutAmount", 1), bloom = D("fxBloom", 0), vignette = D("fxVignette", 0),
                ca = D("fxCA", 0), grain = D("fxGrain", 0), grainSize = D("fxGrainSize", 0.3), sharpen = D("fxSharpen", 0),
            });
        }

        /// <summary>A slider of a camera effect: shown as the user wants it (scale, offset), stored as the engine wants it.</summary>
        UIElement FxSlider(string label, string key, double def, double min, double max, double scale, string fmt, string unit, string tip, bool log = false)
        {
            var cfg = _renderSettings["config"] as JsonObject;
            var s = new ValueSlider(label, ((double?)cfg?[key] ?? def) * scale, min, max, log, fmt, unit, null, tip);
            s.Changing += v => PushFxToViewer(key, v / scale);
            s.Committed += async v => await SetConfig(key, JsonValue.Create(Math.Round(v / scale, 4)));
            return s;
        }

        /// <summary>The colour sliders and the look in the card; its «Avanzate» with the lens and film effects (and, when
        /// given, the other advanced settings of the card: extra).</summary>
        void AddCameraFx(StackPanel col, Action<StackPanel>? extra = null, bool extraChanged = false, Func<Task>? extraReset = null)
        {
            var cfg = _renderSettings["config"] as JsonObject ?? new JsonObject();
            double C(string k, double def) => (double?)cfg[k] ?? def;
            col.Children.Add(FxSlider(L.T("Contrasto"), "fxContrast", 0, -100, 100, 100, "0", "%",
                L.T("Più differenza tra chiari e scuri (o meno, verso sinistra). Subito, senza ricalcolare; vale anche per il render finale")));
            col.Children.Add(FxSlider(L.T("Saturazione"), "fxSaturation", 1, 0, 200, 100, "0", "%",
                L.T("0% = bianco e nero · 100% = colori come sono · 200% = molto più vivi")));
            col.Children.Add(FxSlider(L.T("Temperatura"), "fxTemp", 6500, 2000, 12000, 1, "0", "K",
                L.T("Bilanciamento del bianco: più basso = più freddo (blu), più alto = più caldo (giallo). 6500 K = neutro")));
            col.Children.Add(FxSlider(L.T("Tinta"), "fxTint", 0, -100, 100, 100, "0", "",
                L.T("Verso il verde (a sinistra) o il magenta (a destra), per correggere una dominante")));
            col.Children.Add(LutRow(cfg));
            if (((string?)cfg["fxLut"] ?? "") != "")
                col.Children.Add(FxSlider(L.T("Intensità del look"), "fxLutAmount", 1, 0, 100, 100, "0", "%",
                    L.T("Quanto del look applicare: 0% = immagine originale, 100% = look pieno")));

            var a = Advanced(col, "camerafx");
            a.Body.Children.Add(Theme.Label(L.T("Effetti dell'obiettivo e della pellicola"), 12, Theme.TextMuted));
            a.Body.Children.Add(FxSlider(L.T("Bagliore"), "fxBloom", 0, 0, 100, 100, "0", "%",
                L.T("Un alone attorno alle luci forti e ai punti più chiari (finestre, lampade, riflessi)")));
            a.Body.Children.Add(FxSlider(L.T("Vignettatura"), "fxVignette", 0, 0, 100, 100, "0", "%",
                L.T("Angoli più scuri del centro, come con un obiettivo vero: porta lo sguardo al centro")));
            a.Body.Children.Add(FxSlider(L.T("Aberrazione cromatica"), "fxCA", 0, 0, 100, 100, "0", "%",
                L.T("Bordi colorati rosso e blu verso i lati dell'immagine, come in un obiettivo economico")));
            a.Body.Children.Add(FxSlider(L.T("Grana"), "fxGrain", 0, 0, 100, 100, "0", "%",
                L.T("Grana della pellicola: con un po' di Nitidezza dà l'effetto «crispy» delle foto vere")));
            a.Body.Children.Add(FxSlider(L.T("Dimensione grana"), "fxGrainSize", 0.3, 0, 100, 100, "0", "%",
                L.T("Grana fine (0%) o grossa (100%), uguale nella vista e nel render finale")));
            a.Body.Children.Add(FxSlider(L.T("Nitidezza"), "fxSharpen", 0, 0, 100, 100, "0", "%",
                L.T("Dettagli più netti (maschera di contrasto sui pixel)")));
            extra?.Invoke(a.Body);
            a.Done(extraChanged || C("fxBloom", 0) > 1e-3 || C("fxVignette", 0) > 1e-3 || C("fxCA", 0) > 1e-3 || C("fxGrain", 0) > 1e-3
                   || Math.Abs(C("fxGrainSize", 0.3) - 0.3) > 1e-3 || C("fxSharpen", 0) > 1e-3,
                async () =>
                {
                    var c = new JsonObject { ["fxBloom"] = 0.0, ["fxVignette"] = 0.0, ["fxCA"] = 0.0, ["fxGrain"] = 0.0, ["fxGrainSize"] = 0.3, ["fxSharpen"] = 0.0 };
                    await RsPost(new JsonObject { ["config"] = c });
                    if (extraReset != null) await extraReset();
                    PushFxToViewer();
                    RenderProps();
                });
        }

        // ---------------------------------------------------------------- look (LUT)

        UIElement LutRow(JsonObject cfg)
        {
            var id = (string?)cfg["fxLut"] ?? "";
            if (_luts == null) _ = LoadLuts();
            var item = (_luts?["items"] as JsonArray)?.OfType<JsonObject>().FirstOrDefault(x => (string?)x["id"] == id);
            var name = id == "" ? L.T("Nessuno") : (string?)item?["name"] ?? L.T("(non trovato su questo computer)");
            var row = new DockPanel { Margin = new Thickness(0, 2, 0, 12) };
            var l = Theme.Label(L.T("Look (LUT)"), 12, Theme.TextMuted);
            l.Width = 96;
            l.VerticalAlignment = VerticalAlignment.Center;
            l.ToolTip = L.T("Un look di colore pronto (tabella LUT): quelli di Simpler, o i file .cube che importi. Ogni look si vede in anteprima sulla tua inquadratura; tasto destro per i preferiti");
            row.Children.Add(l);
            var b = Theme.Button(new DockPanel
            {
                Children =
                {
                    new TextBlock { Text = name, TextTrimming = TextTrimming.CharacterEllipsis, VerticalAlignment = VerticalAlignment.Center, MaxWidth = 170 },
                },
            }, Theme.Kind.Normal, L.T("Scegli un look"));
            b.HorizontalAlignment = HorizontalAlignment.Left;
            b.HorizontalContentAlignment = HorizontalAlignment.Left;
            b.MinWidth = 190;
            b.Click += (_, __) => OpenLutPicker(b);
            row.Children.Add(b);
            return row;
        }

        async Task LoadLuts()
        {
            if (_api == null) return;
            try { _luts = await _api.Get("luts"); } catch { return; }
            LutsChanged();
        }

        void LutsChanged()
        {
            if (_rightPanel == "render") RenderProps();
            if (_libraryTab == "favorites") RenderLibrary();
        }

        // a look: three bands of colour (the icon of the folder of the favourite looks)
        static readonly Geometry LutIcon = MakeGeometry("M4 6h16M4 12h16M4 18h16M8 4v4M15 10v4M10 16v4");

        List<JsonObject> LutFavs() =>
            (_luts?["items"] as JsonArray)?.OfType<JsonObject>().Where(x => (bool?)x["fav"] == true).ToList() ?? new List<JsonObject>();

        /// <summary>A favourite look in the library: its preview on the view (or on a chart of colours before the list of
        /// the looks was opened); click: applied to the camera.</summary>
        Button LutTile(JsonObject it)
        {
            var id = (string?)it["id"] ?? "";
            var name = (string?)it["name"] ?? id;
            var img = LutPreview(id, 84, 52);
            img.Margin = new Thickness(0, 6, 0, 8);
            img.HorizontalAlignment = HorizontalAlignment.Center;
            var cur = (string?)(_renderSettings["config"] as JsonObject)?["fxLut"] ?? "";
            var btn = BigTile(new Border { Child = img, CornerRadius = new CornerRadius(6), ClipToBounds = true }, name,
                              id == cur ? L.T("in uso") : (string?)it["group"] ?? "", name + "\n" + L.T("Clic: applica il look alla fotocamera"));
            btn.Click += async (_, __) =>
            {
                await SetConfig("fxLut", JsonValue.Create(id));
                Status(L.F("Look «{0}» applicato", name));
                if (_libraryTab == "favorites") RenderLibrary();
            };
            var m = new ContextMenu();
            var off = new MenuItem { Header = L.T("Togli dai preferiti") };
            off.Click += async (_, __) => { try { _luts = await _api!.Post("luts/favorite", new JsonObject { ["id"] = id, ["on"] = false }); } catch { } LutsChanged(); };
            m.Items.Add(off);
            btn.ContextMenu = m;
            return btn;
        }

        string _lutSrcKey = "";

        /// <summary>The small picture of the view that the previews of the looks are made from (engine: luts.set_source).
        /// "" when the view does not answer: the previews then use a chart of colours.</summary>
        async Task<string> LutPreviewSource()
        {
            var b64 = await CaptureViewSnapshot(292, 184, 0.9);
            if (string.IsNullOrEmpty(b64) || _api == null) return _lutSrcKey;
            try
            {
                var bi = new System.Windows.Media.Imaging.BitmapImage();
                bi.BeginInit();
                bi.StreamSource = new System.IO.MemoryStream(Convert.FromBase64String(b64));
                bi.CacheOption = System.Windows.Media.Imaging.BitmapCacheOption.OnLoad;
                bi.EndInit();
                var rgb = new System.Windows.Media.Imaging.FormatConvertedBitmap(bi, PixelFormats.Rgb24, null, 0);
                int w = rgb.PixelWidth, h = rgb.PixelHeight;
                var px = new byte[w * h * 3];
                rgb.CopyPixels(px, w * 3, 0);
                var r = await _api.Post("lut/source", new JsonObject { ["w"] = w, ["h"] = h, ["rgb"] = Convert.ToBase64String(px) });
                _lutSrcKey = (string?)r["key"] ?? "";
            }
            catch (Exception ex) { AppLog.Write("look previews: " + ex.Message); }
            return _lutSrcKey;
        }

        Image LutPreview(string id, double w, double h)
        {
            var img = new Image { Width = w, Height = h, Stretch = Stretch.UniformToFill };
            // (15/11, Luca: «un arcobaleno di colori nelle miniature») without the picture of the view the engine drew the looks
            // on a chart of colours: no picture at all then, the tile says that the preview is coming (LutItem)
            if (_lutSrcKey == "") return img;
            try
            {
                var bi = new System.Windows.Media.Imaging.BitmapImage();
                bi.BeginInit();
                bi.UriSource = new Uri($"http://127.0.0.1:{_host.Port}/api/lut/thumb?id={Uri.EscapeDataString(id)}&k={_lutSrcKey}");
                bi.CacheOption = System.Windows.Media.Imaging.BitmapCacheOption.OnLoad;
                bi.EndInit();
                img.Source = bi;
            }
            catch { }
            return img;
        }

        /// <summary>The looks as previews of the view: a click chooses one; right click: favourites (and, for the
        /// imported ones, remove).</summary>
        async void OpenLutPicker(FrameworkElement anchor)
        {
            await LutPreviewSource();
            var popup = new Popup { PlacementTarget = anchor, Placement = PlacementMode.Bottom, StaysOpen = false, AllowsTransparency = true };
            var list = new WrapPanel();
            var search = new TextBox { Margin = new Thickness(0, 0, 0, 8), Padding = new Thickness(6, 4, 6, 4), Background = Theme.B(Theme.Inset),
                                       Foreground = Theme.B(Theme.Text), BorderBrush = Theme.B(Theme.Line), CaretBrush = Theme.B(Theme.Text) };
            Theme.AddClear(search);          // (1.75.47)
            search.ToolTip = L.T("Cerca per nome");
            var root = new DockPanel { Width = 336 };
            DockPanel.SetDock(search, Dock.Top);
            root.Children.Add(search);
            var foot = new WrapPanel { Margin = new Thickness(0, 8, 0, 0) };
            DockPanel.SetDock(foot, Dock.Bottom);
            root.Children.Add(foot);
            root.Children.Add(new ScrollViewer { Content = list, MaxHeight = 440, VerticalScrollBarVisibility = ScrollBarVisibility.Auto });
            popup.Child = new Border { Child = root, Background = Theme.B(Theme.Raised), BorderBrush = Theme.B(Theme.LineStrong), BorderThickness = new Thickness(1),
                                       CornerRadius = new CornerRadius(10), Padding = new Thickness(10) };
            var imp = Theme.Button(L.T("Importa file…"), Theme.Kind.Ghost, L.T("File .cube, o archivi .zip che li contengono (ogni archivio diventa un gruppo)"));
            imp.MinHeight = 28; imp.FontSize = 12;
            imp.Click += async (_, __) => { popup.IsOpen = false; await ImportLuts(false); };
            var impDir = Theme.Button(L.T("Importa cartella…"), Theme.Kind.Ghost, L.T("Tutti i file .cube di una cartella e delle sue sottocartelle (la cartella diventa un gruppo)"));
            impDir.MinHeight = 28; impDir.FontSize = 12;
            impDir.Click += async (_, __) => { popup.IsOpen = false; await ImportLuts(true); };
            foot.Children.Add(imp);
            foot.Children.Add(impDir);

            void Fill()
            {
                list.Children.Clear();
                var items = (_luts?["items"] as JsonArray)?.OfType<JsonObject>().ToList() ?? new List<JsonObject>();
                var q = search.Text.Trim();
                if (q != "") items = items.Where(x => ((string?)x["name"] ?? "").Contains(q, StringComparison.CurrentCultureIgnoreCase)).ToList();
                var cur = (string?)(_renderSettings["config"] as JsonObject)?["fxLut"] ?? "";
                void Header(string title, int n)
                {
                    var h = Theme.Label(title.ToUpperInvariant() + "  ·  " + n, 11, Theme.TextFaint);
                    h.Margin = new Thickness(4, 8, 0, 4);
                    h.Width = 320;
                    list.Children.Add(h);
                }
                if (q == "") list.Children.Add(LutItem(null, cur == "", popup, Fill));
                void Group(string title, IEnumerable<JsonObject> g)
                {
                    var arr = g.ToList();
                    if (arr.Count == 0) return;
                    Header(title, arr.Count);
                    foreach (var it in arr) list.Children.Add(LutItem(it, (string?)it["id"] == cur, popup, Fill));
                }
                Group(L.T("Preferiti"), items.Where(x => (bool?)x["fav"] == true));
                foreach (var g in items.GroupBy(x => (string?)x["group"] ?? "").OrderBy(g => g.Key == "Simpler" ? 0 : 1).ThenBy(g => g.Key, StringComparer.CurrentCultureIgnoreCase))
                    Group(g.Key, g);
                if (items.Count == 0 && q != "") list.Children.Add(Theme.Label(L.T("Nessun look con questo nome"), 12, Theme.TextFaint));
            }
            search.TextChanged += (_, __) => Fill();
            Fill();
            popup.IsOpen = true;
            search.Focus();
            // the view was busy and gave no picture: asked again every 2 s while the list is open (up to 2 minutes); the
            // previews are drawn as soon as it arrives
            for (int i = 0; i < 60 && _lutSrcKey == "" && popup.IsOpen; i++)
            {
                await Task.Delay(2000);
                if (!popup.IsOpen) break;
                await LutPreviewSource();
                if (_lutSrcKey != "" && popup.IsOpen) Fill();
            }
        }

        /// <summary>A look in the list: its preview on the view, the name under it; a small black heart on the
        /// favourites (right click to add or take away).</summary>
        UIElement LutItem(JsonObject? it, bool current, Popup popup, Action refill)
        {
            var id = (string?)it?["id"] ?? "";
            var name = it == null ? L.T("Nessuno") : (string?)it["name"] ?? id;
            var pic = new Grid();
            pic.Children.Add(new Border { Child = LutPreview(id, 148, 92), CornerRadius = new CornerRadius(6), ClipToBounds = true });
            if (_lutSrcKey == "")
            {
                var wait = Theme.Label(L.T("Anteprima in arrivo…"), 11, Theme.TextFaint);
                wait.HorizontalAlignment = HorizontalAlignment.Center; wait.VerticalAlignment = VerticalAlignment.Center;
                pic.Children.Insert(0, new Border { Width = 148, Height = 92, CornerRadius = new CornerRadius(6), Background = Theme.B(Theme.Inset) });
                pic.Children.Add(wait);
            }
            bool fav = it != null && (bool?)it["fav"] == true;
            if (fav) pic.Children.Add(HeartMark(14));
            var label = Theme.Label(name, 12, current ? Colors.White : Theme.TextSoft);
            label.TextTrimming = TextTrimming.CharacterEllipsis;
            label.Margin = new Thickness(2, 4, 2, 0);
            var sp = new StackPanel();
            sp.Children.Add(pic);
            sp.Children.Add(label);
            var tile = new Border
            {
                Child = sp, Width = 158, Margin = new Thickness(0, 0, 4, 6), Padding = new Thickness(4), CornerRadius = new CornerRadius(8),
                Background = current ? Theme.B(Theme.Selected) : Brushes.Transparent, Cursor = Cursors.Hand,
                BorderBrush = current ? Theme.B(Theme.Accent) : Brushes.Transparent, BorderThickness = new Thickness(1), ToolTip = name,
            };
            tile.MouseEnter += (_, __) => { if (!current) tile.Background = Theme.B("#1B2C4E"); };
            tile.MouseLeave += (_, __) => { if (!current) tile.Background = Brushes.Transparent; };
            tile.MouseLeftButtonUp += async (_, __) =>
            {
                popup.IsOpen = false;
                await SetConfig("fxLut", JsonValue.Create(id));
            };
            if (it == null) return tile;
            var m = new ContextMenu();
            var favItem = new MenuItem { Header = fav ? L.T("Togli dai preferiti") : L.T("Aggiungi ai preferiti") };
            favItem.Click += async (_, __) =>
            {
                try { _luts = await _api!.Post("luts/favorite", new JsonObject { ["id"] = id, ["on"] = !fav }); } catch { return; }
                refill();
                if (_libraryTab == "favorites") RenderLibrary();
                Status(fav ? L.F("«{0}» tolto dai preferiti", name) : L.F("«{0}» aggiunto ai preferiti ({1})", name, L.T("Look (LUT)")));
            };
            m.Items.Add(favItem);
            if ((bool?)it["user"] == true)
            {
                m.Items.Add(new Separator());
                var del = new MenuItem { Header = L.T("Rimuovi questo look") };
                del.Click += async (_, __) => { try { _luts = await _api!.Post("luts/delete", new JsonObject { ["id"] = id }); } catch { } refill(); };
                m.Items.Add(del);
                var grp = (string?)it["group"] ?? "";
                if (grp != L.T("Importati"))
                {
                    var delG = new MenuItem { Header = L.F("Rimuovi tutto il gruppo «{0}»", grp) };
                    delG.Click += async (_, __) => { try { _luts = await _api!.Post("luts/delete", new JsonObject { ["group"] = grp }); } catch { } refill(); };
                    m.Items.Add(delG);
                }
            }
            tile.ContextMenu = m;
            return tile;
        }

        async Task ImportLuts(bool folder)
        {
            var paths = new List<string>();
            if (folder)
            {
                var d = new Microsoft.Win32.OpenFolderDialog { Title = L.T("Cartella con i file .cube"), Multiselect = true };
                if (d.ShowDialog(this) != true) return;
                paths.AddRange(d.FolderNames);
            }
            else
            {
                var d = new Microsoft.Win32.OpenFileDialog { Title = L.T("Look da importare"), Multiselect = true, Filter = L.T("Look LUT (*.cube, *.zip)") + "|*.cube;*.zip" };
                if (d.ShowDialog(this) != true) return;
                paths.AddRange(d.FileNames);
            }
            JsonObject? r = null;
            await Run(async api => { r = await api.Post("luts/import", new JsonObject { ["paths"] = new JsonArray(paths.Select(p => (JsonNode)p!).ToArray()) }); });
            if (r == null) return;
            _luts = r;
            int n = (int?)r["imported"] ?? 0, bad = (int?)r["skipped"] ?? 0;
            Status(n == 0 ? L.T("Nessun look importato: servono file .cube 3D") : bad > 0 ? L.F("{0} look importati ({1} file non validi saltati)", n, bad) : L.F("{0} look importati", n));
            RenderProps();
        }
    }
}
