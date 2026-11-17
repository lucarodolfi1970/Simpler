using System;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;

namespace Simpler
{
    /// <summary>
    /// Sending of the diagnostics (see Diagnostics.cs for what is collected and cleaned). Nothing leaves the computer without
    /// the user's yes: «Automatico» (only the serious problems, by themselves, at most once a day), «Solo quando decido io»
    /// (the button «Invia ora»), «Non inviare». The question is asked once (again only if the text changes).
    /// </summary>
    public static class DiagService
    {
        public static string Endpoint = "https://www.rodluc.com/simpler/diag/receive.php";

        static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(20) };
        static string Roaming => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Simpler");
        static string Local => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Simpler");
        static string StateFile => Path.Combine(Roaming, AppInstance.Prefix + "diag.json");
        static string SessionFile => Path.Combine(Local, AppInstance.Prefix + "session.json");
        static readonly object Gate = new();
        static bool _previousCrashed, _asked;
        static DispatcherTimer? _timer;

        /// <summary>First thing at start: was the previous run closed badly?</summary>
        public static void Begin()
        {
            _previousCrashed = Diagnostics.StartSession(SessionFile);
            if (_previousCrashed) AppLog.Write("the previous session did not end cleanly (crash or forced close)");
        }

        /// <summary>The window closes by the user's choice: this run ended well.</summary>
        public static void End() => Diagnostics.EndSession(SessionFile);

        public static Diagnostics.State GetState()
        {
            lock (Gate)
            {
                var existed = File.Exists(StateFile);
                var st = Diagnostics.Load(StateFile);
                if (!existed) Diagnostics.Save(StateFile, st);        // (the random id of this installation is kept from now on)
                return st;
            }
        }

        static void SaveState(Diagnostics.State st) { lock (Gate) Diagnostics.Save(StateFile, st); }

        static Diagnostics.Context MakeContext()
        {
            var g = GpuRating.Last ?? GpuRating.Detect();
            double ram = 0;
            try { ram = Math.Round(GC.GetGCMemoryInfo().TotalAvailableMemoryBytes / 1073741824.0, 1); } catch { }
            return new Diagnostics.Context
            {
                App = SettingsDialog.Version, Os = Environment.OSVersion.VersionString, RamGb = ram, Lang = L.Lang,
                Gpu = g?.Name ?? "", VramGb = g?.VramGb ?? 0, GpuScore = g?.Score ?? 0,
            };
        }

