using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;

namespace Simpler
{
    /// <summary>
    /// The bottom library as a small file system: folders (nested) with materials inside, a path bar to go back,
    /// drag a material onto a folder to move it. The user's materials and the built-in ones can be organised freely;
    /// Poly Haven textures are grouped by their category (read only). Typing in the search box looks in every folder.
    /// </summary>
    public sealed partial class MainWindow
    {
        string _matFolder = "", _phFolder = "";
        List<string> _materialFolders = new();
        StackPanel _libraryCrumbs = null!;
        ScrollViewer _libraryCrumbScroll = null!;
        readonly List<(FrameworkElement el, string folder)> _dropFolders = new();

        string LibraryQuery => (_librarySearch?.Text ?? "").Trim().ToLowerInvariant();

        static string ParentFolder(string f) => f.Contains('/') ? f[..f.LastIndexOf('/')] : "";
        static string FolderName(string f) => f.Contains('/') ? f[(f.LastIndexOf('/') + 1)..] : f;
        static bool InFolder(string item, string folder) => item == folder || item.StartsWith(folder + "/", StringComparison.Ordinal);

        void SetLibraryMaterials(JsonObject? r)
        {
            _materials = r?["materials"] as JsonArray ?? new JsonArray();
            _materialFolders = (r?["folders"] as JsonArray)?.Select(x => (string?)x ?? "").Where(x => x != "").ToList() ?? new List<string>();
        }

        // ---------------------------------------------------------------- materials

        /// <summary>Materials of the library: those that come with Simpler (mine = false; also when you edited them) or
        /// the ones you made (mine = true). The folders are shared: each view shows the folders with something of its own
        /// (and, among yours, also the empty ones you made).</summary>
        const string SimplerMats = "Simpler";     // the materials that come with Simpler: a folder of Personali · Materiali

        static string FolderLabel(string f) => f == SimplerMats ? "Simpler" : f == PrimitiveFolder ? L.T("Primitive") : FolderName(f);

        /// <summary>(1.78.4) A material of Simpler: in the folder «Simpler» of the material library (a real folder,
        /// as Modelli 3D ▸ Simpler; red and read only with SimplerLocked).</summary>
        static bool InSimplerMatPath(string f) => f == SimplerMats || (f ?? "").StartsWith(SimplerMats + "/", StringComparison.Ordinal);
        static bool InSimplerMats(JsonObject m) { var f = (string?)m["folder"] ?? ""; return f == SimplerMats || f.StartsWith(SimplerMats + "/", StringComparison.Ordinal); }

        void RenderSimplerMaterials() => RenderMaterialBrowser(false);

        void RenderMaterialBrowser(bool mine)
        {
            var mats = _materials.OfType<JsonObject>().Where(m => InSimplerMats(m) != mine).ToList();
            var rootLabel = mine ? L.T("I miei materiali") : L.T("Materiali Simpler");
            var root = mine ? "" : SimplerMats;
            var ro = !mine && SimplerLocked;
            string Rel(string full) => mine || full == root ? (mine ? full : "") : full.Substring(root.Length + 1);
            string Full(string rel) => mine ? rel : rel == "" ? root : root + "/" + rel;
            var q = LibraryQuery;
            if (q != "")
            {
                // search: every folder at once
                RenderCrumbs(rootLabel, "", f => { _matFolder = Full(f); _librarySearch.Text = ""; }, L.F("risultati per \"{0}\"", _librarySearch.Text.Trim()), mine || ro ? null : root);
                int n = 0;
                foreach (var m in mats)
                {
                    var text = ((string?)m["name"] + " " + (string?)m["category"] + " " + (string?)m["folder"]).ToLowerInvariant();
                    if (!text.Contains(q)) continue;
                    _libraryTiles.Children.Add(LibraryTile(m, true));
                    n++;
                }
                if (n == 0) _libraryTiles.Children.Add(EmptyNote(L.T("Nessun materiale trovato")));
                return;
            }
            bool Here(string f) => mine ? !(f == SimplerMats || f.StartsWith(SimplerMats + "/", StringComparison.Ordinal)) : f == root || f.StartsWith(root + "/", StringComparison.Ordinal);
            var used = new HashSet<string>();
            foreach (var f in mats.Select(m => (string?)m["folder"] ?? "").Where(f => f != ""))
                for (var p = f; p != ""; p = ParentFolder(p)) used.Add(p);
            var all = _materialFolders.Where(f => Here(f) && f != root && (used.Contains(f) || !_materials.OfType<JsonObject>().Any(m => InFolder((string?)m["folder"] ?? "", f)))).ToList();
            if (_matFolder != root && !all.Contains(_matFolder)) _matFolder = root;
            RenderCrumbs(rootLabel, Rel(_matFolder), f => _matFolder = Full(f), null, mine || ro ? null : root);
            if (ro) _dropFolders.Clear();                     // (locked: nothing is dropped into the folders of Simpler)
            if (_matFolder != root) _libraryTiles.Children.Add(UpTile(ParentFolder(_matFolder), f => _matFolder = f, !ro));
            // (1.79, Luca: «perché new folder è in fondo a destra?») «Nuova cartella» first, with the tiles that add
            if (!ro) _libraryTiles.Children.Add(NewFolderTile("material", _matFolder));
            foreach (var f in all.Where(f => ParentFolder(f) == _matFolder).OrderBy(f => f, StringComparer.CurrentCultureIgnoreCase))
            {
                var count = mats.Count(m => InFolder((string?)m["folder"] ?? "", f));
                var ff = f;
                _libraryTiles.Children.Add(FolderTile(f, count, () => { _matFolder = ff; RenderLibrary(); }, ro ? "simplermat" : "material"));
            }
            foreach (var m in mats.Where(m => ((string?)m["folder"] ?? "") == _matFolder))
                _libraryTiles.Children.Add(LibraryTile(m, true));
            if (mine && mats.Count == 0)
                _libraryTiles.Children.Add(EmptyNote(L.T("Ancora nessun materiale tuo: nell'editor dei materiali usa «Salva nella libreria»")));
        }

