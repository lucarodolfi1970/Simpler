using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace Simpler
{
    /// <summary>
    /// Decals. Personali ▸ Decal: your PNG pictures with transparency, in folders (real folders under
    /// %APPDATA%\Simpler\decals; "Apri decal…" copies the chosen files into the folder shown). A click puts the decal in
    /// the middle of the view, a drag puts it where you let go: the engine (decals.py) projects it onto the piece under
    /// that point. Selected, it has its panel: size, depth, opacity, order, colour, roughness, metal, glow; the gizmo
    /// moves and turns it on the surface.
    /// </summary>
    public partial class MainWindow
    {
        string _decalFolder = "";

        // (1.78.2) the folder of «Le mie decal» comes from the engine (Impostazioni > Cartelle, paths.py "decals"):
        // it can be moved like the other libraries; until the engine answers, the default one
        static string _decalRootPath = "";

        static string DecalRoot
        {
            get
            {
                var d = _decalRootPath != "" ? _decalRootPath : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Simpler", "decals");
                try { Directory.CreateDirectory(d); } catch { }
                return d;
            }
        }

        async Task LoadDecalRoot()
        {
            try
            {
                var r = await _api.Get("paths");
                var f = (r?["folders"] as JsonArray)?.OfType<JsonObject>().FirstOrDefault(x => (string?)x["key"] == "decals");
                var p = (string?)f?["path"] ?? "";
                if (p != "") _decalRootPath = p;
            }
            catch { }
        }

        static string DecalDir(string rel) => rel == "" ? DecalRoot : Path.Combine(DecalRoot, rel.Replace('/', Path.DirectorySeparatorChar));

        static IEnumerable<string> DecalFiles(string dir, bool deep) =>
            Directory.Exists(dir) ? Directory.EnumerateFiles(dir, "*.png", deep ? SearchOption.AllDirectories : SearchOption.TopDirectoryOnly)
                                             .OrderBy(f => Path.GetFileName(f), StringComparer.CurrentCultureIgnoreCase)
                                  : Enumerable.Empty<string>();

        // ---------------------------------------------------------------- library tab

        // (1.78.4, Luca: «metti Simpler come folder anche nelle decals») Decal ▸ Simpler: the folder «Simpler» of the
        // decal library, as for models, plants and materials - a normal folder, red and read only with SimplerLocked
        const string SimplerDecals = "Simpler";
        static bool InSimplerDecals(string rel) => rel == SimplerDecals || rel.StartsWith(SimplerDecals + "/", StringComparison.Ordinal);
        static string DecalRel(string file)
        {
            var rel = Path.GetRelativePath(DecalRoot, Path.GetDirectoryName(file) ?? DecalRoot).Replace('\\', '/');
            return rel == "." || rel.StartsWith("..") ? "" : rel;
        }

        void RenderDecalBrowser(bool simpler = false)
        {
            var root = simpler ? SimplerDecals : "";
            if (simpler) { try { Directory.CreateDirectory(DecalDir(root)); } catch { } }
            if (!Directory.Exists(DecalDir(_decalFolder)) || InSimplerDecals(_decalFolder) != simpler) _decalFolder = root;
            var ro = simpler && SimplerLocked;
            string Rel(string full) => full == root ? "" : simpler ? full.Substring(root.Length + 1) : full;
            string Full(string rel) => rel == "" ? root : simpler ? root + "/" + rel : rel;
            var rootLabel = simpler ? L.T("Decal Simpler") : L.T("Le mie decal");
            var q = LibraryQuery;
            if (q != "")
            {
                RenderCrumbs(rootLabel, "", f => { _decalFolder = Full(f); _librarySearch.Text = ""; }, L.F("risultati per \"{0}\"", _librarySearch.Text.Trim()));
                int n = 0;
                foreach (var f in DecalFiles(DecalDir(root), true).Where(f => InSimplerDecals(DecalRel(f)) == simpler && Path.GetFileNameWithoutExtension(f).ToLowerInvariant().Contains(q)))
                {
                    _libraryTiles.Children.Add(DecalTile(f));
                    n++;
                }
                if (n == 0) _libraryTiles.Children.Add(EmptyNote(L.T("Nessuna decal trovata")));
                return;
            }
            RenderCrumbs(rootLabel, Rel(_decalFolder), f => _decalFolder = Full(f), null);
            if (_decalFolder != root) _libraryTiles.Children.Add(UpTile(ParentFolder(_decalFolder), f => _decalFolder = f, false));
            // (1.79, Luca: «perché new folder è in fondo a destra?») «Nuova cartella» first, with the tiles that add
            if (!ro)
            {
                var add = BigTile(TileIcon(Icons.Plus, Theme.Accent), L.T("Apri decal…"), "",
                                  L.T("Aggiunge a questa cartella una o più immagini PNG con trasparenza: diventano decal da mettere sui modelli"));
                add.Click += async (_, __) => await OpenDecals(_decalFolder);
                _libraryTiles.Children.Add(add);
                var nf = BigTile(TileIcon(Icons.Plus, Theme.Accent), L.T("Nuova cartella"), "", L.T("Crea una cartella qui, per raggruppare le decal (es. Graffiti, Cartelli, Sporco)"));
                nf.Click += (_, __) => NewDecalFolder(_decalFolder);
                _libraryTiles.Children.Add(nf);
            }
            var dir = DecalDir(_decalFolder);
            foreach (var sub in Directory.Exists(dir) ? Directory.GetDirectories(dir).OrderBy(d => d, StringComparer.CurrentCultureIgnoreCase) : Enumerable.Empty<string>())
            {
                var rel = (_decalFolder == "" ? "" : _decalFolder + "/") + Path.GetFileName(sub);
                if (!simpler && InSimplerDecals(rel)) continue;              // (in Decal ▸ Simpler)
                var count = DecalFiles(sub, true).Count();
                var first = ParentFolder(rel) is "" or SimplerDecals;      // (1.79.0: the first level gets the icon of its kind)
                var t = BigTile(FolderIcon(ro ? Theme.C("#E5534B") : Theme.Warm, first ? FolderBadge(Path.GetFileName(sub)) : null), Path.GetFileName(sub), count == 1 ? L.T("1 decal") : L.F("{0} decal", count),
                                Path.GetFileName(sub) + "\n" + (ro ? L.T("Clic per aprire") : L.T("Clic per aprire · tasto destro: apri decal, nuova sottocartella, rinomina, elimina")));
                t.Click += (_, __) => { _decalFolder = rel; RenderLibrary(); };
                if (!ro) t.ContextMenu = DecalFolderMenu(rel);
                _libraryTiles.Children.Add(t);
            }
            var files = DecalFiles(dir, false).ToList();
            foreach (var f in files) _libraryTiles.Children.Add(DecalTile(f));
            if (files.Count == 0 && _decalFolder == root && !Directory.EnumerateDirectories(dir).Any(d => simpler || !InSimplerDecals(Path.GetFileName(d))))
                _libraryTiles.Children.Add(EmptyNote(simpler ? L.T("Le decal che arriveranno con Simpler: aggiungile qui con «Apri decal…»")
                                                             : L.T("Ancora nessuna decal: con «Apri decal…» aggiungi le tue immagini PNG con trasparenza")));
        }

        // (1.79, Luca: «conviene per tutti uno sfondo bianco») the decals on white: stains, streaks and dark tags are
        // seen at once (on the dark checker they were lost)
        static readonly Brush DecalBack = Brushes.White;

        static BitmapImage? DecalThumb(string file)
        {
            try
            {
                var b = new BitmapImage();
                b.BeginInit();
                b.CacheOption = BitmapCacheOption.OnLoad;
                b.CreateOptions = BitmapCreateOptions.IgnoreImageCache;
                b.UriSource = new Uri(file);
                b.DecodePixelWidth = 160;
                b.EndInit();
                b.Freeze();
                return b;
            }
            catch { return null; }
        }

        Button DecalTile(string file)
        {
            var name = Path.GetFileNameWithoutExtension(file);
            var thumb = DecalThumb(file);
            var pic = new Border
            {
                Width = 80, Height = 80, CornerRadius = new CornerRadius(6), Background = DecalBack, HorizontalAlignment = HorizontalAlignment.Center,
                Margin = new Thickness(0, 2, 0, 6), ClipToBounds = true,
                Child = new Image { Source = thumb, Stretch = Stretch.Uniform, Margin = new Thickness(4) },
            };
            var btn = BigTile(pic, name, "", name + "\n" + L.T("Clic: al centro della vista · trascina nella vista sul modello dove vuoi · tasto destro: rinomina, elimina"));
            btn.Tag = name;
            btn.Click += async (_, __) => await PlaceDecal(file, null);
            MakeDraggable(btn, name, async (x, y) =>
            {
                var at = await AskViewPoint(x, y);
                if (at != null) await PlaceDecal(file, at);
            }, null, () => thumb);
            var m = new ContextMenu();
            void Item(string text, Action act) { var i = new MenuItem { Header = text }; i.Click += (_, __) => act(); m.Items.Add(i); }
            Item(L.T("Metti al centro della vista"), () => _ = PlaceDecal(file, null));
            var locked = SimplerLocked && InSimplerDecals(DecalRel(file));      // (1.78.4: Decal ▸ Simpler read only)
            if (!locked) Item(L.T("Rinomina…"), () =>
            {
                var n = InputDialog.Ask(this, L.T("Rinomina decal"), L.T("Nome della decal"), name);
                if (n == null || n.Trim() == "" || n == name) return;
                var target = Path.Combine(Path.GetDirectoryName(file)!, string.Concat(n.Trim().Split(Path.GetInvalidFileNameChars())) + ".png");
                try { File.Move(file, target); } catch (Exception ex) { Msg.Show(this, ex.Message, "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning); }
                RenderLibrary();
            });
            Item(L.T("Mostra nella cartella"), () => { try { System.Diagnostics.Process.Start("explorer.exe", "/select,\"" + file + "\""); } catch { } });
            if (!locked) m.Items.Add(new Separator());
            if (!locked) Item(L.T("Elimina"), () =>
            {
                if (Msg.Show(this, L.F("Eliminare la decal «{0}» dalla libreria?\nQuelle già messe nei progetti restano (l'immagine è salvata nel progetto).", name),
                             "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
                try { File.Delete(file); } catch (Exception ex) { Msg.Show(this, ex.Message, "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning); }
                RenderLibrary();
            });
            btn.ContextMenu = m;
            return Fav(btn, "decal", file, name, null);
        }

        ContextMenu DecalFolderMenu(string rel)
        {
            var m = new ContextMenu();
            void Item(string text, Action act) { var i = new MenuItem { Header = text }; i.Click += (_, __) => act(); m.Items.Add(i); }
            Item(L.T("Apri"), () => { _decalFolder = rel; RenderLibrary(); });
            Item(L.T("Apri decal…"), () => _ = OpenDecals(rel));
            Item(L.T("Nuova sottocartella…"), () => NewDecalFolder(rel));
            Item(L.T("Rinomina…"), () =>
            {
                var n = InputDialog.Ask(this, L.T("Rinomina cartella"), L.T("Nome della cartella"), FolderName(rel));
                if (n == null || n.Trim() == "" || n == FolderName(rel)) return;
                var src = DecalDir(rel);
                var dst = Path.Combine(Path.GetDirectoryName(src)!, string.Concat(n.Trim().Split(Path.GetInvalidFileNameChars())));
                try { Directory.Move(src, dst); } catch (Exception ex) { Msg.Show(this, ex.Message, "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning); }
                RenderLibrary();
            });
            Item(L.T("Mostra nella cartella"), () => { try { System.Diagnostics.Process.Start("explorer.exe", "\"" + DecalDir(rel) + "\""); } catch { } });
            m.Items.Add(new Separator());
            Item(L.T("Elimina cartella"), () =>
            {
                if (Msg.Show(this, L.F("Eliminare la cartella \"{0}\"?\nLe decal che contiene non vengono eliminate: passano nella cartella superiore.", FolderName(rel)),
                             "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
                try
                {
                    var src = DecalDir(rel);
                    var up = Path.GetDirectoryName(src)!;
                    foreach (var f in Directory.GetFiles(src, "*.png", SearchOption.AllDirectories))
                        File.Move(f, FreeDecalName(up, Path.GetFileNameWithoutExtension(f)));
                    Directory.Delete(src, true);
                }
                catch (Exception ex) { Msg.Show(this, ex.Message, "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning); }
                if (_decalFolder == rel || _decalFolder.StartsWith(rel + "/")) _decalFolder = ParentFolder(rel);
                RenderLibrary();
            });
            return m;
        }

        void NewDecalFolder(string parent)
        {
            var name = InputDialog.Ask(this, L.T("Nuova cartella"), L.T("Nome della cartella (usa / per creare sottocartelle)"), "");
            if (name == null) return;
            var rel = string.Join("/", name.Replace('\\', '/').Split('/').Select(p => string.Concat(p.Trim().Split(Path.GetInvalidFileNameChars()))).Where(p => p != ""));
            if (rel == "") return;
            var full = (parent == "" ? "" : parent + "/") + rel;
            try { Directory.CreateDirectory(DecalDir(full)); } catch (Exception ex) { Msg.Show(this, ex.Message, "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning); return; }
            _decalFolder = full;
            RenderLibrary();
        }

        static string FreeDecalName(string dir, string stem)
        {
            for (int i = 1; ; i++)
            {
                var p = Path.Combine(dir, stem + (i == 1 ? "" : " " + i) + ".png");
                if (!File.Exists(p)) return p;
            }
        }

        /// <summary>"Apri decal…": PNG files copied into the folder (the originals stay where they are).</summary>
        async Task OpenDecals(string rel)
        {
            var dlg = new Microsoft.Win32.OpenFileDialog { Filter = L.T("Immagini PNG|*.png"), Multiselect = true, InitialDirectory = StartFolder("decal"), Title = L.T("Scegli le decal (PNG con trasparenza)") };
            if (dlg.ShowDialog(this) != true) return;
            Keep("decal", dlg.FileName);
            var dir = DecalDir(rel);
            Directory.CreateDirectory(dir);
            var opaque = new List<string>();
            int n = 0;
            foreach (var f in dlg.FileNames)
            {
                try
                {
                    var dec = BitmapDecoder.Create(new Uri(f), BitmapCreateOptions.DelayCreation, BitmapCacheOption.None);
                    var fmt = dec.Frames[0].Format;
                    if (fmt != PixelFormats.Bgra32 && fmt != PixelFormats.Pbgra32 && fmt != PixelFormats.Rgba64 && fmt != PixelFormats.Prgba64 && fmt != PixelFormats.Rgba128Float && fmt != PixelFormats.Prgba128Float
                        && !(dec.Frames[0].Palette?.Colors.Any(c => c.A < 255) ?? false))
                        opaque.Add(Path.GetFileName(f));
                    File.Copy(f, FreeDecalName(dir, Path.GetFileNameWithoutExtension(f)));
                    n++;
                }
                catch (Exception ex) { AppLog.Write("decal copy: " + ex.Message); }
            }
            _decalFolder = rel;
            _libraryTab = InSimplerDecals(rel) ? "simplerdecals" : "mydecals";
            RenderLibrary();
            Status(n == 1 ? L.T("1 decal aggiunta") : L.F("{0} decal aggiunte", n));
            if (opaque.Count > 0)
                Msg.Show(this, L.T("Queste immagini non hanno trasparenza: sul modello si vedranno come un rettangolo pieno.") + "\n\n" + string.Join("\n", opaque.Take(12)),
                         "Simpler", MessageBoxButton.OK, MessageBoxImage.Information);
            await Task.CompletedTask;
        }

        // ---------------------------------------------------------------- placing

        /// <summary>The decal on the surface at the point (a drop) or at the middle of the view; about a quarter of the
        /// distance it is looked from wide.</summary>
        async Task PlaceDecal(string file, JsonObject? at)
        {
            if (!File.Exists(file)) { RenderLibrary(); return; }
            var vp = at ?? await AskViewPoint();
            if (vp == null) return;
            if (!((bool?)vp["hit"] ?? false))
            {
                Status(L.T("Metti la decal su un modello: trascinala sulla superficie dove la vuoi"), true);
                return;
            }
            var dist = Math.Max(1, (double?)vp["distance"] ?? 300);
            var width = Math.Clamp(Math.Round(dist * 0.25), 10, 400);
            string id = "", target = "";
            using (BeginBusy())
            {
                await Run(async api =>
                {
                    var r = await api.Post("decal/add", new JsonObject
                    {
                        ["file"] = file, ["location"] = vp["point"]?.DeepClone(), ["normal"] = vp["normal"]?.DeepClone(),
                        ["camera"] = vp["camera"]?.DeepClone(), ["width"] = width,
                        ["hitObject"] = $"{(string?)vp["objectId"]}/{(string?)vp["meshId"]}/{(string?)vp["material"]}",
                    });
                    id = (string?)r["id"] ?? "";
                    target = (string?)r["target"] ?? "";
                });
            }
            if (id == "") return;
            if (target == "") Status(L.T("Decal messa, ma sotto quel punto non c'è un pezzo su cui proiettarla: spostala su un modello"), true);
            SetSelectionRaw(id);
            await RefreshScene();
        }

        // ---------------------------------------------------------------- panel

        UIElement DecalSection(SceneObject o)
        {
            var d = o.Decal ?? new JsonObject();
            double V(string k, double def) { try { return (double?)d[k] ?? def; } catch { return def; } }
            var sp = new StackPanel();
            sp.Children.Add(SectionTitle(L.T("Decal")));
            sp.Children.Add(HintSmall(L.T("Proiettata sul pezzo sotto di lei: con il gizmo la sposti e la ruoti sulla superficie.")));
            async Task Edit(JsonObject values)
            {
                values["id"] = o.Id;
                await Run(async api => { await api.Post("decal/edit", values); });
                await RefreshScene();
            }
            double w = V("w", 50), l = V("l", 50), ratio = w > 0 ? l / w : 1;
            var size = new ValueSlider(L.T("Dimensione"), w, 1, 2000, true, "0.#", "cm", null, L.T("Larghezza della decal (l'altezza la segue, in proporzione)"));
            size.Committed += async v => await Edit(new JsonObject { ["w"] = Math.Round(v, 2), ["l"] = Math.Round(v * ratio, 2) });
            sp.Children.Add(size);
            var depth = new ValueSlider(L.T("Profondità"), V("d", 20), 0.5, 500, true, "0.#", "cm",
                                        null, L.T("Quanto entra la proiezione davanti e dietro la superficie: alta su superfici mosse (mattoni, sassi), bassa per non finire su oggetti vicini"));
            depth.Committed += async v => await Edit(new JsonObject { ["d"] = Math.Round(v, 2) });
            sp.Children.Add(depth);
            // (Luca: «un sacco della spazzatura tondeggiante … vorrei poterlo fare con un buon risultato»)
            var angle = new ValueSlider(L.T("Angolo massimo"), V("angle", 90), 0, 90, false, "0", "°",
                                        null, L.T("Dove la superficie si gira oltre questo angolo rispetto alla decal, la decal sfuma: 60–70° per non sbavare su gomme, gradini o paletti dentro la scatola; 90° per stamparla su tutto, anche su oggetti tondeggianti"));
            angle.Committed += async v => await Edit(new JsonObject { ["angle"] = Math.Round(v, 1) });
            sp.Children.Add(angle);
            var op = new ValueSlider(L.T("Opacità"), V("opacity", 1) * 100, 0, 100, false, "0", "%", null, L.T("Quanto si vede la decal"));
            op.Committed += async v => await Edit(new JsonObject { ["opacity"] = Math.Round(v, 2) / 100.0 });
            sp.Children.Add(op);
            var tintArr = (d["tint"] as JsonArray)?.Select(x => (double?)x ?? 1).ToArray();
            var tint = new ColorField(L.T("Colore"), tintArr is { Length: 3 } ? tintArr : new[] { 1.0, 1.0, 1.0 }, L.T("Moltiplica i colori della decal: bianco = come l'immagine"));
            tint.Committed += async c => await Edit(new JsonObject { ["tint"] = new JsonArray(c.Select(x => (JsonNode)JsonValue.Create(Math.Round(x, 4))!).ToArray()) });
            sp.Children.Add(tint);

            var mode = (string?)d["mode"] ?? "alpha";
            var has = new HashSet<string>((d["has"] as JsonArray)?.Select(x => (string?)x ?? "") ?? Enumerable.Empty<string>());
            var maps = d["maps"] as JsonObject ?? new JsonObject();
            string MapOf(string ch) => (string?)maps[ch] ?? "";
            var colorImage = (string?)d["image"] ?? "";

            // (closed Avanzate: which maps the decal has, so they are not forgotten inside)
            var present = new[] { ("normal", L.T("rilievo")), ("roughness", L.T("rugosità")), ("metalness", L.T("metallo")), ("opacity", L.T("trasparenza")), ("emission", L.T("emissione")) }
                .Where(x => MapOf(x.Item1) != "").Select(x => x.Item2).ToList();
            if (mode != "multiply" && present.Count > 0)
                sp.Children.Add(HintSmall(L.F("Mappe: {0} (in Avanzate)", string.Join(" · ", present))));
            // Avanzate: one card per channel, each with its map and only the values that belong to it
            // (before: the maps piled up under the main values, the sliders of the same channels somewhere else)
            var a = Advanced(sp, "decal");
            StackPanel Card(string title, string? tip = null)
            {
                var body = new StackPanel();
                var t = Theme.Label(title, 12, Theme.Text);
                t.FontWeight = FontWeights.SemiBold;
                t.Margin = new Thickness(0, 0, 0, 6);
                if (tip != null) t.ToolTip = tip;
                body.Children.Add(t);
                a.Body.Children.Add(new Border
                {
                    Child = body, Background = Theme.B(Theme.Inset), BorderBrush = Theme.B(Theme.Line), BorderThickness = new Thickness(1),
                    CornerRadius = new CornerRadius(6), Padding = new Thickness(10, 8, 10, 4), Margin = new Thickness(0, 0, 0, 8),
                });
                return body;
            }
            // the picture of the decal itself: changed, copied, pasted like the other maps
            var cc = Card(L.T("Immagine (colore)"), L.T("La figura della decal: la sua trasparenza ritaglia la forma (se non c'è una mappa di opacità)"));
            DecalMapRow(cc, L.T("Mappa"), "color", colorImage, Edit, L.T("La figura della decal. Cambiandola la misura resta: Larghezza e Altezza in Forma"), null, removable: false);
            if (mode != "multiply")
            {
                // a crack on a wall needs its normal map to look carved in
                var cn = Card(L.T("Rilievo (normale)"), L.T("Dà rilievo alla decal (una crepa, un'incisione): cambia la luce, non la forma"));
                DecalMapRow(cn, L.T("Mappa"), "normal", MapOf("normal"), Edit,
                            L.T("Dà rilievo alla decal (una crepa, un'incisione): cambia la luce, non la forma"),
                            colorImage != "" ? () => DecalNormalFromColor(o.Id, colorImage) : null);
                if (MapOf("normal") != "")
                {
                    var ns = new ValueSlider(L.T("Intensità"), V("nstr", 1), 0, 5, false, "0.##", null, null, L.T("Quanto si vede il rilievo della normal map (1 = com'è)"));
                    ns.Committed += async v => await Edit(new JsonObject { ["nstr"] = Math.Round(v, 2) });
                    cn.Children.Add(ns);
                    var dx = new Toggle(L.T("Normale DirectX"), (bool?)d["ndx"] ?? false, L.T("Accendi se il rilievo sembra rovesciato (in fuori invece che in dentro): mappe fatte per DirectX, con il verde capovolto"));
                    dx.Toggled += async v => await Edit(new JsonObject { ["ndx"] = v });
                    dx.Margin = new Thickness(0, 0, 0, 6);
                    cn.Children.Add(dx);
                }
                else cn.Children.Add(HintSmall(L.T("Senza mappa la decal è piatta. La bacchetta la ricava dall'immagine.")));

                var cr = Card(L.T("Rugosità"));
                DecalMapRow(cr, L.T("Mappa"), "roughness", MapOf("roughness"), Edit, L.T("Chiaro = opaco, scuro = lucido (sostituisce il cursore Rugosità)"), null);
                if (MapOf("roughness") == "" && !has.Contains("roughness"))
                {
                    var ro = new ValueSlider(L.T("Rugosità"), V("rough", 0.6) * 100, 0, 100, false, "0", "%", null, L.T("0% = lucida come vernice fresca · 100% = opaca come carta"));
                    ro.Committed += async v => await Edit(new JsonObject { ["rough"] = Math.Round(v, 2) / 100.0 });
                    cr.Children.Add(ro);
                }
                else cr.Children.Add(HintSmall(L.T("La mappa decide quanto è lucida, punto per punto.")));

                var cm = Card(L.T("Metallo"));
                DecalMapRow(cm, L.T("Mappa"), "metalness", MapOf("metalness"), Edit, L.T("Bianco = metallo, nero = no (sostituisce il cursore Metallo)"), null);
                if (MapOf("metalness") == "" && !has.Contains("metalness"))
                {
                    var me = new ValueSlider(L.T("Metallo"), V("metal", 0) * 100, 0, 100, false, "0", "%", null, L.T("Per adesivi metallizzati o targhe"));
                    me.Committed += async v => await Edit(new JsonObject { ["metal"] = Math.Round(v, 2) / 100.0 });
                    cm.Children.Add(me);
                }
                else cm.Children.Add(HintSmall(L.T("La mappa decide dove è metallo, punto per punto.")));

                var co = Card(L.T("Trasparenza"));
                DecalMapRow(co, L.T("Mappa"), "opacity", MapOf("opacity"), Edit, L.T("Bianco = si vede, nero = trasparente (al posto della trasparenza dell'immagine)"), null);
                co.Children.Add(HintSmall(MapOf("opacity") != "" ? L.T("Bianco = si vede, nero = trasparente. L'Opacità in alto la attenua tutta.")
                                                                  : L.T("Senza mappa conta la trasparenza dell'immagine (PNG).")));

                // emission map: only its light parts glow (neon, luminous writing); setting it turns the glow on
                var ce = Card(L.T("Emissione (luce)"), L.T("La decal emette luce del suo colore: insegne, schermi, neon"));
                var em = new ValueSlider(L.T("Luminosità"), V("emit", 0), 0, 20, false, "0.#", null, null, L.T("La decal emette luce del suo colore: insegne, schermi (0 = spenta)"));
                em.Committed += async v => await Edit(new JsonObject { ["emit"] = Math.Round(v, 2) });
                ce.Children.Add(em);
                DecalMapRow(ce, L.T("Mappa"), "emission", MapOf("emission"), Edit,
                            L.T("Solo le parti chiare della mappa si accendono (neon, scritte luminose), del colore della decal; la forza è Luminosità"), null);
            }
            else sp.Children.Add(HintSmall(L.T("Questa decal è una macchia (scurisce la superficie sotto): non usa mappe.")));

            var cf = Card(L.T("Forma"));
            var wS = new ValueSlider(L.T("Larghezza"), w, 1, 2000, true, "0.#", "cm", null, L.T("Solo la larghezza (deforma l'immagine)"));
            wS.Committed += async v => await Edit(new JsonObject { ["w"] = Math.Round(v, 2) });
            cf.Children.Add(wS);
            var lS = new ValueSlider(L.T("Altezza"), l, 1, 2000, true, "0.#", "cm", null, L.T("Solo l'altezza (deforma l'immagine)"));
            lS.Committed += async v => await Edit(new JsonObject { ["l"] = Math.Round(v, 2) });
            cf.Children.Add(lS);
            var ord = new ValueSlider(L.T("Ordine"), V("order", 0), 0, 10, false, "0", null, null, L.T("Quale decal sta sopra quando due si sovrappongono: il numero più alto"));
            ord.Committed += async v => await Edit(new JsonObject { ["order"] = (int)Math.Round(v) });
            cf.Children.Add(ord);

            bool changed = Math.Abs(V("rough", 0.6) - 0.6) > 1e-3 || V("metal", 0) > 0 || V("emit", 0) > 0 || V("order", 0) > 0 || Math.Abs(l - w * ratio) > 0.1;
            a.Done(changed, async () => await Edit(new JsonObject { ["rough"] = 0.6, ["metal"] = 0.0, ["emit"] = 0.0, ["order"] = 0 }));
            var file = (string?)d["file"] ?? "";
            var source = (string?)d["source"] ?? "";
            if (source != "") sp.Children.Add(HintSmall(L.F("{0} · CC0 (salvata nel progetto)", source) + (mode == "multiply" ? " · " + L.T("macchia: scurisce la superficie sotto") : "")));
            else if (file != "") sp.Children.Add(HintSmall(L.F("Immagine: {0} (salvata nel progetto)", file)));
            return sp;
        }

        /// <summary>A map slot of a decal: thumbnail, name, load / take away (and "Genera" for the normal).</summary>
        void DecalMapRow(Panel parent, string label, string channel, string image, Func<JsonObject, Task> edit, string tip, Func<Task>? generate, bool removable = true)
        {
            var row = new DockPanel { Margin = new Thickness(0, 2, 0, 8), ToolTip = tip };
            var l = Theme.Label(label, 12, Theme.TextMuted);
            l.Width = label == L.T("Mappa") ? 52 : 96;
            row.Children.Add(l);
            var thumb = new Border { Width = 34, Height = 34, CornerRadius = new CornerRadius(4), Background = Theme.B(Theme.Inset),
                                     BorderBrush = Theme.B(Theme.Line), BorderThickness = new Thickness(1), Margin = new Thickness(0, 0, 8, 0) };
            row.Children.Add(thumb);
            var load = Theme.Button(image == "" ? L.T("Carica…") : L.T("Cambia…"), Theme.Kind.Normal, L.T("Scegli un'immagine (PNG, JPG, EXR, TIFF…)"));
            load.MinHeight = 28; load.FontSize = 12; load.Padding = new Thickness(8, 0, 8, 0);
            DockPanel.SetDock(load, Dock.Right);
            row.Children.Add(load);
            if (image != "" && removable)
            {
                var rm = Theme.Button("×", Theme.Kind.Ghost, L.T("Togli la mappa"));
                rm.MinHeight = 28; rm.Padding = new Thickness(8, 0, 8, 0);
                rm.Click += async (_, __) => await edit(new JsonObject { ["maps"] = new JsonObject { [channel] = "" } });
                DockPanel.SetDock(rm, Dock.Right);
                row.Children.Add(rm);
            }
            if (generate != null)
            {
                var gen = Theme.Button(Theme.Icon(Icons.Wand, Theme.TextSoft, 14, 1.2), Theme.Kind.Ghost,
                                       L.T("Genera la normale dall'immagine della decal sul tuo computer (DeepBump)"));
                gen.MinHeight = 28; gen.Width = 30; gen.Height = 28; gen.Padding = new Thickness(0);
                gen.Click += async (_, __) => await generate();
                DockPanel.SetDock(gen, Dock.Right);
                row.Children.Add(gen);
            }
            var fn = Theme.Label(image == "" ? L.T("nessuna mappa") : image, 12, image == "" ? Theme.TextFaint : Theme.TextSoft);
            fn.ToolTip = image == "" ? tip : image;
            row.Children.Add(fn);
            load.Click += async (_, __) =>
            {
                var dlg = new Microsoft.Win32.OpenFileDialog { Filter = L.T(ImageFilter), InitialDirectory = StartFolder("image") };
                if (dlg.ShowDialog(this) != true) return;
                Keep("image", dlg.FileName);
                await edit(new JsonObject { ["maps"] = new JsonObject { [channel] = dlg.FileName } });
            };
            // right click: copy this map, paste a map copied in Simpler (from a material or another decal), or a picture
            // from the clipboard (a cut-out, a copied image file) - as the maps of the materials
            void PasteMenu(object s, System.Windows.Input.MouseButtonEventArgs e)
            {
                e.Handled = true;
                var cm = new ContextMenu { PlacementTarget = (UIElement)s };
                void Item(string text, bool enabled, Func<Task> act)
                {
                    var i = new MenuItem { Header = text, IsEnabled = enabled };
                    i.Click += async (_, __) => await act();
                    cm.Items.Add(i);
                }
                Item(L.T("Copia la mappa"), image != "", async () => await CopyMap(image, null));
                bool canPaste = false;
                try { canPaste = Clipboard.ContainsData(MapClipFormat); } catch { }
                Item(L.T("Incolla la mappa"), canPaste, async () =>
                {
                    JsonObject? clip = null;
                    try { if (Clipboard.GetData(MapClipFormat) is string cs) clip = JsonNode.Parse(cs) as JsonObject; } catch { }
                    if (clip == null) { Status(L.T("Negli appunti non c'è una mappa copiata in Simpler")); return; }
                    var img = (string?)clip["image"] ?? "";
                    var file = (string?)clip["path"] ?? "";
                    bool same = (int?)clip["process"] == Environment.ProcessId && (int?)clip["project"] == _aiProjectGen;
                    var value = same && img != "" ? img : File.Exists(file) ? file : "";
                    if (value == "")
                    {
                        Msg.Show(this, L.T("La mappa copiata era incorporata in un altro progetto e non ha un file sul disco: non posso incollarla qui. Copiala di nuovo da questo progetto, o caricala dal suo file."),
                                 "Simpler", MessageBoxButton.OK, MessageBoxImage.Information);
                        return;
                    }
                    await edit(new JsonObject { ["maps"] = new JsonObject { [channel] = value } });
                    Status(L.F("Mappa incollata: {0}", (string?)clip["file"] ?? img));
                });
                Item(L.T("Incolla immagine dagli appunti"), ClipboardHasPicture(), async () =>
                {
                    var f = ClipboardPictureFile();
                    if (f == null) { Status(L.T("Negli appunti non c'è un'immagine")); return; }
                    await edit(new JsonObject { ["maps"] = new JsonObject { [channel] = f.Value.path } });
                    Status(L.F("Immagine incollata come mappa: {0}", Path.GetFileName(f.Value.path)));
                });
                cm.IsOpen = true;
            }
            thumb.MouseRightButtonUp += PasteMenu;
            fn.Background = Brushes.Transparent;
            fn.MouseRightButtonUp += PasteMenu;
            parent.Children.Add(row);
            if (image != "") _ = LoadThumb(image, thumb);
        }

        /// <summary>"Genera" on the normal of a decal: DeepBump (color_to_normals) on its picture; the result is
        /// embedded in the project with the decal.</summary>
        async Task DecalNormalFromColor(string decalId, string colorImage)
        {
            var title = L.T("Normale dall'immagine della decal");
            var db = FindDeepBump();
            var py = BlenderPython();
            if (db == null || py == null)
            {
                Msg.Show(this, db == null ? L.T("Manca la cartella tools\\deepbump di Simpler: reinstalla Simpler.") : L.T("Non trovo il Python di Blender."),
                         "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }
            using var busy = BeginBusy();
            var clock = System.Diagnostics.Stopwatch.StartNew();
            try
            {
                if (!await EnsureDeepBumpLibs(py)) return;
                Directory.CreateDirectory(DeepBumpWork);
                CleanDeepBumpWork();
                ShowTask(L.F("{0}: preparo l'immagine…", title));
                var input = Path.Combine(DeepBumpWork, Guid.NewGuid().ToString("N") + "-in.png");
                await File.WriteAllBytesAsync(input, await MapAsRgbPng(colorImage, ""));
                var result = await RunStep(py, db, input, "color_to_normals", title, "");
                // a clear name in the project (contachilometri_normal.png), not the temporary one
                // (in a folder of its own: the engine reuses an image loaded before from the same path)
                var dir = Path.Combine(DeepBumpWork, Guid.NewGuid().ToString("N"));
                var named = Path.Combine(dir, Path.GetFileNameWithoutExtension(colorImage) + "_normal.png");
                try { Directory.CreateDirectory(dir); File.Copy(result, named, true); result = named; } catch { }
                await Run(async api => { await api.Post("decal/edit", new JsonObject { ["id"] = decalId, ["maps"] = new JsonObject { ["normal"] = result } }); });
                await RefreshScene();
                Status(L.F("{0}: fatto in {1} s{2}", title, (int)clock.Elapsed.TotalSeconds, " · " + L.T("incorporata nel progetto")));
            }
            catch (Exception ex)
            {
                AppLog.Write("deepbump decal: " + ex);
                Msg.Show(this, L.F("{0}: non è riuscito.", title) + "\n\n" + ex.Message, "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning);
            }
            finally { HideTask(); }
        }

        // ---------------------------------------------------------------- ambientCG (menu Decal)

        JsonArray _acgDecals = new();
        string _acgFolder = "";
        readonly Dictionary<string, BitmapImage> _acgThumbs = new();

        void RenderAcgDecals()
        {
            if (_acgDecals.Count == 0)
            {
                _libraryTiles.Children.Add(EmptyNote(L.T("Caricamento dell'elenco delle decal di ambientCG…")));
                _ = LoadAcgDecals();
                return;
            }
            var all = _acgDecals.OfType<JsonObject>().ToList();
            var q = LibraryQuery;
            if (q != "")
            {
                RenderCrumbs("ambientCG", "", f => { _acgFolder = f; _librarySearch.Text = ""; }, L.F("risultati per \"{0}\"", _librarySearch.Text.Trim()));
                var found = all.Where(a => (((string?)a["name"] ?? "") + " " + ((string?)a["folder"] ?? "") + " " + string.Join(" ", (a["tags"] as JsonArray)?.Select(t => (string?)t) ?? Array.Empty<string>()))
                                              .ToLowerInvariant().Contains(q)).ToList();
                foreach (var a in found) _libraryTiles.Children.Add(AcgDecalTile(a));
                if (found.Count == 0) _libraryTiles.Children.Add(EmptyNote(L.T("Nessuna decal trovata")));
                return;
            }
            var folders = all.Select(a => (string?)a["folder"] ?? "").Distinct().OrderBy(f => f, StringComparer.CurrentCultureIgnoreCase).ToList();
            if (_acgFolder != "" && !folders.Contains(_acgFolder)) _acgFolder = "";
            RenderCrumbs("ambientCG", _acgFolder, f => _acgFolder = f, null);
            if (_acgFolder == "")
            {
                foreach (var f in folders)
                {
                    var items = all.Where(a => (string?)a["folder"] == f).ToList();
                    var t = FolderTile(f, items.Count, () => { _acgFolder = f; RenderLibrary(); }, "acgdecal", items.Count(a => (bool?)a["downloaded"] ?? false));
                    _libraryTiles.Children.Add(t);
                }
                return;
            }
            _libraryTiles.Children.Add(UpTile("", f => _acgFolder = f, false));
            foreach (var a in all.Where(a => (string?)a["folder"] == _acgFolder)) _libraryTiles.Children.Add(AcgDecalTile(a));
        }

        async Task LoadAcgDecals()
        {
            for (int attempt = 0; attempt < 40; attempt++)
            {
                JsonObject? r = null;
                try { if (_api != null) r = await _api.Get("library/decals/list"); } catch { }
                if (r?["assets"] is JsonArray list && list.Count > 0)
                {
                    _acgDecals = (JsonArray)list.DeepClone();
                    if (_libraryTab == "acgdecals") RenderLibrary();
                    return;
                }
                if (r != null && !((bool?)r["loading"] ?? false) && (string?)r["error"] is string err && err != "")
                {
                    if (_libraryTab == "acgdecals")
                    {
                        _libraryTiles.Children.Clear();
                        _libraryTiles.Children.Add(EmptyNote(L.T("ambientCG non raggiungibile (serve la connessione a Internet): ") + err));
                    }
                    return;
                }
                await Task.Delay(1500);
            }
        }

        Button AcgDecalTile(JsonObject a)
        {
            var id = (string?)a["id"] ?? "";
            var label = (string?)a["name"] ?? id;
            var downloaded = (bool?)a["downloaded"] ?? false;
            var tile = new StackPanel { Width = 92, Margin = new Thickness(4, 0, 4, 0) };   // (no top/bottom margin: two-line names fit the 130 px tile)
            var img = new Border { Width = 72, Height = 72, CornerRadius = new CornerRadius(8), Background = DecalBack };
            tile.Children.Add(WithBadge(img, 72, "d:" + id, downloaded, new Thickness(0, 2, 0, 6)));
            tile.Children.Add(Theme.TileText(new TextBlock { Text = label, FontSize = 11.5, TextAlignment = TextAlignment.Center, TextWrapping = TextWrapping.Wrap,
                                              Foreground = Theme.B(downloaded ? Theme.TextSoft : Theme.TextMuted), MaxHeight = 32 }));
            double w = (double?)a["w"] ?? 0, l = (double?)a["l"] ?? 0;
            var tip = label + (w > 0 && l > 0 ? " · " + L.F("{0} × {1} cm", Num.F(w, 0), Num.F(l, 0)) : "") + "\n" +
                      (downloaded ? L.T("Già scaricata") : L.T("Si scarica al primo uso (1K, qualche MB)")) + "\n" +
                      L.T("Clic: al centro della vista · trascina nella vista sul modello dove vuoi") + "\nambientCG · CC0";
            var btn = Theme.Button(tile, Theme.Kind.Normal, tip);
            btn.Padding = new Thickness(2, 4, 2, 6);
            btn.Margin = new Thickness(4);
            btn.VerticalContentAlignment = VerticalAlignment.Top;
            btn.Height = 130;
            btn.Tag = label;
            btn.Click += async (_, __) => await PlaceAcgDecal(id, label, null);
            MakeDraggable(btn, label, async (x, y) =>
            {
                var at = await AskViewPoint(x, y);
                if (at != null) await PlaceAcgDecal(id, label, at);
            }, null, () => _acgThumbs.TryGetValue(id, out var th) ? th : null);
            _ = LoadAcgThumb(id, img, (bool?)a["hasThumb"] ?? false);
            return Fav(btn, "acgdecal", id, label, a);
        }

        async Task LoadAcgThumb(string id, Border target, bool ready)
        {
            if (!_acgThumbs.TryGetValue(id, out var bmp))
            {
                for (int i = 0; i < (ready ? 1 : 20) && bmp == null; i++)
                {
                    try
                    {
                        var bytes = await TexHttp.GetByteArrayAsync($"http://127.0.0.1:{_host.Port}/api/library/decals/thumb?id={Uri.EscapeDataString(id)}");
                        var b = new BitmapImage();
                        b.BeginInit(); b.CacheOption = BitmapCacheOption.OnLoad; b.DecodePixelWidth = 128;
                        b.StreamSource = new MemoryStream(bytes); b.EndInit(); b.Freeze();
                        bmp = b;
                        _acgThumbs[id] = b;
                    }
                    catch { await Task.Delay(2500); }
                }
                if (bmp == null) return;
            }
            target.Child = new Image { Source = bmp, Stretch = Stretch.Uniform, Margin = new Thickness(3) };
        }

        /// <summary>An ambientCG decal: downloaded the first time (progress in the status bar), then placed like yours,
        /// at its real size when ambientCG gives it.</summary>
        async Task PlaceAcgDecal(string id, string label, JsonObject? at)
        {
            if (_api == null) return;
            var vp = at ?? await AskViewPoint();
            if (vp == null) return;
            if (!((bool?)vp["hit"] ?? false)) { Status(L.T("Metti la decal su un modello: trascinala sulla superficie dove la vuoi"), true); return; }
            JsonObject? st = null;
            await Run(async api => { st = await api.Post("library/decals/download", new { id }); });
            var clock = System.Diagnostics.Stopwatch.StartNew();
            while (st != null && (string?)st["state"] == "running" && clock.Elapsed.TotalMinutes < 5)
            {
                var f = (double?)st["fraction"];
                Status(f is double ff ? L.F("Scarico la decal {0}… {1}%", label, (int)(ff * 100)) : L.F("Scarico la decal {0}…", label));
                await Task.Delay(400);
                try { st = await _api.Get("library/decals/status?id=" + Uri.EscapeDataString(id)); } catch { }
            }
            if ((string?)st?["state"] != "done")
            {
                Msg.Show(this, L.F("La decal {0} non si è scaricata: {1}", label, (string?)st?["error"] ?? ""), "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }
            foreach (var a in _acgDecals.OfType<JsonObject>()) if ((string?)a["id"] == id) a["downloaded"] = true;
            var dist = Math.Max(1, (double?)vp["distance"] ?? 300);
            string newId = "", target = "";
            using (BeginBusy())
            {
                await Run(async api =>
                {
                    var r = await api.Post("decal/add", new JsonObject
                    {
                        ["acg"] = id, ["location"] = vp["point"]?.DeepClone(), ["normal"] = vp["normal"]?.DeepClone(),
                        ["camera"] = vp["camera"]?.DeepClone(), ["width"] = Math.Clamp(Math.Round(dist * 0.25), 10, 400),
                        ["hitObject"] = $"{(string?)vp["objectId"]}/{(string?)vp["meshId"]}/{(string?)vp["material"]}",
                    });
                    newId = (string?)r["id"] ?? "";
                    target = (string?)r["target"] ?? "";
                });
            }
            if (newId == "") return;
            Status(target == "" ? L.T("Decal messa, ma sotto quel punto non c'è un pezzo su cui proiettarla: spostala su un modello") : L.F("Decal {0} messa", label), target == "");
            SetSelectionRaw(newId);
            await RefreshScene();
            if (_libraryTab == "acgdecals") RenderLibrary();
        }
    }
}
