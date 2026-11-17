using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace Simpler
{
    /// <summary>
    /// (1.78.0) «Vegetazione»: the plants of the library. They are models of the model library marked as vegetation
    /// (engine matbulk.vegetation: every material of the type Fogliame, leaves or wood) and kept in the folder
    /// «Vegetazione» (Alberi, Arbusti e siepi, Erbe e prati, Fiori e coprenti). The menu «Vegetazione ▾ · Personalizzate»
    /// shows that folder; Modelli 3D ▸ Personalizzati leaves it out. «Importa vegetazione nella libreria…» (the import
    /// wizard in its Vegetazione mode), «Converti in vegetazione…» on a model, «Foglie e legno…» on a plant.
    /// </summary>
    public sealed partial class MainWindow
    {
        sealed class PartsDialog : ThemedDialog
        {
            public PartsDialog(string title) : base(title, 560) { }
            public StackPanel Content2 => Body;
        }

        internal string _vegRoot = "Vegetazione";
        // (1.78.3) the plants and models «di Simpler» (the ones that will go into the installation): for now the folders
        // «Simpler» of the library (Vegetazione/Simpler, Simpler), shown as their own entries and still editable while
        // Luca fills them; later read only (red)
        internal const string SimplerModels = "Simpler";
        internal string SimplerPlants => _vegRoot + "/Simpler";
        // (Luca: «una voce package a cartelle blu») the models and plants of the packs: Modelli 3D ▸ Packages and
        // Vegetazione ▸ Packages, blue folders, read only as the Simpler parts (an update or an uninstall of a pack
        // finds its models where it put them; «Copia nei miei» gives the user a copy of their own)
        internal const string PacksModelFolder = PackInstaller.PacksFolder;
        internal string PacksPlantFolder => _vegRoot + "/" + PackInstaller.PacksFolder;
        internal string _vegPackFolder = "", _objPackFolder = "";
        internal bool IsPackFolder(string f) => Under(f, PacksModelFolder) || Under(f, PacksPlantFolder);
        string ModelFolderNow => _libraryTab switch { "myplants" => _vegFolder, "simplerplants" => _vegSimFolder, "primitives" => _objSimFolder, "packplants" => _vegPackFolder, "packmodels" => _objPackFolder, _ => _objFolder };
        internal string _vegFolder = "", _vegSimFolder = "", _objSimFolder = "";

        static bool IsVegModel(JsonObject m) => m["veg"] is JsonObject;
        internal bool IsVegFolder(string f) => f == _vegRoot || (f ?? "").StartsWith(_vegRoot + "/", StringComparison.Ordinal);
        static bool Under(string f, string root) => f == root || (f ?? "").StartsWith(root + "/", StringComparison.Ordinal);
        internal bool IsSimplerFolder(string f) => Under(f, SimplerModels) || Under(f, SimplerPlants);
        /// <summary>(1.78.4) settings.json «SimplerLocked» = 1: the Simpler parts are red and read only (the engine refuses
        /// every change there too: models/lock).</summary>
        internal bool SimplerLocked => _settings.SimplerLocked == 1 && !InStudio;
        /// <summary>(1.78.4, Luca: «l'utente può fare azioni nelle cartelle rosse di Simpler che non deve fare») a folder
        /// of the locked Simpler parts, a model in one: only looked at, inserted, scattered and copied (into one's own
        /// folders) - never renamed, moved, deleted or changed, and nothing is moved or pasted into them.
        /// (Luca: «c'è ancora delete folder») the folders of the packs are read only always, whatever «SimplerLocked»:
        /// install, update and uninstall must find the models where they put them.</summary>
        internal bool ReadOnlyFolder(string? f) => (SimplerLocked && IsSimplerFolder(f ?? "")) || IsPackFolder(f ?? "");
        internal bool ReadOnlyModel(string id) =>
            _models.OfType<JsonObject>().Any(x => (string?)x["id"] == id && ReadOnlyFolder((string?)x["folder"]));

        /// <summary>(1.78.4, Luca: «dopo avere salvato una vegetazione in una cartella la libreria si sposta qui») the tab
        /// and folder of the library where a model of this folder is shown: Vegetazione (Simpler or I miei), Modelli 3D
        /// ▸ Simpler, or Modelli 3D ▸ I miei.</summary>
        internal string ModelTabFor(string fo, bool open)
        {
            string tab;
            if (Under(fo, PacksPlantFolder)) { tab = "packplants"; if (open) _vegPackFolder = fo; }
            else if (Under(fo, PacksModelFolder)) { tab = "packmodels"; if (open) _objPackFolder = fo; }
            else if (Under(fo, SimplerPlants)) { tab = "simplerplants"; if (open) _vegSimFolder = fo; }
            else if (Under(fo, SimplerModels)) { tab = "primitives"; if (open) _objSimFolder = fo; }
            else if (IsVegFolder(fo)) { tab = "myplants"; if (open) _vegFolder = fo; }
            else { tab = "objects"; if (open) _objFolder = fo; }
            return tab;
        }

        /// <summary>The folder the library shows now for models (the starting folder of «Salva nella libreria»).</summary>
        string ModelFolderShown() => _libraryTab switch
        {
            "myplants" => _vegFolder == "" ? _vegRoot : _vegFolder,
            "simplerplants" => _vegSimFolder == "" ? SimplerPlants : _vegSimFolder,
            "primitives" => _objSimFolder == "" ? SimplerModels : _objSimFolder,
            "packplants" => _vegPackFolder == "" ? PacksPlantFolder : _vegPackFolder,
            "packmodels" => _objPackFolder == "" ? PacksModelFolder : _objPackFolder,
            _ => _objFolder == PrimitiveFolder ? "" : _objFolder,
        };

        /// <summary>A part of the model library shown from one of its folders: the path bar from there, its subfolders
        /// (some left out), its models. extra: tiles at the top level (import, the primitives).</summary>
        void RenderRootedModels(string root, string rootLabel, Func<string> get, Action<string> set, List<JsonObject> models,
                                Func<string, bool> hidden, Action? extra, string emptyNote, string? extraAt = null, int extraCount = 0)
        {
            extraAt ??= root;
            _modelTiles.Clear();
            var place = root + "|" + get() + "|" + LibraryQuery;
            if (place != _modelSelPlace) { _modelSel.Clear(); _modelSelPlace = place; }
            var cur = get();
            if (cur == "" || !Under(cur, root) || hidden(cur) || (cur != root && !_modelFolders.Contains(cur))) { cur = root; set(root); }
            string Rel(string full) => full == root ? "" : full.Substring(root.Length + 1);
            string Full(string rel) => rel == "" ? root : root + "/" + rel;
            var q = LibraryQuery;
            if (q != "")
            {
                RenderCrumbs(rootLabel, "", f => { set(Full(f)); _librarySearch.Text = ""; }, L.F("risultati per \"{0}\"", _librarySearch.Text.Trim()), root);
                int n = 0;
                foreach (var m in models.Where(m => ((string?)m["name"] + " " + (string?)m["folder"]).ToLowerInvariant().Contains(q)))
                {
                    _libraryTiles.Children.Add(ModelTile(m));
                    n++;
                }
                if (n == 0) _libraryTiles.Children.Add(EmptyNote(L.T("Nessun modello trovato")));
                return;
            }
            RenderCrumbs(rootLabel, Rel(cur), f => set(Full(f)), null, root);
            var ro = ReadOnlyFolder(root);   // (red / blue, read only: nothing is added or changed)
            if (cur != root) _libraryTiles.Children.Add(UpTile(ParentFolder(cur), f => set(f), true));
            // (1.78.4, Luca: «metti import vegetation all'inizio») the tiles that add (import, the basic shapes) come
            // first, before the folders: always in the same place however many folders there are
            if (cur == extraAt) extra?.Invoke();
            // (1.79, Luca: «perché new folder è in fondo a destra?») «Nuova cartella» first, with the tiles that add
            if (!ro) _libraryTiles.Children.Add(NewFolderTile("model", cur));
            else if (cur == root && UpdateAllTile() is FrameworkElement upAll) _libraryTiles.Children.Add(upAll);      // (a newer version in the cloud)
            foreach (var f in _modelFolders.Where(f => ParentFolder(f) == cur && !hidden(f)).OrderBy(f => f, StringComparer.CurrentCultureIgnoreCase))
            {
                var count = models.Count(m => InFolder((string?)m["folder"] ?? "", f)) + (InFolder(extraAt, f) ? extraCount : 0);
                var ff = f;
                // (cloud) the red folders: how many of their models are already on this computer (e.g. 3/19)
                var cloudCount = ro && ContentOn;
                var here = cloudCount ? models.Count(m => InFolder((string?)m["folder"] ?? "", f) && !((bool?)m["cloud"] ?? false)) + (InFolder(extraAt, f) ? extraCount : 0) : 0;   // (the basic shapes are always here)
                if (here > count) { AppLog.Write($"folder counter: {here}/{count} in «{f}» (models {models.Count}): limited"); here = count; }   // (it cannot be: the log says if it happens)
                var upN = cloudCount ? models.Count(m => InFolder((string?)m["folder"] ?? "", f) && ((bool?)m["update"] ?? false)) : 0;
                _libraryTiles.Children.Add(FolderTile(f, count, () => { set(ff); RenderLibrary(); }, ro ? "simplermodel" : "model", here, cloudCount, upN));
            }
            foreach (var m in models.Where(m => ((string?)m["folder"] ?? "") == cur))
                _libraryTiles.Children.Add(ModelTile(m));
            if (!models.Any() && emptyNote != "") _libraryTiles.Children.Add(EmptyNote(emptyNote));
        }

        /// <summary>«Vegetazione ▸ I miei» (the folder Vegetazione without its «Simpler») or «Vegetazione ▸ Simpler».</summary>
        void RenderVegBrowser(bool simpler)
        {
            EnsureFolder(simpler ? SimplerPlants : _vegRoot);
            if (simpler)
                RenderRootedModels(SimplerPlants, L.T("Vegetazione Simpler"), () => _vegSimFolder, f => _vegSimFolder = f,
                                   _models.OfType<JsonObject>().Where(m => Under((string?)m["folder"] ?? "", SimplerPlants)).ToList(),
                                   _ => false, () => { if (!SimplerLocked) _libraryTiles.Children.Add(ImportPlantsTile()); },
                                   L.T("Le piante che arriveranno con Simpler: importale qui («Importa vegetazione…»), o spostale qui dai tuoi"));
            else
                RenderRootedModels(_vegRoot, L.T("Le mie piante"), () => _vegFolder, f => _vegFolder = f,
                                   _models.OfType<JsonObject>().Where(m => (IsVegModel(m) || IsVegFolder((string?)m["folder"] ?? "")) && !Under((string?)m["folder"] ?? "", SimplerPlants) && !Under((string?)m["folder"] ?? "", PacksPlantFolder)).ToList(),
                                   f => Under(f, SimplerPlants) || Under(f, PacksPlantFolder), () => _libraryTiles.Children.Add(ImportPlantsTile()),
                                   L.T("Nessuna pianta ancora: «Importa vegetazione…» qui accanto, oppure tasto destro su un modello di Modelli 3D ▸ I miei, «Converti in vegetazione…»"));
        }

        /// <summary>«Modelli 3D ▸ Simpler»: the basic shapes and the models of the folder «Simpler».</summary>
        /// <summary>(1.78.4, Luca: «non riesco a spostarli nella cartella Primitives») the basic shapes are not files of
        /// the library: they stand in the folder «Simpler/Primitives» (made when missing), not loose at the top.</summary>
        internal string SimplerPrimitives => SimplerModels + "/Primitives";

        void RenderSimplerModels()
        {
            EnsureFolder(SimplerModels);
            EnsureFolder(SimplerPrimitives);
            RenderRootedModels(SimplerModels, L.T("Modelli 3D Simpler"), () => _objSimFolder, f => _objSimFolder = f,
                               _models.OfType<JsonObject>().Where(m => Under((string?)m["folder"] ?? "", SimplerModels) && !IsVegModel(m)).ToList(),
                               _ => false, () => { foreach (var (kind, label) in InsertObjects) AddPrimitiveTile(kind, label); }, "",
                               _modelFolders.Contains(SimplerPrimitives) ? SimplerPrimitives : SimplerModels, InsertObjects.Length);
        }

        /// <summary>Modelli 3D ▸ Packages / Vegetazione ▸ Packages: one blue folder per installed pack.</summary>
        void RenderPackModels(bool plants)
        {
            var root = plants ? PacksPlantFolder : PacksModelFolder;
            RenderRootedModels(root, L.T("Pacchetti"), plants ? () => _vegPackFolder : () => _objPackFolder,
                               plants ? f => _vegPackFolder = f : f => _objPackFolder = f,
                               _models.OfType<JsonObject>().Where(m => Under((string?)m["folder"] ?? "", root) && (plants || !IsVegModel(m))).ToList(),
                               _ => false, null, L.T("Nessun pacchetto installato: «Pacchetti…» nel menu di import. Ogni pacchetto installato ha qui la sua cartella blu"));
        }

        readonly HashSet<string> _ensured = new();
        /// <summary>The folder exists in the library (once per session): the Simpler entries always have their folder.</summary>
        void EnsureFolder(string path)
        {
            if (_api == null || _modelFolders.Contains(path) || !_ensured.Add(path)) return;
            _ = Task.Run(async () =>
            {
                try { await _api.Post("models/folder", new JsonObject { ["action"] = "create", ["path"] = path }); } catch { return; }
                await Dispatcher.InvokeAsync(async () => await ReloadModels());
            });
        }

        Button ImportPlantsTile()
        {
            var btn = BigTile(TileIcon(Icons.Leaf, Theme.C("#7CC46A")), L.T("Importa vegetazione…"), "",
                              L.T("Importa piante da file (FBX, glTF, OBJ, USD): le foglie e il legno ricevono il materiale Fogliame, con la stagione"));
            btn.Click += (_, __) => ShowImportWizard(true);
            return btn;
        }

        /// <summary>The models become plants (engine models/vegetation, a separate Blender): waits for the end. parts:
        /// {id: {material: foglie|legno|altro}} chosen by hand; types: {id: kind}. Returns how many materials went to
        /// leaves and to wood and the folder of the first one, or null when it did not work.</summary>
        internal async Task<(int leaves, int wood, string folder)?> MakeVegetation(List<string> ids, JsonObject? parts, JsonObject? types, bool reload = true)
        {
            if (ids.Count == 0) return null;
            JsonObject? st = null;
            try
            {
                await _api.Post("models/vegetation", new JsonObject
                {
                    ["ids"] = new JsonArray(ids.Select(x => (JsonNode?)JsonValue.Create(x)).ToArray()),
                    ["parts"] = parts ?? new JsonObject(), ["types"] = types ?? new JsonObject(),
                });
                st = await WaitBulk(L.T("Foglie e legno"));
            }
            catch (Exception ex) { Status(ex.Message, true); return null; }
            if (st == null || (string?)st["state"] != "done") { Status(L.T("Vegetazione: non riuscito") + " " + ((string?)st?["error"] ?? ""), true); return null; }
            int lv = 0, wd = 0;
            foreach (var it in (st["result"]?["models"] as JsonArray)?.OfType<JsonObject>() ?? Enumerable.Empty<JsonObject>())
                foreach (var mm in (it["materials"] as JsonArray)?.OfType<JsonObject>() ?? Enumerable.Empty<JsonObject>())
                {
                    if ((string?)mm["part"] == "foglie") lv++;
                    else if ((string?)mm["part"] == "legno") wd++;
                }
            await ReloadModels();
            var first = _models.OfType<JsonObject>().FirstOrDefault(m => (string?)m["id"] == ids[0]);
            if (reload) RenderLibrary();
            return (lv, wd, (string?)first?["folder"] ?? "");
        }

        /// <summary>Waits for the job of models/vegetation (the same runner as «Correggi materiali»), with the busy note.</summary>
        async Task<JsonObject?> WaitBulk(string what)
        {
            var t0 = DateTime.Now;
            while (true)
            {
                await Task.Delay(400);
                JsonObject? st = null;
                try { st = await _api.Get("matbulk/status"); } catch { }
                var state = (string?)st?["state"] ?? "";
                if (state == "running")
                {
                    int done = (int?)st?["done"] ?? 0, total = (int?)st?["total"] ?? 0;
                    ShowTask(L.F("{0}: {1} di {2}", what, Math.Min(done + 1, Math.Max(1, total)), Math.Max(1, total)));
                    if ((DateTime.Now - t0).TotalMinutes < 30) continue;
                }
                HideTask();
                return st;
            }
        }

        /// <summary>«Converti in vegetazione…»: one model or the selection; the kind proposed from the height.</summary>
        async Task ConvertToVegetation(List<string> ids)
        {
            var r = await MakeVegetation(ids, null, null);
            if (r == null) return;
            Status(L.F("Vegetazione: {0} piante · foglie {1} materiali, legno {2} (tasto destro sulla pianta: «Foglie e legno…» per correggere)", ids.Count, r.Value.leaves, r.Value.wood));
            if (Under(r.Value.folder, SimplerPlants)) { _vegSimFolder = r.Value.folder; _libraryTab = "simplerplants"; }
            else { _vegFolder = IsVegFolder(r.Value.folder) ? r.Value.folder : _vegRoot; _libraryTab = "myplants"; }
            RenderLibrary();
        }

        /// <summary>(1.78.1, Luca: «convert to vegetation serve anche nella viewport») «Converti in vegetazione» on objects
        /// of the scene: Fogliame on their materials, leaves or wood, at once (engine scene/vegetation; one Ctrl+Z).</summary>
        async Task SceneToVegetation(List<string> ids)
        {
            if (ids.Count == 0) return;
            JsonObject? r = null;
            ShowTask(L.T("Converti in vegetazione"));
            try
            {
                await Run(async api =>
                {
                    r = await api.Post("scene/vegetation", new JsonObject { ["ids"] = new JsonArray(ids.Select(x => (JsonNode?)JsonValue.Create(x)).ToArray()) });
                    UpdateHistory(await api.Get("history"));
                });
            }
            finally { HideTask(); }
            if (r == null) return;
            int lv = 0, wd = 0;
            foreach (var mm in (r["materials"] as JsonArray)?.OfType<JsonObject>() ?? Enumerable.Empty<JsonObject>())
            {
                var part = (string?)mm["part"];
                if (part == "foglie") lv++; else if (part == "legno") wd++;
                var n = (string?)mm["name"] ?? "";
                if (n != "") await PushMaterialToViewer(n);
            }
            if (_matName != "" && _rightPanel == "material") { await LoadMaterial(); RenderProps(); }
            Status(L.F("Convertito in vegetazione: foglie {0} materiali, legno {1} · Ctrl+Z per tornare indietro · nell'editor del materiale puoi cambiare Foglie o Legno", lv, wd));
        }

        /// <summary>«Foglie e legno…»: what Simpler took for leaves and for wood in this plant, to change with a click.</summary>
        async Task ShowVegParts(string id, string name)
        {
            JsonObject? st = null;
            try
            {
                await _api.Post("models/vegetation", new JsonObject { ["ids"] = new JsonArray(JsonValue.Create(id)), ["dry"] = true });
                st = await WaitBulk(L.T("Foglie e legno"));
            }
            catch (Exception ex) { Status(ex.Message, true); return; }
            var mats = (st?["result"]?["models"] as JsonArray)?.OfType<JsonObject>().FirstOrDefault()?["materials"] as JsonArray;
            if (mats == null || mats.Count == 0) { Status(L.T("Nessun materiale trovato in questa pianta"), true); return; }
            var dlg = new PartsDialog(L.F("Foglie e legno: {0}", name)) { Owner = this };
            var sp = new StackPanel { Margin = new Thickness(20, 4, 20, 16) };
            var intro = Theme.Label(L.T("Per ogni materiale della pianta: Foglie (stagione, luce attraverso, retro più chiaro), Legno (tronco e rami: la stagione non lo tocca) o Altro (resta com'è: vasi, sassi, etichette)."), 12, Theme.TextMuted);
            intro.TextWrapping = TextWrapping.Wrap;
            intro.Margin = new Thickness(0, 0, 0, 12);
            sp.Children.Add(intro);
            var choice = new Dictionary<string, string>();
            string[] ids3 = { "foglie", "legno", "altro" };
            foreach (var mm in mats.OfType<JsonObject>())
            {
                var mn = (string?)mm["name"] ?? "";
                choice[mn] = (string?)mm["part"] ?? "legno";
                var row = new DockPanel { Margin = new Thickness(0, 0, 0, 6) };
                var seg = Theme.Segmented(out var bs, (L.T("Foglie"), L.T("Foglie, aghi, petali, fili d'erba")), (L.T("Legno"), L.T("Tronco, rami, corteccia")),
                                          (L.T("Altro"), L.T("Non è una parte della pianta: resta com'è")));
                Theme.SetSegment(bs, Math.Max(0, Array.IndexOf(ids3, choice[mn])));
                for (int i = 0; i < bs.Count; i++)
                {
                    var k = i;
                    bs[i].Click += (_, __) => { choice[mn] = ids3[k]; Theme.SetSegment(bs, k); };
                }
                DockPanel.SetDock(seg, Dock.Right);
                row.Children.Add(seg);
                var why = (string?)mm["why"] ?? "";
                var lab = Theme.Label(mn, 12.5, Theme.TextSoft);
                lab.VerticalAlignment = VerticalAlignment.Center;
                lab.TextTrimming = TextTrimming.CharacterEllipsis;
                lab.ToolTip = mn + "\n" + (why switch
                {
                    "name" => L.T("Riconosciuto dal nome"),
                    "cutout" => L.T("Riconosciuto dal ritaglio della texture (una foglia su un piano)"),
                    "colour" => L.T("Riconosciuto dal colore verde"),
                    "user" => L.T("Scelto da te"),
                    "set" => L.T("Già impostato (da Simpler o da te)"),
                    _ => L.T("Nessun indizio: legno, che la stagione non tocca"),
                });
                row.Children.Add(lab);
                sp.Children.Add(row);
            }
            var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 12, 0, 0) };
            var cancel = Theme.Button(L.T("Annulla"), Theme.Kind.Ghost);
            cancel.Click += (_, __) => dlg.Close();
            var ok = Theme.Button(L.T("Applica"), Theme.Kind.Primary);
            ok.Margin = new Thickness(8, 0, 0, 0);
            bool apply = false;
            ok.Click += (_, __) => { apply = true; dlg.Close(); };
            buttons.Children.Add(cancel);
            buttons.Children.Add(ok);
            sp.Children.Add(buttons);
            dlg.Content2.Children.Add(sp);
            dlg.ShowDialog();
            if (!apply) return;
            var own = new JsonObject();
            foreach (var (k, v) in choice) own[k] = v;
            var r = await MakeVegetation(new List<string> { id }, new JsonObject { [id] = own }, null);
            if (r != null) Status(L.F("{0}: foglie {1} materiali, legno {2}", name, r.Value.leaves, r.Value.wood));
        }
    }
}
