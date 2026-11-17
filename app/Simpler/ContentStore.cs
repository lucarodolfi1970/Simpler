using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;

namespace Simpler
{
    /// <summary>(cloud) A model or an ecosystem that is not in the setup: it is downloaded on click from the place of the
    /// contents (Cloudflare R2, behind a small door that answers only to the exact name of a file, with a secret part in
    /// the address).</summary>
    public sealed class ContentAsset
    {
        public string Kind = "";          // "model" | "eco"
        public string Id = "", Name = "", Folder = "", Rev = "", File = "", Sha256 = "", Thumb = "";
        public long Size, Bytes;           // the zip, and what it holds once open
        public JsonObject? Meta;           // a model: its entry of the library
        public string[] Models = Array.Empty<string>();      // an ecosystem: the models it needs
        public bool IsEco => Kind == "eco";
    }

    /// <summary>What went wrong, in words the app can show: «offline», «signature», «size», «space», «bad», «file».</summary>
    public sealed class ContentException : Exception
    {
        public string Code;
        public ContentException(string code, string detail = "") : base(detail == "" ? code : code + ": " + detail) { Code = code; }
    }

    /// <summary>The catalog of the contents (catalog.json + catalog.sig, signed with the key of the packs: nothing is
    /// believed that is not signed), their download (resumed after a break, checked by size and SHA-256, opened in a
    /// folder beside the library and moved in only when whole) and their removal. No WPF here: tools/contenttest.</summary>
    public sealed class ContentStore
    {
        /// <summary>The address of the contents: the door on Cloudflare and the secret part (never in the notes or the
        /// site; it only lives in the Worker and here).</summary>
        public const string DefaultBase = "https://simpler-content.rodluc.workers.dev/SEGRETO-NON-PUBBLICATO/";   // (public sources: the secret part is not published; a build from these sources has no cloud contents)

        static readonly Regex SafeFile = new(@"^[A-Za-z0-9_\-\.]+$", RegexOptions.Compiled);
        static readonly Regex SafeId = new(@"^[em]_[0-9a-f]{6,16}(_[0-9]{1,4})?$", RegexOptions.Compiled);   // (some models of the library: m_xxxxxxxxxx_001)

        readonly string[] _keys;
        readonly HttpClient _http;
        readonly string _base;
        public string CacheDir { get; }
        public Dictionary<string, ContentAsset> Models { get; private set; } = new(StringComparer.Ordinal);
        public Dictionary<string, ContentAsset> Ecosystems { get; private set; } = new(StringComparer.Ordinal);
        public bool HasCatalog => Models.Count + Ecosystems.Count > 0;
        public bool Online { get; private set; }
        public DateTime Loaded { get; private set; }

        public ContentStore(IEnumerable<string> keys, string? baseUrl = null, string? cacheDir = null, HttpClient? http = null)
        {
            _keys = keys.Where(k => !string.IsNullOrWhiteSpace(k)).Select(k => k.Trim()).Distinct().ToArray();
            _base = (baseUrl ?? DefaultBase).TrimEnd('/') + "/";
            CacheDir = cacheDir ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Simpler", "content");
            _http = http ?? new HttpClient(new HttpClientHandler { AllowAutoRedirect = true }) { Timeout = Timeout.InfiniteTimeSpan };
        }

        // (16/11) the version of this build, not a number written by hand (it said 1.80 in 1.79.0)
        static void Agent(HttpRequestMessage r) => r.Headers.TryAddWithoutValidation("User-Agent", "Simpler/" + SettingsDialog.Version + " (content)");

        // ------------------------------------------------------------------ the catalog

        bool Verify(byte[] data, string sig)
        {
            byte[] s;
            try { s = Convert.FromBase64String(sig.Trim()); } catch { return false; }
            foreach (var k in _keys)
            {
                try
                {
                    using var ec = ECDsa.Create();
                    ec.ImportSubjectPublicKeyInfo(Convert.FromBase64String(k), out _);
                    if (ec.VerifyData(data, s, HashAlgorithmName.SHA256, DSASignatureFormat.IeeeP1363FixedFieldConcatenation)) return true;
                }
                catch { }
            }
            return false;
        }