        /// <summary>Path bar next to the search box: every piece is clickable (and a drop target for materials).</summary>
        void RenderCrumbs(string rootLabel, string path, Action<string> go, string? extra, string? dropRoot = null)
        {
            // dropRoot: the crumbs show a path inside this folder (Vegetazione): what is dropped on them goes to the full path
            _libraryCrumbs.Children.Clear();
            _libraryCrumbs.Visibility = Visibility.Visible;
            void Piece(string label, string target, bool last)
            {
                var b = Theme.Button(label, last ? Theme.Kind.Segment : Theme.Kind.Ghost);
                b.MinHeight = 26; b.Height = 26; b.FontSize = 12; b.Padding = new Thickness(8, 0, 8, 0);
                b.Click += (_, __) => { go(target); RenderLibrary(); };
                _libraryCrumbs.Children.Add(b);
                _dropFolders.Add((b, dropRoot == null ? target : target == "" ? dropRoot : dropRoot + "/" + target));
                if (!last)
                {
                    var sep = Theme.Icon(Icons.Chevron, Theme.TextFaint, 12, 1.6);
                    sep.VerticalAlignment = VerticalAlignment.Center;
                    sep.Margin = new Thickness(1, 0, 1, 0);
                    _libraryCrumbs.Children.Add(sep);
                }
            }
            var parts = path == "" ? Array.Empty<string>() : path.Split('/');
            Piece(rootLabel, "", parts.Length == 0 && extra == null);
            for (int i = 0; i < parts.Length; i++)
                Piece(parts[i], string.Join("/", parts.Take(i + 1)), i == parts.Length - 1 && extra == null);
            if (extra != null)
            {
                var t = Theme.Label(extra, 12, Theme.TextMuted);
                t.VerticalAlignment = VerticalAlignment.Center;
                t.Margin = new Thickness(8, 0, 0, 0);
                _libraryCrumbs.Children.Add(t);
                // (1.78.1) the results of a section: the same words in the whole library
                if (_libraryTab != "search" && LibraryQuery != "") _libraryCrumbs.Children.Add(GlobalSearchLink());
            }
            // (a path longer than the row: its end, the folder open now, stays in view)
            Dispatcher.BeginInvoke(new Action(() => _libraryCrumbScroll.ScrollToRightEnd()), System.Windows.Threading.DispatcherPriority.Loaded);
        }

        Button BigTile(UIElement visual, string label, string sub, string tip)
        {
            var tile = new StackPanel { Width = 92, Margin = new Thickness(4, 0, 4, 0) };   // (no top/bottom margin: two-line names fit the 130 px tile)
            tile.Children.Add(visual);
            tile.Children.Add(Theme.TileText(new TextBlock { Text = label, FontSize = 11.5, TextAlignment = TextAlignment.Center, TextWrapping = TextWrapping.Wrap,
                                              Foreground = Theme.B(Theme.TextSoft), MaxHeight = 32 }));
            if (sub != "")
                tile.Children.Add(new TextBlock { Text = sub, FontSize = 10.5, TextAlignment = TextAlignment.Center, Foreground = Theme.B(Theme.TextFaint) });
            var btn = Theme.Button(tile, Theme.Kind.Normal, tip);
            btn.Padding = new Thickness(2, 4, 2, 6);
            btn.Margin = new Thickness(4);
            btn.VerticalContentAlignment = VerticalAlignment.Top;
            btn.Height = 130;
            return btn;
        }

        /// <summary>(1.79.0, Luca: «tipizza le cartelle con delle icone, una bella icona evocativa nel centro, almeno per quelle
        /// della root») the icon drawn inside a folder of the first level, by the words of its name (Italian or English: the
        /// folders of Simpler and the user's); null when no word is known - a plain folder.</summary>
        static readonly (string[] keys, Geometry icon)[] FolderIcons =
        {
            (new[] { "interior", "interni" }, Icons.FWindow),
            (new[] { "architett", "architectur", "porte", "door", "finestr", "window", "stair" }, Icons.FDoor),
            (new[] { "street", "strada", "strade", "città", "citta", "city", "urban" }, Icons.FStreetLamp),
            (new[] { "animal", "fauna" }, Icons.FPaw),
            (new[] { "character", "person", "people", "personaggi", "crowd", "human", "umani" }, Icons.FPerson),
            (new[] { "furniture", "arredament", "arredi", "mobili", "sedute", "chair", "sofa", "divan" }, Icons.FSofa),
            (new[] { "garden", "giardin", "terrace", "terrazz", "esterni", "outdoor" }, Icons.FPlantPot),
            (new[] { "office", "uffic" }, Icons.FBriefcase),
            (new[] { "primitive" }, Icons.FCube),
            (new[] { "statue", "statu", "sculpt", "scultur" }, Icons.FBust),
            (new[] { "footprint", "impront", "orme", "passi" }, Icons.FPerson),
            (new[] { "tyre", "tire", "pneumat" }, Icons.Car),
            (new[] { "vehicle", "veicol", "cars", "auto" }, Icons.Car),
            (new[] { "flower", "fior", "perennial", "perenn" }, Icons.FFlower),
            (new[] { "shrub", "arbust", "cespugl", "hedge", "siep", "bush" }, Icons.FShrub),
            (new[] { "grass", "erba", "erbe", "prat", "lawn" }, Icons.Grass),
            (new[] { "tree", "alber", "wood", "bosc", "forest" }, Icons.FTree),
            (new[] { "terrain", "terren", "rock", "rocc", "pietr", "stone", "mountain", "montagn" }, Icons.FMountain),
            (new[] { "nature", "natura", "vegetation", "vegetaz", "plant", "piant" }, Icons.Leaf),
            (new[] { "fabric", "tessut", "cloth", "stoff" }, Icons.Cloth),
            (new[] { "gem", "gioiell", "jewel" }, Icons.Gem),
            (new[] { "glass", "vetr" }, Icons.Glass),
            (new[] { "light", "luci", "luce", "illumin", "lamp" }, Icons.Bulb),
            (new[] { "liquid", "water", "acqu" }, Icons.WaterDrop),
            (new[] { "metal" }, Icons.FIngot),
            (new[] { "paint", "vernic", "pittur" }, Icons.Brush),
            (new[] { "plastic", "rubber", "gomm" }, Icons.FBottle),
            (new[] { "surface", "superfic", "floor", "paviment", "wall", "muri", "pareti" }, Icons.Grid),
            (new[] { "volume", "fumo", "smoke", "nebbi" }, Icons.Cloud),
            (new[] { "cloud", "nuvol", "sky", "cielo" }, Icons.Cloud),
            (new[] { "building", "edific", "palazz", "house", "case" }, Icons.FBuilding),
            (new[] { "electronic", "elettron", "tech", "computer" }, Icons.Monitor),
            (new[] { "decor" }, Icons.Sparkles),
            (new[] { "package", "pacchett", "kitbash", "kit", "collection", "collezion" }, Icons.FBox),
            (new[] { "haven", "download", "scaricat" }, Icons.Globe),
            (new[] { "trash", "rifiut", "spazzatur", "garbage", "waste" }, Icons.FTrash),
            (new[] { "palm" }, Icons.FPalm),
            (new[] { "sci", "fantascien", "futur", "space", "spazio" }, Icons.FRocket),
            (new[] { "crack", "crepa", "crepe" }, Icons.FCrack),
            (new[] { "dirt", "grime", "sporc", "sudic" }, Icons.FGrime),
            (new[] { "graffit", "spray", "murales" }, Icons.FSpray),
            (new[] { "rust", "ruggin", "leak", "perdit", "corros" }, Icons.FRust),
            (new[] { "altro", "altri", "other", "misc", "vari" }, Icons.Dots),
        };

