using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;

namespace Simpler
{
    /// <summary>(1.76.0) «Terreno» in the Paesaggio panel (engine: terrain.py, terrain_gen.py). A preset makes the
    /// terrain - one mesh per zone (prato, terra e ghiaia, roccia, neve, spianata, sabbia) under a group, so a zone can
    /// take its own material or ecosystem. Then: size, relief, another version, snow, the flat area around the model;
    /// erosion, age, rock slope, gravel, irregular borders, direction, edge, detail and a height map of the user in the
    /// Avanzate. Every change makes the terrain again (seconds: a progress bar) and is one Ctrl+Z step. The Poly Haven
    /// textures of the zones are downloaded in the background and put on the zones that still have their plain colour.</summary>
    public sealed partial class MainWindow
    {
        JsonObject? _terrain;                  // GET terrain/state of the terrain shown (null: none in the scene)
        bool _terrainLoading, _terrainWatch;
        static readonly Color TerrainColor = Color.FromRgb(0x7B, 0xA8, 0x4E);
        static readonly (string id, string name, string tip)[] TerrainPresets =
        {
            ("pianura", "Pianura", "Terreno quasi piano con lievi ondulazioni (800 m, dislivello 10 m)"),
            ("colline", "Colline", "Colline dolci con valli che scendono, scavate dall'acqua (1,2 km, dislivello 90 m)"),
            ("valle", "Valle", "Una valle con il fondo piano e i versanti ripidi (1,5 km, dislivello 380 m)"),
            ("montagne", "Montagne", "Montagne con creste, valli e rocce (3 km, dislivello 650 m)"),
            ("dune", "Dune", "Dune di sabbia mosse dal vento (800 m, dislivello 25 m)"),
        };

        async Task LoadTerrain()
        {
            if (_api == null || _terrainLoading) return;
            _terrainLoading = true;
            try
            {
                var l = await _api.Get("terrain/list");
                var first = (l["terrains"] as JsonArray)?.OfType<JsonObject>().FirstOrDefault();
                // (the terrain of the selected zone, if one is selected)
                var sel = (l["terrains"] as JsonArray)?.OfType<JsonObject>()
                    .FirstOrDefault(t => _selection.Contains((string?)t["id"] ?? "") || ((t["zones"] as JsonObject)?.Select(z => (string?)z.Value).Any(i => _selection.Contains(i ?? "")) ?? false));
                var t = sel ?? first;
                _terrain = t == null ? null : await _api.Get("terrain/state?id=" + Uri.EscapeDataString((string?)t["id"] ?? ""));
            }
            catch { _terrain = null; }
            finally { _terrainLoading = false; }
            if (_terrain != null) WatchTerrainTextures();
        }

        JsonObject TerrainParams() => _terrain?["params"] as JsonObject ?? new JsonObject();

        async Task CreateTerrain(JsonObject prm)
        {
            if (_api == null) return;
            SendToWeb(new { type = "busyNow", what = L.T("Terreno") });
            using var busy = BeginBusy();
            JsonObject? r = null;
            await Run(async api => { r = await api.Post("terrain/create", prm); });
            if (r == null) return;
            if (r["history"] is JsonObject h) UpdateHistory(h);
            await RefreshScene();
            await LoadTerrain();
            Status(L.T("Terreno creato: ogni zona è un oggetto a sé (tasto destro o trascinamento per materiali ed ecosistemi)"));
            if (_rightPanel == "landscape") RenderProps();
        }

        async Task UpdateTerrain(JsonObject change)
        {
            if (_api == null || _terrain == null) return;
            await FlushTerrainSculpt(leave: false);         // (1.76.44: strokes still only in the view go first)
            SendToWeb(new { type = "busyNow", what = L.T("Terreno") });
            JsonObject? r = null;
            using (var busy = BeginBusy())
                await Run(async api => { r = await api.Post("terrain/update", new JsonObject { ["id"] = (string?)_terrain["id"], ["params"] = change }); });
            if (r == null) return;
            if (r["history"] is JsonObject h) UpdateHistory(h);
            await ViewNewGeometry(Ids(r["geometry"]), L.T("Terreno"));
            // (1.76.15) the ecosystems on its zones were made again on the new shape: one that could not (the camera
            // no longer sees its surface, nothing fell on it) is said
            var failed = (r["ecosystems"]?["failed"] as JsonArray)?.OfType<JsonObject>().ToList();
            if (failed != null && failed.Count > 0)
                Status(L.F("Ecosistema «{0}» non rifatto sulla nuova forma: {1}", (string?)failed[0]["name"] ?? "", (string?)failed[0]["error"] ?? ""), true);
            await LoadTerrain();
            if (_rightPanel == "landscape") RenderProps();
        }

        /// <summary>The Poly Haven textures of the zones: asked again every 2 s while they download, then put on.
        /// (1.76.9, Luca) From the first moment there is something to wait for, «Occupato · attendi» with «Materiali del
        /// terreno» and the download's progress, and the commands locked: before, the terrain looked finished for tens
        /// of seconds, and a material put on meanwhile could be followed by the standard ones arriving. Esc stops only
        /// the waiting: the materials come by themselves when downloaded (a material chosen meanwhile stays).</summary>
        async void WatchTerrainTextures()
        {
            if (_terrainWatch || _api == null) return;
            _terrainWatch = true;
            try
            {
                for (int i = 0; i < 300; i++)
                {
                    if (_terrain == null) return;
                    var zones = (_terrain["zones"] as JsonObject)?.Select(z => z.Value as JsonObject).Where(z => z != null).ToList() ?? new();
                    // the detail texture of a zone still plain, and (1.76.6) the large texture of a zone that has its detail
                    var states = new List<string>();
                    var fractions = new List<double>();
                    foreach (var z in zones)
                    {
                        if ((bool?)z!["placeholder"] == true && (int?)z["faces"] > 0)
                        {
                            states.Add((string?)z["download"] ?? "none");
                            fractions.Add(Fraction((string?)z["download"], (double?)z["fraction"]));
                        }
                        if ((bool?)z["macroWaiting"] == true && (int?)z["faces"] > 0)
                        {
                            states.Add((string?)z["macroDownload"] ?? "none");
                            fractions.Add(Fraction((string?)z["macroDownload"], (double?)z["macroFraction"]));
                        }
                    }
                    if (states.Count == 0) return;
                    bool ready = states.All(st => st is "done" or "error" or "none");
                    bool toApply = states.Any(st => st == "done");
                    if (ready && !toApply) return;
                    if (!_terrainTexQuiet) TerrainTexBusy(ready ? -1 : fractions.Count > 0 ? fractions.Average() : 0);
                    if (ready)
                    {
                        _terrainTexApplying = true;
                        // (another command of the app still running - the terrain just made being added to the view:
                        // after it, not skipped: before 1.76.9 the materials waited for the next look at the terrain)
                        for (int w = 0; w < 600 && _busyCount > (_terrainTexBusy != null ? 1 : 0); w++) await Task.Delay(100);
                        if (_terrain == null) return;
                        JsonObject? r = null;
                        await Run(async api => { r = await api.Post("terrain/materials", new JsonObject { ["id"] = (string?)_terrain["id"] }); });
                        if (r?["history"] is JsonObject h) UpdateHistory(h);
                        if (_terrainTexBusy != null) TerrainTexBusy(-1);     // (the pill of the engine call took its place)
                        await RefreshScene();
                        foreach (var m in (r?["materials"] as JsonArray ?? new JsonArray()).Select(x => (string?)x ?? "").Where(x => x != "").Distinct())
                            await PushMaterialToViewer(m);
                        await LoadTerrainQuiet();
                        EndTerrainTexBusy();
                        if (_rightPanel == "landscape" && !IsBusy) RenderProps();
                        return;
                    }
                    await Task.Delay(2000);
                    await LoadTerrainQuiet();
                    if (_rightPanel == "landscape" && _busyCount <= (_terrainTexBusy != null ? 1 : 0)) RenderProps();
                }
            }
            finally
            {
                _terrainWatch = false;
                _terrainTexQuiet = false;
                _terrainTexApplying = false;
                EndTerrainTexBusy();
            }
        }

        IDisposable? _terrainTexBusy;
        bool _terrainTexQuiet;             // (Esc: the waiting goes on without the lock)
        bool _terrainTexApplying;          // (the materials being put on: not stopped halfway)

        static double Fraction(string? state, double? f) => state is "done" or "error" or "none" ? 1.0 : Math.Clamp(f ?? 0, 0, 1);

        /// <summary>«Occupato · attendi · Materiali del terreno» with the commands locked; <paramref name="f"/> &lt; 0:
        /// downloaded, being put on.</summary>
        void TerrainTexBusy(double f)
        {
            _terrainTexBusy ??= BeginBusy();
            ShowTask(L.T("Materiali del terreno…"));
            SendToWeb(new
            {
                type = "task", text = L.T("Materiali del terreno…"), fraction = f < 0 ? (double?)null : f,
                detail = f < 0 ? L.T("applico i materiali") : L.F("scarico le texture {0}%", Math.Round(f * 100)) + " · " + L.T("Esc: continua senza aspettare"),
            });
        }

        void EndTerrainTexBusy()
        {
            if (_terrainTexBusy == null) return;
            _terrainTexBusy.Dispose();
            _terrainTexBusy = null;
            HideTask();
        }

