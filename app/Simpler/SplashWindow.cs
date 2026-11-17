using System;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Media.Imaging;

namespace Simpler
{
    /// <summary>Start-up screen: shown while the engine starts and the scene is prepared, then the app appears maximized.</summary>
    public sealed class SplashWindow : Window
    {
        readonly TextBlock _status;
        readonly Border _fill;
        readonly Border _track;
        double? _fraction;

        public SplashWindow()
        {
            WindowStyle = WindowStyle.None;
            AllowsTransparency = true;      // needed for the fade-out
            ResizeMode = ResizeMode.NoResize;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            ShowInTaskbar = true;
            Topmost = false;      // (1.75.55) the other programs can go over it while Simpler starts (Luca)
            Title = "Simpler";
            Background = Theme.B("#0A1730");
            UseLayoutRounding = true;
            try
            {
                var ico = Path.Combine(AppContext.BaseDirectory, "Simpler.ico");
                if (File.Exists(ico)) Icon = BitmapFrame.Create(new Uri(ico));
            }
            catch { }

            // 1672 × 941 image shown at 70% of the earlier size: about 42% of the screen width
            var w = Math.Min(770, Math.Max(448, SystemParameters.WorkArea.Width * 0.42));
            Width = w;
            Height = w * 941 / 1672;

            var grid = new Grid();
            var file = Path.Combine(AppContext.BaseDirectory, "splash.jpg");
            if (File.Exists(file))
            {
                var bmp = new BitmapImage();
                bmp.BeginInit();
                bmp.UriSource = new Uri(file);
                bmp.CacheOption = BitmapCacheOption.OnLoad;
                bmp.EndInit();
                grid.Children.Add(new Image { Source = bmp, Stretch = Stretch.UniformToFill });
            }
            else
            {
                grid.Children.Add(new TextBlock { Text = "Simpler", FontSize = 64, FontWeight = FontWeights.Bold, Foreground = Brushes.White, Margin = new Thickness(60) });
            }

            // progress: a thin line on the top edge of the dark footer band (at 87% of the height) and the current step
            _track = new Border { Height = 2, VerticalAlignment = VerticalAlignment.Bottom, Background = Theme.B("#1A2842"), ClipToBounds = true };
            _fill = new Border { Height = 2, HorizontalAlignment = HorizontalAlignment.Left, Width = 0, Background = Theme.B(Theme.Warm) };
            _track.Child = _fill;
            var bottom = new Grid { VerticalAlignment = VerticalAlignment.Bottom, Height = Height * (941 - 818) / 941.0 };
            _track.VerticalAlignment = VerticalAlignment.Top;
            bottom.Children.Add(_track);
            _status = new TextBlock
            {
                FontSize = 12, Foreground = Theme.B("#E4EAF4"), HorizontalAlignment = HorizontalAlignment.Right,
                // (15/11, Luca: on a smaller screen the step was written over the small print of the band) just ABOVE the band,
                // at the right under the ring: the band keeps only its own text, at every size of the splash
                VerticalAlignment = VerticalAlignment.Top, Margin = new Thickness(0, -24, 18, 0), FontFamily = Theme.Sans,
                Effect = new System.Windows.Media.Effects.DropShadowEffect { Color = Colors.Black, BlurRadius = 6, ShadowDepth = 0, Opacity = 0.9 },
            };
            bottom.ClipToBounds = false;
            bottom.Children.Add(_status);
            // video card rating: one small line just above the logo (left, on the dark sky of the picture, away from the rings):
            // the percentage in green / yellow / red and the verdict right after it
            _gpu = new StackPanel { Orientation = Orientation.Horizontal };
            _gpuBox = new Border
            {
                Child = _gpu, HorizontalAlignment = HorizontalAlignment.Left, VerticalAlignment = VerticalAlignment.Top,
                Margin = new Thickness(Width * 37 / 770.0, Height * 11 / 433.0, 0, 0), Opacity = 0, Background = Brushes.Transparent,
            };
            grid.Children.Add(bottom);
            grid.Children.Add(_gpuBox);
            // the version, small, top right (on the dark part of the picture)
            _grid = grid;
            grid.Children.Add(_versionText = new TextBlock
            {
                Text = "v" + SettingsDialog.Version, FontSize = 11, Foreground = Theme.B("#E4EAF4"), FontFamily = Theme.Mono,
                Effect = new System.Windows.Media.Effects.DropShadowEffect { BlurRadius = 6, ShadowDepth = 0, Opacity = 0.8, Color = Colors.Black },
                HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Top,
                Margin = new Thickness(0, Height * 11 / 433.0, 16, 0),
            });
            grid.Children.Add(new Border { BorderBrush = Theme.B("#22355A"), BorderThickness = new Thickness(1) });
            Content = grid;

            // indeterminate shimmer while no fraction is known
            var timer = new System.Windows.Threading.DispatcherTimer { Interval = TimeSpan.FromMilliseconds(30) };
            double phase = 0;
            timer.Tick += (_, __) =>
            {
                var total = _track.ActualWidth;
                if (total <= 0) return;
                if (_fraction is double f) { _fill.Margin = new Thickness(0); _fill.Width = total * Math.Clamp(f, 0, 1); return; }
                phase = (phase + 0.012) % 1.3;
                _fill.Width = total * 0.22;
                _fill.Margin = new Thickness((phase - 0.22) * total, 0, 0, 0);
            };
            timer.Start();
            Closed += (_, __) => timer.Stop();
        }

