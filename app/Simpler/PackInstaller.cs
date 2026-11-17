using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using System.Threading;

namespace Simpler
{
    /// <summary>(1.78.4) Packs of models (.simplerpack): checked and installed into the Simpler parts of the model
    /// library, exactly in the folders the author chose there (Modelli 3D ▸ Simpler ▸ …, Vegetazione ▸ Simpler ▸ …).
    /// A pack is a zip: pack.json (the manifest, with the SHA-256 of every file), pack.sig (its signature, ECDSA P-256
    /// SHA-256), LICENSE.txt, the cover, models/&lt;id&gt;.json and models/&lt;id&gt;/… (the folders of the models).
    /// Only a pack signed with a trusted key goes in, and only if every file is the one signed. What every pack put in is
    /// kept in &lt;library&gt;\packs\installed.json: uninstalling takes away only its models (not those another pack
    /// installed too) and only the folders it made that are left empty. No WPF here: tools/packtest checks every case.</summary>
    public sealed class PackInstaller
    {
        /// <summary>The keys of the official packs: the public key of the author's pack tool (Simpler Pack Studio). Only
        /// the packs signed with its private key, which never leaves the author's computer, install.</summary>
        public static readonly string[] OfficialKeys =
        {
            "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEVGDA911Ejn3/P0GLELJaKdYLkk82LgWvZnkeTMUWZ5kjKvYV5s/f/W9iC8KGFINtnXOV6lCgxPws/ZRvhlsqgg==",
        };

        readonly string _lib, _vegRoot;
        readonly string[] _keys;

        public PackInstaller(string libraryDir, string vegRoot, IEnumerable<string> keys)
        {
            _lib = libraryDir;
            _vegRoot = string.IsNullOrWhiteSpace(vegRoot) ? "Vegetazione" : vegRoot.Trim('/');
            _keys = keys.Where(k => !string.IsNullOrWhiteSpace(k)).Select(k => k.Trim()).Distinct().ToArray();
        }

        string RegDir => Path.Combine(_lib, "packs");
        string RegFile => Path.Combine(RegDir, "installed.json");
        static readonly Regex IdRx = new(@"^[A-Za-z0-9_\-]{1,64}$");

        public sealed class Info
        {
            public JsonObject Manifest = new();
            public string Error = "";
            public string PackId = "", Title = "", Description = "", Version = "", Author = "", License = "";
            public int Models;
            public long Bytes;
            public string? InstalledVersion;
            public string CoverFile = "", LicenseText = "";
            public List<string> Folders = new();          // where it goes, in the library of this computer
            public bool Ok => Error == "";
        }

        // ---------------------------------------------------------------- reading and checking

        static byte[] Read(ZipArchiveEntry e)
        {
            using var s = e.Open();
            using var ms = new MemoryStream();
            s.CopyTo(ms);
            return ms.ToArray();
        }

        /// <summary>(Luca: «una voce package a cartelle blu») every pack has its own folder under «Packages» (Modelli 3D ▸
        /// Packages, Vegetazione ▸ Packages): Packages/&lt;title&gt;/&lt;path chosen by the author&gt;. What a pack brings is
        /// apart from Simpler's own models and from the user's, and its uninstall takes away just that folder.</summary>
        public string Destination(string part, string path, string title)
        {
            var name = PackName(title);
            path = PackPath(path, title);
            var root = (part == "plants" ? _vegRoot + "/" + PacksFolder : PacksFolder) + "/" + name;
            return path == "" ? root : root + "/" + path;
        }

        /// <summary>The name of the folder of a pack in «Packages»: its title.</summary>
        public static string PackName(string? title)
        {
            var name = Clean((title ?? "").Replace('/', '-').Replace('\\', '-'));
            return name == "" ? "Package" : name;
        }

        /// <summary>The path of a model inside its pack, without the folders named as the pack: the pack has its own
        /// folder in «Packages» already («Animals/Victorian era» of «Victorian era» → «Animals»).</summary>
        public static string PackPath(string? path, string? title)
        {
            var name = PackName(title);
            return string.Join("/", Clean(path).Split('/', StringSplitOptions.RemoveEmptyEntries)
                                              .Where(x => !string.Equals(x, name, StringComparison.OrdinalIgnoreCase)));
        }

