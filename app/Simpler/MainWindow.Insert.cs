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
using System.Windows.Media.Imaging;

namespace Simpler
{
    /// <summary>
    /// Library tabs to insert things: lights, objects, Poly Haven textures - and drag &amp; drop of every tile into the view:
    /// a light or an object lands on the surface under the mouse, a material goes onto the piece under the mouse
    /// (Shift: onto the whole group). A click still works as before (centre of the view / selected objects).
    /// </summary>
    public sealed partial class MainWindow
    {
        TextBox _librarySearch = null!;
        JsonArray _phAssets = new JsonArray();
        readonly Dictionary<string, BitmapImage> _phThumbs = new();

        static Geometry LightIcon(string kind) => kind switch
        {
            "point" => Icons.Bulb, "spot" => Icons.LightSpot, "area" => Icons.LightArea, "disk" => Icons.LightDisk, "strip" => Icons.LightStrip,
            _ => Icons.Light,
        };
        static readonly (string kind, string label, string tip)[] InsertLights =
        {
            ("point", "Omni", "Lampadina: illumina in tutte le direzioni"),
            ("spot", "Spot", "Faretto con cono orientabile"),
            ("area", "Area", "Pannello luminoso morbido (softbox)"),
            ("disk", "Disco", "Pannello luminoso rotondo"),
            ("strip", "Striscia LED", "Striscia luminosa lunga e sottile"),
            ("sun", "Sole", "Luce solare: conta solo la direzione"),
        };
        static readonly (string kind, string label)[] InsertObjects =
        {
            ("cube", "Cubo"), ("sphere", "Sfera"), ("cylinder", "Cilindro"), ("cone", "Cono"), ("plane", "Piano"), ("torus", "Toro"),
        };

        /// <summary>Tiles of the insert tabs. Returns false when the tab is not one of them.</summary>
        bool RenderInsertTab()
        {
            if (_libraryTab == "lights")
            {
                foreach (var (kind, label, tip) in InsertLights)
                    AddTile(LightIcon(kind), L.T(label), L.T(tip), async at => await InsertLight(kind, at), "#F2C877");
                return true;
            }
            if (_libraryTab == "objects")
            {
                RenderObjectBrowser();
                return true;
            }
            if (_libraryTab == "primitives")
            {
                RenderSimplerModels();
                return true;
            }
            if (_libraryTab is "packmodels" or "packplants")
            {
                RenderPackModels(_libraryTab == "packplants");
                return true;
            }
            if (_libraryTab == "phmodels")
            {
                RenderPhModels();
                return true;
            }
            if (_libraryTab == "polyhaven")
            {
                RenderPolyHaven();
                return true;
            }
            return false;
        }

        void AddTile(Geometry icon, string label, string tip, Func<JsonObject?, Task> act, string color)
        {
            var tile = new StackPanel { Width = 92, Margin = new Thickness(4, 0, 4, 0) };   // (no top/bottom margin: two-line names fit the 130 px tile)
            var ic = Theme.Icon(icon, Theme.C(color), 34, 1.6);
            ic.HorizontalAlignment = HorizontalAlignment.Center;
            ic.Margin = new Thickness(0, 18, 0, 16);
            tile.Children.Add(ic);
            tile.Children.Add(Theme.TileText(new TextBlock { Text = label, FontSize = 11.5, TextAlignment = TextAlignment.Center, TextWrapping = TextWrapping.Wrap, Foreground = Theme.B(Theme.TextSoft) }));
            var btn = Theme.Button(tile, Theme.Kind.Normal, tip + "\n" + L.T("Clic: al centro della vista · trascina nella vista: dove lo lasci"));
            btn.Padding = new Thickness(2, 4, 2, 6);
            btn.Margin = new Thickness(4);
            btn.VerticalContentAlignment = VerticalAlignment.Top;
            btn.Height = 130;
            btn.Tag = label;
            btn.Click += async (_, __) => await act(null);
            MakeDraggable(btn, label, async (x, y) =>
            {
                var at = await AskViewPoint(x, y);
                if (at != null) await act(at);
            });
            _libraryTiles.Children.Add(btn);
        }

