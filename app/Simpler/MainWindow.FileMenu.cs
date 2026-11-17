using System;
using System.IO;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace Simpler
{
    /// <summary>The file menu (open, save, save as, info, close), the settings panel on the left, automatic saves.</summary>
    public sealed partial class MainWindow
    {
        // ---------------------------------------------------------------- one file command at a time

        bool _fileOp;

        // a click on New / Open / Save while another one is running (or the engine is stuck) is ignored: before, the
        // clicks waited in a queue and came back one after the other as "save the changes?" questions
        async Task NewProject()
        {
            if (_fileOp) return;
            _fileOp = true;
            try { await NewProjectCore(); } finally { _fileOp = false; }
        }

        async Task OpenProject()
        {
            if (_fileOp) return;
            _fileOp = true;
            try { await OpenProjectCore(); } finally { _fileOp = false; }
        }

        async Task OpenRecent(string path)
        {
            if (_fileOp) return;
            _fileOp = true;
            try { await OpenRecentCore(path); } finally { _fileOp = false; }
        }

        async Task<bool> SaveProject(bool saveAs)
        {
            await FlushTerrainSculpt();         // (1.76.44: the strokes of a «Scultura» still open, in the file)
            if (_fileOp) return false;
            _fileOp = true;
            try { return await SaveProjectCore(saveAs); } finally { _fileOp = false; }
        }

        void ShowFileMenu(FrameworkElement anchor)
        {
            var m = new ContextMenu { PlacementTarget = anchor, Placement = System.Windows.Controls.Primitives.PlacementMode.Bottom };
            MenuItem Item(string text, string keys, Func<Task> act)
            {
                var i = new MenuItem { Header = text, InputGestureText = keys };
                i.Click += async (_, __) => await act();
                m.Items.Add(i);
                return i;
            }
            // (1.78.4, Luca: «la storia di Simpler sparisce, mettilo come primo comando del menu: scena di esempio»; the story
            // stays in the library, «Perché esiste Simpler»)
            var sampleDir = System.IO.Path.Combine(AppContext.BaseDirectory, "samples", SampleFolder);
            if (System.IO.File.Exists(System.IO.Path.Combine(sampleDir, SampleFile)))
            {
                // (Luca: «example scene non va bene, voglio che apra il riquadro dell'avvio sotto») the start box of the
                // library, with the example project, the ideas and the free models
                Item(L.T("Scena di esempio"), "", () => { _libraryTab = "story"; RenderLibrary(); return System.Threading.Tasks.Task.CompletedTask; });
                m.Items.Add(new Separator());
            }
            Item(L.T("Nuova scena"), "Ctrl+N", NewProject);
            Item(L.T("Apri…"), "Ctrl+O", OpenProject);
            m.Items.Add(new Separator());
            Item(L.T("Salva"), "Ctrl+S", async () => await SaveProject(false));
            Item(L.T("Salva con nome…"), L.T("Ctrl+Maiusc+S"), async () => await SaveProject(true));
            m.Items.Add(new Separator());
            Item(L.T("Cerca texture mancanti…"), "", FindMissingTexturesOfProject);
            m.Items.Add(new Separator());
            Item(L.T("Info"), "", () => { ShowInfo(); return Task.CompletedTask; });
            Item(L.T("Licenze e crediti"), "", () => { new CreditsWindow(this).ShowDialog(); return Task.CompletedTask; });
            Item(L.T("Diagnostica…"), "", () => { new DiagDialog(this, firstTime: false).ShowDialog(); return Task.CompletedTask; });
            Item(L.T("Impostazioni"), "", () => { ToggleSettingsPanel(true); return Task.CompletedTask; });
            m.Items.Add(new Separator());
            Item(L.T("Chiudi Simpler"), "Alt+F4", () => { Close(); return Task.CompletedTask; });
            // the last projects opened or saved: one click opens them
            var recent = Settings.Load().RecentProjects;
            if (recent.Count > 0)
            {
                m.Items.Add(new Separator());
                m.Items.Add(new MenuItem { Header = L.T("Recenti"), IsEnabled = false });
                foreach (var file in recent)
                {
                    var f = file;
                    var exists = File.Exists(f);
                    var i = new MenuItem
                    {
                        Header = Path.GetFileNameWithoutExtension(f).Replace("_", "__"),
                        ToolTip = exists ? f : L.F("Non trovato: {0}", f),
                        Opacity = exists ? 1.0 : 0.5,
                        IsChecked = _projectPath != null && string.Equals(Path.GetFullPath(_projectPath), f, StringComparison.OrdinalIgnoreCase),
                    };
                    i.Click += async (_, __) => await OpenRecent(f);
                    m.Items.Add(i);
                }
            }
            m.IsOpen = true;
        }

        void ShowInfo()
        {
            var w = new SplashWindow { Owner = this, Topmost = false, WindowStartupLocation = WindowStartupLocation.CenterOwner, ShowInTaskbar = false };
            w.AsInfo(L.F("Simpler {0} · {1}", SettingsDialog.Version, _engineLabel));
            w.ShowDialog();
        }

        // ---------------------------------------------------------------- automatic saves

        System.Windows.Threading.DispatcherTimer? _autosaveTimer;
        DateTime _lastAutosave = DateTime.UtcNow;

        void StartAutosave()
        {
            if (_autosaveTimer != null) return;
            _autosaveTimer = new System.Windows.Threading.DispatcherTimer { Interval = TimeSpan.FromSeconds(30) };
            _autosaveTimer.Tick += async (_, __) => await AutosaveTick();
            _autosaveTimer.Start();
        }

        /// <summary>Minutes between automatic copies: off, 10, 20 or 30 (an older setting of 5 or 15 goes to the next
        /// one up: on a big project each copy stops the engine for some seconds).</summary>
        static int AutosaveEvery()
        {
            var m = Settings.Load().AutosaveMinutes;
            return m <= 0 ? 0 : m <= 10 ? 10 : m <= 20 ? 20 : 30;
        }

        async Task AutosaveTick()
        {
            var minutes = AutosaveEvery();
            if (minutes <= 0 || _api == null || _engineDead) return;
            if ((DateTime.UtcNow - _lastAutosave).TotalMinutes < minutes) return;
            // only when nothing else is going on: never in the middle of a command, a file operation or a render
            if (_fileOp || _engineCalls > 0 || IsBusy) return;
            // (audit 1.78.5) not while the user works (also in the 3D view, which WPF does not see): 20 s without input
            if (InputIdleSeconds() < 20) return;
            _lastAutosave = DateTime.UtcNow;
            try
            {
                var r = await _api.Post("autosave", new { project = _projectPath ?? "" });
                if ((bool?)r["saved"] ?? false)
                    Status(L.F("Salvataggio automatico alle {0}", DateTime.Now.ToString("HH:mm")));
            }
            catch (Exception ex) { AppLog.Write("autosave failed: " + ex.Message); }
        }

        [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
        struct LastInputInfo { public uint cbSize; public uint dwTime; }
        [System.Runtime.InteropServices.DllImport("user32.dll")]
        static extern bool GetLastInputInfo(ref LastInputInfo info);

        /// <summary>Seconds since the last key or mouse input of the session (anywhere: the 3D view too).</summary>
        static double InputIdleSeconds()
        {
            var li = new LastInputInfo { cbSize = (uint)System.Runtime.InteropServices.Marshal.SizeOf<LastInputInfo>() };
            if (!GetLastInputInfo(ref li)) return 1e9;
            return unchecked((uint)Environment.TickCount - li.dwTime) / 1000.0;
        }

        async Task DiscardAutosave()
        {
            try { if (_api != null) await _api.Post("autosave/discard", new { project = _projectPath ?? "" }); } catch { }
        }

        /// <summary>Before opening a project: is there an automatic copy newer than it? Returns the file to open.</summary>
        async Task<(string path, bool recovered)> AskRecoverAutosave(string project)
        {
            if (_api == null) return (project, false);
            JsonObject? info = null;
            try { info = await _api.Get("autosave/info?project=" + Uri.EscapeDataString(project)); } catch { }
            if (info == null || !((bool?)info["exists"] ?? false) || !((bool?)info["newer"] ?? false)) return (project, false);
            var q = L.F("C'è un salvataggio automatico di «{0}» più recente del progetto ({1}): Simpler forse non era stato chiuso bene.\n\nRecuperarlo? (No: si apre il progetto com'era all'ultimo salvataggio e la copia automatica viene eliminata)",
                        Path.GetFileNameWithoutExtension(project), (string?)info["when"] ?? "");
            var a = Msg.Show(this, q, "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question);
            if (a == MessageBoxResult.Yes) return ((string?)info["path"] ?? project, true);
            try { await _api.Post("autosave/discard", new { project }); } catch { }
            return (project, false);
        }

        // ---------------------------------------------------------------- settings: a panel in the right sidebar

        JsonObject? _projectOpts;

        void ToggleSettingsPanel(bool? show = null)
        {
            var on = show ?? _rightPanel != "settings";
            _ = Dispatcher.InvokeAsync(async () =>
            {
                if (on)
                {
                    try { if (_api != null) _projectOpts = await _api.Get("project/options"); } catch { }
                    await ShowRightPanel("settings");
                    // (1.75.46) the Krea key's state for the API keys section (OpenAI is tested at start)
                    if (KreaKey.Exists && KreaKey.Ok == null) { await KreaKey.TestAsync(); if (_rightPanel == "settings") RenderProps(); }
                }
                else if (_rightPanel == "settings") await ShowRightPanel("");
            });
        }

        void RenderSettingsPanel()
        {
            // (1.75.46) in sections that close like the other panels (double arrow, icons), the API keys at the bottom
            var opts = _projectOpts;
            var head = new DockPanel();
            var close = Theme.Button(Theme.Icon(CloseIcon, null, 14), Theme.Kind.Ghost, L.T("Chiudi le impostazioni"));
            close.Padding = new Thickness(6, 0, 6, 0);
            close.Click += (_, __) => ToggleSettingsPanel(false);
            DockPanel.SetDock(close, Dock.Right);
            head.Children.Add(close);
            head.Children.Add(Theme.Label(L.T("Impostazioni"), 16, Theme.Text, FontWeights.SemiBold));
            _props.Children.Add(Theme.Card(head, 16));

            StackPanel Section(string title, Geometry icon, Color color)
            {
                var sp = new StackPanel();
                var t = SectionTitle(title);
                t.DataContext = (icon, color);
                sp.Children.Add(t);
                _props.Children.Add(Theme.Card(sp, 16));
                return sp;
            }
            UIElement Sub(string t) { var l = Theme.Label(t, 12.5, Theme.TextSoft); l.Margin = new Thickness(0, 12, 0, 6); return l; }

            // ---- language
            var lang = Section(L.T("Lingua"), Icons.Globe, Theme.Accent);
            var langs = Theme.Segmented(out var langButtons, ("Italiano", null), ("English", null));
            langs.HorizontalAlignment = HorizontalAlignment.Left;
            Theme.SetSegment(langButtons, L.Lang == "en" ? 1 : 0);
            string[] ids = { "it", "en" };
            for (int i = 0; i < langButtons.Count; i++)
            {
                var id = ids[i];
                var idx = i;
                langButtons[i].Click += (_, __) =>
                {
                    Theme.SetSegment(langButtons, idx);
                    var s = Settings.Load();
                    if (s.Language == id || (s.Language == "" && L.Lang == id)) return;
                    s.Language = id;
                    s.Save();
                    Msg.Show(this, id == "en" ? L.T("The language will change the next time you start Simpler.") : L.T("La lingua cambierà al prossimo avvio di Simpler."),
                        "Simpler", MessageBoxButton.OK, MessageBoxImage.Information);
                };
            }
            lang.Children.Add(langs);

            // ---- navigation
            var nav = Section(L.T("Navigazione"), Icons.Move, Theme.Teal);
            var pad = new Toggle(L.T("Touchpad: due dita spostano la vista"), Settings.Load().TouchpadPan,
                L.T("Due dita su e giù (o di lato) spostano la scena senza ruotarla, come il tasto centrale del mouse; pizzicare avvicina o allontana. Spento: le due dita camminano avanti e indietro come la rotellina"));
            pad.Toggled += v => { var s = Settings.Load(); s.TouchpadPan = v; s.Save(); if (_webReady) SendToWeb(new { type = "touchpad", on = v }); };
            nav.Children.Add(pad);

            // ---- saving
            var save = Section(L.T("Salvataggio"), Icons.Save, Theme.AxisY);
            var backup = new Toggle(L.T("Backup prima di salvare"), (bool?)opts?["backup"] ?? true,
                L.T("Salvando, il file precedente resta come copia «nome.simpler1» accanto al progetto (una sola copia, sostituita a ogni salvataggio). È un'impostazione di questa scena, salvata con lei"));
            backup.Toggled += async v => { try { if (_api != null) _projectOpts = await _api.Post("project/options", new { backup = v }); } catch { } };
            save.Children.Add(backup);
            var copyTex = new Toggle(L.T("Copia le texture accanto al progetto"), (bool?)opts?["copyTextures"] ?? true,
                L.T("Salvando, le immagini prese da cartelle esterne (Download, desktop, la cartella di un modello importato) vengono copiate nella cartella «nome texture» accanto al progetto, e il progetto usa le copie: puoi spostare o cancellare gli originali e portare il progetto su un altro computer. Ogni immagine si copia una volta sola. Le librerie di Simpler restano dove sono. È un'impostazione di questa scena, salvata con lei"));
            copyTex.Toggled += async v => { try { if (_api != null) _projectOpts = await _api.Post("project/options", new { copyTextures = v }); } catch { } };
            save.Children.Add(copyTex);
            save.Children.Add(Sub(L.T("Salvataggio automatico")));
            int[] mins = { 0, 10, 20, 30 };
            var auto = Theme.Segmented(out var autoButtons, (L.T("Spento"), null), ("10 min", null), ("20 min", null), ("30 min", null));
            auto.HorizontalAlignment = HorizontalAlignment.Left;
            Theme.SetSegment(autoButtons, Math.Max(0, Array.IndexOf(mins, AutosaveEvery())));
            for (int i = 0; i < autoButtons.Count; i++)
            {
                var idx = i;
                autoButtons[i].Padding = new Thickness(8, 0, 8, 0);
                autoButtons[i].Click += (_, __) =>
                {
                    Theme.SetSegment(autoButtons, idx);
                    foreach (var b in autoButtons) b.Padding = new Thickness(8, 0, 8, 0);
                    var s = Settings.Load(); s.AutosaveMinutes = mins[idx]; s.Save();
                };
            }
            save.Children.Add(auto);
            save.Children.Add(Hint(L.T("Una copia «nome.autosave.simpler» accanto al progetto, solo se ci sono modifiche: il tuo file cambia solo quando premi Salva. Se Simpler si chiude male, all'apertura del progetto propone di recuperarla.")));

            // ---- folders
            var fold = Section(L.T("Cartelle"), Icons.Folder, Theme.Warm);
            var folders = SmallButton(Icons.Folder, L.T("Cartelle dei file scaricati e delle librerie…"), async () => await ShowFoldersDialog());
            folders.HorizontalAlignment = HorizontalAlignment.Left;
            fold.Children.Add(folders);
            // the materials of Simpler are files of the library like the user's (1.68.1): deleted or changed ones back
            var restore = SmallButton(Icons.Refresh, L.T("Ripristina i materiali di Simpler"), async () =>
            {
                JsonObject? r = null;
                await Run(async api => { r = await api.Post("material/library/restore", new JsonObject()); });
                if (r == null) return;
                int back = (int?)r["restored"] ?? 0, kept = (int?)r["kept"] ?? 0;
                Status(back == 0 ? L.T("I materiali di Simpler sono già tutti come l'originale")
                                 : L.F("Ripristinati {0} materiali di Simpler", back) + (kept > 0 ? " · " + L.F("{0} versioni modificate tenute come «(modificato)»", kept) : ""));
                await ReloadLibraryMaterials();
            });
            restore.ToolTip = L.T("Rimette nella libreria i materiali di Simpler eliminati e riporta all'originale quelli modificati (la versione modificata resta, come «nome (modificato)»). I tuoi materiali e i progetti non cambiano");
            restore.HorizontalAlignment = HorizontalAlignment.Left;
            restore.Margin = new Thickness(0, 6, 0, 0);
            fold.Children.Add(restore);

            // ---- API keys (OpenAI, Krea): what they are, the state of each, add / test / delete
            var keys = Section(L.T("Chiavi API"), Icons.Key, Theme.Warm);
            var what = Theme.Label(L.T("Le chiavi API sono codici personali che collegano Simpler al tuo account presso un fornitore di intelligenza artificiale: OpenAI per le immagini e i testi, Krea per i video. Le crei tu sul sito del fornitore e le incolli qui. Simpler le conserva cifrate solo su questo computer, per il tuo utente di Windows, e non le mostra più."), 12, Theme.TextMuted);
            what.TextWrapping = TextWrapping.Wrap;
            keys.Children.Add(what);
            var how = Theme.Label(L.T("Le richieste partono dal tuo computer e vanno direttamente al fornitore. I costi sono a consumo, ai prezzi del fornitore, e li addebita il fornitore sul tuo account; le stime nel programma sono solo indicative. Le chiavi sono tue: sei tu responsabile del loro uso, dei contenuti che invii, del rispetto delle condizioni del fornitore e dei limiti di spesa, che puoi impostare sul suo sito."), 12, Theme.TextMuted);
            how.TextWrapping = TextWrapping.Wrap;
            how.Margin = new Thickness(0, 8, 0, 0);
            keys.Children.Add(how);
            var note = new Border
            {
                Margin = new Thickness(0, 10, 0, 4), Padding = new Thickness(10, 8, 10, 8), CornerRadius = new CornerRadius(7),
                Background = new SolidColorBrush(Color.FromArgb(34, Theme.AxisY.R, Theme.AxisY.G, Theme.AxisY.B)),
                BorderBrush = new SolidColorBrush(Color.FromArgb(110, Theme.AxisY.R, Theme.AxisY.G, Theme.AxisY.B)), BorderThickness = new Thickness(1),
            };
            var noteT = Theme.Label(L.T("Simpler non riceve alcun compenso, commissione o vantaggio dall'uso delle API: i costi sono solo quelli dei fornitori, pagati da te direttamente a loro."), 12.5, Theme.Text, FontWeights.SemiBold);
            noteT.TextWrapping = TextWrapping.Wrap;
            note.Child = noteT;
            keys.Children.Add(note);
            keys.Children.Add(ApiKeyBlock("OpenAI", L.T("Immagini AI e «Crea/migliora con l'AI»"), "https://platform.openai.com/api-keys",
                () => AiKey.Exists, () => AiKey.Ok, () => AiKey.Message,
                k => AiKey.Save(k), async () => { await AiKey.TestAsync(); UpdateAiButton(); }, () => { AiKey.Delete(); UpdateAiButton(); }));
            keys.Children.Add(ApiKeyBlock("Krea", L.T("Video AI"), "https://www.krea.ai/app/api/tokens",
                () => KreaKey.Exists, () => KreaKey.Ok, () => KreaKey.Message,
                k => KreaKey.Save(k), async () => { await KreaKey.TestAsync(); }, () => KreaKey.Delete()));

            // ---- version
            var ver = Section(L.T("Versione"), Icons.Help, Theme.Accent);
            var vt = Theme.Label(L.T("Simpler ") + SettingsDialog.Version, 14, Theme.Text);
            vt.Margin = new Thickness(0, 0, 0, 8);
            ver.Children.Add(vt);
            var row = new WrapPanel();
            row.Children.Add(SmallButton(Icons.Sparkles, L.T("Novità di questa versione"), async () => await ShowNotesPanel()));
            row.Children.Add(SmallButton(Icons.Help, L.T("Info"), () => { ShowInfo(); return Task.CompletedTask; }));
            row.Children.Add(SmallButton(Icons.Layers, L.T("Licenze e crediti"), () => { new CreditsWindow(this).ShowDialog(); return Task.CompletedTask; }));
            ver.Children.Add(row);

            // ---- (1.78.4, Luca) updates: the automatic check (on by default) and «Controlla ora», its outcome always shown
            var upd = Section(L.T("Aggiornamenti"), Icons.Refresh, Theme.Accent);
            var autoUpd = new Toggle(L.T("Controlla automaticamente gli aggiornamenti"), Settings.Load().UpdateCheck,
                L.T("All'avvio, al massimo una volta al giorno, Simpler chiede al sito se c'è una versione nuova. Non scarica e non installa nulla da solo"));
            autoUpd.Toggled += v => { var s = Settings.Load(); s.UpdateCheck = v; s.Save(); };
            upd.Children.Add(autoUpd);
            upd.Children.Add(Hint(L.T("Simpler invia al sito soltanto il numero di versione e la lingua. Si può disattivare.")));
            var checkBar = new ProgressBar { Height = 6, IsIndeterminate = false, Foreground = Theme.B(Theme.Accent), Background = Theme.B("#1A2842"),
                                             BorderThickness = new Thickness(0), Margin = new Thickness(0, 4, 0, 6), Visibility = Visibility.Collapsed };
            var checkOut = Theme.Label("", 12, Theme.TextSoft);
            checkOut.TextWrapping = TextWrapping.Wrap;
            checkOut.Visibility = Visibility.Collapsed;
            Button? checkNow = null;
            checkNow = SmallButton(Icons.Refresh, L.T("Controlla ora"), async () =>
            {
                checkNow!.IsEnabled = false;
                checkBar.Visibility = Visibility.Visible; checkBar.IsIndeterminate = true;
                upd.Cursor = System.Windows.Input.Cursors.AppStarting;
                checkOut.Visibility = Visibility.Visible;
                checkOut.Foreground = Theme.B(Theme.TextSoft);
                checkOut.Text = L.T("Controllo in corso…");
                var info = await UpdateCheck.Run(manual: true);
                checkBar.IsIndeterminate = false; checkBar.Visibility = Visibility.Collapsed;
                upd.Cursor = null;
                checkNow.IsEnabled = true;
                if (info == null)
                {
                    checkOut.Foreground = Theme.B(Theme.Warm);
                    checkOut.Text = L.T("Non è stato possibile controllare: il sito non risponde o manca la connessione. Riprova più tardi.");
                }
                else if (info.UpdateAvailable)
                    checkOut.Text = (info.Required ? L.F("Questa versione non è più aggiornata: è disponibile Simpler {0}.", info.Latest)
                                                   : L.F("È disponibile Simpler {0}.", info.Latest))
                                    + " " + L.T("La trovi nella striscia in basso nella finestra di Simpler.");
                else checkOut.Text = L.F("Hai già l'ultima versione (Simpler {0}).", SettingsDialog.Version);
            });
            checkNow.ToolTip = L.T("Chiede subito al sito se c'è una versione nuova di Simpler");
            checkNow.HorizontalAlignment = HorizontalAlignment.Left;
            checkNow.Margin = new Thickness(0, 8, 0, 0);
            upd.Children.Add(checkNow);
            upd.Children.Add(checkBar);
            upd.Children.Add(checkOut);

            // ---- engine
            var eng = Section(L.T("Motore di render"), Icons.Chip, Theme.AxisY);
            var blender = Theme.Label(EngineHost.FindBlender() ?? L.T("Blender non trovato"), 12, Theme.TextFaint);
            blender.TextWrapping = TextWrapping.Wrap;
            eng.Children.Add(blender);
        }

        /// <summary>(1.75.46) One API key in the settings: active or not, test again, delete; without a key the box to
        /// paste it (saved encrypted, never shown again) and the link to the provider's page.</summary>
        UIElement ApiKeyBlock(string provider, string usedFor, string url, Func<bool> exists, Func<bool?> ok, Func<string> message,
                              Action<string> save, Func<Task> test, Action delete)
        {
            var box = new StackPanel { Margin = new Thickness(0, 14, 0, 0) };
            var top = new DockPanel();
            bool has = exists(), works = has && ok() == true, bad = has && ok() == false;
            var (stateText, stateColor) = !has ? (L.T("Non inserita"), Theme.TextFaint)
                                       : works ? (L.T("Attiva"), Theme.AxisY)
                                       : bad ? (L.T("Non funziona"), Theme.Danger)
                                       : (L.T("Da verificare"), Theme.Warm);
            var pill = new Border
            {
                CornerRadius = new CornerRadius(9), Padding = new Thickness(8, 1, 8, 2), VerticalAlignment = VerticalAlignment.Center,
                Background = new SolidColorBrush(Color.FromArgb(40, stateColor.R, stateColor.G, stateColor.B)),
                Child = Theme.Label(stateText, 11.5, stateColor, FontWeights.SemiBold),
            };
            DockPanel.SetDock(pill, Dock.Right);
            top.Children.Add(pill);
            var name = new StackPanel { Orientation = Orientation.Horizontal };
            name.Children.Add(Theme.Label(provider, 13, Theme.Text, FontWeights.SemiBold));
            var uf = Theme.Label(" · " + usedFor, 12, Theme.TextFaint);
            uf.VerticalAlignment = VerticalAlignment.Center;
            name.Children.Add(uf);
            top.Children.Add(name);
            box.Children.Add(top);
            if (bad)
            {
                var m = Theme.Label(message(), 11.5, Theme.Danger);
                m.TextWrapping = TextWrapping.Wrap;
                m.Margin = new Thickness(0, 4, 0, 0);
                box.Children.Add(m);
            }
            var row = new WrapPanel { Margin = new Thickness(0, 6, 0, 0) };
            if (!has)
            {
                var input = Theme.Input("", true);
                input.Margin = new Thickness(0, 6, 0, 6);
                input.ToolTip = L.T("Incolla qui la chiave: viene salvata cifrata e non si potrà più vedere");
                box.Children.Add(input);
                row.Children.Add(SmallButton(Icons.Key, L.T("Salva e verifica"), async () =>
                {
                    var k = input.Text.Trim();
                    if (k.Length < 16) { Msg.Show(this, L.T("Questa non sembra una chiave API: incollala per intero."), "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning); return; }
                    save(k);
                    input.Text = "";
                    RenderProps();
                    await test();
                    AppLog.Write($"{provider} key saved from the settings, test {(ok() == true ? "ok" : "failed")}");
                    if (_rightPanel == "settings") RenderProps();
                }));
                row.Children.Add(SmallButton(Icons.Globe, L.F("Crea la chiave su {0}", provider), () => { OpenUrl(url); return Task.CompletedTask; }));
            }
            else
            {
                row.Children.Add(SmallButton(Icons.Refresh, L.T("Verifica di nuovo"), async () => { await test(); if (_rightPanel == "settings") RenderProps(); }));
                row.Children.Add(SmallButton(Icons.Trash, L.T("Elimina chiave"), () =>
                {
                    if (Msg.Show(this, L.F("Eliminare la chiave {0} da Simpler? Le funzioni che la usano si spengono finché non ne inserisci una.", provider), "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return Task.CompletedTask;
                    delete();
                    AppLog.Write($"{provider} key deleted from the settings");
                    RenderProps();
                    return Task.CompletedTask;
                }));
            }
            box.Children.Add(row);
            return box;
        }
    }
}