        /// <summary>The folder of the packs, in Modelli 3D and (under the vegetation root) in Vegetazione.</summary>
        public const string PacksFolder = "Packages";

        static string Clean(string? p) =>
            string.Join("/", (p ?? "").Replace('\\', '/').Split('/').Select(x => x.Trim()).Where(x => x != "" && x != "." && x != ".."));

        static bool SafeEntry(string name) =>
            !name.StartsWith("/") && !name.Contains('\\') && !name.Split('/').Any(x => x == ".." || x == "." || x == "") && !name.Contains(':');

        /// <summary>The manifest and its signature (not yet the files: those are checked while installing).</summary>
        public Info Inspect(string packFile, string? tempDir = null)
        {
            var info = new Info();
            try
            {
                using var zip = ZipFile.OpenRead(packFile);
                var me = zip.GetEntry("pack.json");
                var se = zip.GetEntry("pack.sig");
                if (me == null || se == null) { info.Error = "not a Simpler pack"; return info; }
                var mbytes = Read(me);
                var sig = Convert.FromBase64String(Encoding.ASCII.GetString(Read(se)).Trim());
                if (!Verify(mbytes, sig)) { info.Error = "signature"; return info; }
                if (JsonNode.Parse(mbytes) is not JsonObject m || (int?)m["format"] != 1) { info.Error = "format"; return info; }
                info.Manifest = m;
                info.PackId = (string?)m["packId"] ?? "";
                if (!IdRx.IsMatch(info.PackId)) { info.Error = "format"; return info; }
                info.Title = (string?)m["title"] ?? "";
                info.Description = (string?)m["description"] ?? "";
                info.Version = (string?)m["version"] ?? "";
                info.Author = (string?)m["author"] ?? "";
                info.License = ((string?)m["license"]?["name"] ?? "") + " " + ((string?)m["license"]?["version"] ?? "");
                info.Bytes = (long?)m["bytes"] ?? 0;
                var models = m["models"] as JsonArray ?? new JsonArray();
                info.Models = models.Count;
                foreach (var x in models.OfType<JsonObject>())
                {
                    if (!IdRx.IsMatch((string?)x["id"] ?? "")) { info.Error = "format"; return info; }
                    var d = Destination((string?)x["part"] ?? "models", (string?)x["path"] ?? "", info.Title);
                    if (!info.Folders.Contains(d)) info.Folders.Add(d);
                }
                info.Folders.Sort(StringComparer.Ordinal);
                if (m["files"] is not JsonObject files || files.Any(kv => !SafeEntry(kv.Key))) { info.Error = "format"; return info; }
                info.InstalledVersion = (string?)(Registry()["packs"]?[info.PackId]?["version"]);
                var lic = zip.GetEntry((string?)m["license"]?["file"] ?? "LICENSE.txt");
                if (lic != null) info.LicenseText = Encoding.UTF8.GetString(Read(lic));
                var cover = (string?)m["cover"] ?? "";
                if (tempDir != null && cover != "" && SafeEntry(cover) && zip.GetEntry(cover) is ZipArchiveEntry ce)
                {
                    Directory.CreateDirectory(tempDir);
                    info.CoverFile = Path.Combine(tempDir, info.PackId + "_cover" + Path.GetExtension(cover));
                    File.WriteAllBytes(info.CoverFile, Read(ce));
                }
            }
            catch (Exception ex) { info.Error = ex is InvalidDataException ? "not a Simpler pack" : ex.Message; }
            return info;
        }

        bool Verify(byte[] data, byte[] sig)
        {
            foreach (var k in _keys)
            {
                try
                {
                    using var ec = ECDsa.Create();
                    ec.ImportSubjectPublicKeyInfo(Convert.FromBase64String(k), out _);
                    if (ec.VerifyData(data, sig, HashAlgorithmName.SHA256, DSASignatureFormat.IeeeP1363FixedFieldConcatenation)) return true;
                }
                catch { }
            }
            return false;
        }

        // ---------------------------------------------------------------- the registry

        public JsonObject Registry()
        {
            try { if (File.Exists(RegFile) && JsonNode.Parse(File.ReadAllText(RegFile)) is JsonObject r) { r["packs"] ??= new JsonObject(); return r; } }
            catch { }
            return new JsonObject { ["packs"] = new JsonObject() };
        }

