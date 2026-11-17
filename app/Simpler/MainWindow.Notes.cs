using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace Simpler
{
    /// <summary>"What's new" shown in the right sidebar (not a separate window), closed with a small ×.</summary>
    public sealed partial class MainWindow
    {
        string _notesVersion = "";
        static readonly Geometry CloseIcon = Geometry.Parse("M6 6l12 12 M18 6 6 18");

        async Task ShowNotesPanel(string? version = null)
        {
            _notesVersion = version ?? SettingsDialog.Version;
            await ShowRightPanel("notes");
        }

        // ---- short summary of every version (release-notes/summaries.json: icon, it, en)
        static Dictionary<string, (string icon, string it, string en)>? _summaries;
        static Dictionary<string, (string icon, string it, string en)> Summaries()
        {
            if (_summaries != null) return _summaries;
            _summaries = new();
            try
            {
                var folder = SettingsDialog.NotesFolderPath();
                var file = folder != null ? Path.Combine(folder, "summaries.json") : null;
                if (file != null && File.Exists(file) && System.Text.Json.Nodes.JsonNode.Parse(File.ReadAllText(file, Encoding.UTF8)) is System.Text.Json.Nodes.JsonObject o)
                    foreach (var (k, v) in o)
                        if (v is System.Text.Json.Nodes.JsonObject s)
                            _summaries[k] = ((string?)s["icon"] ?? "", (string?)s["it"] ?? "", (string?)s["en"] ?? "");
            }
            catch { }
            return _summaries;
        }

        static string SummaryOf(string version) => Summaries().TryGetValue(version, out var s) ? (L.Lang == "en" ? s.en : s.it) : "";

        static (Geometry icon, Color color) ThemeIcon(string version)
        {
            var id = Summaries().TryGetValue(version, out var s) ? s.icon : "";
            return id switch
            {
                "material" => (Icons.MatStandard, Theme.C("#C9D3E4")),
                "water" => (Icons.WaterDrop, Theme.C("#4FB6E8")),
                "light" => (Icons.Light, Theme.C("#F2C877")),
                "ambience" => (Icons.Globe, Theme.C("#7FC8F8")),
                "render" => (Icons.Camera, Theme.C("#F2B54B")),
                "view" => (Icons.Eye, Theme.C("#8FB8FF")),
                "library" => (Icons.Folder, Theme.C("#F2B54B")),
                "scatter" => (Icons.Brush, Theme.C("#6FD66F")),
                "import" => (Icons.Import, Theme.C("#B49CFF")),
                "performance" => (Icons.Bolt, Theme.C("#F2E05B")),
                "fix" => (Icons.Wrench, Theme.C("#FF9B8F")),
                "scene" => (Icons.Save, Theme.C("#9DAAC2")),
                "navigation" => (Icons.Walk, Theme.C("#5FC7B5")),
                _ => (Icons.Sliders, Theme.C("#9DAAC2")),
            };
        }

        static Border NotesBadge(string version, double size)
        {
            var (ic, col) = ThemeIcon(version);
            return new Border
            {
                Width = size, Height = size, CornerRadius = new CornerRadius(size * 0.27), VerticalAlignment = VerticalAlignment.Top,
                Background = new SolidColorBrush(Color.FromArgb(0x30, col.R, col.G, col.B)),
                Child = Theme.Icon(ic, col, size * 0.58),
            };
        }

        static string DateOf(string version)
        {
            var f = SettingsDialog.NotesFile(version);
            if (f == null) return "";
            try { return SplitTitle(File.ReadLines(f, Encoding.UTF8).FirstOrDefault() ?? "", version).date; } catch { return ""; }
        }

        /// <summary>The news go away as soon as the user does something else (a click outside them, in the view, in the
        /// tree, in the library…): no need to look for the ×.</summary>
        void CloseNotesOnUse()
        {
            if (_rightPanel == "notes") _ = ShowRightPanel("");
        }

        void HookNotesAutoClose()
        {
            PreviewMouseDown += (_, e) =>
            {
                if (_rightPanel != "notes") return;
                var area = (DependencyObject?)(_props.Parent as FrameworkElement) ?? _props;
                for (var d = e.OriginalSource as DependencyObject; d != null;
                     d = d is Visual || d is System.Windows.Media.Media3D.Visual3D ? VisualTreeHelper.GetParent(d) : LogicalTreeHelper.GetParent(d))
                    if (d == area || (d != null && d == _notesButton)) return;   // (the ? button opens and closes them itself)
                CloseNotesOnUse();
            };
        }

        Button? _notesButton;    // the ? of the header
        bool _notesAll;          // the whole text of the version is open (otherwise its first lines)
        // (1.76.62, Luca: «una casella di ricerca con vicino un tastino con la lente … l'elenco delle release con il pezzo
        // di frase che contiene il testo evidenziato in arancione, se clicca va a quella nota») the words looked for, the
        // results shown (else the version), the words to light up in the version opened from a result
        string _notesQuery = "";
        bool _notesResults;
        string _notesMark = "";
        static readonly Color NotesMarkColor = Theme.C("#F08A24");

        /// <summary>The search box at the top of the news, with its lens (Enter does the same).</summary>
        FrameworkElement NotesSearchBox()
        {
            var row = new DockPanel { Margin = new Thickness(0, 0, 0, 0) };
            var go = Theme.Button(Theme.Icon(Icons.Search, Theme.TextSoft, 15), Theme.Kind.Normal, L.T("Cerca nelle note di tutte le versioni"));
            go.MinHeight = 32; go.Width = 36; go.Padding = new Thickness(0); go.Margin = new Thickness(6, 0, 0, 0);
            DockPanel.SetDock(go, Dock.Right);
            row.Children.Add(go);
            if (_notesResults || _notesMark != "")
            {
                var clear = Theme.Button(Theme.Icon(CloseIcon, Theme.TextMuted, 12, 1.8), Theme.Kind.Ghost, L.T("Togli la ricerca"));
                clear.MinHeight = 32; clear.Width = 30; clear.Padding = new Thickness(0); clear.Margin = new Thickness(4, 0, 0, 0);
                clear.Click += (_, __) => { _notesQuery = ""; _notesResults = false; _notesMark = ""; RenderProps(); };
                DockPanel.SetDock(clear, Dock.Right);
                row.Children.Add(clear);
            }
            var box = new TextBox
            {
                Text = _notesQuery, FontSize = 13, MinHeight = 32, VerticalContentAlignment = VerticalAlignment.Center, Padding = new Thickness(8, 0, 8, 0),
                Background = Theme.B(Theme.Inset), Foreground = Theme.B(Theme.Text), CaretBrush = Theme.B(Theme.Text),
                BorderBrush = Theme.B(Theme.Line), BorderThickness = new Thickness(1),
                ToolTip = L.T("Cerca una parola o una frase nelle note di tutte le versioni: l'elenco mostra dove compare, evidenziata; un clic apre quella nota"),
            };
            void Search()
            {
                _notesQuery = box.Text.Trim();
                _notesResults = _notesQuery.Length >= 2;
                _notesMark = "";
                RenderProps();
            }
            box.KeyDown += (_, e) => { if (e.Key == System.Windows.Input.Key.Enter) { e.Handled = true; Search(); } };
            go.Click += (_, __) => Search();
            row.Children.Add(box);
            if (_notesResults) box.Loaded += (_, __) => { box.Focus(); box.CaretIndex = box.Text.Length; };
            return row;
        }

        /// <summary>A text with every occurrence of the words looked for in bold orange.</summary>
        static TextBlock Marked(string text, string mark, double size, Color color)
        {
            var tb = new TextBlock { TextWrapping = TextWrapping.Wrap, FontSize = size, Foreground = Theme.B(color), LineHeight = size + 6 };
            int i = 0;
            while (mark != "" && i < text.Length)
            {
                int k = text.IndexOf(mark, i, StringComparison.CurrentCultureIgnoreCase);
                if (k < 0) break;
                if (k > i) tb.Inlines.Add(new System.Windows.Documents.Run(text[i..k]));
                tb.Inlines.Add(new System.Windows.Documents.Run(text.Substring(k, mark.Length)) { Foreground = Theme.B(NotesMarkColor), FontWeight = FontWeights.SemiBold });
                i = k + mark.Length;
            }
            if (i < text.Length) tb.Inlines.Add(new System.Windows.Documents.Run(text[i..]));
            return tb;
        }

        /// <summary>The results: every version whose notes contain the words, newest first, with the pieces of sentence
        /// around them (at most three per version); a click opens that version with the words lit up.</summary>
        void RenderNotesResults(List<string> versions)
        {
            var list = new StackPanel();
            int found = 0;
            foreach (var v in versions)
            {
                var f = SettingsDialog.NotesFile(v);
                if (f == null) continue;
                string body;
                try { body = LanguagePart(File.ReadAllText(f, Encoding.UTF8)); } catch { continue; }
                var lines = Parse(body).SelectMany(sec => sec.Lines.Select(l => l.text)).ToList();
                var sum = SummaryOf(v);
                if (sum != "") lines.Insert(0, sum);
                var hits = lines.Where(l => l.IndexOf(_notesQuery, StringComparison.CurrentCultureIgnoreCase) >= 0).Take(3).ToList();
                if (hits.Count == 0) continue;
                found++;
                var item = new StackPanel();
                var top = new DockPanel { Margin = new Thickness(0, 0, 0, 4) };
                var bd = NotesBadge(v, 22); bd.Margin = new Thickness(0, 0, 8, 0);
                DockPanel.SetDock(bd, Dock.Left);
                top.Children.Add(bd);
                top.Children.Add(new TextBlock { Text = "Simpler " + v + "  ·  " + DateOf(v), FontSize = 12.5, FontWeight = FontWeights.SemiBold, Foreground = Theme.B(Theme.Text), VerticalAlignment = VerticalAlignment.Center });
                item.Children.Add(top);
                foreach (var h in hits)
                {
                    int k = h.IndexOf(_notesQuery, StringComparison.CurrentCultureIgnoreCase);
                    int a = Math.Max(0, k - 70), b = Math.Min(h.Length, k + _notesQuery.Length + 90);
                    var piece = (a > 0 ? "…" : "") + h[a..b].Trim() + (b < h.Length ? "…" : "");
                    var tb = Marked(piece, _notesQuery, 12.5, Theme.TextSoft);
                    tb.Margin = new Thickness(30, 0, 0, 4);
                    item.Children.Add(tb);
                }
                var btn = new Button { Content = item, HorizontalContentAlignment = HorizontalAlignment.Stretch, Cursor = System.Windows.Input.Cursors.Hand,
                                       ToolTip = L.T("Apri questa nota"), FocusVisualStyle = null };
                Theme.Style(btn, Theme.Kind.Ghost);
                btn.Padding = new Thickness(8, 6, 8, 6); btn.Margin = new Thickness(-8, 0, -8, 4);
                btn.HorizontalContentAlignment = HorizontalAlignment.Stretch;
                btn.VerticalContentAlignment = VerticalAlignment.Top;
                var ver = v;
                btn.Click += async (_, __) => { _notesMark = _notesQuery; _notesResults = false; _notesAll = true; await ShowNotesPanel(ver); };
                list.Children.Add(btn);
            }
            var head = Theme.Caption(found == 0 ? L.F("Nessuna versione contiene «{0}»", _notesQuery) : L.F("«{0}» in {1} versioni", _notesQuery, found));
            head.Margin = new Thickness(0, 0, 0, 8);
            list.Children.Insert(0, head);
            _props.Children.Add(Theme.Card(list, 16));
        }

        void RenderNotesPanel()
        {
            var versions = SettingsDialog.NotesVersions();
            _props.Children.Add(Theme.Card(NotesSearchBox(), 12));
            if (_notesResults)
            {
                RenderNotesResults(versions);
                return;
            }
            var file = SettingsDialog.NotesFile(_notesVersion);
            var text = file != null ? File.ReadAllText(file, Encoding.UTF8) : "";
            var shown = file != null ? Path.GetFileNameWithoutExtension(file).Replace("Simpler-", "") : _notesVersion;

            // ---- header: "Novità", the version picker (a drop-down list with icon, number and summary) and ×
            var head = new DockPanel();
            var close = new Button
            {
                Content = Theme.Icon(CloseIcon, Theme.TextMuted, 14, 1.8), Width = 26, Height = 26, Padding = new Thickness(0),
                Background = Brushes.Transparent, BorderThickness = new Thickness(0), Cursor = System.Windows.Input.Cursors.Hand,
                ToolTip = L.T("Chiudi"), VerticalAlignment = VerticalAlignment.Top, FocusVisualStyle = null,
            };
            close.Template = CloseTemplate();
            close.Click += async (_, __) => await ShowRightPanel("");
            DockPanel.SetDock(close, Dock.Right);
            head.Children.Add(close);
            var titles = new StackPanel();
            titles.Children.Add(Theme.Caption(L.T("Novità")));

            var face = new DockPanel { LastChildFill = true };
            var chev = Theme.Icon(Icons.ChevronDown, Theme.TextMuted, 14);
            chev.Margin = new Thickness(10, 0, 0, 0); chev.VerticalAlignment = VerticalAlignment.Center;
            DockPanel.SetDock(chev, Dock.Right);
            face.Children.Add(chev);
            var fb = NotesBadge(shown, 26); fb.VerticalAlignment = VerticalAlignment.Center;
            DockPanel.SetDock(fb, Dock.Left);
            face.Children.Add(fb);
            var ft = new StackPanel { Margin = new Thickness(10, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center };
            ft.Children.Add(new TextBlock { Text = "Simpler " + shown, FontSize = 16, FontWeight = FontWeights.SemiBold, Foreground = Theme.B(Theme.Text) });
            var (_, date) = SplitTitle(text, shown);
            if (date != "") ft.Children.Add(new TextBlock { Text = date + (shown == SettingsDialog.Version ? " · " + L.T("questa versione") : ""), FontSize = 11.5, Foreground = Theme.B(Theme.TextFaint) });
            face.Children.Add(ft);
            var picker = Theme.Button(face, Theme.Kind.Normal, L.T("Scegli la versione"));
            picker.HorizontalContentAlignment = HorizontalAlignment.Stretch;
            picker.MinHeight = 46; picker.Padding = new Thickness(8, 4, 10, 4); picker.Margin = new Thickness(0, 8, 8, 0);
            picker.Click += (_, __) =>
            {
                var cm = new ContextMenu { PlacementTarget = picker, Placement = System.Windows.Controls.Primitives.PlacementMode.Bottom, MaxHeight = 560 };
                foreach (var v in versions)
                {
                    var row = new DockPanel { Margin = new Thickness(0, 3, 0, 3), Width = 300 };
                    var bd = NotesBadge(v, 28); bd.Margin = new Thickness(0, 0, 10, 0);
                    DockPanel.SetDock(bd, Dock.Left);
                    row.Children.Add(bd);
                    var tx = new StackPanel();
                    tx.Children.Add(new TextBlock { Text = v + (v == shown ? "  ✓" : ""), FontSize = 12.5, FontWeight = FontWeights.SemiBold, Foreground = Theme.B(Theme.Text) });
                    var sum = SummaryOf(v);
                    if (sum != "") tx.Children.Add(new TextBlock { Text = sum, FontSize = 11.5, Foreground = Theme.B(Theme.TextFaint), TextWrapping = TextWrapping.Wrap, MaxHeight = 32, TextTrimming = TextTrimming.CharacterEllipsis });
                    row.Children.Add(tx);
                    var mi = new MenuItem { Header = row };
                    var ver = v;
                    mi.Click += async (_, __) => { _notesAll = false; await ShowNotesPanel(ver); };
                    cm.Items.Add(mi);
                }
                cm.IsOpen = true;
            };
            titles.Children.Add(picker);
            head.Children.Add(titles);
            _props.Children.Add(Theme.Card(head, 16));

            if (file == null)
            {
                _props.Children.Add(Theme.Card(Para(L.T("Note di rilascio non trovate."), Theme.TextFaint), 16));
                return;
            }

            // ---- in short: icon of the main theme and two or three lines
            var summary = SummaryOf(shown);
            if (summary != "")
            {
                var sd = new DockPanel();
                var sb = NotesBadge(shown, 40); sb.Margin = new Thickness(0, 2, 12, 0);
                DockPanel.SetDock(sb, Dock.Left);
                sd.Children.Add(sb);
                sd.Children.Add(new TextBlock { Text = summary, TextWrapping = TextWrapping.Wrap, FontSize = 13.5, Foreground = Theme.B(Theme.Text), LineHeight = 20 });
                _props.Children.Add(Theme.Card(sd, 16));
            }

            // ---- the detail: the first lines, then "Mostra tutto" opens the whole text of the version
            const int Preview = 4;
            var sections = Parse(LanguagePart(text));
            TextBlock? firstMark = null;      // (the first line with the words looked for: brought into view)
            int shownLines = 0, total = sections.Sum(s => s.Lines.Count);
            var detail = new StackPanel();
            foreach (var section in sections)
            {
                if (!_notesAll && shownLines >= Preview) break;
                if (section.Title != "")
                {
                    var st = SectionTitle(section.Title);
                    st.DataContext = (Icons.File, Theme.Accent);       // (titles of the notes: one icon for all)
                    detail.Children.Add(st);
                }
                for (int li = 0; li < section.Lines.Count; li++)
                {
                    if (!_notesAll && shownLines >= Preview) break;
                    shownLines++;
                    var (bullet, line) = section.Lines[li];
                    if (!bullet)
                    {
                        bool sub = li + 1 < section.Lines.Count && section.Lines[li + 1].bullet && line.Length < 100;
                        var pb = Para(line, sub ? Theme.Text : Theme.TextSoft);
                        if (_notesMark != "" && line.IndexOf(_notesMark, StringComparison.CurrentCultureIgnoreCase) >= 0)
                        {
                            pb = Marked(line, _notesMark, 13, sub ? Theme.Text : Theme.TextSoft);
                            pb.Margin = new Thickness(0, 0, 0, 8);
                            firstMark ??= pb;
                        }
                        if (sub) { pb.FontWeight = FontWeights.SemiBold; pb.Margin = new Thickness(0, li == 0 ? 0 : 8, 0, 8); }
                        detail.Children.Add(pb);
                        continue;
                    }
                    var row = new DockPanel { Margin = new Thickness(0, 0, 0, 8) };
                    var dot = new Border { Width = 5, Height = 5, CornerRadius = new CornerRadius(3), Background = Theme.B(Theme.Accent), Margin = new Thickness(2, 7, 10, 0), VerticalAlignment = VerticalAlignment.Top };
                    DockPanel.SetDock(dot, Dock.Left);
                    row.Children.Add(dot);
                    var ltb = _notesMark != "" && line.IndexOf(_notesMark, StringComparison.CurrentCultureIgnoreCase) >= 0
                        ? Marked(line, _notesMark, 13, Theme.TextSoft)
                        : new TextBlock { Text = line, TextWrapping = TextWrapping.Wrap, FontSize = 13, Foreground = Theme.B(Theme.TextSoft), LineHeight = 19 };
                    if (ltb.Inlines.Count > 1) firstMark ??= ltb;
                    row.Children.Add(ltb);
                    detail.Children.Add(row);
                }
            }
            if (total > Preview)
            {
                var more = Theme.Button(Theme.IconText(_notesAll ? Icons.Chevron : Icons.ChevronDown,
                                                       _notesAll ? L.T("Mostra meno") : L.F("Mostra tutto ({0} punti)", total), Theme.Accent, 13),
                                        Theme.Kind.Ghost, null);
                more.HorizontalAlignment = HorizontalAlignment.Left; more.MinHeight = 28; more.Margin = new Thickness(-8, 2, 0, 0);
                more.Click += (_, __) => { _notesAll = !_notesAll; RenderProps(); };
                detail.Children.Add(more);
            }
            _props.Children.Add(Theme.Card(detail, 16));
            if (firstMark != null)
                firstMark.Loaded += (_, __) => Dispatcher.BeginInvoke(new Action(() => firstMark.BringIntoView()), System.Windows.Threading.DispatcherPriority.Background);
        }

        static ControlTemplate CloseTemplate()
        {
            // round hover background, no Windows chrome
            var t = new ControlTemplate(typeof(Button));
            var bd = new FrameworkElementFactory(typeof(Border), "Bd");
            bd.SetValue(Border.CornerRadiusProperty, new CornerRadius(13));
            bd.SetValue(Border.BackgroundProperty, Brushes.Transparent);
            var cp = new FrameworkElementFactory(typeof(ContentPresenter));
            cp.SetValue(HorizontalAlignmentProperty, HorizontalAlignment.Center);
            cp.SetValue(VerticalAlignmentProperty, VerticalAlignment.Center);
            bd.AppendChild(cp);
            t.VisualTree = bd;
            var hover = new Trigger { Property = UIElement.IsMouseOverProperty, Value = true };
            hover.Setters.Add(new Setter(Border.BackgroundProperty, Theme.B(Theme.Raised), "Bd"));
            t.Triggers.Add(hover);
            return t;
        }

        static TextBlock Para(string text, Color color)
            => new TextBlock { Text = text, TextWrapping = TextWrapping.Wrap, FontSize = 13, Foreground = Theme.B(color), LineHeight = 19, Margin = new Thickness(0, 0, 0, 8) };

        /// <summary>"SIMPLER 1.1.1  —  18 ottobre 2026" → ("Simpler 1.1.1", "18 ottobre 2026").</summary>
        static (string title, string date) SplitTitle(string text, string version)
        {
            var first = text.Split('\n').Select(l => l.Trim()).FirstOrDefault(l => l != "") ?? "";
            var parts = first.Split('—');
            var date = parts.Length > 1 ? parts[1].Trim() : "";
            return ("Simpler " + version, date);
        }

        /// <summary>The notes file has the Italian text first and an "(English)" section at the end.</summary>
        static string LanguagePart(string text)
        {
            var lines = text.Replace("\r", "").Split('\n').ToList();
            int en = lines.FindIndex(l => l.Contains("(English)"));
            if (en < 0) return string.Join("\n", lines.Skip(2));
            if (L.Lang == "en") return string.Join("\n", lines.Skip(en + 2));
            return string.Join("\n", lines.Take(en).Skip(2));
        }

        sealed class NotesSection
        {
            public string Title = "";
            public List<(bool bullet, string text)> Lines = new();
        }

        /// <summary>Headings are lines underlined with --- or ===; "- " starts an item, indented lines continue it.</summary>
        static List<NotesSection> Parse(string text)
        {
            var lines = text.Split('\n');
            var sections = new List<NotesSection> { new NotesSection() };
            var cur = sections[0];
            for (int i = 0; i < lines.Length; i++)
            {
                var raw = lines[i].TrimEnd();
                var line = raw.Trim();
                if (line == "") continue;
                if (i + 1 < lines.Length && IsRule(lines[i + 1].Trim()))
                {
                    cur = new NotesSection { Title = Capitalize(line) };
                    sections.Add(cur);
                    i++;
                    continue;
                }
                if (IsRule(line)) continue;
                if (line.StartsWith("- ")) { cur.Lines.Add((true, line[2..].Trim())); continue; }
                if (raw.StartsWith(" ") && cur.Lines.Count > 0)
                {
                    var last = cur.Lines[^1];
                    cur.Lines[^1] = (last.bullet, last.text + " " + line);
                    continue;
                }
                // a plain line: a short line ending without a full stop starts a group (e.g. "Scene salvate (…)")
                if (cur.Lines.Count > 0 && !cur.Lines[^1].bullet && !cur.Lines[^1].text.EndsWith(".") && !cur.Lines[^1].text.EndsWith(":"))
                {
                    var last = cur.Lines[^1];
                    cur.Lines[^1] = (false, last.text + " " + line);
                }
                else cur.Lines.Add((false, line));
            }
            return sections.Where(s => s.Lines.Count > 0).ToList();
        }

        static bool IsRule(string l) => l.Length >= 3 && (l.All(c => c == '-') || l.All(c => c == '='));
        static string Capitalize(string s) => s.Length == 0 ? s : char.ToUpper(s[0]) + s[1..].ToLower();
    }
}
