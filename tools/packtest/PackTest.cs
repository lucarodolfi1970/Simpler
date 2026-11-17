// (1.78.4) Non-regression of the packs (PackInstaller): every combination of install, uninstall, install again, install
// over, update, downgrade, two packs sharing models and folders, packs changed or signed by someone else, unsafe paths,
// the vegetation in a library in another language, the user's own models and folders left alone.
// Run: dotnet run --project tools/packtest   (prints PACKS_OK or PACKS_FAIL and the failed checks)
using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using Simpler;

static class PackTest
{
    static readonly List<string> Bad = new();
    static int _checks;
    static void Check(bool ok, string what) { _checks++; if (!ok) { Bad.Add(what); Console.WriteLine("  FAIL " + what); } }

    sealed record M(string Id, string Name, string Part, string Path, string Content = "blend");

    static ECDsa Key = ECDsa.Create(ECCurve.NamedCurves.nistP256);
    static string Pub(ECDsa k) => Convert.ToBase64String(k.ExportSubjectPublicKeyInfo());

    /// <summary>A pack as Simpler Pack Studio writes it (format 1).</summary>
    static string MakePack(string dir, string packId, string version, IEnumerable<M> models, ECDsa? key = null,
                           Action<Dictionary<string, byte[]>>? tamperAfterSign = null, string? extraEntry = null)
    {
        var files = new Dictionary<string, byte[]>();
        foreach (var m in models)
        {
            files[$"models/{m.Id}.json"] = Encoding.UTF8.GetBytes(new JsonObject { ["id"] = m.Id, ["name"] = m.Name, ["folder"] = m.Path, ["rev"] = version }.ToJsonString());
            files[$"models/{m.Id}/model.blend"] = Encoding.UTF8.GetBytes(m.Content + " " + m.Id + " " + version);
            files[$"models/{m.Id}/thumb.png"] = new byte[] { 137, 80, 78, 71 };
            files[$"models/{m.Id}/textures/a.png"] = Encoding.UTF8.GetBytes("tex " + m.Id);
        }
        files["LICENSE.txt"] = Encoding.UTF8.GetBytes("licence");
        files["cover.jpg"] = new byte[] { 255, 216, 255 };
        if (extraEntry != null) files[extraEntry] = new byte[] { 1 };
        var hashes = new JsonObject();
        foreach (var kv in files) hashes[kv.Key] = Convert.ToHexString(SHA256.HashData(kv.Value)).ToLowerInvariant();
        var ms = models.ToList();
        var manifest = new JsonObject
        {
            ["format"] = 1, ["packId"] = packId, ["title"] = "Pack " + packId, ["description"] = "d", ["version"] = version,
            ["author"] = "Test", ["license"] = new JsonObject { ["name"] = "Simpler Content License", ["version"] = "1.0", ["file"] = "LICENSE.txt" },
            ["cover"] = "cover.jpg", ["bytes"] = files.Values.Sum(v => (long)v.Length),
            ["models"] = new JsonArray(ms.Select(m => (JsonNode)new JsonObject { ["id"] = m.Id, ["name"] = m.Name, ["part"] = m.Part, ["path"] = m.Path }).ToArray()),
            ["files"] = hashes,
        };
        var mb = Encoding.UTF8.GetBytes(manifest.ToJsonString());
        var sig = Convert.ToBase64String((key ?? Key).SignData(mb, HashAlgorithmName.SHA256, DSASignatureFormat.IeeeP1363FixedFieldConcatenation));
        tamperAfterSign?.Invoke(files);
        var path = Path.Combine(dir, $"{packId}_{version}_{Guid.NewGuid():N}.simplerpack");
        using (var z = ZipFile.Open(path, ZipArchiveMode.Create))
        {
            foreach (var kv in files) using (var s = z.CreateEntry(kv.Key).Open()) s.Write(kv.Value);
            using (var s = z.CreateEntry("pack.json").Open()) s.Write(mb);
            using (var s = z.CreateEntry("pack.sig").Open()) s.Write(Encoding.ASCII.GetBytes(sig));
        }
        return path;
    }

