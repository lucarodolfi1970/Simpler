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
using System.Windows.Media.Effects;
using System.Windows.Media.Imaging;

namespace Simpler
{
    /// <summary>(1.78.4) Packs of models (PackInstaller): «Installa un pacchetto Simpler…» opens the pack in a window as
    /// large as its cover (16:9) with the title and the description over the picture; the licence to accept, where it
    /// goes, then the models in the Simpler parts of the library. (1.79.0) «Pacchetti…»: MainWindow.PackStore.cs.</summary>
    public sealed partial class MainWindow
    {
        string _packLibraryDir = "";

        async Task<PackInstaller?> PackInstallerNow(bool quiet = false)
        {
            if (_api == null) return null;
            // (Luca: «questa resta valida anche con i package?») asked every time: the folder of the library can be
            // moved in Cartelle while Simpler runs, and the packs (their models and packs\installed.json) move with it
            _packLibraryDir = "";
            {
                try
                {
                    var p = await _api.Get("paths");
                    _packLibraryDir = (p["folders"] as JsonArray)?.OfType<JsonObject>().Where(f => (string?)f["key"] == "models")
                                      .Select(f => (string?)f["path"] ?? "").FirstOrDefault() ?? "";
                }
                catch { }
            }
            if (_packLibraryDir == "" || !Directory.Exists(_packLibraryDir)) { if (!quiet) Status(L.T("Cartella della libreria dei modelli non trovata"), true); return null; }
            return new PackInstaller(_packLibraryDir, _vegRoot, PackKeysTrusted());
        }

        /// <summary>The official keys; on the computer of the author, while the Simpler folders are still open
        /// (SimplerLocked 0), also the key of his own pack tool.</summary>
        IEnumerable<string> PackKeysTrusted()
        {
            foreach (var k in PackInstaller.OfficialKeys) yield return k;
            if (_settings.SimplerLocked == 0)
            {
                var f = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Simpler", "packstudio-public.txt");
                string k = "";
                try { if (File.Exists(f)) k = File.ReadAllText(f).Trim(); } catch { }
                if (k != "") yield return k;
            }
        }

        async Task InstallPackAsk()
        {
            var d = new Microsoft.Win32.OpenFileDialog { Filter = L.T("Pacchetto Simpler") + "|*.simplerpack", Title = L.T("Installa un pacchetto Simpler") };
            if (d.ShowDialog(this) != true) return;
            await InstallPack(d.FileName);
        }

        async Task InstallPack(string file)
        {
            var pi = await PackInstallerNow();
            if (pi == null) return;
            var temp = Path.Combine(Path.GetTempPath(), "Simpler", "packs");
            var info = await Task.Run(() => pi.Inspect(file, temp));
            var w = new PackInstallWindow(this, pi, file, info) { Owner = this };
            w.ShowDialog();
            try { if (info.CoverFile != "" && File.Exists(info.CoverFile)) File.Delete(info.CoverFile); } catch { }
            if (w.Installed)
            {
                await ReloadModels();
                Status(L.F("Pacchetto «{0}» installato: {1} modelli", info.Title, info.Models));
            }
        }

        internal static ImageSource? PackPicture(string file, int width)
        {
            try
            {
                if (file == "" || !File.Exists(file)) return null;
                var bmp = new BitmapImage();
                bmp.BeginInit();
                bmp.UriSource = new Uri(file);
                bmp.CacheOption = BitmapCacheOption.OnLoad;
                bmp.DecodePixelWidth = width;
                bmp.EndInit();
                bmp.Freeze();
                return bmp;
            }
            catch { return null; }
        }

        internal static string PackSize(long b) => b >= 1L << 30 ? $"{b / 1073741824.0:0.0} GB" : $"{Math.Max(1, b / 1048576.0):0} MB";

        internal static string PackError(string e) => e switch
        {
            "signature" => L.T("La firma del pacchetto non è riconosciuta: non viene da una fonte ufficiale di Simpler, oppure è stato modificato."),
            "format" => L.T("Il pacchetto è scritto in un formato che questa versione di Simpler non conosce."),
            "not a Simpler pack" => L.T("Questo file non è un pacchetto Simpler."),
            "disk full" => L.T("Non c'è abbastanza spazio sul disco della libreria."),
            _ when e.StartsWith("changed ") || e.StartsWith("missing ") || e.StartsWith("unsigned ") || e.StartsWith("path ") =>
                L.T("Il pacchetto è danneggiato o è stato modificato dopo la firma: non è stato installato nulla."),
            _ => e,
        };

