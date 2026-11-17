using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;

namespace Simpler
{
    /// <summary>
    /// (cloud) The models and the ecosystems of the red «Simpler» folders are not in the setup: they are downloaded when
    /// they are needed (ContentStore: signed catalog, resumable download, SHA-256, atomic install).
    ///  - the library shows all of them: a cloud on the picture = not on this computer yet, a green tick = here;
    ///  - a click on a cloud downloads it (a bar on the picture and the percentage in the status bar);
    ///  - whatever the engine is asked to use (put in the view, the brush, an ecosystem, a copy…) that is not here yet is
    ///    downloaded first (EngineClient.BeforePost), an ecosystem with the models it needs, and an ecosystem here that
    ///    lost a model downloads it again: no pink materials, no missing models, no errors;
    ///  - «Rimuovi dal computer» frees the space (files only: it can be downloaded again);
    ///  - a project that opens with textures of such a model that is not here downloads it and links the textures.
    /// Where the files go: the folders chosen in Impostazioni ▸ Cartelle (models, ecosystems), like the models made by hand.
    /// </summary>
    public sealed partial class MainWindow
    {
        ContentStore? _content;
        string _contentModelsDir = "", _contentEcoDir = "";
        int _contentRunning;
        bool _contentDirsOk;
        readonly Dictionary<string, double> _contentProg = new();
        readonly List<(string id, Border badge, Border fill, double width)> _contentUi = new();
        readonly SemaphoreSlim _thumbGate = new(4);
        DispatcherTimer? _contentTimer;
        static readonly Regex ContentIdRx = new(@"\b[em]_[0-9a-f]{10}(?:_[0-9]{1,4})?\b", RegexOptions.Compiled);

        /// <summary>Only on a computer where the red folders are locked (the author's one has everything already).</summary>
        bool ContentOn => _content != null && SimplerLocked && _content.HasCatalog;

        void Ui(Action a) { if (Dispatcher.CheckAccess()) a(); else Dispatcher.InvokeAsync(a); }

        // ------------------------------------------------------------------ start

        async Task InitContentAsync()
        {
            try
            {
                if (!SimplerLocked) return;
                _content = new ContentStore(PackKeysTrusted());
                EngineClient.BeforePost = EnsureContentForRequest;
                await ContentDirs();                                        // (the folders: to see which models have a newer version)
                if (_content.LoadCache()) await RefreshAfterContent();             // (the tiles at once, also without Internet)
                if (await _content.Refresh()) await RefreshAfterContent();
                AppLog.Write($"content: {_content.Models.Count} models, {_content.Ecosystems.Count} ecosystems in the catalog ({(_content.Online ? "online" : "from the copy kept")})");
            }
            catch (Exception ex) { AppLog.Write("content: " + ex.Message); }
        }

        async Task RefreshAfterContent()
        {
            await ReloadModels();
            await LoadEcosystems();
            RenderLibrary();
        }

        /// <summary>After a download: the lists are read again once, not at every file.</summary>
        void ScheduleContentRefresh()
        {
            _contentTimer ??= new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(700) };
            _contentTimer.Stop();
            _contentTimer.Tick -= ContentTimerTick;
            _contentTimer.Tick += ContentTimerTick;
            _contentTimer.Start();
        }

        async void ContentTimerTick(object? s, EventArgs e)
        {
            _contentTimer?.Stop();
            if (_contentRunning > 0) { ScheduleContentRefresh(); return; }
            try { await RefreshAfterContent(); } catch { }
        }

        async Task<bool> ContentDirs()
        {
            if (_api == null) return false;
            try
            {
                var p = await _api.Get("paths");
                string F(string k) => (p["folders"] as JsonArray)?.OfType<JsonObject>().Where(f => (string?)f["key"] == k).Select(f => (string?)f["path"] ?? "").FirstOrDefault() ?? "";
                _contentModelsDir = F("models");
                _contentEcoDir = F("ecosystems");
            }
            catch { }
            foreach (var d in new[] { _contentModelsDir, _contentEcoDir })
                if (d != "") { try { Directory.CreateDirectory(d); } catch { } }
            return _contentDirsOk = _contentModelsDir != "" && _contentEcoDir != "" && Directory.Exists(_contentModelsDir) && Directory.Exists(_contentEcoDir);
        }

