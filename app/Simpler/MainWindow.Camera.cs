using System;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;

namespace Simpler
{
    /// <summary>"Fotocamera" panel: focal length, depth of field (click-to-focus), lens shift / two-point
    /// perspective and frame format (guides in the view, same framing in the final render).</summary>
    public sealed partial class MainWindow
    {
        static readonly (string id, string label)[] Formats =
        {
            ("", "Libero"), ("16:9", "16:9"), ("3:2", "3:2"), ("4:3", "4:3"), ("1:1", "1:1"),
            ("4:5", "4:5"), ("2:3", "2:3"), ("9:16", "9:16"), ("A4", "A4 orizz."), ("A4v", "A4 vert."),
        };

        static double FormatAspect(string id) => id switch
        {
            "16:9" => 16.0 / 9, "3:2" => 1.5, "4:3" => 4.0 / 3, "1:1" => 1, "4:5" => 0.8, "2:3" => 2.0 / 3,
            "9:16" => 9.0 / 16, "A4" => 297.0 / 210, "A4v" => 210.0 / 297, _ => 0,
        };

        /// <summary>Lens shift and frame guide to the real-time view.</summary>
        void SendCameraOptions(JsonObject view)
        {
            SendToWeb(new
            {
                type = "cameraOpts",
                shiftX = (double?)view["shiftX"] ?? 0,
                shiftY = (double?)view["shiftY"] ?? 0,
                aspect = FormatAspect((string?)view["format"] ?? ""),
            });
        }

        async Task CameraSet(JsonObject body, bool rerender = true)
        {
            body["action"] = "settings";
            await Run(async api => { await api.Post("camera", body); });
            await LoadRenderSettings();
            if (_renderSettings["view"] is JsonObject view) SendCameraOptions(view);
            if (rerender) RenderProps();
        }

