using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;

namespace Simpler
{
    /// <summary>Scene tree: hierarchy, selection, visibility, drag &amp; drop re-parenting, add menu.</summary>
    public sealed partial class MainWindow
    {
        readonly HashSet<string> _expanded = new HashSet<string>();
        bool _collapseTree = true;          // the next scene read is a new one (start, open, new): the tree closed
        Point _dragStart;
        string _dragId = "";
        string _pendingClick = "";        // a row of a multiple selection pressed: selected alone at the release, if not dragged

        async Task RefreshScene(string? frameId = null)
        {
            await Run(async api =>
            {
                var json = await api.Get("scene");
                var first = _scene.ById.Count == 0;
                var before = new HashSet<string>(_scene.ById.Keys);
                _scene = SceneModel.From(json);
                // a scene just loaded (opened, new, the start): the tree all closed - only the first rows, the user
                // opens what he needs (before, the models opened at once: a long list to scroll)
                if (_collapseTree) { _expanded.Clear(); _expandedInst.Clear(); _collapseTree = false; first = true; }
                _selection.RemoveAll(id => !_scene.ById.ContainsKey(id));
                if (!_scene.ById.ContainsKey(_selected)) _selected = _selection.LastOrDefault() ?? "";
                if (_paintGroup != "" && !_scene.ById.ContainsKey(_paintGroup)) PaintGroupGone();
                if (_benchId != "") BenchNote();       // (1.76.31: the bench's note goes when something comes back)
                // something just made and selected (a decal under the piece it is projected on, a pasted copy, a
                // primitive...): its parents open, so its row is in sight - selected before it was in the scene, its
                // parents stayed closed (a decal on a car's glass was hidden inside the collapsed "glass" row)
                var fresh = first ? new List<string>() : _selection.Where(id => !before.Contains(id)).ToList();
                foreach (var id in fresh)
                    foreach (var a in _scene.Ancestors(_scene.ById[id])) _expanded.Add(a.Id);
                // the tree is built again only when what it shows changed (a move, a light, a material: not - 1 s
                // at every action with 2,400 rows; 1.70.3)
                if (TreeSig() == _treeSig) RestyleRows();
                else RenderTree();
                if (fresh.Count > 0) { var to = fresh.Contains(_selected) ? _selected : fresh[^1]; Dispatcher.BeginInvoke(() => ScrollTreeTo(to), System.Windows.Threading.DispatcherPriority.Loaded); }
                // the ambience first: an open Ambiente panel was drawn with the values of before (after New: the
                // clouds, the sunset... of the old scene, while the engine was already back to the defaults)
                var ambSeq = _ambSeq;                      // (a change sent while this reading was on its way is not overwritten by it)
                var ambRead = await api.Get("ambience");
                if (ambSeq == _ambSeq) _ambience = ambRead;
                RenderProps();
                if (_webReady) await SyncViewer(json, frameId);
                if (_webReady) await PushSwitchedEmissions(json);
                if (_webReady) PushAmbienceToViewer();
                UpdateGizmo();
                UpdateHistory(await api.Get("history"));
            });
        }

        // how many decals each object holds (in itself or deeper): a violet dot on its icon - a decal sits under the
        // piece it is projected on, often inside a closed row of a model
        Dictionary<string, int> _decalsInside = new();
        // the same for the ecosystems (a blue dot): an ecosystem is the child of the object it grows on, often deep
        // inside a model - the dot shows on every row above it where it went
        Dictionary<string, int> _ecosInside = new();
        Dictionary<string, int> _plotScatters = new();

        string _treeSig = "";

        /// <summary>What the rows of the tree show (not the places of the objects), the rows opened and the filter.</summary>
        string TreeSig()
        {
            var sb = new System.Text.StringBuilder(_scene.ById.Count * 48);
            foreach (var o in _scene.ById.Values)
                sb.Append(o.Id).Append('|').Append(o.Parent).Append('|').Append(o.Name).Append('|').Append(o.Kind).Append('|')
                  .Append(o.Visible ? '1' : '0').Append(o.Paint ? '1' : '0').Append(o.IsAmbience ? '1' : '0').Append(o.IsLight ? '1' : '0')
                  .Append('|').Append(o.InstanceOf).Append('|').Append(o.InstanceCount).Append('|').Append(o.PaintCount).Append('|')
                  .Append(o.Eco).Append('|').Append(o.Order).Append('|').Append(o.Children.Count).Append('|')
                  .Append(string.Join(",", o.Materials)).Append('\n');
            sb.Append(string.Join(",", _expanded.OrderBy(x => x, StringComparer.Ordinal))).Append('\n');
            sb.Append(string.Join(",", _expandedInst.OrderBy(x => x, StringComparer.Ordinal))).Append('\n');
            sb.Append(_treeSearch.Text.Trim()).Append('|').Append(_treeType).Append('|').Append(_scatterPending ? '1' : '0');
            return sb.ToString();
        }

        /// <summary>The selection shown on the rows already drawn.</summary>
        void RestyleRows()
        {
            var before = _selSet;
            _selSet = new HashSet<string>(_selection);
            before.UnionWith(_selSet);
            before.Add(_selected);
            foreach (var id in before)
                if (_rowLook.TryGetValue(id, out var look)) look();
        }

        void RenderTree()
        {
            _treeRows.Children.Clear();
            _rowLook.Clear();
            _selSet = new HashSet<string>(_selection);
            _treeSig = TreeSig();
            _decalsInside = new Dictionary<string, int>();
            foreach (var d in _scene.ById.Values.Where(x => x.Kind == "decal"))
                foreach (var a in _scene.Ancestors(d))
                    _decalsInside[a.Id] = _decalsInside.GetValueOrDefault(a.Id) + 1;
            _ecosInside = new Dictionary<string, int>();
            foreach (var g in _scene.ById.Values.Where(x => x.Eco == "group"))
                foreach (var a in _scene.Ancestors(g))
                    _ecosInside[a.Id] = _ecosInside.GetValueOrDefault(a.Id) + 1;
            // the test plot: the same blue dot when scatters painted on it (its children, an ecosystem being made)
            _plotScatters = new Dictionary<string, int>();
            foreach (var g in _scene.ById.Values.Where(x => x.Paint && x.Eco == ""))
                if (_scene.ById.TryGetValue(g.Parent, out var pl) && pl.Eco == "plot")
                    _plotScatters[pl.Id] = _plotScatters.GetValueOrDefault(pl.Id) + 1;
            var filter = _treeSearch.Text.Trim();
            if (filter.Length > 0 || _treeType != "")
            {
                var match = NameMatcher(filter);
                var hits = _scene.ById.Values.Where(o => !o.IsAmbience && match(o.Name) && TypeMatches(o)).OrderBy(o => o.Name, StringComparer.CurrentCultureIgnoreCase).ToList();
                foreach (var o in hits.Take(2000))
                    _treeRows.Children.Add(Row(o, 0, false));
                var info = Theme.Label(hits.Count == 0 ? L.T("Nessun oggetto corrisponde al filtro") : L.F("{0} risultati", hits.Count) + (hits.Count > 2000 ? L.T(" (mostrati i primi 2000)") : ""), 12, Theme.TextFaint);
                info.Margin = new Thickness(10, 8, 0, 0);
                _treeRows.Children.Add(info);
                return;
            }
            void Walk(IEnumerable<SceneObject> list, int depth, bool parentHidden)
            {
                var all = list.Where(o => !o.IsAmbience).ToList();
                var ids = new HashSet<string>(all.Select(o => o.Id));
                // instances whose original sits in the same list are not listed one by one: they go under the
                // original, in a collapsed "N istanze" row (a scene with thousands of copies stays readable)
                var grouped = all.Where(o => o.InstanceOf != "" && ids.Contains(o.InstanceOf)).ToLookup(o => o.InstanceOf);
                foreach (var o in all.Where(o => !(o.InstanceOf != "" && ids.Contains(o.InstanceOf)))
                                     .OrderBy(o => o.Order).ThenBy(o => o.Kind == "file" ? 0 : 1).ThenBy(o => o.Name, StringComparer.CurrentCultureIgnoreCase))
                {
                    var hidden = parentHidden || !o.Visible;
                    _treeRows.Children.Add(Row(o, depth, hidden));
                    if (o.Children.Count > 0 && _expanded.Contains(o.Id)) Walk(o.Children, depth + 1, hidden);
                    var inst = grouped[o.Id].OrderBy(x => x.Name, StringComparer.CurrentCultureIgnoreCase).ToList();
                    if (inst.Count == 0) continue;
                    _treeRows.Children.Add(InstancesRow(o, inst, depth + 1));
                    if (!_expandedInst.Contains(o.Id)) continue;
                    foreach (var i in inst.Take(5000))
                    {
                        var ih = parentHidden || !i.Visible;
                        _treeRows.Children.Add(Row(i, depth + 2, ih));
                        if (i.Children.Count > 0 && _expanded.Contains(i.Id)) Walk(i.Children, depth + 3, ih);
                    }
                }
            }
            Walk(_scene.Roots, 0, false);
            if (_scatterPending)
            {
                // a new distribution is being made by the engine (the first one of big models takes a while): it has a
                // row at once, so it is clear that it is coming
                var row = Theme.IconText(Icons.Folder, L.T("Nuova distribuzione · in preparazione…"), Theme.TextFaint, 15);
                row.Margin = new Thickness(18, 6, 0, 6);
                row.Opacity = 0.75;
                ((TextBlock)row.Children[1]).FontStyle = FontStyles.Italic;
                ((TextBlock)row.Children[1]).Foreground = Theme.B(Theme.TextFaint);
                _treeRows.Children.Add(row);
            }
        }

