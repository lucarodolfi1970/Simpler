using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;

namespace Simpler
{
    /// <summary>
    /// Impostazioni > Cartelle: where Simpler keeps what it downloads (Poly Haven materials and models) and the
    /// user's libraries (3D models, materials). Each one can be moved; the files can go along. Projects keep
    /// working: their textures remember the library they come from, not the folder (engine/simpler/paths.py).
    /// </summary>
    public sealed partial class MainWindow
    {
        async Task ShowFoldersDialog()
        {
            if (_api == null) return;
            JsonObject? r = null;
            await Run(async api => { r = await api.Get("paths"); });
            if (r == null) return;
            var dlg = new FoldersDialog(this, r) { Owner = this };
            dlg.ShowDialog();
            if (!dlg.Changed) return;
            await LoadDecalRoot();
            _ecosystems = new JsonArray(); _ecoLoaded = false;
            _phAssets = new JsonArray();
            _phmAssets = new JsonArray();
            await ReloadModels();
            await ReloadLibraryMaterials();
            _ = LoadPolyHaven();
            _ = LoadPhModels();
            RenderLibrary();
        }

        sealed class FoldersDialog : ThemedDialog
        {
            readonly MainWindow _mw;
            readonly StackPanel _rows = new StackPanel();
            public bool Changed { get; private set; }

            public FoldersDialog(MainWindow mw, JsonObject data) : base(L.T("Cartelle"), 640)
            {
                _mw = mw;
                Body.Children.Add(Theme.Label(L.T("Cartelle dei file"), 18, Theme.Text, FontWeights.SemiBold));
                var intro = Theme.Label(L.T("Dove Simpler tiene i file scaricati e le tue librerie. Puoi spostarle dove vuoi (un altro disco, una cartella condivisa): i progetti continuano ad aprirsi, perché ricordano la libreria da cui viene ogni texture, non la cartella."), 12, Theme.TextMuted);
                intro.TextWrapping = TextWrapping.Wrap;
                intro.Margin = new Thickness(0, 8, 0, 14);
                Body.Children.Add(intro);
                Body.Children.Add(_rows);
                Fill(data);
                var close = Theme.Button(L.T("Chiudi"), Theme.Kind.Primary);
                close.HorizontalAlignment = HorizontalAlignment.Right;
                close.Margin = new Thickness(0, 16, 0, 0);
                close.Click += (_, __) => Close();
                Body.Children.Add(close);
            }

            void Fill(JsonObject data)
            {
                _rows.Children.Clear();
                foreach (var f in (data["folders"] as JsonArray)?.OfType<JsonObject>() ?? Enumerable.Empty<JsonObject>())
                {
                    var key = (string?)f["key"] ?? "";
                    var path = (string?)f["path"] ?? "";
                    var isDefault = (bool?)f["isDefault"] ?? true;
                    var box = new Border
                    {
                        Background = Theme.B("#0E1A30"), BorderBrush = Theme.B("#1E2F50"), BorderThickness = new Thickness(1),
                        CornerRadius = new CornerRadius(8), Padding = new Thickness(12, 10, 12, 10), Margin = new Thickness(0, 0, 0, 8),
                    };
                    var sp = new StackPanel();
                    var head = new DockPanel();
                    var title = Theme.Label((string?)f["label"] ?? key, 13, Theme.Text, FontWeights.SemiBold);
                    head.Children.Add(title);
                    if (isDefault)
                    {
                        var tag = Theme.Label(L.T("predefinita"), 11, Theme.TextFaint);
                        tag.Margin = new Thickness(8, 1, 0, 0);
                        head.Children.Add(tag);
                    }
                    sp.Children.Add(head);
                    var p = new TextBox
                    {
                        Text = path, IsReadOnly = true, Background = System.Windows.Media.Brushes.Transparent, BorderThickness = new Thickness(0),
                        Foreground = Theme.B(Theme.TextSoft), FontSize = 12, Margin = new Thickness(0, 4, 0, 8), TextWrapping = TextWrapping.Wrap,
                    };
                    sp.Children.Add(p);
                    var buttons = new StackPanel { Orientation = Orientation.Horizontal };
                    var change = Theme.Button(L.T("Cambia…"), Theme.Kind.Normal);
                    change.Click += async (_, __) => await Change(key, path, null);
                    buttons.Children.Add(change);
                    var open = Theme.Button(L.T("Apri in Esplora risorse"), Theme.Kind.Ghost);
                    open.Margin = new Thickness(6, 0, 0, 0);
                    open.Click += (_, __) => { try { System.Diagnostics.Process.Start("explorer.exe", path); } catch { } };
                    buttons.Children.Add(open);
                    if (!isDefault)
                    {
                        var reset = Theme.Button(L.T("Torna alla predefinita"), Theme.Kind.Ghost, (string?)f["default"]);
                        reset.Margin = new Thickness(6, 0, 0, 0);
                        reset.Click += async (_, __) => await Change(key, path, (string?)f["default"] ?? "");
                        buttons.Children.Add(reset);
                    }
                    sp.Children.Add(buttons);
                    box.Child = sp;
                    _rows.Children.Add(box);
                }
            }

