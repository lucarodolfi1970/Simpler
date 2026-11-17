using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;

namespace Simpler
{
    /// <summary>
    /// The AI panel (right sidebar, AI button with a working key). From the top: the key (works, test, delete), the
    /// tokens used, the engine (model, quality), the picture to process (the view as it is on screen, the last final
    /// render, a file, a picture opened in Simpler), the functions as small before/after cards, the options of the
    /// chosen one, Esegui. The result opens in its own window with the before/after line.
    /// </summary>
    public sealed partial class MainWindow
    {
        string _aiFn = "render";
        readonly Dictionary<string, Dictionary<string, string>> _aiSel = new();     // per function: key -> option
        readonly Dictionary<string, HashSet<string>> _aiMulti = new();
        string _aiSource = "view";                 // view | render | image
        BitmapSource? _aiImage;                    // a picture opened in Simpler or loaded from a file
        string _aiImageLabel = "";
        string? _lastRenderPath;
        string? _aiRefPath;                        // Sostituisci: the photo of the object
        CancellationTokenSource? _aiCts;
        DateTime _aiStart;
        TextBlock? _aiStatus;
        DispatcherTimer? _aiTimer;
        long _aiLastIn = -1, _aiLastOut = -1;

        Dictionary<string, string> Sel => _aiSel.TryGetValue(_aiFn, out var d) ? d : (_aiSel[_aiFn] = new Dictionary<string, string>());
        HashSet<string> Multi => _aiMulti.TryGetValue(_aiFn, out var m) ? m : (_aiMulti[_aiFn] = new HashSet<string>());

        // measured on renderAI (seconds): to let the bar say how long it should take
        static readonly Dictionary<string, (int low, int medium, int high)> AiSeconds = new()
        {
            ["gpt-image-1-mini"] = (25, 35, 60), ["gpt-image-1.5"] = (20, 30, 70), ["gpt-image-2"] = (35, 70, 120),
        };

        int _aiProjectGen;      // +1 at every Nuova scena / Apri: a result that arrives later doesn't go into another project

