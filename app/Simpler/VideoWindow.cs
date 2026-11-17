using System;
using System.Diagnostics;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace Simpler
{
    /// <summary>(1.75.32) The AI video in its own window, playing in a loop: Salva con nome, the folder, open it
    /// outside Simpler.</summary>
    public sealed class VideoWindow : Window
    {
        readonly MediaElement _media = new MediaElement { LoadedBehavior = MediaState.Manual, UnloadedBehavior = MediaState.Close, Stretch = Stretch.Uniform };
        readonly string _file;
        bool _paused;

        public VideoWindow(Window owner, string file)
        {
            Owner = owner;
            _file = file;
            Title = L.T("Video AI") + " — " + Path.GetFileName(file);
            ShowInTaskbar = true;
            Background = Theme.B(Theme.Window);
            Foreground = Theme.B(Theme.Text);
            FontFamily = Theme.Sans;
            var wa = SystemParameters.WorkArea;
            Width = Math.Min(wa.Width * 0.7, 1400); Height = Math.Min(wa.Height * 0.75, 860);
            WindowStartupLocation = WindowStartupLocation.CenterOwner;

            var root = new DockPanel();
            var bar = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(10, 8, 10, 8) };
            var barBorder = new Border { Child = bar, Background = Theme.B(Theme.Panel), BorderBrush = Theme.B(Theme.Line), BorderThickness = new Thickness(0, 0, 0, 1) };
            DockPanel.SetDock(barBorder, Dock.Top);
            root.Children.Add(barBorder);

            Button B(string text, string tip, Action act)
            {
                var b = Theme.Button(text, Theme.Kind.Ghost, tip);
                b.Margin = new Thickness(0, 0, 6, 0);
                b.Click += (_, __) => act();
                bar.Children.Add(b);
                return b;
            }
            B(L.T("Salva con nome…"), L.T("Una copia del video dove vuoi"), SaveAs);
            B(L.T("Apri la cartella"), L.T("La cartella dei video del progetto"), () =>
            {
                try { Process.Start(new ProcessStartInfo("explorer.exe", $"/select,\"{_file}\"") { UseShellExecute = true }); } catch { }
            });
            B(L.T("Apri fuori"), L.T("Nel lettore video di Windows"), () =>
            {
                try { Process.Start(new ProcessStartInfo(_file) { UseShellExecute = true }); } catch { }
            });
            var hint = Theme.Label(L.T("Clic sul video: pausa / riprendi"), 12, Theme.TextFaint);
            hint.VerticalAlignment = VerticalAlignment.Center;
            hint.Margin = new Thickness(10, 0, 0, 0);
            bar.Children.Add(hint);

            var stage = new Grid { Background = Brushes.Black, Cursor = System.Windows.Input.Cursors.Hand };
            stage.Children.Add(_media);
            stage.MouseLeftButtonUp += (_, __) => { if (_paused) _media.Play(); else _media.Pause(); _paused = !_paused; };
            root.Children.Add(stage);
            Content = root;

            _media.Source = new Uri(file);
            _media.MediaEnded += (_, __) => { _media.Position = TimeSpan.Zero; _media.Play(); };
            _media.MediaFailed += (_, e) =>
            {
                AppLog.Write("video window: " + e.ErrorException?.Message);
                Msg.Show(this, L.T("Windows non riesce a riprodurre il video qui: lo apro nel lettore di Windows.") + "\n\n" + e.ErrorException?.Message, "Simpler", MessageBoxButton.OK, MessageBoxImage.Information);
                try { Process.Start(new ProcessStartInfo(_file) { UseShellExecute = true }); } catch { }
                Close();
            };
            Loaded += (_, __) => _media.Play();
            Closed += (_, __) => _media.Close();
        }

        void SaveAs()
        {
            var d = new Microsoft.Win32.SaveFileDialog { Filter = "MP4|*.mp4", FileName = Path.GetFileName(_file) };
            if (d.ShowDialog(this) != true) return;
            try { File.Copy(_file, d.FileName, true); }
            catch (Exception ex) { Msg.Show(this, ex.Message, "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning); }
        }
    }
}
