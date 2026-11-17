using System;
using System.Collections.Generic;
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
    /// Library tab "HDRI" (Poly Haven ▾ HDRI): the studio backgrounds, the HDRIs that come with Blender (offline) and the
    /// Poly Haven HDRIs (downloaded the first time, 4K). A click makes it the Ambiente (engine: hdri.py, ambience.py):
    /// background and light from the picture, its sun as a real Sun light.
    /// </summary>
    public sealed partial class MainWindow
    {
        JsonArray _hdris = new JsonArray();
        string _hdriFolder = "";
        readonly Dictionary<string, BitmapImage> _hdriThumbs = new();

        void RenderHdri()
        {
            if (_hdris.Count == 0)
            {
                var wait = Theme.Label(L.T("Caricamento degli HDRI…"), 12, Theme.TextFaint);
                wait.Margin = new Thickness(10);
                _libraryTiles.Children.Add(wait);
                _ = LoadHdris();
                return;
            }
            var items = _hdris.OfType<JsonObject>().ToList();
            var studio = L.T("Studio");
            var q = LibraryQuery;
            if (q != "")
            {
                RenderCrumbs("HDRI", "", f => { _hdriFolder = f; _librarySearch.Text = ""; }, L.F("risultati per \"{0}\"", _librarySearch.Text.Trim()));
                var hits = items.Where(a => ((string?)a["name"] + " " + (string?)a["folder"]).ToLowerInvariant().Contains(q)).ToList();
                foreach (var a in hits) _libraryTiles.Children.Add(HdriTile(a));
                if (hits.Count == 0) _libraryTiles.Children.Add(EmptyNote(L.T("Nessun HDRI trovato")));
                return;
            }
            var folders = new List<string> { L.T("Sfondi da studio") };
            folders.AddRange(items.Select(a => (string?)a["folder"] ?? "").Where(f => f != "").Distinct());
            if (_hdriFolder != "" && !folders.Contains(_hdriFolder)) _hdriFolder = "";
            RenderCrumbs("HDRI", _hdriFolder, f => _hdriFolder = f, null);
            if (_hdriFolder == "")
            {
                foreach (var f in folders)
                {
                    var count = f == L.T("Sfondi da studio") ? StudioBackgrounds().Count() : items.Count(a => (string?)a["folder"] == f);
                    var down = f == L.T("Sfondi da studio") ? count : items.Count(a => (string?)a["folder"] == f && ((bool?)a["downloaded"] ?? false));
                    var ff = f;
                    _libraryTiles.Children.Add(FolderTile(f, count, () => { _hdriFolder = ff; RenderLibrary(); }, "polyhaven", down));
                }
            }
            else
            {
                _libraryTiles.Children.Add(UpTile("", f => _hdriFolder = f, false));
                if (_hdriFolder == L.T("Sfondi da studio"))
                    foreach (var node in StudioBackgrounds()) _libraryTiles.Children.Add(LibraryTile(node, false));
                else
                    foreach (var a in items.Where(a => (string?)a["folder"] == _hdriFolder)) _libraryTiles.Children.Add(HdriTile(a));
            }
            var credit = Theme.Label(L.T("HDRI di Poly Haven (polyhaven.com) · CC0, liberi anche per uso commerciale · HDRI di Blender"), 11, Theme.TextFaint);
            credit.Margin = new Thickness(10, 0, 10, 0);
            _libraryTiles.Children.Add(credit);
        }

        IEnumerable<JsonObject> StudioBackgrounds() =>
            _environments.OfType<JsonObject>().Where(e => !((string?)e["id"] ?? "").StartsWith("amb_"));

        Button HdriTile(JsonObject a)
        {
            var id = (string?)a["id"] ?? "";
            var label = (string?)a["name"] ?? id;
            var tile = new StackPanel { Width = 132, Margin = new Thickness(4) };
            var img = new Border { Width = 120, Height = 60, CornerRadius = new CornerRadius(8), Background = Theme.B(Theme.Inset) };
            var downloaded = (bool?)a["downloaded"] ?? false;
            tile.Children.Add(WithBadge(img, 60, "h:" + id, downloaded && (string?)a["source"] != "blender", new Thickness(0, 8, 0, 8)));
            tile.Children.Add(Theme.TileText(new TextBlock { Text = label, FontSize = 11.5, TextAlignment = TextAlignment.Center, TextWrapping = TextWrapping.Wrap,
                                              Foreground = Theme.B(downloaded ? Theme.TextSoft : Theme.TextMuted), MaxHeight = 32 }));
            var src = (string?)a["source"] == "blender" ? L.T("HDRI di Blender (sempre disponibile)") :
                      (downloaded ? L.T("Già scaricato") : L.T("Si scarica al primo uso (4K, 20-40 MB)")) + "\nPoly Haven · CC0";
            var btn = Theme.Button(tile, Theme.Kind.Normal, label + "\n" + src + "\n" + L.T("Clic: cielo e luce della scena (il suo sole diventa una luce Sole)"));
            btn.Padding = new Thickness(2, 4, 2, 6);
            btn.Margin = new Thickness(4);
            btn.VerticalContentAlignment = VerticalAlignment.Top;
            btn.Height = 130;
            btn.Click += async (_, __) => await ApplyHdri(id, label, a);
            _ = LoadHdriThumb(id, img, (bool?)a["hasThumb"] ?? false);
            return Fav(btn, "hdri", id, label, a);
        }

        async Task ApplyHdri(string id, string label, JsonObject a)
        {
            if (_api == null) return;
            if (!((bool?)a["downloaded"] ?? false) && !await PolyHavenDownload("hdri", id, label)) return;
            a["downloaded"] = true;
            ShowBadge("h:" + id);
            Status(L.F("Misuro il sole di {0}…", label));
            await SetAmbience(new JsonObject { ["hdri"] = new JsonObject { ["id"] = id, ["name"] = label } });
            Status(L.F("Ambiente: HDRI {0}", label));
        }

        async Task LoadHdris()
        {
            for (int attempt = 0; attempt < 30; attempt++)
            {
                JsonObject? r = null;
                try { if (_api != null) r = await _api.Get("hdri/list"); } catch { }
                var list = r?["items"] as JsonArray;
                var loading = (bool?)r?["loading"] ?? false;
                if (list != null && list.Count > 0 && (!loading || attempt > 3))
                {
                    _hdris = (JsonArray)list.DeepClone();
                    if (_libraryTab == "hdri") RenderLibrary();
                    if (!loading) return;
                }
                if (r != null && !loading)
                {
                    if (list != null) { _hdris = (JsonArray)list.DeepClone(); if (_libraryTab == "hdri") RenderLibrary(); }
                    return;
                }
                await Task.Delay(1500);
            }
        }

        async Task LoadHdriThumb(string id, Border target, bool ready)
        {
            if (!_hdriThumbs.TryGetValue(id, out var bmp))
            {
                for (int i = 0; i < (ready ? 1 : 20) && bmp == null; i++)
                {
                    try
                    {
                        var bytes = await TexHttp.GetByteArrayAsync($"http://127.0.0.1:{_host.Port}/api/hdri/thumb?id={Uri.EscapeDataString(id)}");
                        var b = new BitmapImage();
                        b.BeginInit(); b.CacheOption = BitmapCacheOption.OnLoad; b.DecodePixelWidth = 160;
                        b.StreamSource = new System.IO.MemoryStream(bytes); b.EndInit(); b.Freeze();
                        bmp = b;
                        _hdriThumbs[id] = b;
                    }
                    catch { await Task.Delay(2500); }
                }
                if (bmp == null) return;
            }
            target.Background = new ImageBrush(bmp) { Stretch = Stretch.UniformToFill };
        }
    }
}
