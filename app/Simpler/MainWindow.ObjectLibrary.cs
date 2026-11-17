using System;
using System.Collections.Generic;
using System.IO;
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
    /// <summary>
    /// "Oggetti" tab of the bottom library: folders like the materials. "Primitive" holds the basic shapes; the other
    /// folders hold the models the user saved from a scene (right click on a piece in the view > Salva nella libreria):
    /// a path-traced thumbnail, click = in the middle of the view, drag = where it is dropped (onto a folder: moved).
    /// </summary>
    public sealed partial class MainWindow
    {
        const string PrimitiveFolder = "::primitive";
        JsonArray _models = new JsonArray();
        List<string> _modelFolders = new();
        string _objFolder = "";

        void SetModels(JsonObject? r)
        {
            _models = r?["models"] as JsonArray ?? new JsonArray();
            _modelFolders = (r?["folders"] as JsonArray)?.Select(x => (string?)x ?? "").Where(x => x != "").ToList() ?? new List<string>();
            _vegRoot = (string?)r?["vegRoot"] ?? _vegRoot;
            MergeCloudModels();          // (cloud) what is in the cloud and not here yet
        }

        async Task ReloadModels()
        {
            await Run(async api => { SetModels(await api.Get("models")); });
            if (_libraryTab is "objects" or "myplants" or "simplerplants" or "primitives" or "packplants" or "packmodels" or "search") RenderLibrary();      // (1.78.4: a rename in Vegetazione ▸ Simpler did not show)
        }

        void RenderObjectBrowser()
        {
            _modelTiles.Clear();
            // another folder or a search: the Ctrl selection was of the tiles seen before
            var place = _objFolder + "|" + LibraryQuery;
            if (place != _modelSelPlace) { _modelSel.Clear(); _modelSelPlace = place; }
            // (1.78.0) the plants are in Vegetazione ▾, not here
            var models = _models.OfType<JsonObject>().Where(m => !IsVegModel(m) && !IsVegFolder((string?)m["folder"] ?? "") && !IsSimplerFolder((string?)m["folder"] ?? "") && !IsPackFolder((string?)m["folder"] ?? "")).ToList();
            var q = LibraryQuery;
            var root = L.T("Modelli 3D");
            if (q != "")
            {
                RenderCrumbs(root, "", f => { _objFolder = f; _librarySearch.Text = ""; }, L.F("risultati per \"{0}\"", _librarySearch.Text.Trim()));
                int n = 0;
                foreach (var m in models.Where(m => ((string?)m["name"] + " " + (string?)m["folder"]).ToLowerInvariant().Contains(q)))
                {
                    _libraryTiles.Children.Add(ModelTile(m));
                    n++;
                }
                if (n == 0) _libraryTiles.Children.Add(EmptyNote(L.T("Nessun oggetto trovato")));
                return;
            }
            if (_objFolder == PrimitiveFolder)
            {
                RenderCrumbs(root, "", f => _objFolder = f, null);
                AddPrimitiveCrumb();
                _libraryTiles.Children.Add(UpTile("", f => _objFolder = f, false));
                foreach (var (kind, label) in InsertObjects) AddPrimitiveTile(kind, label);
                return;
            }
            if (_objFolder != "" && (!_modelFolders.Contains(_objFolder) || IsVegFolder(_objFolder) || IsSimplerFolder(_objFolder) || IsPackFolder(_objFolder))) _objFolder = "";
            RenderCrumbs(root, _objFolder, f => _objFolder = f, null);
            if (_objFolder != "") _libraryTiles.Children.Add(UpTile(ParentFolder(_objFolder), f => _objFolder = f, true));
            // (1.79, Luca: «perché new folder è in fondo a destra?») «Nuova cartella» first, with the tiles that add
            _libraryTiles.Children.Add(NewFolderTile("model", _objFolder));
            // (the primitives of Simpler: Modelli 3D ▸ Primitive since 1.68.3, no more a folder here)
            foreach (var f in _modelFolders.Where(f => ParentFolder(f) == _objFolder && !IsVegFolder(f) && !IsSimplerFolder(f) && !IsPackFolder(f)).OrderBy(f => f, StringComparer.CurrentCultureIgnoreCase))
            {
                var count = models.Count(m => InFolder((string?)m["folder"] ?? "", f));
                _libraryTiles.Children.Add(FolderTile(f, count, () => { _objFolder = f; RenderLibrary(); }, "model"));
            }
            foreach (var m in models.Where(m => ((string?)m["folder"] ?? "") == _objFolder))
                _libraryTiles.Children.Add(ModelTile(m));
        }

        void AddPrimitiveCrumb()
        {
            // the path bar shows "Oggetti > Primitive" (Primitive is not a real folder)
            if (_libraryCrumbs.Children.Count > 0 && _libraryCrumbs.Children[0] is Button first) Theme.Style(first, Theme.Kind.Ghost);
            var sep = Theme.Icon(Icons.Chevron, Theme.TextFaint, 12, 1.6);
            sep.VerticalAlignment = VerticalAlignment.Center;
            sep.Margin = new Thickness(1, 0, 1, 0);
            _libraryCrumbs.Children.Add(sep);
            var b = Theme.Button(L.T("Primitive"), Theme.Kind.Segment);
            b.MinHeight = 26; b.Height = 26; b.FontSize = 12; b.Padding = new Thickness(8, 0, 8, 0);
            _libraryCrumbs.Children.Add(b);
        }

        /// <summary>A primitive: its rendered picture (primitives/&lt;kind&gt;.png next to Simpler.exe), or an icon.</summary>
        void AddPrimitiveTile(string kind, string label)
        {
            var file = Path.Combine(AppContext.BaseDirectory, "primitives", kind + ".png");
            ImageSource? picture = File.Exists(file) ? LoadBitmapFresh(file) : null;
            if (picture == null)
            {
                AddTile(Icons.Mesh, L.T(label), L.T("Clic: al centro della vista · trascina: dove lo lasci"), async at => await AddObject(kind, "", at), "#9DB4D8");
                return;
            }
            var visual = new Grid { Width = 80, Height = 80, Margin = new Thickness(0, 0, 0, 4), HorizontalAlignment = HorizontalAlignment.Center };
            visual.Children.Add(new Image { Source = picture, Stretch = Stretch.UniformToFill, Clip = new RectangleGeometry(new Rect(0, 0, 80, 80), 10, 10) });
            var tile = new StackPanel { Width = 92, Margin = new Thickness(4, 0, 4, 0) };   // (no top/bottom margin: two-line names fit the 130 px tile)
            tile.Children.Add(visual);
            tile.Children.Add(Theme.TileText(new TextBlock { Text = L.T(label), FontSize = 11.5, TextAlignment = TextAlignment.Center, TextWrapping = TextWrapping.Wrap, Foreground = Theme.B(Theme.TextSoft) }));
            var btn = Theme.Button(tile, Theme.Kind.Normal, L.T(label) + "\n" + L.T("Clic: al centro della vista · trascina nella vista: dove lo lasci"));
            btn.Padding = new Thickness(2, 4, 2, 6); btn.Margin = new Thickness(4);
            btn.VerticalContentAlignment = VerticalAlignment.Top; btn.Height = 130; btn.Tag = L.T(label);
            btn.Click += async (_, __) => await AddObject(kind, "", null);
            MakeDraggable(btn, L.T(label), async (x, y) => { var at = await AskViewPoint(x, y); if (at != null) await AddObject(kind, "", at); }, null, () => picture);
            _libraryTiles.Children.Add(btn);
        }

        static string MegaBytes(double bytes)
        {
            var mb = bytes / (1024.0 * 1024.0);
            return (mb >= 100 ? Num.F(mb, 0) : mb >= 10 ? Num.F(mb, 1) : mb >= 0.1 ? Num.F(mb, 2) : "< " + Num.F(0.1, 1)) + " MB";
        }

        Button ModelTile(JsonObject m)
        {
            var id = (string?)m["id"] ?? "";
            var ro = ReadOnlyFolder((string?)m["folder"]);          // (a model of Simpler, locked: no change)
            var name = (string?)m["name"] ?? id;
            var thumb = (string?)m["thumb"] ?? "";
            var ready = (bool?)m["ready"] ?? false;
            var cloud = (bool?)m["cloud"] ?? false;             // (cloud) in the cloud, not here yet
            var inCat = (bool?)m["inCatalog"] ?? false;         // here, and in the cloud too
            var upd = !cloud && ((bool?)m["update"] ?? false);   // here, with a newer version in the cloud
            var visual = new Grid { Width = 80, Height = 80, Margin = new Thickness(0, 0, 0, 4), HorizontalAlignment = HorizontalAlignment.Center };
            ImageSource? picture = thumb != "" && File.Exists(thumb) ? LoadBitmapFresh(thumb) : null;
            if (picture != null)
                visual.Children.Add(new Image { Source = picture, Stretch = Stretch.UniformToFill,
                                                Clip = new RectangleGeometry(new Rect(0, 0, 80, 80), 10, 10) });
            else
            {
                var ic = Theme.Icon(Icons.Mesh, Theme.C("#9DB4D8"), 34, 1.6);
                ic.HorizontalAlignment = HorizontalAlignment.Center;
                ic.VerticalAlignment = VerticalAlignment.Center;
                visual.Children.Add(ic);
            }
            if (cloud && picture == null && _content?.Find(id) is ContentAsset ca)
            {
                var im = new Image { Stretch = Stretch.UniformToFill, Clip = new RectangleGeometry(new Rect(0, 0, 80, 80), 10, 10) };
                visual.Children.Add(im);
                CloudThumb(ca, im);
            }
            var tile = new StackPanel { Width = 92, Margin = new Thickness(4, 0, 4, 0) };   // (no top/bottom margin: two-line names fit the 130 px tile)
            tile.Children.Add(visual);
            tile.Children.Add(Theme.TileText(new TextBlock { Text = name, FontSize = 11.5, TextAlignment = TextAlignment.Center, TextWrapping = TextWrapping.Wrap,
                                              Foreground = Theme.B(cloud ? Theme.TextMuted : Theme.TextSoft), MaxHeight = 32, TextTrimming = TextTrimming.CharacterEllipsis }));
            // how much it weighs on disk (model and its textures): a small label on the corner of the thumbnail (under
            // the name it was cut off by the row height when the name took two lines)
            var bytes = (double?)m["bytes"] ?? 0;
            if (bytes > 0)
                visual.Children.Add(new Border
                {
                    Background = new SolidColorBrush(Color.FromArgb(200, 0x10, 0x18, 0x2A)), CornerRadius = new CornerRadius(4),
                    Padding = new Thickness(4, 0, 4, 1), Margin = new Thickness(0, 0, 3, 3),
                    HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Bottom, IsHitTestVisible = false,
                    Child = new TextBlock { Text = MegaBytes(bytes), FontSize = 10, Foreground = Theme.B("#E6EDF7") },
                });
            var size = m["sizeCm"] as JsonArray;
            var dims = size != null && size.Count == 3
                ? L.F("{0} × {1} × {2} cm", Num.F((double?)size[0] ?? 0, 1), Num.F((double?)size[1] ?? 0, 1), Num.F((double?)size[2] ?? 0, 1)) : "";
            AddCloudBadge(visual, 80, id, cloud, inCat, upd);
            var btn = Theme.Button(tile, Theme.Kind.Normal,
                                   name + (dims != "" ? " · " + dims : "") + "\n" +
                                   (upd ? L.T("Aggiornamento disponibile (la freccia arancione): il clic lo inserisce con la versione che hai") + "\n" : "") +
                                   (cloud ? L.T("Nel cloud, non ancora sul computer: un clic lo scarica (poi si usa come gli altri)")
                                    : !ready ? L.T("In preparazione (copia delle texture e miniatura)…")
                                    : ro ? L.T("Clic: al centro della vista · trascina nella vista: dove lo lasci · modello di Simpler: si può copiare nelle tue cartelle")
                                    : L.T("Clic: al centro della vista · trascina nella vista: dove lo lasci · su una cartella: lo sposta")));
            btn.Padding = new Thickness(2, 4, 2, 6);
            btn.Margin = new Thickness(4);
            btn.VerticalContentAlignment = VerticalAlignment.Top;
            btn.Height = 130;
            _modelTiles[id] = btn;
            ShowModelSelected(btn, _modelSel.Contains(id));
            btn.Click += async (_, __) =>
            {
                if (cloud) { await DownloadCloud(id); return; }          // (cloud) a click on a cloud: it is downloaded
                // Ctrl+clic: selects several models (to move, copy or delete them together); with models selected a
                // plain click only clears the selection - nothing goes into the view
                if ((Keyboard.Modifiers & ModifierKeys.Control) != 0) { ToggleModelSelection(id); return; }
                if (_modelSel.Count > 0) { ClearModelSelection(); return; }
                if (_screePicking) { AddScreeModel(id, name); return; }      // (1.76.22) «Scegli le pietre dalla libreria»
                if (_ecoAddLayer >= 0 && _ecoAddModel != null && _rightPanel == "ecosystem") { await _ecoAddModel(id, name); return; }   // (1.79.0) a layer of this project
                if (Painting) AddToPalette(id, name); else await InsertModel(id, name, null);
            };
            MakeDraggable(btn, name, async (x, y) =>
            {
                if (_modelSel.Count > 0) { Status(L.T("Ci sono modelli selezionati con Ctrl: un clic su un modello toglie la selezione, poi puoi inserirlo"), true); return; }
                var at = await AskViewPoint(x, y);
                if (at != null) await InsertModel(id, name, at);
            }, ro ? null : async folder =>
            {
                if (_modelSel.Contains(id) && _modelSel.Count > 1) await MoveModels(_modelSel.ToList(), folder);
                else await MoveModel(id, folder);
            }, () => picture);
            var menu = new ContextMenu();
            void Item(string text, Func<Task> act) { var i = new MenuItem { Header = text }; i.Click += async (_, __) => await act(); menu.Items.Add(i); }
            Item(L.T("Inserisci al centro della vista"), async () => await InsertModel(id, name, null));
            Item(L.T("Aggiungi al pennello Distribuisci"), async () => { await Task.Yield(); if (!Painting) SetTool("paint"); AddToPalette(id, name); });
            Item(L.T("Aggiungi a Pietre e detriti"), async () => { await Task.Yield(); AddScreeModel(id, name); });
            if (ro)
            {
                // a model of Simpler: it can be used and copied, nothing else
                var cp = new MenuItem { Header = L.T("Copia") };
                cp.Click += (_, __) => CopyModels(new[] { id });
                menu.Items.Insert(0, cp);
                menu.Items.Insert(1, new Separator());
                if (cloud)
                {
                    var dl = new MenuItem { Header = L.T("Scarica sul computer") };
                    dl.Click += async (_, __) => await DownloadCloud(id);
                    menu.Items.Insert(0, dl);
                }
                else if (inCat)
                {
                    if (upd)
                    {
                        var up = new MenuItem { Header = L.T("Aggiorna (versione più nuova nel cloud)") };
                        up.Click += async (_, __) => await UpdateContent(new[] { id });
                        menu.Items.Insert(0, up);
                    }
                    var rm = new MenuItem { Header = L.T("Rimuovi dal computer (si può riscaricare)") };
                    rm.Click += async (_, __) => await RemoveCloud(id);
                    menu.Items.Add(new Separator());
                    menu.Items.Add(rm);
                }
                btn.ContextMenu = menu;
                btn.ContextMenuOpening += (_, e) => { btn.ContextMenu = _modelSel.Count > 1 && _modelSel.Contains(id) ? SelectionMenu() : menu; };
                return Fav(btn, "model", id, name, m);
            }
            Item(L.T("Rinomina…"), async () =>
            {
                var n = InputDialog.Ask(this, L.T("Rinomina oggetto della libreria"), L.T("Nome"), name);
                if (n == null || n == name) return;
                await Run(async api => { await api.Post("models/rename", new { id, name = n }); });
                await ReloadModels();
            });
            Item(L.T("Rigenera miniatura"), async () =>
            {
                JsonObject? r = null;
                await Run(async api => { r = await api.Post("models/thumb", new { id }); });
                if ((int?)r?["pending"] is int rid) await WaitModelJob(rid, name, "");
            });
            Item(L.T("Correggi materiali…"), async () => { ShowMaterialFixWizard(new[] { id }); await Task.CompletedTask; });
            // (1.78.0) a plant: Fogliame on its leaves and wood, into Vegetazione; a plant already: what is leaf and what wood
            if (IsVegModel(m)) Item(L.T("Foglie e legno…"), async () => await ShowVegParts(id, name));
            else Item(L.T("Converti in vegetazione…"), async () => await ConvertToVegetation(new List<string> { id }));
            // orientation: the front of the model along the red X axis (the direction of a Spacing line)
            var orient = new MenuItem { Header = L.T("Orientamento"), ToolTip = L.T("Il davanti del modello lungo l'asse rosso X (la direzione della linea dello spacing). Vale per i nuovi inserimenti e per gli scatter; le copie già nelle scene non cambiano") };
            void OItem(string text, string tip, string mode)
            {
                var i = new MenuItem { Header = text, ToolTip = tip };
                i.Click += async (_, __) => await OrientModel(id, name, mode, "");
                orient.Items.Add(i);
            }
            OItem(L.T("Raddrizza"), L.T("Simpler gira il modello visto dall'alto in modo che il suo lato lungo stia sull'asse rosso X"), "auto");
            OItem(L.T("Gira di 90°"), L.T("Un quarto di giro attorno all'asse verticale"), "rot90");
            OItem(L.T("Gira di 180°"), L.T("Mezzo giro: il davanti dall'altra parte"), "rot180");
            // (Luca: «se prendo il gizmo per appoggiare la pianta al pavimento ruota di 90 gradi … un comando che possa
            // risolvere») the turn the file gave the model goes into its shape: its up is the vertical again
            OItem(L.T("Correggi gli assi"), L.T("Se il modello, spostato con il quadratino giallo del gizmo per appoggiarlo, si gira di 90° o si sdraia: Simpler porta la sua verticale sull'asse Z senza spostarlo né girarlo. Vale per i nuovi inserimenti; le copie già nella scena vanno inserite di nuovo"), "bake");
            menu.Items.Add(orient);
            menu.Items.Add(new Separator());
            Item(L.T("Elimina dalla libreria"), async () =>
            {
                if (Msg.Show(this, L.F("Eliminare \"{0}\" dalla libreria?\nGli oggetti già inseriti nelle scene restano.", name),
                             "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
                await Run(async api => { await api.Post("models/delete", new { id }); });
                await ReloadModels();
            });
            AddMoveMenu(menu, id, (string?)m["folder"] ?? "", "model");
            var cut = new MenuItem { Header = L.T("Taglia") };
            cut.Click += (_, __) => CutLibrary("model", false, id, name);
            menu.Items.Insert(0, cut);
            var copy = new MenuItem { Header = L.T("Copia") };
            copy.Click += (_, __) => CopyModels(new[] { id });
            menu.Items.Insert(1, copy);
            if (IsCut("model", false, id)) btn.Opacity = 0.45;
            btn.ContextMenu = menu;
            // several models selected with Ctrl and the right click on one of them: the menu acts on all of them
            btn.ContextMenuOpening += (_, e) =>
            {
                if (_modelSel.Count > 1 && _modelSel.Contains(id)) btn.ContextMenu = SelectionMenu();
                else btn.ContextMenu = menu;
            };
            return Fav(btn, "model", id, name, m);
        }

        async Task MoveModel(string id, string folder)
        {
            if (ReadOnlyFolder(folder) || ReadOnlyModel(id)) { Status(L.T("Le cartelle Simpler sono di sola lettura"), true); return; }
            var m = _models.OfType<JsonObject>().FirstOrDefault(x => (string?)x["id"] == id);
            if (m != null && ((string?)m["folder"] ?? "") == folder) return;
            await Run(async api => { await api.Post("models/move", new { id, folder }); });
            Status(L.F("{0} spostato in {1}", (string?)m?["name"] ?? id, folder == "" ? L.T("Modelli 3D") : folder));
            await ReloadModels();
        }

        /// <summary>A model of the library into the scene: its base on the surface under the drop (or in the middle of the view).</summary>
        async Task InsertModel(string id, string name, JsonObject? at)
        {
            Func<Task>? before = null;
            StudioBeforeInsert(ref before);
            if (before != null) await before();
            StudioInsertAt(ref at);
            at ??= await AskViewPoint();
            var body = new JsonObject { ["id"] = id };
            if (at?["point"] is JsonArray p) body["location"] = p.DeepClone();
            string newId = "";
            using (BeginBusy())
            {
                _reloadOrigin = "action";
                ShowTask(L.F("Inserimento di {0}…", name));
                await Run(async api => { newId = (string?)(await api.Post("models/insert", body))["id"] ?? ""; });
                HideTask();
            }
            if (newId == "") return;
            _expanded.Add(newId);
            SetSelectionRaw(newId);
            await RefreshScene();      // (drawn by the view from its prototype: no new preparation of the view)
            Status(L.F("{0} inserito", name));
            StudioAfterInsert(newId);
        }

        /// <summary>The selected pieces into the model library: name and folder, then the engine saves them and the
        /// preview process copies the textures and renders the thumbnail (the app keeps working meanwhile).</summary>
        async Task SaveSelectionToLibrary()
        {
            var ids = _selection.Where(i => _scene.ById.ContainsKey(i)).ToList();
            if (ids.Count == 0) { Status(L.T("Seleziona prima un oggetto"), true); return; }
            // a piece and its group both selected: the group is enough
            ids = ids.Where(i => !_scene.Ancestors(_scene.ById[i]).Any(a => ids.Contains(a.Id))).ToList();
            var first = _scene.ById[ids[0]];
            var folder = ModelFolderShown();
            if (ReadOnlyFolder(folder)) folder = "";        // (the library shows a red folder: the dialog starts from the main one, never there)
            // (Luca: «c'è tutta la libreria ma non "I miei"») only the folders of the part you are saving into: Modelli 3D ▸ I miei
            // (without Vegetazione, Simpler and the packs) or, from Vegetazione ▸ Le mie piante, the plants' own folders
            // a model that came from the library: its own folder first (if it still exists and is not a read-only one)
            if (ids.Count == 1)
            {
                var src = new[] { first }.Concat(_scene.Ancestors(first)).Select(x => x.PaintModel).FirstOrDefault(m => m != "") ?? "";
                var from = src == "" ? null : _models.OfType<JsonObject>().FirstOrDefault(m => (string?)m["id"] == src);
                var ff = (string?)from?["folder"];
                if (ff != null && !ReadOnlyFolder(ff) && (ff == "" || _modelFolders.Contains(ff))) folder = ff;
            }
            bool inVeg = IsVegFolder(folder);
            var ans = SaveToLibraryDialog.Ask(this, L.T("Salva nella libreria dei modelli 3D"), L.T("Nome dell'oggetto"),
                                              ids.Count == 1 ? first.Name : L.F("{0} e altri {1}", first.Name, ids.Count - 1),
                                              folder, _modelFolders.Where(f => !ReadOnlyFolder(f) && IsVegFolder(f) == inVeg), inVeg ? L.T("Le mie piante") : L.T("I miei modelli"));
            if (ans == null) return;
            if (ReadOnlyFolder(ans.Value.folder)) { Status(L.T("Le cartelle Simpler sono di sola lettura"), true); return; }
            var saveName = ans.Value.name.Trim();
            // a model with the same name in the same folder: overwrite it, save a new one beside it, or stop
            var replace = "";
            static string Key(string f, string n) => (f.Trim('/') + "|" + n.Trim()).ToLowerInvariant();
            var models = _models.OfType<JsonObject>().ToList();
            var same = models.FirstOrDefault(m => Key((string?)m["folder"] ?? "", (string?)m["name"] ?? "") == Key(ans.Value.folder, saveName));
            if (same != null)
            {
                var (choice, _) = ConflictDialog.Ask(this, saveName, ans.Value.folder, saving: true);
                if (choice == "skip") return;
                if (choice == "overwrite") replace = (string?)same["id"] ?? "";
                else
                {
                    int n = 2;
                    while (models.Any(m => Key((string?)m["folder"] ?? "", (string?)m["name"] ?? "") == Key(ans.Value.folder, $"{saveName} ({n})"))) n++;
                    saveName = $"{saveName} ({n})";
                }
            }
            JsonObject? r = null;
            await Run(async api =>
            {
                r = await api.Post("models/save", new JsonObject
                {
                    ["ids"] = new JsonArray(ids.Select(x => (JsonNode)x!).ToArray()), ["name"] = saveName, ["folder"] = ans.Value.folder,
                    ["replace"] = replace,
                });
            });
            if (r == null) return;
            var name = (string?)r["name"] ?? ans.Value.name;
            _libraryTab = ModelTabFor(ans.Value.folder, true);
            await ReloadModels();
            RenderLibrary();
            Status(L.F("{0}: salvataggio nella libreria (texture e miniatura)…", name));
            if (r["missing"] is JsonArray miss && miss.Count > 0)
            {
                // textures whose file no longer exists: the model is saved without them - say it, and how to fix it
                var list = string.Join("\n", miss.Take(8).Select(m => "• " + (string?)m)) + (miss.Count > 8 ? "\n…" : "");
                Msg.Show(this, L.F("{0} texture di questo modello non si trovano sul disco, quindi il modello è stato salvato senza:", miss.Count) + "\n\n" + list + "\n\n" +
                         L.T("Il file è stato spostato o cancellato, oppure è su un disco non collegato. Se lo ritrovi, ricollegalo (tasto destro sul modello nell'albero ▸ Cerca texture mancanti…) e salva di nuovo il modello; altrimenti reimporta il modello dal suo file originale (FBX, OBJ…)."),
                         L.T("Texture mancanti"), MessageBoxButton.OK, MessageBoxImage.Warning);
            }
            if ((int?)r["pending"] is int rid)
                await WaitModelJob(rid, name, L.F("{0} salvato nella libreria dei modelli 3D ({1})", name, ans.Value.folder == "" ? L.T("Modelli 3D") : ans.Value.folder));
        }

        /// <summary>A library model turned (Raddrizza / 90° / 180°, or as its copy in the scene: objectId): the model file
        /// is written again with its new orientation, then the models of the distributions of this project follow.</summary>
        async Task OrientModel(string id, string name, string mode, string objectId)
        {
            JsonObject? r = null;
            await Run(async api =>
            {
                r = objectId != "" ? await api.Post("models/orientfromscene", new JsonObject { ["object"] = objectId })
                                   : await api.Post("models/orient", new JsonObject { ["id"] = id, ["mode"] = mode });
            });
            if ((int?)r?["pending"] is not int rid) return;
            id = (string?)r?["id"] ?? id;
            if (name == "") name = (string?)_models.OfType<JsonObject>().FirstOrDefault(m => (string?)m["id"] == id)?["name"] ?? id;
            Status(L.F("{0}: orientamento in corso…", name));
            using (BeginBusy()) await WaitModelJob(rid, name, L.F("{0}: nuovo orientamento salvato nella libreria", name));
            JsonObject? t = null;
            await Run(async api => { t = await api.Post("models/orient/apply", new JsonObject { ["id"] = id }); });
            if ((int?)t?["turned"] is int n && n > 0)
            {
                await RefreshScene();
                Status(L.F("{0}: nuovo orientamento salvato nella libreria, anche negli scatter di questo progetto", name));
            }
        }

        /// <summary>Waits for the preview process (texture copy + thumbnail), then shows the library again.</summary>
        async Task WaitModelJob(int rid, string name, string doneText)
        {
            if (_api == null) return;
            for (int i = 0; i < 1200; i++)
            {
                await Task.Delay(500);
                JsonObject? st = null;
                try { st = await _api.Get($"material/preview/status?id={rid}"); } catch { }
                var state = (string?)st?["state"] ?? "";
                if (state == "running") continue;
                if (state == "done") Status(doneText != "" ? doneText : L.F("Miniatura di {0} aggiornata", name));
                else Status(L.F("{0}: miniatura non riuscita ({1})", name, (string?)st?["error"] ?? ""), true);
                break;
            }
            await ReloadModels();
        }

        /// <summary>A picture read now from disk (the same file may have been rendered again: no image cache).</summary>
        static ImageSource? LoadBitmapFresh(string path)
        {
            try
            {
                var bmp = new System.Windows.Media.Imaging.BitmapImage();
                bmp.BeginInit();
                bmp.CacheOption = System.Windows.Media.Imaging.BitmapCacheOption.OnLoad;
                bmp.StreamSource = new MemoryStream(File.ReadAllBytes(path));
                bmp.DecodePixelWidth = 160;
                bmp.EndInit();
                bmp.Freeze();
                return bmp;
            }
            catch { return null; }
        }

        // ---------------------------------------------------------------- right click on a piece in the view

        void ShowViewportMenu(string id, string material)
        {
            // (15/11) the same menu as the tree (MainWindow.Tree.cs, ObjectMenu): one list of commands, one set of rules
            if (!_scene.ById.TryGetValue(id, out var o)) return;
            ObjectMenu(o, material, true).IsOpen = true;
        }
    }
}
