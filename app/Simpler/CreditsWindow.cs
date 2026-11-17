using System;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;

namespace Simpler
{
    /// <summary>
    /// File ▸ Licenze e crediti: the programs, libraries, services and content of other authors that Simpler uses,
    /// with their licenses and the names mentioned (credits/Crediti.md, credits/en/Credits.md - kept up to date with
    /// every version that adds one). A small reader of that Markdown: headings, bullets, links that open in the browser.
    /// </summary>
    public sealed class CreditsWindow : ThemedDialog
    {
        public CreditsWindow(Window owner) : base(L.T("Licenze e crediti"), 760)
        {
            Owner = owner;
            _keepCentred = true;
            // (1.75.28) the license agreement accepted at the first start, to read it again
            var eula = Theme.Button(L.T("Contratto di licenza"), Theme.Kind.Normal, L.T("Il contratto accettato al primo avvio"));
            eula.HorizontalAlignment = HorizontalAlignment.Left;
            eula.Margin = new Thickness(0, 0, 0, 8);
            eula.Click += (_, __) => new LicenseWindow(this, readOnly: true).ShowDialog();
            Body.Children.Add(eula);
            Fill(Body, Load("Crediti.md", "Credits.md"), L.T("Il file delle licenze non è stato trovato."));
            EnableBodyScroll();
            MaxHeight = SystemParameters.WorkArea.Height * 0.9;
        }

        /// <summary>The small Markdown reader: headings, bullets, links that open in the browser.</summary>
        internal static void Fill(Panel body, string? text, string missing)
        {
            if (text == null) { body.Children.Add(Theme.Label(missing, 13, Theme.TextFaint)); return; }
            foreach (var raw in text.Replace("\r", "").Split('\n'))
            {
                var line = raw.TrimEnd();
                if (line == "") continue;
                if (line.StartsWith("# ")) body.Children.Add(Block(line[2..], 19, Theme.Text, FontWeights.SemiBold, new Thickness(0, 4, 0, 8)));
                else if (line.StartsWith("## ")) body.Children.Add(Block(line[3..], 15, Theme.Accent, FontWeights.SemiBold, new Thickness(0, 16, 0, 6)));
                else if (line.StartsWith("### ")) body.Children.Add(Block(line[4..], 13.5, Theme.Text, FontWeights.SemiBold, new Thickness(0, 10, 0, 3)));
                else if (line.StartsWith("- ")) body.Children.Add(Block("•  " + line[2..], 12.5, Theme.TextSoft, FontWeights.Normal, new Thickness(8, 1, 0, 1)));
                else body.Children.Add(Block(line, 12.5, Theme.TextSoft, FontWeights.Normal, new Thickness(0, 2, 0, 4)));
            }
        }

        /// <summary>A file of the «credits» folder in the language of the app (English in credits/en).</summary>
        internal static string? Load(string itName, string enName) => Load(itName, enName, L.Lang == "en");

        internal static string? Load(string itName, string enName, bool english)
        {
            for (var dir = new DirectoryInfo(AppContext.BaseDirectory); dir != null; dir = dir.Parent)
            {
                var folder = Path.Combine(dir.FullName, "credits");
                if (!Directory.Exists(folder)) continue;
                var en = Path.Combine(folder, "en", enName);
                var it = Path.Combine(folder, itName);
                var file = english && File.Exists(en) ? en : it;
                return File.Exists(file) ? File.ReadAllText(file, Encoding.UTF8) : null;
            }
            return null;
        }

        static readonly Regex Url = new(@"https?://[^\s)»]+", RegexOptions.Compiled);

        static TextBlock Block(string text, double size, Color color, FontWeight weight, Thickness margin)
        {
            var tb = new TextBlock { FontSize = size, Foreground = Theme.B(color), FontWeight = weight, Margin = margin, TextWrapping = TextWrapping.Wrap };
            int at = 0;
            foreach (Match m in Url.Matches(text))
            {
                if (m.Index > at) tb.Inlines.Add(new Run(text[at..m.Index]));
                var link = new Hyperlink(new Run(m.Value)) { Foreground = Theme.B(Theme.Accent), NavigateUri = new Uri(m.Value) };
                link.RequestNavigate += (_, e) =>
                {
                    try { System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(e.Uri.AbsoluteUri) { UseShellExecute = true }); } catch { }
                    e.Handled = true;
                };
                tb.Inlines.Add(link);
                at = m.Index + m.Length;
            }
            if (at < text.Length) tb.Inlines.Add(new Run(text[at..]));
            return tb;
        }
    }
}
