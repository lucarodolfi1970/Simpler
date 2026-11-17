using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;

namespace Simpler
{
    /// <summary>(1.79.0, Luca: «immaginati fra qualche mese ci sono 5 pacchetti rilasciati e l'utente ne ha installati 3 come
    /// lo aiutiamo a fare ordine … si chiama SIMPLER non può essere complicato») One window «Pacchetti»: every pack
    /// released (PackCatalog) and every pack installed, each with its state - Installato (green), Nuovo (blue),
    /// Aggiornamento (orange) - and Dettagli / Installa / Aggiorna / Licenza / Disinstalla. The filters Tutti · Installati ·
    /// Da installare. A pack downloaded is then installed as one chosen from the disk (PackInstallWindow: licence,
    /// signature, every file). A blue strip tells of new packs and updates, once each.</summary>
    public sealed partial class MainWindow
    {
        Border? _packStrip;

        /// <summary>«Pacchetti…» (focus: the pack to show first, from the strip).</summary>
        async Task ShowInstalledPacks() => await ShowPacks(null);

        async Task ShowPacks(string? focus)
        {
            var pi = await PackInstallerNow();
            if (pi == null) return;
            if (_packStrip != null) _packStrip.Visibility = Visibility.Collapsed;
            var w = new PacksWindow(this, pi, focus) { Owner = this };
            w.ShowDialog();
            if (w.Changed) await ReloadModels();
        }

        /// <summary>Installs a pack file from the window of the packs; true when it went in.</summary>
        internal async Task<bool> InstallPackFrom(Window owner, string file)
        {
            var pi = await PackInstallerNow();
            if (pi == null) return false;
            var temp = Path.Combine(Path.GetTempPath(), "Simpler", "packs");
            var info = await Task.Run(() => pi.Inspect(file, temp));
            var w = new PackInstallWindow(this, pi, file, info) { Owner = owner };
            w.ShowDialog();
            try { if (info.CoverFile != "" && File.Exists(info.CoverFile)) File.Delete(info.CoverFile); } catch { }
            if (w.Installed) Status(L.F("Pacchetto «{0}» installato: {1} modelli", info.Title, info.Models));
            return w.Installed;
        }

        /// <summary>After the check of the updates (once a day, in the background): the packs not installed and the
        /// updates of the installed ones that were never told.</summary>
        async Task PackNewsCheck()
        {
            try
            {
                var list = await PackCatalog.Fetch();
                if (list == null || list.Count == 0) return;
                var pi = await PackInstallerNow(quiet: true);
                var installed = PacksInstalledVersions(pi);
                var s = Settings.Load();
                var news = PackCatalog.News(list, installed, s.PacksSeen);
                if (news.Count == 0) return;
                foreach (var e in news) s.PacksSeen.Add(PackCatalog.Key(e));
                s.Save();
                ShowPackStrip(news, installed);
            }
            catch (Exception ex) { AppLog.Write("packs news: " + ex.Message); }
        }

        internal static Dictionary<string, string> PacksInstalledVersions(PackInstaller? pi)
        {
            var d = new Dictionary<string, string>(StringComparer.Ordinal);
            if (pi == null) return d;
            foreach (var p in pi.Installed()) d[(string?)p["packId"] ?? ""] = (string?)p["version"] ?? "";
            return d;
        }

