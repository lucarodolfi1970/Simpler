using System;
using System.Collections.Generic;
using System.Globalization;
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
    /// (1.75.32) The Video AI panel (clapperboard button after «Render finale»): a short video between two views of the
    /// scene, made by a video model of Krea with the user's key. From the top: the key, the two keyframes «Inizio» and
    /// «Fine» (each a render of a view, with the whole state of the scene kept: a click on it goes back there), the
    /// model, the resolution, the seconds, the motion asked, the cost, «Crea video». The video is saved in the folder of
    /// the project and opens in its own window, in a loop.
    /// </summary>
    public sealed partial class MainWindow
    {
        Button _videoButton = null!;
        JsonObject _videoFrames = new JsonObject();
        CancellationTokenSource? _videoCts;
        DispatcherTimer? _videoTimer;
        DateTime _videoStart;
        string _videoPhase = "";
        double _videoProgress;
        TextBlock? _videoStatus;
        string? _lastVideoPath;
        bool _videoModelsAsked;

        static readonly string[] VideoSlots = { "start", "end" };

        async Task ToggleVideoPanel()
        {
            await ShowRightPanel(_rightPanel == "video" ? "" : "video");
            if (_rightPanel != "video") return;
            if (KreaKey.Exists && KreaKey.Ok == null)
            {
                await KreaKey.TestAsync();
                if (_rightPanel == "video") RenderProps();
            }
            if (!_videoModelsAsked)
            {
                _videoModelsAsked = true;
                await KreaClient.ListModelsAsync();
                if (_rightPanel == "video") RenderProps();
            }
        }

        async Task LoadVideoFrames()
        {
            await Run(async api => { _videoFrames = await api.Get("video/frames"); });
        }

        /// <summary>Where the videos and their keyframes go: next to the project (a folder with its name), or in
        /// Simpler's own folder while the project has not been saved yet.</summary>
        string VideoFolder()
        {
            if (_projectPath != null && Path.GetDirectoryName(_projectPath) is string dir)
                return Path.Combine(dir, Path.GetFileNameWithoutExtension(_projectPath) + " - Video AI");
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Simpler", "Video AI");
        }

        static (int w, int h) VideoSize(string res) => res == "1080p" ? (1920, 1080) : (1280, 720);

        VideoModel CurrentVideoModel()
        {
            var s = Settings.Load();
            var list = KreaClient.Models;
            return list.FirstOrDefault(m => m.Id == s.VideoModel)
                   ?? list.Where(m => m.PricePerSecond.Values.Any(p => p > 0)).OrderBy(m => m.PricePerSecond.Values.Where(p => p > 0).Min()).FirstOrDefault()
                   ?? list[0];
        }

        string CurrentVideoRes(VideoModel m)
        {
            var r = Settings.Load().VideoRes;
            return m.Resolutions.Contains(r) ? r : m.Resolutions[0];
        }

        static string Dollars(double v) => v.ToString("0.00", CultureInfo.CurrentCulture) + " $";

        bool FrameReady(string slot) => _videoFrames[slot] is JsonObject f && File.Exists((string?)f["image"] ?? "");

        // ------------------------------------------------------------------------------------------------ the panel

        void RenderVideoPanel()
        {
            var settings = Settings.Load();

            var head = new DockPanel();
            var close = Theme.Button(L.T("Chiudi"), Theme.Kind.Ghost, L.T("Torna alle proprietà dell'oggetto"));
            close.Click += async (_, __) => await ShowRightPanel("");
            DockPanel.SetDock(close, Dock.Right);
            head.Children.Add(close);
            head.Children.Add(Theme.Caption(L.T("Video AI")));
            _props.Children.Add(Theme.Card(head, 16));

            // ---- 1. the Krea key
            var key = new StackPanel();
            key.Children.Add(SectionTitle(L.T("Chiave Krea")));
            if (!KreaKey.Exists)
            {
                var how = Theme.Label(L.T("Il video lo crea Krea con la tua chiave API personale, a consumo sul tuo account Krea. Creala su krea.ai › API tokens e incollala qui."), 12, Theme.TextMuted);
                how.TextWrapping = TextWrapping.Wrap;
                key.Children.Add(how);
                var box = Theme.Input("", true);
                box.Margin = new Thickness(0, 8, 0, 6);
                key.Children.Add(box);
                key.Children.Add(HintSmall(L.T("Una volta salvata non si può più vedere: viene conservata cifrata e solo per il tuo utente di Windows. Per cambiarla la elimini e la inserisci di nuovo.")));
                var row = new WrapPanel();
                var save = Theme.Button(L.T("Salva e verifica"), Theme.Kind.Primary);
                save.Margin = new Thickness(0, 0, 8, 0);
                save.Click += async (_, __) =>
                {
                    var k = box.Text.Trim();
                    if (k.Length < 16) { Msg.Show(this, L.T("Questa non sembra una chiave API di Krea: incollala per intero."), "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning); return; }
                    KreaKey.Save(k);
                    box.Text = "";
                    RenderProps();
                    await KreaKey.TestAsync();
                    AppLog.Write("krea key saved, test " + (KreaKey.Ok == true ? "ok" : "failed"));
                    if (_rightPanel == "video") RenderProps();
                };
                row.Children.Add(save);
                row.Children.Add(SmallButton(Icons.Globe, L.T("Apri krea.ai"), () => { OpenUrl("https://www.krea.ai/app/api/tokens"); return Task.CompletedTask; }));
                key.Children.Add(row);
                _props.Children.Add(Theme.Card(key, 16));
                return;
            }
            var st = new DockPanel { Margin = new Thickness(0, 0, 0, 8) };
            bool ok = KreaKey.Ok == true;
            var mark = Theme.Icon(ok ? Geometry.Parse("M5 12.5l4.5 4.5L19 7.5") : Geometry.Parse("M12 7v6 M12 16.5v.5"), ok ? Theme.AxisY : KreaKey.Ok == false ? Theme.Danger : Theme.Warm, 18, 2.4);
            mark.Margin = new Thickness(0, 0, 8, 0); mark.VerticalAlignment = VerticalAlignment.Top;
            DockPanel.SetDock(mark, Dock.Left);
            st.Children.Add(mark);
            var stt = Theme.Label(KreaKey.Ok == null ? L.T("Verifica della chiave in corso…") : KreaKey.Message, 12.5,
                                  ok ? Theme.AxisY : KreaKey.Ok == false ? Theme.Danger : Theme.TextMuted);
            stt.TextWrapping = TextWrapping.Wrap;
            st.Children.Add(stt);
            key.Children.Add(st);
            var kb = new WrapPanel();
            kb.Children.Add(SmallButton(Icons.Refresh, L.T("Verifica di nuovo"), async () => { await KreaKey.TestAsync(); if (_rightPanel == "video") RenderProps(); }));
            kb.Children.Add(SmallButton(Icons.Trash, L.T("Elimina chiave"), () =>
            {
                if (Msg.Show(this, L.T("Eliminare la chiave Krea da Simpler? Il video AI si spegne finché non ne inserisci una."), "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return Task.CompletedTask;
                KreaKey.Delete();
                RenderProps();
                return Task.CompletedTask;
            }));
            key.Children.Add(kb);
            _props.Children.Add(Theme.Card(key, 16));
            if (!ok) return;

            // ---- videos asked and not downloaded yet (Simpler closed, or «Smetti di aspettare»): (1.75.43) Simpler keeps
            // asking Krea by itself and puts them in Elaborazioni AI as soon as they are ready, with a green notice
            var pending = PendingJobs().Where(e => e.Split('|')[0] != _videoFgJob).ToList();
            if (pending.Count > 0)
            {
                var pend = new StackPanel();
                pend.Children.Add(SectionTitle(L.T("Video in preparazione")));
                pend.Children.Add(HintSmall(pending.Count == 1
                    ? L.T("Un video è in preparazione su Krea: Simpler controlla da solo e, appena è pronto, lo mette in Elaborazioni AI › Video AI con un avviso verde.")
                    : L.F("{0} video sono in preparazione su Krea: Simpler controlla da solo e, appena sono pronti, li mette in Elaborazioni AI › Video AI con un avviso verde.", pending.Count)));
                var pr = new WrapPanel();
                if (_videoCts == null)
                    pr.Children.Add(SmallButton(Icons.Refresh, L.T("Aspettalo qui"), async () =>
                    {
                        var parts = pending[0].Split('|', 2);
                        await RunVideoJob(parts[0], parts.Length > 1 ? parts[1] : "");
                    }));
                pr.Children.Add(SmallButton(Icons.Trash, L.T("Lascia perdere"), () =>
                {
                    if (Msg.Show(this, L.T("Smettere di controllare questi video? Krea li finisce comunque (e li addebita), ma Simpler non li scaricherà."), "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return Task.CompletedTask;
                    foreach (var e in pending) RemovePending(e.Split('|')[0]);
                    RenderProps();
                    return Task.CompletedTask;
                }));
                pend.Children.Add(pr);
                _props.Children.Add(Theme.Card(pend, 16));
            }

            // ---- 2. the keyframes
            var fr = new StackPanel();
            fr.Children.Add(SectionTitle(L.T("Fotogrammi")));
            // (1.78.4, Luca: «generare video partendo da un solo frame e dal prompt») two keyframes, or the first one and
            // the text only: the model starts from the picture and follows the words (people walking away, children
            // playing), not forced to come back to a last frame
            bool one = settings.VideoOneFrame;
            var modeSeg = Theme.Segmented(out var modeBtns,
                (L.T("Inizio e fine"), L.T("Due fotogrammi: il video va dal primo all'ultimo (movimenti di camera, luce che cambia)")),
                (L.T("Solo inizio"), L.T("Un fotogramma e la descrizione: il video parte dall'immagine e segue il testo (persone che camminano, si allontanano, giocano)")));
            modeSeg.HorizontalAlignment = HorizontalAlignment.Left;
            modeSeg.Margin = new Thickness(0, 0, 0, 10);
            Theme.SetSegment(modeBtns, one ? 1 : 0);
            modeBtns[0].Click += (_, __) => { var s = Settings.Load(); s.VideoOneFrame = false; s.Save(); RenderProps(); };
            modeBtns[1].Click += (_, __) => { var s = Settings.Load(); s.VideoOneFrame = true; s.Save(); RenderProps(); };
            fr.Children.Add(modeSeg);
            fr.Children.Add(FrameSlot("start", L.T("Inizio")));
            if (!one) fr.Children.Add(FrameSlot("end", L.T("Fine")));
            if (!one && _videoFrames["gap"] is JsonObject gap)
            {
                double m = (double?)gap["metres"] ?? 0, deg = (double?)gap["degrees"] ?? 0;
                if (m > 3 || deg > 35)
                {
                    var w = Theme.Label(L.F("Le due inquadrature sono lontane ({0} m, {1}°): il video potrebbe inventare parti della scena. Per un movimento credibile meglio pochi metri e meno di 30-40°.",
                                            m.ToString("0.#", CultureInfo.CurrentCulture), deg.ToString("0", CultureInfo.CurrentCulture)), 12, Theme.Warm);
                    w.TextWrapping = TextWrapping.Wrap;
                    w.Margin = new Thickness(0, 2, 0, 4);
                    fr.Children.Add(w);
                }
            }
            _props.Children.Add(Theme.Card(fr, 16));

            // ---- 3. model, resolution, seconds, motion
            var en = new StackPanel();
            en.Children.Add(SectionTitle(L.T("Video")));
            var model = CurrentVideoModel();
            var mw = new WrapPanel { Margin = new Thickness(0, 0, 0, 4) };
            // (1.75.33) as buttons the models Simpler knows (and the one chosen); the others found on Krea - many,
            // without a price - in «Altri modelli…»
            var others = KreaClient.Models.Where(m => !KreaClient.Known.Contains(m)).ToList();
            foreach (var m in KreaClient.Models.Where(m => KreaClient.Known.Contains(m) || m.Id == model.Id))
            {
                var b = Theme.Button(m.Name, m.Id == model.Id ? Theme.Kind.Segment : Theme.Kind.Ghost, m.Hint);
                b.MinHeight = 28; b.FontSize = 12; b.Padding = new Thickness(10, 0, 10, 0); b.Margin = new Thickness(0, 0, 6, 6);
                var id = m.Id;
                b.Click += (_, __) => { var s = Settings.Load(); s.VideoModel = id; s.Save(); RenderProps(); };
                mw.Children.Add(b);
            }
            if (others.Count > 0)
            {
                var more = Theme.Button(L.F("Altri modelli ({0})…", others.Count), Theme.Kind.Ghost, L.T("Altri modelli di Krea che accettano il primo e l'ultimo fotogramma: Simpler non ne conosce il prezzo"));
                more.MinHeight = 28; more.FontSize = 12; more.Padding = new Thickness(10, 0, 10, 0); more.Margin = new Thickness(0, 0, 6, 6);
                more.Foreground = Theme.B(AdvancedColor);
                more.Click += (_, __) =>
                {
                    var menu = new ContextMenu { PlacementTarget = more, Placement = System.Windows.Controls.Primitives.PlacementMode.Bottom };
                    foreach (var m in others.OrderBy(o => o.Name, StringComparer.OrdinalIgnoreCase))
                    {
                        var mi = new MenuItem { Header = m.Name, IsCheckable = true, IsChecked = m.Id == model.Id };
                        var id = m.Id;
                        mi.Click += (_, __) => { var s = Settings.Load(); s.VideoModel = id; s.Save(); RenderProps(); };
                        menu.Items.Add(mi);
                    }
                    menu.IsOpen = true;
                };
                mw.Children.Add(more);
            }
            en.Children.Add(mw);
            en.Children.Add(HintSmall(model.Hint + (KreaClient.ModelsSource != "" ? " · " + KreaClient.ModelsSource : "")));
            var res = CurrentVideoRes(model);
            var resItems = model.Resolutions.Select(r => ((object)r, (string?)(r == "720p" ? L.T("La più economica") : L.T("Più definita, costa di più")))).ToArray();
            var rs = Theme.Segmented(out var rb, resItems);
            Theme.SetSegment(rb, Math.Max(0, Array.IndexOf(model.Resolutions, res)));
            for (int i = 0; i < rb.Count; i++)
            {
                var v = model.Resolutions[i];
                rb[i].Click += async (_, __) =>
                {
                    var s = Settings.Load(); s.VideoRes = v; s.Save();
                    RenderProps();
                    if ((FrameReady("start") || FrameReady("end")) && FramesSize() != VideoSize(v))
                        Status(L.T("Risoluzione cambiata: rifai i due fotogrammi con «Usa la vista attuale» perché abbiano la stessa misura del video"), true);
                    await Task.CompletedTask;
                };
            }
            en.Children.Add(Row(L.T("Risoluzione"), rs));
            int secs = Math.Clamp(settings.VideoSeconds, 5, 10);
            var sl = new ValueSlider(L.T("Durata"), secs, 5, 10, false, "0", "s", null, L.T("Da 5 a 10 secondi: si paga ogni secondo"));
            sl.Committed += v => { var s = Settings.Load(); s.VideoSeconds = (int)Math.Round(v); s.Save(); RenderProps(); };
            en.Children.Add(sl);
            // (1.75.37) the sound Krea adds by itself: kept only if asked, otherwise taken out after the download
            var audio = new CheckBox { Content = L.T("Genera audio automatico"), IsChecked = settings.VideoAudio, Foreground = Theme.B(Theme.TextSoft), Margin = new Thickness(0, 0, 0, 10),
                                       ToolTip = L.T("Krea aggiunge al video un audio creato in automatico. Spento: Simpler lo toglie dopo averlo scaricato (il video non cambia)") };
            audio.Checked += (_, __) => { var s = Settings.Load(); s.VideoAudio = true; s.Save(); };
            audio.Unchecked += (_, __) => { var s = Settings.Load(); s.VideoAudio = false; s.Save(); };
            en.Children.Add(audio);
            if (secs > 8)
                en.Children.Add(WarnSmall(one ? L.T("Più è lungo, più costa e più facilmente il modello inventa movimenti strani.")
                                              : L.T("Più è lungo, più costa e più facilmente il modello inventa movimenti strani tra i due fotogrammi.")));
            en.Children.Add(Theme.Label(one ? L.T("Cosa succede nella scena") : L.T("Movimento (facoltativo)"), 12, Theme.TextMuted));
            var prompt = Theme.Input(VideoPromptText, clear: false);      // (its own ×: «Annulla» brings the text back)
            prompt.AcceptsReturn = true; prompt.TextWrapping = TextWrapping.Wrap; prompt.MinHeight = 54; prompt.MaxLength = 2000;
            prompt.VerticalContentAlignment = VerticalAlignment.Top;
            prompt.Margin = new Thickness(0, 6, 0, 0);
            // (1.75.44) a long text: at most about 12 lines high, then a vertical scrollbar; room on the right for the ×
            prompt.MaxHeight = 200;
            prompt.VerticalScrollBarVisibility = ScrollBarVisibility.Auto;
            prompt.Padding = new Thickness(6, 4, 24, 4);
            prompt.ToolTip = one ? L.T("Cosa fa ciascuno e come si muove la camera, in poche frasi (meglio in inglese). Il video parte dal fotogramma e segue questo testo.")
                                 : L.T("Come si muove la camera o cosa cambia, in poche parole (meglio in inglese). Vuoto: un movimento di camera lento e pulito tra i due fotogrammi.");
            prompt.LostFocus += async (_, __) => { if (prompt.Text != VideoPromptText) await SetVideoPrompt(prompt.Text); };
            // (1.75.44) a small × in the corner empties the text («Annulla» brings it back)
            var promptBox = new Grid();
            promptBox.Children.Add(prompt);
            var clear = new Button
            {
                Content = Theme.Icon(Icons.Close, Theme.TextMuted, 11, 1.8), Width = 20, Height = 20, Padding = new Thickness(0),
                HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Top, Margin = new Thickness(0, 9, 16, 0),
                Background = Brushes.Transparent, BorderThickness = new Thickness(0), Cursor = Cursors.Hand, FocusVisualStyle = null,
                ToolTip = L.T("Cancella il testo"),
                Visibility = string.IsNullOrEmpty(prompt.Text) ? Visibility.Collapsed : Visibility.Visible,
            };
            clear.Template = new ControlTemplate(typeof(Button)) { VisualTree = new FrameworkElementFactory(typeof(ContentPresenter)) };
            clear.Click += async (_, __) =>
            {
                if (prompt.Text.Trim() == "") return;
                _promptBefore = prompt.Text;
                prompt.Text = "";
                await SetVideoPrompt("");
                RenderProps();
            };
            prompt.TextChanged += (_, __) => clear.Visibility = string.IsNullOrEmpty(prompt.Text) ? Visibility.Collapsed : Visibility.Visible;
            promptBox.Children.Add(clear);
            en.Children.Add(promptBox);
            // (1.75.40) «Migliora con l'AI»: the text rewritten for the video model by the cheapest OpenAI text model
            var improveRow = new WrapPanel { Margin = new Thickness(0, 6, 0, 0) };
            var improve = SmallButton(Icons.Sparkles, _improving ? L.T("Sto scrivendo…") : L.T("Crea/migliora con l'AI"), async () => await ImproveVideoPrompt(prompt.Text));
            bool aiOk = AiKey.Exists && AiKey.Ok == true;
            improve.IsEnabled = aiOk && !_improving;
            improve.ToolTip = aiOk && one ? L.T("Guardando il fotogramma scrive il testo di cosa succede (vuoto: lo crea da zero; scritto: lo migliora) nel modo che il modello video segue meglio. Modello di testo più economico della tua chiave OpenAI, costo di una frazione di centesimo")
                            : aiOk ? L.T("Guardando i due fotogrammi scrive il testo del movimento (vuoto: lo crea da zero; scritto: lo migliora) nel modo che il modello video segue meglio. Modello di testo più economico della tua chiave OpenAI, costo di una frazione di centesimo")
                                   : L.T("Serve la chiave OpenAI funzionante (pulsante AI con le stelline)");
            improveRow.Children.Add(improve);
            if (_promptBefore != null)
            {
                var undo = SmallButton(Icons.Undo, L.T("Annulla"), async () =>
                {
                    var before = _promptBefore ?? "";
                    _promptBefore = null;
                    await SetVideoPrompt(before);
                    RenderProps();
                });
                undo.ToolTip = L.T("Torna al testo di prima");
                improveRow.Children.Add(undo);
            }
            en.Children.Add(improveRow);
            en.Children.Add(HintSmall(one ? L.T("Per esempio: «il vecchio e il bambino camminano verso la camera, le ragazze giocano tra le onde, l'uomo sulla destra si allontana, camera ferma».")
                                          : L.T("Vuoto: un movimento di camera lento e pulito tra i due fotogrammi.")));
            _props.Children.Add(Theme.Card(en, 16));

            // ---- 4. cost and «Crea video»
            var go = new StackPanel();
            double pps = model.PricePerSecond.TryGetValue(res, out var p) ? p : 0;
            go.Children.Add(Theme.Label(pps > 0 ? L.F("Costo stimato: {0} ({1} s × {2}/s)", Dollars(pps * secs), secs, Dollars(pps).Replace(" $", "") + " $")
                                                : L.T("Costo: non noto a Simpler per questo modello, controllalo su krea.ai"), 13, Theme.Text, FontWeights.SemiBold));
            go.Children.Add(HintSmall(L.T("Addebitato sul tuo account Krea; il prezzo esatto lo decide Krea.")));
            bool both = FrameReady("start") && (one || FrameReady("end"));
            if (_videoCts == null)
            {
                var create = Theme.Button(Theme.IconText(Icons.Clapper, L.T("Crea video"), Theme.AccentText), Theme.Kind.Primary,
                                          one ? (both ? L.T("Manda il fotogramma e la descrizione a Krea e crea il video") : L.T("Serve il fotogramma Inizio"))
                                              : both ? L.T("Manda i due fotogrammi a Krea e crea il video") : L.T("Servono i due fotogrammi, Inizio e Fine"));
                create.IsEnabled = both;
                create.HorizontalAlignment = HorizontalAlignment.Left;
                create.Click += async (_, __) => await CreateVideo();
                go.Children.Add(create);
            }
            else
            {
                _videoStatus = Theme.Label(VideoStatusText(), 12.5, Theme.Accent);
                _videoStatus.TextWrapping = TextWrapping.Wrap;
                _videoStatus.Margin = new Thickness(0, 0, 0, 8);
                go.Children.Add(_videoStatus);
                var stop = SmallButton(Icons.Close, L.T("Continua a lavorare"), () => { _videoCts?.Cancel(); return Task.CompletedTask; });
                stop.HorizontalAlignment = HorizontalAlignment.Left;
                stop.ToolTip = L.T("Puoi continuare a lavorare: Simpler controlla da solo e, quando il video è pronto, compare un avviso verde e lo trovi in Elaborazioni AI › Video AI");
                go.Children.Add(stop);
            }
            if (_lastVideoPath != null && File.Exists(_lastVideoPath))
            {
                var last = SmallButton(Icons.Play, L.T("Apri l'ultimo video"), () => { ShowVideo(_lastVideoPath); return Task.CompletedTask; });
                last.HorizontalAlignment = HorizontalAlignment.Left;
                last.Margin = new Thickness(0, 10, 0, 0);
                go.Children.Add(last);
            }
            _props.Children.Add(Theme.Card(go, 16));
        }

        static UIElement WarnSmall(string text)
        {
            var t = Theme.Label(text, 12, Theme.Warm);
            t.TextWrapping = TextWrapping.Wrap;
            t.Margin = new Thickness(0, 0, 0, 10);
            return t;
        }

        (int, int) FramesSize()
        {
            foreach (var s in VideoSlots)
                if (_videoFrames[s] is JsonObject f && (int?)f["width"] is int w && w > 0) return (w, (int?)f["height"] ?? 0);
            return (0, 0);
        }

        /// <summary>One keyframe: its picture (a click goes back to that view) and the buttons to make it.</summary>
        UIElement FrameSlot(string slot, string title)
        {
            var box = new StackPanel { Margin = new Thickness(0, 0, 0, 12) };
            box.Children.Add(Theme.Label(title, 12.5, Theme.TextSoft, FontWeights.SemiBold));
            // (1.75.42) the saved scene it came from, told by its id: renamed = the new name, deleted or updated = said.
            // The keyframe is a copy in any case: the video uses it as it was made
            if (_videoFrames[slot] is JsonObject src && (string?)src["viewId"] is string vid && vid != "")
            {
                var vn = (string?)src["viewName"] ?? "";
                bool gone = (bool?)src["viewGone"] ?? false, changed = (bool?)src["viewChanged"] ?? false;
                var txt = gone ? L.F("Dalla scena «{0}», ora eliminata: il fotogramma resta com'era", vn)
                        : changed ? L.F("Dalla scena «{0}», aggiornata dopo: il fotogramma è la versione di prima, rifallo se vuoi quella nuova", vn)
                        : L.F("Dalla scena «{0}»", vn);
                var lt = Theme.Label(txt, 11.5, gone || changed ? Theme.Warm : Theme.TextFaint);
                lt.TextWrapping = TextWrapping.Wrap;
                lt.Margin = new Thickness(0, 2, 0, 0);
                box.Children.Add(lt);
            }
            var thumb = new Border
            {
                Height = 150, Margin = new Thickness(0, 6, 0, 6), CornerRadius = new CornerRadius(6), ClipToBounds = true,
                Background = Theme.B(Theme.Inset), BorderBrush = Theme.B(Theme.Line), BorderThickness = new Thickness(1),
            };
            var f = _videoFrames[slot] as JsonObject;
            var img = (string?)f?["image"] ?? "";
            if (File.Exists(img))
            {
                try
                {
                    var bmp = new BitmapImage();
                    bmp.BeginInit();
                    bmp.CacheOption = BitmapCacheOption.OnLoad;
                    bmp.DecodePixelWidth = 600;
                    bmp.StreamSource = new MemoryStream(File.ReadAllBytes(img));
                    bmp.EndInit();
                    bmp.Freeze();
                    // (1.75.36) the whole picture with its proportions: black bands where the box is wider or taller
                    thumb.Background = Brushes.Black;
                    thumb.Child = new Image { Source = bmp, Stretch = Stretch.Uniform };
                }
                catch { }
                thumb.Cursor = Cursors.Hand;
                thumb.ToolTip = L.F("Torna a questa vista: inquadratura, luci e ambiente del fotogramma «{0}» ({1})", title, (string?)f?["updated"] ?? "");
                thumb.MouseLeftButtonUp += async (_, __) => await ApplyVideoFrame(slot, title);
            }
            else
            {
                var t = Theme.Label(L.T("Nessun fotogramma"), 12, Theme.TextFaint);
                t.HorizontalAlignment = HorizontalAlignment.Center; t.VerticalAlignment = VerticalAlignment.Center;
                thumb.Child = t;
            }
            box.Children.Add(thumb);
            var row = new WrapPanel();
            var running = _videoCts != null;
            // (1.75.38) the render of the keyframe, to check it before the video (on when there is one)
            var see = SmallButton(Icons.Eye, L.T("Vedi il render"), () =>
            {
                try { new AiImageWindow(this, title + " · " + Path.GetFileName(img), AiImage.Decode(File.ReadAllBytes(img)), null, SetAiImage, img).Show(); }
                catch (Exception ex) { Msg.Show(this, L.T("Non riesco a leggere l'immagine: ") + ex.Message, "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning); }
                return Task.CompletedTask;
            });
            see.IsEnabled = File.Exists(img);
            see.ToolTip = File.Exists(img) ? L.T("Apre il render del fotogramma a piena grandezza: controllalo prima di creare il video") : L.T("Il render di questo fotogramma non è ancora stato fatto");
            row.Children.Add(see);
            var cur = SmallButton(Icons.Camera, L.T("Usa la vista attuale"), async () => { if (ConfirmFrameRender(slot)) await CaptureVideoFrame(slot, false); });
            cur.ToolTip = L.T("Fa il render della vista com'è adesso e la tiene come fotogramma, con luci e ambiente");
            cur.IsEnabled = !running;
            row.Children.Add(cur);
            var fromView = SmallButton(Icons.Dots, L.T("Da una vista salvata…"), async () => await FrameFromSavedView(slot));
            fromView.IsEnabled = !running;
            row.Children.Add(fromView);
            if (slot == "end" && _videoFrames["start"] is JsonObject)
            {
                var same = SmallButton(Icons.Copy, L.T("Stessa inquadratura dell'inizio"), async () => { if (ConfirmFrameRender("end")) await CaptureVideoFrame("end", true); });
                same.ToolTip = L.T("La camera torna dov'era all'inizio, luci e ambiente restano come sono adesso: per un timelapse della luce");
                same.IsEnabled = !running;
                row.Children.Add(same);
            }
            box.Children.Add(row);
            return box;
        }

        async Task FrameFromSavedView(string slot)
        {
            JsonObject? r = null;
            await Run(async api => { r = await api.Get("views"); });
            var list = (r?["views"] as JsonArray)?.OfType<JsonObject>().ToList() ?? new();
            if (list.Count == 0) { Status(L.T("Nessuna vista salvata: salvane una nella scheda Scene della libreria"), true); return; }
            var menu = new ContextMenu { PlacementTarget = this, Placement = System.Windows.Controls.Primitives.PlacementMode.MousePoint };
            foreach (var v in list)
            {
                var id = (string?)v["id"] ?? ""; var name = (string?)v["name"] ?? "";
                var mi = new MenuItem { Header = name };
                mi.Click += async (_, __) => { await ApplyView(id, name); await CaptureVideoFrame(slot, false, id); };
                menu.Items.Add(mi);
            }
            menu.IsOpen = true;
        }

        /// <summary>The current view becomes the keyframe: the state of the scene kept by the engine, then a render at
        /// the size of the video (both keyframes the same size and the same render settings of the scene).
        /// <paramref name="startCamera"/>: first the camera goes back to the one of «Inizio» (the light timelapse).</summary>
        /// <summary>(1.76.11, Luca) One click started the render of the keyframe at once: asked first (it takes a while,
        /// and replaces the keyframe there is).</summary>
        bool ConfirmFrameRender(string slot)
        {
            var (w, h) = VideoSize(CurrentVideoRes(CurrentVideoModel()));
            var title = slot == "start" ? L.T("Inizio") : L.T("Fine");
            var q = L.F("Fare ora il render del fotogramma «{0}» ({1}×{2}) dalla vista attuale?", title, w, h);
            if (FrameReady(slot))
                q += "\n\n" + L.T("Il fotogramma che c'è adesso viene sostituito.");
            return Msg.Show(this, q, "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) == MessageBoxResult.Yes;
        }

        async Task CaptureVideoFrame(string slot, bool startCamera, string? viewId = null)
        {
            if (_api == null || _finalRendering) return;
            var (w, h) = VideoSize(CurrentVideoRes(CurrentVideoModel()));
            if (startCamera)
            {
                JsonObject? a = null;
                await Run(async api => { a = await api.Post("video/frame/apply", new { slot = "start", cameraOnly = true }); });
                if (a?["view"] is JsonObject view) { SendToWeb(new { type = "setCamera", view = view.DeepClone() }); SendCameraOptions(view); }
            }
            var folder = Path.Combine(VideoFolder(), "frames");
            try { Directory.CreateDirectory(folder); }
            catch (Exception ex) { Status(L.T("Impossibile creare la cartella del video: ") + ex.Message, true); return; }
            var path = Path.Combine(folder, $"{slot}_{DateTime.Now:yyyyMMdd_HHmmss}.jpg");
            var title = slot == "start" ? L.T("Inizio") : L.T("Fine");
            await CamViewBeforeRender();
            ShowBusy(L.F("Fotogramma «{0}»: render {1}×{2} in corso…", title, w, h), cancellable: true);
            var busy = BeginBusy();
            _finalRendering = true;
            try
            {
                await Run(async api =>
                {
                    await api.Post("video/frame/save", new { slot, view = viewId ?? "" });
                    var r = await api.Post("render", new { path, width = w, height = h, quality = "attuale", textures = -1 });
                    var saved = (string?)r["path"] ?? path;
                    _videoFrames = await api.Post("video/frame/image", new { slot, image = saved, width = w, height = h });
                    AppLog.Write($"video: keyframe {slot} {w}x{h} -> {saved}");
                    Status(L.F("Fotogramma «{0}» pronto", title));
                });
            }
            finally
            {
                _finalRendering = false;
                busy.Dispose();
                HideBusy();
            }
            await LoadVideoFrames();
            if (_rightPanel == "video") RenderProps();
        }

        async Task ApplyVideoFrame(string slot, string title)
        {
            if (_api == null || _finalRendering) return;
            JsonObject? r = null;
            using (BeginBusy())
            {
                _reloadOrigin = "action";
                ShowTask(L.F("Fotogramma «{0}»…", title));
                await Run(async api => { r = await api.Post("video/frame/apply", new { slot }); });
                HideTask();
            }
            if (r == null) return;
            if (r["view"] is JsonObject view) { SendToWeb(new { type = "setCamera", view = view.DeepClone() }); SendCameraOptions(view); }
            await RefreshScene();
            await LoadRenderSettings();
            await LoadAmbience();
            PushAmbienceToViewer();
            if (_rightPanel != "") RenderProps();
            Status(L.F("Vista del fotogramma «{0}»", title));
        }

        // ------------------------------------------------------------------------------------------------ the video

        string VideoStatusText()
        {
            var t = DateTime.Now - _videoStart;
            var time = $"{(int)t.TotalMinutes}:{t.Seconds:00}";
            // (1.75.38) Krea says 100% and the video is not ready yet: it happens - a sentence instead of a stuck 100%
            if (_videoProgress >= 0.995 && _videoPhase != L.T("Scaricamento del video"))
                return L.T("Ci mette più del solito, aspetta…") + " · " + time;
            var pct = _videoProgress > 0 ? $" · {Math.Round(_videoProgress * 100)}%" : "";
            return $"{_videoPhase}{pct} · {time}";
        }

        void VideoPhase(string text, double progress = 0)
        {
            _videoPhase = text; _videoProgress = progress;
            if (_videoStatus != null) _videoStatus.Text = VideoStatusText();
        }

        async Task CreateVideo()
        {
            if (_videoCts != null) return;
            if (!FrameReady("start") || (!Settings.Load().VideoOneFrame && !FrameReady("end"))) return;
            var model = CurrentVideoModel();
            var res = CurrentVideoRes(model);
            var settings = Settings.Load();
            int secs = Math.Clamp(settings.VideoSeconds, 5, 10);
            double pps = model.PricePerSecond.TryGetValue(res, out var p) ? p : 0;
            var cost = pps > 0 ? L.F("Costo stimato: {0}", Dollars(pps * secs)) : L.T("Costo: non noto a Simpler per questo modello, controllalo su krea.ai");
            var q = L.F("Creare il video con {0} ({1}, {2} s)?\n\n{3}, addebitato sul tuo account Krea.", model.Name, res, secs, cost);
            if (settings.VideoOneFrame) q += "\n\n" + L.T("Solo il fotogramma Inizio: il video parte da lì e segue la descrizione.");
            if (FramesSize() != VideoSize(res))
                q += "\n\n" + L.T("I fotogrammi sono stati fatti con un'altra risoluzione: Krea li adatta, ma per la qualità migliore rifalli con «Usa la vista attuale».");
            if (Msg.Show(this, q, "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;

            var userPrompt = VideoPromptText;
            var prompt = userPrompt.Trim();
            bool oneFrame = settings.VideoOneFrame;
            if (prompt == "" && oneFrame)
                prompt = "Gentle, realistic motion of the scene starting from this frame: natural movement of people, water, leaves and light where present. Slow, steady camera. Keep the architecture, objects and materials consistent. No text.";
            else if (prompt == "")
            {
                bool still = _videoFrames["gap"] is JsonObject g && ((double?)g["metres"] ?? 1) < 0.05 && ((double?)g["degrees"] ?? 1) < 0.5;
                prompt = still
                    ? "Static camera, no camera movement. The light changes gradually and naturally from the first frame to the last frame, like a time-lapse. Keep the architecture, objects and materials exactly unchanged. No people, no text."
                    : "Smooth, slow cinematic camera move from the first frame to the last frame. Keep the architecture, objects, materials and lighting consistent and realistic. No people, no text.";
            }
            var start = (string)_videoFrames["start"]!["image"]!;
            var end = oneFrame ? null : (string)_videoFrames["end"]!["image"]!;
            // (1.75.35) the video goes in Elaborazioni AI › Video AI (session folder, then «nome AI» with the project)
            var info = $"{model.Name}|{res}|{secs}|{(settings.VideoAudio ? "audio" : "mute")}";
            // (1.75.39) the recipe of this video, kept with it in the library: a click on it puts everything back
            var recipeDir = await SaveVideoRecipe(model, res, secs, settings.VideoAudio, userPrompt, start, end);
            if (recipeDir != null) info += "|" + Path.GetFileName(recipeDir);

            _videoCts = new CancellationTokenSource();
            var ct = _videoCts.Token;
            _videoStart = DateTime.Now;
            StartVideoTimer();
            VideoPhase(oneFrame ? L.T("Invio del fotogramma a Krea") : L.T("Invio dei fotogrammi a Krea"));
            RenderProps();
            string? job = null;
            try
            {
                var su = await KreaClient.UploadAsync(start, ct);
                var eu = end == null ? null : await KreaClient.UploadAsync(end, ct);
                VideoPhase(L.T("Richiesta del video"));
                job = await KreaClient.SubmitAsync(model, res, secs, prompt, su, eu, ct);
                AddPending(job + "|" + info);
            }
            catch (OperationCanceledException) { EndVideo(); Status(L.T("Video annullato prima di partire: nessun costo")); return; }
            catch (Exception ex)
            {
                EndVideo();
                AppLog.Write("krea: " + ex.Message);
                Msg.Show(this, L.T("Krea non ha accettato la richiesta del video:") + "\n\n" + ex.Message, "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }
            await WaitVideo(job, info, ct);
        }

        /// <summary>A video asked before: wait for it here again and download it.</summary>
        async Task RunVideoJob(string job, string info)
        {
            if (_videoCts != null) return;
            _videoCts = new CancellationTokenSource();
            _videoStart = DateTime.Now;
            StartVideoTimer();
            VideoPhase(L.T("Krea sta creando il video"));
            RenderProps();
            await WaitVideo(job, info, _videoCts.Token);
        }

        // ---------------------------------------------------------------- (1.75.43) videos still on Krea

        string? _videoFgJob;          // the job waited for in the panel (the watch leaves it alone)
        bool _videoWatching;

        static List<string> PendingJobs()
        {
            var s = Settings.Load();
            var l = s.VideoPendingJobs ?? new List<string>();
            if (s.VideoPendingJob.Contains('|'))           // (one left by 1.75.32-42)
            {
                if (!l.Contains(s.VideoPendingJob)) l.Add(s.VideoPendingJob);
                s.VideoPendingJob = ""; s.VideoPendingJobs = l; s.Save();
            }
            return l;
        }

        static void AddPending(string entry)
        {
            var l = PendingJobs();
            var s = Settings.Load();
            if (!l.Contains(entry)) l.Add(entry);
            s.VideoPendingJobs = l; s.Save();
        }

        static void RemovePending(string job)
        {
            var l = PendingJobs();
            var s = Settings.Load();
            l.RemoveAll(e => e.Split('|')[0] == job);
            s.VideoPendingJobs = l; s.Save();
        }

        /// <summary>Asks Krea every 15 s about the videos asked and not downloaded (after «Smetti di aspettare», or at
        /// the start of Simpler): each one ready goes to Elaborazioni AI › Video AI with a green notice.</summary>
        async void StartVideoWatch()
        {
            if (_videoWatching || !KreaKey.Exists) return;
            _videoWatching = true;
            try
            {
                while (true)
                {
                    var list = PendingJobs();
                    if (list.Count == 0 || !KreaKey.Exists) break;
                    foreach (var e in list)
                    {
                        var parts = e.Split('|', 2);
                        var job = parts[0];
                        if (job == _videoFgJob) continue;
                        try
                        {
                            using var cts = new CancellationTokenSource(TimeSpan.FromMinutes(3));
                            var st = await KreaClient.PollAsync(job, cts.Token);
                            if (st.Status == "completed" && !string.IsNullOrEmpty(st.VideoUrl))
                                await FinishVideo(job, parts.Length > 1 ? parts[1] : "", st.VideoUrl!, cts.Token);
                            else if (st.Error != null)
                            {
                                RemovePending(job);
                                AppLog.Write($"krea: job {job} failed in the background: {st.Error}");
                                Status(L.T("Un video in preparazione su Krea non è riuscito: ") + st.Error, true);
                            }
                        }
                        catch (Exception ex) { AppLog.Write($"krea: watch {job}: {ex.Message}"); }     // (asked again later)
                    }
                    if (_rightPanel == "video" && _videoCts == null) RenderProps();
                    await Task.Delay(15000);
                }
            }
            finally { _videoWatching = false; }
        }

        /// <summary>The video ready on Krea: downloaded, without sound if so chosen, into Elaborazioni AI with its recipe,
        /// a green notice. Returns the file.</summary>
        async Task<string> FinishVideo(string job, string info, string url, CancellationToken ct)
        {
            var ip = info.Split('|');
            string vModel = ip.Length >= 3 ? ip[0] : "Krea", vRes = ip.Length >= 3 ? ip[1] : "";
            int vSecs = ip.Length >= 3 && int.TryParse(ip[2], out var vs) ? vs : 0;
            bool keepAudio = ip.Length >= 4 && ip[3] == "audio";      // (1.75.37) as chosen when the video was asked
            string? recipeDir = ip.Length >= 5 ? Path.Combine(VideoRecipesRoot, ip[4]) : null;
            var file = NewAiVideoPath(out var vid);
            await KreaClient.DownloadAsync(url, file, ct);
            // (1.75.34) without sound: Krea adds it and no longer lets it be turned off
            if (!keepAudio) try { var k = Mp4.StripAudio(file); if (k > 0) AppLog.Write($"krea: sound track taken out of {Path.GetFileName(file)}"); }
            catch (Exception ex) { AppLog.Write("krea: sound not taken out (" + ex.Message + ")"); }
            RemovePending(job);
            _lastVideoPath = file;
            AppLog.Write($"krea: job {job} done -> {file}");
            var startImg = (string?)(_videoFrames["start"] as JsonObject)?["image"];
            AddAiVideo(vid, file, startImg, vModel, vRes, vSecs, recipeDir);
            if (_webReady) SendToWeb(new { type = "toast", text = L.T("Video AI creato e salvato in Elaborazioni AI") });
            Status(L.T("Video pronto: lo trovi nella libreria, Elaborazioni AI › Video AI (si salva con il progetto)"));
            return file;
        }

        async Task WaitVideo(string job, string info, CancellationToken ct)
        {
            _videoFgJob = job;
            try
            {
                var limit = DateTime.Now.AddMinutes(30);
                while (true)
                {
                    ct.ThrowIfCancellationRequested();
                    var st = await KreaClient.PollAsync(job, ct);
                    if (st.Status == "completed")
                    {
                        if (string.IsNullOrEmpty(st.VideoUrl)) throw new InvalidOperationException(L.T("Krea ha finito ma non ha dato l'indirizzo del video"));
                        VideoPhase(L.T("Scaricamento del video"), 1);
                        var file = await FinishVideo(job, info, st.VideoUrl!, ct);
                        AppLog.Write($"krea: waited {(DateTime.Now - _videoStart).TotalSeconds:0} s in the panel");
                        _videoFgJob = null;
                        EndVideo();
                        ShowVideo(file);
                        return;
                    }
                    if (st.Error != null)
                    {
                        RemovePending(job);
                        throw new InvalidOperationException(st.Error);
                    }
                    if (DateTime.Now > limit) throw new TimeoutException(L.T("Krea non ha finito in 30 minuti: Simpler continua a controllare da solo"));
                    VideoPhase(st.Status is "processing" or "sampling" or "intermediate-complete" ? L.T("Krea sta creando il video") : L.T("In coda su Krea"), st.Progress);
                    await Task.Delay(3000, ct);
                }
            }
            catch (OperationCanceledException)
            {
                _videoFgJob = null;
                EndVideo();
                Status(L.T("Simpler non aspetta più qui: controlla da solo e, quando il video è pronto, compare un avviso verde e lo trovi in Elaborazioni AI › Video AI"));
                StartVideoWatch();
            }
            catch (Exception ex)
            {
                _videoFgJob = null;
                EndVideo();
                AppLog.Write("krea: job " + job + " " + ex.Message);
                Msg.Show(this, L.T("Il video non è riuscito:") + "\n\n" + ex.Message, "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning);
                StartVideoWatch();          // (a timeout: the job is still pending, watched in the background)
            }
        }

        bool _improving;
        string? _promptBefore;          // the text before «Migliora con l'AI» (for Annulla)

        /// <summary>(1.75.44) The motion text of this project (kept in the .simpler: a new project starts empty).</summary>
        string VideoPromptText => (string?)_videoFrames["prompt"] ?? "";

        async Task SetVideoPrompt(string text)
        {
            await Run(async api => { _videoFrames = await api.Post("video/prompt", new { text }); });
        }

        const string ImprovePromptSystem =
            "You write prompts for an image-to-video AI model that animates between a given FIRST frame and LAST frame " +
            "(photorealistic architectural / 3D scene renders). Rewrite the user's request into one prompt the video model " +
            "follows well. Rules: English; one paragraph, at most 110 words; describe the camera motion that leads from the first " +
            "frame to the last (or a static camera if they share the same framing) and what moves or changes in the scene; keep " +
            "everything the user asked and add nothing they did not ask (no people, vehicles or events of your own), only the " +
            "details needed for realistic, physically plausible motion that stays consistent with both frames; no text, logos, " +
            "cuts or transitions. Reply with the prompt only, no quotes, no comments.";

        /// <summary>(1.78.4) The same for a video made from the first frame only: what each subject does over time.</summary>
        const string ImprovePromptOneSystem =
            "You write prompts for an image-to-video AI model that starts from a given FIRST frame only (no last frame) and " +
            "follows the prompt (photorealistic architectural / 3D scene renders). Rewrite the user's request into one prompt the " +
            "video model follows well. Rules: English; one paragraph, at most 110 words; describe what each subject in the frame " +
            "does over time, referring to them by position and look (e.g. 'the old man in the white shirt'), and the camera (static " +
            "unless the user asks for a move); keep everything the user asked and add nothing they did not ask (no people, vehicles " +
            "or events of your own), only the details needed for realistic, physically plausible motion consistent with the frame; " +
            "no text, logos, cuts or transitions. Reply with the prompt only, no quotes, no comments.";

        /// <summary>(1.75.40) The motion text rewritten by the cheapest text model of the user's OpenAI key, with the two
        /// keyframes as small pictures (detail low: the cheapest way); the old text kept for Annulla.</summary>
        async Task ImproveVideoPrompt(string current)
        {
            if (_improving) return;
            _improving = true;
            RenderProps();
            try
            {
                var model = CurrentVideoModel();
                int secs = Math.Clamp(Settings.Load().VideoSeconds, 5, 10);
                bool still = _videoFrames["gap"] is JsonObject g && ((double?)g["metres"] ?? 1) < 0.05 && ((double?)g["degrees"] ?? 1) < 0.5;
                bool one = Settings.Load().VideoOneFrame;
                var user = one
                    ? $"Video model: {model.Name}. Length: {secs} seconds. ONLY the first frame is given (no last frame): the video starts from it and follows the prompt. " +
                      (current.Trim() == "" ? "The user wrote nothing: write a good prompt for this frame." : "User's request (any language):\n" + current.Trim())
                    : $"Video model: {model.Name}. Length: {secs} seconds. " +
                      (still ? "The two frames have the same camera framing (static camera; e.g. the light changes). " : "The camera moves between the two frames. ") +
                      (current.Trim() == "" ? "The user wrote nothing: write a good prompt for these two frames." : "User's request (any language):\n" + current.Trim());
                var imgs = new System.Collections.Generic.List<string>();
                foreach (var slot in one ? new[] { "start" } : VideoSlots)
                {
                    var path = (string?)(_videoFrames[slot] as JsonObject)?["image"] ?? "";
                    if (!File.Exists(path)) continue;
                    var small = AiImage.Decode(File.ReadAllBytes(path), 512);
                    var enc = new JpegBitmapEncoder { QualityLevel = 80 };
                    enc.Frames.Add(BitmapFrame.Create(small));
                    using var ms = new MemoryStream();
                    enc.Save(ms);
                    imgs.Add("data:image/jpeg;base64," + Convert.ToBase64String(ms.ToArray()));
                }
                using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(90));
                var r = await AiText.AskAsync(one ? ImprovePromptOneSystem : ImprovePromptSystem, user, imgs.ToArray(), cts.Token);
                var s = Settings.Load();
                _promptBefore = current;
                await SetVideoPrompt(r.Text.Trim().Trim('"'));
                s.AiTokensIn += r.InputTokens; s.AiTokensOut += r.OutputTokens;
                s.Save();
                AppLog.Write($"video prompt improved with {r.Model}: {r.InputTokens} in, {r.OutputTokens} out");
                Status(L.F(current.Trim() == "" ? "Testo creato con {0} ({1} token in, {2} out)" : "Testo migliorato con {0} ({1} token in, {2} out)", r.Model, r.InputTokens, r.OutputTokens));
            }
            catch (Exception ex)
            {
                AppLog.Write("video prompt improve: " + ex.Message);
                Msg.Show(this, L.T("Non sono riuscito a scrivere il testo:") + "\n\n" + ex.Message, "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning);
            }
            finally
            {
                _improving = false;
                if (_rightPanel == "video") RenderProps();
            }
        }

        static string VideoRecipesRoot => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Simpler", "video-recipes");

        /// <summary>(1.75.39) Everything that makes this video, in a folder of its own until the video arrives (it
        /// survives a restart of Simpler, for a video downloaded later): recipe.json and the two keyframe pictures.</summary>
        async Task<string?> SaveVideoRecipe(VideoModel model, string res, int secs, bool audio, string prompt, string start, string? end)
        {
            try
            {
                JsonObject? raw = null;
                await Run(async api => { raw = await api.Get("video/frames/raw"); });
                var dir = Path.Combine(VideoRecipesRoot, DateTime.Now.ToString("yyyyMMdd-HHmmss-fff"));
                Directory.CreateDirectory(dir);
                File.Copy(start, Path.Combine(dir, "start.jpg"), true);
                if (end != null) File.Copy(end, Path.Combine(dir, "end.jpg"), true);
                var recipe = new JsonObject
                {
                    ["version"] = 1, ["model"] = model.Id, ["modelName"] = model.Name, ["res"] = res, ["seconds"] = secs, ["audio"] = audio,
                    ["prompt"] = prompt, ["frames"] = raw?["frames"]?.DeepClone() ?? new JsonObject(),
                    ["oneFrame"] = end == null,
                };
                File.WriteAllText(Path.Combine(dir, "recipe.json"), recipe.ToJsonString());
                return dir;
            }
            catch (Exception ex) { AppLog.Write("video recipe: " + ex.Message); return null; }
        }

        /// <summary>(1.75.39) A video of the library: model, resolution, seconds, audio, motion and the two keyframes
        /// (with the state of the scene and their pictures) back in the Video AI panel, to make another version.</summary>
        async Task RestoreVideoRecipe(AiOutput o)
        {
            if (_videoCts != null) { Status(L.T("Un video è in preparazione: i parametri si potranno caricare quando ha finito"), true); return; }
            try
            {
                var r = JsonNode.Parse(o.Params) as JsonObject;
                if (r == null) return;
                var s = Settings.Load();
                s.VideoModel = (string?)r["model"] ?? s.VideoModel;
                s.VideoRes = (string?)r["res"] ?? s.VideoRes;
                s.VideoSeconds = (int?)r["seconds"] ?? s.VideoSeconds;
                s.VideoAudio = (bool?)r["audio"] ?? s.VideoAudio;
                s.VideoOneFrame = (bool?)r["oneFrame"] ?? false;
                var recipePrompt = (string?)r["prompt"] ?? "";
                s.Save();
                _promptBefore = null;
                await SetVideoPrompt(recipePrompt);
                if (r["frames"] is JsonObject fr)
                {
                    fr = (JsonObject)fr.DeepClone();
                    if (fr["start"] is JsonObject fs && File.Exists(o.StartImg)) fs["image"] = o.StartImg;
                    if (fr["end"] is JsonObject fe && File.Exists(o.EndImg)) fe["image"] = o.EndImg;
                    await Run(async api => { _videoFrames = await api.Post("video/frames/restore", new JsonObject { ["frames"] = fr }); });
                }
                if (_rightPanel != "video") await ShowRightPanel("video");
                else { await LoadVideoFrames(); RenderProps(); }
                Status(L.F("Parametri di «{0}» caricati nel pannello Video AI: cambia quello che vuoi e crea un'altra versione", AiOutputTitle(o)));
            }
            catch (Exception ex) { AppLog.Write("video recipe restore: " + ex.Message); }
        }

        void StartVideoTimer()
        {
            _videoTimer ??= new DispatcherTimer { Interval = TimeSpan.FromSeconds(1) };
            _videoTimer.Tick -= VideoTimerTick;
            _videoTimer.Tick += VideoTimerTick;
            _videoTimer.Start();
        }

        void VideoTimerTick(object? sender, EventArgs e)
        {
            if (_videoStatus != null && _rightPanel == "video") _videoStatus.Text = VideoStatusText();
        }

        void EndVideo()
        {
            _videoTimer?.Stop();
            _videoCts?.Dispose();
            _videoCts = null;
            _videoStatus = null;
            if (_rightPanel == "video") RenderProps();
        }

        void ShowVideo(string file)
        {
            var w = new VideoWindow(this, file);
            w.Show();
        }

        static void OpenUrl(string url)
        {
            try { System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(url) { UseShellExecute = true }); } catch { }
        }
    }
}
