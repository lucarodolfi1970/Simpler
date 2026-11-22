using System;
using System.Net.Http;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.Wpf;

namespace Simpler
{
    /// <summary>
    /// (1.78.4, Luca) «Suggerisci un'idea»: next to the example scene, a tile that opens the ideas page of rodluc.com in
    /// the space of the 3D view, with «× Torna alla scena». Only that page is shown inside; any other address opens in
    /// the browser (only https on rodluc.com / github.com). If the site cannot be reached: one plain message, the view
    /// with the scene stays as it was - never an error.
    /// </summary>
    public sealed partial class MainWindow
    {
        const string IdeasUrl = "https://www.rodluc.com/simpler/ideas/index.php";
        static readonly HttpClient IdeasHttp = new HttpClient { Timeout = TimeSpan.FromSeconds(6) };
        static readonly Geometry BulbIcon = Geometry.Parse("M9 18h6 M10 21h4 M12 3a6 6 0 0 0-3.6 10.8c.7.6 1.1 1.3 1.1 2.1V16h5v-.1c0-.8.4-1.5 1.1-2.1A6 6 0 0 0 12 3z");
        Grid? _ideasPanel;
        WebView2? _ideasWeb;
        bool _ideasOpening;

        /// <summary>A page of rodluc.com shown in the space of the view: where it lives (only that folder inside), its bar,
        /// its texts, and the other sites its links may open in the browser (https only).</summary>
        sealed record SitePage(string Url, string Folder, string Title, Geometry Icon, string Opening, string Opened, string Back,
                               string Unreachable, string Log, string[] Hosts);

        static readonly SitePage IdeasPage = new(IdeasUrl, "/simpler/ideas/", "Idee per Simpler", BulbIcon, "Apro la pagina delle idee…",
            "Pagina delle idee: «Torna alla scena» la chiude", "Chiude la pagina delle idee e torna alla vista con la scena",
            "Il sito delle idee non è raggiungibile ora", "ideas", Array.Empty<string>());

        // (Luca: «una miniatura con modelli e vegetazioni gratuiti … una pagina web sopra la viewport con link e info … poi
        // ci penserà l'utente a recuperarli per i fatti propri») where to find free models: the links open in the browser
        const string FreeUrl = "https://www.rodluc.com/simpler/free/index.php";
        static readonly Geometry TreeIcon = Geometry.Parse("M12 2l5 7h-3l4 6h-4l3 5H7l3-5H6l4-6H7z M12 20v2");
        static readonly SitePage FreePage = new(FreeUrl, "/simpler/free/", "Modelli e vegetazione gratuiti", TreeIcon, "Apro la pagina dei modelli gratuiti…",
            "Modelli gratuiti: i collegamenti si aprono nel browser · «Torna alla scena» chiude la pagina",
            "Chiude la pagina dei modelli gratuiti e torna alla vista con la scena",
            "La pagina dei modelli gratuiti non è raggiungibile ora", "free models",
            // (Luca, 13/11: «una pagina che elenca i vari siti dove prendere modelli come megascan sketchfab e altri») every
            // website the page lists (server/free/index.php) must be here, or its link does not open
            new[] { "maxtree.org", "www.maxtree.org", "www.bentley.com", "bentley.com", "polyhaven.com", "www.polyhaven.com",
                    "fab.com", "www.fab.com", "sketchfab.com", "www.sketchfab.com", "blenderkit.com", "www.blenderkit.com",
                    "cgtrader.com", "www.cgtrader.com", "3d.si.edu", "science.nasa.gov" });

        // (Luca, 13/11: «un tasto Roadmap prima di free model che punta a … en/roadmap.html … oppure … it/roadmap.html se
        // italiano») the roadmap of the website in the language of Simpler, in the space of the view like the others
        static readonly Geometry RoadmapIcon = Geometry.Parse("M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3z M9 3v15 M15 6v15");
        // (Luca, 19/11: «una versione identica … senza nessun link: l'utente deve accedere solo alla roadmap») the copy of the site's
        // roadmap made for Simpler by tools/make_inapp_roadmap.py: no menu, no links; the folder /simpler/inapp/ holds only these pages
        static SitePage RoadmapPage => new("https://www.rodluc.com/simpler/inapp/roadmap-" + (L.Lang == "en" ? "en" : "it") + ".html",
            "/simpler/inapp/", "Roadmap di Simpler", RoadmapIcon, "Apro la roadmap…",
            "Roadmap: «Torna alla scena» la chiude", "Chiude la roadmap e torna alla vista con la scena",
            "La roadmap non è raggiungibile ora", "roadmap", Array.Empty<string>());

