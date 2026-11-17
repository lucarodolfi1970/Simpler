using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;
using System.Windows.Threading;

namespace Simpler
{
    /// <summary>
    /// Favourites of the library: any 3D model, material, decal, HDRI (or studio background) or ecosystem can be
    /// marked from its right-click menu. They are the user's, not the project's (favorites.json next to the settings),
    /// shown with a small black heart on the thumbnail wherever the item appears, and gathered in the «Preferiti» menu
    /// in folders by kind (the plants in their own). A favourite tile works as the original (click, drag, its menu) and has «Porta
    /// all'elemento»: the tab and the folder of the original open, the tile comes into view and flashes.
    /// </summary>
    public sealed partial class MainWindow
    {
        sealed class FavItem { public string Kind = "", Id = "", Name = ""; public JsonObject? Node; }

        static string FavFile => System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Simpler", "favorites.json");
        List<FavItem>? _favs;
        string _favFolder = "";
        readonly Dictionary<string, Button> _favTiles = new();              // kind|id -> the tile shown now
        readonly Dictionary<string, List<FrameworkElement>> _favHearts = new();

        // the folders: (group, label, icon); (1.79, Luca) the plants in their own green folder after the models
        static readonly (string group, string label, Geometry icon)[] FavGroups =
        {
            ("models", "Modelli 3D", Icons.Mesh), ("vegetation", "Vegetazione", Icons.Leaf),
            ("materials", "Materiali", Icons.MatStandard), ("decals", "Decal", Icons.Image),
            ("hdri", "HDRI e sfondi", Icons.Globe), ("ecosystems", "Ecosistemi", Icons.Grass),
        };
        static string FavGroupLabel(string group)
        {
            var g = FavGroups.First(x => x.group == group);
            return group == "decals" ? (L.Lang == "en" ? "Decals" : "Decal") : L.T(g.label);
        }
        static readonly Color FavGreen = Color.FromRgb(0x6C, 0xC0, 0x5A);

        /// <summary>A model in the Vegetation folders goes in the «Vegetazione» folder of the favourites.</summary>
        string FavGroupOf(string kind, string id, JsonObject? node)
        {
            if (kind == "model")
            {
                var m = _models.OfType<JsonObject>().FirstOrDefault(o => (string?)o["id"] == id) ?? node;
                if (IsVegFolder((string?)m?["folder"] ?? "")) return "vegetation";
            }
            return FavGroupOf(kind);
        }
        string FavGroupOf(FavItem f) => FavGroupOf(f.Kind, f.Id, f.Node);

        static string FavGroupOf(string kind) => kind switch
        {
            "model" or "phmodel" => "models",
            "material" or "phmaterial" => "materials",
            "decal" or "acgdecal" => "decals",
            "hdri" or "studio" => "hdri",
            _ => "ecosystems",
        };

        List<FavItem> Favs
        {
            get
            {
                if (_favs != null) return _favs;
                _favs = new List<FavItem>();
                try
                {
                    if (File.Exists(FavFile) && JsonNode.Parse(File.ReadAllText(FavFile)) is JsonArray arr)
                        foreach (var o in arr.OfType<JsonObject>())
                            _favs.Add(new FavItem { Kind = (string?)o["kind"] ?? "", Id = (string?)o["id"] ?? "", Name = (string?)o["name"] ?? "", Node = o["node"]?.DeepClone() as JsonObject });
                }
                catch (Exception ex) { AppLog.Write("favourites not read: " + ex.Message); }
                _favs.RemoveAll(f => f.Kind == "" || f.Id == "");
                return _favs;
            }
        }