        /// <summary>Esc while only the textures of the terrain are awaited: the commands free again, the materials come
        /// by themselves when downloaded.</summary>
        bool SkipTerrainTexWait()
        {
            if (_terrainTexBusy == null || _terrainTexApplying || _busyCount > 1) return false;
            _terrainTexQuiet = true;
            EndTerrainTexBusy();
            Status(L.T("I materiali del terreno arriveranno da soli appena scaricate le texture (un materiale scelto nel frattempo resta)"));
            return true;
        }

        /// <summary>(1.76.4) The materials of zones of a terrain to the view (their border blend changed): the slots
        /// as the engine has them now, matched by the names the view has (the scene list before it is read again).</summary>
        async Task PushZoneMaterials(System.Collections.Generic.List<string> ids)
        {
            if (_api == null || ids.Count == 0) return;
            JsonObject? rm = null;
            try { rm = await _api.Post("realtime/materials", new { ids }); } catch { return; }
            if (rm?["objects"] is not JsonObject objs) return;
            var items = new System.Collections.Generic.List<object>();
            foreach (var id in ids)
            {
                if (objs[id] is not JsonArray slots) continue;
                _scene.ById.TryGetValue(id, out var o);
                var arr = new JsonArray();
                for (int i = 0; i < slots.Count; i++)
                {
                    var sl = (JsonObject)slots[i]!.DeepClone();
                    sl["old"] = o == null ? (string?)sl["name"] : i < o.Materials.Count ? o.Materials[i] : null;
                    arr.Add(sl);
                }
                items.Add(new { id, slots = arr });
            }
            if (items.Count > 0) SendToWeb(new { type = "materials", items = items.ToArray() });
            await RefreshScene();
        }

        async Task SetTerrainBlend(JsonObject change)
        {
            if (_api == null || _terrain == null) return;
            if (!((bool?)_terrain["blendReady"] ?? true))
            {
                await UpdateTerrain(new JsonObject());        // (a terrain of 1.76.3 or before: made again with the distances)
                if (_terrain == null) return;
            }
            change["id"] = (string?)_terrain["id"];
            JsonObject? r = null;
            using (var busy = BeginBusy())
                await Run(async api => { r = await api.Post("terrain/blend", change); });
            if (r == null) return;
            if (r["history"] is JsonObject h) UpdateHistory(h);
            await LoadTerrainQuiet();
            if (_rightPanel == "landscape") RenderProps();
        }

        /// <summary>(1.76.14) «Colori dal terreno»: materials only; a terrain made before has no data for them - made
        /// again first.</summary>
        async Task SetTerrainTone(JsonObject change)
        {
            if (_api == null || _terrain == null) return;
            if (!((bool?)_terrain["toneReady"] ?? true))
            {
                await UpdateTerrain(new JsonObject());
                if (_terrain == null) return;
            }
            change["id"] = (string?)_terrain["id"];
            JsonObject? r = null;
            using (var busy = BeginBusy())
                await Run(async api => { r = await api.Post("terrain/tone", change); });
            if (r == null) return;
            if (r["history"] is JsonObject h) UpdateHistory(h);
            await LoadTerrainQuiet();
            if (_rightPanel == "landscape") RenderProps();
        }

        // ---- (1.76.53, Luca: «un'altra scheda dedicata che chiamerei "Rilievo 3D" con dentro tutto, miniature comprese»)
        // The relief of the rock in the shading of the path tracing (1.76.40 «Rilievo della roccia»: now «Attuale»), in
        // kinds with a picture each. The numbers are set on the materials in place (no wait); the kind makes them again.
        static readonly (string id, string name, string tip)[] ReliefKinds =
        {
            // (1.76.54, Luca: «rinominerei current... decidi un ordine») the mixed one first (the default), then from the
            // softest to the most angular
            ("attuale", "Roccia mista", "Il rilievo di sempre, tutto insieme: cenge degli strati, canaloni che scendono lungo la parete e roccia spaccata in blocchi"),
            ("canaloni", "Canaloni erosi", "La parete scavata dall'acqua: canaloni che scendono dritti, speroni affilati fra l'uno e l'altro, canali più piccoli che si diramano e rigagnoli fini"),
            ("cenge", "Strati a cenge", "Gli strati della roccia (gli stessi di «Roccia scolpita» e delle fasce di colore) come cenge marcate: una mensola, poi un salto, strato dopo strato, strati duri e teneri alternati, i salti consumati in striature"),
            ("fratture", "Parete fratturata", "La parete rotta in blocchi spigolosi di misure diverse, ognuno con la sua faccia piana inclinata a modo suo: la luce si spezza blocco per blocco, con crepe sottili dentro i blocchi"),
            ("nessuno", "Nessuno", "Pareti lisce: nessun rilievo nello shading (la forma del terreno resta quella)"),
        };