            static string Size(double b) => b >= 1e9 ? L.F("{0} GB", (b / 1e9).ToString("0.0")) : b >= 1e6 ? L.F("{0} MB", (b / 1e6).ToString("0")) : L.F("{0} KB", Math.Max(1, b / 1e3).ToString("0"));

            async Task<JsonObject?> Post(string path, object body)
            {
                try { return _mw._api == null ? null : await _mw._api.Post(path, body); }
                catch (Exception ex) { Msg.Show(this, ex.Message, "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning); return null; }
            }

            async Task Change(string key, string current, string? target)
            {
                if (target == null)
                {
                    var dlg = new Microsoft.Win32.OpenFolderDialog
                    {
                        Title = L.T("Scegli la nuova cartella (vuota): Simpler ci copierà tutto"), InitialDirectory = System.IO.Path.GetDirectoryName(current) ?? current,
                    };
                    if (dlg.ShowDialog(this) != true) return;
                    target = dlg.FolderName;
                }
                var chk = await Post("paths/check", new { key, path = target });
                if (chk == null) return;
                target = (string?)chk["path"] ?? target;
                var old = (string?)chk["old"] ?? current;
                var files = (int?)chk["files"] ?? 0;
                var bytes = (double?)chk["bytes"] ?? 0;
                if (!((bool?)chk["empty"] ?? true))
                {
                    var use = Msg.Show(this, L.F("La cartella\n{0}\nnon è vuota.\n\nSì: usala così com'è (per esempio contiene già una copia della libreria).\nNo: scegline un'altra, vuota.", target),
                                       "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question);
                    if (use != MessageBoxResult.Yes) return;
                    await Switch(key, target, false);
                    return;
                }
                if (files > 0)
                {
                    var ans = Msg.Show(this, L.F("Vuoi che Simpler sposti automaticamente tutto il contenuto ({0} file, {1}, con tutte le sottocartelle) da\n{2}\na\n{3}?\n\nSì: Simpler copia tutto, controlla la copia e poi usa la nuova cartella.\nNo: Simpler usa la nuova cartella vuota (la libreria ripartirà da zero; i file restano dove sono).",
                                                 files, Size(bytes), old, target),
                                       "Simpler", MessageBoxButton.YesNoCancel, MessageBoxImage.Question);
                    if (ans == MessageBoxResult.Cancel || ans == MessageBoxResult.None) return;
                    if (ans == MessageBoxResult.No) { await Switch(key, target, false); return; }
                    if (await Post("paths/copy", new { key, path = target }) == null) return;
                    var res = JobDialog.Run(this, _mw, L.T("Copia della libreria"), L.F("Da {0}\na {1}", old, target));
                    if ((string?)res?["state"] != "done")
                    {
                        var why = (string?)res?["state"] == "cancelled" ? L.T("Copia annullata.") : L.F("Copia non riuscita: {0}", (string?)res?["error"] ?? "");
                        Msg.Show(this, why + "\n\n" + L.F("Simpler continua a usare la cartella di prima. I file già copiati sono rimasti in\n{0}", target),
                                 "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning);
                        return;
                    }
                    if (!await Switch(key, target, true)) return;
                    var del = Msg.Show(this, L.F("Copia completata e verificata: {0} file, {1}. Simpler ora usa\n{2}\n\nLa vecchia cartella\n{3}\nnon serve più. Vuoi che Simpler la elimini adesso?\n\nSì: la elimina subito.\nNo: la lascio dov'è, così puoi controllare che la nuova copia funzioni e cancellarla tu.",
                                                 files, Size(bytes), target, old),
                                       "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question);
                    if (del == MessageBoxResult.Yes && await Post("paths/deleteold", new { path = old }) != null)
                    {
                        var r2 = JobDialog.Run(this, _mw, L.T("Eliminazione della vecchia cartella"), old);
                        if ((string?)r2?["state"] != "done")
                            Msg.Show(this, L.F("La vecchia cartella non è stata eliminata del tutto: {0}", (string?)r2?["error"] ?? ""), "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning);
                    }
                    return;
                }
                await Switch(key, target, false);
            }

            async Task<bool> Switch(string key, string path, bool follow)
            {
                var r = await Post("paths/set", new { key, path, follow });
                if (r == null) return false;
                Changed = true;
                Fill(r);
                return true;
            }
        }

        /// <summary>Progress of a long folder job in the engine (copy or delete): bar, file count, size, current file,
        /// Annulla. Returns the last status.</summary>
        sealed class JobDialog : ThemedDialog
        {
            readonly MainWindow _mw;
            readonly ProgressBar _bar;
            readonly TextBlock _count, _file;
            JsonObject? _last;
            bool _cancelAsked;

            public static JsonObject? Run(Window owner, MainWindow mw, string title, string subtitle)
            {
                var d = new JobDialog(mw, title, subtitle) { Owner = owner };
                d.ShowDialog();
                return d._last;
            }

            JobDialog(MainWindow mw, string title, string subtitle) : base(title, 560)
            {
                _mw = mw;
                Body.Children.Add(Theme.Label(title, 16, Theme.Text, FontWeights.SemiBold));
                var sub = Theme.Label(subtitle, 11.5, Theme.TextMuted);
                sub.TextWrapping = TextWrapping.Wrap;
                sub.Margin = new Thickness(0, 6, 0, 12);
                Body.Children.Add(sub);
                _bar = new ProgressBar { Height = 8, Minimum = 0, Maximum = 1, Value = 0, Foreground = Theme.B(Theme.Accent), Background = Theme.B("#1A2842"), BorderThickness = new Thickness(0) };
                Body.Children.Add(_bar);
                _count = Theme.Label("", 12, Theme.TextSoft);
                _count.Margin = new Thickness(0, 8, 0, 2);
                Body.Children.Add(_count);
                _file = Theme.Label("", 11, Theme.TextFaint);
                _file.TextTrimming = TextTrimming.CharacterEllipsis;
                Body.Children.Add(_file);
                var cancel = Theme.Button(L.T("Annulla"), Theme.Kind.Normal);
                cancel.HorizontalAlignment = HorizontalAlignment.Right;
                cancel.Margin = new Thickness(0, 14, 0, 0);
                cancel.Click += async (_, __) => await Cancel();
                Body.Children.Add(cancel);
                Loaded += async (_, __) => await Poll();
                Closing += (_, e) => { if ((string?)_last?["state"] == "running") { e.Cancel = true; _ = Cancel(); } };
            }

            async Task Cancel()
            {
                if (_cancelAsked || _mw._api == null) return;
                _cancelAsked = true;
                _count.Text = L.T("Annullamento…");
                try { await _mw._api.Post("paths/cancel", new { }); } catch { }
            }

            async Task Poll()
            {
                while (true)
                {
                    try { if (_mw._api != null) _last = await _mw._api.Get("paths/status"); } catch { }
                    var st = (string?)_last?["state"] ?? "error";
                    double done = (double?)_last?["done"] ?? 0, total = (double?)_last?["total"] ?? 0;
                    double b = (double?)_last?["bytes"] ?? 0, tb = (double?)_last?["totalBytes"] ?? 0;
                    _bar.Value = tb > 0 ? b / tb : total > 0 ? done / total : 0;
                    if (!_cancelAsked)
                        _count.Text = tb > 0 ? L.F("{0} di {1} file · {2} di {3}", done, total, FoldersDialog_Size(b), FoldersDialog_Size(tb))
                                             : L.F("{0} di {1} file", done, total);
                    _file.Text = (string?)_last?["current"] ?? "";
                    if (st != "running") break;
                    await Task.Delay(250);
                }
                Close();
            }

            static string FoldersDialog_Size(double b) => b >= 1e9 ? L.F("{0} GB", (b / 1e9).ToString("0.0")) : b >= 1e6 ? L.F("{0} MB", (b / 1e6).ToString("0")) : L.F("{0} KB", Math.Max(1, b / 1e3).ToString("0"));
        }
    }
}