        readonly Grid _grid;
        readonly TextBlock _versionText;

        /// <summary>The splash as the "Info" window: no progress, a × at the top right, Esc or a click on × closes it.</summary>
        public void AsInfo(string text)
        {
            _track.Visibility = Visibility.Collapsed;
            _status.Text = text;
            _versionText.Margin = new Thickness(0, _versionText.Margin.Top, 48, 0);
            var x = new Button
            {
                Content = new TextBlock { Text = "✕", FontSize = 15, Foreground = Brushes.White },
                Width = 30, Height = 30, Cursor = System.Windows.Input.Cursors.Hand, ToolTip = L.T("Chiudi"),
                HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Top, Margin = new Thickness(0, 6, 8, 0),
                Background = new SolidColorBrush(Color.FromArgb(0x60, 0, 0, 0)), BorderThickness = new Thickness(0),
            };
            x.Click += (_, __) => Close();
            _grid.Children.Add(x);
            KeyDown += (_, e) => { if (e.Key == System.Windows.Input.Key.Escape) Close(); };
        }

        readonly StackPanel _gpu;
        readonly Border _gpuBox;

        /// <summary>The video card and how well it suits Simpler (bar + %), faded in when the check is done.</summary>
        public void SetGpu(GpuRating.Result r)
        {
            _gpu.Children.Clear();
            var color = r.Score >= 65 ? "#4FD18B" : r.Score >= 45 ? "#F2C14E" : r.Score >= 25 ? "#F39A3A" : "#E5534B";
            var shadow = new System.Windows.Media.Effects.DropShadowEffect { BlurRadius = 6, ShadowDepth = 0, Opacity = 0.8, Color = Colors.Black };
            _gpu.Children.Add(new TextBlock { Text = r.Score + "%", FontSize = 12, FontWeight = FontWeights.Bold, Foreground = Theme.B(color), FontFamily = Theme.Sans,
                                              VerticalAlignment = VerticalAlignment.Center, Effect = shadow });
            _gpu.Children.Add(new TextBlock { Text = r.Verdict, FontSize = 11.5, Foreground = Theme.B("#C9D3E4"), FontFamily = Theme.Sans, Margin = new Thickness(7, 0, 0, 0),
                                              VerticalAlignment = VerticalAlignment.Center, Effect = shadow, TextTrimming = TextTrimming.CharacterEllipsis, MaxWidth = Width * 0.5 });
            _gpuBox.ToolTip = L.F("{0} · {1} GB", r.Name, r.VramGb.ToString("0")) + "\n" + L.T("Potenza per Simpler") + ": " + r.Detail;
            _gpuBox.BeginAnimation(OpacityProperty, new DoubleAnimation(0, 1, TimeSpan.FromMilliseconds(300)));
        }

        public void SetStatus(string text, double? fraction = null)
        {
            _status.Text = text;
            _fraction = fraction;
        }

        /// <summary>Fades out and closes.</summary>
        public void FadeOutAndClose()
        {
            Topmost = false;
            var anim = new DoubleAnimation(1, 0, TimeSpan.FromMilliseconds(220));
            anim.Completed += (_, __) => Close();
            BeginAnimation(OpacityProperty, anim);
        }
    }
}
