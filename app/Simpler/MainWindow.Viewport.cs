using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;
using System.Windows.Threading;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.Wpf;

namespace Simpler
{
    /// <summary>
    /// Viewport: a real-time WebGL view (three.js inside WebView2) for navigation, picking and the gizmo.
    /// "Path tracing" turns on progressive Cycles rendering from the same camera, overlaid on the real-time view.
    /// </summary>
    public sealed partial class MainWindow
    {
        Grid _viewport = null!;
        WebView2 _web = null!;
        Border _busy = null!;
        TextBlock _busyText = null!;
        bool _webReady;
        readonly List<object> _pendingToWeb = new List<object>();
        DispatcherTimer? _progressTimer;
        bool _realistic;
        string _structureSig = "";
        int _vpW, _vpH;

        // busy screen with a progress bar fed by the engine (GET /api/progress)
        Border _busyTrack = null!, _busyFill = null!;
        Button _busyCancel = null!;
        TextBlock _busyPhase = null!, _busyTime = null!;
        StackPanel _busyHw = null!;          // the final render: graphics card and memory (BusyHardware)
        DispatcherTimer? _busyTimer;
        DateTime _busyStart;
        double _indeterminate;
        bool _busyPolling;

        UIElement BuildViewport()
        {
            _viewport = new Grid { Background = Theme.B("#0B1220"), ClipToBounds = true };
            _web = new WebView2 { DefaultBackgroundColor = System.Drawing.Color.FromArgb(255, 11, 18, 32) };
            _viewport.Children.Add(_web);

            // WPF content cannot be drawn over WebView2, so the busy screen hides the web view while shown.
            _busyText = new TextBlock { FontSize = 15, Foreground = Theme.B(Theme.Text), HorizontalAlignment = HorizontalAlignment.Center };
            var busyStack = new StackPanel { VerticalAlignment = VerticalAlignment.Center, HorizontalAlignment = HorizontalAlignment.Center, Width = 460 };
            var logo = new Grid { Width = 54, Height = 54, Margin = new Thickness(0, 0, 0, 16) };
            logo.Children.Add(new Ellipse { Stroke = Theme.B(Theme.Accent), StrokeThickness = 3 });
            _eyePupil = new Ellipse { Fill = Theme.B(Theme.Warm), Width = 20, Height = 20, RenderTransform = _eyeMove };
            logo.Children.Add(_eyePupil);
            logo.RenderTransformOrigin = new Point(0.5, 0.5);
            logo.RenderTransform = _eyeBlink;
            busyStack.Children.Add(logo);
            busyStack.Children.Add(_busyText);
            _busyTrack = new Border { Height = 6, CornerRadius = new CornerRadius(3), Background = Theme.B("#1A2842"), Margin = new Thickness(0, 16, 0, 8), ClipToBounds = true };
            _busyFill = new Border { Height = 6, CornerRadius = new CornerRadius(3), Background = Theme.B(Theme.Warm), HorizontalAlignment = HorizontalAlignment.Left, Width = 0 };
            _busyTrack.Child = _busyFill;
            busyStack.Children.Add(_busyTrack);
            // phase on the left (wraps on two lines if long), percentage and time on the right: never on top of each other
            var info = new Grid();
            info.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            info.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            _busyPhase = new TextBlock { FontSize = 12, Foreground = Theme.B(Theme.TextMuted), TextWrapping = TextWrapping.Wrap, MaxHeight = 36, TextTrimming = TextTrimming.CharacterEllipsis };
            info.Children.Add(_busyPhase);
            _busyTime = new TextBlock { FontFamily = Theme.Mono, FontSize = 12, Foreground = Theme.B(Theme.TextFaint), Margin = new Thickness(14, 0, 0, 0), VerticalAlignment = VerticalAlignment.Top };
            Grid.SetColumn(_busyTime, 1);
            info.Children.Add(_busyTime);
            busyStack.Children.Add(info);
            _busyHw = new StackPanel { Margin = new Thickness(0, 12, 0, 0) };
            busyStack.Children.Add(_busyHw);
            _busyCancel = Theme.Button(L.T("Annulla render"), Theme.Kind.Normal, L.T("Interrompe il render finale"));
            _busyCancel.Margin = new Thickness(0, 18, 0, 0);
            _busyCancel.HorizontalAlignment = HorizontalAlignment.Center;
            _busyCancel.Visibility = Visibility.Collapsed;
            _busyCancel.Click += async (_, __) => await CancelFinalRender();
            busyStack.Children.Add(_busyCancel);
            // (1.75.20) the final render: the samples over time at the bottom, behind the progress
            var busyGrid = new Grid();
            busyGrid.Children.Add(BuildSampleChart());
            busyGrid.Children.Add(busyStack);
            _busy = new Border { Background = Theme.B("#0B1220"), Child = busyGrid };
            _viewport.Children.Add(_busy);
            return _viewport;
        }

        /// <summary>(1.75.19) «Salva immagine» in the view: the picture as it is now (path tracing or real time) to a file.</summary>
        void SaveViewImage(string b64, string kind)
        {
            if (b64 == "") { Status(L.T("Non è stato possibile prendere l'immagine della vista"), true); return; }
            byte[] bytes;
            try { bytes = Convert.FromBase64String(b64); } catch { Status(L.T("Non è stato possibile prendere l'immagine della vista"), true); return; }
            var dlg = new Microsoft.Win32.SaveFileDialog
            {
                Filter = "JPEG|*.jpg",
                FileName = (kind == "pathtracing" ? "Simpler path tracing " : "Simpler vista ") + DateTime.Now.ToString("yyyy-MM-dd HH.mm.ss") + ".jpg",
                InitialDirectory = StartFolder("render"),
            };
            if (dlg.ShowDialog(this) != true) return;
            try
            {
                File.WriteAllBytes(dlg.FileName, bytes);
                Remember(dlg.FileName, "render");
                Status(L.F("Immagine della vista salvata: {0}", dlg.FileName));
                AppLog.Write($"view image saved ({kind}, {bytes.Length / 1024} KB): {dlg.FileName}");
            }
            catch (Exception ex) { Status(L.T("Salvataggio non riuscito: ") + ex.Message, true); }
        }

        /// <summary>Full-screen wait (engine start-up, final render). <paramref name="cancellable"/> shows "Annulla render".</summary>
        void ShowBusy(string text, bool cancellable = false)
        {
            _busyCancel.Visibility = cancellable ? Visibility.Visible : Visibility.Collapsed;
            _busyCancel.IsEnabled = true;
            _busyText.Text = text;
            _busyPhase.Text = "";
            _busyTime.Text = "";
            _busyHw.Children.Clear();
            _busyFill.Width = 0;
            _busyFill.Margin = new Thickness(0);
            _busyStart = DateTime.Now;
            CloseIdeas();                   // (1.78.4: the ideas page gives the place back to the wait)
            _busy.Visibility = Visibility.Visible;
            if (_web != null) _web.Visibility = Visibility.Hidden;
            EyeStart(cancellable);          // (the final render: the logo looks around)
            ChartStart(cancellable);        // (and the samples over time at the bottom)
            _busyTimer ??= new DispatcherTimer(TimeSpan.FromMilliseconds(120), DispatcherPriority.Background, async (_, __) => await BusyTick(), Dispatcher);
            _busyTimer.Start();
        }

