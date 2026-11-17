using System;
using System.Diagnostics;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;

namespace Simpler
{
    /// <summary>"Risorse" panel: graphics card (memory, load, temperature), processor, memory, and whether the
    /// textures of the scene fit in the video memory. Updated every second while it is open.</summary>
    public sealed partial class MainWindow
    {
        static readonly Geometry ResourcesIcon = Geometry.Parse("M7 7h10v10H7z M9.5 9.5h5v5h-5z M9 3v4 M15 3v4 M9 17v4 M15 17v4 M3 9h4 M3 15h4 M17 9h4 M17 15h4");
        Button _resourcesPanelButton = null!;
        DispatcherTimer? _resourcesTimer;
        bool _resourcesPolling;
        Action<JsonObject?>? _resourcesUpdate;
        ulong _lastIdle, _lastKernel, _lastUser;

        [StructLayout(LayoutKind.Sequential)]
        struct FileTime { public uint Low, High; public ulong Value => ((ulong)High << 32) | Low; }

        [StructLayout(LayoutKind.Sequential)]
        struct MemoryStatus
        {
            public uint Length, MemoryLoad;
            public ulong TotalPhys, AvailPhys, TotalPageFile, AvailPageFile, TotalVirtual, AvailVirtual, AvailExtendedVirtual;
        }

        [DllImport("kernel32.dll")] static extern bool GetSystemTimes(out FileTime idle, out FileTime kernel, out FileTime user);
        [DllImport("kernel32.dll")] static extern bool GlobalMemoryStatusEx(ref MemoryStatus status);

        double? CpuLoad()
        {
            if (!GetSystemTimes(out var i, out var k, out var u)) return null;
            ulong di = i.Value - _lastIdle, dk = k.Value - _lastKernel, du = u.Value - _lastUser;
            bool first = _lastIdle == 0;
            (_lastIdle, _lastKernel, _lastUser) = (i.Value, k.Value, u.Value);
            var total = dk + du;          // kernel time includes idle time
            if (first || total == 0) return null;
            return Math.Clamp(1.0 - (double)di / total, 0, 1);
        }

        static (ulong total, ulong used)? Ram()
        {
            var m = new MemoryStatus { Length = (uint)Marshal.SizeOf<MemoryStatus>() };
            if (!GlobalMemoryStatusEx(ref m)) return null;
            return (m.TotalPhys, m.TotalPhys - m.AvailPhys);
        }

        static string Gb(double bytes) => bytes >= 1024.0 * 1024 * 1024 ? $"{bytes / (1024.0 * 1024 * 1024):0.0} GB" : $"{bytes / (1024.0 * 1024):0} MB";

        /// <summary>A labelled bar: returns the setter (fraction 0-1 or null, text on the right).</summary>
        Action<double?, string> Meter(StackPanel parent, string label, string tip)
        {
            var row = new Grid { Margin = new Thickness(0, 0, 0, 10), ToolTip = tip };
            row.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            row.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            var name = Theme.Label(label, 12.5, Theme.TextSoft);
            var value = Theme.Label("–", 12, Theme.TextMuted);
            value.FontFamily = Theme.Mono;
            value.HorizontalAlignment = HorizontalAlignment.Right;
            row.Children.Add(name);
            row.Children.Add(value);
            var track = new Border { Height = 6, CornerRadius = new CornerRadius(3), Background = Theme.B("#1A2842"), Margin = new Thickness(0, 6, 0, 0), ClipToBounds = true };
            var fill = new Border { Height = 6, CornerRadius = new CornerRadius(3), HorizontalAlignment = HorizontalAlignment.Left, Width = 0, Background = Theme.B(Theme.Accent) };
            track.Child = fill;
            Grid.SetRow(track, 1);
            row.Children.Add(track);
            parent.Children.Add(row);
            return (f, text) =>
            {
                value.Text = text;
                var w = track.ActualWidth;
                fill.Width = f is double v && w > 0 ? Math.Clamp(v, 0, 1) * w : 0;
                fill.Background = Theme.B(f is double x && x > 0.9 ? Theme.Danger : (f is double y && y > 0.7 ? Theme.Warm : Theme.Accent));
            };
        }

