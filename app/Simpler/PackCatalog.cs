using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;

namespace Simpler
{
    /// <summary>(1.79.0, Luca: «se arriva un messaggio di un nuovo package disponibile come possiamo aiutare l'utente a
    /// capire qual è?») The packs released, from www.rodluc.com/simpler/packs/packs.json (written by Simpler Pack Studio,
    /// «Prepara per il sito»). Only file names of that folder are used, never addresses from the list; a downloaded pack
    /// must have the size and the SHA-256 of the list, and is then checked (signature, every file) by PackInstaller as
    /// a pack chosen from the disk. No WPF here.</summary>
    public static class PackCatalog
    {
        public const string Base = "https://www.rodluc.com/simpler/packs/";
        static readonly HttpClient Http = new HttpClient { Timeout = TimeSpan.FromSeconds(8) };
        static readonly HttpClient Download = new HttpClient { Timeout = Timeout.InfiniteTimeSpan };
        static readonly Regex FileRx = new(@"^[A-Za-z0-9_\-\.]{1,120}$");
        static readonly Regex IdRx = new(@"^[A-Za-z0-9_\-]{1,64}$");

        public sealed class Entry
        {
            public string PackId = "", Title = "", Description = "", Version = "", Author = "", Released = "", License = "", SimplerMin = "";
            public string File = "", Sha256 = "", Cover = "";
            public long Size, Bytes;
            public int Models;
            public List<string> Thumbs = new();
            public List<string> Folders = new();
        }

        /// <summary>A name of a file of the folder of the packs: only letters, digits, «-», «_», «.», no folders.</summary>
        public static bool SafeName(string? n) => n != null && FileRx.IsMatch(n) && !n.StartsWith(".") && !n.Contains("..");

        public static string Url(string name) => Base + name;

        /// <summary>The list as the site gives it; null when it is not a valid one.</summary>
        public static List<Entry>? Parse(string json)
        {
            try
            {
                if (JsonNode.Parse(json) is not JsonObject o || (int?)o["format"] != 1 || o["packs"] is not JsonArray a) return null;
                var list = new List<Entry>();
                foreach (var x in a.OfType<JsonObject>())
                {
                    static string S(JsonObject x, string k) { try { return (string?)x[k] ?? ""; } catch { return ""; } }
                    static long N(JsonObject x, string k) { try { return (long?)x[k] ?? 0; } catch { return 0; } }
                    var e = new Entry
                    {
                        PackId = S(x, "packId"), Title = S(x, "title"), Description = S(x, "description"), Version = S(x, "version"),
                        Author = S(x, "author"), Released = S(x, "released"), License = S(x, "license"), SimplerMin = S(x, "simplerMin"),
                        File = S(x, "file"), Sha256 = S(x, "sha256").ToLowerInvariant(), Cover = S(x, "cover"),
                        Size = N(x, "size"), Bytes = N(x, "bytes"), Models = (int)N(x, "models"),
                    };
                    if (!IdRx.IsMatch(e.PackId) || !SafeName(e.File) || !e.File.EndsWith(".simplerpack", StringComparison.OrdinalIgnoreCase)
                        || !Regex.IsMatch(e.Sha256, "^[0-9a-f]{64}$") || e.Size <= 0) continue;
                    if (!SafeName(e.Cover)) e.Cover = "";
                    if (x["thumbs"] is JsonArray t) e.Thumbs = t.Select(v => { try { return (string?)v ?? ""; } catch { return ""; } }).Where(SafeName).Take(12).ToList();
                    if (x["folders"] is JsonArray f) e.Folders = f.Select(v => { try { return (string?)v ?? ""; } catch { return ""; } }).Where(s => s != "").Take(40).ToList();
                    if (list.All(y => y.PackId != e.PackId)) list.Add(e);
                }
                return list;
            }
            catch { return null; }
        }