        /// <summary>Under the progress of the final render: the graphics card (memory used and how full, load,
        /// temperature), the memory Cycles uses, the computer's memory - and, in the warm colour, when part of the
        /// render does not fit on the card and runs from the computer's memory (much slower).</summary>
        void BusyHardware(JsonObject? hw)
        {
            _busyHw.Children.Clear();
            if (hw == null) return;
            static string Gb(double b) => (b / 1e9).ToString(b >= 10e9 ? "0" : "0.0") + " GB";
            double? D(string k) => (double?)hw[k];
            TextBlock Line(string text, Color c)
            {
                var t = new TextBlock { Text = text, FontSize = 11.5, Foreground = Theme.B(c), TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 0, 0, 3) };
                _busyHw.Children.Add(t);
                return t;
            }
            var gpu = (string?)hw["gpu"] ?? "";
            if (D("vramUsed") is double vu && D("vramTotal") is double vt && vt > 0)
            {
                var pct = vu / vt * 100;
                var parts = new List<string> { L.F("Scheda grafica: {0} di {1} ({2}%)", Gb(vu), Gb(vt), pct.ToString("0")) };
                if (D("load") is double ld) parts.Add(L.F("al lavoro {0}%", ld.ToString("0")));
                if (D("temperature") is double tc) parts.Add($"{tc:0} °C");
                Line((gpu != "" ? gpu + " · " : "") + string.Join(" · ", parts), pct >= 97 ? Theme.Warm : Theme.TextMuted);
                // a thin bar of how full the card is
                var track = new Border { Height = 4, CornerRadius = new CornerRadius(2), Background = Theme.B("#1A2842"), Margin = new Thickness(0, 0, 0, 7), ClipToBounds = true };
                var fill = new Border { Height = 4, CornerRadius = new CornerRadius(2), HorizontalAlignment = HorizontalAlignment.Left,
                                        Background = Theme.B(pct >= 97 ? Theme.Warm : Theme.Accent), Width = Math.Max(2, 460 * Math.Min(1, vu / vt)) };
                track.Child = fill;
                _busyHw.Children.Add(track);
            }
            var mem = new List<string>();
            if (D("cyclesMem") is double cm && cm > 0) mem.Add(L.F("il render usa {0}", Gb(cm)));
            if (D("procRam") is double pr && pr > 0) mem.Add(L.F("memoria del computer del render {0}", Gb(pr)));
            if (D("ramUsed") is double ru && D("ramTotal") is double rt && rt > 0) mem.Add(L.F("computer {0} di {1}", Gb(ru), Gb(rt)));
            if (mem.Count > 0) Line(string.Join(" · ", mem), Theme.TextFaint);
            if (D("spill") is double sp && sp > 0)
                Line(L.F("Circa {0} del render non stanno sulla scheda grafica e lavorano dalla memoria del computer: molto più lento. Chiudi altri programmi che usano la scheda o scegli texture più piccole nel render.", Gb(sp)), Theme.Warm);
        }

        void HideBusy()
        {
            _busyTimer?.Stop();
            EyeStop();
            ChartStart(false);
            _busy.Visibility = Visibility.Collapsed;
            if (_web != null && _ideasPanel == null) _web.Visibility = Visibility.Visible;
        }

        async Task BusyTick()
        {
            var secs = (DateTime.Now - _busyStart).TotalSeconds;
            _busyTime.Text = secs >= 1 ? $"{secs:0} s" : "";
            double? fraction = null;
            if (_api != null && !_busyPolling)
            {
                _busyPolling = true;
                try
                {
                    var p = await _api.Get("progress");
                    if ((bool?)p["active"] == true)
                    {
                        fraction = (double?)p["fraction"];
                        var phase = (string?)p["phase"] ?? "";
                        var detail = (string?)p["detail"] ?? "";
                        _busyPhase.Text = detail != "" ? phase + " · " + detail : phase;
                        _lastFraction = fraction;
                        BusyHardware(p["hardware"] as JsonObject);
                        ChartFeed((int?)p["samples"] ?? 0, (int?)p["samplesTotal"] ?? 0, fraction >= 0.97);
                    }
                    else _lastFraction = null;
                }
                catch { }
                finally { _busyPolling = false; }
            }
            fraction ??= _lastFraction;
            ChartTick(secs);
            var w = _busyTrack.ActualWidth;
            if (fraction is double f)
            {
                _busyFill.Margin = new Thickness(0);
                _busyFill.Width = Math.Max(6, w * f);
                _busyTime.Text = $"{f * 100:0}%" + (secs >= 1 ? $" · {secs:0} s" : "");
            }
            else
            {
                // indeterminate: a segment sliding along the track
                _indeterminate = (_indeterminate + 0.035) % 1.3;
                var seg = w * 0.28;
                _busyFill.Width = seg;
                _busyFill.Margin = new Thickness((_indeterminate - 0.28) * w, 0, 0, 0);
            }
        }

        double? _lastFraction;

        // ---------------------------------------------------------------- small progress pill (bottom of the 3D view)
        DispatcherTimer? _taskTimer;
        string _taskText = "";
        bool _taskPolling;

        /// <summary>Non-blocking progress: a small bar at the bottom of the 3D view, fed by the engine progress.</summary>
        void ShowTask(string text)
        {
            if (!_webReady) { ShowBusy(text); return; }
            _taskText = text;
            SendToWeb(new { type = "task", text });
            _taskTimer ??= new DispatcherTimer(TimeSpan.FromMilliseconds(200), DispatcherPriority.Background, async (_, __) => await TaskTick(), Dispatcher);
            _taskTimer.Start();
        }

        void HideTask()
        {
            if (_busy.Visibility == Visibility.Visible && !_webReady) { HideBusy(); return; }
            _taskTimer?.Stop();
            _taskText = "";
            SendToWeb(new { type = "task", text = "" });
        }

        async Task TaskTick()
        {
            if (_api == null || _taskPolling || _taskText == "") return;
            _taskPolling = true;
            try
            {
                var p = await _api.Get("progress");
                if ((bool?)p["active"] == true && _taskText != "")
                {
                    var phase = L.T((string?)p["phase"] ?? "");
                    var detail = (string?)p["detail"] ?? "";
                    SendToWeb(new { type = "task", text = _taskText, fraction = (double?)p["fraction"], detail = phase + (detail != "" ? " · " + detail : "") });
                }
            }
            catch { }
            finally { _taskPolling = false; }
        }

        static string? FindWebFolder()
        {
            for (var dir = new DirectoryInfo(AppContext.BaseDirectory); dir != null; dir = dir.Parent)
            {
                foreach (var candidate in new[] { System.IO.Path.Combine(dir.FullName, "web"), System.IO.Path.Combine(dir.FullName, "app", "Simpler", "web") })
                    if (File.Exists(System.IO.Path.Combine(candidate, "viewer.html"))) return candidate;
            }
            return null;
        }

        /// <summary>(1.75.54) Kept for the other WebView2 of Simpler (the 3D preview of «Ottimizza poligoni»): the same
        /// data folder with other options would fail.</summary>
        CoreWebView2Environment? _webEnv;

        /// <summary>Starts WebView2 and loads the viewer page. Called once the engine is up.</summary>
        async Task StartViewer()
        {
            var webFolder = FindWebFolder() ?? throw new InvalidOperationException(L.T("Non trovo la cartella 'web' del visualizzatore."));
            var dataFolder = System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Simpler", AppInstance.Prefix + "WebView2");
            CoreWebView2Environment env;
            try
            {
                // the view must keep drawing when Windows thinks it is covered or in the background: without these, the
                // path tracing picture (fetched by a timer of the page) could stop at a pass until the window was
                // activated again (Chromium slows timers and drawing of windows it judges hidden or occluded)
                var opts = new CoreWebView2EnvironmentOptions(
                    "--disable-features=CalculateNativeWinOcclusion --disable-background-timer-throttling " +
                    "--disable-renderer-backgrounding --disable-backgrounding-occluded-windows " +
                    // (14/11, measured on Luca's card: a shader of the view costs 0,2-0,6 s the first time and 0,015 s when the card
                    // finds it in its cache) the cache of compiled shaders of Chromium is 6 MB by default: room for all the
                    // shaders of big projects, in memory and on disk, so each one is paid once and not at every opening
                    // (15/11: once the video card closed the view while a project opened - GpuProcessExited; cause not known, the cache in
                    // memory brought down from 512 to 128 MB to leave it out; the one on disk stays at 1 GB)
                    "--gpu-program-cache-size-kb=131072 --gpu-disk-cache-size-kb=1048576");
                env = await CoreWebView2Environment.CreateAsync(null, dataFolder, opts);
            }
            catch (WebView2RuntimeNotFoundException)
            {
                throw new InvalidOperationException("Manca Microsoft Edge WebView2 Runtime (di solito già presente in Windows 10/11).\nScaricalo da https://go.microsoft.com/fwlink/p/?LinkId=2124703");
            }
            _webEnv = env;
            await _web.EnsureCoreWebView2Async(env);
            var core = _web.CoreWebView2;
            core.Settings.AreDefaultContextMenusEnabled = false;
            core.Settings.IsStatusBarEnabled = false;
            core.Settings.IsZoomControlEnabled = false;
            core.Settings.AreBrowserAcceleratorKeysEnabled = false;
#if !DEBUG
            core.Settings.AreDevToolsEnabled = false;
#endif
            _web.AllowExternalDrop = false;
            core.SetVirtualHostNameToFolderMapping("simpler.local", webFolder, CoreWebView2HostResourceAccessKind.Allow);
            core.WebMessageReceived += (_, e) => OnWebMessage(e.WebMessageAsJson);
            core.ProcessFailed += (_, e) => OnViewerFailed(e.ProcessFailedKind);
            core.Navigate("https://simpler.local/viewer.html?lang=" + L.Lang);
        }

