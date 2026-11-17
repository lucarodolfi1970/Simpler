using System;
using System.IO;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Shapes;

namespace Simpler
{
    /// <summary>Pictures for the AI: any file or capture made into a plain 8-bit PNG OpenAI accepts, the mask of an
    /// area, and the result of "Sostituisci" put back into the original only inside the area.</summary>
    public static class AiImage
    {
        public static BitmapSource Decode(byte[] data, int maxSide = 3840)
        {
            var frame = BitmapFrame.Create(new MemoryStream(data), BitmapCreateOptions.PreservePixelFormat, BitmapCacheOption.OnLoad);
            BitmapSource b = new FormatConvertedBitmap(frame, PixelFormats.Bgra32, null, 0);
            int mx = Math.Max(b.PixelWidth, b.PixelHeight);
            if (mx > maxSide)
            {
                double k = maxSide / (double)mx;
                b = new TransformedBitmap(b, new ScaleTransform(k, k));
                b = new FormatConvertedBitmap(b, PixelFormats.Bgra32, null, 0);
            }
            var wb = new WriteableBitmap(b);           // (a plain bitmap: no lazy decode chain kept alive)
            wb.Freeze();
            return wb;
        }

        public static byte[] Png(BitmapSource b)
        {
            var enc = new PngBitmapEncoder();
            enc.Frames.Add(BitmapFrame.Create(b));
            using var ms = new MemoryStream();
            enc.Save(ms);
            return ms.ToArray();
        }

        static byte[] Pixels(BitmapSource b)
        {
            var px = new byte[b.PixelWidth * b.PixelHeight * 4];
            b.CopyPixels(px, b.PixelWidth * 4, 0);
            return px;
        }

        static BitmapSource FromPixels(byte[] px, int w, int h)
        {
            var bmp = BitmapSource.Create(w, h, 96, 96, PixelFormats.Bgra32, null, px, w * 4);
            bmp.Freeze();
            return bmp;
        }

        /// <summary>The mask for OpenAI: same size as the picture, opaque everywhere but the area (transparent = edit).</summary>
        public static byte[] Mask(int w, int h, Rect r)
        {
            var px = new byte[w * h * 4];
            int x0 = (int)(r.X * w), y0 = (int)(r.Y * h), x1 = (int)Math.Ceiling((r.X + r.Width) * w), y1 = (int)Math.Ceiling((r.Y + r.Height) * h);
            for (int y = 0; y < h; y++)
                for (int x = 0; x < w; x++)
                {
                    int i = (y * w + x) * 4;
                    px[i] = px[i + 1] = px[i + 2] = 255;
                    px[i + 3] = (byte)(x >= x0 && x < x1 && y >= y0 && y < y1 ? 0 : 255);
                }
            return Png(FromPixels(px, w, h));
        }

        /// <summary>Of the AI result only the area, faded over a band at its edges; the rest from the original
        /// (renderAI mask_composite: identical outside by construction, not by trust).</summary>
        public static BitmapSource Composite(BitmapSource original, BitmapSource result, Rect r, int feather = 28)
        {
            int W = result.PixelWidth, H = result.PixelHeight;
            BitmapSource o = original.PixelWidth == W && original.PixelHeight == H ? original
                : new FormatConvertedBitmap(new TransformedBitmap(original, new ScaleTransform(W / (double)original.PixelWidth, H / (double)original.PixelHeight)), PixelFormats.Bgra32, null, 0);
            var po = Pixels(o);
            var pr = Pixels(new FormatConvertedBitmap(result, PixelFormats.Bgra32, null, 0));
            double x0 = r.X * W, y0 = r.Y * H, x1 = (r.X + r.Width) * W, y1 = (r.Y + r.Height) * H;
            for (int y = 0; y < H; y++)
                for (int x = 0; x < W; x++)
                {
                    double d = Math.Min(Math.Min(x - x0, x1 - x), Math.Min(y - y0, y1 - y));
                    double a = Math.Clamp(d / feather, 0, 1);
                    if (a <= 0) continue;
                    int i = (y * W + x) * 4;
                    for (int c = 0; c < 4; c++) po[i + c] = (byte)Math.Round(po[i + c] * (1 - a) + pr[i + c] * a);
                }
            return FromPixels(po, W, H);
        }
    }