        /// <summary>The list from the site; null = no valid answer (offline, error, 8 seconds without answer).</summary>
        public static async Task<List<Entry>?> Fetch()
        {
            try
            {
                using var resp = await Http.GetAsync(Base + "packs.json?t=" + DateTime.UtcNow.ToString("yyyyMMddHH")).ConfigureAwait(false);
                if (!resp.IsSuccessStatusCode) { AppLog.Write($"packs list: http {(int)resp.StatusCode}"); return null; }
                var list = Parse(await resp.Content.ReadAsStringAsync().ConfigureAwait(false));
                AppLog.Write(list == null ? "packs list: not valid" : $"packs list: {list.Count} packs");
                return list;
            }
            catch (Exception ex) { AppLog.Write("packs list: no answer (" + ex.GetType().Name + ")"); return null; }
        }

        /// <summary>The folder of the pictures and the downloads of the list (in the local data of Simpler).</summary>
        public static string CacheDir => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Simpler", "packcache");

        /// <summary>A picture of the list (cover, thumbnail), downloaded once; "" when it cannot be had.</summary>
        public static async Task<string> Picture(string name)
        {
            if (!SafeName(name)) return "";
            var f = Path.Combine(CacheDir, name);
            if (File.Exists(f)) return f;
            try
            {
                Directory.CreateDirectory(CacheDir);
                var bytes = await Http.GetByteArrayAsync(Base + name).ConfigureAwait(false);
                if (bytes.Length == 0 || bytes.Length > 20 << 20) return "";
                await File.WriteAllBytesAsync(f + ".part", bytes).ConfigureAwait(false);
                File.Move(f + ".part", f, true);
                return f;
            }
            catch { return ""; }
        }

        /// <summary>Downloads the pack (a .part file, renamed when size and SHA-256 are those of the list).
        /// progress: (bytes so far, bytes in all).</summary>
        public static async Task<string> Get(Entry e, Action<long, long> progress, CancellationToken ct)
        {
            if (!SafeName(e.File)) throw new InvalidDataException("name");
            Directory.CreateDirectory(CacheDir);
            var f = Path.Combine(CacheDir, e.File);
            if (File.Exists(f) && new FileInfo(f).Length == e.Size && Hash(f) == e.Sha256) return f;
            var part = f + ".part";
            try
            {
                using (var resp = await Download.GetAsync(Base + e.File, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false))
                {
                    resp.EnsureSuccessStatusCode();
                    using var src = await resp.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
                    using var dst = new FileStream(part, FileMode.Create, FileAccess.Write, FileShare.None, 1 << 20);
                    var buf = new byte[1 << 20];
                    long done = 0;
                    int n;
                    while ((n = await src.ReadAsync(buf, ct).ConfigureAwait(false)) > 0)
                    {
                        await dst.WriteAsync(buf.AsMemory(0, n), ct).ConfigureAwait(false);
                        done += n;
                        if (done > e.Size) throw new InvalidDataException("size");
                        progress(done, e.Size);
                    }
                }
                if (new FileInfo(part).Length != e.Size || Hash(part) != e.Sha256) throw new InvalidDataException("download");
                File.Move(part, f, true);
                return f;
            }
            catch
            {
                try { File.Delete(part); } catch { }
                throw;
            }
        }

        static string Hash(string file)
        {
            using var s = File.OpenRead(file);
            return Convert.ToHexString(SHA256.HashData(s)).ToLowerInvariant();
        }

        /// <summary>A downloaded pack once installed: its file goes (the models are in the library now).</summary>
        public static void Forget(string file)
        {
            try { if (Path.GetDirectoryName(Path.GetFullPath(file)) == Path.GetFullPath(CacheDir) && File.Exists(file)) File.Delete(file); } catch { }
        }

        public enum State { New, Installed, Update }

        /// <summary>Its state on this computer from the version installed (null: not installed).</summary>
        public static State StateOf(Entry e, string? installed) =>
            installed == null ? State.New : PackInstallWindow.CompareVersions(e.Version, installed) > 0 ? State.Update : State.Installed;

        /// <summary>The key of a release (pack and version), for the notices already seen.</summary>
        public static string Key(Entry e) => e.PackId + "|" + e.Version;

        /// <summary>What to tell: the packs not installed and the updates of the installed ones, not yet seen.</summary>
        public static List<Entry> News(List<Entry> list, IDictionary<string, string> installed, ICollection<string> seen) =>
            list.Where(e => !seen.Contains(Key(e)) && StateOf(e, installed.TryGetValue(e.PackId, out var v) ? v : null) != State.Installed).ToList();
    }
}
