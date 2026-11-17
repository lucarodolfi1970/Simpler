using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;

namespace Simpler
{
    /// <summary>
    /// Copy, paste and Shift-drag copies. Two kinds of copy, as Blender allows:
    ///  · istanza: the copies share geometry and materials with the original (linked duplicate). Cycles draws them as
    ///    instances of one mesh: almost no memory even with thousands (a forest, a row of chairs);
    ///  · copia indipendente: every copy has its own geometry: materials can be changed on each one, memory as the
    ///    original.
    /// Shift held while starting a gizmo drag: the original stays, at release Simpler asks kind and quantity; copy k is
    /// placed at k times the movement of the drag (a rotation gives copies in a circle around the pivot).
    /// </summary>
    public sealed partial class MainWindow
    {
        readonly List<string> _clipboard = new();
        string _dupMode = "instance";
        int _dupCount = 1;

        void CopySelected()
        {
            var objs = TopLevelSelection();
            if (objs.Count == 0) { Status(L.T("Seleziona qualcosa da copiare"), true); return; }
            _clipboard.Clear();
            _clipboard.AddRange(objs.Select(o => o.Id));
            Status(objs.Count == 1 ? L.F("Copiato: {0}  (Ctrl+V per incollare)", objs[0].Name) : L.F("Copiati {0} oggetti  (Ctrl+V per incollare)", objs.Count));
        }

        /// <summary>(15/11, Luca) into: where the copies go in the tree - null: next to their originals (Ctrl+V, as always);
        /// "": at the top of the tree (the menu of the empty part); an id: inside that group (the menu on a group).
        /// In the scene they are always placed side by side along X, next to the originals.</summary>
        Task PasteClipboard() => PasteClipboard(null);

        async Task PasteClipboard(string? into)
        {
            var ids = _clipboard.Where(id => _scene.ById.ContainsKey(id)).ToList();
            if (ids.Count == 0) { Status(L.T("Niente da incollare: copia prima qualcosa con Ctrl+C"), true); return; }
            var name = ids.Count == 1 ? _scene.ById[ids[0]].Name : L.F("{0} oggetti", ids.Count);
            var ans = DuplicateDialog.Ask(this, L.T("Incolla"), name, _dupMode, _dupCount,
                                          L.T("Le copie vengono messe una accanto all'altra lungo l'asse X (rosso): poi spostale con il gizmo."));
            if (ans == null) return;
            await MakeCopies(ids, ans.Value.mode, ans.Value.count, null, into);
        }

        /// <summary>From the viewer: a gizmo drag started with Shift was released.</summary>
        async Task OnShiftCopy(List<string> ids, JsonArray delta)
        {
            ids = ids.Where(id => _scene.ById.ContainsKey(id)).ToList();
            if (ids.Count == 0) return;
            var name = ids.Count == 1 ? _scene.ById[ids[0]].Name : L.F("{0} oggetti", ids.Count);
            var ans = DuplicateDialog.Ask(this, L.T("Copia con trascinamento"), name, _dupMode, _dupCount,
                                          L.T("La prima copia va dove hai lasciato il mouse; le successive continuano alla stessa distanza e nella stessa direzione (con una rotazione: in cerchio attorno al centro del gizmo)."));
            if (ans == null) return;
            await MakeCopies(ids, ans.Value.mode, ans.Value.count, delta);
        }

        async Task MakeCopies(List<string> ids, string mode, int count, JsonArray? delta, string? into = null)
        {
            _dupMode = mode; _dupCount = count;
            var body = new JsonObject
            {
                ["ids"] = new JsonArray(ids.Select(i => (JsonNode)i!).ToArray()), ["mode"] = mode, ["count"] = count,
            };
            if (delta != null) body["delta"] = delta.DeepClone(); else body["row"] = true;
            JsonObject? r = null;
            using (BeginBusy())
            {
                _reloadOrigin = "action";
                await Run(async api => { r = await api.Post("duplicate/many", body); });
                if (r == null) return;
                // (into a group or to the top of the tree: the copies keep their place in the scene, only their row moves)
                if (into != null && r["ids"] is JsonArray made && made.Count > 0 && (into == "" || _scene.ById.ContainsKey(into)))
                {
                    var moved = new JsonArray(made.Select(n => (JsonNode)((string?)n ?? "")!).ToArray());
                    await Run(async api => { await api.Post("parent", new JsonObject { ["ids"] = moved, ["parent"] = into }); });
                    if (into != "") _expanded.Add(into);
                }
                // the viewer copies what it already shows: no new export of the scene
                if (r["copies"] is JsonObject copies && WithoutPainted(copies) is { Count: > 0 } shown && shown.All(kv => _viewerIds.Contains((string?)kv.Value ?? "")))
                {
                    SendToWeb(new { type = "clone", copies = shown });
                    foreach (var kv in copies) _viewerIds.Add(kv.Key);
                }
                await RefreshScene();
            }
            var created = (r["ids"] as JsonArray)?.Select(n => (string?)n ?? "").Where(x => x != "").ToList() ?? new List<string>();
            if (created.Count > 0) SetSelection(created, created[^1]);
            Status(L.F("{0} copie create ({1})", created.Count, mode == "copy" ? L.T("copie indipendenti") : L.T("istanze")));
        }