    /// <summary>
    /// A picture of Simpler (a final render, an AI result) in its own window, always on top and resizable: zoom with
    /// the wheel, move by dragging, Fit / 100%. With a result, a line divides before (left) and after (right): drag it
    /// to compare. Save, copy, process with the AI. For "Sostituisci" it also picks the area to change.
    /// </summary>
    public sealed class AiImageWindow : Window
    {
        BitmapSource _before;
        BitmapSource? _after;
        readonly Grid _content = new Grid();             // the picture(s), in image pixels
        readonly Image _imgBefore = new Image(), _imgAfter = new Image();
        readonly RectangleGeometry _clip = new RectangleGeometry();
        readonly Line _split = new Line { Stroke = Theme.B(Theme.Accent), StrokeThickness = 2 };
        readonly Border _knob;
        readonly ScaleTransform _scale = new ScaleTransform(1, 1);
        readonly TranslateTransform _move = new TranslateTransform();
        readonly Border _view;
        readonly StackPanel _bar;
        readonly TextBlock _hint;
        double _splitAt = 0.5;
        bool _dragSplit, _dragMove, _picking;
        Point _last;
        Rectangle? _pickRect;
        Point _pickStart;
        TaskCompletionSource<Rect?>? _pickDone;
        readonly Action<BitmapSource, string>? _toAi;
        readonly string? _externalPath;
        string? _info, _infoTip;          // (1.75.10) the final render: time and memory, after the buttons

        public void SetInfo(string text, string tip)
        {
            _info = text; _infoTip = tip;
            BuildBar();
        }

        public AiImageWindow(Window owner, string title, BitmapSource before, BitmapSource? after, Action<BitmapSource, string>? toAi, string? externalPath = null)
        {
            Owner = owner;
            Title = title;
            _before = before; _after = after; _toAi = toAi; _externalPath = externalPath;
            // (1.75.55) not Topmost: an owned window stays above Simpler only - other programs can go over it (Luca)
            ShowInTaskbar = true;
            Background = Theme.B(Theme.Window);
            Foreground = Theme.B(Theme.Text);
            FontFamily = Theme.Sans;
            var wa = SystemParameters.WorkArea;
            Width = Math.Min(wa.Width * 0.7, 1400); Height = Math.Min(wa.Height * 0.75, 900);
            WindowStartupLocation = WindowStartupLocation.CenterOwner;

            var root = new DockPanel();
            _bar = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(10, 8, 10, 8) };
            var barBorder = new Border { Child = _bar, Background = Theme.B(Theme.Panel), BorderBrush = Theme.B(Theme.Line), BorderThickness = new Thickness(0, 0, 0, 1) };
            DockPanel.SetDock(barBorder, Dock.Top);
            root.Children.Add(barBorder);
            _hint = new TextBlock { Foreground = Theme.B(Theme.TextMuted), FontSize = 12, Margin = new Thickness(12, 6, 12, 6), TextWrapping = TextWrapping.Wrap };
            DockPanel.SetDock(_hint, Dock.Bottom);
            root.Children.Add(_hint);