        // (21/11) the video tutorials of the website in the language of Simpler, in the space of the view like the roadmap
        // (same folder /simpler/inapp/). The videos are on rodluc.com and play in the page; the full screen button of a
        // video takes the whole screen (SiteFullScreen)
        static readonly Geometry PlayIcon = Geometry.Parse("M4 5h16v12H4z M10 8.5l5 2.5-5 2.5z M8 20h8");
        static SitePage TutorialsPage => new("https://www.rodluc.com/simpler/inapp/tutorials-" + (L.Lang == "en" ? "en" : "it") + ".html",
            "/simpler/inapp/", "Video tutorial", PlayIcon, "Apro i video tutorial…",
            "Video tutorial: i video si guardano qui, anche a tutto schermo · «Torna alla scena» chiude la pagina",
            "Chiude i video tutorial e torna alla vista con la scena",
            "La pagina dei video tutorial non è raggiungibile ora", "tutorials",
            new[] { "www.youtube.com", "youtube.com", "youtu.be", "m.youtube.com", "www.youtube-nocookie.com", "vimeo.com", "www.vimeo.com", "player.vimeo.com" });

        FrameworkElement TutorialsTile() => SiteTile(TutorialsPage, L.T("Video tutorial"), new LinearGradientBrush(Theme.C("#1D3766"), Theme.C("#3A2A12"), 35), "tutorials.jpg",
            L.T("I video tutorial di Simpler, sul sito di Simpler. La pagina si apre qui, nello spazio della vista, e i video si guardano qui, anche a tutto schermo: «Torna alla scena» la chiude"));

        FrameworkElement IdeasTile() => SiteTile(IdeasPage, L.T("Suggerisci un'idea"), new LinearGradientBrush(Theme.C("#1D3766"), Theme.C("#3A2A12"), 35), "idea.jpg",
            L.T("Proponi una funzione o un miglioramento per Simpler e guarda a che punto sono le idee. La pagina si apre qui, nello spazio della vista: «Torna alla scena» la chiude. Al sito arrivano la versione, la lingua e ciò che scrivi nel modulo"));

        FrameworkElement RoadmapTile() => SiteTile(RoadmapPage, L.T("Roadmap"), new LinearGradientBrush(Theme.C("#1D3766"), Theme.C("#2E1F4D"), 35), "roadmap.jpg",
            L.T("Cosa è arrivato in Simpler e cosa arriverà, sul sito di Simpler. La pagina si apre qui, nello spazio della vista: «Torna alla scena» la chiude"));

        FrameworkElement FreeTile() => SiteTile(FreePage, L.T("Modelli gratuiti"), new LinearGradientBrush(Theme.C("#1D3766"), Theme.C("#173A26"), 35), "free.jpg",
            L.T("Dove trovare modelli 3D e vegetazione gratuiti da scaricare e importare in Simpler. La pagina si apre qui, nello spazio della vista; i collegamenti si aprono nel browser: «Torna alla scena» la chiude"));

        /// <summary>The picture of a tile of the start box (tiles\<name> next to the exe, 16:9, like the examples); null when it is not there.</summary>
        static System.Windows.Media.Imaging.BitmapImage? TilePicture(string name)
        {
            try
            {
                var f = System.IO.Path.Combine(AppContext.BaseDirectory, "tiles", name);
                if (!System.IO.File.Exists(f)) return null;
                var bmp = new System.Windows.Media.Imaging.BitmapImage();
                bmp.BeginInit(); bmp.CacheOption = System.Windows.Media.Imaging.BitmapCacheOption.OnLoad; bmp.DecodePixelWidth = 300;
                bmp.UriSource = new Uri(f); bmp.EndInit(); bmp.Freeze();
                return bmp;
            }
            catch { return null; }
        }

