using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;

namespace Simpler
{
    /// <summary>Error reported by the engine, already in Italian and meant for the user.</summary>
    public sealed class EngineException : Exception
    {
        public EngineException(string message) : base(message) { }
    }

    /// <summary>Starts the private Blender process that runs the Simpler engine and stops it on exit.</summary>
    public sealed class EngineHost : IDisposable
    {
        public int Port { get; private set; }
        public string BlenderPath { get; private set; } = "";
        public string EngineScript { get; private set; } = "";
        public string LogPath { get; }
        public int ProcessId => _process is { HasExited: false } p ? p.Id : 0;
        Process? _process;
        readonly StringBuilder _tail = new StringBuilder();
        bool _stopping, _started;

        /// <summary>The engine ended while Simpler was using it (out of memory, killed, crash).</summary>
        public event Action? Died;
        public long MemoryLimitBytes { get; private set; }

        // ---- memory cap: Blender and the processes it starts (previews, exports) live in a Windows job object
        // with a memory limit. A request too big for the computer (a voxel remesh of a 4 km ground) then makes
        // Blender fail and stop instead of filling the RAM and freezing Windows.
        [System.Runtime.InteropServices.DllImport("kernel32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
        static extern IntPtr CreateJobObject(IntPtr attr, string? name);
        [System.Runtime.InteropServices.DllImport("kernel32.dll")]
        static extern bool SetInformationJobObject(IntPtr job, int infoClass, ref JOBOBJECT_EXTENDED_LIMIT_INFORMATION info, uint size);
        [System.Runtime.InteropServices.DllImport("kernel32.dll")]
        static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
        [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
        struct JOBOBJECT_BASIC_LIMIT_INFORMATION
        {
            public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
            public uint LimitFlags;
            public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
            public uint ActiveProcessLimit;
            public UIntPtr Affinity;
            public uint PriorityClass, SchedulingClass;
        }
        [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
        struct IO_COUNTERS { public ulong R, W, O, RB, WB, OB; }
        [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
        struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        {
            public JOBOBJECT_BASIC_LIMIT_INFORMATION Basic;
            public IO_COUNTERS Io;
            public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
        }
        IntPtr _job;

        void LimitMemory(Process p)
        {
            try
            {
                if (!OperatingSystem.IsWindows()) return;
                long total = GC.GetGCMemoryInfo().TotalAvailableMemoryBytes;      // physical memory of the computer
                if (total <= 0) return;
                // three quarters of the RAM, and at least 3 GB left to Windows and Simpler
                long limit = Math.Min((long)(total * 0.75), total - 3L * 1024 * 1024 * 1024);
                if (limit < 2L * 1024 * 1024 * 1024) return;
                _job = CreateJobObject(IntPtr.Zero, null);
                if (_job == IntPtr.Zero) return;
                var info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
                info.Basic.LimitFlags = 0x00000200 /* JOB_MEMORY */ | 0x00002000 /* KILL_ON_JOB_CLOSE */;
                info.JobMemoryLimit = (UIntPtr)(ulong)limit;
                if (!SetInformationJobObject(_job, 9, ref info, (uint)System.Runtime.InteropServices.Marshal.SizeOf<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>())) return;
                if (AssignProcessToJobObject(_job, p.Handle)) MemoryLimitBytes = limit;
            }
            catch { }
        }

        /// <summary>Stops the engine at once (it is stuck in a computation that cannot be interrupted).</summary>
        public void Kill()
        {
            try { if (_process != null && !_process.HasExited) _process.Kill(true); } catch { }
        }

        public EngineHost()
        {
            var dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Simpler");
            Directory.CreateDirectory(dir);
            LogPath = Path.Combine(dir, AppInstance.Prefix + "engine.log");
        }

        /// <summary>engine\start_engine.py next to Simpler.exe (installed) or in a parent folder (development).</summary>
        public static string? FindEngineScript()
        {
            var dir = new DirectoryInfo(AppContext.BaseDirectory);
            for (int i = 0; i < 8 && dir != null; i++, dir = dir.Parent)
            {
                var candidate = Path.Combine(dir.FullName, "engine", "start_engine.py");
                if (File.Exists(candidate)) return candidate;
            }
            return null;
        }

        public const string BlenderVersion = "5.2";

        /// <summary>Bundled copy first, then the saved setting, then a standard Blender 5.2 install.
        /// Only 5.2: Simpler is tuned and tested on that version (19/11: before, any "Blender 5*" was taken, newest first,
        /// so a PC with 5.3 installed started an engine nobody had tried).</summary>
        public static string? FindBlender()
        {
            var bundled = Path.Combine(AppContext.BaseDirectory, "blender", "blender.exe");
            if (File.Exists(bundled)) return bundled;
            var saved = Settings.Load().BlenderPath;
            if (!string.IsNullOrEmpty(saved) && File.Exists(saved)) return saved;
            foreach (var root in new[] { Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), @"C:\Program Files" })
            {
                var foundation = Path.Combine(root, "Blender Foundation");
                if (!Directory.Exists(foundation)) continue;
                var best = Directory.GetDirectories(foundation, "Blender " + BlenderVersion + "*")
                    .OrderByDescending(d => d, StringComparer.OrdinalIgnoreCase)
                    .Select(d => Path.Combine(d, "blender.exe"))
                    .FirstOrDefault(File.Exists);
                if (best != null) return best;
            }
            return null;
        }

        static int FreePort()
        {
            var l = new TcpListener(IPAddress.Loopback, 0);
            l.Start();
            int port = ((IPEndPoint)l.LocalEndpoint).Port;
            l.Stop();
            return port;
        }

        public async Task StartAsync(string blender, string script, CancellationToken ct = default)
        {
            BlenderPath = blender;
            EngineScript = script;
            Port = FreePort();
            var psi = new ProcessStartInfo
            {
                FileName = blender,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8,
                WorkingDirectory = Path.GetDirectoryName(script)!,
            };
            foreach (var a in new[] { "--background", "--factory-startup", "--python", script, "--",
                                      "--port", Port.ToString(), "--parent-pid", Environment.ProcessId.ToString(), "--lang", L.Lang })
                psi.ArgumentList.Add(a);

            var ready = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            // the previous session's log is kept as engine-prev.log (to compare two runs)
            try { if (File.Exists(LogPath)) File.Copy(LogPath, Path.Combine(Path.GetDirectoryName(LogPath)!, AppInstance.Prefix + "engine-prev.log"), true); } catch { }
            // (the engine of a session that ended badly may still be closing and hold engine.log: a log of another name
            // for this run - the app starts all the same, never a window about a file)
            StreamWriter log;
            try { log = new StreamWriter(new FileStream(LogPath, FileMode.Create, FileAccess.Write, FileShare.ReadWrite), Encoding.UTF8) { AutoFlush = true }; }
            catch (IOException)
            {
                var alt = Path.Combine(Path.GetDirectoryName(LogPath)!, AppInstance.Prefix + "engine-" + Environment.ProcessId + ".log");
                log = new StreamWriter(new FileStream(alt, FileMode.Create, FileAccess.Write, FileShare.ReadWrite), Encoding.UTF8) { AutoFlush = true };
                AppLog.Write("engine.log is in use by another process (the engine of the session before): this run writes " + Path.GetFileName(alt));
            }
            void OnLine(string? line)
            {
                if (line == null) return;
                lock (log) log.WriteLine(line);
                lock (_tail) { _tail.AppendLine(line); if (_tail.Length > 8000) _tail.Remove(0, _tail.Length - 8000); }
                if (line.StartsWith("SIMPLER_READY")) ready.TrySetResult(true);
            }
            _process = new Process { StartInfo = psi, EnableRaisingEvents = true };
            _process.OutputDataReceived += (_, e) => OnLine(e.Data);
            _process.ErrorDataReceived += (_, e) => OnLine(e.Data);
            _process.Exited += (_, __) =>
            {
                ready.TrySetException(new EngineException(L.T("Il motore si è chiuso all'avvio.\n\n") + Tail()));
                if (_started && !_stopping) Died?.Invoke();
            };
            _process.Start();
            LimitMemory(_process);
            // below normal: Blender may use every core during imports and renders, Windows and the app must stay responsive
            try { _process.PriorityClass = ProcessPriorityClass.BelowNormal; } catch { }
            // (1.78.4) ...but at full speed when Simpler is not in front: Windows would move its work to the slow cores
            FullSpeed.Apply(_process);
            FullSpeed.Apply(Process.GetCurrentProcess());
            _process.BeginOutputReadLine();
            _process.BeginErrorReadLine();

            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
            timeout.CancelAfter(TimeSpan.FromSeconds(120));
            using (timeout.Token.Register(() => ready.TrySetException(new EngineException(L.T("Il motore non risponde dopo 2 minuti.\n\n") + Tail()))))
                await ready.Task.ConfigureAwait(false);
            _started = true;
        }

        public string Tail() { lock (_tail) return _tail.ToString(); }

        public void Dispose()
        {
            _stopping = true;
            try
            {
                if (_process != null && !_process.HasExited)
                {
                    using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };
                    try { http.PostAsync($"http://127.0.0.1:{Port}/api/shutdown", new StringContent("{}")).Wait(2000); } catch { }
                    if (!_process.WaitForExit(3000)) _process.Kill(true);
                }
            }
            catch { }
        }
    }

    /// <summary>(1.78.4, Luca: «se tolgo il focus da Simpler … rallenta tantissimo») Windows 11 runs a process with no
    /// window in front at a low quality of service (slow cores, lower clock on processors with two kinds of cores):
    /// the engine has no window at all. Power throttling off («high QoS») for Simpler and the engine; the engine's
    /// jobs ask the same (engine/simpler/fullspeed.py). The priority stays as it is.</summary>
    internal static class FullSpeed
    {
        [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
        struct PowerThrottlingState { public uint Version, ControlMask, StateMask; }
        [System.Runtime.InteropServices.DllImport("kernel32.dll", SetLastError = true)]
        static extern bool SetProcessInformation(IntPtr process, int infoClass, ref PowerThrottlingState info, uint size);
        const int ProcessPowerThrottling = 4;
        const uint ExecutionSpeed = 0x1, IgnoreTimerResolution = 0x4;

        public static bool Apply(Process p)
        {
            try
            {
                if (!OperatingSystem.IsWindows() || p.HasExited) return false;
                var st = new PowerThrottlingState { Version = 1, ControlMask = ExecutionSpeed | IgnoreTimerResolution, StateMask = 0 };
                return SetProcessInformation(p.Handle, ProcessPowerThrottling, ref st,
                    (uint)System.Runtime.InteropServices.Marshal.SizeOf<PowerThrottlingState>());
            }
            catch { return false; }
        }
    }

    /// <summary>Typed access to the engine's local JSON API.</summary>
    public sealed class EngineClient
    {
        readonly HttpClient _http;
        public EngineClient(int port)
        {
            _http = new HttpClient { BaseAddress = new Uri($"http://127.0.0.1:{port}/api/"), Timeout = Timeout.InfiniteTimeSpan };
            // the engine's server closes every connection after the answer: never reuse a pooled one
            _http.DefaultRequestHeaders.ConnectionClose = true;
        }

        /// <summary>A wait of the app itself (e.g. the 3D view waiting for an export), shown as "working" too.</summary>
        public static IDisposable Waiting(string label)
        {
            var id = Interlocked.Increment(ref _nextCall);
            _pending[id] = ("wait:" + label, DateTime.UtcNow);
            return new WaitToken(id);
        }

        sealed class WaitToken : IDisposable
        {
            readonly long _id;
            public WaitToken(long id) => _id = id;
            public void Dispose() => _pending.TryRemove(_id, out _);
        }

        public async Task<JsonObject> Get(string path, CancellationToken ct = default)
        {
            var id = Interlocked.Increment(ref _nextCall);
            _pending[id] = ("get:" + path, DateTime.UtcNow);
            try { return await GetCore(path, ct).ConfigureAwait(false); }
            finally { _pending.TryRemove(id, out _); }
        }

        async Task<JsonObject> GetCore(string path, CancellationToken ct)
        {
            for (int attempt = 0; ; attempt++)
            {
                try
                {
                    using var resp = await _http.GetAsync(path, ct).ConfigureAwait(false);
                    return await Read(resp, ct).ConfigureAwait(false);
                }
                catch (HttpRequestException) when (attempt < 2)
                {
                    await Task.Delay(150, ct).ConfigureAwait(false);   // transient: the engine was busy accepting connections
                }
            }
        }

        // the commands waiting for the engine (POST: something the user did), so the app can say it is working
        static readonly System.Collections.Concurrent.ConcurrentDictionary<long, (string path, DateTime start)> _pending = new();
        static long _nextCall;

        /// <summary>The command waiting the longest, or null.</summary>
        public static (string path, double seconds)? Oldest(Func<string, bool>? skip = null)
        {
            (string path, DateTime start)? best = null;
            foreach (var v in _pending.Values)
                if ((skip == null || !skip(v.path)) && (best == null || v.start < best.Value.start)) best = v;
            return best == null ? null : (best.Value.path, (DateTime.UtcNow - best.Value.start).TotalSeconds);
        }

        public async Task<JsonObject> Post(string path, object? body = null, CancellationToken ct = default)
        {
            var id = Interlocked.Increment(ref _nextCall);
            _pending[id] = (path, DateTime.UtcNow);
            try { return await PostCore(path, body, ct).ConfigureAwait(false); }
            finally { _pending.TryRemove(id, out _); }
        }

        /// <summary>(cloud) Called with the body of every command before it goes to the engine: the app downloads there what the
        /// command names that is in the cloud and not on this computer yet (MainWindow.Content.cs). May throw EngineException.</summary>
        public static Func<string, CancellationToken, Task>? BeforePost;

        async Task<JsonObject> PostCore(string path, object? body, CancellationToken ct)
        {
            var json = body == null ? "{}" : JsonSerializer.Serialize(body);
            if (BeforePost != null) await BeforePost(json, ct).ConfigureAwait(false);
            for (int attempt = 0; ; attempt++)
            {
                try
                {
                    using var content = new StringContent(json, Encoding.UTF8, "application/json");
                    using var resp = await _http.PostAsync(path, content, ct).ConfigureAwait(false);
                    return await Read(resp, ct).ConfigureAwait(false);
                }
                catch (HttpRequestException ex) when (attempt < 2 && ex.InnerException is System.Net.Sockets.SocketException or System.IO.IOException)
                {
                    // the request never reached the engine (connection refused/reset): safe to send again
                    await Task.Delay(150, ct).ConfigureAwait(false);
                }
            }
        }

        /// <summary>(1.76.4) A command changed the materials of zones of a terrain (their border blend followed a
        /// material dropped or edited): the ids of those zones, for the view.</summary>
        public static event Action<System.Collections.Generic.List<string>>? TerrainBlend;

        /// <summary>(1.76.16) A command moved the sea at the foot of a terrain (the terrain made, changed, moved): its
        /// new state, for the panel and the view.</summary>
        public static event Action<JsonObject>? OceanFollow;

        static async Task<JsonObject> Read(HttpResponseMessage resp, CancellationToken ct)
        {
            var text = await resp.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            var node = string.IsNullOrWhiteSpace(text) ? new JsonObject() : (JsonNode.Parse(text) as JsonObject ?? new JsonObject());
            if (node["ok"]?.GetValue<bool>() == false)
                throw new EngineException(node["error"]?.GetValue<string>() ?? L.T("Errore del motore"));
            if (node["terrainBlend"] is JsonArray tb && tb.Count > 0)
            {
                var ids = new System.Collections.Generic.List<string>();
                foreach (var x in tb) if (x != null && (string?)x is string sx && sx != "") ids.Add(sx);
                if (ids.Count > 0) TerrainBlend?.Invoke(ids);
            }
            if (node["oceanFollow"] is JsonObject of)
                OceanFollow?.Invoke((JsonObject)of.DeepClone());
            return node;
        }

        public async Task<(byte[]? image, JsonObject info)> Frame(CancellationToken ct = default)
        {
            using var resp = await _http.GetAsync("frame", ct).ConfigureAwait(false);
            if (resp.StatusCode == HttpStatusCode.NoContent) return (null, new JsonObject());
            var bytes = await resp.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);
            var info = resp.Headers.TryGetValues("X-Simpler-Frame", out var v)
                ? (JsonNode.Parse(v.First()) as JsonObject ?? new JsonObject()) : new JsonObject();
            return (bytes, info);
        }
    }

    /// <summary>Per-user settings (%APPDATA%\Simpler\settings.json).</summary>
    public sealed class FavPreset
    {
        public string Name { get; set; } = "";
        public string Description { get; set; } = "";
        public string Icon { get; set; } = "star";
        public System.Collections.Generic.List<string> Keys { get; set; } = new();
    }

    public sealed class Settings
    {
        public string BlenderPath { get; set; } = "";
        public string LastFolder { get; set; } = "";
        public System.Collections.Generic.Dictionary<string, string> LastFolders { get; set; } = new();   // per kind of file (MainWindow.StartFolder)
        public System.Collections.Generic.List<string> RecentProjects { get; set; } = new();   // last opened or saved, newest first
        public System.Collections.Generic.List<string> TextureFolders { get; set; } = new();
        // (1.74.0) per project: the missing textures the user answered «No» for - not asked again at every opening
        public System.Collections.Generic.Dictionary<string, System.Collections.Generic.List<string>> DeclinedTextures { get; set; } = new();
        public string NavSpeed { get; set; } = "walk";
        public bool TouchpadPan { get; set; } = true;
        public bool MergeOnImport { get; set; } = false;
        // (1.76.32, Luca) favourite commands of the right panel: the hearts, the filter of the toolbar, the presets
        public System.Collections.Generic.List<string> FavCommands { get; set; } = new();
        public bool FavFilter { get; set; } = false;
        public System.Collections.Generic.List<FavPreset> FavPresets { get; set; } = new();      // «Unisci in un solo oggetto» when importing (scene and library)
        public int AutosaveMinutes { get; set; } = 20;          // 0 = off, 10, 20, 30: a copy next to the project (name.autosave.simpler)
        public string DropMode { get; set; } = "object";       // a dropped material: object | replace | selection        // touchpad: two fingers move the view (off: they walk as the wheel)
        public string PivotMode { get; set; } = "base";      // where the gizmo sits: base | center | origin
        public string ViewerShadows { get; set; } = "alta";
        // «Alleggerisci» (the box under the tree): what the real-time view leaves out, kept from one time to the next
        public bool LightSets { get; set; } = false;          // distributions (and their lamps) not drawn in the view
        public bool LightFlakes { get; set; } = false;        // falling flakes not drawn in the view
        public bool LightHalf { get; set; } = false;          // the view at half resolution
        public string LightPrevShadows { get; set; } = "alta"; // the shadows to go back to after «Ombre spente»
        // (1.75.9) SmartView: the view is not computed again by itself; the shadows off while it is on
        public bool SmartView { get; set; } = false;
        public string SmartPrevShadows { get; set; } = "";     // the shadows SmartView switched off ("" = it did not)
        public string Language { get; set; } = "";          // "it" | "en" ("" = from Windows)
        public string LastSeenVersion { get; set; } = "";
        // (1.75.28) the license agreement accepted: "version|date" ("" = never; another version = asked again)
        public string LicenseAccepted { get; set; } = "";
        public double LeftPanelWidth { get; set; } = 288;   // (1.78.4, Luca) first start: his proportions
        public double RightPanelWidth { get; set; } = 366;
        public double LibraryHeight { get; set; } = 200;     // (1.2.2; replaced by LibraryRows)
        public int LibraryRows { get; set; } = 0;              // rows of tiles in the bottom library: 1-3 (0 = not chosen yet)
        public System.Collections.Generic.List<string> CollapsedSections { get; set; } = new();   // (no longer used: 1.17.7)
        public System.Collections.Generic.List<string> OpenAdvanced { get; set; } = new();        // (no longer used: 1.17.7)
        public string AiModel { get; set; } = "";               // AI panel: image model ("" = the best one found)
        public string AiQuality { get; set; } = "medium";        // low | medium | high
        // (1.75.32) the AI video (Krea): model, resolution, seconds, the motion asked, a job left running
        public string VideoModel { get; set; } = "";             // "" = the cheapest
        public string VideoRes { get; set; } = "720p";
        public int VideoSeconds { get; set; } = 5;
        public bool VideoAudio { get; set; } = false;
        /// <summary>(1.78.4) Video AI from the first frame and the text only (no last frame).</summary>
        public bool VideoOneFrame { get; set; } = false;
        public bool ImportAtView { get; set; } = true;           // (1.75.48) an imported model at the centre of the view            // (1.75.37) keep the sound Krea adds
        public string VideoPrompt { get; set; } = "";
        public string VideoPendingJob { get; set; } = "";        // (1.75.32-42, one only; moved into VideoPendingJobs)
        public System.Collections.Generic.List<string> VideoPendingJobs { get; set; } = new();   // (1.75.43) "jobId|info": asked, not downloaded yet
        public long AiTokensIn { get; set; }                     // tokens used since the last reset (OpenAI usage)
        public long AiTokensOut { get; set; }
        public System.Collections.Generic.List<WeatherPreset> WeatherPresets { get; set; } = new();   // the user's own presets of rain and snow
        // (1.78.4, Luca) the «Simpler» parts of the library (Modelli 3D ▸ Simpler, Vegetazione ▸ Simpler): 0 = normal folders
        // (while they are being filled), 1 = red and read only. (1.79.0, Luca: «ricordati di mettere di default il parametro che
        // rende rosse le cartelle») 1 by default: a user who never touched it has them red; 0 only by hand in settings.json.
        public int SimplerLocked { get; set; } = 1;
        // (1.78.4, Luca) update check on rodluc.com: on by default, at most once a day; the last answer, the version skipped
        public bool UpdateCheck { get; set; } = true;
        public string UpdateLastCheck { get; set; } = "";       // UTC, ISO 8601 ("" = never)
        public string UpdateLast { get; set; } = "";            // the last valid answer (JSON)
        public string UpdateSkipped { get; set; } = "";         // «Salta questa versione»
        public string UpdateChannel { get; set; } = "";         // "" or "beta" (by hand in settings.json)
        // (1.79.0) the packs (pack|version) already told by the blue strip or seen in «Pacchetti…»
        public System.Collections.Generic.List<string> PacksSeen { get; set; } = new();

        static string FilePath => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Simpler", "settings.json");

        public static Settings Load()
        {
            try { return JsonSerializer.Deserialize<Settings>(File.ReadAllText(FilePath)) ?? new Settings(); }
            catch { return new Settings(); }
        }

        public void Save()
        {
            Directory.CreateDirectory(Path.GetDirectoryName(FilePath)!);
            File.WriteAllText(FilePath, JsonSerializer.Serialize(this, new JsonSerializerOptions { WriteIndented = true }));
        }
    }
}