        string DirFor(ContentAsset a) => a.IsEco ? _contentEcoDir : _contentModelsDir;

        // ------------------------------------------------------------------ the lists: what is in the cloud joins what is here

        static void AddFolderChain(List<string> folders, string folder)
        {
            if (folder == "") return;
            var parts = folder.Split('/');
            for (int i = 1; i <= parts.Length; i++)
            {
                var f = string.Join("/", parts.Take(i));
                if (!folders.Contains(f)) folders.Add(f);
            }
        }

        /// <summary>At the end of SetModels: the models of the catalog that are not here, as «cloud» entries.</summary>
        void MergeCloudModels()
        {
            var c = _content;
            if (c == null || !SimplerLocked || !c.HasCatalog) return;
            var have = new HashSet<string>(StringComparer.Ordinal);
            foreach (var m in _models.OfType<JsonObject>())
            {
                var id = (string?)m["id"] ?? "";
                have.Add(id);
                if (c.Models.TryGetValue(id, out var ca))
                {
                    m["inCatalog"] = true;
                    if (_contentModelsDir != "" && ContentStore.NeedsUpdate(ca, _contentModelsDir)) m["update"] = true;     // (a newer version in the cloud)
                }
            }
            foreach (var a in c.Models.Values)
            {
                if (have.Contains(a.Id)) continue;
                var o = a.Meta != null ? (JsonObject)a.Meta.DeepClone() : new JsonObject();
                // (15/11) the plants of the cloud are under «Vegetation» in the list: here the root of the plants has the
                // name of the language in use (as the engine does for the models on the disk, models._clean)
                var folder = CloudModelFolder(a.Folder);
                o["id"] = a.Id; o["name"] = a.Name; o["folder"] = folder;
                o["ready"] = true; o["bytes"] = (double)a.Bytes; o["cloud"] = true;      // (double: the tiles read the numbers as double)
                var tp = c.ThumbPath(a);
                o["thumb"] = tp != "" && File.Exists(tp) ? tp : "";
                _models.Add(o);
                AddFolderChain(_modelFolders, folder);
            }
        }

        /// <summary>The folder of a model of the cloud, with the root of the plants in the language in use.</summary>
        string CloudModelFolder(string f)
        {
            foreach (var root in new[] { "Vegetazione", "Vegetation" })
                if (f == root || f.StartsWith(root + "/", StringComparison.Ordinal)) return _vegRoot + f.Substring(root.Length);
            return f;
        }

        /// <summary>At the end of LoadEcosystems: the same for the ecosystems.</summary>
        void MergeCloudEcosystems()
        {
            var c = _content;
            if (c == null || !SimplerLocked || !c.HasCatalog) return;
            var have = new HashSet<string>(StringComparer.Ordinal);
            foreach (var e in _ecosystems.OfType<JsonObject>())
            {
                var id = (string?)e["id"] ?? "";
                have.Add(id);
                if (c.Ecosystems.TryGetValue(id, out var ca))
                {
                    e["inCatalog"] = true;
                    if (_contentEcoDir != "" && ContentStore.NeedsUpdate(ca, _contentEcoDir)) e["update"] = true;
                }
            }
            foreach (var a in c.Ecosystems.Values)
            {
                if (have.Contains(a.Id)) continue;
                var deps = c.WithDependencies(a).ToList();
                var o = new JsonObject
                {
                    ["id"] = a.Id, ["name"] = a.Name, ["folder"] = a.Folder, ["cloud"] = true, ["size"] = 20.0,
                    ["models"] = new JsonArray(deps.Where(d => !d.IsEco).Select(d => (JsonNode?)JsonValue.Create(d.Name)).ToArray()),
                    ["cloudBytes"] = (double)deps.Sum(d => d.Size),
                };
                var tp = c.ThumbPath(a);
                if (tp != "" && File.Exists(tp)) { try { o["thumb"] = Convert.ToBase64String(File.ReadAllBytes(tp)); } catch { } }
                _ecosystems.Add(o);
                AddFolderChain(_ecoFolders, a.Folder);
            }
        }

