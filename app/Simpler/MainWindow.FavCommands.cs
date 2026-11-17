using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Data;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;

namespace Simpler
{
    /// <summary>(1.76.32, Luca: «Simpler sta diventando pieno di funzionalità ... meno disorientante») Favourite
    /// commands of the right panel. A small yellow heart before every command (normal and in Avanzate): yellow
    /// outline and black inside when off, all yellow when on, black outline and yellow inside for the base commands
    /// (always there, cannot be taken away: a panel never ends up with one lonely command). The heart of the toolbar
    /// (between SmartView and the double arrow) shows only the favourites and the base ones: a section with none of
    /// them disappears, an Avanzate too. Next to it the presets: the start panel lists them (save the hearts of now,
    /// load one, «Deseleziona tutti»). The hearts are per computer, for every project (Settings).
    /// The panels are not touched one by one: after a panel is built (before its accordions) its sections are walked,
    /// each command gets its heart (keyed by panel, section and its own label).</summary>
    public sealed partial class MainWindow
    {
        // (1.76.46, Luca: «i cuoricini vanno bene ma il giallo resta un problema, tonalità di azzurro poco invadente»)
        // a soft azure, quieter than the blue of the buttons; the empty heart only an outline, darker still
        static readonly Color FavYellow = Theme.C("#86B4E0");
        static readonly Color FavOff = Theme.C("#4D6C90");
        Button? _favFilterButton, _favPresetsButton;
        HashSet<string>? _favSet;

        HashSet<string> FavSet => _favSet ??= LoadFavSet();

        /// <summary>The hearts saved; (1.76.35) those put in 1.76.32-34 on an ecosystem by its name
        /// («ecosystem|Thin grass|Oltre il bordo») become the ones of every ecosystem («ecosystem|ecosystem|...»).</summary>
        static HashSet<string> LoadFavSet()
        {
            var st = Settings.Load();
            bool changed = false;
            for (int i = 0; i < st.FavCommands.Count; i++)
            {
                var parts = st.FavCommands[i].Split('|');
                if (parts.Length >= 3 && parts[0] == "ecosystem" && parts[1] != "ecosystem" && parts[1] != L.T("Crea un ecosistema"))
                {
                    st.FavCommands[i] = "ecosystem|ecosystem|" + string.Join("|", parts.Skip(2));
                    changed = true;
                }
            }
            // (1.76.41) the terrain in five sections: the hearts of the commands moved out of «Terreno» follow them
            for (int i = 0; i < st.FavCommands.Count; i++)
            {
                var m = MovedTerrainKey(st.FavCommands[i]);
                if (m != null) { st.FavCommands[i] = m; changed = true; }
            }
            if (changed)
            {
                st.FavCommands = st.FavCommands.Distinct().ToList();
                foreach (var pr in st.FavPresets)
                    pr.Keys = pr.Keys.Select(k => { var q = k.Split('|'); return q.Length >= 3 && q[0] == "ecosystem" && q[1] != "ecosystem" && q[1] != L.T("Crea un ecosistema") ? "ecosystem|ecosystem|" + string.Join("|", q.Skip(2)) : k; })
                                     .Select(k => MovedTerrainKey(k) ?? k).Distinct().ToList();
                st.Save();
            }
            return new HashSet<string>(st.FavCommands);
        }

