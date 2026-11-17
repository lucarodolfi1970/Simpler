using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;

namespace Simpler
{
    /// <summary>
    /// Pivot placed by hand: the button next to the tools turns the gizmo violet; moving it moves only the gizmo
    /// (the model stays); its place is kept as the pivot of the whole model (the top of its hierarchy) - engine
    /// POST pivot, simpler_pivot in the model's own space - and from then on its gizmo stands there. Clicked again,
    /// the gizmo is back to normal. Properties ▸ Trasformazione can put the automatic pivot back.
    /// </summary>
    public partial class MainWindow
    {
        bool _pivotEdit;
        Button _pivotButton = null!;

        void SetPivotEdit(bool on)
        {
            if (on && _selection.Count == 0) { Status(L.T("Seleziona prima il modello di cui spostare il pivot"), true); return; }
            if (on && _tool != "move") SetTool("move");
            _pivotEdit = on;
            Theme.Style(_pivotButton, on ? Theme.Kind.Segment : Theme.Kind.Ghost);
            _pivotButton.Padding = new Thickness(10, 0, 10, 0);
            _pivotButton.Margin = new Thickness(6, 0, 0, 0);
            SendToWeb(new { type = "pivotEdit", on });
            Status(on ? L.T("Sposta il gizmo viola dove vuoi il pivot del modello; riclicca il pulsante per finire")
                      : L.T("Pivot fissato: da ora il gizmo di questo modello sta lì"));
        }

        async Task SavePivot(string id, JsonArray? pivot)
        {
            await Run(async api => { await api.Post("pivot", new JsonObject { ["id"] = id, ["pivot"] = pivot?.DeepClone() }); UpdateHistory(await api.Get("history")); });
            await RefreshScene();
        }
    }
}