        // ------------------------------------------------------------------ tiles

        /// <summary>The cloud (not here) or the green tick (here, and in the catalog) in the corner of the picture, and the
        /// bar of the download along its foot.</summary>
        void AddCloudBadge(Grid host, double size, string id, bool cloud, bool inCatalog, bool update = false)
        {
            if (!cloud && !inCatalog) return;
            if (update && !cloud)
            {
                // a newer version in the cloud: an orange arrow beside the tick (not over it); a click on it updates this one
                var up = new Border
                {
                    Width = 18, Height = 18, CornerRadius = new CornerRadius(9), Background = Theme.B("#E8912D"),
                    BorderBrush = Theme.B(Theme.Panel), BorderThickness = new Thickness(1.5), Cursor = System.Windows.Input.Cursors.Hand,
                    HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Top, Margin = new Thickness(0, 3, 24, 0),
                    ToolTip = L.T("Aggiornamento disponibile: un clic qui lo aggiorna (i progetti già salvati non cambiano)"),
                    Child = Theme.Icon(Icons.Refresh, Colors.White, 11, 2.2),
                };
                up.MouseLeftButtonDown += (_, e) => e.Handled = true;           // (not a click on the tile: nothing is put in the view)
                up.MouseLeftButtonUp += async (_, e) => { e.Handled = true; await UpdateContent(new[] { id }); };
                host.Children.Add(up);
            }
            var badge = new Border
            {
                Width = 18, Height = 18, CornerRadius = new CornerRadius(9),
                BorderBrush = Theme.B(Theme.Panel), BorderThickness = new Thickness(1.5),
                HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Top, Margin = new Thickness(0, 3, 3, 0),
                Tag = "dl-tick",
            };
            var bw = size - 12;
            var fill = new Border { Width = 0, Height = 5, CornerRadius = new CornerRadius(2.5), Background = Theme.B(Theme.Accent), HorizontalAlignment = HorizontalAlignment.Left };
            var track = new Border
            {
                Height = 5, Width = bw, CornerRadius = new CornerRadius(2.5), Background = new SolidColorBrush(Color.FromArgb(210, 0x10, 0x18, 0x2A)),
                HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Bottom, Margin = new Thickness(0, 0, 0, 5),
                Child = fill, Visibility = Visibility.Collapsed, IsHitTestVisible = false,
            };
            host.Children.Add(badge);
            host.Children.Add(track);
            if (_contentUi.Count > 24) _contentUi.RemoveAll(x => !x.badge.IsLoaded);
            _contentUi.Add((id, badge, fill, bw));
            _contentProg.TryGetValue(id, out var f);
            ApplyBadge(badge, fill, bw, cloud, _contentProg.ContainsKey(id) ? f : -1);
        }

        static void ApplyBadge(Border badge, Border fill, double width, bool cloud, double progress)
        {
            var track = (Border)fill.Parent!;      // (the bar is the child of its track)
            if (!cloud || progress >= 1)
            {
                badge.Background = Theme.B("#2FB86A");
                badge.Child = Theme.Icon(Geometry.Parse("M6 12.5l4 4 8-9"), Colors.White, 11, 2.6);
                badge.ToolTip = L.T("Sul computer: si usa subito, anche senza Internet");
                var updating = !cloud && progress >= 0 && progress < 1;        // (an update is coming: the bar, the tick stays)
                track.Visibility = updating ? Visibility.Visible : Visibility.Collapsed;
                if (updating) fill.Width = Math.Max(2, width * progress);
                return;
            }
            badge.Background = Theme.B("#27324A");
            badge.Child = Theme.Icon(Icons.Cloud, Theme.C("#9DB4D8"), 12, 1.8);
            badge.ToolTip = progress >= 0 ? L.T("Download in corso…") : L.T("Nel cloud: un clic lo scarica sul computer");
            track.Visibility = progress >= 0 ? Visibility.Visible : Visibility.Collapsed;
            fill.Width = Math.Max(2, width * Math.Min(1, Math.Max(0, progress)));
        }