        FrameworkElement SiteTile(SitePage page, string caption, Brush back, string picture, string tip)
        {
            // (Luca, 14/11: «usa queste immagini come miniature») the picture; without the file the old gradient with the icon
            var img = TilePicture(picture);
            var pic = new Border
            {
                Width = 128, Height = 72, CornerRadius = new CornerRadius(6), BorderThickness = new Thickness(1), BorderBrush = Theme.B(Theme.Line),
                Background = img != null ? new ImageBrush(img) { Stretch = Stretch.UniformToFill } : back,
            };
            if (img == null)
            {
                pic.Child = Theme.Icon(page.Icon, Theme.Warm, 30, 1.6);
                ((FrameworkElement)pic.Child).HorizontalAlignment = HorizontalAlignment.Center;
                ((FrameworkElement)pic.Child).VerticalAlignment = VerticalAlignment.Center;
            }
            var cap = new TextBlock { Text = caption, FontSize = 11.5, Foreground = Theme.B(Theme.TextSoft),
                                      Margin = new Thickness(0, 4, 0, 0), HorizontalAlignment = HorizontalAlignment.Center };
            var tile = new StackPanel { Margin = new Thickness(14, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center, Cursor = System.Windows.Input.Cursors.Hand,
                                        Background = Brushes.Transparent,
                                        ToolTip = tip };
            tile.Children.Add(pic);
            tile.Children.Add(cap);
            tile.MouseEnter += (_, __) => pic.BorderBrush = Theme.B(Theme.Accent);
            tile.MouseLeave += (_, __) => pic.BorderBrush = Theme.B(Theme.Line);
            tile.MouseLeftButtonUp += async (_, e) => { e.Handled = true; await OpenSitePage(page); };
            return tile;
        }

        static string PageStart(SitePage page) => $"{page.Url}?lang={(L.Lang == "en" ? "en" : "it")}&v={Uri.EscapeDataString(SettingsDialog.Version)}";

        static bool IdeasInside(Uri? u, SitePage page)
            => u != null && u.Scheme == Uri.UriSchemeHttps && u.Host.ToLowerInvariant() is "www.rodluc.com" or "rodluc.com"
               && u.AbsolutePath.StartsWith(page.Folder, StringComparison.OrdinalIgnoreCase);

        /// <summary>A link of the page to another site: in the browser, only https on rodluc.com / github.com or on the
        /// sites the page names (default port).</summary>
        static void OpenOutside(string url, SitePage page)
        {
            if (UpdateCheck.SafeUrl(url)) { UpdateCheck.Open(url); return; }
            if (!Uri.TryCreate(url, UriKind.Absolute, out var u) || u.Scheme != Uri.UriSchemeHttps || !u.IsDefaultPort
                || Array.IndexOf(page.Hosts, u.Host.ToLowerInvariant()) < 0) return;
            try { System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(u.AbsoluteUri) { UseShellExecute = true }); } catch { }
        }

        void IdeasUnreachable(SitePage page)
        {
            CloseIdeas();
            Status(L.T(page.Unreachable));
            Msg.Show(this, L.T(page.Unreachable) + ". " + L.T("Riprova più tardi."), "Simpler", MessageBoxButton.OK, MessageBoxImage.Information);
        }

        async Task OpenSitePage(SitePage page)
        {
            if (_ideasOpening || _webEnv == null) return;
            // (Luca: «se clicco roadmap non vedo nulla» with the free models open) another page of the site replaces the open one
            if (_ideasPanel != null)
            {
                if (_ideasPageLog == page.Log) return;
                CloseIdeas();
            }
            _ideasPageLog = page.Log;
            _ideasOpening = true;
            Status(L.T(page.Opening));
            try
            {
                // first a quick look: if the site does not answer, nothing changes in the view
                bool up;
                try { using var r = await IdeasHttp.GetAsync(PageStart(page), HttpCompletionOption.ResponseHeadersRead); up = r.IsSuccessStatusCode; }
                catch (Exception ex) { AppLog.Write(page.Log + ": site not reachable (" + ex.GetType().Name + ")"); up = false; }
                if (!up) { IdeasUnreachable(page); return; }

                var bar = new DockPanel { Background = Theme.B(Theme.Raised), Height = 38 };
                var back = Theme.Button(L.T("× Torna alla scena"), Theme.Kind.Primary, L.T(page.Back));
                back.Margin = new Thickness(8, 4, 8, 4);
                back.Padding = new Thickness(12, 0, 12, 0);
                back.Click += (_, __) => CloseIdeas();
                DockPanel.SetDock(back, Dock.Right);
                bar.Children.Add(back);
                var head = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(12, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center };
                head.Children.Add(Theme.Icon(page.Icon, Theme.Warm, 16));
                var t = Theme.Label(L.T(page.Title), 13, Theme.Text, FontWeights.SemiBold);
                t.Margin = new Thickness(8, 0, 0, 0);
                head.Children.Add(t);
                bar.Children.Add(head);

                var web = new WebView2 { DefaultBackgroundColor = System.Drawing.Color.FromArgb(255, 11, 19, 36) };
                var panel = new Grid { Background = Theme.B("#0B1324") };
                panel.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
                panel.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
                panel.Children.Add(bar);
                Grid.SetRow(web, 1);
                panel.Children.Add(web);
                _ideasPanel = panel; _ideasWeb = web;
                _viewport.Children.Add(panel);
                if (_web != null) _web.Visibility = Visibility.Hidden;      // (WPF and two web views do not overlap well: the scene view waits hidden)

                await web.EnsureCoreWebView2Async(_webEnv);
                var core = web.CoreWebView2;
                core.Settings.IsStatusBarEnabled = false;
                core.Settings.AreDevToolsEnabled = false;
                core.Settings.IsZoomControlEnabled = false;
                // (21/11) a video of the page asked for the whole screen (its own button, or a double click): the page takes
                // the whole screen, Esc or the same button gives it back
                core.ContainsFullScreenElementChanged += (_, __) => { if (_ideasWeb == web) SiteFullScreen(core.ContainsFullScreenElement, bar); };
                core.NavigationStarting += (_, e) =>
                {
                    if (Uri.TryCreate(e.Uri, UriKind.Absolute, out var u) && IdeasInside(u, page)) return;
                    e.Cancel = true;
                    OpenOutside(e.Uri, page);           // (only https on rodluc.com / github.com or the page's sites, in the browser)
                };
                core.NewWindowRequested += (_, e) => { e.Handled = true; OpenOutside(e.Uri, page); };
                core.NavigationCompleted += (_, e) =>
                {
                    if (e.IsSuccess || _ideasWeb != web) return;
                    AppLog.Write(page.Log + ": page not loaded (" + e.WebErrorStatus + ")");
                    if (e.WebErrorStatus != CoreWebView2WebErrorStatus.OperationCanceled) Dispatcher.BeginInvoke(() => IdeasUnreachable(page));
                };
                core.Navigate(PageStart(page));
                Status(L.T(page.Opened));
                AppLog.Write(page.Log + ": opened");
            }
            catch (Exception ex)
            {
                AppLog.Write(page.Log + ": " + ex.Message);
                IdeasUnreachable(page);
            }
            finally { _ideasOpening = false; }
        }