        /// <summary>(1.78.3) The lights button of the header: the kinds of light; one click puts it in the middle of the view.</summary>
        void ShowLightsMenu(FrameworkElement anchor)
        {
            var m = new ContextMenu { PlacementTarget = anchor, Placement = System.Windows.Controls.Primitives.PlacementMode.Bottom };
            foreach (var (kind, label, tip) in InsertLights)
            {
                var k = kind;
                var i = new MenuItem { Header = L.T(label), ToolTip = L.T(tip), Icon = Theme.Icon(LightIcon(k), Theme.C("#F2C877"), 16, 1.7) };
                i.Click += async (_, __) => await InsertLight(k, null);
                m.Items.Add(i);
            }
            m.IsOpen = true;
        }

        async Task InsertLight(string kind, JsonObject? at)
        {
            var engineKind = kind is "disk" or "strip" ? "area" : kind;
            var id = await AddObject(engineKind, "", at);
            if (id == "" || engineKind == kind) return;
            var body = kind == "disk"
                ? new JsonObject { ["id"] = id, ["shape"] = "DISK" }
                : new JsonObject { ["id"] = id, ["shape"] = "RECTANGLE", ["width"] = 120.0, ["height"] = 3.0, ["visibleCamera"] = true };   // a LED strip is seen glowing
            await Run(async api => { await api.Post("light", body); });
            await RefreshScene();
        }

        void FilterLibrary()
        {
            var q = (_librarySearch?.Text ?? "").Trim().ToLowerInvariant();
            foreach (var el in _libraryTiles.Children.OfType<FrameworkElement>())
            {
                var label = (el.Tag as string ?? "").ToLowerInvariant();
                el.Visibility = q == "" || label == "" || label.Contains(q) ? Visibility.Visible : Visibility.Collapsed;
            }
        }

        // ---------------------------------------------------------------- drag & drop into the view

        /// <summary>Press and drag a tile: a small label follows the mouse; released over the view, onDrop gets the
        /// point in the view (CSS pixels of the viewer). A plain click stays a click.</summary>
        void MakeDraggable(FrameworkElement tile, string label, Func<double, double, Task> onDrop, Func<string, Task>? onFolderDrop = null,
                           Func<ImageSource?>? icon = null, bool viewDrop = true, Func<string, bool>? folderOk = null)
        {
            string? Target(MouseEventArgs e) => onFolderDrop != null && FolderUnder(e) is string f && (folderOk == null || folderOk(f)) ? f : null;
            Point start = default;
            bool pressed = false, dragging = false;
            Popup? ghost = null;
            tile.PreviewMouseLeftButtonDown += (_, e) => { pressed = true; dragging = false; start = e.GetPosition(this); };
            tile.PreviewMouseMove += (_, e) =>
            {
                if (!pressed || e.LeftButton != MouseButtonState.Pressed) { pressed = false; return; }
                var p = e.GetPosition(this);
                if (!dragging && (Math.Abs(p.X - start.X) > 6 || Math.Abs(p.Y - start.Y) > 6))
                {
                    dragging = true;
                    tile.CaptureMouse();
                    ghost = new Popup
                    {
                        AllowsTransparency = true, Placement = PlacementMode.Relative, PlacementTarget = this, IsHitTestVisible = false,
                        Child = DragGhost(label, icon?.Invoke()),
                    };
                    ghost.IsOpen = true;
                    StartEdgeScroll(() => dragging);
                }
                if (dragging && ghost != null)
                {
                    ghost.HorizontalOffset = p.X + 6;      // right at the pointer: the user sees what is being carried
                    ghost.VerticalOffset = p.Y + 6;
                    Mouse.OverrideCursor = viewDrop && OverView(e) ? Cursors.Cross : Target(e) != null ? Cursors.Hand : Cursors.No;
                }
            };
            tile.PreviewMouseLeftButtonUp += async (_, e) =>
            {
                pressed = false;
                if (!dragging) return;
                dragging = false;
                e.Handled = true;                 // not a click
                tile.ReleaseMouseCapture();
                Mouse.OverrideCursor = null;
                if (ghost != null) { ghost.IsOpen = false; ghost = null; }
                if (Target(e) is string folder) { await onFolderDrop!(folder); return; }
                if (!viewDrop || !OverView(e)) return;
                var pos = e.GetPosition(_web);
                await onDrop(pos.X, pos.Y);
            };
            tile.LostMouseCapture += (_, __) =>
            {
                if (!dragging) return;
                dragging = false; pressed = false;
                Mouse.OverrideCursor = null;
                if (ghost != null) { ghost.IsOpen = false; ghost = null; }
            };
        }