        static Geometry? FolderBadge(string name)
        {
            var words = System.Text.RegularExpressions.Regex.Split((name ?? "").ToLowerInvariant(), @"[^\p{L}]+").Where(w => w != "").ToArray();
            foreach (var (keys, icon) in FolderIcons)
                if (words.Any(w => keys.Any(k => w.StartsWith(k, StringComparison.Ordinal)))) return icon;
            return null;
        }

        /// <summary>A folder of the first level of a library (the user's, or inside Simpler, Vegetazione, Vegetazione ▸ Simpler):
        /// it gets its icon; the subfolders stay plain.</summary>
        bool FirstLevelFolder(string folder)
        {
            var parent = ParentFolder(folder);
            return parent == "" || parent == SimplerModels || parent == _vegRoot || parent == _vegRoot + "/" + SimplerModels;
        }

        /// <summary>The folder of a tile, with the icon of its kind inside when it has one.</summary>
        static FrameworkElement FolderIcon(Color c, Geometry? badge)
        {
            var ic = TileIcon(Icons.Folder, c);
            if (badge == null) return ic;
            var g = new Grid { HorizontalAlignment = HorizontalAlignment.Center, Margin = ic.Margin };
            ic.Margin = new Thickness(0);
            g.Children.Add(ic);
            var b = Theme.Icon(badge, c, 15, 1.6);
            b.HorizontalAlignment = HorizontalAlignment.Center;
            b.VerticalAlignment = VerticalAlignment.Center;
            b.Margin = new Thickness(0, 4, 0, 0);
            g.Children.Add(b);
            return g;
        }

        static FrameworkElement TileIcon(Geometry g, Color c)
        {
            var ic = Theme.Icon(g, c, 40, 1.5);
            ic.HorizontalAlignment = HorizontalAlignment.Center;
            ic.Margin = new Thickness(0, 16, 0, 12);
            return ic;
        }

        // scope of a folder: "material" and "model" (the user's, editable), "polyhaven" and "primitive" (fixed)
        static bool Editable(string scope) => scope is "material" or "model" or "eco";
        static string FolderEndpoint(string scope) => scope == "model" ? "models/folder" : scope == "eco" ? "ecosystems/folder" : "material/library/folder";
        async Task ReloadScope(string scope)
        {
            if (scope == "model") await ReloadModels();
            else if (scope == "eco") { await LoadEcosystems(); RenderLibrary(); }
            else await ReloadLibraryMaterials();
        }
        List<string> ScopeFolders(string scope) => scope == "model" ? _modelFolders : scope == "eco" ? _ecoFolders : _materialFolders;
        void SetScopeFolder(string scope, string f) { if (scope == "model" && _libraryTab == "packplants") _vegPackFolder = f; else if (scope == "model" && _libraryTab == "packmodels") _objPackFolder = f; else if (scope == "model" && _libraryTab == "myplants") _vegFolder = f; else if (scope == "model" && _libraryTab == "simplerplants") _vegSimFolder = f; else if (scope == "model" && _libraryTab == "primitives") _objSimFolder = f; else if (scope == "model") _objFolder = f; else if (scope == "eco") _ecoFolder = f; else _matFolder = f; }
        static string ScopeRoot(string scope) => scope == "model" ? L.T("Modelli 3D") : scope == "eco" ? L.T("Ecosistemi") : L.T("Materiali");

        Button FolderTile(string folder, int count, Action open, string scope, int downloaded = 0, bool counter = false, int updates = 0)
        {
            var sub = scope switch
            {
                "material" or "simplermat" => count == 1 ? L.T("1 materiale") : L.F("{0} materiali", count),
                "model" or "primitive" or "simplermodel" => count == 1 ? L.T("1 oggetto") : L.F("{0} oggetti", count),
                "eco" or "simplereco" => count == 1 ? L.T("1 ecosistema") : L.F("{0} ecosistemi", count),
                "phmodels" => count == 1 ? L.T("1 modello") : L.F("{0} modelli", count),
                "acgdecal" => count == 1 ? L.T("1 decal") : L.F("{0} decal", count),
                _ => count == 1 ? L.T("1 texture") : L.F("{0} texture", count),
            };
            var editable = Editable(scope);
            // Poly Haven folders: how many of their contents are already on disk (e.g. 3/88, in green)
            // the folders of Simpler (its materials, the primitives) are red: they cannot be changed and take no paste
            var locked = scope is "simplermat" or "primitive" or "simplermodel" or "simplereco";
            // (Luca) the folders of the packs are blue, locked or not: what a pack brought is seen at once
            FrameworkElement visual = FolderIcon(scope is "model" or "simplermodel" && IsPackFolder(folder) ? Theme.C("#4C9DFF") : locked ? Theme.C("#E5534B") : Theme.Warm,
                                                 FirstLevelFolder(folder) ? FolderBadge(FolderName(folder)) : null);
            if (downloaded > 0 || counter || updates > 0)          // (cloud) the red folders show «here/in all» also at 0
            {
                var g = new Grid();
                g.Children.Add(visual);
                if (updates > 0)           // the orange one: how many in this folder have a newer version in the cloud
                    g.Children.Add(new Border
                    {
                        HorizontalAlignment = HorizontalAlignment.Left, VerticalAlignment = VerticalAlignment.Top, Margin = new Thickness(2, 4, 0, 0),
                        CornerRadius = new CornerRadius(7), Background = Theme.B("#3A2A14"), Padding = new Thickness(5, 0, 5, 1),
                        ToolTip = L.F("{0} da aggiornare (versione più nuova nel cloud)", updates),
                        Child = new TextBlock { Text = "↻ " + updates, FontSize = 10.5, Foreground = Theme.B("#F2A13F"), FontWeight = FontWeights.SemiBold },
                    });
                if (downloaded > 0 || counter) g.Children.Add(new Border
                {
                    HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Top, Margin = new Thickness(0, 4, 2, 0),
                    CornerRadius = new CornerRadius(7), Background = Theme.B("#1F3A2C"), Padding = new Thickness(5, 0, 5, 1),
                    ToolTip = L.F("{0} su {1} già scaricati", downloaded, count),
                    Child = new TextBlock { Text = $"{downloaded}/{count}", FontSize = 10.5, Foreground = Theme.B("#4FD18B"), FontWeight = FontWeights.SemiBold },
                });
                visual = g;
            }
            var btn = BigTile(visual, FolderLabel(folder), sub,
                              FolderLabel(folder) + "\n" + (editable ? (scope == "eco" ? L.T("Clic per aprire · trascina qui un ecosistema o una cartella per spostarli dentro · trascina la cartella su un'altra per spostarla · tasto destro: sposta, rinomina, elimina")
                                                                             : scope == "model" ? L.T("Clic per aprire · trascina qui un oggetto o una cartella per spostarli dentro · trascina la cartella su un'altra per spostarla · tasto destro: sposta, rinomina, elimina")
                                                                             : L.T("Clic per aprire · trascina qui un materiale o una cartella per spostarli dentro · trascina la cartella su un'altra per spostarla · tasto destro: sposta, rinomina, elimina"))
                                                        : L.T("Clic per aprire")));
            btn.Click += (_, __) => open();
            if (editable)
            {
                _dropFolders.Add((btn, folder));
                btn.ContextMenu = FolderMenu(folder, scope);
                if (IsCut(scope, true, folder)) btn.Opacity = 0.45;
                // a folder can be dragged onto another folder (or "Indietro", or a piece of the path bar) to go inside it
                MakeDraggable(btn, FolderName(folder), (_, __) => Task.CompletedTask, async target => await MoveFolder(folder, target, scope),
                              null, viewDrop: false, folderOk: t => CanMoveFolder(folder, t));
            }
            return btn;
        }