        static string[] ReadLog()
        {
            try
            {
                using var fs = new FileStream(AppLog.FilePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
                using var sr = new StreamReader(fs, Encoding.UTF8);
                return sr.ReadToEnd().Split('\n').Select(l => l.TrimEnd('\r')).ToArray();
            }
            catch { return Array.Empty<string>(); }
        }

        /// <summary>The report of what the log holds now. since = null: all of it; the crash of the previous run is told once.</summary>
        public static Diagnostics.Report Build(Diagnostics.State st, DateTime? since)
        {
            var crashed = _previousCrashed;
            return Diagnostics.Build(ReadLog(), MakeContext(), st.Install, since, crashed);
        }

        static async Task<bool> Post(Diagnostics.Report r)
        {
            try
            {
                using var content = new StringContent(Diagnostics.ToJson(r), Encoding.UTF8, "application/json");
                using var resp = await Http.PostAsync(Endpoint, content).ConfigureAwait(false);
                var ok = resp.IsSuccessStatusCode;
                AppLog.Write($"diagnostics {r.Trigger}: {(ok ? "sent" : "not sent (" + (int)resp.StatusCode + ")")}, {r.Events.Count} entries");
                return ok;
            }
            catch (Exception ex) { AppLog.Write("diagnostics: not sent (" + ex.GetType().Name + ")"); return false; }
        }

        /// <summary>«Invia ora»: everything the log holds, whatever the mode (the user pressed the button).</summary>
        public static async Task<bool> SendNow()
        {
            var st = GetState();
            var r = Build(st, null);
            r.Trigger = "manual";
            if (!await Post(r)) return false;
            _previousCrashed = false;
            Diagnostics.MarkSent(r, st, DateTime.UtcNow, false);
            SaveState(st);
            return true;
        }

        /// <summary>By itself, only with the consent «auto»: a serious problem not sent yet (see Diagnostics.AutoCandidate).</summary>
        public static async Task AutoCheck()
        {
            try
            {
                if (AppInstance.Prefix != "") return;
                var st = GetState();
                if (st.Consent != "auto") return;
                // (15/11, Luca: «perché non si vede anche il secondo PC?») a computer where all goes well never sent anything and was
                // not in the statistics. With the consent «auto» for the current text (which says it), once for each version: a
                // report with no events - the version, Windows, the language, the memory and the video card with its rating
                if (st.TextVersion == Diagnostics.ConsentTextVersion && st.HelloVersion != SettingsDialog.Version)
                {
                    var hello = new Diagnostics.Report { Install = st.Install, Ctx = MakeContext(), Created = DateTime.UtcNow.ToString("o"), Trigger = "install" };
                    if (await Post(hello)) { st.HelloVersion = SettingsDialog.Version; SaveState(st); }
                    return;                 // (the site wants a minute between two reports: the problems go at the next check)
                }
                DateTime? since = DateTime.TryParse(st.LastSent, null, System.Globalization.DateTimeStyles.RoundtripKind, out var t) ? t : null;
                var all = Build(st, since);
                var r = Diagnostics.AutoCandidate(all, st, DateTime.UtcNow);
                if (r == null) return;
                if (!await Post(r)) return;
                _previousCrashed = false;
                Diagnostics.MarkSent(r, st, DateTime.UtcNow, true);
                SaveState(st);
            }
            catch (Exception ex) { AppLog.Write("diagnostics: " + ex.GetType().Name); }
        }

        public static void SetConsent(string mode)
        {
            var st = GetState();
            st.Consent = mode;
            st.TextVersion = Diagnostics.ConsentTextVersion;
            st.ConsentAt = DateTime.UtcNow.ToString("o");
            SaveState(st);
            AppLog.Write("diagnostics: consent " + mode);
        }

        /// <summary>After the window is shown: the question (once), then the automatic check now and every half an hour.</summary>
        public static void Schedule(Window owner)
        {
            if (AppInstance.Prefix != "") return;          // (Pack Studio is built from the same sources: it never asks and never sends)
            var first = new DispatcherTimer { Interval = TimeSpan.FromSeconds(40) };
            first.Tick += (_, __) =>
            {
                first.Stop();
                try
                {
                    var st = GetState();
                    bool ask = !_asked && st.Consent != "none" && (st.Consent == "unknown" || st.TextVersion != Diagnostics.ConsentTextVersion);
                    if (ask && owner.IsVisible) { _asked = true; new DiagDialog(owner, firstTime: true).ShowDialog(); }
                }
                catch (Exception ex) { AppLog.Write("diagnostics: " + ex.GetType().Name); }
                _ = Task.Run(AutoCheck);
                _timer = new DispatcherTimer { Interval = TimeSpan.FromMinutes(30) };
                _timer.Tick += (_, ___) => { _ = Task.Run(AutoCheck); };
                _timer.Start();
            };
            first.Start();
        }
    }