        /// <summary>While something is dragged, the library scrolls by itself when the mouse is near its left or right
        /// edge (or past it, still at the height of the library): faster the closer to the edge. Tiles out of sight
        /// can be reached without letting go.</summary>
        void StartEdgeScroll(Func<bool> active)
        {
            if (_libraryScroller == null) return;
            var timer = new System.Windows.Threading.DispatcherTimer { Interval = TimeSpan.FromMilliseconds(16) };
            timer.Tick += (_, __) =>
            {
                var sv = _libraryScroller;
                if (!active() || sv == null || !sv.IsVisible) { timer.Stop(); return; }
                var p = Mouse.GetPosition(sv);
                if (p.Y < -20 || p.Y > sv.ActualHeight + 20) return;
                const double zone = 70;
                double speed = 0;
                if (p.X < zone) speed = -Math.Min(1, (zone - p.X) / zone);
                else if (p.X > sv.ActualWidth - zone) speed = Math.Min(1, (p.X - (sv.ActualWidth - zone)) / zone);
                if (speed != 0) sv.ScrollToHorizontalOffset(sv.HorizontalOffset + speed * 22);
            };
            timer.Start();
        }

        /// <summary>What follows the mouse while dragging: a small round picture of the material (when there is one) and its name.</summary>
        static Border DragGhost(string label, ImageSource? image)
        {
            var row = new StackPanel { Orientation = Orientation.Horizontal };
            if (image != null)
            {
                var ball = new System.Windows.Shapes.Ellipse
                {
                    Width = 30, Height = 30, Margin = new Thickness(0, 0, 8, 0), Stroke = Theme.B(Theme.Accent), StrokeThickness = 1,
                    Fill = new ImageBrush(image) { Stretch = Stretch.UniformToFill },
                };
                row.Children.Add(ball);
            }
            var t = Theme.Label(label, 12, Theme.Text);
            t.VerticalAlignment = VerticalAlignment.Center;
            row.Children.Add(t);
            return new Border
            {
                Background = Theme.B("#E01A2B4C"), BorderBrush = Theme.B(Theme.Accent), BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(image != null ? 18 : 6), Padding = image != null ? new Thickness(3, 3, 10, 3) : new Thickness(8, 4, 8, 4),
                Child = row,
            };
        }

        bool OverView(MouseEventArgs e)
        {
            if (_web == null || !_webReady) return false;
            var p = e.GetPosition(_web);
            return p.X >= 0 && p.Y >= 0 && p.X <= _web.ActualWidth && p.Y <= _web.ActualHeight;
        }

        /// <summary>A material tile dropped on the view: on the piece under the mouse (that slot), Shift on the whole group.</summary>
        string? _assignReplace;    // material/assign on a distribution: only the surfaces with this material

        // how a dropped material is applied (as in Twinmotion): on the object under the mouse, in place of its material
        // everywhere, or on every selected object
        static readonly (string id, string label, string tip, Geometry icon)[] DropModes =
        {
            ("object", "Applica all'oggetto", "Il materiale va solo sull'oggetto (la superficie) dove lo lasci", Icons.Mesh),
            ("replace", "Sostituisci il materiale", "Il materiale prende il posto di quello sotto il mouse su tutti gli oggetti che lo usano", Icons.Refresh),
            ("replacesel", "Sostituisci nella selezione", "Il materiale prende il posto di quello sotto il mouse solo negli oggetti selezionati e nei loro pezzi (niente selezionato: nel modello dove lo lasci); gli altri modelli con lo stesso materiale restano com'erano", Icons.Layers),
            ("selection", "Applica alla selezione", "Il materiale va su tutti gli oggetti selezionati, dovunque lo lasci nella vista", Icons.Frame),
        };
        string _dropMode = Settings.Load().DropMode is string dm && DropModes.Any(m => m.id == dm) ? dm : "object";
        Button? _dropModeButton;

