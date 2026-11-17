// (1.78.4) Non-regression of the update check: the answers of the site (valid, errors, slow), the 24 hours,
// «Salta questa versione», the links allowed. A small local server stands in for rodluc.com.
using System;
using System.Net;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace Simpler
{
    // stand-ins for the parts of the app that UpdateCheck.Run uses (not exercised here)
    public static class AppLog { public static void Write(string s) => Console.WriteLine("  log: " + s); }
    public static class L { public static string Lang = "it"; }
    public sealed class Settings
    {
        public string UpdateChannel { get; set; } = ""; public string UpdateLastCheck { get; set; } = "";
        public string UpdateLast { get; set; } = ""; public string UpdateSkipped { get; set; } = "";
        public static Settings Load() => new Settings(); public void Save() { }
    }
    public static class SettingsDialog { public static string Version => "1.78.4"; }

    static class UpdateTest
    {
        static int fails;
        static void Check(bool ok, string what) { Console.WriteLine((ok ? "ok   " : "FAIL ") + what); if (!ok) fails++; }

        const string Good = "{\"ok\":true,\"channel\":\"stable\",\"current\":\"1.78.4\",\"latest\":\"1.79.0\",\"update_available\":true,\"required\":false,"
            + "\"released\":\"2026-11-20\",\"title\":\"Simpler 1.79\",\"summary\":\"Novità\",\"notes_url\":\"https://www.rodluc.com/simpler/it/novita.html\","
            + "\"download_url\":\"https://github.com/x/simpler/releases/download/v1.79.0/SimplerSetup.exe\"}";

        static async Task<int> Main()
        {
            // ---- parsing
            var i = UpdateCheck.Parse(Good);
            Check(i != null && i.Latest == "1.79.0" && i.UpdateAvailable && !i.Required && i.NotesUrl != "" && i.DownloadUrl != "", "valid answer read");
            Check(UpdateCheck.Parse("{\"ok\":false,\"error\":\"bad_version\"}") == null, "ok=false ignored");
            Check(UpdateCheck.Parse("<html>404</html>") == null, "html page ignored");
            Check(UpdateCheck.Parse("") == null, "empty answer ignored");
            Check(UpdateCheck.Parse("{\"ok\":true,\"latest\":5}") == null, "wrong types ignored");
            var evil = UpdateCheck.Parse(Good.Replace("https://github.com/x", "http://evil.example").Replace("https://www.rodluc.com/simpler/it/novita.html", "https://rodluc.com.evil.net/x"));
            Check(evil != null && evil.DownloadUrl == "" && evil.NotesUrl == "", "links outside rodluc.com / github.com dropped");

            // ---- links allowed
            Check(UpdateCheck.SafeUrl("https://www.rodluc.com/a") && UpdateCheck.SafeUrl("https://rodluc.com/a") && UpdateCheck.SafeUrl("https://github.com/a"), "https rodluc/github allowed");
            Check(!UpdateCheck.SafeUrl("http://www.rodluc.com/a") && !UpdateCheck.SafeUrl("https://evil.com/a") && !UpdateCheck.SafeUrl("https://xgithub.com/a")
                  && !UpdateCheck.SafeUrl("https://github.com.evil.com/a") && !UpdateCheck.SafeUrl("file:///c:/x.exe") && !UpdateCheck.SafeUrl("https://www.rodluc.com:8443/a")
                  && !UpdateCheck.SafeUrl(null) && !UpdateCheck.SafeUrl("javascript:alert(1)"), "everything else refused");

            // ---- request: only version and language (and the beta channel when chosen)
            Check(UpdateCheck.BuildUrl("https://h/c.php", "1.78.4", "en", "") == "https://h/c.php?v=1.78.4&lang=en", "url it/en");
            Check(UpdateCheck.BuildUrl("https://h/c.php", "1.78.4", "fr", "beta") == "https://h/c.php?v=1.78.4&lang=it&channel=beta", "unknown language → it, beta channel");

            // ---- 24 hours
            var now = new DateTime(2026, 11, 8, 12, 0, 0, DateTimeKind.Utc);
            Check(UpdateCheck.Due("", now), "never checked: due");
            Check(!UpdateCheck.Due(now.AddHours(-23).ToString("o"), now), "23 h ago: not due");
            Check(UpdateCheck.Due(now.AddHours(-24).ToString("o"), now), "24 h ago: due");
            Check(UpdateCheck.Due(now.AddDays(3).ToString("o"), now), "date in the future (clock changed): due");
            Check(UpdateCheck.Due("garbage", now), "unreadable date: due");

            // ---- strip
            Check(UpdateCheck.ShouldShow(i, "1.78.4", ""), "newer version: strip");
            Check(!UpdateCheck.ShouldShow(i, "1.78.4", "1.79.0"), "skipped version: no strip");
            Check(UpdateCheck.ShouldShow(i, "1.78.4", "1.78.9"), "an older skip does not hide a newer version");
            Check(!UpdateCheck.ShouldShow(i, "1.79.0", ""), "answer for another version (after updating): no strip");
            var req = UpdateCheck.Parse(Good.Replace("\"required\":false", "\"required\":true"));
            Check(UpdateCheck.ShouldShow(req, "1.78.4", "1.79.0"), "required: shown even if skipped");
            Check(!UpdateCheck.ShouldShow(UpdateCheck.Parse(Good.Replace("\"update_available\":true", "\"update_available\":false")), "1.78.4", ""), "up to date: no strip");
            Check(!UpdateCheck.ShouldShow(null, "1.78.4", ""), "no answer: no strip");

            // ---- the network: a local server in place of the site
            using var l = new HttpListener(); l.Prefixes.Add("http://127.0.0.1:18765/"); l.Start();
            string lastQuery = "";
            _ = Task.Run(async () =>
            {
                while (l.IsListening)
                {
                    HttpListenerContext c; try { c = await l.GetContextAsync(); } catch { break; }
                    _ = Task.Run(async () =>
                    {
                        var path = c.Request.Url!.AbsolutePath; lastQuery = c.Request.Url.Query;
                        int code = 200; string body = Good;
                        if (path == "/bad") { code = 400; body = "{\"ok\":false,\"error\":\"bad_version\"}"; }
                        else if (path == "/down") { code = 503; body = "{\"ok\":false,\"error\":\"unavailable\"}"; }
                        else if (path == "/slow") await Task.Delay(9000);
                        var b = Encoding.UTF8.GetBytes(body);
                        c.Response.StatusCode = code; c.Response.ContentType = "application/json";
                        try { await c.Response.OutputStream.WriteAsync(b); c.Response.Close(); } catch { }
                    });
                }
            });
            var a = await UpdateCheck.Ask("http://127.0.0.1:18765/ok", "1.78.4", "en", "");
            Check(a != null && a.Latest == "1.79.0", "200: answer read");
            Check(lastQuery == "?v=1.78.4&lang=en", "only version and language sent (" + lastQuery + ")");
            Check(await UpdateCheck.Ask("http://127.0.0.1:18765/bad", "x", "it", "") == null, "400 bad_version: silent");
            Check(await UpdateCheck.Ask("http://127.0.0.1:18765/down", "1.78.4", "it", "") == null, "503 unavailable: silent");
            var t0 = DateTime.UtcNow;
            Check(await UpdateCheck.Ask("http://127.0.0.1:18765/slow", "1.78.4", "it", "") == null && (DateTime.UtcNow - t0).TotalSeconds < 7.5, "no answer in 6 s: silent, gives up");
            Check(await UpdateCheck.Ask("http://127.0.0.1:18799/none", "1.78.4", "it", "") == null, "offline: silent");
            l.Stop();

            Console.WriteLine(fails == 0 ? "update check: all ok" : $"update check: {fails} FAILED");
            return fails == 0 ? 0 : 1;
        }
    }
}