        void SaveRegistry(JsonObject r)
        {
            Directory.CreateDirectory(RegDir);
            WriteAtomic(RegFile, r.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
        }

        static void WriteAtomic(string file, string text)
        {
            File.WriteAllText(file + ".part", text, new UTF8Encoding(false));
            File.Move(file + ".part", file, true);
        }

        /// <summary>The packs installed: id, title, version, author, date, models, folders, cover (a file in the library).</summary>
        public List<JsonObject> Installed()
        {
            var list = new List<JsonObject>();
            foreach (var kv in Registry()["packs"]!.AsObject())
            {
                if (kv.Value is not JsonObject p) continue;
                var o = (JsonObject)p.DeepClone();
                o["packId"] = kv.Key;
                var cover = (string?)p["cover"] ?? "";
                o["coverFile"] = cover == "" ? "" : Path.Combine(RegDir, kv.Key, cover);
                list.Add(o);
            }
            return list.OrderBy(p => (string?)p["title"] ?? "", StringComparer.CurrentCultureIgnoreCase).ToList();
        }

        // ---------------------------------------------------------------- folders of the library (folders.json)

        string FoldersFile => Path.Combine(_lib, "folders.json");

        List<string> LoadFolders()
        {
            try
            {
                if (File.Exists(FoldersFile) && JsonNode.Parse(File.ReadAllText(FoldersFile))?["folders"] is JsonArray a)
                    return a.Select(x => (string?)x ?? "").Where(x => x != "").ToList();
            }
            catch { }
            return new List<string>();
        }

        void SaveFolders(IEnumerable<string> folders)
        {
            JsonObject d;
            try { d = (File.Exists(FoldersFile) ? JsonNode.Parse(File.ReadAllText(FoldersFile)) as JsonObject : null) ?? new JsonObject(); }
            catch { d = new JsonObject(); }
            var list = folders.Select(Clean).Where(f => f != "").Distinct().OrderBy(f => f, StringComparer.OrdinalIgnoreCase).ToList();
            d["folders"] = new JsonArray(list.Select(f => (JsonNode)JsonValue.Create(f)!).ToArray());
            WriteAtomic(FoldersFile, d.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
        }

        static IEnumerable<string> WithParents(string f)
        {
            for (var p = f; p != ""; p = p.Contains('/') ? p[..p.LastIndexOf('/')] : "") yield return p;
        }

        HashSet<string> ModelFoldersInLibrary()
        {
            var set = new HashSet<string>(StringComparer.Ordinal);
            if (!Directory.Exists(_lib)) return set;
            foreach (var f in Directory.EnumerateFiles(_lib, "*.json"))
            {
                if (Path.GetFileName(f) == "folders.json") continue;
                try { if (JsonNode.Parse(File.ReadAllText(f)) is JsonObject e) foreach (var p in WithParents(Clean((string?)e["folder"]))) set.Add(p); }
                catch { }
            }
            return set;
        }

        // ---------------------------------------------------------------- install

        /// <summary>Installs (or updates, or installs again) the pack. Every file is checked against the signed manifest
        /// while it is written in a staging folder; only when all are right do the models take their places. A model
        /// of an older version of the same pack that is no longer in it goes away (unless another pack has it).</summary>
        public void Install(string packFile, Action<int, int, string>? progress = null, CancellationToken ct = default)
        {
            var info = Inspect(packFile);
            if (!info.Ok) throw new InvalidOperationException(info.Error);
            var m = info.Manifest;
            var files = (JsonObject)m["files"]!;
            var models = (m["models"] as JsonArray ?? new JsonArray()).OfType<JsonObject>().ToList();
            var ids = models.Select(x => (string)x["id"]!).ToList();
            // room on the disk (the files as they will be, and a margin)
            try
            {
                var drive = new DriveInfo(Path.GetPathRoot(Path.GetFullPath(_lib))!);
                if (drive.IsReady && drive.AvailableFreeSpace < info.Bytes * 11 / 10 + (64L << 20)) throw new IOException("disk full");
            }
            catch (IOException) { throw; }
            catch { }

            Directory.CreateDirectory(RegDir);
            var stage = Path.Combine(RegDir, ".staging_" + info.PackId);
            if (Directory.Exists(stage)) Directory.Delete(stage, true);
            Directory.CreateDirectory(stage);
            try
            {
                using (var zip = ZipFile.OpenRead(packFile))
                {
                    var names = zip.Entries.Where(e => !e.FullName.EndsWith("/")).Select(e => e.FullName).ToHashSet(StringComparer.Ordinal);
                    // every file of the manifest in the zip, nothing else (but the manifest and its signature)
                    foreach (var kv in files) if (!names.Contains(kv.Key)) throw new InvalidDataException("missing " + kv.Key);
                    foreach (var n in names) if (n != "pack.json" && n != "pack.sig" && !files.ContainsKey(n)) throw new InvalidDataException("unsigned " + n);
                    var list = files.Select(kv => kv.Key).ToList();
                    var buf = new byte[1 << 20];
                    for (int i = 0; i < list.Count; i++)
                    {
                        ct.ThrowIfCancellationRequested();
                        var name = list[i];
                        progress?.Invoke(i, list.Count, name);
                        var target = Path.GetFullPath(Path.Combine(stage, name.Replace('/', Path.DirectorySeparatorChar)));
                        if (!target.StartsWith(Path.GetFullPath(stage) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                            throw new InvalidDataException("path " + name);
                        Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                        using var h = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
                        using (var src = zip.GetEntry(name)!.Open())
                        using (var dst = new FileStream(target, FileMode.Create, FileAccess.Write, FileShare.None, 1 << 20))
                        {
                            int n;
                            while ((n = src.Read(buf, 0, buf.Length)) > 0) { ct.ThrowIfCancellationRequested(); dst.Write(buf, 0, n); h.AppendData(buf, 0, n); }
                        }
                        if (!string.Equals(Convert.ToHexString(h.GetHashAndReset()), (string?)files[name], StringComparison.OrdinalIgnoreCase))
                            throw new InvalidDataException("changed " + name);
                    }
                    progress?.Invoke(list.Count, list.Count, "");
                }
                foreach (var id in ids)
                    if (!File.Exists(Path.Combine(stage, "models", id + ".json"))) throw new InvalidDataException("missing " + id);

                // ---- commit: the models in their places
                var reg = Registry();
                var packs = reg["packs"]!.AsObject();
                var old = packs[info.PackId] as JsonObject;
                var oldIds = (old?["models"] as JsonArray)?.Select(x => (string?)x ?? "").ToList() ?? new List<string>();
                var others = OtherModels(packs, info.PackId);
                // models already in the library before any pack (the author's own library, where the pack was made):
                // replaced by the pack's copy, but never taken away by uninstalling it
                var kept = (old?["kept"] as JsonArray)?.Select(x => (string?)x ?? "").ToHashSet(StringComparer.Ordinal) ?? new HashSet<string>(StringComparer.Ordinal);
                foreach (var id in ids)
                    if (!oldIds.Contains(id) && !others.Contains(id) && File.Exists(Path.Combine(_lib, id + ".json"))) kept.Add(id);
                // (Luca: the author's own models went into «Packages» and left his Simpler folders) where each of them
                // was before the pack: uninstalling (or a version without it) puts it back there
                var keptFrom = (old?["keptFrom"] as JsonObject)?.DeepClone() as JsonObject ?? new JsonObject();
                foreach (var id in kept)
                    if (keptFrom[id] == null)
                        try { if (JsonNode.Parse(File.ReadAllText(Path.Combine(_lib, id + ".json"))) is JsonObject e0 && !IsPacks(Clean((string?)e0["folder"]))) keptFrom[id] = Clean((string?)e0["folder"]); }
                        catch { }
                var gone = kept.Where(id => !ids.Contains(id)).ToList();
                kept.IntersectWith(ids);
                foreach (var x in models)
                {
                    var id = (string)x["id"]!;
                    var dest = Destination((string?)x["part"] ?? "models", (string?)x["path"] ?? "", info.Title);
                    var entry = JsonNode.Parse(File.ReadAllText(Path.Combine(stage, "models", id + ".json"))) as JsonObject ?? new JsonObject();
                    entry["id"] = id;
                    entry["folder"] = dest;
                    entry["pack"] = info.PackId;
                    var dir = Path.Combine(_lib, id);
                    var newDir = Path.Combine(stage, "models", id);
                    if (Directory.Exists(dir)) Directory.Delete(dir, true);
                    if (Directory.Exists(newDir)) Directory.Move(newDir, dir); else Directory.CreateDirectory(dir);
                    WriteAtomic(Path.Combine(_lib, id + ".json"), entry.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
                }
                var oldKept = (old?["kept"] as JsonArray)?.Select(x => (string?)x ?? "").ToHashSet(StringComparer.Ordinal) ?? new HashSet<string>();
                foreach (var id in oldIds.Except(ids))
                    if (!others.Contains(id) && !oldKept.Contains(id)) RemoveModel(id);
                foreach (var id in oldKept.Except(ids).Concat(gone).Distinct())
                    if (!others.Contains(id)) GiveBack(id, Before((string?)keptFrom[id], info.PackId, id));
                foreach (var id in keptFrom.Select(kv => kv.Key).ToList()) if (!kept.Contains(id)) keptFrom.Remove(id);

                // ---- the folders: those of the pack (and their parents) in the library; those it had made before and
                // are left empty now (an update that moved models) go
                var folders = LoadFolders();
                var have = folders.ToHashSet(StringComparer.Ordinal);
                var made = (old?["madeFolders"] as JsonArray)?.Select(x => (string?)x ?? "").ToList() ?? new List<string>();
                foreach (var f in info.Folders.SelectMany(WithParents))
                    if (have.Add(f)) { folders.Add(f); made.Add(f); }
                    else if (IsPacks(f)) made.Add(f);       // (in «Packages» only the packs write: there already or not, the pack's)
                SaveFolders(folders);
                made = made.Distinct().ToList();

                // ---- the pack itself: cover, licence, manifest (for the list of the installed packs)
                var pdir = Path.Combine(RegDir, info.PackId);
                if (Directory.Exists(pdir)) Directory.Delete(pdir, true);
                Directory.CreateDirectory(pdir);
                File.Copy(packFileEntry(stage, "pack.json", m), Path.Combine(pdir, "pack.json"));
                var cover = (string?)m["cover"] ?? "";
                if (cover != "" && File.Exists(Path.Combine(stage, cover))) File.Copy(Path.Combine(stage, cover), Path.Combine(pdir, Path.GetFileName(cover)));
                var lic = (string?)m["license"]?["file"] ?? "LICENSE.txt";
                if (File.Exists(Path.Combine(stage, lic))) File.Copy(Path.Combine(stage, lic), Path.Combine(pdir, "LICENSE.txt"));
                packs[info.PackId] = new JsonObject
                {
                    ["title"] = info.Title,
                    ["description"] = info.Description,
                    ["version"] = info.Version,
                    ["author"] = info.Author,
                    ["license"] = info.License.Trim(),
                    ["installed"] = DateTime.Now.ToString("yyyy-MM-dd HH:mm"),
                    ["cover"] = cover == "" ? "" : Path.GetFileName(cover),
                    ["bytes"] = info.Bytes,
                    ["models"] = new JsonArray(ids.Select(i => (JsonNode)JsonValue.Create(i)!).ToArray()),
                    ["folders"] = new JsonArray(info.Folders.Select(f => (JsonNode)JsonValue.Create(f)!).ToArray()),
                    ["madeFolders"] = new JsonArray(made.Select(f => (JsonNode)JsonValue.Create(f)!).ToArray()),
                    ["kept"] = new JsonArray(kept.OrderBy(k => k, StringComparer.Ordinal).Select(k => (JsonNode)JsonValue.Create(k)!).ToArray()),
                    ["keptFrom"] = keptFrom,
                };
                PruneFolders(reg);
                SaveRegistry(reg);
            }
            finally
            {
                try { if (Directory.Exists(stage)) Directory.Delete(stage, true); } catch { }
            }
        }

        /// <summary>A model that was in the library before the pack, no longer the pack's: back in the folder it had (out
        /// of «Packages», read only), with its folder in the library.</summary>
        void GiveBack(string id, string? folder)
        {
            var f = Path.Combine(_lib, id + ".json");
            try
            {
                if (JsonNode.Parse(File.ReadAllText(f)) is not JsonObject e) return;
                e.Remove("pack");
                folder = Clean(folder);
                if (folder != "" && !IsPacks(folder))
                {
                    e["folder"] = folder;
                    var folders = LoadFolders();
                    var have = folders.ToHashSet(StringComparer.Ordinal);
                    foreach (var x in WithParents(folder)) if (have.Add(x)) folders.Add(x);
                    SaveFolders(folders);
                }
                WriteAtomic(f, e.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
            }
            catch { }
        }

        /// <summary>The folder a kept model goes back to: the one remembered, unless it was already in «Packages» (moved
        /// there by hand), else its place in the Simpler part from the pack's manifest.</summary>
        string? Before(string? remembered, string packId, string id) =>
            !string.IsNullOrEmpty(remembered) && !IsPacks(Clean(remembered)) ? remembered : FolderBefore(packId, id);

        bool IsPacks(string f) => f == PacksFolder || f.StartsWith(PacksFolder + "/", StringComparison.Ordinal)
                                  || f == _vegRoot + "/" + PacksFolder || f.StartsWith(_vegRoot + "/" + PacksFolder + "/", StringComparison.Ordinal);

        /// <summary>(packs installed before «keptFrom») the folder a kept model had: its place in the Simpler part, as the
        /// pack's manifest gives it.</summary>
        string? FolderBefore(string packId, string id)
        {
            try
            {
                var man = JsonNode.Parse(File.ReadAllText(Path.Combine(RegDir, packId, "pack.json")));
                var m = (man?["models"] as JsonArray)?.OfType<JsonObject>().FirstOrDefault(x => (string?)x["id"] == id);
                if (m == null) return null;
                var root = (string?)m["part"] == "plants" ? _vegRoot + "/Simpler" : "Simpler";
                var path = Clean((string?)m["path"]);
                return path == "" ? root : root + "/" + path;
            }
            catch { return null; }
        }

        // (the manifest as read from the zip: written in the staging folder for the copy kept with the pack)
        static string packFileEntry(string stage, string name, JsonObject m)
        {
            var f = Path.Combine(stage, name);
            File.WriteAllText(f, m.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
            return f;
        }

        static HashSet<string> OtherModels(JsonObject packs, string except)
        {
            var set = new HashSet<string>(StringComparer.Ordinal);
            foreach (var kv in packs)
                if (kv.Key != except && kv.Value?["models"] is JsonArray a)
                    foreach (var x in a) set.Add((string?)x ?? "");
            return set;
        }

        /// <summary>A model out of the library, as Simpler deletes one (models.delete): its textures stay where they are -
        /// the copies of the model already in a scene (and in saved projects) show them from that folder.</summary>
        void RemoveModel(string id)
        {
            if (!IdRx.IsMatch(id)) return;
            var dir = Path.Combine(_lib, id);
            var tex = Path.Combine(dir, "textures");
            if (Directory.Exists(tex) && Directory.EnumerateFileSystemEntries(tex).Any())
            {
                foreach (var f in Directory.EnumerateFileSystemEntries(dir))
                {
                    if (string.Equals(Path.GetFileName(f), "textures", StringComparison.OrdinalIgnoreCase)) continue;
                    try { if (Directory.Exists(f)) Directory.Delete(f, true); else File.Delete(f); } catch { }
                }
            }
            else if (Directory.Exists(dir)) Directory.Delete(dir, true);
            var json = Path.Combine(_lib, id + ".json");
            if (File.Exists(json)) File.Delete(json);
        }

        /// <summary>The folders made by packs that hold no model any more (none of their own, none below), unless another
        /// installed pack still uses them: out of the library.</summary>
        void PruneFolders(JsonObject reg)
        {
            var packs = reg["packs"]!.AsObject();
            var used = new HashSet<string>(StringComparer.Ordinal);
            foreach (var kv in packs)
                if (kv.Value?["folders"] is JsonArray a)
                    foreach (var x in a) foreach (var p in WithParents((string?)x ?? "")) used.Add(p);
            var withModels = ModelFoldersInLibrary();
            var made = new HashSet<string>(StringComparer.Ordinal);
            foreach (var kv in packs)
                if (kv.Value?["madeFolders"] is JsonArray a) foreach (var x in a) made.Add((string?)x ?? "");
            made.UnionWith(((reg["orphanFolders"] as JsonArray)?.Select(x => (string?)x ?? "")) ?? Enumerable.Empty<string>());
            var folders = LoadFolders();
            var keep = new List<string>();
            var gone = new List<string>();
            foreach (var f in folders)
            {
                var hasChildFolder = folders.Any(o => o.StartsWith(f + "/", StringComparison.Ordinal) && !(made.Contains(o) && !used.Contains(o) && !withModels.Contains(o)));
                if (made.Contains(f) && !used.Contains(f) && !withModels.Contains(f) && !hasChildFolder) gone.Add(f); else keep.Add(f);
            }
            if (gone.Count > 0) SaveFolders(keep);
            reg.Remove("orphanFolders");
        }

        // ---------------------------------------------------------------- uninstall

        public void Uninstall(string packId)
        {
            var reg = Registry();
            var packs = reg["packs"]!.AsObject();
            if (packs[packId] is not JsonObject p) return;
            var ids = (p["models"] as JsonArray)?.Select(x => (string?)x ?? "").ToList() ?? new List<string>();
            var others = OtherModels(packs, packId);
            var kept = (p["kept"] as JsonArray)?.Select(x => (string?)x ?? "").ToHashSet(StringComparer.Ordinal) ?? new HashSet<string>();
            foreach (var id in ids) if (!others.Contains(id) && !kept.Contains(id)) RemoveModel(id);
            // (a model that was in the library before the pack: it stays, no longer the pack's, back in its folder)
            var from = p["keptFrom"] as JsonObject;
            foreach (var id in kept)
                if (!others.Contains(id)) GiveBack(id, Before((string?)from?[id], packId, id));
            // a model another pack keeps: it stays, and stays that pack's
            foreach (var id in ids.Where(others.Contains))
            {
                var owner = packs.First(kv => kv.Key != packId && kv.Value?["models"] is JsonArray a && a.Any(x => (string?)x == id)).Key;
                var f = Path.Combine(_lib, id + ".json");
                try { if (JsonNode.Parse(File.ReadAllText(f)) is JsonObject e) { e["pack"] = owner; WriteAtomic(f, e.ToJsonString(new JsonSerializerOptions { WriteIndented = true })); } }
                catch { }
            }
            var made = (p["madeFolders"] as JsonArray)?.Select(x => (JsonNode)JsonValue.Create((string?)x ?? "")!).ToArray() ?? Array.Empty<JsonNode>();
            packs.Remove(packId);
            var orphans = reg["orphanFolders"] as JsonArray ?? new JsonArray();
            foreach (var x in made) orphans.Add(x.DeepClone());
            // (Luca: «è giusto lasciare la cartella?») its folders in «Packages» go too, even if they were there before it
            var own = new[] { Destination("models", "", (string?)p["title"] ?? ""), Destination("plants", "", (string?)p["title"] ?? "") };
            foreach (var f in ((p["folders"] as JsonArray)?.Select(x => (string?)x ?? "") ?? Enumerable.Empty<string>()).SelectMany(WithParents)
                              .Concat(LoadFolders().Where(f => own.Any(o => f == o || f.StartsWith(o + "/", StringComparison.Ordinal)))).Distinct())
                if (IsPacks(f)) orphans.Add(JsonValue.Create(f));
            reg["orphanFolders"] = orphans;
            PruneFolders(reg);
            // the folders it made that another pack still uses go to that pack (they are taken away with it)
            foreach (var x in made)
            {
                var f = (string?)x ?? "";
                if (!LoadFolders().Contains(f)) continue;
                var owner = packs.FirstOrDefault(kv => kv.Value?["folders"] is JsonArray a && a.Any(y => WithParents((string?)y ?? "").Contains(f)));
                if (owner.Value is JsonObject op)
                {
                    var mf = op["madeFolders"] as JsonArray ?? new JsonArray();
                    if (!mf.Any(y => (string?)y == f)) mf.Add(JsonValue.Create(f));
                    op["madeFolders"] = mf;
                }
            }
            SaveRegistry(reg);
            var pdir = Path.Combine(RegDir, packId);
            try { if (Directory.Exists(pdir)) Directory.Delete(pdir, true); } catch { }
        }
    }
}
