using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json.Nodes;

namespace Simpler
{
    public sealed class SceneObject
    {
        public string Id = "", Name = "", Kind = "", Parent = "", Source = "";
        public bool Visible = true;
        public int Instances;               // other objects sharing this mesh (linked copies); 0 = unique
        public string InstanceOf = "";      // id of the original model when this is an instance of it
        public bool Paint;                  // a group made by Distribuisci
        public string Eco = "";
        public string Role = "";            // made by Simpler as: "terrain", "zone" (of a terrain), "ground", "scree", "screeLayer"             // "group" (an ecosystem placed), "layer" (one of its distributions), "plot"
        public bool NoScatter;              // "Escludi da Area": the Area tool puts nothing on it
        public bool Dry;                    // «Sempre asciutto» → no rain: the rain does not wet it (rain.py)
        public bool NoSnow;                 // «Sempre asciutto» → no snow (rain.snow_dry)
        public bool NoShelter;              // «Non fa riparo»: what is under it gets the rain (a moving car)
        public bool NoMantle;               // «Senza mantello»: no layer of snow on it (snow.py)
        public bool NoCaustics;             // «Genera caustiche» off: it draws no sharp caustic (render.no_caustics)
        public string SnowDetail = "auto";  // «Dettaglio neve»: auto | high | low (snow.py)
        public int PaintCount;              // its pieces (points drawn as instances)
        public string PaintModel = "";      // a painted piece (or a part of one): library model it comes from
        public bool OpenModel;              // a library model opened to change its parts (MainWindow.OpenModel)
        public bool HasPivot;               // pivot placed by hand (MainWindow.Pivot)
        public int InstanceCount;           // on an original: how many instances it has
        public int Order = int.MaxValue;    // place among its siblings set by dragging in the tree (none: by name)
        public double[] Location = new double[3], Rotation = new double[3], Scale = { 1, 1, 1 };
        public JsonObject? Light;
        public JsonObject? Water;
        public JsonObject? Decal;           // a decal: its values (sizes in cm, opacity, tint...) and revision
        public List<string> Materials = new List<string>();
        public List<SceneObject> Children = new List<SceneObject>();

        public bool IsLight => Light != null;
        /// <summary>Sun and moon of the Ambiente: driven by its panel, not listed in the tree nor drawn as a light icon.</summary>
        public bool IsAmbience => (bool?)Light?["ambience"] ?? false;
        public bool IsMesh => Kind == "mesh";

        public string KindLabel => Kind switch
        {
            "file" => L.T("File importato"),
            "group" => L.T("Gruppo"),
            "mesh" => L.T("Oggetto"),
            "sun" => L.T("Sole"),
            "area" => L.T("Luce ad area"),
            "spot" => L.T("Faretto (spot)"),
            "point" => L.T("Luce puntiforme"),
            "camera" => L.T("Camera importata"),
            "decal" => L.T("Decal"),
            _ => Kind,
        };

        static double[] Vec(JsonNode? n) => n is JsonArray a && a.Count == 3
            ? new[] { (double)a[0]!, (double)a[1]!, (double)a[2]! } : new double[3];

        public static SceneObject From(JsonObject o) => new SceneObject
        {
            Id = (string?)o["id"] ?? "",
            Name = (string?)o["name"] ?? "",
            Kind = (string?)o["kind"] ?? "",
            Parent = (string?)o["parent"] ?? "",
            Source = (string?)o["source"] ?? "",
            Visible = (bool?)o["visible"] ?? true,
            Location = Vec(o["location"]),
            Rotation = Vec(o["rotation"]),
            Scale = Vec(o["scale"]),
            Light = o["light"] as JsonObject,
            Water = o["water"] as JsonObject,
            Decal = o["decal"] as JsonObject,
            Materials = (o["materials"] as JsonArray)?.Select(m => (string?)m ?? "").ToList() ?? new List<string>(),
            Instances = (int?)o["instances"] ?? 0,
            InstanceOf = (string?)o["instanceOf"] ?? "",
            InstanceCount = (int?)o["instanceCount"] ?? 0,
            PaintModel = (string?)o["paintModel"] ?? "",
            OpenModel = (bool?)o["openModel"] ?? false,
            HasPivot = o["pivot"] is JsonArray,
            PaintCount = (int?)o["paintCount"] ?? 0,
            Eco = (string?)o["eco"] ?? "",
            Role = (string?)o["role"] ?? "",
            NoScatter = (bool?)o["noScatter"] ?? false,
            Dry = (bool?)o["dry"] ?? false,
            NoSnow = (bool?)o["noSnow"] ?? false,
            NoShelter = (bool?)o["noShelter"] ?? false,
            NoMantle = (bool?)o["noMantle"] ?? false,
            NoCaustics = (bool?)o["noCaustics"] ?? false,
            SnowDetail = (string?)o["snowDetail"] ?? "auto",
            Paint = o["paint"] is JsonValue pv && (pv.TryGetValue<bool>(out var pb) ? pb : pv.TryGetValue<int>(out var pi) && pi != 0),
            Order = (int?)o["order"] ?? int.MaxValue,
        };
    }

    public sealed class SceneModel
    {
        public readonly Dictionary<string, SceneObject> ById = new Dictionary<string, SceneObject>();
        public readonly List<SceneObject> Roots = new List<SceneObject>();

        public static SceneModel From(JsonObject scene)
        {
            var m = new SceneModel();
            var list = (scene["objects"] as JsonArray)?.OfType<JsonObject>().Select(SceneObject.From).ToList() ?? new List<SceneObject>();
            foreach (var o in list) m.ById[o.Id] = o;
            foreach (var o in list)
            {
                if (!string.IsNullOrEmpty(o.Parent) && m.ById.TryGetValue(o.Parent, out var p)) p.Children.Add(o);
                else m.Roots.Add(o);
            }
            return m;
        }

        public IEnumerable<SceneObject> Ancestors(SceneObject o)
        {
            var p = o.Parent;
            while (!string.IsNullOrEmpty(p) && ById.TryGetValue(p, out var po)) { yield return po; p = po.Parent; }
        }
    }

    public static class Num
    {
        public static string F(double v, int decimals = 2) => v.ToString("0." + new string('#', decimals), CultureInfo.CurrentCulture);

        public static bool TryParse(string s, out double v)
        {
            s = (s ?? "").Trim().Replace(',', '.');
            return double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out v);
        }
    }
}