        /// <summary>Can `folder` go inside `target`? Not into itself, not into one of its subfolders, not where it already is.</summary>
        static bool CanMoveFolder(string folder, string target) => !InFolder(target, folder) && target != ParentFolder(folder);

        async Task MoveFolder(string folder, string target, string scope)
        {
            if (!CanMoveFolder(folder, target)) return;
            var newPath = (target == "" ? "" : target + "/") + FolderName(folder);
            if (ScopeFolders(scope).Contains(newPath))
            {
                var q = L.F("In \"{0}\" esiste già una cartella \"{1}\".\nUnire le due cartelle? I contenuti finiscono tutti insieme.",
                            target == "" ? ScopeRoot(scope) : FolderName(target), FolderName(folder));
                if (Msg.Show(this, q, "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
            }
            bool ok = false;
            await Run(async api => { await api.Post(FolderEndpoint(scope), new { action = "rename", path = folder, newPath }); ok = true; });
            if (!ok) return;
            Status(L.F("Cartella {0} spostata in {1}", FolderName(folder), target == "" ? ScopeRoot(scope) : target));
            await ReloadScope(scope);
        }

        Button UpTile(string parent, Action<string> go, bool dropTarget)
        {
            var btn = BigTile(TileIcon(Icons.Undo, Theme.TextMuted), L.T("Indietro"), parent == "" ? "" : FolderName(parent),
                              L.T("Torna alla cartella superiore") + (dropTarget ? "\n" + L.T("Trascina qui per spostare nella cartella superiore") : ""));
            btn.Click += (_, __) => { go(parent); RenderLibrary(); };
            if (dropTarget) _dropFolders.Add((btn, parent));
            return btn;
        }

        Button NewFolderTile(string scope, string parent)
        {
            var btn = BigTile(TileIcon(Icons.Plus, Theme.Accent), L.T("Nuova cartella"), "",
                              scope == "eco" ? L.T("Crea una cartella qui, per raggruppare gli ecosistemi (es. Boschi, Prati, Giardini)")
                              : scope == "model" ? L.T("Crea una cartella qui, per raggruppare gli oggetti (es. Alberi, Edifici, Arredamento)")
                                               : L.T("Crea una cartella qui, per raggruppare i materiali (es. Legno, Mattoni, Metallo)"));
            btn.Click += async (_, __) => await CreateFolder(parent, scope);
            return btn;
        }

        static TextBlock EmptyNote(string text)
        {
            var t = Theme.Label(text, 12, Theme.TextFaint);
            t.Margin = new Thickness(10);
            return t;
        }

        async Task<string?> CreateFolder(string parent, string scope = "material")
        {
            var name = InputDialog.Ask(this, L.T("Nuova cartella"), L.T("Nome della cartella (usa / per creare sottocartelle)"), "");
            if (name == null) return null;
            var path = (parent == "" ? "" : parent + "/") + name.Replace('\\', '/').Trim('/');
            JsonObject? r = null;
            await Run(async api => { r = await api.Post(FolderEndpoint(scope), new { action = "create", path }); });
            if (r == null) return null;
            await ReloadScope(scope);
            return (string?)r["path"] ?? path;
        }

        // ---------------------------------------------------------------- cut and paste (materials, 3D models, folders)
        // Taglia marks a material, a model or a folder (with everything inside it); Incolla, in another folder of the
        // same kind (tasto destro on a folder, or on the empty part of the library), moves it there. A material never
        // goes into a folder of models or the other way round: the cut is forgotten when the library shows the other kind.
        // Keys: several 3D models selected with Ctrl (MainWindow.ModelSelection); Copy: Incolla makes copies instead of moving
        sealed record LibClip(string Scope, bool IsFolder, string Key, string Label, string[]? Keys = null, bool Copy = false);
        LibClip? _libClip;

        /// <summary>"material" or "model" for the tab shown now (and a real folder of it), "" when nothing can be pasted.</summary>
        string PasteScope()
        {
            if (_libraryTab == "mymaterials" && !(_matFolder == SimplerMats || _matFolder.StartsWith(SimplerMats + "/"))) return "material";
            // (1.78.4, Luca: «Simpler è una cartella come le altre se il parametro è 0») unlocked, it takes a paste too
            if (_libraryTab == "simplermats" && !SimplerLocked) return "material";
            if (_libraryTab is "packplants" or "packmodels" || (_libraryTab is "simplerplants" or "primitives" && SimplerLocked)) return "";
            if ((_libraryTab == "objects" && _objFolder != PrimitiveFolder) || _libraryTab is "myplants" or "simplerplants" or "primitives") return "model";
            if (_libraryTab == "ecosystems" || (_libraryTab == "simplereco" && !SimplerLocked)) return "eco";
            return "";
        }

        void CutLibrary(string scope, bool isFolder, string key, string label)
        {
            _libClip = new LibClip(scope, isFolder, key, label);
            Status(L.F("Tagliato: {0} · apri la cartella dove vuoi metterlo e scegli «Incolla» (tasto destro)", label));
            RenderLibrary();
        }

        bool CanPaste(string scope, string target)
        {
            var c = _libClip;
            if (c == null || c.Scope != scope) return false;
            if (scope == "eco" && c.Copy) return !ReadOnlyEco(target);      // (a copy: into any folder that is not locked)
            // (nothing goes into the locked Simpler parts; out of them only copies)
            if (scope == "model" && (ReadOnlyFolder(target) || (!c.Copy && (c.IsFolder ? ReadOnlyFolder(c.Key) : (c.Keys ?? new[] { c.Key }).Any(ReadOnlyModel))))) return false;
            if (scope == "material" && SimplerLocked && (InSimplerMatPath(target)
                    || (!c.Copy && !c.IsFolder && _materials.OfType<JsonObject>().Any(x => (string?)x["id"] == c.Key && InSimplerMats(x))))) return false;
            if (c.IsFolder) return CanMoveFolder(c.Key, target);
            if (c.Keys != null)                       // several models: at least one moves (copies can go anywhere)
                return c.Copy || c.Keys.Any(k => _models.OfType<JsonObject>().Any(x => (string?)x["id"] == k && ((string?)x["folder"] ?? "") != target));
            var list = scope == "model" ? _models : scope == "eco" ? _ecosystems : _materials;
            var it = list.OfType<JsonObject>().FirstOrDefault(x => (string?)x["id"] == c.Key);
            return it != null && ((string?)it["folder"] ?? "") != target;
        }

        async Task PasteLibrary(string scope, string target)
        {
            var c = _libClip;
            if (c == null || !CanPaste(scope, target)) return;
            if (scope == "eco" && c.Copy)
            {
                await PasteEcoCopy(c, target);
                return;
            }
            if (c.Keys != null || c.Copy)
            {
                await PasteModels(c, target);
                return;
            }
            _libClip = null;
            if (c.IsFolder) await MoveFolder(c.Key, target, scope);
            else if (scope == "model") await MoveModel(c.Key, target);
            else if (scope == "eco") await MoveEco(c.Key, target);
            else await MoveMaterial(c.Key, target);
            RenderLibrary();
        }

        MenuItem PasteItem(string scope, string target, string text)
        {
            var c = _libClip;
            var i = new MenuItem { Header = c != null && c.Scope == scope ? text + " · " + c.Label : text, IsEnabled = CanPaste(scope, target) };
            i.Click += async (_, __) => await PasteLibrary(scope, target);
            return i;
        }

        /// <summary>Tasto destro on the empty part of the library: paste into the folder shown.</summary>
        void HookLibraryPaste()
        {
            _libraryScroller!.Background = Brushes.Transparent;
            _libraryScroller.ContextMenu = new ContextMenu();
            _libraryScroller.ContextMenuOpening += (_, e) =>
            {
                // (the event comes up from every tile: a tile with its own menu keeps it)
                for (var d = e.OriginalSource as DependencyObject; d != null && d != _libraryScroller;
                     d = d is Visual ? VisualTreeHelper.GetParent(d) : LogicalTreeHelper.GetParent(d))
                    if (d is FrameworkElement fe && fe.ContextMenu != null) return;
                var scope = PasteScope();
                if (scope == "" || _libClip == null || _libClip.Scope != scope) { e.Handled = true; return; }
                var cm = _libraryScroller.ContextMenu!;
                cm.Items.Clear();
                cm.Items.Add(PasteItem(scope, scope == "model" ? ModelFolderNow : scope == "eco" ? _ecoFolder : _matFolder, L.T("Incolla qui")));
                var cancel = new MenuItem { Header = L.T("Annulla il taglia") };
                cancel.Click += (_, __) => { _libClip = null; RenderLibrary(); };
                cm.Items.Add(cancel);
            };
        }

        bool IsCut(string scope, bool isFolder, string key) => _libClip is LibClip c && !c.Copy && c.Scope == scope && c.IsFolder == isFolder
                                                                && (c.Key == key || (c.Keys != null && c.Keys.Contains(key)));

        ContextMenu FolderMenu(string folder, string scope)
        {
            var m = new ContextMenu();
            void Item(string text, Func<Task> act) { var i = new MenuItem { Header = text }; i.Click += async (_, __) => await act(); m.Items.Add(i); }
            Item(L.T("Apri"), async () => { await Task.Yield(); SetScopeFolder(scope, folder); RenderLibrary(); });
            Item(L.T("Taglia"), async () => { await Task.Yield(); CutLibrary(scope, true, folder, FolderName(folder)); });
            m.Items.Add(PasteItem(scope, folder, L.T("Incolla in questa cartella")));
            Item(L.T("Nuova sottocartella…"), async () => { var p = await CreateFolder(folder, scope); if (p != null) { SetScopeFolder(scope, folder); RenderLibrary(); } });
            if (scope == "model" && !IsVegFolder(folder))
            {
                // (1.78.1) a whole folder of plants at once (and its subfolders): Fogliame, into Vegetazione by kind
                Item(L.T("Converti la cartella in vegetazione…"), async () =>
                {
                    var ids = _models.OfType<JsonObject>().Where(x => !IsVegModel(x) && InFolder((string?)x["folder"] ?? "", folder))
                                     .Select(x => (string?)x["id"] ?? "").Where(x => x != "").ToList();
                    if (ids.Count == 0) { Status(L.T("Nessun modello in questa cartella"), true); return; }
                    if (Msg.Show(this, L.F("Convertire in vegetazione i {0} modelli di «{1}» (anche nelle sottocartelle)?\nFoglie e legno ricevono il materiale Fogliame e le piante vanno in Vegetazione, divise per tipo. Prova prima su due o tre piante con «Converti in vegetazione…» per vedere se foglie e legno sono riconosciuti bene.", ids.Count, FolderName(folder)),
                                 "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
                    await ConvertToVegetation(ids);
                });
            }
            var move = new MenuItem { Header = L.T("Sposta in") };
            void Target(string t, string label)
            {
                var i = new MenuItem { Header = label, IsEnabled = CanMoveFolder(folder, t) };
                i.Click += async (_, __) => await MoveFolder(folder, t, scope);
                move.Items.Add(i);
            }
            // (1.78.5, Luca: «perché non posso muovere la cartella in Mine?») the main folder of models and materials is «I miei»
            Target("", scope == "eco" ? L.T("Ecosistemi (cartella principale)") : L.T("I miei (cartella principale)"));
            foreach (var f in ScopeFolders(scope).Where(f => !InFolder(f, folder)).OrderBy(f => f, StringComparer.CurrentCultureIgnoreCase))
                Target(f, new string(' ', 4 * f.Count(c => c == '/')) + FolderName(f));
            m.Items.Add(move);
            Item(L.T("Rinomina…"), async () =>
            {
                var n = InputDialog.Ask(this, L.T("Rinomina cartella"), L.T("Nome della cartella"), FolderName(folder));
                if (n == null || n == FolderName(folder)) return;
                var parent = ParentFolder(folder);
                var newPath = (parent == "" ? "" : parent + "/") + n.Replace('/', '-').Replace('\\', '-');
                await Run(async api => { await api.Post(FolderEndpoint(scope), new { action = "rename", path = folder, newPath }); });
                await ReloadScope(scope);
            });
            m.Items.Add(new Separator());
            Item(L.T("Elimina cartella"), async () =>
            {
                // (1.78.4, Luca: «ho eliminato la cartella con i modelli dentro: è sparita ma i modelli ci sono tutti»)
                // a folder of models with models inside: delete them too, or only the folder (they go up)
                var inside = scope == "model" ? _models.OfType<JsonObject>().Count(x => { var f = (string?)x["folder"] ?? ""; return f == folder || f.StartsWith(folder + "/", StringComparison.Ordinal); }) : 0;
                if (inside > 0)
                {
                    var a = Msg.Show(this, L.F("La cartella \"{0}\" contiene {1} modelli (con le sue sottocartelle).\n\nSì: elimina la cartella e i modelli (non si possono recuperare).\nNo: elimina la cartella e le sottocartelle, i modelli passano nella cartella superiore.", FolderName(folder), inside),
                                     "Simpler", MessageBoxButton.YesNoCancel, MessageBoxImage.Warning);
                    if (a == MessageBoxResult.Cancel || a == MessageBoxResult.None) return;
                    var items = a == MessageBoxResult.Yes;
                    await Run(async api => { await api.Post(FolderEndpoint(scope), new { action = "delete", path = folder, items }); });
                    await ReloadScope(scope);
                    if (items) Status(L.F("Cartella \"{0}\" eliminata con {1} modelli", FolderName(folder), inside));
                    return;
                }
                var q = scope == "eco"
                    ? L.F("Eliminare la cartella \"{0}\" e le sue sottocartelle?\nGli ecosistemi che contengono non vengono eliminati: passano nella cartella superiore.", FolderName(folder))
                    : scope == "model"
                    ? L.F("Eliminare la cartella \"{0}\" e le sue sottocartelle?\nGli oggetti che contengono non vengono eliminati: passano nella cartella superiore.", FolderName(folder))
                    : L.F("Eliminare la cartella \"{0}\" e le sue sottocartelle?\nI materiali che contengono non vengono eliminati: passano nella cartella superiore.", FolderName(folder));
                if (Msg.Show(this, q, "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
                await Run(async api => { await api.Post(FolderEndpoint(scope), new { action = "delete", path = folder }); });
                await ReloadScope(scope);
            });
            return m;
        }

        /// <summary>"Sposta in" submenu of a library tile: every folder of the library (indented by level).</summary>
        void AddMoveMenu(ContextMenu menu, string id, string current, string scope = "material")
        {
            var move = new MenuItem { Header = L.T("Sposta in") };
            Func<string, string, Task> doMove = scope == "model" ? MoveModel : MoveMaterial;
            void Target(string folder, string label)
            {
                var i = new MenuItem { Header = label, IsEnabled = folder != current };
                i.Click += async (_, __) => await doMove(id, folder);
                move.Items.Add(i);
            }
            Target("", L.T("I miei (cartella principale)"));
            foreach (var f in ScopeFolders(scope).OrderBy(f => f, StringComparer.CurrentCultureIgnoreCase))
                if ((scope != "model" || !ReadOnlyFolder(f)) && (scope != "eco" || !ReadOnlyEco(f))) Target(f, new string(' ', 4 * f.Count(c => c == '/')) + FolderName(f));
            move.Items.Add(new Separator());
            var add = new MenuItem { Header = L.T("Nuova cartella…") };
            add.Click += async (_, __) =>
            {
                var p = await CreateFolder(scope == "model" ? ModelFolderNow : _matFolder, scope);
                if (p != null) await doMove(id, p);
            };
            move.Items.Add(add);
            menu.Items.Insert(0, move);
            menu.Items.Insert(1, new Separator());
        }

        async Task MoveMaterial(string id, string folder)
        {
            var m = _materials.OfType<JsonObject>().FirstOrDefault(x => (string?)x["id"] == id);
            if (m != null && ((string?)m["folder"] ?? "") == folder) return;
            if (SimplerLocked && ((m != null && InSimplerMats(m)) || InSimplerMatPath(folder))) { Status(L.T("Le cartelle Simpler sono di sola lettura"), true); return; }
            await Run(async api => { await api.Post("material/library/move", new { id, folder }); });
            Status(L.F("{0} spostato in {1}", (string?)m?["name"] ?? id, folder == "" ? L.T("Materiali") : folder));
            await ReloadLibraryMaterials();
        }

        /// <summary>The folder (tile or path piece) under the mouse while dragging a material, or null.</summary>
        string? FolderUnder(MouseEventArgs e)
        {
            foreach (var (el, folder) in _dropFolders)
            {
                if (!el.IsVisible) continue;
                var p = e.GetPosition(el);
                if (p.X >= 0 && p.Y >= 0 && p.X <= el.ActualWidth && p.Y <= el.ActualHeight) return folder;
            }
            return null;
        }

        // ---------------------------------------------------------------- Poly Haven (folders from the categories, read only)

        void RenderPolyHavenBrowser()
        {
            var assets = _phAssets.OfType<JsonObject>().ToList();
            var q = LibraryQuery;
            IEnumerable<JsonObject> shown;
            if (q != "")
            {
                RenderCrumbs("Poly Haven", "", f => { _phFolder = f; _librarySearch.Text = ""; }, L.F("risultati per \"{0}\"", _librarySearch.Text.Trim()));
                shown = assets.Where(a => ((string?)a["name"] + " " + (string?)a["category"] + " " + (string?)a["folder"]).ToLowerInvariant().Contains(q));
                if (!shown.Any()) _libraryTiles.Children.Add(EmptyNote(L.T("Nessuna texture trovata")));
            }
            else
            {
                // every folder with its parents (Poly Haven paths are two levels deep: Legno / Boards & Planks)
                var folders = new HashSet<string>();
                foreach (var f in assets.Select(a => (string?)a["folder"] ?? "").Where(f => f != ""))
                    for (var p = f; p != ""; p = ParentFolder(p)) folders.Add(p);
                if (_phFolder != "" && !folders.Contains(_phFolder)) _phFolder = "";
                RenderCrumbs("Poly Haven", _phFolder, f => _phFolder = f, null);
                if (_phFolder != "") _libraryTiles.Children.Add(UpTile(ParentFolder(_phFolder), f => _phFolder = f, false));
                foreach (var f in folders.Where(f => ParentFolder(f) == _phFolder)
                                         .OrderBy(f => f == L.T("Altro")).ThenBy(f => f, StringComparer.CurrentCultureIgnoreCase))
                {
                    var count = assets.Count(a => InFolder((string?)a["folder"] ?? "", f));
                    var down = assets.Count(a => InFolder((string?)a["folder"] ?? "", f) && ((bool?)a["downloaded"] ?? false));
                    _libraryTiles.Children.Add(FolderTile(f, count, () => { _phFolder = f; RenderLibrary(); }, "polyhaven", down));
                }
                shown = assets.Where(a => ((string?)a["folder"] ?? "") == _phFolder);
            }
            foreach (var a in shown) _libraryTiles.Children.Add(PolyHavenTile(a));
            var credit = Theme.Label(L.T("Texture di Poly Haven (polyhaven.com) · CC0, libere anche per uso commerciale"), 11, Theme.TextFaint);
            credit.Margin = new Thickness(10, 0, 10, 0);
            _libraryTiles.Children.Add(credit);
        }
    }

    /// <summary>
    /// Save something to a library (a material, a model): its name and the folder where it goes. The folders are a
    /// tree (indented, the chosen one highlighted, scroll bar when they are many); "Nuova cartella" adds one inside the
    /// chosen folder, and a path typed by hand works too (the folder is created when saving).
    /// </summary>
    public sealed class SaveToLibraryDialog : ThemedDialog
    {
        readonly TextBox _name, _folder;
        readonly StackPanel _list = new StackPanel();
        readonly List<string> _folders;
        readonly string _rootLabel;
        readonly TextBlock _hint;
        bool _syncing;
        readonly HashSet<string> _open = new HashSet<string>();     // the folders shown open (all closed at the start, but the way to the starting folder)

        static IEnumerable<string> Parents(string f)
        {
            for (var p = f.Contains('/') ? f[..f.LastIndexOf('/')] : ""; p != ""; p = p.Contains('/') ? p[..p.LastIndexOf('/')] : "") yield return p;
        }

        SaveToLibraryDialog(string title, string nameLabel, string name, string folder, IEnumerable<string> folders, string rootLabel, ImageSource? picture)
            : base(title, 500)
        {
            _folders = folders.Where(f => f != "").Distinct().ToList();
            _rootLabel = rootLabel;
            foreach (var p in Parents(folder.Replace('\\', '/').Trim('/'))) _open.Add(p);       // (only the way to the folder where the model goes)
            var sp = Body;
            sp.Margin = new Thickness(22, 6, 22, 20);

            // name (with the picture of what is being saved, when there is one)
            var top = new DockPanel { Margin = new Thickness(0, 0, 0, 16) };
            if (picture != null)
            {
                var pic = new Border
                {
                    Width = 64, Height = 64, CornerRadius = new CornerRadius(10), Margin = new Thickness(0, 0, 14, 0),
                    Background = new ImageBrush(picture) { Stretch = Stretch.UniformToFill }, BorderBrush = Theme.B(Theme.Line), BorderThickness = new Thickness(1),
                };
                DockPanel.SetDock(pic, Dock.Left);
                top.Children.Add(pic);
            }
            var nameBox = new StackPanel { VerticalAlignment = VerticalAlignment.Center };
            nameBox.Children.Add(Theme.Label(nameLabel, 13, Theme.TextSoft));
            _name = Theme.Input(name);
            _name.Margin = new Thickness(0, 8, 0, 0);
            nameBox.Children.Add(_name);
            top.Children.Add(nameBox);
            sp.Children.Add(top);

            // folder: tree + path
            var head = new DockPanel { Margin = new Thickness(0, 0, 0, 8) };
            var add = Theme.Button(Theme.IconText(Icons.Plus, L.T("Nuova cartella"), Theme.Accent, 13), Theme.Kind.Ghost,
                                   L.T("Crea una cartella dentro quella scelta"));
            add.MinHeight = 26; add.Height = 26; add.FontSize = 12; add.Padding = new Thickness(8, 0, 8, 0);
            add.Click += (_, __) => NewFolder();
            DockPanel.SetDock(add, Dock.Right);
            head.Children.Add(add);
            var cap = Theme.Label(L.T("Cartella"), 13, Theme.TextSoft);
            cap.VerticalAlignment = VerticalAlignment.Center;
            head.Children.Add(cap);
            sp.Children.Add(head);
            sp.Children.Add(new Border
            {
                Child = new ScrollViewer { Content = _list, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled,
                                           Height = 250, Padding = new Thickness(0, 0, 4, 0) },
                Background = Theme.B(Theme.Inset), BorderBrush = Theme.B(Theme.Line), BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(8), Padding = new Thickness(4),
            });
            _folder = Theme.Input(folder);
            _folder.Margin = new Thickness(0, 10, 0, 4);
            // (Luca: «perché dovrei scriverlo a mano?») the folder is chosen in the tree, a new one with «Nuova cartella»: the path
            // below only shows where the model goes
            _folder.IsReadOnly = true; _folder.Focusable = false; _folder.IsTabStop = false; _folder.Cursor = Cursors.Arrow;
            _folder.ToolTip = L.T("La cartella scelta: scegline un'altra nell'albero, o creane una con «Nuova cartella»");
            _folder.TextChanged += (_, __) => { if (!_syncing) Highlight(); };
            sp.Children.Add(_folder);
            _hint = Theme.Label("", 11.5, Theme.TextFaint);
            _hint.Margin = new Thickness(2, 0, 0, 16);
            sp.Children.Add(_hint);

            foreach (var box in new[] { _name, _folder })
                box.KeyDown += (_, e) => { if (e.Key == Key.Enter) DialogResult = true; if (e.Key == Key.Escape) DialogResult = false; };
            var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right };
            var cancel = Theme.Button(L.T("Annulla"), Theme.Kind.Ghost);
            cancel.Click += (_, __) => DialogResult = false;
            var ok = Theme.Button(L.T("Salva"), Theme.Kind.Primary);
            ok.Margin = new Thickness(8, 0, 0, 0);
            ok.Click += (_, __) => DialogResult = true;
            buttons.Children.Add(cancel);
            buttons.Children.Add(ok);
            sp.Children.Add(buttons);
            BuildList();
            Highlight();
            Loaded += (_, __) => { _name.Focus(); _name.SelectAll(); BringSelectedIntoView(); };
        }

        string Path => string.Join("/", _folder.Text.Replace('\\', '/').Split('/').Select(p => p.Trim()).Where(p => p != ""));

        void BuildList()
        {
            _list.Children.Clear();
            Row("", _rootLabel, 0);
            // every folder with its parents, as a tree
            var all = new HashSet<string>();
            foreach (var f in _folders)
                for (var p = f; p != ""; p = p.Contains('/') ? p[..p.LastIndexOf('/')] : "") all.Add(p);
            string ParentOf(string f) => f.Contains('/') ? f[..f.LastIndexOf('/')] : "";
            void Children(string parent, int depth)
            {
                foreach (var f in all.Where(f => ParentOf(f) == parent).OrderBy(f => f, StringComparer.CurrentCultureIgnoreCase))
                {
                    bool kids = all.Any(x => ParentOf(x) == f), open = kids && _open.Contains(f);
                    Row(f, f.Contains('/') ? f[(f.LastIndexOf('/') + 1)..] : f, depth, kids, open);
                    if (open) Children(f, depth + 1);
                }
            }
            Children("", 1);
        }

        void Row(string path, string label, int depth, bool kids = false, bool open = false)
        {
            var content = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(16 * depth, 0, 0, 0) };
            // a folder with subfolders: a small arrow to open (▸) or close (▾) it; the others keep the space so the names line up
            var arrow = new TextBlock { Text = kids ? (open ? "▾" : "▸") : "", Width = 16, FontSize = 12, Foreground = Theme.B(Theme.TextMuted),
                                        VerticalAlignment = VerticalAlignment.Center, TextAlignment = TextAlignment.Center, Cursor = kids ? Cursors.Hand : Cursors.Arrow };
            if (kids)
                arrow.MouseLeftButtonDown += (_, e) =>
                {
                    e.Handled = true;
                    if (!_open.Remove(path)) _open.Add(path);
                    BuildList(); Highlight();
                };
            content.Children.Add(arrow);
            var ic = Theme.Icon(Icons.Folder, path == "" ? Theme.TextMuted : Theme.Warm, 15, 1.6);
            ic.Margin = new Thickness(0, 0, 8, 0);
            ic.VerticalAlignment = VerticalAlignment.Center;
            content.Children.Add(ic);
            content.Children.Add(new TextBlock { Text = label, FontSize = 12.5, Foreground = Theme.B(Theme.TextSoft), VerticalAlignment = VerticalAlignment.Center });
            var row = new Border { Child = content, Padding = new Thickness(8, 5, 8, 5), CornerRadius = new CornerRadius(6), Background = Brushes.Transparent,
                                   Cursor = Cursors.Hand, Tag = path, Margin = new Thickness(0, 0, 0, 1) };
            row.MouseEnter += (_, __) => { if (!IsSelected(row)) row.Background = Theme.B(Theme.Raised); };
            row.MouseLeave += (_, __) => { if (!IsSelected(row)) row.Background = Brushes.Transparent; };
            row.MouseLeftButtonUp += (_, __) =>
            {
                _syncing = true; _folder.Text = path; _syncing = false;
                Highlight();
            };
            row.MouseLeftButtonDown += (_, e) => { if (e.ClickCount == 2) DialogResult = true; };
            _list.Children.Add(row);
        }

        bool IsSelected(Border row) => (row.Tag as string) == Path;

        void Highlight()
        {
            bool found = false;
            foreach (var row in _list.Children.OfType<Border>())
            {
                var sel = IsSelected(row);
                found |= sel;
                row.Background = sel ? Theme.B(Theme.Selected) : Brushes.Transparent;
                row.BorderBrush = sel ? Theme.B(Theme.Accent) : null;
                row.BorderThickness = new Thickness(sel ? 1 : 0);
            }
            // (a folder that exists but sits inside a closed one is still an existing folder)
            found |= Path == "" || _folders.Any(f => f == Path || f.StartsWith(Path + "/", StringComparison.Ordinal));
            _hint.Text = found ? (Path == "" ? L.T("Nella cartella principale") : L.T("Cartella esistente"))
                               : L.T("Nuova cartella: viene creata al salvataggio");
            _hint.Foreground = Theme.B(found ? Theme.TextFaint : Theme.Warm);
        }

        void BringSelectedIntoView()
        {
            foreach (var row in _list.Children.OfType<Border>())
                if (IsSelected(row)) { row.BringIntoView(); break; }
        }

        void NewFolder()
        {
            var n = InputDialog.Ask(this, L.T("Nuova cartella"), L.F("Nome della cartella dentro \"{0}\"", Path == "" ? _rootLabel : Path), "");
            if (n == null) return;
            var path = (Path == "" ? "" : Path + "/") + n.Replace('/', '-').Replace('\\', '-').Trim();
            if (!_folders.Contains(path)) _folders.Add(path);
            foreach (var q in Parents(path)) _open.Add(q);
            BuildList();
            _syncing = true; _folder.Text = path; _syncing = false;
            Highlight();
            BringSelectedIntoView();
        }

        protected override void OnCloseButton() => DialogResult = false;

        /// <summary>(name, folder) or null when cancelled.</summary>
        public static (string name, string folder)? Ask(Window owner, string title, string nameLabel, string name, string folder,
                                                       IEnumerable<string> folders, string rootLabel, ImageSource? picture = null)
        {
            var d = new SaveToLibraryDialog(title, nameLabel, name, folder, folders, rootLabel, picture) { Owner = owner };
            if (d.ShowDialog() != true || d._name.Text.Trim() == "") return null;
            return (d._name.Text.Trim(), d.Path);
        }
    }
}