        async Task<byte[]> GetBytes(string name, CancellationToken ct, int seconds = 25)
        {
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(TimeSpan.FromSeconds(seconds));
            using var req = new HttpRequestMessage(HttpMethod.Get, _base + name);
            Agent(req);
            using var resp = await _http.SendAsync(req, cts.Token).ConfigureAwait(false);
            if (!resp.IsSuccessStatusCode) throw new ContentException("offline", ((int)resp.StatusCode).ToString());
            return await resp.Content.ReadAsByteArrayAsync(cts.Token).ConfigureAwait(false);
        }

        /// <summary>Reads the catalog from the site (kept for the next time without a connection); without a connection or
        /// when the site does not answer, the last good one. True when there is one to use.</summary>
        public async Task<bool> Refresh(CancellationToken ct = default)
        {
            Directory.CreateDirectory(CacheDir);
            try
            {
                var data = await GetBytes("catalog.json", ct).ConfigureAwait(false);
                var sig = Encoding.ASCII.GetString(await GetBytes("catalog.sig", ct).ConfigureAwait(false));
                if (!Verify(data, sig)) throw new ContentException("signature");
                if (!Parse(data)) throw new ContentException("bad");
                File.WriteAllBytes(Path.Combine(CacheDir, "catalog.json"), data);
                File.WriteAllText(Path.Combine(CacheDir, "catalog.sig"), sig, Encoding.ASCII);
                Online = true;
                Loaded = DateTime.Now;
                return true;
            }
            catch (Exception ex) when (ex is not OperationCanceledException || !ct.IsCancellationRequested)
            {
                Online = false;
                return LoadCache() || HasCatalog;
            }
        }

        /// <summary>The last good catalog kept on this computer (checked again against the signature): the tiles are there
        /// at once at the start and also without a connection.</summary>
        public bool LoadCache()
        {
            try
            {
                var f = Path.Combine(CacheDir, "catalog.json");
                var data = File.ReadAllBytes(f);
                var sig = File.ReadAllText(Path.Combine(CacheDir, "catalog.sig"));
                if (!Verify(data, sig) || !Parse(data)) return false;
                Loaded = File.GetLastWriteTime(f);
                return true;
            }
            catch { return false; }
        }

        bool Parse(byte[] data)
        {
            if (JsonNode.Parse(data) is not JsonObject c || ((int?)c["format"] ?? 0) != 1) return false;
            var models = new Dictionary<string, ContentAsset>(StringComparer.Ordinal);
            var ecos = new Dictionary<string, ContentAsset>(StringComparer.Ordinal);
            foreach (var kind in new[] { "models", "ecosystems" })
                foreach (var o in (c[kind] as JsonArray)?.OfType<JsonObject>() ?? Enumerable.Empty<JsonObject>())
                {
                    var a = new ContentAsset
                    {
                        Kind = kind == "models" ? "model" : "eco",
                        Id = (string?)o["id"] ?? "", Name = (string?)o["name"] ?? "", Folder = (string?)o["folder"] ?? "",
                        Rev = (string?)o["rev"] ?? "", File = (string?)o["file"] ?? "", Sha256 = ((string?)o["sha256"] ?? "").ToLowerInvariant(),
                        Thumb = (string?)o["thumb"] ?? "", Size = (long?)o["size"] ?? 0, Bytes = (long?)o["bytes"] ?? 0,
                        Meta = kind == "models" ? o["meta"] as JsonObject : null,
                        Models = (o["models"] as JsonArray)?.Select(x => (string?)x ?? "").Where(x => x != "").ToArray() ?? Array.Empty<string>(),
                    };
                    // only plain names: nothing of the list is ever used as a path or an address
                    if (!SafeId.IsMatch(a.Id) || !SafeFile.IsMatch(a.File) || !a.File.EndsWith(".zip", StringComparison.Ordinal)
                        || a.Sha256.Length != 64 || a.Size <= 0 || (a.Thumb != "" && !SafeFile.IsMatch(a.Thumb))
                        || a.Models.Any(m => !SafeId.IsMatch(m)) || a.Id[0] != (a.IsEco ? 'e' : 'm')) continue;
                    (a.IsEco ? ecos : models)[a.Id] = a;
                }
            Models = models;
            Ecosystems = ecos;
            return true;
        }

