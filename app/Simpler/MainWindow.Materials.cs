using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace Simpler
{
    /// <summary>
    /// Material editor (right sidebar): every channel of a material like in Twinmotion - colour, roughness, metallic,
    /// relief, reflections, glass (with dispersion), velvet, subsurface, emission, opacity, true displacement and
    /// texture mapping. The engine builds the Cycles nodes (engine/simpler/matedit.py); the real-time view rebuilds the
    /// material in place, maps included, so no edit prepares the 3D view again.
    /// </summary>
    public sealed partial class MainWindow
    {
        string _matName = "", _matObject = "";
        int _matSlot = -1;
        JsonObject _matInfo = new JsonObject();
        static readonly HttpClient TexHttp = new HttpClient { Timeout = TimeSpan.FromSeconds(60) };
        readonly Dictionary<string, BitmapImage> _thumbs = new();

        // ---------------------------------------------------------------- entry points

        async Task OpenMaterialEditor(string name, string objectId = "", int slot = -1)
        {
            if (string.IsNullOrEmpty(name)) return;
            _matName = name; _matObject = objectId; _matSlot = slot;
            _editAll = false;       // every material opened from an object starts on «Solo questo modello»
            if (!await LoadMaterial()) return;
            await ShowRightPanel("material");
            if (_lastPreview.name != _matName) _ = RequestLivePreview();
        }

        async Task<bool> LoadMaterial()
        {
            JsonObject? info = null;
            var q = "material/edit?name=" + Uri.EscapeDataString(_matName) + (_matObject != "" ? "&id=" + Uri.EscapeDataString(_matObject) : "");
            await Run(async api => { info = await api.Get(q); });
            if (info == null) return false;
            _matInfo = info;
            return true;
        }

        async Task ShowSceneMaterials() => await ShowRightPanel("materials");

        /// <summary>The "Materiali" button of the header: the material of the selected object (its first one), or with
        /// nothing selected the white Standard material of the library («Bianco»), to adjust and then drag onto objects.
        /// A second click closes the panel.</summary>
        async Task ToggleMaterialPanel()
        {
            if (_rightPanel is "material" or "materials") { await ShowRightPanel(""); return; }
            if (_selected != "" && _scene.ById.TryGetValue(_selected, out var sel))
            {
                // the object itself, or (a group, a model of the library) its first piece with a material
                SceneObject? First(SceneObject x)
                {
                    if (x.Materials.Any(m => m != "")) return x;
                    foreach (var c in x.Children) if (First(c) is SceneObject f) return f;
                    return null;
                }
                if (First(sel) is SceneObject o)
                {
                    var slot = o.Materials.FindIndex(m => m != "");
                    await OpenMaterialEditor(o.Materials[slot], o.Id, slot);
                    return;
                }
            }
            await OpenLibraryMaterial("bianco");
            if (_rightPanel == "material")
                Status(_selected == "" ? L.T("Nessun oggetto selezionato: ecco il materiale bianco standard. Trascina la sfera di anteprima su un oggetto per applicarlo")
                                       : L.T("L'oggetto selezionato non ha un materiale: ecco il bianco standard. Trascina la sfera di anteprima sull'oggetto per applicarlo"));
        }

        /// <summary>Click on a library material: it opens in the editor (made in the project if needed, not applied).</summary>
        async Task OpenLibraryMaterial(string id)
        {
            JsonObject? r = null;
            await Run(async api => { r = await api.Post("material/open", new { id }); });
            var name = (string?)r?["name"];
            if (string.IsNullOrEmpty(name)) return;
            var obj = _selected != "" && _scene.ById.TryGetValue(_selected, out var o) && o.Materials.Contains(name) ? o.Id : "";
            await OpenMaterialEditor(name, obj, obj != "" ? _scene.ById[obj].Materials.IndexOf(name) : -1);
        }

        ContextMenu LibraryMaterialMenu(JsonObject node)
        {
            var m = new ContextMenu();
            var id = (string?)node["id"] ?? "";
            void Item(string text, Func<Task> act) { var i = new MenuItem { Header = text }; i.Click += async (_, __) => await act(); m.Items.Add(i); }
            Item(L.T("Modifica"), async () => await OpenLibraryMaterial(id));
            // (Luca: «le cartelle rosse non consentono modifiche»: the materials of Simpler cannot be restored, removed or
            // moved while they are locked; «Modifica» opens a copy in the project)
            if (SimplerLocked && InSimplerMats(node)) return m;
            if (((bool?)node["overrides"] ?? false) || ((bool?)node["simpler"] ?? false))
                Item(L.T("Ripristina il materiale di Simpler"), async () =>
                {
                    // (1.68.1: only the library; the changed version stays as «(modificato)», the projects do not change)
                    await Run(async api => { await api.Post("material/library/reset", new { id }); });
                    await ReloadLibraryMaterials();
                });
            if (((bool?)node["user"] ?? false) && !((bool?)node["overrides"] ?? false))
                Item(L.T("Elimina dalla libreria"), async () =>
                {
                    if (Msg.Show(this, L.F("Eliminare {0} dalla libreria? Gli oggetti che lo usano nella scena non cambiano.", (string?)node["name"] ?? id), "Simpler",
                                 MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
                    await Run(async api => { await api.Post("material/library/delete", new { id }); });
                    await ReloadLibraryMaterials();
                });
            return m;
        }

        async Task ReloadLibraryMaterials()
        {
            await Run(async api => { SetLibraryMaterials(await api.Get("materials")); });
            RenderLibrary();
        }

        // ---------------------------------------------------------------- live preview (sphere, path traced in a separate process)

        Image? _previewImage;
        TextBlock? _previewState;
        int _previewRequest;

        async Task RequestLivePreview()
        {
            if (_api == null || _matName == "") return;
            var mine = ++_previewRequest;
            await Task.Delay(250);                         // a burst of changes renders once
            if (mine != _previewRequest) return;
            if (_previewState != null) _previewState.Text = L.T("aggiornamento…");
            JsonObject? r = null;
            try { r = await _api.Post("material/livepreview", new { name = _matName }); } catch { return; }
            var rid = (int?)r?["id"] ?? 0;
            for (int i = 0; i < 400 && rid > 0; i++)
            {
                await Task.Delay(200);
                if (mine != _previewRequest) return;       // a newer change: that one will show
                JsonObject st;
                try { st = await _api.Get($"material/preview/status?id={rid}"); } catch { return; }
                var state = (string?)st["state"] ?? "";
                if (state == "running") continue;
                if (state == "done")
                {
                    try
                    {
                        var bytes = await TexHttp.GetByteArrayAsync($"http://127.0.0.1:{_host.Port}/api/material/preview/file?id={rid}");
                        var bmp = new BitmapImage();
                        bmp.BeginInit(); bmp.CacheOption = BitmapCacheOption.OnLoad; bmp.StreamSource = new System.IO.MemoryStream(bytes); bmp.EndInit(); bmp.Freeze();
                        if (_previewImage != null) _previewImage.Source = bmp;
                        _lastPreview = (_matName, bmp);
                        if (_previewState != null) _previewState.Text = "";
                    }
                    catch { }
                }
                else if (_previewState != null) _previewState.Text = L.T("anteprima non riuscita");
                return;
            }
        }
        (string name, BitmapImage? image) _lastPreview;

        UIElement PreviewFrame()
        {
            var g = new Grid { Width = 200, Height = 200, Margin = new Thickness(0, 8, 0, 10), HorizontalAlignment = HorizontalAlignment.Center };
            g.Children.Add(new Border { CornerRadius = new CornerRadius(10), Background = Theme.B(Theme.Inset), BorderBrush = Theme.B(Theme.Line), BorderThickness = new Thickness(1) });
            _previewImage = new Image { Stretch = Stretch.UniformToFill };
            _previewImage.Clip = new RectangleGeometry(new Rect(0, 0, 200, 200), 10, 10);
            if (_lastPreview.name == _matName && _lastPreview.image != null) _previewImage.Source = _lastPreview.image;
            else _ = RequestLivePreview();       // a material the sphere has not shown yet (new copy, renamed...)
            g.Children.Add(_previewImage);
            _previewState = new TextBlock { FontSize = 11, Foreground = Theme.B(Theme.TextSoft), Margin = new Thickness(8), HorizontalAlignment = HorizontalAlignment.Right,
                                            VerticalAlignment = VerticalAlignment.Bottom, Background = Theme.B("#A0081020"), Padding = new Thickness(6, 2, 6, 2) };
            g.Children.Add(_previewState);
            g.ToolTip = L.T("Anteprima in path tracing: si aggiorna a ogni modifica") + "\n" +
                        L.T("Trascina la sfera sopra un oggetto nella vista per applicargli questo materiale (Maiusc: tutto il gruppo)");
            g.Cursor = Cursors.Hand;
            g.Background = Brushes.Transparent;     // the whole square can be grabbed
            var name = _matName;
            var img = _previewImage;
            MakeDraggable(g, name, async (x, y) => await DropMaterial(x, y, async (ids, slot) => await AssignSceneMaterial(name, ids, slot),
                                                                   async under => await ReplaceMaterialEverywhere(under, name, false, name)),
                          icon: () => img.Source);
            return g;
        }

        /// <summary>A piece clicked in the view while the material editor (or the list of the scene's materials) is open:
        /// the editor switches to the material of the clicked surface.</summary>
        async Task FollowPickedMaterial(List<string> ids, string primary, string material)
        {
            if (_rightPanel is not ("material" or "materials") || ids.Count != 1 || material == "") return;
            if (!_scene.ById.TryGetValue(primary, out var o)) return;
            var slot = o.Materials.IndexOf(material);
            if (slot < 0 || (material == _matName && primary == _matObject)) return;
            await OpenMaterialEditor(material, primary, slot);
        }

        /// <summary>A material of the project (the one in the editor) dropped on a piece in the view.</summary>
        async Task AssignSceneMaterial(string name, string[] ids, int? slot)
        {
            JsonObject? r = null;
            await Run(async api =>
            {
                r = await api.Post("material/assign", new JsonObject { ["ids"] = new JsonArray(ids.Select(x => (JsonNode)x!).ToArray()), ["name"] = name, ["slot"] = slot, ["replace"] = _assignReplace });
            });
            if (r == null) return;
            Status(L.F("{0} applicato a {1} superfici", name, (int?)r["assigned"] ?? 0));
            await RefreshScene();
            await PushMaterialToViewer(name);
            if (_rightPanel == "material" && _matName == name)
            {
                await LoadMaterial();          // "used by N objects" changes
                RenderProps();
            }
        }

        // ---------------------------------------------------------------- saving to the library

        async Task SaveMaterial(bool asNew)
        {
            var lib = _matInfo["library"] as JsonObject;
            var body = new JsonObject { ["name"] = _matName, ["asNew"] = asNew };
            if (asNew || lib == null)
            {
                // name and folder of the library material (a new path creates the folder)
                var folder = (string?)lib?["folder"] ?? _matFolder;
                if (SimplerLocked && InSimplerMatPath(folder)) folder = "";      // (not into the red folder)
                var ans = SaveToLibraryDialog.Ask(this, asNew ? L.T("Aggiungi come nuovo alla libreria") : L.T("Aggiungi alla libreria"), L.T("Nome del materiale"),
                                                  asNew ? _matName + " " + L.T("copia") : _matName, folder, _materialFolders.Where(f => !(SimplerLocked && InSimplerMatPath(f))),
                                                  L.T("Materiali (cartella principale)"), _previewImage?.Source);
                if (ans == null) return;
                body["newName"] = ans.Value.name;
                body["folder"] = ans.Value.folder;
            }
            else if (Msg.Show(this, L.F("Sostituisce «{0}» nella libreria.", (string?)lib["name"] ?? _matName) + "\n\n"
                              + L.T("Vale per i nuovi usi: i progetti e i modelli già fatti non cambiano. Per tenere anche quello di prima usa «Aggiungi come nuovo…»."),
                              "Simpler", MessageBoxButton.OKCancel, MessageBoxImage.Question) != MessageBoxResult.OK) return;
            JsonObject? r = null;
            await Run(async api => { r = await api.Post("material/save", body); });
            if (r == null) return;
            var oldName = _matName;
            if (asNew)
            {
                // (1.68.1) the material of the project becomes the new library material: its objects keep their look
                _matName = (string?)r["name"] ?? _matName;
                if (_lastPreview.name == oldName && _lastPreview.image != null) _lastPreview = (_matName, _lastPreview.image);
                if (_matName != oldName) { await RefreshScene(); await PushMaterialToViewer(_matName); }
                Status(L.F("Salvato nella libreria come {0}: gli oggetti lo usano già", _matName));
            }
            else Status(L.F("{0} salvato nella libreria", _matName));
            await ReloadLibraryMaterials();
            await LoadMaterial();
            RenderProps();
        }

        void StartEyedropper()
        {
            SendToWeb(new { type = "eyedropper" });
            Status(L.T("Contagocce: clicca una superficie nella vista per modificarne il materiale (Esc per annullare)"));
        }

        /// <summary>Called by the viewer after an eyedropper click.</summary>
        async Task OnEyedropper(string id, string material)
        {
            if (material == "" && _scene.ById.TryGetValue(id, out var o) && o.Materials.Count > 0) material = o.Materials[0];
            if (material == "") { Status(L.T("Nessun materiale su quella superficie"), true); return; }
            // a library model is picked as a whole: the piece of it that really has this material
            if (_scene.ById.TryGetValue(id, out var picked) && !picked.Materials.Contains(material))
            {
                SceneObject? Find(SceneObject o) { foreach (var c in o.Children) { if (c.Materials.Contains(material)) return c; var f = Find(c); if (f != null) return f; } return null; }
                if (Find(picked) is SceneObject part) id = part.Id;
            }
            int slot = _scene.ById.TryGetValue(id, out var so) ? so.Materials.IndexOf(material) : -1;
            await OpenMaterialEditor(material, id, slot);
        }

        // ---------------------------------------------------------------- object properties: the material slots

        UIElement MaterialSection(SceneObject o)
        {
            var sp = new StackPanel();
            sp.Children.Add(SectionTitle(L.T("Materiale")));
            if (o.IsMesh && o.Materials.Count > 0)
            {
                for (int i = 0; i < o.Materials.Count; i++)
                {
                    var name = o.Materials[i];
                    var slot = i;
                    // the material of the object: a click opens it in the editor
                    var row = new DockPanel { Margin = new Thickness(0, 0, 0, 4), Background = Brushes.Transparent, Cursor = name != "" ? Cursors.Hand : null,
                                              ToolTip = name != "" ? L.T("Clic per modificare il materiale") : null };
                    var chev = Theme.Icon(Icons.Chevron, Theme.TextFaint, 14);
                    DockPanel.SetDock(chev, Dock.Right);
                    if (name != "") row.Children.Add(chev);
                    var label = Theme.Label((o.Materials.Count > 1 ? $"{slot + 1}. " : "") + (name == "" ? L.T("(nessuno)") : name), 13, Theme.Text);
                    label.Margin = new Thickness(0, 3, 8, 3);
                    row.Children.Add(label);
                    if (name != "")
                    {
                        row.MouseLeftButtonUp += async (_, __) => await OpenMaterialEditor(name, o.Id, slot);
                        row.MouseEnter += (_, __) => row.Background = Theme.B("#13213B");
                        row.MouseLeave += (_, __) => row.Background = Brushes.Transparent;
                    }
                    sp.Children.Add(row);
                }
            }
            var tools = new WrapPanel { Margin = new Thickness(0, 6, 0, 0) };
            tools.Children.Add(SmallButton(EyedropperIcon, L.T("Contagocce"), () => { StartEyedropper(); return Task.CompletedTask; }));
            tools.Children.Add(SmallButton(Icons.Sliders, L.T("Materiali della scena"), async () => await ShowSceneMaterials()));
            sp.Children.Add(tools);
            var hint = Theme.Label(L.T("Per applicare un materiale trascinalo dalla libreria in basso sopra l'oggetto nella vista (Maiusc: tutto il gruppo). ") +
                                   L.T("Per modificarlo clicca il suo nome qui sopra o il materiale nella libreria."), 12, Theme.TextFaint);
            hint.TextWrapping = TextWrapping.Wrap;
            hint.Margin = new Thickness(0, 6, 0, 0);
            sp.Children.Add(hint);
            return sp;
        }

        static readonly Geometry EyedropperIcon = Geometry.Parse("M14.5 5.5 18.5 9.5 M16.5 3.5a2.1 2.1 0 0 1 3 3l-2 2-3-3z M15 7l-9 9-1.5 4.5L9 19l9-9");

        // ---------------------------------------------------------------- scene materials

        void RenderSceneMaterialsPanel()
        {
            var head = new StackPanel();
            head.Children.Add(Theme.Caption(L.T("Materiali della scena")));
            var back = SmallButton(Icons.Undo, L.T("Torna alle proprietà"), async () => await ShowRightPanel(""));
            back.Margin = new Thickness(0, 10, 0, 0);
            back.HorizontalAlignment = HorizontalAlignment.Left;
            head.Children.Add(back);
            _props.Children.Add(Theme.Card(head, 16));
            var list = new StackPanel();
            _props.Children.Add(Theme.Card(list, 16));
            list.Children.Add(Theme.Label(L.T("Caricamento…"), 12, Theme.TextFaint));
            _ = FillSceneMaterials(list);
        }

        async Task FillSceneMaterials(StackPanel list)
        {
            JsonObject? r = null;
            await Run(async api => { r = await api.Get("scene/materials"); });
            list.Children.Clear();
            foreach (var m in (r?["materials"] as JsonArray)?.OfType<JsonObject>() ?? Enumerable.Empty<JsonObject>())
            {
                var name = (string?)m["name"] ?? "";
                var row = new DockPanel { Margin = new Thickness(0, 0, 0, 4), Background = Brushes.Transparent, Cursor = Cursors.Hand };
                var col = m["color"] as JsonArray;
                var sw = new Border { Width = 20, Height = 20, CornerRadius = new CornerRadius(10), Margin = new Thickness(0, 0, 10, 0),
                                      Background = new SolidColorBrush(LinColor(col)) };
                row.Children.Add(sw);
                var users = Theme.Label(L.F("{0} ogg.", (int?)m["users"] ?? 0), 11, Theme.TextFaint);
                DockPanel.SetDock(users, Dock.Right);
                row.Children.Add(users);
                var tags = ((bool?)m["textured"] ?? false ? " · " + L.T("texture") : "") + ((bool?)m["advanced"] ?? false ? " · " + L.T("avanzato") : "");
                row.Children.Add(Theme.Label(name + tags, 13, Theme.Text));
                row.MouseLeftButtonUp += async (_, __) => await OpenMaterialEditor(name);
                row.MouseEnter += (_, __) => row.Background = Theme.B("#13213B");
                row.MouseLeave += (_, __) => row.Background = Brushes.Transparent;
                list.Children.Add(row);
            }
            if (list.Children.Count == 0) list.Children.Add(Theme.Label(L.T("Nessun materiale nella scena"), 12, Theme.TextFaint));
        }

        static Color LinColor(JsonArray? c)
        {
            double V(int i) => c != null && c.Count > i ? (double?)c[i] ?? 0.8 : 0.8;
            byte B(double lin) => (byte)Math.Round(Math.Clamp(ColorField.ToSrgb(Math.Clamp(lin, 0, 1)), 0, 1) * 255);
            return Color.FromRgb(B(V(0)), B(V(1)), B(V(2)));
        }

        // ---------------------------------------------------------------- the editor

        JsonObject MP => _matInfo["params"] as JsonObject ?? new JsonObject();

        JsonNode? P(string path)
        {
            JsonNode? n = MP;
            foreach (var k in path.Split('.')) n = (n as JsonObject)?[k];
            return n;
        }
        double D(string path, double def = 0) { try { return (double?)P(path) ?? def; } catch { return def; } }
        bool Bo(string path) { try { return (bool?)P(path) ?? false; } catch { return false; } }
        string S(string path) { try { return (string?)P(path) ?? ""; } catch { return ""; } }
        double[] V3(string path)
        {
            var a = P(path) as JsonArray;
            return a != null && a.Count >= 3 ? new[] { (double?)a[0] ?? 0, (double?)a[1] ?? 0, (double?)a[2] ?? 0 } : new[] { 0.8, 0.8, 0.8 };
        }

        static JsonObject Patch(string path, JsonNode? value)
        {
            var keys = path.Split('.');
            var root = new JsonObject();
            var cur = root;
            for (int i = 0; i < keys.Length - 1; i++) { var next = new JsonObject(); cur[keys[i]] = next; cur = next; }
            cur[keys[^1]] = value;
            return root;
        }

        /// <summary>Sends a change of the material; rebuild=true redraws the panel (sections that appear or disappear).</summary>
        bool _editAll;          // a shared material: false = the changes go only on the object it was opened from

        /// <summary>Before a change: a shared material opened from one object, in "Solo questo oggetto" mode, becomes
        /// a copy of that object only (the others keep the original). True when the copy was made.</summary>
        /// <summary>The other models (not pieces of the one the material was opened from) that use the material, and
        /// whether models of distributions use it too (they are not in the scene list).</summary>
        (List<SceneObject> others, List<SceneObject> all, bool inDistributions) MaterialModels()
        {
            var rootOf = _matObject != "" ? ModelRootOf(_matObject) : "";
            var users = _scene.ById.Values.Where(o => o.IsMesh && o.Materials.Contains(_matName)).ToList();
            var all = users.Select(o => ModelRootOf(o.Id)).Distinct()
                           .Select(id => _scene.ById.TryGetValue(id, out var x) ? x : null).Where(x => x != null).Select(x => x!).ToList();
            bool dist = ((int?)_matInfo["users"] ?? 0) > users.Count;
            return (all.Where(x => x.Id != rootOf).ToList(), all, dist);
        }

        /// <summary>«Qui» (1.68.5): where a change goes when it must not reach the others - the selection, when the
        /// object the material was opened from is in it (a model selected = all its pieces), else that object alone.</summary>
        List<string> HereIds()
        {
            if (_matObject == "") return new List<string>();
            var sel = _selection.Where(s => _scene.ById.ContainsKey(s)).ToList();
            bool inside = sel.Contains(_matObject) || (_scene.ById.TryGetValue(_matObject, out var mo) && _scene.Ancestors(mo).Any(a => sel.Contains(a.Id)));
            return inside ? sel : new List<string> { _matObject };
        }

        /// <summary>The pieces with this material inside «qui», and all the pieces with it (distribution models too).</summary>
        (int here, int all) HereCounts()
        {
            var ids = new HashSet<string>(HereIds());
            int here = _scene.ById.Values.Count(o => o.Materials.Contains(_matName) && (ids.Contains(o.Id) || _scene.Ancestors(o).Any(a => ids.Contains(a.Id))));
            int all = Math.Max((int?)_matInfo["users"] ?? 0, _scene.ById.Values.Count(o => o.Materials.Contains(_matName)));
            return (here, all);
        }

        async Task<bool> EnsureOwnCopy()
        {
            if (_editAll || _matObject == "") return false;
            var (here, all) = HereCounts();
            if (here == 0 || here >= all) return false;        // nobody else uses it: nothing to protect
            var before = _matName;
            await DuplicateForObject();
            return _matName != before;
        }

        async Task EditMat(JsonObject patch, bool rebuild = false, bool convert = false)
        {
            if (await EnsureOwnCopy()) rebuild = true;
            JsonObject? r = null;
            await Run(async api =>
            {
                r = await api.Post("material/edit", new JsonObject { ["name"] = _matName, ["params"] = patch, ["convert"] = convert, ["id"] = _matObject });
                UpdateHistory(await api.Get("history"));
            });
            if (r == null) return;
            _matInfo["params"] = r["params"]?.DeepClone();
            if ((bool?)r["metalRemoved"] == true)
            {
                rebuild = true;
                Status(L.T("Metallo tolto: un vetro non può essere metallico (il metallo vince sulla trasparenza e il vetro resta uno specchio)"));
            }
            await PushMaterialToViewer(_matName);
            bool wasDirty = (bool?)_matInfo["dirty"] ?? false;
            if (rebuild || convert || (!wasDirty && _matInfo["library"] is JsonObject)) { await LoadMaterial(); RenderProps(); }
            _ = RequestLivePreview();
        }

        Task EditMat(string path, JsonNode? value, bool rebuild = false) => EditMat(Patch(path, value), rebuild);

        /// <summary>The texture centred on the selected object (the engine computes the offset, matedit.center).</summary>
        async Task FitMap()
        {
            // (opened from the list of the scene materials: every object with it, each on its own shape)
            await EnsureOwnCopy();
            JsonObject? r = null;
            var body = new JsonObject { ["name"] = _matName };
            // (1.68.6) the pieces chosen - the selection, or the piece clicked - get ONE picture over all of them together
            // (a window made of several pieces); opened from the list: every object on its own shape
            if (_matObject != "") body["ids"] = new JsonArray(HereIds().Select(x => (JsonNode)x!).ToArray());
            await Run(async api =>
            {
                r = await api.Post("material/fit", body);
                UpdateHistory(await api.Get("history"));
            });
            if (r == null) return;
            _matInfo["params"] = r["params"]?.DeepClone();
            // the faces got new UV: the view takes again only the objects changed (1.70.3: the whole scene before -
            // 20 s on a big model); many of them, or anything unexpected: the whole view, as before
            var geo = (r["geometry"] as JsonArray)?.Select(x => (string?)x ?? "").Where(x => x != "").Distinct().ToList() ?? new List<string>();
            bool partial = geo.Count > 0 && geo.Count <= 500 && _webReady && !_reloading;
            if (!partial) ForcePreviewReload("new UV of «Adatta all'oggetto»");
            await RefreshScene();
            if (partial && !await AddPartToViewer(geo, replace: true)) { ForcePreviewReload("new UV of «Adatta all'oggetto»"); await RefreshScene(); }
            else if (partial) await PushMaterialToViewer(_matName);      // (its repeat and offset back to one picture)
            await LoadMaterial(); RenderProps();
            _ = RequestLivePreview();
            int n = (int?)r["fitted"] ?? 1, pieces = (int?)r["pieces"] ?? 0;
            Status(pieces > 1 ? L.F("Una sola immagine su {0} pezzi insieme", pieces)
                 : n > 1 ? L.F("Texture adattata a {0} oggetti, ognuno sulla sua forma", n) : L.T("Texture adattata all'oggetto"));
        }

        async Task CenterMap()
        {
            if (_matObject == "") return;
            await EnsureOwnCopy();
            JsonObject? r = null;
            await Run(async api =>
            {
                r = await api.Post("material/center", new JsonObject { ["name"] = _matName, ["id"] = _matObject });
                UpdateHistory(await api.Get("history"));
            });
            if (r == null) return;
            _matInfo["params"] = r["params"]?.DeepClone();
            await PushMaterialToViewer(_matName);
            await LoadMaterial(); RenderProps();
            _ = RequestLivePreview();
            Status(L.T("Texture centrata sull'oggetto"));
        }

        /// <summary>The real-time view rebuilds the material of every object using it (maps loaded from the engine).</summary>
        async Task PushMaterialToViewer(string name)
        {
            var ids = _scene.ById.Values.Where(o => o.IsMesh && o.Materials.Contains(name)).Select(o => o.Id).ToList();
            // the models of the distributions are not in the scene list: the engine knows them
            JsonObject? us = null;
            await Run(async api => { us = await api.Get("material/users?name=" + Uri.EscapeDataString(name)); });
            foreach (var u in (us?["ids"] as JsonArray)?.Select(n => (string?)n ?? "") ?? Enumerable.Empty<string>())
                if (u != "" && !ids.Contains(u)) ids.Add(u);
            if (ids.Count == 0) return;
            JsonObject? rm = null;
            await Run(async api => { rm = await api.Post("realtime/materials", new { ids }); });
            if (rm?["objects"] is not JsonObject objs) return;
            var items = new List<object>();
            foreach (var id in ids)
            {
                if (objs[id] is not JsonArray slots) continue;
                _scene.ById.TryGetValue(id, out var o);        // (null: a model of a distribution, the view matches by name)
                var arr = new JsonArray();
                for (int i = 0; i < slots.Count; i++)
                {
                    var sl = (JsonObject)slots[i]!.DeepClone();
                    sl["old"] = o == null ? (string?)sl["name"] : i < o.Materials.Count ? o.Materials[i] : null;
                    arr.Add(sl);
                }
                items.Add(new { id, slots = arr });
            }
            SendToWeb(new { type = "materials", items = items.ToArray() });
        }

        /// <summary>After a new 3D view is loaded: materials edited in Simpler are rebuilt there with all their channels.</summary>
        async Task PushSimplerMaterials()
        {
            JsonObject? r = null;
            try { if (_api != null) r = await _api.Get("scene/materials"); } catch { return; }
            var names = (r?["materials"] as JsonArray)?.OfType<JsonObject>().Where(m => (bool?)m["simpler"] ?? false)
                        .Select(m => (string?)m["name"] ?? "").ToList() ?? new List<string>();
            foreach (var n in names) await PushMaterialToViewer(n);
        }

        void RenderMaterialPanel()
        {
            if (_matName == "") { RenderSceneMaterialsPanel(); return; }
            bool advanced = (bool?)_matInfo["advanced"] ?? false;
            bool simpler = (bool?)_matInfo["simpler"] ?? false;

            // ---- header
            var head = new StackPanel();
            head.Children.Add(Theme.Caption(L.T("Materiale")));
            var name = Theme.Input(_matName);
            name.FontSize = 15;
            name.Margin = new Thickness(0, 8, 0, 4);
            async Task CommitName()
            {
                var n = name.Text.Trim();
                if (n == "" || n == _matName) return;
                JsonObject? r = null;
                await Run(async api => { r = await api.Post("material/rename", new { name = _matName, newName = n }); });
                if (r == null) return;
                _matName = (string?)r["name"] ?? n;
                await RefreshScene();
                await LoadMaterial();
                RenderProps();
            }
            name.KeyDown += async (_, e) => { if (e.Key == Key.Enter) await CommitName(); };
            name.LostFocus += async (_, __) => await CommitName();
            head.Children.Add(name);
            // type of material (as the templates of D5 Render): it decides which controls the panel shows.
            // Standard = every channel of a physical material; Acqua = only what water needs. More types later.
            var isWater = (bool?)(_matInfo["water"] as JsonObject)?["on"] ?? false;
            var isVolume = (bool?)(_matInfo["volumetric"] as JsonObject)?["on"] ?? false;
            var typeRow = new DockPanel { Margin = new Thickness(0, 4, 0, 8) };
            var tl = Theme.Label(L.T("Tipo"), 12, Theme.TextMuted);
            tl.Width = 50; tl.VerticalAlignment = VerticalAlignment.Center;
            DockPanel.SetDock(tl, Dock.Left);
            typeRow.Children.Add(tl);
            // which objects show this material: right under the type, in sight (editing a material that is on no object
            // of the scene changes nothing in the view, and it was easy not to notice). Many objects: an openable list.
            UIElement? pendingUsers = null;
            {
                var usersN = (int?)_matInfo["users"] ?? 0;
                var objs = _scene.ById.Values.Where(o => o.IsMesh && o.Materials.Contains(_matName)).OrderBy(o => o.Name, StringComparer.CurrentCultureIgnoreCase).ToList();
                if (usersN == 0)
                {
                    var ul = Theme.Label(L.T("Non è su nessun oggetto della scena: le modifiche non si vedono nella vista"), 12, Theme.Warm);
                    ul.TextWrapping = TextWrapping.Wrap; ul.Margin = new Thickness(0, 0, 0, 6);
                    pendingUsers = ul;
                }
                else
                {
                    var label = objs.Count == 1 ? L.F("Su: {0}", objs[0].Name)
                              : usersN == 1 ? L.T("Su 1 oggetto") : L.F("Su {0} oggetti", usersN);
                    var ub = Theme.Button(Theme.IconText(Icons.ChevronDown, label, Theme.TextMuted, 12), Theme.Kind.Ghost,
                                          L.T("Gli oggetti con questo materiale: clic su uno per selezionarlo"));
                    ub.MinHeight = 24; ub.FontSize = 12; ub.Padding = new Thickness(4, 0, 6, 0); ub.Margin = new Thickness(-4, 0, 0, 6);
                    ub.HorizontalAlignment = HorizontalAlignment.Left;
                    ub.Click += (_, __) =>
                    {
                        var cm = new ContextMenu { PlacementTarget = ub, Placement = System.Windows.Controls.Primitives.PlacementMode.Bottom, MaxHeight = 420 };
                        foreach (var o in objs.Take(300))
                        {
                            var mi = new MenuItem { Header = o.Name };
                            var oid = o.Id;
                            mi.Click += (_, __) => Select(oid);
                            cm.Items.Add(mi);
                        }
                        var hidden = usersN - Math.Min(300, objs.Count);
                        if (hidden > 0)
                            cm.Items.Add(new MenuItem { Header = objs.Count > 300 ? L.F("… e altri {0}", hidden) : L.F("… e {0} nei modelli delle distribuzioni", hidden), IsEnabled = false });
                        cm.IsOpen = true;
                    };
                    pendingUsers = ub;
                }
            }
            typeRow.Children.Add(MaterialTypePicker(isVolume ? "volumetric" : isWater ? "water" : Bo("foliage.enabled") ? "foliage" : Bo("fabric.enabled") ? "fabric" : Bo("interior.enabled") ? "interior" : Bo("displacement.enabled") ? "displacement" : "standard"));
            head.Children.Add(typeRow);
            if (pendingUsers != null) head.Children.Add(pendingUsers);
            // a material shared by several objects, opened from one of them: the changes go only on that object (it gets
            // its own copy at the first change, as one expects) or on all of them. A copy can then be dragged on others.
            // the models (not the pieces) that use this material: «Solo questo modello» copies it for one of them
            // (1.68.5) one switch, whenever other objects use the material too: «Solo qui» (the selection, or the piece
            // clicked: they get a copy of the material at the first change) or «Ovunque» (every object with it)
            var (others, models, inDist) = MaterialModels();
            var (hereN, allN) = HereCounts();
            if (_matObject != "" && hereN > 0 && hereN < allN)
            {
                var sc = Theme.Segmented(out var scb,
                    (L.F("Solo qui ({0})", hereN), L.T("Alla prima modifica questi pezzi (gli oggetti selezionati, o solo quello cliccato se non c'è una selezione) ricevono una copia del materiale tutta loro: gli altri oggetti non cambiano")),
                    (L.F("Ovunque ({0})", allN), L.T("Le modifiche valgono per tutti gli oggetti con questo materiale")));
                Theme.SetSegment(scb, _editAll ? 1 : 0);
                scb[0].Click += (_, __) => { _editAll = false; RenderProps(); };
                scb[1].Click += (_, __) => { _editAll = true; RenderProps(); };
                var srow = new DockPanel { Margin = new Thickness(0, 0, 0, 8) };
                var sl = Theme.Label(L.T("Vale"), 12, Theme.TextMuted); sl.Width = 50; sl.VerticalAlignment = VerticalAlignment.Center;
                DockPanel.SetDock(sl, Dock.Left);
                srow.Children.Add(sl); srow.Children.Add(sc);
                head.Children.Add(srow);
            }
            // the change reaches other models: said in orange, with their names
            if ((others.Count > 0 || inDist) && (_matObject == "" || _editAll))
            {
                var parts = others.Take(4).Select(x => x.Name).ToList();
                if (others.Count > 4) parts.Add(L.F("altri {0}", others.Count - 4));
                if (inDist) parts.Add(L.T("i modelli delle distribuzioni"));
                var names = string.Join(", ", parts);
                var warn = Theme.Label(L.F("Le modifiche cambiano anche: {0}", names), 12, Theme.Warm);
                warn.TextWrapping = TextWrapping.Wrap; warn.Margin = new Thickness(0, 0, 0, 8);
                head.Children.Add(warn);
            }
            var users = (int?)_matInfo["users"] ?? 0;
            var lib = _matInfo["library"] as JsonObject;
            bool dirty = (bool?)_matInfo["dirty"] ?? false;
            head.Children.Add(PreviewFrame());
            // the library (1.68.5): what the changes of the panel never touch by themselves. One line says how the
            // material stands there, at most two buttons. «Salva» is only the project's
            var libState = lib == null ? L.T("Non è nella libreria (le modifiche restano in questo progetto)")
                         : dirty ? L.T("Nella libreria: diverso da questo (le modifiche restano in questo progetto)")
                         : L.T("Nella libreria: uguale a questo");
            var ls = Theme.Label(libState, 12, lib != null && dirty ? Theme.Warm : Theme.TextFaint);
            ls.TextWrapping = TextWrapping.Wrap; ls.Margin = new Thickness(0, 8, 0, 4);
            if (lib != null) ls.ToolTip = L.F("Nella libreria: {0}", string.IsNullOrEmpty((string?)lib["folder"]) ? L.T("Materiali") : L.T("Materiali") + " / " + ((string?)lib["folder"])!.Replace("/", " / "));
            head.Children.Add(ls);
            var save = new WrapPanel();
            // (Luca: «le cartelle rosse non consentono modifiche») the material of a locked Simpler folder is not replaced:
            // only «Aggiungi come nuovo…» (into one's own folders)
            bool libRo = SimplerLocked && lib != null && InSimplerMatPath((string?)lib["folder"] ?? "");
            var saveBtn = Theme.Button(Theme.IconText(Icons.Save, lib != null ? L.T("Aggiorna la libreria") : L.T("Aggiungi alla libreria…"), dirty || lib == null ? Theme.AccentText : null, 14),
                                       dirty || lib == null ? Theme.Kind.Primary : Theme.Kind.Normal,
                                       lib != null ? L.T("Il materiale della libreria prende queste impostazioni: vale per i nuovi usi, i progetti già fatti non cambiano")
                                                   : L.T("Una copia nella libreria, per usarlo anche in altri progetti; qui non cambia niente"));
            saveBtn.MinHeight = 30; saveBtn.FontSize = 12; saveBtn.Margin = new Thickness(0, 0, 6, 0);
            saveBtn.Click += async (_, __) => await SaveMaterial(false);
            if (!libRo) save.Children.Add(saveBtn);
            if (lib != null)
            {
                var saveNew = SmallButton(Icons.Copy, L.T("Aggiungi come nuovo…"), async () => await SaveMaterial(true));
                saveNew.ToolTip = L.T("Un materiale nuovo nella libreria con queste impostazioni, con il nome che scegli; quello di prima resta com'è");
                save.Children.Add(saveNew);
            }
            head.Children.Add(save);
            // name, preview and saving stay at the top while the parameters scroll
            _propsTop.Children.Add(Theme.Card(head, 16));
            _propsTop.Visibility = Visibility.Visible;

            head = new StackPanel();
            if (users == 0)
                head.Children.Add(Theme.Label(L.T("Non ancora usato nella scena: trascinalo su un oggetto"), 12, Theme.TextFaint));
            var actions = new WrapPanel { Margin = new Thickness(0, users == 0 ? 6 : 0, 0, 0) };
            actions.Children.Add(SmallButton(Icons.Undo, L.T("Proprietà"), async () => await ShowRightPanel("")));
            actions.Children.Add(SmallButton(Icons.Refresh, L.T("Sostituisci ovunque…"), async () => { await Task.Yield(); ShowReplaceMenu(); }));
            if ((bool?)_matInfo["hasOriginal"] ?? false)
                actions.Children.Add(SmallButton(Icons.Undo, L.T("Ripristina originale"), async () =>
                {
                    await Run(async api => { await api.Post("material/reset", new { name = _matName }); UpdateHistory(await api.Get("history")); });
                    await LoadMaterial(); await PushMaterialToViewer(_matName); RenderProps();
                }));
            actions.Children.Add(SmallButton(Icons.Sliders, L.T("Materiali della scena"), async () => await ShowSceneMaterials()));
            head.Children.Add(actions);
            _props.Children.Add(Theme.Card(head, 16));

            if (advanced)
            {
                var adv = new StackPanel();
                var t = Theme.Label(L.T("Questo materiale usa una costruzione che l'editor non sa leggere senza perdere qualcosa: è lasciato com'è. ") +
                                    L.T("Convertendolo diventa un materiale Simpler modificabile, ricostruito dai canali che l'editor riconosce."), 12, Theme.TextSoft);
                t.TextWrapping = TextWrapping.Wrap;
                adv.Children.Add(t);
                var conv = Theme.Button(L.T("Converti in materiale Simpler"), Theme.Kind.Primary);
                conv.Margin = new Thickness(0, 10, 0, 0);
                conv.HorizontalAlignment = HorizontalAlignment.Left;
                conv.Click += async (_, __) => await EditMat(new JsonObject(), true, true);
                adv.Children.Add(conv);
                _props.Children.Add(Theme.Card(adv, 16));
                return;
            }

            if ((bool?)(_matInfo["water"] as JsonObject)?["on"] ?? false)
            {
                WaterSection();         // type Acqua: only the controls water needs
                return;
            }
            if ((bool?)(_matInfo["volumetric"] as JsonObject)?["on"] ?? false)
            {
                VolumeSection();        // type Volumetrico: fog, smoke, clouds, fire inside the model
                return;
            }
            if (Bo("interior.enabled"))
            {
                // type Interni (1.79.0): the rooms behind the glass, then the glass itself (its tint and its reflections)
                InteriorSection();
                ColorSection();
                RoughnessSection();
                return;
            }
            if (Bo("foliage.enabled"))
            {
                // type Fogliame (1.77.0): its group first, then only what a leaf or a bark needs
                FoliageSection();
                ColorSection();
                RoughnessSection();
                GrungeSection();
                ReliefSection();
                if (D("subsurface.weight") > 0) SubsurfaceSection();     // (set before: shown so it can be taken away)
                OpacitySection();
                MappingSection();
                return;
            }
            if (Bo("fabric.enabled"))
            {
                // type Tessuto (1.77.1): its group (with the fuzz, the sheen of Standard), then what a cloth needs
                FabricSection();
                ColorSection();
                RoughnessSection();
                GrungeSection();
                ReliefSection();
                if (D("subsurface.weight") > 0) SubsurfaceSection();
                OpacitySection();
                MappingSection();
                return;
            }
            // type Displacement: its group first, then every channel of Standard (Standard has no displacement)
            if (Bo("displacement.enabled")) DisplacementSection();
            ColorSection();
            RoughnessSection();
            GrungeSection();
            MacroSection();
            MetallicSection();
            ReliefSection();
            ReflectionSection();
            GlassSection();
            SheenSection();
            SubsurfaceSection();
            EmissionSection();
            OpacitySection();
            MappingSection();
            if (!simpler)
            {
                var note = Theme.Label(L.T("Alla prima modifica il materiale originale viene conservato: \"Ripristina originale\" lo rimette com'era."), 11, Theme.TextFaint);
                note.TextWrapping = TextWrapping.Wrap;
                _props.Children.Add(Theme.Card(note, 16));
            }
        }

        async Task DuplicateForObject()
        {
            JsonObject? r = null;
            var ids = HereIds();
            // the copy's name: the object chosen when it is one, else «<name> copia» (renamed at the top if wanted)
            var oneName = ids.Count == 1 && _scene.ById.TryGetValue(ids[0], out var one) ? one.Name : "";
            await Run(async api =>
            {
                r = await api.Post("material/duplicate", new JsonObject { ["name"] = _matName, ["ids"] = new JsonArray(ids.Select(x => (JsonNode)x!).ToArray()),
                                                                         ["newName"] = oneName != "" ? _matName + " · " + oneName : null });
                UpdateHistory(await api.Get("history"));
            });
            if (r == null) return;
            if ((int?)r["assigned"] == 0)
            {
                // the object chosen does not use this material (e.g. a group): the change goes to the material itself
                _editAll = true;
                return;
            }
            _matName = (string?)r["name"] ?? _matName;
            await RefreshScene();
            await LoadMaterial();
            RenderProps();
            Status(L.F("Da qui in avanti «{0}» vale solo qui: gli altri oggetti tengono il materiale di prima. Puoi rinominarlo in alto.", _matName));
        }

        void ShowReplaceMenu()
        {
            var m = new ContextMenu { Placement = System.Windows.Controls.Primitives.PlacementMode.MousePoint };
            foreach (var lib in _materials.OfType<JsonObject>())
            {
                var id = (string?)lib["id"] ?? "";
                var label = (string?)lib["name"] ?? id;
                var item = new MenuItem { Header = label + "  ·  " + ((string?)lib["category"] ?? "") };
                item.Click += async (_, __) =>
                {
                    var ids = _scene.ById.Values.Where(o => o.Materials.Contains(_matName)).Select(o => o.Id).ToArray();
                    JsonObject? r = null;
                    await Run(async api => { r = await api.Post("material/replace", new { name = _matName, with = id }); UpdateHistory(await api.Get("history")); });
                    if (r == null) return;
                    Status(L.F("{0} sostituito con {1} su {2} oggetti", _matName, label, (int?)r["replaced"] ?? 0));
                    _matName = (string?)r["material"] ?? _matName;
                    await RefreshScene();
                    await LoadMaterial();
                    RenderProps();
                };
                m.Items.Add(item);
            }
            m.IsOpen = true;
        }

        // ---------------------------------------------------------------- building blocks

        StackPanel Section(string title)
        {
            var sp = new StackPanel();
            sp.Children.Add(SectionTitle(title));
            _props.Children.Add(Theme.Card(sp, 16));
            return sp;
        }

        ValueSlider MatSlider(Panel parent, string label, string path, double def, double min, double max, bool log = false,
                              string fmt = "0.##", string? unit = null, string? tip = null, double scale = 1, bool rebuild = false, Brush? track = null)
        {
            var s = new ValueSlider(label, D(path, def) * scale, min, max, log, fmt, unit, track, tip);
            s.Committed += async v => await EditMat(path, JsonValue.Create(v / scale), rebuild);
            parent.Children.Add(s);
            return s;
        }

        Toggle MatToggle(Panel parent, string label, string path, string? tip = null, bool rebuild = true)
        {
            var t = new Toggle(label, Bo(path), tip);
            t.Toggled += async v => await EditMat(path, JsonValue.Create(v), rebuild);
            parent.Children.Add(t);
            return t;
        }

        ColorField MatColor(Panel parent, string label, string path, string? tip = null)
        {
            var c = new ColorField(label, V3(path), tip);
            c.Committed += async v => await EditMat(path, new JsonArray(v[0], v[1], v[2]));
            parent.Children.Add(c);
            return c;
        }

        /// <summary>How water moves (material Acqua): height and size of its waves, right for each other.</summary>
        static readonly (string label, string tip, bool on, double h, double s)[] WaterPresets =
        {
            ("Ferma", "Acqua immobile: uno specchio (niente onde)", false, 0.08, 0.6),
            ("Increspata", "Increspature leggere: una piscina, un lago senza vento (1,5 cm, ogni 15 cm)", true, 0.015, 0.15),
            ("Mossa", "Onde piccole: acqua mossa da un po' di vento (5 cm, ogni 50 cm)", true, 0.05, 0.5),
            ("Agitata", "Onde vere e proprie (15 cm, ogni 1,2 m)", true, 0.15, 1.2),
        };

        /// <summary>(1.75.0) Water with waves chosen: the caustics come on by themselves when they are off (the net of
        /// light on the bottom and the light reflected on the walls). Never switched off here.</summary>
        async Task CausticsForWater()
        {
            await LoadRenderSettings();
            bool B(string k) => (bool?)_renderSettings["config"]?[k] ?? true;
            bool any = CausticsAny(), refl = (bool?)_renderSettings["config"]?["causticsReflected"] ?? false;
            if (any && refl) return;
            await RsPost(new JsonObject
            {
                ["config"] = new JsonObject
                {
                    ["causticsReflective"] = true, ["causticsRefractive"] = true, ["causticsReflected"] = true,
                    ["blurGlossy"] = 0.0, ["clampIndirect"] = 0.0,
                },
            });
            await LoadRenderSettings();
            // (19/11) «Attive» is the only way they are on now: before, this left the hidden «Normali» (no net on the bottom)
            if (!_caustics) await SetCaustics(true, 2);
            Status(L.T("Caustiche accese per l'acqua: rete di luce sul fondale e luce riflessa sulle pareti (Rendering → Caustiche per spegnerle)"));
        }

        static TextBlock Note(string text)
        {
            var t = Theme.Label(text, 11, Theme.TextFaint);
            t.TextWrapping = TextWrapping.Wrap;
            t.Margin = new Thickness(0, 0, 0, 8);
            return t;
        }

        const string ImageFilter = "Immagini|*.png;*.jpg;*.jpeg;*.tif;*.tiff;*.exr;*.hdr;*.bmp;*.tga;*.webp|Tutti i file|*.*";

        /// <summary>A texture slot: thumbnail, file name, load/remove; options for invert, channel and strength.</summary>
        void MapRow(Panel parent, string label, string path, bool strength = true, bool channel = true, bool invert = true, Panel? adv = null, bool scale = false)
        {
            var image = S(path + ".image");
            var row = new DockPanel { Margin = new Thickness(0, 2, 0, 8) };
            var l = Theme.Label(label, 12, Theme.TextMuted);
            l.Width = 96;
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
                rm.Click += async (_, __) => await EditMat(path, new JsonObject { ["image"] = "", ["channel"] = "", ["invert"] = false, ["strength"] = 1.0 }, true);
                DockPanel.SetDock(rm, Dock.Right);
                row.Children.Add(rm);
            }
            var info = (_matInfo["images"] as JsonObject)?[image] as JsonObject;
            // "Genera": the map made by DeepBump on this computer (normal from the colour, height, resolution ×2)
            if (MapGenerators(path, image, info).Count > 0)
            {
                var gen = Theme.Button(Theme.Icon(Icons.Wand, Theme.TextSoft, 14, 1.2), Theme.Kind.Ghost,
                                       L.T("Genera questa mappa sul tuo computer (DeepBump): normale dalla texture del colore, altezza dalla normale, risoluzione doppia"));
                gen.MinHeight = 28; gen.Width = 30; gen.Height = 28; gen.Padding = new Thickness(0);
                gen.Click += (_, __) => { var cm = GenerateMenu(path, image, info); cm.PlacementTarget = gen; cm.Placement = System.Windows.Controls.Primitives.PlacementMode.Bottom; cm.IsOpen = true; };
                DockPanel.SetDock(gen, Dock.Right);
                row.Children.Add(gen);
            }
            var fileName = image == "" ? L.T("nessuna mappa") : ((string?)info?["file"] ?? image) + (((bool?)info?["missing"] ?? false) ? "  " + L.T("(file mancante)") : "");
            var fn = Theme.Label(fileName, 12, image == "" ? Theme.TextFaint : Theme.TextSoft);
            fn.ToolTip = fileName;
            row.Children.Add(fn);
            // right click on the map: preview, folder, copy, paste (maps copied in Simpler)
            void OpenMapMenu(FrameworkElement at, MouseButtonEventArgs e)
            {
                e.Handled = true;
                var cm = MapMenu(path, image, info);
                cm.PlacementTarget = at;
                cm.IsOpen = true;
            }
            thumb.MouseRightButtonUp += (_, e) => OpenMapMenu(thumb, e);
            fn.Background = Brushes.Transparent;
            fn.MouseRightButtonUp += (_, e) => OpenMapMenu(fn, e);
            if (image == "") thumb.ToolTip = L.T("Tasto destro: incolla una mappa copiata, o un'immagine dagli appunti (un ritaglio dello schermo, un'immagine copiata)");
            load.Click += async (_, __) =>
            {
                var dlg = new Microsoft.Win32.OpenFileDialog { Filter = L.T(ImageFilter), InitialDirectory = StartFolder("image") };
                if (dlg.ShowDialog(this) != true) return;
                Keep("image", dlg.FileName);
                await EditMat(path, new JsonObject { ["file"] = dlg.FileName }, true);
            };
            parent.Children.Add(row);
            if (image != "")
            {
                _ = LoadThumb(image, thumb);
                // click on the thumbnail: the texture big, in a small window that stays on top
                thumb.Cursor = Cursors.Hand;
                thumb.ToolTip = L.T("Clic per vedere la texture · tasto destro: anteprima, cartella, copia, incolla");
                thumb.MouseLeftButtonUp += async (_, __) =>
                {
                    if (_host == null) return;
                    await TextureViewer.Show(this, TexHttp, _host.Port, image, (string?)info?["file"] ?? image, (string?)info?["path"] ?? "",
                                             (int?)info?["width"] ?? 0, (int?)info?["height"] ?? 0, (bool?)info?["packed"] ?? false);
                };
            }
            if (image == "") return;

            var opts = new WrapPanel { Margin = new Thickness(96, 0, 0, 6) };
            if (channel)
            {
                var chans = new[] { "", "R", "G", "B", "A" };
                var seg = Theme.Segmented(out var buttons, (L.T("Auto"), L.T("Media dei canali")), ("R", L.T("Solo rosso")), ("G", L.T("Solo verde")),
                                          ("B", L.T("Solo blu")), ("A", L.T("Solo alfa")));
                Theme.SetSegment(buttons, Math.Max(0, Array.IndexOf(chans, S(path + ".channel"))));
                for (int i = 0; i < buttons.Count; i++)
                {
                    var ch = chans[i];
                    buttons[i].Click += async (_, __) => await EditMat(path + ".channel", JsonValue.Create(ch), true);
                }
                seg.Margin = new Thickness(0, 0, 8, 6);
                opts.Children.Add(seg);
            }
            if (opts.Children.Count > 0) parent.Children.Add(opts);
            var more = adv ?? parent;          // invert and weight: in the section's "Avanzate" when it has one
            if (invert) MatToggle(more, L.T("Inverti la mappa"), path + ".invert", L.T("Bianco diventa nero e viceversa"));
            if (strength) MatSlider(more, L.T("Peso mappa"), path + ".strength", 1, 0, 100, false, "0", "%",
                                    L.T("100% = conta solo la mappa · 0% = conta solo il valore del cursore"), 100);
            // (1.75.60) the map bigger than the material's UV, on its own (Luca: a glossiness map over many tiles)
            if (scale) MatSlider(more, L.T("Scala mappa"), path + ".scale", 1, 0.1, 50, true, "0.##", "×",
                                 L.T("1 = come le altre texture del materiale · 4 = la mappa quattro volte più grande: le sue macchie non si ripetono più su ogni piastrella"), 1, true);
        }

        async Task LoadThumb(string image, Border target)
        {
            if (_host == null) return;
            if (!_thumbs.TryGetValue(image, out var bmp))
            {
                try
                {
                    var bytes = await TexHttp.GetByteArrayAsync($"http://127.0.0.1:{_host.Port}/api/texture?image={Uri.EscapeDataString(image)}&px=128");
                    bmp = new BitmapImage();
                    bmp.BeginInit();
                    bmp.CacheOption = BitmapCacheOption.OnLoad;
                    bmp.DecodePixelWidth = 64;
                    bmp.StreamSource = new System.IO.MemoryStream(bytes);
                    bmp.EndInit();
                    bmp.Freeze();
                    _thumbs[image] = bmp;
                }
                catch { return; }
            }
            target.Background = new ImageBrush(bmp) { Stretch = Stretch.UniformToFill };
        }

        // ---------------------------------------------------------------- sections

        /// <summary>Invert or weight of a map away from the default (for the orange dot of "Avanzate").</summary>
        bool MapChanged(string path) => S(path + ".image") != "" && (Bo(path + ".invert") || Diff(D(path + ".strength", 1), 1) || Diff(D(path + ".scale", 1), 1));

        bool BoD(string path, bool def) { try { return (bool?)P(path) ?? def; } catch { return def; } }

        void ColorSection()
        {
            var sp = Section(L.T("Colore"));
            MatColor(sp, L.T("Tinta"), "color.tint", L.T("Colore di base; con una texture la tinge (bianco = texture com'è)"));
            var a = Advanced(sp, "mat:color");
            MapRow(sp, L.T("Texture"), "color.map", strength: false, channel: false, adv: a.Body);
            sp.Children.Remove(a.Root); sp.Children.Add(a.Root);          // under the texture
            MatSlider(a.Body, L.T("Luminosità"), "color.brightness", 1, 0, 200, false, "0", "%", L.T("100% = invariata"), 100);
            MatSlider(a.Body, L.T("Saturazione"), "color.saturation", 1, 0, 200, false, "0", "%", L.T("0% = bianco e nero · 100% = invariata"), 100);
            MatSlider(a.Body, L.T("Contrasto"), "color.contrast", 0, -100, 100, false, "0", "%", L.T("Più o meno differenza fra le parti chiare e scure della texture: 0% = come la foto, positivo = più contrasto, negativo = più piatta"), 100);
            a.Done(Diff(D("color.brightness", 1), 1) || Diff(D("color.saturation", 1), 1) || Diff(D("color.contrast", 0), 0) || MapChanged("color.map"));
        }

        /// <summary>«Sporco» (1.69.0): a layer of dirt over the material, its size independent of the UV.</summary>
        void GrungeSection()
        {
            var sp = Section(L.T("Sporco"));
            MatSlider(sp, L.T("Quantità"), "grunge.amount", 0, 0, 100, false, "0", "%",
                      L.T("Quanta superficie è coperta dallo sporco (macchie, colature, polvere): 0% = spento"), 100);
            MatSlider(sp, L.T("Opacità"), "grunge.opacity", 1, 0, 100, false, "0", "%",
                      L.T("Quanto lo sporco copre il materiale: 100% = pieno, 5% = appena un velo"), 100);
            // (1.69.2) from 5 cm to 50 m on a log scale, written in cm or m as it grows; typed as «3 m», «3,5m» or «250» (cm)
            var gs = MatSlider(sp, L.T("Dimensione"), "grunge.sizeCm", 50, 5, 5000, true, "0", null,
                      L.T("Quanto è grande una ripetizione dello sporco, in misure vere (non dipende dalle coordinate UV né dalle unità del modello). Puoi scrivere 250 (cm) o 2,5 m"));
            gs.Display = v => v >= 100 ? (v / 100).ToString(v >= 1000 ? "0.#" : "0.##") + " m" : v.ToString("0") + " cm";
            gs.Parse = t =>
            {
                t = t.Trim().ToLowerInvariant().Replace(',', '.');
                double k = 1;
                if (t.EndsWith("cm")) t = t[..^2];
                else if (t.EndsWith("m")) { t = t[..^1]; k = 100; }
                return double.TryParse(t.Trim(), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var x)
                    ? Math.Clamp(x * k, 5, 5000) : null;
            };
            gs.Refresh();
            // (1.71.0) another random placement of the stains, on every object with this material
            var seed = (int)D("grunge.seed", 0);
            var sb = Theme.Button(Theme.IconText(Icons.Refresh, seed == 0 ? L.T("Seme casuale") : L.F("Seme casuale ({0})", seed), null, 14), Theme.Kind.Ghost,
                L.T("Sposta le macchie in un punto a caso dello sporco: ogni clic una distribuzione diversa (Ctrl+Z torna alla precedente)"));
            sb.MinHeight = 28;
            sb.FontSize = 12;
            sb.HorizontalAlignment = HorizontalAlignment.Left;
            sb.Margin = new Thickness(0, 0, 0, 10);
            sb.Click += async (_, __) => await EditMat("grunge.seed", JsonValue.Create(Random.Shared.Next(1, 10000)));
            sp.Children.Add(sb);
            var a = Advanced(sp, "mat:grunge");
            MatColor(a.Body, L.T("Colore"), "grunge.color", L.T("Il colore dello sporco"));
            MatSlider(a.Body, L.T("Meno lucido"), "grunge.roughness", 0.3, 0, 100, false, "0", "%", L.T("Quanto lo sporco rende la superficie meno lucida"), 100);
            MatSlider(a.Body, L.T("Rilievo"), "grunge.relief", 0, 0, 100, false, "0", "%", L.T("Un leggero rilievo dello sporco (path tracing)"), 100);
            MatToggle(a.Body, L.T("Varia per oggetto"), "grunge.randomize", L.T("Lo sporco spostato a caso su ogni oggetto: oggetti uguali non hanno le stesse macchie"));
            MapRow(a.Body, L.T("Maschera"), "grunge.map", strength: false, channel: false);
            MapRow(a.Body, L.T("Texture colore"), "grunge.colorMap", strength: false, channel: false, invert: false);
            MapRow(a.Body, L.T("Normal map"), "grunge.normal", strength: false, channel: false, invert: false);
            if (S("grunge.normal.image") != "")
                MatSlider(a.Body, L.T("Forza normal"), "grunge.normalStrength", 0.5, 0, 200, false, "0", "%", L.T("Quanto il rilievo della normal map dello sporco si sente nella luce: 0% = sporco piatto, 100% = come la mappa, 200% = il doppio"), 100);
            a.Body.Children.Insert(a.Body.Children.Count, Note(L.T("Senza maschera usa lo sporco di Simpler; una maschera tua: bianco = sporco.")));
            DirtBrushControls(a.Body);
            a.Done(Diff(V3("grunge.color")[0], 0.09) || Diff(D("grunge.roughness", 0.3), 0.3) || Diff(D("grunge.relief", 0), 0) || !BoD("grunge.randomize", true)
                   || S("grunge.map.image") != "" || S("grunge.colorMap.image") != "" || S("grunge.normal.image") != "");
        }

        /// <summary>(1.76.6) «Variazione su grande scala»: for big surfaces (terrains, kilometres of ground), where a
        /// texture of a metre or two becomes a flat colour from afar - a slow change of tone and a large texture laid
        /// over the detail (its patterns, optionally its colour).</summary>
        void MacroSection()
        {
            var sp = Section(L.T("Variazione su grande scala"));
            MatSlider(sp, L.T("Variazione di tono"), "macro.tone", 0, 0, 100, false, "0", "%",
                      L.T("Chiaro e scuro, più e meno saturo, a macchie di decine di metri: una grande superficie non è mai di un colore solo. 0% = spenta"), 100);
            var big = S("macro.map.image") != "";
            if (big)
            {
                MatSlider(sp, L.T("Texture grande"), "macro.strength", 0, 0, 100, false, "0", "%",
                          L.T("Quanto si vedono le forme della texture grande (rocce che affiorano, chiazze di ghiaia) sopra il dettaglio"), 100);
                MatSlider(sp, L.T("Colore dalla texture grande"), "macro.colour", 0, 0, 100, false, "0", "%",
                          L.T("0% = il colore resta quello del materiale · 100% = il colore della texture grande, con la grana del dettaglio"), 100);
            }
            var a = Advanced(sp, "mat:macro");
            MapRow(a.Body, L.T("Texture grande"), "macro.map", strength: false, channel: false, invert: false);
            MapRow(a.Body, L.T("Normal map grande"), "macro.normal", strength: false, channel: false, invert: false);
            // (1.76.56, Luca: «manca "m" come unità di misura») in metres, with the unit beside the box like the others
            MatSlider(a.Body, L.T("Dimensione della texture grande"), "macro.sizeCm", 2000, 1, 200, true, "0.#", "m",
                      L.T("Quanto è grande una ripetizione della texture grande, in misure vere (le texture aeree di Poly Haven: 15-90 m)"), scale: 0.01);
            MatSlider(a.Body, L.T("Dimensione delle macchie di tono"), "macro.toneSizeM", 30, 2, 300, true, "0", "m",
                      L.T("Quanto sono grandi le macchie più chiare e più scure di «Variazione di tono», in metri: piccole per un prato a chiazze, grandi per un versante che cambia colore piano piano"));
            a.Done(big || Diff(D("macro.toneSizeM", 30), 30));
        }

        /// <summary>«Dipingi lo sporco» (1.70.0): the brush on any surface, three kinds of dirt, add or take away.</summary>
        void DirtBrushControls(StackPanel to)
        {
            var on = _puddleBrush && _brushLayer == "dirt";
            var pt = new Toggle(L.T("Dipingi lo sporco"), on,
                L.T("Dipingi lo sporco dove vuoi, su qualsiasi superficie (anche su altri materiali: il loro sporco dipinto si accende). Clic e trascina sulla vista · Maiusc toglie · [ e ] grandezza · Esc finisce"));
            pt.Margin = new Thickness(0, 10, 0, 0);
            pt.Toggled += v => { _puddleBrush = v; _brushLayer = "dirt"; SendPuddleBrush(); RenderProps(); };
            to.Children.Add(pt);
            if (on)
            {
                var grid = new System.Windows.Controls.Primitives.UniformGrid { Columns = 3, Margin = new Thickness(0, 8, -6, 2) };
                foreach (var (id, name, tip) in new[] {
                    ("uniforme", "Uniforme", "Sporco fine e uniforme"),
                    ("frastagliato", "Frastagliato", "Una macchia piena con il bordo frastagliato"),
                    ("macchie", "A macchie", "Macchie separate") })
                {
                    var pid = id;
                    grid.Children.Add(WeatherTile(WeatherIcon("dirt", id), null, L.T(name), _dirtPreset == id, L.T(tip),
                        () => { _dirtPreset = pid; SendPuddleBrush(); RenderProps(); return Task.CompletedTask; }));
                }
                to.Children.Add(grid);
                var seg = Theme.Segmented(out var segButtons, (L.T("Aggiungi"), L.T("Il pennello mette sporco")), (L.T("Togli"), L.T("Il pennello toglie lo sporco dipinto")));
                seg.HorizontalAlignment = HorizontalAlignment.Left;
                seg.Margin = new Thickness(0, 4, 0, 6);
                Theme.SetSegment(segButtons, _puddleMode == "remove" ? 1 : 0);
                for (int i = 0; i < segButtons.Count; i++)
                {
                    var idx = i;
                    segButtons[i].Click += (_, __) => { _puddleMode = idx == 1 ? "remove" : "add"; Theme.SetSegment(segButtons, idx); SendPuddleBrush(); };
                }
                to.Children.Add(seg);
                var rs = new ValueSlider(L.T("Grandezza pennello"), _dirtRadius * 100, 2, 500, true, "0", "cm", null, L.T("Il raggio del pennello ([ e ] sulla vista)"));
                rs.Changing += x => { _dirtRadius = x / 100; SendPuddleBrush(); };
                rs.Committed += x => { _dirtRadius = x / 100; SendPuddleBrush(); };
                to.Children.Add(rs);
                var ks = new ValueSlider(L.T("Forza"), _dirtStrength * 100, 5, 100, false, "0", "%", null, L.T("Quanto sporco mette ogni passata"));
                ks.Changing += x => { _dirtStrength = x / 100; SendPuddleBrush(); };
                ks.Committed += x => { _dirtStrength = x / 100; SendPuddleBrush(); };
                to.Children.Add(ks);
            }
            var clear = SmallButton(Icons.Trash, L.T("Cancella lo sporco dipinto"), async () =>
            {
                JsonObject? r = null;
                await Run(async api => { r = await api.Post("dirt/paint/clear", new JsonObject()); UpdateHistory(await api.Get("history")); });
                if (r == null) return;
                SendToWeb(new { type = "dirtPaint", info = (object?)null });
                Status(L.T("Sporco dipinto cancellato"));
            });
            clear.Margin = new Thickness(0, 6, 0, 0);
            clear.ToolTip = L.T("Toglie tutto lo sporco dipinto della scena (si annulla con Ctrl+Z)");
            to.Children.Add(clear);
        }

        /// <summary>A stroke of the dirt brush: the engine paints the maps (and turns on the painted dirt of the
        /// materials painted on), the view gets the new maps and those materials.</summary>
        async Task DirtStroke(JsonObject msg)
        {
            JsonObject? r = null;
            await Run(async api =>
            {
                r = await api.Post("dirt/paint", new JsonObject
                {
                    ["points"] = msg["points"]?.DeepClone(), ["radius"] = msg["radius"]?.DeepClone(), ["mode"] = msg["mode"]?.DeepClone(),
                    ["preset"] = msg["preset"]?.DeepClone(), ["strength"] = msg["strength"]?.DeepClone(), ["materials"] = msg["materials"]?.DeepClone(),
                });
                UpdateHistory(await api.Get("history"));
            });
            if (r == null) return;
            SendToWeb(new { type = "dirtPaint", info = r["info"]?.DeepClone() });
            var mats = (r["materials"] as JsonArray)?.Select(x => (string?)x ?? "").Where(x => x != "").ToList() ?? new List<string>();
            foreach (var m in mats) await PushMaterialToViewer(m);
            if (mats.Contains(_matName)) { await LoadMaterial(); RenderProps(); }
        }

        void RoughnessSection()
        {
            var sp = Section(L.T("Rugosità"));
            MatSlider(sp, L.T("Rugosità"), "roughness.value", 0.5, 0, 100, false, "0", "%", L.T("0% = specchio · 100% = completamente opaco"), 100);
            var a = Advanced(sp, "mat:roughness");
            MapRow(sp, L.T("Mappa"), "roughness.map", adv: a.Body, scale: true);
            sp.Children.Remove(a.Root); sp.Children.Add(a.Root);
            if (S("roughness.map.image") != "")
                MatToggle(a.Body, L.T("È una mappa di lucentezza (glossy)"), "roughness.glossy", L.T("Le mappe glossy sono l'inverso di quelle di rugosità: bianco = lucido"));
            a.Done(MapChanged("roughness.map") || (S("roughness.map.image") != "" && Bo("roughness.glossy")));
        }

        void MetallicSection()
        {
            var sp = Section(L.T("Metallico"));
            MatSlider(sp, L.T("Metallico"), "metallic.value", 0, 0, 100, false, "0", "%", L.T("100% = metallo · 0% = tutto il resto"), 100);
            var a = Advanced(sp, "mat:metallic");
            MapRow(sp, L.T("Mappa"), "metallic.map", adv: a.Body, scale: true);
            sp.Children.Remove(a.Root); sp.Children.Add(a.Root);
            a.Done(MapChanged("metallic.map"));
        }

        void ReliefSection()
        {
            var sp = Section(L.T("Rilievo"));
            var a = Advanced(sp, "mat:relief");
            MapRow(sp, L.T("Normal map"), "normal.map", strength: false, channel: false, invert: false, adv: a.Body, scale: true);
            sp.Children.Remove(a.Root);
            if (S("normal.map.image") != "")
                MatSlider(sp, L.T("Intensità"), "normal.strength", 1, 0, 300, false, "0", "%", L.T("Quanto si sente il rilievo della normal map nella luce: 0% = superficie liscia, 100% = come la mappa, oltre = più marcato"), 100);
            sp.Children.Add(a.Root);
            if (S("normal.map.image") != "")
                MatToggle(a.Body, L.T("Formato DirectX"), "normal.directx", L.T("Acceso per le normal map DirectX (il verde è invertito); spento per OpenGL"), false);
            MapRow(a.Body, L.T("Bump"), "normal.bumpMap", strength: false, scale: true);
            if (S("normal.bumpMap.image") != "")
            {
                MatSlider(a.Body, L.T("Intensità bump"), "normal.bump", 0, 0, 100, false, "0", "%", L.T("Quanto si sente il rilievo della mappa bump (in bianco e nero) nella luce: 0% = spento, 100% = il massimo"), 100);
                MatSlider(a.Body, L.T("Profondità"), "normal.bumpDistanceMm", 1, 0.01, 100, true, "0.##", "mm", L.T("Altezza del rilievo simulato"));
            }
            a.Done((S("normal.map.image") != "" && (Bo("normal.directx") || Diff(D("normal.map.scale", 1), 1))) || S("normal.bumpMap.image") != "");
        }

        void ReflectionSection()
        {
            var sp = Section(L.T("Riflessi e vernice"));
            MatSlider(sp, L.T("Vernice (clearcoat)"), "coat.weight", 0, 0, 100, false, "0", "%", L.T("Strato trasparente lucido sopra il materiale: auto, lacche, ceramiche"), 100);
            var a = Advanced(sp, "mat:reflection");
            MatSlider(a.Body, L.T("Riflesso"), "specular", 0.5, 0, 100, false, "0", "%", L.T("Quanto riflette un materiale non metallico (50% = normale)"), 100);
            if (D("coat.weight") > 0)
                MatSlider(a.Body, L.T("Rugosità vernice"), "coat.roughness", 0.03, 0, 100, false, "0", "%", L.T("Quanto è opaca la vernice trasparente sopra il materiale: 0% = lucida come uno specchio, 100% = satinata"), 100);
            // «Con la pioggia» (engine rain.py, DROPS_KEY): the drops lying on this material when it rains
            var rdl = new TextBlock { Text = L.T("Con la pioggia"), FontSize = 12, Foreground = Theme.B(Theme.TextMuted), Margin = new Thickness(0, 8, 0, 4) };
            a.Body.Children.Add(rdl);
            var modes = new[] { "auto", "on", "off" };
            var rds = Theme.Segmented(out var rdb,
                (L.T("Automatico"), L.T("Gocce sui materiali lisci (vernici, vetri, metalli, plastiche); pietra, legno e tessuti si bagnano soltanto")),
                (L.T("Gocce"), L.T("Sempre le gocce posate, anche se il materiale è ruvido")),
                (L.T("Niente gocce"), L.T("Mai gocce posate su questo materiale: si bagna soltanto")));
            rds.HorizontalAlignment = HorizontalAlignment.Left;
            Theme.SetSegment(rdb, Math.Max(0, Array.IndexOf(modes, (string?)_matInfo["rainDrops"] ?? "auto")));
            for (int i = 0; i < rdb.Count; i++)
            {
                var md = modes[i];
                rdb[i].Click += async (_, __) => await SetMaterialRainDrops(md);
            }
            a.Body.Children.Add(rds);
            a.Done(Diff(D("specular", 0.5), 0.5) || (D("coat.weight") > 0 && Diff(D("coat.roughness", 0.03), 0.03))
                   || ((string?)_matInfo["rainDrops"] ?? "auto") != "auto");
        }

        // the types of material (D5 templates): id, name, description, icon, colour of the icon
        static readonly (string id, string name, string desc, Geometry icon, Color color)[] MaterialTypes =
        {
            ("standard", "Standard", "Materiale fisico con tutti i canali: colore, rugosità, metallo, rilievo, vetro, tessuto, emissione", Icons.MatStandard, Theme.C("#C9D3E4")),
            ("water", "Acqua", "Trasparente, con onde vere, colore con la profondità, limpidezza e torbidità: il pannello mostra solo questi", Icons.WaterDrop, Theme.C("#4FB6E8")),
            ("displacement", "Displacement", "La superficie si sposta davvero con la mappa di altezza (sassi, mattoni, cortecce, terreni), con tutti i canali dello Standard", Icons.Relief, Theme.C("#D9A066")),
            ("foliage", "Fogliame", "Foglie, aghi, petali e il legno delle piante: luce attraverso la foglia, ogni pianta un po' diversa e la stagione, dal verde all'autunno fino all'inverno senza foglie", Icons.Leaf, Theme.C("#7CC46A")),
            ("fabric", "Tessuto", "Stoffe e tessili: pieno (velluto, lana, cotone, jeans) con la peluria, o sottile (tende, tulle, garza) che lascia vedere e passare la luce", Icons.Cloth, Theme.C("#C79BD9")),
            ("interior", "Interni", "Per i vetri delle finestre di edifici e vetrine: dietro ogni finestra compare una stanza con la sua profondità, senza modellarla. Per facce piatte: sulle superfici curve le stanze si deformano", Icons.Grid, Theme.C("#E8C468")),
            ("volumetric", "Volumetrico", "Il modello si riempie di nuvola, fumo, nebbia, vapore, polvere o fuoco: la superficie sparisce e resta il volume, con bordi morbidi e sbuffi", Icons.Cloud, Theme.C("#B8C7DD")),
        };

        static Border TypeBadge(Geometry icon, Color color, double size = 26) => new Border
        {
            Width = size, Height = size, CornerRadius = new CornerRadius(7), VerticalAlignment = VerticalAlignment.Center,
            Background = new SolidColorBrush(Color.FromArgb(0x33, color.R, color.G, color.B)),
            Child = Theme.Icon(icon, color, size * 0.62),
        };

        /// <summary>A drop-down list of the material types (icon, name, what it is for): it decides which controls the panel shows.</summary>
        UIElement MaterialTypePicker(string curId)
        {
            var cur = MaterialTypes.First(x => x.id == curId);
            var face = new DockPanel { LastChildFill = true };
            var chev = Theme.Icon(Icons.ChevronDown, Theme.TextMuted, 14);
            chev.Margin = new Thickness(10, 0, 0, 0);
            DockPanel.SetDock(chev, Dock.Right);
            face.Children.Add(chev);
            var badge = TypeBadge(cur.icon, cur.color, 22);
            DockPanel.SetDock(badge, Dock.Left);
            face.Children.Add(badge);
            face.Children.Add(new TextBlock { Text = L.T(cur.name), FontSize = 13, FontWeight = FontWeights.SemiBold, Foreground = Theme.B(Theme.Text),
                                              VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(8, 0, 0, 0) });
            var btn = Theme.Button(face, Theme.Kind.Normal, L.T("Tipo di materiale: decide quali parametri vedi nel pannello"));
            btn.HorizontalContentAlignment = HorizontalAlignment.Stretch;
            btn.MinWidth = 190; btn.MinHeight = 34; btn.Padding = new Thickness(6, 0, 10, 0);
            btn.HorizontalAlignment = HorizontalAlignment.Left;
            btn.Click += (_, __) =>
            {
                var cm = new ContextMenu { PlacementTarget = btn, Placement = System.Windows.Controls.Primitives.PlacementMode.Bottom };
                foreach (var ty in MaterialTypes)
                {
                    var row = new DockPanel { Margin = new Thickness(0, 4, 0, 4) };
                    var bdg = TypeBadge(ty.icon, ty.color, 30);
                    bdg.Margin = new Thickness(0, 0, 10, 0);
                    DockPanel.SetDock(bdg, Dock.Left);
                    row.Children.Add(bdg);
                    var txt = new StackPanel { VerticalAlignment = VerticalAlignment.Center };
                    txt.Children.Add(new TextBlock { Text = L.T(ty.name) + (ty.id == cur.id ? "  ✓" : ""), FontSize = 13, FontWeight = FontWeights.SemiBold, Foreground = Theme.B(Theme.Text) });
                    txt.Children.Add(new TextBlock { Text = L.T(ty.desc), FontSize = 11.5, Foreground = Theme.B(Theme.TextFaint), TextWrapping = TextWrapping.Wrap, MaxWidth = 260 });
                    row.Children.Add(txt);
                    var mi = new MenuItem { Header = row };
                    var id = ty.id;
                    mi.Click += async (_, __) => await SetMaterialType(curId, id);
                    cm.Items.Add(mi);
                }
                cm.IsOpen = true;
            };
            return btn;
        }

        /// <summary>Changes the type: water is a property of the material (water.py), displacement its "displacement.enabled".</summary>
        async Task SetMaterialType(string from, string to)
        {
            if (from == to) return;
            if (from == "water") await SetMaterialWater(new JsonObject { ["on"] = false });
            if (from == "volumetric") await SetMaterialVolume(new JsonObject { ["on"] = false });
            if (to == "volumetric") await SetMaterialVolume(new JsonObject { ["on"] = true });
            if (from == "displacement") await EditMat(new JsonObject { ["displacement"] = new JsonObject { ["enabled"] = false } }, true);
            if (from == "foliage") await EditMat(new JsonObject { ["foliage"] = new JsonObject { ["enabled"] = false } }, true);
            if (to == "foliage") await EditMat(new JsonObject { ["foliage"] = new JsonObject { ["enabled"] = true } }, true);
            if (from == "fabric") await EditMat(new JsonObject { ["fabric"] = new JsonObject { ["enabled"] = false } }, true);
            if (from == "interior") await EditMat(new JsonObject { ["interior"] = new JsonObject { ["enabled"] = false } }, true);
            if (to == "interior")
            {
                // (1.79.0) a dark glass with sharp reflections in front of the rooms; no transparency (the room is the picture)
                await EditMat(new JsonObject
                {
                    ["interior"] = new JsonObject { ["enabled"] = true },
                    ["color"] = new JsonObject { ["tint"] = new JsonArray(0.02, 0.02, 0.02) },
                    ["roughness"] = new JsonObject { ["value"] = 0.04 },
                    ["metallic"] = new JsonObject { ["value"] = 0.0 },
                    ["transmission"] = new JsonObject { ["weight"] = 0.0 },
                }, true);
            }
            if (to == "fabric")
            {
                // a cloth with no fuzz at all would look like plastic: some to start with (the user's value kept if set)
                var patch = new JsonObject { ["fabric"] = new JsonObject { ["enabled"] = true } };
                if (D("sheen.weight") <= 0) patch["sheen"] = new JsonObject { ["weight"] = 0.5 };
                await EditMat(patch, true);
            }
            if (to == "water") await SetMaterialWater(new JsonObject { ["on"] = true });
            if (to == "displacement")
            {
                await DispEdit("displacement.enabled", JsonValue.Create(true));
                if (S("displacement.map.image") == "" && S("displacement.vector.image") == "")
                    Status(L.T("Displacement: scegli la mappa di altezza nel gruppo Rilievo vero"));
            }
            _ = RequestLivePreview();
        }

        /// <summary>
        /// "Acqua": a property of the material (every object with it is water). On: the material becomes a clear water
        /// (transparency 100%, index 1.333; then it can be changed like any material), with real waves (geometry, for
        /// the caustics) and the body of the water (colour with depth, clarity, murk). Engine: water.py.
        /// The caustics themselves are a render setting: Rendering → Caustiche.
        /// </summary>
        async Task SetMaterialRainDrops(string mode)
        {
            await EnsureOwnCopy();
            await Run(async api => { await api.Post("material/raindrops", new JsonObject { ["name"] = _matName, ["mode"] = mode }); UpdateHistory(await api.Get("history")); });
            await LoadMaterial();
            RenderProps();
            await PushMaterialToViewer(_matName);
        }

        async Task SetMaterialWater(JsonObject body)
        {
            await EnsureOwnCopy();
            body["name"] = _matName;
            await Run(async api => { await api.Post("material/water", body); UpdateHistory(await api.Get("history")); });
            await LoadMaterial();
            RenderProps();
            await RefreshScene();
            await PushMaterialToViewer(_matName);
            if (body.ContainsKey("on")) _ = RequestLivePreview();     // the sphere shows the new type (water: transparent)
        }

        /// <summary>
        /// "Volumetrico": a property of the material (every object with it is filled): the surface disappears, the
        /// inside becomes fog, smoke, cloud, steam, dust or fire. Engine: volumetric.py; view: viewer.js volMaterial.
        /// </summary>
        async Task SetMaterialVolume(JsonObject body)
        {
            await EnsureOwnCopy();
            body["name"] = _matName;
            await Run(async api => { await api.Post("material/volumetric", body); UpdateHistory(await api.Get("history")); });
            await LoadMaterial();
            RenderProps();
            await RefreshScene();
            await PushMaterialToViewer(_matName);
            _ = RequestLivePreview();
        }

        static readonly (string id, string label, string tip)[] VolumePresets =
        {
            ("nuvola", "Nuvola", "Bianca e densa, con sbuffi grandi"),
            ("fumo", "Fumo", "Grigio, assorbe la luce, sbuffi piccoli"),
            ("nebbia", "Banco di nebbia", "Leggera, bordi molto morbidi: su un parallelepipedo basso diventa un banco di nebbia"),
            ("vapore", "Vapore", "Bianco, leggero, sfilacciato"),
            ("polvere", "Polvere", "Sabbia o terra sollevata, color sabbia"),
            ("fuoco", "Fuoco", "Brilla di luce propria, più forte al centro: illumina la scena"),
        };

        void VolumeSection()
        {
            var v = _matInfo["volumetric"] as JsonObject;
            if (v == null) return;
            Task Set(JsonObject body) => SetMaterialVolume(body);
            double Dv(string k, double d) => (double?)v[k] ?? d;
            double[] Cv(string k, double[] d) => v[k] is JsonArray a && a.Count >= 3 ? new[] { (double?)a[0] ?? d[0], (double?)a[1] ?? d[1], (double?)a[2] ?? d[2] } : d;

            var ps = Section(L.T("Tipo di volume"));
            if (v["open"] is JsonArray open && open.Count > 0)
            {
                // a model that is not closed (open pieces, a cloud made of small discs): it has no inside of its own
                var w = Theme.Label(L.F("Modello non chiuso ({0}): non ha un dentro da riempire, così Simpler avvolge i suoi pezzi in una forma morbida e riempie quella. Per una forma precisa usa un modello chiuso.",
                    string.Join(", ", open.Take(3).Select(x => (string?)x ?? ""))), 11.5, Theme.Warm);
                w.TextWrapping = TextWrapping.Wrap; w.Margin = new Thickness(0, 0, 0, 8);
                ps.Children.Add(w);
            }
            var wrap = new WrapPanel { Margin = new Thickness(0, 0, 0, 6) };
            var cur = (string?)v["preset"] ?? "custom";
            foreach (var (id, label, tip) in VolumePresets)
            {
                var b = Theme.Button(L.T(label), id == cur ? Theme.Kind.Primary : Theme.Kind.Ghost, L.T(tip));
                b.MinHeight = 26; b.FontSize = 12; b.Padding = new Thickness(9, 0, 9, 0); b.Margin = new Thickness(0, 0, 4, 4);
                var pid = id;
                b.Click += async (_, __) => await Set(new JsonObject { ["preset"] = pid });
                wrap.Children.Add(b);
            }
            ps.Children.Add(wrap);
            ps.Children.Add(Note(L.T("Un tipo imposta tutti i valori qui sotto; poi puoi cambiarli. Funziona su modelli chiusi: una sfera diventa una nuvola, tre sfere una colonna di fumo, un parallelepipedo basso un banco di nebbia.")));

            var ls = Section(L.T("Aspetto"));
            var vis = new ValueSlider(L.T("Visibilità"), Dv("visibility", 0.8), 0.05, 500, true, "0.##", "m", null,
                L.T("Attraverso quanti metri non si vede più dall'altra parte: poco = denso (fumo, nuvola), tanto = leggero (nebbia). Vale per il centro del volume"));
            vis.Committed += async x => await Set(new JsonObject { ["visibility"] = x });
            ls.Children.Add(vis);
            var col = new ColorField(L.T("Colore"), Cv("color", new[] { 1.0, 1.0, 1.0 }), L.T("Il colore della luce che il volume diffonde: bianco per nuvole e vapore, grigio per il fumo, sabbia per la polvere"));
            col.Committed += async c => await Set(new JsonObject { ["color"] = new JsonArray(c[0], c[1], c[2]) });
            ls.Children.Add(col);
            var soft = new ValueSlider(L.T("Morbidezza bordi"), Dv("soft", 0.6) * 100, 0, 100, false, "0", "%",
                null, L.T("Quanto il volume sfuma verso la superficie del modello: 0% = bordo netto, 100% = sfuma fino al centro"));
            soft.Committed += async x => await Set(new JsonObject { ["soft"] = x / 100 });
            ls.Children.Add(soft);
            var puffs = new ValueSlider(L.T("Sbuffi"), Dv("puffs", 0.6) * 100, 0, 100, false, "0", "%",
                null, L.T("Quanto il bordo è mangiato a sbuffi: 0% = forma liscia del modello, 100% = tutto a sbuffi"));
            puffs.Committed += async x => await Set(new JsonObject { ["puffs"] = x / 100 });
            ls.Children.Add(puffs);
            var gs = new ValueSlider(L.T("Grandezza sbuffi"), Dv("puffRel", 0.12) * 100, 1, 100, true, "0", "%",
                null, L.T("Quanto sono grandi gli sbuffi rispetto al modello (al suo lato più lungo): 10-15% per una nuvola a cumulo, di più per fumo e nebbia morbidi. Vale per qualunque grandezza: una nuvola di 6 m e una di 100 m con lo stesso valore hanno lo stesso aspetto"));
            gs.Committed += async x => await Set(new JsonObject { ["puffRel"] = x / 100 });
            ls.Children.Add(gs);

            var es = Section(L.T("Luce propria (fuoco)"));
            var em = new ValueSlider(L.T("Bagliore"), Dv("emission", 0), 0, 500, true, "0.#", null,
                null, L.T("0 = spento. Il volume brilla di luce propria, più forte al centro, e illumina la scena: fuoco, braci, bagliori"));
            em.Committed += async x => await Set(new JsonObject { ["emission"] = x });
            es.Children.Add(em);
            if (Dv("emission", 0) > 0)
            {
                var ec = new ColorField(L.T("Colore della luce"), Cv("emitColor", new[] { 1.0, 0.42, 0.08 }), L.T("Arancio per il fuoco, rosso per le braci"));
                ec.Committed += async c => await Set(new JsonObject { ["emitColor"] = new JsonArray(c[0], c[1], c[2]) });
                es.Children.Add(ec);
            }

            var adv = Advanced(ls, "mat:volume");
            var ab = new ValueSlider(L.T("Assorbimento"), Dv("absorb", 0) * 100, 0, 100, false, "0", "%",
                null, L.T("Quanta luce il volume mangia invece di diffonderla: 0% = nuvola bianca, alto = fumo scuro"));
            ab.Committed += async x => await Set(new JsonObject { ["absorb"] = x / 100 });
            adv.Body.Children.Add(ab);
            var an = new ValueSlider(L.T("Direzione della luce"), Dv("aniso", 0.4) * 100, -90, 90, false, "0", "%",
                null, L.T("Positivo: la luce passa in avanti (controluce luminoso, come nuvole e nebbia). Negativo: torna indietro. 0 = uguale in tutte le direzioni"));
            an.Committed += async x => await Set(new JsonObject { ["aniso"] = x / 100 });
            adv.Body.Children.Add(an);
            var dt = new ValueSlider(L.T("Dettaglio"), Dv("detail", 0.5) * 100, 0, 100, false, "0", "%",
                null, L.T("Quanto sono fini forma e sbuffi nel rendering: più alto = più preciso, più lento e più memoria"));
            dt.Committed += async x => await Set(new JsonObject { ["detail"] = x / 100 });
            adv.Body.Children.Add(dt);
            var sd = new ValueSlider(L.T("Variante"), Dv("seed", 0), 0, 99, false, "0", null,
                null, L.T("Un'altra disposizione degli sbuffi, a parità di tutto il resto"));
            sd.Committed += async x => await Set(new JsonObject { ["seed"] = Math.Round(x) });
            adv.Body.Children.Add(sd);
            var rb = new ValueSlider(L.T("Rimbalzi della luce"), Dv("bounces", 4), 1, 32, false, "0", null,
                null, L.T("Quante volte la luce rimbalza dentro il volume, uguale nell'anteprima e nel rendering finale. Pochi (4, veloce): l'interno di una nuvola resta scuro e bluastro. Di più: più luminoso e naturale, ma più lento"));
            rb.Committed += async x => await Set(new JsonObject { ["bounces"] = Math.Round(x) });
            adv.Body.Children.Add(rb);
            if (Dv("bounces", 4) > 12)
            {
                var wb = Theme.Label(L.T("Molti rimbalzi: l'anteprima e il rendering diventano più lenti, soprattutto con volumi densi."), 11.5, Theme.Warm);
                wb.TextWrapping = TextWrapping.Wrap; wb.Margin = new Thickness(0, 0, 0, 6);
                adv.Body.Children.Add(wb);
            }
            adv.Done(Math.Abs(Dv("absorb", 0)) > 0.001 || Math.Abs(Dv("detail", 0.5) - 0.5) > 0.001 || Dv("seed", 0) > 0 || Math.Abs(Dv("bounces", 4) - 4) > 0.1);
            if ((bool?)v["heavy"] ?? false)
            {
                var w = Theme.Label(L.T("Volume pesante: molti voxel nel rendering. Abbassa il Dettaglio o la grandezza del modello se il rendering rallenta troppo."), 11.5, Theme.Warm);
                w.TextWrapping = TextWrapping.Wrap; w.Margin = new Thickness(0, 4, 0, 0);
                ls.Children.Add(w);
            }
            ls.Children.Add(Note(L.T("Pioggia e neve non toccano i volumi. Nella vista in tempo reale il volume è più leggero (meno passi mentre muovi la vista): sagoma e colore sono gli stessi, gli sbuffi simili.")));
        }

        void WaterSection()
        {
            var w = _matInfo["water"] as JsonObject;
            if (w == null) return;
            JsonObject Sub(string k) => w[k] as JsonObject ?? new JsonObject();
            Task Set(JsonObject body) => SetMaterialWater(body);

            // colour and depth (D5: base colour + depth)
            var cs = Section(L.T("Colore e profondità"));
            var bd = Sub("body");
            bool bon = (bool?)bd["on"] ?? true;
            var bt = new Toggle(L.T("Colore e limpidezza (volume)"), bon, L.T("L'acqua vera assorbe la luce: diventa azzurra o verde con la profondità e si vela con la distanza, anche vista da sott'acqua. Costa circa il 20-40% in più (di più se torbida), per questo si può spegnere"));
            bt.Toggled += async v => await Set(new JsonObject { ["body"] = new JsonObject { ["on"] = v } });
            cs.Children.Add(bt);
            if (bon)
            {
                var ids = new[] { "piscina", "lago", "mare", "palude" };
                var seg = Theme.Segmented(out var cb, (L.T("Piscina"), L.T("Azzurra: la piastrella resta chiara")), (L.T("Lago"), L.T("Verde-azzurra")), (L.T("Mare"), L.T("Blu profondo")), (L.T("Palude"), L.T("Verde-bruna")));
                Theme.SetSegment(cb, Math.Max(0, Array.IndexOf(ids, (string?)bd["color"] ?? "piscina")));
                for (int i = 0; i < cb.Count; i++)
                {
                    var id = ids[i];
                    cb[i].Click += async (_, __) => await Set(new JsonObject { ["body"] = new JsonObject { ["color"] = id } });
                }
                seg.Margin = new Thickness(0, 4, 0, 8);
                seg.HorizontalAlignment = HorizontalAlignment.Left;
                cs.Children.Add(seg);
                var cl = new ValueSlider(L.T("Limpidezza"), (double?)bd["clarity"] ?? 25, 1, 200, true, "0.#", "m", null, L.T("Distanza a cui l'acqua vela circa due terzi della luce: piscina 20-40 m, lago 5-15 m, acqua torbida 1-3 m"));
                cl.Committed += async v => await Set(new JsonObject { ["body"] = new JsonObject { ["clarity"] = v } });
                cs.Children.Add(cl);
                var mk = new ValueSlider(L.T("Torbidità"), ((double?)bd["murk"] ?? 0) * 100, 0, 100, false, "0", "%", null, L.T("Quanta parte del velo è lattiginosa (particelle in sospensione che diffondono la luce) invece che scura. Più torbida: più lenta"));
                mk.Committed += async v => await Set(new JsonObject { ["body"] = new JsonObject { ["murk"] = v / 100 } });
                cs.Children.Add(mk);
            }

            // surface (D5: normal = waves, refraction = IOR)
            var ss = Section(L.T("Superficie e onde"));
            if (((int?)w["shells"] ?? 0) > 0)
                ss.Children.Add(Hint(L.T("Su un oggetto aperto con pareti (un bicchiere senza coperchio, un vaso) l'acqua è solo la sua superficie trasparente: onde vere e colore in profondità valgono per superfici piane d'acqua e per pezzi chiusi.")));
            var wv = Sub("waves");
            bool won = (bool?)wv["on"] ?? true;
            double hh = (double?)wv["height"] ?? 0.08, wsz = (double?)wv["size"] ?? 0.6;
            // (1.75.0) one choice: how the water moves. Height and size come with it, already right for each other
            // (higher than a fifth of their size they would be spikes); the two sliders and the switch stay in the
            // Avanzate for whoever wants them. Not water that is still: the caustics come on by themselves.
            var presets = WaterPresets;
            int cur = won ? Array.FindIndex(presets, p => p.on && Math.Abs(p.h - hh) < 1e-4 && Math.Abs(p.s - wsz) < 1e-4) : 0;
            var wseg = Theme.Segmented(out var pb, presets.Select(p => ((object)L.T(p.label), (string?)L.T(p.tip))).ToArray());
            Theme.SetSegment(pb, cur);
            for (int pi = 0; pi < pb.Count; pi++)
            {
                var pr = presets[pi];
                pb[pi].Click += async (_, __) =>
                {
                    await Set(new JsonObject { ["waves"] = new JsonObject { ["on"] = pr.on, ["height"] = pr.h, ["size"] = pr.s } });
                    if (pr.on) await CausticsForWater();
                };
            }
            wseg.Margin = new Thickness(0, 2, 0, 6);
            ss.Children.Add(Row(L.T("Acqua"), wseg));
            if (cur < 0)
                ss.Children.Add(Note(L.F("Onde personalizzate: {0} cm alte, {1} cm l'una dall'altra (Avanzate).", (hh * 100).ToString("0.#"), (wsz * 100).ToString("0"))));
            var eff = (double?)w["effectiveHeight"];
            if (won && eff != null && eff < hh * 0.95)
            {
                // short, and what to do: the reason comes from the engine (water.editor_info)
                var effTxt = (eff.Value * 100).ToString("0.#");
                ss.Children.Add(Note((string?)w["waveLimit"] == "size"
                    ? L.F("Onde ridotte a {0} cm: la superficie d'acqua è troppo grande ({1} m) per disegnarle. Riducila all'area che serve, o aumenta la Dimensione.", effTxt, ((double?)w["span"] ?? 0).ToString("0"))
                    : L.F("Onde ridotte a {0} cm: più alte di un quinto della Dimensione diventerebbero punte. Per onde più alte aumenta la Dimensione.", effTxt)));
            }
            MatSlider(ss, L.T("Indice di rifrazione"), "transmission.ior", 1.333, 1.0, 2.0, false, "0.000", null, L.T("1,333 acqua dolce · 1,34 acqua di mare"));
            ss.Children.Add(Note(CausticsAny()
                ? L.T("Caustiche accese (Rendering → Caustiche): con le onde vere il sole disegna la rete di luce sul fondale.")
                : L.T("Per la rete di luce sul fondale accendi le caustiche in Rendering → Caustiche «Attive».")));
            ss.Children.Add(Note(L.T("Sul fondo e sui bordi dell'acqua serve un oggetto vero (vasca, terreno): l'acqua ne prende il colore con la profondità.")));

            // ice (engine ice.py): while it snows the water freezes from the shore inwards
            var adv = Advanced(ss, "water");
            var wt = new Toggle(L.T("Onde vere"), won, L.T("La superficie diventa ondulata davvero (solo nel path tracing: la vista in tempo reale resta piatta). Le onde fanno da lenti: con le caustiche il sole disegna sul fondale la rete di luce. Su un oggetto chiuso (sfera, vasca, bicchiere) le onde sono solo sulla parte di sopra"));
            wt.Toggled += async v => await Set(new JsonObject { ["waves"] = new JsonObject { ["on"] = v } });
            adv.Body.Children.Add(wt);
            if (won)
            {
                var h = new ValueSlider(L.T("Altezza onde"), hh * 100, 0, 50, false, "0.#", "cm", null, L.T("Dal cavo alla cresta. Più alte: rete di luce più marcata e più vicina alla superficie"));
                h.Committed += async v => await Set(new JsonObject { ["waves"] = new JsonObject { ["height"] = v / 100 } });
                adv.Body.Children.Add(h);
                var sz = new ValueSlider(L.T("Dimensione onde"), wsz * 100, 10, 500, true, "0", "cm", null, L.T("Distanza tra un'onda e l'altra. Piccole: increspature; grandi: onde lente. Per un fondale a circa 1 m: 40-80 cm"));
                sz.Committed += async v => await Set(new JsonObject { ["waves"] = new JsonObject { ["size"] = v / 100 } });
                adv.Body.Children.Add(sz);
            }
            var ic = Sub("ice");
            bool ion = (bool?)ic["on"] ?? false;
            var it = new Toggle(L.T("Ghiaccia quando nevica"), ion, L.T("Con la neve l'acqua gela dalla riva verso il centro: ghiaccio con crepe, una spolverata di neve, le onde si calmano"));
            it.Toggled += async v => await Set(new JsonObject { ["ice"] = new JsonObject { ["on"] = v } });
            adv.Body.Children.Add(it);
            double Iv(string k, double d) => (double?)ic[k] ?? d;
            if (ion)
            {
                var am = new ValueSlider(L.T("Ghiaccio"), Iv("amount", 0.5) * 100, 0, 100, false, "0", "%", null,
                    L.T("Dalla riva verso il centro: pochi % una cornice sottile lungo le rive, 100% tutta la superficie"));
                am.Committed += async v => await Set(new JsonObject { ["ice"] = new JsonObject { ["amount"] = v / 100 } });
                adv.Body.Children.Add(am);
                var cl = new ValueSlider(L.T("Trasparenza del ghiaccio"), Iv("clear", 0.6) * 100, 0, 100, false, "0", "%", null,
                    L.T("100%: ghiaccio nero, limpido e liscio, si vede il fondo. 0%: lattiginoso, più chiaro e ruvido"));
                cl.Committed += async v => await Set(new JsonObject { ["ice"] = new JsonObject { ["clear"] = v / 100 } });
                adv.Body.Children.Add(cl);
                var bb = new ValueSlider(L.T("Bolle d'aria"), Iv("bubbles", 0.3) * 100, 0, 100, false, "0", "%", null,
                    L.T("Aria intrappolata nel ghiaccio: puntini chiari a gruppi sotto la superficie (solo nel path tracing)"));
                bb.Committed += async v => await Set(new JsonObject { ["ice"] = new JsonObject { ["bubbles"] = v / 100 } });
                adv.Body.Children.Add(bb);
                var cg = new ValueSlider(L.T("Crepe grandi"), Iv("cracks", 1) * 100, 0, 200, false, "0", "%", null,
                    L.T("La rete di crepe tra le lastre grandi (circa 3 m): 0% nessuna, 100% normale, 200% più marcate (solo nel path tracing)"));
                cg.Committed += async v => await Set(new JsonObject { ["ice"] = new JsonObject { ["cracks"] = v / 100 } });
                adv.Body.Children.Add(cg);
                var cf = new ValueSlider(L.T("Crepe sottili"), Iv("cracksFine", 1) * 100, 0, 200, false, "0", "%", null,
                    L.T("Le crepe fini dentro le lastre (circa 80 cm): 0% nessuna, 100% normale, 200% più marcate (solo nel path tracing)"));
                cf.Committed += async v => await Set(new JsonObject { ["ice"] = new JsonObject { ["cracksFine"] = v / 100 } });
                adv.Body.Children.Add(cf);
                if (!((bool?)w["snowing"] ?? false))
                    adv.Body.Children.Add(Note(L.T("Si vede quando nevica (Ambiente → Neve).")));
            }
            // the rings of the rain (engine ripples.py): while the drops fall, circles on the water that faces up
            adv.Body.Children.Add(new Border { Height = 1, Background = Theme.B(Theme.Line), Margin = new Thickness(0, 10, 0, 10) });
            var rg = Sub("rings");
            double Rv(string k, double d) => (double?)rg[k] ?? d;
            bool ron = (bool?)rg["on"] ?? true;
            var rt = new Toggle(L.T("Cerchi della pioggia"), ron, L.T("Mentre cadono le gocce, sull'acqua rivolta verso l'alto si aprono i cerchi della pioggia; non sotto le tettoie"));
            rt.Toggled += async v => await Set(new JsonObject { ["rings"] = new JsonObject { ["on"] = v } });
            adv.Body.Children.Add(rt);
            if (ron)
            {
                var ra = new ValueSlider(L.T("Quantità di cerchi"), Rv("amount", 0.5) * 100, 0, 100, false, "0", "%", null,
                    L.T("Quanti cerchi insieme; crescono anche con l'intensità della pioggia"));
                ra.Committed += async v => await Set(new JsonObject { ["rings"] = new JsonObject { ["amount"] = v / 100 } });
                adv.Body.Children.Add(ra);
                var rs = new ValueSlider(L.T("Dimensione dei cerchi"), Rv("size", 0.5) * 100, 0, 100, false, "0", "%", null,
                    L.T("Da cerchi piccoli e fitti (fino a circa 10 cm di diametro) a grandi e radi (fino a circa 45 cm)"));
                rs.Committed += async v => await Set(new JsonObject { ["rings"] = new JsonObject { ["size"] = v / 100 } });
                adv.Body.Children.Add(rs);
                var rf = new ValueSlider(L.T("Forza dei cerchi"), Rv("strength", 1) * 100, 0, 200, false, "0", "%", null,
                    L.T("Quanto sono marcate le creste: 0% piatte, 200% molto evidenti"));
                rf.Committed += async v => await Set(new JsonObject { ["rings"] = new JsonObject { ["strength"] = v / 100 } });
                adv.Body.Children.Add(rf);
                if (!((bool?)w["raining"] ?? false))
                    adv.Body.Children.Add(Note(L.T("Si vedono quando cadono le gocce (Ambiente → Pioggia → Avanzate).")));
            }
            bool ringsChanged = !ron || Math.Abs(Rv("amount", 0.5) - 0.5) > 1e-3 || Math.Abs(Rv("size", 0.5) - 0.5) > 1e-3 || Math.Abs(Rv("strength", 1) - 1) > 1e-3;
            adv.Done(ion || Math.Abs(Iv("amount", 0.5) - 0.5) > 1e-3 || Math.Abs(Iv("clear", 0.6) - 0.6) > 1e-3 || Math.Abs(Iv("bubbles", 0.3) - 0.3) > 1e-3
                     || Math.Abs(Iv("cracks", 1) - 1) > 1e-3 || Math.Abs(Iv("cracksFine", 1) - 1) > 1e-3 || ringsChanged,
                     async () => await Set(new JsonObject { ["ice"] = new JsonObject { ["on"] = false, ["amount"] = 0.5, ["clear"] = 0.6, ["bubbles"] = 0.3, ["cracks"] = 1.0, ["cracksFine"] = 1.0 },
                                                           ["rings"] = new JsonObject { ["on"] = true, ["amount"] = 0.5, ["size"] = 0.5, ["strength"] = 1.0 } }));
        }

        static readonly (string id, string label)[] GlassKinds =
        {
            ("vetro", "Vetro"), ("cristallo", "Cristallo"), ("acqua", "Acqua"), ("plastica", "Plastica"), ("diamante", "Diamante"),
            ("zaffiro", "Zaffiro"), ("rubino", "Rubino"), ("smeraldo", "Smeraldo"), ("zirconia", "Zirconia"),
        };

        void GlassSection()
        {
            var sp = Section(L.T("Vetro e trasparenza"));
            MatSlider(sp, L.T("Trasparenza"), "transmission.weight", 0, 0, 100, false, "0", "%", L.T("100% = vetro, gemma, acqua, plastica trasparente"), 100, true);
            if (D("transmission.weight") <= 0) return;
            var presets = new WrapPanel { Margin = new Thickness(96, 0, 0, 8) };
            var gp = _matInfo["glassPresets"] as JsonObject;
            foreach (var (id, label) in GlassKinds)
            {
                var vals = gp?[id] as JsonArray;
                if (vals == null) continue;
                var b = Theme.Button(L.T(label), Theme.Kind.Ghost, L.F("Indice di rifrazione {0} · numero di Abbe {1}", (double?)vals[0], (double?)vals[1]));
                b.MinHeight = 24; b.FontSize = 11.5; b.Padding = new Thickness(7, 0, 7, 0); b.Margin = new Thickness(0, 0, 4, 4);
                b.Click += async (_, __) => await EditMat(new JsonObject { ["transmission"] = new JsonObject { ["ior"] = (double?)vals[0], ["abbe"] = (double?)vals[1] } }, true);
                presets.Children.Add(b);
            }
            sp.Children.Add(presets);
            // glass of imported models often has maps meant for the old trick of the half-invisible window (dark colour,
            // dirt in the roughness, smudges in the normal map, sometimes a metal map): one click makes it clear glass
            var clean = Theme.Button(L.T("Rendi vetro pulito"), Theme.Kind.Normal,
                L.T("Toglie le mappe di colore, ruvidezza, rilievo, metallo e opacità: resta un vetro trasparente e liscio (Ctrl+Z per tornare indietro)"));
            clean.MinHeight = 26; clean.FontSize = 12; clean.Margin = new Thickness(96, 0, 0, 8); clean.HorizontalAlignment = HorizontalAlignment.Left;
            clean.Click += async (_, __) => await EditMat(new JsonObject
            {
                ["color"] = new JsonObject { ["tint"] = new JsonArray(1.0, 1.0, 1.0), ["map"] = new JsonObject { ["image"] = "" } },
                ["roughness"] = new JsonObject { ["value"] = 0.0, ["map"] = new JsonObject { ["image"] = "" } },
                ["metallic"] = new JsonObject { ["value"] = 0.0, ["map"] = new JsonObject { ["image"] = "" } },
                ["normal"] = new JsonObject { ["map"] = new JsonObject { ["image"] = "" }, ["bumpMap"] = new JsonObject { ["image"] = "" } },
                ["opacity"] = new JsonObject { ["useAlpha"] = false, ["map"] = new JsonObject { ["image"] = "" } },
            }, true);
            sp.Children.Add(clean);
            var a = Advanced(sp, "mat:glass");
            MatSlider(a.Body, L.T("Indice di rifrazione"), "transmission.ior", 1.5, 1.0, 3.0, false, "0.000", null, L.T("1.33 acqua · 1.5 vetro · 1.77 zaffiro · 2.42 diamante"));
            MatToggle(a.Body, L.T("Parete sottile"), "transmission.thin", L.T("Per vetri di finestre e bolle: una sola superficie, la luce non devia"));
            if (!Bo("transmission.thin") && ((bool?)_matInfo?["flat"] ?? false))
            {
                // a pane without thickness as solid glass: the light enters a block that never ends (a mirror)
                var warn = Theme.Label(L.T("Questo oggetto è un foglio senza spessore: come vetro pieno sembra uno specchio. Attiva «Parete sottile»."), 11.5, Theme.Warm);
                warn.TextWrapping = TextWrapping.Wrap;
                warn.Margin = new Thickness(0, 0, 0, 6);
                sp.Children.Add(warn);
                var fix = Theme.Button(L.T("Attiva parete sottile"), Theme.Kind.Normal, null);
                fix.MinHeight = 26; fix.FontSize = 12; fix.Margin = new Thickness(96, 0, 0, 8); fix.HorizontalAlignment = HorizontalAlignment.Left;
                fix.Click += async (_, __) => await EditMat(new JsonObject { ["transmission"] = new JsonObject { ["thin"] = true } }, true);
                sp.Children.Add(fix);
                sp.Children.Remove(a.Root); sp.Children.Add(a.Root);      // the warning stays in sight, above
            }
            a.Done(Bo("transmission.thin") || D("transmission.absorbCm") > 0 || Bo("transmission.dispersion"));
            if (Bo("transmission.thin")) return;
            MatSlider(a.Body, L.T("Colore in profondità"), "transmission.absorbCm", 0, 0, 100, false, "0.#", "cm",
                      L.T("0 = spento · distanza alla quale la luce prende il colore qui sotto: vetro verde spesso, acqua, liquori"), 1, true);
            if (D("transmission.absorbCm") > 0) MatColor(a.Body, L.T("Colore"), "transmission.absorbColor");
            var disp = MatToggle(a.Body, L.T("Dispersione (arcobaleno)"), "transmission.dispersion",
                                 L.T("La luce si separa nei colori: \"fuoco\" nelle gemme e caustiche colorate"));
            if (Bo("transmission.dispersion"))
            {
                MatSlider(a.Body, L.T("Intensità"), "transmission.dispersionAmount", 0.35, 0, 100, false, "0", "%",
                          L.T("Quanta luce si separa nei colori: 10-20% delicato · 35% gemma · 100% massimo (più rumore)"), 100);
                MatSlider(a.Body, L.T("Separazione colori"), "transmission.dispersionBoost", 1, 0.25, 5, true, "0.##", "×",
                          L.T("Quanto si allontanano i colori: 1× = valore reale del materiale"));
                MatSlider(a.Body, L.T("Numero di Abbe"), "transmission.abbe", 55, 10, 90, false, "0", null,
                          L.T("Più basso = più dispersione. Diamante 55 · vetro 58 · cristallo 36 · zirconia 34"));
                a.Body.Children.Add(Note(L.T("Cycles non calcola i colori della luce uno per uno: la dispersione è simulata e porta un po' di rumore colorato, che sparisce con più campioni. ") +
                                     L.T("Le caustiche nitide restano bianche; quelle colorate si vedono con le caustiche normali.")));
            }
        }

        void SheenSection()
        {
            var sp = Section(L.T("Velluto"));
            MatSlider(sp, L.T("Velluto"), "sheen.weight", 0, 0, 100, false, "0", "%", L.T("Lucentezza morbida ai bordi: velluti, tessuti, pesche"), 100, true);
            if (D("sheen.weight") <= 0) return;
            var a = Advanced(sp, "mat:sheen");
            MatSlider(a.Body, L.T("Morbidezza"), "sheen.roughness", 0.5, 0, 100, false, "0", "%", L.T("Quanto si allarga il riflesso vellutato sui bordi (Sheen): basso = un filo di luce sul bordo, alto = un alone morbido, come velluto o stoffa"), 100);
            MatColor(a.Body, L.T("Tinta"), "sheen.tint");
            a.Done(Diff(D("sheen.roughness", 0.5), 0.5));
        }

        /// <summary>(1.77.0) «Fogliame»: the leaves (season, light through, back) or the wood of a plant; engine
        /// matedit.foliage_color / foliage_translucent, view viewer.js useFoliage.</summary>
        void FoliageSection()
        {
            var sp = Section(L.T("Fogliame"));
            bool leaves = S("foliage.part") != "legno";
            var seg = Theme.Segmented(out var pb,
                (L.T("Foglie"), L.T("Foglie, aghi, petali, fili d'erba: hanno la stagione, la luce che le attraversa e il retro più chiaro")),
                (L.T("Legno"), L.T("Tronco, rami e corteccia della stessa pianta: la stagione non li tocca, restano la variazione e lo scuro all'interno")));
            Theme.SetSegment(pb, leaves ? 0 : 1);
            pb[0].Click += async (_, __) => await EditMat("foliage.part", JsonValue.Create("foglie"), true);
            pb[1].Click += async (_, __) => await EditMat("foliage.part", JsonValue.Create("legno"), true);
            seg.Margin = new Thickness(0, 0, 0, 8);
            seg.HorizontalAlignment = HorizontalAlignment.Left;
            sp.Children.Add(seg);
            if (leaves)
            {
                MatSlider(sp, L.T("Stagione"), "foliage.season", 0, 0, 100, false, "0", "%",
                          L.T("0% = estate, tutto verde · verso il 30-50% le foglie ingialliscono, poi diventano arancioni e rosse e cominciano a cadere · 100% = inverno, niente foglie. Ogni foglia ha il suo momento: rami interi cambiano insieme, ogni pianta un po' prima o un po' dopo"), 100, true);
                sp.Children.Add(Note(SeasonText(D("foliage.season"))));
                MatSlider(sp, L.T("Luce attraverso"), "foliage.translucency", 0.5, 0, 100, false, "0", "%",
                          L.T("Quanta luce del sole passa attraverso la foglia e la illumina dall'altra parte: una chioma vista da sotto, controsole, diventa verde chiaro e luminosa invece che scura. 0% = foglia opaca come la carta"), 100);
            }
            var a = Advanced(sp, "mat:foliage");
            if (leaves)
            {
                MatSlider(a.Body, L.T("Retro della foglia"), "foliage.back", 0.3, 0, 100, false, "0", "%",
                          L.T("Il lato di sotto della foglia, più chiaro e un po' più giallo, come nelle foglie vere"), 100);
                MatSlider(a.Body, L.T("Rossi d'autunno"), "foliage.red", 0.5, 0, 100, false, "0", "%",
                          L.T("Quante piante diventano rosse in autunno: 0% = tutte gialle e dorate · 100% = tutte arancioni e rosse. Si vede con la Stagione oltre il 30%"), 100);
            }
            MatSlider(a.Body, L.T("Scuro all'interno"), "foliage.inner", 0.3, 0, 100, false, "0", "%",
                      L.T("Più scuro al centro della pianta, più chiaro sul bordo esterno, dove arriva più luce: dà volume alla chioma. Solo nel path tracing e nel render"), 100);
            MatSlider(a.Body, L.T("Variazione"), "foliage.variation", 0.3, 0, 100, false, "0", "%",
                      L.T("Ogni pianta e ogni foglia un po' diversa di tinta e di luminosità: le copie di una distribuzione non sembrano fatte con lo stampo"), 100);
            a.Done(Diff(D("foliage.back", 0.3), 0.3) || Diff(D("foliage.red", 0.5), 0.5) || Diff(D("foliage.inner", 0.3), 0.3) || Diff(D("foliage.variation", 0.3), 0.3));
        }

        /// <summary>(1.77.1) «Tessuto»: pieno (the fuzz: the sheen of the Principled, with its mask) or sottile (seen
        /// through, more opaque edge on, light through); the tint by a mask. Engine matedit.fabric_color, view useFabric.</summary>
        /// <summary>(1.79.0, Luca: «parallax room») type Interni: a room behind every window (interior mapping). Engine
        /// matedit.interior, view useInterior.</summary>
        void InteriorSection()
        {
            var sp = Section(L.T("Interni"));
            sp.Children.Add(HintSmall(L.T("Le stanze seguono gli assi dell'oggetto: su ogni facciata piatta la superficie si divide in stanze della misura scelta. Sulle facce quasi orizzontali resta solo il vetro")));
            // (Luca: «queste sono parallax credo standard ma se le carico il tuo materiale non funziona»)
            MapRow(sp, L.T("Stanza"), "interior.map", strength: false, channel: false, invert: false);
            sp.Children.Add(HintSmall(L.T("Un'immagine di stanza a croce, divisa in 3×3: al centro la parete di fondo, sopra il soffitto, sotto il pavimento, ai lati le pareti; negli angoli, con la trasparenza, il telaio della finestra e due file di mobili. Senza immagine: la stanza di prova")));
            MatSlider(sp, L.T("Larghezza stanza"), "interior.roomW", 4, 1, 20, false, "0.0", "m",
                      L.T("Quanto è larga ogni stanza lungo la facciata: di solito la distanza tra una finestra e l'altra"), 1, true);
            MatSlider(sp, L.T("Altezza piano"), "interior.roomH", 3, 2, 10, false, "0.0", "m",
                      L.T("L'altezza di un piano dell'edificio: la distanza tra una fila di finestre e quella sopra"), 1, true);
            MatSlider(sp, L.T("Profondità"), "interior.depthM", 4, 1, 20, false, "0.0", "m",
                      L.T("Quanto è profonda la stanza dietro il vetro"), 1, true);
            // (Luca: «vorrei un check button per lo scaling: se flaggato è il materiale che si ridimensiona in base a come resizo il modello»)
            MatToggle(sp, L.T("Si adatta al modello"), "interior.stretch",
                      L.T("Prima sistema le stanze con le misure qui sopra, poi accendilo: le stanze restano come sono adesso e, se poi cambi la scala del modello, si allungano, si schiacciano, crescono e rimpiccioliscono con lui. Spento: le stanze restano delle misure scelte e il modello ne contiene più o meno"), true);
            MatSlider(sp, L.T("Luce della stanza"), "interior.bright", 0.4, 0.001, 20, true, "0.###", null,
                      L.T("Quanto è illuminata la stanza di giorno, vista da fuori. Quando l'Ambiente è buio scende da sola a 0,005, una luce debolissima: di notte la luce la danno «Luci accese»"), 1, true);
            // (Luca: «serve anche la versione notturna con luci accese, dusk to dawn, l'intensità e il calore»)
            MatToggle(sp, L.T("Luci accese"), "interior.lightsOn", L.T("Le luci delle stanze accese: una parte delle stanze si illumina, con la luce calda o fredda scelta"), true);
            if (Bo("interior.lightsOn"))
            {
                var dk = new Toggle(L.T("Dal tramonto all'alba"), BoD("interior.dusk", true),
                                    L.T("Le luci si accendono da sole solo la sera e di notte, secondo l'ora dell'Ambiente. Spento: accese sempre"));
                dk.Toggled += async v => await EditMat("interior.dusk", JsonValue.Create(v), true);
                sp.Children.Add(dk);
                MatSlider(sp, L.T("Intensità"), "interior.power", 1.5, 0.001, 20, true, "0.###", null,
                          L.T("Quanto sono forti le luci accese nelle stanze"), 1, true);
                MatSlider(sp, L.T("Calore"), "interior.kelvin", 3000, 1500, 10000, false, "0", "K",
                          L.T("Il colore delle luci: 2700 K calde (gialle), 4000 K neutre, 6500 K e oltre fredde (azzurre)"), 1, true, KelvinBrush());
                MatSlider(sp, L.T("Stanze illuminate"), "interior.share", 0.6, 0, 100, false, "0", "%",
                          L.T("Quante stanze hanno la luce accesa: ogni stanza è scelta dal suo posto, la stessa nella vista e nel render"), 100, true);
            }
        }

        void FabricSection()
        {
            var sp = Section(L.T("Tessuto"));
            bool thin = S("fabric.mode") == "sottile";
            var seg = Theme.Segmented(out var pb,
                (L.T("Pieno"), L.T("Stoffe che non lasciano vedere: velluto, lana, feltro, cotone, jeans, seta pesante")),
                (L.T("Sottile"), L.T("Stoffe leggere che lasciano vedere e passare la luce: tende, tulle, garza, cotone sottile")));
            Theme.SetSegment(pb, thin ? 1 : 0);
            pb[0].Click += async (_, __) => await EditMat("fabric.mode", JsonValue.Create("pieno"), true);
            pb[1].Click += async (_, __) => await EditMat("fabric.mode", JsonValue.Create("sottile"), true);
            seg.Margin = new Thickness(0, 0, 0, 8);
            seg.HorizontalAlignment = HorizontalAlignment.Left;
            sp.Children.Add(seg);
            MatSlider(sp, L.T("Peluria"), "sheen.weight", 0, 0, 100, false, "0", "%",
                      L.T("Il velo chiaro e morbido ai bordi delle stoffe, dove le fibre prendono la luce di sbieco: alto per velluto, feltro e lana, basso per cotone liscio e seta"), 100, true);
            if (thin)
            {
                MatSlider(sp, L.T("Trasparenza"), "fabric.see", 0.6, 0, 100, false, "0", "%",
                          L.T("Quanto si vede attraverso la stoffa guardandola di fronte: 0% = coprente · 80-90% = tulle o velo"), 100);
                MatSlider(sp, L.T("Più fitto di taglio"), "fabric.edge", 0.6, 0, 100, false, "0", "%",
                          L.T("Guardata di sbieco una tenda sottile diventa più fitta, come una vera: 0% = trasparente uguale da ogni lato · 100% = quasi coprente di taglio"), 100);
                MatSlider(sp, L.T("Luce attraverso"), "fabric.light", 0.5, 0, 100, false, "0", "%",
                          L.T("Quanta luce passa attraverso la stoffa e la illumina dall'altra parte: una tenda con il sole dietro si accende"), 100);
            }
            var a = Advanced(sp, "mat:fabric");
            MatSlider(a.Body, L.T("Morbidezza della peluria"), "sheen.roughness", 0.5, 0, 100, false, "0", "%",
                      L.T("Quanto si allarga il velo della peluria: basso = un filo di luce sul bordo (raso, seta) · alto = un alone morbido (velluto, lana)"), 100);
            MatColor(a.Body, L.T("Colore della peluria"), "sheen.tint", L.T("Il colore del velo ai bordi: bianco per quasi tutte le stoffe, una tinta per i velluti cangianti"));
            MapRow(a.Body, L.T("Dove c'è peluria"), "fabric.fuzzMap", false, true, true, a.Body);
            MapRow(a.Body, L.T("Maschera di tinta"), "fabric.tintMap", false, true, true, a.Body);
            if (S("fabric.tintMap.image") != "")
                MatColor(a.Body, L.T("Colore della tinta"), "fabric.tint", L.T("Il colore steso dove la maschera di tinta è bianca, sopra la texture della stoffa: per cambiare il colore di una parte (righe, motivi) senza rifare la texture"));
            a.Done(Diff(D("sheen.roughness", 0.5), 0.5) || S("fabric.fuzzMap.image") != "" || S("fabric.tintMap.image") != "");
        }

        /// <summary>What the «Stagione» of the leaves shows at this value (as matedit FOLIAGE_START/SPREAD/LIFE).</summary>
        static string SeasonText(double s) =>
            s < 0.1 ? L.T("Estate: tutto verde") :
            s < 0.35 ? L.T("Fine estate: le prime foglie ingialliscono") :
            s < 0.55 ? L.T("Autunno: gialli e arancioni") :
            s < 0.72 ? L.T("Autunno pieno: arancioni e rossi, le prime foglie cadono") :
            s < 0.92 ? L.T("Fine autunno: restano poche foglie") :
            L.T("Inverno: niente foglie");

        void SubsurfaceSection()
        {
            var sp = Section(L.T("Sottosuperficie"));
            MatSlider(sp, L.T("Sottosuperficie"), "subsurface.weight", 0, 0, 100, false, "0", "%", L.T("La luce entra e si diffonde: marmo, cera, pelle, frutta, latte"), 100, true);
            if (D("subsurface.weight") <= 0) return;
            // (1.76.58, Luca: il bosco buio - «le foglie sono un materiale standard») a leaf, a petal, a curtain: a thin
            // sheet the light goes through (Blender: Thin Wall - the subsurface becomes translucency). The same switch
            // as «Parete sottile» of the glass, which shows only with some Trasparenza
            MatToggle(sp, L.T("Foglio sottile (luce attraverso)"), "transmission.thin",
                      L.T("Per foglie, petali, carta, tende: una superficie sottile che la luce attraversa e illumina dall'altra parte, come una chioma vista da sotto con il sole dietro. Con la Sottosuperficie al 30-40%: il sottobosco non resta nero"));
            var a = Advanced(sp, "mat:subsurface");
            MatSlider(a.Body, L.T("Profondità"), "subsurface.radiusMm", 1, 0.05, 200, true, "0.##", "mm", L.T("Quanto penetra la luce"));
            MatColor(a.Body, L.T("Colore interno"), "subsurface.color", L.T("Colore della luce che attraversa il materiale"));
            a.Done(Diff(D("subsurface.radiusMm", 1), 1));
        }

        void EmissionSection()
        {
            var sp = Section(L.T("Emissione"));
            var on = D("emission.nits") > 0;
            var t = new Toggle(L.T("Emette luce"), on, L.T("Schermi, LED, insegne, lampade"));
            t.Toggled += async v => await EditMat("emission.nits", JsonValue.Create(v ? 500.0 : 0.0), true);
            sp.Children.Add(t);
            if (!on) return;
            // switches (engine dusk.py): Accesa wins; Dal tramonto all'alba = lit only at evening and at night
            bool eOn = BoD("emission.on", true);
            MatToggle(sp, L.T("Accesa"), "emission.on", L.T("Spenta: non emette luce, qualunque sia l'ora (vale più di «Dal tramonto all'alba»); la luminanza resta impostata"), true);
            if (eOn)
                MatToggle(sp, L.T("Dal tramonto all'alba"), "emission.dusk",
                          L.T("Si accende da sola solo la sera e di notte, secondo l'ora dell'Ambiente: finestre illuminate, neon, insegne. Di giorno resta spenta"), false);
            MapRow(sp, L.T("Texture"), "emission.map", strength: false, channel: false, invert: false);
            var a = Advanced(sp, "mat:emission");
            MatSlider(a.Body, L.T("Luminanza"), "emission.nits", 500, 1, 100000, true, "0", "nit",
                      L.T("100 nit schermo spento in ufficio · 300-500 monitor · 1000+ insegna · 10000+ lampada"));
            MatSlider(a.Body, L.T("Temperatura"), "emission.kelvin", 6500, 1000, 12000, false, "0", "K", L.T("Il colore della luce emessa in gradi Kelvin: 2700 K = lampadina calda, 4000 K = neutra, 6500 K = luce del giorno, oltre = bluastra"), 1, false, KelvinBrush());
            MatColor(a.Body, L.T("Filtro colore"), "emission.color");
            a.Done(Diff(D("emission.nits", 500), 500) || Diff(D("emission.kelvin", 6500), 6500));
        }

        void OpacitySection()
        {
            var sp = Section(L.T("Opacità (ritaglio)"));
            if (S("color.map.image") != "")
                MatToggle(sp, L.T("Usa l'alfa della texture colore"), "opacity.useAlpha", L.T("Le parti trasparenti della texture spariscono: foglie, griglie, decalcomanie"));
            if (!Bo("opacity.useAlpha")) MapRow(sp, L.T("Mappa"), "opacity.map", strength: false, invert: false);
            if (Bo("opacity.useAlpha") || S("opacity.map.image") != "")
            {
                var a = Advanced(sp, "mat:opacity");
                MatToggle(a.Body, L.T("Inverti"), "opacity.invert", null, false);
                MatToggle(a.Body, L.T("Ritaglio netto"), "opacity.cutout",
                          L.T("Acceso: ogni punto è pieno o vuoto (soglia 50%), come nel tempo reale; giusto per foglie, griglie e texture con lo sfondo semitrasparente. Le mappe a sfumature (vetri smerigliati o incisi, paralumi) restano comunque graduali: tagliate diventerebbero puntini. Spento: trasparenza sempre graduale"), false);
                a.Done(Bo("opacity.invert") || !BoD("opacity.cutout", true));
            }
        }

        /// <summary>A change of the displacement that can make a lot of geometry (remesh, subdivision in cm, the type
        /// itself): the engine estimates it first; too heavy for the objects using the material = a question, with
        /// the value that fits (a 4 km ground with a 2 cm remesh would fill the memory and stop the computer).</summary>
        async Task DispEdit(string path, JsonNode? value)
        {
            await EnsureOwnCopy();
            var patch = Patch(path, value);
            for (int round = 0; round < 2; round++)
            {
                JsonObject? c = null;
                await Run(async api => { c = await api.Post("material/dispcheck", new JsonObject { ["name"] = _matName, ["params"] = patch.DeepClone() }); });
                if (c == null || ((bool?)c["safe"] ?? true)) break;
                var obj = (string?)c["object"] ?? "";
                var rem = (double?)c["remeshFaces"] ?? 0; var remMax = (double?)c["remeshMax"] ?? 15e6;
                var sub = (double?)c["subdivFaces"] ?? 0; var subMax = (double?)c["subdivMax"] ?? 60e6;
                string M(double v) => v >= 1e9 ? L.F("{0} miliardi", (v / 1e9).ToString("0.#")) : L.F("{0} milioni", (v / 1e6).ToString("0"));
                var disp = patch["displacement"] as JsonObject ?? new JsonObject();
                if (rem > remMax)
                {
                    var cm = (double?)c["suggestRemeshCm"] ?? 50;
                    var q = L.F("«Rifai la maglia» su «{0}» creerebbe circa {1} di facce (il limite sicuro è {2}): servirebbe più memoria di quella del computer, che si bloccherebbe.\n\nUsare voxel da {3} cm (il più fine che ci sta)?\nNo = non cambiare nulla.",
                                obj, M(rem), M(remMax), cm.ToString("0.#"));
                    if (Msg.Show(this, q, "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Warning) != MessageBoxResult.Yes) { await LoadMaterial(); RenderProps(); return; }
                    disp["remeshCm"] = cm;
                    patch["displacement"] = disp;
                    continue;
                }
                if (sub > subMax)
                {
                    var cm = (double?)c["suggestEdgeCm"] ?? 10;
                    var q = L.F("La suddivisione in centimetri su «{0}» creerebbe circa {1} di triangoli (il limite sicuro è {2}): servirebbe più memoria di quella del computer.\n\nUsare triangoli da {3} cm (il più fine che ci sta)?\nNo = non cambiare nulla.",
                                obj, M(sub), M(subMax), cm.ToString("0.#"));
                    if (Msg.Show(this, q, "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Warning) != MessageBoxResult.Yes) { await LoadMaterial(); RenderProps(); return; }
                    disp["edgeCm"] = cm;
                    patch["displacement"] = disp;
                    continue;
                }
                break;
            }
            await EditMat(patch, true);
        }

        void DispToggle(Panel parent, string label, string path, string tip)
        {
            var tg = new Toggle(label, Bo(path), tip);
            tg.Toggled += async v => await DispEdit(path, JsonValue.Create(v));
            parent.Children.Add(tg);
        }

        void DispSlider(Panel parent, string label, string path, double def, double min, double max, bool log, string fmt, string? unit, string tip)
        {
            var s = new ValueSlider(label, D(path, def), min, max, log, fmt, unit, null, tip);
            s.Committed += async v => await DispEdit(path, JsonValue.Create(v));
            parent.Children.Add(s);
        }

        void DisplacementSection()
        {
            var sp = Section(L.T("Rilievo vero"));
            // mode
            var modes = new[] { "both", "true", "bump" };
            var mseg = Theme.Segmented(out var mb,
                (L.T("Vero + dettaglio"), L.T("La superficie si sposta e in più il rilievo fine della mappa: il risultato più ricco (consigliato)")),
                (L.T("Vero"), L.T("Solo lo spostamento della superficie")),
                (L.T("Solo rilievo"), L.T("Nessuna geometria nuova: solo l'aspetto del rilievo, veloce (come Height Field di D5). La sagoma resta piatta")));
            Theme.SetSegment(mb, Math.Max(0, Array.IndexOf(modes, S("displacement.mode") == "" ? "both" : S("displacement.mode"))));
            for (int i = 0; i < mb.Count; i++) { var m = modes[i]; mb[i].Click += async (_, __) => await DispEdit("displacement.mode", JsonValue.Create(m)); }
            mseg.Margin = new Thickness(0, 2, 0, 10); mseg.HorizontalAlignment = HorizontalAlignment.Left;
            sp.Children.Add(mseg);
            var bump = S("displacement.mode") == "bump";
            // maps
            var da = Advanced(sp, "mat:displacement");
            MapRow(sp, L.T("Altezza"), "displacement.map", strength: false, adv: da.Body);
            MatSlider(sp, L.T("Altezza massima"), "displacement.heightCm", 1, 0.01, 50, true, "0.##", "cm", L.T("Quanto si alzano le zone bianche della mappa"), 1, true);
            sp.Children.Remove(da.Root); sp.Children.Add(da.Root);       // under the height
            MatSlider(da.Body, L.T("Livello zero"), "displacement.midlevel", 0.5, 0, 100, false, "0", "%",
                      L.T("Il grigio della mappa che resta alla quota della superficie (50% = grigio medio). Alzalo se l'oggetto sembra galleggiare, abbassalo se affonda"), 100, true);
            MapRow(da.Body, L.T("Vettoriale"), "displacement.vector", strength: false, channel: false, invert: false);
            if (S("displacement.vector.image") != "")
            {
                MatSlider(da.Body, L.T("Forza vettoriale"), "displacement.vectorScale", 1, 0, 10, false, "0.##", "×", L.T("Moltiplica gli spostamenti della mappa vettoriale (spazio tangente)"), 1, true);
                MatSlider(da.Body, L.T("Zero vettoriale"), "displacement.vectorMid", 0, 0, 100, false, "0", "%", L.T("0% per le mappe EXR a 32 bit, 50% per le PNG a 8 bit"), 100, true);
            }
            da.Body.Children.Add(Note(L.T("La mappa vettoriale sposta la superficie anche di lato (sporgenze, rocce, tegole): la danno alcuni programmi di scultura. Si somma all'altezza.")));
            da.Done(Diff(D("displacement.midlevel", 0.5), 0.5) || S("displacement.vector.image") != "" || MapChanged("displacement.map"));
            if (bump) { sp.Children.Add(Note(L.T("Solo rilievo: nessuna suddivisione, nessun costo in memoria. Visibile in path tracing e nel render finale."))); return; }

            // subdivision
            var sub = Section(L.T("Suddivisione"));
            var spaces = new[] { "pixel", "object" };
            var sseg = Theme.Segmented(out var sb,
                (L.T("In pixel"), L.T("Più fine vicino alla fotocamera, leggera in lontananza: la scelta per un singolo oggetto")),
                (L.T("In centimetri"), L.T("Lo stesso dettaglio ovunque e per tutte le copie: per le distribuzioni e gli oggetti ripetuti")));
            Theme.SetSegment(sb, Math.Max(0, Array.IndexOf(spaces, S("displacement.space") == "" ? "pixel" : S("displacement.space"))));
            for (int i = 0; i < sb.Count; i++) { var s = spaces[i]; sb[i].Click += async (_, __) => await DispEdit("displacement.space", JsonValue.Create(s)); }
            sseg.Margin = new Thickness(0, 2, 0, 10); sseg.HorizontalAlignment = HorizontalAlignment.Left;
            sub.Children.Add(sseg);
            if (S("displacement.space") == "object")
                DispSlider(sub, L.T("Lato dei triangoli"), "displacement.edgeCm", 1, 0.1, 50, true, "0.##", "cm", L.T("Più piccolo = più dettaglio e più memoria"));
            else
            {
                var details = new[] { "bassa", "media", "alta" };
                var seg = Theme.Segmented(out var buttons, (L.T("Bassa"), L.T("Più veloce: 4 pixel")), (L.T("Media"), L.T("2 pixel")), (L.T("Alta"), L.T("1 pixel: il massimo dettaglio")));
                Theme.SetSegment(buttons, Math.Max(0, Array.IndexOf(details, S("displacement.detail"))));
                for (int i = 0; i < buttons.Count; i++) { var d = details[i]; buttons[i].Click += async (_, __) => await EditMat("displacement.detail", JsonValue.Create(d), true); }
                var row = new DockPanel { Margin = new Thickness(0, 0, 0, 8) };
                var l = Theme.Label(L.T("Dettaglio"), 12, Theme.TextMuted); l.Width = 96;
                row.Children.Add(l); row.Children.Add(seg);
                sub.Children.Add(row);
            }
            var sa = Advanced(sub, "mat:subdivision");
            DispSlider(sa.Body, L.T("Livello massimo"), "displacement.maxLevel", 10, 1, 16, false, "0", null,
                       L.T("Tetto alle suddivisioni (ognuna moltiplica per 4 i triangoli): limita memoria e tempi sulle superfici molto grandi"));
            MatToggle(sa.Body, L.T("Chiudi le fessure"), "displacement.weld", L.T("Unisce i vertici doppi prima di spostarli: sulle cuciture delle UV e tra i pezzi non si aprono crepe"));
            DispToggle(sa.Body, L.T("Rifai la maglia"), "displacement.remesh", L.T("Ricostruisce la maglia a voxel prima di suddividerla: per modelli con topologia pessima (triangoli lunghi, buchi). Costoso; le UV si perdono, usa la proiezione Triplanare"));
            if (Bo("displacement.remesh"))
                DispSlider(sa.Body, L.T("Dimensione voxel"), "displacement.remeshCm", 2, 0.2, 500, true, "0.#", "cm", L.T("Più piccolo = forma più fedele e più memoria"));
            MatToggle(sa.Body, L.T("Meno dettaglio fuori inquadratura"), "displacement.offscreen", L.T("Quello che la fotocamera non vede (ma si riflette o fa ombra) si suddivide meno: risparmia memoria"));
            MatToggle(sa.Body, L.T("Solo nel render finale"), "displacement.finalOnly", L.T("Nel path tracing della vista resta solo il rilievo, veloce; nel render finale la superficie si sposta davvero"));
            sa.Done(Diff(D("displacement.maxLevel", 10), 10) || !BoD("displacement.weld", true) || Bo("displacement.remesh")
                    || !BoD("displacement.offscreen", true) || Bo("displacement.finalOnly"));
            sub.Children.Add(Note(L.T("Visibile in path tracing e nel render finale; nella vista in tempo reale si vede la normal map.")));
        }

        void MappingSection()
        {
            var sp = Section(L.T("Mappatura texture"));
            var modes = new[] { "uv", "box", "planar", "cylinder", "sphere" };
            var mode = S("uv.mode") is var m && m != "" ? m : "uv";
            var seg = Theme.Segmented(out var buttons, ("UV", L.T("Coordinate del modello")), (L.T("Triplanare"), L.T("Box: la texture proiettata da tre direzioni, senza bisogno di UV (mondo o oggetto qui sotto)")),
                                      (L.T("Piana"), L.T("Proiezione dall'alto")), (L.T("Cilindro"), null), (L.T("Sfera"), null));
            Theme.SetSegment(buttons, Math.Max(0, Array.IndexOf(modes, mode)));
            for (int i = 0; i < buttons.Count; i++) { var md = modes[i]; buttons[i].Click += async (_, __) => await EditMat("uv.mode", JsonValue.Create(md), true); }
            seg.Margin = new Thickness(0, 0, 0, 10);
            seg.HorizontalAlignment = HorizontalAlignment.Left;
            sp.Children.Add(seg);
            if (mode == "uv" && ((bool?)_matInfo["hasUv"] ?? true) == false)
                sp.Children.Add(Note(L.T("Questo oggetto non ha coordinate UV: scegli Box per vedere la texture.")));
            var ma = Advanced(sp, "mat:mapping");      // moved to the end below
            if (mode == "uv")
            {
                MatSlider(sp, L.T("Scala · ripetizioni"), "uv.scale", 1, 0.01, 100, true, "0.###", "×", L.T("Quante volte la texture si ripete sulle UV del modello (in UV la scala è in ripetizioni; in Box, Piana, Cilindro e Sfera è in centimetri)"));
                {
                    // one picture exactly over the part with this material (a picture made for that shape); always
                    // here (1.67.8): opened from the list of the scene materials it fits every object using it
                    var fb = SmallButton(Icons.Expand, L.T("Adatta all'oggetto"), FitMap);
                    fb.ToolTip = L.T("Una sola immagine, intera, sulla parte dell'oggetto con questo materiale, proiettata dal lato verso cui guarda e stirata alla sua forma: nuove coordinate UV per quelle facce (le altre restano come sono). Per un'immagine fatta per quella sagoma (una vetrata, un'insegna); poi puoi ritoccare scala e spostamento. Si annulla con Ctrl+Z")
                                 + "\n" + (_matObject == "" ? L.T("Nessun oggetto selezionato: vale per tutti gli oggetti con questo materiale, ognuno sulla sua forma.")
                                      : L.T("Con più pezzi selezionati (una finestra fatta di più parti): una sola immagine su tutti insieme."));
                    fb.HorizontalAlignment = HorizontalAlignment.Left;
                    fb.Margin = new Thickness(0, 2, 0, 8);
                    sp.Children.Add(fb);
                }
            }
            else
            {
                MatSlider(sp, L.T("Scala · dimensione reale"), "uv.sizeCm", 100, 1, 2000, true, "0.#", "cm", L.T("Una ripetizione della texture misura questo (es. una piastrella 60 cm)"));
                var spaces = new[] { "object", "world" };
                var ss = Theme.Segmented(out var sb, (L.T("Oggetto"), L.T("La texture segue l'oggetto quando lo sposti")), (L.T("Mondo"), L.T("La texture resta ferma: continua tra oggetti vicini")));
                Theme.SetSegment(sb, S("uv.space") == "world" ? 1 : 0);
                for (int i = 0; i < sb.Count; i++) { var sv = spaces[i]; sb[i].Click += async (_, __) => await EditMat("uv.space", JsonValue.Create(sv), true); }
                var row = new DockPanel { Margin = new Thickness(0, 0, 0, 10) };
                var l = Theme.Label(L.T("Riferimento"), 12, Theme.TextMuted); l.Width = 96;
                row.Children.Add(l); row.Children.Add(ss);
                sp.Children.Add(row);
                if (mode == "box")
                    MatSlider(ma.Body, L.T("Sfumatura spigoli"), "uv.blend", 0.2, 0, 100, false, "0", "%", L.T("Quanto si fondono le proiezioni sugli spigoli"), 100);
            }
            var st = P("uv.stretch") as JsonArray;
            double sx = st != null && st.Count > 0 ? (double?)st[0] ?? 1 : 1, sy = st != null && st.Count > 1 ? (double?)st[1] ?? 1 : 1;
            var sxs = new ValueSlider(L.T("Stira X"), sx, 0.1, 10, true, "0.###", "×", null, L.T("Allunga o accorcia la texture in orizzontale: 1× = proporzioni giuste, 2× = due volte più larga"));
            var sys = new ValueSlider(L.T("Stira Y"), sy, 0.1, 10, true, "0.###", "×", null, L.T("Allunga o accorcia la texture in verticale: 1× = proporzioni giuste, 2× = due volte più alta"));
            sxs.Committed += async v => await EditMat("uv.stretch", new JsonArray(v, sys.Value));
            sys.Committed += async v => await EditMat("uv.stretch", new JsonArray(sxs.Value, v));
            ma.Body.Children.Add(sxs); ma.Body.Children.Add(sys);
            MatSlider(ma.Body, L.T("Rotazione"), "uv.rotation", 0, 0, 360, false, "0.#", "°", L.T("Gira la texture sulla superficie, in gradi: per allineare venature, mattoni o doghe alla direzione voluta"));
            var off = P("uv.offset") as JsonArray;
            double ox = off != null && off.Count > 0 ? (double?)off[0] ?? 0 : 0, oy = off != null && off.Count > 1 ? (double?)off[1] ?? 0 : 0;
            // (0,125 = 1/8 of a tile: thousandths count)
            var oxs = new ValueSlider(L.T("Sposta X"), ox, -1, 1, false, "0.####", null, null, L.T("Fa scorrere la texture in orizzontale, in frazioni di una ripetizione: per mettere un disegno o una giunzione dove vuoi"));
            var oys = new ValueSlider(L.T("Sposta Y"), oy, -1, 1, false, "0.####", null, null, L.T("Fa scorrere la texture in verticale, in frazioni di una ripetizione: per mettere un disegno o una giunzione dove vuoi"));
            // (a third value comes only from «Centra sull'oggetto»: up and down on walls; kept when X or Y change)
            double oz = off != null && off.Count > 2 ? (double?)off[2] ?? 0 : 0;
            JsonArray Off(double x, double y) => oz != 0 ? new JsonArray(x, y, oz) : new JsonArray(x, y);
            oxs.Committed += async v => await EditMat("uv.offset", Off(v, oys.Value));
            oys.Committed += async v => await EditMat("uv.offset", Off(oxs.Value, v));
            ma.Body.Children.Add(oxs); ma.Body.Children.Add(oys);
            if (_matObject != "")
            {
                var cb = SmallButton(Icons.Pivot, L.T("Centra sull'oggetto"), CenterMap);
                cb.ToolTip = L.T("Mette il centro della texture al centro dell'oggetto selezionato (della sua parte con questo materiale) e ce la tiene quando cambi scala o rotazione. Succede da solo quando metti una texture; spostandola a mano resta dove la metti");
                cb.HorizontalAlignment = HorizontalAlignment.Left;
                cb.Margin = new Thickness(0, 4, 0, 8);
                ma.Body.Children.Add(cb);
            }
            // every separate piece of the object (two lamps in one object, the lenses of a lamp) with the picture
            // centred on its own middle (matedit.piece_attributes)
            MatToggle(ma.Body, L.T("Centra ogni pezzo"), "uv.perPiece",
                L.T("Ogni parte staccata dell'oggetto (i due fanali di un'auto, le lenti di un fanale, le piastrelle separate) ha la texture centrata sul suo centro, invece di un solo centro per tutto l'oggetto. Sposta X/Y spostano allo stesso modo tutti i pezzi"));
            MatToggle(sp, L.T("Varia per oggetto"), "uv.randomize", L.T("Sposta e ruota la texture a caso su ogni oggetto: cento sedie con lo stesso legno non sembrano fotocopiate"), false);
            // Randomize UV (as in Twinmotion): the same texture without visible repetition on a large surface
            MatToggle(sp, L.T("Rompi la ripetizione (Randomize UV)"), "uv.antitile",
                L.T("La texture viene mostrata a zone, ognuna spostata (e ruotata) a caso, sfumate tra loro: su un pavimento, un prato o un muro grande non si vede più lo stesso disegno ripetuto. Anche con texture che non si ripetono bene in origine. Non adatto a disegni regolari come piastrelle e mattoni (le fughe non combacerebbero)"));
            if (Bo("uv.antitile"))
            {
                MatSlider(ma.Body, L.T("Grandezza delle zone"), "uv.cellRepeats", 3, 1, 10, false, "0.#", "×", L.T("Quante ripetizioni della texture in ogni zona: più grande = zone ampie e cambi rari"));
                MatSlider(ma.Body, L.T("Sfumatura tra le zone"), "uv.antitileBlend", 0.25, 2, 50, false, "0", "%", L.T("Larghezza del passaggio tra una zona e l'altra"), 100);
                MatToggle(ma.Body, L.T("Ruota le zone"), "uv.antitileRotate", L.T("Spento: le zone sono solo spostate, la direzione resta (venature del legno, righe)"), false);
                sp.Children.Add(Note(L.T("Si vede nel path tracing e nel render finale; la vista in tempo reale mostra la texture normale.")));
            }
            sp.Children.Remove(ma.Root); sp.Children.Add(ma.Root);
            ma.Done(Diff(sx, 1) || Diff(sy, 1) || Diff(ox, 0) || Diff(oy, 0) || Diff(D("uv.rotation", 0), 0)
                    || (mode == "box" && Diff(D("uv.blend", 0.2), 0.2))
                    || (Bo("uv.antitile") && (Diff(D("uv.cellRepeats", 3), 3) || Diff(D("uv.antitileBlend", 0.25), 0.25) || !BoD("uv.antitileRotate", true))));
        }
    }
}
