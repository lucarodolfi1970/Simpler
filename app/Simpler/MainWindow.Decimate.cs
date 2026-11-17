using System;
using System.IO;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace Simpler
{
    /// <summary>(1.75.52) «Ottimizza poligoni»: fewer triangles for a model (right click in the tree or in the view).
    /// The engine reduces every distinct mesh of the model with one budget (decimate.py): materials, UVs and edges kept,
    /// repeated pieces reduced once and every copy follows. The window: presets, a slider (15% at least), the picture
    /// before and after, progress and Interrompi; «Applica» changes the project only (the library stays as it is).</summary>
    public sealed partial class MainWindow
    {
        /// <summary>Above this many distinct triangles the preview is computed only on «Calcola anteprima».</summary>
        const int DecimateAutoLimit = 1_500_000;

        bool CanDecimate(SceneObject o) =>
            o.Kind is "mesh" or "group" or "file" or "model" || o.Children.Count > 0;

        async Task OptimizePolygons(string id)
        {
            if (_api == null || !_scene.ById.TryGetValue(id, out var o)) return;
            JsonObject? info = null;
            await Run(async api => { info = await api.Get("decimate/info?id=" + Uri.EscapeDataString(id)); });
            if (info == null) return;
            var d = new DecimateDialog(this, o, info) { Owner = this };
            d.ShowDialog();
            if (!d.Applied) return;
            await ViewNewGeometry(d.Geometry, "Ottimizza poligoni");
            SetSelection(new[] { d.TargetId }, d.TargetId);
            Status(L.F("Poligoni ottimizzati: {0} → {1} triangoli  (Ctrl+Z per annullare)", Tris(d.Before), Tris(d.After)));
        }

        /// <summary>The objects whose geometry changed (Ottimizza poligoni, its Ctrl+Z): the real-time view takes them
        /// again alone; many, or pieces drawn from a library model, or the export failing: the whole view again.</summary>
        async Task ViewNewGeometry(System.Collections.Generic.List<string> geo, string why)
        {
            bool fromLibrary = geo.Any(i => _scene.ById.TryGetValue(i, out var x) && (x.PaintModel != "" || _scene.Ancestors(x).Any(a => a.PaintModel != "")));
            bool partial = geo.Count > 0 && geo.Count <= 500 && !fromLibrary && _webReady && !_reloading;
            if (!partial) ForcePreviewReload("new geometry of «" + why + "»");
            await RefreshScene();
            if (partial && !await AddPartToViewer(geo, replace: true)) { ForcePreviewReload("new geometry of «" + why + "»"); await RefreshScene(); }
        }

        static System.Collections.Generic.List<string> Ids(JsonNode? n) =>
            (n as JsonArray)?.Select(x => (string?)x ?? "").Where(x => x != "").Distinct().ToList() ?? new System.Collections.Generic.List<string>();

        static string Tris(long n) => n.ToString("N0", System.Globalization.CultureInfo.CurrentCulture);

        /// <summary>(1.75.54) A normal window (not a ThemedDialog: WebView2 is not drawn in a transparent window), large,
        /// always on top: the commands on the left, the 3D preview on the right - the model before and after side by
        /// side, one camera for both (web/compare.html).</summary>
        sealed class DecimateDialog : Window
        {
            readonly MainWindow _mw;
            string _id;
            JsonObject _info;
            readonly ValueSlider _slider;
            readonly System.Collections.Generic.List<Button> _presets;
            readonly TextBlock _infoText, _after, _status;
            readonly CheckBox _wire, _merge;
            readonly ProgressBar _bar;
            readonly Button _stop, _apply, _calc;
            readonly Microsoft.Web.WebView2.Wpf.WebView2 _web = new Microsoft.Web.WebView2.Wpf.WebView2 { DefaultBackgroundColor = System.Drawing.Color.FromArgb(255, 10, 18, 34) };
            readonly System.Windows.Threading.DispatcherTimer _poll;
            bool _running, _webOk, _afterOk;
            double _shownRatio = -1;
            static readonly int[] PresetValues = { 75, 50, 30, 15 };

            public bool Applied;
            public string TargetId => _id;
            public long Before, After;
            public System.Collections.Generic.List<string> Geometry = new();

            long Distinct => (long?)_info["distinct"] ?? 0;
            long Drawn => (long?)_info["triangles"] ?? 0;
            bool Heavy => Distinct > DecimateAutoLimit;

            public DecimateDialog(MainWindow mw, SceneObject o, JsonObject info)
            {
                _mw = mw; _id = o.Id; _info = info;
                Title = L.T("Ottimizza poligoni") + " — " + o.Name;
                // (1.75.55) not Topmost: an owned window stays above Simpler only - other programs can go over it (Luca)
                ShowInTaskbar = false;
                Background = Theme.B(Theme.Window);
                Foreground = Theme.B(Theme.Text);
                FontFamily = Theme.Sans;
                var wa = SystemParameters.WorkArea;
                Width = Math.Min(wa.Width * 0.88, 1800); Height = Math.Min(wa.Height * 0.88, 1050);
                MinWidth = 900; MinHeight = 560;
                WindowStartupLocation = WindowStartupLocation.CenterOwner;

                var root = new Grid();
                root.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(360) });
                root.ColumnDefinitions.Add(new ColumnDefinition());
                var side = new DockPanel { Margin = new Thickness(18, 14, 14, 16) };
                var panelBorder = new Border { Child = side, Background = Theme.B(Theme.Panel), BorderBrush = Theme.B(Theme.Line), BorderThickness = new Thickness(0, 0, 1, 0) };
                root.Children.Add(panelBorder);
                var stage = new Border { Child = _web, Background = Theme.B("#0A1222") };
                Grid.SetColumn(stage, 1);
                root.Children.Add(stage);
                Content = root;

                // the buttons at the bottom of the panel
                var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 10, 0, 0) };
                DockPanel.SetDock(buttons, Dock.Bottom);
                var cancel = Theme.Button(L.T("Annulla"), Theme.Kind.Ghost);
                cancel.Margin = new Thickness(0, 0, 8, 0);
                cancel.Click += (_, __) => Close();
                _apply = Theme.Button(L.T("Applica"), Theme.Kind.Primary, L.T("Sostituisce il modello nel progetto (anche le sue copie). La libreria non cambia. Ctrl+Z per tornare indietro"));
                _apply.Click += async (_, __) => await Apply();
                buttons.Children.Add(cancel);
                buttons.Children.Add(_apply);
                side.Children.Add(buttons);

                var body = new StackPanel();
                side.Children.Add(new ScrollViewer { Content = body, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled });
                body.Children.Add(Theme.Label(L.T("Ottimizza poligoni"), 17, Theme.Text, FontWeights.SemiBold));
                var name = Theme.Label(o.Name, 12, Theme.TextMuted);
                name.TextTrimming = TextTrimming.CharacterEllipsis;
                name.Margin = new Thickness(0, 4, 0, 4);
                body.Children.Add(name);
                _infoText = Theme.Label("", 12, Theme.TextSoft);
                _infoText.TextWrapping = TextWrapping.Wrap;
                _infoText.Margin = new Thickness(0, 0, 0, 14);
                body.Children.Add(_infoText);

                var presets = new UniformGrid2(2);
                _presets = new System.Collections.Generic.List<Button>();
                foreach (var (label, tip) in new[] {
                    (L.T("Leggera") + " 75%", L.T("Quasi uguale da vicino")),
                    (L.T("Media") + " 50%", L.T("Metà dei triangoli: va bene quasi sempre")),
                    (L.T("Forte") + " 30%", L.T("Per oggetti a qualche metro di distanza")),
                    (L.T("Massima") + " 15%", L.T("Per oggetti lontani o sullo sfondo")) })
                {
                    var b = Theme.Button(label, Theme.Kind.Ghost, tip);
                    b.MinHeight = 30; b.Margin = new Thickness(0, 0, 6, 6);
                    _presets.Add(b);
                    presets.Add(b);
                }
                presets.Panel.Margin = new Thickness(0, 0, 0, 8);
                body.Children.Add(presets.Panel);
                for (int i = 0; i < _presets.Count; i++)
                {
                    int v = PresetValues[i];
                    _presets[i].Click += async (_, __) => { _slider!.SetValue(v, false); SliderMoved(v); await Committed(); };
                }

                _slider = new ValueSlider(L.T("Da tenere"), 50, 15, 100, false, "0", "%", null,
                                          L.T("Quanti triangoli restano, rispetto a ora. Non meno del 15%: sotto, la forma si rovina")) { Step = 1 };
                _slider.Compact();
                _slider.Changing += SliderMoved;
                _slider.Committed += async _ => await Committed();
                body.Children.Add(_slider);
                _after = Theme.Label("", 12, Theme.TextMuted);
                _after.TextWrapping = TextWrapping.Wrap;
                _after.Margin = new Thickness(0, -4, 0, 12);
                body.Children.Add(_after);

                _wire = new CheckBox { Content = L.T("Fil di ferro"), IsChecked = false, Foreground = Theme.B(Theme.TextSoft), Margin = new Thickness(0, 0, 0, 10),
                                       ToolTip = L.T("Mostra i triangoli sopra i materiali, in tutte e due le viste") };
                _wire.Click += (_, __) => Send(new { type = "wire", on = _wire.IsChecked == true });
                body.Children.Add(_wire);
                _calc = Theme.Button(L.T("Calcola anteprima"), Theme.Kind.Normal, L.T("Modello pesante: l'anteprima si calcola solo quando la chiedi"));
                _calc.HorizontalAlignment = HorizontalAlignment.Left;
                _calc.Margin = new Thickness(0, 0, 0, 10);
                _calc.Click += async (_, __) => await LoadAfter();
                body.Children.Add(_calc);

                _bar = new ProgressBar { Height = 6, Minimum = 0, Maximum = 1, Value = 0, Foreground = Theme.B(Theme.Accent), Background = Theme.B("#1A2842"), BorderThickness = new Thickness(0), Margin = new Thickness(0, 2, 0, 6), Visibility = Visibility.Collapsed };
                body.Children.Add(_bar);
                _status = Theme.Label("", 12, Theme.TextMuted);
                _status.TextWrapping = TextWrapping.Wrap;
                _status.Margin = new Thickness(0, 0, 0, 6);
                body.Children.Add(_status);
                _stop = Theme.Button(L.T("Interrompi"), Theme.Kind.Ghost, L.T("Ferma il calcolo dopo il pezzo che sta facendo"));
                _stop.HorizontalAlignment = HorizontalAlignment.Left;
                _stop.Visibility = Visibility.Collapsed;
                _stop.Margin = new Thickness(0, 0, 0, 10);
                _stop.Click += async (_, __) => { try { await _mw._api!.Post("decimate/cancel", new { }); } catch { } _status.Text = L.T("Interrompo…"); };
                body.Children.Add(_stop);

                var adv = _mw.Advanced(body, "decimate");
                _merge = new CheckBox { Content = L.T("Unisci prima i pezzi"), IsChecked = false, Foreground = Theme.B(Theme.TextSoft),
                                        ToolTip = L.T("Prima di ottimizzare, i pezzi diventano un solo oggetto (i pezzi ripetuti restano copie). Serve solo a tenere l'albero in ordine: l'ottimizzazione è la stessa") };
                if (o.Children.Count > 0) adv.Body.Children.Add(_merge);
                adv.Done(false);

                _poll = new System.Windows.Threading.DispatcherTimer(TimeSpan.FromMilliseconds(400), System.Windows.Threading.DispatcherPriority.Background, async (_, __) => await Poll(), Dispatcher);
                ShowInfo();
                SliderMoved(50);
                _calc.Visibility = Heavy ? Visibility.Visible : Visibility.Collapsed;
                Loaded += async (_, __) => await StartWeb();
                Closing += (s, e) =>
                {
                    if (_running) { e.Cancel = true; _status.Text = L.T("Attendi la fine del calcolo, o premi «Interrompi»"); return; }
                    if (!Applied) _ = _mw._api?.Post("decimate/discard", new { });
                };
                Closed += (_, __) => { try { _web.Dispose(); } catch { } try { if (Owner is { IsVisible: true } w) w.Activate(); } catch { } };
            }

            void ShowInfo()
            {
                var t = L.F("{0} triangoli · {1} pezzi · {2} materiali", Tris(Drawn), (int?)_info["pieces"] ?? 0, (int?)_info["materials"] ?? 0);
                var dup = (long)((int?)_info["pieces"] ?? 0) - ((int?)_info["meshes"] ?? 0);
                if (dup > 0) t += "\n" + L.F("{0} pezzi sono copie di altri: si ottimizzano una volta sola", dup);
                var outside = (int?)_info["copiesOutside"] ?? 0;
                if (outside > 0) t += "\n" + L.F("Anche {0} copie di questo modello nella scena verranno ottimizzate", outside);
                _infoText.Text = t;
            }

            double Ratio => Math.Clamp(_slider.Value, 15, 100) / 100.0;

            void SliderMoved(double v)
            {
                int sel = Array.IndexOf(PresetValues, (int)Math.Round(v));
                for (int i = 0; i < _presets.Count; i++) { Theme.Style(_presets[i], i == sel ? Theme.Kind.Segment : Theme.Kind.Ghost); _presets[i].MinHeight = 30; }
                _after.Text = L.F("Dopo: circa {0} triangoli", Tris((long)(Drawn * v / 100.0)));
                if (_afterOk && Math.Abs(v / 100.0 - _shownRatio) > 0.004)
                    _after.Text += "\n" + (Heavy ? L.T("L'anteprima mostra ancora la percentuale di prima: «Calcola anteprima»") : L.T("L'anteprima si aggiorna quando lasci il cursore"));
            }

            async Task Committed()
            {
                if (!Heavy && !_running && _webOk) await LoadAfter();
            }

            void Send(object m)
            {
                try { _web.CoreWebView2?.PostWebMessageAsJson(System.Text.Json.JsonSerializer.Serialize(m)); } catch { }
            }

            async Task StartWeb()
            {
                try
                {
                    var folder = FindWebFolder();
                    if (folder == null || _mw._webEnv == null) throw new InvalidOperationException(L.T("Non trovo la cartella 'web' del visualizzatore."));
                    await _web.EnsureCoreWebView2Async(_mw._webEnv);
                    var core = _web.CoreWebView2;
                    core.Settings.AreDefaultContextMenusEnabled = false;
                    core.Settings.IsStatusBarEnabled = false;
                    core.Settings.IsZoomControlEnabled = false;
#if !DEBUG
                    core.Settings.AreDevToolsEnabled = false;
#endif
                    core.SetVirtualHostNameToFolderMapping("simpler.local", folder, Microsoft.Web.WebView2.Core.CoreWebView2HostResourceAccessKind.Allow);
                    core.WebMessageReceived += async (_, e) => await OnWeb(e.WebMessageAsJson);
                    core.Navigate("https://simpler.local/compare.html?lang=" + L.Lang);
                }
                catch (Exception ex)
                {
                    AppLog.Write("decimate preview: " + ex.Message);
                    _status.Text = L.T("Anteprima 3D non disponibile:") + " " + ex.Message;
                }
            }

            async Task OnWeb(string json)
            {
                JsonObject? m;
                try { m = JsonNode.Parse(json) as JsonObject; } catch { return; }
                switch ((string?)m?["type"])
                {
                    case "ready":
                        _webOk = true;
                        Send(new { type = "texts", before = L.T("Prima"), after = L.T("Dopo"), lang = L.Lang,
                                   hint = L.T("Trascina: ruota · tasto destro: sposta · rotella: zoom · doppio clic: inquadra") });
                        await LoadSide("before");
                        if (!Heavy) await LoadAfter();
                        else _status.Text = L.T("Modello pesante: scegli quanto ridurre, poi «Calcola anteprima» (o direttamente «Applica»)");
                        break;
                    case "error":
                        AppLog.Write("decimate preview: " + (string?)m!["text"]);
                        _status.Text = L.T("L'anteprima non si è caricata:") + " " + (string?)m!["text"];
                        break;
                    case "log":
                        AppLog.Write("decimate preview: " + (string?)m!["text"]);
                        break;
                    case "loaded":
                        AppLog.Write($"decimate preview: {(string?)m!["side"]} loaded, {(long?)m["triangles"]} triangles, size {m["size"]?.ToJsonString()}");
                        break;
                }
            }

            void SetRunning(bool on, string text)
            {
                _running = on;
                _bar.Visibility = on ? Visibility.Visible : Visibility.Collapsed;
                _bar.IsIndeterminate = on;
                _stop.Visibility = on ? Visibility.Visible : Visibility.Collapsed;
                _apply.IsEnabled = _calc.IsEnabled = _slider.IsEnabled = _merge.IsEnabled = !on;
                foreach (var b in _presets) b.IsEnabled = !on;
                _status.Text = text;
                if (on) _poll.Start(); else _poll.Stop();
            }

            async Task Poll()
            {
                try
                {
                    var p = await _mw._api!.Get("progress");
                    if ((bool?)p["active"] == true && (string?)p["task"] == "decimate" && p["fraction"] is JsonNode f)
                    {
                        _bar.IsIndeterminate = false;
                        _bar.Value = Math.Clamp((double)f, 0, 1);
                        var detail = (string?)p["detail"] ?? "";
                        // (1.75.55) the piece on, estimated by the engine from the speed of the pieces done
                        var left = (int?)p["pieceLeft"];
                        if (left is int sec) detail += (detail != "" ? " · " : "") + (sec > 0 ? L.F("circa {0} s", sec) : L.T("quasi finito"));
                        _status.Text = ((string?)p["phase"] ?? "") + (detail != "" ? " · " + detail : "");
                    }
                    else if (_running && !_bar.IsIndeterminate)
                    {
                        _bar.IsIndeterminate = true;      // (no measure: the piece that moves back and forth)
                        _status.Text = L.T("Preparo l'anteprima 3D…");
                    }
                }
                catch { }
            }

            /// <summary>«Unisci prima i pezzi»: done once, before the first computation (its own Ctrl+Z step).</summary>
            async Task<bool> MergeFirst()
            {
                if (_merge.IsChecked != true || !_mw._scene.ById.TryGetValue(_id, out var o) || o.Children.Count == 0) return true;
                SetRunning(true, L.T("Unisco i pezzi…"));
                try
                {
                    var r = await _mw._api!.Post("merge", new { ids = new[] { _id } });
                    var nid = (string?)r["id"] ?? "";
                    if (nid == "") return false;
                    _id = nid;
                    _info = await _mw._api.Get("decimate/info?id=" + Uri.EscapeDataString(_id));
                    await _mw.RefreshScene();
                    _merge.IsChecked = false;
                    _merge.Visibility = Visibility.Collapsed;
                    ShowInfo();
                    return true;
                }
                catch (Exception ex) { _status.Text = ex.Message; return false; }
                finally { if (_running) SetRunning(false, _status.Text); }
            }

            /// <summary>One side of the 3D preview: the engine makes the GLB (the reduced meshes for «after»), the page
            /// loads it.</summary>
            async Task<bool> LoadSide(string side)
            {
                if (_running || _mw._api == null || !_webOk) return false;
                var ratio = Ratio;
                using var busy = _mw.BeginBusy();
                SetRunning(true, side == "after" ? L.T("Ottimizzazione dei poligoni") : L.T("Preparo l'anteprima 3D…"));
                Send(new { type = "busy", side, text = side == "after" ? L.T("Calcolo…") : L.T("Preparo…") });
                var t0 = DateTime.Now;
                try
                {
                    var r = await _mw._api.Post("decimate/view", new { id = _id, which = side, ratio });
                    var key = (string?)r["key"] ?? "";
                    var state = (string?)r["state"] ?? "";
                    while (state == "running")
                    {
                        await Task.Delay(250);
                        state = (string?)(await _mw._api.Get("preview/part/status?k=" + Uri.EscapeDataString(key)))["state"] ?? "";
                    }
                    if (state != "done") throw new InvalidOperationException(state == "empty" ? L.T("niente da mostrare") : state);
                    Send(new { type = "model", side, url = $"http://127.0.0.1:{_mw._host.Port}/api/preview/part.glb?k={Uri.EscapeDataString(key)}" });
                    if (side == "after") { _shownRatio = (double?)r["ratio"] ?? ratio; _afterOk = true; }
                    var tris = (long?)r["triangles"] ?? 0;
                    SetRunning(false, side == "after"
                        ? L.F("Anteprima: {0} triangoli ({1} s)", Tris(tris), (DateTime.Now - t0).TotalSeconds.ToString("0"))
                        : "");
                    SliderMoved(_slider.Value);
                    return true;
                }
                catch (Exception ex)
                {
                    Send(new { type = "busy", side, text = "" });
                    SetRunning(false, ex.Message);
                    return false;
                }
            }

            async Task LoadAfter()
            {
                if (_running) return;
                if (!await MergeFirst()) return;
                await LoadSide("after");
            }

            async Task Apply()
            {
                if (_running || _mw._api == null) return;
                if (!await MergeFirst()) return;
                using var busy = _mw.BeginBusy();
                SetRunning(true, L.T("Ottimizzazione dei poligoni"));
                try
                {
                    Before = Drawn;
                    var r = await _mw._api.Post("decimate/apply", new { id = _id, ratio = Ratio });
                    After = (long?)r["triangles"] ?? Before;
                    Geometry = Ids(r["geometry"]);
                    Applied = true;
                    SetRunning(false, "");
                    Close();
                }
                catch (Exception ex) { SetRunning(false, ex.Message); }
            }
        }
    }
}
