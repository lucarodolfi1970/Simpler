using System; using System.IO; using System.Linq; using Simpler;
class P { static int bad = 0; static void Ck(bool ok, string m) { Console.WriteLine((ok ? "ok   " : "FAIL ") + m); if (!ok) bad++; }
static int Main(string[] args) {
  var lines = File.ReadAllLines(args.Length > 0 ? args[0] : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Simpler", "app.log"));
  var ctx = new Diagnostics.Context { App = "1.79.0", Os = "Win11", Gpu = "x" };
  var r = Diagnostics.Build(lines, ctx, "abc");
  Console.WriteLine($"sessions {r.Sessions} perf {r.PerfSamples} median {r.FpsMedian} p10 {r.FpsP10} events {r.Events.Count}");
  foreach (var e in r.Events.Take(14)) Console.WriteLine($"  {e.Kind,-12} x{e.Count,-4} max {e.MaxMs,7:0} ms  {e.Key.Substring(0, Math.Min(70, e.Key.Length))}");
  Ck(r.Events.Any(e => e.Kind == "viewer-crash" && e.Count == 5), "5 viewer crashes grouped in one entry");
  Ck(!r.Events.Any(e => e.Kind == "problem" && e.Key.Contains("gl error")), "«GL error 0» is not a problem");
  Ck(r.Events.Any(e => e.Kind == "slow-frame" && e.MaxMs > 20000), "the 21 s frame is there");
  Ck(r.Events.Count < 60, "the report stays small: " + r.Events.Count + " entries, " + Diagnostics.ToJson(r).Length + " bytes");
  // privacy
  var c = Diagnostics.Clean(@"cannot open C:\Users\lucar\Documents\Progetto Segreto\casa.simpler and mail luca@x.com at 10.1.2.3 http://a.b/c?token=XYZ \\nas\share\foo\bar.blend");
  Console.WriteLine("  " + c);
  Ck(!c.Contains("lucar") && !c.Contains("Segreto") && !c.Contains("luca@") && !c.Contains("10.1.2.3") && !c.Contains("XYZ") && !c.Contains("nas\\share"), "no user name, folder, e-mail, ip, token");
  Ck(c.Contains("casa.simpler"), "the file name stays (needed to understand the error)");
  // the same problem has the same id with different numbers
  var a = Diagnostics.Build(new[] { "2026-11-14 10:00:00.000 viewer process failed: RenderProcessUnresponsive" }, ctx, "i");
  var b = Diagnostics.Build(new[] { "2026-11-14 11:00:00.000 viewer process failed: RenderProcessUnresponsive" }, ctx, "j");
  Ck(a.Events[0].Id == b.Events[0].Id, "same id for the same problem on two PCs");
  // sending rules
  var now = DateTime.UtcNow; var st = new Diagnostics.State { Consent = "auto", TextVersion = Diagnostics.ConsentTextVersion };
  var cand = Diagnostics.AutoCandidate(Diagnostics.Build(lines, ctx, "abc"), st, now);
  Ck(cand != null && cand.Trigger == "auto", "auto: critical problems and consent -> sends");
  Diagnostics.MarkSent(cand!, st, now, true);
  Ck(Diagnostics.AutoCandidate(Diagnostics.Build(lines, ctx, "abc"), st, now.AddHours(2)) == null, "auto: not again within 24 h");
  Ck(Diagnostics.AutoCandidate(Diagnostics.Build(lines, ctx, "abc"), st, now.AddHours(30)) == null, "auto: same problems already sent, nothing new");
  Ck(Diagnostics.AutoCandidate(Diagnostics.Build(lines, ctx, "abc"), new Diagnostics.State { Consent = "manual" }, now) == null, "manual consent: never by itself");
  Ck(Diagnostics.AutoCandidate(Diagnostics.Build(lines, ctx, "abc"), new Diagnostics.State { Consent = "auto", TextVersion = 0 }, now) == null, "old consent text: asks again");
  var calm = Diagnostics.Build(new[] { "2026-11-14 10:00:00.000 wait 6,0 s: The engine is working", "2026-11-14 10:00:01.000 view: diag (20 s after loading): GL error 0" }, ctx, "i");
  Ck(!Diagnostics.IsCritical(new Diagnostics.Event { Kind = "wait", MaxMs = 792000 }), "a 13 minute render wait is not critical");
  Ck(Diagnostics.AutoCandidate(calm, new Diagnostics.State { Consent = "auto", TextVersion = 1 }, now) == null, "a 6 s wait is not critical");
  // crash marker
  var f = Path.Combine(Path.GetTempPath(), "sess-" + Guid.NewGuid().ToString("N") + ".json");
  Ck(!Diagnostics.StartSession(f), "first start: no crash");
  Diagnostics.EndSession(f); Ck(!Diagnostics.StartSession(f), "clean end then start: no crash");
  Ck(Diagnostics.StartSession(f), "start without clean end: crash found");
  var cr = Diagnostics.Build(new string[0], ctx, "i", null, true);
  Ck(cr.Events.Count == 1 && Diagnostics.IsCritical(cr.Events[0]), "a crash is a critical event");
  Console.WriteLine(bad == 0 ? "ALL OK" : bad + " FAILED"); return bad; } }
