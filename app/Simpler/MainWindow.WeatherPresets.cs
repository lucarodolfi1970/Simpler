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
    /// <summary>A preset of the rain or of the snow saved by the user (Settings.WeatherPresets).</summary>
    public sealed class WeatherPreset
    {
        public string Kind { get; set; } = "rain";     // rain | snow
        public string Name { get; set; } = "";
        public JsonObject Values { get; set; } = new();
    }

    public partial class MainWindow
    {
        // The presets of the Avanzate of the rain and of the snow: the drops (or flakes) that fall and the drops on the
        // surfaces, all together. Wet, puddles and snow on the ground stay as they are (the main sliders of the card).
        static readonly Dictionary<string, object> RainPresetDefaults = new()
        {
            ["drop"] = false, ["dropAmount"] = 0.5, ["dropSize"] = 0.5, ["dropWind"] = 0.15, ["dropGust"] = 0.3, ["dropClear"] = 0.5,
            ["dropBlur"] = 0.6, ["splash"] = true, ["splashAmount"] = 0.5, ["puddleRings"] = 0.5,
            ["beads"] = true, ["beadAmount"] = 0.5, ["beadSize"] = 0.5, ["beadBig"] = 0.3, ["beadRivul"] = 0.4, ["beadFilm"] = 0.5,
        };
        static readonly Dictionary<string, object> SnowPresetDefaults = new()
        {
            ["fall"] = false, ["fallAmount"] = 0.5, ["fallSize"] = 0.5, ["fallWind"] = 0.2, ["fallGust"] = 0.4, ["fallZones"] = 0.4, ["fallBlur"] = 0.4,
        };

        // (tuned on renders of a street: the rain by night under street lamps, the snow by day)
        static readonly (string id, string name, string tip, double[] v)[] RainPresets =
        {
            //                                         amount size  wind  gust clear blur  splash rings beads bsize big  rivul film
            ("leggera", "Leggera", "Pioggerella: gocce fini e rade, pochi schizzi, qualche goccia sulle superfici",
                new[] { 0.22, 0.20, 0.08, 0.20, 0.55, 0.45, 0.25, 0.25, 0.30, 0.30, 0.10, 0.15, 0.30 }),
            ("moderata", "Moderata", "Pioggia normale: gocce medie, schizzi e cerchi nelle pozzanghere",
                new[] { 0.50, 0.45, 0.15, 0.30, 0.50, 0.60, 0.50, 0.50, 0.55, 0.45, 0.30, 0.40, 0.50 }),
            ("intensa", "Intensa", "Pioggia forte e un po' obliqua: gocce grosse, tanti schizzi, rivoli sulle pareti",
                new[] { 0.75, 0.70, 0.30, 0.40, 0.45, 0.65, 0.75, 0.75, 0.75, 0.55, 0.45, 0.65, 0.70 }),
            ("nubifragio", "Nubifragio", "Acquazzone con vento: cortine d'acqua fitte, la strada che ribolle di schizzi, superfici grondanti",
                new[] { 1.00, 0.90, 0.45, 0.60, 0.35, 0.70, 1.00, 1.00, 0.95, 0.65, 0.60, 0.90, 0.90 }),
        };
        static readonly string[] RainPresetKeys = { "dropAmount", "dropSize", "dropWind", "dropGust", "dropClear", "dropBlur", "splashAmount",
                                                    "puddleRings", "beadAmount", "beadSize", "beadBig", "beadRivul", "beadFilm" };
        static readonly (string id, string name, string tip, double[] v)[] SnowPresets =
        {
            //                                         amount size  wind  gust  zones blur
            ("leggera", "Leggero", "Qualche fiocco che scende piano, quasi dritto",
                new[] { 0.25, 0.40, 0.08, 0.30, 0.30, 0.35 }),
            ("intensa", "Intenso", "Nevicata fitta di grossi fiocchi, a cortine, con un po' di vento",
                new[] { 0.65, 0.70, 0.20, 0.45, 0.55, 0.45 }),
            ("tormenta", "Tormenta", "Vento forte: fiocchi fitti e fini quasi orizzontali, a mulinelli",
                new[] { 1.00, 0.60, 0.70, 0.80, 0.70, 0.30 }),
        };
        static readonly string[] SnowPresetKeys = { "fallAmount", "fallSize", "fallWind", "fallGust", "fallZones", "fallBlur" };

        static readonly Dictionary<string, ImageSource?> _weatherIcons = new();

        /// <summary>The picture of a preset (weather\rain_leggera.png...), loaded once.</summary>
        static ImageSource? WeatherIcon(string kind, string id)
        {
            var key = kind + "_" + id;
            if (_weatherIcons.TryGetValue(key, out var img)) return img;
            try
            {
                var file = System.IO.Path.Combine(AppContext.BaseDirectory, "weather", key + ".png");
                var b = new BitmapImage();
                b.BeginInit();
                b.UriSource = new Uri(file);
                b.CacheOption = BitmapCacheOption.OnLoad;
                b.DecodePixelWidth = 96;
                b.EndInit();
                b.Freeze();
                img = b;
            }
            catch { img = null; }
            return _weatherIcons[key] = img;
        }

        /// <summary>The values of a built-in preset, as sent to the engine (with the drops or flakes turned on).</summary>
        static JsonObject PresetValues(string kind, double[] v)
        {
            var keys = kind == "rain" ? RainPresetKeys : SnowPresetKeys;
            var o = new JsonObject { [kind == "rain" ? "drop" : "fall"] = true };
            if (kind == "rain") { o["splash"] = true; o["beads"] = true; }
            for (int i = 0; i < keys.Length; i++) o[keys[i]] = v[i];
            return o;
        }

        /// <summary>The current values of the keys of the presets (what a user preset saves).</summary>
        static JsonObject CurrentPresetValues(string kind, JsonObject group)
        {
            var defs = kind == "rain" ? RainPresetDefaults : SnowPresetDefaults;
            var o = new JsonObject();
            foreach (var (k, d) in defs)
            {
                var n = group[k];
                if (d is bool db) o[k] = n is JsonValue jv && jv.TryGetValue<bool>(out var b) ? b : db;
                else o[k] = (double?)n ?? (double)d;
            }
            o[kind == "rain" ? "drop" : "fall"] = true;
            return o;
        }

        /// <summary>Do the current settings equal the preset (the tile shown as chosen)?</summary>
        static bool PresetMatches(string kind, JsonObject group, JsonObject preset)
        {
            var defs = kind == "rain" ? RainPresetDefaults : SnowPresetDefaults;
            foreach (var (k, node) in preset)
            {
                if (!defs.TryGetValue(k, out var d)) continue;
                if (d is bool db)
                {
                    var cur = group[k] is JsonValue cv && cv.TryGetValue<bool>(out var cb) ? cb : db;
                    var want = node is JsonValue wv && wv.TryGetValue<bool>(out var wb) ? wb : db;
                    if (cur != want) return false;
                }
                else if (Math.Abs(((double?)group[k] ?? (double)d) - ((double?)node ?? (double)d)) > 0.004) return false;
            }
            return true;
        }

        /// <summary>A tile of a preset: its picture and its name, the chosen one outlined.</summary>
        static Border WeatherTile(ImageSource? icon, FrameworkElement? fallback, string name, bool on, string tip, Func<Task> click)
        {
            var sp = new StackPanel();
            FrameworkElement pic = icon != null
                ? new Image { Source = icon, Width = 40, Height = 40, Stretch = Stretch.Uniform, HorizontalAlignment = HorizontalAlignment.Center }
                : new Border { Width = 40, Height = 40, HorizontalAlignment = HorizontalAlignment.Center, Child = fallback };
            RenderOptions.SetBitmapScalingMode(pic, BitmapScalingMode.HighQuality);
            sp.Children.Add(pic);
            sp.Children.Add(new TextBlock
            {
                Text = name, FontSize = 11, Margin = new Thickness(0, 3, 0, 0), TextAlignment = TextAlignment.Center,
                TextTrimming = TextTrimming.CharacterEllipsis, Foreground = Theme.B(on ? Theme.Text : Theme.TextMuted),
                FontWeight = on ? FontWeights.SemiBold : FontWeights.Normal,
            });
            var idle = Theme.B(on ? Theme.Accent : Theme.Line);
            var tile = new Border
            {
                Child = sp, Padding = new Thickness(2, 5, 2, 4), Margin = new Thickness(0, 0, 6, 6), CornerRadius = new CornerRadius(9),
                BorderThickness = new Thickness(on ? 1.5 : 1), BorderBrush = idle, Cursor = Cursors.Hand,
                Background = Theme.B(on ? Theme.Selected : Theme.Inset), ToolTip = tip,
            };
            tile.MouseEnter += (_, __) => { if (!on) tile.BorderBrush = Theme.B(Theme.LineStrong); };
            tile.MouseLeave += (_, __) => tile.BorderBrush = idle;
            tile.MouseLeftButtonUp += async (_, e) => { e.Handled = true; await click(); };
            return tile;
        }

        /// <summary>The presets of the rain or of the snow (4 built in, the user's own, «Salva…»), 4 per row.</summary>
        void WeatherPresetGrid(StackPanel to, string kind, JsonObject group, bool on)
        {
            var grid = new UniformGrid { Columns = 4, Margin = new Thickness(0, 8, -6, 2) };
            foreach (var (id, name, tip, v) in kind == "rain" ? RainPresets : SnowPresets)
            {
                var vals = PresetValues(kind, v);
                grid.Children.Add(WeatherTile(WeatherIcon(kind, id), null, L.T(name), on && PresetMatches(kind, group, vals), L.T(tip),
                    async () => await SetAmbience(new JsonObject { [kind] = vals.DeepClone() })));
            }
            var s = Settings.Load();
            foreach (var p in (s.WeatherPresets ?? new()).Where(p => p != null && p.Kind == kind && p.Values != null && p.Name != "").ToList())
            {
                var vals = p.Values;
                var tile = WeatherTile(WeatherIcon(kind, "mio"), null, p.Name, on && PresetMatches(kind, group, vals),
                    p.Name + " · " + L.T("tasto destro: aggiorna, rinomina o elimina"),
                    async () => await SetAmbience(new JsonObject { [kind] = vals.DeepClone() }));
                var menu = new ContextMenu();
                var upd = new MenuItem { Header = L.T("Aggiorna con le impostazioni attuali") };
                upd.Click += (_, __) => EditWeatherPreset(kind, p.Name, x => x.Values = CurrentPresetValues(kind, group));
                var ren = new MenuItem { Header = L.T("Rinomina…") };
                ren.Click += (_, __) =>
                {
                    var n = InputDialog.Ask(this, L.T("Rinomina preset"), L.T("Nome del preset"), p.Name);
                    if (n == null || n == p.Name) return;
                    if (Settings.Load().WeatherPresets?.Any(x => x != null && x.Kind == kind && x.Name == n) ?? false)
                    {
                        Status(L.F("C'è già un preset «{0}»: scegli un altro nome", n), true);
                        return;
                    }
                    EditWeatherPreset(kind, p.Name, x => x.Name = n);
                };
                var del = new MenuItem { Header = L.T("Elimina") };
                del.Click += (_, __) => EditWeatherPreset(kind, p.Name, null);
                menu.Items.Add(upd); menu.Items.Add(ren); menu.Items.Add(new Separator()); menu.Items.Add(del);
                tile.ContextMenu = menu;
                grid.Children.Add(tile);
            }
            var plus = Theme.Icon(Icons.Plus, Theme.TextMuted, 20, 1.8);
            plus.HorizontalAlignment = HorizontalAlignment.Center; plus.VerticalAlignment = VerticalAlignment.Center;
            grid.Children.Add(WeatherTile(null, plus, L.T("Salva…"),
                false, kind == "rain" ? L.T("Salva le impostazioni attuali della pioggia come un tuo preset, con il nome che vuoi")
                                      : L.T("Salva le impostazioni attuali della neve che cade come un tuo preset, con il nome che vuoi"),
                () =>
                {
                    var n = InputDialog.Ask(this, L.T("Salva preset"), L.T("Nome del preset"), L.T("Il mio preset"));
                    if (n != null)
                    {
                        var st = Settings.Load();
                        st.WeatherPresets ??= new();
                        st.WeatherPresets.RemoveAll(x => x == null || (x.Kind == kind && x.Name == n));    // (the same name: replaced)
                        st.WeatherPresets.Add(new WeatherPreset { Kind = kind, Name = n, Values = CurrentPresetValues(kind, group) });
                        st.Save();
                        RenderProps();
                    }
                    return Task.CompletedTask;
                }));
            to.Children.Add(grid);
        }

        void EditWeatherPreset(string kind, string name, Action<WeatherPreset>? change)
        {
            var st = Settings.Load();
            st.WeatherPresets ??= new();
            var p = st.WeatherPresets.FirstOrDefault(x => x != null && x.Kind == kind && x.Name == name);
            if (p == null) return;
            if (change == null) st.WeatherPresets.Remove(p);
            else change(p);
            st.Save();
            RenderProps();
        }

        /// <summary>«Regola a mano»: a small fold that keeps the many sliders out of the way (open or closed is
        /// remembered like the Avanzate boxes). Returns the panel to fill, or null when closed.</summary>
        StackPanel? ManualFold(StackPanel to, string key)
        {
            var fullKey = "manual:" + key;
            bool open = _openAdvanced.Contains(fullKey);
            var chevron = Theme.Icon(ChevronDown, Theme.TextMuted, 12, 2);
            chevron.RenderTransformOrigin = new Point(0.5, 0.5);
            chevron.RenderTransform = new RotateTransform(open ? 0 : -90);
            chevron.VerticalAlignment = VerticalAlignment.Center;
            var header = new StackPanel { Orientation = Orientation.Horizontal, Background = Brushes.Transparent, Cursor = Cursors.Hand, Margin = new Thickness(0, 4, 0, 6) };
            header.ToolTip = L.T("Tutti i valori, uno per uno: un preset li imposta tutti insieme");
            header.Children.Add(chevron);
            var t = Theme.Label(L.T("Regola a mano"), 12, Theme.TextMuted);
            t.Margin = new Thickness(5, 0, 0, 0);
            t.VerticalAlignment = VerticalAlignment.Center;
            header.Children.Add(t);
            header.MouseLeftButtonUp += (_, e) =>
            {
                e.Handled = true;
                if (open) _openAdvanced.Remove(fullKey); else _openAdvanced.Add(fullKey);
                RenderProps();
            };
            to.Children.Add(header);
            if (!open) return null;
            var body = new StackPanel();
            to.Children.Add(body);
            return body;
        }
    }
}