        void UpdateCloudUi(string id, double progress)
        {
            _contentUi.RemoveAll(x => !x.badge.IsLoaded && x.badge.Parent == null);
            var a = _content?.Find(id);
            var here = a != null && _contentDirsOk && ContentStore.IsInstalled(a, DirFor(a));      // (an update: the tick, not the cloud)
            foreach (var x in _contentUi.Where(x => x.id == id))
                ApplyBadge(x.badge, x.fill, x.width, !here, progress);
        }

        async void CloudThumb(ContentAsset a, Image img)
        {
            var c = _content;
            if (c == null) return;
            var p = c.ThumbPath(a);
            if (p == "") return;
            if (!File.Exists(p))
            {
                await _thumbGate.WaitAsync();
                try { p = await c.EnsureThumb(a); } catch { p = ""; } finally { _thumbGate.Release(); }
            }
            if (p != "" && File.Exists(p)) { try { img.Source = LoadBitmapFresh(p); } catch { } }
        }

        // ------------------------------------------------------------------ download

        static string ContentErrorText(ContentException ex) => ex.Code switch
        {
            "offline" => L.T("Non riesco a raggiungere il sito dei contenuti: controlla la connessione a Internet. Quello che è già arrivato resta, e il prossimo tentativo riparte da lì."),
            "signature" => L.T("L'elenco dei contenuti non ha la firma di Simpler: non lo uso."),
            "space" => L.F("Non c'è abbastanza spazio sul disco della libreria (servono circa {0}).", ex.Message.Contains(':') ? ex.Message.Substring(ex.Message.IndexOf(':') + 1).Trim() : ""),
            "file" => L.T("Non riesco a scrivere nella cartella della libreria: controlla Impostazioni ▸ Cartelle."),
            _ => L.T("Il file scaricato è danneggiato o non è quello atteso: riprova (se ripete, avvisa chi mantiene Simpler)."),
        };

        /// <summary>Makes sure the assets (with the models an ecosystem needs) are on this computer: downloads what is missing.
        /// Throws ContentException on failure.</summary>
        async Task EnsureAssets(IEnumerable<string> ids, CancellationToken ct = default)
        {
            var c = _content;
            if (c == null || !ContentOn) return;
            if (!await ContentDirs()) throw new ContentException("file", "folders");
            var todo = new List<ContentAsset>();
            void Want(ContentAsset d) { if (!ContentStore.IsInstalled(d, DirFor(d)) && !todo.Any(t => t.Id == d.Id)) todo.Add(d); }
            foreach (var id in ids)
            {
                var a = c.Find(id);
                if (a == null) continue;
                foreach (var d in c.WithDependencies(a)) Want(d);
                if (a.IsEco && ContentStore.IsInstalled(a, DirFor(a)))
                {
                    // an ecosystem here that lost a model of the catalog: it comes back
                    try
                    {
                        foreach (Match m in ContentIdRx.Matches(File.ReadAllText(Path.Combine(DirFor(a), a.Id, "eco.json"))))
                            if (m.Value[0] == 'm' && c.Models.TryGetValue(m.Value, out var dep)) Want(dep);
                    }
                    catch { }
                }
            }
            await RunInstalls(todo, false, ct);
        }