        /// <summary>Before Nuova scena, Apri or closing Simpler: an AI processing in progress would end up in the wrong
        /// project or be lost. Asks: No = wait for it (nothing happens), Yes = cancel it and go on. True = go on.</summary>
        bool AiRunningAllows()
        {
            if (_aiCts == null) return true;
            var q = L.T("È in corso un'elaborazione AI: il risultato andrebbe perso.\n\nAnnullarla e continuare?\n(No: aspetta che finisca; i token già usati da OpenAI vengono comunque addebitati)");
            if (Msg.Show(this, q, "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Warning) != MessageBoxResult.Yes) return false;
            _aiCts?.Cancel();
            return true;
        }

        /// <summary>AI button: with a working key the panel, otherwise the window to enter or fix the key.</summary>
        async Task ToggleAiPanel()
        {
            if (!AiKey.Exists || AiKey.Ok == false) { ShowAiDialog(); if (AiKey.Exists && AiKey.Ok == true) await ShowRightPanel("ai"); return; }
            await ShowRightPanel(_rightPanel == "ai" ? "" : "ai");
        }

        /// <summary>A picture from a window of Simpler (a final render, an AI result) becomes the one to process.</summary>
        void SetAiImage(BitmapSource bmp, string label)
        {
            _aiImage = bmp; _aiImageLabel = label; _aiSource = "image";
            if (!AiKey.Exists || AiKey.Ok == false) { Activate(); ShowAiDialog(); return; }
            Activate();
            _ = ShowRightPanel("ai");
        }

        /// <summary>The final render opens in Simpler's picture window (zoom, save, copy, "Elabora con l'AI", "Apri fuori");
        /// an EXR, or a picture Windows can't decode, opens in the system viewer as before.</summary>
        void ShowRenderResult(string path, JsonObject? stats = null)
        {
            BitmapSource? bmp = null;
            if (!path.EndsWith(".exr", StringComparison.OrdinalIgnoreCase))
                try { bmp = AiImage.Decode(File.ReadAllBytes(path)); } catch (Exception ex) { AppLog.Write("render view: " + ex.Message); }
            if (bmp == null)
            {
                try { System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(path) { UseShellExecute = true }); } catch { }
                return;
            }
            var w = new AiImageWindow(this, L.T("Render finale") + " · " + Path.GetFileName(path), bmp, null, SetAiImage, path);
            if (stats != null)
            {
                try { var (text, tip) = RenderStatsText(stats); w.SetInfo(text, tip); }
                catch (Exception ex) { AppLog.Write("render stats: " + ex.Message); }
            }
            w.Show();
        }

        /// <summary>(1.75.10) The line at the top of the final image: time, peaks of the card and of the memory; the
        /// phases in the tooltip.</summary>
        static (string text, string tip) RenderStatsText(JsonObject st)
        {
            static double? D(JsonNode? n) { try { return n == null ? null : (double?)n; } catch { return null; } }
            static string T(double s) => s < 60 ? s.ToString("0.#") + " s" : $"{(int)(s / 60)}:{(int)(s % 60):00}";
            static string G(double b) => (b / 1073741824.0).ToString("0.0") + " GB";
            var parts = new System.Collections.Generic.List<string>();
            var tips = new System.Collections.Generic.List<string>();
            if (D(st["total"]) is double tot) parts.Add(L.F("Tempo {0}", T(tot)));
            if (D(st["sampling"]) is double smp)
            {
                parts.Add(L.F("calcolo {0}", T(smp)));
                tips.Add(L.F("Preparazione della scena: {0}", T(D(st["prepare"]) ?? 0)));
                tips.Add(L.F("Caricamento di geometrie e texture: {0}", T(D(st["load"]) ?? 0)));
                tips.Add(L.F("Calcolo dei campioni: {0}", T(smp)));
                if ((D(st["denoise"]) ?? 0) > 0) tips.Add(L.F("Riduzione del rumore: {0}", T(D(st["denoise"]) ?? 0)));
                if ((D(st["finish"]) ?? 0) > 0.05) tips.Add(L.F("Salvataggio e colore: {0}", T(D(st["finish"]) ?? 0)));
            }
            if (D(st["vramPeak"]) is double vp)
            {
                var vt = D(st["vramTotal"]);
                parts.Add(vt is double t1 ? L.F("VRAM picco {0} di {1}", G(vp), G(t1)) : L.F("VRAM picco {0}", G(vp)));
                if (D(st["vramFree"]) is double vf) tips.Add(L.F("Scheda video già occupata prima del render: {0} (Windows, altri programmi)", G(vf)));
            }
            if (D(st["cyclesPeak"]) is double cp) tips.Add(L.F("Memoria dichiarata da Cycles (picco): {0}", G(cp)));
            if (D(st["ramPeak"]) is double rp)
            {
                var rt = D(st["ramTotal"]);
                parts.Add(rt is double t2 ? L.F("RAM picco {0} di {1}", G(rp), G(t2)) : L.F("RAM picco {0}", G(rp)));
            }
            if ((string?)st["gpu"] is string gname && gname != "") tips.Add(gname);
            return (string.Join("  ·  ", parts), string.Join("\n", tips));
        }

        string AiModel()
        {
            var models = AiModels();
            var s = Settings.Load().AiModel;
            if (s != "" && models.Contains(s)) return s;
            return models.FirstOrDefault(m => m == "gpt-image-2") ?? models.FirstOrDefault() ?? "gpt-image-2";
        }

        static List<string> AiModels()
        {
            // dated snapshots (…-2026-04-21) are the same models: only the names that follow the latest version
            var list = AiKey.ImageModels.Where(m => !System.Text.RegularExpressions.Regex.IsMatch(m, @"-\d{4}-\d{2}-\d{2}$")).ToList();
            return list.Count > 0 ? list : new List<string> { "gpt-image-2" };
        }

        static (string name, string hint) ModelInfo(string id) => id switch
        {
            "gpt-image-2" => ("GPT Image 2", L.T("Il migliore per il fotorealismo: consigliato per le immagini finali")),
            "gpt-image-1.5" => ("GPT Image 1.5", L.T("Il modello precedente: costo simile a GPT Image 2, sceglilo solo se ne preferisci la resa")),
            "gpt-image-1-mini" => ("GPT Image 1 Mini", L.T("Circa un terzo dei token: ottimo per prove veloci")),
            "gpt-image-1" => ("GPT Image 1", L.T("Il primo modello di immagini di OpenAI")),
            "chatgpt-image-latest" => ("ChatGPT Image (ultimo)", L.T("Il modello di immagini usato da ChatGPT in questo momento")),
            _ => (id, L.T("Modello di immagini di OpenAI")),
        };

        void RenderAiPanel()
        {
            var settings = Settings.Load();

            // ---- header
            var head = new StackPanel();
            var top = new DockPanel();
            var close = Theme.Button(L.T("Chiudi"), Theme.Kind.Ghost, L.T("Torna alle proprietà dell'oggetto"));
            close.Click += async (_, __) => await ShowRightPanel("");
            DockPanel.SetDock(close, Dock.Right);
            top.Children.Add(close);
            top.Children.Add(Theme.Caption(L.T("Intelligenza artificiale")));
            head.Children.Add(top);
            _props.Children.Add(Theme.Card(head, 16));

            // ---- 1. the key
            var key = new StackPanel();
            key.Children.Add(SectionTitle(L.T("Chiave OpenAI")));
            var st = new DockPanel { Margin = new Thickness(0, 0, 0, 8) };
            bool ok = AiKey.Ok == true;
            var mark = Theme.Icon(ok ? Geometry.Parse("M5 12.5l4.5 4.5L19 7.5") : Geometry.Parse("M12 7v6 M12 16.5v.5"), ok ? Theme.AxisY : Theme.Warm, 18, 2.4);
            mark.Margin = new Thickness(0, 0, 8, 0); mark.VerticalAlignment = VerticalAlignment.Top;
            DockPanel.SetDock(mark, Dock.Left);
            st.Children.Add(mark);
            var stt = Theme.Label(ok ? L.T("Funziona: la parte ChatGPT image è attiva.") : L.T("Verifica della chiave in corso…"), 12.5, ok ? Theme.AxisY : Theme.TextMuted);
            stt.TextWrapping = TextWrapping.Wrap;
            st.Children.Add(stt);
            key.Children.Add(st);
            var kb = new WrapPanel();
            kb.Children.Add(SmallButton(Icons.Refresh, L.T("Verifica di nuovo"), async () => { await AiKey.TestAsync(); UpdateAiButton(); if (AiKey.Ok == false) { await ShowRightPanel(""); ShowAiDialog(); } else RenderProps(); }));
            var del = SmallButton(Icons.Trash, L.T("Elimina chiave"), async () =>
            {
                if (Msg.Show(this, L.T("Eliminare la chiave API da Simpler? Le funzioni AI si spengono finché non ne inserisci una."), "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
                AiKey.Delete();
                UpdateAiButton();
                await ShowRightPanel("");
            });
            kb.Children.Add(del);
            key.Children.Add(kb);
            _props.Children.Add(Theme.Card(key, 16));

            // ---- 2. tokens
            var tk = new StackPanel();
            tk.Children.Add(SectionTitle(L.T("Consumo")));
            tk.Children.Add(TokenRow(L.T("Ultima immagine"), _aiLastIn, _aiLastOut));
            tk.Children.Add(TokenRow(L.T("Totale"), settings.AiTokensIn, settings.AiTokensOut));
            var reset = SmallButton(Icons.Refresh, L.T("Azzera il totale"), () =>
            {
                var s = Settings.Load(); s.AiTokensIn = s.AiTokensOut = 0; s.Save(); RenderProps(); return Task.CompletedTask;
            });
            reset.HorizontalAlignment = HorizontalAlignment.Left;
            reset.Margin = new Thickness(0, 4, 0, 0);
            tk.Children.Add(reset);
            tk.Children.Add(HintSmall(L.T("Token usati da OpenAI per le tue immagini (ingresso: la tua immagine e le istruzioni; uscita: l'immagine generata). Il costo lo vedi sul tuo account OpenAI.")));
            _props.Children.Add(Theme.Card(tk, 16));

            // ---- 3. engine
            var en = new StackPanel();
            en.Children.Add(SectionTitle(L.T("Motore")));
            var model = AiModel();
            var mw = new WrapPanel { Margin = new Thickness(0, 0, 0, 4) };
            foreach (var m in AiModels())
            {
                var (name, hint) = ModelInfo(m);
                var b = Theme.Button(name, m == model ? Theme.Kind.Segment : Theme.Kind.Ghost, hint);
                b.MinHeight = 28; b.FontSize = 12; b.Padding = new Thickness(10, 0, 10, 0); b.Margin = new Thickness(0, 0, 6, 6);
                var id = m;
                b.Click += (_, __) => { var s = Settings.Load(); s.AiModel = id; s.Save(); RenderProps(); };
                mw.Children.Add(b);
            }
            en.Children.Add(mw);
            en.Children.Add(HintSmall(ModelInfo(model).hint));
            var qIds = new[] { "low", "medium", "high" };
            var q = Theme.Segmented(out var qb, (L.T("Bassa"), L.T("Economica, per le prove")), (L.T("Media"), L.T("Equilibrata")), (L.T("Alta"), L.T("Il massimo, più token")));
            Theme.SetSegment(qb, Math.Max(0, Array.IndexOf(qIds, settings.AiQuality)));
            for (int i = 0; i < qb.Count; i++) { var v = qIds[i]; qb[i].Click += (_, __) => { var s = Settings.Load(); s.AiQuality = v; s.Save(); RenderProps(); }; }
            en.Children.Add(Row(L.T("Qualità"), q));
            _props.Children.Add(Theme.Card(en, 16));

            // ---- 4. the picture
            var src = new StackPanel();
            src.Children.Add(SectionTitle(L.T("Immagine da elaborare")));
            var srcIds = new List<string> { "view", "render" };
            var labels = new List<(object content, string? tooltip)>
            {
                (L.T("La vista"), L.T("Esattamente come la vedi ora: sagome, tempo reale o path tracing")),
                (L.T("Ultimo render"), L.T("L'ultimo render finale di questa sessione")),
            };
            if (_aiImage != null) { srcIds.Add("image"); labels.Add((L.T("Immagine aperta"), _aiImageLabel)); }
            var sseg = Theme.Segmented(out var sb, labels.ToArray());
            if (_aiSource == "render" && _lastRenderPath == null) _aiSource = "view";
            if (_aiSource == "image" && _aiImage == null) _aiSource = "view";
            Theme.SetSegment(sb, srcIds.IndexOf(_aiSource));
            for (int i = 0; i < sb.Count; i++) { var v = srcIds[i]; sb[i].Click += (_, __) => { _aiSource = v; RenderProps(); }; }
            sb[1].IsEnabled = _lastRenderPath != null;
            sseg.HorizontalAlignment = HorizontalAlignment.Left;
            sseg.Margin = new Thickness(0, 0, 0, 6);
            src.Children.Add(sseg);
            src.Children.Add(HintSmall(_aiSource switch
            {
                "render" => L.F("Render finale: {0}", Path.GetFileName(_lastRenderPath ?? "")),
                "image" => L.F("Immagine: {0}", _aiImageLabel),
                _ => _realistic ? L.T("La vista in path tracing, con l'immagine raggiunta finora: aspetta qualche passaggio per una base più pulita.")
                                : L.T("La vista in tempo reale (o le sagome), senza gizmo né selezioni, nella proporzione del formato scelto."),
            }));
            _props.Children.Add(Theme.Card(src, 16));

            // ---- 5. functions
            var fn = new StackPanel();
            fn.Children.Add(SectionTitle(L.T("Funzione")));
            fn.Children.Add(AiFunctionPicker());
            _props.Children.Add(Theme.Card(fn, 16));

            // ---- 6. options of the function
            var op = new StackPanel();
            var fd = AiPrompts.Functions.First(x => x.Key == _aiFn);
            op.Children.Add(SectionTitle(L.T(fd.Name)));
            AiOptions(op);
            var notes = Theme.Input(Sel.TryGetValue("notes", out var nt) ? nt : "");
            notes.TextWrapping = TextWrapping.Wrap; notes.AcceptsReturn = true; notes.MinHeight = 54; notes.MaxLength = 600;
            notes.TextChanged += (_, __) => Sel["notes"] = notes.Text;
            op.Children.Add(Theme.Label(L.T("Note finali (facoltative, in qualsiasi lingua)"), 12, Theme.TextMuted));
            notes.Margin = new Thickness(0, 4, 0, 10);
            op.Children.Add(notes);

            var run = Theme.Button(SparkleText(_aiCts != null ? L.T("Annulla") : L.T("Esegui")), Theme.Kind.Primary,
                L.T("Manda l'immagine e le scelte a OpenAI e apre il risultato"));
            run.HorizontalAlignment = HorizontalAlignment.Stretch;
            run.MinHeight = 36;
            run.Click += async (_, __) => { if (_aiCts != null) _aiCts.Cancel(); else await RunAi(); };
            op.Children.Add(run);
            _aiStatus = Theme.Label("", 12, Theme.TextMuted);
            _aiStatus.TextWrapping = TextWrapping.Wrap;
            _aiStatus.Margin = new Thickness(0, 8, 0, 0);
            op.Children.Add(_aiStatus);
            _props.Children.Add(Theme.Card(op, 16));
        }

        static UIElement SparkleText(string text)
        {
            var sp = new StackPanel { Orientation = Orientation.Horizontal };
            sp.Children.Add(new System.Windows.Shapes.Path { Data = SparklesIcon, Width = 15, Height = 15, Stretch = Stretch.Uniform, Fill = Theme.B(Theme.AccentText), VerticalAlignment = VerticalAlignment.Center });
            sp.Children.Add(new TextBlock { Text = text, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(8, 0, 0, 0) });
            return sp;
        }

        UIElement TokenRow(string label, long tin, long tout)
        {
            var g = new DockPanel { Margin = new Thickness(0, 0, 0, 4) };
            var l = Theme.Label(label, 12, Theme.TextMuted); l.Width = 110;
            g.Children.Add(l);
            g.Children.Add(Theme.Label(tin < 0 ? "—" : L.F("{0} in · {1} out", tin.ToString("N0"), tout.ToString("N0")), 12.5, Theme.Text));
            return g;
        }

        /// <summary>The function chooser: a drop-down that shows only the chosen function (thumbnail, name, a few words);
        /// a click opens the list of all of them under it, a click on one picks it and the options below follow.</summary>
        UIElement AiFunctionPicker()
        {
            var cur = AiPrompts.Functions.FirstOrDefault(x => x.Key == _aiFn) ?? AiPrompts.Functions[0];
            var head = new DockPanel();
            var chev = Theme.Icon(Geometry.Parse("M6 9l6 6 6-6"), Theme.TextSoft, 16, 2);
            chev.Margin = new Thickness(6, 0, 4, 0);
            DockPanel.SetDock(chev, Dock.Right);
            head.Children.Add(chev);
            head.Children.Add(AiFunctionContent(cur, true));
            var box = new Border
            {
                Child = head, Padding = new Thickness(5), CornerRadius = new CornerRadius(8), Cursor = Cursors.Hand,
                BorderThickness = new Thickness(1), BorderBrush = Theme.B(Theme.LineStrong), Background = Theme.B(Theme.Inset),
                ToolTip = L.T("Scegli la funzione"),
            };
            box.MouseEnter += (_, __) => box.BorderBrush = Theme.B(Theme.Accent);
            box.MouseLeave += (_, __) => box.BorderBrush = Theme.B(Theme.LineStrong);
            box.MouseLeftButtonUp += (_, __) =>
            {
                var list = new StackPanel { Margin = new Thickness(5) };
                var popup = new System.Windows.Controls.Primitives.Popup
                {
                    PlacementTarget = box, Placement = System.Windows.Controls.Primitives.PlacementMode.Bottom, StaysOpen = false, AllowsTransparency = true,
                    VerticalOffset = 4, PopupAnimation = System.Windows.Controls.Primitives.PopupAnimation.Fade,
                };
                foreach (var f in AiPrompts.Functions)
                {
                    bool on = f.Key == _aiFn;
                    var row = new Border
                    {
                        Child = AiFunctionContent(f, on), Padding = new Thickness(5), Margin = new Thickness(0, 0, 0, 2), CornerRadius = new CornerRadius(6), Cursor = Cursors.Hand,
                        Background = on ? Theme.B(Theme.Selected) : Brushes.Transparent,
                    };
                    if (!on)
                    {
                        row.MouseEnter += (_, __) => row.Background = Theme.B("#13213B");
                        row.MouseLeave += (_, __) => row.Background = Brushes.Transparent;
                    }
                    row.MouseLeftButtonUp += (_, __) =>
                    {
                        popup.IsOpen = false;
                        if (_aiFn != f.Key) { _aiFn = f.Key; RenderProps(); }
                    };
                    list.Children.Add(row);
                }
                var scroll = new ScrollViewer { Content = list, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, MaxHeight = 560 };
                popup.Child = new Border
                {
                    Child = scroll, Width = Math.Max(240, box.ActualWidth), Background = Theme.B(Theme.Raised), BorderBrush = Theme.B(Theme.LineStrong),
                    BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(8),
                };
                popup.IsOpen = true;
            };
            return box;
        }

        /// <summary>Thumbnail of a function (before/after) with its name and a few words on what it does.</summary>
        UIElement AiFunctionContent(AiPrompts.Function f, bool on)
        {
            var row = new DockPanel();
            var img = new Border { Width = 96, Height = 64, CornerRadius = new CornerRadius(5), Background = Theme.B(Theme.Inset), Margin = new Thickness(0, 0, 10, 0) };
            try
            {
                var bmp = new BitmapImage();
                bmp.BeginInit();
                bmp.CacheOption = BitmapCacheOption.OnLoad;
                bmp.UriSource = new Uri(Path.Combine(AppContext.BaseDirectory, "ai", f.Card));
                bmp.DecodePixelWidth = 200;
                bmp.EndInit();
                bmp.Freeze();
                img.Background = new ImageBrush(bmp) { Stretch = Stretch.UniformToFill };
            }
            catch { }
            DockPanel.SetDock(img, Dock.Left);
            row.Children.Add(img);
            var txt = new StackPanel { VerticalAlignment = VerticalAlignment.Center };
            var name = Theme.Label(L.T(f.Name), 13, Theme.Text);
            name.FontWeight = on ? FontWeights.SemiBold : FontWeights.Normal;
            name.TextWrapping = TextWrapping.Wrap;
            txt.Children.Add(name);
            var desc = Theme.Label(L.T(f.Desc), 11.5, Theme.TextFaint);
            desc.TextWrapping = TextWrapping.Wrap;
            desc.Margin = new Thickness(0, 3, 0, 0);
            txt.Children.Add(desc);
            row.Children.Add(txt);
            return row;
        }

        // ---------------------------------------------------------------- options of each function

        void Chips(Panel to, string label, AiPrompts.Opt[] opts, string key, string def)
        {
            to.Children.Add(Theme.Label(label, 12, Theme.TextMuted));
            var cur = Sel.TryGetValue(key, out var v) ? v : def;
            var w = new WrapPanel { Margin = new Thickness(0, 4, 0, 8) };
            foreach (var o in opts)
            {
                var b = Theme.Button(L.T(o.Label), o.Key == cur ? Theme.Kind.Segment : Theme.Kind.Ghost, null);
                b.MinHeight = 26; b.FontSize = 12; b.Padding = new Thickness(9, 0, 9, 0); b.Margin = new Thickness(0, 0, 5, 5);
                var k = o.Key;
                b.Click += (_, __) => { Sel[key] = k; RenderProps(); };
                w.Children.Add(b);
            }
            to.Children.Add(w);
        }

        void MultiChips(Panel to, string label, AiPrompts.Opt[] opts, string prefix)
        {
            to.Children.Add(Theme.Label(label, 12, Theme.TextMuted));
            var w = new WrapPanel { Margin = new Thickness(0, 4, 0, 8) };
            foreach (var o in opts)
            {
                var id = prefix + ":" + o.Key;
                var b = Theme.Button(L.T(o.Label), Multi.Contains(id) ? Theme.Kind.Segment : Theme.Kind.Ghost, null);
                b.MinHeight = 26; b.FontSize = 12; b.Padding = new Thickness(9, 0, 9, 0); b.Margin = new Thickness(0, 0, 5, 5);
                b.Click += (_, __) => { if (!Multi.Remove(id)) Multi.Add(id); RenderProps(); };
                w.Children.Add(b);
            }
            to.Children.Add(w);
        }

        void Flag(Panel to, string label, string key, string? tip = null)
        {
            var t = new Toggle(label, Sel.ContainsKey(key), tip);
            t.Toggled += v => { if (v) Sel[key] = "1"; else Sel.Remove(key); };
            t.Margin = new Thickness(0, 0, 0, 6);
            to.Children.Add(t);
        }

        void AiOptions(StackPanel op)
        {
            switch (_aiFn)
            {
                case "render":
                {
                    Chips(op, L.T("Tipo di scena"), AiPrompts.RenderTypes, "render_type", "archviz_exterior");
                    Chips(op, L.T("Luce"), AiPrompts.TimeOfDay, "time", "as_is");
                    Chips(op, L.T("Stile"), AiPrompts.Styles, "style", "standard");
                    var a = Advanced(op, "ai:render");
                    MultiChips(a.Body, L.T("Materiali presenti (da far riconoscere)"), AiPrompts.Materials, "mat");
                    Chips(a.Body, L.T("Obiettivo"), AiPrompts.Lenses, "lens", "standard");
                    Chips(a.Body, L.T("Foschia"), AiPrompts.Haze, "haze", "none");
                    Chips(a.Body, L.T("Nebbia"), AiPrompts.Fog, "fog", "none");
                    Chips(a.Body, L.T("Illuminazione globale"), AiPrompts.Gi, "gi", "balanced");
                    Chips(a.Body, L.T("Ombre"), AiPrompts.Shadows, "shadows", "medium");
                    Chips(a.Body, L.T("Riflessi"), AiPrompts.Reflections, "reflections", "balanced");
                    Flag(a.Body, L.T("Raggi di luce volumetrici"), "volumetric");
                    Flag(a.Body, L.T("Caustiche visibili"), "caustics");
                    a.Done(Multi.Count > 0 || Sel.Keys.Any(k => k is "lens" or "haze" or "fog" or "gi" or "shadows" or "reflections" or "volumetric" or "caustics"));
                    break;
                }
                case "variants":
                    op.Children.Add(HintSmall(L.T("La stessa vista in un altro momento: scegli la luce, la stagione o il tempo.")));
                    Chips(op, L.T("Luce"), AiPrompts.TimeOfDay, "time", "golden_hour");
                    Chips(op, L.T("Stagione"), AiPrompts.Seasons, "season", "none");
                    Chips(op, L.T("Tempo"), AiPrompts.Weather, "weather", "none");
                    Chips(op, L.T("Tipo di scena"), AiPrompts.RenderTypes, "render_type", "archviz_exterior");
                    break;
                case "enhance":
                {
                    Chips(op, L.T("Intensità"), AiPrompts.EnhanceStrength, "strength", "standard");
                    var a = Advanced(op, "ai:enhance");
                    Chips(a.Body, L.T("Soggetto"), AiPrompts.EnhanceSubjects, "subject", "auto");
                    MultiChips(a.Body, L.T("Dove recuperare il dettaglio"), AiPrompts.EnhanceFocus, "focus");
                    a.Done(Multi.Count > 0 || Sel.ContainsKey("subject"));
                    break;
                }
                case "people":
                {
                    Chips(op, L.T("Quante persone"), AiPrompts.PeopleDensity, "density", "moderate");
                    Chips(op, L.T("Cosa fanno"), AiPrompts.PeopleActivities, "activity", "auto");
                    Chips(op, L.T("Volti"), AiPrompts.PeopleFaces, "faces", "discreet");
                    var a = Advanced(op, "ai:people");
                    Chips(a.Body, L.T("Che spazio è"), AiPrompts.PeopleScenes, "scene", "auto");
                    MultiChips(a.Body, L.T("Età"), AiPrompts.PeopleAges, "age");
                    Chips(a.Body, L.T("Gruppi"), AiPrompts.PeopleGrouping, "grouping", "auto");
                    Chips(a.Body, L.T("Abbigliamento"), AiPrompts.PeopleClothing, "clothing", "auto");
                    Chips(a.Body, L.T("Luogo"), AiPrompts.PeopleRegions, "region", "auto");
                    Flag(a.Body, L.T("Inclusività (sedia a rotelle, passeggino)"), "accessibility");
                    a.Done(Multi.Count > 0 || Sel.Keys.Any(k => k is "scene" or "grouping" or "clothing" or "region" or "accessibility"));
                    break;
                }
                case "staging":
                {
                    Chips(op, L.T("Stanza"), AiPrompts.StagingRooms, "room", "living");
                    Chips(op, L.T("Stile"), AiPrompts.StagingStyles, "style", "modern");
                    Chips(op, L.T("Quanto arredare"), AiPrompts.StagingLevels, "level", "moderate");
                    var a = Advanced(op, "ai:staging");
                    Chips(a.Body, L.T("Colori"), AiPrompts.Palettes, "palette", "none");
                    Flag(a.Body, L.T("Togli prima l'arredo che c'è"), "remove_existing");
                    a.Done(Sel.ContainsKey("palette") || Sel.ContainsKey("remove_existing"));
                    break;
                }
                case "camera":
                {
                    var cur = Sel.TryGetValue("angle", out var v) ? v : "three_quarter";
                    foreach (var (tier, title) in new[] { (1, L.T("Ritaglio: il punto di vista non cambia")), (2, L.T("La fotocamera si sposta: quasi tutto resta visibile")), (3, L.T("Viste nuove: l'AI deve inventare ciò che non ha mai visto")) })
                    {
                        op.Children.Add(Theme.Label(title, 12, tier == 3 ? Theme.Warm : Theme.TextMuted));
                        var w = new WrapPanel { Margin = new Thickness(0, 4, 0, 8) };
                        foreach (var o in AiPrompts.CameraAngles.Where(x => x.Tier == tier))
                        {
                            var b = Theme.Button(L.T(o.Label), o.Key == cur ? Theme.Kind.Segment : Theme.Kind.Ghost, null);
                            b.MinHeight = 26; b.FontSize = 12; b.Padding = new Thickness(9, 0, 9, 0); b.Margin = new Thickness(0, 0, 5, 5);
                            var k = o.Key;
                            b.Click += (_, __) => { Sel["angle"] = k; RenderProps(); };
                            w.Children.Add(b);
                        }
                        op.Children.Add(w);
                    }
                    break;
                }
                case "replace":
                {
                    Chips(op, L.T("Cosa fare nell'area"), AiPrompts.ReplaceActions, "action", "remove");
                    var action = Sel.TryGetValue("action", out var ac) ? ac : "remove";
                    if (action != "remove")
                    {
                        op.Children.Add(Theme.Label(action == "image" ? L.T("Indicazioni in più (facoltative)") : L.T("Con che cosa"), 12, Theme.TextMuted));
                        var d = Theme.Input(Sel.TryGetValue("description", out var dv) ? dv : "");
                        d.Margin = new Thickness(0, 4, 0, 8);
                        d.TextChanged += (_, __) => Sel["description"] = d.Text;
                        op.Children.Add(d);
                    }
                    if (action == "image")
                    {
                        var pick = SmallButton(Icons.Image, _aiRefPath != null ? Path.GetFileName(_aiRefPath) : L.T("Foto dell'oggetto…"), () =>
                        {
                            var dlg = new Microsoft.Win32.OpenFileDialog { Filter = L.T("Immagini|*.jpg;*.jpeg;*.png;*.webp;*.tif;*.tiff;*.bmp|Tutti i file|*.*"), InitialDirectory = StartFolder("image") };
                            if (dlg.ShowDialog(this) == true) { Keep("image", dlg.FileName); _aiRefPath = dlg.FileName; RenderProps(); }
                            return Task.CompletedTask;
                        });
                        pick.HorizontalAlignment = HorizontalAlignment.Left;
                        pick.Margin = new Thickness(0, 0, 0, 8);
                        op.Children.Add(pick);
                    }
                    var a = Advanced(op, "ai:replace");
                    Chips(a.Body, L.T("Come inserire la modifica"), AiPrompts.ReplaceBlends, "blend", "precise");
                    a.Body.Children.Add(HintSmall(L.T("«Solo l'area scelta»: fuori dal rettangolo l'immagine resta identica, ma su piastrelle o mattoni il bordo può notarsi. «Rielabora tutta l'immagine»: tutto coerente, ma anche il resto viene rifatto.")));
                    a.Body.Children.Add(Theme.Label(L.T("Cosa c'è ora nell'area (facoltativo)"), 12, Theme.TextMuted));
                    var cx = Theme.Input(Sel.TryGetValue("context", out var cv) ? cv : "");
                    cx.Margin = new Thickness(0, 4, 0, 8);
                    cx.TextChanged += (_, __) => Sel["context"] = cx.Text;
                    a.Body.Children.Add(cx);
                    a.Done(Sel.ContainsKey("blend") && Sel["blend"] != "precise");
                    op.Children.Add(HintSmall(L.T("Con «Esegui» si apre l'immagine: disegni un rettangolo attorno a ciò che vuoi togliere o cambiare.")));
                    break;
                }
            }
        }

        // ---------------------------------------------------------------- run

        async Task<BitmapSource?> AiSourceImage()
        {
            try
            {
                if (_aiSource == "image" && _aiImage != null) return _aiImage;
                if (_aiSource == "render" && _lastRenderPath != null)
                {
                    if (_lastRenderPath.EndsWith(".exr", StringComparison.OrdinalIgnoreCase))
                    {
                        Msg.Show(this, L.T("Il render finale è in OpenEXR (HDR), che OpenAI non legge: salvalo in PNG, JPEG o TIFF per elaborarlo."), "Simpler", MessageBoxButton.OK, MessageBoxImage.Information);
                        return null;
                    }
                    return AiImage.Decode(await File.ReadAllBytesAsync(_lastRenderPath));
                }
                if (_realistic && _api != null)
                {
                    var (frame, _) = await _api.Frame();
                    if (frame != null && frame.Length > 0) return AiImage.Decode(frame);
                }
                var b64 = await CaptureViewSnapshot(4096, 4096, 0.95);
                if (b64 != null) return AiImage.Decode(Convert.FromBase64String(b64));
            }
            catch (Exception ex)
            {
                Msg.Show(this, L.T("Non riesco a preparare l'immagine: ") + ex.Message, "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning);
                return null;
            }
            Msg.Show(this, L.T("La vista non ha risposto: riprova tra un attimo."), "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning);
            return null;
        }

        async Task RunAi()
        {
            var src = await AiSourceImage();
            if (src == null) return;
            var sel = new Dictionary<string, string>(Sel);
            var multi = new HashSet<string>(Multi);
            Rect? area = null;
            byte[]? reference = null;
            if (_aiFn == "replace")
            {
                var action = sel.TryGetValue("action", out var ac) ? ac : "remove";
                if (action == "image")
                {
                    if (_aiRefPath == null || !File.Exists(_aiRefPath))
                    {
                        Msg.Show(this, L.T("Scegli prima la foto dell'oggetto da mettere nell'area."), "Simpler", MessageBoxButton.OK, MessageBoxImage.Information);
                        return;
                    }
                    reference = AiImage.Png(AiImage.Decode(await File.ReadAllBytesAsync(_aiRefPath), 1536));
                }
                if (action == "describe" && (!sel.TryGetValue("description", out var dd) || dd.Trim() == ""))
                {
                    Msg.Show(this, L.T("Scrivi con che cosa sostituire ciò che c'è nell'area."), "Simpler", MessageBoxButton.OK, MessageBoxImage.Information);
                    return;
                }
                area = await AiImageWindow.PickArea(this, src);
                if (area == null) return;
            }
            var settings = Settings.Load();
            var model = AiModel();
            var quality = settings.AiQuality is "low" or "medium" or "high" ? settings.AiQuality : "medium";
            var prompt = AiPrompts.Build(_aiFn, sel, multi);
            var png = AiImage.Png(src);
            var size = AiClient.SizeFor(model, src.PixelWidth, src.PixelHeight);
            var mask = area is Rect r ? AiImage.Mask(src.PixelWidth, src.PixelHeight, r) : null;
            var fname = L.T(AiPrompts.Functions.First(f => f.Key == _aiFn).Name);
            var exp = AiSeconds.FirstOrDefault(kv => model.StartsWith(kv.Key, StringComparison.OrdinalIgnoreCase)).Value;
            if (exp == default) exp = AiSeconds["gpt-image-2"];
            int expected = quality == "low" ? exp.low : quality == "high" ? exp.high : exp.medium;

            _aiCts = new CancellationTokenSource();
            var ct = _aiCts.Token;
            var gen = _aiProjectGen;
            _aiStart = DateTime.Now;
            AppLog.Write($"AI {_aiFn} model={model} quality={quality} size={size} source={_aiSource} {src.PixelWidth}x{src.PixelHeight}");
            RenderProps();
            _aiTimer = new DispatcherTimer(TimeSpan.FromSeconds(1), DispatcherPriority.Background, (_, __) =>
            {
                var s = (int)(DateTime.Now - _aiStart).TotalSeconds;
                if (_aiStatus != null)
                    _aiStatus.Text = s <= expected ? L.F("{0}: OpenAI sta generando l'immagine… {1} s di circa {2}", fname, s, expected)
                                                   : L.F("{0}: ci sta mettendo più del solito ({1} s), l'immagine arriva…", fname, s);
                Status(L.F("AI · {0}: {1} s", fname, s));
            }, Dispatcher);
            _aiTimer.Start();
            try
            {
                var res = await AiClient.EditAsync(model, quality, prompt, png, mask, reference, size, _aiCts.Token);
                if (ct.IsCancellationRequested || gen != _aiProjectGen) throw new OperationCanceledException();
                var outBmp = AiImage.Decode(res.Image);
                if (area is Rect ar && (!sel.TryGetValue("blend", out var bl) || bl == "precise"))
                    outBmp = AiImage.Composite(src, outBmp, ar);
                _aiLastIn = res.InputTokens; _aiLastOut = res.OutputTokens;
                var s = Settings.Load(); s.AiTokensIn += res.InputTokens; s.AiTokensOut += res.OutputTokens; s.Save();
                // every result stays in the project (library, "Elaborazioni AI"), saved with it
                AddAiOutput(src, outBmp, _aiFn, model, quality, res.InputTokens, res.OutputTokens);
                Status(L.F("AI · {0}: fatto in {1} s ({2} token in, {3} out)", fname, (int)(DateTime.Now - _aiStart).TotalSeconds, res.InputTokens.ToString("N0"), res.OutputTokens.ToString("N0")));
                var w = new AiImageWindow(this, "Simpler AI · " + fname, src, outBmp, SetAiImage, _aiOutputs.FirstOrDefault()?.After);
                w.Show();
            }
            catch (OperationCanceledException) { Status(L.T("AI: annullato")); }
            catch (Exception ex)
            {
                AppLog.Write("AI failed: " + ex.Message);
                Msg.Show(this, L.T("L'elaborazione AI non è riuscita:") + "\n\n" + ex.Message, "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning);
            }
            finally
            {
                _aiTimer?.Stop(); _aiTimer = null;
                _aiCts?.Dispose(); _aiCts = null;
                if (_rightPanel == "ai") RenderProps();
            }
        }
    }
}