            _imgBefore.Stretch = Stretch.Fill; _imgAfter.Stretch = Stretch.Fill;
            RenderOptions.SetBitmapScalingMode(_imgBefore, BitmapScalingMode.HighQuality);
            RenderOptions.SetBitmapScalingMode(_imgAfter, BitmapScalingMode.HighQuality);
            _imgAfter.Clip = _clip;
            _content.Children.Add(_imgBefore);
            _content.Children.Add(_imgAfter);
            var overlay = new Canvas();
            overlay.Children.Add(_split);
            _knob = new Border { Width = 34, Height = 34, CornerRadius = new CornerRadius(17), Background = Theme.B("#FFFFFF"), BorderBrush = Theme.B(Theme.Accent), BorderThickness = new Thickness(2),
                                 Child = new TextBlock { Text = "⇆", FontSize = 16, Foreground = Theme.B(Theme.Accent), HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center } };
            overlay.Children.Add(_knob);
            _content.Children.Add(overlay);
            _content.HorizontalAlignment = HorizontalAlignment.Left; _content.VerticalAlignment = VerticalAlignment.Top;
            var tg = new TransformGroup(); tg.Children.Add(_scale); tg.Children.Add(_move);
            _content.RenderTransform = tg;
            var canvasHost = new Grid { ClipToBounds = true, Background = Theme.B(Theme.Ground) };
            // the picture on a Canvas: in a Grid a picture larger than the window (a 1920 render in a 1300 window) was
            // cut by the layout to the window's size before the zoom, and "Adatta" showed only its top left part
            var stage = new Canvas();
            stage.Children.Add(_content);
            canvasHost.Children.Add(stage);
            _view = new Border { Child = canvasHost };
            root.Children.Add(_view);
            Content = root;

            canvasHost.MouseWheel += (_, e) => Zoom(e.Delta > 0 ? 1.15 : 1 / 1.15, e.GetPosition(canvasHost));
            canvasHost.MouseLeftButtonDown += OnDown;
            canvasHost.MouseMove += OnMove;
            canvasHost.MouseLeftButtonUp += (_, e) => OnUp(e);
            canvasHost.MouseRightButtonDown += (_, e) => { _dragMove = true; _last = e.GetPosition(canvasHost); canvasHost.CaptureMouse(); };
            canvasHost.MouseRightButtonUp += (_, __) => { _dragMove = false; canvasHost.ReleaseMouseCapture(); };
            Loaded += (_, __) => { SetImages(_before, _after); Fit(); };
            SizeChanged += (_, __) => { if (IsLoaded) Fit(); };
            BuildBar();
        }

        void SetImages(BitmapSource before, BitmapSource? after)
        {
            _before = before; _after = after;
            _content.Width = before.PixelWidth; _content.Height = before.PixelHeight;
            _imgBefore.Source = before;
            _imgAfter.Source = after;
            _imgAfter.Visibility = _split.Visibility = _knob.Visibility = after != null ? Visibility.Visible : Visibility.Collapsed;
            _hint.Text = after != null
                ? L.T("A sinistra l'originale, a destra il risultato: trascina la linea per confrontarli. Rotellina per lo zoom, tasto destro (o fuori dalla linea) per spostare l'immagine.")
                : L.T("Rotellina per lo zoom, trascina per spostare l'immagine.");
            UpdateSplit();
        }

        void UpdateSplit()
        {
            double W = _content.Width, H = _content.Height, x = _splitAt * W;
            _clip.Rect = new Rect(x, 0, Math.Max(0, W - x), H);
            _split.X1 = _split.X2 = x; _split.Y1 = 0; _split.Y2 = H;
            double s = 1 / Math.Max(1e-6, _scale.ScaleX);          // the line and the knob keep their size on screen
            _split.StrokeThickness = 2 * s;
            _knob.RenderTransform = new ScaleTransform(s, s, 17, 17);
            Canvas.SetLeft(_knob, x - 17); Canvas.SetTop(_knob, H / 2 - 17);
        }

        void Fit()
        {
            if (_view.ActualWidth <= 0 || _content.Width <= 0) return;
            double k = Math.Min(_view.ActualWidth / _content.Width, _view.ActualHeight / _content.Height);
            _scale.ScaleX = _scale.ScaleY = k;
            _move.X = (_view.ActualWidth - _content.Width * k) / 2;
            _move.Y = (_view.ActualHeight - _content.Height * k) / 2;
            UpdateSplit();
        }

        void Zoom(double f, Point at)
        {
            double k = Math.Clamp(_scale.ScaleX * f, 0.02, 16);
            f = k / _scale.ScaleX;
            _move.X = at.X - (at.X - _move.X) * f;
            _move.Y = at.Y - (at.Y - _move.Y) * f;
            _scale.ScaleX = _scale.ScaleY = k;
            UpdateSplit();
        }

