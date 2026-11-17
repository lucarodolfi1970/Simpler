using System;
using System.Windows;
using System.Windows.Controls;

namespace Simpler
{
    /// <summary>
    /// (1.75.28) The license agreement (credits/Licenza.md, credits/en/License.md). At the first start - and again only
    /// when the agreement changes (Version) - it must be accepted before Simpler starts: two boxes, the agreement and
    /// the specific approval of the onerous clauses (articles 1341 and 1342 of the Italian Civil Code), then «Accetto».
    /// «Non accetto» or the × close Simpler. From File ▸ Licenze e crediti it opens to be read again (readOnly).
    /// </summary>
    public sealed class LicenseWindow : ThemedDialog
    {
        /// <summary>The version of the agreement: a new one is asked again at the next start.</summary>
        public const string Version = "2.0";

        /// <summary>True when the current agreement has been accepted on this computer.</summary>
        public static bool Accepted()
        {
            var a = Settings.Load().LicenseAccepted ?? "";
            if (a.Split('|')[0] == Version) return true;
            // (1.79.0) accepted in the setup, which shows the agreement and the specific approval: it leaves
            // license-accepted.txt («version|date|setup …») next to settings.json, taken here as the acceptance
            try
            {
                var f = System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Simpler", "license-accepted.txt");
                if (!System.IO.File.Exists(f)) return false;
                var p = System.IO.File.ReadAllText(f).Trim().Split('|');
                if (p[0] != Version) return false;
                var s = Settings.Load();
                s.LicenseAccepted = Version + "|" + (p.Length > 1 && p[1] != "" ? p[1] : DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"));
                s.Save();
                AppLog.Write("license " + Version + " accepted in the setup");
                return true;
            }
            catch { return false; }
        }

        /// <summary>At the start: the agreement if not accepted yet. False = not accepted, Simpler must not start.</summary>
        public static bool EnsureAccepted()
        {
            if (Accepted()) return true;
            var w = new LicenseWindow(null, readOnly: false);
            var ok = w.ShowDialog() == true;
            if (ok)
            {
                var s = Settings.Load();
                s.LicenseAccepted = Version + "|" + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss");
                s.Save();
                AppLog.Write("license " + Version + " accepted");
            }
            else AppLog.Write("license " + Version + " not accepted: Simpler closes");
            return ok;
        }

        readonly bool _readOnly;

        public LicenseWindow(Window? owner, bool readOnly) : base(L.T("Contratto di licenza"), 760)
        {
            _readOnly = readOnly;
            if (owner != null) Owner = owner;
            else { WindowStartupLocation = WindowStartupLocation.CenterScreen; ShowInTaskbar = true; Topmost = true; }
            _keepCentred = true;
            // (1.75.30) both languages: Italiano | English above the text (the Italian one prevails, point 16);
            // (1.75.31) the boxes and buttons at the bottom follow the language chosen there too
            var lang = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(22, 0, 22, 6) };
            var it = Theme.Button("Italiano", Theme.Kind.Ghost);
            var en = Theme.Button("English", Theme.Kind.Ghost);
            it.Margin = new Thickness(0, 0, 6, 0);
            lang.Children.Add(it);
            lang.Children.Add(en);
            AddAboveBody(lang);

            var acceptedTb = new TextBlock { FontSize = 12, Foreground = Theme.B(Theme.TextFaint), TextWrapping = TextWrapping.Wrap };
            var allTb = new TextBlock { TextWrapping = TextWrapping.Wrap };
            var specificTb = new TextBlock { TextWrapping = TextWrapping.Wrap };
            var all = new CheckBox { Content = allTb, Foreground = Theme.B(Theme.TextSoft), Margin = new Thickness(0, 10, 0, 6) };
            var specific = new CheckBox { Content = specificTb, Foreground = Theme.B(Theme.TextSoft), Margin = new Thickness(0, 0, 0, 12) };
            var no = Theme.Button("", Theme.Kind.Normal);
            var yes = Theme.Button("", Theme.Kind.Primary);
            var close = Theme.Button("", Theme.Kind.Normal);
            var acceptedParts = (Settings.Load().LicenseAccepted ?? "").Split('|');

            void Show(bool english)
            {
                string T(string itText, string enText) => english ? enText : itText;
                Body.Children.Clear();
                CreditsWindow.Fill(Body, CreditsWindow.Load("Licenza.md", "License.md", english),
                    T("Il file del contratto di licenza non è stato trovato.", "The license agreement file was not found."));
                Theme.Style(it, english ? Theme.Kind.Ghost : Theme.Kind.Segment);
                Theme.Style(en, english ? Theme.Kind.Segment : Theme.Kind.Ghost);
                Title = T("Contratto di licenza", "License agreement");
                if (acceptedParts.Length > 1)
                    acceptedTb.Text = english ? $"Accepted on {acceptedParts[1]} (agreement version {acceptedParts[0]})"
                                              : $"Accettato il {acceptedParts[1]} (versione {acceptedParts[0]} del contratto)";
                close.Content = T("Chiudi", "Close");
                allTb.Text = T("Ho letto il contratto di licenza e lo accetto.", "I have read the license agreement and I accept it.");
                specificTb.Text = T("Ai sensi degli articoli 1341 e 1342 del Codice civile approvo specificamente le clausole 4 (nome, logo e uso corretto), 6 (contenuti di Simpler), 9 (esclusione di garanzia), 10 (limitazione di responsabilità), 11 (manleva), 12 (aggiornamenti e modifiche), 13 (risoluzione di diritto) e 15 (legge applicabile e foro competente).",
                                    "Under articles 1341 and 1342 of the Italian Civil Code I specifically approve clauses 4 (name, logo and fair use), 6 (Simpler content), 9 (disclaimer of warranty), 10 (limitation of liability), 11 (indemnity), 12 (updates and changes), 13 (termination by operation of law) and 15 (governing law and jurisdiction).");
                no.Content = T("Non accetto", "I do not accept");
                no.ToolTip = T("Simpler si chiude", "Simpler closes");
                yes.Content = T("Accetto", "I accept");
                if (Body.Parent is ScrollViewer sv) sv.ScrollToTop();
            }
            it.Click += (_, __) => Show(false);
            en.Click += (_, __) => Show(true);

            if (readOnly)
            {
                if (acceptedParts.Length > 1) Footer.Children.Add(acceptedTb);
                close.HorizontalAlignment = HorizontalAlignment.Right;
                close.Margin = new Thickness(0, 8, 0, 0);
                close.Click += (_, __) => Close();
                Footer.Children.Add(close);
            }
            else
            {
                var row = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right };
                no.Margin = new Thickness(0, 0, 8, 0);
                no.Click += (_, __) => { DialogResult = false; };
                yes.IsEnabled = false;
                yes.Click += (_, __) => { DialogResult = true; };
                void Update() => yes.IsEnabled = all.IsChecked == true && specific.IsChecked == true;
                all.Checked += (_, __) => Update(); all.Unchecked += (_, __) => Update();
                specific.Checked += (_, __) => Update(); specific.Unchecked += (_, __) => Update();
                row.Children.Add(no);
                row.Children.Add(yes);
                Footer.Children.Add(all);
                Footer.Children.Add(specific);
                Footer.Children.Add(row);
            }
            Show(L.Lang == "en");
            EnableBodyScroll();
            MaxHeight = SystemParameters.WorkArea.Height * 0.9;
            Height = Math.Min(SystemParameters.WorkArea.Height * 0.9, 820);
            SizeToContent = SizeToContent.Manual;
        }

        protected override void OnCloseButton()
        {
            if (_readOnly) Close();
            else DialogResult = false;          // (the × at the first start: not accepted)
        }
    }
}
