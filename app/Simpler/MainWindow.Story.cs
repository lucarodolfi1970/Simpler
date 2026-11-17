using System;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;

namespace Simpler
{
    /// <summary>
    /// «La storia», the first menu of the library and what Simpler shows when it starts: a few lines on why Simpler
    /// exists (by Luca Rodolfi, from the story page of the site) and the address of the site, in Italian and English.
    /// </summary>
    public sealed partial class MainWindow
    {
        const string SiteUrl = "https://www.rodluc.com/simpler/en/";     // (1.78.4, Luca) the official site, in English

        Border? _storyBox;
        TextBlock? _storyBody, _storyFoot;

        // the width of the library area minus the margins (the tiles panel 10 + 10, the box 4 + 4)
        double StoryWidth() => Math.Max(300, (_libraryScroller.ActualWidth > 0 ? _libraryScroller.ActualWidth : 900) - 30);
        bool _storyHooked;

        void RenderStory()
        {
            // one box as wide as the library: an orange title, two short lines, the signature and the site
            var sp = new StackPanel();
            var head = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 0, 0, 6) };
            // the logo of Simpler, small, before the title (the largest picture of the icon file, drawn at 22 px)
            try
            {
                var ico = System.IO.Path.Combine(AppContext.BaseDirectory, "Simpler.ico");
                if (System.IO.File.Exists(ico))
                {
                    var dec = System.Windows.Media.Imaging.BitmapDecoder.Create(new Uri(ico), System.Windows.Media.Imaging.BitmapCreateOptions.None,
                                                                              System.Windows.Media.Imaging.BitmapCacheOption.OnLoad);
                    var best = dec.Frames.OrderByDescending(f => f.PixelWidth).First();
                    var img = new Image { Source = best, Width = 22, Height = 22, Margin = new Thickness(0, 0, 9, 0), VerticalAlignment = VerticalAlignment.Center };
                    RenderOptions.SetBitmapScalingMode(img, BitmapScalingMode.HighQuality);
                    head.Children.Add(img);
                }
            }
            catch { }
            var title = new TextBlock { Text = L.T("Blender, ma più semplice"), FontSize = 17, FontWeight = FontWeights.SemiBold,
                                        Foreground = new SolidColorBrush(AdvancedColor), VerticalAlignment = VerticalAlignment.Center };
            head.Children.Add(title);
            sp.Children.Add(head);
            var body = new TextBlock { TextWrapping = TextWrapping.Wrap, FontSize = 13, LineHeight = 19, Foreground = Theme.B(Theme.TextSoft) };
            body.Inlines.Add(new Run(L.T("Simpler nasce dalla passione per le immagini, non da un'azienda: la potenza di Blender e Cycles con un'interfaccia semplice e immediata, ispirata ai migliori programmi di visualizzazione in tempo reale. Gratuito, senza abbonamenti né registrazione.")));
            sp.Children.Add(body);
            _storyBody = body;
            var foot = new TextBlock { TextWrapping = TextWrapping.Wrap, FontSize = 12.5, Foreground = Theme.B(Theme.TextMuted), Margin = new Thickness(0, 8, 0, 0) };
            foot.Inlines.Add(new Italic(new Run("— Luca Rodolfi")) { Foreground = Theme.B(Theme.Text) });
            foot.Inlines.Add(new Run("  ·  " + L.T("Tutto su Simpler, in italiano e in inglese, sul") + " "));
            // (1.78.4, Luca: «non mettere l'url, scrivi nel link "sito ufficiale di Simpler"»)
            var link = new Hyperlink(new Run(L.T("sito ufficiale"))) { NavigateUri = new Uri(SiteUrl), Foreground = Theme.B(Theme.Accent), ToolTip = SiteUrl };
            link.RequestNavigate += (_, e) =>
            {
                try { System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(e.Uri.AbsoluteUri) { UseShellExecute = true }); } catch { }
                e.Handled = true;
            };
            foot.Inlines.Add(link);
            sp.Children.Add(foot);
            _storyFoot = foot;
            // (1.78.4, Luca) the text on the left, the example scene on the right: its picture opens it
            var row = new Grid();
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            row.Children.Add(sp);
            var tiles = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            // (1.78.5, Luca) «Example #1» (the shop) and «Example #2» (the bedroom), one after the other
            for (int i = 0; i < Samples.Length; i++)
                if (SampleTile(i) is FrameworkElement sample) tiles.Children.Add(sample);
            tiles.Children.Add(IdeasTile());                // (1.78.4, Luca) «Suggerisci un'idea»
            tiles.Children.Add(RoadmapTile());              // (Luca, 13/11) the roadmap of the website, in the language of Simpler
            tiles.Children.Add(FreeTile());                 // (Luca) where to find free models and vegetation
            Grid.SetColumn(tiles, 1);
            row.Children.Add(tiles);
            var box = new Border
            {
                Margin = new Thickness(4), Padding = new Thickness(18, 12, 18, 12), CornerRadius = new CornerRadius(8),
                Background = Theme.B(Theme.Raised), BorderBrush = Theme.B(Theme.Line), BorderThickness = new Thickness(1), Child = row,
            };
            // (the tiles of the library wrap sideways: the box takes the whole width the library shows - also when the
            // window or the sidebars change size, and at start, when the layout is not final yet)
            _storyBox = box;
            box.Width = StoryWidth();
            if (!_storyHooked)
            {
                _storyHooked = true;
                void Follow() { if (_libraryTab == "story" && _storyBox != null) { _storyBox.Width = StoryWidth(); FitStory(); } }
                _libraryScroller.SizeChanged += (_, __) => Follow();
                _libraryScroller.ScrollChanged += (_, e) => { if (e.ViewportWidthChange != 0 || e.ExtentWidthChange != 0) Follow(); };
                _libraryScroller.LayoutUpdated += (_, __) =>
                {
                    if (_libraryTab == "story" && _storyBox != null && Math.Abs(_storyBox.Width - StoryWidth()) > 1) { _storyBox.Width = StoryWidth(); FitStory(); }
                };
            }
            _libraryTiles.Children.Add(box);
            FitStory();
        }

        // (Luca: «sotto è tagliato») the library is one row high and does not scroll up and down: with the three tiles the
        // text wraps on one more line and the signature fell out of sight. The text gets a little smaller until the box
        // fits in the height the library shows (13 → 11.5 px, then less margin inside), back to 13 as soon as there is room.
        void FitStory()
        {
            if (_storyBox == null || _storyBody == null || _storyFoot == null) return;
            var avail = (_libraryScroller.ViewportHeight > 0 ? _libraryScroller.ViewportHeight : _libraryScroller.ActualHeight) - 8;
            if (avail <= 0 || double.IsNaN(_storyBox.Width)) return;
            _storyBox.Padding = new Thickness(18, 12, 18, 12);
            foreach (var size in new[] { 13.0, 12.5, 12.0, 11.5, 0 })
            {
                if (size == 0) { _storyBox.Padding = new Thickness(18, 7, 18, 6); break; }     // (still too tall: less margin inside)
                if (Math.Abs(_storyBody.FontSize - size) > 0.01)
                {
                    _storyBody.FontSize = size; _storyBody.LineHeight = Math.Round(size * 19 / 13);
                    _storyFoot.FontSize = size - 0.5;
                }
                _storyBox.Measure(new Size(_storyBox.Width, double.PositiveInfinity));
                if (_storyBox.DesiredSize.Height <= avail) break;
            }
        }
    
        // ---------------------------------------------------------------- (1.78.4) the example scene

        const string SampleFolder = "Cosmetic shop", SampleFile = "cosmetic shop.simpler";
        // (1.78.5, Luca: «aggiungiamo un altro progetto di esempio … mettila dopo il progetto shop e rinominali in example
        // #1 e #2») the example scenes in samples\<folder>, in the order of their tiles
        static readonly (string Folder, string File)[] Samples = { (SampleFolder, SampleFile), ("Bedroom", "bedroom.simpler") };

        /// <summary>The example scene shipped with Simpler (samples\Cosmetic shop next to the exe): its picture with
        /// the name under it; null when it is not installed.</summary>
        FrameworkElement? SampleTile(int n)
        {
            var (folder, file) = Samples[n];
            var dir = System.IO.Path.Combine(AppContext.BaseDirectory, "samples", folder);
            var thumb = System.IO.Path.Combine(dir, "thumb.jpg");
            if (!System.IO.File.Exists(System.IO.Path.Combine(dir, file)) || !System.IO.File.Exists(thumb)) return null;
            System.Windows.Media.Imaging.BitmapImage bmp;
            try
            {
                bmp = new System.Windows.Media.Imaging.BitmapImage();
                bmp.BeginInit(); bmp.CacheOption = System.Windows.Media.Imaging.BitmapCacheOption.OnLoad; bmp.DecodePixelWidth = 300;
                bmp.UriSource = new Uri(thumb); bmp.EndInit(); bmp.Freeze();
            }
            catch { return null; }
            var pic = new Border
            {
                Width = 128, Height = 72, CornerRadius = new CornerRadius(6), BorderThickness = new Thickness(1), BorderBrush = Theme.B(Theme.Line),
                Background = new ImageBrush(bmp) { Stretch = Stretch.UniformToFill },
            };
            var cap = new TextBlock { Text = L.F("Esempio #{0}", n + 1), FontSize = 11.5, Foreground = Theme.B(Theme.TextSoft),
                                      Margin = new Thickness(0, 4, 0, 0), HorizontalAlignment = HorizontalAlignment.Center };
            var tile = new StackPanel { Margin = new Thickness(n == 0 ? 18 : 12, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center, Cursor = System.Windows.Input.Cursors.Hand,
                                        Background = Brushes.Transparent,
                                        ToolTip = L.T("Apre la scena di esempio. Simpler ne fa una copia nella cartella «Examples», accanto alla tua libreria dei modelli (la cartella scelta all'installazione): puoi modificarla e salvarla, l'originale resta com'è") };
            tile.Children.Add(pic);
            tile.Children.Add(cap);
            tile.MouseEnter += (_, __) => pic.BorderBrush = Theme.B(Theme.Accent);
            tile.MouseLeave += (_, __) => pic.BorderBrush = Theme.B(Theme.Line);
            tile.MouseLeftButtonUp += async (_, e) => { e.Handled = true; await OpenSample(dir, folder, file); };
            return tile;
        }

        /// <summary>The example scene opened from a copy in Documents\Simpler\Examples (only the files not there yet are
        /// copied: a copy the user changed stays his), after asking to save the scene open now.</summary>
        async System.Threading.Tasks.Task OpenSample(string dir, string folder, string file)
        {
            if (!await AskSaveChanges("Ci sono modifiche non salvate in «{0}».\nVuoi salvarle prima di aprire la scena di esempio?")) return;
            // (16/11, Luca: «metterei tutto nella cartella scelta dall'utente») next to the library of the models - the folder
            // asked by the setup, changed in Impostazioni ▸ Cartelle - not in Documents any more (always there, whatever the user
            // chose; and Documents is what Windows keeps on OneDrive: its «download of files» notice at every example opened).
            // The copies already made in Documents\Simpler\Examples stay where they are.
            var root = "";
            try
            {
                if (_contentModelsDir == "") await ContentDirs();
                if (_contentModelsDir != "") root = System.IO.Path.GetDirectoryName(_contentModelsDir.TrimEnd('\\', '/')) ?? "";
            }
            catch { }
            if (root == "") root = System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Simpler");
            var dest = System.IO.Path.Combine(root, "Examples", folder);     // (one name in every language)
            try
            {
                foreach (var f in System.IO.Directory.GetFiles(dir, "*", System.IO.SearchOption.AllDirectories))
                {
                    var rel = System.IO.Path.GetRelativePath(dir, f);
                    if (rel.Equals("thumb.jpg", StringComparison.OrdinalIgnoreCase)) continue;
                    var to = System.IO.Path.Combine(dest, rel);
                    if (System.IO.File.Exists(to)) continue;
                    System.IO.Directory.CreateDirectory(System.IO.Path.GetDirectoryName(to)!);
                    System.IO.File.Copy(f, to);
                }
            }
            catch (Exception ex)
            {
                AppLog.Write("sample: copy failed: " + ex.Message);
                Msg.Show(this, L.F("Non riesco a copiare la scena di esempio in {0}: ", dest) + ex.Message, "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }
            AppLog.Write("sample: open " + dest);
            await OpenProjectPath(System.IO.Path.Combine(dest, file));
        }
    }
}