        Point ToImage(Point p) => new Point((p.X - _move.X) / _scale.ScaleX, (p.Y - _move.Y) / _scale.ScaleY);

        void OnDown(object sender, MouseButtonEventArgs e)
        {
            var host = (IInputElement)sender;
            var p = e.GetPosition(host);
            var ip = ToImage(p);
            ((UIElement)sender).CaptureMouse();
            if (_picking)
            {
                _pickStart = new Point(Math.Clamp(ip.X, 0, _content.Width), Math.Clamp(ip.Y, 0, _content.Height));
                if (_pickRect == null)
                {
                    _pickRect = new Rectangle { Stroke = Theme.B(Theme.Warm), StrokeThickness = 2, Fill = new SolidColorBrush(Color.FromArgb(50, 0xF2, 0xB5, 0x4B)) };
                    ((Canvas)_content.Children[2]).Children.Add(_pickRect);
                }
                _pickRect.StrokeThickness = 2 / _scale.ScaleX;
                Canvas.SetLeft(_pickRect, _pickStart.X); Canvas.SetTop(_pickRect, _pickStart.Y);
                _pickRect.Width = _pickRect.Height = 0;
                _dragSplit = false; _dragMove = false;
                return;
            }
            if (_after != null && Math.Abs(ip.X - _splitAt * _content.Width) * _scale.ScaleX < 18) { _dragSplit = true; return; }
            _dragMove = true; _last = p;
        }

        void OnMove(object sender, MouseEventArgs e)
        {
            var host = (IInputElement)sender;
            var p = e.GetPosition(host);
            if (_picking && e.LeftButton == MouseButtonState.Pressed && _pickRect != null)
            {
                var ip = ToImage(p);
                double x = Math.Clamp(ip.X, 0, _content.Width), y = Math.Clamp(ip.Y, 0, _content.Height);
                Canvas.SetLeft(_pickRect, Math.Min(x, _pickStart.X)); Canvas.SetTop(_pickRect, Math.Min(y, _pickStart.Y));
                _pickRect.Width = Math.Abs(x - _pickStart.X); _pickRect.Height = Math.Abs(y - _pickStart.Y);
                return;
            }
            if (_dragSplit) { _splitAt = Math.Clamp(ToImage(p).X / _content.Width, 0, 1); UpdateSplit(); return; }
            if (_dragMove) { _move.X += p.X - _last.X; _move.Y += p.Y - _last.Y; _last = p; }
            if (_after != null && !_picking)
                ((FrameworkElement)sender).Cursor = Math.Abs(ToImage(p).X - _splitAt * _content.Width) * _scale.ScaleX < 18 ? Cursors.SizeWE : Cursors.Arrow;
        }

        void OnUp(MouseButtonEventArgs e)
        {
            _dragSplit = _dragMove = false;
            Mouse.Capture(null);
        }

        // ---------------------------------------------------------------- toolbar