        void RenderReliefCard(StackPanel card)
        {
            var t = _terrain?["tone"] as JsonObject;
            var prm = TerrainParams();
            // (1.76.54, Luca: «voglio che siano usati per modificare la maglia della roccia») the kind is in the shape
            // of the rock (the terrain's params) and in the light on it; «Nessuno» only in the light
            var kind = (string?)prm["rockKind"] ?? (string?)t?["rtype"] ?? "attuale";
            double depth = (double?)t?["relief"] ?? 0.5;
            if (depth <= 0 || (string?)t?["rtype"] == "nessuno") kind = "nessuno";
            card.Children.Add(HintSmall(L.T("La forma della roccia sulle pareti ripide: canaloni, blocchi e cenge veri nella maglia del terreno (dove agisce «Roccia scolpita»), e il dettaglio più fine nella luce del path tracing. Scegli il tipo:")));
            // (1.76.58, Luca: «true displacement deve avere anche l'opzione per caricare una displacement») a relief map
            // of one's own replaces the kind in the light and in «Displacement vero»; the colour map of its set, just under
            var maps = _terrain?["reliefMaps"] as JsonObject;
            bool hasMap = maps?["rmap"] is JsonObject, hasCol = maps?["rcolor"] is JsonObject;
            var grid = new UniformGrid { Columns = 5, Margin = new Thickness(0, 8, -6, 2) };
            if (hasMap) grid.Opacity = 0.55;
            foreach (var (id, name, tip) in ReliefKinds)
            {
                var kid = id;
                grid.Children.Add(WeatherTile(WeatherIcon("relief", id), null, L.T(name), kind == id && !hasMap, L.T(tip), async () =>
                {
                    if (hasMap && kid != "nessuno") { await SetTerrainTone(new JsonObject { ["rmap"] = "" }); if (kid == kind) return; }
                    if (kid == kind) return;
                    if (kid == "nessuno") { await SetTerrainTone(new JsonObject { ["rtype"] = "nessuno" }); return; }
                    if (depth <= 0) await SetTerrainTone(new JsonObject { ["relief"] = 0.5 });    // (from 0%: the default depth)
                    // (the shape of the rock made again: the terrain recomputed, as with «Roccia scolpita»)
                    await UpdateTerrain(new JsonObject { ["rockKind"] = kid });
                }));
            }
            card.Children.Add(grid);
            ReliefMapRow(card, L.T("Mappa di rilievo"), "rmap", "rmapFile", maps,
                         L.T("Una mappa di rilievo (displacement, in bianco e nero) al posto del tipo scelto: bianco sporge, nero rientra, grigio 50% resta com'è. Vale nella luce e, con «Displacement vero», nella geometria del render finale. Togliendola torna il tipo"), kind, depth);
            ReliefMapRow(card, L.T("Mappa colore"), "rcolor", "rcolorFile", maps,
                         L.T("Facoltativa: la texture colore dello stesso set della mappa di rilievo. Sulle pareti della zona Roccia prende il posto del colore del materiale (quanto: «Colore dalla mappa»), così le crepe scure cadono proprio nelle crepe del rilievo. Prati, neve e ghiaioni restano del loro materiale"), kind, depth);
            if (hasMap) card.Children.Add(HintSmall(L.T("La mappa di rilievo sostituisce il tipo: scegli un tipo per tornare ai rilievi preparati.")));
            if (kind == "nessuno") return;
            if (hasMap || hasCol)
            {
                double rms = (double?)t?["rmsize"] ?? 10.0, rmr = (double?)t?["rmrot"] ?? 0.0, rca = (double?)t?["rcamt"] ?? 1.0;
                // (1.76.59, Luca: «due size non vanno bene descrivi meglio») the map's own, in metres, apart from the shapes'
                var gs = new ValueSlider(L.T("Grandezza della mappa"), rms, 0.5, 500, true, "0.#", "m", null,
                  L.T("Quanti metri di parete copre una ripetizione delle tue mappe (rilievo e colore), in metri veri: 50 m = l'immagine intera disegnata su 50 m di roccia. Più grande = crepe e gradini più grandi e un rilievo più alto. Non cambia la forma vera della roccia nella maglia (quella è «Dimensione delle forme»). Si cambia subito"));
                gs.Committed += async x => await SetTerrainTone(new JsonObject { ["rmsize"] = Math.Round(x, 2) });
                card.Children.Add(gs);
                var rs = new ValueSlider(L.T("Rotazione"), rmr, -180, 180, false, "0", "°", null,
                  L.T("Gira le mappe sulla parete: per disegnare gli strati e le fratture con l'inclinazione che vuoi (0° = come nell'immagine). Vale allo stesso modo su tutte le pareti. Si cambia subito"));
                rs.Committed += async x => await SetTerrainTone(new JsonObject { ["rmrot"] = Math.Round(x) });
                card.Children.Add(rs);
                if (hasCol)
                    R(card, L.T("Colore dalla mappa"), rca * 100, 0, 100, false, "%",
                      L.T("Quanto il colore della mappa prende il posto del colore del materiale sulle pareti: 100% = il colore del set, 0% = il colore del materiale. I colori dal terreno (creste, canali, strati) restano sopra. Si cambia subito"),
                      x => new JsonObject { ["rcamt"] = Math.Round(x, 1) / 100.0 });
            }
            ValueSlider R(Panel to, string label, double v, double min, double max, bool log, string unit, string tip, Func<double, JsonObject> change)
            {
                var s = new ValueSlider(label, v, min, max, log, "0", unit, null, tip);
                s.Committed += async x => await SetTerrainTone(change(x));
                to.Children.Add(s);
                return s;
            }
            R(card, L.T("Profondità"), depth * 100, 0, 100, false, "%",
              L.T("Quanto il rilievo si sente nella luce: 0% = pareti lisce. Si cambia subito, senza rifare i materiali"), x => new JsonObject { ["relief"] = Math.Round(x, 1) / 100.0 });
            double rsize = (double?)prm["rockSize"] ?? (double?)t?["rsize"] ?? 1.0;
            var sz = new ValueSlider(L.T("Dimensione delle forme"), rsize * 100, 25, 400, true, "0", "%", null,
              L.T("Quanto sono grandi canaloni, blocchi e cenge del tipo scelto, rispetto allo spessore degli strati di roccia (Forma e roccia): 100% = come lo spessore, 200% = il doppio. Cambia la forma vera della roccia nella maglia del terreno (il terreno si ricalcola) e, senza una mappa tua, anche il dettaglio nella luce. Con una mappa caricata, la grandezza della mappa è «Grandezza della mappa»"));
            sz.Committed += async x => await UpdateTerrain(new JsonObject { ["rockSize"] = Math.Round(x, 1) / 100.0 });
            card.Children.Add(sz);
            double rdet = (double?)t?["rdetail"] ?? 0.5;
            R(card, L.T("Dettaglio"), rdet * 100, 0, 100, false, "%",
              L.T("Quanti dettagli piccoli dentro le forme grandi: rigagnoli, crepe, roccia rotta. 50% = il dettaglio di sempre; sopra il 50% si aggiunge una grana fine di roccia spaccata. Si cambia subito"), x => new JsonObject { ["rdetail"] = Math.Round(x, 1) / 100.0 });
            double rwh = (double?)t?["rwhere"] ?? 0.5;
            R(card, L.T("Dove"), rwh * 100, 0, 100, false, "%",
              L.T("Su quali facce: 0% = solo le pareti più ripide, 50% = le pareti (come sempre), 100% = anche i pendii meno ripidi. Si cambia subito"), x => new JsonObject { ["rwhere"] = Math.Round(x, 1) / 100.0 });
            var adv = Advanced(card, "terrainRelief");
            double ror = (double?)prm["rockOrient"] ?? (double?)t?["rorient"] ?? 0.0;
            var orS = new ValueSlider(L.T("Orientamento"), ror, -90, 90, false, "0", "°", null,
              L.T("Per «Parete fratturata»: la direzione delle fratture, girata intorno alla verticale (le fratture di una parete vera seguono le stesse direzioni su tutta la montagna). Gli altri tipi seguono la pendenza o gli strati. Cambia la forma vera della roccia: il terreno si ricalcola"));
            orS.Committed += async x => await UpdateTerrain(new JsonObject { ["rockOrient"] = Math.Round(x) });
            adv.Body.Children.Add(orS);
            bool ranti = (bool?)t?["rmanti"] ?? false;
            if (hasMap || hasCol)
            {
                var at = new Toggle(L.T("Rompi la ripetizione"), ranti,
                  L.T("Per le mappe di rilievo e colore: le sposta a caso a zone, così su una montagna intera non si vede la stessa immagine ripetuta in fila. Non le gira: la Rotazione scelta resta. Solo nel path tracing e nel render finale"));
                at.Toggled += async v => await SetTerrainTone(new JsonObject { ["rmanti"] = v });
                adv.Body.Children.Add(at);
            }
            // (1.76.55, Luca: «metterei in avanzate il displacement, spento di default, se acceso messagebox che indica
            // che i tempi di elaborazione si allungano») the same relief made real geometry, only in the final render
            bool rdisp = (bool?)t?["rdisp"] ?? false;
            var dsw = new Toggle(L.T("Displacement vero"), rdisp,
              L.T("Solo nel render finale, il rilievo della roccia diventa geometria vera: le crepe, i gradini e i bordi dei blocchi sporgono davvero, si vedono di profilo e fanno ombra. Spento: lo stesso rilievo resta solo nella luce, più veloce. La vista in tempo reale non cambia. Il render finale richiede più tempo e più memoria"));
            dsw.Toggled += async v =>
            {
                if (v && Msg.Show(this, L.T("Con il displacement vero il rilievo della roccia diventa geometria nel render finale: è più bello di profilo e nelle ombre, ma il render finale richiede più tempo (anche il doppio) e più memoria. La vista in tempo reale non cambia.\n\nVuoi attivarlo?"),
                        "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Warning) != MessageBoxResult.Yes)
                {
                    dsw.SetQuiet(false);
                    return;
                }
                await SetTerrainTone(new JsonObject { ["rdisp"] = v });
            };
            adv.Body.Children.Add(dsw);
            double ramp = (double?)t?["ramp"] ?? 1.0, rfine = (double?)t?["rfine"] ?? 0.5;
            if (rdisp)
            {
                R(adv.Body, L.T("Ampiezza"), ramp * 100, 0, 200, false, "%",
                  L.T("Quanto sporge la roccia vera, rispetto al rilievo che si vede nella luce: 100% = la stessa profondità, 200% = il doppio, 0% = niente geometria. Agisce insieme a Profondità. Si cambia subito, senza rifare i materiali"),
                  x => new JsonObject { ["ramp"] = Math.Round(x, 1) / 100.0 });
                R(adv.Body, L.T("Finezza"), rfine * 100, 0, 100, false, "%",
                  L.T("Quanto sono piccoli i triangoli della geometria vera: 0% = più grandi (più veloce), 50% = il giusto, 100% = i più piccoli (il più lento e con più memoria). Lontano dalla camera i triangoli crescono da soli; a ogni risoluzione del render il costo resta lo stesso"),
                  x => new JsonObject { ["rfine"] = Math.Round(x, 1) / 100.0 });
            }
            bool dispSet = rdisp || Math.Abs(ramp - 1.0) > 1e-3 || Math.Abs(rfine - 0.5) > 1e-3;
            adv.Done(Math.Abs(ror) > 0.5 || rdisp || ranti, async () =>
            {
                if (dispSet || ranti) await SetTerrainTone(new JsonObject { ["rdisp"] = false, ["ramp"] = 1.0, ["rfine"] = 0.5, ["rmanti"] = false });
                if (Math.Abs(ror) > 0.5) await UpdateTerrain(new JsonObject { ["rockOrient"] = 0 });
            });
        }

        /// <summary>(1.76.58) A map of «Rilievo 3D»: its picture, its file, «Carica…» and «×».</summary>
        void ReliefMapRow(Panel parent, string label, string key, string fileKey, JsonObject? maps, string tip, string kind, double depth)
        {
            var info = maps?[key] as JsonObject;
            var image = (string?)info?["image"] ?? "";
            var row = new DockPanel { Margin = new Thickness(0, 6, 0, 4), ToolTip = tip };
            var l = Theme.Label(label, 12, Theme.TextMuted);
            l.Width = 110;
            l.VerticalAlignment = VerticalAlignment.Center;
            row.Children.Add(l);
            var thumb = new Border { Width = 34, Height = 34, CornerRadius = new CornerRadius(4), Background = Theme.B(Theme.Inset),
                                     BorderBrush = Theme.B(Theme.Line), BorderThickness = new Thickness(1), Margin = new Thickness(0, 0, 8, 0) };
            row.Children.Add(thumb);
            var load = Theme.Button(image == "" ? L.T("Carica…") : L.T("Cambia…"), Theme.Kind.Normal, L.T("Scegli un'immagine (PNG, JPG, EXR, TIFF…)"));
            load.MinHeight = 28; load.FontSize = 12; load.Padding = new Thickness(8, 0, 8, 0);
            DockPanel.SetDock(load, Dock.Right);
            row.Children.Add(load);
            if (image != "")
            {
                var rm = Theme.Button("×", Theme.Kind.Ghost, L.T("Togli la mappa"));
                rm.MinHeight = 28; rm.Padding = new Thickness(8, 0, 8, 0);
                rm.Click += async (_, __) => await SetTerrainTone(new JsonObject { [key] = "" });
                DockPanel.SetDock(rm, Dock.Right);
                row.Children.Add(rm);
            }
            var file = (string?)info?["file"] ?? "";
            var name = image == "" ? L.T("nessuna mappa") : (file != "" ? System.IO.Path.GetFileName(file) : image) + (((bool?)info?["missing"] ?? false) ? "  " + L.T("(file mancante)") : "");
            var fn = Theme.Label(name, 12, image == "" ? Theme.TextFaint : Theme.TextSoft);
            fn.VerticalAlignment = VerticalAlignment.Center;
            fn.TextTrimming = TextTrimming.CharacterEllipsis;
            fn.ToolTip = file != "" ? file : tip;
            row.Children.Add(fn);
            load.Click += async (_, __) =>
            {
                var dlg = new Microsoft.Win32.OpenFileDialog { Filter = L.T(ImageFilter), InitialDirectory = StartFolder("image") };
                if (dlg.ShowDialog(this) != true) return;
                Keep("image", dlg.FileName);
                var ch = new JsonObject { [fileKey] = dlg.FileName };
                if (kind == "nessuno") ch["rtype"] = "attuale";          // (a map asks for a relief: not «Nessuno»)
                if (depth <= 0) ch["relief"] = 0.5;
                await SetTerrainTone(ch);
            };
            parent.Children.Add(row);
            if (image != "") _ = LoadThumb(image, thumb);
        }

        async Task LoadTerrainQuiet()
        {
            if (_api == null || _terrain == null) return;
            try { _terrain = await _api.Get("terrain/state?id=" + Uri.EscapeDataString((string?)_terrain["id"] ?? "")); } catch { }
        }

        static Border TerrainTile(string id, string name, string tip, bool on, Func<Task> click)
        {
            var (top, bottom) = id switch
            {
                "pianura" => ("#B9CF8A", "#6C8F3E"),
                "colline" => ("#9CC27A", "#4E7A33"),
                "valle" => ("#8FB7C9", "#4D7A3E"),
                "montagne" => ("#C9D2DA", "#5C6670"),
                "dune" => ("#F0C98A", "#B07A3C"),
                _ => ("#9CC27A", "#4E7A33"),
            };
            var swatch = new Border
            {
                Height = 34, CornerRadius = new CornerRadius(6), Background = new LinearGradientBrush(Theme.C(top), Theme.C(bottom), 90),
                Child = Theme.Icon(id == "dune" ? WavesSoft : Mountain, Theme.C("#FFFFFF"), 18, 1.7),
            };
            var label = new TextBlock
            {
                Text = name, FontSize = 11, Margin = new Thickness(0, 5, 0, 0), TextAlignment = TextAlignment.Center,
                TextTrimming = TextTrimming.CharacterEllipsis, Foreground = Theme.B(on ? Theme.Text : Theme.TextMuted),
                FontWeight = on ? FontWeights.SemiBold : FontWeights.Normal,
            };
            var sp = new StackPanel();
            sp.Children.Add(swatch);
            sp.Children.Add(label);
            var idle = Theme.B(on ? Theme.Accent : Theme.Line);
            var tile = new Border
            {
                Child = sp, Padding = new Thickness(4), Margin = new Thickness(0, 0, 6, 6), CornerRadius = new CornerRadius(9),
                BorderThickness = new Thickness(on ? 1.5 : 1), BorderBrush = idle, Cursor = Cursors.Hand,
                Background = Theme.B(on ? Theme.Selected : Theme.Inset), ToolTip = tip,
            };
            tile.MouseEnter += (_, __) => { if (!on) tile.BorderBrush = Theme.B(Theme.LineStrong); };
            tile.MouseLeave += (_, __) => tile.BorderBrush = idle;
            tile.MouseLeftButtonUp += async (_, e) => { e.Handled = true; await click(); };
            return tile;
        }

        // ---- (1.76.44, Luca: «il pennello per alzare e abbassare la geometria del terreno») «Scultura»: the brush of
        // the puddles with layer "terrain". The view deforms the zones at once (viewer.js terrainDab); the strokes come
        // to the engine only when the tool is left (switched off, another panel, path tracing, final render, save):
        // terrain/update {sculptAdd}, one undo step, «Occupato · attendi» only then (Luca: «non un'interruzione
        // continua ma fatto solo alla fine»).
        string _tsTool = "raise";
        double _tsRadius = 20, _tsStrength = 0.3, _tsSoft = 0.7;
        int _tsPending;
        Action? _tsRadiusChanged;
        TaskCompletionSource<bool>? _tsCommit;
        static readonly Geometry TsRaise = MakeGeometry("M3 20h18 M5.5 20c1.6-3.6 3.8-5.5 6.5-5.5s4.9 1.9 6.5 5.5 M12 12V3 M8.8 6.2 12 3l3.2 3.2");
        static readonly Geometry TsLower = MakeGeometry("M3 14h3.5c1.6 3.4 3.4 5.5 5.5 5.5s3.9-2.1 5.5-5.5H21 M12 3v8.5 M8.8 8.3 12 11.5l3.2-3.2");
        static readonly Geometry TsSmooth = MakeGeometry("M3 9.5c1.5-3 2.5 3 4.5 0s3 3 4.5 0 3 3 4.5 0 2.5 3 4.5 0 M3 17.5c6-2 12-2 18 0");
        static readonly Geometry TsSculpt = MakeGeometry("M2 20 8.5 10l4 5.5 2.5-3L22 20z M14 4.5l5.5 5.5 M15.6 2.9l1.6 1.6-6 6-2.2.6.6-2.2z");

        List<string> TerrainZoneIds() =>
            (_terrain?["zones"] as JsonObject)?.Select(z => (string?)(z.Value as JsonObject)?["id"] ?? "").Where(i => i != "").ToList() ?? new();

        /// <summary>The strokes of a session of «Scultura» to the engine: the terrain made again with them, once.</summary>
        async Task CommitTerrainSculpt(JsonArray? strokes)
        {
            _tsPending = 0;
            try
            {
                if (strokes != null && strokes.Count > 0 && _terrain != null)
                {
                    AppLog.Write($"terrain sculpt: {strokes.Count} strokes to the engine");
                    await UpdateTerrain(new JsonObject { ["sculptAdd"] = strokes.DeepClone() });
                }
            }
            finally
            {
                _tsCommit?.TrySetResult(true);
            }
        }

        /// <summary>Before the path tracing, the final render or a save: the strokes still only in the view go to the
        /// engine first (and the tool is left, except for a save).</summary>
        async Task FlushTerrainSculpt(bool leave = true)
        {
            if (!(_puddleBrush && _brushLayer == "terrain")) return;
            if (_tsPending == 0 && !leave) return;
            var tcs = _tsPending > 0 ? (_tsCommit = new TaskCompletionSource<bool>()) : null;
            if (leave)
            {
                _puddleBrush = false;
                SendPuddleBrush();
                if (_rightPanel == "landscape") RenderProps();
            }
            else SendToWeb(new { type = "terrainSculptFlush" });
            if (tcs != null)
            {
                // (the strokes come from the view in a moment; the terrain made again can take a while)
                var first = await Task.WhenAny(tcs.Task, Task.Delay(300000));
                if (first != tcs.Task) AppLog.Write("terrain sculpt: the strokes did not come from the view");
            }
        }

        void RenderTerrainCard()
        {
            var card = new StackPanel();
            var title = SectionTitle(L.T("Terreno"));
            title.DataContext = (Mountain, TerrainColor);
            card.Children.Add(title);
            _props.Children.Add(Theme.Card(card, 16));
            var prm = TerrainParams();
            var cur = _terrain == null ? "" : ((string?)prm["heightmap"] ?? "") != "" ? "mappa" : (string?)prm["preset"] ?? "";

            if (_terrain == null)
                card.Children.Add(HintSmall(L.T("Un terreno vero intorno alla scena: valli scavate dall'acqua, creste, rocce dove è ripido. Ogni zona (prato, roccia…) è un oggetto a sé: puoi darle un materiale o un ecosistema. Scegli il tipo:")));
            var grid = new UniformGrid { Columns = 5, Margin = new Thickness(0, 6, 0, 4) };
            foreach (var (id, name, tip) in TerrainPresets)
            {
                var pid = id;
                grid.Children.Add(TerrainTile(id, L.T(name), L.T(tip), cur == id, async () =>
                {
                    if (_terrain == null) await CreateTerrain(new JsonObject { ["preset"] = pid });
                    else if (cur != pid) await UpdateTerrain(new JsonObject { ["preset"] = pid, ["size"] = null, ["height"] = null, ["heightmap"] = "" });
                }));
            }
            card.Children.Add(grid);
            if (_terrain == null)
            {
                var hm = Theme.Button(L.T("Da una mappa di altezze…"), Theme.Kind.Ghost, L.T("Un'immagine in scala di grigi (PNG a 16 bit, TIFF, EXR, RAW): nero il punto più basso, bianco il più alto. Oppure un file di quote vero (USGS .dem, SRTM .hgt, ESRI .asc): con la sua larghezza e il suo dislivello reali"));
                hm.HorizontalAlignment = HorizontalAlignment.Left;
                hm.Click += async (_, __) =>
                {
                    var f = PickHeightmap();
                    if (f == null) return;
                    var body = await WithDemPart(f, new JsonObject { ["heightmap"] = f, ["size"] = 1000.0, ["hmHeight"] = 100.0 });
                    if (body != null) await CreateTerrain(body);
                };
                card.Children.Add(hm);
                card.Children.Add(HintSmall(L.T("Il calcolo richiede da qualche secondo a mezzo minuto.")));
                return;
            }

            double P(string k, double d) => (double?)prm[k] ?? d;
            bool B(string k, bool d) => (bool?)prm[k] ?? d;
            var flat = prm["flat"] as JsonObject ?? new JsonObject();
            var info = _terrain;
            double size = (double?)prm["size"] ?? DefaultTerrainSize(cur);
            double height = (double?)prm["height"] ?? DefaultTerrainHeight(cur);
            ValueSlider S(Panel to, string label, double v, double min, double max, bool log, string fmt, string unit, string tip, Func<double, JsonObject> change)
            {
                var s = new ValueSlider(label, v, min, max, log, fmt, unit, null, tip);
                s.Committed += async x => await UpdateTerrain(change(x));
                to.Children.Add(s);
                return s;
            }
            // (1.76.41, Luca: «guarda quante opzioni! raggruppale con macro voci come pietre e detriti») the terrain in
            // five sections, each with its own Avanzate: the terrain itself, its shape and rock, the zones, the colours
            // from the land, the flat area and the edge
            var mainCard = card;
            StackPanel Section2(string t, Geometry icon, Color col)
            {
                var c = new StackPanel();
                var tt = SectionTitle(t);
                tt.DataContext = (icon, col);
                c.Children.Add(tt);
                _props.Children.Add(Theme.Card(c, 16));
                return c;
            }
            var shapeCard = Section2(L.T("Forma e roccia"), Mountain, Color.FromRgb(0xA8, 0x9C, 0x8A));
            var reliefCard = Section2(L.T("Rilievo 3D"), Icons.Relief, Color.FromRgb(0xB8, 0xA4, 0x8C));
            var sculptCard = Section2(L.T("Scultura"), TsSculpt, Color.FromRgb(0xD9, 0xC0, 0x8A));
            var zonesCard = Section2(L.T("Zone del terreno"), Icons.Layers, TerrainColor);
            var toneCard = Section2(L.T("Colori dal terreno"), Icons.Palette, Color.FromRgb(0xD8, 0xA0, 0x5A));
            var flatCard = Section2(L.T("Spianata e bordi"), Icons.Grid, Color.FromRgb(0x8C, 0xB4, 0xD8));
            if (cur == "mappa")
            {
                S(card, L.T("Dimensione"), size, 50, 8000, true, "0", "m", L.T("Larghezza del terreno (la mappa è quadrata)"), x => new JsonObject { ["size"] = x });
                S(card, L.T("Dislivello"), P("hmHeight", 100), 1, 3000, true, "0", "m", L.T("Dal nero (punto più basso) al bianco (più alto)"), x => new JsonObject { ["hmHeight"] = x });
            }
            else
            {
                S(card, L.T("Dimensione"), size, 100, 6000, true, "0", "m", L.T("Larghezza del terreno"), x => new JsonObject { ["size"] = x });
                S(card, L.T("Dislivello"), height, 2, 2000, true, "0", "m", L.T("Dal punto più basso al più alto"), x => new JsonObject { ["height"] = x });
                var again = Theme.Button(Theme.IconText(Icons.Refresh, L.T("Un'altra versione"), null, 13), Theme.Kind.Ghost, L.T("Lo stesso tipo di terreno con un'altra forma"));
                again.HorizontalAlignment = HorizontalAlignment.Left; again.Margin = new Thickness(0, 0, 0, 10);
                again.Click += async (_, __) => await UpdateTerrain(new JsonObject { ["seed"] = (int)P("seed", 1) + 1 });
                card.Children.Add(again);
            }
            // (1.76.10) the rock cut into ledges, gullies and broken crests (terrains made before: 0, unchanged)
            var rock = _terrain["rock"] as JsonObject;
            double rocky = (double?)rock?["rocky"] ?? 0;
            card = shapeCard;
            S(card, L.T("Roccia scolpita"), rocky * 100, 0, 100, false, "0", "%",
              L.T("Pareti a cenge e salti, canaloni, creste frastagliate sui pendii ripidi: 0% = forme morbide e consumate"), x => new JsonObject { ["rocky"] = x / 100.0 });
            S(card, L.T("Pendenza della roccia"), P("rockSlope", DefaultRock(cur)), 15, 70, false, "0", "°", L.T("Più ripido di così è roccia: abbassalo per più pareti di roccia, alzalo per più prato sui pendii"), x => new JsonObject { ["rockSlope"] = x });
            RenderReliefCard(reliefCard);
            card = zonesCard;
            var snow = new Toggle(L.T("Neve in quota"), B("snow", false), L.T("Neve sulle parti alte, nelle conche e non sulle pareti ripide"));
            snow.Toggled += async v => await UpdateTerrain(new JsonObject { ["snow"] = v });
            card.Children.Add(snow);
            if (B("snow", false))
                S(card, L.T("Quota della neve"), P("snowHeight", 0.75) * 100, 10, 98, false, "0", "%", L.T("Da che altezza c'è neve, rispetto al dislivello"), x => new JsonObject { ["snowHeight"] = x / 100.0 });
            // (1.76.4) the border between two zones blended in the materials (no ecosystem needed)
            var bl = _terrain["blend"] as JsonObject;
            var bw = (double?)bl?["width"] ?? 2.5;
            var bws = new ValueSlider(L.T("Sfumatura dei bordi"), bw, 0, 5, false, "0.0", "m", null,
                L.T("Dove due zone si toccano i materiali si mescolano: la ghiaia esce dall'erba, l'erba resta fra i sassi, con un bordo irregolare. Quanto in là può arrivare un materiale nell'altro; 0 = bordo netto"));
            bws.Committed += async v => await SetTerrainBlend(new JsonObject { ["width"] = Math.Round(v, 2) });
            card.Children.Add(bws);
            card = flatCard;
            var fon = new Toggle(L.T("Spianata intorno al modello"), (bool?)flat["on"] ?? true, L.T("Un'area piana alla quota 0, dove sta il modello, che si raccorda morbida al terreno"));
            fon.Toggled += async v => await UpdateTerrain(new JsonObject { ["flat"] = new JsonObject { ["on"] = v } });
            card.Children.Add(fon);
            if ((bool?)flat["on"] ?? true)
            {
                S(card, L.T("Raggio della spianata"), (double?)flat["radius"] ?? 30, 2, 1000, true, "0", "m", L.T("Quanto è grande l'area piana"), x => new JsonObject { ["flat"] = new JsonObject { ["radius"] = x } });
                var here = Theme.Button(L.T("Centra sulla selezione"), Theme.Kind.Ghost, L.T("La spianata va sotto l'oggetto selezionato"));
                here.HorizontalAlignment = HorizontalAlignment.Left; here.Margin = new Thickness(0, 0, 0, 10);
                here.IsEnabled = _selection.Count > 0;
                here.Click += async (_, __) =>
                {
                    if (_selection.Count == 0 || !_scene.ById.TryGetValue(_selection.First(), out var so)) return;
                    await UpdateTerrain(new JsonObject { ["flat"] = new JsonObject { ["x"] = so.Location[0] / 100.0, ["y"] = so.Location[1] / 100.0 } });
                };
                card.Children.Add(here);
            }

            // the zones: each one an object (select it to give it a material or an ecosystem). (1.76.8) «Dividi»: a zone
            // split in two by the ground itself (wet hollows, the side in the sun, high pastures...); the parts follow
            // the terrain when it is made again, each with its own material
            card = zonesCard;
            card.Children.Add(Theme.Label(L.T("Zone"), 12, Theme.TextMuted, FontWeights.SemiBold));
            var zonesObj = _terrain["zones"] as JsonObject ?? new JsonObject();
            var splits = prm["splits"] as JsonArray ?? new JsonArray();
            int maxZones = (int?)_terrain["maxZones"] ?? 16;
            int depthOf(string key)
            {
                int d = 0;
                var k = key;
                while (d < 16 && zonesObj[k] is JsonObject zo && ((string?)zo["parent"] ?? "") != "") { k = (string?)zo["parent"] ?? ""; d++; }
                return d;
            }
            // the parts listed under the zone they come from
            var ordered = new List<string>();
            void addWithChildren(string key)
            {
                ordered.Add(key);
                foreach (var c in zonesObj.Where(c => c.Value is JsonObject co && (string?)co["parent"] == key).Select(c => c.Key).ToList())
                    addWithChildren(c);
            }
            foreach (var z in zonesObj.Where(z => z.Value is JsonObject zo && ((string?)zo["parent"] ?? "") == "").Select(z => z.Key).ToList())
                addWithChildren(z);
            foreach (var key in ordered)
            {
                if (zonesObj[key] is not JsonObject zi) continue;
                var sp = zi["split"] as JsonObject;
                if (((int?)zi["faces"] ?? 0) == 0 && sp == null) continue;
                var depth = depthOf(key);
                var row = new DockPanel { Margin = new Thickness(14 * depth, 4, 0, 0) };
                var sel = Theme.Button(L.T("Seleziona"), Theme.Kind.Ghost, L.T("Seleziona la zona: poi trascinaci un materiale o un ecosistema"));
                sel.MinHeight = 24; sel.FontSize = 11.5; sel.Padding = new Thickness(8, 0, 8, 0);
                var zid = (string?)zi["id"] ?? "";
                sel.Click += (_, __) => Select(zid);
                DockPanel.SetDock(sel, Dock.Right);
                row.Children.Add(sel);
                if (zonesObj.Count < maxZones && ((int?)zi["faces"] ?? 0) > 0)
                {
                    var div = Theme.Button(L.T("Dividi"), Theme.Kind.Ghost, L.T("Divide la zona in due seguendo il terreno: la parte nuova ha un suo materiale"));
                    div.MinHeight = 24; div.FontSize = 11.5; div.Padding = new Thickness(8, 0, 8, 0);
                    var parentKey = key;
                    div.Click += (_, __) => ShowSplitMenu(div, parentKey, splits);
                    DockPanel.SetDock(div, Dock.Right);
                    row.Children.Add(div);
                }
                var st = (string?)zi["download"] ?? "";
                var note = (bool?)zi["placeholder"] == true
                    ? st == "running" ? L.F(" · scarico la texture {0}%", Math.Round(((double?)zi["fraction"] ?? 0) * 100)) : st == "error" ? L.T(" · texture non scaricata") : ""
                    : "";
                var t = Theme.Label(((string?)zi["name"] ?? key) + note, 12, Theme.TextSoft);
                t.VerticalAlignment = VerticalAlignment.Center;
                t.TextTrimming = TextTrimming.CharacterEllipsis;
                t.ToolTip = (string?)zi["material"];
                row.Children.Add(t);
                card.Children.Add(row);
                if (sp != null)
                {
                    // the controls of a part: how much of its zone, how ragged, (patches) how big; «Togli» joins it back
                    var box = new StackPanel { Margin = new Thickness(14 * depth + 14, 2, 0, 4) };
                    var spId = (string?)sp["id"] ?? key;
                    JsonObject changed(string k, JsonNode v)
                    {
                        var arr = new JsonArray();
                        foreach (var x in splits)
                        {
                            var c = (JsonObject)x!.DeepClone();
                            if ((string?)c["id"] == spId) c[k] = v;
                            arr.Add(c);
                        }
                        return new JsonObject { ["splits"] = arr };
                    }
                    var am = new ValueSlider(L.T("Quanto"), ((double?)sp["amount"] ?? 0.4) * 100, 2, 98, false, "0", "%", null,
                        L.T("Che parte della zona da cui viene diventa questa"));
                    am.Committed += async v => await UpdateTerrain(changed("amount", JsonValue.Create(Math.Round(v, 1) / 100.0)));
                    box.Children.Add(am);
                    var ir = new ValueSlider(L.T("Irregolarità"), ((double?)sp["irregular"] ?? 0.5) * 100, 0, 100, false, "0", "%", null,
                        L.T("Quanto il confine si frastaglia invece di seguire esattamente il terreno"));
                    ir.Committed += async v => await UpdateTerrain(changed("irregular", JsonValue.Create(Math.Round(v, 1) / 100.0)));
                    box.Children.Add(ir);
                    if ((string?)sp["rule"] == "macchie")
                    {
                        var szs = new ValueSlider(L.T("Dimensione delle macchie"), (double?)sp["size"] ?? 40, 3, 400, true, "0", "m", null, L.T("Quanto sono grandi le chiazze di questa parte della zona, in metri: piccole per macchie sparse, grandi per aree ampie"));
                        szs.Committed += async v => await UpdateTerrain(changed("size", JsonValue.Create(Math.Round(v, 1))));
                        box.Children.Add(szs);
                    }
                    var rm = SmallButton(Icons.Undo, L.T("Togli la divisione"), async () =>
                    {
                        // (the parts made from this one go too: their ground goes back to the zone above)
                        var gone = new HashSet<string> { spId };
                        bool more = true;
                        while (more)
                        {
                            more = false;
                            foreach (var x in splits.OfType<JsonObject>())
                                if (!gone.Contains((string?)x["id"] ?? "") && gone.Contains((string?)x["zone"] ?? "")) { gone.Add((string?)x["id"] ?? ""); more = true; }
                        }
                        var arr = new JsonArray();
                        foreach (var x in splits.OfType<JsonObject>())
                            if (!gone.Contains((string?)x["id"] ?? "")) arr.Add(x.DeepClone());
                        await UpdateTerrain(new JsonObject { ["splits"] = arr });
                    });
                    rm.HorizontalAlignment = HorizontalAlignment.Left;
                    rm.ToolTip = L.T("Questa parte torna nella zona da cui viene");
                    box.Children.Add(rm);
                    card.Children.Add(box);
                }
            }

            var adv = Advanced(shapeCard, "terrainShape");
            if (cur != "mappa")
            {
                S(adv.Body, L.T("Erosione"), P("erosion", 1) * 100, 0, 200, false, "0", "%", L.T("Quanto l'acqua scava valli e canali sui pendii e deposita il materiale in basso. 0% = forme come escono dal rumore, senza valli; 200% = valli profonde e conoidi grandi. Il terreno si ricalcola"), x => new JsonObject { ["erosion"] = x / 100.0 });
                S(adv.Body, L.T("Età"), P("age", 1) * 100, 30, 250, false, "0", "%", L.T("Quanto è vecchio il terreno: più alta = creste più consumate e morbide, fondovalle più pieni e piatti; più bassa = forme giovani, aspre e incise"), x => new JsonObject { ["age"] = x / 100.0 });
                if (cur is "dune" or "valle")
                    S(adv.Body, L.T("Direzione"), P("direction", 0), 0, 359, false, "0", "°", cur == "dune" ? L.T("Da dove viene il vento") : L.T("Verso della valle"), x => new JsonObject { ["direction"] = x });
            }
            else
                S(adv.Body, L.T("Erosione della mappa"), P("hmErosion", 0.3) * 100, 0, 200, false, "0", "%", L.T("Un po' di erosione dell'acqua sopra la mappa di altezze: rifinisce i pendii con canali e depositi. 0% = la mappa così com'è"), x => new JsonObject { ["hmErosion"] = x / 100.0 });
            if (rocky > 0)
            {
                S(adv.Body, L.T("Spigolosità"), ((double?)rock?["sharp"] ?? 0.5) * 100, 0, 100, false, "0", "%",
                  L.T("Con «Roccia scolpita»: creste e canaloni più netti, roccia più rotta e spigolosa. 0% = spigoli smussati"), x => new JsonObject { ["sharp"] = x / 100.0 });
                S(adv.Body, L.T("Strati di roccia"), ((double?)rock?["strata"] ?? 0.6) * 100, 0, 100, false, "0", "%",
                  L.T("Con «Roccia scolpita»: quanto le pareti sono fatte a cenge e salti, come strati di roccia sovrapposti. 0% = pareti continue"), x => new JsonObject { ["strata"] = x / 100.0 });
                S(adv.Body, L.T("Spessore degli strati"), (double?)rock?["thick"] ?? 10, 2, 60, true, "0.0", "m",
                  L.T("Altezza di un salto di roccia (di partenza: dal dislivello del terreno)"), x => new JsonObject { ["strataThick"] = x });
                S(adv.Body, L.T("Inclinazione degli strati"), (double?)rock?["dip"] ?? 8, 0, 40, false, "0", "°",
                  L.T("Gli strati di roccia non sono orizzontali: quanto pendono"), x => new JsonObject { ["strataDip"] = x });
            }
            adv.Done(Math.Abs(P("erosion", 1) - 1) > 1e-3 || Math.Abs(P("age", 1) - 1) > 1e-3
                     || (rocky > 0 && (Math.Abs(((double?)rock?["strata"] ?? 0.6) - 0.6) > 1e-3 || Math.Abs(((double?)rock?["dip"] ?? 8) - 8) > 1e-3 || ((double?)prm["strataThick"] ?? 0) > 0
                                       || Math.Abs(((double?)rock?["sharp"] ?? 0.5) - 0.5) > 1e-3)));
            // (1.76.44) «Scultura»: the brush that raises, lowers and smooths the ground
            {
                var on = _puddleBrush && _brushLayer == "terrain";
                var tg = new Toggle(L.T("Scolpisci il terreno"), on,
                    L.T("Un pennello per modellare il terreno a mano: tieni premuto il tasto sinistro sulla vista e trascina. Il terreno cambia subito nella vista; Blender lo rifà una volta sola, quando chiudi lo strumento (spegnendolo, cambiando pannello, passando al path tracing, al render finale o salvando): solo allora «Occupato · attendi». Le zone si ricalcolano con la nuova forma (dove diventa ripido roccia, dove spiani prato) e gli ecosistemi e le pietre seguono. Le pennellate restano nel progetto e valgono anche per «Un'altra versione», la dimensione e il dettaglio. Mentre scolpisci Ctrl+Z toglie l'ultima pennellata; dopo, tutta la sessione è un solo passo di Ctrl+Z. [ e ] cambiano il diametro, Esc chiude"));
                tg.Toggled += v => { _puddleBrush = v; _brushLayer = "terrain"; SendPuddleBrush(); RenderProps(); };
                sculptCard.Children.Add(tg);
                if (on)
                {
                    var tools = new (string id, Geometry icon, string name, string tip)[]
                    {
                        ("raise", TsRaise, L.T("Alza"), L.T("Alza: solleva il terreno sotto il pennello, di più al centro. Più passate alzano di più. Con Maiusc premuto abbassa")),
                        ("lower", TsLower, L.T("Abbassa"), L.T("Abbassa: scava il terreno sotto il pennello, di più al centro. Più passate scavano di più. Con Maiusc premuto alza")),
                        ("smooth", TsSmooth, L.T("Liscia"), L.T("Liscia: toglie gobbe e buche sotto il pennello, la pendenza resta. Utile dopo Alza e Abbassa, o per ammorbidire una cresta")),
                    };
                    var row = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 8, 0, 2) };
                    foreach (var (id, icon, name, tip) in tools)
                    {
                        var sel = _tsTool == id;
                        var b = Theme.Button(Theme.Icon(icon, sel ? Theme.AccentText : Theme.Text, 22), sel ? Theme.Kind.Segment : Theme.Kind.Ghost, tip);
                        b.Width = 44; b.Height = 38; b.Padding = new Thickness(0); b.Margin = new Thickness(0, 0, 6, 0);
                        var tid = id;
                        b.Click += (_, __) => { _tsTool = tid; SendPuddleBrush(); RenderProps(); };
                        row.Children.Add(b);
                    }
                    sculptCard.Children.Add(row);
                    var curT = tools.First(t => t.id == _tsTool);
                    sculptCard.Children.Add(Theme.Label(curT.name, 12, Theme.TextMuted, FontWeights.SemiBold));
                    var dia = new ValueSlider(L.T("Diametro"), _tsRadius * 2, 1, 2000, true, "0", "m", null,
                        L.T("Quanto è largo il pennello sul terreno ([ e ] sulla vista). Grande per modellare colline e valli, piccolo per un argine o un sentiero"));
                    dia.Changing += x => { _tsRadius = x / 2; SendPuddleBrush(); };
                    dia.Committed += x => { _tsRadius = x / 2; SendPuddleBrush(); };
                    _tsRadiusChanged = () => dia.SetValue(_tsRadius * 2, false);
                    sculptCard.Children.Add(dia);
                    var its = new ValueSlider(L.T("Intensità"), _tsStrength * 100, 1, 100, false, "0", "%", null,
                        L.T("Quanto agisce ogni passata: bassa per ritocchi graduali, alta per cambiare molto in fretta. Con Alza e Abbassa al 100% una passata sposta il centro di circa un decimo del diametro"));
                    its.Changing += x => { _tsStrength = x / 100; SendPuddleBrush(); };
                    its.Committed += x => { _tsStrength = x / 100; SendPuddleBrush(); };
                    sculptCard.Children.Add(its);
                    var sft = new ValueSlider(L.T("Morbidezza del bordo"), _tsSoft * 100, 0, 100, false, "0", "%", null,
                        L.T("Come finisce il pennello: 0% = tutto il cerchio agisce uguale e il bordo resta un gradino netto; 100% = agisce soprattutto al centro e sfuma verso il bordo"));
                    sft.Changing += x => { _tsSoft = x / 100; SendPuddleBrush(); };
                    sft.Committed += x => { _tsSoft = x / 100; SendPuddleBrush(); };
                    sculptCard.Children.Add(sft);
                    sculptCard.Children.Add(HintSmall(L.T("Il terreno vero si aggiorna quando chiudi lo strumento. Ctrl+Z toglie l'ultima pennellata, Maiusc inverte Alza e Abbassa.")));
                }
                var nStrokes = (prm["sculpt"] as JsonArray)?.Count ?? 0;
                var advS = Advanced(sculptCard, "terrainSculpt");
                if (nStrokes > 0)
                {
                    advS.Body.Children.Add(HintSmall(L.F("Pennellate nel terreno: {0}", nStrokes)));
                    var clr = Theme.Button(Theme.IconText(Icons.Trash, L.T("Togli tutte le modifiche"), null, 13), Theme.Kind.Ghost,
                        L.T("Riporta il terreno alla forma che aveva prima di tutte le pennellate di «Scultura» (Ctrl+Z la rimette)"));
                    clr.HorizontalAlignment = HorizontalAlignment.Left;
                    clr.Click += async (_, __) => await UpdateTerrain(new JsonObject { ["sculpt"] = new JsonArray() });
                    advS.Body.Children.Add(clr);
                }
                advS.Done(false);
            }

            // (1.76.14) «Colori dal terreno»: the colour of the zones guided by the shape of the land (materials only).
            // (1.76.41) a section of its own: the switch and the relief of the rock in view, the rest in its Avanzate
            var tone = _terrain["tone"] as JsonObject;
            bool toneOn = (bool?)tone?["on"] ?? false;
            var tgl = new Toggle(L.T("Usa i colori dal terreno"), toneOn,
                L.T("Il colore segue la forma del terreno: creste più chiare, canaloni più scuri, colate sulle pareti, fasce degli strati di roccia, più scuro dove si raccoglie l'acqua. Cambia solo i materiali delle zone, non la forma"));
            tgl.Toggled += async v => await SetTerrainTone(new JsonObject { ["on"] = v });
            toneCard.Children.Add(tgl);
            var advTone = Advanced(toneCard, "terrainTone");
            if (toneOn)
            {
                ValueSlider TS(Panel to, string label, string key, string tip)
                {
                    var sl = new ValueSlider(label, ((double?)tone?[key] ?? 0.5) * 100, 0, 100, false, "0", "%", null, tip);
                    sl.Committed += async v => await SetTerrainTone(new JsonObject { [key] = Math.Round(v, 1) / 100.0 });
                    to.Children.Add(sl);
                    return sl;
                }
                TS(advTone.Body, L.T("Colate sulle pareti"), "streaks", L.T("Strisce scure che scendono lungo le pareti ripide, come l'acqua e i minerali che colano sulla roccia. 0% = nessuna colata"));
                TS(advTone.Body, L.T("Fasce degli strati"), "bands", L.T("Fasce di colore sulle pareti che seguono gli strati della roccia (con lo spessore e l'inclinazione di «Forma e roccia»). 0% = parete di un colore solo"));
                TS(advTone.Body, L.T("Creste e canaloni"), "ridges", L.T("Creste più chiare e consumate dal vento, canaloni più scuri dove si raccoglie il materiale. 0% = colore uguale ovunque"));
                TS(advTone.Body, L.T("Umido"), "wet", L.T("Più scuro dove l'acqua scorre e si raccoglie: impluvi, conche, piedi dei pendii. 0% = asciutto ovunque"));
            }
            double TV(string k) => (double?)tone?[k] ?? 0.5;
            advTone.Done(toneOn && (Math.Abs(TV("streaks") - 0.5) > 1e-3 || Math.Abs(TV("bands") - 0.5) > 1e-3 || Math.Abs(TV("ridges") - 0.5) > 1e-3 || Math.Abs(TV("wet") - 0.5) > 1e-3));

            // (1.76.41) «Zone del terreno» · Avanzate: how the zones are drawn and how their borders mix
            var advZones = Advanced(zonesCard, "terrainZones");
            S(advZones.Body, L.T("Ghiaia e terra"), P("gravel", 0.5) * 100, 0, 100, false, "0", "%", L.T("Quanto terreno lungo i canali e ai piedi dei pendii diventa la zona di ghiaia e terra invece di prato o roccia. 0% = niente ghiaia; il terreno si ricalcola"), x => new JsonObject { ["gravel"] = x / 100.0 });
            S(advZones.Body, L.T("Confini irregolari"), P("irregular", 0.5) * 100, 0, 100, false, "0", "%", L.T("Quanto sono frastagliati i confini tra le zone (dove finisce il prato e comincia la roccia). 0% = confini che seguono solo la forma del terreno; il terreno si ricalcola"), x => new JsonObject { ["irregular"] = x / 100.0 });
            if (bw > 0)
            {
                var bis = new ValueSlider(L.T("Irregolarità del bordo"), ((double?)bl?["irregular"] ?? 0.6) * 100, 0, 100, false, "0", "%", null,
                    L.T("Con «Sfumatura dei bordi» acceso: quanto il confine fra due materiali si frastaglia. 0% = segue la linea fra le zone, sfumato solo dai rilievi delle texture"));
                bis.Committed += async v => await SetTerrainBlend(new JsonObject { ["irregular"] = Math.Round(v, 1) / 100.0 });
                advZones.Body.Children.Add(bis);
            }
            advZones.Done(Math.Abs(P("gravel", 0.5) - 0.5) > 1e-3 || Math.Abs(P("irregular", 0.5) - 0.5) > 1e-3
                          || (bw > 0 && Math.Abs(((double?)bl?["irregular"] ?? 0.6) - 0.6) > 1e-3));

            // (1.76.41) «Spianata e bordi» · Avanzate: the fillet of the flat area and the edge of the terrain
            var advFlat = Advanced(flatCard, "terrainFlat");
            if ((bool?)flat["on"] ?? true)
                S(advFlat.Body, L.T("Raccordo della spianata"), (double?)flat["soft"] ?? 40, 1, 1000, true, "0", "m", L.T("Larghezza della fascia che raccorda la spianata al terreno intorno: poco = un gradino netto, tanto = una salita lunga e dolce"), x => new JsonObject { ["flat"] = new JsonObject { ["soft"] = x } });
            var edge = new Toggle(L.T("Bordo raccordato al suolo"), B("edge", true), L.T("Il bordo del terreno scende al suo punto più basso, dove sta il suolo dell'Ambiente: niente gradino. Spento: il terreno finisce di netto ai lati del quadrato"));
            edge.Toggled += async v => await UpdateTerrain(new JsonObject { ["edge"] = v });
            advFlat.Body.Children.Add(edge);
            if (B("edge", true))
            {
                // (1.76.19) the edge with bays and headlands: with the sea at the foot the coast is not the square
                var nat = new Toggle(L.T("Bordo con baie e promontori"), B("edgeNatural", false),
                    L.T("Il bordo scende in modo irregolare: con il mare al piede la costa ha baie e promontori invece della linea dritta del quadrato"));
                nat.Toggled += async v => await UpdateTerrain(new JsonObject { ["edgeNatural"] = v });
                advFlat.Body.Children.Add(nat);
            }
            advFlat.Done((((bool?)flat["on"] ?? true) && Math.Abs(((double?)flat["soft"] ?? 40) - 40) > 1e-3) || !B("edge", true) || B("edgeNatural", false));

            // (1.76.41) «Terreno» · Avanzate: how fine the grid is, and the height map
            var advMain = Advanced(mainCard, "terrain");
            var segs = new[] { "normale", "alto", "massimo" };
            var seg = Theme.Segmented(out var sb, (L.T("Normale"), L.T("Un punto ogni 2 m vicino al modello e alla camera, più radi verso i bordi (al massimo 512 × 512): leggero")), (L.T("Alto"), L.T("Ogni 1,5 m vicino al modello e alla camera (al massimo 768 × 768)")), (L.T("Massimo"), L.T("Ogni metro vicino al modello e alla camera (al massimo 1024 × 1024: un milione di vertici)")));
            Theme.SetSegment(sb, Math.Max(0, Array.IndexOf(segs, (string?)prm["detail"] ?? "normale")));
            for (int i = 0; i < sb.Count; i++) { var v = segs[i]; sb[i].Click += async (_, __) => await UpdateTerrain(new JsonObject { ["detail"] = v }); }
            var segRow = new DockPanel { Margin = new Thickness(0, 0, 0, 10) };
            var sl = Theme.Label(L.T("Dettaglio"), 12, Theme.TextMuted); sl.Width = 96; sl.VerticalAlignment = VerticalAlignment.Center;
            segRow.Children.Add(sl); segRow.Children.Add(seg);
            advMain.Body.Children.Add(segRow);
            // (1.76.3) the fine grid is made around the model and the camera of when the terrain was made: after moving
            // the camera far, this makes it again for the view of now
            var here2 = Theme.Button(L.T("Dettaglio dove guarda la camera"), Theme.Kind.Ghost,
                L.T("Il terreno è più fitto vicino al modello e alla camera di quando l'hai creato o modificato: dopo aver spostato la camera lontano, questo rifà la griglia fitta anche lì"));
            here2.HorizontalAlignment = HorizontalAlignment.Left; here2.Margin = new Thickness(0, 0, 0, 10);
            here2.Click += async (_, __) => await UpdateTerrain(new JsonObject());
            advMain.Body.Children.Add(here2);
            var hmb = Theme.Button(cur == "mappa" ? L.T("Cambia mappa di altezze…") : L.T("Usa una mappa di altezze…"), Theme.Kind.Ghost, L.T("Un'immagine in scala di grigi (PNG a 16 bit, TIFF, EXR, RAW): nero il punto più basso, bianco il più alto. Oppure un file di quote vero (USGS .dem, SRTM .hgt, ESRI .asc): con la sua larghezza e il suo dislivello reali"));
            hmb.HorizontalAlignment = HorizontalAlignment.Left;
            hmb.Click += async (_, __) =>
            {
                var f = PickHeightmap();
                if (f == null) return;
                var body = await WithDemPart(f, new JsonObject { ["heightmap"] = f, ["size"] = size });
                if (body != null) await UpdateTerrain(body);
            };
            advMain.Body.Children.Add(hmb);
            // (1.76.34) another part of the same elevation file
            var hmPath = (string?)prm["heightmap"] ?? "";
            if (IsDemFile(hmPath))
            {
                var part = Theme.Button(L.T("Scegli un'altra parte del file…"), Theme.Kind.Ghost, L.T("Il quadrato del file di quote usato per il terreno: dove e quanto grande"));
                part.HorizontalAlignment = HorizontalAlignment.Left;
                part.Margin = new Thickness(0, 4, 0, 0);
                part.Click += async (_, __) =>
                {
                    var body = await WithDemPart(hmPath, new JsonObject(), always: true);
                    if (body != null && body["hmCrop"] != null) await UpdateTerrain(new JsonObject { ["hmCrop"] = body["hmCrop"]!.DeepClone() });
                };
                advMain.Body.Children.Add(part);
            }
            advMain.Done(((string?)prm["detail"] ?? "normale") != "normale");
        }

