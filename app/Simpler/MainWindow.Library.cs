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
    /// <summary>Bottom library: materials (path-traced previews), environments and saved scenes.</summary>
    public sealed partial class MainWindow
    {
        TextBlock _libraryHint = null!;
        JsonArray _views = new JsonArray();
        readonly Queue<string> _previewQueue = new Queue<string>();
        bool _previewWorker;
        readonly Dictionary<string, Image> _materialImages = new Dictionary<string, Image>();

        static string PreviewFolder => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Simpler", "previews");

        // (1.76.13, Luca: «il testo di ricerca deve valere solo per il menu selezionato») every tab of the library has
        // its own search text: going to another tab shows that tab's (empty the first time), coming back gives the
        // text it had
        readonly Dictionary<string, string> _searchByTab = new Dictionary<string, string>();
        string _searchTab = "";
        bool _searchSwitching;

        void SearchForTab()
        {
            if (_librarySearch == null || _searchTab == _libraryTab) return;
            if (_searchTab != "") _searchByTab[_searchTab] = _librarySearch.Text;
            _searchTab = _libraryTab;
            var want = _searchByTab.TryGetValue(_libraryTab, out var t) ? t : "";
            if (_librarySearch.Text == want) return;
            _searchSwitching = true;
            try { _librarySearch.Text = want; }
            finally { _searchSwitching = false; }
        }

        void RenderLibrary()
        {
            if (_libraryTab == "environments") _libraryTab = "hdri";           // (the old tab: its backgrounds are under HDRI)
            // (1.13.14: the Simpler menu is gone - its materials are a folder of Personali · Materiali, the primitives
            // a folder of Personali · Modelli 3D)
            if (_libraryTab == "materials") { _libraryTab = "simplermats"; _matFolder = SimplerMats; }
            // (1.78.1) the materials of Simpler have their own entry (Materiali ▸ Simpler); I miei never shows them
            if (_libraryTab == "simplermats" && !(_matFolder == SimplerMats || _matFolder.StartsWith(SimplerMats + "/"))) _matFolder = SimplerMats;
            if (_libraryTab == "mymaterials" && (_matFolder == SimplerMats || _matFolder.StartsWith(SimplerMats + "/"))) _matFolder = "";
            // (1.68.3: the primitives are an entry of the 3D models menu again, no more a folder of the personal ones)
            if (_libraryTab == "objects" && _objFolder == PrimitiveFolder) { _libraryTab = "primitives"; _objFolder = ""; }
            SearchForTab();
            foreach (var (menu, b) in _libraryMenuButtons)
            {
                var cur = LibraryMenus.FirstOrDefault(m => m.menu == menu && m.id == _libraryTab);
                var active = cur.id != null;
                Theme.Style(b, active ? Theme.Kind.Segment : Theme.Kind.Ghost);
                b.MinHeight = 30;
                var many = LibraryMenus.Count(m => m.menu == menu) > 1;
                b.Content = active && many ? MenuTitle(menu).Replace(" ▾", "") + " · " + L.T(cur.label) + " ▾" : MenuTitle(menu);
            }
            _libraryHint.Text = _libraryTab switch
            {
                "story" => L.T("Perché esiste Simpler"),
                "favorites" => L.T("I tuoi preferiti, divisi per tipo · tasto destro su un elemento: «Porta all'elemento» apre la sua cartella"),
                "simplereco" => L.T("Gli ecosistemi di Simpler: trascina su un oggetto (o sul suo materiale) e si popola · clic: sull'oggetto selezionato"),
                "ecosystems" => L.T("Trascina un ecosistema su un oggetto (o sul suo materiale) e si popola · clic: sull'oggetto selezionato · + per crearne uno sul banco di prova"),
                "lights" => L.T("Clicca per aggiungere al centro della vista, o trascina nella vista sulla superficie che vuoi"),
                "objects" => L.T("Clic: al centro della vista · trascina nella vista dove vuoi · tasto destro su un oggetto nella vista: Salva nella libreria"),
                "materials" => L.T("Trascina su un pezzo per applicarlo (Maiusc: tutto il gruppo) o su una cartella per spostarlo · clic per modificarlo"),
                "polyhaven" => L.T("Trascina su un pezzo per applicarla · clic per modificarla · Poly Haven, CC0"),
                "phmodels" => L.T("Clic: al centro della vista · trascina nella vista dove vuoi · si scarica al primo uso · Poly Haven, CC0"),
                "hdri" => L.T("Clic: il cielo fotografato diventa sfondo e luce della scena (il suo sole una luce Sole) · Sfondi da studio per la luce delle sole lampade"),
                "primitives" => L.T("Le forme di base e i modelli di Simpler: clic al centro della vista · trascina nella vista dove vuoi"),
                "packmodels" or "packplants" => L.T("I modelli dei pacchetti installati, una cartella blu per pacchetto: clic al centro della vista · trascina nella vista · tasto destro: Copia, poi incolla tra i tuoi modelli"),
                "simplerplants" => L.T("Le piante di Simpler: clic al centro della vista · trascina nella vista o nel pennello Distribuisci"),
                "myplants" => L.T("Le tue piante: clic al centro della vista · trascina nella vista o nel pennello Distribuisci · tasto destro: Foglie e legno…"),
                "mymaterials" => L.T("I tuoi materiali: trascina su un pezzo per applicarlo · clic per modificarlo"),
                "simplermats" => SimplerLocked ? L.T("I materiali di Simpler: trascina su un pezzo per applicarlo · clic per modificarlo (una copia diventa tua)")
                                               : L.T("I materiali di Simpler: trascina su un pezzo per applicarlo · clic per modificarlo"),
                "search" => L.T("Risultati in tutta la libreria, divisi per tipo: clic o trascina come nelle loro sezioni"),
                "acgdecals" => L.T("Decal di ambientCG (CC0): strisce stradali, colature, tombini… · clic al centro della vista, o trascina sul modello · si scaricano al primo uso"),
                "simplerdecals" => L.T("Le decal di Simpler: clic al centro della vista, o trascina sul modello dove la vuoi"),
                "mydecals" => L.T("Le tue decal (PNG con trasparenza): clic al centro della vista, o trascina sul modello dove la vuoi · tasto destro su una cartella: Apri decal…"),
                "aioutputs" => L.T("Le immagini e i video fatti con l'AI in questo progetto, ognuno nella sua cartella · tasto … per rinominare o eliminare · si salvano con il progetto, nella cartella «nome AI» accanto"),
                _ => L.T("Salva l'inquadratura con tutte le impostazioni; clicca una scena per tornarci, ⟳ per aggiornarla"),
            };
            _libraryTiles.Children.Clear();
            _materialImages.Clear();
            _badges.Clear();
            _dropFolders.Clear();
            _favTiles.Clear();
            _favHearts.Clear();
            _libraryCrumbs.Children.Clear();
            _libraryCrumbs.Visibility = Visibility.Collapsed;
            if (_libraryTab == "story") { RenderStory(); return; }
            if (_libraryTab == "favorites") { RenderFavorites(); return; }
            if (_libraryTab is "ecosystems" or "simplereco") { RenderEcosystems(); return; }
            if (_libraryTab == "myplants") { RenderVegBrowser(false); return; }
            if (_libraryTab == "simplerplants") { RenderVegBrowser(true); return; }
            if (_libraryTab == "search") { RenderGlobalSearch(); return; }
            if (_libraryTab == "simplermats")
            {
                if (LibraryQuery != "") RenderMaterialBrowser(false);
                else RenderSimplerMaterials();
                return;
            }
            if (_libraryTab == "scenes") { RenderScenes(); return; }
            if (_libraryTab == "aioutputs") { RenderAiOutputs(); return; }
            if (_libraryTab == "mydecals") { RenderDecalBrowser(); return; }
            if (_libraryTab == "simplerdecals") { RenderDecalBrowser(true); return; }
            if (_libraryTab == "acgdecals") { RenderAcgDecals(); return; }
            if (_libraryTab == "materials") { RenderMaterialBrowser(false); return; }
            if (_libraryTab == "mymaterials") { RenderMaterialBrowser(true); return; }
            if (_libraryTab == "hdri") { RenderHdri(); return; }
            if (RenderInsertTab()) { if (_libraryTab is not ("polyhaven" or "objects" or "phmodels")) FilterLibrary(); return; }

            foreach (var node in _environments.OfType<JsonObject>())
                _libraryTiles.Children.Add(LibraryTile(node, false));
            FilterLibrary();
        }

        /// <summary>A tile of the library: a material (path-traced thumbnail; drag = apply, click = edit) or an environment.</summary>
        Button LibraryTile(JsonObject node, bool isMaterial)
        {
            {
                var id = (string?)node["id"] ?? "";
                var label = (string?)node["name"] ?? id;
                var hex = (string?)node["swatch"] ?? EnvSwatch(id);
                var tile = new StackPanel { Width = 92, Margin = new Thickness(4, 0, 4, 0) };   // (no top/bottom margin: two-line names fit the 130 px tile)
                var visual = new Grid { Width = 72, Height = 72, Margin = new Thickness(0, 2, 0, 6), HorizontalAlignment = HorizontalAlignment.Center };
                var sw = Theme.Swatch(hex, 50);
                sw.HorizontalAlignment = HorizontalAlignment.Center;
                sw.VerticalAlignment = VerticalAlignment.Center;
                visual.Children.Add(sw);
                if (isMaterial)
                {
                    // path-traced preview (cached on disk); the swatch shows until it is ready
                    var img = new Image { Stretch = Stretch.UniformToFill };
                    img.Clip = new RectangleGeometry(new Rect(0, 0, 72, 72), 10, 10);
                    visual.Children.Add(img);
                    _materialImages[id] = img;
                    var rev = (string?)node["rev"] ?? "base";
                    var cached = Path.Combine(PreviewFolder, $"{id}_{rev}_v2.png");
                    if (File.Exists(cached)) img.Source = LoadBitmap(cached);
                    else QueuePreview(id);
                }
                tile.Children.Add(visual);
                var t = Theme.TileText(new TextBlock { Text = label, FontSize = 11.5, TextAlignment = TextAlignment.Center, TextWrapping = TextWrapping.Wrap, Foreground = Theme.B(Theme.TextSoft) });
                tile.Children.Add(t);
                var btn = Theme.Button(tile, Theme.Kind.Normal, (string?)node["category"]);
                btn.Padding = new Thickness(2, 4, 2, 6);
                btn.Margin = new Thickness(4);
                btn.VerticalContentAlignment = VerticalAlignment.Top;
                btn.Height = 130;
                btn.Tag = label + " " + ((string?)node["category"] ?? "");
                if (isMaterial)
                {
                    // two clear gestures: drag onto a piece in the view = apply · click = edit in the sidebar
                    btn.ToolTip = label + " · " + ((string?)node["folder"] ?? "") + "\n" +
                                  L.T("Trascina sopra un oggetto nella vista per applicarlo, o su una cartella per spostarlo · clic per modificarlo");
                    var roMat = SimplerLocked && InSimplerMats(node);       // (red folder: used and edited as a copy, never moved or removed)
                    MakeDraggable(btn, label, async (x, y) => await DropMaterial(x, y, async (ids, slot) => await AssignMaterial(id, label, ids, slot),
                                                                         async under => await ReplaceMaterialEverywhere(under, id, true, label)),
                                  roMat ? null : async folder => await MoveMaterial(id, folder),
                                  () => _materialImages.TryGetValue(id, out var im) ? im.Source : null);
                    btn.ContextMenu = LibraryMaterialMenu(node);
                    if (!roMat) AddMoveMenu(btn.ContextMenu, id, (string?)node["folder"] ?? "");
                    if (!roMat && ((bool?)node["user"] ?? false) && !((bool?)node["overrides"] ?? false))
                    {
                        var cut = new MenuItem { Header = L.T("Taglia") };
                        cut.Click += (_, __) => CutLibrary("material", false, id, label);
                        btn.ContextMenu.Items.Insert(0, cut);
                        if (IsCut("material", false, id)) btn.Opacity = 0.45;
                    }
                }
                btn.Click += async (_, __) =>
                {
                    if (isMaterial) await OpenLibraryMaterial(id);
                    else
                    {
                        await Run(async api => { await api.Post("environment", new { id }); });
                        Status(L.T("Ambiente: ") + label);
                    }
                };
                if (isMaterial) return Fav(btn, "material", id, label, node);
                if (StudioBackgrounds().Any(e => (string?)e["id"] == id)) return Fav(btn, "studio", id, label, node);
                return btn;
            }
        }

        async Task AssignMaterial(string id, string label, string[] ids, int? slot)
        {
            string newName = "";
            await Run(async api =>
            {
                var r = await api.Post("material/assign", new JsonObject { ["ids"] = new JsonArray(ids.Select(x => (JsonNode)x!).ToArray()), ["material"] = id, ["slot"] = slot, ["replace"] = _assignReplace });
                newName = (string?)r["material"] ?? "";
                Status(L.F("{0} applicato a {1} superfici", label, (int?)r["assigned"] ?? 0));
            });
            await RefreshScene();
            // the editor was showing this piece's material: it follows the new one
            if (_rightPanel == "material" && newName != "" && ids.Contains(_matObject) && newName != _matName)
                await OpenMaterialEditor(newName, _matObject, slot ?? 0);
        }

        static BitmapImage? LoadBitmap(string path)
        {
            try
            {
                var bmp = new BitmapImage();
                bmp.BeginInit();
                bmp.CacheOption = BitmapCacheOption.OnLoad;   // don't keep the file locked
                bmp.UriSource = new Uri(path);
                bmp.EndInit();
                bmp.Freeze();
                return bmp;
            }
            catch { return null; }
        }

        static BitmapImage? LoadBase64(string? b64)
        {
            if (string.IsNullOrEmpty(b64)) return null;
            try
            {
                var bmp = new BitmapImage();
                bmp.BeginInit();
                bmp.CacheOption = BitmapCacheOption.OnLoad;
                bmp.StreamSource = new MemoryStream(Convert.FromBase64String(b64));
                bmp.EndInit();
                bmp.Freeze();
                return bmp;
            }
            catch { return null; }
        }

        // ---------------------------------------------------------------- material previews (one at a time, in the background)

        void QueuePreview(string id)
        {
            if (!_previewQueue.Contains(id)) _previewQueue.Enqueue(id);
            if (!_previewWorker) _ = PreviewWorker();
        }

        async Task PreviewWorker()
        {
            _previewWorker = true;
            try
            {
                while (_previewQueue.Count > 0 && _api != null)
                {
                    var id = _previewQueue.Dequeue();
                    try
                    {
                        // rendered by the preview process: the engine answers at once, then we wait for the picture
                        var r = await _api.Post("materials/preview", new { id, folder = PreviewFolder });
                        var path = (string?)r["path"];
                        if (path == null && (int?)r["pending"] is int rid)
                        {
                            for (int i = 0; i < 600; i++)
                            {
                                await Task.Delay(300);
                                var st = await _api.Get($"material/preview/status?id={rid}");
                                var state = (string?)st["state"] ?? "";
                                if (state == "running") continue;
                                if (state == "done") path = (string?)st["path"];
                                break;
                            }
                        }
                        if (path != null && _materialImages.TryGetValue(id, out var img)) img.Source = LoadBitmap(path);
                    }
                    catch { /* engine busy or preview failed: the swatch stays */ }
                }
            }
            finally { _previewWorker = false; }
        }

        // ---------------------------------------------------------------- saved scenes

        async Task LoadViews()
        {
            await Run(async api => { _views = (await api.Get("views"))["views"] as JsonArray ?? new JsonArray(); });
            // (1.75.42) a scene renamed, updated or deleted: the Video AI panel says it under the keyframes made from it
            if (_rightPanel == "video") { await LoadVideoFrames(); RenderProps(); }
        }

        void RenderScenes()
        {
            // "+ Salva scena" tile
            var add = new StackPanel { Width = 150, VerticalAlignment = VerticalAlignment.Center };
            var plus = Theme.Icon(Icons.Plus, Theme.Accent, 30);
            plus.HorizontalAlignment = HorizontalAlignment.Center;
            plus.Margin = new Thickness(0, 18, 0, 10);
            add.Children.Add(plus);
            add.Children.Add(new TextBlock { Text = L.T("Salva scena"), FontSize = 12, TextAlignment = TextAlignment.Center, Foreground = Theme.B(Theme.TextSoft) });
            var addBtn = Theme.Button(add, Theme.Kind.Normal, L.T("Memorizza inquadratura, impostazioni di rendering, ambiente, luci e oggetti visibili"));
            addBtn.Height = 130;
            addBtn.Margin = new Thickness(4);
            addBtn.Click += async (_, __) => await SaveView();
            _libraryTiles.Children.Add(addBtn);

            foreach (var v in _views.OfType<JsonObject>())
            {
                var id = (string?)v["id"] ?? "";
                var name = (string?)v["name"] ?? "";
                var grid = new Grid { Width = 168, Height = 122 };
                grid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
                grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
                var img = new Image { Source = LoadBase64((string?)v["thumb"]), Stretch = Stretch.Uniform, Margin = new Thickness(0, 0, 0, 4) };
                grid.Children.Add(img);
                var row = new DockPanel();
                Grid.SetRow(row, 1);
                var more = SmallIconButton(Icons.Dots, L.T("Rinomina, duplica, elimina"));
                more.Click += (_, e) => { e.Handled = true; SceneMenu(more, id, name).IsOpen = true; };
                DockPanel.SetDock(more, Dock.Right);
                row.Children.Add(more);
                var upd = SmallIconButton(Icons.Refresh, L.T("Aggiorna: salva qui inquadratura e impostazioni attuali"));
                upd.Click += async (_, e) => { e.Handled = true; await UpdateView(id, name); };
                DockPanel.SetDock(upd, Dock.Right);
                row.Children.Add(upd);
                row.Children.Add(new TextBlock { Text = name, FontSize = 12, Foreground = Theme.B(Theme.TextSoft), VerticalAlignment = VerticalAlignment.Center, TextTrimming = TextTrimming.CharacterEllipsis });
                grid.Children.Add(row);
                var btn = Theme.Button(grid, Theme.Kind.Normal, L.F("{0} · aggiornata {1}", name, (string?)v["updated"] ?? ""));
                btn.Padding = new Thickness(5);
                btn.Margin = new Thickness(4);
                btn.Height = 130;
                btn.Click += async (_, __) => await ApplyView(id, name);
                _libraryTiles.Children.Add(btn);
            }
        }

        static Button SmallIconButton(Geometry icon, string tip)
        {
            var b = Theme.Button(Theme.Icon(icon, null, 14), Theme.Kind.Ghost, tip);
            b.Padding = new Thickness(4, 0, 4, 0);
            b.MinHeight = 22;
            b.Height = 22;
            b.Margin = new Thickness(2, 0, 0, 0);
            return b;
        }

        ContextMenu SceneMenu(FrameworkElement anchor, string id, string name)
        {
            var m = new ContextMenu { PlacementTarget = anchor, Placement = System.Windows.Controls.Primitives.PlacementMode.Bottom };
            void Item(string text, Func<Task> act) { var i = new MenuItem { Header = text }; i.Click += async (_, __) => await act(); m.Items.Add(i); }
            Item(L.T("Rinomina…"), async () =>
            {
                var n = InputDialog.Ask(this, L.T("Rinomina scena"), L.T("Nome della scena"), name);
                if (n == null) return;
                await Run(async api => { await api.Post("views/rename", new { id, name = n }); });
                await LoadViews(); RenderLibrary();
            });
            Item(L.T("Duplica"), async () => { await Run(async api => { await api.Post("views/duplicate", new { id }); }); await LoadViews(); RenderLibrary(); });
            m.Items.Add(new Separator());
            Item(L.T("Elimina"), async () =>
            {
                if (Msg.Show(this, L.F("Eliminare la scena \"{0}\"?", name), "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
                await Run(async api => { await api.Post("views/delete", new { id }); });
                await LoadViews(); RenderLibrary();
            });
            return m;
        }

        async Task SaveView()
        {
            var name = InputDialog.Ask(this, L.T("Salva scena"), L.T("Nome della scena"), L.F("Scena {0}", _views.Count + 1));
            if (name == null) return;
            using var busy = BeginBusy();
            ShowTask(L.T("Salvataggio della scena e miniatura…"));
            var thumb = await CaptureViewSnapshot();
            await Run(async api =>
            {
                var r = await api.Post("views/save", new { name, thumb });
                var vid = (string?)r["view"]?["id"] ?? "";
                if (vid != "") _appliedView = vid;          // (1.76.37: its path tracing may become its thumbnail)
            });
            HideTask();
            await LoadViews();
            _libraryTab = "scenes";
            RenderLibrary();
            Status(L.F("Scena salvata: {0}", name));
        }

        async Task UpdateView(string id, string name)
        {
            using var busy = BeginBusy();
            ShowTask(L.F("Aggiornamento della scena {0}…", name));
            var thumb = await CaptureViewSnapshot();
            await Run(async api => { await api.Post("views/update", new { id, thumb }); });
            _appliedView = id;                                 // (1.76.37: its path tracing may become its thumbnail)
            HideTask();
            await LoadViews();
            RenderLibrary();
            Status(L.F("Scena aggiornata: {0}", name));
        }

        string _appliedView = "";

        /// <summary>(1.75.57, Luca's idea) The path tracing finished in the view: if it shows the scene opened last from
        /// its thumbnail and nothing changed since (the engine checks), it becomes the thumbnail of that scene - a green
        /// notice says so. «Aggiorna» on the scene gives back the thumbnail of the real-time view.</summary>
        async Task PathTracedThumb(string thumb)
        {
            if (_api == null || thumb == "") return;
            if (_appliedView == "") { AppLog.Write("path traced thumbnail: no scene opened, saved or updated from the view"); return; }
            // (1.79.0, Luca: «ero su scene 4, ho cliccato su scene 2 e la miniatura della 4 si è trasferita sulla 2») the
            // scene this picture belongs to is the one open NOW: while waiting below another scene can be opened (it is
            // busy too), and the picture of the old one went to the new one - the engine saw no change since it opened
            var id = _appliedView;
            // (1.76.37) busy when the path tracing ends (the coast, the ecosystems...): wait for it, up to a minute
            for (int i = 0; i < 120 && IsBusy; i++) await Task.Delay(500);
            if (IsBusy) { AppLog.Write("path traced thumbnail: still busy"); return; }
            if (_appliedView != id) { AppLog.Write("path traced thumbnail: another scene was opened meanwhile"); return; }
            try
            {
                var r = await _api.Post("views/ptthumb", new { id, thumb });
                if ((bool?)r["replaced"] != true) { AppLog.Write("path traced thumbnail kept: " + ((string?)r["why"] ?? "")); return; }
                await LoadViews();
                RenderLibrary();
                SendToWeb(new { type = "toast", text = L.T("Miniatura della scena aggiornata con il path tracing") });
            }
            catch (Exception e) { AppLog.Write("path traced thumbnail: " + e.Message); }
        }

        async Task ApplyView(string id, string name)
        {
            JsonObject? r = null;
            using var busy = BeginBusy();
            _reloadOrigin = "action";
            ShowTask(L.F("Scena {0}…", name));
            await Run(async api => { r = await api.Post("views/apply", new { id }); });
            HideTask();
            if (r == null) return;
            _appliedView = id;          // (1.75.57) its finished path tracing may become its thumbnail (PathTracedThumb)
            if (r["view"] is JsonObject view)
            {
                SendToWeb(new { type = "setCamera", view = view.DeepClone() });
                SendCameraOptions(view);
            }
            await RefreshScene();
            await LoadRenderSettings();
            // (1.75.6) the ambience of the scene too (sky, rain, snow, preset): the engine had it back, the panel and
            // the real-time view kept the one before - it looked as if the scene had not saved it
            await LoadAmbience();
            PushAmbienceToViewer();
            if (_rightPanel != "") RenderProps();
            Status(L.F("Scena: {0}", name));
        }
    }

    /// <summary>Minimal text prompt (rename, new names).</summary>
    public sealed class InputDialog : ThemedDialog
    {
        readonly TextBox _box;
        InputDialog(string title, string label, string value) : base(title, 400)
        {
            var sp = Body;
            sp.Margin = new Thickness(22, 4, 22, 20);
            sp.Children.Add(Theme.Label(label, 13, Theme.TextSoft));
            _box = Theme.Input(value);
            _box.Margin = new Thickness(0, 10, 0, 18);
            _box.KeyDown += (_, e) => { if (e.Key == Key.Enter) DialogResult = true; if (e.Key == Key.Escape) DialogResult = false; };
            sp.Children.Add(_box);
            var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right };
            var cancel = Theme.Button(L.T("Annulla"), Theme.Kind.Ghost);
            cancel.Click += (_, __) => DialogResult = false;
            var ok = Theme.Button("OK", Theme.Kind.Primary);
            ok.Margin = new Thickness(8, 0, 0, 0);
            ok.Click += (_, __) => DialogResult = true;
            buttons.Children.Add(cancel);
            buttons.Children.Add(ok);
            sp.Children.Add(buttons);
            Loaded += (_, __) => { _box.Focus(); _box.SelectAll(); };
        }

        protected override void OnCloseButton() => DialogResult = false;

        public static string? Ask(Window owner, string title, string label, string value)
        {
            var d = new InputDialog(title, label, value) { Owner = owner };
            return d.ShowDialog() == true && d._box.Text.Trim() != "" ? d._box.Text.Trim() : null;
        }
    }
}