        /// <summary>Downloads and installs what is in the list (the models first), with the bars on the tiles and the status line.
        /// updating: they are here already and a newer version comes (the status says «Aggiorno»).</summary>
        async Task RunInstalls(List<ContentAsset> todo, bool updating, CancellationToken ct)
        {
            var c = _content;
            if (c == null || todo.Count == 0) return;
            todo = todo.OrderBy(t => t.IsEco ? 1 : 0).ToList();          // the models first
            long total = Math.Max(1, todo.Sum(t => t.Size)), done = 0;
            Interlocked.Increment(ref _contentRunning);
            try
            {
                for (int i = 0; i < todo.Count; i++)
                {
                    var t = todo[i];
                    var before = done;
                    Ui(() => { _contentProg[t.Id] = 0; UpdateCloudUi(t.Id, 0); });
                    var prog = new Progress<double>(f => Ui(() =>
                    {
                        _contentProg[t.Id] = f;
                        UpdateCloudUi(t.Id, f);
                        var all = (before + f * t.Size) / total;
                        Status(L.F(updating ? "Aggiorno «{0}»… {1}" : "Scarico «{0}» dal cloud… {1}", t.Name, $"{all * 100:0}%") + (todo.Count > 1 ? $"  ({i + 1}/{todo.Count})" : ""));
                    }));
                    try { await c.Install(t, DirFor(t), prog, ct).ConfigureAwait(false); }
                    catch
                    {
                        Ui(() => { foreach (var x in todo) { _contentProg.Remove(x.Id); UpdateCloudUi(x.Id, -1); } });
                        throw;
                    }
                    done += t.Size;
                    Ui(() => { _contentProg[t.Id] = 1; UpdateCloudUi(t.Id, 1); });
                }
                Ui(() => { Status(todo.Count == 1 ? L.F(updating ? "«{0}» è aggiornato" : "«{0}» è sul computer", todo[0].Name) : L.F(updating ? "{0} elementi aggiornati" : "{0} elementi scaricati dal cloud", todo.Count)); ScheduleContentRefresh(); });
            }
            finally { Interlocked.Decrement(ref _contentRunning); Ui(() => { foreach (var t in todo) _contentProg.Remove(t.Id); }); }
        }

        // ------------------------------------------------------------------ updates

        /// <summary>The models and ecosystems here that have a newer version in the cloud.</summary>
        List<ContentAsset> PendingUpdates()
        {
            var c = _content;
            if (c == null || !ContentOn || !_contentDirsOk) return new List<ContentAsset>();
            return c.Models.Values.Concat(c.Ecosystems.Values).Where(a => ContentStore.NeedsUpdate(a, DirFor(a))).ToList();
        }

        /// <summary>The orange arrow, «Aggiorna» and «Aggiorna tutti»: the new files come over the old ones (see ContentStore.Unpack);
        /// the projects already saved keep their copy of the model.</summary>
        async Task UpdateContent(IEnumerable<string> ids)
        {
            var c = _content;
            if (c == null || !ContentOn) return;
            if (!await ContentDirs()) { Status(ContentErrorText(new ContentException("file")), true); return; }
            var want = new HashSet<string>(ids, StringComparer.Ordinal);
            var todo = PendingUpdates().Where(a => want.Contains(a.Id)).OrderBy(a => a.IsEco ? 1 : 0).ToList();
            if (todo.Count == 0) return;
            try { await RunInstalls(todo, true, CancellationToken.None); }
            catch (ContentException ex)
            {
                // (no connection, a firewall: only the line at the bottom, never a window - the user did nothing wrong)
                if (ex.Code == "offline") { Status(L.F("Aggiornamento di «{0}» non riuscito: nessuna connessione al sito dei contenuti", todo[0].Name), true); AppLog.Write("content: update offline"); return; }
                Status(L.F("Aggiornamento di «{0}» non riuscito", todo[0].Name), true);
                Msg.Show(this, L.T("Non sono riuscito ad aggiornare.") + "\n\n" + ContentErrorText(ex) + (ex.Code == "file" ? "\n" + L.T("Se il modello è in uso, chiudi il progetto e riprova.") : ""),
                         L.T("Aggiornamento non riuscito"), MessageBoxButton.OK, MessageBoxImage.Warning);
            }
            catch (Exception ex) { Status(L.F("Aggiornamento non riuscito: {0}", ex.Message), true); }
        }

        /// <summary>The tile «Aggiorna tutti (n)» at the start of the red folders when something has a newer version.</summary>
        FrameworkElement? UpdateAllTile()
        {
            var list = PendingUpdates();
            if (list.Count == 0) return null;
            var pic = new Border
            {
                Width = 72, Height = 72, CornerRadius = new CornerRadius(10), Background = Theme.B("#3A2A14"), BorderBrush = Theme.B("#E8912D"), BorderThickness = new Thickness(1.5),
                HorizontalAlignment = HorizontalAlignment.Center, Margin = new Thickness(0, 2, 0, 6),
                Child = Theme.Icon(Icons.Refresh, Theme.C("#E8912D"), 30, 2),
            };
            var btn = BigTile(pic, L.F("Aggiorna tutti ({0})", list.Count), "",
                              L.F("{0} elementi hanno una versione più nuova nel cloud: un clic li aggiorna tutti", list.Count) + "\n" + L.T("I progetti già salvati non cambiano"));
            btn.Click += async (_, __) => await UpdateContent(PendingUpdates().Select(a => a.Id).ToList());
            return btn;
        }