        JsonObject? _lastCamera;         // the last framing told by the view (cm, as the engine)
        JsonObject? _cameraToRestore;    // the framing of the project just opened (the view may fall while it opens)

        void SendToWeb(object message)
        {
            if (!_webReady) { _pendingToWeb.Add(message); return; }
            try { _web.CoreWebView2?.PostWebMessageAsJson(JsonSerializer.Serialize(message)); }
            catch { /* view not available (closing) */ }
        }

        async void OnWebMessage(string json)
        {
            JsonObject? msg;
            try { msg = JsonNode.Parse(json) as JsonObject; } catch { return; }
            if (msg == null) return;
            switch ((string?)msg["type"])
            {
                case "ptDone":
                    await PathTracedThumb((string?)msg["thumb"] ?? "");
                    break;
                case "ready":
                    AppLog.Write("viewer ready" + (_recovering ? " (after a restart)" : ""));
                    _webReady = true;
                    SendToWeb(new { type = "init", engine = $"http://127.0.0.1:{_host.Port}/api/" });
                    SendToWeb(new { type = "tool", mode = ToolMode() });
                    SendToWeb(new { type = "mode", realistic = _realistic });
                    SendToWeb(new { type = "boxes", on = _boxMode });
                    SendToWeb(new { type = "speed", level = Settings.Load().NavSpeed });
                    SendToWeb(new { type = "touchpad", on = Settings.Load().TouchpadPan });
                    PushToneToViewer();
                    PushFxToViewer();
                    SendToWeb(new { type = "pivotMode", mode = Settings.Load().PivotMode });
                    SendToWeb(new { type = "shadows", level = Settings.Load().ViewerShadows });
                    PushViewLight();
                    SendToWeb(new { type = "smartView", on = Settings.Load().SmartView });
                    SendPaint();
                    await LoadRenderSettings();
                    if (_renderSettings["view"] is JsonObject startView) SendCameraOptions(startView);
                    await LoadViews();
                    RenderLibrary();
                    foreach (var m in _pendingToWeb) SendToWeb(m);
                    _pendingToWeb.Clear();
                    if (_recovering && _loadedUrl != null)
                    {
                        // the viewer restarted after a crash: reload the last view, no new export
                        _recovering = false;
                        SendToWeb(new { type = "load", url = _loadedUrl, frame = (string?)null, big = true });
                        // (15/11, Luca: «il progetto riaperto e la camera in un altro punto», log: the video card closed the view while
                        // the project was opening - GpuProcessExited - and the view started again stood at its first framing,
                        // on the bare ground) the framing it had: the one of the project just sent, or the last one of the view
                        var back = _cameraToRestore ?? _lastCamera;
                        if (back != null)
                        {
                            SendToWeb(new { type = "setCamera", view = back.DeepClone() });
                            AppLog.Write("view started again: framing put back " + (back["position"]?.ToJsonString() ?? "?"));
                        }
                        // the view shows the last prepared scene again: what changed since is re-applied in place
                        _structure = _loadedStructure;
                        _structureSig = "";
                        _viewerIds.Clear();
                        foreach (var x in _loadedStructure) _viewerIds.Add(x.Id);
                        await RefreshScene();
                        UpdateGizmo();
                        break;
                    }
                    _recovering = false;
                    ForcePreviewReload("start of the 3D view");
                    await RefreshScene("");
                    break;
                case "size":
                    _vpW = (int?)msg["width"] ?? 0; _vpH = (int?)msg["height"] ?? 0;
                    await PushViewportSize();
                    break;
                case "viewBusy":
                    _viewBusy = (bool?)msg["on"] ?? false;
                    UpdateBusyCursor();   // (background work: the arrow with the hourglass, the panels still work)
                    break;
                case "puddleStroke":
                    await PuddleStroke(msg);
                    break;
                case "puddleExit":
                    _puddleBrush = false; SendPuddleBrush();
                    if (_rightPanel is "ambience" or "material" or "landscape") RenderProps();
                    break;
                case "terrainSculptCount":
                    _tsPending = (int?)msg["n"] ?? 0;
                    break;
                case "terrainSculptCommit":
                    await CommitTerrainSculpt(msg["strokes"] as JsonArray);
                    break;
                case "puddleRadius":
                    if (_brushLayer == "terrain") { _tsRadius = (double?)msg["radius"] ?? _tsRadius; _tsRadiusChanged?.Invoke(); break; }
                    if (_brushLayer == "sculpt") _sculptRadius = (double?)msg["radius"] ?? _sculptRadius;
                    else if (_brushLayer == "dirt") _dirtRadius = (double?)msg["radius"] ?? _dirtRadius;
                    else _puddleRadius = (double?)msg["radius"] ?? _puddleRadius;
                    break;
                case "sculptStroke":
                    await SculptStroke(msg);
                    break;
                case "snowState":
                    // it snows with a mantle / the mantle is hidden («Nascondi la neve», menu of the right button)
                    _snowPresent = (bool?)msg["present"] ?? false;
                    _snowHidden = (bool?)msg["hidden"] ?? false;
                    RenderLightenBox();
                    break;
                case "engineBusy":
                    // «Occupato · attendi» shown in the view (engine busy, app waiting, view preparing): the hourglass
                    // on the panels too, until everything is over
                    _engineBusy = (bool?)msg["on"] ?? false;
                    UpdateBusyCursor();   // (background work: the arrow with the hourglass, the panels still work)
                    // the log of the waits: every time «Occupato · attendi» was shown, how long and for what
                    if (!_engineBusy && ((double?)msg["secs"] ?? 0) > 0)
                        AppLog.Write($"wait {((double?)msg["secs"] ?? 0):0.0} s: {(string?)msg["what"] ?? ""}");
                    // a new snow mantle: the panel of the Ambiente shows its cells and vertices («Dettaglio del mantello»)
                    if (!_engineBusy && _rightPanel == "ambience" && (((string?)msg["what"]) ?? "").Contains(L.T("Calcolo del mantello di neve")))
                    {
                        await LoadAmbience();
                        RenderProps();
                    }
                    break;
                case "loaded":
                    _viewerWait?.Dispose(); _viewerWait = null;
                    if (_viewerLoadClock != null)
                    {
                        AppLog.Write($"3D view loaded by the viewer in {_viewerLoadClock.Elapsed.TotalSeconds:0.0} s");
                        _viewerLoadClock = null;
                    }
                    _firstLoad.TrySetResult(true);
                    _ = PushSimplerMaterials();      // materials edited in Simpler: every channel, maps included
                    if (_refreshAfterLoad)
                    {
                        // changes made while the view was being prepared: applied now, in place
                        _refreshAfterLoad = false;
                        await RefreshScene();
                    }
                    _statusRight.Text = _engineLabel + L.F(" · vista: {0} mesh", (int?)msg["meshes"] ?? 0);
                    break;
                case "eyedropper":
                    await OnEyedropper((string?)msg["id"] ?? "", (string?)msg["material"] ?? "");
                    break;
                case "pick":
                    var ids = (msg["ids"] as JsonArray)?.Select(n => (string?)n ?? "").Where(x => x != "").ToList() ?? new List<string>();
                    SelectFromViewport(ids, (string?)msg["primary"] ?? "");
                    await FollowPickedMaterial(ids, (string?)msg["primary"] ?? "", (string?)msg["material"] ?? "");
                    break;
                case "setPivot":
                    await SavePivot((string?)msg["id"] ?? "", msg["pivot"] as JsonArray);
                    break;
                case "benchExit":           // (1.79.0: the button of the blue note of the bench)
                    await ExitBench();
                    break;
                case "pivotEditOff":
                    if (_pivotEdit) SetPivotEdit(false);
                    break;
                case "pickInside":
                    await PickInsideModel((string?)msg["id"] ?? "");
                    break;
                case "transform":
                    if (msg["items"] is JsonArray items && items.Count > 0)
                    {
                        await Run(async api => { await api.Post("matrices", new JsonObject { ["items"] = items.DeepClone() }); });
                        await RefreshScene();
                    }
                    break;
                case "camera":
                    // (15/11) the framing the view really has: put back if the view has to be started again (see «ready»)
                    if (!_recovering && msg["position"] is JsonArray && msg["target"] is JsonArray)
                    {
                        _lastCamera = new JsonObject { ["position"] = msg["position"]!.DeepClone(), ["target"] = msg["target"]!.DeepClone(), ["vfov"] = msg["vfov"]?.DeepClone() };
                        _cameraToRestore = null;         // (the view has its framing: from now on the last one it tells)
                    }
                    ViewMovedForDome(msg);
                    await Run(async api =>
                    {
                        await api.Post("camera", new JsonObject
                        {
                            ["action"] = "lookat",
                            ["position"] = msg["position"]?.DeepClone(),
                            ["target"] = msg["target"]?.DeepClone(),
                            ["vfov"] = msg["vfov"]?.DeepClone(),
                            ["aspect"] = msg["aspect"]?.DeepClone(),
                        });
                    });
                    CamViewAfterCamera();
                    break;
                case "pivotMode":
                {
                    var ps = Settings.Load(); ps.PivotMode = (string?)msg["mode"] ?? "base"; ps.Save();
                    break;
                }
                case "shadows":
                    var st = Settings.Load(); st.ViewerShadows = (string?)msg["level"] ?? "alta"; st.Save();
                    UpdateQualityDrop();
                    if (_rightPanel != "") RenderProps();
                    RenderLightenBox();
                    break;
                case "focus":
                    await OnFocusPicked((double?)msg["distance"] ?? 100);
                    break;
                case "context":
                {
                    // right click on a piece: selected (Ctrl: its group), then the menu
                    var cids = (msg["ids"] as JsonArray)?.Select(n => (string?)n ?? "").Where(x => x != "").ToList() ?? new List<string>();
                    var prim = (string?)msg["primary"] ?? "";
                    if (prim == "") break;
                    // (the viewer keeps the selection when the piece is inside it: the menu acts on all of it)
                    SelectFromViewport(cids.Count > 0 ? cids : new List<string> { prim }, prim);
                    ShowViewportMenu(prim, (string?)msg["material"] ?? "");
                    break;
                }
                case "paintSet":
                    await OnPaintSet(msg);
                    break;
                case "paintAdd":
                    if (msg["items"] is JsonArray pitems) await OnPaintAdd(pitems, (int?)msg["batch"] ?? 0);
                    break;
                case "paintErase":
                    if (msg["ids"] is JsonArray pids) await OnPaintErase(pids);
                    break;
                case "paintRadius":
                    _paint.Radius = Math.Clamp((double?)msg["radius"] ?? _paint.Radius, 0.05, 50);
                    SavePaint();
                    if (_rightPanel == "paint") RenderProps();
                    break;
                case "paintExit":
                    SetTool("move");
                    break;
                case "paintInfo":
                    // (1.78.4) the brush held pieces back: too many for one touch, or the distribution is full
                    if ((string?)msg["state"] == "total")
                        Status(L.F("Distribuzione al limite ({0} oggetti): il pennello non ne aggiunge altri. Per continuare crea un'altra distribuzione con «Nuova»", ((double?)msg["count"] ?? 0).ToString("N0")), true);
                    else
                        Status(L.F("Troppi oggetti per pennellata: con questo raggio usa una distanza di almeno {0} m", Math.Round(((double?)msg["spacing"] ?? 1) + 0.005, 2)));
                    break;
                case "areaInfo":
                    if ((string?)msg["state"] == "tooMany")
                        Status(L.F("Area troppo grande per questa distanza: aumenta la distanza ad almeno {0} m", Math.Round(((double?)msg["spacing"] ?? 1) + 0.005, 2)));
                    else Status(L.T("Calcolo dell'area…"));
                    break;
                case "shiftCopy":
                    if (msg["delta"] is JsonArray sdelta)
                        await OnShiftCopy((msg["ids"] as JsonArray)?.Select(n => (string?)n ?? "").Where(x => x != "").ToList() ?? new List<string>(), sdelta);
                    break;
                case "key":
                    OnViewerKey((string?)msg["key"] ?? "", (bool?)msg["ctrl"] ?? false, (bool?)msg["shift"] ?? false);
                    break;
                case "error":
                    _firstLoad.TrySetResult(false);
                    Status((string?)msg["message"] ?? L.T("Errore del visualizzatore"), true);
                    break;
                case "userInput":
                    CloseNotesOnUse();
                    break;
                case "log":
                    AppLog.Write("view: " + ((string?)msg["text"] ?? ""));
                    break;
                case "wheelLog":
                    AppLog.Write("wheel " + ((string?)msg["text"] ?? ""));
                    break;
                case "partLoaded":
                    _viewerWait?.Dispose(); _viewerWait = null;
                    AppLog.Write($"3D view: {(int?)msg["objects"] ?? 0} new objects added by the viewer in {((int?)msg["ms"] ?? 0) / 1000.0:0.0} s");
                    _ = PushSimplerMaterials();
                    break;
                case "contextLost":
                    AppLog.Write("viewer lost the video card (WebGL context lost)" + (_recovering ? " (already restarting)" : ""));
                    if (!_recovering && (DateTime.Now - _lastContextReload).TotalSeconds > 30)
                    {
                        _lastContextReload = DateTime.Now;
                        Status(L.T("La scheda video ha azzerato la vista 3D: la riavvio…"), true);
                        _webReady = false;
                        _recovering = true;
                        try { _web.CoreWebView2?.Reload(); } catch { }
                    }
                    break;
                case "partRetry":
                    // (1.76.50) objects whose pieces changed (a zone of a terrain that appeared or went empty): brought
                    // again whole, with their materials - only them, not the whole view
                    {
                        var rids = (msg["ids"] as JsonArray)?.Select(x => (string?)x ?? "").Where(x => x != "").ToList() ?? new List<string>();
                        AppLog.Write($"3D view: {rids.Count} objects with new pieces brought again whole");
                        if (rids.Count > 0 && !await AddPartToViewer(rids, replace: false)) { ForcePreviewReload("new pieces"); await RefreshScene(); }
                    }
                    break;
                case "needReload":
                    AppLog.Write("viewer asked for a new preparation: " + ((string?)msg["reason"] ?? "?"));
                    ForcePreviewReload("viewer: " + ((string?)msg["reason"] ?? "?"));
                    await RefreshScene();
                    break;
                case "viewPoint":
                    if (_viewPointWait != null && (string?)msg["id"] == _viewPointId) _viewPointWait.TrySetResult(msg);
                    break;
                case "lockedClick":
                    if (DialogBlocker() != null) ShowBlocked();
                    break;
                case "saveView":
                    SaveViewImage((string?)msg["data"] ?? "", (string?)msg["kind"] ?? "");
                    break;
                case "snapshot":
                    if (_snapshotWait != null && (string?)msg["id"] == _snapshotId)
                        _snapshotWait.TrySetResult((string?)msg["data"] ?? "");
                    break;
            }
        }

