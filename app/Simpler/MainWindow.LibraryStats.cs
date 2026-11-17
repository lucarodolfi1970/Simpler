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
        LibraryStatsDialog? _libStats;

        void ShowLibraryStats()
        {
            if (_libStats != null) { _libStats.Show(); _libStats.Activate(); WatchDialogLock(); return; }
            _libStats = new LibraryStatsDialog(this) { Owner = this };
            _libStats.Closed += (_, __) => _libStats = null;
            _libStats.Show();
            WatchDialogLock();
        }

        /// <summary>
        /// "Statistiche e pulizia della libreria": how many models, how much space (model files, textures, thumbnails,
        /// original files) for the whole library or the chosen folders, per folder, the biggest models; then suggestions
        /// to save space (backups of the material fixes, textures of deleted models, duplicates, caches, broken models),
        /// each with its action when there is one. Only files are read: the scene and the engine stay free.
        /// </summary>
        sealed class LibraryStatsDialog : ThemedDialog
        {
            readonly MainWindow _mw;
            readonly CheckBox _all;
            readonly WrapPanel _folders = new();
            readonly List<(string folder, CheckBox box)> _folderChecks = new();
            readonly StackPanel _results = new();
            readonly ProgressBar _bar;
            readonly TextBlock _status;
            readonly Button _run;
            bool _busy;

            public LibraryStatsDialog(MainWindow mw) : base(L.T("Statistiche e pulizia della libreria"), 900)
            {
                _mw = mw;
                var sp = Body;
                sp.Children.Add(new TextBlock
                {
                    Text = L.T("Quanti modelli hai, quanto spazio occupano (file dei modelli, texture, miniature, file originali importati) e dove. Poi i suggerimenti per non sprecare spazio: copie di sicurezza, texture di modelli eliminati, duplicati, cache. Simpler legge solo i file: la scena non viene toccata."),
                    TextWrapping = TextWrapping.Wrap, FontSize = 12.5, Foreground = Theme.B(Theme.TextMuted), LineHeight = 19, Margin = new Thickness(0, 0, 0, 12),
                });
                var row = new DockPanel { Margin = new Thickness(0, 0, 0, 6) };
                _all = new CheckBox { Content = L.T("Tutta la libreria"), IsChecked = true, Foreground = Theme.B(Theme.TextSoft), VerticalAlignment = VerticalAlignment.Center };
                _all.Checked += (_, __) => _folders.IsEnabled = false;
                _all.Unchecked += (_, __) => _folders.IsEnabled = true;
                row.Children.Add(_all);
                _run = Theme.Button(Theme.IconText(Icons.Sliders, L.T("Calcola"), Theme.Accent, 14), Theme.Kind.Primary);
                _run.Click += async (_, __) => await Run();
                DockPanel.SetDock(_run, Dock.Right);
                row.Children.Insert(0, _run);
                sp.Children.Add(row);
                foreach (var f in mw._modelFolders.OrderBy(x => x, StringComparer.CurrentCultureIgnoreCase))
                {
                    var cb = new CheckBox { Content = Theme.IconText(Icons.Folder, f.Replace("/", " / "), Theme.Warm, 13), Foreground = Theme.B(Theme.TextMuted), Margin = new Thickness(0, 2, 14, 2) };
                    _folderChecks.Add((f, cb));
                    _folders.Children.Add(cb);
                }
                _folders.IsEnabled = false;
                sp.Children.Add(new ScrollViewer { Content = _folders, MaxHeight = 92, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Margin = new Thickness(22, 0, 0, 8), Padding = new Thickness(0, 0, 6, 0) });
                _bar = new ProgressBar { Height = 6, Minimum = 0, Maximum = 1, Value = 0, Foreground = Theme.B(Theme.Accent), Background = Theme.B("#1A2842"), BorderThickness = new Thickness(0), Margin = new Thickness(0, 4, 0, 6) };
                sp.Children.Add(_bar);
                _status = Theme.Label("", 12, Theme.TextMuted);
                sp.Children.Add(_status);
                sp.Children.Add(new ScrollViewer { Content = _results, MaxHeight = Math.Max(260, SystemParameters.WorkArea.Height - 430), VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Margin = new Thickness(0, 10, 0, 0), Padding = new Thickness(0, 0, 6, 0) });
                var close = Theme.Button(L.T("Chiudi"), Theme.Kind.Ghost);
                close.HorizontalAlignment = HorizontalAlignment.Right;
                close.Margin = new Thickness(0, 12, 0, 0);
                close.Click += (_, __) => Close();
                sp.Children.Add(close);
                KeyDown += (_, e) => { if (e.Key == Key.Escape) Close(); };
                Loaded += async (_, __) => await Run();
                _keepCentred = true;      // the window grows when the results arrive: always in the middle of the screen
            }

            static string Bytes(double b)
            {
                var c = CultureInfo.CurrentCulture;
                if (b >= 1e9) return (b / 1e9).ToString("0.##", c) + " GB";
                if (b >= 1e6) return (b / 1e6).ToString("0.#", c) + " MB";
                if (b >= 1e3) return (b / 1e3).ToString("0", c) + " KB";
                return b.ToString("0", c) + " B";
            }

            static double D(JsonNode? n) => (double?)n ?? 0;

            async Task Run()
            {
                if (_busy || _mw._api == null) return;
                var chosen = _folderChecks.Where(x => x.box.IsChecked == true).Select(x => x.folder).ToList();
                if (_all.IsChecked != true && chosen.Count == 0) { _status.Text = L.T("Scegli almeno una cartella"); return; }
                _busy = true;
                _run.IsEnabled = false;
                try
                {
                    var body = _all.IsChecked == true ? new JsonObject { ["all"] = true }
                                                      : new JsonObject { ["folders"] = new JsonArray(chosen.Select(f => (JsonNode)f!).ToArray()) };
                    await _mw._api.Post("libstats/run", body);
                    while (true)
                    {
                        await Task.Delay(300);
                        JsonObject st;
                        try { st = await _mw._api.Get("libstats/status"); } catch { continue; }
                        var state = (string?)st["state"] ?? "";
                        int done = (int?)st["done"] ?? 0, total = Math.Max(1, (int?)st["total"] ?? 1);
                        _bar.Value = Math.Min(1, (double)done / total);
                        _status.Text = (string?)st["phase"] ?? "";
                        if (state == "running") continue;
                        _bar.Value = 0;
                        if (state != "done" || st["result"] is not JsonObject r) { _status.Text = (string?)st["error"] ?? state; break; }
                        _status.Text = "";
                        Show(r);
                        break;
                    }
                }
                catch (Exception ex) { _status.Text = ex.Message; }
                finally { _busy = false; _run.IsEnabled = true; }
            }

            // ---------------------------------------------------------------- results

            static FrameworkElement Section(string title)
            {
                var t = Theme.Label(title, 14, Theme.Text, FontWeights.SemiBold);
                t.Margin = new Thickness(0, 16, 0, 8);
                return t;
            }

            static FrameworkElement Tile(string label, string value, string sub, Color color)
            {
                var sp = new StackPanel();
                sp.Children.Add(Theme.Label(label, 11.5, Theme.TextMuted));
                sp.Children.Add(new TextBlock { Text = value, FontSize = 22, FontWeight = FontWeights.SemiBold, Foreground = new SolidColorBrush(color), Margin = new Thickness(0, 2, 0, 0) });
                if (sub != "") sp.Children.Add(Theme.Label(sub, 11, Theme.TextFaint));
                return new Border { Child = sp, Background = Theme.B(Theme.Inset), BorderBrush = Theme.B(Theme.Line), BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(10), Padding = new Thickness(12, 10, 12, 10), Margin = new Thickness(0, 0, 8, 8) };
            }

            static FrameworkElement BarRow(string name, string sub, double bytes, double max, string right)
            {
                var g = new Grid { Margin = new Thickness(0, 0, 0, 6) };
                g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(280) });
                g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(170) });
                var left = new StackPanel();
                left.Children.Add(new TextBlock { Text = name, FontSize = 12, Foreground = Theme.B(Theme.TextSoft), TextTrimming = TextTrimming.CharacterEllipsis, ToolTip = name });
                if (sub != "") left.Children.Add(new TextBlock { Text = sub, FontSize = 10.5, Foreground = Theme.B(Theme.TextFaint), TextTrimming = TextTrimming.CharacterEllipsis });
                g.Children.Add(left);
                var track = new Grid { Height = 6, Margin = new Thickness(8, 0, 10, 0), VerticalAlignment = VerticalAlignment.Center };
                track.Children.Add(new Border { Background = Theme.B("#1A2842"), CornerRadius = new CornerRadius(3) });
                var frac = max > 0 ? Math.Max(0.01, bytes / max) : 0;
                track.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(frac, GridUnitType.Star) });
                track.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(Math.Max(0, 1 - frac), GridUnitType.Star) });
                var fill = new Border { Background = Theme.B(Theme.Accent), CornerRadius = new CornerRadius(3) };
                Grid.SetColumnSpan(track.Children[0], 2);
                track.Children.Add(fill);
                Grid.SetColumn(track, 1);
                g.Children.Add(track);
                var rt = new TextBlock { Text = right, FontSize = 12, Foreground = Theme.B(Theme.TextSoft), HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Center };
                Grid.SetColumn(rt, 2);
                g.Children.Add(rt);
                return g;
            }

            void Show(JsonObject r)
            {
                _results.Children.Clear();
                var t = r["totals"] as JsonObject ?? new JsonObject();
                double blend = D(t["blend"]), tex = D(t["textures"]), thumbs = D(t["thumbs"]), src = D(t["sources"]);
                var tiles = new UniformGrid { Columns = 3 };
                tiles.Children.Add(Tile(L.T("Modelli"), ((int?)t["models"] ?? 0).ToString(), (bool?)r["all"] == true ? L.T("tutta la libreria") : L.T("nelle cartelle scelte"), Theme.Text));
                tiles.Children.Add(Tile(L.T("Spazio nella libreria"), Bytes(blend + tex + thumbs), L.T("modelli + texture + miniature"), Theme.Accent));
                tiles.Children.Add(Tile(L.T("File dei modelli (.blend)"), Bytes(blend), "", Theme.TextSoft));
                tiles.Children.Add(Tile(L.T("Texture"), Bytes(tex), L.F("{0} file", (int?)t["texFiles"] ?? 0), Theme.Teal));
                tiles.Children.Add(Tile(L.T("Miniature"), Bytes(thumbs), "", Theme.TextSoft));
                tiles.Children.Add(Tile(L.T("File originali importati (FBX, OBJ…)"), Bytes(src),
                    L.F("{0} file, fuori dalla libreria: Simpler non li usa", (int?)t["sourceFiles"] ?? 0) + (((int?)t["sourceMissing"] ?? 0) > 0 ? " · " + L.F("{0} non più trovati", (int?)t["sourceMissing"]) : ""), Theme.Warm));
                _results.Children.Add(tiles);
                // what is what: the library is what Simpler uses; the original files are the user's, elsewhere
                var expl = new TextBlock
                {
                    Text = L.F("Spazio usato da Simpler: {0} (la libreria: modelli, texture e miniature).", Bytes(blend + tex + thumbs)) + "\n" +
                           L.F("I file originali importati ({0}) sono i tuoi FBX, OBJ… nelle loro cartelle: dopo l'import Simpler non li usa più, servono solo se vuoi reimportare. In tutto su disco: {1}.", Bytes(src), Bytes(blend + tex + thumbs + src)),
                    TextWrapping = TextWrapping.Wrap, FontSize = 12, Foreground = Theme.B(Theme.TextSoft), LineHeight = 18, Margin = new Thickness(0, 2, 0, 0),
                };
                _results.Children.Add(expl);

                var folders = (r["folders"] as JsonArray ?? new JsonArray()).OfType<JsonObject>().ToList();
                if (folders.Count > 0)
                {
                    _results.Children.Add(Section(L.T("Per cartella")));
                    var max = folders.Max(f => D(f["bytes"]));
                    foreach (var f in folders)
                    {
                        var name = (string?)f["folder"] is string fn && fn != "" ? fn.Replace("/", " / ") : L.T("Modelli 3D (cartella principale)");
                        _results.Children.Add(BarRow(name, L.F("{0} modelli", (int?)f["models"] ?? 0), D(f["bytes"]), max,
                            Bytes(D(f["bytes"])) + "  ·  " + L.F("texture {0}", Bytes(D(f["textures"])))));
                    }
                }
                var big = (r["biggest"] as JsonArray ?? new JsonArray()).OfType<JsonObject>().ToList();
                if (big.Count > 0)
                {
                    _results.Children.Add(Section(L.T("I modelli più pesanti")));
                    var max = big.Max(m => D(m["bytes"]));
                    foreach (var m in big)
                        _results.Children.Add(BarRow((string?)m["name"] ?? "", ((string?)m["folder"] ?? "").Replace("/", " / "), D(m["bytes"]), max,
                            Bytes(D(m["bytes"])) + "  ·  " + L.F("{0} texture", (int?)m["texFiles"] ?? 0)));
                }
                var exts = (r["exts"] as JsonArray ?? new JsonArray()).OfType<JsonObject>().ToList();
                if (exts.Count > 0)
                {
                    _results.Children.Add(Section(L.T("Texture per formato")));
                    var max = exts.Max(e => D(e["bytes"]));
                    foreach (var e in exts)
                        _results.Children.Add(BarRow(((string?)e["ext"] ?? "").TrimStart('.').ToUpperInvariant(), "", D(e["bytes"]), max, Bytes(D(e["bytes"]))));
                }
                var other = (r["other"] as JsonArray ?? new JsonArray()).OfType<JsonObject>().Where(o => D(o["bytes"]) > 0).ToList();
                if (other.Count > 0)
                {
                    _results.Children.Add(Section(L.T("Altro spazio usato da Simpler")));
                    var max = other.Max(o => D(o["bytes"]));
                    foreach (var o in other)
                        _results.Children.Add(BarRow((string?)o["label"] ?? "", (string?)o["dir"] ?? "", D(o["bytes"]), max, Bytes(D(o["bytes"]))));
                }

                var sug = (r["suggestions"] as JsonArray ?? new JsonArray()).OfType<JsonObject>().ToList();
                _results.Children.Add(Section(L.T("Suggerimenti per risparmiare spazio")));
                if (sug.Count == 0)
                    _results.Children.Add(Theme.Label(L.T("Niente da segnalare: la libreria è in ordine."), 12.5, Theme.TextSoft));
                else
                {
                    var total = sug.Where(s => ((string?)s["action"] ?? "") != "").Sum(s => D(s["bytes"]));
                    if (total > 0) _results.Children.Add(Theme.Label(L.F("Si possono liberare fino a {0}.", Bytes(total)), 12.5, Theme.Accent));
                    foreach (var s in sug) _results.Children.Add(Suggestion(s));
                }
            }

            FrameworkElement Suggestion(JsonObject s)
            {
                var kind = (string?)s["kind"] ?? "";
                var action = (string?)s["action"] ?? "";
                var warn = (bool?)s["warning"] == true;
                var sp = new StackPanel();
                var head = new DockPanel();
                var size = Theme.Label(D(s["bytes"]) > 0 ? Bytes(D(s["bytes"])) : "", 13, warn ? Theme.Warm : Theme.Accent, FontWeights.SemiBold);
                DockPanel.SetDock(size, Dock.Right);
                head.Children.Add(size);
                head.Children.Add(Theme.Label((string?)s["title"] ?? "", 13, Theme.Text, FontWeights.SemiBold));
                sp.Children.Add(head);
                sp.Children.Add(new TextBlock { Text = (string?)s["text"] ?? "", TextWrapping = TextWrapping.Wrap, FontSize = 12, Foreground = Theme.B(Theme.TextMuted), Margin = new Thickness(0, 4, 0, 6), LineHeight = 17 });
                var items = (s["items"] as JsonArray ?? new JsonArray()).OfType<JsonObject>().ToList();
                var lines = items.Select(it => ItemText(kind, it)).Where(x => x != "").ToList();
                if (lines.Count > 0)
                {
                    var list = new TextBlock { Text = string.Join("\n", lines.Take(8)) + (lines.Count > 8 ? "\n" + L.F("… e altri {0}", lines.Count - 8) : ""), FontSize = 11.5, Foreground = Theme.B(Theme.TextFaint), Margin = new Thickness(8, 0, 0, 6) };
                    sp.Children.Add(list);
                }
                if (action != "")
                {
                    var label = action switch
                    {
                        "backups" => L.T("Elimina le copie di sicurezza"),
                        "orphans" => L.T("Elimina queste texture…"),
                        "broken" => L.T("Togli dall'elenco"),
                        "caches" => L.T("Svuota la cache"),
                        _ => L.T("Pulisci"),
                    };
                    var b = Theme.Button(label, warn ? Theme.Kind.Ghost : Theme.Kind.Normal);
                    b.HorizontalAlignment = HorizontalAlignment.Left;
                    b.Click += async (_, __) => await Clean(action, (string?)s["title"] ?? "", D(s["bytes"]), warn);
                    sp.Children.Add(b);
                }
                return new Border
                {
                    Child = sp, Background = Theme.B(Theme.Inset), BorderBrush = Theme.B(warn ? Theme.Warm : Theme.Line), BorderThickness = new Thickness(1),
                    CornerRadius = new CornerRadius(10), Padding = new Thickness(14, 10, 14, 12), Margin = new Thickness(0, 0, 0, 8),
                };
            }

            static string ItemText(string kind, JsonObject it) => kind switch
            {
                "dupTextures" => L.F("{0} · {1} copie · {2}", (string?)it["file"] ?? "", (int?)it["copies"] ?? 0, Bytes(D(it["bytes"]))) + "  (" +
                                 string.Join(", ", (it["models"] as JsonArray ?? new JsonArray()).Select(m => (string?)m ?? "").Take(3)) + ")",
                "backups" => L.F("{0} · {1} modelli · {2}", (string?)it["when"] ?? "", (int?)it["models"] ?? 0, Bytes(D(it["bytes"]))) + ((bool?)it["restored"] == true ? "  " + L.T("(già ripristinata)") : ""),
                "orphans" => L.F("{0} · {1} file · {2}", (string?)it["id"] ?? "", (int?)it["files"] ?? 0, Bytes(D(it["bytes"]))),
                "packed" => ((string?)it["name"] ?? "") + " · " + Bytes(D(it["bytes"])),
                "broken" => ((string?)it["name"] ?? "") + (((string?)it["folder"] ?? "") != "" ? "  (" + (string?)it["folder"] + ")" : ""),
                "caches" => ((string?)it["id"] == "viewcache" ? L.T("Scene preparate per la vista 3D") : L.T("Texture ridotte")) + " · " + Bytes(D(it["bytes"])),
                _ => it is JsonObject ? "" : "",
            };

            async Task Clean(string action, string title, double bytes, bool warn)
            {
                if (_busy || _mw._api == null) return;
                var text = warn
                    ? L.F("{0}: {1}.", title, Bytes(bytes)) + "\n\n" + L.T("Attenzione: se un progetto salvato usa ancora uno di questi modelli, si riaprirà con i materiali rosa. Le texture usate dalla scena aperta ora vengono tenute.") + "\n\n" + L.T("Eliminare comunque?")
                    : L.F("{0}: liberare {1}?", title, Bytes(bytes));
                if (Msg.Show(this, text, "Simpler", MessageBoxButton.YesNo, warn ? MessageBoxImage.Warning : MessageBoxImage.Question) != MessageBoxResult.Yes) return;
                try
                {
                    var r = await _mw._api.Post("libstats/clean", new JsonObject { ["action"] = action });
                    _mw.Status(L.F("Liberati {0}", Bytes(D(r["bytes"]))));
                    if (action == "broken") await _mw.ReloadModels();
                }
                catch (Exception ex) { _status.Text = ex.Message; return; }
                await Run();
            }
        }
    }
}