        /// <summary>(1.76.8) The rules a zone can be split by: a new part of «Dividi zona», added at the end.</summary>
        void ShowSplitMenu(FrameworkElement anchor, string zone, JsonArray splits)
        {
            var m = new ContextMenu { PlacementTarget = anchor, Placement = System.Windows.Controls.Primitives.PlacementMode.Bottom };
            var tips = new Dictionary<string, string>
            {
                ["umido"] = L.T("Dove l'acqua si raccoglie: impluvi, conche, fondovalle"),
                ["secco"] = L.T("Il contrario di umido: dossi e pendii che l'acqua lascia presto"),
                ["sole"] = L.T("I versanti rivolti verso il sole dell'Ambiente"),
                ["ombra"] = L.T("I versanti che il sole dell'Ambiente guarda poco"),
                ["alto"] = L.T("Le parti più alte della zona"),
                ["basso"] = L.T("Le parti più basse della zona"),
                ["ripido"] = L.T("Le parti più ripide della zona"),
                ["piano"] = L.T("Le parti più pianeggianti della zona"),
                ["dossi"] = L.T("Creste e dossi, dove il terreno è convesso"),
                ["conche"] = L.T("Avvallamenti, dove il terreno è concavo"),
                ["macchie"] = L.T("Chiazze naturali, senza un motivo del terreno: per variare"),
            };
            foreach (var r in (_terrain?["rules"] as JsonArray ?? new JsonArray()).OfType<JsonObject>())
            {
                var rid = (string?)r["id"] ?? "";
                var item = new MenuItem { Header = (string?)r["name"] ?? rid, ToolTip = tips.TryGetValue(rid, out var tp) ? tp : null };
                item.Click += async (_, __) =>
                {
                    var arr = new JsonArray();
                    foreach (var x in splits) arr.Add(x!.DeepClone());
                    arr.Add(new JsonObject { ["zone"] = zone, ["rule"] = rid, ["amount"] = 0.4, ["irregular"] = 0.5, ["size"] = 40.0 });
                    await UpdateTerrain(new JsonObject { ["splits"] = arr });
                };
                m.Items.Add(item);
            }
            m.IsOpen = true;
        }

