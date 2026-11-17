using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace Simpler
{
    /// <summary>
    /// "Genera" in the row of a map: DeepBump (GPL-3.0, tools\deepbump, unmodified) run as a separate program with the
    /// Python of Blender: normal map from the colour map, height from the normal (or from the colour, in two steps),
    /// resolution ×2. Everything on this computer, free. Its libraries (onnxruntime, imageio) are downloaded once, the
    /// first time, into %LOCALAPPDATA%\Simpler\deepbump-libs. The new map is saved next to the one it comes from
    /// (legno.jpg → legno_normal.png); from a map embedded in the project, it is embedded too.
    /// </summary>
    public partial class MainWindow
    {
        static string DeepBumpLibs => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Simpler", "deepbump-libs");
        static string DeepBumpWork => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Simpler", "deepbump-work");

        static string? FindDeepBump()
        {
            var dir = new DirectoryInfo(AppContext.BaseDirectory);
            for (int i = 0; i < 8 && dir != null; i++, dir = dir.Parent)
            {
                var cli = Path.Combine(dir.FullName, "tools", "deepbump", "cli.py");
                if (File.Exists(cli)) return Path.GetDirectoryName(cli);
            }
            return null;
        }

        /// <summary>python.exe of the Blender Simpler uses (blender\5.x\python\bin).</summary>
        string? BlenderPython()
        {
            var exe = _host?.BlenderPath;
            if (string.IsNullOrEmpty(exe)) exe = EngineHost.FindBlender();
            var dir = exe != null ? Path.GetDirectoryName(exe) : null;
            if (dir == null || !Directory.Exists(dir)) return null;
            return Directory.GetDirectories(dir)
                .OrderByDescending(d => d, StringComparer.OrdinalIgnoreCase)
                .Select(d => Path.Combine(d, "python", "bin", "python.exe"))
                .FirstOrDefault(File.Exists);
        }

        /// <summary>What "Genera" offers for a map slot (label, why it can't now or null, what it does).</summary>
        List<(string label, string? reason, Func<Task> act)> MapGenerators(string path, string image, JsonObject? info)
        {
            var list = new List<(string, string?, Func<Task>)>();
            var color = S("color.map.image");
            var normal = S("normal.map.image");
            if (path == "normal.map")
                list.Add((L.T("Normale dalla mappa colore"), color == "" ? L.T("prima metti la texture del colore") : null,
                          () => Generate(path, color, new[] { "color_to_normals" }, "_normal", L.T("Normale dalla mappa colore"))));
            if (path is "normal.bumpMap" or "displacement.map")
            {
                list.Add((L.T("Altezza dalla normale"), normal == "" ? L.T("prima metti la normal map") : null,
                          () => Generate(path, normal, new[] { "normals_to_height" }, "_height", L.T("Altezza dalla normale"))));
                list.Add((L.T("Altezza dalla mappa colore"), color == "" ? L.T("prima metti la texture del colore") : null,
                          () => Generate(path, color, new[] { "color_to_normals", "normals_to_height" }, "_height", L.T("Altezza dalla mappa colore"))));
            }
            if (path == "roughness.map")
            {
                list.Add((L.T("Rugosità dalla mappa colore"), color == "" ? L.T("prima metti la texture del colore") : null,
                          () => GenerateRoughness(color, normal, false, L.T("Rugosità dalla mappa colore"))));
                list.Add((L.T("Rugosità con i bordi consumati"), color == "" ? L.T("prima metti la texture del colore") : null,
                          () => GenerateRoughness(color, normal, true, L.T("Rugosità con i bordi consumati"))));
            }
            if (image != "" && path != "displacement.vector")
            {
                int w = (int?)info?["width"] ?? 0, h = (int?)info?["height"] ?? 0;
                list.Add((L.T("Raddoppia la risoluzione"), Math.Max(w, h) > 2048 ? L.T("è già oltre 2048 px") : null,
                          () => Generate(path, image, new[] { "lowres_to_highres" }, "_x2", L.T("Raddoppia la risoluzione"))));
            }
            return list;
        }

        ContextMenu GenerateMenu(string path, string image, JsonObject? info)
        {
            var m = new ContextMenu();
            foreach (var (label, reason, act) in MapGenerators(path, image, info))
            {
                var i = new MenuItem { Header = reason == null ? label : label + "  (" + reason + ")", IsEnabled = reason == null };
                i.Click += async (_, __) => await act();
                m.Items.Add(i);
            }
            return m;
        }

        /// <summary>Runs the DeepBump steps on the source image and puts the result in the map slot.</summary>
        Task Generate(string slot, string sourceImage, string[] steps, string suffix, string title) =>
            RunGenerator(slot, sourceImage, suffix, title, async (py, db) =>
            {
                var current = await PrepareInput(sourceImage, title);
                for (int k = 0; k < steps.Length; k++)
                    current = await RunStep(py, db, current, steps[k], title, steps.Length > 1 ? $" ({k + 1}/{steps.Length})" : "");
                return current;
            });

        /// <summary>Common frame of a generator: checks, first-time libraries, busy, the result next to the map it
        /// comes from (legno.jpg → legno_normal.png; an embedded one: embedded in the project too), errors.</summary>
        async Task RunGenerator(string slot, string placeLike, string suffix, string title, Func<string, string, Task<string>> work)
        {
            var db = FindDeepBump();
            var py = BlenderPython();
            if (db == null || py == null)
            {
                Msg.Show(this, db == null ? L.T("Manca la cartella tools\\deepbump di Simpler: reinstalla Simpler.") : L.T("Non trovo il Python di Blender."),
                         "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }
            var info = (_matInfo["images"] as JsonObject)?[placeLike] as JsonObject;
            var origPath = (string?)info?["path"] ?? "";
            var origName = Path.GetFileNameWithoutExtension((string?)info?["file"] ?? placeLike);
            using var busy = BeginBusy();
            var clock = Stopwatch.StartNew();
            try
            {
                if (!await EnsureDeepBumpLibs(py)) return;
                Directory.CreateDirectory(DeepBumpWork);
                CleanDeepBumpWork();
                var current = await work(py, db);
                JsonObject value;
                var dir = File.Exists(origPath) ? Path.GetDirectoryName(origPath) : null;
                string? final = dir != null ? FreeName(dir, origName + suffix, ".png") : null;
                if (final != null && TryCopy(current, final)) value = new JsonObject { ["file"] = final };
                else value = new JsonObject { ["file"] = current, ["pack"] = true };
                await EditMat(slot, value, true);
                Status(L.F("{0}: fatto in {1} s{2}", title, (int)clock.Elapsed.TotalSeconds,
                           value["pack"] == null ? " · " + final : " · " + L.T("incorporata nel progetto")));
            }
            catch (Exception ex)
            {
                AppLog.Write("deepbump: " + ex);
                Msg.Show(this, L.F("{0}: non è riuscito.", title) + "\n\n" + ex.Message, "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning);
            }
            finally { HideTask(); }
        }

        async Task<string> PrepareInput(string image, string title)
        {
            ShowTask(L.F("{0}: preparo l'immagine…", title));
            var info = (_matInfo["images"] as JsonObject)?[image] as JsonObject;
            var input = Path.Combine(DeepBumpWork, Guid.NewGuid().ToString("N") + "-in.png");
            await File.WriteAllBytesAsync(input, await MapAsRgbPng(image, (string?)info?["path"] ?? ""));
            return input;
        }

        /// <summary>One DeepBump step (cli.py) on a PNG; the progress in the view.</summary>
        async Task<string> RunStep(string py, string db, string input, string module, string title, string stepLabel)
        {
            var outFile = Path.Combine(DeepBumpWork, Guid.NewGuid().ToString("N") + "-" + module + ".png");
            var args = new List<string> { "cli.py", input, outFile, module, "--verbose" };
            if (module == "lowres_to_highres") { args.Add("--lowres_to_highres-scale_factor"); args.Add("x2"); }
            if (module == "normals_to_curvature") { args.Add("--normals_to_curvature-blur_radius"); args.Add("SMALL"); }
            var (code, log) = await RunPython(py, args, db, DeepBumpLibs, line =>
            {
                var parts = line.Trim().Split('/');
                if (parts.Length == 2 && int.TryParse(parts[0], out var a) && int.TryParse(parts[1], out var b) && b > 0)
                    Dispatcher.Invoke(() => ShowTask(L.F("{0}{1}: {2}%", title, stepLabel, a * 100 / b)));
            });
            if (code != 0 || !File.Exists(outFile)) throw new Exception(LastLines(log));
            return outFile;
        }

        /// <summary>Roughness from the colour map (on this computer, no DeepBump needed for the plain one): the
        /// brightness, levelled (2%–98%) and turned round (dark = rough), between 25% and 90%. With the worn edges:
        /// the curvature of the normal map (DeepBump) makes edges smoother and hollows rougher.</summary>
        Task GenerateRoughness(string color, string normal, bool edges, string title) =>
            RunGenerator("roughness.map", color, edges ? "_roughness_edges" : "_roughness", title, async (py, db) =>
            {
                var colorPng = await PrepareInput(color, title);
                string? curv = null;
                if (edges)
                {
                    var n = normal != "" ? await PrepareInput(normal, title) : await RunStep(py, db, colorPng, "color_to_normals", title, " (1/2)");
                    curv = await RunStep(py, db, n, "normals_to_curvature", title, normal != "" ? "" : " (2/2)");
                }
                ShowTask(L.F("{0}: calcolo la rugosità…", title));
                var outFile = Path.Combine(DeepBumpWork, Guid.NewGuid().ToString("N") + "-roughness.png");
                await Task.Run(() => File.WriteAllBytes(outFile, RoughnessPng(colorPng, curv)));
                return outFile;
            });

        static byte[] Gray(string png, out int w, out int h, int? fitW = null, int? fitH = null)
        {
            var dec = BitmapDecoder.Create(new Uri(png), BitmapCreateOptions.None, BitmapCacheOption.OnLoad);
            BitmapSource src = dec.Frames[0];
            if (fitW is int fw && fitH is int fh && (src.PixelWidth != fw || src.PixelHeight != fh))
                src = new TransformedBitmap(src, new ScaleTransform((double)fw / src.PixelWidth, (double)fh / src.PixelHeight));
            var g = new FormatConvertedBitmap(src, PixelFormats.Gray8, null, 0);
            w = g.PixelWidth; h = g.PixelHeight;
            var px = new byte[w * h];
            g.CopyPixels(px, w, 0);
            return px;
        }

        static byte[] RoughnessPng(string colorPng, string? curvPng)
        {
            var lum = Gray(colorPng, out int w, out int h);
            // levels: 2% and 98% of the brightness
            var hist = new long[256];
            foreach (var v in lum) hist[v]++;
            long n = lum.Length, acc = 0;
            int lo = 0, hi = 255;
            for (int i = 0; i < 256; i++) { acc += hist[i]; if (acc >= n * 0.02) { lo = i; break; } }
            acc = 0;
            for (int i = 255; i >= 0; i--) { acc += hist[i]; if (acc >= n * 0.02) { hi = i; break; } }
            double span = Math.Max(1, hi - lo);
            byte[]? curv = curvPng != null ? Gray(curvPng, out _, out _, w, h) : null;
            double mean = 0, sd = 1;
            if (curv != null)
            {
                double s = 0, s2 = 0;
                foreach (var v in curv) { s += v; s2 += (double)v * v; }
                mean = s / n;
                sd = Math.Max(1, Math.Sqrt(Math.Max(0, s2 / n - mean * mean)));
            }
            var outPx = new byte[w * h];
            for (int i = 0; i < outPx.Length; i++)
            {
                double b = Math.Clamp((lum[i] - lo) / span, 0, 1);
                double r = 0.90 - 0.65 * b;                                    // dark = rough (90%), bright = smooth (25%)
                if (curv != null)
                {
                    double e = Math.Clamp((curv[i] - mean) / (2.5 * sd), -1, 1);   // + = edge, - = hollow
                    r -= 0.30 * e;
                }
                outPx[i] = (byte)Math.Round(Math.Clamp(r, 0.05, 1) * 255);
            }
            var bmp = BitmapSource.Create(w, h, 96, 96, PixelFormats.Gray8, null, outPx, w);
            var enc = new PngBitmapEncoder();
            enc.Frames.Add(BitmapFrame.Create(bmp));
            using var ms = new MemoryStream();
            enc.Save(ms);
            return ms.ToArray();
        }

        /// <summary>The map as an 8-bit RGB PNG (what DeepBump reads): from its file, or from the engine when it is
        /// embedded or in a format Windows can't read (EXR).</summary>
        async Task<byte[]> MapAsRgbPng(string image, string path)
        {
            BitmapSource? src = null;
            if (File.Exists(path))
                try { src = AiImage.Decode(await File.ReadAllBytesAsync(path), 8192); } catch { src = null; }
            if (src == null)
            {
                if (_host == null) throw new Exception(L.T("Motore non pronto"));
                var bytes = await TexHttp.GetByteArrayAsync($"http://127.0.0.1:{_host.Port}/api/texture?image={Uri.EscapeDataString(image)}&px=4096");
                src = AiImage.Decode(bytes, 8192);
            }
            var rgb = new FormatConvertedBitmap(src, PixelFormats.Bgr24, null, 0);
            var enc = new PngBitmapEncoder();
            enc.Frames.Add(BitmapFrame.Create(rgb));
            using var ms = new MemoryStream();
            enc.Save(ms);
            return ms.ToArray();
        }

        static string? FreeName(string dir, string stem, string ext)
        {
            for (int i = 1; i < 100; i++)
            {
                var p = Path.Combine(dir, stem + (i == 1 ? "" : "_" + i) + ext);
                if (!File.Exists(p)) return p;
            }
            return null;
        }

        static bool TryCopy(string from, string to)
        {
            try { File.Copy(from, to, false); return true; } catch (Exception ex) { AppLog.Write("deepbump copy: " + ex.Message); return false; }
        }

        static void CleanDeepBumpWork()
        {
            try
            {
                foreach (var f in Directory.GetFiles(DeepBumpWork))
                    if (File.GetLastWriteTime(f) < DateTime.Now.AddDays(-2)) try { File.Delete(f); } catch { }
                foreach (var d in Directory.GetDirectories(DeepBumpWork))      // (normals of decals: one folder each)
                    if (Directory.GetLastWriteTime(d) < DateTime.Now.AddDays(-2)) try { Directory.Delete(d, true); } catch { }
            }
            catch { }
        }

        static string LastLines(string log)
        {
            var lines = log.Split('\n').Select(l => l.TrimEnd()).Where(l => l != "").ToList();
            return string.Join("\n", lines.Skip(Math.Max(0, lines.Count - 6)));
        }

        /// <summary>The first time: onnxruntime and imageio into deepbump-libs, with the pip of Blender's Python.</summary>
        async Task<bool> EnsureDeepBumpLibs(string py)
        {
            var marker = Path.Combine(DeepBumpLibs, ".simpler-ok");
            if (File.Exists(marker) && File.ReadAllText(marker).Trim() == py) return true;
            if (Msg.Show(this, L.T("La prima volta Simpler scarica i componenti di DeepBump (onnxruntime e imageio, circa 40 MB): serve la connessione a internet. Procedo?"),
                         "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return false;
            ShowTask(L.T("DeepBump: scarico i componenti (solo la prima volta)…"));
            Directory.CreateDirectory(DeepBumpLibs);
            var (pipCode, _) = await RunPython(py, new List<string> { "-m", "pip", "--version" }, null, null, null);
            if (pipCode != 0)
            {
                var (ensure, elog) = await RunPython(py, new List<string> { "-m", "ensurepip", "--user" }, null, null, null);
                if (ensure != 0) throw new Exception(L.T("Il Python di Blender non ha pip: ") + LastLines(elog));
            }
            var (code, log) = await RunPython(py, new List<string> { "-m", "pip", "install", "--disable-pip-version-check", "--no-warn-script-location",
                                                                      "--upgrade", "--target", DeepBumpLibs, "onnxruntime", "imageio", "numpy" }, null, null, null);
            if (code != 0) throw new Exception(L.T("Download dei componenti non riuscito: ") + LastLines(log));
            File.WriteAllText(marker, py);
            return true;
        }

        /// <summary>Runs Blender's Python with the given arguments; lines of its output go to onLine as they come.</summary>
        static Task<(int code, string log)> RunPython(string py, List<string> args, string? workDir, string? libs, Action<string>? onLine)
        {
            var psi = new ProcessStartInfo
            {
                FileName = py, UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8,
            };
            foreach (var a in args) psi.ArgumentList.Add(a);
            if (workDir != null) psi.WorkingDirectory = workDir;
            psi.Environment["PYTHONIOENCODING"] = "utf-8";          // (its messages have arrows: the Windows code page would fail)
            if (libs != null) { psi.Environment["PYTHONPATH"] = libs; psi.Environment["PYTHONNOUSERSITE"] = "1"; }
            var log = new StringBuilder();
            var tcs = new TaskCompletionSource<(int, string)>();
            var p = new Process { StartInfo = psi, EnableRaisingEvents = true };
            void Line(string? s) { if (s == null) return; lock (log) log.AppendLine(s); onLine?.Invoke(s); }
            p.OutputDataReceived += (_, e) => Line(e.Data);
            p.ErrorDataReceived += (_, e) => Line(e.Data);
            p.Exited += (_, __) => { p.WaitForExit(); lock (log) tcs.TrySetResult((p.ExitCode, log.ToString())); p.Dispose(); };
            try
            {
                p.Start();
                FullSpeed.Apply(p);                     // (1.78.4: full speed also with another program in front)
                p.BeginOutputReadLine();
                p.BeginErrorReadLine();
            }
            catch (Exception ex) { tcs.TrySetResult((-1, ex.Message)); }
            return tcs.Task;
        }
    }
}