        /// <summary>The click on a cloud tile (and «Scarica sul computer»): with the choice to try again when it fails.</summary>
        async Task DownloadCloud(string id)
        {
            var name = _content?.Find(id)?.Name ?? id;
            while (true)
            {
                try { await EnsureAssets(new[] { id }); return; }
                catch (ContentException ex)
                {
                    // (no connection, a firewall: only the line at the bottom, no window and no «riprova»: the next click tries again)
                    if (ex.Code == "offline") { Status(L.F("«{0}» non scaricato: nessuna connessione al sito dei contenuti (Internet o firewall). Riprova più tardi", name), true); AppLog.Write("content: download offline"); return; }
                    Status(L.F("Download di «{0}» non riuscito", name), true);
                    var again = Msg.Show(this, L.F("Non sono riuscito a scaricare «{0}».", name) + "\n\n" + ContentErrorText(ex) + "\n\n" + L.T("Vuoi riprovare adesso?"),
                                         L.T("Download non riuscito"), MessageBoxButton.YesNo, MessageBoxImage.Warning);
                    if (again != MessageBoxResult.Yes) return;
                }
                catch (Exception ex) { Status(L.F("Download di «{0}» non riuscito: {1}", name, ex.Message), true); return; }
            }
        }

        /// <summary>EngineClient.BeforePost: before a command goes to the engine, what it names that is in the cloud and not
        /// here is downloaded.</summary>
        async Task EnsureContentForRequest(string json, CancellationToken ct)
        {
            if (!ContentOn) return;
            var c = _content!;
            var ids = ContentIdRx.Matches(json).Select(m => m.Value).Distinct().Where(i => c.Find(i) != null).ToList();
            if (ids.Count == 0) return;
            try { await EnsureAssets(ids, ct).ConfigureAwait(false); }
            catch (ContentException ex) { throw new EngineException(ContentErrorText(ex)); }
        }

        /// <summary>A project opened with textures of models of the cloud that are not here: they are downloaded and the
        /// textures linked again. True when something was downloaded.</summary>
        async Task<bool> RestoreContentTextures(List<string> missing)
        {
            if (!ContentOn) return false;
            var c = _content!;
            var ids = missing.SelectMany(p => ContentIdRx.Matches(p).Select(m => m.Value)).Distinct().Where(i => c.Find(i) != null).ToList();
            if (ids.Count == 0) return false;
            try { await EnsureAssets(ids); }
            catch (ContentException ex) { Status(ContentErrorText(ex), true); return false; }
            await Run(async api =>
            {
                foreach (var id in ids)
                {
                    var folder = Path.Combine(DirFor(c.Find(id)!), id);
                    if (Directory.Exists(folder)) await api.Post("textures/relink", new { folder });
                }
            });
            return true;
        }

        // ------------------------------------------------------------------ removal

        /// <summary>«Rimuovi dal computer»: the files go, the tile stays (a cloud again).</summary>
        async Task RemoveCloud(string id)
        {
            var a = _content?.Find(id);
            if (a == null || !await ContentDirs()) return;
            if (Msg.Show(this, L.F("Rimuovere «{0}» dal computer?", a.Name) + "\n\n" +
                               L.F("Libera circa {0}. Resta nel cloud: si riscarica con un clic, e da solo quando serve a un progetto o a un ecosistema.", MegaBytes(a.Bytes)),
                         "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
            try { await Task.Run(() => ContentStore.Remove(a, DirFor(a))); }
            catch (Exception ex) { Status(L.F("Non riesco a rimuovere «{0}»: {1}", a.Name, ex.Message), true); return; }
            Status(L.F("«{0}» rimosso dal computer", a.Name));
            await RefreshAfterContent();
        }
    }
}
