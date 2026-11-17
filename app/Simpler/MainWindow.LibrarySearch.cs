using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace Simpler
{
    /// <summary>
    /// (1.78.1) «Cerca in tutta la libreria»: the words of the search box looked for in every kind of the library at
    /// once - my models, plants, the primitives, materials (Simpler and mine), ecosystems, Poly Haven models and
    /// textures, ambientCG decals, HDRI - each kind introduced by a tile with its name and count, at most 40 results per
    /// kind. Opened from the link next to «risultati per …» of any search.
    /// </summary>
    public sealed partial class MainWindow
    {
        const int GlobalSearchMax = 40;

        void RenderGlobalSearch()
        {
            var q = LibraryQuery;
            RenderCrumbs(L.T("Tutta la libreria"), "", _ => { }, q == "" ? L.T("scrivi nella casella di ricerca") : L.F("risultati per \"{0}\"", _librarySearch.Text.Trim()));
            if (q == "") return;
            bool Has(JsonObject o, params string[] keys) => string.Join(" ", keys.Select(k => (string?)o[k] ?? "")).ToLowerInvariant().Contains(q);
            int total = 0;
            void Group<T>(string title, Geometry icon, string color, IEnumerable<T> items, Func<T, UIElement> tile)
            {
                var list = items.ToList();
                if (list.Count == 0) return;
                total += list.Count;
                _libraryTiles.Children.Add(SectionTile(title, icon, color, list.Count));
                foreach (var it in list.Take(GlobalSearchMax)) _libraryTiles.Children.Add(tile(it));
                if (list.Count > GlobalSearchMax)
                    _libraryTiles.Children.Add(EmptyNote(L.F("… e altri {0}: apri la sezione per vederli tutti", list.Count - GlobalSearchMax)));
            }
            var models = _models.OfType<JsonObject>().Where(m => Has(m, "name", "folder")).ToList();
            Group(L.T("Modelli 3D · I miei"), Icons.Mesh, "#9DB4D8", models.Where(m => !IsVegModel(m) && !IsVegFolder((string?)m["folder"] ?? "")), m => ModelTile(m));
            Group(L.T("Vegetazione"), Icons.Leaf, "#7CC46A", models.Where(m => IsVegModel(m) || IsVegFolder((string?)m["folder"] ?? "")), m => ModelTile(m));
            var prims = InsertObjects.Where(p => L.T(p.label).ToLowerInvariant().Contains(q)).ToList();
            if (prims.Count > 0)
            {
                total += prims.Count;
                _libraryTiles.Children.Add(SectionTile(L.T("Modelli 3D · Simpler"), Icons.Mesh, "#9DB4D8", prims.Count));
                foreach (var (kind, label) in prims) AddPrimitiveTile(kind, label);
            }
            var mats = _materials.OfType<JsonObject>().Where(m => Has(m, "name", "category", "folder")).ToList();
            Group(L.T("Materiali · Simpler"), Icons.MatStandard, "#C9D3E4", mats.Where(InSimplerMats), m => LibraryTile(m, true));
            Group(L.T("Materiali · I miei"), Icons.MatStandard, "#C9D3E4", mats.Where(m => !InSimplerMats(m)), m => LibraryTile(m, true));
            Group(L.T("Ecosistemi"), Icons.Grass, "#7CC46A", _ecosystems.OfType<JsonObject>().Where(e => Has(e, "name", "folder")), e => EcoTile(e));
            Group(L.T("Modelli 3D · Poly Haven"), Icons.Globe, "#E8A33D", _phmAssets.OfType<JsonObject>().Where(a => Has(a, "name", "category", "folder")), a => PhModelTile(a));
            Group(L.T("Materiali · Poly Haven"), Icons.Globe, "#E8A33D", _phAssets.OfType<JsonObject>().Where(a => Has(a, "name", "category", "folder")), a => PolyHavenTile(a));
            Group(L.T("Decal · ambientCG"), Icons.Image, "#E8A33D", _acgDecals.OfType<JsonObject>().Where(a => Has(a, "name", "category", "folder")), a => AcgDecalTile(a));
            Group(L.T("HDRI e sfondi"), Icons.SunCloud, "#F2C14E", _hdris.OfType<JsonObject>().Where(a => Has(a, "name", "category", "folder")), a => HdriTile(a));
            if (total == 0) _libraryTiles.Children.Add(EmptyNote(L.T("Niente in tutta la libreria (le sezioni online si cercano dopo averle aperte una volta)")));
        }

        /// <summary>The tile that opens a kind in the results: its icon, name and how many were found.</summary>
        FrameworkElement SectionTile(string title, Geometry icon, string color, int count)
        {
            var sp = new StackPanel { Width = 92, VerticalAlignment = VerticalAlignment.Center };
            var ic = Theme.Icon(icon, Theme.C(color), 28, 1.6);
            ic.HorizontalAlignment = HorizontalAlignment.Center;
            ic.Margin = new Thickness(0, 14, 0, 8);
            sp.Children.Add(ic);
            sp.Children.Add(new TextBlock { Text = title, FontSize = 11.5, FontWeight = FontWeights.SemiBold, TextAlignment = TextAlignment.Center,
                                            TextWrapping = TextWrapping.Wrap, Foreground = Theme.B(Theme.Text) });
            sp.Children.Add(new TextBlock { Text = count == 1 ? L.T("1 risultato") : L.F("{0} risultati", count), FontSize = 10.5,
                                            TextAlignment = TextAlignment.Center, Foreground = Theme.B(Theme.TextFaint), Margin = new Thickness(0, 2, 0, 0) });
            return new Border { Child = sp, Height = 130, Width = 100, Margin = new Thickness(4), CornerRadius = new CornerRadius(10),
                                Background = Theme.B(Theme.Inset), BorderBrush = Theme.B(Theme.Line), BorderThickness = new Thickness(1) };
        }

        /// <summary>The link «Cerca in tutta la libreria» next to the results of a section.</summary>
        Button GlobalSearchLink()
        {
            var b = Theme.Button(Theme.IconText(Icons.Search, L.T("Cerca in tutta la libreria"), Theme.Accent, 13), Theme.Kind.Ghost,
                                 L.T("Le stesse parole in tutti i tipi della libreria: modelli, piante, materiali, ecosistemi, Poly Haven, decal, HDRI"));
            b.MinHeight = 26; b.Height = 26; b.FontSize = 12; b.Padding = new Thickness(8, 0, 8, 0); b.Margin = new Thickness(8, 0, 0, 0);
            b.Click += (_, __) =>
            {
                _searchByTab["search"] = _librarySearch.Text;
                ShowLibraryTab("search");
            };
            return b;
        }
    }
}
