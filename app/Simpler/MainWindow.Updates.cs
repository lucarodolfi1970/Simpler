using System;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace Simpler
{
    /// <summary>(1.78.4, Luca) A newer Simpler: a discreet strip above the status bar. The check runs in the background
    /// after the start (no hourglass, nothing waits for it), at most once a day; it never downloads anything.</summary>
    public sealed partial class MainWindow
    {
        Border? _updateStrip;
        string _updateLater = "";       // «Più tardi»: hidden until the next start

        UIElement BuildUpdateStrip()
        {
            _updateStrip = new Border
            {
                Visibility = Visibility.Collapsed, BorderBrush = Theme.B(Theme.Line), BorderThickness = new Thickness(0, 1, 0, 0),
                Padding = new Thickness(14, 5, 10, 5),
            };
            // (1.79.0) new packs and updates of packs (MainWindow.PackStore.cs)
            _packStrip = new Border
            {
                Visibility = Visibility.Collapsed, BorderBrush = Theme.B(Theme.Line), BorderThickness = new Thickness(0, 1, 0, 0),
                Padding = new Thickness(14, 5, 10, 5),
            };
            var both = new StackPanel();
            both.Children.Add(_packStrip);
            both.Children.Add(_updateStrip);
            return both;
        }

        void StartUpdateCheck()
        {
            UpdateCheck.Found += (info, manual) => Dispatcher.BeginInvoke(() => ShowUpdateStrip(info, manual));
            var st = Settings.Load();
            if (!st.UpdateCheck) return;
            // (Luca: «ho rimesso .4 ma appare ancora») the strip only from a real answer of the site, never from the one
            // kept in the settings: a version taken back on the site disappears at once; a reminder at most once a day
            if (!UpdateCheck.Due(st.UpdateLastCheck, DateTime.UtcNow)) return;
            // a little after the start, on a background thread: the first seconds belong to the scene
            _ = Task.Run(async () =>
            {
                await Task.Delay(TimeSpan.FromSeconds(8));
                await UpdateCheck.Run();
                await Dispatcher.InvokeAsync(() => { _ = PackNewsCheck(); });      // (1.79.0) new packs, updates of packs
            });
        }

        void ShowUpdateStrip(UpdateCheck.Info info, bool manual = false)
        {
            if (_updateStrip == null || (!manual && info.Latest == _updateLater)) return;
            if (manual) _updateLater = "";
            var row = new DockPanel { LastChildFill = true };
            var required = info.Required;
            _updateStrip.Background = Theme.B(required ? "#4A1C1C" : "#3A2A12");     // (Luca: «in arancio, così si nota subito»; non più supportata: rosso)

            void Hide() => _updateStrip.Visibility = Visibility.Collapsed;
            Button Btn(string text, Theme.Kind kind, string tip, Action click)
            {
                var b = Theme.Button(text, kind, tip);
                b.Margin = new Thickness(6, 0, 0, 0);
                b.Padding = new Thickness(10, 3, 10, 3);
                b.Click += (_, __) => click();
                DockPanel.SetDock(b, Dock.Right);
                return b;
            }
            // (right to left: the last added sits nearest the text)
            if (!required)
                row.Children.Add(Btn(L.T("Salta questa versione"), Theme.Kind.Ghost, L.F("Non avvisare più per Simpler {0}: si avviserà per la versione successiva", info.Latest), () =>
                {
                    var s = Settings.Load(); s.UpdateSkipped = info.Latest; s.Save(); Hide();
                }));
            row.Children.Add(Btn(L.T("Più tardi"), Theme.Kind.Ghost, L.T("Nascondi fino al prossimo avvio di Simpler"), () => { _updateLater = info.Latest; Hide(); }));
            if (info.DownloadUrl != "")
                row.Children.Add(Btn(L.T("Scarica"), Theme.Kind.Primary, L.T("Apre nel browser la pagina per scaricare la nuova versione: Simpler non scarica né installa nulla da solo"), () => UpdateCheck.Open(info.DownloadUrl)));
            if (info.NotesUrl != "")
                row.Children.Add(Btn(L.T("Novità"), Theme.Kind.Normal, L.T("Apre nel browser le novità della nuova versione"), () => UpdateCheck.Open(info.NotesUrl)));

            var text = new TextBlock { VerticalAlignment = VerticalAlignment.Center, TextTrimming = TextTrimming.CharacterEllipsis, FontSize = 13 };
            text.Inlines.Add(new System.Windows.Documents.Run(required
                    ? L.F("Questa versione di Simpler non è più aggiornata: scarica Simpler {0}", info.Latest)
                    : L.F("Disponibile Simpler {0}", info.Latest))
                { Foreground = Theme.B(required ? Theme.Danger : Theme.Warm), FontWeight = FontWeights.SemiBold });
            var extra = info.Title != "" ? info.Title : info.Summary;
            if (extra != "") text.Inlines.Add(new System.Windows.Documents.Run("  ·  " + extra) { Foreground = Theme.B(required ? "#F0B0A8" : "#E8C48A") });
            if (info.Summary != "") text.ToolTip = info.Summary;
            row.Children.Add(text);

            _updateStrip.Child = row;
            _updateStrip.Visibility = Visibility.Visible;
        }
    }
}
