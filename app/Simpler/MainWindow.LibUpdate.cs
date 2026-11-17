using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;

namespace Simpler
{
    public sealed partial class MainWindow
    {
        /// <summary>A row that uses library models: a distribution, an ecosystem (or one of its layers), a placed model,
        /// or a group with one of them inside.</summary>
        bool UsesLibraryModels(SceneObject o)
        {
            if (o.Paint || o.Eco == "group" || o.Eco == "layer" || o.PaintModel != "") return true;
            foreach (var c in o.Children) if (UsesLibraryModels(c)) return true;
            return false;
        }

        /// <summary>«Aggiorna dalla libreria…»: the models used by these rows (GET models/usage), the choice, then
        /// POST models/refresh (one undo step).</summary>
        async Task UpdateFromLibrary(IEnumerable<string> ids)
        {
            JsonObject? u = null;
            await Run(async api => { u = await api.Get("models/usage?ids=" + Uri.EscapeDataString(string.Join(",", ids))); });
            var models = (u?["models"] as JsonArray)?.OfType<JsonObject>().ToList() ?? new List<JsonObject>();
            if (models.Count == 0)
            {
                Status(L.T("Qui non ci sono modelli della libreria da aggiornare"), true);
                return;
            }
            if (models.All(m => !((bool?)m["inLibrary"] ?? false)))
            {
                // (a model deleted from the library and saved again is a new model for Simpler: nothing to update)
                Msg.Show(this, L.T("I modelli usati qui non sono più nella libreria: forse sono stati eliminati e salvati di nuovo, e per Simpler sono modelli nuovi.\n\nPer correggere un modello della libreria senza perdere il legame con i progetti, salvalo con lo stesso nome nella stessa cartella e scegli di sovrascriverlo. Qui puoi eliminare la distribuzione o il modello e rimetterlo dalla libreria."),
                         L.T("Aggiorna dalla libreria"), MessageBoxButton.OK, MessageBoxImage.Information);
                return;
            }
            var chosen = LibUpdateDialog.Ask(this, L.T("Aggiorna dalla libreria"),
                L.T("I modelli usati qui verranno ricaricati come sono adesso nella libreria (per esempio dopo «Correggi materiali dei modelli»)."),
                models, L.T("Aggiorna"));
            if (chosen != null) await RunLibraryUpdate(chosen);
        }

        async Task RunLibraryUpdate(List<string> chosen)
        {
            using var busy = BeginBusy();
            _reloadOrigin = "action";
            JsonObject? r = null;
            await Run(async api => { r = await api.Post("models/refresh", new { models = chosen.ToArray() }); });
            if (r == null) return;
            await RefreshScene();
            int n = (int?)r["models"] ?? 0;
            Status(n == 1 ? L.T("Aggiornato 1 modello dalla libreria  (Ctrl+Z per annullare)")
                          : L.F("Aggiornati {0} modelli dalla libreria  (Ctrl+Z per annullare)", n));
        }

        /// <summary>After opening a project: the library models it uses that were changed in the library since then
        /// (known only for what was placed from 1.59 on) - a question, «Non ora» leaves them as they are.</summary>
        async Task CheckOutdatedModels()
        {
            await Task.Delay(600);
            JsonObject? u = null;
            try { if (_api != null) u = await _api.Get("models/outdated"); } catch { return; }
            var models = (u?["models"] as JsonArray)?.OfType<JsonObject>().ToList() ?? new List<JsonObject>();
            if (models.Count == 0) return;
            var chosen = LibUpdateDialog.Ask(this, L.T("Modelli cambiati nella libreria"),
                models.Count == 1 ? L.T("Un modello usato in questo progetto è stato cambiato nella libreria dopo che l'hai usato. Vuoi aggiornarlo anche qui?")
                                  : L.F("{0} modelli usati in questo progetto sono stati cambiati nella libreria dopo che li hai usati. Vuoi aggiornarli anche qui?", models.Count),
                models, L.T("Aggiorna"));
            if (chosen != null) await RunLibraryUpdate(chosen);
        }
    
        bool _snowPresent, _snowHidden;

        /// <summary>«Nascondi la neve» / «Mostra la neve»: the snow mantle out of the view and the images while models are
        /// moved (nothing made again meanwhile); shown, it is made again once (POST rain/snowhide, not saved).</summary>
        async Task SetSnowHidden(bool hidden)
        {
            JsonObject? r = null;
            await Run(async api => { r = await api.Post("rain/snowhide", new { hidden }); });
            if (r == null) return;
            _snowHidden = hidden;
            SendToWeb(new { type = "snowHidden", hidden });
            Status(hidden ? L.T("Neve nascosta") : L.T("Neve di nuovo visibile: il manto si rifà"));
            RenderLightenBox();
        }
}
}
