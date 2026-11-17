using System;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;

namespace Simpler
{
    /// <summary>
    /// Pieces of a library model. In the 3D view a library model is drawn from its prototype (its parts merged by
    /// material): a part could not be picked, outlined alone or moved. Selecting a part (in the tree, or in the view
    /// with a second click on a model already selected) "opens" the model: the engine takes the library mark off it
    /// (scene_ops.open_model) and the view gets its parts one by one; they are outlined in light blue and behave like
    /// any piece (move, material, delete). When the selection leaves the model it is closed again and drawn from its
    /// prototype (a new one if something changed). One model open at a time.
    /// </summary>
    public partial class MainWindow
    {
        bool _openBusy, _openAgain;

        /// <summary>The root of the library model that must be open for this piece; "" when none (the piece is not
        /// inside a model, it is a model chosen as a whole, or a piece of a distribution).</summary>
        string OpenTargetRoot(string id)
        {
            if (!_scene.ById.TryGetValue(id, out var o)) return "";
            var chain = new[] { o }.Concat(_scene.Ancestors(o)).ToList();
            var open = chain.FirstOrDefault(x => x.OpenModel);
            if (open != null) return open.Id;
            var root = chain.LastOrDefault(x => x.PaintModel != "");
            if (root == null || root == o) return "";
            if (root.Parent != "" && _scene.ById.TryGetValue(root.Parent, out var rp) && rp.Paint) return "";
            return root.Id;
        }

        /// <summary>After every change of selection: opens the model whose part is selected, closes the one left.</summary>
        async Task SyncOpenModel()
        {
            if (_api == null) return;
            if (_openBusy) { _openAgain = true; return; }
            _openBusy = true;
            try
            {
                do
                {
                    _openAgain = false;
                    var roots = _selection.Select(OpenTargetRoot).Distinct().ToList();
                    var want = roots.Count == 1 ? roots[0] : "";
                    var now = _scene.ById.Values.FirstOrDefault(o => o.OpenModel)?.Id ?? "";
                    if (want == now) continue;
                    bool changed = false;
                    await Run(async api =>
                    {
                        var r = want != "" ? await api.Post("model/open", new { id = want })
                                           : await api.Post("model/close", new { });
                        changed = (bool?)r["changed"] ?? false;
                    });
                    if (changed) await RefreshScene();
                } while (_openAgain);
            }
            finally { _openBusy = false; }
        }

        /// <summary>Second click on a selected library model in the view: open it and pick the part under the mouse.</summary>
        async Task PickInsideModel(string id)
        {
            if (_api == null || !_scene.ById.TryGetValue(id, out var o) || o.PaintModel == "") return;
            if (o.Parent != "" && _scene.ById.TryGetValue(o.Parent, out var p) && p.Paint) return;      // (a distribution)
            bool changed = false;
            await Run(async api =>
            {
                var r = await api.Post("model/open", new { id });
                changed = (bool?)r["changed"] ?? false;
            });
            if (changed) await RefreshScene();
            SendToWeb(new { type = "pickAt", root = id });      // (after the parts: the view picks where it was clicked)
        }
    }
}