        Button DropModePicker()
        {
            var b = Theme.Button("", Theme.Kind.Ghost, null);
            b.MinHeight = 30; b.Padding = new Thickness(8, 0, 8, 0); b.Margin = new Thickness(10, 0, 0, 0);
            void Face()
            {
                var m = DropModes.First(x => x.id == _dropMode);
                var sp = Theme.IconText(m.icon, L.T(m.label) + " ▾", Theme.Accent, 15);
                ((TextBlock)sp.Children[1]).FontSize = 12;
                b.Content = sp;
                b.ToolTip = L.T("Come si applica un materiale trascinato nella vista") + "\n" + L.T(m.tip);
            }
            Face();
            b.Click += (_, __) =>
            {
                var cm = new ContextMenu { PlacementTarget = b, Placement = System.Windows.Controls.Primitives.PlacementMode.Bottom };
                foreach (var m in DropModes)
                {
                    var row = Theme.IconText(m.icon, L.T(m.label), m.id == _dropMode ? Theme.Accent : Theme.TextSoft, 16);
                    var mi = new MenuItem { Header = row, ToolTip = L.T(m.tip), FontWeight = m.id == _dropMode ? FontWeights.SemiBold : FontWeights.Normal };
                    var id = m.id;
                    mi.Click += (_, __) =>
                    {
                        _dropMode = id;
                        var s = Settings.Load(); s.DropMode = id; s.Save();
                        Face();
                        Status(L.T(DropModes.First(x => x.id == id).tip));
                    };
                    cm.Items.Add(mi);
                }
                cm.IsOpen = true;
            };
            _dropModeButton = b;
            return b;
        }

        /// <summary>The model a piece belongs to: its library model, or else the imported file it comes from.</summary>
        string ModelRootOf(string id)
        {
            if (!_scene.ById.TryGetValue(id, out var o)) return id;
            var chain = new[] { o }.Concat(_scene.Ancestors(o)).ToList();
            var lib = chain.LastOrDefault(x => x.PaintModel != "" || x.OpenModel);
            if (lib != null) return lib.Id;
            // an imported model: the imported file it comes from (one import = one model); else the piece itself
            var file = chain.FirstOrDefault(x => x.Kind == "file");
            return file?.Id ?? id;
        }

        /// <summary>Material "under" (the one under the mouse) becomes "with" on every object that uses it.</summary>
        string[]? _replaceScope;   // «Sostituisci nella selezione»: only inside these objects (null: everywhere)

        async Task ReplaceMaterialEverywhere(string under, string with, bool preset, string label)
        {
            JsonObject? r = null;
            var scope = _replaceScope;
            await Run(async api =>
            {
                var body = new JsonObject { ["name"] = under, ["with"] = with, ["preset"] = preset };
                if (scope != null) body["ids"] = new JsonArray(scope.Select(x => (JsonNode?)x).ToArray());
                r = await api.Post("material/replace", body);
                UpdateHistory(await api.Get("history"));
            });
            if (r == null) return;
            Status(L.F("{0} al posto di {1} su {2} oggetti", (string?)r["material"] ?? label, under, (int?)r["replaced"] ?? 0));
            await RefreshScene();
            await PushMaterialToViewer((string?)r["material"] ?? label);
        }