        void BuildBar()
        {
            _bar.Children.Clear();
            Button B(string text, Theme.Kind kind, string? tip, Action click)
            {
                var b = Theme.Button(text, kind, tip);
                b.Margin = new Thickness(0, 0, 6, 0);
                b.Click += (_, __) => click();
                _bar.Children.Add(b);
                return b;
            }
            if (_picking)
            {
                _bar.Children.Add(new TextBlock { Text = L.T("Trascina un rettangolo sull'area da cambiare"), Foreground = Theme.B(Theme.Warm), VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(4, 0, 14, 0) });
                B(L.T("Conferma"), Theme.Kind.Primary, null, () =>
                {
                    if (_pickRect == null || _pickRect.Width < 4 || _pickRect.Height < 4) { Msg.Show(this, L.T("Disegna prima il rettangolo sull'immagine."), "Simpler", MessageBoxButton.OK, MessageBoxImage.Information); return; }
                    var r = new Rect(Canvas.GetLeft(_pickRect) / _content.Width, Canvas.GetTop(_pickRect) / _content.Height, _pickRect.Width / _content.Width, _pickRect.Height / _content.Height);
                    _pickDone?.TrySetResult(r);
                    Close();
                });
                B(L.T("Annulla"), Theme.Kind.Ghost, null, () => Close());
                B(L.T("Adatta"), Theme.Kind.Ghost, L.T("Tutta l'immagine nella finestra"), Fit);
                return;
            }
            B(L.T("Salva…"), Theme.Kind.Primary, L.T("Salva l'immagine (il risultato, se c'è) in PNG o JPEG"), Save);
            B(L.T("Copia"), Theme.Kind.Normal, L.T("Copia l'immagine negli appunti"), () => { try { Clipboard.SetImage(_after ?? _before); } catch { } });
            B(L.T("Adatta"), Theme.Kind.Ghost, L.T("Tutta l'immagine nella finestra"), Fit);
            B("100%", Theme.Kind.Ghost, L.T("Un pixel dell'immagine per pixel dello schermo"), () =>
            {
                var c = new Point(_view.ActualWidth / 2, _view.ActualHeight / 2);
                Zoom(1 / _scale.ScaleX, c);
            });
            if (_toAi != null)
            {
                var ai = B(L.T("Elabora con l'AI"), Theme.Kind.Normal, L.T("Usa questa immagine nel pannello AI (il risultato, se c'è)"), () => _toAi(_after ?? _before, Title));
            }
            if (_externalPath != null)
                B(L.T("Apri fuori"), Theme.Kind.Ghost, L.T("Apre il file con il programma predefinito di Windows"), () =>
                {
                    try { System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(_externalPath) { UseShellExecute = true }); } catch { }
                });
            if (!string.IsNullOrEmpty(_info))
                _bar.Children.Add(new TextBlock
                {
                    Text = _info, Foreground = Theme.B(Theme.TextMuted), FontSize = 12, VerticalAlignment = VerticalAlignment.Center,
                    Margin = new Thickness(14, 0, 0, 0), ToolTip = string.IsNullOrEmpty(_infoTip) ? null : _infoTip,
                });
        }

        void Save()
        {
            var dlg = new Microsoft.Win32.SaveFileDialog
            {
                Filter = L.T("PNG|*.png|JPEG|*.jpg"),
                FileName = (_after != null ? "Simpler AI " : "Simpler ") + DateTime.Now.ToString("yyyy-MM-dd HH.mm.ss") + ".png",
            };
            var mw = Owner as MainWindow;
            if (mw != null) dlg.InitialDirectory = mw.StartFolder("render");
            if (dlg.ShowDialog(this) != true) return;
            mw?.Keep("render", dlg.FileName);
            BitmapEncoder enc = dlg.FileName.EndsWith(".jpg", StringComparison.OrdinalIgnoreCase) || dlg.FileName.EndsWith(".jpeg", StringComparison.OrdinalIgnoreCase)
                ? new JpegBitmapEncoder { QualityLevel = 95 } : new PngBitmapEncoder();
            enc.Frames.Add(BitmapFrame.Create(_after ?? _before));
            using var fs = File.Create(dlg.FileName);
            enc.Save(fs);
        }

        /// <summary>The area to change (fractions of the picture), drawn by the user on it; null if cancelled.</summary>
        public static Task<Rect?> PickArea(Window owner, BitmapSource image)
        {
            var w = new AiImageWindow(owner, L.T("Scegli l'area da cambiare"), image, null, null) { _picking = true };
            w._pickDone = new TaskCompletionSource<Rect?>();
            w.BuildBar();
            w._hint.Text = L.T("Trascina con il tasto sinistro un rettangolo attorno a ciò che vuoi togliere o sostituire, poi «Conferma». Rotellina per lo zoom, tasto destro per spostare l'immagine.");
            w.Loaded += (_, __) => w._hint.Text = L.T("Trascina con il tasto sinistro un rettangolo attorno a ciò che vuoi togliere o sostituire, poi «Conferma». Rotellina per lo zoom, tasto destro per spostare l'immagine.");
            w.Closed += (_, __) => w._pickDone.TrySetResult(null);
            w.Show();
            return w._pickDone.Task;
        }
    }
}