        TaskCompletionSource<JsonObject>? _viewPointWait;
        string _viewPointId = "";

        /// <summary>The surface in the middle of the view (cm), its normal, the camera position and distance.</summary>
        async Task<JsonObject?> AskViewPoint(double? x = null, double? y = null)
        {
            if (!_webReady) return null;
            _viewPointId = Guid.NewGuid().ToString("N");
            _viewPointWait = new TaskCompletionSource<JsonObject>(TaskCreationOptions.RunContinuationsAsynchronously);
            var wait = _viewPointWait;
            SendToWeb(new { type = "viewPoint", id = _viewPointId, x, y });
            var done = await Task.WhenAny(wait.Task, Task.Delay(2000));
            if (done != wait.Task)
            {
                // the view is busy (materials being prepared, one very long frame after a change of scene): before, the
                // drop was dropped without a word after 2 s (a decal dragged onto a wall, nothing placed, no message);
                // now it waits for the view, with «Occupato · attendi», and says so if the view never answers
                using (BeginBusy()) done = await Task.WhenAny(wait.Task, Task.Delay(20000));
                AppLog.Write(done == wait.Task ? "view point: the view answered late (busy)" : "view point: no answer from the view in 22 s");
                if (done != wait.Task) Status(L.T("La vista 3D non ha risposto: riprova tra un attimo"), true);
            }
            var r = done == wait.Task ? wait.Task.Result : null;
            if (_viewPointWait == wait) _viewPointWait = null;
            return r;
        }

