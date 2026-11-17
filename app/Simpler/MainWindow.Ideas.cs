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
        static SitePage RoadmapPage => new(L.Lang == "en" ? "https://www.rodluc.com/simpler/en/roadmap.html" : "https://www.rodluc.com/simpler/it/roadmap.html",
            L.Lang == "en" ? "/simpler/en/" : "/simpler/it/", "Roadmap di Simpler", RoadmapIcon, "Apro la roadmap…",
            "Roadmap: «Torna alla scena» la chiude", "Chiude la roadmap e torna alla vista con la scena",
            "La roadmap non è raggiungibile ora", "roadmap", Array.Empty<string>());

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

        void CloseIdeas()
        {
            if (_ideasPanel == null) return;
            _viewport.Children.Remove(_ideasPanel);
            try { _ideasWeb?.Dispose(); } catch { }
            _ideasPanel = null; _ideasWeb = null;
            if (_web != null && _busy.Visibility != Visibility.Visible) _web.Visibility = Visibility.Visible;
            AppLog.Write("site page: closed");
        }
    }
}