        /// <summary>(1.76.41) A heart saved on a terrain command that moved out of «Terreno» into one of its new
        /// sections: the new key (null when it did not move).</summary>
        static string? MovedTerrainKey(string key)
        {
            var q = key.Split('|');
            if (q.Length != 3) return null;
            // (1.76.42) «Rilievo della roccia» went from «Colori dal terreno» (1.76.41) to «Forma e roccia»; (1.76.53) it
            // is now «Profondità» in «Rilievo 3D»
            if (q[2] == L.T("Rilievo della roccia") && (q[1] == L.T("Colori dal terreno") || q[1] == L.T("Forma e roccia") || q[1] == L.T("Terreno")))
                return q[0] + "|" + L.T("Rilievo 3D") + "|" + L.T("Profondità");
            // (1.76.59, Luca: «due size non vanno bene») «Dimensione» of «Rilievo 3D» is now «Dimensione delle forme»
            if (q[1] == L.T("Rilievo 3D") && q[2] == L.T("Dimensione"))
                return q[0] + "|" + q[1] + "|" + L.T("Dimensione delle forme");
            if (q[1] != L.T("Terreno")) return null;
            var moves = new (string sec, string[] labels)[]
            {
                ("Forma e roccia", new[] { "Roccia scolpita", "Pendenza della roccia", "Erosione", "Età", "Direzione", "Erosione della mappa", "Spigolosità", "Strati di roccia", "Spessore degli strati", "Inclinazione degli strati" }),
                ("Zone del terreno", new[] { "Neve in quota", "Quota della neve", "Sfumatura dei bordi", "Ghiaia e terra", "Confini irregolari", "Irregolarità del bordo" }),
                ("Colori dal terreno", new[] { "Colori dal terreno", "Colate sulle pareti", "Fasce degli strati", "Creste e canaloni", "Umido" }),
                ("Spianata e bordi", new[] { "Spianata intorno al modello", "Raggio della spianata", "Centra sulla selezione", "Raccordo della spianata", "Bordo raccordato al suolo", "Bordo con baie e promontori" }),
            };
            foreach (var (sec, labels) in moves)
                foreach (var l in labels)
                    if (q[2] == L.T(l))
                        return q[0] + "|" + L.T(sec) + "|" + (l == "Colori dal terreno" ? L.T("Usa i colori dal terreno") : q[2]);
            return null;
        }

        bool FavFilterOn => Settings.Load().FavFilter;

        /// <summary>The base commands: per section title, the labels always kept ("#1": the first command of the
        /// section - the presets row of the terrain or the sea, the list of the stones...). Besides these, the first
        /// command of the first section of a panel with none of them.</summary>
        static readonly Dictionary<string, string[]> FavBase = new()
        {
            ["Trasformazione"] = new[] { "#1" },
            ["Materiale"] = new[] { "#1" },
            ["Luce"] = new[] { "#1", "Intensità", "Colore" },
            ["Terreno"] = new[] { "#1", "Dimensione", "Dislivello" },
            ["Oceano"] = new[] { "#1", "Altezza onde" },
            ["Costa"] = new[] { "Spiagge e scogli" },
            ["Pietre e detriti"] = new[] { "Scegli le pietre dalla libreria", "Posa le pietre", "Quantità", "Grandezza" },
            ["Pennello"] = new[] { "Diametro" },
            ["Oggetti"] = new[] { "Scala" },
            ["Modelli da distribuire"] = new[] { "#1" },
            ["Obiettivo"] = new[] { "#1" },
            ["Formato dell'immagine"] = new[] { "#1" },
            ["Path tracing · qualità"] = new[] { "#1" },
            ["Vista in tempo reale"] = new[] { "#1" },
            ["Colore ed esposizione"] = new[] { "#1" },
            ["Crea un ecosistema"] = new[] { "#1" },
            ["ecosystem"] = new[] { "Densità", "Scala" },
            ["Decal"] = new[] { "#1" },
            ["Video"] = new[] { "#1" },
            ["Funzione"] = new[] { "#1" },
        };