    /// <summary>The question about the diagnostics (first time, then File ▸ Diagnostica…): the mode, what is sent, «Invia ora».</summary>
    public sealed class DiagDialog : ThemedDialog
    {
        public DiagDialog(Window owner, bool firstTime) : base(L.T("Diagnostica e miglioramento di Simpler"), 560)
        {
            Owner = owner;
            var st = DiagService.GetState();
            var sp = new StackPanel();
            var intro = Theme.Label(L.T("Se qualcosa non funziona (un blocco, una schermata rossa che non finisce, un errore), Simpler può mandare all'autore un rapporto tecnico per correggerlo. Contiene solo le righe di problema del registro, senza nomi, cartelle, email, immagini né contenuti dei tuoi progetti, più la versione di Simpler, di Windows e la scheda video. Puoi cambiare scelta quando vuoi da File ▸ Diagnostica."), 13, Theme.TextSoft);
            intro.TextWrapping = TextWrapping.Wrap;
            sp.Children.Add(intro);

            sp.Children.Add(new Border { Height = 14 });
            sp.Children.Add(Theme.Caption(L.T("Invio")));
            var seg = Theme.Segmented(out var buttons,
                (L.T("Automatico"), L.T("I problemi gravi, da solo, al massimo una volta al giorno; e una volta per versione il tipo di computer")),
                (L.T("Solo quando decido io"), L.T("Non parte nulla da solo: usi il pulsante «Invia ora»")),
                (L.T("Non inviare"), L.T("Nulla lascia il tuo computer")));
            seg.HorizontalAlignment = HorizontalAlignment.Left;
            seg.Margin = new Thickness(0, 8, 0, 4);
            string[] modes = { "auto", "manual", "none" };
            var sel = Array.IndexOf(modes, st.Consent);
            // (16/11) the first question starts on «Solo quando decido io», not on «Automatico»: nothing leaves the computer by itself
            // unless the user chooses it (a consent must not be chosen for him)
            if (sel < 0) sel = 1;
            Theme.SetSegment(buttons, sel);
            var hint = Theme.Label("", 12, Theme.TextFaint);
            hint.TextWrapping = TextWrapping.Wrap;
            hint.Margin = new Thickness(0, 4, 0, 0);
            void Hint(int i) => hint.Text = i switch
            {
                0 => L.T("Quando succede un problema grave (un blocco, un errore, un arresto di Simpler) il rapporto parte da solo, in silenzio. Mai più di uno al giorno. In più, una sola volta per ogni versione, Simpler comunica la versione di Simpler e di Windows, la lingua, la memoria e la scheda video con il suo voto: serve a sapere su quali computer funziona bene."),
                1 => L.T("Non parte nulla da solo. Se vuoi segnalare un problema, premi «Invia ora»."),
                _ => L.T("Nulla lascia il tuo computer."),
            };
            Hint(sel);
            int chosen = sel;
            for (int i = 0; i < buttons.Count; i++)
            {
                var idx = i;
                buttons[i].Click += (_, __) => { chosen = idx; Theme.SetSegment(buttons, idx); Hint(idx); };
            }
            sp.Children.Add(seg);
            sp.Children.Add(hint);

            // what is sent, as it is
            var preview = new TextBox
            {
                IsReadOnly = true, TextWrapping = TextWrapping.Wrap, FontFamily = Theme.Mono, FontSize = 11,
                Height = 200, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Visibility = Visibility.Collapsed, Margin = new Thickness(0, 10, 0, 0),
                Background = Theme.B(Theme.Inset), Foreground = Theme.B(Theme.TextSoft), BorderBrush = Theme.B(Theme.Line),
            };
            var see = Theme.Button(L.T("Vedi cosa viene inviato"), Theme.Kind.Ghost);
            see.HorizontalAlignment = HorizontalAlignment.Left;
            see.Margin = new Thickness(0, 12, 0, 0);
            see.Click += (_, __) =>
            {
                if (preview.Visibility == Visibility.Visible) { preview.Visibility = Visibility.Collapsed; return; }
                try { var r = DiagService.Build(st, null); preview.Text = Diagnostics.ToJson(r); } catch (Exception ex) { preview.Text = ex.Message; }
                preview.Visibility = Visibility.Visible;
            };
            sp.Children.Add(see);
            sp.Children.Add(preview);

            var status = Theme.Label("", 12, Theme.TextFaint);
            status.TextWrapping = TextWrapping.Wrap;
            status.Margin = new Thickness(0, 10, 0, 0);
            sp.Children.Add(status);

            var row = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 16, 0, 0) };
            var send = Theme.Button(L.T("Invia ora"), Theme.Kind.Normal);
            send.Margin = new Thickness(0, 0, 8, 0);
            send.Click += async (_, __) =>
            {
                send.IsEnabled = false;
                status.Text = L.T("Invio in corso…");
                var ok = await DiagService.SendNow();
                status.Text = ok ? L.T("Inviato. Grazie!") : L.T("Invio non riuscito: controlla la connessione e riprova.");
                send.IsEnabled = true;
            };
            var save = Theme.Button(firstTime ? L.T("Conferma") : L.T("Salva"), Theme.Kind.Primary);
            save.Click += (_, __) => { DiagService.SetConsent(modes[chosen]); Close(); };
            row.Children.Add(send);
            row.Children.Add(save);
            sp.Children.Add(row);
            Body.Children.Add(sp);
        }

        protected override void OnCloseButton()
        {
            // (the × on the first question: no answer = asked again next time, nothing is sent)
            Close();
        }
    }
}