        internal static void ShowPackLicense(Window owner, string title, string text)
        {
            var d = new PackLicenseWindow(title, text) { Owner = owner };
            d.ShowDialog();
        }
    }

    sealed class PackLicenseWindow : ThemedDialog
    {
        public PackLicenseWindow(string title, string text) : base(L.T("Licenza") + " — " + title, 640)
        {
            Body.Children.Add(PackTextWindow.Box(text, true));
            var ok = Theme.Button(L.T("Chiudi"), Theme.Kind.Normal);
            ok.HorizontalAlignment = HorizontalAlignment.Right;
            ok.Margin = new Thickness(0, 12, 0, 0);
            ok.Click += (_, __) => Close();
            Body.Children.Add(ok);
        }
    }

    /// <summary>A text of a pack to read (its whole description).</summary>
    sealed class PackTextWindow : ThemedDialog
    {
        internal static TextBox Box(string text, bool mono) => new TextBox
        {
            Text = text, IsReadOnly = true, TextWrapping = TextWrapping.Wrap, VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
            Height = 420, FontFamily = mono ? Theme.Mono : Theme.Sans, FontSize = mono ? 11.5 : 13.5, Background = Theme.B(Theme.Inset),
            Foreground = Theme.B(Theme.TextSoft), BorderBrush = Theme.B(Theme.Line), Padding = new Thickness(12),
        };

        public PackTextWindow(string title, string text, bool mono) : base(title, 640)
        {
            Body.Children.Add(Box(text, mono));
            var ok = Theme.Button(L.T("Chiudi"), Theme.Kind.Normal);
            ok.HorizontalAlignment = HorizontalAlignment.Right;
            ok.Margin = new Thickness(0, 12, 0, 0);
            ok.Click += (_, __) => Close();
            Body.Children.Add(ok);
        }
    }

    /// <summary>The pack as its cover: 16:9, the title and the description over the picture with a soft shadow, the
    /// facts, the licence and «Installa» on a dark band below. Checked again (every file) while installing.</summary>
    sealed class PackInstallWindow : Window
    {
        public bool Installed { get; private set; }
        /// <summary>Only to look at it (the pack tool shows how the pack will look in Simpler): nothing installs.</summary>
        public bool Preview { get; init; }
        bool _more;
        readonly MainWindow _mw;
        readonly PackInstaller? _pi;
        readonly string _file;
        readonly PackInstaller.Info _info;
        bool _accepted, _busy;
        CancellationTokenSource? _cancel;
        readonly StackPanel _actions = new() { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Center };
        readonly TextBlock _state = new() { FontSize = 12.5, Foreground = Theme.B(Theme.Warm), VerticalAlignment = VerticalAlignment.Center, TextWrapping = TextWrapping.Wrap };
        readonly Border _track = new() { Height = 3, Background = Theme.B("#33FFFFFF"), CornerRadius = new CornerRadius(2), Visibility = Visibility.Collapsed, Margin = new Thickness(0, 6, 0, 0) };
        readonly Border _fill = new() { Height = 3, Background = Theme.B(Theme.Warm), CornerRadius = new CornerRadius(2), HorizontalAlignment = HorizontalAlignment.Left, Width = 0 };

        static readonly Effect Shadow = new DropShadowEffect { BlurRadius = 14, ShadowDepth = 1.5, Opacity = 0.75, Color = Colors.Black, Direction = 270 };