        void ShowPackStrip(List<PackCatalog.Entry> news, Dictionary<string, string> installed)
        {
            if (_packStrip == null) return;
            var row = new DockPanel { LastChildFill = true };
            _packStrip.Background = Theme.B("#10284A");      // (the blue of the packs)
            Button Btn(string text, Theme.Kind kind, string tip, Action click)
            {
                var b = Theme.Button(text, kind, tip);
                b.Margin = new Thickness(6, 0, 0, 0);
                b.Padding = new Thickness(10, 3, 10, 3);
                b.Click += (_, __) => click();
                DockPanel.SetDock(b, Dock.Right);
                return b;
            }
            row.Children.Add(Btn(L.T("Chiudi"), Theme.Kind.Ghost, L.T("Nascondi: i pacchetti restano in Importa ▸ Pacchetti…"), () => _packStrip.Visibility = Visibility.Collapsed));
            row.Children.Add(Btn(L.T("Vedi"), Theme.Kind.Primary, L.T("Apre la finestra dei pacchetti"), () => _ = ShowPacks(news[0].PackId)));
            string Name(PackCatalog.Entry e) => installed.ContainsKey(e.PackId) ? L.F("«{0}» {1} (aggiornamento)", e.Title, e.Version) : "«" + e.Title + "»";
            var text = new TextBlock { VerticalAlignment = VerticalAlignment.Center, TextTrimming = TextTrimming.CharacterEllipsis, FontSize = 13 };
            text.Inlines.Add(new System.Windows.Documents.Run(news.Count == 1
                    ? (installed.ContainsKey(news[0].PackId) ? L.T("Aggiornamento di un pacchetto") : L.T("Nuovo pacchetto"))
                    : L.F("{0} pacchetti nuovi o aggiornati", news.Count))
                { Foreground = Theme.B(Theme.Accent), FontWeight = FontWeights.SemiBold });
            text.Inlines.Add(new System.Windows.Documents.Run("  ·  " + string.Join(", ", news.Select(Name))) { Foreground = Theme.B("#BFD9FF") });
            row.Children.Add(text);
            _packStrip.Child = row;
            _packStrip.Visibility = Visibility.Visible;
        }
    }

    /// <summary>The packs: released (from the site) and installed, one card each.</summary>
    sealed class PacksWindow : ThemedDialog
    {
        public bool Changed { get; private set; }
        readonly MainWindow _mw;
        readonly PackInstaller _pi;
        readonly string? _focus;
        List<PackCatalog.Entry>? _catalog;
        bool _loading = true, _busy;
        string _filter = "all";
        CancellationTokenSource? _cancel;
        readonly StackPanel _filters = new() { Orientation = Orientation.Horizontal };
        readonly TextBlock _note = new() { FontSize = 12.5, Foreground = Theme.B(Theme.TextMuted), TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 8, 0, 4) };
        readonly StackPanel _list = new();
        readonly ScrollViewer _scroll;

        internal static readonly Color Blue = Theme.C("#4C9DFF");
        static readonly Color Green = Theme.C("#3FB950");
        static readonly Color Orange = Theme.C("#F0883E");

        sealed class Item
        {
            public string Id = "", Title = "", Description = "", Version = "", Author = "", Cover = "", License = "";
            public PackCatalog.Entry? Cat;
            public JsonObject? Inst;
            public string? InstalledVersion;
            public PackCatalog.State State;
            public int Models;
            public long Bytes;
            public List<string> Folders = new();
        }