        void SaveFavs()
        {
            try
            {
                Directory.CreateDirectory(System.IO.Path.GetDirectoryName(FavFile)!);
                var arr = new JsonArray(Favs.Select(f => (JsonNode)new JsonObject
                {
                    ["kind"] = f.Kind, ["id"] = f.Id, ["name"] = f.Name, ["node"] = f.Node?.DeepClone(),
                }).ToArray());
                File.WriteAllText(FavFile, arr.ToJsonString(new System.Text.Json.JsonSerializerOptions { WriteIndented = true }));
            }
            catch (Exception ex) { AppLog.Write("favourites not saved: " + ex.Message); }
        }

        bool IsFav(string kind, string id) => Favs.Any(f => f.Kind == kind && f.Id == id);

        void ToggleFav(string kind, string id, string name, JsonObject? node)
        {
            var key = kind + "|" + id;
            var on = !IsFav(kind, id);
            if (on) Favs.Add(new FavItem { Kind = kind, Id = id, Name = name, Node = node?.DeepClone() as JsonObject });
            else Favs.RemoveAll(f => f.Kind == kind && f.Id == id);
            SaveFavs();
            if (_favHearts.TryGetValue(key, out var hearts))
                foreach (var h in hearts) h.Visibility = on ? Visibility.Visible : Visibility.Collapsed;
            Status(on ? L.F("«{0}» aggiunto ai preferiti ({1})", name, FavGroupLabel(FavGroupOf(kind, id, node)))
                      : L.F("«{0}» tolto dai preferiti", name));
            if (_libraryTab == "favorites") RenderLibrary();
        }

        /// <summary>The small heart: black with a thin white outline.</summary>
        static FrameworkElement HeartMark(double size = 15)
        {
            var p = new System.Windows.Shapes.Path
            {
                Data = Geometry.Parse("M12,21 C12,21 2.5,14.6 2.5,8.4 C2.5,5.4 4.9,3 7.9,3 C9.7,3 11.2,3.9 12,5.3 C12.8,3.9 14.3,3 16.1,3 C19.1,3 21.5,5.4 21.5,8.4 C21.5,14.6 12,21 12,21 Z"),
                Fill = Brushes.Black, Stroke = Brushes.White, StrokeThickness = 1.6, Stretch = Stretch.Uniform,
                Width = size, Height = size, IsHitTestVisible = false,
                HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Top, Margin = new Thickness(0, 4, 4, 0),
            };
            p.Effect = new System.Windows.Media.Effects.DropShadowEffect { BlurRadius = 3, ShadowDepth = 0, Opacity = 0.6, Color = Colors.Black };
            return p;
        }

        /// <summary>Called by every library tile that can be a favourite: the heart on its thumbnail, and in its menu
        /// «Aggiungi ai preferiti» / «Togli dai preferiti» (and in the favourites «Porta all'elemento»).</summary>
        Button Fav(Button btn, string kind, string id, string name, JsonObject? node)
        {
            if (id == "") return btn;
            var key = kind + "|" + id;
            _favTiles[key] = btn;
            // the heart sits on the thumbnail (the first element of the tile)
            if (btn.Content is Panel tile && tile.Children.Count > 0 && tile.Children[0] is FrameworkElement visual)
            {
                var holder = new Grid { HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = visual.VerticalAlignment, Margin = visual.Margin };
                visual.Margin = new Thickness(0);
                tile.Children.RemoveAt(0);
                holder.Children.Add(visual);
                var heart = HeartMark();
                heart.Visibility = IsFav(kind, id) ? Visibility.Visible : Visibility.Collapsed;
                holder.Children.Add(heart);
                tile.Children.Insert(0, holder);
                // (1.76.31, Luca) the tick of «già scaricato» sits in the same corner: with the heart on, it moves to
                // its left, so both show
                if (visual is Panel pv && pv.Children.OfType<Border>().FirstOrDefault(b => (b.Tag as string) == "dl-tick") is Border tick)
                {
                    void Place() => tick.Margin = heart.Visibility == Visibility.Visible ? new Thickness(0, 3, 22, 0) : new Thickness(0, 3, 3, 0);
                    Place();
                    heart.IsVisibleChanged += (_, __) => Place();
                }
                if (!_favHearts.TryGetValue(key, out var list)) _favHearts[key] = list = new List<FrameworkElement>();
                list.Add(heart);
            }
            var menu = btn.ContextMenu ?? new ContextMenu();
            btn.ContextMenu = menu;
            int at = 0;
            if (_libraryTab == "favorites")
            {
                var go = new MenuItem { Header = L.T("Porta all'elemento"), ToolTip = L.T("Apre la cartella della libreria dove si trova l'originale") };
                go.Click += (_, __) => GoToFav(kind, id);
                menu.Items.Insert(at++, go);
            }
            var toggle = new MenuItem();
            toggle.Click += (_, __) => ToggleFav(kind, id, name, node);
            menu.Items.Insert(at++, toggle);
            menu.Items.Insert(at, new Separator());
            void Header() => toggle.Header = IsFav(kind, id) ? L.T("Togli dai preferiti") : L.T("Aggiungi ai preferiti");
            Header();
            menu.Opened += (_, __) => Header();
            return btn;
        }