        /// <summary>Called by RenderProps after a panel is built, before its accordions: hearts, and the filter.</summary>
        void MakeFavorites()
        {
            var panel = _rightPanel == "" ? "props" : _rightPanel;
            bool filter = FavFilterOn;
            bool anyBase = false;
            var cards = new List<(Border card, StackPanel sp, string section, List<Cmd> cmds)>();
            foreach (var card in _props.Children.OfType<Border>().ToList())
            {
                if (card.Child is not StackPanel sp || sp.Children.Count < 2 || sp.Children[0] is not TextBlock title || (title.Tag as string) != "section")
                    continue;
                var cmds = new List<Cmd>();
                // (1.76.35, Luca: «il comando preferito non deve essere legato a un'istanza») a section named after what
                // it shows (an ecosystem: «Thin grass», «Bush and grass») has a stable key of its own (Uid): one heart
                // for all of them
                var secKey = string.IsNullOrEmpty(title.Uid) ? title.Text : title.Uid;
                Walk(sp, 1, panel + "|" + secKey, secKey, cmds, null);
                var baseList = FavBase.TryGetValue(secKey, out var bl) ? bl : FavBase.TryGetValue(title.Text, out var bl2) ? bl2 : Array.Empty<string>();
                for (int i = 0; i < cmds.Count; i++)
                    if (baseList.Contains(cmds[i].Label) || (i == 0 && baseList.Contains("#1"))) { cmds[i].Base = true; anyBase = true; }
                cards.Add((card, sp, title.Text, cmds));
            }
            // (a panel with no base command: its first command is one - never an empty panel)
            if (!anyBase)
            {
                var first = cards.SelectMany(c => c.cmds).FirstOrDefault();
                if (first != null) first.Base = true;
            }
            foreach (var (card, sp, _, cmds) in cards)
            {
                foreach (var c in cmds) AddHeart(c);
                if (!filter) continue;
                bool Keep(Cmd c) => c.Base || FavSet.Contains(c.Key);
                foreach (var c in cmds)
                    if (!Keep(c)) c.Row.Visibility = Visibility.Collapsed;
                // an Avanzate with nothing kept: away; the notes (not commands) away; a section with nothing: away
                foreach (var adv in cmds.Select(c => c.Adv).Where(a => a != null).Distinct())
                    if (!cmds.Any(c => c.Adv == adv && Keep(c))) adv!.Visibility = Visibility.Collapsed;
                foreach (var el in sp.Children.OfType<UIElement>().Skip(1).Where(e => e is TextBlock || (e is FrameworkElement fe && (fe.Tag as string) == "note")))
                    el.Visibility = Visibility.Collapsed;
                if (!cmds.Any(Keep)) card.Visibility = Visibility.Collapsed;
            }
        }

        sealed class Cmd
        {
            public string Key = "", Label = "";
            public FrameworkElement Row = null!;
            public Panel Parent = null!;
            public FrameworkElement? Adv;
            public bool Base;
        }

        /// <summary>The commands under a panel: sliders, switches, buttons, rows of choices; into an Avanzate (its
        /// body) and into a plain column of several commands; not the notes. The content of the scene (a stone of
        /// the list, a model of the brush: Tag "content") has no heart and always stays.</summary>
        void Walk(Panel host, int from, string keyBase, string section, List<Cmd> cmds, FrameworkElement? adv)
        {
            foreach (var el in host.Children.OfType<FrameworkElement>().Skip(from).ToList())
            {
                if (el is TextBlock || (el.Tag as string) is "content" or "note" or "section") continue;
                if (el is StackPanel advRoot && advRoot.Tag is StackPanel body)
                {
                    Walk(body, 0, keyBase, section, cmds, advRoot);
                    continue;
                }
                if (el is StackPanel col && col.Orientation == Orientation.Vertical && col.Tag == null
                    && col.Children.OfType<FrameworkElement>().Count(IsCommand) >= 2)
                {
                    Walk(col, 0, keyBase, section, cmds, adv);
                    continue;
                }
                var label = LabelOf(el);
                if (label == "") continue;
                cmds.Add(new Cmd { Key = keyBase + "|" + label, Label = label, Row = el, Parent = host, Adv = adv });
            }
        }

        static bool IsCommand(FrameworkElement e) => e is ValueSlider or Toggle or ButtonBase or ColorField
            || (e is Panel p && p.Children.OfType<ButtonBase>().Any());

