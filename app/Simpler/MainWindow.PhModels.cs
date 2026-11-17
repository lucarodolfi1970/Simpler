using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace Simpler
{
    /// <summary>
    /// "Modelli 3D Poly Haven" tab: the CC0 models of polyhaven.com in folders from their categories (read only).
    /// Downloaded the first time they are used (Poly Haven's own .blend with its textures, 2K), then kept on disk.
    /// Click = in the middle of the view; drag = its base on the surface where it is dropped.
    /// </summary>
    public sealed partial class MainWindow
    {
        JsonArray _phmAssets = new JsonArray();
        string _phmFolder = "";
        bool _phmLoading;

        void RenderPhModels()
        {
            if (_phmAssets.Count == 0)
            {
                _libraryTiles.Children.Add(EmptyNote(L.T("Caricamento dell'elenco dei modelli di Poly Haven…")));
                if (!_phmLoading) _ = LoadPhModels();
                return;
            }
            var assets = _phmAssets.OfType<JsonObject>().ToList();
            var q = LibraryQuery;
            IEnumerable<JsonObject> shown;
            if (q != "")
            {
                RenderCrumbs("Poly Haven", "", f => { _phmFolder = f; _librarySearch.Text = ""; }, L.F("risultati per \"{0}\"", _librarySearch.Text.Trim()));
                shown = assets.Where(a => ((string?)a["name"] + " " + (string?)a["category"] + " " + (string?)a["folder"]).ToLowerInvariant().Contains(q)).ToList();
                if (!shown.Any()) _libraryTiles.Children.Add(EmptyNote(L.T("Nessun modello trovato")));
            }
            else
            {
                var folders = new HashSet<string>();
                foreach (var f in assets.Select(a => (string?)a["folder"] ?? "").Where(f => f != ""))
                    for (var p = f; p != ""; p = ParentFolder(p)) folders.Add(p);
                if (_phmFolder != "" && !folders.Contains(_phmFolder)) _phmFolder = "";
                RenderCrumbs("Poly Haven", _phmFolder, f => _phmFolder = f, null);
                if (_phmFolder != "") _libraryTiles.Children.Add(UpTile(ParentFolder(_phmFolder), f => _phmFolder = f, false));
                foreach (var f in folders.Where(f => ParentFolder(f) == _phmFolder)
                                         .OrderBy(f => f == L.T("Altro")).ThenBy(f => f, StringComparer.CurrentCultureIgnoreCase))
                {
                    var count = assets.Count(a => InFolder((string?)a["folder"] ?? "", f));
                    var down = assets.Count(a => InFolder((string?)a["folder"] ?? "", f) && ((bool?)a["downloaded"] ?? false));
                    _libraryTiles.Children.Add(FolderTile(f, count, () => { _phmFolder = f; RenderLibrary(); }, "phmodels", down));
                }
                shown = assets.Where(a => ((string?)a["folder"] ?? "") == _phmFolder);
            }
            foreach (var a in shown) _libraryTiles.Children.Add(PhModelTile(a));
            var credit = Theme.Label(L.T("Modelli 3D di Poly Haven (polyhaven.com) · CC0, liberi anche per uso commerciale"), 11, Theme.TextFaint);
            credit.Margin = new Thickness(10, 0, 10, 0);
            _libraryTiles.Children.Add(credit);
        }

        async Task LoadPhModels()
        {
            _phmLoading = true;
            try
            {
                for (int attempt = 0; attempt < 60; attempt++)
                {
                    JsonObject? r = null;
                    try { if (_api != null) r = await _api.Get("library/models/list"); } catch { }
                    if (r?["assets"] is JsonArray list && list.Count > 0)
                    {
                        _phmAssets = (JsonArray)list.DeepClone();
                        if (_libraryTab == "phmodels") RenderLibrary();
                        return;
                    }
                    if (r != null && !((bool?)r["loading"] ?? false) && (string?)r["error"] is string err && err != "")
                    {
                        if (_libraryTab == "phmodels")
                        {
                            _libraryTiles.Children.Clear();
                            var t = Theme.Label(L.T("Poly Haven non raggiungibile (serve la connessione a Internet): ") + err, 12, Theme.Danger);
                            t.Margin = new Thickness(10);
                            _libraryTiles.Children.Add(t);
                        }
                        return;
                    }
                    await Task.Delay(1000);
                }
            }
            finally { _phmLoading = false; }
        }

        Button PhModelTile(JsonObject a)
        {
            var id = (string?)a["id"] ?? "";
            var label = (string?)a["name"] ?? id;
            var tile = new StackPanel { Width = 92, Margin = new Thickness(4, 0, 4, 0) };   // (no top/bottom margin: two-line names fit the 130 px tile)
            var img = new Border { Width = 80, Height = 80, CornerRadius = new CornerRadius(10), Background = Theme.B(Theme.Inset) };
            var downloaded = (bool?)a["downloaded"] ?? false;
            tile.Children.Add(WithBadge(img, 80, "m:" + id, downloaded, new Thickness(0, 0, 0, 4)));
            tile.Children.Add(Theme.TileText(new TextBlock { Text = label, FontSize = 11.5, TextAlignment = TextAlignment.Center, TextWrapping = TextWrapping.Wrap,
                                              Foreground = Theme.B(downloaded ? Theme.TextSoft : Theme.TextMuted), MaxHeight = 32,
                                              TextTrimming = TextTrimming.CharacterEllipsis }));
            var poly = (long?)a["polycount"] ?? 0;
            var tip = label + " · " + ((string?)a["category"] ?? "") + (poly > 0 ? " · " + L.F("{0} poligoni", poly.ToString("N0")) : "") + "\n" +
                      (downloaded ? L.T("Già scaricato") : L.T("Si scarica al primo uso (con le sue texture 2K)")) + "\n" +
                      L.T("Clic: al centro della vista · trascina nella vista: dove lo lasci") + "\nPoly Haven · CC0";
            var btn = Theme.Button(tile, Theme.Kind.Normal, tip);
            btn.Padding = new Thickness(2, 4, 2, 6);
            btn.Margin = new Thickness(4);
            btn.VerticalContentAlignment = VerticalAlignment.Top;
            btn.Height = 130;
            btn.Click += async (_, __) => await InsertPhModel(id, label, null);
            MakeDraggable(btn, label, async (x, y) =>
            {
                var at = await AskViewPoint(x, y);
                if (at != null) await InsertPhModel(id, label, at);
            }, icon: () => _phThumbs.TryGetValue("m:" + id, out var th) ? th : null);
            _ = LoadPhModelThumb(id, img, (bool?)a["hasThumb"] ?? false);
            // (1.76.23) as the models of the library: to the brush, to the stones of the terrain
            var menu = new ContextMenu();
            var toBrush = new MenuItem { Header = L.T("Aggiungi al pennello Distribuisci") };
            toBrush.Click += async (_, __) => { if (!Painting) SetTool("paint"); await PhModelToLibrary(id, label, AddToPalette); };
            menu.Items.Add(toBrush);
            var toScree = new MenuItem { Header = L.T("Aggiungi a Pietre e detriti") };
            toScree.Click += async (_, __) =>
            {
                if (_terrain == null) { Status(L.T("Pietre e detriti vanno su un terreno: crealo prima in Paesaggio"), true); return; }
                await PhModelToLibrary(id, label, AddScreeModel);
            };
            menu.Items.Add(toScree);
            btn.ContextMenu = menu;
            return Fav(btn, "phmodel", id, label, a);
        }

        // ---------------------------------------------------------------- downloads from Poly Haven
        // The engine retries every file 3 times and gives a download up when no data arrives for 2.5 minutes (the
        // slot is free again); here: progress in the status bar, and when it fails the reason in words and the
        // choice to try again (the files already downloaded are kept: it goes on from where it stopped).

        /// <summary>Downloads a Poly Haven texture ("library") or model ("library/models"). True when it is on disk.</summary>
        async Task<bool> PolyHavenDownload(string prefix, string id, string label)
        {
            while (true)
            {
                if (_api == null) return false;
                JsonObject? st = null;
                string error = "";
                try { st = await _api.Post(prefix + "/download", new { id }); }
                catch (Exception ex) { error = ex.Message; }
                double last = -1;
                var lastMove = DateTime.Now;
                int failures = 0;
                while (st != null && (string?)st["state"] == "running")
                {
                    var f = (double?)st["fraction"] ?? 0;
                    if (f != last) { last = f; lastMove = DateTime.Now; }
                    var quiet = (DateTime.Now - lastMove).TotalSeconds;
                    Status(L.F("Download di {0} da Poly Haven… {1}", label, $"{f * 100:0}%") +
                           (quiet > 20 ? "  " + L.F("(nessun dato da {0} s: attendo, poi riprovo)", (int)quiet) : ""));
                    // (the engine gives up after 150 s without data; this is a last guard if it does not answer)
                    if (quiet > 200) { st = null; error = L.T("nessun dato da Poly Haven da oltre tre minuti"); break; }
                    await Task.Delay(400);
                    try { st = await _api.Get(prefix + "/status?id=" + Uri.EscapeDataString(id)); failures = 0; }
                    catch (Exception ex)
                    {
                        if (++failures < 10) continue;
                        st = null; error = ex.Message;
                    }
                }
                if ((string?)st?["state"] == "done") return true;
                if (error == "") error = (string?)st?["error"] ?? "";
                Status(L.F("Download di {0} non riuscito: {1}", label, error), true);
                var again = Msg.Show(this,
                    L.F("Non sono riuscito a scaricare \"{0}\" da Poly Haven.", label) + "\n\n" +
                    L.T("Motivo: ") + (error != "" ? error : L.T("sconosciuto")) + "\n\n" +
                    L.T("Simpler ha già riprovato da solo; i file arrivati restano sul disco e un nuovo tentativo riparte da dove si era fermato.") + "\n\n" +
                    L.T("Vuoi riprovare adesso?"),
                    L.T("Download non riuscito"), MessageBoxButton.YesNo, MessageBoxImage.Warning);
                if (again != MessageBoxResult.Yes) return false;
            }
        }

        // small green tick on the picture of what is already on disk (no download needed)
        readonly Dictionary<string, FrameworkElement> _badges = new();

        FrameworkElement WithBadge(FrameworkElement picture, double size, string key, bool on, Thickness margin)
        {
            var g = new Grid { Width = size, Height = size, Margin = margin, HorizontalAlignment = HorizontalAlignment.Center };
            g.Children.Add(picture);
            var tick = new Border
            {
                Width = 18, Height = 18, CornerRadius = new CornerRadius(9), Background = Theme.B("#2FB86A"),
                BorderBrush = Theme.B(Theme.Panel), BorderThickness = new Thickness(1.5),
                HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Top, Margin = new Thickness(0, 3, 3, 0),
                Child = Theme.Icon(Geometry.Parse("M6 12.5l4 4 8-9"), Colors.White, 11, 2.6),
                ToolTip = L.T("Già scaricato: si usa subito, anche senza Internet"),
                Visibility = on ? Visibility.Visible : Visibility.Collapsed,
                Tag = "dl-tick",            // (1.76.31: moved left of the favourite's heart, Fav)
            };
            g.Children.Add(tick);
            _badges[key] = tick;
            return g;
        }

        void ShowBadge(string key)
        {
            if (_badges.TryGetValue(key, out var b)) b.Visibility = Visibility.Visible;
        }

        async Task LoadPhModelThumb(string id, Border target, bool ready)
        {
            var key = "m:" + id;
            if (!_phThumbs.TryGetValue(key, out var bmp))
            {
                for (int i = 0; i < (ready ? 1 : 30) && bmp == null; i++)
                {
                    try
                    {
                        var bytes = await TexHttp.GetByteArrayAsync($"http://127.0.0.1:{_host.Port}/api/library/models/thumb?id={Uri.EscapeDataString(id)}");
                        var b = new BitmapImage();
                        b.BeginInit(); b.CacheOption = BitmapCacheOption.OnLoad; b.DecodePixelWidth = 160;
                        b.StreamSource = new System.IO.MemoryStream(bytes); b.EndInit(); b.Freeze();
                        bmp = b;
                        _phThumbs[key] = b;
                    }
                    catch { await Task.Delay(2000); }
                }
                if (bmp == null) return;
            }
            target.Background = new ImageBrush(bmp) { Stretch = Stretch.UniformToFill };
        }

        /// <summary>(1.76.23) The level of detail of a downloaded Poly Haven model: -1 when it has one level only, null
        /// when the user cancelled.</summary>
        async Task<int?> AskPhLod(string id, string label, bool many)
        {
            JsonObject? r = null;
            await Run(async api => { r = await api.Post("library/models/lods", new { id }); });
            var lods = (r?["lods"] as JsonArray)?.OfType<JsonObject>()
                .Select(x => ((int?)x["level"] ?? 0, (int?)x["triangles"] ?? 0)).ToList();
            if (lods == null || lods.Count < 2) return -1;
            return LodDialog.Ask(this, label, lods, many);
        }

        async Task InsertPhModel(string id, string label, JsonObject? at)
        {
            if (_api == null) return;
            // (1.76.23) «Scegli le pietre dalla libreria»: the model joins the stones (before, it went into the scene)
            if (_screePicking && at == null) { await PhModelToLibrary(id, label, AddScreeModel); return; }
            if (Painting && at == null) { await PhModelToLibrary(id, label, AddToPalette); return; }
            at ??= await AskViewPoint();
            if (!await PolyHavenDownload("library/models", id, label)) return;
            var a = _phmAssets.OfType<JsonObject>().FirstOrDefault(x => (string?)x["id"] == id);
            if (a != null) a["downloaded"] = true;
            ShowBadge("m:" + id);
            var lod = await AskPhLod(id, label, false);
            if (lod == null) return;
            var body = new JsonObject { ["id"] = id };
            if (lod >= 0) body["lod"] = lod;
            if (at?["point"] is JsonArray p) body["location"] = p.DeepClone();
            string newId = "";
            using (BeginBusy())
            {
                _reloadOrigin = "action";
                ShowTask(L.F("Inserimento di {0}…", label));
                await Run(async api => { newId = (string?)(await api.Post("library/models/insert", body))["id"] ?? ""; });
                HideTask();
            }
            if (newId == "") return;
            _expanded.Add(newId);
            SetSelectionRaw(newId);
            await RefreshScene();
            Status(L.F("{0} inserito · Poly Haven, CC0", label));
        }

        /// <summary>(1.75.0) The brush of Distribuisci is on (1.76.23: or «Scegli le pietre»): a Poly Haven model clicked joins the brush, as a model of
        /// the library would (before, it was put in the scene). The brush works with library models: the first time
        /// the downloaded model is added to the library, in the folder «Poly Haven»; then the same one is used.</summary>
        async Task PhModelToLibrary(string id, string label, Action<string, string> add)
        {
            if (!await PolyHavenDownload("library/models", id, label)) return;
            var a = _phmAssets.OfType<JsonObject>().FirstOrDefault(x => (string?)x["id"] == id);
            if (a != null) a["downloaded"] = true;
            ShowBadge("m:" + id);
            // (1.76.23) one level of detail: for many copies a light one
            var lod = await AskPhLod(id, label, true);
            if (lod == null) return;
            var body = new JsonObject { ["id"] = id };
            if (lod >= 0) body["lod"] = lod;
            JsonObject? r = null;
            using (BeginBusy())
            {
                ShowTask(L.F("{0} nella libreria…", label));
                await Run(async api => { r = await api.Post("library/models/tolibrary", body); });
                HideTask();
            }
            var mid = (string?)r?["id"] ?? "";
            if (mid == "") return;
            if ((int?)r?["pending"] is int rid) await WaitModelJob(rid, label, L.F("{0} aggiunto alla libreria (cartella Poly Haven)", label));
            else await ReloadModels();
            add(mid, (string?)r?["name"] ?? label);
        }
    }
}