        void RenderResourcesPanel()
        {
            var head = new StackPanel();
            var top = new DockPanel();
            var close = Theme.Button(L.T("Chiudi"), Theme.Kind.Ghost, L.T("Torna alle proprietà dell'oggetto"));
            close.Click += async (_, __) => await ShowRightPanel("");
            DockPanel.SetDock(close, Dock.Right);
            top.Children.Add(close);
            top.Children.Add(Theme.Caption(L.T("Risorse")));
            head.Children.Add(top);
            head.Children.Add(HintSmall(L.T("Aggiornato ogni secondo. Se la memoria della scheda video è piena, Cycles usa la memoria del computer e diventa molto più lento.")));
            _props.Children.Add(Theme.Card(head, 16));

            var g = new StackPanel();
            g.Children.Add(SectionTitle(L.T("Scheda video")));
            var gpuName = Theme.Label("", 12, Theme.TextFaint);
            gpuName.Margin = new Thickness(0, -4, 0, 10);
            g.Children.Add(gpuName);
            if (GpuRating.Last is { } rating)
            {
                var rate = Theme.Label(L.F("Potenza per Simpler: {0}% — {1}", rating.Score, rating.Verdict), 12, Theme.TextSoft);
                rate.TextWrapping = TextWrapping.Wrap;
                rate.Margin = new Thickness(0, -4, 0, 10);
                rate.ToolTip = rating.Detail + "\n" + L.T("100% = scheda per scene molto grandi (es. RTX 4090, 24 GB). Calcolato da potenza di calcolo, ray tracing e memoria video, senza test.");
                g.Children.Add(rate);
            }
            var vram = Meter(g, L.T("Memoria video"), L.T("Memoria della scheda video usata da tutti i programmi"));
            var load = Meter(g, L.T("Utilizzo"), L.T("Quanto sta lavorando la scheda video"));
            var temp = Theme.Label("", 12, Theme.TextFaint);
            g.Children.Add(temp);
            var device = Theme.Label("", 12, Theme.TextFaint);
            g.Children.Add(device);
            // who uses the video memory: the number above is the whole card, every program together
            var who = new StackPanel { Margin = new Thickness(0, 12, 0, 0) };
            who.Children.Add(Theme.Label(L.T("Chi usa la memoria video"), 12.5, Theme.TextSoft));
            var whoRows = new StackPanel { Margin = new Thickness(0, 6, 0, 0) };
            whoRows.Children.Add(Theme.Label(L.T("Lettura…"), 12, Theme.TextFaint));
            who.Children.Add(whoRows);
            g.Children.Add(who);
            _vramRows = whoRows;
            _ = UpdateVramByProcess();
            _props.Children.Add(Theme.Card(g, 16));

            var c = new StackPanel();
            c.Children.Add(SectionTitle(L.T("Computer")));
            var cpu = Meter(c, L.T("Processore"), L.T("Utilizzo di tutti i core"));
            var ram = Meter(c, L.T("Memoria"), L.T("Memoria del computer usata da tutti i programmi"));
            var engineRam = Theme.Label("", 12, Theme.TextFaint);
            c.Children.Add(engineRam);
            _props.Children.Add(Theme.Card(c, 16));

            var t = new StackPanel();
            t.Children.Add(SectionTitle(L.T("Texture della scena")));
            var texInfo = new TextBlock { TextWrapping = TextWrapping.Wrap, FontSize = 12.5, Foreground = Theme.B(Theme.TextSoft), LineHeight = 19, Text = L.T("Calcolo…") };
            t.Children.Add(texInfo);
            _props.Children.Add(Theme.Card(t, 16));

            _ = Task.Run(async () =>
            {
                JsonObject? e = null;
                try { if (_api != null) e = await _api.Get("textures/estimate"); } catch { }
                await Dispatcher.InvokeAsync(() =>
                {
                    if (e == null) { texInfo.Text = L.T("Non disponibile"); return; }
                    double full = (double?)e["full"] ?? 0, k2 = (double?)e["px2048"] ?? 0, k1 = (double?)e["px1024"] ?? 0;
                    int count = (int?)e["count"] ?? 0, auto = (int?)e["auto"] ?? 0;
                    double total = (double?)e["gpu"]?["total"] ?? 0;
                    var lines = L.F("{0} texture. Memoria video stimata: {1} originali · {2} a 2048 pixel · {3} a 1024 pixel.", count, Gb(full), Gb(k2), Gb(k1));
                    if (total > 0)
                        lines += "\n\n" + (full <= total * 0.6
                            ? L.F("Le texture originali stanno nella memoria video ({0}).", Gb(total))
                            : L.F("Le texture originali non stanno nella memoria video ({0}): il render finale in Auto userà copie a {1} pixel.", Gb(total), auto == 0 ? "—" : auto.ToString()));
                    texInfo.Text = lines;
                });
            });

            _resourcesUpdate = gi =>
            {
                var gpu = gi?["gpu"] as JsonObject;
                if (gpu != null)
                {
                    double tot = (double?)gpu["total"] ?? 0, used = (double?)gpu["used"] ?? 0;
                    gpuName.Text = (string?)gpu["name"] ?? "";
                    vram(tot > 0 ? used / tot : null, tot > 0 ? $"{Gb(used)} / {Gb(tot)}" : "–");
                    var l = (int?)gpu["load"];
                    load(l / 100.0, l is int li ? $"{li} %" : "–");
                    temp.Text = gpu["temperature"] is JsonNode tn ? L.F("Temperatura {0} °C", (int?)tn ?? 0) : "";
                }
                else
                {
                    gpuName.Text = L.T("Scheda NVIDIA non rilevata: dati della scheda video non disponibili");
                    vram(null, "–"); load(null, "–");
                }
                device.Text = L.F("Motore di render: {0}", DeviceLabel((string?)gi?["device"]));
                var cl = CpuLoad();
                cpu(cl, cl is double cv ? $"{cv * 100:0} %" : "…");
                if (Ram() is var (rt, ru)) ram((double)ru / rt, $"{Gb(ru)} / {Gb(rt)}");
                try
                {
                    var pid = _host.ProcessId;
                    if (pid > 0) engineRam.Text = L.F("Blender (motore di Simpler): {0}", Gb(Process.GetProcessById(pid).WorkingSet64));
                }
                catch { }
            };
            _resourcesTimer ??= new DispatcherTimer(TimeSpan.FromSeconds(1), DispatcherPriority.Background, async (_, __) => await ResourcesTick(), Dispatcher);
            _resourcesTimer.Start();
            _ = ResourcesTick();
        }