        public PacksWindow(MainWindow mw, PackInstaller pi, string? focus) : base(L.T("Pacchetti"), 820)
        {
            _mw = mw; _pi = pi; _focus = focus;
            var top = new DockPanel { LastChildFill = false };
            top.Children.Add(_filters);
            var file = Theme.Button(Theme.IconText(Icons.Open, L.T("Installa da file…"), null, 14), Theme.Kind.Ghost,
                                    L.T("Installa un pacchetto Simpler (.simplerpack) che hai già sul computer"));
            file.Click += async (_, __) =>
            {
                if (_busy) return;
                var d = new Microsoft.Win32.OpenFileDialog { Filter = L.T("Pacchetto Simpler") + "|*.simplerpack", Title = L.T("Installa un pacchetto Simpler") };
                if (d.ShowDialog(this) != true) return;
                if (await _mw.InstallPackFrom(this, d.FileName)) { Changed = true; Render(); }
            };
            DockPanel.SetDock(file, Dock.Right);
            top.Children.Add(file);
            Body.Children.Add(top);
            Body.Children.Add(_note);
            _scroll = new ScrollViewer { Content = _list, MaxHeight = Math.Max(320, SystemParameters.WorkArea.Height - 260), VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
            Body.Children.Add(_scroll);
            var close = Theme.Button(L.T("Chiudi"), Theme.Kind.Normal);
            close.HorizontalAlignment = HorizontalAlignment.Right;
            close.Margin = new Thickness(0, 14, 0, 0);
            close.Click += (_, __) => Close();
            Body.Children.Add(close);
            Closing += (_, e) =>
            {
                if (!_busy) return;
                if (Msg.Show(this, L.T("Un pacchetto si sta scaricando. Interrompere?"), "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) { e.Cancel = true; return; }
                _cancel?.Cancel();
            };
            Render();
            Loaded += async (_, __) =>
            {
                _catalog = await PackCatalog.Fetch();
                _loading = false;
                // (what the window shows is seen: the strip does not tell it again)
                if (_catalog != null && _catalog.Count > 0)
                {
                    var s = Settings.Load();
                    foreach (var e in _catalog) if (!s.PacksSeen.Contains(PackCatalog.Key(e))) s.PacksSeen.Add(PackCatalog.Key(e));
                    s.Save();
                }
                Render();
            };
        }

        List<Item> Items()
        {
            var inst = _pi.Installed();
            var items = new List<Item>();
            foreach (var e in _catalog ?? new List<PackCatalog.Entry>())
            {
                var p = inst.FirstOrDefault(x => (string?)x["packId"] == e.PackId);
                var iv = p == null ? null : (string?)p["version"] ?? "";
                items.Add(new Item
                {
                    Id = e.PackId, Title = e.Title, Description = e.Description, Version = e.Version, Author = e.Author, License = e.License,
                    Cat = e, Inst = p, InstalledVersion = iv, State = PackCatalog.StateOf(e, iv), Models = e.Models, Bytes = e.Bytes,
                    Folders = e.Folders, Cover = p != null && e.Cover == "" ? (string?)p["coverFile"] ?? "" : "",
                });
            }
            // (installed from a file, or no longer on the site, or no internet): from what the pack left on this computer
            foreach (var p in inst.Where(p => items.All(i => i.Id != (string?)p["packId"])))
                items.Add(new Item
                {
                    Id = (string?)p["packId"] ?? "", Title = (string?)p["title"] ?? "", Description = (string?)p["description"] ?? "",
                    Version = (string?)p["version"] ?? "", Author = (string?)p["author"] ?? "", License = (string?)p["license"] ?? "",
                    Inst = p, InstalledVersion = (string?)p["version"] ?? "", State = PackCatalog.State.Installed,
                    Models = (p["models"] as JsonArray)?.Count ?? 0, Bytes = (long?)p["bytes"] ?? 0, Cover = (string?)p["coverFile"] ?? "",
                    Folders = (p["folders"] as JsonArray)?.Select(x => (string?)x ?? "").ToList() ?? new List<string>(),
                });
            // the news first (updates, then new ones), then the installed; by title
            return items.OrderBy(i => i.State switch { PackCatalog.State.Update => 0, PackCatalog.State.New => 1, _ => 2 })
                        .ThenBy(i => i.Title, StringComparer.CurrentCultureIgnoreCase).ToList();
        }

        void Render()
        {
            var items = Items();
            var nInst = items.Count(i => i.State != PackCatalog.State.New);
            var nNew = items.Count(i => i.State != PackCatalog.State.Installed);
            _filters.Children.Clear();
            void F(string key, string text, string tip)
            {
                var b = Theme.Button(text, _filter == key ? Theme.Kind.Segment : Theme.Kind.Ghost, tip);
                b.Margin = new Thickness(0, 0, 6, 0);
                b.Click += (_, __) => { _filter = key; Render(); };
                _filters.Children.Add(b);
            }
            F("all", L.F("Tutti ({0})", items.Count), L.T("Tutti i pacchetti: installati e disponibili"));
            F("installed", L.F("Installati ({0})", nInst), L.T("I pacchetti che hai già nella libreria"));
            F("todo", L.F("Da installare ({0})", nNew), L.T("I pacchetti che non hai e gli aggiornamenti di quelli che hai"));

            _note.Text = _loading ? L.T("Occupato · attendi") + " — " + L.T("lettura dei pacchetti disponibili")
                       : _catalog == null ? L.T("Il sito di Simpler non risponde (senza internet?): si vedono solo i pacchetti installati.")
                       : "";
            _note.Visibility = _note.Text == "" ? Visibility.Collapsed : Visibility.Visible;

            _list.Children.Clear();
            var shown = items.Where(i => _filter == "all" || (_filter == "installed" ? i.State != PackCatalog.State.New : i.State != PackCatalog.State.Installed)).ToList();
            if (shown.Count == 0 && !_loading)
                _list.Children.Add(new TextBlock
                {
                    Text = _filter == "todo" ? L.T("Hai già tutti i pacchetti, aggiornati.") : _filter == "installed" || _catalog == null
                        ? L.T("Nessun pacchetto installato.") : L.T("Nessun pacchetto disponibile per ora."),
                    Foreground = Theme.B(Theme.TextMuted), TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 6, 0, 6),
                });
            FrameworkElement? focusCard = null;
            foreach (var it in shown)
            {
                var card = Card(it);
                if (it.Id == _focus) focusCard = card;
                _list.Children.Add(card);
            }
            if (focusCard != null) Dispatcher.BeginInvoke(new Action(() => focusCard.BringIntoView()), System.Windows.Threading.DispatcherPriority.Loaded);
        }

        static Border Badge(string text, Color c) => new()
        {
            Background = new SolidColorBrush(Color.FromArgb(48, c.R, c.G, c.B)), BorderBrush = new SolidColorBrush(c), BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(4), Padding = new Thickness(7, 1, 7, 2), HorizontalAlignment = HorizontalAlignment.Left, Margin = new Thickness(0, 0, 0, 5),
            Child = new TextBlock { Text = text, FontSize = 11, FontWeight = FontWeights.Bold, Foreground = new SolidColorBrush(c) },
        };

        static (string text, Color color) StateLook(Item it) => it.State switch
        {
            PackCatalog.State.Update => (L.F("AGGIORNAMENTO {0} → {1}", it.InstalledVersion ?? "", it.Version), Orange),
            PackCatalog.State.New => (L.T("NUOVO"), Blue),
            _ => (L.T("INSTALLATO"), Green),
        };

        FrameworkElement Card(Item it)
        {
            var (stateText, stateColor) = StateLook(it);
            var row = new Border
            {
                Background = Theme.B(Theme.Raised), CornerRadius = new CornerRadius(8), Padding = new Thickness(10), Margin = new Thickness(0, 0, 0, 8),
                BorderBrush = it.Id == _focus ? new SolidColorBrush(stateColor) : Theme.B(Theme.Line), BorderThickness = new Thickness(1),
            };
            var g = new Grid();
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(184) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var picBox = new Border { Width = 170, Height = 96, CornerRadius = new CornerRadius(6), ClipToBounds = true, Background = Theme.B(Theme.Inset), HorizontalAlignment = HorizontalAlignment.Left, VerticalAlignment = VerticalAlignment.Top, Cursor = Cursors.Hand };
            picBox.MouseLeftButtonUp += (_, __) => Details(it);
            SetPicture(picBox, it, 340);
            g.Children.Add(picBox);

            var text = new StackPanel { VerticalAlignment = VerticalAlignment.Top, Margin = new Thickness(0, 0, 10, 0) };
            Grid.SetColumn(text, 1);
            text.Children.Add(Badge(stateText, stateColor));
            text.Children.Add(new TextBlock { Text = it.Title, FontSize = 15, FontWeight = FontWeights.SemiBold, Foreground = Theme.B(Theme.Text), TextWrapping = TextWrapping.Wrap });
            var lead = (it.Description.Replace("\r", "").Split("\n\n", StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).FirstOrDefault() ?? "");
            if (lead != "")
                text.Children.Add(new TextBlock { Text = lead, FontSize = 12.5, Foreground = Theme.B(Theme.TextSoft), TextWrapping = TextWrapping.Wrap, MaxHeight = 36, TextTrimming = TextTrimming.WordEllipsis, Margin = new Thickness(0, 3, 0, 0) });
            var facts = L.F("{0} modelli", it.Models) + " · " + MainWindow.PackSize(it.Cat?.Size > 0 && it.State != PackCatalog.State.Installed ? it.Cat.Size : it.Bytes)
                        + " · " + L.F("Versione {0}", it.Version) + (it.Cat?.Released is string r && r != "" ? " · " + r : "");
            text.Children.Add(new TextBlock { Text = facts, FontSize = 12, Foreground = Theme.B(Theme.TextMuted), Margin = new Thickness(0, 4, 0, 0), TextWrapping = TextWrapping.Wrap });
            var state = new TextBlock { FontSize = 12, Foreground = Theme.B(Theme.Warm), TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 4, 0, 0), Visibility = Visibility.Collapsed };
            var track = new Border { Height = 3, Background = Theme.B("#33FFFFFF"), CornerRadius = new CornerRadius(2), Visibility = Visibility.Collapsed, Margin = new Thickness(0, 5, 0, 0) };
            var fill = new Border { Height = 3, Background = Theme.B(Blue), CornerRadius = new CornerRadius(2), HorizontalAlignment = HorizontalAlignment.Left, Width = 0 };
            track.Child = fill;
            text.Children.Add(state);
            text.Children.Add(track);
            g.Children.Add(text);

            var btns = new StackPanel { VerticalAlignment = VerticalAlignment.Top, MinWidth = 120 };
            Grid.SetColumn(btns, 2);
            Button B(string label, Theme.Kind kind, string tip, Action click)
            {
                var b = Theme.Button(label, kind, tip);
                b.Margin = new Thickness(0, 0, 0, 6);
                b.Click += (_, __) => { if (!_busy) click(); };
                btns.Children.Add(b);
                return b;
            }
            if (it.Cat != null && it.State != PackCatalog.State.Installed)
                B(it.State == PackCatalog.State.Update ? L.F("Aggiorna alla {0}", it.Version) : L.T("Installa"), Theme.Kind.Primary,
                  L.T("Scarica il pacchetto da rodluc.com e lo installa (prima leggi e accetti la licenza)"), () => _ = Get(it, state, track, fill));
            B(L.T("Dettagli"), Theme.Kind.Normal, L.T("Descrizione completa, cartelle, miniature dei modelli"), () => Details(it));
            if (it.Inst != null)
            {
                B(L.T("Licenza"), Theme.Kind.Ghost, L.T("La licenza del pacchetto installato"), () =>
                {
                    var f = Path.Combine(Path.GetDirectoryName((string?)it.Inst["coverFile"] ?? "") ?? "", "LICENSE.txt");
                    string t = "";
                    try { t = File.Exists(f) ? File.ReadAllText(f) : ""; } catch { }
                    MainWindow.ShowPackLicense(this, it.Title, t);
                });
                B(L.T("Disinstalla"), Theme.Kind.Ghost, L.T("Toglie dalla libreria i modelli del pacchetto"), () => _ = Uninstall(it, state));
            }
            g.Children.Add(btns);
            row.Child = g;
            return row;
        }

        async void SetPicture(Border box, Item it, int width)
        {
            var f = it.Cover;
            if (f == "" && it.Cat != null && it.Cat.Cover != "") f = await PackCatalog.Picture(it.Cat.Cover);
            if (MainWindow.PackPicture(f, width) is ImageSource img) box.Child = new Image { Source = img, Stretch = Stretch.UniformToFill };
        }

        async Task Get(Item it, TextBlock state, Border track, Border fill)
        {
            if (it.Cat == null) return;
            if (it.Cat.SimplerMin != "" && PackInstallWindow.CompareVersions(it.Cat.SimplerMin, SettingsDialog.Version) > 0)
            {
                Msg.Show(this, L.F("Questo pacchetto chiede Simpler {0} o più recente: aggiorna prima Simpler.", it.Cat.SimplerMin), "Simpler", MessageBoxButton.OK, MessageBoxImage.Information);
                return;
            }
            _busy = true;
            _cancel = new CancellationTokenSource();
            state.Visibility = track.Visibility = Visibility.Visible;
            state.Foreground = Theme.B(Theme.Warm);
            state.Text = L.T("Occupato · attendi") + " — " + L.T("download");
            Cursor = Cursors.AppStarting;
            string? file = null;
            try
            {
                file = await PackCatalog.Get(it.Cat, (done, all) => Dispatcher.BeginInvoke(() =>
                {
                    state.Text = L.T("Occupato · attendi") + " — " + L.F("download {0} di {1}", MainWindow.PackSize(done), MainWindow.PackSize(all));
                    fill.Width = track.ActualWidth * (all == 0 ? 0 : (double)done / all);
                }), _cancel.Token);
            }
            catch (OperationCanceledException) { state.Text = L.T("Download interrotto"); }
            catch (Exception ex)
            {
                AppLog.Write("pack download: " + ex.Message);
                state.Text = ex is InvalidDataException ? L.T("Il file scaricato non è quello pubblicato: non è stato installato nulla. Riprova più tardi.")
                                                        : L.T("Download non riuscito: controlla la connessione e riprova.");
                state.Foreground = Theme.B(Theme.Danger);
            }
            finally { _busy = false; Cursor = null; track.Visibility = Visibility.Collapsed; }
            if (file == null) return;
            state.Visibility = Visibility.Collapsed;
            if (await _mw.InstallPackFrom(this, file)) { Changed = true; PackCatalog.Forget(file); }
            Render();
        }

        async Task Uninstall(Item it, TextBlock state)
        {
            if (Msg.Show(this, L.F("Disinstallare «{0}»? I suoi modelli escono dalla libreria (quelli che servono anche a un altro pacchetto restano).", it.Title),
                         "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
            _busy = true;
            state.Visibility = Visibility.Visible;
            state.Foreground = Theme.B(Theme.Warm);
            state.Text = L.T("Occupato · attendi");
            Cursor = Cursors.AppStarting;
            try { await Task.Run(() => _pi.Uninstall(it.Id)); Changed = true; }
            catch (Exception ex) { Msg.Show(this, ex.Message, "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning); }
            finally { _busy = false; Cursor = null; }
            Render();
        }

        void Details(Item it)
        {
            var (stateText, stateColor) = StateLook(it);
            var w = new PackDetailsWindow(it.Title, it.Description, stateText, stateColor, it.Cover, it.Cat,
                                          L.F("{0} modelli", it.Models) + " · " + MainWindow.PackSize(it.Bytes) + " · " + L.F("Versione {0}", it.Version)
                                          + (it.Author != "" ? " · " + it.Author : "") + (it.License.Trim() != "" ? " · " + it.License.Trim() : ""),
                                          it.Folders) { Owner = this };
            w.ShowDialog();
        }
    }

    /// <summary>A pack in full: the cover, all the description, the facts, where it goes (in blue, the colour of the
    /// packs) and the thumbnails of some of its models.</summary>
    sealed class PackDetailsWindow : ThemedDialog
    {
        public PackDetailsWindow(string title, string description, string stateText, Color stateColor, string coverFile, PackCatalog.Entry? cat,
                                 string facts, List<string> folders) : base(title, 760)
        {
            var cover = new Border { Height = 716 * 9 / 16.0, CornerRadius = new CornerRadius(8), ClipToBounds = true, Background = Theme.B(Theme.Inset), Margin = new Thickness(0, 0, 0, 12) };
            Body.Children.Add(cover);
            Body.Children.Add(new Border
            {
                Background = new SolidColorBrush(Color.FromArgb(48, stateColor.R, stateColor.G, stateColor.B)), BorderBrush = new SolidColorBrush(stateColor),
                BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(4), Padding = new Thickness(7, 1, 7, 2), HorizontalAlignment = HorizontalAlignment.Left,
                Child = new TextBlock { Text = stateText, FontSize = 11, FontWeight = FontWeights.Bold, Foreground = new SolidColorBrush(stateColor) },
            });
            Body.Children.Add(new TextBlock { Text = facts, FontSize = 12.5, Foreground = Theme.B(Theme.TextMuted), Margin = new Thickness(0, 6, 0, 8), TextWrapping = TextWrapping.Wrap });
            if (description.Trim() != "")
                Body.Children.Add(new TextBlock { Text = description.Trim(), FontSize = 13.5, Foreground = Theme.B(Theme.Text), TextWrapping = TextWrapping.Wrap, LineHeight = 20, Margin = new Thickness(0, 0, 0, 10) });
            if (folders.Count > 0)
            {
                Body.Children.Add(Theme.Label(L.T("Dove va nella libreria"), 12.5, Theme.TextSoft, FontWeights.SemiBold));
                foreach (var f in folders.Take(12))
                {
                    var r = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 4, 0, 0) };
                    r.Children.Add(Theme.Icon(Icons.Folder, PacksWindow.Blue, 13));
                    r.Children.Add(new TextBlock { Text = f.Replace("/", "  ▸  "), FontSize = 12, Foreground = new SolidColorBrush(PacksWindow.Blue), Margin = new Thickness(7, 0, 0, 0), TextWrapping = TextWrapping.Wrap });
                    Body.Children.Add(r);
                }
                if (folders.Count > 12) Body.Children.Add(Theme.Label(L.F("… e altre {0} cartelle", folders.Count - 12), 12, Theme.TextFaint));
            }
            var thumbs = new WrapPanel { Margin = new Thickness(0, 12, 0, 0) };
            if (cat != null && cat.Thumbs.Count > 0)
            {
                Body.Children.Add(Theme.Label(L.T("Alcuni modelli"), 12.5, Theme.TextSoft, FontWeights.SemiBold));
                Body.Children.Add(thumbs);
            }
            var ok = Theme.Button(L.T("Chiudi"), Theme.Kind.Normal);
            ok.Click += (_, __) => Close();
            ok.HorizontalAlignment = HorizontalAlignment.Right;
            ok.Margin = new Thickness(0, 12, 0, 0);
            Footer.Children.Add(ok);
            EnableBodyScroll();
            Loaded += async (_, __) =>
            {
                var f = coverFile;
                if (f == "" && cat != null && cat.Cover != "") f = await PackCatalog.Picture(cat.Cover);
                if (MainWindow.PackPicture(f, 1100) is ImageSource img) cover.Child = new Image { Source = img, Stretch = Stretch.UniformToFill };
                else cover.Visibility = Visibility.Collapsed;
                if (cat == null) return;
                foreach (var t in cat.Thumbs)
                {
                    var tf = await PackCatalog.Picture(t);
                    if (MainWindow.PackPicture(tf, 240) is not ImageSource ti) continue;
                    thumbs.Children.Add(new Border
                    {
                        Width = 112, Height = 112, CornerRadius = new CornerRadius(6), ClipToBounds = true, Background = Theme.B(Theme.Inset), Margin = new Thickness(0, 0, 8, 8),
                        Child = new Image { Source = ti, Stretch = Stretch.Uniform },
                    });
                }
            };
        }
    }
}
