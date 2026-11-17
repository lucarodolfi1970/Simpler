using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;

namespace Simpler
{
    /// <summary>
    /// How well the video card suits Simpler, as a percentage (100% = a card for very large scenes, e.g. RTX 4090).
    /// No benchmark (start-up must stay fast): the score comes from what the driver reports, in a few milliseconds.
    ///   · power: FP32 throughput = CUDA cores × 2 × max clock (NVML), ×0.6 without ray-tracing cores (OptiX);
    ///     reference 80 TFLOPS. Other vendors: an estimate (AMD HIP, Intel Arc, integrated).
    ///   · memory: the video memory decides how big a scene fits (Cycles slows down a lot when it overflows);
    ///     reference 24 GB.
    ///   score = 60% power + 40% memory, each on a soft curve (x^0.6): differences at the top count less than at the
    ///   bottom, as the user feels them.
    /// </summary>
    public static class GpuRating
    {
        public sealed record Result(string Name, double VramGb, double Tflops, bool RayTracing, int Score, string Verdict, string Detail);

        static Result? _cached;
        public static Result? Last => _cached;

        public static Result Detect()
        {
            if (_cached != null) return _cached;
            Result r;
            try { r = FromNvml() ?? FromRegistry() ?? Cpu(); }
            catch { r = FromRegistry() ?? Cpu(); }
            _cached = r;
            return r;
        }

        static Result Make(string name, double vramGb, double tflops, bool rt, string detail)
        {
            double power = Math.Pow(Math.Clamp(tflops / 80.0, 0, 1), 0.6) * (rt ? 1.0 : 0.6);
            double memory = Math.Pow(Math.Clamp(vramGb / 24.0, 0, 1), 0.6);
            int score = (int)Math.Round(100 * Math.Clamp(0.6 * power + 0.4 * memory, 0.02, 1));
            return new Result(name, vramGb, tflops, rt, score, Verdict(score), detail);
        }

        public static string Verdict(int score) => score switch
        {
            >= 85 => L.T("Eccellente: scene molto grandi e path tracing fluido"),
            >= 65 => L.T("Ottima: scene grandi senza problemi"),
            >= 45 => L.T("Buona: scene medie; per le scene enormi usa la qualità Bozza mentre lavori"),
            >= 25 => L.T("Sufficiente: scene piccole e medie, path tracing più lento"),
            _ => L.T("Limitata: preferisci scene leggere; il path tracing sarà lento"),
        };

        // ---------------------------------------------------------------- NVIDIA (NVML, part of the driver)

        [StructLayout(LayoutKind.Sequential)] struct NvmlMemory { public ulong Total, Free, Used; }
        [DllImport("nvml.dll")] static extern int nvmlInit_v2();
        [DllImport("nvml.dll")] static extern int nvmlShutdown();
        [DllImport("nvml.dll")] static extern int nvmlDeviceGetHandleByIndex_v2(uint index, out IntPtr device);
        [DllImport("nvml.dll")] static extern int nvmlDeviceGetName(IntPtr device, byte[] name, uint length);
        [DllImport("nvml.dll")] static extern int nvmlDeviceGetMemoryInfo(IntPtr device, out NvmlMemory memory);
        [DllImport("nvml.dll")] static extern int nvmlDeviceGetNumGpuCores(IntPtr device, out uint cores);
        [DllImport("nvml.dll")] static extern int nvmlDeviceGetMaxClockInfo(IntPtr device, int type, out uint mhz);
        [DllImport("nvml.dll")] static extern int nvmlDeviceGetCudaComputeCapability(IntPtr device, out int major, out int minor);

        static Result? FromNvml()
        {
            try
            {
                if (nvmlInit_v2() != 0) return null;
            }
            catch (DllNotFoundException) { return null; }
            catch (EntryPointNotFoundException) { return null; }
            try
            {
                if (nvmlDeviceGetHandleByIndex_v2(0, out var dev) != 0) return null;
                var buf = new byte[96];
                var name = nvmlDeviceGetName(dev, buf, (uint)buf.Length) == 0 ? Encoding.ASCII.GetString(buf).TrimEnd('\0').Trim() : "NVIDIA";
                double vram = nvmlDeviceGetMemoryInfo(dev, out var mem) == 0 ? mem.Total / 1073741824.0 : 0;
                uint cores = 0, mhz = 0;
                try { if (nvmlDeviceGetNumGpuCores(dev, out var c) == 0) cores = c; } catch (EntryPointNotFoundException) { }
                try { if (nvmlDeviceGetMaxClockInfo(dev, 1 /* SM */, out var m) == 0) mhz = m; } catch (EntryPointNotFoundException) { }
                int major = 0, minor = 0;
                try { nvmlDeviceGetCudaComputeCapability(dev, out major, out minor); } catch (EntryPointNotFoundException) { }
                var known = Known(name);
                if (cores == 0 && known != null) cores = (uint)known.Value.cores;
                if (mhz == 0 && known != null) mhz = (uint)(known.Value.ghz * 1000);
                // ray-tracing cores from Turing (7.5) on, except the GTX 16 series
                bool rt = (major > 7 || (major == 7 && minor >= 5)) && !name.Contains("GTX", StringComparison.OrdinalIgnoreCase);
                if (major == 0) rt = name.Contains("RTX", StringComparison.OrdinalIgnoreCase);
                double tflops = cores > 0 && mhz > 0 ? cores * 2.0 * mhz / 1e6 : 0;
                if (tflops == 0) tflops = vram * 2.5;                // unknown model: a rough guess from its memory
                var detail = cores > 0 ? L.F("{0} core CUDA · {1} MHz · {2} TFLOPS{3}", cores, mhz, tflops.ToString("0.0"), rt ? L.T(" · ray tracing") : "")
                                       : L.F("{0} TFLOPS stimati", tflops.ToString("0.0"));
                return Make(name, vram, tflops, rt, detail);
            }
            finally { try { nvmlShutdown(); } catch { } }
        }