        public ContentAsset? Find(string id) => Models.TryGetValue(id, out var m) ? m : Ecosystems.TryGetValue(id, out var e) ? e : null;

        /// <summary>The models and the ecosystems: the ecosystem, then the models it needs.</summary>
        public IEnumerable<ContentAsset> WithDependencies(ContentAsset a)
        {
            yield return a;
            if (a.IsEco)
                foreach (var m in a.Models)
                    if (Models.TryGetValue(m, out var d)) yield return d;
        }

        // ------------------------------------------------------------------ what is on the computer

        /// <summary>The rev of what is on this computer: a model keeps it in its entry of the library; an ecosystem's rev is
        /// the start of the SHA-256 of its eco.json (as Pack Studio makes it). "" when it cannot be read.</summary>
        public static string InstalledRev(ContentAsset a, string dir)
        {
            try
            {
                if (a.IsEco)
                    return Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(Path.Combine(dir, a.Id, "eco.json")))).ToLowerInvariant().Substring(0, 12);
                return (string?)(JsonNode.Parse(File.ReadAllBytes(Path.Combine(dir, a.Id + ".json"))) as JsonObject)?["rev"] ?? "";
            }
            catch { return ""; }
        }

        /// <summary>Here, and not the rev of the catalog: a newer version is in the cloud. What cannot be read is not
        /// said to be old (no false alarms).</summary>
        public static bool NeedsUpdate(ContentAsset a, string dir)
        {
            if (a.Rev == "" || !IsInstalled(a, dir)) return false;
            var have = InstalledRev(a, dir);
            return have != "" && !string.Equals(have, a.Rev, StringComparison.OrdinalIgnoreCase);
        }

        public static bool IsInstalled(ContentAsset a, string dir) =>
            a.IsEco ? File.Exists(Path.Combine(dir, a.Id, "eco.json"))
                    : File.Exists(Path.Combine(dir, a.Id, "model.blend")) && File.Exists(Path.Combine(dir, a.Id + ".json"));

        /// <summary>The thumbnail of a not downloaded asset, kept on this computer (made once; a new rev makes a new one).</summary>
        public string ThumbPath(ContentAsset a)
        {
            if (a.Thumb == "") return "";
            var name = a.Id + "_" + Regex.Replace(a.Rev, @"[^A-Za-z0-9]", "") + Path.GetExtension(a.Thumb).ToLowerInvariant();
            // the pictures that come with the setup (the name carries the rev: a changed one is not there, it is downloaded)
            var bundled = Path.Combine(BundledThumbs, name);
            return File.Exists(bundled) ? bundled : Path.Combine(CacheDir, "thumbs", name);
        }

        /// <summary>thumbs, next to the program: the pictures of the library made at the release.</summary>
        public string BundledThumbs { get; set; } = Path.Combine(AppContext.BaseDirectory, "thumbs");

        public async Task<string> EnsureThumb(ContentAsset a, CancellationToken ct = default)
        {
            var path = ThumbPath(a);
            if (path == "") return "";
            if (File.Exists(path)) return path;
            try
            {
                var bytes = await GetBytes("thumbs/" + a.Thumb, ct, 20).ConfigureAwait(false);
                Directory.CreateDirectory(Path.GetDirectoryName(path)!);
                var part = path + ".part";
                File.WriteAllBytes(part, bytes);
                File.Move(part, path, true);
                return path;
            }
            catch { return ""; }
        }

        // ------------------------------------------------------------------ download

        readonly Dictionary<string, Task> _running = new(StringComparer.Ordinal);
        readonly object _lock = new();

        /// <summary>Downloads and installs one asset into dir (the models folder of the library, or the ecosystems one).
        /// The same asked twice at once is downloaded once. progress: 0..1.</summary>
        public Task Install(ContentAsset a, string dir, IProgress<double>? progress = null, CancellationToken ct = default)
        {
            lock (_lock)
            {
                if (_running.TryGetValue(a.Id, out var t)) return t;
                t = InstallCore(a, dir, progress, ct);
                _running[a.Id] = t;
                _ = t.ContinueWith(_ => { lock (_lock) _running.Remove(a.Id); }, TaskScheduler.Default);
                return t;
            }
        }

        async Task InstallCore(ContentAsset a, string dir, IProgress<double>? progress, CancellationToken ct)
        {
            if (!Directory.Exists(dir)) throw new ContentException("file", "folder");
            var dl = Path.Combine(CacheDir, "dl");
            Directory.CreateDirectory(dl);
            var part = Path.Combine(dl, a.File + ".part");
            // room for the zip and for what it holds (the zip is not kept)
            try
            {
                var free = new DriveInfo(Path.GetPathRoot(Path.GetFullPath(dir))!).AvailableFreeSpace;
                var have = File.Exists(part) ? new FileInfo(part).Length : 0;
                if (free < (a.Size - have) + a.Bytes + (200L << 20)) throw new ContentException("space", ((a.Size + a.Bytes) >> 20) + " MB");
            }
            catch (ContentException) { throw; }
            catch { }
            await Download(a, part, progress, ct).ConfigureAwait(false);
            string sha;
            using (var s = new FileStream(part, FileMode.Open, FileAccess.Read, FileShare.Read, 1 << 20))
                sha = Convert.ToHexString(await SHA256.HashDataAsync(s, ct).ConfigureAwait(false)).ToLowerInvariant();
            if (sha != a.Sha256)
            {
                try { File.Delete(part); } catch { }
                throw new ContentException("bad", "sha256");
            }
            await Task.Run(() => Unpack(a, part, dir, ct), ct).ConfigureAwait(false);
            try { File.Delete(part); } catch { }
            progress?.Report(1);
        }

        async Task Download(ContentAsset a, string part, IProgress<double>? progress, CancellationToken ct)
        {
            long have = File.Exists(part) ? new FileInfo(part).Length : 0;
            if (have > a.Size) { File.Delete(part); have = 0; }
            if (have == a.Size) { progress?.Report(0.99); return; }
            for (int attempt = 0; ; attempt++)
            {
                try
                {
                    using var req = new HttpRequestMessage(HttpMethod.Get, _base + (a.IsEco ? "ecosystems/" : "models/") + a.File);
                    Agent(req);
                    if (have > 0) req.Headers.Range = new System.Net.Http.Headers.RangeHeaderValue(have, null);
                    using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
                    cts.CancelAfter(TimeSpan.FromSeconds(60));
                    using var resp = await _http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, cts.Token).ConfigureAwait(false);
                    if (resp.StatusCode == HttpStatusCode.RequestedRangeNotSatisfiable) { File.Delete(part); have = 0; continue; }
                    if (!resp.IsSuccessStatusCode) throw new ContentException("offline", ((int)resp.StatusCode).ToString());
                    // 200 to a request with a range: the door sent it all again
                    var append = have > 0 && resp.StatusCode == HttpStatusCode.PartialContent;
                    if (!append) have = 0;
                    using var src = await resp.Content.ReadAsStreamAsync(cts.Token).ConfigureAwait(false);
                    using var dst = new FileStream(part, append ? FileMode.Append : FileMode.Create, FileAccess.Write, FileShare.None, 1 << 20);
                    var buf = new byte[1 << 20];
                    int n;
                    while ((n = await src.ReadAsync(buf, 0, buf.Length, cts.Token).ConfigureAwait(false)) > 0)
                    {
                        await dst.WriteAsync(buf, 0, n, ct).ConfigureAwait(false);
                        have += n;
                        if (have > a.Size) throw new ContentException("bad", "size");
                        cts.CancelAfter(TimeSpan.FromSeconds(60));
                        progress?.Report(Math.Min(0.98, (double)have / a.Size));
                    }
                    if (have != a.Size) throw new ContentException("bad", "size");
                    return;
                }
                catch (Exception ex) when (attempt < 3 && !ct.IsCancellationRequested && (ex is HttpRequestException or IOException or OperationCanceledException or ContentException { Code: "offline" }))
                {
                    // a break of the connection: the part is kept and the download goes on from there
                    if (File.Exists(part)) have = new FileInfo(part).Length;
                    await Task.Delay(1500 * (attempt + 1), ct).ConfigureAwait(false);
                }
                catch (Exception ex) when (ex is HttpRequestException or OperationCanceledException && !ct.IsCancellationRequested)
                {
                    throw new ContentException("offline", ex.Message);
                }
            }
        }

        static void Unpack(ContentAsset a, string zipFile, string dir, CancellationToken ct)
        {
            var incoming = Path.Combine(dir, ".incoming");
            var stage = Path.Combine(incoming, a.Id + "-" + Guid.NewGuid().ToString("N").Substring(0, 8));
            Directory.CreateDirectory(stage);
            var root = Path.GetFullPath(stage) + Path.DirectorySeparatorChar;
            try
            {
                using (var zip = ZipFile.OpenRead(zipFile))
                {
                    long total = 0;
                    foreach (var e in zip.Entries)
                    {
                        ct.ThrowIfCancellationRequested();
                        if (e.FullName.EndsWith("/", StringComparison.Ordinal)) continue;
                        // only what belongs to the asset: <id>/... and <id>.json - nothing else, nothing outside the folder
                        var ok = e.FullName.StartsWith(a.Id + "/", StringComparison.Ordinal) || e.FullName == a.Id + ".json";
                        var dest = Path.GetFullPath(Path.Combine(stage, e.FullName));
                        if (!ok || e.FullName.Contains("..") || !dest.StartsWith(root, StringComparison.OrdinalIgnoreCase)) throw new ContentException("bad", "path");
                        total += e.Length;
                        if (total > a.Bytes + (4L << 20)) throw new ContentException("bad", "size");
                        Directory.CreateDirectory(Path.GetDirectoryName(dest)!);
                        e.ExtractToFile(dest, true);
                    }
                }
                var folder = Path.Combine(stage, a.Id);
                if (!Directory.Exists(folder)) throw new ContentException("bad", "empty");
                if (!a.IsEco && (!File.Exists(Path.Combine(folder, "model.blend")) || !File.Exists(Path.Combine(stage, a.Id + ".json")))) throw new ContentException("bad", "model");
                if (a.IsEco && !File.Exists(Path.Combine(folder, "eco.json"))) throw new ContentException("bad", "eco");
                // a new rev replaces the old one: the entry goes first (nothing lists a model that is half there), the folder next
                var target = Path.Combine(dir, a.Id);
                if (!a.IsEco) { try { File.Delete(Path.Combine(dir, a.Id + ".json")); } catch { } }
                // an update (the asset is here, whole): the new files are put over the old ones and the old ones that the new
                // rev does not have stay - a project saved before still finds its textures, whatever they are called now
                var update = Directory.Exists(target) && File.Exists(Path.Combine(target, a.IsEco ? "eco.json" : "model.blend"));
                if (update)
                {
                    var main = a.IsEco ? "eco.json" : "model.blend";
                    foreach (var f in Directory.EnumerateFiles(folder, "*", SearchOption.AllDirectories).OrderBy(f => Path.GetFileName(f) == main ? 1 : 0))
                    {
                        var dest = Path.Combine(target, Path.GetRelativePath(folder, f));
                        Directory.CreateDirectory(Path.GetDirectoryName(dest)!);
                        try { File.Move(f, dest, true); }
                        catch (IOException) { throw new ContentException("file", "update"); }
                        catch (UnauthorizedAccessException) { throw new ContentException("file", "update"); }
                    }
                }
                else
                {
                    if (Directory.Exists(target)) Directory.Delete(target, true);
                    Directory.Move(folder, target);
                }
                if (!a.IsEco) File.Move(Path.Combine(stage, a.Id + ".json"), Path.Combine(dir, a.Id + ".json"), true);
            }
            finally
            {
                try { Directory.Delete(stage, true); } catch { }
                try { if (!Directory.EnumerateFileSystemEntries(incoming).Any()) Directory.Delete(incoming); } catch { }
            }
        }

        // ------------------------------------------------------------------ removal

        /// <summary>«Rimuovi dal computer»: the files of the asset leave the library (they can be downloaded again). The
        /// entry goes first, so nothing lists a model without its files.</summary>
        public static void Remove(ContentAsset a, string dir)
        {
            if (!a.IsEco) { try { File.Delete(Path.Combine(dir, a.Id + ".json")); } catch { } }
            var folder = Path.Combine(dir, a.Id);
            if (Directory.Exists(folder)) Directory.Delete(folder, true);
        }
    }
}
