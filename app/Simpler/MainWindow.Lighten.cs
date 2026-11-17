using System;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Media;

namespace Simpler
{
    /// <summary>«Alleggerisci»: a box at the bottom of the tree with what makes a heavy scene lighter at once - the snow,
    /// the distributions and the flakes in the view, the shadows of the view, half resolution, the automatic
    /// computations paused, memory freed. A button that is on (something left out) is orange.</summary>
    public sealed partial class MainWindow
    {
        Border _lightBox = null!;
        UniformGrid _lightButtons = null!;
        bool _pauseCalc;

        UIElement BuildLightenBox()
        {
            var sp = new StackPanel();
            // «Calcola solo l'area inquadrata» (MainWindow.CamView.cs): above the buttons, with its words in sight
            _camViewPanel = new StackPanel();
            sp.Children.Add(_camViewPanel);
            sp.Children.Add(new Border { Height = 1, Background = Theme.B(Theme.Line), Margin = new Thickness(0, 4, 0, 8) });
            RenderCamView();
            var title = Theme.Label(L.T("Alleggerisci"), 11.5, Theme.TextMuted, FontWeights.SemiBold);
            title.Margin = new Thickness(2, 0, 0, 6);
            title.ToolTip = L.T("Per le scene pesanti: ogni pulsante toglie qualcosa da calcolare o da disegnare. Arancione = attivo. Il path tracing e le immagini finali restano complete, salvo la neve nascosta");
            sp.Children.Add(title);
            _lightButtons = new UniformGrid { Rows = 1, Columns = 7, HorizontalAlignment = HorizontalAlignment.Stretch };
            sp.Children.Add(_lightButtons);
            _lightBox = new Border
            {
                Child = sp, Background = Theme.B(Theme.Panel), BorderBrush = Theme.B(Theme.Line), BorderThickness = new Thickness(0, 1, 0, 0),
                Padding = new Thickness(12, 8, 12, 10),
            };
            RenderLightenBox();
            return _lightBox;
        }

        void RenderLightenBox()
        {
            if (_lightButtons == null) return;
            var st = Settings.Load();
            _lightButtons.Children.Clear();
            void Btn(Geometry icon, bool on, bool enabled, string tip, Func<Task> act, Color? color = null)
            {
                var b = Theme.Button(Theme.Icon(icon, on ? Theme.Warm : (color ?? Theme.TextMuted), 16), on ? Theme.Kind.Segment : Theme.Kind.Ghost, tip);
                b.MinHeight = 30;
                b.Padding = new Thickness(0);
                b.Margin = new Thickness(2, 0, 2, 0);
                b.HorizontalAlignment = HorizontalAlignment.Stretch;
                b.IsEnabled = enabled;
                if (!enabled) b.Opacity = 0.35;
                if (on) b.BorderBrush = Theme.B(Theme.Warm);
                b.Click += async (_, __) => { await act(); RenderLightenBox(); };
                ToolTipService.SetShowOnDisabled(b, true);
                _lightButtons.Children.Add(b);
            }
            Btn(Icons.Snow, _snowHidden, _snowPresent || _snowHidden,
                _snowHidden ? L.T("Mostra la neve: il manto e i fiocchi tornano, ricalcolati una volta con quello che hai cambiato")
                            : L.T("Nascondi la neve: il manto e i fiocchi spariscono dalla vista e dalle immagini e non si ricalcolano mentre sposti i modelli (c'è solo quando nevica)"),
                async () => await SetSnowHidden(!_snowHidden));
            Btn(Icons.Grass, st.LightSets, true,
                st.LightSets ? L.T("Mostra le distribuzioni nella vista")
                             : L.T("Nascondi le distribuzioni nella vista: alberi, erba, scatter ed ecosistemi (e le loro lampade) non vengono disegnati in tempo reale. Nel path tracing e nelle immagini ci sono"),
                () => { var s = Settings.Load(); s.LightSets = !s.LightSets; s.Save(); PushViewLight(); return Task.CompletedTask; });
            Btn(Icons.Dots, st.LightFlakes, true,
                st.LightFlakes ? L.T("Mostra fiocchi e gocce che cadono nella vista")
                               : L.T("Nascondi fiocchi e gocce che cadono nella vista; neve a terra e superfici bagnate restano. Nel path tracing ci sono"),
                () => { var s = Settings.Load(); s.LightFlakes = !s.LightFlakes; s.Save(); PushViewLight(); return Task.CompletedTask; });
            var shadowsOff = st.ViewerShadows == "off";
            Btn(Icons.SunCloud, shadowsOff, true,
                shadowsOff ? L.T("Riaccendi le ombre della vista, come prima")
                           : L.T("Spegni le ombre della vista in tempo reale (le luci con ombre ridisegnano la scena più volte). Nel path tracing restano"),
                () =>
                {
                    var s = Settings.Load();
                    if (s.ViewerShadows == "off") s.ViewerShadows = s.LightPrevShadows is "media" or "alta" or "ultra" ? s.LightPrevShadows : "alta";
                    else { s.LightPrevShadows = s.ViewerShadows; s.ViewerShadows = "off"; }
                    s.Save();
                    SendToWeb(new { type = "shadows", level = s.ViewerShadows });
                    UpdateQualityDrop();
                    return Task.CompletedTask;
                });
            Btn(Icons.Image, st.LightHalf, true,
                st.LightHalf ? L.T("Vista a piena risoluzione")
                             : L.T("Vista a mezza risoluzione: disegna un quarto dei pixel, molto più fluida, un po' meno nitida. Il path tracing e le immagini non cambiano"),
                () => { var s = Settings.Load(); s.LightHalf = !s.LightHalf; s.Save(); PushViewLight(); return Task.CompletedTask; });
            Btn(Icons.Clock, _pauseCalc, true,
                _pauseCalc ? L.T("Riprendi i ricalcoli automatici: riparo dalla pioggia, manto di neve, fiocchi e gocce si rifanno una volta con quello che hai cambiato")
                           : L.T("Ferma i ricalcoli automatici: dopo ogni spostamento riparo dalla pioggia, manto di neve, fiocchi e gocce non si rifanno finché non li riprendi (il path tracing li aggiorna comunque per le sue immagini)"),
                async () =>
                {
                    JsonObject? r = null;
                    await Run(async api => { r = await api.Post("rain/pause", new { on = !_pauseCalc }); });
                    if (r != null) _pauseCalc = (bool?)r["on"] ?? false;
                    Status(_pauseCalc ? L.T("Ricalcoli automatici fermi") : L.T("Ricalcoli automatici ripresi"));
                });
            Btn(Icons.Broom, false, true,
                L.T("Libera memoria: toglie dalla memoria gli oggetti eliminati tenuti per l'annulla e i materiali, le texture e le geometrie che nessun oggetto usa più. Prima ti dice cosa e quanto, e chiede conferma."),
                PurgeMemory, Theme.Danger);
        }

        void PushViewLight()
        {
            var s = Settings.Load();
            SendToWeb(new { type = "viewLight", sets = s.LightSets, flakes = s.LightFlakes, half = s.LightHalf });
        }
    }
}
