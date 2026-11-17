using System;
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
    /// "Colori da una foto" (Cielo › Avanzate): a photo guides the colours of the sky. The engine (skyphoto.py) does
    /// not understand the picture, it compares its colours with a table of the skies Simpler can make and sets time,
    /// haze, ozone and clouds: the sky stays physical. Presets (small square photos) in a list, the user's own photo,
    /// saved as a preset if it is liked.
    /// </summary>
    public sealed partial class MainWindow
    {
        JsonObject? _skyRefs;
        JsonObject? _photoResult;          // the last analysis (similarity, palette, what was set)
        string? _photoPath;                // the last photo loaded from a file (it can be saved as a preset)

        async Task LoadSkyRefs()
        {
            await Run(async api => { _skyRefs = await api.Get("ambience/skyrefs"); });
        }

        async Task ApplySkyPhoto(JsonObject body)
        {
            var r = await AmbWrite("ambience/fromphoto", body);
            if (r == null) return;
            _photoResult = r["photo"] as JsonObject;
            await LoadRenderSettings();          // (exposure and colour rendering come from the photo too)
            await RefreshScene();
            if (_rightPanel == "ambience") RenderProps();
            if (_photoResult != null)
                Status(L.F("Cielo regolato sulla foto: somiglianza {0}%", (int?)_photoResult["similarity"] ?? 0));
        }

        void SkyPhotoSection(StackPanel to, JsonObject st)
        {
            var title = Theme.Label(L.T("Colori da una foto"), 12, Theme.TextMuted);
            title.Margin = new Thickness(0, 8, 0, 2);
            to.Children.Add(title);
            var hasTable = (bool?)_skyRefs?["table"] ?? false;
            to.Children.Add(HintSmall(hasTable
                ? L.T("Simpler confronta i colori della foto con quelli dei cieli che sa fare e regola ora, foschia, ozono, nuvole volumetriche, esposizione e resa colore. Il cielo resta fisico: la foto fa da guida, non da filtro.")
                : L.T("La tabella dei colori del cielo non è ancora pronta: le foto si potranno usare quando c'è.")));
            var cur = (string?)st["photoRef"] ?? "";
            var refs = (_skyRefs?["refs"] as JsonArray)?.OfType<JsonObject>().ToList() ?? new();
            foreach (var group in refs.Select(r => (string?)r["group"] ?? "").Distinct())
            {
                var items = refs.Where(r => (string?)r["group"] == group).ToList();
                if (items.Count == 0) continue;
                var label = group == "mie" ? L.T("Le mie foto") : L.T(char.ToUpper(group[0]) + group[1..]);
                var gl = Theme.Label(label, 11.5, Theme.TextFaint);
                gl.Margin = new Thickness(0, 2, 0, 4);
                to.Children.Add(gl);
                var wrap = new WrapPanel { Margin = new Thickness(0, 0, 0, 4) };
                foreach (var r in items)
                    wrap.Children.Add(SkyThumb(r, (string?)r["id"] == cur || (string?)r["path"] == cur, hasTable));
                to.Children.Add(wrap);
            }

            var row = new WrapPanel { Margin = new Thickness(0, 2, 0, 4) };
            var load = SmallButton(Icons.Image, L.T("Carica foto…"), async () =>
            {
                var dlg = new Microsoft.Win32.OpenFileDialog
                {
                    Filter = L.T("Immagini|*.jpg;*.jpeg;*.png;*.webp;*.tif;*.tiff;*.bmp|Tutti i file|*.*"),
                    InitialDirectory = StartFolder("image"),
                };
                if (dlg.ShowDialog(this) != true) return;
                Keep("image", dlg.FileName);
                _photoPath = dlg.FileName;
                await ApplySkyPhoto(new JsonObject { ["path"] = dlg.FileName });
            });
            load.ToolTip = L.T("Una foto qualsiasi: Simpler ne guarda solo i colori");
            load.IsEnabled = hasTable;
            load.Margin = new Thickness(0, 0, 6, 0);
            row.Children.Add(load);
            if (_photoPath != null && _photoResult != null && cur == _photoPath)
            {
                var save = SmallButton(Icons.Plus, L.T("Salva come preset"), async () =>
                {
                    var name = InputDialog.Ask(this, L.T("Salva come preset"), L.T("Nome del preset"), Path.GetFileNameWithoutExtension(_photoPath));
                    if (name == null) return;
                    JsonObject? r = null;
                    await Run(async api => { r = await api.Post("ambience/skyrefs/save", new JsonObject { ["path"] = _photoPath, ["name"] = name }); });
                    if (r == null) return;
                    _skyRefs = r;
                    // the sky stays as it is; from now on it refers to the preset
                    await AmbWrite("ambience", new JsonObject { ["photoRef"] = (string?)r["saved"] ?? "", ["presetKeep"] = (string?)st["preset"] ?? "custom" });
                    _photoPath = null;
                    RenderProps();
                    Status(L.F("Preset salvato: {0}", name));
                });
                save.ToolTip = L.T("La foto, ritagliata quadrata, resta nella lista per le prossime volte");
                row.Children.Add(save);
            }
            to.Children.Add(row);

            // what the last photo gave: its colours and what was set
            if (_photoResult != null && cur != "")
            {
                var res = new WrapPanel { Margin = new Thickness(0, 4, 0, 2) };
                foreach (var hex in (_photoResult["palette"] as JsonArray ?? new JsonArray()).Select(n => (string?)n ?? "#000000"))
                    res.Children.Add(new Border { Width = 14, Height = 14, CornerRadius = new CornerRadius(3), Margin = new Thickness(0, 0, 3, 0), Background = Theme.B(hex) });
                to.Children.Add(res);
                double Dv(string k) => (double?)_photoResult[k] ?? 0;
                var type = (string?)_photoResult["type"] ?? "";
                var typeName = type switch
                {
                    "cumuli_grandi" => L.T("Cumuli grandi"), "altocumuli" => L.T("Altocumuli"), "strati" => L.T("Strati"),
                    "cumuli_piccoli" => L.T("Cumuli piccoli"), "cumulonembo" => L.T("Cumulonembo"), "nembostrati" => L.T("Nembostrati"), _ => type,
                };
                var sim = (int?)_photoResult["similarity"] ?? 0;
                var ev = Dv("ev");
                var txt = L.F("Somiglianza {0}% · sole a {1}° · foschia {2}% · ozono {3}% · {4} {5}% · esposizione {6} EV · resa {7}",
                    sim, Dv("elev").ToString("0.#"), Math.Round(Dv("aerosol") * 100), Math.Round(Dv("ozone") * 100), typeName, Math.Round(Dv("cover") * 100),
                    (ev > 0 ? "+" : "") + ev.ToString("0.#"), (string?)_photoResult["render"] == "vivid" ? L.T("Vivida") : L.T("Naturale"));
                var info = HintSmall(txt);
                to.Children.Add(info);
                if (sim < 50)
                    to.Children.Add(HintSmall(L.T("Somiglianza bassa: i colori di questa foto sono lontani da quelli di un cielo vero, Simpler ha preso il più vicino.")));
            }
        }

        UIElement SkyThumb(JsonObject r, bool on, bool enabled)
        {
            var path = (string?)r["path"] ?? "";
            var b = new Border
            {
                Width = 46, Height = 46, CornerRadius = new CornerRadius(6), Margin = new Thickness(0, 0, 6, 6),
                BorderThickness = new Thickness(on ? 2 : 1), BorderBrush = Theme.B(on ? Theme.Accent : Theme.Line),
                Background = Theme.B(Theme.Inset), Cursor = enabled ? System.Windows.Input.Cursors.Hand : null,
                ToolTip = (string?)r["name"] ?? "",
            };
            try
            {
                var bmp = new BitmapImage();
                bmp.BeginInit();
                bmp.CacheOption = BitmapCacheOption.OnLoad;            // (the file is not kept open: it can be deleted)
                bmp.DecodePixelWidth = 92;
                bmp.UriSource = new Uri(path);
                bmp.EndInit();
                bmp.Freeze();
                b.Background = new ImageBrush(bmp) { Stretch = Stretch.UniformToFill };
            }
            catch { }
            var id = (string?)r["id"] ?? "";
            if (enabled)
                b.MouseLeftButtonUp += async (_, e) => { e.Handled = true; _photoPath = null; await ApplySkyPhoto(new JsonObject { ["ref"] = id }); };
            if ((bool?)r["user"] ?? false)
            {
                var menu = new ContextMenu();
                var del = new MenuItem { Header = L.T("Togli dai preset") };
                del.Click += async (_, __) =>
                {
                    JsonObject? res = null;
                    await Run(async api => { res = await api.Post("ambience/skyrefs/delete", new JsonObject { ["ref"] = id }); });
                    if (res == null) return;
                    _skyRefs = res;
                    RenderProps();
                };
                menu.Items.Add(del);
                b.ContextMenu = menu;
                b.ToolTip = ((string?)r["name"] ?? "") + " · " + L.T("clic destro per toglierla");
            }
            return b;
        }

        // ---------------------------------------------------------------- the table of colours, made in the background

        System.Windows.Threading.DispatcherTimer? _skyTableTimer;

        /// <summary>While the engine makes the table of sky colours in the background (a second Blender, about half
        /// an hour), its progress stays in the status bar, on the right.</summary>
        void StartSkyTableWatch()
        {
            if (_skyTableTimer != null) return;
            _skyTableTimer = new System.Windows.Threading.DispatcherTimer { Interval = TimeSpan.FromSeconds(3) };
            _skyTableTimer.Tick += async (_, __) => await SkyTableTick();
            _skyTableTimer.Start();
            _ = SkyTableTick();
        }

        bool _skyTablePolling;

        async Task SkyTableTick()
        {
            if (_api == null || _skyTablePolling) return;
            _skyTablePolling = true;
            try
            {
                JsonObject? s = null;
                try { s = await _api.Get("skytable"); } catch { return; }
                if (s == null || !((bool?)s["active"] ?? false)) { _skyTableTimer?.Stop(); _skyTableTimer = null; return; }
                bool running = (bool?)s["running"] ?? false;
                if (running)
                {
                    int done = (int?)s["done"] ?? 0, total = (int?)s["total"] ?? 0, min = (int?)s["minutes"] ?? -1;
                    _statusJob.Text = total > 0
                        ? L.F("Tabella colori del cielo: {0} di {1}", done, total) + (min >= 0 ? " · " + L.F("circa {0} min", Math.Max(1, min)) : "")
                        : L.T("Tabella colori del cielo: avvio…");
                    _statusJob.ToolTip = L.T("Simpler sta preparando in background i colori dei cieli per «Colori da una foto» (Cielo › Avanzate). Puoi lavorare; evita i render finali finché non ha finito");
                    _statusJob.Visibility = Visibility.Visible;
                    return;
                }
                _skyTableTimer?.Stop();
                _skyTableTimer = null;
                _statusJob.Visibility = Visibility.Collapsed;
                if ((bool?)s["finished"] ?? false)
                {
                    Status(L.T("Tabella dei colori del cielo pronta: «Colori da una foto» è disponibile in Cielo › Avanzate"));
                    if (_rightPanel == "ambience") { await LoadSkyRefs(); RenderProps(); }
                }
                else
                    Status(L.T("La tabella dei colori del cielo si è interrotta: riprenderà da dove era al prossimo avvio"), true);
            }
            finally { _skyTablePolling = false; }
        }
    }
}
