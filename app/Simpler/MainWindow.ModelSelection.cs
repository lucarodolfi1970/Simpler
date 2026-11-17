using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace Simpler
{
    /// <summary>
    /// Several 3D models of the library at once: Ctrl+clic selects them (an accent border), the right click on one of
    /// them gives Taglia, Copia, Sposta in, Elimina for all of them; Incolla (on a folder or on the empty part of the
    /// library) moves or copies them there. While models are selected nothing goes into the view: a plain click clears
    /// the selection. Deleting and pasting ask first.
    /// </summary>
    public partial class MainWindow
    {
        readonly HashSet<string> _modelSel = new();
        readonly Dictionary<string, Button> _modelTiles = new();
        string _modelSelPlace = "";

        void ShowModelSelected(Button b, bool on)
        {
            b.BorderBrush = on ? Theme.B(Theme.Accent) : Theme.B(Theme.Line);
            b.BorderThickness = new Thickness(on ? 2 : 1);
        }

        void ToggleModelSelection(string id)
        {
            if (!_modelSel.Remove(id)) _modelSel.Add(id);
            if (_modelTiles.TryGetValue(id, out var b)) ShowModelSelected(b, _modelSel.Contains(id));
            Status(_modelSel.Count > 0
                ? L.F("{0} modelli selezionati · tasto destro su uno di loro: taglia, copia, sposta, elimina · clic senza Ctrl: togli la selezione", _modelSel.Count)
                : L.T("Nessun modello selezionato"));
        }

        void ClearModelSelection()
        {
            foreach (var id in _modelSel.ToList())
                if (_modelTiles.TryGetValue(id, out var b)) ShowModelSelected(b, false);
            _modelSel.Clear();
            Status(L.T("Selezione dei modelli tolta"));
        }

        string ModelName(string id) => (string?)_models.OfType<JsonObject>().FirstOrDefault(x => (string?)x["id"] == id)?["name"] ?? id;

        ContextMenu SelectionMenu()
        {
            var ids = _modelSel.ToList();
            var m = new ContextMenu();
            void Item(string text, Func<Task> act) { var i = new MenuItem { Header = text }; i.Click += async (_, __) => await act(); m.Items.Add(i); }
            if (ids.Any(ReadOnlyModel))
            {
                // (models of Simpler among them, locked: copied into one's own folders, nothing else)
                Item(L.F("Copia {0} modelli", ids.Count), () => { CopyModels(ids); return Task.CompletedTask; });
                m.Items.Add(new Separator());
                Item(L.T("Togli la selezione"), () => { ClearModelSelection(); return Task.CompletedTask; });
                return m;
            }
            Item(L.F("Taglia {0} modelli", ids.Count), () =>
            {
                _libClip = new LibClip("model", false, ids[0], L.F("{0} modelli", ids.Count), ids.ToArray());
                Status(L.F("Tagliati {0} modelli · apri la cartella dove vuoi metterli e scegli «Incolla» (tasto destro)", ids.Count));
                RenderLibrary();
                return Task.CompletedTask;
            });
            Item(L.F("Copia {0} modelli", ids.Count), () => { CopyModels(ids); return Task.CompletedTask; });
            // move into a folder
            var move = new MenuItem { Header = L.F("Sposta {0} modelli in", ids.Count) };
            void Target(string folder, string label)
            {
                var i = new MenuItem { Header = label };
                i.Click += async (_, __) => await MoveModels(ids, folder);
                move.Items.Add(i);
            }
            Target("", L.T("I miei (cartella principale)"));
            foreach (var f in ScopeFolders("model").OrderBy(f => f, StringComparer.CurrentCultureIgnoreCase))
                if (!ReadOnlyFolder(f)) Target(f, new string(' ', 4 * f.Count(c => c == '/')) + FolderName(f));
            m.Items.Add(move);
            Item(L.F("Converti {0} modelli in vegetazione", ids.Count), async () => await ConvertToVegetation(ids));
            m.Items.Add(new Separator());
            Item(L.F("Elimina {0} modelli dalla libreria", ids.Count), async () => await DeleteModels(ids));
            m.Items.Add(new Separator());
            Item(L.T("Togli la selezione"), () => { ClearModelSelection(); return Task.CompletedTask; });
            return m;
        }

        void CopyModels(IList<string> ids)
        {
            var label = ids.Count == 1 ? ModelName(ids[0]) : L.F("{0} modelli", ids.Count);
            _libClip = new LibClip("model", false, ids[0], label, ids.ToArray(), Copy: true);
            Status(L.F("Copiato: {0} · apri la cartella dove vuoi la copia e scegli «Incolla» (tasto destro)", label));
            RenderLibrary();
        }

        async Task MoveModels(IList<string> ids, string folder)
        {
            if (ReadOnlyFolder(folder) || ids.Any(ReadOnlyModel)) { Status(L.T("Le cartelle Simpler sono di sola lettura"), true); return; }
            var todo = ids.Where(id => _models.OfType<JsonObject>().Any(x => (string?)x["id"] == id && ((string?)x["folder"] ?? "") != folder)).ToList();
            if (todo.Count == 0) return;
            var where = folder == "" ? L.T("Modelli 3D") : folder;
            if (todo.Count > 1 && Msg.Show(this, L.F("Spostare {0} modelli in «{1}»?", todo.Count, where), "Simpler",
                                           MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
            await Run(async api => { foreach (var id in todo) await api.Post("models/move", new { id, folder }); });
            _modelSel.Clear();
            Status(L.F("{0} modelli spostati in {1}", todo.Count, where));
            await ReloadModels();
        }

        async Task PasteModels(LibClip c, string target)
        {
            var ids = c.Keys ?? new[] { c.Key };
            var where = target == "" ? L.T("Modelli 3D") : target;
            if (!c.Copy)
            {
                _libClip = null;
                await MoveModels(ids, target);
                RenderLibrary();
                return;
            }
            var q = ids.Length == 1 ? L.F("Copiare «{0}» in «{1}»?", ModelName(ids[0]), where) : L.F("Copiare {0} modelli in «{1}»?", ids.Length, where);
            if (Msg.Show(this, q + "\n" + L.T("Ogni copia occupa sul disco quanto l'originale (modello e texture)."), "Simpler",
                         MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
            int n = 0;
            using (BeginBusy())
            {
                ShowTask(L.F("Copia di {0} modelli…", ids.Length));
                await Run(async api => { foreach (var id in ids) { await api.Post("models/copy", new { id, folder = target }); n++; } });
                HideTask();
            }
            Status(L.F("{0} modelli copiati in {1}", n, where));
            await ReloadModels();
        }

        async Task DeleteModels(IList<string> ids)
        {
            var names = string.Join("\n", ids.Take(8).Select(id => "• " + ModelName(id))) + (ids.Count > 8 ? "\n…" : "");
            if (Msg.Show(this, L.F("Eliminare {0} modelli dalla libreria?\n\n{1}\n\nGli oggetti già inseriti nelle scene restano.", ids.Count, names),
                         "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Warning) != MessageBoxResult.Yes) return;
            await Run(async api => { foreach (var id in ids) await api.Post("models/delete", new { id }); });
            _modelSel.Clear();
            if (_libClip?.Keys != null && _libClip.Keys.Any(ids.Contains)) _libClip = null;
            Status(L.F("{0} modelli eliminati dalla libreria", ids.Count));
            await ReloadModels();
        }
    }
}