        public PackInstallWindow(MainWindow mw, PackInstaller? pi, string file, PackInstaller.Info info)
        {
            _mw = mw; _pi = pi; _file = file; _info = info;
            WindowStyle = WindowStyle.None;
            ResizeMode = ResizeMode.NoResize;
            ShowInTaskbar = false;
            WindowStartupLocation = WindowStartupLocation.CenterOwner;
            var w = Math.Min(1040, SystemParameters.WorkArea.Width * 0.62);
            Width = w;
            Height = w * 9 / 16;
            Background = Theme.B(Theme.Ground);
            FontFamily = Theme.Sans;
            UseLayoutRounding = true;
            Title = info.Ok ? info.Title : L.T("Pacchetto Simpler");
            KeyDown += (_, e) => { if (e.Key == Key.Escape && !_busy) Close(); };
            Closing += (_, e) => { if (_busy) e.Cancel = true; };

            var grid = new Grid { ClipToBounds = true };
            var pic = MainWindow.PackPicture(info.CoverFile, (int)(w * 1.5));
            if (pic != null) grid.Children.Add(new Image { Source = pic, Stretch = Stretch.UniformToFill });
            // the shade behind the words: from the top, and from the bottom for the band
            grid.Children.Add(new Border
            {
                Height = Height * 0.48, VerticalAlignment = VerticalAlignment.Top, IsHitTestVisible = false,
                Background = new LinearGradientBrush(Color.FromArgb(200, 4, 8, 18), Color.FromArgb(0, 4, 8, 18), 90),
            });
            grid.Children.Add(new Border
            {
                Height = Height * 0.42, VerticalAlignment = VerticalAlignment.Bottom, IsHitTestVisible = false,
                Background = new LinearGradientBrush(Color.FromArgb(0, 4, 8, 18), Color.FromArgb(235, 4, 8, 18), 90),
            });

            // over the picture: the brand, the title, the description
            var top = new StackPanel { Margin = new Thickness(34, 26, 70, 0), VerticalAlignment = VerticalAlignment.Top };
            var brand = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 0, 0, 8), Effect = Shadow };
            var logo = new Grid { Width = 16, Height = 16 };
            logo.Children.Add(new System.Windows.Shapes.Ellipse { Stroke = Theme.B(Theme.Accent), StrokeThickness = 1.7 });
            logo.Children.Add(new System.Windows.Shapes.Ellipse { Fill = Theme.B(Theme.Warm), Width = 6, Height = 6 });
            brand.Children.Add(logo);
            brand.Children.Add(new TextBlock { Text = "SIMPLER PACK", FontSize = 11.5, FontWeight = FontWeights.SemiBold, Foreground = Theme.B("#BFD9FF"), Margin = new Thickness(8, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center });
            top.Children.Add(brand);
            top.Children.Add(new TextBlock
            {
                Text = info.Ok ? info.Title : L.T("Pacchetto non valido"), FontSize = 34, FontWeight = FontWeights.SemiBold, Foreground = Brushes.White,
                TextWrapping = TextWrapping.Wrap, Effect = Shadow,
            });
            // over the picture only the opening of the description (its first paragraph, four lines at most): a long text
            // would cover the cover; all of it with «Leggi tutto»
            var paras = info.Description.Replace("\r", "").Split("\n\n", StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
            var lead = paras.FirstOrDefault() ?? "";
            _more = paras.Length > 1 || lead.Length > 320;
            if (info.Ok && lead != "")
                top.Children.Add(new TextBlock
                {
                    Text = lead, FontSize = 14.5, Foreground = Theme.B("#EAF0FA"), TextWrapping = TextWrapping.Wrap, MaxWidth = w * 0.62,
                    HorizontalAlignment = HorizontalAlignment.Left, Margin = new Thickness(0, 8, 0, 0), Effect = Shadow, LineHeight = 21,
                    LineStackingStrategy = LineStackingStrategy.BlockLineHeight, MaxHeight = 21 * 4, TextTrimming = TextTrimming.WordEllipsis,
                });
            grid.Children.Add(top);

            // close, top right
            var close = new Button
            {
                Content = Theme.Icon(Icons.Close, Colors.White, 14), Width = 32, Height = 32, HorizontalAlignment = HorizontalAlignment.Right,
                VerticalAlignment = VerticalAlignment.Top, Margin = new Thickness(0, 12, 12, 0), ToolTip = L.T("Chiudi"), Cursor = Cursors.Hand,
            };
            Theme.Style(close, Theme.Kind.Ghost);
            close.Click += (_, __) => { if (!_busy) Close(); };
            grid.Children.Add(close);

            // the band below: the facts, the licence, the buttons
            var band = new Grid { VerticalAlignment = VerticalAlignment.Bottom, Margin = new Thickness(34, 0, 26, 22) };
            band.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            band.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var left = new StackPanel { VerticalAlignment = VerticalAlignment.Bottom };
            if (info.Ok)
            {
                var facts = new WrapPanel { Margin = new Thickness(0, 0, 0, 10) };
                void Fact(Geometry icon, string text)
                {
                    var sp = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 0, 18, 4) };
                    sp.Children.Add(Theme.Icon(icon, Theme.Warm, 14));
                    sp.Children.Add(new TextBlock { Text = text, FontSize = 12.5, Foreground = Theme.B("#E4EAF4"), Margin = new Thickness(7, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center });
                    facts.Children.Add(sp);
                }
                Fact(Icons.Mesh, L.F("{0} modelli", info.Models));
                Fact(Icons.Drive, MainWindow.PackSize(info.Bytes));
                Fact(Icons.Layers, L.F("Versione {0}", info.Version) + (info.Author != "" ? " · " + info.Author : ""));
                if (info.InstalledVersion != null) Fact(Icons.Clock, L.F("Installata: {0}", info.InstalledVersion));
                left.Children.Add(facts);
                var row = new StackPanel { Orientation = Orientation.Horizontal };
                var accept = new Toggle(L.T("Accetto la licenza"), false) { Margin = new Thickness(0), MinWidth = 170 };
                accept.Toggled += on => { _accepted = on; RenderActions(); };
                row.Children.Add(accept);
                var read = new TextBlock { Text = L.T("Leggi la licenza") + (info.License.Trim() != "" ? " (" + info.License.Trim() + ")" : ""), FontSize = 12, Foreground = Theme.B("#9CC7FF"), Cursor = Cursors.Hand, Margin = new Thickness(16, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center, TextDecorations = TextDecorations.Underline };
                read.MouseLeftButtonUp += (_, __) => MainWindow.ShowPackLicense(this, info.Title, info.LicenseText);
                row.Children.Add(read);
                var where = new TextBlock { Text = L.T("Dove va"), FontSize = 12, Foreground = Theme.B("#9CC7FF"), Cursor = Cursors.Hand, Margin = new Thickness(16, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center, TextDecorations = TextDecorations.Underline };
                where.MouseLeftButtonUp += (_, __) =>
                {
                    var m = new ContextMenu { PlacementTarget = where, Placement = System.Windows.Controls.Primitives.PlacementMode.Top };
                    foreach (var f in info.Folders) m.Items.Add(new MenuItem { Header = f.Replace("/", "  ▸  "), IsEnabled = false });
                    m.IsOpen = true;
                };
                row.Children.Add(where);
                if (_more)
                {
                    var all = new TextBlock { Text = L.T("Leggi tutto"), FontSize = 12, Foreground = Theme.B("#9CC7FF"), Cursor = Cursors.Hand, Margin = new Thickness(16, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center, TextDecorations = TextDecorations.Underline };
                    all.MouseLeftButtonUp += (_, __) => new PackTextWindow(info.Title, info.Description, false) { Owner = this }.ShowDialog();
                    row.Children.Insert(1, all);
                }
                left.Children.Add(row);
            }
            else _state.Text = MainWindow.PackError(info.Error);
            _state.Margin = new Thickness(0, 8, 0, 0);
            left.Children.Add(_state);
            _track.Child = _fill;
            left.Children.Add(_track);
            band.Children.Add(left);
            Grid.SetColumn(_actions, 1);
            band.Children.Add(_actions);
            grid.Children.Add(band);
            grid.Children.Add(new Border { BorderBrush = Theme.B(Theme.LineStrong), BorderThickness = new Thickness(1), IsHitTestVisible = false });
            // the window is moved by dragging the picture - not the band below: DragMove takes the mouse, and the switch
            // of the licence and the links (they act when the button goes up) got no click at all (Luca)
            grid.MouseLeftButtonDown += (_, e) =>
            {
                for (var d = e.OriginalSource as DependencyObject; d != null;
                     d = d is Visual or System.Windows.Media.Media3D.Visual3D ? VisualTreeHelper.GetParent(d) : LogicalTreeHelper.GetParent(d))
                    if (d == band || d is System.Windows.Controls.Primitives.ButtonBase) return;
                if (e.ButtonState == MouseButtonState.Pressed) try { DragMove(); } catch { }
            };
            Content = grid;
            RenderActions();
        }

        string InstallLabel()
        {
            if (_info.InstalledVersion == null) return L.T("Installa");
            var c = CompareVersions(_info.Version, _info.InstalledVersion);
            return c > 0 ? L.F("Aggiorna alla {0}", _info.Version) : c < 0 ? L.F("Torna alla {0}", _info.Version) : L.T("Reinstalla");
        }

        internal static int CompareVersions(string a, string b)
        {
            int[] P(string v) => v.Split('.').Select(x => int.TryParse(x, out var n) ? n : 0).ToArray();
            var x = P(a); var y = P(b);
            for (int i = 0; i < Math.Max(x.Length, y.Length); i++)
            {
                var d = (i < x.Length ? x[i] : 0) - (i < y.Length ? y[i] : 0);
                if (d != 0) return Math.Sign(d);
            }
            return 0;
        }

        void RenderActions()
        {
            _actions.Children.Clear();
            if (_busy)
            {
                var stop = Theme.Button(L.T("Interrompi"), Theme.Kind.Normal);
                stop.Click += (_, __) => _cancel?.Cancel();
                _actions.Children.Add(stop);
                return;
            }
            var cancel = Theme.Button(L.T(Installed ? "Chiudi" : "Annulla"), Theme.Kind.Ghost);
            cancel.Click += (_, __) => Close();
            _actions.Children.Add(cancel);
            if (!_info.Ok || Installed) return;
            var go = Theme.Button(Theme.IconText(Icons.Import, InstallLabel()), Theme.Kind.Primary);
            go.Margin = new Thickness(8, 0, 0, 0);
            go.IsEnabled = _accepted && !Preview;
            go.ToolTip = _accepted ? null : L.T("Accetta la licenza per installare");
            go.Click += async (_, __) => await Run();
            _actions.Children.Add(go);
        }

        async Task Run()
        {
            if (Preview) return;
            if (_info.InstalledVersion != null && CompareVersions(_info.Version, _info.InstalledVersion) < 0 &&
                Msg.Show(this, L.F("È installata la versione {0}, più recente di questa ({1}). Tornare alla {1}?", _info.InstalledVersion, _info.Version),
                         "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
            _busy = true;
            _cancel = new CancellationTokenSource();
            _track.Visibility = Visibility.Visible;
            _state.Foreground = Theme.B(Theme.Warm);
            RenderActions();
            Cursor = Cursors.AppStarting;          // (this window works, Simpler can be used meanwhile)
            try
            {
                var ct = _cancel.Token;
                // (by model, not by file: a model is several files)
                var order = (_info.Manifest["models"] as JsonArray)?.OfType<JsonObject>().Select(x => (string?)x["id"] ?? "").ToList() ?? new List<string>();
                await Task.Run(() => _pi!.Install(_file, (i, n, name) => Dispatcher.BeginInvoke(() =>
                {
                    var parts = name.Split('/');
                    var k = parts.Length >= 2 && parts[0] == "models" ? order.IndexOf(Path.GetFileNameWithoutExtension(parts[1])) : -1;
                    _state.Text = L.T("Occupato · attendi") + " — " + (k >= 0 ? L.F("verifica e installazione: modello {0} di {1}", k + 1, order.Count) : L.T("verifica del pacchetto"));
                    _fill.Width = _track.ActualWidth * (n == 0 ? 0 : (double)i / n);
                }), ct), ct);
                Installed = true;
                _state.Text = L.F("Installato: {0} modelli nella libreria, in Simpler", _info.Models);
                _state.Foreground = Theme.B(Theme.Teal);
            }
            catch (OperationCanceledException) { _state.Text = L.T("Interrotto: non è stato installato nulla"); }
            catch (Exception ex) { _state.Text = MainWindow.PackError(ex.Message); _state.Foreground = Theme.B(Theme.Danger); }
            finally
            {
                _busy = false;
                _track.Visibility = Visibility.Collapsed;
                Cursor = null;
                RenderActions();
            }
        }
    }
}