        // ---------------------------------------------------------------- the «Preferiti» menu

        void RenderFavorites()
        {
            var q = LibraryQuery;
            if (q != "")
            {
                RenderCrumbs(L.T("Preferiti"), "", f => { _favFolder = ""; _librarySearch.Text = ""; }, L.F("risultati per \"{0}\"", _librarySearch.Text.Trim()));
                _dropFolders.Clear();
                var n = 0;
                foreach (var f in Favs.Where(f => f.Name.ToLowerInvariant().Contains(q)).ToList())
                    if (FavTile(f) is Button b) { _libraryTiles.Children.Add(b); n++; }
                if (n == 0) _libraryTiles.Children.Add(EmptyNote(L.T("Nessun preferito trovato")));
                return;
            }
            if (_favFolder == "" || (!FavGroups.Any(g => g.group == _favFolder) && _favFolder != "luts"))
            {
                _favFolder = "";
                RenderCrumbs(L.T("Preferiti"), "", f => _favFolder = "", null);
                _dropFolders.Clear();
                foreach (var (group, _, icon) in FavGroups)
                {
                    var count = Favs.Count(f => FavGroupOf(f) == group);
                    _libraryTiles.Children.Add(FavFolderTile(group, icon, count));
                }
                // the folders of the effects: black, the icon in the warm colour (the opposite of the others)
                if (_luts == null) _ = LoadLuts();
                _libraryTiles.Children.Add(FavFolderTile("luts", LutIcon, LutFavs().Count, effects: true));
                return;
            }
            if (_favFolder == "luts")
            {
                RenderCrumbs(L.T("Preferiti"), L.T("Look (LUT)"), f => { if (f == "") _favFolder = ""; }, null);
                _dropFolders.Clear();
                _libraryTiles.Children.Add(UpTile("", f => _favFolder = "", false));
                var luts = LutFavs();
                foreach (var it in luts) _libraryTiles.Children.Add(LutTile(it));
                if (luts.Count == 0)
                    _libraryTiles.Children.Add(EmptyNote(L.T("Ancora nessun look preferito: nel pannello Render ▸ Colore ed esposizione ▸ Look, tasto destro su un look ▸ «Aggiungi ai preferiti»")));
                return;
            }
            var label = FavGroupLabel(_favFolder);
            RenderCrumbs(L.T("Preferiti"), label, f => { if (f == "") _favFolder = ""; }, null);
            _dropFolders.Clear();                      // (nothing is moved into the favourites by dragging)
            _libraryTiles.Children.Add(UpTile("", f => _favFolder = "", false));
            var shown = 0;
            var gone = new List<FavItem>();
            foreach (var f in Favs.Where(f => FavGroupOf(f) == _favFolder).ToList())
            {
                var b = FavTile(f, gone);
                if (b == null) continue;
                _libraryTiles.Children.Add(b);
                shown++;
            }
            if (gone.Count > 0) { foreach (var g in gone) Favs.Remove(g); SaveFavs(); }
            if (shown == 0)
                _libraryTiles.Children.Add(EmptyNote(L.T("Ancora nessun preferito qui: tasto destro su un elemento della libreria ▸ «Aggiungi ai preferiti»")));
        }

