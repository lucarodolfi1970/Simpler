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
    /// <summary>(1.76.22) «Pietre e detriti» of a terrain (engine: scree.py): the stone models the user picks from the
    /// library, laid where a mountain sheds them - talus cones at the foot of the walls, stones in the gullies and where
    /// they open out - with the colour of the terrain's rock. A card of the Paesaggio panel, under the terrain's. Main:
    /// the stones, «Quantità»; the rest in Avanzate (Luca: «avanzate piene di parametri»).</summary>
    public sealed partial class MainWindow
    {
        static readonly Geometry Stones = MakeGeometry("M2.5 19c0-3.2 2.2-5.5 5.2-5.5s4.8 2.3 4.8 5.5z M11.5 19c0-2.6 1.8-4.3 4.4-4.3s4.6 1.7 4.6 4.3z M7.5 12.2c0-2.2 1.5-3.7 3.6-3.7s3.4 1.5 3.4 3.7z");
        static readonly Color ScreeColor = Color.FromRgb(0xA8, 0x9A, 0x86);

        // the stones chosen before the first «Posa le pietre» (after: those of the scree, in the engine)
        readonly List<(string id, string name)> _screePending = new();
        // (1.76.25, Luca) the size and amount of each stone, chosen also before the first «Posa le pietre»
        readonly Dictionary<string, double> _screePendScale = new(), _screePendWeight = new();
        double _screePendSize = 1.0;          // (1.76.31: «Grandezza» of all the stones, also before placing them)
        bool _screePickOn;
        /// <summary>A click on a model of the library adds it to the stones: only while the Paesaggio panel is open
        /// (1.76.24, Luca: the open panel decides where a click goes - leaving it, the clicks go to the scene again).</summary>
        bool _screePicking { get => _screePickOn && _rightPanel == "landscape"; set => _screePickOn = value; }

        JsonObject? ScreeOfTerrain() => (_terrain?["scree"] as JsonArray)?.OfType<JsonObject>().FirstOrDefault();

        /// <summary>A model of the library clicked while «Scegli le pietre» is on.</summary>
        void AddScreeModel(string id, string name)
        {
            if (_terrain == null) { Status(L.T("Pietre e detriti vanno su un terreno: crealo prima in Paesaggio"), true); return; }
            var sc = ScreeOfTerrain();
            if (sc != null)
            {
                var ids = (sc["models"] as JsonArray)?.OfType<JsonObject>().Select(m => (string?)m["id"] ?? "").ToList() ?? new();
                if (ids.Contains(id)) { Status(L.F("{0} è già fra le pietre", name)); return; }
                ids.Add(id);
                _ = ChangeScree(new JsonObject { ["models"] = new JsonArray(ids.Select(x => (JsonNode)JsonValue.Create(x)!).ToArray()) });
                return;
            }
            if (_screePending.Any(p => p.id == id)) { Status(L.F("{0} è già fra le pietre", name)); return; }
            _screePending.Add((id, name));
            Status(L.F("{0} aggiunto alle pietre", name));
            if (_rightPanel == "landscape") RenderProps();
        }

        async Task CreateScree()
        {
            if (_api == null || _terrain == null || _screePending.Count == 0) return;
            SendToWeb(new { type = "busyNow", what = L.T("Pietre e detriti") });
            JsonObject? r = null;
            using (var busy = BeginBusy())
                await Run(async api => { r = await api.Post("scree/apply", new JsonObject
                {
                    ["terrain"] = (string?)_terrain["id"],
                    ["models"] = new JsonArray(_screePending.Select(p => (JsonNode)JsonValue.Create(p.id)!).ToArray()),
                    ["modelScale"] = DictJson(_screePendScale),
                    ["modelWeight"] = DictJson(_screePendWeight),
                    ["size"] = _screePendSize,
                }); });
            if (r == null) return;
            _screePending.Clear();
            _screePendScale.Clear();
            _screePendWeight.Clear();
            _screePendSize = 1.0;
            _screePicking = false;
            await RefreshScene();
            await LoadTerrain();
            Status(ScreeDone(r));
            await LoadCamView();          // (1.76.31: «Ricalcola» bottom left knows the stones now)
            if (_rightPanel == "landscape") RenderProps();
        }

        static JsonObject DictJson(Dictionary<string, double> d)
        {
            var o = new JsonObject();
            foreach (var kv in d) o[kv.Key] = Math.Round(kv.Value, 3);
            return o;
        }

        string ScreeDone(JsonObject r)
        {
            var n = ((int?)r["pieces"] ?? 0).ToString("N0");
            if ((int?)r["recoloured"] == 0 && (int?)r["kept"] > 0)
                return L.F("Pietre e detriti: {0} pietre - il colore dei loro materiali non si può cambiare (fatti in un modo che Simpler non ricostruisce): «Accordo al terreno» e i colori non hanno effetto", n);
            return (bool?)r["reduced"] == true
                ? L.F("Pietre e detriti: {0} pietre (ridotte: sarebbero state troppe - aumenta la grandezza o abbassa la quantità)", n)
                : L.F("Pietre e detriti: {0} pietre", n);
        }

        async Task ChangeScree(JsonObject change)
        {
            var sc = ScreeOfTerrain();
            if (_api == null || sc == null) return;
            change["group"] = (string?)sc["id"];
            SendToWeb(new { type = "busyNow", what = L.T("Pietre e detriti") });
            JsonObject? r = null;
            using (var busy = BeginBusy())
                await Run(async api => { r = await api.Post("scree/apply", change); });
            if (r != null)
            {
                await RefreshScene();
                Status(ScreeDone(r));
            }
            await LoadTerrain();
            if (_rightPanel == "landscape") RenderProps();
        }

        void RenderScreeCard()
        {
            if (_terrain == null) return;
            var card = new StackPanel();
            var title = SectionTitle(L.T("Pietre e detriti"));
            title.DataContext = (Stones, ScreeColor);
            card.Children.Add(title);
            _props.Children.Add(Theme.Card(card, 16));
            var sc = ScreeOfTerrain();
            var set = sc?["settings"] as JsonObject ?? new JsonObject();
            double V(string k, double d) => (double?)set[k] ?? d;

            // the stones: picked from the library
            var models = sc != null
                ? (sc["models"] as JsonArray)?.OfType<JsonObject>().Select(m => ((string?)m["id"] ?? "", (string?)m["name"] ?? "")).ToList() ?? new()
                : _screePending.ToList();
            if (sc == null)
                card.Children.Add(HintSmall(L.T("I modelli di pietra che scegli, posati dove la montagna li fa cadere: a coni ai piedi delle pareti e lungo i canaloni, i piccoli in alto e i grandi più in basso, con il colore della roccia del terreno.")));
            var pick = new Toggle(L.T("Scegli le pietre dalla libreria"), _screePicking,
                L.T("Acceso: un clic su un modello della libreria (Modelli 3D) lo aggiunge alle pietre, invece di metterlo nella scena"));
            pick.Toggled += v => { _screePicking = v; if (v) Status(L.T("Clic sui modelli di pietra nella libreria «Modelli 3D»")); };
            card.Children.Add(pick);
            // every stone as in the brush: its picture, its name and, under it, its own Avanzate (size, how many)
            var mScale = set["modelScale"] as JsonObject ?? new JsonObject();
            var mWeight = set["modelWeight"] as JsonObject ?? new JsonObject();
            foreach (var (mid, mname) in models)
            {
                var id_ = mid;
                var entry = _models.OfType<JsonObject>().FirstOrDefault(m => (string?)m["id"] == mid);
                var row = new Grid { Margin = new Thickness(0, 0, 0, 8) };
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(46) });
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(32) });
                var thumb = (string?)entry?["thumb"] ?? "";
                var pic = new Border { Width = 40, Height = 40, CornerRadius = new CornerRadius(6), Background = Theme.B(Theme.Inset), VerticalAlignment = VerticalAlignment.Top };
                if (thumb != "" && System.IO.File.Exists(thumb) && LoadBitmapFresh(thumb) is ImageSource im) pic.Background = new ImageBrush(im) { Stretch = Stretch.UniformToFill };
                row.Children.Add(pic);
                var mcol = new StackPanel { Margin = new Thickness(8, 0, 4, 0) };
                var nm = Theme.Label(mname, 12, Theme.TextSoft);
                nm.TextTrimming = TextTrimming.CharacterEllipsis;
                mcol.Children.Add(nm);
                double scaleNow = sc != null ? ((double?)mScale[id_] ?? 1) : (_screePendScale.TryGetValue(id_, out var ps) ? ps : 1);
                double weightNow = sc != null ? ((double?)mWeight[id_] ?? 1) : (_screePendWeight.TryGetValue(id_, out var pw) ? pw : 1);
                var adv1 = Advanced(mcol, "screeItem:" + id_);
                void Item(string label, double v, double min, double max, bool log, string tip, Func<double, Task> set_)
                {
                    var vs = new ValueSlider(label, v, min, max, log, "0", "%", null, tip).Compact(stacked: true);
                    vs.Committed += async x => await set_(x);
                    adv1.Body.Children.Add(vs);
                }
                JsonObject With(JsonObject src, double v)
                {
                    var o = new JsonObject();
                    foreach (var kv in src) o[kv.Key] = kv.Value?.DeepClone();
                    o[id_] = Math.Round(v, 3);
                    return o;
                }
                Item(L.T("Grandezza"), scaleNow * 100, 10, 1000, true, L.T("La grandezza di questa pietra, rispetto alle altre"), async x =>
                {
                    if (sc == null) { _screePendScale[id_] = x / 100.0; RenderProps(); await Task.Yield(); return; }
                    await ChangeScree(new JsonObject { ["modelScale"] = With(mScale, x / 100.0) });
                });
                Item(L.T("Quante di questa"), weightNow * 100, 0, 300, false, L.T("Quanto spesso c'è questa pietra rispetto alle altre"), async x =>
                {
                    if (sc == null) { _screePendWeight[id_] = x / 100.0; RenderProps(); await Task.Yield(); return; }
                    await ChangeScree(new JsonObject { ["modelWeight"] = With(mWeight, x / 100.0) });
                });
                adv1.Done(Math.Abs(scaleNow - 1) > 1e-3 || Math.Abs(weightNow - 1) > 1e-3, async () =>
                {
                    if (sc == null) { _screePendScale.Remove(id_); _screePendWeight.Remove(id_); RenderProps(); await Task.Yield(); return; }
                    var a = With(mScale, 1); var b = With(mWeight, 1);
                    await ChangeScree(new JsonObject { ["modelScale"] = a, ["modelWeight"] = b });
                });
                Grid.SetColumn(mcol, 1);
                row.Children.Add(mcol);
                var rm = IconButton(Icons.Trash, L.T("Togli dalle pietre"), async () =>
                {
                    if (sc == null) { _screePending.RemoveAll(p => p.id == id_); RenderProps(); await Task.Yield(); return; }
                    var rest = models.Where(m => m.Item1 != id_).Select(m => (JsonNode)JsonValue.Create(m.Item1)!).ToArray();
                    if (rest.Length == 0) { Status(L.T("Serve almeno una pietra: per toglierle tutte usa «Elimina pietre e detriti»"), true); return; }
                    await ChangeScree(new JsonObject { ["models"] = new JsonArray(rest) });
                });
                rm.VerticalAlignment = VerticalAlignment.Top;
                Grid.SetColumn(rm, 2);
                row.Children.Add(rm);
                row.Tag = "content";          // (a stone of the list: no heart, always there - 1.76.32)
                card.Children.Add(row);
            }
            if (sc == null)
            {
                var go = Theme.Button(Theme.IconText(Stones, L.T("Posa le pietre"), null, 14), Theme.Kind.Primary,
                    L.T("Calcola dove cadono le pietre su questo terreno e le posa (da qualche secondo a un minuto)"));
                go.HorizontalAlignment = HorizontalAlignment.Left;
                go.Margin = new Thickness(0, 6, 0, 0);
                go.IsEnabled = _screePending.Count > 0;
                if (_screePending.Count > 0)
                {
                    var ps_ = new ValueSlider(L.T("Grandezza"), _screePendSize * 100, 5, 2000, true, "0", "%", null,
                        L.T("La grandezza di tutte le pietre insieme, rispetto ai modelli (quella di ogni pietra, nelle sue Avanzate, si moltiplica a questa). Più grandi: coprono uguale, quindi sono meno"));
                    ps_.Committed += x => { _screePendSize = x / 100.0; };
                    card.Children.Add(ps_);
                }
                go.Click += async (_, __) => await CreateScree();
                card.Children.Add(go);
                if (_screePending.Count == 0)
                    card.Children.Add(HintSmall(L.T("Accendi «Scegli le pietre dalla libreria» e fai clic sui modelli di pietra (più di uno: più varietà).")));
                return;
            }

            ValueSlider S(Panel to, string label, double v, double min, double max, bool log, string fmt, string unit, string tip, Func<double, JsonObject> change)
            {
                var s = new ValueSlider(label, v, min, max, log, fmt, unit, null, tip);
                s.Committed += async x => await ChangeScree(change(x));
                to.Children.Add(s);
                return s;
            }
            card.Children.Add(HintSmall(L.F("{0} pietre", ((int?)sc["pieces"] ?? 0).ToString("N0"))
                + ((bool?)sc["camOnly"] == true ? " · " + L.T("solo dove guarda la camera") : "")));
            S(card, L.T("Quantità"), V("amount", 0.5) * 100, 0, 200, false, "0", "%", L.T("Quante pietre: 50% = dove ne cadono di più coprono il terreno, 100% = ammucchiate"), x => new JsonObject { ["amount"] = Math.Round(x, 1) / 100.0 });
            // (1.76.31, Luca) the size of all the stones at once (each one's own in its Avanzate multiplies it)
            S(card, L.T("Grandezza"), V("size", 1) * 100, 5, 2000, true, "0", "%", L.T("La grandezza di tutte le pietre insieme, rispetto ai modelli (quella di ogni pietra, nelle sue Avanzate, si moltiplica a questa). Più grandi: coprono uguale, quindi sono meno"), x => new JsonObject { ["size"] = x / 100.0 });
            var again = Theme.Button(Theme.IconText(Icons.Refresh, L.T("Altre posizioni"), null, 13), Theme.Kind.Ghost, L.T("Le stesse regole, le pietre messe in un altro modo"));
            again.HorizontalAlignment = HorizontalAlignment.Left; again.Margin = new Thickness(0, 0, 0, 8);
            again.Click += async (_, __) => await ChangeScree(new JsonObject { ["seed"] = (int)V("seed", 1) + 1 });
            card.Children.Add(again);

            var adv = Advanced(card, "scree");
            S(adv.Body, L.T("Ai piedi delle pareti"), V("talus", 1) * 100, 0, 200, false, "0", "%", L.T("Coni di detriti sotto le pareti di roccia"), x => new JsonObject { ["talus"] = x / 100.0 });
            S(adv.Body, L.T("Lunghezza dei coni"), V("reach", 1) * 100, 20, 300, false, "0", "%", L.T("Quanto scendono i coni: 100% = circa quanto è alta la parete sopra"), x => new JsonObject { ["reach"] = x / 100.0 });
            S(adv.Body, L.T("Nei canaloni"), V("gully", 0.6) * 100, 0, 200, false, "0", "%", L.T("Pietre lungo il fondo dei canaloni e dove si aprono a ventaglio"), x => new JsonObject { ["gully"] = x / 100.0 });
            S(adv.Body, L.T("Grandezza minima"), V("sizeMin", 0.5) * 100, 5, 2000, true, "0", "%", L.T("Le pietre più piccole, rispetto al modello"), x => new JsonObject { ["sizeMin"] = x / 100.0 });
            S(adv.Body, L.T("Grandezza massima"), V("sizeMax", 2) * 100, 5, 2000, true, "0", "%", L.T("Le pietre più grandi, rispetto al modello"), x => new JsonObject { ["sizeMax"] = x / 100.0 });
            S(adv.Body, L.T("Grandi in fondo"), V("sort", 0.7) * 100, 0, 100, false, "0", "%", L.T("Nei coni le pietre piccole restano vicino alla parete e le grandi rotolano più in basso; 0% = grandezze a caso"), x => new JsonObject { ["sort"] = x / 100.0 });
            S(adv.Body, L.T("Interrate"), V("bury", 0.35) * 100, 0, 90, false, "0", "%", L.T("Quanto le pietre affondano nel terreno"), x => new JsonObject { ["bury"] = x / 100.0 });
            // the colour (a copy of the stones' materials: the library model does not change)
            S(adv.Body, L.T("Accordo al terreno"), V("match", 1) * 100, 0, 100, false, "0", "%",
              L.T("Quanto le pietre prendono il colore della roccia del terreno: 0% = il colore del modello"), x => new JsonObject { ["match"] = x / 100.0 });
            var col = (set["color"] as JsonArray)?.Select(x => (double?)x ?? 0.5).ToArray() ?? new[] { 0.5, 0.45, 0.4 };
            var cf = new ColorField(L.T("Colore"), col, L.T("Un colore da dare alle pietre, con la loro luminosità"));
            cf.Committed += async c => await ChangeScree(new JsonObject { ["color"] = new JsonArray(c.Select(x => (JsonNode)JsonValue.Create(Math.Round(x, 4))!).ToArray()) });
            adv.Body.Children.Add(cf);
            S(adv.Body, L.T("Quanto colore"), V("colorAmount", 0) * 100, 0, 100, false, "0", "%", L.T("Quanto le pietre prendono il colore scelto qui sopra"), x => new JsonObject { ["colorAmount"] = x / 100.0 });
            S(adv.Body, L.T("Saturazione"), V("saturation", 1) * 100, 0, 200, false, "0", "%", L.T("Colori più vivi o più spenti"), x => new JsonObject { ["saturation"] = x / 100.0 });
            S(adv.Body, L.T("Luminosità"), V("brightness", 1) * 100, 20, 300, true, "0", "%", L.T("Pietre più chiare o più scure"), x => new JsonObject { ["brightness"] = x / 100.0 });
            S(adv.Body, L.T("Contrasto"), V("contrast", 0) * 100, -100, 100, false, "0", "%", L.T("Più o meno differenza fra le parti chiare e scure della pietra"), x => new JsonObject { ["contrast"] = x / 100.0 });
            // where: only what the camera sees (as the ecosystems, «Calcola solo l'area inquadrata»), or all the terrain
            var whole = new Toggle(L.T("Sempre intero"), (bool?)set["whole"] ?? false,
                L.T("Le pietre su tutto il terreno, anche dove la camera non guarda. Spento: solo nell'inquadratura quando «Calcola solo l'area inquadrata · Pietre e detriti» è acceso (più leggero)"));
            whole.Toggled += async v => await ChangeScree(new JsonObject { ["whole"] = v });
            adv.Body.Children.Add(whole);
            if (!((bool?)set["whole"] ?? false))
            {
                var again2 = Theme.Button(Theme.IconText(Icons.Refresh, L.T("Ricalcola dalla vista"), null, 13), Theme.Kind.Ghost,
                    L.T("Le pietre dove guarda la camera adesso (dopo averla spostata)"));
                again2.HorizontalAlignment = HorizontalAlignment.Left; again2.Margin = new Thickness(0, 0, 0, 8);
                again2.Click += async (_, __) => await ChangeScree(new JsonObject { ["camRefresh"] = true });
                adv.Body.Children.Add(again2);
            }
            var del = Theme.Button(Theme.IconText(Icons.Trash, L.T("Elimina pietre e detriti"), null, 13), Theme.Kind.Ghost, L.T("Toglie le pietre da questo terreno (Ctrl+Z le riporta)"));
            del.HorizontalAlignment = HorizontalAlignment.Left; del.Margin = new Thickness(0, 6, 0, 0);
            del.Click += async (_, __) =>
            {
                using (var busy = BeginBusy())
                    await Run(async api => { await api.Post("delete", new JsonObject { ["ids"] = new JsonArray(JsonValue.Create((string?)sc["id"])) }); });
                await RefreshScene();
                await LoadTerrain();
                if (_rightPanel == "landscape") RenderProps();
            };
            adv.Body.Children.Add(del);
            adv.Done(Math.Abs(V("talus", 1) - 1) > 1e-3 || Math.Abs(V("reach", 1) - 1) > 1e-3 || Math.Abs(V("gully", 0.6) - 0.6) > 1e-3
                     || Math.Abs(V("sizeMin", 0.5) - 0.5) > 1e-3 || Math.Abs(V("sizeMax", 2) - 2) > 1e-3 || Math.Abs(V("sort", 0.7) - 0.7) > 1e-3
                     || Math.Abs(V("bury", 0.35) - 0.35) > 1e-3 || Math.Abs(V("match", 1) - 1) > 1e-3 || V("colorAmount", 0) > 1e-3
                     || Math.Abs(V("saturation", 1) - 1) > 1e-3 || Math.Abs(V("brightness", 1) - 1) > 1e-3 || Math.Abs(V("contrast", 0)) > 1e-3);
        }
    }
}
