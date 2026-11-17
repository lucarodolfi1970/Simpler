using System;
using System.Windows.Input;
using System.Windows.Threading;

namespace Simpler
{
    /// <summary>"Simpler is working": when a command waits for the engine for more than half a second (a drag
    /// that moves a big model, a material on thousands of pieces), the mouse shows the arrow with the hourglass - over the 3D view
    /// too - and the view a small pill with what it is doing and for how long. Quick commands show nothing.</summary>
    public sealed partial class MainWindow
    {
        DispatcherTimer? _workTimer;
        IDisposable? _viewerWait;          // the 3D view is loading what was sent to it
        bool _working;
        bool _viewBusy;                    // the 3D view shows a task of its own (its pill): busy arrow too

        // commands that have their own progress (final render, preparation of the view) or run in the background
        static readonly string[] QuietCommands =
        {
            "camera", "render", "render/cancel", "preview", "preview/part", "preview/cancel", "material/livepreview",
            "materials/preview", "models/thumb", "autosave/discard", "paths/cancel",
        };

        // readings the app makes in the background all the time (progress, status of jobs, resources): never shown
        static bool Quiet(string p)
        {
            if (p.StartsWith("wait:", StringComparison.Ordinal)) return false;
            if (p.StartsWith("get:", StringComparison.Ordinal))
            {
                var g = p.Substring(4).Split('?')[0];
                return g.EndsWith("status", StringComparison.Ordinal) || g is "progress" || g is "resources" || g is "ping"
                       || g is "dirty" || g is "history" || g.StartsWith("render", StringComparison.Ordinal);
            }
            return Array.IndexOf(QuietCommands, p.Split('?')[0]) >= 0;
        }

        static string WorkLabel(string path)
        {
            if (path.StartsWith("wait:", StringComparison.Ordinal)) return path.Substring(5);
            if (path.StartsWith("get:", StringComparison.Ordinal))
                return path.StartsWith("get:scene", StringComparison.Ordinal) ? L.T("Aggiornamento della scena") : L.T("Simpler sta lavorando");
            string P(string p) => path.StartsWith(p, StringComparison.Ordinal) ? p : "";
            if (P("transform") != "" || P("matrices") != "") return L.T("Spostamento degli oggetti");
            if (P("material/assign") != "" || P("material/replace") != "") return L.T("Assegnazione del materiale");
            if (P("material/water") != "") return L.T("Aggiornamento dell'acqua");
            if (P("material") != "") return L.T("Aggiornamento del materiale");
            if (P("models/insert") != "" || path == "add") return L.T("Inserimento nella scena");
            if (P("models") != "") return L.T("Libreria dei modelli");
            if (P("delete") != "") return L.T("Eliminazione");
            if (P("import") != "") return L.T("Importazione");
            if (P("autosave") != "") return L.T("Salvataggio automatico");
            if (P("save") != "") return L.T("Salvataggio del progetto");
            if (P("open") != "" || path == "new") return L.T("Apertura del progetto");
            if (P("undo") != "" || P("redo") != "") return L.T("Annulla / Ripeti");
            if (P("ambience") != "") return L.T("Aggiornamento dell'ambiente");
            if (P("light") != "") return L.T("Aggiornamento della luce");
            if (P("paint") != "" || P("noscatter") != "") return L.T("Distribuzione");
            if (P("views") != "") return L.T("Viste salvate");
            return L.T("Simpler sta lavorando");
        }

        void StartWorkIndicator()
        {
            if (_workTimer != null) return;
            _workTimer = new DispatcherTimer(TimeSpan.FromMilliseconds(200), DispatcherPriority.Background, (_, __) => WorkTick(), Dispatcher);
            _workTimer.Start();
        }

        void WorkTick()
        {
            var o = EngineClient.Oldest(Quiet);
            if (o != null && o.Value.seconds > 60 && o.Value.path.StartsWith("wait:", StringComparison.Ordinal))
            {   // (a view that never answered: stop saying it is working)
                _viewerWait?.Dispose(); _viewerWait = null;
                o = EngineClient.Oldest(Quiet);
            }
            bool show = o != null && o.Value.seconds >= 0.5;
            if (show)
            {
                var label = WorkLabel(o!.Value.path);
                var secs = (int)o.Value.seconds;
                _working = true;
                UpdateBusyCursor();   // (a command waiting: the arrow with the hourglass, full hourglass only if locked)
                SendToWeb(new { type = "working", on = true, text = label + "…", detail = secs >= 1 ? L.F("{0} s", secs) : "" });
            }
            else if (_working)
            {
                _working = false;
                ReleaseBusyCursor();
                SendToWeb(new { type = "working", on = false });
            }
        }
    }
}