        /// <summary>A folder of the favourites: a folder filled in the warm colour with a black outline, the icon of
        /// its kind in the middle.
        /// effects: a folder of effects (looks...): black, the outline and the icon in the warm colour.</summary>
        Button FavFolderTile(string group, Geometry icon, int count, bool effects = false)
        {
            var g = new Grid { Width = 64, Height = 54, Margin = new Thickness(0, 8, 0, 8), HorizontalAlignment = HorizontalAlignment.Center };
            g.Children.Add(new System.Windows.Shapes.Path
            {
                Data = Geometry.Parse("M2,6.5 C2,5.4 2.9,4.5 4,4.5 L9.2,4.5 L11.4,7 L20,7 C21.1,7 22,7.9 22,9 L22,18.5 C22,19.6 21.1,20.5 20,20.5 L4,20.5 C2.9,20.5 2,19.6 2,18.5 Z"),
                Fill = effects ? Brushes.Black : new SolidColorBrush(group == "vegetation" ? FavGreen : Theme.Warm), Stroke = effects ? new SolidColorBrush(Theme.Warm) : Brushes.Black,
                StrokeThickness = 1.3, Stretch = Stretch.Fill, StrokeLineJoin = PenLineJoin.Round,
            });
            var ic = Theme.Icon(icon, effects ? Theme.Warm : Colors.Black, 22, 1.9);
            ic.HorizontalAlignment = HorizontalAlignment.Center;
            ic.VerticalAlignment = VerticalAlignment.Center;
            ic.Margin = new Thickness(0, 7, 0, 0);
            g.Children.Add(ic);
            var label = group == "luts" ? L.T("Look (LUT)") : FavGroupLabel(group);
            var btn = BigTile(g, label, count == 1 ? L.T("1 preferito") : L.F("{0} preferiti", count), label + "\n" + L.T("Clic per aprire"));
            btn.Click += (_, __) => { _favFolder = group; RenderLibrary(); };
            return btn;
        }

        /// <summary>The tile of a favourite, made by the library it comes from (so it behaves as the original). Lists not
        /// loaded yet (Poly Haven, ambientCG, HDRI): the copy kept with the favourite. Items deleted from the library: null
        /// (and the favourite goes).</summary>
        Button? FavTile(FavItem f, List<FavItem>? gone = null)
        {
            JsonObject? Live(JsonArray list) => list.OfType<JsonObject>().FirstOrDefault(o => (string?)o["id"] == f.Id);
            switch (f.Kind)
            {
                case "model":
                {
                    var m = Live(_models);
                    if (m == null) { if (_models.Count > 0) gone?.Add(f); return null; }
                    return ModelTile(m);
                }
                case "phmodel":
                {
                    if (_phmAssets.Count == 0 && !_phmLoading) _ = LoadPhModels();
                    var a = Live(_phmAssets) ?? f.Node;
                    return a == null ? null : PhModelTile(a);
                }
                case "material":
                {
                    var m = Live(_materials);
                    if (m == null) { if (_materials.Count > 0) gone?.Add(f); return null; }
                    return LibraryTile(m, true);
                }
                case "phmaterial":
                {
                    if (_phAssets.Count == 0) _ = LoadPolyHaven();
                    var a = Live(_phAssets) ?? f.Node;
                    return a == null ? null : PolyHavenTile(a);
                }
                case "decal":
                    if (!File.Exists(f.Id)) { gone?.Add(f); return null; }
                    return DecalTile(f.Id);
                case "acgdecal":
                {
                    if (_acgDecals.Count == 0) _ = LoadAcgDecals();
                    var a = Live(_acgDecals) ?? f.Node;
                    return a == null ? null : AcgDecalTile(a);
                }
                case "hdri":
                {
                    if (_hdris.Count == 0) _ = LoadHdris();
                    var a = Live(_hdris) ?? f.Node;
                    return a == null ? null : HdriTile(a);
                }
                case "studio":
                {
                    var e = Live(_environments) ?? f.Node;
                    return e == null ? null : LibraryTile(e, false);
                }
                case "eco":
                {
                    if (!_ecoLoaded) { _ecoLoaded = true; _ = LoadEcosystems().ContinueWith(_ => Dispatcher.Invoke(() => { if (_libraryTab == "favorites") RenderLibrary(); })); }
                    var e = Live(_ecosystems);
                    if (e == null) { if (_ecosystems.Count > 0) gone?.Add(f); return null; }
                    return EcoTile(e);
                }
            }
            return null;
        }