        /// <summary>Name filter: plain text = "contains"; % or * are wildcards (SQL LIKE style), case-insensitive.</summary>
        static Func<string, bool> NameMatcher(string filter)
        {
            if (filter == "") return _ => true;
            if (filter.IndexOfAny(new[] { '%', '*', '?', '_' }) < 0 || !(filter.Contains('%') || filter.Contains('*')))
                return n => n.Contains(filter, StringComparison.OrdinalIgnoreCase);
            var pattern = "^" + System.Text.RegularExpressions.Regex.Escape(filter)
                .Replace("%", ".*").Replace("\\*", ".*").Replace("\\?", ".").Replace("_", ".") + "$";
            var rx = new System.Text.RegularExpressions.Regex(pattern, System.Text.RegularExpressions.RegexOptions.IgnoreCase);
            return n => rx.IsMatch(n);
        }

        bool TypeMatches(SceneObject o) => _treeType switch
        {
            "mesh" => o.Kind == "mesh",
            "light" => o.IsLight,
            "group" => o.Kind == "group" || o.Kind == "file",
            _ => true,
        };

        readonly HashSet<string> _expandedInst = new();

        /// <summary>"N istanze" under an original: click to open/close the list; right click to select them.</summary>
        UIElement InstancesRow(SceneObject original, List<SceneObject> inst, int depth)
        {
            bool open = _expandedInst.Contains(original.Id);
            var grid = new Grid { Height = 26, Margin = new Thickness(0, 0, 0, 1), Background = Brushes.Transparent, Cursor = Cursors.Hand };
            Point down = default;
            bool pressed = false;
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(depth * 16 + 2) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(20) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            var bg = new Border { CornerRadius = new CornerRadius(7), Background = Brushes.Transparent };
            Grid.SetColumnSpan(bg, 3);
            grid.Children.Add(bg);
            grid.MouseEnter += (_, __) => bg.Background = Theme.B("#111E36");
            grid.MouseLeave += (_, __) => bg.Background = Brushes.Transparent;
            var chevron = Theme.Icon(Icons.Chevron, Theme.TextFaint, 10, 2.4);
            chevron.RenderTransformOrigin = new Point(0.5, 0.5);
            chevron.RenderTransform = new RotateTransform(open ? 90 : 0);
            Grid.SetColumn(chevron, 1);
            grid.Children.Add(chevron);
            var row = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            row.Children.Add(new System.Windows.Shapes.Ellipse { Width = 7, Height = 7, Fill = Theme.B(Theme.Warm), Margin = new Thickness(2, 1, 7, 0) });
            row.Children.Add(Theme.Label(inst.Count == 1 ? L.T("1 istanza") : L.F("{0} istanze", inst.Count), 12, Theme.TextMuted));
            Grid.SetColumn(row, 2);
            grid.Children.Add(row);
            grid.ToolTip = L.F("Copie di «{0}» che ne condividono forma e materiali. Clic: mostra o nascondi l'elenco · tasto destro: selezionale", original.Name);
            grid.MouseLeftButtonUp += (_, __) =>
            {
                if (!pressed) return;          // (a drag, not a click)
                pressed = false;
                if (!_expandedInst.Remove(original.Id)) _expandedInst.Add(original.Id);
                RenderTree();
            };
            grid.PreviewMouseLeftButtonDown += (_, e) => { down = e.GetPosition(this); pressed = true; };
            grid.MouseMove += (_, e) =>
            {
                if (!pressed || e.LeftButton != MouseButtonState.Pressed) { pressed = false; return; }
                var p = e.GetPosition(this);
                if (Math.Abs(p.X - down.X) + Math.Abs(p.Y - down.Y) < 8) return;
                pressed = false;
                DragDrop.DoDragDrop(grid, new DataObject("simpler-id", original.Id), DragDropEffects.Move);   // the original brings them along
            };
            grid.AllowDrop = true;
            grid.DragOver += (_, e) => { e.Handled = true; bg.Background = Theme.B("#16284A"); };
            grid.DragLeave += (_, __) => bg.Background = Brushes.Transparent;
            grid.Drop += async (_, e) => { e.Handled = true; bg.Background = Brushes.Transparent; await OnTreeDrop(e, original.Parent, original.Id, "after"); };
            var m = new ContextMenu();
            void Item(string text, Action act) { var i = new MenuItem { Header = text }; i.Click += (_, __) => act(); m.Items.Add(i); }
            Item(L.F("Seleziona le {0} istanze", inst.Count), () => SetSelection(inst.Select(x => x.Id), inst[^1].Id));
            Item(L.T("Seleziona l'originale e tutte le istanze"), () => SetSelection(new[] { original.Id }.Concat(inst.Select(x => x.Id)), original.Id));
            grid.ContextMenu = m;
            return grid;
        }

        // the rows drawn, by object: a click only changes how they look (1.70.3 - the whole tree was built again at
        // every click: 1 s with 2,400 rows of a big model open)
        readonly Dictionary<string, Action> _rowLook = new();
        HashSet<string> _selSet = new();

        UIElement Row(SceneObject o, int depth, bool hidden)
        {
            bool selected = _selSet.Contains(o.Id);
            bool isPrimary = o.Id == _selected;
            var grid = new Grid { Tag = o.Id, Height = 30, Margin = new Thickness(0, 0, 0, 1), Background = Brushes.Transparent, Cursor = Cursors.Hand, AllowDrop = true };
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(depth * 16 + 2) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(20) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(24) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(28) });

