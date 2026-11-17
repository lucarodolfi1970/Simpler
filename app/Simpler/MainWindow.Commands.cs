using System.Linq;
using System.Collections.Generic;
using System;
using System.Text.Json.Nodes;
using System.Diagnostics;
using System.IO;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Input;

namespace Simpler
{
    /// <summary>Project files, import, quality, caustics and final render.</summary>
    public sealed partial class MainWindow
    {
        Settings _settings = Settings.Load();

        string StartFolder() => Directory.Exists(_settings.LastFolder) ? _settings.LastFolder : Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);

        /// <summary>Where a file dialog opens: the folder last used for that kind of file (projects, models, images,
        /// renders, texture folders), else the last folder used at all, else Documents.</summary>
        internal string StartFolder(string kind)
            => _settings.LastFolders.TryGetValue(kind, out var f) && Directory.Exists(f) ? f : StartFolder();

        /// <summary>A file (or folder) chosen in a dialog: its folder is where the next dialog of that kind opens.</summary>
        internal void Keep(string kind, string path, bool isFolder = false)
        {
            if (string.IsNullOrEmpty(path)) return;
            var dir = isFolder ? path : Path.GetDirectoryName(path) ?? "";
            if (dir == "") return;
            // saved on a fresh copy of the settings: the one kept here since the start is old - saving it put back
            // what other panels had changed meanwhile (the gizmo's Base/Centre/Origin came back to the old choice
            // at every open or save of a project, the way a material is applied, the speed of the wheel...)
            var s = Settings.Load();
            s.LastFolders[kind] = dir;
            s.LastFolder = dir;
            s.Save();
            _settings.LastFolders[kind] = dir;
            _settings.LastFolder = dir;
        }

        void Remember(string file, string kind = "project") => Keep(kind, file);

        /// <summary>A project opened or saved goes first in the recent list of the file menu (at most 5).</summary>
        void AddRecent(string file)
        {
            try
            {
                var full = Path.GetFullPath(file);
                if (full.EndsWith(".autosave.simpler", StringComparison.OrdinalIgnoreCase)) return;
                var s = Settings.Load();              // (fresh: other panels save settings too)
                s.RecentProjects.RemoveAll(p => string.Equals(p, full, StringComparison.OrdinalIgnoreCase));
                s.RecentProjects.Insert(0, full);
                if (s.RecentProjects.Count > 5) s.RecentProjects.RemoveRange(5, s.RecentProjects.Count - 5);
                s.Save();
                _settings.RecentProjects = new List<string>(s.RecentProjects);
            }
            catch (Exception ex) { AppLog.Write("recent list: " + ex.Message); }
        }

        void SetProjectPath(string? path)
        {
            _projectPath = path;
            _projectLabel.Text = path == null ? L.T("Nuovo progetto") : Path.GetFileNameWithoutExtension(path);
            Title = path == null ? L.T("Simpler ") + SettingsDialog.Version : Path.GetFileNameWithoutExtension(path) + L.T(" – Simpler ") + SettingsDialog.Version;
        }

        // ---------------------------------------------------------------- unsaved changes

        bool _closeConfirmed;

        /// <summary>Unsaved changes? Asks Save / Don't save / Cancel. Returns false when the user cancels (or the save
        /// was cancelled). The engine counts the changes that the project file keeps (navigation does not count).</summary>
        async Task<bool> AskSaveChanges(string question)
        {
            if (InStudio) return true;
            if (!AiRunningAllows()) return false;
            bool dirty = true;
            try { if (_api != null) dirty = (bool?)(await _api.Get("dirty"))["dirty"] ?? true; } catch { dirty = _api != null; }
            dirty |= _aiOutputsDirty;           // (an AI result not saved yet counts as a change of the project)
            if (dirty)
            {
                var name = _projectPath != null ? Path.GetFileNameWithoutExtension(_projectPath) : L.T("Nuovo progetto");
                var answer = Msg.Show(this, L.F(question, name), "Simpler", MessageBoxButton.YesNoCancel, MessageBoxImage.Question);
                if (answer == MessageBoxResult.Cancel || answer == MessageBoxResult.None) return false;
                if (answer == MessageBoxResult.Yes && !await SaveProjectCore(false)) return false;
            }
            // the project is left on purpose (closing Simpler, a new scene, another project): its automatic copy is
            // not needed any more - before, after a new scene the next opening asked to recover a copy left behind
            await DiscardAutosave();
            return true;
        }