        string _ideasPageLog = "";

        // ---------------------------------------------------------------- (21/11) a video of the page on the whole screen

        /// <summary>What was changed to give the whole screen to the page, to put it back.</summary>
        sealed class SiteFullState
        {
            public readonly System.Collections.Generic.List<(UIElement El, Visibility Was)> Hidden = new();
            public readonly System.Collections.Generic.List<(ColumnDefinition Col, GridLength Width, double Min)> Cols = new();
            public readonly System.Collections.Generic.List<(RowDefinition Row, GridLength Height, double Min)> Rows = new();
            public WindowStyle Style;
            public WindowState State;
            public ResizeMode Resize;
            public Rect Bounds;          // where the window is when not maximized
        }

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        static extern IntPtr MonitorFromWindow(IntPtr hwnd, uint flags);

        [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
        struct MonitorInfo { public int Size; public int L, T, R, B; public int WL, WT, WR, WB; public uint Flags; }

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        static extern bool GetMonitorInfo(IntPtr monitor, ref MonitorInfo info);

        /// <summary>The whole screen the window is on (taskbar included), in the units of WPF; null if Windows does not say.</summary>
        Rect? ScreenOfWindow()
        {
            try
            {
                var hwnd = new System.Windows.Interop.WindowInteropHelper(this).Handle;
                var mi = new MonitorInfo { Size = System.Runtime.InteropServices.Marshal.SizeOf<MonitorInfo>() };
                if (hwnd == IntPtr.Zero || !GetMonitorInfo(MonitorFromWindow(hwnd, 2), ref mi)) return null;
                var m = PresentationSource.FromVisual(this)?.CompositionTarget?.TransformFromDevice ?? Matrix.Identity;
                var a = m.Transform(new Point(mi.L, mi.T));
                var b = m.Transform(new Point(mi.R, mi.B));
                return b.X > a.X && b.Y > a.Y ? new Rect(a, b) : null;
            }
            catch { return null; }
        }

        SiteFullState? _siteFull;

        /// <summary>The page of the site on the whole screen (a video with its full screen button) and back. WebView2 by itself
        /// fills only its own control: here everything around it in the window is put aside - the bar of the page, the header,
        /// the side panels, the library - the window loses its border and covers the taskbar. All of it is put back as it was.</summary>
        void SiteFullScreen(bool on, UIElement? bar = null)
        {
            if (on == (_siteFull != null)) return;
            try
            {
                if (!on)
                {
                    var was = _siteFull!;
                    _siteFull = null;
                    foreach (var (col, width, min) in was.Cols) { col.Width = width; col.MinWidth = min; }
                    foreach (var (row, height, min) in was.Rows) { row.Height = height; row.MinHeight = min; }
                    foreach (var (el, vis) in was.Hidden) el.Visibility = vis;
                    WindowStyle = was.Style;
                    ResizeMode = was.Resize;
                    WindowState = WindowState.Normal;
                    if (!was.Bounds.IsEmpty && was.Bounds.Width > 0 && was.Bounds.Height > 0)
                    {
                        Left = was.Bounds.Left; Top = was.Bounds.Top; Width = was.Bounds.Width; Height = was.Bounds.Height;
                    }
                    WindowState = was.State;
                    AppLog.Write("site page: full screen off");
                    return;
                }
                if (_ideasPanel == null) return;
                var st = new SiteFullState { Style = WindowStyle, State = WindowState, Resize = ResizeMode,
                                             Bounds = WindowState == WindowState.Normal ? new Rect(Left, Top, Width, Height) : RestoreBounds };
                var clock = System.Diagnostics.Stopwatch.StartNew();
                void Hide(UIElement e)
                {
                    if (e.Visibility == Visibility.Collapsed) return;
                    st.Hidden.Add((e, e.Visibility));
                    e.Visibility = Visibility.Collapsed;
                }
                if (bar != null) Hide(bar);
                // up from the page to the window: at every panel on the way, whatever is beside the way is put aside
                DependencyObject child = _ideasPanel;
                var parent = VisualTreeHelper.GetParent(child);
                while (parent != null && !ReferenceEquals(parent, this))
                {
                    if (parent is Panel panel)
                    {
                        foreach (UIElement sib in panel.Children)
                            if (!ReferenceEquals(sib, child)) Hide(sib);
                        if (panel is Grid grid && child is UIElement ce)
                        {
                            int c0 = Grid.GetColumn(ce), c1 = c0 + Grid.GetColumnSpan(ce) - 1;
                            for (int i = 0; i < grid.ColumnDefinitions.Count; i++)
                            {
                                var col = grid.ColumnDefinitions[i];
                                st.Cols.Add((col, col.Width, col.MinWidth));
                                col.MinWidth = 0;
                                col.Width = i >= c0 && i <= c1 ? new GridLength(1, GridUnitType.Star) : new GridLength(0);
                            }
                            int r0 = Grid.GetRow(ce), r1 = r0 + Grid.GetRowSpan(ce) - 1;
                            for (int i = 0; i < grid.RowDefinitions.Count; i++)
                            {
                                var row = grid.RowDefinitions[i];
                                st.Rows.Add((row, row.Height, row.MinHeight));
                                row.MinHeight = 0;
                                row.Height = i >= r0 && i <= r1 ? new GridLength(1, GridUnitType.Star) : new GridLength(0);
                            }
                        }
                    }
                    child = parent;
                    parent = VisualTreeHelper.GetParent(parent);
                }
                _siteFull = st;
                WindowStyle = WindowStyle.None;
                ResizeMode = ResizeMode.NoResize;
                // (21/11, first try: the window went back to its normal size and was then maximized again - the video stayed
                // small in a corner for 2-3 s before taking the screen) now one step: the window, without border, placed
                // straight on the whole screen it is on
                if (ScreenOfWindow() is Rect screen)
                {
                    if (WindowState != WindowState.Normal) WindowState = WindowState.Normal;
                    Left = screen.Left; Top = screen.Top; Width = screen.Width; Height = screen.Height;
                }
                else
                {
                    WindowState = WindowState.Normal;
                    WindowState = WindowState.Maximized;
                }
                AppLog.Write($"site page: full screen on ({st.Hidden.Count} parts put aside) in {clock.ElapsedMilliseconds} ms");
                var webNow = _ideasWeb;
                Dispatcher.BeginInvoke(new Action(() =>
                    AppLog.Write($"site page: full screen drawn after {clock.ElapsedMilliseconds} ms, page {webNow?.ActualWidth:0}x{webNow?.ActualHeight:0}")),
                    System.Windows.Threading.DispatcherPriority.ContextIdle);
            }
            catch (Exception ex)
            {
                AppLog.Write("site page: full screen: " + ex.Message);
            }
        }

        void CloseIdeas()
        {
            if (_ideasPanel == null) return;
            SiteFullScreen(false);       // (the page closed while a video had the whole screen)
            _viewport.Children.Remove(_ideasPanel);
            try { _ideasWeb?.Dispose(); } catch { }
            _ideasPanel = null; _ideasWeb = null;
            if (_web != null && _busy.Visibility != Visibility.Visible) _web.Visibility = Visibility.Visible;
            AppLog.Write("site page: closed");
        }
    }
}