        /// <summary>Approximate cores and boost clock of common cards, used only if the driver does not say.</summary>
        static (int cores, double ghz)? Known(string name)
        {
            var table = new (string key, int cores, double ghz)[]
            {
                ("5090", 21760, 2.41), ("5080", 10752, 2.62), ("5070 Ti", 8960, 2.45), ("5070", 6144, 2.51),
                ("4090", 16384, 2.52), ("4080 SUPER", 10240, 2.55), ("4080", 9728, 2.505), ("4070 Ti SUPER", 8448, 2.61),
                ("4070 Ti", 7680, 2.61), ("4070 SUPER", 7168, 2.475), ("4070", 5888, 2.475), ("4060 Ti", 4352, 2.535), ("4060", 3072, 2.46),
                ("3090 Ti", 10752, 1.86), ("3090", 10496, 1.695), ("3080 Ti", 10240, 1.665), ("3080", 8704, 1.71),
                ("3070 Ti", 6144, 1.77), ("3070", 5888, 1.725), ("3060 Ti", 4864, 1.665), ("3060", 3584, 1.777),
                ("2080 Ti", 4352, 1.545), ("2080", 2944, 1.71), ("2070", 2304, 1.62), ("2060", 1920, 1.68),
            };
            foreach (var t in table)
                if (name.Contains(t.key, StringComparison.OrdinalIgnoreCase)) return (t.cores, t.ghz);
            return null;
        }

        // ---------------------------------------------------------------- other cards (Windows registry, display class)

        static Result? FromRegistry()
        {
            if (!OperatingSystem.IsWindows()) return null;
            string bestName = ""; double bestGb = 0;
            try
            {
                using var cls = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(@"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}");
                if (cls == null) return null;
                foreach (var sub in cls.GetSubKeyNames().Where(n => n.Length == 4 && n.All(char.IsDigit)))
                {
                    using var k = cls.OpenSubKey(sub);
                    if (k == null) continue;
                    var name = k.GetValue("DriverDesc") as string ?? "";
                    double gb = 0;
                    var q = k.GetValue("HardwareInformation.qwMemorySize");
                    if (q is long l) gb = l / 1073741824.0;
                    else if (q is byte[] b8 && b8.Length >= 8) gb = BitConverter.ToInt64(b8, 0) / 1073741824.0;
                    else if (k.GetValue("HardwareInformation.MemorySize") is int i) gb = (uint)i / 1073741824.0;
                    else if (k.GetValue("HardwareInformation.MemorySize") is byte[] b4 && b4.Length >= 4) gb = BitConverter.ToUInt32(b4, 0) / 1073741824.0;
                    if (name != "" && gb > bestGb) { bestGb = gb; bestName = name; }
                }
            }
            catch { return null; }
            if (bestName == "") return null;
            var n = bestName.ToLowerInvariant();
            bool amd = n.Contains("radeon") || n.Contains("amd");
            bool arc = n.Contains("arc");
            bool integrated = bestGb < 2.5 || n.Contains("uhd") || n.Contains("iris") || (amd && n.Contains("graphics") && !n.Contains("rx"));
            double tflops = integrated ? 1.5 : amd ? Math.Min(40, bestGb * 2.2) : arc ? Math.Min(20, bestGb * 1.6) : bestGb * 1.5;
            bool rt = !integrated && (n.Contains("rx 6") || n.Contains("rx 7") || n.Contains("rx 9") || arc);
            var r = Make(bestName, bestGb, tflops, rt, L.T("valori stimati: il driver non fornisce i dettagli"));
            return r;
        }

        static Result Cpu() => Make(L.T("Nessuna scheda video dedicata"), 0, 0.5, false, L.T("il rendering userà il processore"));
    }
}
