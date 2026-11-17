using System;
using System.IO;
using System.Net.Http;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace Simpler
{
    /// <summary>
    /// A texture of the material editor, big, in a small window that stays on top (not modal: the editor keeps
    /// working). Transparent parts show on a checker. One window at a time: clicking another texture shows it here.
    /// </summary>
    public sealed class TextureViewer : ThemedDialog
    {
        static TextureViewer? _open;
        readonly Image _image = new Image { Stretch = Stretch.Uniform };
        readonly TextBlock _info = Theme.Label("", 12, Theme.TextMuted);
        readonly TextBlock _wait = Theme.Label("", 12, Theme.TextFaint);
        readonly Button _folder;
        string _path = "";

        TextureViewer() : base(L.T("Texture"), 600)
        {
            // (1.75.55) not Topmost: an owned window stays above Simpler only - other programs can go over it (Luca)
            ShowInTaskbar = false;
            var sp = Body;
            sp.Margin = new Thickness(18, 0, 18, 18);
            var head = new DockPanel { Margin = new Thickness(0, 0, 0, 10) };
            _folder = Theme.Button(L.T("Apri la cartella"), Theme.Kind.Ghost, L.T("Mostra il file in Esplora risorse"));
            _folder.MinHeight = 26; _folder.Height = 26; _folder.FontSize = 12; _folder.Padding = new Thickness(8, 0, 8, 0);
            _folder.Click += (_, __) =>
            {
                try { if (File.Exists(_path)) System.Diagnostics.Process.Start("explorer.exe", "/select,\"" + _path + "\""); } catch { }
            };
            DockPanel.SetDock(_folder, Dock.Right);
            head.Children.Add(_folder);
            _info.TextTrimming = TextTrimming.CharacterEllipsis;
            _info.VerticalAlignment = VerticalAlignment.Center;
            head.Children.Add(_info);
            sp.Children.Add(head);

            // checker under the picture: transparency is visible
            var checker = new DrawingBrush
            {
                TileMode = TileMode.Tile, Viewport = new Rect(0, 0, 16, 16), ViewportUnits = BrushMappingMode.Absolute,
                Drawing = new DrawingGroup
                {
                    Children =
                    {
                        new GeometryDrawing(Theme.B("#2A3242"), null, new RectangleGeometry(new Rect(0, 0, 16, 16))),
                        new GeometryDrawing(Theme.B("#1C2230"), null, new GeometryGroup { Children = { new RectangleGeometry(new Rect(0, 0, 8, 8)), new RectangleGeometry(new Rect(8, 8, 8, 8)) } }),
                    },
                },
            };
            var frame = new Grid { Width = 560, Height = 560 };
            frame.Children.Add(new Border { Background = checker, CornerRadius = new CornerRadius(8) });
            frame.Children.Add(_image);
            _wait.HorizontalAlignment = HorizontalAlignment.Center;
            _wait.VerticalAlignment = VerticalAlignment.Center;
            frame.Children.Add(_wait);
            sp.Children.Add(frame);
            KeyDown += (_, e) => { if (e.Key == Key.Escape) Close(); };
            Closed += (_, __) => _open = null;
        }

        /// <summary>Shows a texture of the project (name of the Blender image; info from the material editor).</summary>
        public static async Task Show(Window owner, HttpClient http, int port, string image, string file, string path, int width, int height, bool packed)
        {
            var v = _open;
            if (v == null)
            {
                v = new TextureViewer { Owner = owner };
                _open = v;
                v.Show();
            }
            v.Activate();
            v._path = path;
            v._folder.Visibility = File.Exists(path) ? Visibility.Visible : Visibility.Collapsed;
            v._info.Text = file + (width > 0 ? $"  ·  {width} × {height} px" : "") + (packed ? "  ·  " + L.T("incorporata nel file") : "");
            v._info.ToolTip = path != "" ? path : file;
            v._image.Source = null;
            v._wait.Text = L.T("Caricamento…");
            try
            {
                var bytes = await http.GetByteArrayAsync($"http://127.0.0.1:{port}/api/texture?image={Uri.EscapeDataString(image)}&px=2048");
                var bmp = new BitmapImage();
                bmp.BeginInit();
                bmp.CacheOption = BitmapCacheOption.OnLoad;
                bmp.StreamSource = new MemoryStream(bytes);
                bmp.EndInit();
                bmp.Freeze();
                if (_open != v) return;
                v._image.Source = bmp;
                v._wait.Text = "";
            }
            catch (Exception ex)
            {
                v._wait.Text = L.T("Texture non disponibile: ") + ex.Message;
            }
        }
    }
}
