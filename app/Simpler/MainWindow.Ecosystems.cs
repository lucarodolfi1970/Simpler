using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace Simpler
{
    /// <summary>
    /// Ecosistemi (engine: ecosystems.py). The library menu shows the ecosystems the user made (his own models: many
    /// are commercial, Simpler ships none); dragged on an object they populate it. The panel on the right (toolbar
    /// button Ecosistemi) makes a new one on the "banco di prova" and changes the one selected in the scene: density,
    /// scale, another arrangement; the rest in Avanzate.
    /// </summary>
    public sealed partial class MainWindow
    {
        JsonArray _ecosystems = new JsonArray();
        // (1.79, Luca: «anche ecosystem devono avere simpler e mine») Ecosistemi ▸ Simpler shows the folder «Simpler» of
        // the ecosystem library (the ones that will ship with Simpler: red and read only with SimplerLocked), I miei
        // all the rest; each tab keeps its own folder
        internal const string SimplerEco = "Simpler";
        string _ecoMineFolder = "", _ecoSimFolder = SimplerEco;
        string _ecoFolder
        {
            get => _libraryTab == "simplereco" ? _ecoSimFolder : _ecoMineFolder;
            set { if (_libraryTab == "simplereco") _ecoSimFolder = value; else _ecoMineFolder = value; }
        }
        bool ReadOnlyEco(string folder) => SimplerLocked && Under(folder, SimplerEco);
        List<string> _ecoFolders = new();
        JsonObject? _ecoInfo;

        async Task LoadEcosystems()
        {
            JsonObject? r = null;
            await Run(async api => { r = await api.Get("ecosystems"); });
            _ecosystems = r?["items"] as JsonArray ?? new JsonArray();
            _ecoFolders = (r?["folders"] as JsonArray)?.Select(x => (string?)x ?? "").Where(x => x != "").ToList() ?? new List<string>();
            MergeCloudEcosystems();          // (cloud) what is in the cloud and not here yet
        }

        /// <summary>«Copia» on an ecosystem: «Incolla» (tasto destro on a folder or on the empty part of the library)
        /// makes a copy there, named «… (copia)»; it can be pasted again.</summary>
        void CopyEco(string id, string name)
        {
            _libClip = new LibClip("eco", false, id, name, Copy: true);
            Status(L.F("Copiato: {0} · apri la cartella dove vuoi la copia e scegli «Incolla» (tasto destro)", name));
            RenderLibrary();
        }

        async Task PasteEcoCopy(LibClip c, string target)
        {
            JsonObject? r = null;
            using (BeginBusy())
                await Run(async api => { r = await api.Post("ecosystems/copy", new { id = c.Key, folder = target }); });
            if (r == null) return;
            await LoadEcosystems();
            RenderLibrary();
            Status(L.F("Ecosistema copiato: {0}", (string?)r["name"] ?? c.Label));
        }

        async Task MoveEco(string id, string folder)
        {
            await Run(async api => { await api.Post("ecosystems/move", new { id, folder }); });
            Status(L.F("Ecosistema spostato in {0}", folder == "" ? L.T("Ecosistemi") : folder));
            await LoadEcosystems();
            RenderLibrary();
        }

        /// <summary>The ecosystem selected in the scene (its group, or one of its layers), for the panel.</summary>
        string EcoGroupOfSelection()
        {
            if (_selected == "" || !_scene.ById.TryGetValue(_selected, out var o)) return "";
            var g = new[] { o }.Concat(_scene.Ancestors(o)).FirstOrDefault(x => x.Eco == "group");
            return g?.Id ?? "";
        }

        /// <summary>The test plot of the scene (one per scene; an older project may have more: the selected one, or the
        /// one with most scatters on it).</summary>
        string PlotInScene()
        {
            var plots = _scene.ById.Values.Where(o => o.Eco == "plot").ToList();
            if (plots.Count <= 1) return plots.FirstOrDefault()?.Id ?? "";
            if (_selected != "" && _scene.ById.TryGetValue(_selected, out var sel))
            {
                var p = new[] { sel }.Concat(_scene.Ancestors(sel)).FirstOrDefault(x => x.Eco == "plot");
                if (p != null) return p.Id;
            }
            return plots.OrderByDescending(p => p.Children.Count(c => c.Paint || c.Eco == "group")).First().Id;
        }

        async Task LoadEcoInfo()
        {
            _ecoInfo = null;
            var g = EcoGroupOfSelection();
            if (g != "") await Run(async api => { _ecoInfo = await api.Get("ecosystems/info?group=" + Uri.EscapeDataString(g)); });
            await LoadEcoLibraryView();
        }

        // ---------------------------------------------------------------- an ecosystem of the library in the panel

        string _ecoViewId = "";          // the ecosystem of the library shown in the panel (a click on its tile)
        JsonObject? _ecoView;            // its layers (ecosystems/detail)
        JsonObject? _ecoEditing;         // the one put back on the bench to be changed (ecosystems/editing)

        async Task LoadEcoLibraryView()
        {
            JsonObject? v = null, ed = null;
            try
            {
                if (_ecoViewId != "") v = await _api!.Get("ecosystems/detail?id=" + Uri.EscapeDataString(_ecoViewId));
            }
            catch { _ecoViewId = ""; }      // (deleted meanwhile: the panel without it)
            try { ed = await _api!.Get("ecosystems/editing"); } catch { }
            _ecoView = v;
            _ecoEditing = ed != null && ((string?)ed["id"] ?? "") != "" ? ed : null;
        }

        /// <summary>(1.79.0, Luca: «se ne apro un altro devo poterlo vedere, non rimanere intrappolato nel precedente») a
        /// click on an ecosystem of the library opens it: on the bench as it was saved, framed, its scatters in the panel
        /// with «Salva modifiche» / «Salva come nuovo». The one open before, changed and not saved: asked first (save,
        /// leave, stay). The locked Simpler ones are opened only to look at them.</summary>
        async Task OpenEcoInPanel(string id)
        {
            if (_ecosystems.OfType<JsonObject>().Any(x => (string?)x["id"] == id && ((bool?)x["cloud"] ?? false))) { await DownloadCloud(id); return; }   // (cloud) not here yet: a click downloads it
            if (_ecoOpening) return;
            _ecoOpening = true;
            try
            {
                var name = (string?)_ecosystems.OfType<JsonObject>().FirstOrDefault(x => (string?)x["id"] == id)?["name"] ?? "";
                var st = await BenchState();
                var bench = (string?)st?["bench"] ?? "";
                if ((string?)st?["id"] == id && bench != "" && _scene.ById.ContainsKey(bench))
                {
                    // (already open: back to it)
                    _ecoViewId = id;
                    SelectFromViewport(new[] { bench }, bench);
                    SendToWeb(new { type = "frameBench", id = ViewerId(bench) });
                    await LoadEcoLibraryView();
                }
                else
                {
                    if (!await LeaveBench(st)) return;
                    _ecoViewId = id;
                    if (!await EditEcosystem(id, name, true)) return;
                }
                if (_rightPanel == "ecosystem") { await LoadEcoInfo(); RenderProps(); }
                else await ShowRightPanel("ecosystem");
                if (_libraryTab is "ecosystems" or "simplereco") RenderLibrary();      // (the open one marked)
            }
            finally { _ecoOpening = false; }
        }

        bool _ecoOpening;

        /// <summary>The bench of the scene: the ecosystem open on it and whether its scatters changed since it was opened or
        /// saved (ecosystems/editing?changed=1); null when the engine does not answer.</summary>
        async Task<JsonObject?> BenchState()
        {
            try { return await _api!.Get("ecosystems/editing?changed=1"); }
            catch { return null; }
        }

        /// <summary>Before another ecosystem (or a new one) takes the bench: what is on it, changed and not saved, is saved,
        /// left or kept (false: stay). A locked Simpler one cannot be saved: only asked whether to leave it.</summary>
        async Task<bool> LeaveBench(JsonObject? st)
        {
            if (!((bool?)st?["changed"] ?? false)) return true;
            var openId = (string?)st?["id"] ?? "";
            var openName = (string?)st?["name"] ?? "";
            var folder = (string?)_ecosystems.OfType<JsonObject>().FirstOrDefault(x => (string?)x["id"] == openId)?["folder"] ?? "";
            if (openId != "" && ReadOnlyEco(folder))
                return Msg.Show(this, L.F("Le modifiche a «{0}» non si possono salvare (ecosistema Simpler): vanno perse. Continuo?", openName),
                                "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) == MessageBoxResult.Yes;
            var q = openId != "" ? L.F("Hai modificato «{0}» sul banco di prova. Salvare le modifiche?", openName)
                                 : L.T("Sul banco di prova c'è un ecosistema non salvato. Salvarlo?");
            var a = Msg.Show(this, q, "Simpler", MessageBoxButton.YesNoCancel, MessageBoxImage.Question);
            if (a == MessageBoxResult.Cancel) return false;
            if (a == MessageBoxResult.No) return true;
            if (openId != "") { _ecoEditing = st; return await SaveEcoChanges(); }
            return await SaveEcosystem();
        }

        /// <summary>«Nuovo ecosistema»: the bench empty (what was on it, changed: asked first), the brush ready.</summary>
        async Task NewEcosystem()
        {
            if (!await LeaveBench(await BenchState())) return;
            _ecoViewId = "";
            _ecoView = null;
            await NewEcoPlot(20, true);
            await LoadEcoLibraryView();
            if (_libraryTab is "ecosystems" or "simplereco") RenderLibrary();
            RenderProps();
        }

        /// <summary>(1.79.0, Luca: «come esco da qui!!») «Esci dal banco di prova»: what is on it, changed and not saved,
        /// asked first (save, leave, stay); then the bench goes with its scatters, the scene it hid is shown again and
        /// framed. One undo step.</summary>
        async Task ExitBench()
        {
            if (!await LeaveBench(await BenchState())) return;
            if (Painting) SetTool("move");
            JsonObject? r = null;
            using (BeginBusy())
            {
                ShowTask(L.T("Chiudo il banco di prova…"));
                try { await Run(async api => { r = await api.Post("ecosystems/close", new { }); }); }
                finally { HideTask(); }
            }
            if (r == null) return;
            _benchId = "";
            _benchHidden.Clear();
            _ecoViewId = "";
            _ecoView = null;
            await RefreshScene();
            BenchNote();
            SendToWeb(new { type = "frame", ids = Array.Empty<string>() });
            await LoadEcoLibraryView();
            if (_libraryTab is "ecosystems" or "simplereco") RenderLibrary();
            RenderProps();
            Status(L.T("Banco di prova chiuso: la scena è di nuovo visibile"));
        }

        /// <summary>The button that leaves the bench (panels).</summary>
        Button ExitBenchButton()
        {
            var b = SmallButton(Icons.Close, L.T("Esci dal banco di prova"), ExitBench);
            b.ToolTip = L.T("Toglie il banco di prova e i suoi scatter e rimostra la scena (prima chiede se salvare le modifiche)");
            return b;
        }

        /// <summary>Whether the ecosystem open on the bench is a locked Simpler one (only to look at).</summary>
        bool EditingReadOnly()
        {
            var id = (string?)_ecoEditing?["id"] ?? "";
            var folder = (string?)_ecosystems.OfType<JsonObject>().FirstOrDefault(x => (string?)x["id"] == id)?["folder"] ?? "";
            return id != "" && ReadOnlyEco(folder);
        }

        async Task PlaceOnSelected(string id, string name)
        {
            var t = _selected != "" && _scene.ById.TryGetValue(_selected, out var so) && so.IsMesh ? so : null;
            if (t == null) { Status(L.T("Trascina l'ecosistema su un oggetto della vista, o seleziona prima l'oggetto"), true); return; }
            await PlaceEcosystem(id, name, t.Id, null);
        }

        /// <summary>«Modifica sul banco di prova»: the ecosystem back on the bench as it was saved, one scatter per layer
        /// (the brush adds and erases, Shift erases); scatters already on the bench: asked first.</summary>
        async Task<bool> EditEcosystem(string id, string name, bool clear = false)
        {
            JsonObject? r = null;
            using (BeginBusy())
            {
                ShowTask(L.F("Apro «{0}» sul banco di prova…", name));
                try { await Run(async api => { r = await api.Post("ecosystems/edit", new { id, clear }); }); }
                finally { HideTask(); }
            }
            if (r == null) return false;
            var busy = (int?)r["busy"] ?? 0;
            if (busy > 0)
            {
                if (Msg.Show(this, L.F("Sul banco di prova ci sono già {0} scatter. Li tolgo per mettere «{1}»?", busy, name),
                             "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return false;
                using (BeginBusy())
                {
                    ShowTask(L.F("Apro «{0}» sul banco di prova…", name));
                    try { await Run(async api => { r = await api.Post("ecosystems/edit", new { id, clear = true }); }); }
                    finally { HideTask(); }
                }
                if (r == null) return false;
            }
            await RefreshScene();
            var plot = (string?)r["plot"] ?? "";
            var hidden = (r["hidden"] as JsonArray)?.Select(x => (string?)x ?? "").Where(x => x != "").ToList() ?? new List<string>();
            if (hidden.Count > 0) _benchHidden = hidden;
            _benchId = plot;
            if (plot != "") { _expanded.Add(plot); SelectFromViewport(new[] { plot }, plot); SendToWeb(new { type = "frameBench", id = ViewerId(plot) }); }
            BenchNote();
            await LoadEcoLibraryView();
            Status(EditingReadOnly()
                ? L.F("«{0}» aperto sul banco di prova, solo da guardare (ecosistema Simpler)", name)
                : L.F("«{0}» aperto sul banco di prova: a destra clicca uno scatter per cambiarne i modelli o dipingere (Maiusc cancella), poi «Salva modifiche»", name));
            RenderProps();
            return true;
        }

        /// <summary>«Salva modifiche»: the ecosystem being changed gets the scatters of the bench (same name and folder);
        /// the thumbnail is made again.</summary>
        async Task<bool> SaveEcoChanges()
        {
            var plot = PlotInScene();
            var id = (string?)_ecoEditing?["id"] ?? "";
            var name = (string?)_ecoEditing?["name"] ?? "";
            if (plot == "" || id == "" || EditingReadOnly()) return false;
            if (Painting) SetTool("move");
            using var busy = BeginBusy();
            ShowTask(L.T("Salvataggio dell'ecosistema e miniatura…"));
            var thumb = await CaptureViewSnapshot(256, 256, 0.88);
            JsonObject? r = null;
            try { await Run(async api => { r = await api.Post("ecosystems/save", new { plot, replace = id, thumb }); }); }
            finally { HideTask(); }
            if (r == null) return false;
            await LoadEcosystems();
            if (_libraryTab is "ecosystems" or "simplereco") RenderLibrary();
            Status(L.F("Ecosistema aggiornato: {0} ({1} pezzi in {2} strati)", name, (int?)r["pieces"] ?? 0, (int?)r["layers"] ?? 0));
            if (((int?)r["thumbJob"] ?? 0) is int job && job > 0) _ = PollEcoThumb(job);
            await LoadEcoLibraryView();
            if (_rightPanel == "ecosystem") RenderProps();
            return true;
        }

        /// <summary>(Luca: «non vedo gli scatter? come faccio a selezionarne uno e a modificarlo») the scatters on the bench,
        /// one button each: it opens the Scatter panel on that scatter - its models (add one, change one, their weights)
        /// and the brush (Shift erases).</summary>
        void AddBenchScatters(Panel into, string plot)
        {
            if (!_scene.ById.TryGetValue(plot, out var po)) return;
            foreach (var sc in po.Children.Where(c => c.Paint && c.Eco == ""))
            {
                var scId = sc.Id;
                var b = SmallButton(Icons.Brush, L.F("{0} · {1} pezzi", sc.Name, sc.PaintCount.ToString("N0")), async () =>
                {
                    await Task.Yield();
                    Select(scId);
                    if (Painting) SwitchPaintGroup(scId);
                    else SetTool("paint");
                });
                b.HorizontalAlignment = HorizontalAlignment.Left;
                b.Margin = new Thickness(0, 2, 0, 2);
                b.ToolTip = L.T("Apre questo scatter nel pannello Scatter: aggiungi o cambia i suoi modelli e il loro peso, dipingi per aggiungere pezzi, Maiusc per cancellarli");
                into.Children.Add(b);
            }
        }

        /// <summary>(Luca: «ho fatto exit brush... ma come diavolo salvo le modifiche fatte?») while an ecosystem of the
        /// library is being changed on the bench, the Scatter panel and the properties of the bench and of its scatters
        /// start with «Stai modificando …» and its two saves (before, they were only in the Ecosystems panel).</summary>
        void EcoEditBar()
        {
            if (_ecoEditing == null || _rightPanel is not ("paint" or "") || EditingReadOnly()) return;
            var plot = PlotInScene();
            if (plot == "" || (string?)_ecoEditing["plot"] != plot) return;
            if (_rightPanel == "" && !(_selected != "" && _scene.ById.TryGetValue(_selected, out var so)
                                       && new[] { so }.Concat(_scene.Ancestors(so)).Any(x => x.Id == plot))) return;
            var bar = new StackPanel();
            bar.Children.Add(HintSmall(L.F("Stai modificando l'ecosistema «{0}»", (string?)_ecoEditing["name"] ?? "")));
            var row = new WrapPanel { Margin = new Thickness(0, 4, 0, 0) };
            var keep = SmallButton(Icons.Save, L.T("Salva modifiche"), SaveEcoChanges);
            keep.ToolTip = L.T("Aggiorna l'ecosistema nella libreria (stesso nome e cartella) con gli scatter del banco di prova");
            row.Children.Add(keep);
            var asNew = SmallButton(Icons.Save, L.T("Salva come nuovo"), SaveEcosystem);
            asNew.ToolTip = L.T("Un nuovo ecosistema con gli scatter del banco di prova: quello di partenza resta com'era");
            row.Children.Add(asNew);
            row.Children.Add(ExitBenchButton());
            bar.Children.Add(row);
            var card = Theme.Card(bar, 12);
            _props.Children.Insert(Math.Min(1, _props.Children.Count), card);
        }

        /// <summary>(1.79.0, Luca: «come salvo questo ecosistema? … perché non riesci a creare un'interfaccia chiara») the
        /// scatters of what is selected - an object with scatters on it, a scatter, an ecosystem placed, the bench - can
        /// be saved as an ecosystem right there: the Scatter panel and the properties start with «Salva come ecosistema»
        /// (before, only in the Ecosystems panel, under Avanzate for the scatters of the scene).</summary>
        void EcoSaveBar()
        {
            if (_rightPanel is not ("paint" or "")) return;
            var plot = PlotInScene();
            if (_ecoEditing != null && plot != "" && (string?)_ecoEditing["plot"] == plot) return;     // (EcoEditBar)
            var start = _rightPanel == "paint" && _paintGroup != "" ? _paintGroup : _selected;
            if (start == "" || !_scene.ById.TryGetValue(start, out var o)) return;
            var ids = EcoScattersOf(o, out var bench);
            if (ids == null) return;
            var bar = new StackPanel();
            bar.Children.Add(HintSmall(bench
                ? L.T("Il banco di prova diventa un ecosistema della libreria (Ecosistemi), da trascinare su qualunque superficie")
                : L.F("Gli scatter di «{0}» diventano un ecosistema della libreria (Ecosistemi), da trascinare su qualunque superficie", o.Name)));
            var b = SmallButton(Icons.Save, L.T("Salva come ecosistema"), async () => { await SaveEcosystemOf(ids, bench ? "" : o.Name); });
            b.ToolTip = L.T("Salva questi scatter come ecosistema: chiede il nome e lo mette nella libreria Ecosistemi, nella cartella aperta");
            b.HorizontalAlignment = HorizontalAlignment.Left;
            b.Margin = new Thickness(0, 4, 0, 0);
            bar.Children.Add(b);
            _props.Children.Insert(Math.Min(1, _props.Children.Count), Theme.Card(bar, 12));
        }

        /// <summary>What of o can be saved as an ecosystem: the distributions (scatters, ecosystems placed) it is in or has
        /// on it - or, on the bench, the whole bench (bench true, empty list); null: nothing.</summary>
        List<string>? EcoScattersOf(SceneObject o, out bool bench)
        {
            var plot = PlotInScene();
            bench = plot != "" && (o.Id == plot || _scene.Ancestors(o).Any(a => a.Id == plot));
            if (bench) return _scene.ById.TryGetValue(plot, out var po) && po.Children.Any(c => c.Paint) ? new List<string>() : null;
            var ids = new List<string>();
            var top = new[] { o }.Concat(_scene.Ancestors(o)).FirstOrDefault(x => x.Eco == "group" || (x.Paint && x.Eco != "layer"));
            if (top != null) ids.Add(top.Id);
            else
            {
                void Walk(SceneObject n)
                {
                    foreach (var c in n.Children)
                    {
                        if (c.Eco == "group" || (c.Paint && c.Eco != "layer")) ids.Add(c.Id);
                        else Walk(c);
                    }
                }
                Walk(o);
            }
            return ids.Count > 0 ? ids : null;
        }

        /// <summary>The card of the ecosystem of the library shown in the panel.</summary>
        void RenderEcoLibraryCard()
        {
            var v = _ecoView;
            if (v == null) return;
            var id = (string?)v["id"] ?? "";
            var name = (string?)v["name"] ?? "";
            var folder = (string?)v["folder"] ?? "";
            var ro = ReadOnlyEco(folder);
            var card = new StackPanel();
            var head = new DockPanel();
            var x = SmallIconButton(Icons.Close, L.T("Chiudi"));
            x.Click += (_, __) => { _ecoViewId = ""; _ecoView = null; RenderProps(); };
            DockPanel.SetDock(x, Dock.Right);
            head.Children.Add(x);
            head.Children.Add(SectionTitle(name));
            card.Children.Add(head);
            var layers = v["layers"] as JsonArray ?? new JsonArray();
            card.Children.Add(HintSmall(L.F("Nella libreria: {0}", folder == "" ? L.T("Ecosistemi") : folder) + " · "
                                        + L.F("campione di {0} m", ((double?)v["size"] ?? 20).ToString("0"))));
            var benchPlot = PlotInScene();
            if (_ecoEditing != null && (string?)_ecoEditing["id"] == id && benchPlot != "" && (string?)_ecoEditing["plot"] == benchPlot && ro)
            {
                card.Children.Add(HintSmall(L.T("Aperto sul banco di prova, solo da guardare. Per cambiarlo, «Copia» (tasto destro sulla miniatura) e incollalo in I miei")));
                var exRo = ExitBenchButton();
                exRo.HorizontalAlignment = HorizontalAlignment.Left;
                exRo.Margin = new Thickness(0, 8, 0, 0);
                card.Children.Add(exRo);
                _props.Children.Add(Theme.Card(card, 16));
                return;
            }
            if (_ecoEditing != null && (string?)_ecoEditing["id"] == id && benchPlot != "" && (string?)_ecoEditing["plot"] == benchPlot)
            {
                card.Children.Add(HintSmall(L.T("Aperto sul banco di prova: clicca uno scatter per cambiarne i modelli o dipingere (Maiusc cancella), poi «Salva modifiche»")));
                AddBenchScatters(card, benchPlot);
                var sv = new WrapPanel { Margin = new Thickness(0, 8, 0, 0) };
                var keep = SmallButton(Icons.Save, L.T("Salva modifiche"), SaveEcoChanges);
                keep.ToolTip = L.T("Aggiorna l'ecosistema nella libreria (stesso nome e cartella) con gli scatter del banco di prova");
                sv.Children.Add(keep);
                var asNew = SmallButton(Icons.Save, L.T("Salva come nuovo"), SaveEcosystem);
                asNew.ToolTip = L.T("Un nuovo ecosistema con gli scatter del banco di prova: quello di partenza resta com'era");
                sv.Children.Add(asNew);
                sv.Children.Add(ExitBenchButton());
                card.Children.Add(sv);
                _props.Children.Add(Theme.Card(card, 16));
                return;
            }
            foreach (var l in layers.OfType<JsonObject>())
            {
                var row = new StackPanel { Margin = new Thickness(0, 6, 0, 0) };
                row.Children.Add(Theme.Label(L.F("{0} · {1} pezzi", (string?)l["name"] ?? "", ((int?)l["count"] ?? 0).ToString("N0")), 12.5, Theme.Text));
                var mods = (l["models"] as JsonArray ?? new JsonArray()).OfType<JsonObject>().ToList();
                var tot = mods.Sum(m => Math.Max(0, (double?)m["weight"] ?? 0));
                var text = string.Join(", ", mods.Select(m => ((string?)m["name"] ?? "")
                    + (tot > 0 && mods.Count > 1 ? $" {Math.Round(100 * Math.Max(0, (double?)m["weight"] ?? 0) / tot)}%" : "")
                    + (((bool?)m["missing"] ?? false) ? " (" + L.T("non in libreria") + ")" : "")));
                row.Children.Add(new Border { Margin = new Thickness(10, 0, 0, 0), Child = HintSmall(text) });
                card.Children.Add(row);
            }
            var btns = new WrapPanel { Margin = new Thickness(0, 8, 0, 0) };
            var put = SmallButton(Icons.Grass, L.T("Metti sull'oggetto selezionato"), async () => await PlaceOnSelected(id, name));
            put.ToolTip = L.T("Fa crescere l'ecosistema sull'oggetto selezionato nella vista (oppure trascina la miniatura su un oggetto)");
            btns.Children.Add(put);
            if (!ro)
            {
                var ed = SmallButton(Icons.Brush, L.T("Modifica sul banco di prova"), async () => await OpenEcoInPanel(id));
                ed.ToolTip = L.T("Rimette l'ecosistema sul banco di prova com'era salvato, uno scatter per strato: lo cambi con Scatter (Maiusc cancella) e poi «Salva modifiche»");
                btns.Children.Add(ed);
            }
            card.Children.Add(btns);
            if (ro)
                card.Children.Add(HintSmall(L.T("Ecosistema Simpler: per cambiarlo, «Copia» (tasto destro sulla miniatura) e incollalo in I miei")));
            _props.Children.Add(Theme.Card(card, 16));
        }

        // ---------------------------------------------------------------- library

        void RenderEcosystems()
        {
            if (_ecosystems.Count == 0 && !_ecoLoaded) { _ecoLoaded = true; _ = LoadEcosystems().ContinueWith(_ => Dispatcher.Invoke(() => { if (_libraryTab is "ecosystems" or "simplereco") RenderLibrary(); })); }
            var simpler = _libraryTab == "simplereco";
            var root = simpler ? SimplerEco : "";
            var ro = simpler && SimplerLocked;
            bool Mine(string f) => simpler ? Under(f, SimplerEco) : !Under(f, SimplerEco);
            var items = _ecosystems.OfType<JsonObject>().Where(x => Mine((string?)x["folder"] ?? "")).ToList();
            string Rel(string full) => full == root ? "" : root == "" ? full : full.Substring(root.Length + 1);
            string Full(string rel) => rel == "" ? root : root == "" ? rel : root + "/" + rel;
            var rootLabel = simpler ? L.T("Ecosistemi Simpler") : L.T("Ecosistemi");
            // first: a new one (the plot)
            var plus = new StackPanel { Width = 92 };
            plus.Children.Add(new Border { Width = 72, Height = 72, Margin = new Thickness(0, 2, 0, 6), HorizontalAlignment = HorizontalAlignment.Center,
                                          Child = Theme.Icon(Icons.Plus, Theme.Accent, 28, 1.6) });
            plus.Children.Add(Theme.TileText(new TextBlock { Text = L.T("Nuovo ecosistema"), FontSize = 11.5, TextAlignment = TextAlignment.Center, TextWrapping = TextWrapping.Wrap, Foreground = Theme.B(Theme.TextSoft) }));
            var nb = Theme.Button(plus, Theme.Kind.Normal, L.T("Crea un ecosistema sul banco di prova: un terreno di 20 m accanto alla scena dove dipingi e riempi aree con Scatter"));
            nb.Padding = new Thickness(2, 4, 2, 6); nb.Margin = new Thickness(4); nb.Height = 130; nb.VerticalContentAlignment = VerticalAlignment.Top;
            nb.Click += async (_, __) => await NewEcosystem();
            if (!ro) _libraryTiles.Children.Add(nb);
            var q = (_librarySearch?.Text ?? "").Trim().ToLowerInvariant();
            if (q != "")
            {
                // (searching: in every folder)
                RenderCrumbs(rootLabel, "", f => { _ecoFolder = Full(f); _librarySearch!.Text = ""; }, L.F("risultati per \"{0}\"", _librarySearch!.Text.Trim()), simpler ? root : null);
                foreach (var e in items)
                {
                    var nm = (string?)e["name"] ?? (string?)e["id"] ?? "";
                    if (nm.ToLowerInvariant().Contains(q)) _libraryTiles.Children.Add(EcoTile(e));
                }
                return;
            }
            // folders, as the 3D models: made, renamed, moved and deleted the same way
            var cur = _ecoFolder;
            if (!Mine(cur) || (cur != root && !_ecoFolders.Contains(cur))) _ecoFolder = cur = root;
            RenderCrumbs(rootLabel, Rel(cur), f => _ecoFolder = Full(f), null, simpler ? root : null);
            if (cur != root) _libraryTiles.Children.Add(UpTile(ParentFolder(cur), f => _ecoFolder = f, true));
            // (1.79, Luca: «perché new folder è in fondo a destra?») «Nuova cartella» first, with the tiles that add
            if (!ro) _libraryTiles.Children.Add(NewFolderTile("eco", cur));
            else if (cur == root && UpdateAllTile() is FrameworkElement upAll) _libraryTiles.Children.Add(upAll);
            foreach (var f in _ecoFolders.Where(f => ParentFolder(f) == cur && Mine(f)).OrderBy(f => f, StringComparer.CurrentCultureIgnoreCase))
            {
                var ff = f;
                var count = items.Count(x => InFolder((string?)x["folder"] ?? "", ff));
                var cloudCount = ro && ContentOn;       // (cloud) how many are already on this computer
                var here = cloudCount ? items.Count(x => InFolder((string?)x["folder"] ?? "", ff) && !((bool?)x["cloud"] ?? false)) : 0;
                if (here > count) { AppLog.Write($"folder counter: {here}/{count} in «{ff}» (ecosystems {items.Count}): limited"); here = count; }
                var upN = cloudCount ? items.Count(x => InFolder((string?)x["folder"] ?? "", ff) && ((bool?)x["update"] ?? false)) : 0;
                _libraryTiles.Children.Add(FolderTile(ff, count, () => { _ecoFolder = ff; RenderLibrary(); }, ro ? "simplereco" : "eco", here, cloudCount, upN));
            }
            foreach (var e in items.Where(x => ((string?)x["folder"] ?? "") == cur))
                _libraryTiles.Children.Add(EcoTile(e));
        }

        Button EcoTile(JsonObject e)
        {
            {
                var id = (string?)e["id"] ?? "";
                var name = (string?)e["name"] ?? id;
                var cloud = (bool?)e["cloud"] ?? false;             // (cloud) in the cloud, not here yet
                var inCat = (bool?)e["inCatalog"] ?? false;
                var upd = !cloud && ((bool?)e["update"] ?? false);      // here, with a newer version in the cloud
                var tile = new StackPanel { Width = 92 };
                var img = new Image { Source = LoadBase64((string?)e["thumb"]), Stretch = Stretch.UniformToFill, Width = 72, Height = 72 };
                img.Clip = new RectangleGeometry(new Rect(0, 0, 72, 72), 10, 10);
                var picture = new Grid { Width = 72, Height = 72, Margin = new Thickness(0, 2, 0, 6), HorizontalAlignment = HorizontalAlignment.Center };
                picture.Children.Add(new Border { Child = img, Background = Theme.B(Theme.Inset), CornerRadius = new CornerRadius(10) });
                AddCloudBadge(picture, 72, id, cloud, inCat, upd);
                if (cloud && img.Source == null && _content?.Find(id) is ContentAsset ca) CloudThumb(ca, img);
                tile.Children.Add(picture);
                tile.Children.Add(Theme.TileText(new TextBlock { Text = name, FontSize = 11.5, TextAlignment = TextAlignment.Center, TextWrapping = TextWrapping.Wrap, Foreground = Theme.B(cloud ? Theme.TextMuted : Theme.TextSoft) }));
                var models = string.Join(", ", (e["models"] as JsonArray ?? new JsonArray()).Select(m => (string?)m ?? ""));
                var btn = Theme.Button(tile, Theme.Kind.Normal,
                    name + "\n" + L.F("{0} strati · {1} pezzi sul campione di {2} m", (int?)e["layers"] ?? 0, (int?)e["pieces"] ?? 0, (double?)e["size"] ?? 20) + (models != "" ? "\n" + models : ""));
                btn.Padding = new Thickness(2, 4, 2, 6); btn.Margin = new Thickness(4); btn.Height = 130; btn.VerticalContentAlignment = VerticalAlignment.Top;
                btn.Tag = name;
                if (cloud) btn.ToolTip = name + "\n" + L.F("Nel cloud, non ancora sul computer: un clic lo scarica ({0}, con i modelli che usa)", MegaBytes((double?)e["cloudBytes"] ?? 0)) + (models != "" ? "\n" + models : "");
                if (_ecoEditing != null && (string?)_ecoEditing["id"] == id && PlotInScene() != "")
                {
                    // (1.79.0) the one open on the bench
                    btn.BorderBrush = Theme.B(Theme.Accent);
                    btn.BorderThickness = new Thickness(2);
                    btn.ToolTip = L.T("Aperto sul banco di prova") + "\n" + btn.ToolTip;
                }
                // (Luca: «facendo click sulla miniatura … si apra nel pannello degli ecosistemi in una modalità edit»)
                btn.Click += async (_, __) => await OpenEcoInPanel(id);
                var ro = ReadOnlyEco((string?)e["folder"] ?? "");
                MakeDraggable(btn, name, async (x, y) => await DropEcosystem(id, name, x, y),
                              onFolderDrop: async f => await MoveEco(id, f), icon: () => img.Source,
                              folderOk: f => !ro && !ReadOnlyEco(f) && f != ((string?)e["folder"] ?? ""));
                if (IsCut("eco", false, id)) btn.Opacity = 0.45;
                var cm = new ContextMenu();
                void Item(string text, Func<Task> act) { var i = new MenuItem { Header = text }; i.Click += async (_, __) => await act(); cm.Items.Add(i); }
                // (Luca: «diversi ecosistemi hanno la stessa matrice»: a copy to change, also of a Simpler one into I miei)
                Item(L.T("Copia"), async () => { await Task.Yield(); CopyEco(id, name); });
                if (ro && cloud) Item(L.T("Scarica sul computer"), async () => await DownloadCloud(id));
                else if (ro && inCat)
                {
                    if (upd) Item(L.T("Aggiorna (versione più nuova nel cloud)"), async () => await UpdateContent(new[] { id }));
                    cm.Items.Add(new Separator()); Item(L.T("Rimuovi dal computer (si può riscaricare)"), async () => await RemoveCloud(id));
                }
                if (ro) { btn.ContextMenu = cm; return Fav(btn, "eco", id, name, e); }   // (Simpler, locked: only used and copied)   // (Simpler, locked: only used and copied)
                Item(L.T("Rinomina"), async () =>
                {
                    var nn = InputDialog.Ask(this, L.T("Rinomina"), L.T("Nome dell'ecosistema"), name);
                    if (string.IsNullOrWhiteSpace(nn)) return;
                    await Run(async api => { await api.Post("ecosystems/rename", new { id, name = nn }); });
                    await LoadEcosystems(); RenderLibrary();
                });
                Item(L.T("Taglia"), async () => { await Task.Yield(); CutLibrary("eco", false, id, name); });
                var mv = new MenuItem { Header = L.T("Sposta in") };
                void Target(string t, string label)
                {
                    var i = new MenuItem { Header = label, IsEnabled = t != ((string?)e["folder"] ?? "") };
                    i.Click += async (_, __) => await MoveEco(id, t);
                    mv.Items.Add(i);
                }
                Target("", L.T("Ecosistemi (cartella principale)"));
                foreach (var f in _ecoFolders.Where(f => !ReadOnlyEco(f)).OrderBy(f => f, StringComparer.CurrentCultureIgnoreCase))
                    Target(f, new string(' ', 4 * f.Count(c => c == '/')) + FolderName(f));
                cm.Items.Add(mv);
                Item(L.T("Rifai la miniatura dal banco di prova"), async () =>
                    {
                        var plotId = PlotInScene();
                        if (plotId == "") { Status(L.T("Prima crea il banco di prova (o seleziona le distribuzioni da salvare)"), true); return; }
                        JsonObject? r = null;
                        await Run(async api => { r = await api.Post("ecosystems/thumb", new { id, plot = plotId }); });
                        if (((int?)r?["thumbJob"] ?? 0) is int job && job > 0)
                        {
                            Status(L.T("Miniatura in preparazione con il path tracer…"));
                            _ = PollEcoThumb(job);
                        }
                    });
                cm.Items.Add(new Separator());
                Item(L.T("Elimina"), async () =>
                {
                    if (Msg.Show(this, L.F("Eliminare l'ecosistema \"{0}\"? Quelli già messi nelle scene restano.", name), "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
                    await Run(async api => { await api.Post("ecosystems/delete", new { id }); });
                    await LoadEcosystems(); RenderLibrary();
                });
                btn.ContextMenu = cm;
                return Fav(btn, "eco", id, name, e);
            }
        }
        bool _ecoLoaded;

        async Task DropEcosystem(string id, string name, double x, double y)
        {
            var at = await AskViewPoint(x, y);
            var oid = (string?)at?["objectId"] ?? "";
            // (a model of the library is picked as a whole - its root is a group: the ecosystem grows on the piece
            // under the mouse)
            var mid = (string?)at?["meshId"] ?? "";
            if (mid != "" && _scene.ById.TryGetValue(mid, out var mo) && mo.IsMesh) oid = mid;
            if (oid == "" || !((bool?)at?["hit"] ?? false) || !_scene.ById.TryGetValue(oid, out var o)) { Status(L.T("Lascia l'ecosistema sopra un oggetto"), true); return; }
            // the material under the mouse: on an object with several (a lawn and a path), only that one grows
            var mat = (string?)at?["material"] ?? "";
            int? slot = o.Materials.Count > 1 && mat != "" && o.Materials.IndexOf(mat) is int k && k >= 0 ? k : null;
            await PlaceEcosystem(id, name, oid, slot);
        }

        async Task PlaceEcosystem(string id, string name, string target, int? slot)
        {
            // (only where the camera looks when «Calcola solo l'area inquadrata» has «Ecosistemi» on: the engine decides and
            // counts the pieces that way - estimate answers camOnly)
            JsonObject? est = null;
            await Run(async api => { est = await api.Post("ecosystems/estimate", new { id, target, slot, density = 1.0 }); });
            if (est == null) return;
            var n = (int?)est["pieces"] ?? 0;
            var mx = (int?)est["max"] ?? 0;
            var camOnly = (bool?)est["camOnly"] ?? false;
            double fall = 0;
            if (!camOnly && ((bool?)est["warn"] ?? false))
            {
                // a big surface with the ecosystems whole: «only where the camera looks» offered, with how many pieces
                JsonObject? ce = null;
                using (BeginBusy()) await Run(async api => { ce = await api.Post("ecosystems/estimate", new { id, target, slot, density = 1.0, camOnly = true }); });
                var nc = (int?)ce?["pieces"] ?? 0;
                var tooMany = (bool?)est["tooMany"] ?? false;
                if (ce != null && nc > 0)
                {
                    var res = Msg.Show(this, L.F("Su tutta la superficie sarebbero circa {0} pezzi.\n\nSolo dove guarda la camera ne bastano circa {1}: accendo «Ecosistemi» in «Calcola solo l'area inquadrata» (in basso a sinistra)? Vale per tutti gli ecosistemi della scena.", n.ToString("N0"), nc.ToString("N0")),
                                       "Simpler", tooMany ? MessageBoxButton.YesNo : MessageBoxButton.YesNoCancel, MessageBoxImage.Question);
                    if (res == MessageBoxResult.Cancel) return;
                    if (res == MessageBoxResult.Yes)
                    {
                        await SetCamView(new { eco = true });
                        if (!((bool?)_camView?["eco"] ?? false)) return;
                        await Run(async api => { est = await api.Post("ecosystems/estimate", new { id, target, slot, density = 1.0 }); });
                        if (est == null) return;
                        n = (int?)est["pieces"] ?? 0;
                        camOnly = (bool?)est["camOnly"] ?? false;
                    }
                    else if (tooMany)
                    {
                        Status(L.F("Troppi pezzi: circa {0} (il massimo è {1}). Abbassa la densità o usa una superficie più piccola", n.ToString("N0"), mx.ToString("N0")), true);
                        return;
                    }
                }
                else if (tooMany)
                {
                    Status(L.F("Troppi pezzi: circa {0} (il massimo è {1}). Abbassa la densità o usa una superficie più piccola", n.ToString("N0"), mx.ToString("N0")), true);
                    return;
                }
            }
            if (camOnly && ((bool?)est!["tooMany"] ?? false))
            {
                // even the frame is too much (a long view over a big ground): thinner with the distance
                JsonObject? cf = null;
                using (BeginBusy()) await Run(async api => { cf = await api.Post("ecosystems/estimate", new { id, target, slot, density = 1.0, camFalloff = 0.7 }); });
                var nf = (int?)cf?["pieces"] ?? 0;
                if (cf == null || nf <= 0 || ((bool?)cf["tooMany"] ?? true))
                {
                    Status(L.F("Troppi pezzi anche solo nell'inquadratura: circa {0} (il massimo è {1}). Abbassa la densità o avvicina la camera", n.ToString("N0"), mx.ToString("N0")), true);
                    return;
                }
                n = nf; fall = 0.7;
                Status(L.T("Anche l'inquadratura da sola sarebbe troppo: in lontananza i pezzi saranno più radi («Più rado in lontananza» al 70%, nel pannello dell'ecosistema)."));
            }
            else if ((bool?)est!["warn"] ?? false)
            {
                var memGB = (double?)est["memGB"] ?? 0; var freeGB = (double?)est["freeGB"] ?? 0;
                var ask = freeGB > 0
                    ? L.F("L'ecosistema metterà circa {0} pezzi su questa superficie, circa {1} GB di memoria (liberi ora: {2} GB): ci vorrà un po' e la scena peserà di più.", n.ToString("N0"), memGB.ToString("0.0"), freeGB.ToString("0.0"))
                    : L.F("L'ecosistema metterà circa {0} pezzi su questa superficie: ci vorrà un po' e la scena peserà di più.", n.ToString("N0"));
                if (Msg.Show(this, ask + "\n\n" + L.T("Continuo?"), "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
            }
            using var busy = BeginBusy();
            ShowTask(L.F("Ecosistema «{0}»: circa {1} pezzi…", name, n.ToString("N0")));
            JsonObject? r = null;
            try { await Run(async api => { r = await api.Post("ecosystems/apply", new { id, target, slot, camFalloff = fall }); }); }
            finally { HideTask(); }
            if (r == null) return;
            await RefreshScene();
            var g = (string?)r["group"] ?? "";
            if (g != "") SelectFromViewport(new[] { g }, g);
            await ShowRightPanel("ecosystem");
            Status(L.F("Ecosistema «{0}»: {1} pezzi", name, ((int?)r["pieces"] ?? 0).ToString("N0")));
            await LoadCamView();
        }

        async Task NewEcoPlot(double size, bool clear = false)
        {
            JsonObject? r = null;
            await Run(async api => { r = await api.Post("ecosystems/plot", new { size, clear }); });
            if (r == null) return;
            await RefreshScene();
            var id = (string?)r["id"] ?? "";
            // (1.76.31, Luca) the bench alone: the rest hidden by the engine (shown again from the scene panel), the
            // bench seen three quarters from above, and a blue note in the view that says so
            _benchHidden = (r["hidden"] as JsonArray)?.Select(x => (string?)x ?? "").Where(x => x != "").ToList() ?? new List<string>();
            _benchId = id;
            if (id != "") { SelectFromViewport(new[] { id }, id); SendToWeb(new { type = "frameBench", id = ViewerId(id) }); }
            BenchNote();
            SetTool("paint");
            if ((bool?)r["existing"] ?? false)
                Status((bool?)r["resized"] ?? false
                    ? L.F("Il banco di prova è uno per scena: ora misura {0} m, con i suoi scatter", size.ToString("0"))
                    : L.T("Il banco di prova è uno per scena: eccolo"));
            else
                Status(L.T("Banco di prova pronto: scegli i modelli e dipingi o riempi un'area su di lui, poi Ecosistemi ▸ Salva ecosistema"));
        }

        List<string> _benchHidden = new();
        string _benchId = "";

        /// <summary>The blue note of the bench in the view: while the bench is there and what it hid is still hidden
        /// (one shown again from the scene panel, or the bench gone: the note goes).</summary>
        void BenchNote()
        {
            bool on = _benchId != "" && _benchHidden.Count > 0 && _scene.ById.ContainsKey(_benchId)
                      && _benchHidden.All(h => !_scene.ById.TryGetValue(h, out var o) || !o.Visible);
            if (!on) { _benchId = ""; _benchHidden.Clear(); }
            if (_webReady)
                SendToWeb(new { type = "benchNote", show = on, title = L.T("Banco per ecosistema attivato"),
                                text = L.T("Tutti gli altri elementi sono nascosti finché sei sul banco di prova"),
                                exit = L.T("Esci dal banco di prova") });
        }

        Task<bool> SaveEcosystem() => SaveEcosystemOf(null);

        async Task<bool> SaveEcosystemOf(IEnumerable<string>? only, string defaultName = "")
        {
            var plot = PlotInScene();
            // (1.79.0, Luca: one of the two scatters of the bench was not saved) a scatter of the bench selected is not a
            // choice: the whole bench is saved; only distributions of the scene are saved on their own
            var dists = (only ?? _selection).Where(s => _scene.ById.TryGetValue(s, out var o) && (o.Paint || o.Eco == "group")
                                              && !(plot != "" && _scene.Ancestors(o).Any(a => a.Id == plot))).ToArray();
            if (plot == "" && dists.Length == 0) { Status(L.T("Prima crea il banco di prova (o seleziona le distribuzioni da salvare)"), true); return false; }
            // (1.79.0, Luca: «salva in libreria mi mostra tutta la libreria tranne gli ecosistemi») name and folder among the
            // folders of the ecosystems (the locked Simpler ones left out)
            var startFolder = ReadOnlyEco(_ecoFolder) ? "" : _ecoFolder;
            var ans = SaveToLibraryDialog.Ask(this, L.T("Salva nella libreria degli ecosistemi"), L.T("Nome dell'ecosistema"),
                                              defaultName != "" ? defaultName : L.F("Ecosistema {0}", _ecosystems.Count + 1),
                                              startFolder, _ecoFolders.Where(f => !ReadOnlyEco(f)), L.T("Ecosistemi (cartella principale)"));
            if (ans == null) return false;
            var name = ans.Value.name;
            var folder = ReadOnlyEco(ans.Value.folder) ? "" : ans.Value.folder;
            if (Painting) SetTool("move");
            using var busy = BeginBusy();
            ShowTask(L.T("Salvataggio dell'ecosistema e miniatura…"));
            var thumb = await CaptureViewSnapshot(256, 256, 0.88);
            JsonObject? r = null;
            try { await Run(async api => { r = await api.Post("ecosystems/save", new { name, plot = dists.Length > 0 ? "" : plot, ids = dists, thumb, folder }); }); }
            finally { HideTask(); }
            if (r == null) return false;
            if (dists.Length == 0) _ecoViewId = (string?)r["id"] ?? "";       // (the new one is now the one open on the bench)
            await LoadEcosystems();
            _ecoFolder = folder;                 // (the library shows where it went)
            ShowLibraryTab(Under(folder, SimplerEco) ? "simplereco" : "ecosystems");
            Status(L.F("Ecosistema salvato: {0} ({1} pezzi in {2} strati)", name, (int?)r["pieces"] ?? 0, (int?)r["layers"] ?? 0));
            if (((int?)r["thumbJob"] ?? 0) is int job && job > 0) _ = PollEcoThumb(job);
            await LoadEcoLibraryView();          // («Salva come nuovo»: the new one is the one open on the bench)
            if (_libraryTab is "ecosystems" or "simplereco") RenderLibrary();      // (its tile marked as the open one)
            RenderProps();
            return true;
        }

        /// <summary>The path traced thumbnail of a saved ecosystem (preview process): the tile gets it when ready.</summary>
        async Task PollEcoThumb(int job)
        {
            for (int i = 0; i < 600; i++)
            {
                await Task.Delay(1000);
                JsonObject? st = null;
                try { st = await _api!.Get($"material/preview/status?id={job}"); } catch { }
                var state = (string?)st?["state"] ?? "";
                if (state == "running") continue;
                if (state == "done")
                {
                    await LoadEcosystems();
                    if (_libraryTab is "ecosystems" or "simplereco") RenderLibrary();
                }
                return;
            }
        }

        /// <summary>«Ricalcola dalla vista» (and «Solo dove guarda la camera» switched on): the pieces counted first for
        /// the view of now (ecosystems/count, nothing changes); many: a question, as when it is placed; too many for the
        /// memory: thinner with the distance offered, or nothing done.</summary>
        async Task RecalcEco(JsonObject change)
        {
            var g = (string?)_ecoInfo?["group"] ?? "";
            if (g == "") return;
            JsonObject Ask(JsonObject extra)
            {
                var q = new JsonObject { ["group"] = g };
                foreach (var kv in change) q[kv.Key] = kv.Value?.DeepClone();
                foreach (var kv in extra) q[kv.Key] = kv.Value?.DeepClone();
                return q;
            }
            // (not done - a no, an error: the panel again, so «Solo dove guarda la camera» shows as it is)
            var ok = false;
            try
            {
                JsonObject? c = null;
                using (BeginBusy()) await Run(async api => { c = await api.Post("ecosystems/count", Ask(new JsonObject())); });
                if (c == null) return;
                var n = (int?)c["pieces"] ?? 0;
                var mx = (int?)c["max"] ?? 0;
                if ((bool?)c["tooMany"] ?? false)
                {
                    var fall = (double?)_ecoInfo?["camFalloff"] ?? 0;
                    JsonObject? cf = null;
                    if (fall < 0.7)
                        using (BeginBusy()) await Run(async api => { cf = await api.Post("ecosystems/count", Ask(new JsonObject { ["camFalloff"] = 0.7 })); });
                    var nf = (int?)cf?["pieces"] ?? 0;
                    if (cf == null || nf <= 0 || ((bool?)cf["tooMany"] ?? true))
                    {
                        Status(L.F("Troppi pezzi anche solo nell'inquadratura: circa {0} (il massimo è {1}). Abbassa la densità o avvicina la camera", n.ToString("N0"), mx.ToString("N0")), true);
                        return;
                    }
                    if (Msg.Show(this, L.F("Con la vista di adesso sarebbero circa {0} pezzi, troppi per la memoria di questo PC (al massimo {1}).\n\nCon i pezzi più radi in lontananza («Più rado in lontananza» al 70%) ne bastano circa {2}. Procedo così?", n.ToString("N0"), mx.ToString("N0"), nf.ToString("N0")),
                                 "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
                    change["camFalloff"] = 0.7;
                }
                else if ((bool?)c["warn"] ?? false)
                {
                    var memGB = (double?)c["memGB"] ?? 0; var freeGB = (double?)c["freeGB"] ?? 0;
                    var ask = freeGB > 0
                        ? L.F("Con la vista di adesso l'ecosistema avrà circa {0} pezzi, circa {1} GB di memoria (liberi ora: {2} GB): ci vorrà un po' e la scena peserà di più. Continuo?", n.ToString("N0"), memGB.ToString("0.0"), freeGB.ToString("0.0"))
                        : L.F("Con la vista di adesso l'ecosistema avrà circa {0} pezzi: ci vorrà un po' e la scena peserà di più. Continuo?", n.ToString("N0"));
                    if (Msg.Show(this, ask, "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
                }
                await ChangeEco(change);
                ok = true;
            }
            finally { if (!ok) RenderProps(); }
        }

        async Task ChangeEco(JsonObject change)
        {
            var g = (string?)_ecoInfo?["group"] ?? "";
            if (g == "") return;
            change["group"] = g;
            using var busy = BeginBusy();
            JsonObject? r = null;
            await Run(async api => { r = await api.Post("ecosystems/apply", change); });
            if (r == null) { RenderProps(); return; }      // (not done: the panel again, its switches as they really are)
            await RefreshScene();
            await LoadEcoInfo();
            RenderProps();
            await LoadCamView();
        }

        // ---------------------------------------------------------------- layers of this project

        /// <summary>The layer a library model clicked now joins («Aggiungi un modello» of «Strati di questo ecosistema»), -1: none.</summary>
        int _ecoAddLayer = -1;

        /// <summary>(Luca: «A va bene ma solo se lo vincoliamo a quella particolare istanza di ecosistema nel progetto, senza
        /// toccare l'originale in libreria») the layers of the ecosystem placed here: its models (presence, scale, turn,
        /// season, taken away, added from the library), a layer off, its density - changed only in this project (engine:
        /// ecosystems._effective); back as in the library, or saved in the library as a new one.</summary>
        void EcoLayersCard(JsonObject info)
        {
            var layers = info["layers"] as JsonArray;
            if (layers == null || layers.Count == 0) return;
            var own = (bool?)info["own"] ?? false;
            var card = new StackPanel();
            card.Children.Add(SectionTitle(L.T("Strati di questo ecosistema – solo in questo progetto")));
            card.Children.Add(HintSmall(own
                ? L.T("Modificato in questo progetto: la libreria resta com'era")
                : L.T("Come in libreria. Quello che cambi qui vale solo per questo ecosistema in questo progetto: la libreria non cambia")));
            if (own)
            {
                var row = new WrapPanel { Margin = new Thickness(0, 4, 0, 6) };
                var back = SmallButton(Icons.Refresh, L.T("Torna come in libreria"), async () => await ChangeEco(new JsonObject { ["own"] = null }));
                back.ToolTip = L.T("Toglie le modifiche fatte qui: gli strati tornano come nell'ecosistema della libreria");
                row.Children.Add(back);
                var asNew = SmallButton(Icons.Save, L.T("Salva in libreria come nuovo"), SaveOwnEcosystem);
                asNew.ToolTip = L.T("Un nuovo ecosistema in libreria con gli strati come sono qui: quello di partenza resta com'era");
                row.Children.Add(asNew);
                card.Children.Add(row);
            }
            // the layers as they are now, to change one thing and send them all (ecosystems/apply «own»)
            JsonObject State()
            {
                var arr = new JsonArray();
                foreach (var l in layers.OfType<JsonObject>())
                    arr.Add(new JsonObject { ["off"] = (bool?)l["off"] ?? false, ["density"] = (double?)l["density"] ?? 1.0,
                                             ["palette"] = (l["palette"] as JsonArray)?.DeepClone() ?? new JsonArray() });
                return new JsonObject { ["layers"] = arr };
            }
            async Task Change(Action<JsonArray> edit)
            {
                var st = State();
                edit((JsonArray)st["layers"]!);
                _ecoAddLayer = -1;
                await ChangeEco(new JsonObject { ["own"] = st });
            }
            for (int li = 0; li < layers.Count; li++)
            {
                if (layers[li] is not JsonObject l) continue;
                var k = li;
                var off = (bool?)l["off"] ?? false;
                var head = new DockPanel { Margin = new Thickness(0, 10, 0, 2) };
                var eye = IconButton(off ? Icons.EyeOff : Icons.Eye, off ? L.T("Accendi lo strato") : L.T("Spegni lo strato: i suoi pezzi spariscono, gli altri strati restano come sono"),
                                     async () => await Change(ls => ls[k]!["off"] = !off));
                DockPanel.SetDock(eye, Dock.Left);
                head.Children.Add(eye);
                var title = Theme.Label(((string?)l["name"] ?? "") + " · " + L.F("{0} pezzi", ((int?)l["pieces"] ?? 0).ToString("N0")), 13, off ? Theme.TextFaint : Theme.TextSoft);
                title.VerticalAlignment = VerticalAlignment.Center;
                title.TextTrimming = TextTrimming.CharacterEllipsis;
                title.Margin = new Thickness(6, 0, 0, 0);
                head.Children.Add(title);
                card.Children.Add(head);
                if (off) continue;
                var dens = new ValueSlider(L.T("Densità dello strato"), ((double?)l["density"] ?? 1) * 100, 0, 100, false, "0", "%", null,
                    L.T("Quanti pezzi di questo strato restano: 100% = come l'hai composto. Gli altri strati non cambiano"));
                dens.Committed += async v => await Change(ls => ls[k]!["density"] = Math.Round(v, 1) / 100.0);
                card.Children.Add(dens);
                var pal = l["palette"] as JsonArray ?? new JsonArray();
                var total = pal.OfType<JsonObject>().Sum(p => (double?)p["weight"] ?? 100);
                for (int pi = 0; pi < pal.Count; pi++)
                {
                    if (pal[pi] is not JsonObject p) continue;
                    var j = pi;
                    var mid = (string?)p["model"] ?? "";
                    var entry = _models.OfType<JsonObject>().FirstOrDefault(m => (string?)m["id"] == mid);
                    var name = (string?)entry?["name"] ?? (string?)p["name"] ?? mid;
                    var row = new Grid { Margin = new Thickness(0, 4, 0, 4), Tag = "content" };
                    row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(46) });
                    row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                    row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(32) });
                    var thumb = (string?)entry?["thumb"] ?? "";
                    var pic = new Border { Width = 40, Height = 40, CornerRadius = new CornerRadius(6), Background = Theme.B(Theme.Inset), VerticalAlignment = VerticalAlignment.Top };
                    if (thumb != "" && File.Exists(thumb)) pic.Background = new ImageBrush(LoadBitmapFresh(thumb)) { Stretch = Stretch.UniformToFill };
                    row.Children.Add(pic);
                    var col = new StackPanel { Margin = new Thickness(8, 0, 4, 0) };
                    var nm = Theme.Label(entry == null ? name + " " + L.T("(non più in libreria)") : name, 12, entry == null ? Theme.TextFaint : Theme.TextSoft);
                    nm.TextTrimming = TextTrimming.CharacterEllipsis;
                    col.Children.Add(nm);
                    var w = (double?)p["weight"] ?? 100;
                    var pres = new ValueSlider(L.T("Presenza"), w, 0, 100, false, "0", "%", null,
                        L.F("Quanto spesso compare rispetto agli altri modelli dello strato (ora circa {0}% dei pezzi). Cambiando le presenze cambia modello solo la parte di pezzi che serve", Math.Round(total > 0 ? w / total * 100 : 0)));
                    pres.Compact();
                    pres.Margin = new Thickness(0, 2, 0, 0);
                    pres.Committed += async v => await Change(ls => ls[k]!["palette"]![j]!["weight"] = Math.Round(v, 1));
                    col.Children.Add(pres);
                    var adv = Advanced(col, "ecoItem:" + k + ":" + mid);
                    void Item(string label, string key, double v, double min, double max, bool log, string fmt, string unit, double div, string tip)
                    {
                        var vs = new ValueSlider(label, v * div, min, max, log, fmt, unit, null, tip).Compact(stacked: true);
                        vs.Committed += async x => await Change(ls => ls[k]!["palette"]![j]![key] = Math.Round(x, 2) / div);
                        adv.Body.Children.Add(vs);
                    }
                    var sk = (double?)p["scale"] ?? 1; var rot = (double?)p["rot"] ?? 0;
                    var sea = (double?)p["season"] ?? 0; var seaR = (double?)p["seasonRand"] ?? 0;
                    Item(L.T("Scala"), "scale", sk, 10, 1000, true, "0", "%", 100, L.T("Grandezza di questo modello nell'ecosistema: 100% = come l'hai composto"));
                    Item(L.T("Rotazione"), "rot", rot, -180, 180, false, "0", "°", 1, L.T("Gira tutti i pezzi di questo modello attorno al loro asse verticale"));
                    if ((entry?["veg"]?["leaves"] as JsonArray)?.Count > 0 || (entry != null && IsVegFolder((string?)entry["folder"] ?? "")))
                    {
                        Item(L.T("Stagione"), "season", sea, 0, 100, false, "0", "%", 100,
                             L.T("La stagione delle foglie di questo modello: 0% estate, 50% autunno, 100% inverno (foglie cadute). Con Stagione e Stagione casuale a 0% resta quella del suo materiale"));
                        Item(L.T("Stagione casuale"), "seasonRand", seaR, 0, 100, false, "0", "%", 100,
                             L.T("Ogni pianta prende una stagione un po' diversa, fino a questa percentuale in più o in meno: un mix di colori delle foglie"));
                    }
                    adv.Done(Math.Abs(sk - 1) > 1e-6 || Math.Abs(rot) > 1e-6 || sea > 0 || seaR > 0);
                    Grid.SetColumn(col, 1);
                    row.Children.Add(col);
                    var rm = IconButton(Icons.Trash, L.T("Togli dallo strato: i suoi pezzi spariscono"),
                                        async () => await Change(ls => ((JsonArray)ls[k]!["palette"]!).RemoveAt(j)));
                    rm.VerticalAlignment = VerticalAlignment.Top;
                    Grid.SetColumn(rm, 2);
                    row.Children.Add(rm);
                    card.Children.Add(row);
                }
                var adding = _ecoAddLayer == k;
                var add = SmallButton(Icons.Plus, adding ? L.T("Clicca un modello nella libreria in basso…") : L.T("Aggiungi un modello"), async () =>
                {
                    await Task.Yield();
                    _ecoAddLayer = _ecoAddLayer == k ? -1 : k;
                    if (_ecoAddLayer >= 0) Status(L.T("Clicca un modello nella libreria in basso: si aggiunge a questo strato e prende una parte dei suoi pezzi"));
                    RenderProps();
                });
                add.ToolTip = L.T("Poi clicca un modello nella libreria in basso: entra nello strato e prende una parte dei suoi pezzi (secondo la Presenza)");
                add.HorizontalAlignment = HorizontalAlignment.Left;
                card.Children.Add(add);
            }
            _props.Children.Add(Theme.Card(card, 16));

            // a library model clicked while «Aggiungi un modello» is armed
            _ecoAddModel = async (id, name) =>
            {
                var k = _ecoAddLayer;
                _ecoAddLayer = -1;
                if (k < 0 || k >= layers.Count) return;
                var pal = layers[k]?["palette"] as JsonArray;
                if (pal != null && pal.OfType<JsonObject>().Any(p => (string?)p["model"] == id)) { Status(L.F("{0} è già nello strato", name)); RenderProps(); return; }
                await Change(ls => ((JsonArray)ls[k]!["palette"]!).Add(new JsonObject { ["model"] = id, ["name"] = name, ["weight"] = 100.0 }));
            };
        }

        Func<string, string, Task>? _ecoAddModel;

        /// <summary>«Salva in libreria come nuovo»: the ecosystem placed here, with its layers as changed in this project.</summary>
        async Task SaveOwnEcosystem()
        {
            var g = (string?)_ecoInfo?["group"] ?? "";
            if (g == "") return;
            var startFolder = ReadOnlyEco(_ecoFolder) ? "" : _ecoFolder;
            var ans = SaveToLibraryDialog.Ask(this, L.T("Salva nella libreria degli ecosistemi"), L.T("Nome dell'ecosistema"),
                                              L.F("{0} (modificato)", (string?)_ecoInfo?["name"] ?? ""), startFolder,
                                              _ecoFolders.Where(f => !ReadOnlyEco(f)), L.T("Ecosistemi (cartella principale)"));
            if (ans == null) return;
            var folder = ReadOnlyEco(ans.Value.folder) ? "" : ans.Value.folder;
            JsonObject? r = null;
            using (BeginBusy()) await Run(async api => { r = await api.Post("ecosystems/saveown", new { group = g, name = ans.Value.name, folder }); });
            if (r == null) return;
            await LoadEcosystems();
            _ecoFolder = folder;
            ShowLibraryTab(Under(folder, SimplerEco) ? "simplereco" : "ecosystems");
            Status(L.F("Ecosistema salvato: {0} ({1} pezzi in {2} strati)", ans.Value.name, (int?)r["pieces"] ?? 0, (int?)r["layers"] ?? 0));
        }

        // ---------------------------------------------------------------- panel

        void RenderEcosystemPanel()
        {
            _ecoAddModel = null;             // (set again by the layers card when an ecosystem of the scene is shown)
            var sp = new StackPanel();
            var top = new DockPanel();
            var close = Theme.Button(L.T("Chiudi"), Theme.Kind.Ghost, L.T("Torna alle proprietà dell'oggetto"));
            close.Click += async (_, __) => await ShowRightPanel("");
            DockPanel.SetDock(close, Dock.Right);
            top.Children.Add(close);
            top.Children.Add(Theme.Caption(L.T("Ecosistemi")));
            sp.Children.Add(top);
            _props.Children.Add(Theme.Card(sp, 16));
            RenderEcoLibraryCard();

            var info = _ecoInfo;
            if (info != null && (string?)info["group"] is string gid && gid != "" && EcoGroupOfSelection() == gid)
            {
                var card = new StackPanel();
                var et = SectionTitle((string?)info["name"] ?? L.T("Ecosistema"));
                et.Uid = "ecosystem";        // (1.76.35: its favourite commands are the same for every ecosystem, Luca)
                et.DataContext = (Icons.Grass, Theme.AxisY);    // (the title is the ecosystem's name: its icon given here)
                card.Children.Add(et);
                var on = (string?)info["targetName"] ?? "";
                var mat = (string?)info["material"] ?? "";
                card.Children.Add(HintSmall(L.F("Su {0}", on) + (mat != "" && ((bool?)info["onlyMaterial"] ?? true) ? " · " + L.F("solo il materiale «{0}»", mat) : "")
                                           + " · " + L.F("{0} pezzi", ((int?)info["pieces"] ?? 0).ToString("N0"))));
                var dens = new ValueSlider(L.T("Densità"), ((double?)info["density"] ?? 1) * 100, 5, 100, false, "0", "%", null,
                    L.T("Quanti pezzi del campione restano: 100% = come l'hai composto"));
                dens.Committed += async v => await ChangeEco(new JsonObject { ["density"] = Math.Round(v, 1) / 100.0 });
                card.Children.Add(dens);
                var scl = new ValueSlider(L.T("Scala"), ((double?)info["scale"] ?? 1) * 100, 25, 400, true, "0", "%", null, L.T("Più grandi o più piccoli tutti insieme"));
                scl.Committed += async v => await ChangeEco(new JsonObject { ["scale"] = Math.Round(v, 1) / 100.0 });
                card.Children.Add(scl);
                // (1.76.2) past the edge of the surface: no sharp line where a lawn meets the gravel (Luca)
                var spill = (double?)info["spill"] ?? 0.0;
                var spillD = (double?)info["spillDensity"] ?? 0.5;
                var spS = new ValueSlider(L.T("Oltre il bordo"), spill, 0, 20, false, "0.0", "m", null,
                    L.T("Quanto i pezzi possono uscire dalla superficie su cui crescono, sulle superfici accanto (altre zone del terreno, il suolo): la fascia è irregolare e si dirada verso l'esterno. 0 = si fermano al bordo"));
                spS.Committed += async v => await ChangeEco(new JsonObject { ["spill"] = Math.Round(v, 2) });
                card.Children.Add(spS);
                if (spill > 0)
                {
                    var spD = new ValueSlider(L.T("Densità oltre il bordo"), spillD * 100, 0, 100, false, "0", "%", null,
                        L.T("Quanto sono fitti appena fuori dal bordo; più in là si diradano fino a niente, a ciuffi"));
                    spD.Committed += async v => await ChangeEco(new JsonObject { ["spillDensity"] = Math.Round(v, 1) / 100.0 });
                    card.Children.Add(spD);
                }
                var libSpill = info["libSpill"] is JsonValue ls && ls.TryGetValue<double>(out var lsv) ? lsv : (double?)null;
                var libSpillD = (double?)info["libSpillDensity"] ?? 0.5;
                if (libSpill != null && (Math.Abs(libSpill.Value - spill) > 1e-3 || (spill > 0 && Math.Abs(libSpillD - spillD) > 1e-3)))
                {
                    var keep = SmallButton(Icons.Save, L.T("Salva questi valori nell'ecosistema"), async () =>
                    {
                        await Run(async api => { await api.Post("ecosystems/defaults", new { id = (string?)info["id"], spill, spillDensity = spillD }); });
                        await LoadEcoInfo();
                        RenderProps();
                    });
                    keep.HorizontalAlignment = HorizontalAlignment.Left;
                    keep.ToolTip = L.T("Nella libreria: ogni volta che lo metti, l'ecosistema esce dal bordo così");
                    card.Children.Add(keep);
                }
                var again = SmallButton(Icons.Refresh, L.T("Altra disposizione"), async () => await ChangeEco(new JsonObject { ["seed"] = ((int?)info["seed"] ?? 1) + 1 }));
                again.HorizontalAlignment = HorizontalAlignment.Left;
                again.Margin = new Thickness(0, 4, 0, 8);
                card.Children.Add(again);
                // only where the camera looks (as Vue did): decided by «Calcola solo l'area inquadrata» (bottom left) and by
                // «Sempre intero» below
                var camOn = (bool?)info["camOnly"] ?? false;
                if (camOn)
                {
                    card.Children.Add(HintSmall(L.T("Solo dove guarda la camera («Calcola solo l'area inquadrata», in basso a sinistra): spostando la camera i bordi restano vuoti finché non ricalcoli")));
                    var re = SmallButton(Icons.Refresh, L.T("Ricalcola dalla vista"), async () => await RecalcEco(new JsonObject { ["camRefresh"] = true }));
                    re.HorizontalAlignment = HorizontalAlignment.Left;
                    re.Margin = new Thickness(0, 0, 0, 4);
                    re.ToolTip = L.T("L'ecosistema è tagliato sull'inquadratura di quando l'hai messo: dopo aver spostato la camera, questo lo rifà per la vista di adesso (dove le due viste coincidono, i pezzi restano gli stessi)");
                    card.Children.Add(re);
                    // the two that decide how many pieces a view needs: in sight, not in the Avanzate
                    var occ = new Toggle(L.T("Niente pezzi dietro i modelli"), (bool?)info["camOcclude"] ?? true,
                        L.T("Dove un oggetto già nella scena (alberi, edifici, muri, auto, rocce) nasconde la superficie, lì non mette pezzi; dove la superficie si vede, anche fra un albero e l'altro, sì. Contano gli oggetti alti almeno 1,5 m; vetri, acqua e foglie trasparenti non nascondono niente"));
                    occ.Toggled += async v => await ChangeEco(new JsonObject { ["camOcclude"] = v });
                    occ.Margin = new Thickness(0, 4, 0, 4);
                    card.Children.Add(occ);
                    var fo = new ValueSlider(L.T("Più rado in lontananza"), ((double?)info["camFalloff"] ?? 0.0) * 100, 0, 100, false, "0", "%", null,
                        L.T("Lontano dalla camera i pezzi si diradano, dove l'occhio non li distingue, e quelli che restano diventano un po' più grandi: la superficie resta coperta con meno pezzi. Comincia a 25 m dalla camera, o a un quarto della distanza dal punto che guardi se è più lontano. Quando i pezzi sono già diradati per la memoria (vista molto ampia) ne toglie al massimo il 40% in più: più rado, mai spoglio. 0% = densità piena ovunque. Spesso la gran parte dei pezzi è lontana: è il modo più efficace per alleggerire"));
                    fo.Committed += async v => await ChangeEco(new JsonObject { ["camFalloff"] = Math.Round(v, 1) / 100.0 });
                    card.Children.Add(fo);
                }
                var a = Advanced(card, "eco");
                a.Body.Children.Add(DropButton(gid));
                var turn = new Toggle(L.T("Gira le tessere"), (bool?)info["turnTiles"] ?? true, L.T("Il campione si ripete a tessere: ognuna girata di un quarto a caso, così la ripetizione non si vede"));
                turn.Toggled += async v => await ChangeEco(new JsonObject { ["turnTiles"] = v });
                a.Body.Children.Add(turn);
                var alignV = info["align"];
                var align = new Toggle(L.T("Segui la pendenza"), alignV is JsonValue jv && jv.TryGetValue<bool>(out var ab) && ab,
                    L.T("I pezzi si piegano come la superficie (sassi, erba). Spento: dritti verso l'alto anche in pendenza (alberi)"));
                align.Toggled += async v => await ChangeEco(new JsonObject { ["align"] = v });
                a.Body.Children.Add(align);
                if (mat != "")
                {
                    var only = new Toggle(L.F("Solo sul materiale «{0}»", mat), (bool?)info["onlyMaterial"] ?? true, L.T("Spento: su tutto l'oggetto"));
                    only.Toggled += async v => await ChangeEco(new JsonObject { ["onlyMaterial"] = v });
                    a.Body.Children.Add(only);
                }
                var whole = (bool?)info["whole"] ?? false;
                var wholeT = new Toggle(L.T("Sempre intero"), whole,
                    L.T("Su tutta la superficie anche quando «Ecosistemi» è acceso in «Calcola solo l'area inquadrata» (in basso a sinistra)"));
                wholeT.Toggled += async v => { if (v) await ChangeEco(new JsonObject { ["whole"] = true }); else await RecalcEco(new JsonObject { ["whole"] = false, ["camRefresh"] = true }); };
                a.Body.Children.Add(wholeT);
                var camMargin = (double?)info["camMargin"] ?? 0.15;
                if (camOn)
                {
                    var mg = new ValueSlider(L.T("Margine attorno all'inquadratura"), camMargin * 100, 0, 60, false, "0", "%", null,
                        L.T("Quanto oltre i bordi dell'inquadratura mettere i pezzi: per le ombre e i riflessi di ciò che è appena fuori, e per piccoli spostamenti della camera"));
                    mg.Committed += async v => await ChangeEco(new JsonObject { ["camMargin"] = Math.Round(v, 1) / 100.0 });
                    a.Body.Children.Add(mg);
                }
                a.Done(!((bool?)info["turnTiles"] ?? true) || (alignV is JsonValue jv2 && jv2.TryGetValue<bool>(out var ab2) && ab2) || !((bool?)info["onlyMaterial"] ?? true)
                       || whole || (camOn && Math.Abs(camMargin - 0.15) > 1e-3),
                       async () => await ChangeEco(new JsonObject { ["turnTiles"] = true, ["align"] = null, ["onlyMaterial"] = true, ["camMargin"] = 0.15, ["whole"] = false }));
                _props.Children.Add(Theme.Card(card, 16));
                EcoLayersCard(info);
            }
            else _ecoAddLayer = -1;

            var mk = new StackPanel();
            mk.Children.Add(SectionTitle(L.T("Crea un ecosistema")));
            var plot = PlotInScene();
            mk.Children.Add(HintSmall(plot == ""
                ? L.T("1. Crea il banco di prova: un terreno accanto alla scena. 2. Con Scatter dipingi o riempi aree, uno strato alla volta (alberi, arbusti, erba). 3. Salva: ti ritrovi l'ecosistema in libreria, da trascinare su qualunque superficie.")
                : L.T("Dipingi o riempi aree sul banco di prova con Scatter, uno strato alla volta. Quando ti piace, salva: l'inquadratura di adesso diventa la miniatura.")));
            var row = new WrapPanel { Margin = new Thickness(0, 6, 0, 0) };
            if (plot == "")
            {
                row.Children.Add(SmallButton(Icons.Plus, L.T("Banco di prova 20 m"), async () => await NewEcoPlot(20)));
            }
            else if (_ecoEditing != null && (string?)_ecoEditing["plot"] == plot)
            {
                // (an ecosystem of the library being changed on the bench)
                mk.Children.Add(HintSmall(L.F("Stai modificando «{0}»", (string?)_ecoEditing["name"] ?? "")));
                AddBenchScatters(mk, plot);
                row.Children.Add(SmallButton(Icons.Brush, L.T("Scatter"), async () => { await Task.Yield(); SetTool("paint"); }));
                var keep = SmallButton(Icons.Save, L.T("Salva modifiche"), SaveEcoChanges);
                keep.ToolTip = L.T("Aggiorna l'ecosistema nella libreria (stesso nome e cartella) con gli scatter del banco di prova");
                row.Children.Add(keep);
                var asNew = SmallButton(Icons.Save, L.T("Salva come nuovo"), SaveEcosystem);
                asNew.ToolTip = L.T("Un nuovo ecosistema con gli scatter del banco di prova: quello di partenza resta com'era");
                row.Children.Add(asNew);
            }
            else
            {
                row.Children.Add(SmallButton(Icons.Brush, L.T("Scatter"), async () => { await Task.Yield(); SetTool("paint"); }));
                row.Children.Add(SmallButton(Icons.Save, L.T("Salva ecosistema"), SaveEcosystem));
            }
            if (plot != "") row.Children.Add(ExitBenchButton());
            mk.Children.Add(row);
            var ma = Advanced(mk, "ecomake");
            if (plot == "")
                ma.Body.Children.Add(SmallButton(Icons.Plus, L.T("Banco di prova 50 m (boschi)"), async () => await NewEcoPlot(50)));
            ma.Body.Children.Add(HintSmall(L.T("Anche delle distribuzioni già fatte nella scena possono diventare un ecosistema: selezionale nell'albero e salva.")));
            var sel = SmallButton(Icons.Save, L.T("Salva le distribuzioni selezionate"), SaveEcosystem);
            sel.HorizontalAlignment = HorizontalAlignment.Left;
            ma.Body.Children.Add(sel);
            ma.Done(false);
            _props.Children.Add(Theme.Card(mk, 16));
        }
    }
}