    static string Lib = "", Tmp = "";
    static List<string> Folders() => (JsonNode.Parse(File.ReadAllText(Path.Combine(Lib, "folders.json")))!["folders"] as JsonArray)!.Select(x => (string)x!).ToList();
    static JsonObject? Entry(string id) => File.Exists(Path.Combine(Lib, id + ".json")) ? JsonNode.Parse(File.ReadAllText(Path.Combine(Lib, id + ".json"))) as JsonObject : null;
    static bool Has(string id) => Entry(id) != null && File.Exists(Path.Combine(Lib, id, "model.blend"));
    static string Blend(string id) => File.ReadAllText(Path.Combine(Lib, id, "model.blend"));
    // (the textures of a model taken out stay, as when Simpler deletes a model: scenes still use them - a folder of a
    // model without its card is not in the library)
    static bool Listed(string f)
    {
        var rel = Path.GetRelativePath(Lib, f).Split(Path.DirectorySeparatorChar);
        return rel.Length == 1 || File.Exists(Path.Combine(Lib, rel[0] + ".json"));
    }
    static string Snapshot() => string.Join("\n", Directory.EnumerateFiles(Lib, "*", SearchOption.AllDirectories)
        .Where(f => !f.Contains(Path.DirectorySeparatorChar + "packs" + Path.DirectorySeparatorChar) && Listed(f))
        .OrderBy(f => f, StringComparer.Ordinal).Select(f => Path.GetRelativePath(Lib, f) + ":" + (Path.GetFileName(f) == "folders.json"
            ? string.Join("|", Folders().OrderBy(x => x, StringComparer.Ordinal))           // (the same folders, whatever the order)
            : Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(f))))));

    static void Fresh(string vegRoot = "Vegetazione")
    {
        Lib = Path.Combine(Tmp, "lib_" + Guid.NewGuid().ToString("N")[..8]);
        Directory.CreateDirectory(Lib);
        // the user's library: their own folders (one of them inside Simpler) and a model of their own
        File.WriteAllText(Path.Combine(Lib, "folders.json"), new JsonObject { ["folders"] = new JsonArray("Altro", "Simpler", "Simpler/Characters", vegRoot, vegRoot + "/Simpler") }.ToJsonString());
        Directory.CreateDirectory(Path.Combine(Lib, "m_user"));
        File.WriteAllText(Path.Combine(Lib, "m_user", "model.blend"), "mine");
        File.WriteAllText(Path.Combine(Lib, "m_user.json"), new JsonObject { ["id"] = "m_user", ["name"] = "Mine", ["folder"] = "Altro" }.ToJsonString());
    }

    static bool Throws(Action a) { try { a(); return false; } catch { return true; } }

    static int Main()
    {
        Tmp = Path.Combine(Path.GetTempPath(), "simpler_packtest_" + Guid.NewGuid().ToString("N")[..8]);
        Directory.CreateDirectory(Tmp);
        try
        {
            var keys = new[] { Pub(Key) };
            var victorian = new[]
            {
                new M("m_boy", "Boy", "models", "Characters/Victorian era"),
                new M("m_coach", "Coach", "models", "Vehicles/Carriages"),
                new M("m_hedge", "Hedge", "plants", "Gardens/Victorian"),
            };

            // 1. install
            Fresh();
            var pi = new PackInstaller(Lib, "Vegetazione", keys);
            var v1 = MakePack(Tmp, "p_vic", "1.0", victorian);
            var info = pi.Inspect(v1, Tmp);
            Check(info.Ok && info.Models == 3 && info.InstalledVersion == null, "inspect a new pack");
            Check(info.Folders.SequenceEqual(new[] { "Packages/Pack p_vic/Characters/Victorian era", "Packages/Pack p_vic/Vehicles/Carriages", "Vegetazione/Packages/Pack p_vic/Gardens/Victorian" }), "destinations: " + string.Join(", ", info.Folders));
            Check(File.Exists(info.CoverFile), "cover extracted for the window");
            // (Luca: «Packages/Victorian era/Animals/Victorian era») the folders named as the pack are its folder already
            Check(pi.Destination("models", "Animals/Victorian era", "Victorian era") == "Packages/Victorian era/Animals"
                  && pi.Destination("plants", "Gardens/victorian era/Roses", "Victorian era") == "Vegetazione/Packages/Victorian era/Gardens/Roses"
                  && pi.Destination("models", "Animals/Horses", "Farm") == "Packages/Farm/Animals/Horses", "destination: no folder named as the pack");
            var before = Snapshot();
            pi.Install(v1);
            Check(Has("m_boy") && Has("m_coach") && Has("m_hedge"), "install: models in the library");
            Check((string?)Entry("m_boy")!["folder"] == "Packages/Pack p_vic/Characters/Victorian era", "install: folder of a model");
            Check((string?)Entry("m_hedge")!["folder"] == "Vegetazione/Packages/Pack p_vic/Gardens/Victorian", "install: folder of a plant");
            Check(new[] { "Packages", "Packages/Pack p_vic", "Packages/Pack p_vic/Characters/Victorian era", "Packages/Pack p_vic/Vehicles", "Packages/Pack p_vic/Vehicles/Carriages", "Vegetazione/Packages", "Vegetazione/Packages/Pack p_vic/Gardens", "Vegetazione/Packages/Pack p_vic/Gardens/Victorian" }.All(Folders().Contains), "install: folders and their parents");
            Check(pi.Installed().Count == 1 && (string?)pi.Installed()[0]["version"] == "1.0", "install: in the list of installed packs");
            Check(File.Exists((string)pi.Installed()[0]["coverFile"]!), "install: cover kept for the list");
            Check(!Directory.EnumerateDirectories(Path.Combine(Lib, "packs")).Any(d => Path.GetFileName(d).StartsWith(".staging")), "install: no staging left");
            Check(pi.Inspect(v1).InstalledVersion == "1.0", "inspect knows the installed version");

            // 2. uninstall: the library as it was (the user's folders and model too)
            pi.Uninstall("p_vic");
            Check(!Has("m_boy") && !Has("m_coach") && !Has("m_hedge"), "uninstall: models gone");
            Check(Snapshot() == before, "uninstall: library exactly as before");
            Check(Folders().Contains("Simpler/Characters") && Folders().Contains("Vegetazione/Simpler") && Folders().Contains("Altro"), "uninstall: the user's folders stay");
            Check(!Folders().Contains("Packages") && !Folders().Contains("Vegetazione/Packages") && !Folders().Contains("Packages/Pack p_vic/Vehicles"), "uninstall: the pack's folders go");
            Check(pi.Installed().Count == 0, "uninstall: not in the list");
            Check(!Directory.Exists(Path.Combine(Lib, "packs", "p_vic")), "uninstall: its cover and licence go");
            Check(File.Exists(Path.Combine(Lib, "m_boy", "textures", "a.png")) && !File.Exists(Path.Combine(Lib, "m_boy", "model.blend")),
                  "uninstall: textures stay for the scenes that use the model (as Simpler's own delete)");

            // 3. install again after uninstall
            pi.Install(v1);
            Check(Has("m_boy") && Has("m_coach") && Has("m_hedge") && pi.Installed().Count == 1, "reinstall after uninstall");

            // 4. install again over itself (same version): nothing doubled, nothing lost
            var snap = Snapshot();
            var nf = Folders().Count;
            pi.Install(v1);
            Check(Snapshot() == snap && Folders().Count == nf && pi.Installed().Count == 1, "install over itself: same library");
            pi.Uninstall("p_vic");
            Check(Snapshot() == before, "uninstall after installing twice: library as before");

            // 5. update: a model changed, one removed, one added, one moved to another folder
            pi.Install(v1);
            var v2 = MakePack(Tmp, "p_vic", "1.1", new[]
            {
                new M("m_boy", "Boy", "models", "Characters/Victorian era", "blend-new"),
                new M("m_horse", "Horse", "models", "Animals/Horses"),
                new M("m_hedge", "Hedge", "plants", "Gardens/Formal"),
            });
            pi.Install(v2);
            Check(Blend("m_boy").StartsWith("blend-new"), "update: changed model replaced");
            Check(!Has("m_coach"), "update: model no longer in the pack removed");
            Check(Has("m_horse"), "update: new model added");
            Check((string?)Entry("m_hedge")!["folder"] == "Vegetazione/Packages/Pack p_vic/Gardens/Formal", "update: moved model in its new folder");
            Check(!Folders().Contains("Packages/Pack p_vic/Vehicles/Carriages") && !Folders().Contains("Packages/Pack p_vic/Vehicles"), "update: emptied pack folders removed");
            Check(!Folders().Contains("Vegetazione/Packages/Pack p_vic/Gardens/Victorian") && Folders().Contains("Vegetazione/Packages/Pack p_vic/Gardens/Formal"), "update: moved folder");
            Check((string?)pi.Installed()[0]["version"] == "1.1" && pi.Installed().Count == 1, "update: one pack, new version");

            // 6. downgrade (asked in the window): the older version back
            pi.Install(v1);
            Check(Has("m_coach") && !Has("m_horse") && Blend("m_boy").StartsWith("blend ") && (string?)pi.Installed()[0]["version"] == "1.0", "downgrade");
            pi.Uninstall("p_vic");
            Check(Snapshot() == before, "uninstall after update and downgrade: library as before");

            // 7. two packs sharing a model and a folder
            var farm = MakePack(Tmp, "p_farm", "1.0", new[]
            {
                new M("m_horse", "Horse", "models", "Animals/Horses"),
                new M("m_cow", "Cow", "models", "Animals/Farm"),
            });
            var vic3 = MakePack(Tmp, "p_vic", "1.2", new[]
            {
                new M("m_boy", "Boy", "models", "Characters/Victorian era"),
                new M("m_horse", "Horse", "models", "Animals/Horses"),
            });
            pi.Install(vic3);
            pi.Install(farm);
            Check(pi.Installed().Count == 2, "two packs listed");
            pi.Uninstall("p_vic");
            Check(Has("m_horse") && Has("m_cow") && !Has("m_boy"), "shared model stays with the other pack");
            Check((string?)Entry("m_horse")!["folder"] == "Packages/Pack p_farm/Animals/Horses" && Folders().Contains("Packages/Pack p_farm/Animals/Horses") && !Folders().Contains("Packages/Pack p_vic"), "the shared model in the folder of the pack that keeps it");
            Check((string?)Entry("m_horse")!["pack"] == "p_farm", "shared model now belongs to the other pack");
            pi.Uninstall("p_farm");
            Check(!Has("m_horse") && !Has("m_cow") && !Folders().Contains("Packages"), "last pack gone: shared model and folder gone");
            Check(Snapshot() == before, "two packs, both uninstalled: library as before");
            // the other order
            pi.Install(farm); pi.Install(vic3); pi.Uninstall("p_farm");
            Check(Has("m_horse") && Has("m_boy") && !Has("m_cow"), "shared model stays (other order)");
            pi.Uninstall("p_vic");
            Check(Snapshot() == before, "other order: library as before");

            // 8. a user's own model put in a folder of a pack: it stays, with its folder
            pi.Install(v1);
            File.WriteAllText(Path.Combine(Lib, "m_mine2.json"), new JsonObject { ["id"] = "m_mine2", ["name"] = "Mine 2", ["folder"] = "Packages/Pack p_vic/Vehicles/Carriages" }.ToJsonString());
            Directory.CreateDirectory(Path.Combine(Lib, "m_mine2"));
            pi.Uninstall("p_vic");
            Check(Entry("m_mine2") != null && Folders().Contains("Packages/Pack p_vic/Vehicles/Carriages") && Folders().Contains("Packages/Pack p_vic/Vehicles"), "user's model in a pack folder: model and folder stay");
            File.Delete(Path.Combine(Lib, "m_mine2.json")); Directory.Delete(Path.Combine(Lib, "m_mine2"));

            // 8b. installing on the library where the pack was made (the models are there already, in the same folders):
            // uninstalling must not take the author's models away
            Fresh();
            pi = new PackInstaller(Lib, "Vegetazione", keys);
            Directory.CreateDirectory(Path.Combine(Lib, "m_boy"));
            File.WriteAllText(Path.Combine(Lib, "m_boy", "model.blend"), "blend m_boy 1.0");
            File.WriteAllText(Path.Combine(Lib, "m_boy.json"), new JsonObject { ["id"] = "m_boy", ["name"] = "Boy", ["folder"] = "Simpler/Characters/Victorian era" }.ToJsonString());
            pi.Install(v1);
            Check(Has("m_boy") && Has("m_coach"), "author's library: installed over");
            pi.Install(v1);
            pi.Uninstall("p_vic");
            Check(Has("m_boy") && Entry("m_boy")!["pack"] == null, "author's library: his own model stays after uninstall");
            Check(!Has("m_coach") && !Has("m_hedge"), "author's library: the models that were not there go");
            Check(Folders().Contains((string?)Entry("m_boy")!["folder"] ?? "?"), "author's library: the folder of his model stays");
            // (Luca: his models went into «Packages» and left his Simpler folders) back in the folder they had
            Check((string?)Entry("m_boy")!["folder"] == "Simpler/Characters/Victorian era", "author's library: his model back in its folder after uninstall");
            pi.Install(v1);
            pi.Install(MakePack(Tmp, "p_vic", "1.1", new[] { new M("m_coach", "Coach", "models", "Vehicles/Carriages") }));
            pi.Uninstall("p_vic");
            // a pack installed before the folder was remembered: the folder from the pack's manifest
            pi.Install(v1);
            var regf = Path.Combine(Lib, "packs", "installed.json");
            var regj = JsonNode.Parse(File.ReadAllText(regf))!;
            regj["packs"]!["p_vic"]!.AsObject().Remove("keptFrom");
            File.WriteAllText(regf, regj.ToJsonString());
            pi.Uninstall("p_vic");
            Check((string?)Entry("m_boy")!["folder"] == "Simpler/Characters/Victorian era", "author's library: back in its folder (older install)");
            // (Luca moved the pack's models by hand inside «Packages», then updated) never left in «Packages» without its pack
            pi.Install(v1);
            var bf = Path.Combine(Lib, "m_boy.json");
            var bj = JsonNode.Parse(File.ReadAllText(bf))!; bj["folder"] = "Packages/Pack p_vic/Characters"; File.WriteAllText(bf, bj.ToJsonString());
            regj = JsonNode.Parse(File.ReadAllText(regf))!;
            // (a pack installed, uninstalled, its folders made again by hand: then installed - they are not «made» by it)
            var flj = JsonNode.Parse(File.ReadAllText(Path.Combine(Lib, "folders.json")))!;
            flj["folders"]!.AsArray().Add("Packages/Pack p_vic/Old");
            File.WriteAllText(Path.Combine(Lib, "folders.json"), flj.ToJsonString());
            regj = JsonNode.Parse(File.ReadAllText(regf))!;
            regj["packs"]!["p_vic"]!["madeFolders"] = new JsonArray();
            regj["packs"]!["p_vic"]!["folders"]!.AsArray().Add("Packages/Pack p_vic/Old");
            regj["packs"]!["p_vic"]!["keptFrom"] = new JsonObject { ["m_boy"] = "Packages/Pack p_vic/Characters" };
            File.WriteAllText(regf, regj.ToJsonString());
            pi.Install(v1);
            pi.Uninstall("p_vic");
            Check(((string?)Entry("m_boy")!["folder"] ?? "").StartsWith("Simpler/Characters"), "author's library: moved by hand inside Packages, back in Simpler: " + (string?)Entry("m_boy")!["folder"]);
            Check(!Folders().Any(f => f.StartsWith("Packages/Pack p_vic")), "author's library: no empty pack folder left after uninstall: " + string.Join(", ", Folders().Where(f => f.StartsWith("Packages"))));
            pi.Install(v1);
            pi.Install(MakePack(Tmp, "p_vic", "1.1", new[] { new M("m_coach", "Coach", "models", "Vehicles/Carriages") }));
            Check(Has("m_boy"), "author's library: an update without his model keeps it");
            Check((string?)Entry("m_boy")!["folder"] == "Simpler/Characters/Victorian era", "author's library: an update without his model gives it back to its folder");
            pi.Uninstall("p_vic");

            // 9. refused: changed after signing, signed by another key, unsafe path, not a pack. Library untouched.
            Fresh();
            pi = new PackInstaller(Lib, "Vegetazione", keys);
            before = Snapshot();
            var tampered = MakePack(Tmp, "p_bad", "1.0", victorian, tamperAfterSign: f => f["models/m_boy/model.blend"] = Encoding.UTF8.GetBytes("evil"));
            Check(pi.Inspect(tampered).Ok, "tampered pack: manifest still signed (found while installing)");
            Check(Throws(() => pi.Install(tampered)), "tampered file refused");
            Check(Snapshot() == before && pi.Installed().Count == 0, "tampered: library untouched");
            Check(!Directory.EnumerateDirectories(Path.Combine(Lib, "packs")).Any(), "tampered: no staging left");
            var other = MakePack(Tmp, "p_other", "1.0", victorian, key: ECDsa.Create(ECCurve.NamedCurves.nistP256));
            Check(pi.Inspect(other).Error == "signature" && Throws(() => pi.Install(other)), "other key refused");
            var extra = MakePack(Tmp, "p_extra", "1.0", victorian, tamperAfterSign: f => f["models/m_boy/textures/evil.exe"] = new byte[] { 1 });
            Check(Throws(() => pi.Install(extra)), "unsigned extra file refused");
            var unsafePath = MakePack(Tmp, "p_path", "1.0", victorian, extraEntry: "models/../../evil.txt");
            Check(!pi.Inspect(unsafePath).Ok && Throws(() => pi.Install(unsafePath)), "unsafe path refused");
            var junk = Path.Combine(Tmp, "junk.simplerpack");
            File.WriteAllText(junk, "not a zip");
            Check(!pi.Inspect(junk).Ok, "not a pack");
            Check(Snapshot() == before && pi.Installed().Count == 0, "refused packs: library untouched");
            Check(!File.Exists(Path.Combine(Tmp, "..", "evil.txt")), "nothing written outside");

            // 10. a library in English: the vegetation root is «Vegetation»
            Fresh("Vegetation");
            pi = new PackInstaller(Lib, "Vegetation", keys);
            pi.Install(v1);
            Check((string?)Entry("m_hedge")!["folder"] == "Vegetation/Packages/Pack p_vic/Gardens/Victorian" && Folders().Contains("Vegetation/Packages/Pack p_vic/Gardens"), "vegetation root of the user's language");
            pi.Uninstall("p_vic");
            Check(!Folders().Contains("Vegetation/Simpler/Gardens") && Folders().Contains("Vegetation/Simpler"), "English library: back as before");

            // 11. no trusted key at all: nothing installs
            Check(!new PackInstaller(Lib, "Vegetation", Array.Empty<string>()).Inspect(v1).Ok, "no key: refused");

            // 12. the official keys are real P-256 public keys; a test pack is not official
            Check(PackInstaller.OfficialKeys.Length > 0 && PackInstaller.OfficialKeys.All(k =>
            {
                try { using var ec = ECDsa.Create(); ec.ImportSubjectPublicKeyInfo(Convert.FromBase64String(k), out _); return ec.KeySize == 256; }
                catch { return false; }
            }), "official keys valid");
            Check(new PackInstaller(Lib, "Vegetation", PackInstaller.OfficialKeys).Inspect(v1).Error == "signature", "a pack signed by another key is not official");
        }
        catch (Exception ex) { Bad.Add("exception: " + ex); Console.WriteLine(ex); }
        finally { try { Directory.Delete(Tmp, true); } catch { } }
        Console.WriteLine(Bad.Count == 0 ? $"PACKS_OK ({_checks} checks)" : $"PACKS_FAIL {Bad.Count} of {_checks}: " + string.Join("; ", Bad));
        return Bad.Count == 0 ? 0 : 1;
    }
}
