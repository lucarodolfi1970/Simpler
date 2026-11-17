using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;

namespace Simpler
{
    /// <summary>
    /// Lamps and emissive materials "Dal tramonto all'alba" (engine dusk.py): when the hour of the Ambiente, an undo or
    /// a saved view switches an emission on or off, the scene carries "emitLit" {material: 0/1}; the materials whose
    /// switch changed are drawn again in the real-time view (lamps follow by themselves: their "lit" comes with the sync).
    /// </summary>
    public partial class MainWindow
    {
        Dictionary<string, int> _emitLit = new();

        async Task PushSwitchedEmissions(JsonObject sceneJson)
        {
            if (sceneJson["emitLit"] is not JsonObject lit) return;
            var now = lit.ToDictionary(kv => kv.Key, kv => (int?)kv.Value ?? 1);
            var changed = now.Where(kv => _emitLit.TryGetValue(kv.Key, out var before) && before != kv.Value).Select(kv => kv.Key).ToList();
            _emitLit = now;
            foreach (var name in changed) await PushMaterialToViewer(name);
        }
    }
}