        async Task DropMaterial(double x, double y, Func<string[], int?, Task> assign, Func<string, Task>? replaceWith = null)
        {
            if (_dropMode == "selection")
            {
                var sel = _selection.Where(s => _scene.ById.ContainsKey(s)).ToArray();
                if (sel.Length == 0) { Status(L.T("Applica alla selezione: prima seleziona gli oggetti"), true); return; }
                await assign(sel, null);
                return;
            }
            var at = await AskViewPoint(x, y);
            var id = (string?)at?["objectId"] ?? "";
            if (id == "" || !(bool?)at?["hit"] == true) { Status(L.T("Lascia il materiale sopra un oggetto"), true); return; }
            if ((_dropMode == "replace" || _dropMode == "replacesel") && replaceWith != null)
            {
                var under = (string?)at?["material"] ?? "";
                if (under == "" && _scene.ById.TryGetValue(id, out var ro) && ro.Materials.Count > 0) under = ro.Materials[0];
                if (under != "")
                {
                    // in the selection: the selected objects (a model selected = all its pieces); nothing selected,
                    // or a selection elsewhere: the model under the mouse
                    _replaceScope = null;
                    if (_dropMode == "replacesel")
                    {
                        var sel = _selection.Where(s => _scene.ById.ContainsKey(s)).ToList();
                        bool inside = sel.Any(s => s == id || (_scene.ById.TryGetValue(id, out var ho) && _scene.Ancestors(ho).Any(a => a.Id == s)));
                        _replaceScope = inside ? sel.ToArray() : new[] { ModelRootOf(id) };
                    }
                    try { await replaceWith(under); } finally { _replaceScope = null; }
                    return;
                }
            }
            var whole = (Keyboard.Modifiers & ModifierKeys.Shift) != 0;
            int? slot = null;
            _assignReplace = null;
            if (_scene.ById.TryGetValue(id, out var dist) && dist.Paint)
            {
                // a piece of a distribution: its models get the material, on the surfaces that had the one under the
                // mouse (Shift: every surface of the models)
                _assignReplace = whole ? null : (string?)at?["material"];
                await assign(new[] { id }, null);
                _assignReplace = null;
                return;
            }
            if (!whole && _scene.ById.TryGetValue(id, out var o))
            {
                var mat = (string?)at?["material"] ?? "";
                var i = o.Materials.IndexOf(mat);
                if (i >= 0 && o.Materials.Count > 1) slot = i;
                if (i < 0 && mat != "" && HasMaterialBelow(o, mat))
                {
                    // a library model is hit as a whole (the view draws it from its prototype): only its parts with the
                    // material under the mouse get the new one (e.g. the leaves, not the pot) - Shift: the whole model
                    _assignReplace = mat;
                    await assign(new[] { id }, null);
                    _assignReplace = null;
                    return;
                }
            }
            if (whole && _scene.ById.TryGetValue(id, out var obj))
            {
                var top = _scene.Ancestors(obj).LastOrDefault(a => a.Kind != "file") ?? obj;
                id = top.Id;
            }
            await assign(new[] { id }, slot);
        }

        static bool HasMaterialBelow(SceneObject o, string mat) => o.Children.Any(c => c.Materials.Contains(mat) || HasMaterialBelow(c, mat));

        // ---------------------------------------------------------------- Poly Haven

        void RenderPolyHaven()
        {
            if (_phAssets.Count == 0)
            {
                var wait = Theme.Label(L.T("Caricamento dell'elenco delle texture di Poly Haven…"), 12, Theme.TextFaint);
                wait.Margin = new Thickness(10);
                _libraryTiles.Children.Add(wait);
                _ = LoadPolyHaven();
                return;
            }
            RenderPolyHavenBrowser();
        }

        Button PolyHavenTile(JsonObject a)
        {
            var id = (string?)a["id"] ?? "";
            var label = (string?)a["name"] ?? id;
            var tile = new StackPanel { Width = 92, Margin = new Thickness(4, 0, 4, 0) };   // (no top/bottom margin: two-line names fit the 130 px tile)
            var img = new Border { Width = 72, Height = 72, CornerRadius = new CornerRadius(8),
                                   Background = Theme.B(Theme.Inset) };
            var downloaded = (bool?)a["downloaded"] ?? false;
            tile.Children.Add(WithBadge(img, 72, "t:" + id, downloaded, new Thickness(0, 2, 0, 6)));
            tile.Children.Add(Theme.TileText(new TextBlock { Text = label, FontSize = 11.5, TextAlignment = TextAlignment.Center, TextWrapping = TextWrapping.Wrap,
                                              Foreground = Theme.B(downloaded ? Theme.TextSoft : Theme.TextMuted), MaxHeight = 32 }));
            var size = (double?)a["sizeMm"] ?? 0;
            var tip = label + " · " + ((string?)a["category"] ?? "") + (size > 0 ? " · " + L.F("{0} m", Num.F(size / 1000.0, 1)) : "") +
                      "\n" + (downloaded ? L.T("Già scaricata") : L.T("Si scarica al primo uso (2K, qualche decina di MB)")) + "\nPoly Haven · CC0";
            var btn = Theme.Button(tile, Theme.Kind.Normal, tip);
            btn.Padding = new Thickness(2, 4, 2, 6);
            btn.Margin = new Thickness(4);
            btn.VerticalContentAlignment = VerticalAlignment.Top;
            btn.Height = 130;
            btn.Click += async (_, __) => await ApplyPolyHaven(id, label, Array.Empty<string>(), null, edit: true);   // click = open in the editor
            MakeDraggable(btn, label, async (x, y) => await DropMaterial(x, y, async (ids, slot) => await ApplyPolyHaven(id, label, ids, slot)),
                          icon: () => _phThumbs.TryGetValue(id, out var th) ? th : null);
            _ = LoadPhThumb(id, img, (bool?)a["hasThumb"] ?? false);
            return Fav(btn, "phmaterial", id, label, a);
        }