        TaskCompletionSource<string>? _snapshotWait;
        string _snapshotId = "";

        /// <summary>JPEG (base64) of the real-time view, cropped to the image format: instant scene thumbnails.
        /// Null if the viewer does not answer (the engine then makes a quick path-traced one).</summary>
        async Task<string?> CaptureViewSnapshot(int w = 320, int h = 200, double q = 0.85)
        {
            if (!_webReady) return null;
            // (15/11, Luca: «Object reference not set…» opening the looks while the view was busy) two requests at the same
            // time shared these fields: the first to end put the wait to null and the other one fell on it. Each request keeps
            // its own wait; the fields only say which one the answer of the view is for (the last asked)
            var id = Guid.NewGuid().ToString("N");
            var wait = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
            _snapshotId = id;
            _snapshotWait = wait;
            SendToWeb(new { type = "snapshot", id, w, h, q });
            var done = await Task.WhenAny(wait.Task, Task.Delay(3000));
            var data = done == wait.Task ? wait.Task.Result : "";
            if (ReferenceEquals(_snapshotWait, wait)) _snapshotWait = null;
            return string.IsNullOrEmpty(data) ? null : data;
        }

        async Task PushViewportSize()
        {
            if (_api == null || _vpW < 10 || _vpH < 10) return;
            await Run(async api => { await api.Post("settings", new { viewport = new[] { _vpW, _vpH } }); });
        }

        // ---- real-time view contents
        // _structure/_structureSig describe what the viewer really shows: they change only when the viewer has it.
        bool _reloading;
        List<StructItem>? _pendingTarget;     // what the view will show when the preparation in progress ends
        bool _refreshAfterLoad;
        string _reloadOrigin = "action";            // what caused the reload: action | undo | redo | open
        readonly HashSet<string> _viewerIds = new();  // ids the viewer has a node for (shown or kept for undo)
        string? _loadedUrl;
        System.Diagnostics.Stopwatch? _viewerLoadClock;

        /// <summary>Exports the scene (in a second Blender, cancellable with Esc) and loads it in the real-time view.</summary>
        async Task<bool> ReloadPreview(string? frameId = null, List<StructItem>? target = null, string? targetSig = null)
        {
            if (_api == null || !_webReady) return false;
            if (_reloading) { CancelReloadQuietly(); }
            _reloading = true;
            _pendingTarget = target;
            _refreshAfterLoad = false;
            using var busy = BeginBusy();
            try
            {
                var title = L.T("Preparazione della vista 3D…");
                var esc = L.T("Esc per annullare");
                SendToWeb(new { type = "busy", text = title, detail = L.T("copia della scena") + " · " + esc });
                JsonObject? st = null;
                var exportClock = System.Diagnostics.Stopwatch.StartNew();
                using var waiting = EngineClient.Waiting(title.TrimEnd('…'));
                await Run(async api => { st = await api.Post("preview", new { }); });
                if (st == null) { SendToWeb(new { type = "busy", text = "" }); return false; }
                var jobId = (int?)st["id"] ?? 0;
                while ((string?)st["state"] == "running")
                {
                    await Task.Delay(300);
                    try { st = await _api.Get("preview/status"); } catch { continue; }
                    if (((int?)st["id"] ?? 0) != jobId) return false;              // a newer export took over
                    var phase = L.T((string?)st["phase"] ?? "");
                    var detail = (string?)st["detail"] ?? "";
                    var secs = (int)((double?)st["elapsed"] ?? 0);
                    if (_splash != null)
                        SplashStatus(phase != "" ? phase + (detail != "" ? " · " + L.T(detail) : "") : title, (double?)st["fraction"]);
                    SendToWeb(new
                    {
                        type = "busy", text = title, fraction = (double?)st["fraction"],
                        detail = (phase != "" && phase != L.T("Preparazione della vista 3D") ? phase + " · " : "") + (detail != "" ? L.T(detail) + " · " : "")
                                 + $"{secs / 60}:{secs % 60:00} · " + esc,
                    });
                }
                var state = (string?)st["state"] ?? "";
                if (state == "done") SplashStatus(L.T("Caricamento della vista 3D…"));
                if (state != "done")
                {
                    _firstLoad.TrySetResult(false);
                    SendToWeb(new { type = "busy", text = "" });
                    if (state == "error") Status((string?)st["error"] ?? L.T("Esportazione della vista non riuscita"), true);
                    return false;
                }
                var url = $"http://127.0.0.1:{_host.Port}/api/{(string?)st["url"]}";
                var bytes = (long?)st["bytes"] ?? 0;
                AppLog.Write($"3D view exported in {exportClock.Elapsed.TotalSeconds:0.0} s ({bytes / 1_000_000} MB)");
                _loadedUrl = url;
                _viewerLoadClock = System.Diagnostics.Stopwatch.StartNew();
                SendToWeb(new { type = "load", url, frame = frameId, big = bytes > 300L * 1024 * 1024 });
                if (target != null)
                {
                    _forceReload = false;
                    _loadedStructure = target;
                    _structure = target;
                    _structureSig = targetSig ?? "";
                    _viewerIds.Clear();
                    foreach (var x in target) _viewerIds.Add(x.Id);
                }
                UpdateGizmo();
                return true;
            }
            finally { _reloading = false; _pendingTarget = null; }
        }

        void CancelReloadQuietly()
        {
            try { _ = _api?.Post("preview/cancel", new { }); } catch { }
        }

        /// <summary>Esc during a long export of the view: stop it and go back to the state before the operation.</summary>
        async Task CancelReload()
        {
            if (!_reloading || _api == null) return;
            try { await _api.Post("preview/cancel", new { }); } catch { }
            SendToWeb(new { type = "busy", text = "" });
            var origin = _reloadOrigin;
            _reloadOrigin = "action";
            // wait for the reload loop to finish before restoring
            for (int i = 0; i < 50 && _reloading; i++) await Task.Delay(100);
            switch (origin)
            {
                case "undo": await Redo(); break;
                case "redo": await Undo(); break;
                case "action": if (_undoButton.IsEnabled) await Undo(); break;
            }
            Status(L.T("Operazione annullata: la vista è tornata allo stato precedente"));
        }

