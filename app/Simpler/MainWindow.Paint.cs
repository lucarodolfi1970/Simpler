using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace Simpler
{
    /// <summary>
    /// Distribuisci: models of the library spread on the surfaces of the scene. It is the third tool of the header
    /// (after Sposta/ruota and Scala): choosing it opens its panel on the right and turns the left button of the view
    /// into a brush. Modes: Pennello (now); Area and Spaziatura will come in the same panel.
    ///   · palette: library models (click a tile in "Modelli 3D" while the tool is on), each with its "presence";
    ///   · brush: diameter, spacing (+ random), scale (+ random), rotation (+ random), align to the surface;
    ///   · the painting goes into a group ("Distribuzione 1"): the first piece of each model is the original, the
    ///     others are instances (no extra memory). Shift + drag erases.
    /// </summary>
    public sealed partial class MainWindow
    {
        sealed class PaintModelSlot
        {
            public string Model { get; set; } = ""; public string Name { get; set; } = ""; public double Weight { get; set; } = 100;
            // this model's own settings (Avanzate under its row): scale × the general one, turn + the general one,
            // and random scale / random turn instead of the general ones (null = the general ones)
            public double ScaleK { get; set; } = 1; public double RotOff { get; set; }
            public double? ScaleRand { get; set; } public double? RotRand { get; set; }
            // (1.79.0, Luca: «se è una vegetazione puoi aggiungere season») the season of its leaves (0..1) and how much
            // it changes from plant to plant; both 0 = the season of its material
            public double Season { get; set; } public double SeasonRand { get; set; }
            public bool Custom => Math.Abs(ScaleK - 1) > 1e-6 || Math.Abs(RotOff) > 1e-6 || ScaleRand != null || RotRand != null || Season > 0 || SeasonRand > 0;
            public object View() => new { model = Model, weight = Weight, scale = ScaleK, scaleRand = ScaleRand, rot = RotOff, rotRand = RotRand, season = Season, seasonRand = SeasonRand };
            public JsonObject Json()
            {
                var o = new JsonObject { ["model"] = Model, ["name"] = Name, ["weight"] = Weight };
                if (Math.Abs(ScaleK - 1) > 1e-6) o["scale"] = ScaleK;
                if (Math.Abs(RotOff) > 1e-6) o["rot"] = RotOff;
                if (ScaleRand != null) o["scaleRand"] = ScaleRand;
                if (RotRand != null) o["rotRand"] = RotRand;
                if (Season > 0) o["season"] = Season;
                if (SeasonRand > 0) o["seasonRand"] = SeasonRand;
                return o;
            }
            public static PaintModelSlot From(JsonObject p) => new()
            {
                Model = (string?)p["model"] ?? "", Name = (string?)p["name"] ?? "", Weight = (double?)p["weight"] ?? 100,
                ScaleK = (double?)p["scale"] ?? 1, RotOff = (double?)p["rot"] ?? 0,
                ScaleRand = (double?)p["scaleRand"], RotRand = (double?)p["rotRand"],
                Season = (double?)p["season"] ?? 0, SeasonRand = (double?)p["seasonRand"] ?? 0,
            };
        }

        sealed class PaintSettings
        {
            public double Radius { get; set; } = 1.5;          // metres (half the diameter)
            public double Spacing { get; set; } = 0.8;         // metres between pieces
            public double SpacingRand { get; set; } = 0.3;
            public double Scale { get; set; } = 1;
            public double ScaleRand { get; set; } = 0.2;
            public double Rot { get; set; } = 0;               // degrees
            public double RotRand { get; set; } = 1;           // 1 = any direction
            public bool Align { get; set; }
            // Area
            public string Mode { get; set; } = "brush";       // "brush" | "area" | "spacing"
            public double Tension { get; set; } = 50;          // % (100 = straight stretches)
            public double Prob { get; set; } = 1;              // 0..1
            public bool Falloff { get; set; }
            public double FalloffDist { get; set; } = 2;       // metres
            public bool Snap { get; set; } = true;
            // Spaziatura
            public bool ByCount { get; set; }                  // true: Numero of pieces, false: one every Step
            public double Count { get; set; } = 10;
            public double Step { get; set; } = 2;              // metres
            public double Lateral { get; set; }                // metres, random sideways offset
            public double StepRand { get; set; }               // metres added at random to each gap (never less than Step)
            public bool RandomOrder { get; set; }
            public bool Follow { get; set; } = true;           // turned along the line (the Rotation is then relative to it)
            public List<PaintModelSlot> Palette { get; set; } = new();
        }

        PaintSettings _paint = LoadPaint();
        string _paintGroup = "";
        int _paintSeed;                                         // random seed of the distribution being edited
        readonly SemaphoreSlim _paintLock = new(1, 1);

        static string PaintFile => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Simpler", "paint.json");

        /// <summary>The brush settings are remembered (they are a way of working); the models to scatter and the
        /// distribution being painted belong to the scene: every start, new scene or opened project begins empty.</summary>
        static PaintSettings LoadPaint()
        {
            PaintSettings p;
            try { p = JsonSerializer.Deserialize<PaintSettings>(File.ReadAllText(PaintFile)) ?? new PaintSettings(); }
            catch { p = new PaintSettings(); }
            p.Palette = new List<PaintModelSlot>();
            return p;
        }

        void SavePaint()
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(PaintFile)!);
                var palette = _paint.Palette;
                _paint.Palette = new List<PaintModelSlot>();
                try { File.WriteAllText(PaintFile, JsonSerializer.Serialize(_paint)); }
                finally { _paint.Palette = palette; }
            }
            catch { }
        }

        // every distribution keeps its own models: choosing another one in the tree brings its models back
        readonly Dictionary<string, List<PaintModelSlot>> _groupPalettes = new();

        void SwitchPaintGroup(string id)
        {
            if (_paintGroup != "") _groupPalettes[_paintGroup] = _paint.Palette;
            if (id == "") { _paintGroup = ""; _paint.Palette = new List<PaintModelSlot>(); SendPaint(); SendToWeb(new { type = "paintGroup", group = "" }); if (_rightPanel == "paint") RenderProps(); return; }
            _ = LoadPaintGroup(id);
        }

        /// <summary>A distribution becomes the one being painted: its strokes, settings and models (saved with it by
        /// paint/set) go to the panel and to the view, so the sliders change what was painted.</summary>
        async Task LoadPaintGroup(string id)
        {
            JsonObject? d = null, baseP = null;
            if (id != "") await Run(async api => { d = await api.Get("paint/data?group=" + Uri.EscapeDataString(id)); });
            // (an ecosystem put back on the bench: its pieces are fixed, the brush adds to them and erases them)
            if (id != "" && ((int?)d?["base"] ?? 0) > 0)
                await Run(async api => { baseP = await api.Get("paint/base?group=" + Uri.EscapeDataString(id)); });
            _paintGroup = id;
            if (id == "") _paint.Palette = new List<PaintModelSlot>();
            else if (d?["palette"] is JsonArray pal && pal.Count > 0)
                _paint.Palette = pal.OfType<JsonObject>().Select(PaintModelSlot.From).Where(p => p.Model != "").ToList();
            else _paint.Palette = _groupPalettes.TryGetValue(id, out var known) ? known : PaletteOf(id);
            if (d?["settings"] is JsonObject st)
            {
                double D(string k, double v) => (double?)st[k] ?? v;
                _paint.Spacing = D("spacing", _paint.Spacing); _paint.SpacingRand = D("spacingRand", _paint.SpacingRand);
                _paint.Scale = D("scale", _paint.Scale); _paint.ScaleRand = D("scaleRand", _paint.ScaleRand);
                _paint.Rot = D("rot", _paint.Rot); _paint.RotRand = D("rotRand", _paint.RotRand);
                _paint.Align = (bool?)st["align"] ?? _paint.Align;
                _paint.Tension = D("tension", _paint.Tension); _paint.Prob = D("prob", _paint.Prob);
                _paint.Falloff = (bool?)st["falloff"] ?? _paint.Falloff; _paint.FalloffDist = D("falloffDist", _paint.FalloffDist);
                _paint.Snap = (bool?)st["snap"] ?? _paint.Snap;
                _paint.ByCount = (bool?)st["byCount"] ?? _paint.ByCount; _paint.Count = D("count", _paint.Count);
                _paint.Step = D("step", _paint.Step); _paint.Lateral = D("lateral", _paint.Lateral); _paint.StepRand = D("stepRand", _paint.StepRand);
                _paint.RandomOrder = (bool?)st["randomOrder"] ?? _paint.RandomOrder; _paint.Follow = (bool?)st["follow"] ?? _paint.Follow;
            }
            // a distribution opens in the mode it was made with (Pennello, Area or Spaziatura)
            if (id != "" && d != null && (d["area"] is JsonObject || (d["strokes"] as JsonArray)?.Count > 0 || baseP != null))
                _paint.Mode = d["area"] is JsonObject ? ((string?)d["settings"]?["mode"] == "spacing" ? "spacing" : "area") : "brush";
            _paintSeed = (int?)d?["seed"] ?? 0;
            SendPaint();
            SendToWeb(new
            {
                type = "paintGroup", group = id, strokes = d?["strokes"]?.DeepClone(), seed = (int?)d?["seed"] ?? 0,
                settings = d?["settings"]?.DeepClone(), area = d?["area"]?.DeepClone(),
                palette = _paint.Palette.Select(p => p.View()).ToArray(), @base = baseP,
            });
            if (_rightPanel == "paint") RenderProps();
        }

        // a change of the distribution from the view: the newest one wins (older ones still waiting are skipped)
        JsonObject? _nextSet;

        bool _scatterPending;     // a new distribution is being made: a placeholder row in the tree

        /// <summary>An engine call of the brush/area/spacing: if it takes more than a moment, the view's pill says what
        /// is happening (with the engine's progress: models loaded from the library) and a new distribution gets a
        /// placeholder row in the tree.</summary>
        async Task ScatterCall(bool creating, Func<Task> call)
        {
            var shown = false;
            var done = false;
            _ = Task.Delay(400).ContinueWith(_ => Dispatcher.Invoke(() =>
            {
                if (done) return;
                shown = true;
                ShowTask(creating ? L.T("Creo la distribuzione…") : L.T("Aggiorno la distribuzione…"));
                if (creating) { _scatterPending = true; RenderTree(); }
            }));
            try { await call(); }
            finally
            {
                done = true;
                if (shown) HideTask();
                if (_scatterPending) { _scatterPending = false; RenderTree(); }
            }
        }

        async Task OnPaintSet(JsonObject msg)
        {
            _nextSet = msg;
            if (_paintLock.CurrentCount == 0) return;        // the running one picks it up when it ends
            await _paintLock.WaitAsync();
            try
            {
                while (_nextSet != null)
                {
                    var m = _nextSet; _nextSet = null;
                    var batch = (int?)m["batch"] ?? 0;
                    _paintSeed = (int?)m["seed"] ?? _paintSeed;
                    var body = new JsonObject
                    {
                        ["group"] = _paintGroup, ["packed"] = m["packed"]?.DeepClone(), ["strokes"] = m["strokes"]?.DeepClone(),
                        ["seed"] = (int?)m["seed"] ?? 0, ["settings"] = m["settings"]?.DeepClone(), ["area"] = m["area"]?.DeepClone(),
                        ["palette"] = new JsonArray(_paint.Palette.Select(p => (JsonNode)p.Json()).ToArray()),
                    };
                    if (((int?)m["packed"]?["count"] ?? 0) == 0 && _paintGroup == "") { SendToWeb(new { type = "paintDone", batch }); continue; }
                    JsonObject? r = null;
                    _reloadOrigin = "action";
                    await ScatterCall(_paintGroup == "", () => Run(async api => { r = await api.Post("paint/set", body); }));
                    if (r == null) { SendToWeb(new { type = "paintDone", batch }); continue; }
                    var newGroup = (string?)r["group"] ?? "";
                    if (newGroup != _paintGroup) { _paintGroup = newGroup; _expanded.Add(newGroup); }
                    await RefreshScene();
                    SendToWeb(new { type = "paintDone", group = _paintGroup, batch, rev = (string?)r["rev"] ?? "" });
                    if (_scene.ById.TryGetValue(_paintGroup, out var g))
                        Status(L.F("{0}: {1} pezzi", g.Name, (int?)r["count"] ?? 0));
                    if (_rightPanel == "paint") RenderProps();
                }
            }
            finally { _paintLock.Release(); }
        }

        /// <summary>The models of a distribution painted earlier (e.g. in a project just opened), all at 100%.</summary>
        List<PaintModelSlot> PaletteOf(string groupId)
        {
            var list = new List<PaintModelSlot>();
            if (!_scene.ById.TryGetValue(groupId, out var g)) return list;
            foreach (var c in g.Children)
            {
                if (c.PaintModel == "" || list.Any(p => p.Model == c.PaintModel)) continue;
                var e = _models.OfType<JsonObject>().FirstOrDefault(m => (string?)m["id"] == c.PaintModel);
                list.Add(new PaintModelSlot { Model = c.PaintModel, Name = (string?)e?["name"] ?? c.Name, Weight = 100 });
            }
            return list;
        }

        /// <summary>The distribution being edited was deleted: its line leaves the view and the panel goes back to the
        /// default values (before, its settings and its line stayed, as if it were still there).</summary>
        void PaintGroupGone()
        {
            _groupPalettes.Remove(_paintGroup);
            _paintGroup = "";
            var mode = _paint.Mode;
            _paint = new PaintSettings { Mode = mode };
            SavePaint();
            SendPaint();
            SendToWeb(new { type = "paintGroup", group = "", reset = true });
        }

        /// <summary>«Elimina» of the panel: the distribution being painted goes (undo brings it back), or, when nothing was
        /// made yet, the outline or line being drawn and its pieces in the view.</summary>
        async Task DiscardPainting()
        {
            if (_paintGroup != "" && _scene.ById.ContainsKey(_paintGroup))
            {
                await _paintLock.WaitAsync();
                try
                {
                    var id = _paintGroup;
                    _reloadOrigin = "action";
                    await Run(async api => { await api.Post("delete", new JsonObject { ["ids"] = new JsonArray(id) }); });
                    await RefreshScene();          // (the tree sees the distribution gone: PaintGroupGone)
                }
                finally { _paintLock.Release(); }
                Status(L.T("Distribuzione eliminata"));
                return;
            }
            _paintGroup = "";
            SendToWeb(new { type = "paintGroup", group = "", reset = true });
            if (_rightPanel == "paint") RenderProps();
            Status(L.T("Contorno eliminato: disegnane uno nuovo"));
        }

        void ResetPaint()
        {
            _groupPalettes.Clear();
            _paint.Palette = new List<PaintModelSlot>();
            _paintGroup = "";
            if (Painting) SetTool("move"); else SendPaint();
            SendToWeb(new { type = "paintGroup", group = "" });
        }

        bool Painting => _tool == "paint";

        void SendPaint(bool regen = false)
        {
            SendToWeb(new
            {
                type = "paint", on = Painting, group = _paintGroup, regen,
                settings = new
                {
                    radius = _paint.Radius, spacing = _paint.Spacing, spacingRand = _paint.SpacingRand, scale = _paint.Scale,
                    scaleRand = _paint.ScaleRand, rot = _paint.Rot, rotRand = _paint.RotRand, align = _paint.Align,
                    mode = _paint.Mode, tension = _paint.Tension, prob = _paint.Prob, falloff = _paint.Falloff,
                    falloffDist = _paint.FalloffDist, snap = _paint.Snap,
                    byCount = _paint.ByCount, count = _paint.Count, step = _paint.Step, stepRand = _paint.StepRand, lateral = _paint.Lateral,
                    randomOrder = _paint.RandomOrder, follow = _paint.Follow,
                },
                palette = _paint.Palette.Select(p => p.View()).ToArray(),
            });
        }

        /// <summary>A library model clicked while the brush is on: it joins the palette.</summary>
        void AddToPalette(string id, string name)
        {
            if (_paint.Palette.Any(p => p.Model == id)) { Status(L.F("{0} è già nel pennello", name)); return; }
            _paint.Palette.Add(new PaintModelSlot { Model = id, Name = name, Weight = 100 });
            SavePaint();
            SendPaint();
            RenderProps();
            Status(L.F("{0} aggiunto al pennello", name));
        }

        // ---------------------------------------------------------------- messages from the view

        async Task OnPaintAdd(JsonArray items, int batch)
        {
            if (items.Count == 0) return;
            await _paintLock.WaitAsync();
            try
            {
                JsonObject? r = null;
                _reloadOrigin = "action";
                await ScatterCall(_paintGroup == "", () => Run(async api => { r = await api.Post("paint/add", new JsonObject { ["group"] = _paintGroup, ["items"] = items.DeepClone() }); }));
                if (r == null) { SendToWeb(new { type = "paintDone", batch }); return; }
                var newGroup = (string?)r["group"] ?? "";
                if (newGroup != _paintGroup) { _paintGroup = newGroup; _expanded.Add(newGroup); }
                // the view draws the new pieces from their library model (placeholders + GPU instancing): no export
                await RefreshScene();
                SendToWeb(new { type = "paintDone", group = _paintGroup, batch });
                var n = (r["ids"] as JsonArray)?.Count ?? 0;
                if (_scene.ById.TryGetValue(_paintGroup, out var g))
                    Status(L.F("{0}: +{1} (totale {2})", g.Name, n, g.Children.Count));
            }
            finally { _paintLock.Release(); }
        }

        /// <summary>A part inside a library piece has no node of its own in the view (the piece is drawn from its
        /// model): the view selects the piece.</summary>
        string ViewerId(string id)
        {
            if (!_scene.ById.TryGetValue(id, out var o)) return id;
            while (o.PaintModel != "" && o.Parent != "" && _scene.ById.TryGetValue(o.Parent, out var p) && p.PaintModel != "") o = p;
            return o.Id;
        }

        /// <summary>Copies of painted pieces are drawn by the view from their model: they are left out of a "clone".</summary>
        JsonObject WithoutPainted(JsonObject copies)
        {
            var o = new JsonObject();
            foreach (var kv in copies)
                if (!(_scene.ById.TryGetValue((string?)kv.Value ?? "", out var src) && src.PaintModel != "")) o[kv.Key] = kv.Value?.DeepClone();
            return o;
        }

        async Task OnPaintErase(JsonArray ids)
        {
            if (ids.Count == 0) return;
            await _paintLock.WaitAsync();
            try
            {
                var list = ids.Select(x => (string?)x ?? "").Where(x => x != "" && _scene.ById.ContainsKey(x)).ToArray();
                if (list.Length == 0) return;
                _reloadOrigin = "action";
                await Run(async api => { await api.Post("delete", new JsonObject { ["ids"] = new JsonArray(list.Select(x => (JsonNode)x!).ToArray()) }); });
                await RefreshScene();
            }
            finally { _paintLock.Release(); }
        }

        // ---------------------------------------------------------------- the panel

        void RenderPaintPanel()
        {
            var head = new StackPanel();
            var titleRow = new DockPanel();
            var close = SmallButton(Icons.Close, L.T("Esci dal pennello (Esc)"), async () => { await Task.Yield(); SetTool("move"); });
            DockPanel.SetDock(close, Dock.Right);
            titleRow.Children.Add(close);
            titleRow.Children.Add(Theme.Caption(L.T("Distribuisci")));
            head.Children.Add(titleRow);
            var modes = Theme.Segmented(out var modeButtons,
                (L.T("Pennello"), L.T("Dipingi i modelli sulle superfici trascinando con il tasto sinistro")),
                (L.T("Area"), L.T("Disegna il contorno di un'area con dei clic: si riempie dei modelli")),
                (L.T("Spaziatura"), L.T("Disegna una linea con dei clic: gli oggetti si mettono in fila lungo di essa")));
            modes.HorizontalAlignment = HorizontalAlignment.Left;
            modes.Margin = new Thickness(0, 10, 0, 4);
            var area = _paint.Mode == "area";
            var spacing = _paint.Mode == "spacing";
            Theme.SetSegment(modeButtons, area ? 1 : spacing ? 2 : 0);
            modeButtons[0].Click += (_, __) => SetPaintMode("brush");
            modeButtons[1].Click += (_, __) => SetPaintMode("area");
            modeButtons[2].Click += (_, __) => SetPaintMode("spacing");
            head.Children.Add(modes);

            // where the painting goes
            var target = new DockPanel { Margin = new Thickness(0, 10, 0, 0) };
            var newBtn = SmallButton(Icons.Plus, L.T("Nuova"), async () =>
            {
                await Task.Yield();
                SwitchPaintGroup("");
                Status(L.T("Nuova distribuzione: scegli i modelli nella libreria e dipingi"));
            });
            newBtn.ToolTip = L.T("Nuova distribuzione: svuota i modelli da distribuire; le prossime pennellate vanno in un gruppo nuovo");
            newBtn.Margin = new Thickness(8, 0, 0, 0);
            DockPanel.SetDock(newBtn, Dock.Right);
            target.Children.Add(newBtn);
            // (1.78.4, Luca: «mi serve un tasto elimina per togliere dai piedi questo che ho sbagliato») an outline being
            // drawn is in no list (it becomes a distribution only when it has models): this takes it away; a distribution
            // already made is deleted (Ctrl+Z brings it back). The models chosen stay for the next one.
            if (_paintGroup != "" || area || spacing)
            {
                var delBtn = SmallButton(Icons.Trash, L.T("Elimina"), async () => await DiscardPainting());
                delBtn.ToolTip = _paintGroup != "" ? L.T("Elimina questa distribuzione (Ctrl+Z la riporta)")
                                                   : L.T("Elimina il contorno o la linea che stai disegnando, per ricominciare");
                delBtn.Margin = new Thickness(8, 0, 0, 0);
                DockPanel.SetDock(delBtn, Dock.Right);
                target.Children.Add(delBtn);
            }
            var gname = _paintGroup != "" && _scene.ById.TryGetValue(_paintGroup, out var g) ? L.F("Dipingi in: {0} ({1})", g.Name, g.PaintCount > 0 ? g.PaintCount : g.Children.Count)
                                                                                           : L.T("Dipingi in: una nuova distribuzione");
            var gl = Theme.Label(gname, 12, Theme.TextSoft);
            gl.VerticalAlignment = VerticalAlignment.Center;
            gl.TextTrimming = TextTrimming.CharacterEllipsis;
            gl.ToolTip = L.T("Per continuare una distribuzione esistente selezionala nell'albero mentre il pennello è attivo");
            target.Children.Add(gl);
            head.Children.Add(target);
            _props.Children.Add(Theme.Card(head, 16));

            // palette
            var pal = new StackPanel();
            pal.Children.Add(SectionTitle(L.T("Modelli da distribuire")));
            if (_paint.Palette.Count == 0)
            {
                var t = Theme.Label(L.T("Clicca i modelli nella libreria in basso (scheda Modelli 3D): si aggiungono qui. Per un prato: erba con presenza alta, fiori con presenza bassa."), 12, Theme.TextFaint);
                t.TextWrapping = TextWrapping.Wrap;
                pal.Children.Add(t);
            }
            var total = _paint.Palette.Sum(p => p.Weight);
            foreach (var slot in _paint.Palette.ToList())
            {
                var entry = _models.OfType<JsonObject>().FirstOrDefault(m => (string?)m["id"] == slot.Model);
                var row = new Grid { Margin = new Thickness(0, 0, 0, 8), Tag = "content" };   // (a model of the list: no heart, 1.76.32)
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(46) });
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(32) });
                var thumb = (string?)entry?["thumb"] ?? "";
                var pic = new Border { Width = 40, Height = 40, CornerRadius = new CornerRadius(6), Background = Theme.B(Theme.Inset), VerticalAlignment = VerticalAlignment.Top };
                if (thumb != "" && File.Exists(thumb)) pic.Background = new ImageBrush(LoadBitmapFresh(thumb)) { Stretch = Stretch.UniformToFill };
                row.Children.Add(pic);
                var col = new StackPanel { Margin = new Thickness(8, 0, 4, 0) };
                var nm = Theme.Label(entry == null ? slot.Name + " " + L.T("(non più in libreria)") : slot.Name, 12, entry == null ? Theme.TextFaint : Theme.TextSoft);
                nm.TextTrimming = TextTrimming.CharacterEllipsis;
                col.Children.Add(nm);
                var share = total > 0 ? slot.Weight / total * 100 : 0;
                var s = new ValueSlider(L.T("Presenza"), slot.Weight, 0, 100, false, "0", "%", null,
                                        L.F("Quanto spesso compare rispetto agli altri modelli del pennello (ora circa {0}% dei pezzi)", Math.Round(share)));
                s.Compact();
                s.Margin = new Thickness(0, 2, 0, 0);
                s.Committed += v => { slot.Weight = v; SavePaint(); SendPaint(); RenderProps(); };
                col.Children.Add(s);
                // this model's own scale and turn, under its row (closed: the general settings below apply to it)
                var adv = Advanced(col, "paintItem:" + slot.Model);
                void Item(string label, double v, double min, double max, bool log, string fmt, string unit, string tip, Action<double> set)
                {
                    var vs = new ValueSlider(label, v, min, max, log, fmt, unit, null, tip).Compact(stacked: true);
                    vs.Committed += x => { set(x); SavePaint(); SendPaint(); RenderProps(); };
                    adv.Body.Children.Add(vs);
                }
                Item(L.T("Scala"), slot.ScaleK * 100, 10, 1000, true, "0", "%", L.T("Grandezza di questo modello rispetto alla Scala generale (100% = come la Scala generale)"), x => slot.ScaleK = x / 100);
                Item(L.T("Scala casuale"), (slot.ScaleRand ?? _paint.ScaleRand) * 100, 0, 90, false, "0", "%",
                     slot.ScaleRand == null ? L.T("Ora come la Scala casuale generale: spostalo per dare a questo modello la sua") : L.T("Scala casuale di questo modello, al posto di quella generale"), x => slot.ScaleRand = x / 100);
                Item(L.T("Rotazione"), slot.RotOff, -180, 180, false, "0", "°", L.T("Si aggiunge alla Rotazione generale: per esempio 90° per un modello girato diversamente dagli altri"), x => slot.RotOff = x);
                Item(L.T("Rotazione casuale"), (slot.RotRand ?? _paint.RotRand) * 100, 0, 100, false, "0", "%",
                     slot.RotRand == null ? L.T("Ora come la Rotazione casuale generale: spostalo per dare a questo modello la sua") : L.T("Rotazione casuale di questo modello, al posto di quella generale"), x => slot.RotRand = x / 100);
                // (1.79.0, Luca: «se è una vegetazione puoi aggiungere season, così posso fare un mix di colori di foglie»)
                // (Luca: «perché season c'è solo in una vegetazione?» - Old red oak 1, made before the vegetation kept its
                // leaves in the library: no «veg») every model of the Vegetation library, or tagged as one
                if ((entry?["veg"]?["leaves"] as JsonArray)?.Count > 0 || (entry != null && IsVegFolder((string?)entry["folder"] ?? "")))
                {
                    Item(L.T("Stagione"), slot.Season * 100, 0, 100, false, "0", "%",
                         L.T("La stagione delle foglie di questo modello nello scatter: 0% estate, 50% autunno, 100% inverno (foglie cadute). Con Stagione e Stagione casuale a 0% resta quella del suo materiale"), x => slot.Season = x / 100);
                    Item(L.T("Stagione casuale"), slot.SeasonRand * 100, 0, 100, false, "0", "%",
                         L.T("Ogni pianta prende una stagione un po' diversa, fino a questa percentuale in più o in meno: un mix di colori delle foglie"), x => slot.SeasonRand = x / 100);
                }
                adv.Done(slot.Custom, async () =>
                {
                    await Task.Yield();
                    slot.ScaleK = 1; slot.RotOff = 0; slot.ScaleRand = null; slot.RotRand = null; slot.Season = 0; slot.SeasonRand = 0;
                    SavePaint(); SendPaint(); RenderProps();
                });
                Grid.SetColumn(col, 1);
                row.Children.Add(col);
                var rm = IconButton(Icons.Trash, L.T("Togli dal pennello"), async () => { await Task.Yield(); _paint.Palette.Remove(slot); SavePaint(); SendPaint(); RenderProps(); });
                rm.VerticalAlignment = VerticalAlignment.Top;
                Grid.SetColumn(rm, 2);
                row.Children.Add(rm);
                pal.Children.Add(row);
            }
            _props.Children.Add(Theme.Card(pal, 16));

            // brush or area
            var b = new StackPanel();
            ValueSlider S(StackPanel to, string label, double v, double min, double max, bool log, string fmt, string unit, string tip, Action<double> set)
            {
                var sl = new ValueSlider(label, v, min, max, log, fmt, unit, null, tip);
                sl.Committed += x => { set(x); SavePaint(); SendPaint(true); };      // (regen: the view makes the distribution again whatever it thinks changed)
                to.Children.Add(sl);
                return sl;
            }
            UIElement SeedAndUpdate(string updTip)
            {
                var box = new StackPanel();
                var seedRow = new DockPanel { Margin = new Thickness(0, 8, 0, 0) };
                var dice = SmallButton(Icons.Refresh, L.T("Cambia"), async () =>
                {
                    await Task.Yield();
                    _paintSeed = Random.Shared.Next(1, 1_000_000_000);
                    SendToWeb(new { type = "paintSeed", seed = _paintSeed });
                    RenderProps();
                });
                dice.ToolTip = L.T("Stesse regolazioni, altre scelte casuali (posizioni, modelli, rotazioni)");
                DockPanel.SetDock(dice, Dock.Right);
                seedRow.Children.Add(dice);
                var sl = Theme.Label(L.F("Seme casuale: {0}", _paintSeed == 0 ? "—" : _paintSeed.ToString()), 12, Theme.TextSoft);
                sl.VerticalAlignment = VerticalAlignment.Center;
                seedRow.Children.Add(sl);
                box.Children.Add(seedRow);
                var upd = SmallButton(Icons.Refresh, L.T("Aggiorna"), async () => { await Task.Yield(); SendToWeb(new { type = "areaUpdate" }); });
                upd.ToolTip = updTip;
                upd.HorizontalAlignment = HorizontalAlignment.Left;
                upd.Margin = new Thickness(0, 8, 0, 0);
                box.Children.Add(upd);
                return box;
            }
            if (spacing)
            {
                b.Children.Add(SectionTitle(L.T("Spaziatura")));
                var how = Theme.Segmented(out var howButtons,
                    (L.T("Per distanza"), L.T("Un oggetto ogni tanti metri lungo la linea")),
                    (L.T("Per numero"), L.T("Un numero fisso di oggetti distribuiti su tutta la linea")));
                how.HorizontalAlignment = HorizontalAlignment.Left;
                how.Margin = new Thickness(0, 0, 0, 10);
                Theme.SetSegment(howButtons, _paint.ByCount ? 1 : 0);
                howButtons[0].Click += (_, __) => { _paint.ByCount = false; SavePaint(); SendPaint(); RenderProps(); };
                howButtons[1].Click += (_, __) => { _paint.ByCount = true; SavePaint(); SendPaint(); RenderProps(); };
                b.Children.Add(how);
                if (_paint.ByCount)
                    S(b, L.T("Numero"), _paint.Count, 1, 1000, true, "0", "", L.T("Quanti oggetti in tutto lungo la linea"), x => _paint.Count = Math.Round(x));
                else
                {
                    S(b, L.T("Distanza"), _paint.Step, 0.05, 100, true, "0.##", "m", L.T("Distanza minima tra un oggetto e il successivo lungo la linea: non si scende mai sotto, così i modelli non si sovrappongono"), x => _paint.Step = x);
                    S(b, L.T("Distanza casuale"), _paint.StepRand, 0, 50, false, "0.##", "m", L.T("A ogni intervallo si aggiunge a caso da 0 a questi metri: file meno perfette (auto parcheggiate). 0 = tutti alla stessa distanza"), x => _paint.StepRand = x);
                }
                S(b, L.T("Scostamento laterale"), _paint.Lateral, 0, 20, false, "0.##", "m", L.T("Ogni oggetto si sposta a caso di fianco alla linea, fino a questa distanza: 0 = tutti sulla linea"), x => _paint.Lateral = x);
                S(b, L.T("Tensione"), _paint.Tension, 1, 100, false, "0", "%", L.T("Forma della linea tra i punti: valori alti = tratti dritti, bassi = curve morbide"), x => _paint.Tension = x);
                var order = new Toggle(L.T("Ordine casuale"), _paint.RandomOrder, L.T("Spento: i modelli si ripetono nell'ordine della lista. Acceso: scelti a caso secondo la presenza"));
                order.Toggled += v => { _paint.RandomOrder = v; SavePaint(); SendPaint(); };
                b.Children.Add(order);
                var follow = new Toggle(L.T("Orienta lungo la linea"), _paint.Follow, L.T("Ogni oggetto gira seguendo la direzione della linea, anche nelle curve (auto su una strada, recinzioni, panchine): la Rotazione diventa rispetto alla linea"));
                follow.Toggled += v => { _paint.Follow = v; SavePaint(); SendPaint(); RenderProps(); };
                b.Children.Add(follow);
                var snapS = new Toggle(L.T("Appoggia alle superfici"), _paint.Snap, L.T("Acceso: ogni oggetto cade sulla prima superficie sotto la linea. Spento: all'altezza della linea"));
                snapS.Toggled += v => { _paint.Snap = v; SavePaint(); SendPaint(); };
                b.Children.Add(snapS);
                b.Children.Add(SeedAndUpdate(L.T("Ricalcola la linea: dopo aver spostato o escluso degli oggetti sotto di essa")));
            }
            else if (!area)
            {
                b.Children.Add(SectionTitle(L.T("Pennello")));
                S(b, L.T("Diametro"), _paint.Radius * 2, 0.1, 100, true, "0.##", "m", L.T("Grandezza del pennello (anche con i tasti [ e ])"), x => _paint.Radius = x / 2);
                S(b, L.T("Distanza"), _paint.Spacing, 0.02, 30, true, "0.##", "m", L.T("Distanza minima tra due oggetti: più piccola = più fitto"), x => _paint.Spacing = x);
                S(b, L.T("Distanza casuale"), _paint.SpacingRand * 100, 0, 100, false, "0", "%", L.T("Quanto la distanza può accorciarsi a caso: 0% = regolare, 100% = gruppi naturali"), x => _paint.SpacingRand = x / 100);
            }
            else
            {
                b.Children.Add(SectionTitle(L.T("Area")));
                S(b, L.T("Distanza"), _paint.Spacing, 0.02, 30, true, "0.##", "m", L.T("Distanza tra gli oggetti (lato della griglia su cui sono messi)"), x => _paint.Spacing = x);
                S(b, L.T("Distanza casuale"), _paint.SpacingRand * 100, 0, 100, false, "0", "%", L.T("Ogni oggetto si sposta a caso fino a questa parte della distanza: 0% = griglia regolare"), x => _paint.SpacingRand = x / 100);
                S(b, L.T("Probabilità"), _paint.Prob * 100, 0, 100, false, "0", "%", L.T("Densità: 100% = un oggetto in ogni posto della griglia, 0% = nessuno"), x => _paint.Prob = x / 100);
                S(b, L.T("Tensione"), _paint.Tension, 1, 100, false, "0", "%", L.T("Forma del contorno tra i punti: valori alti = tratti dritti, bassi = curve morbide"), x => _paint.Tension = x);
                var fall = new Toggle(L.T("Sfuma ai bordi"), _paint.Falloff, L.T("Vicino al contorno gli oggetti diventano più radi e più piccoli"));
                fall.Toggled += v => { _paint.Falloff = v; SavePaint(); SendPaint(); RenderProps(); };
                b.Children.Add(fall);
                if (_paint.Falloff)
                    S(b, L.T("Ampiezza sfumatura"), _paint.FalloffDist, 0.1, 20, true, "0.#", "m", L.T("Fino a che distanza dal contorno arriva la sfumatura"), x => _paint.FalloffDist = x);
                var snap = new Toggle(L.T("Appoggia alle superfici"), _paint.Snap, L.T("Acceso: ogni oggetto cade sulla prima superficie sotto l'area. Spento: tutti all'altezza media dei punti del contorno"));
                snap.Toggled += v => { _paint.Snap = v; SavePaint(); SendPaint(); };
                b.Children.Add(snap);
                b.Children.Add(SeedAndUpdate(L.T("Ricalcola l'area: dopo aver spostato o escluso degli oggetti sotto di essa")));
            }
            _props.Children.Add(Theme.Card(b, 16));

            // the pieces
            var ob = new StackPanel();
            ob.Children.Add(SectionTitle(L.T("Oggetti")));
            S(ob, L.T("Scala"), _paint.Scale, 0.1, 10, true, "0.##", "×", L.T("Grandezza degli oggetti rispetto a quella della libreria"), x => _paint.Scale = x);
            S(ob, L.T("Scala casuale"), _paint.ScaleRand * 100, 0, 90, false, "0", "%", L.T("Ogni oggetto più grande o più piccolo a caso, fino a questa percentuale"), x => _paint.ScaleRand = x / 100);
            if (_paint.Mode == "spacing" && _paint.Follow)
                S(ob, L.T("Rotazione rispetto alla linea"), _paint.Rot, -180, 180, false, "0", "°", L.T("Rispetto alla direzione della linea, dal primo punto all'ultimo: 0° = l'asse X del modello segue la linea, 180° = senso opposto, ±90° = di traverso. Resta giusta anche nelle curve"), x => _paint.Rot = x);
            else
                S(ob, L.T("Rotazione"), _paint.Rot, -180, 180, false, "0", "°", L.T("Rotazione di tutti gli oggetti attorno al loro asse verticale"), x => _paint.Rot = x);
            S(ob, L.T("Rotazione casuale"), _paint.RotRand * 100, 0, 100, false, "0", "%", L.T("100% = ogni oggetto girato a caso in qualsiasi direzione"), x => _paint.RotRand = x / 100);
            var align = new Toggle(L.T("Allinea alla superficie"), _paint.Align, L.T("Acceso: gli oggetti seguono la pendenza (sassi, muschio). Spento: restano dritti (alberi, erba, persone)"));
            align.Toggled += v => { _paint.Align = v; SavePaint(); SendPaint(); };
            ob.Children.Add(align);
            var hint = Theme.Label(spacing
                ? L.T("Clic sulle superfici: i punti della linea · doppio clic, clic sull'ultimo punto, Invio o Esc: finisce la linea (clic sul primo punto: linea chiusa) · Backspace: toglie l'ultimo punto. Poi trascina i punti, clic sul + per aggiungerne uno, Canc per togliere quello selezionato. Le regolazioni cambiano la linea anche dopo.")
                : area
                ? L.T("Clic sulle superfici: un punto del contorno · clic sul primo punto, doppio clic, Invio o Esc: chiude l'area · Backspace: toglie l'ultimo punto. Poi trascina i punti per cambiare la forma, clic sul + per aggiungerne uno, Canc per togliere quello selezionato. Le regolazioni cambiano l'area anche dopo. Per non mettere niente su un oggetto: Proprietà > Escludi da Area e Spaziatura.")
                : L.T("Le regolazioni e la presenza cambiano tutta la distribuzione su cui stai dipingendo, anche dopo. Tasto sinistro: dipingi · Shift + tasto sinistro: cancella · [ ]: diametro · rotellina, tasto destro e centrale: muovi la vista · Esc: esci"), 11, Theme.TextFaint);
            hint.TextWrapping = TextWrapping.Wrap;
            hint.Margin = new Thickness(0, 8, 0, 0);
            ob.Children.Add(hint);
            if (_paintGroup != "")
            {
                var adv = Advanced(ob, "paintDrop");
                adv.Body.Children.Add(DropButton(_paintGroup));
            }
            _props.Children.Add(Theme.Card(ob, 16));
        }

        /// <summary>(1.76.18) «Appoggia alla superficie»: the pieces of a distribution (or of the layers of an ecosystem)
        /// dropped again on the surface under or over them - the ground changed after they were placed.</summary>
        FrameworkElement DropButton(string groupId)
        {
            var b = Theme.Button(L.T("Appoggia alla superficie"), Theme.Kind.Ghost,
                L.T("Rimette ogni oggetto sulla superficie sotto (o sopra, se è finito sepolto) in verticale, con la sua rotazione e la sua scala: per quando il terreno o i modelli sotto sono cambiati"));
            b.HorizontalAlignment = HorizontalAlignment.Left;
            b.Margin = new Thickness(0, 4, 0, 8);
            b.Click += async (_, __) =>
            {
                if (_api == null || groupId == "") return;
                SendToWeb(new { type = "busyNow", what = L.T("Appoggia alla superficie") });
                JsonObject? r = null;
                using (var busy = BeginBusy())
                    await Run(async api => { r = await api.Post("paint/drop", new JsonObject { ["ids"] = new JsonArray(groupId) }); });
                if (r == null) return;
                if (r["history"] is JsonObject h) UpdateHistory(h);
                await RefreshScene();
                Status(L.F("{0} oggetti appoggiati alla superficie", (int?)r["moved"] ?? 0));
            };
            return b;
        }

        /// <summary>Pennello / Area: a distribution is made with one of them; changing the mode while one is being
        /// edited starts a new one (the chosen models stay).</summary>
        void SetPaintMode(string mode)
        {
            if (_paint.Mode == mode) return;
            _paint.Mode = mode;
            SavePaint();
            if (_paintGroup != "")
            {
                var pal = _paint.Palette.ToList();
                SwitchPaintGroup("");
                _paint.Palette = pal;
            }
            SendPaint();
            RenderProps();
            Status(mode == "area" ? L.T("Area: clicca sulle superfici per disegnare il contorno")
                 : mode == "spacing" ? L.T("Spaziatura: clicca sulle superfici per disegnare la linea")
                 : L.T("Pennello: trascina con il tasto sinistro per dipingere"));
        }
    }
}