            var bg = new Border
            {
                CornerRadius = new CornerRadius(7),
                Background = selected ? Theme.B(Theme.Selected) : Brushes.Transparent,
                BorderBrush = isPrimary ? Theme.B(Theme.Accent) : (selected ? Theme.B("#2F4A78") : Brushes.Transparent),
                BorderThickness = new Thickness(selected ? 1 : 0),
            };
            Grid.SetColumnSpan(bg, 6);
            grid.Children.Add(bg);
            grid.MouseEnter += (_, __) => { if (!selected) bg.Background = Theme.B("#111E36"); };
            grid.MouseLeave += (_, __) => { if (!selected) bg.Background = Brushes.Transparent; };
            TextBlock? nameLabel = null;
            _rowLook[o.Id] = () =>
            {
                selected = _selSet.Contains(o.Id);
                isPrimary = o.Id == _selected;
                bg.Background = selected ? Theme.B(Theme.Selected) : Brushes.Transparent;
                bg.BorderBrush = isPrimary ? Theme.B(Theme.Accent) : (selected ? Theme.B("#2F4A78") : Brushes.Transparent);
                bg.BorderThickness = new Thickness(selected ? 1 : 0);
                if (nameLabel != null) nameLabel.Foreground = Theme.B(hidden ? Theme.C("#5D6E8C") : (selected ? Colors.White : Theme.C("#D3DCEA")));
            };

            if (o.Children.Count > 0)
            {
                var chevron = Theme.Icon(Icons.Chevron, Theme.TextFaint, 11, 2.4);
                chevron.RenderTransformOrigin = new Point(0.5, 0.5);
                chevron.RenderTransform = new RotateTransform(_expanded.Contains(o.Id) ? 90 : 0);
                var toggle = new Border { Child = chevron, Background = Brushes.Transparent, Width = 20 };
                toggle.MouseLeftButtonDown += (_, e) =>
                {
                    if (!_expanded.Remove(o.Id)) _expanded.Add(o.Id);
                    RenderTree();
                    e.Handled = true;
                };
                Grid.SetColumn(toggle, 1);
                grid.Children.Add(toggle);
            }

            var (icon, color) = o.Eco is "plot" or "group" ? (Icons.Grass, Theme.C("#7FCB8B")) : o.Kind switch     // (ecosystems: plot and placed ones)
            {
                "file" => (Icons.File, Theme.Accent),
                "group" => (Icons.Folder, Theme.C("#8FA3C4")),
                "mesh" => (Icons.Mesh, Theme.C("#B9C6DA")),
                "sun" or "area" or "spot" or "point" => (Icons.Light, Theme.Warm),
                "camera" => (Icons.Camera, Theme.TextFaint),
                "decal" => (Icons.Image, Theme.C("#C792EA")),
                _ => (Icons.Mesh, Theme.TextFaint),
            };
            var ic = Theme.Icon(icon, color, 15);
            ic.HorizontalAlignment = HorizontalAlignment.Center;
            // instance mark: a small orange dot on the icon when the geometry is shared with other objects
            // (for a group: when its pieces are instances of another group's pieces)
            int decalsIn = _decalsInside.GetValueOrDefault(o.Id);
            int ecosIn = _ecosInside.GetValueOrDefault(o.Id);
            int plotIn = _plotScatters.GetValueOrDefault(o.Id);
            if (o.InstanceOf != "" || decalsIn > 0 || ecosIn > 0 || plotIn > 0)
            {
                var holder = new Grid();
                holder.Children.Add(ic);
                var tips = new List<string>();
                if (o.InstanceOf != "")
                {
                    holder.Children.Add(new System.Windows.Shapes.Ellipse
                    {
                        Width = 7, Height = 7, Fill = Theme.B(Theme.Warm), Stroke = Theme.B("#0B1426"), StrokeThickness = 1.2,
                        HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Bottom, Margin = new Thickness(0, 0, 2, 6),
                    });
                    tips.Add(_scene.ById.TryGetValue(o.InstanceOf, out var orig)
                        ? L.F("Istanza di «{0}»: ne condivide forma e materiali", orig.Name)
                        : L.T("Istanza: forma e materiali condivisi con un altro modello"));
                }
                if (decalsIn > 0)
                {
                    // decal mark: a violet dot (the colour of the decal icon) at the top of the icon
                    holder.Children.Add(new System.Windows.Shapes.Ellipse
                    {
                        Width = 7, Height = 7, Fill = Theme.B("#C792EA"), Stroke = Theme.B("#0B1426"), StrokeThickness = 1.2,
                        HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Top, Margin = new Thickness(0, 6, 2, 0),
                    });
                    tips.Add(decalsIn == 1 ? L.T("Contiene una decal") : L.F("Contiene {0} decal", decalsIn));
                }
                if (ecosIn > 0 || plotIn > 0)
                {
                    // ecosystem mark: a blue dot at the top left of the icon
                    holder.Children.Add(new System.Windows.Shapes.Ellipse
                    {
                        Width = 7, Height = 7, Fill = Theme.B(Theme.Accent), Stroke = Theme.B("#0B1426"), StrokeThickness = 1.2,
                        HorizontalAlignment = HorizontalAlignment.Left, VerticalAlignment = VerticalAlignment.Top, Margin = new Thickness(2, 6, 0, 0),
                    });
                    if (ecosIn > 0) tips.Add(ecosIn == 1 ? L.T("Contiene un ecosistema") : L.F("Contiene {0} ecosistemi", ecosIn));
                    if (plotIn > 0) tips.Add(plotIn == 1 ? L.T("Contiene uno scatter del banco di prova") : L.F("Contiene {0} scatter del banco di prova", plotIn));
                }
                holder.ToolTip = string.Join("\n", tips);
                Grid.SetColumn(holder, 2);
                grid.Children.Add(holder);
            }
            else
            {
                Grid.SetColumn(ic, 2);
                grid.Children.Add(ic);
            }

            var name = Theme.Label(o.Name, 13, hidden ? Theme.C("#5D6E8C") : (selected ? Colors.White : Theme.C("#D3DCEA")));
            name.Margin = new Thickness(6, 0, 4, 0);
            name.Tag = "name";
            nameLabel = name;
            Grid.SetColumn(name, 3);
            grid.Children.Add(name);