        /// <summary>«Porta all'elemento»: the tab and the folder of the original, its tile in view, flashing.</summary>
        void GoToFav(string kind, string id)
        {
            var f = Favs.FirstOrDefault(x => x.Kind == kind && x.Id == id);
            JsonObject? Find(JsonArray list) => list.OfType<JsonObject>().FirstOrDefault(o => (string?)o["id"] == id) ?? f?.Node;
            string Folder(JsonObject? n) => (string?)n?["folder"] ?? "";
            string tab;
            switch (kind)
            {
                case "model":
                {
                    tab = ModelTabFor(Folder(Find(_models)), true);        // (1.78.0) a plant: in Vegetazione
                    break;
                }
                case "phmodel": tab = "phmodels"; _phmFolder = Folder(Find(_phmAssets)); break;
                case "material":
                {
                    var m = Find(_materials);
                    var fo = Folder(m);
                    tab = m != null && InSimplerMats(m) ? "simplermats" : "mymaterials";
                    _matFolder = fo;
                    break;
                }
                case "phmaterial": tab = "polyhaven"; _phFolder = Folder(Find(_phAssets)); break;
                case "decal":
                {
                    _decalFolder = DecalRel(id);
                    tab = InSimplerDecals(_decalFolder) ? "simplerdecals" : "mydecals";
                    break;
                }
                case "acgdecal": tab = "acgdecals"; _acgFolder = Folder(Find(_acgDecals)); break;
                case "hdri": tab = "hdri"; _hdriFolder = Folder(Find(_hdris)); break;
                case "studio": tab = "hdri"; _hdriFolder = L.T("Sfondi da studio"); break;
                default:
                {
                    var fo = Folder(Find(_ecosystems));
                    tab = Under(fo, SimplerEco) ? "simplereco" : "ecosystems";      // (1.79) Simpler or I miei
                    if (tab == "simplereco") _ecoSimFolder = fo; else _ecoMineFolder = fo;
                    break;
                }
            }
            if (_librarySearch.Text != "") _librarySearch.Text = "";
            ShowLibraryTab(tab);
            var key = kind + "|" + id;
            Dispatcher.BeginInvoke(DispatcherPriority.Loaded, () =>
            {
                if (_favTiles.TryGetValue(key, out var b) && b.IsLoaded) { b.BringIntoView(); FlashTile(b); }
                else Status(L.T("La cartella si sta ancora caricando: l'elemento compare tra un momento"));
            });
        }

        static void FlashTile(Button b)
        {
            var brush = b.BorderBrush;
            var thick = b.BorderThickness;
            b.BorderBrush = new SolidColorBrush(Color.FromRgb(0xF0, 0x8A, 0x24));
            b.BorderThickness = new Thickness(2);
            var t = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(1800) };
            t.Tick += (_, __) => { t.Stop(); b.BorderBrush = brush; b.BorderThickness = thick; };
            t.Start();
        }
    }
}