        void RenderCameraPanel()
        {
            var view = _renderSettings["view"] as JsonObject ?? new JsonObject();
            double V(string k, double d) => (double?)view[k] ?? d;
            bool dof = (bool?)view["dof"] ?? false;
            var cur = (string?)view["format"] ?? "";

            var head = new StackPanel();
            var top = new DockPanel();
            var close = Theme.Button(L.T("Chiudi"), Theme.Kind.Ghost, L.T("Torna alle proprietà dell'oggetto"));
            close.Click += async (_, __) => await ShowRightPanel("");
            DockPanel.SetDock(close, Dock.Right);
            top.Children.Add(close);
            top.Children.Add(Theme.Caption(L.T("Fotocamera")));
            head.Children.Add(top);
            head.Children.Add(HintSmall(L.T("Valgono per il path tracing e per il render finale. Salva l'inquadratura nella scheda Scene.")));
            _props.Children.Add(Theme.Card(head, 16));

            // ---- lens
            var lens = new StackPanel();
            lens.Children.Add(SectionTitle(L.T("Obiettivo")));
            var focal = new ValueSlider(L.T("Focale"), V("lens", 50), 10, 400, true, "0", "mm", null,
                L.T("Grandangolo (14-24 mm) per interni, normale (35-50 mm), tele (85-200 mm) per oggetti e ritratti senza distorsione"));
            focal.Changing += v => SendToWeb(new { type = "lens", mm = v });
            focal.Committed += async v => { SendToWeb(new { type = "lens", mm = v }); await Task.Delay(400); await LoadRenderSettings(); };
            lens.Children.Add(focal);
            var presets = new WrapPanel { Margin = new Thickness(96, 0, 0, 6) };
            foreach (var mm in new[] { 14, 24, 35, 50, 85, 135, 200 })
            {
                var b = Theme.Button($"{mm}", Theme.Kind.Ghost, L.F("Obiettivo {0} mm", mm));
                b.MinHeight = 26; b.FontSize = 12; b.Padding = new Thickness(8, 0, 8, 0); b.Margin = new Thickness(0, 0, 4, 4);
                b.Click += async (_, __) => { SendToWeb(new { type = "lens", mm }); await Task.Delay(400); await LoadRenderSettings(); RenderProps(); };
                presets.Children.Add(b);
            }
            lens.Children.Add(presets);
            _props.Children.Add(Theme.Card(lens, 16));

            // ---- depth of field
            var d = new StackPanel();
            d.Children.Add(SectionTitle(L.T("Profondità di campo")));
            var dofToggle = new Toggle(L.T("Sfocatura (profondità di campo)"), dof, L.T("Mette a fuoco un punto e sfoca il resto, come una vera fotocamera"));
            dofToggle.Toggled += async v => await CameraSet(new JsonObject { ["dof"] = v });
            d.Children.Add(dofToggle);
            if (dof)
            {
                var focusBtn = Theme.Button(Theme.IconText(Icons.Frame, L.T("Metti a fuoco con un clic")), Theme.Kind.Primary,
                    L.T("Poi clicca nella vista il punto che deve essere nitido"));
                focusBtn.HorizontalAlignment = HorizontalAlignment.Left;
                focusBtn.Margin = new Thickness(0, 0, 0, 12);
                focusBtn.Click += (_, __) => { SendToWeb(new { type = "pickFocus" }); Status(L.T("Clicca nella vista il punto da mettere a fuoco")); };
                d.Children.Add(focusBtn);
                d.Children.Add(CamSlider(L.T("Distanza di fuoco"), "focus", V("focus", 100), 1, 100000, true, "0.#", "cm", L.T("Distanza dalla fotocamera del piano nitido")));
                d.Children.Add(CamSlider(L.T("Apertura"), "fstop", V("fstop", 2.8), 0.7, 32, true, "0.#", "f/", L.T("f/1.4 = sfocato molto, f/16 = quasi tutto nitido. Sugli oggetti piccoli la sfocatura è molto forte")));
                var da = Advanced(d, "dof");
                da.Body.Children.Add(CamSlider(L.T("Lamelle"), "blades", V("blades", 0), 0, 12, false, "0", null, L.T("Forma del bokeh: 0 = rotondo, 5-8 = poligonale")));
                if (V("blades", 0) >= 3)
                    da.Body.Children.Add(CamSlider(L.T("Rotazione lamelle"), "bladeRotation", V("bladeRotation", 0), 0, 180, false, "0.##", "°", L.T("Ruota la forma del bokeh")));
                da.Done(V("blades", 0) != 0 || V("bladeRotation", 0) != 0,
                        async () => await CameraSet(new JsonObject { ["blades"] = 0, ["bladeRotation"] = 0.0 }, true));
            }
            _props.Children.Add(Theme.Card(d, 16));

            // ---- perspective
            var p = new StackPanel();
            p.Children.Add(SectionTitle(L.T("Prospettiva")));
            var straight = Theme.Button(L.T("Raddrizza le verticali (2 punti)"), Theme.Kind.Normal,
                L.T("Mette la fotocamera in bolla e recupera l'inquadratura con il decentramento: pareti e oggetti alti restano diritti"));
            straight.HorizontalAlignment = HorizontalAlignment.Left;
            straight.Margin = new Thickness(0, 0, 0, 12);
            straight.Click += async (_, __) =>
            {
                JsonObject? r = null;
                await Run(async api => { r = await api.Post("camera", new { action = "twoPoint" }); });
                await LoadRenderSettings();
                if (_renderSettings["view"] is JsonObject v2) { SendToWeb(new { type = "setCamera", view = v2.DeepClone() }); SendCameraOptions(v2); }
                RenderProps();
            };
            p.Children.Add(straight);
            var pa = Advanced(p, "shift");
            pa.Body.Children.Add(CamSlider(L.T("Decentra orizz."), "shiftX", V("shiftX", 0), -1, 1, false, "0.###", null, L.T("Sposta l'inquadratura senza ruotare la fotocamera")));
            pa.Body.Children.Add(CamSlider(L.T("Decentra vert."), "shiftY", V("shiftY", 0), -1, 1, false, "0.###", null, L.T("Sposta l'inquadratura in alto o in basso senza inclinare la fotocamera")));
            pa.Done(Diff(V("shiftX", 0), 0) || Diff(V("shiftY", 0), 0),
                    async () => await CameraSet(new JsonObject { ["shiftX"] = 0.0, ["shiftY"] = 0.0 }, true));
            _props.Children.Add(Theme.Card(p, 16));

            // ---- format
            var f = new StackPanel();
            f.Children.Add(SectionTitle(L.T("Formato dell'immagine")));
            f.Children.Add(HintSmall(L.T("Mostra nella vista la cornice dell'immagine finale; il render finale userà questa proporzione.")));
            var wrap = new WrapPanel();
            foreach (var (id, label) in Formats)
            {
                var b = Theme.Button(id == "" ? L.T(label) : (id.StartsWith("A4") ? L.T(label) : label), id == cur ? Theme.Kind.Segment : Theme.Kind.Ghost);
                b.MinHeight = 28; b.FontSize = 12; b.Margin = new Thickness(0, 0, 4, 4);
                var fid = id;
                b.Click += async (_, __) => await CameraSet(new JsonObject { ["format"] = fid });
                wrap.Children.Add(b);
            }
            f.Children.Add(wrap);
            _props.Children.Add(Theme.Card(f, 16));

            UIElement CamSlider(string label, string key, double value, double min, double max, bool log, string fmt, string? unit, string tip)
            {
                var s = new ValueSlider(label, value, min, max, log, fmt, unit, null, tip);
                if (key.StartsWith("shift"))
                    s.Changing += v => SendToWeb(new { type = "cameraOpts", shiftX = key == "shiftX" ? v : V("shiftX", 0), shiftY = key == "shiftY" ? v : V("shiftY", 0), aspect = FormatAspect(cur) });
                s.Committed += async v => await CameraSet(new JsonObject { [key] = fmt == "0" ? JsonValue.Create((int)Math.Round(v)) : JsonValue.Create(v) }, key == "blades");
                return s;
            }
        }

        static UIElement HintSmall(string text)
        {
            var t = Theme.Label(text, 12, Theme.TextFaint);
            t.TextWrapping = TextWrapping.Wrap;
            t.Margin = new Thickness(0, 6, 0, 10);
            return t;
        }

        /// <summary>The viewer measured the distance of the clicked point: focus there.</summary>
        async Task OnFocusPicked(double distanceCm)
        {
            await CameraSet(new JsonObject { ["focus"] = Math.Round(distanceCm, 2), ["dof"] = true }, _rightPanel == "camera");
            Status(L.F("A fuoco a {0} cm", Num.F(distanceCm, 1)));
        }
    }
}