        /// <summary>The words of a command: its label (slider, switch), else the first text inside it.</summary>
        static string LabelOf(FrameworkElement el)
        {
            if (el is ValueSlider vs) return vs.LabelText;
            if (el is Toggle tg) return tg.LabelText;
            if (!IsCommand(el) && el is not Panel) return "";
            string? found = null;
            void Find(object o, int depth)
            {
                if (found != null || depth > 8) return;
                if (o is TextBlock tb && !string.IsNullOrWhiteSpace(tb.Text)) { found = tb.Text.Trim(); return; }
                if (o is TextBox) return;
                if (o is ContentControl cc && cc.Content is string s && s.Trim() != "") { found = s.Trim(); return; }
                if (o is DependencyObject d)
                    foreach (var ch in LogicalTreeHelper.GetChildren(d)) Find(ch, depth + 1);
            }
            Find(el, 0);
            if (found == null) return "";
            return found.Length > 60 ? found[..60] : found;
        }

        /// <summary>The heart before the command: the row wrapped in a grid with a narrow first column.</summary>
        void AddHeart(Cmd c)
        {
            var idx = c.Parent.Children.IndexOf(c.Row);
            if (idx < 0) return;
            var wrap = new Grid { Margin = new Thickness(0) };
            wrap.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(17) });
            wrap.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            c.Parent.Children.RemoveAt(idx);
            var heart = Heart(c);
            // (the heart shows with its command: a command shown later - «Densità oltre il bordo» - brings it along)
            heart.SetBinding(VisibilityProperty, new Binding(nameof(Visibility)) { Source = c.Row });
            wrap.Children.Add(heart);
            Grid.SetColumn(c.Row, 1);
            wrap.Children.Add(c.Row);
            c.Parent.Children.Insert(idx, wrap);
            c.Row = wrap;
        }

        FrameworkElement Heart(Cmd c)
        {
            var path = new Path
            {
                Data = Geometry.Parse("M12,21 C12,21 2.5,14.6 2.5,8.4 C2.5,5.4 4.9,3 7.9,3 C9.7,3 11.2,3.9 12,5.3 C12.8,3.9 14.3,3 16.1,3 C19.1,3 21.5,5.4 21.5,8.4 C21.5,14.6 12,21 12,21 Z"),
                Stretch = Stretch.Uniform, Width = 11, Height = 11, StrokeThickness = 1.6,
            };
            var hit = new Border { Background = Brushes.Transparent, Child = path, VerticalAlignment = VerticalAlignment.Top,
                                   HorizontalAlignment = HorizontalAlignment.Left, Padding = new Thickness(0, 4, 4, 4) };
            void Look()
            {
                bool on = FavSet.Contains(c.Key);
                if (c.Base) { path.Fill = new SolidColorBrush(FavYellow); path.Stroke = new SolidColorBrush(Theme.Ground); }
                else if (on) { path.Fill = new SolidColorBrush(FavYellow); path.Stroke = new SolidColorBrush(FavYellow); }
                else { path.Fill = Brushes.Transparent; path.Stroke = new SolidColorBrush(FavOff); }
                hit.ToolTip = c.Base ? L.T("Comando base: resta sempre visibile anche con i soli preferiti")
                    : on ? L.T("Comando preferito: clic per toglierlo") : L.T("Clic: comando preferito (con il cuore in alto si vedono solo i preferiti)");
            }
            Look();
            if (!c.Base)
            {
                hit.Cursor = Cursors.Hand;
                hit.MouseLeftButtonUp += (_, e) =>
                {
                    var st = Settings.Load();
                    if (!st.FavCommands.Remove(c.Key)) st.FavCommands.Add(c.Key);
                    st.Save();
                    _favSet = new HashSet<string>(st.FavCommands);
                    Look();
                    e.Handled = true;
                };
            }
            return hit;
        }

        // ---------------------------------------------------------------- toolbar

        void BuildFavButtons(DockPanel bar)
        {
            // (docked right, added right to left: the presets then the heart, so: SmartView · heart · presets · arrows)
            _favPresetsButton = Theme.Button(Theme.Icon(Icons.Layers, FavYellow, 16), Theme.Kind.Ghost,
                L.T("Preset dei comandi preferiti: carica o salva quali comandi hanno il cuore"));
            _favPresetsButton.VerticalAlignment = VerticalAlignment.Center;
            _favPresetsButton.Padding = new Thickness(8, 0, 8, 0);
            _favPresetsButton.Margin = new Thickness(2, 0, 0, 0);
            _favPresetsButton.Click += async (_, __) =>
            {
                SelectFromViewport(Array.Empty<string>(), "");
                await ShowRightPanel("");
            };
            DockPanel.SetDock(_favPresetsButton, Dock.Right);
            bar.Children.Add(_favPresetsButton);

            _favFilterButton = Theme.Button(new ContentControl(), Theme.Kind.Ghost, null);
            _favFilterButton.VerticalAlignment = VerticalAlignment.Center;
            _favFilterButton.Padding = new Thickness(8, 0, 8, 0);
            _favFilterButton.Margin = new Thickness(6, 0, 0, 0);
            _favFilterButton.Click += (_, __) =>
            {
                var st = Settings.Load();
                st.FavFilter = !st.FavFilter;
                st.Save();
                FavFilterFace();
                RenderProps();
                Status(st.FavFilter ? L.T("Solo i comandi preferiti (e quelli base): il cuore in alto li mostra di nuovo tutti")
                                    : L.T("Tutti i comandi visibili"));
            };
            DockPanel.SetDock(_favFilterButton, Dock.Right);
            bar.Children.Add(_favFilterButton);
            FavFilterFace();
        }

        void FavFilterFace()
        {
            if (_favFilterButton == null) return;
            bool on = FavFilterOn;
            var p = new Path
            {
                Data = Geometry.Parse("M12,21 C12,21 2.5,14.6 2.5,8.4 C2.5,5.4 4.9,3 7.9,3 C9.7,3 11.2,3.9 12,5.3 C12.8,3.9 14.3,3 16.1,3 C19.1,3 21.5,5.4 21.5,8.4 C21.5,14.6 12,21 12,21 Z"),
                Stretch = Stretch.Uniform, Width = 16, Height = 16, StrokeThickness = 1.8,
                Fill = on ? new SolidColorBrush(FavYellow) : Brushes.Transparent, Stroke = new SolidColorBrush(FavYellow),
            };
            _favFilterButton.Content = p;
            _favFilterButton.BorderBrush = on ? new SolidColorBrush(FavYellow) : Brushes.Transparent;
            _favFilterButton.ToolTip = on ? L.T("Si vedono solo i comandi preferiti: clic per vederli tutti")
                                          : L.T("Mostra solo i comandi preferiti (con il cuore) e quelli base");
        }

        // ---------------------------------------------------------------- presets (in the start panel)

        static List<FavPreset> BuiltInPresets() => new()
        {
            new FavPreset { Name = L.T("Utente Rookie"), Icon = "rookie",
                Description = L.T("Solo i comandi base di ogni pannello: per cominciare senza perdersi") },
        };

        UIElement FavPresetsList()
        {
            var sp = new StackPanel { Margin = new Thickness(0, 24, 0, 0) };
            sp.Children.Add(Theme.Caption(L.T("Comandi preferiti · preset")));
            var hint = Theme.Label(L.T("Un preset ricorda quali comandi hanno il cuore. Con il cuore in alto acceso si vedono solo quelli (e i comandi base, con il cuore giallo bordato di nero)."), 12, Theme.TextFaint);
            hint.TextWrapping = TextWrapping.Wrap;
            hint.Margin = new Thickness(0, 6, 0, 10);
            sp.Children.Add(hint);
            var st = Settings.Load();
            foreach (var pr in BuiltInPresets().Concat(st.FavPresets))
                sp.Children.Add(PresetRow(pr, st.FavPresets.Contains(pr)));
            var row = new WrapPanel { Margin = new Thickness(0, 8, 0, 0) };
            row.Children.Add(SmallButton(Icons.Save, L.T("Salva i cuori di adesso"), async () =>
            {
                var name = InputDialog.Ask(this, L.T("Salva preset"), L.T("Nome del preset"), L.F("Preset {0}", Settings.Load().FavPresets.Count + 1));
                if (string.IsNullOrWhiteSpace(name)) return;
                var desc = InputDialog.Ask(this, L.T("Salva preset"), L.T("Descrizione (facoltativa)"), "") ?? "";
                var s2 = Settings.Load();
                s2.FavPresets.RemoveAll(p => p.Name == name.Trim());
                s2.FavPresets.Add(new FavPreset { Name = name.Trim(), Description = desc.Trim(), Icon = "user", Keys = s2.FavCommands.ToList() });
                s2.Save();
                Status(L.F("Preset salvato: {0} ({1} comandi con il cuore)", name.Trim(), s2.FavCommands.Count));
                RenderProps();
                await System.Threading.Tasks.Task.CompletedTask;
            }));
            row.Children.Add(SmallButton(Icons.Broom, L.T("Deseleziona tutti i preferiti"), async () =>
            {
                var s2 = Settings.Load();
                s2.FavCommands.Clear();
                s2.Save();
                _favSet = null;
                Status(L.T("Nessun comando preferito: con il cuore in alto restano solo i comandi base"));
                RenderProps();
                await System.Threading.Tasks.Task.CompletedTask;
            }));
            sp.Children.Add(row);
            return sp;
        }

        UIElement PresetRow(FavPreset pr, bool own)
        {
            var g = new Grid { Margin = new Thickness(0, 0, 0, 8), Background = Brushes.Transparent, Cursor = Cursors.Hand };
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var (ic, col) = pr.Icon switch
            {
                "rookie" => (Icons.Feather, Theme.Teal),
                _ => (Icons.Star, FavYellow),
            };
            var badge = new Border
            {
                Width = 34, Height = 34, CornerRadius = new CornerRadius(9), Margin = new Thickness(0, 0, 10, 0),
                Background = new SolidColorBrush(Color.FromArgb(40, col.R, col.G, col.B)),
                Child = Theme.Icon(ic, col, 18, 1.8), VerticalAlignment = VerticalAlignment.Top,
            };
            g.Children.Add(badge);
            var txt = new StackPanel();
            txt.Children.Add(Theme.Label(pr.Name, 13, Theme.TextSoft, FontWeights.SemiBold));
            if (pr.Description != "")
            {
                var d = Theme.Label(pr.Description, 11.5, Theme.TextFaint);
                d.TextWrapping = TextWrapping.Wrap;
                txt.Children.Add(d);
            }
            Grid.SetColumn(txt, 1);
            g.Children.Add(txt);
            g.ToolTip = L.T("Clic: carica questo preset (i cuori di adesso sono sostituiti)");
            g.MouseLeftButtonUp += (_, e) =>
            {
                var s2 = Settings.Load();
                s2.FavCommands = pr.Keys.ToList();
                s2.FavFilter = true;
                s2.Save();
                _favSet = null;
                FavFilterFace();
                Status(L.F("Preset caricato: {0} · si vedono solo i comandi preferiti (il cuore in alto li mostra tutti)", pr.Name));
                e.Handled = true;
            };
            if (own)
            {
                var del = IconButton(Icons.Trash, L.T("Elimina questo preset"), async () =>
                {
                    var s2 = Settings.Load();
                    s2.FavPresets.RemoveAll(p => p.Name == pr.Name);
                    s2.Save();
                    RenderProps();
                    await System.Threading.Tasks.Task.CompletedTask;
                });
                del.VerticalAlignment = VerticalAlignment.Top;
                Grid.SetColumn(del, 2);
                g.Children.Add(del);
            }
            return g;
        }
    }
}