            var right = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            if (o.InstanceCount > 0)
            {
                // the original: how many instances it has (orange, like their dots)
                right.Children.Add(new Border
                {
                    CornerRadius = new CornerRadius(6), Background = Theme.B("#2A2416"), Padding = new Thickness(5, 0, 5, 1), Margin = new Thickness(0, 0, 6, 0),
                    VerticalAlignment = VerticalAlignment.Center, ToolTip = L.F("Originale con {0} istanze", o.InstanceCount),
                    Child = new TextBlock { Text = "×" + o.InstanceCount, FontFamily = Theme.Mono, FontSize = 10.5, Foreground = Theme.B(Theme.Warm) },
                });
            }
            var shownCount = o.Paint && o.PaintCount > 0 ? o.PaintCount : o.Children.Count;     // a distribution: its pieces
            if (shownCount > 0)
                right.Children.Add(new TextBlock { Text = shownCount.ToString("N0"), FontFamily = Theme.Mono, FontSize = 11, Foreground = Theme.B(Theme.TextFaint), VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 4, 0) });
            if (right.Children.Count > 0)
            {
                Grid.SetColumn(right, 4);
                grid.Children.Add(right);
            }

            var eye = new Border
            {
                Child = Theme.Icon(o.Visible ? Icons.Eye : Icons.EyeOff, hidden ? Theme.C("#4A5A78") : Theme.C("#6E7F9E"), 15),
                Background = Brushes.Transparent,
                ToolTip = o.Visible ? L.T("Nascondi") : L.T("Mostra"),
            };
            eye.MouseLeftButtonDown += async (_, e) =>
            {
                e.Handled = true;
                await Run(async api => { await api.Post("visible", new { id = o.Id, visible = !o.Visible }); });
                await RefreshScene();
            };
            Grid.SetColumn(eye, 5);
            grid.Children.Add(eye);

            grid.MouseLeftButtonDown += (_, e) =>
            {
                _dragStart = e.GetPosition(this); _dragId = o.Id;
                // a row of a selection of several, pressed without Ctrl/Shift: the selection stays (they may be dragged
                // together); a click without dragging selects the row alone, at the release
                if (Keyboard.Modifiers == ModifierKeys.None && _selection.Count > 1 && _selection.Contains(o.Id)) _pendingClick = o.Id;
                else { _pendingClick = ""; TreeClick(o.Id); }
                StartLongPress(o.Id);
            };
            grid.MouseLeftButtonUp += (_, __) =>
            {
                if (_pendingClick == o.Id) { _pendingClick = ""; TreeClick(o.Id); }
            };
            grid.MouseMove += (_, e) =>
            {
                if (e.LeftButton != MouseButtonState.Pressed || _dragId != o.Id) return;
                var p = e.GetPosition(this);
                if (Math.Abs(p.X - _dragStart.X) + Math.Abs(p.Y - _dragStart.Y) < 8) return;
                _dragId = "";
                _pendingClick = "";
                // the selection when the row is part of it (Ctrl + click on several rows): they move together
                var data = new DataObject("simpler-id", o.Id);
                if (_selection.Count > 1 && _selection.Contains(o.Id)) data.SetData("simpler-ids", _selection.ToArray());
                var scroll = TreeEdgeScroll();
                try { DragDrop.DoDragDrop(grid, data, DragDropEffects.Move); }
                finally { scroll.Stop(); }
            };
            // drop zones: upper or lower edge of the row = next to it (same level: a child can go back up a level);
            // the middle = inside it (it becomes the parent)
            string Zone(DragEventArgs e)
            {
                var y = e.GetPosition(grid).Y;
                return y < grid.ActualHeight * 0.28 ? "before" : y > grid.ActualHeight * 0.72 ? "after" : "inside";
            }
            void ResetLook()
            {
                bg.BorderBrush = isPrimary ? Theme.B(Theme.Accent) : (selected ? Theme.B("#2F4A78") : Brushes.Transparent);
                bg.BorderThickness = new Thickness(selected ? 1 : 0);
                bg.CornerRadius = new CornerRadius(7);
            }
            grid.DragOver += (_, e) =>
            {
                e.Handled = true;
                if (e.Data.GetDataPresent(DataFormats.FileDrop)) { bg.BorderBrush = Theme.B(Theme.Warm); bg.BorderThickness = new Thickness(1); return; }
                var zone = Zone(e);
                bg.BorderBrush = Theme.B(zone == "inside" ? Theme.Warm : Theme.Accent);
                bg.BorderThickness = zone switch { "before" => new Thickness(0, 2, 0, 0), "after" => new Thickness(0, 0, 0, 2), _ => new Thickness(1) };
                bg.CornerRadius = new CornerRadius(zone == "inside" ? 7 : 0);
            };
            grid.DragLeave += (_, __) => ResetLook();
            grid.Drop += async (_, e) =>
            {
                e.Handled = true;
                ResetLook();
                var zone = e.Data.GetDataPresent(DataFormats.FileDrop) ? "inside" : Zone(e);
                if (zone == "inside") await OnTreeDrop(e, o.Id);
                else await OnTreeDrop(e, o.Parent, o.Id, zone);
            };
            // the menu of the right button made when it opens, not with every row: a tree of hundreds of rows built
            // hundreds of menus (and looked through the scene for each) at every click on an object
            grid.ContextMenuOpening += (_, e) =>
            {
                e.Handled = true;
                var now = _scene.ById.GetValueOrDefault(o.Id) ?? o;          // (the row may be older than the scene: TreeSig)
                // (15/11) as in the view: the row under the mouse is selected first when it is not part of the selection
                // (inside a selected group counts as part of it), so the menu and its title speak of what it works on
                if (!_selection.Contains(now.Id) && !_scene.Ancestors(now).Any(anc => _selection.Contains(anc.Id))) Select(now.Id);
                ObjectMenu(now, "", false).IsOpen = true;
            };
            grid.ContextMenu = _rowMenuPlaceholder;
            return grid;
        }

        /// <summary>A row dropped in the tree: inside a group (target = null) or before/after a row (same level as it,
        /// in that place: the order of the rows is the user's).</summary>
        [System.Runtime.InteropServices.DllImport("user32.dll")]
        static extern bool GetCursorPos(out NativePoint p);
        struct NativePoint { public int X, Y; }

        /// <summary>While a row is dragged: near the top or the bottom of the tree the list scrolls by itself (faster
        /// closer to the edge), so the row can be dropped anywhere in a long list. The pointer is read from Windows:
        /// during the drag WPF does not move its own.</summary>
        DispatcherTimer TreeEdgeScroll()
        {
            var timer = new DispatcherTimer(DispatcherPriority.Input) { Interval = TimeSpan.FromMilliseconds(16) };
            timer.Tick += (_, __) =>
            {
                if (!GetCursorPos(out var sp) || !_treeScroll.IsVisible) return;
                var y = _treeScroll.PointFromScreen(new Point(sp.X, sp.Y)).Y;
                const double zone = 44;
                var h = _treeScroll.ActualHeight;
                if (y < -60 || y > h + 60) return;              // (far away: dragging elsewhere, onto the view)
                double speed = y < zone ? -(zone - y) / zone : y > h - zone ? (y - (h - zone)) / zone : 0;
                if (speed != 0) _treeScroll.ScrollToVerticalOffset(_treeScroll.VerticalOffset + Math.Clamp(speed, -1, 1) * 14);
            };
            timer.Start();
            return timer;
        }

        async Task OnTreeDrop(DragEventArgs e, string newParent, string? target = null, string where = "")
        {
            if (e.Data.GetDataPresent(DataFormats.FileDrop)) { await OnFileDrop(e); return; }
            if (e.Data.GetData("simpler-id") is not string id || id == newParent || id == target) return;
            if (!_scene.ById.TryGetValue(id, out var moving)) return;
            // several rows dragged together (the selection): the ones inside another one of them follow it
            var dragged = (e.Data.GetData("simpler-ids") as string[] ?? new[] { id }).Where(x => _scene.ById.ContainsKey(x)).Distinct().ToList();
            var draggedSet = dragged.ToHashSet();
            dragged = dragged.Where(x => !_scene.Ancestors(_scene.ById[x]).Any(a => draggedSet.Contains(a.Id))).ToList();
            if (dragged.Count == 0) return;
            if (target == null && dragged.All(x => _scene.ById[x].Parent == newParent)) return;   // already in that group
            // an original listed with its instances below it: they move together (same group, same place in the tree)
            var ids = new List<string>(dragged);
            foreach (var d in dragged)
            {
                var dm = _scene.ById[d];
                ids.AddRange(_scene.ById.Values.Where(x => x.InstanceOf == d && x.Parent == dm.Parent && x.Id != newParent && !ids.Contains(x.Id)).Select(x => x.Id));
            }
            if (newParent != "" && _scene.ById.TryGetValue(newParent, out var parentObj))
            {
                // never inside one of the moving objects (or their children)
                foreach (var a in new[] { parentObj }.Concat(_scene.Ancestors(parentObj)))
                    if (ids.Contains(a.Id)) { Status(L.T("Non puoi spostare un oggetto dentro sé stesso o un suo figlio"), true); return; }
            }
            if (target != null && ids.Contains(target)) return;          // next to itself / its own instances: nothing to do
            var idArray = new JsonArray(ids.Select(x => (JsonNode)x!).ToArray());
            if (target != null)
                await Run(async api => { await api.Post("order", new JsonObject { ["ids"] = idArray, ["parent"] = newParent, ["target"] = target, ["where"] = where }); });
            else
                await Run(async api => { await api.Post("parent", new JsonObject { ["ids"] = idArray, ["parent"] = newParent }); });
            if (newParent != "") _expanded.Add(newParent);
            await RefreshScene();
        }

        // (a ContextMenu must be there for the right button to raise ContextMenuOpening; the real one is made then)
        readonly ContextMenu _rowMenuPlaceholder = new ContextMenu();

        /// <summary>(Luca: «il menu di destra deve tenere conto del tipo oggetto! … se una voce non c'entra non deve esserci»)
        /// what a row is, for the menus of the tree and of the view: each command only where it applies.</summary>
        readonly struct RowKind
        {
            public readonly bool Model, Light, Ambience, Camera, Decal, Scatter, EcoGroup, EcoLayer, Plot, Terrain, Zone, Ground, Scree, ScreeLayer;
            public RowKind(SceneObject o)
            {
                Light = o.IsLight; Ambience = o.IsAmbience; Camera = o.Kind == "camera"; Decal = o.Kind == "decal";
                EcoGroup = o.Eco == "group"; EcoLayer = o.Eco == "layer"; Plot = o.Eco == "plot";
                Scatter = o.Paint && !EcoLayer;
                Terrain = o.Role == "terrain"; Zone = o.Role == "zone"; Ground = o.Role == "ground";
                Scree = o.Role == "scree"; ScreeLayer = o.Role == "screeLayer" || (o.Paint && Scree);
                // a model: a mesh, an imported file or a group of them - not something Simpler made and keeps
                Model = !Light && !Camera && !Decal && !o.Paint && o.Eco == "" && o.Role == "" && o.Kind is "mesh" or "file" or "group";
            }
            /// <summary>Made by Simpler as part of something else (a terrain, an ecosystem, the ambience): not on its own.</summary>
            public bool Part => EcoLayer || Zone || Ground || ScreeLayer || Ambience;
            /// <summary>Can be duplicated and copied as it is.</summary>
            public bool Copyable => Model || Scatter || EcoGroup || Decal || (Light && !Ambience);
        }

        /// <summary>(15/11, Luca: «voglio un menu chiaro senza difetti») THE menu of the right button on an object, one for
        /// the tree and for the 3D view (before: two menus written apart, with different commands and different rules).
        /// The rules, the same for every command:
        /// - the commands work on the selection (the object under the mouse is selected first when it is not part of it);
        /// - a command is there only if it applies to ALL the selected objects; the commands for one object alone are not
        ///   there with several; nothing is shown greyed out;
        /// - sections, always in this order: look · copies · groups · the model · the library · delete.
        /// material: the material under the mouse in the view ("" from the tree).</summary>
        ContextMenu ObjectMenu(SceneObject o, string material, bool fromView)
        {
            var m = new ContextMenu { Placement = System.Windows.Controls.Primitives.PlacementMode.MousePoint };
            var k = new RowKind(o);
            var targets = MenuTargets(o);
            bool multi = targets.Count > 1;
            bool AllAre(Func<RowKind, bool> f) => targets.All(tt => f(new RowKind(tt)));
            var sections = new List<List<MenuItem>>();
            var cur = new List<MenuItem>();
            void Section() { cur = new List<MenuItem>(); sections.Add(cur); }
            void Item(string text, Func<Task> act) { var mi = new MenuItem { Header = text }; mi.Click += async (_, __) => await act(); cur.Add(mi); }

            // the one object the menu speaks of when there is one: what is selected (in the view the piece under the mouse may
            // be inside the selected group: the title and the commands are those of the group; only «Modifica il materiale»
            // and «Ottimizza poligoni» look at the piece itself)
            var one = multi ? o : targets[0];
            var k1 = new RowKind(one);
            m.Items.Add(new MenuItem { Header = multi ? L.F("{0} oggetti selezionati", targets.Count) : one.Name, IsEnabled = false, FontWeight = FontWeights.SemiBold });

            // ---- look
            Section();
            // (19/11, Luca: «non riesco mai a trovarlo») the panel with the values of the object, whatever panel is open
            Item(L.T("Proprietà"), async () => await ShowRightPanel(""));
            Item(L.T("Inquadra (F)"), FrameSelection);
            if (fromView && !multi && one.Parent != "" && _scene.ById.TryGetValue(one.Parent, out var parentObj))
                Item(L.F("Seleziona il gruppo «{0}» (Ctrl+clic destro)", parentObj.Name), async () => { await Task.Yield(); Select(parentObj.Id); });
            if (!multi) Item(L.T("Rinomina (F2)"), async () => { await Task.Yield(); if (fromView) ScrollTreeTo(one.Id); BeginRename(one.Id); });
            if (AllAre(q => !q.Ambience))
                Item(L.T("Nascondi"), async () =>
                {
                    foreach (var sid in _selection.ToList())
                        await Run(async api => { await api.Post("visible", new { id = sid, visible = false }); });
                    Select("");
                    await RefreshScene();
                });
            if (AllAre(q => !q.Part && !q.Terrain && !q.Scree && !q.Plot))
                Item(L.T("Appoggia sulla superficie sotto"), async () => { await Task.Yield(); SendToWeb(new { type = "dropToFloor" }); });
            if (fromView && _snowPresent)
                Item(_snowHidden ? L.T("Mostra la neve") : L.T("Nascondi la neve"), async () => await SetSnowHidden(!_snowHidden));

            // ---- copies
            Section();
            if (AllAre(q => q.Copyable))
            {
                Item(L.T("Duplica (Ctrl+D)"), DuplicateSelected);
                Item(L.T("Copia (Ctrl+C)"), async () => { await Task.Yield(); CopySelected(); });
            }
            // (15/11, Luca: «incollare su un gruppo le metta dentro quel gruppo») on a group: inside it (unless the group itself
            // is what was copied); on any other single object: next to it, in its group; with several selected: as Ctrl+V
            if (_clipboard.Count > 0)
            {
                bool intoGroup = !multi && k1.Model && (one.Kind == "group" || one.Kind == "file") && !_clipboard.Contains(one.Id);
                if (intoGroup) Item(L.T("Incolla qui dentro…"), () => PasteClipboard(one.Id));
                else if (!multi) Item(L.T("Incolla… (Ctrl+V)"), () => PasteClipboard(one.Parent));
                else Item(L.T("Incolla… (Ctrl+V)"), () => PasteClipboard(null));
            }

            // ---- groups
            Section();
            if (CanGroup(o)) Item(L.T("Raggruppa in un nuovo gruppo (Ctrl+G)"), GroupSelected);
            if (targets.All(tt => { var tk = new RowKind(tt); return tt.Parent != "" && !tk.Part && !tk.EcoGroup && !tk.Scree; }))
            {
                var outIds = targets.Select(tt => tt.Id).ToList();
                Item(L.T("Togli dal gruppo"), async () =>
                {
                    var arr = new JsonArray(outIds.Select(sid => (JsonNode)sid!).ToArray());
                    await Run(async api => { await api.Post("parent", new JsonObject { ["ids"] = arr, ["parent"] = "" }); });
                    await RefreshScene();
                });
            }
            if (!multi && k1.Model && (one.Kind == "group" || one.Kind == "file"))
                Item(L.T("Nuovo gruppo qui dentro"), async () => await AddObject("group", one.Id));
            Item(L.T("Nuovo gruppo vuoto"), async () => await AddObject("group", ""));
            // (only when it can do something: models only, at least two pieces with a surface - what the engine asks)
            if (CanMerge(o)) Item(L.T("Unisci in un solo oggetto"), MergeSelected);

            // ---- the model
            Section();
            if (fromView && !multi && material != "")
                Item(L.F("Modifica il materiale «{0}»", material), async () => await OpenMaterialEditor(material, o.Materials.Contains(material) ? o.Id : "", o.Materials.IndexOf(material)));
            if (!multi)
            {
                // (from the view the piece under the mouse stands for its model, unless the piece itself is what is selected)
                var root = fromView && !_selection.Contains(o.Id) ? ModelRootOf(o.Id) : o.Id;
                if (_scene.ById.TryGetValue(root, out var ro) && new RowKind(ro).Model && CanDecimate(ro))
                    Item(L.T("Ottimizza poligoni…"), async () => await OptimizePolygons(root));
            }
            if (!multi && (k1.Model || k1.Decal))
                Item(L.T("Cerca texture mancanti…"), async () => await FindTexturesIn(one.Source != "" ? System.IO.Path.GetDirectoryName(one.Source) : null));
            if (targets.All(tt => UsesLibraryModels(tt)))
                Item(L.T("Aggiorna dalla libreria…"), async () => await UpdateFromLibrary(targets.Select(tt => tt.Id).ToList()));

            // ---- the library
            Section();
            // (an object with scatters, a scatter, an ecosystem placed, the bench: into the ecosystems; a model: into the 3D models)
            var ecoBench = false;
            var ecoIds = !multi && (k.Scatter || k.EcoGroup || k.EcoLayer || k.Plot || k.Model || o.PaintModel != "") ? EcoScattersOf(o, out ecoBench) : null;
            if (ecoIds != null) Item(L.T("Salva nella libreria…"), async () => { await SaveEcosystemOf(ecoIds, ecoBench ? "" : o.Name); });
            // (15/11, Luca: «un'auto e le sue luci … deve finire nella libreria come modello con le luci come fatto sempre finora»)
            // a model goes into the library WITH the lights (and the decals) selected with it: at least one model, and nothing
            // that Simpler makes and keeps (ambience, terrain, ecosystem, distribution)
            else if (targets.Any(tt => new RowKind(tt).Model) && AllAre(q => q.Model || q.Decal || (q.Light && !q.Ambience)))
                Item(L.T("Salva nella libreria…"), SaveSelectionToLibrary);
            if (AllAre(q => q.Model)) Item(L.T("Converti in vegetazione"), async () => await SceneToVegetation(targets.Select(tt => tt.Id).ToList()));
            if (!multi && o.PaintModel != "")
                Item(L.T("Salva questo orientamento nella libreria"), async () => await OrientModel(o.PaintModel, "", "", ModelRootOf(o.Id)));

            // ---- delete
            Section();
            if (AllAre(q => !q.Part)) Item(L.T("Elimina (Canc)"), DeleteSelected);

            foreach (var sec in sections)
            {
                if (sec.Count == 0) continue;
                m.Items.Add(new Separator());
                foreach (var mi in sec) m.Items.Add(mi);
            }
            return m;
        }

        void ShowAddMenu(FrameworkElement anchor)
        {
            var m = new ContextMenu { PlacementTarget = anchor, Placement = System.Windows.Controls.Primitives.PlacementMode.Bottom };
            void Item(string text, string kind) { var i = new MenuItem { Header = text }; i.Click += async (_, __) => await AddObject(kind, ""); m.Items.Add(i); }
            Item(L.T("Luce ad area"), "area");
            Item(L.T("Faretto (spot)"), "spot");
            Item(L.T("Luce puntiforme"), "point");
            Item(L.T("Sole"), "sun");
            m.Items.Add(new Separator());
            Item(L.T("Gruppo vuoto"), "group");
            Item(L.T("Cubo"), "cube");
            Item(L.T("Sfera"), "sphere");
            Item(L.T("Cilindro"), "cylinder");
            Item(L.T("Piano"), "plane");
            Item(L.T("Toro"), "torus");
            m.IsOpen = true;
        }

        async Task<string> AddObject(string kind, string parent, JsonObject? at = null)
        {
            string newId = "";
            object body = new { kind, parent };
            // everything new appears in the middle of what you are looking at: objects on the surface at the centre
            // of the view, lights on the surface you point at, turned away from it (the sun keeps its direction).
            // at: the surface under a drop from the library instead of the centre of the view
            var vp = kind == "sun" ? null : at ?? await AskViewPoint();
            if (vp?["point"] is JsonArray pa && vp["camera"] is JsonArray ca && vp["normal"] is JsonArray na)
            {
                double[] P = { (double)pa[0]!, (double)pa[1]!, (double)pa[2]! };
                double[] C = { (double)ca[0]!, (double)ca[1]!, (double)ca[2]! };
                double[] N = { (double)na[0]!, (double)na[1]!, (double)na[2]! };
                var dist = Math.Max(1e-3, (double?)vp["distance"] ?? 100);
                // size of new objects: about a fifth of the distance you are looking from (not 1 m on a ring)
                var size = Math.Clamp(dist * 0.2, 0.5, 100.0);
                if (kind is "area" or "spot" or "point")
                {
                    // the light goes where you clicked: just off the surface (along its normal, so it is not inside
                    // it) and turned away from it - a click on a ceiling hangs a lamp lighting downwards
                    var off = Math.Clamp(dist * 0.02, 1.0, 20.0);
                    var reach = Math.Clamp(dist * 0.5, 30.0, 1000.0);
                    var loc = new[] { P[0] + N[0] * off, P[1] + N[1] * off, P[2] + N[2] * off };
                    var aim = new[] { loc[0] + N[0] * reach, loc[1] + N[1] * reach, loc[2] + N[2] * reach };
                    body = new { kind, parent, location = loc, aim, size };
                }
                else
                {
                    var half = kind == "group" ? 0 : (kind == "plane" ? 0.01 : size / 2);
                    var loc = new[] { P[0] + N[0] * half, P[1] + N[1] * half, P[2] + N[2] * half };
                    body = new { kind, parent, location = loc, size };
                }
            }
            // (a new light: the view prepares its shaders again - seconds on a big scene: «Occupato» at once)
            if (kind is "area" or "spot" or "point" or "sun")
                SendToWeb(new { type = "busyNow", what = L.T("Aggiunta della luce") });
            using var busy = BeginBusy();
            await Run(async api => { newId = (string?)(await api.Post("add", body))["id"] ?? ""; });
            if (parent != "") _expanded.Add(parent);
            SetSelectionRaw(newId);
            await RefreshScene();
            return newId;
        }

        readonly List<string> _selection = new List<string>();

        /// <summary>Sets the selection without refreshing anything (the caller refreshes).</summary>
        void SetSelectionRaw(string id)
        {
            _selection.Clear();
            if (id != "") _selection.Add(id);
            _selected = id;
        }

        bool _restoringSelection;

        void RememberSelection(List<string> before, string beforePrimary, List<string> after, string afterPrimary)
        {
            if (_api == null) return;
            var body = new JsonObject
            {
                ["before"] = new JsonObject { ["ids"] = new JsonArray(before.Select(i => (JsonNode)i).ToArray()), ["primary"] = beforePrimary },
                ["after"] = new JsonObject { ["ids"] = new JsonArray(after.Select(i => (JsonNode)i).ToArray()), ["primary"] = afterPrimary },
            };
            _ = Task.Run(async () =>
            {
                try
                {
                    var h = await _api.Post("selection/remember", body);
                    await Dispatcher.InvokeAsync(() => UpdateHistory(h));
                }
                catch (Exception ex) { AppLog.Write("selection not remembered: " + ex.Message); }
            });
        }

        void Select(string id) => SetSelection(id == "" ? Array.Empty<string>() : new[] { id }, id);

        void SetSelection(IEnumerable<string> ids, string primary)
        {
            var list = ids.Where(i => i != "" && _scene.ById.ContainsKey(i)).Distinct().ToList();
            var prim = list.Contains(primary) ? primary : (list.LastOrDefault() ?? "");
            if (prim == _selected && list.SequenceEqual(_selection)) return;
            // a selection of several objects lost (deselected, or replaced by another): a step of the undo history,
            // so Ctrl+Z brings it back. Clicking from one object to another, or adding to the selection, is not
            var lost = _selection.Where(i => !list.Contains(i) && _scene.ById.ContainsKey(i)).Count();
            if (lost >= 2 && !_restoringSelection) RememberSelection(_selection.ToList(), _selected, list, prim);
            var before = new HashSet<string>(_selection) { _selected };
            _selection.Clear();
            _selection.AddRange(list);
            _selected = prim;
            if (Painting && prim != "" && _scene.ById.TryGetValue(prim, out var pobj))
            {
                // a distribution chosen in the tree while the brush is on: the next strokes continue it
                var pg = new[] { pobj }.Concat(_scene.Ancestors(pobj)).FirstOrDefault(x => x.Paint && x.Eco == "");
                if (pg != null && pg.Id != _paintGroup) SwitchPaintGroup(pg.Id);
            }

            int expBefore = _expanded.Count, instBefore = _expandedInst.Count;
            foreach (var id in list)
                if (_scene.ById.TryGetValue(id, out var o))
                {
                    foreach (var a in _scene.Ancestors(o)) _expanded.Add(a.Id);
                    // an instance listed under its original: open that list, so the selected row is visible
                    foreach (var x in new[] { o }.Concat(_scene.Ancestors(o)))
                        if (x.InstanceOf != "" && _scene.ById.TryGetValue(x.InstanceOf, out var org) && org.Parent == x.Parent) _expandedInst.Add(org.Id);
                }
            // material editor open and the new selection has no material (a light, a group, nothing): back to the
            // properties, so the panel always speaks of what is selected (a light shows its parameters right away)
            if ((_rightPanel == "material" || _rightPanel == "materials") &&
                !(_scene.ById.TryGetValue(prim, out var po) && po.IsMesh && po.Materials.Any(m => m != "")))
                _rightPanel = "";
            var sw = System.Diagnostics.Stopwatch.StartNew();
            // no row to open and every chosen row already drawn (or a filter on): only the look of the rows changes
            bool filtered = _treeSearch.Text.Trim().Length > 0 || _treeType != "";
            if (_rowLook.Count > 0 && _expanded.Count == expBefore && _expandedInst.Count == instBefore
                && (filtered || list.All(_rowLook.ContainsKey)))
            {
                _selSet = new HashSet<string>(list);
                before.UnionWith(list);
                foreach (var id in before)
                    if (_rowLook.TryGetValue(id, out var look)) look();
            }
            else RenderTree();
            var tTree = sw.ElapsedMilliseconds;
            RenderProps();
            var tProps = sw.ElapsedMilliseconds - tTree;
            UpdateGizmo();
            _ = SyncOpenModel();          // a part of a library model: the model opens (its parts in the view)
            // (a slow click on an object: what took the time, in app.log)
            if (sw.ElapsedMilliseconds > 250)
                AppLog.Write($"selection: tree {tTree} ms ({_treeRows.Children.Count} rows), panel {tProps} ms, total {sw.ElapsedMilliseconds} ms");
        }

        /// <summary>A piece picked in the tree while the material editor is open: the editor follows it (its first
        /// material, unless the one shown is already one of its materials).</summary>
        void FollowMaterialFromTree()
        {
            if (_rightPanel != "material" || _selection.Count != 1 || !_scene.ById.TryGetValue(_selected, out var o) || !o.IsMesh) return;
            if (o.Materials.Contains(_matName)) return;
            var first = o.Materials.FirstOrDefault(m => m != "");
            if (first != null) _ = OpenMaterialEditor(first, o.Id, o.Materials.IndexOf(first));
        }

        /// <summary>Context menu on a row: keep a multi-selection if the row is part of it.</summary>
        void EnsureSelected(string id)
        {
            if (!_selection.Contains(id)) Select(id);
        }

        /// <summary>Click in the tree: Ctrl adds/removes, Shift selects the range of visible rows.</summary>
        void TreeClick(string id)
        {
            var mods = Keyboard.Modifiers;
            if (mods.HasFlag(ModifierKeys.Control))
            {
                var list = new List<string>(_selection);
                if (!list.Remove(id)) list.Add(id);
                SetSelection(list, list.Contains(id) ? id : _selected);
            }
            else if (mods.HasFlag(ModifierKeys.Shift) && _selected != "")
            {
                var rows = _treeRows.Children.OfType<FrameworkElement>().Select(r => r.Tag as string).Where(t => t != null).Cast<string>().ToList();
                int a = rows.IndexOf(_selected), b = rows.IndexOf(id);
                if (a < 0 || b < 0) { Select(id); return; }
                var range = rows.GetRange(Math.Min(a, b), Math.Abs(a - b) + 1);
                SetSelection(_selection.Concat(range), id);
            }
            else
            {
                Select(id);
                // a distribution clicked in the tree: its panel opens with its models and settings, ready to change
                // it or to paint more (the brush is on; Esc or the tool buttons leave it)
                if (_scene.ById.TryGetValue(id, out var pg))
                {
                    bool inScatter = new[] { pg }.Concat(_scene.Ancestors(pg)).Any(x => x.Paint);
                    bool inEco = new[] { pg }.Concat(_scene.Ancestors(pg)).Any(x => x.Eco is "group" or "layer");
                    if (inEco) { if (Painting) SetTool("move"); _ = ShowRightPanel("ecosystem"); }
                    else if (!Painting && pg.Paint) SetTool("paint");
                    else if (Painting && !inScatter) SetTool("move");      // another object: its properties
                }
            }
            FollowMaterialFromTree();
        }

        void SelectAll()
        {
            var ids = _scene.Roots.Where(o => !o.IsAmbience && !o.Name.StartsWith(L.T("Pavimento"), StringComparison.OrdinalIgnoreCase)).Select(o => o.Id);
            SetSelection(ids, _selected);
        }

        /// <summary>Selection made by clicking in the 3D view.</summary>
        void SelectFromViewport(IEnumerable<string> ids, string primary)
        {
            SetSelection(ids, primary);
            if (primary != "") ScrollTreeTo(primary);
        }

        void ScrollTreeTo(string id)
        {
            foreach (FrameworkElement row in _treeRows.Children)
                if (row.Tag as string == id) { row.BringIntoView(); break; }
        }

        // ---------------------------------------------------------------- rename in place (long press or F2)
        System.Windows.Threading.DispatcherTimer? _longPress;
        string _longPressId = "";

        void StartLongPress(string id)
        {
            _longPressId = id;
            _longPress ??= new System.Windows.Threading.DispatcherTimer(TimeSpan.FromMilliseconds(650), System.Windows.Threading.DispatcherPriority.Input, (_, __) =>
            {
                _longPress!.Stop();
                // still pressed on the same row and not dragging: rename
                if (Mouse.LeftButton == MouseButtonState.Pressed && _dragId == _longPressId) { _dragId = ""; BeginRename(_longPressId); }
            }, Dispatcher);
            _longPress.Stop();
            _longPress.Start();
        }

        void BeginRename(string id)
        {
            if (!_scene.ById.TryGetValue(id, out var o)) return;
            var row = _treeRows.Children.OfType<Grid>().FirstOrDefault(g => g.Tag as string == id);
            var label = row?.Children.OfType<TextBlock>().FirstOrDefault(t => t.Tag as string == "name");
            if (row == null || label == null) return;
            var box = Theme.Input(o.Name);
            box.Margin = new Thickness(2, 2, 4, 2);
            box.Padding = new Thickness(4, 1, 4, 1);
            Grid.SetColumn(box, Grid.GetColumn(label));
            label.Visibility = Visibility.Collapsed;
            row.Children.Add(box);
            bool done = false;
            async Task Finish(bool commit)
            {
                if (done) return;
                done = true;
                var text = box.Text.Trim();
                if (commit && text != "" && text != o.Name)
                {
                    await Run(async api => { await api.Post("rename", new { id, name = text }); });
                    await RefreshScene();
                }
                else RenderTree();
            }
            box.KeyDown += async (_, e) =>
            {
                if (e.Key == Key.Enter) { e.Handled = true; await Finish(true); }
                else if (e.Key == Key.Escape) { e.Handled = true; await Finish(false); }
            };
            box.LostKeyboardFocus += async (_, __) => await Finish(true);
            box.Focus();
            box.SelectAll();
        }

        /// <summary>Selected objects without those inside another selected object.</summary>
        List<SceneObject> TopLevelSelection()
        {
            var set = new HashSet<string>(_selection);
            return _selection.Where(id => _scene.ById.ContainsKey(id)).Select(id => _scene.ById[id])
                .Where(o => !_scene.Ancestors(o).Any(a => set.Contains(a.Id))).ToList();
        }

        async Task DeleteSelected()
        {
            var objs = TopLevelSelection();
            if (objs.Count == 0) return;
            // (1.78.5, Luca: «non chiedere MAI conferma, tanto se uno cancella per sbaglio fa Ctrl+Z») no question: it was
            // asked only for objects with pieces inside, so for some imported models yes and for others no
            using var busy = BeginBusy();
            _reloadOrigin = "action";
            await Run(async api => { await api.Post("delete", new { ids = objs.Select(o => o.Id).ToArray() }); });
            SetSelectionRaw("");
            await RefreshScene();
            Status(objs.Count == 1 ? L.F("Eliminato: {0}  (Ctrl+Z per annullare)", objs[0].Name) : L.F("Eliminati {0} oggetti  (Ctrl+Z per annullare)", objs.Count));
        }

        /// <summary>The objects a command of the row menu would work on: the selection when the row is in it, else the row.</summary>
        List<SceneObject> MenuTargets(SceneObject o)
        {
            var tops = TopLevelSelection();
            bool inside = _selection.Contains(o.Id) || _scene.Ancestors(o).Any(anc => _selection.Contains(anc.Id));
            return inside && tops.Count > 0 ? tops : new List<SceneObject> { o };
        }

        static void Subtree(SceneObject o, List<SceneObject> into)
        {
            into.Add(o);
            foreach (var c in o.Children) Subtree(c, into);
        }

        /// <summary>«Unisci in un solo oggetto» has something to do: only models, nothing the engine refuses inside (a
        /// distribution, a decal), and at least two pieces with a surface in all.</summary>
        bool CanMerge(SceneObject o)
        {
            var tops = MenuTargets(o);
            if (tops.Count == 0 || tops.Any(t => !new RowKind(t).Model)) return false;
            var all = new List<SceneObject>();
            foreach (var t in tops) Subtree(t, all);
            if (all.Any(x => x.Paint || x.Kind == "decal")) return false;
            return all.Count(x => x.Kind == "mesh") >= 2;
        }

        /// <summary>«Raggruppa»: models, lights of the scene and decals - not what Simpler makes and keeps (ambience, parts of
        /// a terrain or of an ecosystem, distributions).</summary>
        bool CanGroup(SceneObject o)
        {
            var tops = MenuTargets(o);
            return tops.Count > 0 && tops.All(t => { var k = new RowKind(t); return k.Model || k.Decal || (k.Light && !k.Ambience); });
        }

        /// <summary>«Raggruppa in un nuovo gruppo»: a new group where the selected objects are (in their group when they share
        /// one, else at the top of the tree) and the objects moved inside it; they stay where they are in the scene.</summary>
        async Task GroupSelected()
        {
            var objs = TopLevelSelection();
            if (objs.Count == 0 || !CanGroup(objs[0])) return;
            var ids = objs.Select(x => x.Id).ToList();
            var parent = objs.All(x => x.Parent == objs[0].Parent) ? objs[0].Parent : "";
            var gid = await AddObject("group", parent);
            if (gid == "") return;
            using var busy = BeginBusy();
            var idArray = new JsonArray(ids.Select(x => (JsonNode)x!).ToArray());
            await Run(async api => { await api.Post("parent", new JsonObject { ["ids"] = idArray, ["parent"] = gid }); });
            _expanded.Add(gid);
            SetSelectionRaw(gid);
            await RefreshScene();
            Status(L.F("{0} oggetti nel nuovo gruppo: trascina altri oggetti sulla sua riga per aggiungerli", ids.Count));
        }

        /// <summary>«Unisci in un solo oggetto»: the selected objects (a group, a model, several pieces) become one object
        /// with all their materials; the originals go to the trash (Ctrl+Z puts them back).</summary>
        async Task MergeSelected()
        {
            var objs = TopLevelSelection();
            if (objs.Count == 0) return;
            using var busy = BeginBusy();
            _reloadOrigin = "action";
            string newId = "";
            int pieces = 0;
            await Run(async api =>
            {
                var r = await api.Post("merge", new { ids = objs.Select(o => o.Id).ToArray() });
                newId = (string?)r["id"] ?? "";
                pieces = (int?)r["pieces"] ?? 0;
            });
            await RefreshScene();
            if (newId == "") return;
            SetSelection(new[] { newId }, newId);
            Status(L.F("Uniti {0} pezzi in un solo oggetto  (Ctrl+Z per annullare)", pieces));
        }

        /// <summary>«Libera memoria»: what would go (GET memory), a question, then POST memory/purge.</summary>
        async Task PurgeMemory()
        {
            JsonObject? p = null;
            await Run(async api => { p = await api.Get("memory"); });
            if (p == null) return;
            int I(string k) => (int?)p[k] ?? 0;
            var mb = (double?)p["mb"] ?? 0;
            int things = I("objects") + I("materials") + I("images") + I("meshes") + I("other");
            if (things == 0 && I("undo") == 0)
            {
                Msg.Show(this, L.T("Non c'è niente da liberare: tutto quello che è in memoria è usato dalla scena."), "Simpler", MessageBoxButton.OK, MessageBoxImage.Information);
                return;
            }
            var text = L.F("Verranno tolti dalla memoria:\n• {0} oggetti eliminati (tenuti per l'annulla)\n• {1} materiali, {2} texture e {3} geometrie non più usati ({4} MB circa)\n\nLa cronologia di annulla (Ctrl+Z) verrà azzerata: non si potrà più tornare indietro alle modifiche fatte finora. La scena non cambia.\n\nProcedere?",
                           I("objects"), I("materials"), I("images"), I("meshes") + I("other"), Math.Round(mb).ToString("0"));
            if (Msg.Show(this, text, L.T("Libera memoria"), MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
            using var busy = BeginBusy();
            JsonObject? r = null;
            await Run(async api => { r = await api.Post("memory/purge", new { }); });
            await RefreshScene();
            if (r?["gone"] is JsonObject g)
            {
                int G(string k) => (int?)g[k] ?? 0;
                Status(L.F("Memoria liberata: {0} oggetti, {1} materiali, {2} texture, {3} geometrie", G("objects"), G("materials"), G("images"), G("meshes")));
            }
        }

        static IEnumerable<SceneObject> Descendants(SceneObject o) => o.Children.SelectMany(c => new[] { c }.Concat(Descendants(c)));

        async Task DuplicateSelected()
        {
            var objs = TopLevelSelection();
            if (objs.Count == 0) return;
            var created = new List<string>();
            using var busy = BeginBusy();
            _reloadOrigin = "action";
            await Run(async api =>
            {
                foreach (var o in objs)
                {
                    var r = await api.Post("duplicate", new { id = o.Id });
                    var id = (string?)r["id"] ?? "";
                    if (id != "") created.Add(id);
                    // the viewer copies what it already shows: no new export of the scene
                    if (r["copies"] is JsonObject copies && WithoutPainted(copies) is { Count: > 0 } shown && shown.All(kv => _viewerIds.Contains((string?)kv.Value ?? "")))
                    {
                        SendToWeb(new { type = "clone", copies = shown });
                        foreach (var kv in copies) _viewerIds.Add(kv.Key);
                    }
                }
            });
            await RefreshScene();
            if (created.Count > 0) SetSelection(created, created[^1]);
        }
    }
}