        // ---------------------------------------------------------------- video memory per program
        // Windows counts it per process ("GPU Process Memory", the numbers of Task Manager); read through WMI, whose
        // class names are the same in every language of Windows.
        StackPanel? _vramRows;
        DateTime _vramAt = DateTime.MinValue;
        bool _vramBusy;

        async Task UpdateVramByProcess()
        {
            if (_vramBusy || _vramRows == null) return;
            _vramBusy = true;
            _vramAt = DateTime.Now;
            try
            {
                var rows = await Task.Run<System.Collections.Generic.Dictionary<int, double>?>(() =>
                {
                    var psi = new ProcessStartInfo("powershell.exe",
                        "-NoProfile -NonInteractive -Command \"Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUProcessMemory | ForEach-Object { $_.Name + '|' + $_.DedicatedUsage }\"")
                    { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true };
                    using var p = Process.Start(psi);
                    if (p == null) return null;
                    var text = p.StandardOutput.ReadToEnd();
                    p.WaitForExit(8000);
                    // one counter per program AND per video card ("pid_<pid>_luid_<card>_phys_<n>"): only the card that
                    // renders counts
                    var rowsAll = new System.Collections.Generic.List<(int pid, string luid, double bytes)>();
                    foreach (var line in text.Split('\n'))
                    {
                        var parts = line.Trim().Split('|');
                        if (parts.Length != 2 || !parts[0].StartsWith("pid_")) continue;
                        var bits = parts[0].Split('_');
                        if (bits.Length < 3 || !int.TryParse(bits[1], out var pid) || !double.TryParse(parts[1], out var bytes) || bytes <= 0) continue;
                        var li = parts[0].IndexOf("_luid_", StringComparison.Ordinal);
                        var pi = parts[0].IndexOf("_phys_", StringComparison.Ordinal);
                        var luid = li >= 0 ? (pi > li ? parts[0].Substring(li + 6, pi - li - 6) : parts[0].Substring(li + 6)) : "";
                        rowsAll.Add((pid, luid, bytes));
                    }
                    var enginePid = _host.ProcessId;
                    // the card of the render engine (where Blender has the most), else the one with the most in use
                    var card = rowsAll.Where(r => r.pid == enginePid).GroupBy(r => r.luid).OrderByDescending(gp => gp.Sum(r => r.bytes)).Select(gp => gp.Key).FirstOrDefault()
                               ?? rowsAll.GroupBy(r => r.luid).OrderByDescending(gp => gp.Sum(r => r.bytes)).Select(gp => gp.Key).FirstOrDefault();
                    var perPid = new System.Collections.Generic.Dictionary<int, double>();
                    foreach (var (pid, luid, bytes) in rowsAll)
                        if (card == null || luid == card)
                            perPid[pid] = (perPid.TryGetValue(pid, out var had) ? had : 0) + bytes;
                    return perPid;
                });
                if (rows == null || _vramRows == null) return;
                _vramRows.Children.Clear();
                var enginePid = _host.ProcessId;
                var self = Environment.ProcessId;
                var named = new System.Collections.Generic.List<(string name, double bytes, bool ours)>();
                double others = 0;
                foreach (var kv in rows.OrderByDescending(kv => kv.Value))
                {
                    int pid = kv.Key; double bytes = kv.Value;
                    string pname;
                    try { pname = Process.GetProcessById(pid).ProcessName; } catch { pname = "?"; }
                    var low = pname.ToLowerInvariant();
                    // Windows' compositor (dwm) and csrss are charged with the window images of every other program:
                    // memory allocated once and counted again in them (Microsoft, DirectX blog "GPUs in the Task
                    // Manager"). dwm showed 7.3 GB with 5.2 GB used on the card in all: left out of the list
                    if (low == "dwm" || low == "csrss") continue;
                    string label; bool ours = true;
                    if (pid == enginePid) label = L.T("Simpler · motore di render (Blender)");
                    else if (low == "blender") label = L.T("Simpler · anteprime e miniature (Blender)");
                    else if (pid == self) label = L.T("Simpler · finestra");
                    else if (low.StartsWith("msedgewebview2")) label = L.T("Vista 3D in tempo reale (WebView2)") + "*";
                    else { label = pname; ours = false; }
                    if (named.Count < 8 && bytes > 64 * 1024 * 1024) named.Add((label, bytes, ours));
                    else others += bytes;
                }
                foreach (var (name, bytes, ours) in named)
                {
                    var row = new DockPanel { Margin = new Thickness(0, 1, 0, 1) };
                    var v = Theme.Label(Gb(bytes), 12, ours ? Theme.TextSoft : Theme.TextMuted);
                    v.FontFamily = Theme.Mono;
                    DockPanel.SetDock(v, Dock.Right);
                    row.Children.Add(v);
                    var n = Theme.Label(name, 12, ours ? Theme.TextSoft : Theme.TextMuted);
                    n.TextTrimming = TextTrimming.CharacterEllipsis;
                    row.Children.Add(n);
                    _vramRows.Children.Add(row);
                }
                if (others > 0)
                {
                    var row = new DockPanel { Margin = new Thickness(0, 1, 0, 1) };
                    var v = Theme.Label(Gb(others), 12, Theme.TextFaint);
                    v.FontFamily = Theme.Mono;
                    DockPanel.SetDock(v, Dock.Right);
                    row.Children.Add(v);
                    row.Children.Add(Theme.Label(L.T("altri programmi"), 12, Theme.TextFaint));
                    _vramRows.Children.Add(row);
                }
                var note = Theme.Label(L.T("Memoria per programma, come in Gestione attività: la memoria condivisa conta in ogni programma che la usa, il totale vero è la barra sopra. Windows (dwm, csrss) non è elencato: conta anche le finestre degli altri programmi. * WebView2 può essere anche di altri programmi (Edge, Teams…)."), 11, Theme.TextFaint);
                note.TextWrapping = TextWrapping.Wrap;
                note.Margin = new Thickness(0, 6, 0, 0);
                _vramRows.Children.Add(note);
            }
            catch
            {
                if (_vramRows != null) { _vramRows.Children.Clear(); _vramRows.Children.Add(Theme.Label(L.T("Non disponibile su questo PC"), 12, Theme.TextFaint)); }
            }
            finally { _vramBusy = false; }
        }

        async Task ResourcesTick()
        {
            if (_rightPanel != "resources") { _resourcesTimer?.Stop(); return; }
            if (_resourcesPolling) return;
            _resourcesPolling = true;
            try
            {
                JsonObject? gi = null;
                try { if (_api != null) gi = await _api.Get("gpu"); } catch { }
                _resourcesUpdate?.Invoke(gi);
                if ((DateTime.Now - _vramAt).TotalSeconds > 4) _ = UpdateVramByProcess();
            }
            finally { _resourcesPolling = false; }
        }
    }
}