        async Task LoadPolyHaven()
        {
            for (int attempt = 0; attempt < 40; attempt++)
            {
                JsonObject? r = null;
                try { if (_api != null) r = await _api.Get("library/list"); } catch { }
                var list = r?["assets"] as JsonArray;
                if (list != null && list.Count > 0)
                {
                    _phAssets = (JsonArray)list.DeepClone();
                    if (_libraryTab == "polyhaven") RenderLibrary();
                    return;
                }
                if (r != null && !((bool?)r["loading"] ?? false) && (string?)r["error"] is string err && err != "")
                {
                    if (_libraryTab == "polyhaven")
                    {
                        _libraryTiles.Children.Clear();
                        var t = Theme.Label(L.T("Poly Haven non raggiungibile (serve la connessione a Internet): ") + err, 12, Theme.Danger);
                        t.Margin = new Thickness(10);
                        _libraryTiles.Children.Add(t);
                    }
                    return;
                }
                await Task.Delay(1000);
            }
        }

        async Task LoadPhThumb(string id, Border target, bool ready)
        {
            if (!_phThumbs.TryGetValue(id, out var bmp))
            {
                for (int i = 0; i < (ready ? 1 : 30) && bmp == null; i++)
                {
                    try
                    {
                        var bytes = await TexHttp.GetByteArrayAsync($"http://127.0.0.1:{_host.Port}/api/library/thumb?id={Uri.EscapeDataString(id)}");
                        var b = new BitmapImage();
                        b.BeginInit(); b.CacheOption = BitmapCacheOption.OnLoad; b.DecodePixelWidth = 96;
                        b.StreamSource = new System.IO.MemoryStream(bytes); b.EndInit(); b.Freeze();
                        bmp = b;
                        _phThumbs[id] = b;
                    }
                    catch { await Task.Delay(2000); }
                }
                if (bmp == null) return;
            }
            target.Background = new ImageBrush(bmp) { Stretch = Stretch.UniformToFill };
        }

        async Task ApplyPolyHaven(string id, string label, string[] ids, int? slot, bool edit = false)
        {
            if (_api == null) return;
            // download (first use) with progress in the status bar, then the material
            if (!await PolyHavenDownload("library", id, label)) return;
            JsonObject? r = null;
            await Run(async api => { r = await api.Post("library/apply", new JsonObject { ["id"] = id, ["ids"] = new JsonArray(ids.Select(x => (JsonNode)x!).ToArray()), ["slot"] = slot }); });
            if (r == null) return;
            if (edit)
            {
                await OpenMaterialEditor((string?)r["material"] ?? "");
                return;
            }
            Status(L.F("{0} applicato a {1} superfici · Poly Haven", (string?)r["material"] ?? label, (int?)r["assigned"] ?? 0));
            var a = _phAssets.OfType<JsonObject>().FirstOrDefault(x => (string?)x["id"] == id);
            if (a != null) a["downloaded"] = true;
            ShowBadge("t:" + id);
            await RefreshScene();
            await PushMaterialToViewer((string?)r["material"] ?? "");
        }
    }
}