        static double DefaultTerrainSize(string preset) => preset switch { "pianura" => 800, "colline" => 1200, "valle" => 1500, "montagne" => 3000, "dune" => 800, _ => 1000 };
        static double DefaultRock(string preset) => preset == "montagne" ? 45 : 35;
        static double DefaultTerrainHeight(string preset) => preset switch { "pianura" => 10, "colline" => 90, "valle" => 380, "montagne" => 650, "dune" => 25, _ => 100 };

        static bool IsDemFile(string path) => System.IO.Path.GetExtension(path ?? "").ToLowerInvariant() is ".dem" or ".hgt" or ".asc";

        /// <summary>(1.76.34, Luca: «se sono enormi meglio selezionare una parte di pochi km») an elevation file bigger
        /// than a few km: which part of it, in a window with its relief and a square to place. The body of the call with
        /// «hmCrop», or null (cancelled). A small file, or a picture: as it is.</summary>
        async Task<JsonObject?> WithDemPart(string path, JsonObject body, bool always = false)
        {
            if (!IsDemFile(path) || _api == null) return body;
            JsonObject? pv = null;
            using (BeginBusy())
            {
                ShowTask(L.T("Lettura del file di quote…"));
                try { await Run(async api => { pv = await api.Post("terrain/dem/preview", new { path }); }); }
                finally { HideTask(); }
            }
            if (pv == null) return null;
            double full = (double?)pv["size"] ?? 0, maxS = (double?)pv["maxSide"] ?? full, defS = (double?)pv["defaultSide"] ?? full;
            if (!always && full <= defS * 1.02) return body;            // (small enough: the whole file)
            var png = Convert.FromBase64String((string?)pv["png"] ?? "");
            var c = DemCropDialog.Ask(this, System.IO.Path.GetFileName(path), png, full, maxS, defS);
            if (c == null) return null;
            body["hmCrop"] = new JsonArray(c.Select(v => (JsonNode)JsonValue.Create(v)!).ToArray());
            return body;
        }

        string? PickHeightmap()
        {
            var dlg = new Microsoft.Win32.OpenFileDialog { Filter = L.T("Mappe di altezze e file di quote|*.png;*.tif;*.tiff;*.exr;*.raw;*.r16;*.dem;*.hgt;*.asc|Tutti i file|*.*"), InitialDirectory = StartFolder("image") };
            if (dlg.ShowDialog(this) != true) return null;
            Keep("image", dlg.FileName);
            return dlg.FileName;
        }
    }
}
