using System;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;

namespace Simpler
{
    /// <summary>«Calcola solo l'area inquadrata»: one place for what is made only (or finer) where the camera looks - the
    /// snow, the ecosystems - saved with the project (engine camview.py). «Tutto» switches them all; each has its own
    /// switch with what it does written under it. The snow follows the camera by itself; the ecosystems, heavier,
    /// wait for «Ricalcola» (lit when the view has changed) and are made for the camera of a final render before it.</summary>
    public sealed partial class MainWindow
    {
        StackPanel _camViewPanel = null!;
        JsonObject? _camView;
        CancellationTokenSource? _camViewWait;

        void RenderCamView()
        {
            if (_camViewPanel == null) return;
            _camViewPanel.Children.Clear();
            bool snow = (bool?)_camView?["snow"] ?? true, eco = (bool?)_camView?["eco"] ?? true, scree = (bool?)_camView?["scree"] ?? eco;
            var head = Theme.Label(L.T("Calcola solo l'area inquadrata"), 11.5, Theme.TextMuted, FontWeights.SemiBold);
            head.Margin = new Thickness(2, 0, 0, 4);
            head.ToolTip = L.T("Più dettaglio dove guarda la camera, poco altrove: scene grandi più leggere. Il render finale usa la sua camera");
            _camViewPanel.Children.Add(head);

            void Switch(string label, bool? on, Func<bool, object> body, string tip)
            {
                var t = new Toggle(label, on, tip) { Margin = new Thickness(2, 0, 2, 4) };
                t.Toggled += async v => await SetCamView(body(v));
                _camViewPanel.Children.Add(t);
            }
            Switch(L.T("Tutto"), snow == eco && eco == scree ? snow : null, v => new { all = v }, L.T("Accende o spegne tutte le voci"));
            Switch(L.T("Manto di neve"), snow, v => new { snow = v },
                L.T("Più fine vicino alla camera, si rifà quando la camera si ferma. Spento: uguale ovunque (la neve resta)"));
            Switch(L.T("Ecosistemi"), eco, v => new { eco = v },
                L.T("Pezzi solo dove la camera vede. Dopo uno spostamento: «Ricalcola»; prima del render si rifanno da soli"));
            // (1.76.25, Luca) the stones of the terrain follow the frame too: their own switch
            Switch(L.T("Pietre e detriti"), scree, v => new { scree = v },
                L.T("Pietre solo dove la camera vede. Dopo uno spostamento: «Ricalcola»; prima del render si rifanno da sole"));
            var stale = (int?)_camView?["ecoStale"] ?? 0;
            var screeStale = (int?)_camView?["screeStale"] ?? 0;
            if (stale > 0)
            {
                var ecoN = stale - screeStale;
                var label = ecoN == 0 ? L.T("Vista cambiata · Ricalcola le pietre")
                          : screeStale > 0 ? L.T("Vista cambiata · Ricalcola ecosistemi e pietre")
                          : ecoN == 1 ? L.T("Vista cambiata · Ricalcola l'ecosistema") : L.F("Vista cambiata · Ricalcola {0} ecosistemi", ecoN);
                var b = Theme.Button(Theme.IconText(Icons.Refresh, label, Theme.Warm, 14),
                                     Theme.Kind.Segment, L.T("Rifà gli ecosistemi per la vista di adesso (un solo passo da annullare). Dove le due viste coincidono, i pezzi restano gli stessi"));
                b.BorderBrush = Theme.B(Theme.Warm);
                b.MinHeight = 30;
                b.FontSize = 12;
                b.HorizontalAlignment = HorizontalAlignment.Stretch;
                b.Margin = new Thickness(2, 0, 2, 4);
                b.Click += async (_, __) => await RefreshCamView();
                _camViewPanel.Children.Add(b);
            }
        }

        async Task LoadCamView()
        {
            JsonObject? r = null;
            try { if (_api != null) r = await _api.Get("camview"); } catch { }
            if (r == null) return;
            _camView = r;
            RenderCamView();
        }

        async Task SetCamView(object body)
        {
            var before = _camView;
            JsonObject? r = null;
            await Run(async api => { r = await api.Post("camview", body); });
            if (r != null) _camView = r;
            RenderCamView();
            if (r == null) return;
            bool was(string k) => (bool?)before?[k] ?? true;
            bool now(string k) => (bool?)r[k] ?? true;
            if (was("snow") != now("snow"))
                Status(now("snow") ? L.T("La neve segue la camera: il manto si rifà per questa vista") : L.T("La neve non segue più la camera: il manto si rifà uguale su tutta la scena"));
            else if ((was("eco") != now("eco") || was("scree") != now("scree")) && ((int?)r["ecoStale"] ?? 0) > 0)
                Status(L.T("Premi «Ricalcola» in basso a sinistra per rifare ecosistemi e pietre"));
        }

        async Task RefreshCamView()
        {
            JsonObject? r = null;
            using (BeginBusy())
            {
                ShowTask(L.T("Ricalcolo per la vista…"));
                try { await Run(async api => { r = await api.Post("camview/refresh", new { }); }); }
                finally { HideTask(); }
            }
            if (r == null) return;
            _camView = r;
            RenderCamView();
            await RefreshScene();
            if (_rightPanel == "ecosystem") { await LoadEcoInfo(); RenderProps(); }
            var failed = r["failed"] as JsonArray;
            if (failed != null && failed.Count > 0)
                Status(string.Join(" · ", failed.Select(f => $"{(string?)f?["name"]}: {(string?)f?["error"]}")), true);
            else
                Status(L.F("Rifatti per la vista: {0}", (int?)r["done"] ?? 0));
            if (_rightPanel == "landscape") { await LoadTerrain(); RenderProps(); }
        }

        /// <summary>The camera moved: a moment after it stops, is there anything to make again for the view?</summary>
        void CamViewAfterCamera()
        {
            // (1.76.31, Luca) the stones too: before only with ecosystems, so with stones alone «Ricalcola» never showed
            bool ecoOn = ((bool?)_camView?["eco"] ?? false) && ((int?)_camView?["ecoTotal"] ?? 0) > 0;
            bool screeOn = ((bool?)_camView?["scree"] ?? false) && ((int?)_camView?["screeTotal"] ?? 0) > 0;
            if (!ecoOn && !screeOn) return;
            _camViewWait?.Cancel();
            var cts = _camViewWait = new CancellationTokenSource();
            _ = Task.Run(async () =>
            {
                try { await Task.Delay(800, cts.Token); } catch { return; }
                await Dispatcher.InvokeAsync(async () => { if (!cts.IsCancellationRequested) await LoadCamView(); });
            });
        }

        /// <summary>Before a final render: the ecosystems made for its camera, when the view has changed.</summary>
        async Task CamViewBeforeRender()
        {
            await LoadCamView();
            if (((int?)_camView?["ecoStale"] ?? 0) > 0) await RefreshCamView();
        }
    }
}