        /// <summary>
        /// Called after every scene refresh. Most changes are applied by the viewer in place (transforms, visibility,
        /// lights, deleted or duplicated objects, simple materials); a new export is made only for new geometry or
        /// textured materials.
        /// </summary>
        async Task SyncViewer(JsonObject sceneJson, string? frameId)
        {
            var objects = sceneJson["objects"] as JsonArray ?? new JsonArray();
            var sig = string.Join("|", objects.OfType<JsonObject>().Select(o =>
                $"{(string?)o["id"]}>{(string?)o["parent"]}:{o["materials"]?.ToJsonString()}{((string?)o["paintModel"] != null ? "#p" : "")}"));
            var structure = objects.OfType<JsonObject>().Select(o => new StructItem(
                (string?)o["id"] ?? "", (string?)o["parent"] ?? "", (string?)o["kind"] ?? "", o["materials"]?.ToJsonString() ?? "",
                (string?)o["paintModel"] ?? "", (bool?)o["paintRoot"] ?? false, (bool?)o["paintGen"] ?? false, (string?)o["protoKey"] ?? "")).ToList();
            if (sig == _structureSig && frameId == null)
            {
                SendToWeb(new { type = "sync", objects = SyncItems(objects) });
                return;
            }
            // a view is being prepared: if this change can be applied in place on top of it (a light, a deletion,
            // a material…) do not start the preparation again — apply it once the new view is loaded
            if (_reloading && frameId == null && _pendingTarget != null
                && CanUpdateInPlace(_pendingTarget, structure, _pendingTarget.Select(x => x.Id).ToHashSet(), out _))
            {
                _refreshAfterLoad = true;
                SendToWeb(new { type = "sync", objects = SyncItems(objects) });
                return;
            }
            string why;
            List<string> matChanged = new();
            List<string> newGeometry = new();
            if (frameId != null) why = "frame requested (import/open/start)";
            else if (_forceReload) why = "forced (" + _forceReason + ")";
            else if (_structure.Count == 0) why = "view empty";
            else if (!CanUpdateWithPart(_structure, structure, _viewerIds, out matChanged, out var r, out newGeometry)) why = r;
            else why = "";
            if (why == "")
            {
                bool ok = true;
                // new objects (a primitive, a model dropped in): only they are exported and added to the view
                if (newGeometry.Count > 0 && !await AddPartToViewer(newGeometry))
                {
                    ok = false;
                    why = "new objects could not be added to the view";
                }
                object[]? matItems = null;
                if (matChanged.Count > 0)
                {
                    // the viewer reuses the materials it already has (by name) and builds the others from their
                    // PBR values; for a textured material it does not have, it asks for a new export (needReload)
                    JsonObject? rm = null;
                    await Run(async api => { rm = await api.Post("realtime/materials", new { ids = matChanged.ToArray() }); });
                    var before = _structure.GroupBy(x => x.Id).ToDictionary(g => g.Key, g => g.First());
                    var list = new List<object>();
                    foreach (var id in matChanged)
                    {
                        if (rm?["objects"]?[id] is not JsonArray slots) continue;   // not a mesh: nothing to show
                        var oldNames = JsonNode.Parse(before.TryGetValue(id, out var b) && b.Materials != "" ? b.Materials : "[]") as JsonArray ?? new JsonArray();
                        var arr = new JsonArray();
                        for (int i = 0; i < slots.Count; i++)
                        {
                            var sl = (JsonObject)slots[i]!.DeepClone();
                            sl["old"] = i < oldNames.Count ? (string?)oldNames[i] : null;
                            arr.Add(sl);
                        }
                        list.Add(new { id, slots = arr });
                    }
                    matItems = list.ToArray();
                }
                if (ok)
                {
                    var had = _structure.Select(x => x.Id).ToHashSet();
                    var plainBefore = _structure.Where(x => x.PaintModel == "").Select(x => x.Id).ToHashSet();
                    var now = structure.Select(x => x.Id).ToHashSet();
                    SendToWeb(new
                    {
                        type = "structure",
                        objects = structure.Select(x => new { id = x.Id, parent = x.Parent, kind = x.Kind, isNew = !had.Contains(x.Id),
                                                              pm = x.PaintModel == "" ? null : x.PaintModel, pr = x.PaintRoot ? true : (bool?)null,
                                                              pg = x.PaintGen ? true : (bool?)null, pk = x.ProtoKey == "" ? null : x.ProtoKey }).ToArray(),
                        // (parts inside a library model have no node of their own in the view: the model is drawn
                        // from its prototype - only its root is removed, else the view asked for a whole new export)
                        removed = _structure.Where(x => !now.Contains(x.Id) && !(x.PaintModel != "" && !x.PaintRoot))
                                            .Select(x => x.Id).Distinct().ToArray(),
                        // library models closed again (MainWindow.OpenModel): their pieces leave the view, the model is
                        // drawn from its prototype again
                        closed = structure.Where(x => x.PaintRoot && plainBefore.Contains(x.Id))
                                          .Select(x => x.Id).ToArray(),
                    });
                    _structureSig = sig;
                    _structure = structure;
                    foreach (var x in structure) _viewerIds.Add(x.Id);
                    if (matItems != null) SendToWeb(new { type = "materials", items = matItems });
                    SendToWeb(new { type = "sync", objects = SyncItems(objects) });
                    return;
                }
            }
            if (why == "") why = "materials could not be read";
            AppLog.Write("3D view prepared again: " + why);
            SendToWeb(new { type = "sync", objects = SyncItems(objects) });   // re-applied by the viewer after the load
            await ReloadPreview(frameId, structure, sig);
        }

        /// <summary>PaintModel: a painted piece (Distribuisci) or a part of one; the view draws them from the library
        /// model with GPU instancing, they never need a new export. PaintRoot: the piece itself (a placeholder in the view).</summary>
        sealed record StructItem(string Id, string Parent, string Kind, string Materials, string PaintModel = "", bool PaintRoot = false, bool PaintGen = false, string ProtoKey = "");
        List<StructItem> _structure = new();
        static readonly HashSet<string> NoGeometryKinds = new() { "point", "spot", "area", "sun", "light", "group", "camera", "decal" };

        /// <summary>True when the viewer can show the change by itself: no new geometry (objects it already has,
        /// lights and groups are fine). matChanged lists the objects whose materials changed.</summary>
        static bool CanUpdateInPlace(List<StructItem> before, List<StructItem> after, HashSet<string> viewerIds, out List<string> matChanged)
            => CanUpdateInPlace(before, after, viewerIds, out matChanged, out _);

        static bool CanUpdateInPlace(List<StructItem> before, List<StructItem> after, HashSet<string> viewerIds, out List<string> matChanged, out string reason)
        {
            matChanged = new List<string>();
            reason = "";
            var old = before.GroupBy(x => x.Id).ToDictionary(g => g.Key, g => g.First());
            foreach (var x in after)
            {
                if (x.PaintModel != "") continue;          // painted pieces: drawn by the view from their model
                if (old.TryGetValue(x.Id, out var o))
                {
                    if (o.Kind != x.Kind) { reason = $"kind of {x.Id} changed ({o.Kind} -> {x.Kind})"; return false; }
                    if (o.Materials != x.Materials) matChanged.Add(x.Id);
                }
                else if (!NoGeometryKinds.Contains(x.Kind) && !viewerIds.Contains(x.Id))
                {
                    reason = $"new {x.Kind} {x.Id} not in the view";      // new geometry: export
                    return false;
                }
            }
            return true;
        }

        /// <summary>Like CanUpdateInPlace, but new geometry is allowed: it is listed in newGeometry (exported alone).</summary>
        static bool CanUpdateWithPart(List<StructItem> before, List<StructItem> after, HashSet<string> viewerIds, out List<string> matChanged,
                                      out string reason, out List<string> newGeometry)
        {
            matChanged = new List<string>();
            newGeometry = new List<string>();
            reason = "";
            var old = before.GroupBy(x => x.Id).ToDictionary(g => g.Key, g => g.First());
            foreach (var x in after)
            {
                if (x.PaintModel != "") continue;
                if (old.TryGetValue(x.Id, out var o))
                {
                    // a library model opened for its parts: until now drawn from its prototype, its pieces are exported
                    if (o.PaintModel != "") { newGeometry.Add(x.Id); continue; }
                    if (o.Kind != x.Kind) { reason = $"kind of {x.Id} changed ({o.Kind} -> {x.Kind})"; return false; }
                    if (o.Materials != x.Materials) matChanged.Add(x.Id);
                }
                else if (!NoGeometryKinds.Contains(x.Kind) && !viewerIds.Contains(x.Id))
                    newGeometry.Add(x.Id);
            }
            // a whole new scene (more new objects than old ones): one export of everything is better
            if (newGeometry.Count > 0 && newGeometry.Count > Math.Max(50, old.Count))
            {
                reason = $"{newGeometry.Count} new objects (whole view prepared again)";
                return false;
            }
            return true;
        }

        /// <summary>Exports only these new objects and adds them to the real-time view (seconds, not the whole scene).</summary>
        async Task<bool> AddPartToViewer(List<string> ids, bool replace = false)
        {
            if (_api == null) return false;
            var clock = System.Diagnostics.Stopwatch.StartNew();
            try
            {
                using var waiting = EngineClient.Waiting(L.T("Aggiunta alla vista 3D"));
                // (1.76.48) a new shape for objects already in the view: the view keeps its materials and textures
                // (replaceGeometry), so the engine sends the shape alone - no second Blender, no texture written
                var r = await _api.Post("preview/part", new { ids = ids.ToArray(), geometry = replace });
                var key = (string?)r["key"] ?? "";
                var state = (string?)r["state"] ?? "";
                bool pill = false;
                while (state == "running" && clock.Elapsed.TotalMinutes < 5)
                {
                    if (!pill && clock.ElapsedMilliseconds > 600)
                    {
                        pill = true;
                        SendToWeb(new { type = "busy", text = L.T("Aggiunta alla vista 3D…"), fraction = (double?)null, detail = "" });
                    }
                    await Task.Delay(150);
                    var st = await _api.Get("preview/part/status?k=" + Uri.EscapeDataString(key));
                    state = (string?)st["state"] ?? "";
                }
                if (pill) SendToWeb(new { type = "busy", text = "" });
                if (state == "empty")
                {
                    // (1.75.9) nothing among them is drawn in the view: nothing to add, the view stays as it is
                    AppLog.Write($"3D view: {ids.Count} new objects with nothing to draw: view kept");
                    return true;
                }
                if (state != "done")
                {
                    AppLog.Write($"3D view: {ids.Count} new objects not exported ({state}), whole view prepared again");
                    return false;
                }
                // (Luca: «il nome del gatto nella treeview è sparito ma il gatto no») the export takes seconds: an object deleted
                // meanwhile (a library model opened for its parts, then deleted) is not added - its pieces would stay in the
                // view as an object the list does not have
                var gone = _scene.ById.Count > 0 ? ids.Where(i => !_scene.ById.ContainsKey(i)).ToList() : new List<string>();
                if (gone.Count > 0)
                {
                    AppLog.Write($"3D view: {gone.Count} of the new objects were deleted while exported: not added ({string.Join(",", gone.Take(6))})");
                    ids = ids.Except(gone).ToList();
                    if (ids.Count == 0) return true;
                }
                _viewerWait?.Dispose();
                _viewerWait = EngineClient.Waiting(L.T("Aggiunta alla vista 3D"));     // (until the view says it has it)
                SendToWeb(new { type = "addPart", url = $"http://127.0.0.1:{_host.Port}/api/preview/part.glb?k={Uri.EscapeDataString(key)}", ids = ids.ToArray(), replace });
                AppLog.Write($"3D view: {ids.Count} {(replace ? "objects with a new geometry" : "new objects")} exported alone in {clock.Elapsed.TotalSeconds:0.0} s (the rest of the view kept)");
                return true;
            }
            catch (Exception e)
            {
                AppLog.Write("3D view: new objects not exported: " + e.Message);
                return false;
            }
        }

        static object[] SyncItems(JsonArray objects) => objects.OfType<JsonObject>()
            .Where(o => o["paintModel"] == null || ((bool?)o["paintRoot"] ?? false))    // parts inside a painted piece: nothing to show
            .Select(o => (bool?)o["paintRoot"] ?? false
                ? (object)new
                {
                    id = (string?)o["id"], kind = (string?)o["kind"], visible = (bool?)o["visible"] ?? true,
                    matrix = (o["matrixWorld"] as JsonArray)?.Select(v => (double?)v ?? 0).ToArray(),
                    pm = (string?)o["paintModel"], pr = true, parent = (string?)o["parent"], pg = (bool?)o["paintGen"] ?? false,
                    pk = (string?)o["protoKey"] ?? "",
                    pv = o["pivot"]?.DeepClone(),
                }
                : new
                {
                    id = (string?)o["id"], kind = (string?)o["kind"], visible = (bool?)o["visible"] ?? true,
                    matrix = (o["matrixWorld"] as JsonArray)?.Select(v => (double?)v ?? 0).ToArray(),
                    light = o["light"]?.DeepClone(),
                    rev = (string?)o["paintRev"],
                    ns = (bool?)o["noScatter"] ?? false,
                    dr = (string?)(o["decal"] as JsonObject)?["rev"],     // a decal: the view fetches its geometry when this changes
                    op = (bool?)o["openModel"] ?? false ? true : (bool?)null,   // a library model opened for its parts
                    pv = o["pivot"]?.DeepClone(),                                // pivot placed by hand (own space)
                }).ToArray();

        List<StructItem> _loadedStructure = new();
        bool _forceReload = true;
        string _forceReason = "start";
        /// <summary>«Ridisegna la vista»: the view lets go of everything it has and is prepared again as at the
        /// opening of the project (the prepared files in the cache make it quick).</summary>
        async Task RedrawView()
        {
            if (!_webReady || _api == null) return;
            AppLog.Write("redraw of the 3D view asked by the user");
            SendToWeb(new { type = "redraw" });
            ForcePreviewReload("redraw button");
            await RefreshScene();
            Status(L.T("Vista ridisegnata"));
        }

        void ForcePreviewReload(string reason = "") { _structureSig = ""; _forceReload = true; _forceReason = reason; }

        string ToolMode() => _tool == "scale" ? "scale" : "transform";

        /// <summary>Sends selection and tool to the viewer (the gizmo lives there).</summary>
        void UpdateGizmo()
        {
            if (_web == null) return;
            SendToWeb(new { type = "tool", mode = ToolMode() });
            // parts of a library model: the view draws the model from its prototype (merged by material), so the part
            // is shown by its materials (models split by material: exactly that part)
            string[]? parts = null;
            if (_selection.Count > 0 && _selection.All(id => ViewerId(id) != id))
            {
                var mats = new HashSet<string>();
                void Collect(SceneObject o) { foreach (var m in o.Materials) if (m != "") mats.Add(m); foreach (var c in o.Children) Collect(c); }
                foreach (var id in _selection) if (_scene.ById.TryGetValue(id, out var so)) Collect(so);
                parts = mats.Count > 0 ? mats.ToArray() : null;
            }
            SendToWeb(new { type = "select", ids = _selection.Select(ViewerId).Distinct().ToArray(), primary = ViewerId(_selected), parts });
        }

        Task FrameSelection()
        {
            SendToWeb(new { type = "frame", ids = _selection.ToArray() });
            return Task.CompletedTask;
        }

        // ================================================================ real-time / realistic

        bool _boxMode;

        /// <summary>"Sagome": clay view of the real-time view (matte grey, outlines, no textures, no lights).</summary>
        void SetBoxMode(bool on)
        {
            _boxMode = on;
            SendToWeb(new { type = "boxes", on });
            UpdateQualityDrop();
        }

        async Task SetRealistic(bool on)
        {
            // (1.75.9) the path tracing is a computation of the engine: asked for, it ends SmartView
            if (on && Settings.Load().SmartView) await SetSmartView(false);
            if (on) await FlushTerrainSculpt();         // (1.76.44: the path tracing with the terrain sculpted)
            _realistic = on;
            ShowViewMode(on ? 2 : _boxMode ? 0 : 1);
            UpdateQualityDrop();
            // the view switches at once; the engine follows (a path tracing pass in progress must not block the app)
            SendToWeb(new { type = "mode", realistic = on });
            if (!on)
            {
                try { await _api!.Post("live/off", new { }); } catch { }
                // (1.79.0) the exposure measured by the path tracing on the framing: the real-time view takes it too
                try { await LoadAmbience(); PushAmbienceToViewer(); } catch { }
            }
            else await Run(async api => { await api.Post("settings", new { live = on }); });
            if (on)
            {
                _progressTimer ??= new DispatcherTimer(TimeSpan.FromMilliseconds(250), DispatcherPriority.Background, async (s, e) => await PollProgress(), Dispatcher);
                _progressTimer.Start();
            }
            else
            {
                _progressTimer?.Stop();
                _progressBar.Width = 0;
                _progressLabel.Text = "";
            }
        }

        bool _progressPolling;
        async Task PollProgress()
        {
            if (_api == null || _progressPolling || !_realistic) return;
            _progressPolling = true;
            try { var fi = await _api.Get("frame/info"); if (_realistic) UpdateProgress(fi); }    // (switched back meanwhile: nothing)
            catch { }
            finally { _progressPolling = false; }
        }

        void UpdateProgress(JsonObject info)
        {
            int pass = (int?)info["pass"] ?? -1, passes = (int?)info["passes"] ?? 4;
            var samples = (int?)info["samples"] ?? 0;
            double frac = passes > 0 ? Math.Clamp((pass + 1) / (double)passes, 0, 1) : 0;
            _progressBar.Width = _progressTrack.Width * frac;
            _progressLabel.Text = pass < 0 ? "" : (frac >= 1 ? L.F("{0} campioni ✓", samples) : L.F("anteprima {0}/{1}", pass + 1, passes));
        }

        // ================================================================ undo / redo

        async Task Undo()
        {
            // (1.76.44) while sculpting the terrain: its last stroke, in the view (the engine has none of them yet)
            if (_tsPending > 0 && _puddleBrush && _brushLayer == "terrain") { SendToWeb(new { type = "terrainSculptUndo" }); return; }
            await HistoryStep("undo");
        }
        async Task Redo() => await HistoryStep("redo");

        async Task HistoryStep(string what)
        {
            if (_api == null) return;
            using var busy = BeginBusy();
            JsonObject? r = null;
            try { r = await _api.Post(what); }
            catch (EngineException ex) { Status(ex.Message); return; }
            catch (Exception ex) { Status(L.T("Errore di comunicazione con il motore: ") + ex.Message, true); return; }
            if ((string?)r["kind"] == "selection")
            {
                // a lost selection: selected again (nothing changed in the scene)
                var sel = r["select"] as JsonObject;
                var ids = (sel?["ids"] as JsonArray)?.Select(x => (string?)x ?? "").Where(x => x != "" && _scene.ById.ContainsKey(x)).ToList() ?? new List<string>();
                _restoringSelection = true;
                try { SetSelection(ids, (string?)sel?["primary"] ?? ""); }
                finally { _restoringSelection = false; }
                UpdateHistory(r);
                Status(what == "undo" ? L.F("Annullato: selezione ({0} oggetti)", ids.Count) : L.F("Ripetuto: selezione ({0} oggetti)", ids.Count));
                return;
            }
            if ((string?)r["kind"] == "file") ForcePreviewReload("undo of a file step");
            if ((string?)r["kind"] is "rainpaint" or "ambience") await LoadAmbience();
            if ((string?)r["kind"] == "dirtpaint") SendToWeb(new { type = "dirtRefresh" });   // (the painted dirt went back)   // (painted puddles: the view follows)   // a whole older copy of the scene: export it again
            _reloadOrigin = what;
            // the panels show the values as they are now: the material in the editor read again, and the right panel
            // drawn again after the Ambiente is reloaded (RefreshScene draws it before)
            if (_rightPanel == "material" && _matName != "") await LoadMaterial();
            if ((string?)r["kind"] == "meshes") await ViewNewGeometry(Ids(r["geometry"]), (string?)r["label"] ?? "");   // (1.75.52) Ottimizza poligoni undone/again
            else await RefreshScene();
            if (_rightPanel == "landscape") await LoadTerrain();      // (1.76.0) the terrain as it is now
            // a material step: the real-time view still had the material as it was (same name, so the scene list
            // did not change): it is drawn again (undo of «Converti in materiale Simpler» left it white)
            if (r["materials"] is JsonArray mats)
                foreach (var m in mats.Select(x => (string?)x ?? "").Where(x => x != "").Distinct())
                    await PushMaterialToViewer(m);
            RenderProps();
            _reloadOrigin = "action";
            Status(L.T(what == "undo" ? L.T("Annullato: ") : L.T("Ripetuto: ")) + L.T((string?)r["label"] ?? ""));
            if (_paintGroup != "") await LoadPaintGroup(_scene.ById.ContainsKey(_paintGroup) ? _paintGroup : "");   // its strokes went back too
            if (((int?)_camView?["ecoTotal"] ?? 0) > 0 || _scene.ById.Values.Any(o => o.Eco == "group")) await LoadCamView();   // (an ecosystem back or gone)
        }

        void UpdateHistory(JsonObject h)
        {
            bool canUndo = (bool?)h["canUndo"] ?? false, canRedo = (bool?)h["canRedo"] ?? false;
            _undoButton.IsEnabled = canUndo;
            _redoButton.IsEnabled = canRedo;
            _undoButton.Opacity = canUndo ? 1 : 0.4;
            _redoButton.Opacity = canRedo ? 1 : 0.4;
            _undoButton.ToolTip = canUndo ? L.F("Annulla: {0} (Ctrl+Z)", L.T((string?)h["undoLabel"] ?? "")) : L.T("Niente da annullare");
            _redoButton.ToolTip = canRedo ? L.F("Ripeti: {0} (Ctrl+Y)", L.T((string?)h["redoLabel"] ?? "")) : L.T("Niente da ripetere");
        }

        // ================================================================ keyboard coming from the web view

        void OnViewerKey(string key, bool ctrl, bool shift)
        {
            if (_ideasPanel != null) return;        // (a page of rodluc.com is open over the hidden scene view: its keys are the page's)
            if (BusyKey(key.ToLowerInvariant() == "escape")) return;
            switch (key.ToLowerInvariant())
            {
                case "z" when ctrl && shift: _ = Redo(); break;
                case "z" when ctrl: _ = Undo(); break;
                case "y" when ctrl: _ = Redo(); break;
                case "a" when ctrl: SelectAll(); break;
                case "w" when !ctrl: SetTool("move"); break;
                case "e" when !ctrl: SetTool("rotate"); break;
                case "r" when !ctrl: SetTool("scale"); break;
                case "b" when !ctrl: SetTool(_tool == "paint" ? "move" : "paint"); break;
                case "f" when !ctrl: _ = FrameSelection(); break;
                case "delete": _ = DeleteSelected(); break;
                case "d" when ctrl: _ = DuplicateSelected(); break;
                case "g" when ctrl: _ = GroupSelected(); break;
                case "c" when ctrl: CopySelected(); break;
                case "v" when ctrl: _ = PasteClipboard(); break;
                case "s" when ctrl && shift: _ = SaveProject(true); break;
                case "s" when ctrl: _ = SaveProject(false); break;
                case "o" when ctrl: _ = OpenProject(); break;
                case "n" when ctrl: _ = NewProject(); break;
                case "i" when ctrl: _ = ImportModel(); break;
                case "escape" when Painting: SetTool("move"); break;
                case "escape": Select(""); break;
                case " " when !ctrl: _ = SetRealistic(!_realistic); break;
            }
        }

        // ================================================================ drag & drop of model files (on the scene panel)

        async Task OnFileDrop(DragEventArgs e)
        {
            if (!e.Data.GetDataPresent(DataFormats.FileDrop) || e.Data.GetData(DataFormats.FileDrop) is not string[] files) return;
            await ImportPaths(files);
        }
    }
}
