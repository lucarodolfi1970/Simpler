using System.Text.Json.Nodes;
// the logic of AmbWrite / LoadAmbience / RefreshScene with a slow engine, copied in miniature
class Sim {
  public JsonObject Amb = new(); public int Seq; public bool Overlay;
  public List<string> Log = new();
  static JsonObject St(double cover,double scale)=>new(){["state"]=new JsonObject{["clouds"]=new JsonObject{["cover"]=cover,["scale"]=scale}}};
  public JsonObject Engine = St(0.70,0.65)["state"]!.AsObject();   // engine truth
  void Ov(JsonObject b){ if(Amb["state"] is not JsonObject st) return; foreach(var g in b) if(g.Value is JsonObject p){ if(st[g.Key] is not JsonObject d) st[g.Key]=d=new JsonObject(); foreach(var kv in p) d[kv.Key]=kv.Value?.DeepClone(); } }
  public (int mine, JsonObject answer) Send(JsonObject body){ var mine=++Seq; if(Overlay) Ov(body);
    var c=(JsonObject)Engine["clouds"]!; foreach(var kv in (JsonObject)body["clouds"]!) c[kv.Key]=kv.Value!.DeepClone();
    return (mine,new JsonObject{["state"]=Engine.DeepClone()}); }
  public void Answer(int mine, JsonObject a){ if(mine==Seq) Amb=a; }
  public double Cover=>(double)Amb["state"]!["clouds"]!["cover"]!;
}
class P { static void Main(){
  foreach (var ov in new[]{false,true}) {
    var s=new Sim{Overlay=ov}; s.Amb=new JsonObject{["state"]=new JsonObject{["clouds"]=new JsonObject{["cover"]=0.70,["scale"]=0.65}}};
    var a=s.Send(new JsonObject{["clouds"]=new JsonObject{["cover"]=0.286}});      // slider 1
    var b=s.Send(new JsonObject{["clouds"]=new JsonObject{["scale"]=0.265}});      // slider 2 before answer 1 arrives
    s.Answer(a.mine,a.answer);                                                      // answer 1 discarded (newer change sent)
    Console.WriteLine($"overlay={ov}: panel after answer 1 shows cover {s.Cover}");  // panel rebuilt here
    s.Answer(b.mine,b.answer);
    Console.WriteLine($"overlay={ov}: panel after answer 2 shows cover {s.Cover}");
  } } }