        /// <summary>Kind of copy and how many.</summary>
        sealed class DuplicateDialog : ThemedDialog
        {
            string _mode;
            readonly TextBox _count;
            bool _ok;

            public static (string mode, int count)? Ask(Window owner, string title, string what, string mode, int count, string note)
            {
                var d = new DuplicateDialog(title, what, mode, count, note) { Owner = owner };
                d.ShowDialog();
                if (!d._ok) return null;
                return (d._mode, Math.Clamp(int.TryParse(d._count.Text.Trim(), out var n) ? n : 1, 1, 2000));
            }

            DuplicateDialog(string title, string what, string mode, int count, string note) : base(title, 520)
            {
                _mode = mode;
                Body.Children.Add(Theme.Label(title, 17, Theme.Text, FontWeights.SemiBold));
                var sub = Theme.Label(what, 12, Theme.TextMuted);
                sub.Margin = new Thickness(0, 4, 0, 14);
                Body.Children.Add(sub);

                var cards = new UniformGrid2(2);
                Border inst = null!, copy = null!;
                Border Card(string id, string head, string text)
                {
                    var sp = new StackPanel();
                    sp.Children.Add(Theme.Label(head, 13.5, Theme.Text, FontWeights.SemiBold));
                    var t = Theme.Label(text, 11.5, Theme.TextMuted);
                    t.TextWrapping = TextWrapping.Wrap;
                    t.Margin = new Thickness(0, 6, 0, 0);
                    sp.Children.Add(t);
                    var b = new Border { CornerRadius = new CornerRadius(8), Padding = new Thickness(12, 10, 12, 12), Margin = new Thickness(0, 0, 8, 0),
                                         Cursor = Cursors.Hand, Child = sp, BorderThickness = new Thickness(1.5), Tag = id };
                    b.MouseLeftButtonUp += (_, __) => { _mode = id; Paint(); };
                    b.MouseLeftButtonDown += (_, e) => { if (e.ClickCount == 2) { _mode = id; Confirm(); } };
                    return b;
                }
                inst = Card("instance", L.T("Istanza"),
                    L.T("Le copie condividono forma e materiali con l'originale: quasi nessuna memoria in più, anche con migliaia di copie (alberi, sedie, lampioni). Cambiare il materiale di una cambia tutte."));
                copy = Card("copy", L.T("Copia indipendente"),
                    L.T("Ogni copia ha la sua geometria: puoi cambiarne i materiali una per una. Occupa memoria come l'originale per ogni copia."));
                cards.Add(inst); cards.Add(copy);
                void Paint()
                {
                    foreach (var c in new[] { inst, copy })
                    {
                        var on = (string)c.Tag == _mode;
                        c.Background = Theme.B(on ? "#13284A" : "#0E1A30");
                        c.BorderBrush = on ? Theme.B(Theme.Accent) : Theme.B("#1E2F50");
                    }
                }
                Paint();
                Body.Children.Add(cards.Panel);

                var row = new DockPanel { Margin = new Thickness(0, 14, 0, 0) };
                var lab = Theme.Label(L.T("Quantità"), 12.5, Theme.TextSoft);
                lab.VerticalAlignment = VerticalAlignment.Center;
                lab.Width = 90;
                row.Children.Add(lab);
                _count = Theme.Input(count.ToString(), true);
                _count.Width = 80;
                _count.HorizontalAlignment = HorizontalAlignment.Left;
                _count.KeyDown += (_, e) => { if (e.Key == Key.Enter) Confirm(); };
                row.Children.Add(_count);
                Body.Children.Add(row);
                var n = Theme.Label(note, 11.5, Theme.TextFaint);
                n.TextWrapping = TextWrapping.Wrap;
                n.Margin = new Thickness(0, 10, 0, 0);
                Body.Children.Add(n);

                var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 18, 0, 0) };
                var cancel = Theme.Button(L.T("Annulla"), Theme.Kind.Normal);
                cancel.Click += (_, __) => Close();
                var ok = Theme.Button(L.T("Crea le copie"), Theme.Kind.Primary);
                ok.Margin = new Thickness(8, 0, 0, 0);
                ok.Click += (_, __) => Confirm();
                buttons.Children.Add(cancel);
                buttons.Children.Add(ok);
                Body.Children.Add(buttons);
                Loaded += (_, __) => { _count.Focus(); _count.SelectAll(); };
                PreviewKeyDown += (_, e) => { if (e.Key == Key.Escape) Close(); };
            }

            void Confirm() { _ok = true; Close(); }
        }

        /// <summary>Two equal columns (WPF UniformGrid without the namespace clutter).</summary>
        sealed class UniformGrid2
        {
            public readonly System.Windows.Controls.Primitives.UniformGrid Panel;
            public UniformGrid2(int columns) { Panel = new System.Windows.Controls.Primitives.UniformGrid { Columns = columns }; }
            public void Add(UIElement e) => Panel.Children.Add(e);
        }
    }
}