        void OnClosingAsk(object? sender, System.ComponentModel.CancelEventArgs e)
        {
            if (_closeConfirmed || _api == null) return;
            e.Cancel = true;                     // asked asynchronously (the engine knows if there are changes)
            // safety nets: never close in the middle of a render, a save, an opening or an import
            if (_finalRendering)
            {
                if (_closeAfterRender) return;
                var q = L.T("È in corso il render finale: chiudendo Simpler l'immagine va persa.\n\nInterrompere il render e chiudere?");
                if (Msg.Show(this, q, "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Warning) != MessageBoxResult.Yes) return;
                _closeAfterRender = true;        // FinalRender closes when the engine has stopped the render
                _ = CancelFinalRender();
                return;
            }
            if (DialogBlocker() != null) { ShowBlocked(); return; }
            if (_saving || _fileOp || IsBusy)
            {
                Msg.Show(this, _saving ? L.T("Simpler sta salvando il progetto: chiudi quando il salvataggio è finito, o il file potrebbe restare incompleto.")
                                       : L.T("Simpler sta ancora lavorando (apertura, importazione o un'altra operazione): chiudi quando ha finito."),
                         "Simpler", MessageBoxButton.OK, MessageBoxImage.Information);
                return;
            }
            if (_matFixWizard?.Running == true)
            {
                Msg.Show(this, L.T("La correzione dei materiali in blocco è ancora in corso: chiudi Simpler quando ha finito, o i modelli resterebbero corretti a metà."),
                         "Simpler", MessageBoxButton.OK, MessageBoxImage.Information);
                return;
            }
            Dispatcher.BeginInvoke(async () =>
            {
                if (_fileOp) return;
                _fileOp = true;
                try { if (!await AskSaveChanges("Ci sono modifiche non salvate in «{0}».\nVuoi salvarle prima di chiudere Simpler?")) return; }
                finally { _fileOp = false; }
                _closeConfirmed = true;
                Close();
            });
        }

        async Task NewProjectCore()
        {
            if (!await AskSaveChanges("Ci sono modifiche non salvate in «{0}».\nVuoi salvarle prima di iniziare una nuova scena?")) return;
            using var busy = BeginBusy();
            _reloadOrigin = "open";
            ShowTask(L.T("Nuova scena…"));
            if (_webReady) SendToWeb(new { type = "releaseAll" });    // the view lets go of the old project (memory)
            await Run(async api => { await api.Post("new"); });
            _collapseTree = true;
            ClearAiOutputs();
            _aiProjectGen++;
            ResetPaint();
            SetSelectionRaw("");
            _scene = new SceneModel();
            SetProjectPath(null);
            await RefreshScene("");
            await LoadViews();
            RenderLibrary();
            // everything back to defaults: framing, render settings, exposure, caustics
            await LoadRenderSettings();
            if (_renderSettings["view"] is JsonObject nv) { SendToWeb(new { type = "setCamera", view = nv.DeepClone() }); SendCameraOptions(nv); }
            _caustics = false;
            ResetPanelState();
            // panels of things that are gone (a material, the brush) close; Rendering, Fotocamera and Ambiente show
            // their defaults
            if (_rightPanel is "material" or "materials" or "paint") await ShowRightPanel("");
            else if (_rightPanel != "") await ShowRightPanel(_rightPanel);
            HideTask();
            await LoadCamView();
        }

        async Task OpenProjectCore()
        {
            if (!await AskSaveChanges("Ci sono modifiche non salvate in «{0}».\nVuoi salvarle prima di aprire un altro progetto?")) return;
            var dlg = new Microsoft.Win32.OpenFileDialog { Filter = L.T("Progetti Simpler|*.simpler"), InitialDirectory = StartFolder("project") };
            if (dlg.ShowDialog(this) != true) return;
            await OpenProjectPath(dlg.FileName);
        }

        /// <summary>A project of the recent list: asks to save the changes first, as Open does.</summary>
        async Task OpenRecentCore(string path)
        {
            if (!File.Exists(path))
            {
                Msg.Show(this, L.F("Il progetto «{0}» non c'è più (spostato o eliminato):\n{1}", Path.GetFileNameWithoutExtension(path), path),
                    "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning);
                var s = Settings.Load();
                s.RecentProjects.RemoveAll(p => string.Equals(p, path, StringComparison.OrdinalIgnoreCase));
                s.Save();
                return;
            }
            if (!await AskSaveChanges("Ci sono modifiche non salvate in «{0}».\nVuoi salvarle prima di aprire un altro progetto?")) return;
            await OpenProjectPath(path);
        }

        async Task OpenProjectPath(string path)
        {
            AppLog.Write("open project: " + path);
            var askClock = System.Diagnostics.Stopwatch.StartNew();
            using var busy = BeginBusy();
            _reloadOrigin = "open";
            ShowTask(L.T("Apertura progetto…"));
            if (_webReady) SendToWeb(new { type = "releaseAll" });
            var hasView = false;
            // an automatic copy newer than the project (Simpler closed badly): recovered on request
            var (openPath, recovered) = await AskRecoverAutosave(path);
            // (the question about the automatic copy waits for the user: not part of the time of the opening - it
            // made a 3 s opening look like 18 s in the log)
            if (askClock.Elapsed.TotalSeconds >= 0.5)
                AppLog.Write($"automatic copy: {(recovered ? "recovered" : "not recovered")}, answered in {askClock.Elapsed.TotalSeconds:0.0} s");
            var openClock = System.Diagnostics.Stopwatch.StartNew();
            var missingTex = new List<string>();
            var emptyTex = new List<string>();
            await Run(async api =>
            {
                // (the engine looks for textures not where they were also in the folders pointed to before)
                var folders = Settings.Load().TextureFolders.Where(Directory.Exists).ToArray();
                var r = await api.Post("open", new { path = openPath, recovered, textureFolders = folders });
                _collapseTree = true;
                hasView = (bool?)r["hasView"] ?? false;
                if (r["missingTextures"] is JsonArray mt) missingTex.AddRange(mt.Select(x => (string?)x ?? "").Where(x => x != ""));
                if (r["emptyTextures"] is JsonArray et) emptyTex.AddRange(et.Select(x => (string?)x ?? "").Where(x => x != ""));
            });
            if (recovered) Status(L.T("Recuperato il salvataggio automatico: salva per tenerlo nel progetto."));
            AppLog.Write($"project read by the engine in {openClock.Elapsed.TotalSeconds:0.0} s");
            Remember(path);
            AddRecent(path);
            SetProjectPath(path);
            LoadAiOutputs(path);
            _aiProjectGen++;
            ResetPaint();
            SetSelectionRaw("");
            _scene = new SceneModel();
            await PushViewportSize();
            // the framing saved with the project is kept: "frame everything" only for projects without one
            if (hasView) ForcePreviewReload("open");
            await RefreshScene(hasView ? null : "");
            await Run(async api =>
            {
                var s = await api.Get("settings");
                if (s["view"] is JsonNode view) SendToWeb(new { type = "setCamera", view = view.DeepClone() });
                // (kept: if the view falls while the project opens, it is put back when the view starts again)
                if (s["view"] is JsonObject keep) { _cameraToRestore = keep.DeepClone() as JsonObject; _lastCamera = keep.DeepClone() as JsonObject; }
                // (15/11, Luca: a project opened with the camera on the bare ground, once; the second time in its place) what
                // is sent, in the log: with the line «camera set» of the view it says where the framing was lost
                AppLog.Write("open: framing of the project " + (s["view"] is JsonObject vo ? "sent to the view: position " + (vo["position"]?.ToJsonString() ?? "?") + " target " + (vo["target"]?.ToJsonString() ?? "?") : "NOT in the settings (hasView " + hasView + ")"));
            });
            await LoadViews();
            RenderLibrary();
            await LoadRenderSettings();
            if (_renderSettings["view"] is JsonObject ov) SendCameraOptions(ov);
            ResetPanelState();
            // an open panel shows the project just opened (before: the Rendering panel kept the old values)
            if (_rightPanel is "material" or "materials" or "paint") await ShowRightPanel("");
            else if (_rightPanel != "") await ShowRightPanel(_rightPanel);
            HideTask();
            _pauseCalc = false; _snowHidden = false;      // (the engine opens a project with both off)
            RenderLightenBox();
            await LoadCamView();
            _ = CheckOutdatedModelsFor(path);
            NoteEmptyTextures(emptyTex);
            // (cloud) textures of a model or an ecosystem of the cloud that is not here yet: downloaded, linked again
            if (missingTex.Count > 0 && await RestoreContentTextures(missingTex))
            {
                missingTex.Clear();
                await Run(async api =>
                {
                    var r2 = await api.Get("textures/missing");
                    if (r2["missing"] is JsonArray m2) missingTex.AddRange(m2.Select(x => (string?)x ?? "").Where(x => x != ""));
                });
            }
            if (missingTex.Count > 0)
            {
                AppLog.Write($"open project: {missingTex.Count} textures missing");
                // (1.74.0) the ones already answered «No» for this project are not asked again at every opening: only
                // said in the status bar (File ▸ Cerca texture mancanti looks for them at any moment)
                var declined = DeclinedFor(path);
                var ask = missingTex.Where(m => !declined.Contains(m)).ToList();
                if (ask.Count > 0)
                    await AskMissingTextures(ask, Path.GetDirectoryName(path), true, path);
                else
                    Status(L.F("{0} texture mancanti, già segnalate: i materiali usano il colore di base (File ▸ Cerca texture mancanti)", missingTex.Count));
            }
        }

        /// <summary>File ▸ Cerca texture mancanti…: the textures of the project not found, at any moment.</summary>
        async Task FindMissingTexturesOfProject()
        {
            var missing = new List<string>();
            await Run(async api =>
            {
                var r = await api.Get("textures/missing");
                if (r["missing"] is JsonArray m) missing.AddRange(m.Select(x => (string?)x ?? "").Where(x => x != ""));
            });
            if (missing.Count == 0) { Status(L.T("Nessuna texture mancante nel progetto")); return; }
            await AskMissingTextures(missing, string.IsNullOrEmpty(_projectPath) ? null : Path.GetDirectoryName(_projectPath), true);
        }

        async Task CheckOutdatedModelsFor(string path)
        {
            await Task.Delay(400);
            if (_projectPath == path) await CheckOutdatedModels();
        }

        async Task<bool> SaveProjectCore(bool saveAs)
        {
            var path = _projectPath;
            if (saveAs || path == null)
            {
                var dlg = new Microsoft.Win32.SaveFileDialog { Filter = L.T("Progetti Simpler|*.simpler"), InitialDirectory = StartFolder("project"), FileName = L.T("Scena.simpler"), OverwritePrompt = false };
                if (dlg.ShowDialog(this) != true) return false;
                path = dlg.FileName;
                if (!path.EndsWith(".simpler", StringComparison.OrdinalIgnoreCase)) path += ".simpler";
                // (1.76.7) over another project: the old one and its folders to the Recycle Bin first (they never mix
                // with the new ones, and can be taken back)
                if (File.Exists(path) && !string.Equals(Path.GetFullPath(path), _projectPath == null ? "" : Path.GetFullPath(_projectPath), StringComparison.OrdinalIgnoreCase))
                {
                    var name = Path.GetFileNameWithoutExtension(path);
                    if (Msg.Show(this, L.F("Esiste già il progetto «{0}». Sostituirlo?\n\nIl vecchio progetto e le sue cartelle (texture, elaborazioni AI, fotogrammi dei video) vanno nel Cestino di Windows: da lì si possono recuperare.", name),
                                 "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes)
                        return false;
                    if (!await TrashOldProject(path)) return false;
                }
            }
            using var busy = BeginBusy();
            ShowTask(L.T("Salvataggio del progetto…"));
            bool ok = false;
            _saving = true;
            try
            {
                await Run(async api =>
                {
                    var r = await api.Post("save", new { path });
                    path = (string?)r["path"] ?? path;
                    // (1.76.7) files of the project's folders it no longer uses: to the Recycle Bin
                    if (r["trash"] is JsonArray tr && tr.Count > 0)
                        RecycleBin.Send(tr.Select(x => (string?)x ?? "").Where(x => x != ""));
                    SetProjectPath(path);
                    Remember(path!);
                    AddRecent(path!);
                    ok = true;
                    Status(L.T("Progetto salvato: ") + path);
                });
                if (ok && path != null) { SaveAiOutputs(path); if (_libraryTab == "aioutputs") RenderLibrary(); }
            }
            finally { _saving = false; }
            HideTask();
            return ok;
        }

        /// <summary>(1.76.7) Saving over another project: the old project (with its backup and automatic copy) and the
        /// files of its folders the open scene does not use go to the Recycle Bin. False: something stays in the way.</summary>
        async Task<bool> TrashOldProject(string path)
        {
            JsonObject? plan = null;
            await Run(async api => { plan = await api.Post("project/overwrite", new { path }); });
            if (plan == null) return false;
            var files = (plan["files"] as JsonArray ?? new JsonArray()).Select(x => (string?)x ?? "").Where(x => x != "").ToList();
            var folders = (plan["folders"] as JsonArray ?? new JsonArray()).Select(x => (string?)x ?? "").Where(x => x != "").ToList();
            // the AI results of the old project (its folder «X AI»): the ones the open scene does not list
            var aiDir = AiProjectDir(path);
            if (Directory.Exists(aiDir))
            {
                var mine = new HashSet<string>(_aiOutputs.SelectMany(o => new[] { o.Before, o.After, o.Thumb, o.StartImg, o.EndImg })
                                               .Where(f => !string.IsNullOrEmpty(f)).Select(f => Path.GetFullPath(f)), StringComparer.OrdinalIgnoreCase);
                files.AddRange(Directory.GetFiles(aiDir).Where(f => !mine.Contains(Path.GetFullPath(f))));
                folders.Add(aiDir);
            }
            RecycleBin.Send(files);
            RecycleBin.SendIfEmpty(folders);
            if (File.Exists(path))
            {
                Msg.Show(this, L.F("Non riesco a spostare nel Cestino il vecchio progetto «{0}» (è aperto in un altro programma?). Il salvataggio è annullato.", Path.GetFileNameWithoutExtension(path)),
                         "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning);
                return false;
            }
            AppLog.Write($"save over another project: {files.Count} files of «{Path.GetFileName(path)}» to the Recycle Bin");
            return true;
        }

        async Task ImportModel()
        {
            var dlg = new Microsoft.Win32.OpenFileDialog
            {
                Filter = L.T("Modelli 3D|*.fbx;*.glb;*.gltf;*.obj;*.usd;*.usda;*.usdc;*.usdz|Tutti i file|*.*"),
                InitialDirectory = StartFolder("model"),
                Multiselect = true,
            };
            if (dlg.ShowDialog(this) != true) return;
            await ImportPaths(dlg.FileNames);
        }

        /// <summary>Models into the scene, after the small dialog with «Unisci i pezzi in un solo oggetto».</summary>
        async Task ImportPaths(IReadOnlyList<string> files)
        {
            if (files.Count == 0) return;
            var st = Settings.Load();
            var ans = ImportSceneDialog.Ask(this, files, st.MergeOnImport, st.ImportAtView);
            if (ans == null) return;
            var (merge, atView) = ans.Value;
            if (merge != st.MergeOnImport || atView != st.ImportAtView) { st.MergeOnImport = merge; st.ImportAtView = atView; st.Save(); }
            // (1.75.48) the first file at the centre of the view, the others with the same shift (aligned to it)
            JsonArray? point = null, offset = null;
            if (atView && (await AskViewPoint())?["point"] is JsonArray p) point = (JsonArray)p.DeepClone();
            foreach (var f in files)
            {
                var o = await ImportPath(f, merge, offset == null ? point : null, offset);
                if (point != null && offset == null) offset = o;
            }
        }

        async Task<JsonArray?> ImportPath(string path, bool merge, JsonArray? location = null, JsonArray? offset = null)
        {
            JsonArray? moved = null;
            using var busy = BeginBusy();
            _reloadOrigin = "action";
            ShowTask(L.F("Importazione di {0}…", Path.GetFileName(path)));
            string newId = "";
            var missing = new List<string>();
            var empty = new List<string>();
            string? error = null;
            await RunOrError(e => error = e, async api =>
            {
                var folders = Settings.Load().TextureFolders.Where(Directory.Exists).ToArray();
                var body = new JsonObject { ["path"] = path, ["textureFolders"] = new JsonArray(folders.Select(x => (JsonNode)x!).ToArray()), ["merge"] = merge };
                if (location != null) body["location"] = location.DeepClone();
                else if (offset != null) body["offset"] = offset.DeepClone();
                var r = await api.Post("import", body);
                newId = (string?)r["id"] ?? "";
                moved = r["offset"] as JsonArray;
                if (r["missingTextures"] is JsonArray m) missing.AddRange(m.Select(x => (string?)x ?? "").Where(x => x != ""));
                if (r["emptyTextures"] is JsonArray et) empty.AddRange(et.Select(x => (string?)x ?? "").Where(x => x != ""));
                var found = (int?)r["texturesFound"] ?? 0;
                var msg = L.F("Importato {0}: {1} nodi, {2} oggetti ({3} mesh distinte), {4} materiali", Path.GetFileName(path), (int?)r["nodes"], (int?)r["meshes"], (int?)r["uniqueMeshes"], (int?)r["materials"]);
                if (r["sizeCm"] is JsonArray sz && sz.Count == 3)
                    msg += L.F(" · dimensioni {0} × {1} × {2} cm", Num.F((double?)sz[0] ?? 0, 1), Num.F((double?)sz[1] ?? 0, 1), Num.F((double?)sz[2] ?? 0, 1));
                if (found > 0) msg += L.F(" · {0} texture ritrovate automaticamente", found);
                if (missing.Count > 0) msg += L.F(" · {0} texture mancanti", missing.Count);
                Status(msg, missing.Count > 0);
            });
            Remember(path, "model");
            HideTask();
            if (error != null)
            {
                Status(L.T("Import non riuscito: ") + Path.GetFileName(path), true);
                Msg.Show(this, L.F("Non sono riuscito a importare {0}.", Path.GetFileName(path)) + L.T("\n\n") + error, L.T("Importa modello"), MessageBoxButton.OK, MessageBoxImage.Warning);
                return null;
            }
            if (newId != "") { _expanded.Add(newId); SetSelectionRaw(newId); }
            await RefreshScene(newId);
            NoteEmptyTextures(empty);
            if (missing.Count > 0) await AskMissingTextures(missing, Path.GetDirectoryName(path));
            return moved;
        }

        /// <summary>Pictures without any file (a map left empty in the program the model comes from, «Map #0» of 3ds Max):
        /// nothing to look for - only said, with the materials they belong to (in app.log the whole list).</summary>
        void NoteEmptyTextures(List<string> empty)
        {
            if (empty.Count == 0) return;
            AppLog.Write("textures without a file (empty in the original model): " + string.Join(" | ", empty));
            Status(L.F("{0} texture vuote già nel modello originale (senza file), ignorate: {1}", empty.Count,
                       string.Join(" · ", empty.Take(3)) + (empty.Count > 3 ? " …" : "")));
        }

        /// <summary>Missing textures: the user points to the folder where they are; Simpler searches it (and subfolders) by file name.
        /// Each one is written as its file and the materials it belongs to (engine: textures.describe).</summary>
        static System.Collections.Generic.HashSet<string> DeclinedFor(string projectPath)
        {
            var s = Settings.Load();
            var key = s.DeclinedTextures.Keys.FirstOrDefault(k => string.Equals(k, projectPath, StringComparison.OrdinalIgnoreCase));
            return key == null ? new() : new(s.DeclinedTextures[key]);
        }

        static void Decline(string projectPath, IEnumerable<string> missing)
        {
            var s = Settings.Load();
            var key = s.DeclinedTextures.Keys.FirstOrDefault(k => string.Equals(k, projectPath, StringComparison.OrdinalIgnoreCase)) ?? projectPath;
            var list = s.DeclinedTextures.TryGetValue(key, out var l) ? l : new List<string>();
            foreach (var m in missing) if (!list.Contains(m)) list.Add(m);
            s.DeclinedTextures.Remove(key);
            if (s.DeclinedTextures.Count >= 60) s.DeclinedTextures.Remove(s.DeclinedTextures.Keys.First());   // (the oldest)
            s.DeclinedTextures[key] = list.TakeLast(200).ToList();
            s.Save();
        }

        async Task AskMissingTextures(List<string> missing, string? startFolder, bool project = false, string? declineFor = null)
        {
            var list = string.Join(L.T("\n"), missing.Take(8).Select(m => "• " + m)) + (missing.Count > 8 ? L.T("\n") + L.F("… e altre {0}", missing.Count - 8) : "");
            var answer = Msg.Show(this,
                (project ? L.F("Non ho trovato {0} texture del progetto (spostate, cancellate o su un disco non collegato):", missing.Count)
                         : L.F("Non ho trovato {0} texture del modello:", missing.Count)) + L.T("\n\n") + list + L.T("\n\n") +
                L.T("Nel frattempo i materiali interessati usano il loro colore di base (niente rosa in path tracing).\n\n") +
                L.T("Vuoi indicare la cartella dove si trovano? Cerco anche nelle sottocartelle."),
                L.T("Texture mancanti"), MessageBoxButton.YesNo, MessageBoxImage.Question);
            if (answer != MessageBoxResult.Yes)
            {
                if (declineFor != null) Decline(declineFor, missing);     // (not asked again at the next opening)
                return;
            }
            await FindTexturesIn(startFolder);
        }

        async Task FindTexturesIn(string? startFolder)
        {
            var dlg = new Microsoft.Win32.OpenFolderDialog { Title = L.T("Cartella delle texture"), InitialDirectory = startFolder ?? StartFolder("texfolder") };
            if (dlg.ShowDialog(this) != true) return;
            var folder = dlg.FolderName;
            Keep("texfolder", folder, true);
            using var busy = BeginBusy();
            _reloadOrigin = "action";
            ShowTask(L.F("Ricerca delle texture in {0}…", folder));
            int found = 0;
            var still = new List<string>();
            await Run(async api =>
            {
                var r = await api.Post("textures/relink", new { folder });
                found = (int?)r["found"] ?? 0;
                if (r["missing"] is JsonArray m) still.AddRange(m.Select(x => (string?)x ?? ""));
            });
            HideTask();
            if (found > 0)
            {
                var s = Settings.Load();
                if (!s.TextureFolders.Contains(folder, StringComparer.OrdinalIgnoreCase)) { s.TextureFolders.Insert(0, folder); s.TextureFolders = s.TextureFolders.Take(12).ToList(); s.Save(); }
                ForcePreviewReload("textures relinked");
            }
            await RefreshScene();
            Status(still.Count == 0 ? L.F("Trovate e collegate {0} texture", found) : L.F("Collegate {0} texture, ne mancano ancora {1}", found, still.Count), still.Count > 0);
            if (still.Count > 0 && found > 0) await AskMissingTextures(still, folder, true);
        }

        async Task SetQuality(string quality)
        {
            _quality = quality;
            UpdateQualityDrop();
            await Run(async api => { await api.Post("settings", new { quality }); });
        }

        System.Windows.Controls.Button? _qualityDrop;
        static readonly (string id, string label, string tip)[] PtQualities =
        {
            ("bozza", "Bozza", "Anteprima veloce"), ("alta", "Alta", "Qualità alta"), ("finale", "Finale", "Massima qualità (lento)"),
        };
        static readonly (string id, string label, string tip)[] ShadowLevels =
        {
            ("off", "No", "Ombre spente nella vista in tempo reale (più veloce)"), ("media", "Media", "Ombre morbide, mappa 1024"),
            ("alta", "Alta", "Ombre nitide, mappa 2048"), ("ultra", "Ultra", "Ombre molto nitide, mappa 4096"),
        };

        /// <summary>The menu of the bar: shadows of the real-time view, or the quality of the path tracing.</summary>
        void UpdateQualityDrop()
        {
            if (_qualityDrop == null) return;
            if (_boxMode && !_realistic) { _qualityDrop.Visibility = Visibility.Collapsed; return; }
            _qualityDrop.Visibility = Visibility.Visible;
            string text;
            if (_realistic)
            {
                var q = Array.Find(PtQualities, x => x.id == _quality);
                text = L.T("Qualità") + ": " + L.T(q.label ?? "Personalizzata");     // (personalizzata: set in the Rendering panel)
                _qualityDrop.ToolTip = L.T("Qualità del path tracing nella vista");
            }
            else
            {
                var cur = Settings.Load().ViewerShadows;
                var sl = Array.Find(ShadowLevels, x => x.id == cur);
                text = L.T("Ombre") + ": " + L.T(sl.label ?? "Alta");
                _qualityDrop.ToolTip = L.T("Ombre della vista in tempo reale");
            }
            _qualityDrop.Content = text + "  ▾";
        }

        void OpenQualityMenu()
        {
            if (_qualityDrop == null) return;
            var cm = new System.Windows.Controls.ContextMenu { PlacementTarget = _qualityDrop, Placement = System.Windows.Controls.Primitives.PlacementMode.Bottom };
            if (_realistic)
            {
                foreach (var (id, label, tip) in PtQualities)
                {
                    var mi = new System.Windows.Controls.MenuItem { Header = L.T(label), ToolTip = L.T(tip), FontWeight = id == _quality ? FontWeights.SemiBold : FontWeights.Normal, IsChecked = id == _quality };
                    mi.Click += async (_, __) => await SetQuality(id);
                    cm.Items.Add(mi);
                }
            }
            else
            {
                var cur = Settings.Load().ViewerShadows;
                foreach (var (id, label, tip) in ShadowLevels)
                {
                    var mi = new System.Windows.Controls.MenuItem { Header = L.T(label), ToolTip = L.T(tip), FontWeight = id == cur ? FontWeights.SemiBold : FontWeights.Normal, IsChecked = id == cur };
                    mi.Click += (_, __) =>
                    {
                        var s = Settings.Load(); s.ViewerShadows = id; s.Save();
                        SendToWeb(new { type = "shadows", level = id });
                        UpdateQualityDrop();
                        RenderLightenBox();
                        if (_rightPanel != "") RenderProps();
                    };
                    cm.Items.Add(mi);
                }
            }
            cm.IsOpen = true;
        }

        /// <summary>The sharp caustics (MNEE) on or off. `mode` (0 off, 1 normal, 2 sharp) when the whole choice of the
        /// Rendering panel changed: the status says that choice - before 1.74.1 «Normali» wrote «Caustiche disattivate»,
        /// because only the sharp ones were looked at.</summary>
        async Task SetCaustics(bool on, int mode = -1)
        {
            _caustics = on;
            await Run(async api => { await api.Post("settings", new { caustics = on }); });
            if (mode < 0) mode = on ? 2 : (CausticsAny() ? 1 : 0);
            Status(mode == 2 ? L.T("Caustiche attive: vetri e gemme concentrano la luce sulle superfici")
                 : mode == 1 ? L.T("Caustiche normali: riflesse e rifratte calcolate dal path tracing")
                 : L.T("Caustiche disattivate"));
        }

        /// <summary>Any caustics on (normal or sharp), as the Rendering panel shows them.</summary>
        bool CausticsAny()
        {
            bool B(string k) => (bool?)_renderSettings["config"]?[k] ?? true;     // (as the panel reads them: missing = on)
            return _caustics || B("causticsReflective") || B("causticsRefractive");
        }

        async Task FinalRender()
        {
            if (_api == null) return;
            await FlushTerrainSculpt();
            await LoadRenderSettings();
            var fmt = (string?)(_renderSettings["view"] as JsonObject)?["format"] ?? "";
            var cfgR = _renderSettings["config"] as JsonObject ?? new JsonObject();
            double vpa = _web.ActualHeight > 1 ? _web.ActualWidth / _web.ActualHeight : 16.0 / 9;
            var dlg = new RenderDialog(_quality, fmt, FormatAspect(fmt), vpa, (int)((double?)cfgR["samples"] ?? 512)) { Owner = this };
            if (dlg.ShowDialog() != true) return;
            var save = new Microsoft.Win32.SaveFileDialog
            {
                Filter = L.T("PNG 16 bit|*.png|JPEG|*.jpg|OpenEXR (HDR)|*.exr|TIFF 16 bit|*.tif"),
                InitialDirectory = StartFolder("render"),
                FileName = (_projectPath != null ? Path.GetFileNameWithoutExtension(_projectPath) : L.T("Render")) + ".png",
            };
            if (save.ShowDialog(this) != true) return;
            await CamViewBeforeRender();      // (the ecosystems «solo ciò che vede la camera»: for the camera of this image)
            ShowBusy(L.F("Render finale {0}×{1} in corso…", dlg.RenderWidth, dlg.RenderHeight), cancellable: true);
            var sw = Stopwatch.StartNew();
            // the whole app waits: panels, tree, library and keys are locked (a change of the scene, a new project or
            // a save in the middle of the render would end up in the picture or break it); Esc asks to stop it
            var busy = BeginBusy();
            _finalRendering = true;
            try
            {
                await Run(async api =>
                {
                    var r = await api.Post("render", new { path = save.FileName, width = dlg.RenderWidth, height = dlg.RenderHeight, quality = dlg.Quality, textures = dlg.Textures, samples = dlg.Samples });
                    // (1.75.23) where the engine really put it: another name when the chosen file could not be written
                    var saved = (string?)r["path"] ?? save.FileName;
                    if (!string.Equals(saved, save.FileName, StringComparison.OrdinalIgnoreCase))
                    {
                        AppLog.Write($"render: {save.FileName} could not be written, saved as {saved}");
                        Status(L.F("Il file {0} non si poteva scrivere (forse è aperto in un altro programma): render salvato come {1}", Path.GetFileName(save.FileName), saved), true);
                    }
                    else Status(L.F("Render salvato in {0} s: {1}", sw.Elapsed.TotalSeconds.ToString("0.0"), saved));
                    _lastRenderPath = saved;
                    if (!_closeAfterRender) ShowRenderResult(saved, r["stats"] as JsonObject);
                });
            }
            finally
            {
                _finalRendering = false;
                busy.Dispose();
                HideBusy();
            }
            Remember(save.FileName, "render");
            if (_closeAfterRender)
            {
                _closeAfterRender = false;
                _ = Dispatcher.BeginInvoke(new Action(Close));      // (the usual question about unsaved changes)
            }
        }

        bool _finalRendering, _closeAfterRender, _saving;

        async Task CancelFinalRender()
        {
            _busyCancel.IsEnabled = false;
            _busyText.Text = L.T("Interruzione del render…");
            await Run(async api => { await api.Post("render/cancel"); });
        }

        /// <summary>Keys during the final render: Esc asks to stop it, every other key is held (with a word in the status bar).</summary>
        bool FinalRenderKey(Key key)
        {
            if (!_finalRendering) return false;
            if (key == Key.Escape)
            {
                if (!_busyCancel.IsEnabled) return true;            // (already stopping)
                if (Msg.Show(this, L.T("Interrompere il render finale?"), "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) == MessageBoxResult.Yes)
                    _ = CancelFinalRender();
            }
            else if (key is not (Key.LeftCtrl or Key.RightCtrl or Key.LeftShift or Key.RightShift or Key.LeftAlt or Key.RightAlt or Key.System))
                Status(L.T("Render finale in corso: i comandi sono sospesi fino alla fine (Esc per interromperlo)"));
            return true;
        }
    }
}
