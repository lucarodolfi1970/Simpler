using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Simpler
{
    /// <summary>
    /// Diagnostics the user can send (always with a yes from the user): the problem lines of app.log, cleaned of personal
    /// data and grouped (the same problem 200 times = one entry with a count), plus the context needed to read them
    /// (version, Windows, video card). No window here: the sending and the question to the user are in the app.
    /// What is never sent: images, project contents, file names of the user's projects, names, e-mails.
    /// </summary>
    public static class Diagnostics
    {
        public const int Schema = 1;
        public const int ConsentTextVersion = 2;           // (raised when the text the user accepted changes)

        public sealed class Event
        {
            public string Kind { get; set; } = "";         // wait | slow-frame | shaders | late | viewer-crash | problem | crash
            public string Key { get; set; } = "";          // the problem without its numbers: «shaders: Updating the materials in the view»
            public string Id { get; set; } = "";           // 12 hex characters: same problem = same id on every PC
            public int Count { get; set; }
            public double TotalMs { get; set; }
            public double MaxMs { get; set; }
            public string First { get; set; } = "";
            public string Last { get; set; } = "";
            public List<string> Samples { get; set; } = new();
        }

        public sealed class Context
        {
            public string App { get; set; } = "";
            public string Os { get; set; } = "";
            public double RamGb { get; set; }
            public string Gpu { get; set; } = "";
            public double VramGb { get; set; }
            public int GpuScore { get; set; }
            public string Lang { get; set; } = "";
        }

        public sealed class Report
        {
            public int SchemaVersion { get; set; } = Schema;
            public string Install { get; set; } = "";
            public string Trigger { get; set; } = "manual";   // manual | auto | install (the «hello»: no events)
            public string Created { get; set; } = "";
            public Context Ctx { get; set; } = new();
            public int Sessions { get; set; }
            public int PerfSamples { get; set; }
            public double FpsMedian { get; set; }
            public double FpsP10 { get; set; }
            public bool PreviousCrashed { get; set; }
            public List<Event> Events { get; set; } = new();
        }

        // ------------------------------------------------------------------------------------------ what is a problem

        // (the log has no levels: lines are told apart by what they say. «GL error 0» is not an error)
        static readonly Regex Stamp = new(@"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}) (.*)$", RegexOptions.Compiled);
        static readonly Regex Wait = new(@"^wait (\d+),(\d) s: (.*)$", RegexOptions.Compiled);
        static readonly Regex Slow = new(@"^view: slow frame: (\d+) ms, (\d+) new shaders", RegexOptions.Compiled);
        static readonly Regex Shaders = new(@"^view: shaders ready in (\d+) ms \((\d+) new\): (.*)$", RegexOptions.Compiled);
        static readonly Regex Late = new(@"^view: update late: «([^»]*)» was drawn (\d+) ms", RegexOptions.Compiled);
        static readonly Regex Perf = new(@"^view: perf: ([\d.]+) fps", RegexOptions.Compiled);
        static readonly Regex Problem = new(@"\b(failed|exception|timeout|timed out|unresponsive|crash(ed)?|cannot|could not|not found|denied|corrupt)\b|\berror\b(?! 0)",
            RegexOptions.Compiled | RegexOptions.IgnoreCase);
        static readonly Regex Benign = new(@"GL error 0|^view: diag|^path traced thumbnail|^wheel |^ambience change", RegexOptions.Compiled);

        public const int WaitMinMs = 5000, ShadersMinMs = 3000, SlowMinMs = 1500;
        const int MaxEvents = 120, MaxSamples = 3, MaxSampleChars = 240;

        /// <summary>Thresholds of the cases that ask the user to send by themselves (once agreed to).</summary>
        public const int CriticalWaitMs = 20000, CriticalSlowMs = 10000;

        public static Report Build(IEnumerable<string> lines, Context ctx, string install, DateTime? since = null, bool previousCrashed = false)
        {
            var rep = new Report { Install = install, Ctx = ctx, Created = DateTime.UtcNow.ToString("o"), PreviousCrashed = previousCrashed };
            var map = new Dictionary<string, Event>();
            var fps = new List<double>();
            void Add(string kind, string key, double ms, string stamp, string sample)
            {
                var id = Fingerprint(kind + "|" + key);
                if (!map.TryGetValue(id, out var e)) map[id] = e = new Event { Kind = kind, Key = key, Id = id, First = stamp };
                e.Count++; e.TotalMs += ms; if (ms > e.MaxMs) e.MaxMs = ms; e.Last = stamp;
                if (e.Samples.Count < MaxSamples) e.Samples.Add(Clean(sample, MaxSampleChars));
            }
            foreach (var raw in lines)
            {
                var m0 = Stamp.Match(raw);
                if (!m0.Success) continue;
                var stamp = m0.Groups[1].Value; var text = m0.Groups[2].Value;
                if (since != null && DateTime.TryParse(stamp, out var t) && t <= since.Value.ToLocalTime()) continue;
                if (text.StartsWith("---- Simpler ")) { rep.Sessions++; continue; }
                var pm = Perf.Match(text);
                if (pm.Success) { if (double.TryParse(pm.Groups[1].Value, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var f)) fps.Add(f); continue; }
                var m = Wait.Match(text);
                if (m.Success)
                {
                    double ms = int.Parse(m.Groups[1].Value) * 1000 + int.Parse(m.Groups[2].Value) * 100;
                    if (ms >= WaitMinMs) Add("wait", "wait: " + Regex.Replace(m.Groups[3].Value.Split(" · ")[0], "^Inserting .*", "Inserting a model"), ms, stamp, text);
                    continue;
                }
                m = Slow.Match(text);
                if (m.Success) { Add("slow-frame", "slow frame", double.Parse(m.Groups[1].Value), stamp, text); continue; }
                m = Shaders.Match(text);
                if (m.Success)
                {
                    double ms = double.Parse(m.Groups[1].Value);
                    if (ms >= ShadersMinMs) Add("shaders", "shaders: " + m.Groups[3].Value, ms, stamp, text);
                    continue;
                }
                m = Late.Match(text);
                if (m.Success) { Add("late", "update late: " + m.Groups[1].Value, double.Parse(m.Groups[2].Value), stamp, text); continue; }
                if (text.StartsWith("viewer process failed")) { Add("viewer-crash", NormalizeKey(text), 0, stamp, text); continue; }
                if (Benign.IsMatch(text)) continue;
                if (Problem.IsMatch(text)) Add("problem", NormalizeKey(text), 0, stamp, text);
            }
            if (previousCrashed) Add("crash", "the previous session did not end cleanly", 0, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff"), "previous session did not end cleanly");
            rep.PerfSamples = fps.Count;
            if (fps.Count > 0) { fps.Sort(); rep.FpsMedian = Math.Round(fps[fps.Count / 2], 1); rep.FpsP10 = Math.Round(fps[(int)(fps.Count * 0.1)], 1); }
            rep.Events = map.Values.OrderByDescending(e => Severity(e)).ThenByDescending(e => e.Count).Take(MaxEvents).ToList();
            return rep;
        }

        static double Severity(Event e) => e.Kind switch { "crash" => 1e9, "viewer-crash" => 1e8, "problem" => 1e7, _ => e.MaxMs };

        /// <summary>The cases that justify an automatic sending: a crash, a view that died, a frame or an update much too long (not the waits: a render of ten minutes is normal), an error.</summary>
        public static bool IsCritical(Event e) =>
            e.Kind is "crash" or "viewer-crash" or "problem"
            || (e.Kind == "late" && e.MaxMs >= CriticalSlowMs)
            || (e.Kind == "slow-frame" && e.MaxMs >= CriticalSlowMs)
            || (e.Kind == "shaders" && e.MaxMs >= CriticalWaitMs);

        // ------------------------------------------------------------------------------------------ cleaning

        static readonly Regex UserPath = new(@"(?i)([A-Z]:\\Users\\)[^\\/\s""']+", RegexOptions.Compiled);
        static readonly Regex AnyPath = new(@"(?i)(?:[A-Z]:\\|\\\\[^\\\s]+\\)(?:[^\\/:*?""<>|\r\n]+[\\/])*([^\\/:*?""<>|\r\n\s]*)", RegexOptions.Compiled);
        static readonly Regex Email = new(@"[\w.+-]+@[\w-]+(\.[\w-]+)+", RegexOptions.Compiled);
        static readonly Regex Url = new(@"(https?://[^\s?#""']+)[^\s""']*", RegexOptions.Compiled);
        static readonly Regex Ip = new(@"\b\d{1,3}(\.\d{1,3}){3}\b", RegexOptions.Compiled);

        /// <summary>Takes out what identifies a person: the user name in a path, any folder (only the file name stays, with
        /// «…\»), e-mails, addresses of the net, the query part of a link.</summary>
        public static string Clean(string s, int max = 0)
        {
            if (string.IsNullOrEmpty(s)) return "";
            s = Email.Replace(s, "<email>");
            s = Url.Replace(s, "$1");
            s = Ip.Replace(s, "<ip>");
            s = UserPath.Replace(s, "$1~");
            s = AnyPath.Replace(s, m => m.Groups[1].Value.Length > 0 ? "…\\" + m.Groups[1].Value : "…\\");
            if (max > 0 && s.Length > max) s = s.Substring(0, max) + "…";
            return s;
        }

        static string NormalizeKey(string text)
        {
            var s = Clean(text);
            s = Regex.Replace(s, @"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", "<id>");
            s = Regex.Replace(s, @"\d+([.,]\d+)?", "#");
            s = Regex.Replace(s, @"\s+", " ").Trim().ToLowerInvariant();
            return s.Length > 140 ? s.Substring(0, 140) : s;
        }

        public static string Fingerprint(string key)
        {
            using var sha = SHA1.Create();
            return Convert.ToHexString(sha.ComputeHash(Encoding.UTF8.GetBytes(key))).Substring(0, 12).ToLowerInvariant();
        }

        public static string ToJson(Report r) => JsonSerializer.Serialize(r, new JsonSerializerOptions
        {
            WriteIndented = true,
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        });

        // ------------------------------------------------------------------------------------------ crash marker

        public sealed class Session { public string Started { get; set; } = ""; public bool Clean { get; set; } }

        /// <summary>At start: true when the previous run did not end cleanly (a crash, a kill, a power cut), then the new run is marked as open.</summary>
        public static bool StartSession(string file)
        {
            bool crashed = false;
            try
            {
                if (File.Exists(file))
                {
                    var prev = JsonSerializer.Deserialize<Session>(File.ReadAllText(file));
                    crashed = prev != null && !prev.Clean;
                }
                Directory.CreateDirectory(Path.GetDirectoryName(file)!);
                File.WriteAllText(file, JsonSerializer.Serialize(new Session { Started = DateTime.UtcNow.ToString("o"), Clean = false }));
            }
            catch { }
            return crashed;
        }

        public static void EndSession(string file)
        {
            try { File.WriteAllText(file, JsonSerializer.Serialize(new Session { Started = DateTime.UtcNow.ToString("o"), Clean = true })); } catch { }
        }

        // ------------------------------------------------------------------------------------------ consent and sending rules

        public sealed class State
        {
            public string Install { get; set; } = Guid.NewGuid().ToString("N");
            public string Consent { get; set; } = "unknown";          // unknown | manual (only when I press) | auto (critical cases by themselves) | none
            public int TextVersion { get; set; }
            public string ConsentAt { get; set; } = "";
            public string LastAutoSent { get; set; } = "";
            public string HelloVersion { get; set; } = "";            // (15/11) the version of Simpler whose «hello» was sent (once per version, consent «auto»)
            public string LastSent { get; set; } = "";                // the last sending of any kind (the next one starts from there)
            public Dictionary<string, string> SentIds { get; set; } = new();     // id of a problem -> when it was sent
        }

        public static State Load(string file)
        {
            try { if (File.Exists(file)) return JsonSerializer.Deserialize<State>(File.ReadAllText(file)) ?? new State(); } catch { }
            return new State();
        }

        public static void Save(string file, State s)
        {
            try { Directory.CreateDirectory(Path.GetDirectoryName(file)!); File.WriteAllText(file, JsonSerializer.Serialize(s)); } catch { }
        }

        public const int AutoMinHours = 24, SameProblemDays = 7;

        /// <summary>
        /// Whether to send by itself: only with consent «auto» given for the current text, at most once a day, and only if the
        /// report holds a critical problem not already sent in the last 7 days. The returned report keeps only what is new.
        /// </summary>
        public static Report? AutoCandidate(Report all, State st, DateTime now)
        {
            if (st.Consent != "auto" || st.TextVersion != ConsentTextVersion) return null;
            if (DateTime.TryParse(st.LastAutoSent, null, System.Globalization.DateTimeStyles.RoundtripKind, out var last) && (now - last).TotalHours < AutoMinHours) return null;
            bool Fresh(Event e) => !(st.SentIds.TryGetValue(e.Id, out var w) && DateTime.TryParse(w, null, System.Globalization.DateTimeStyles.RoundtripKind, out var wt) && (now - wt).TotalDays < SameProblemDays);
            var fresh = all.Events.Where(e => IsCritical(e) && Fresh(e)).ToList();
            if (fresh.Count == 0) return null;
            all.Trigger = "auto";
            all.Events = all.Events.Where(Fresh).ToList();       // (the not critical ones come along: they explain the critical)
            return all;
        }

        public static void MarkSent(Report r, State st, DateTime now, bool auto)
        {
            var w = now.ToString("o");
            foreach (var e in r.Events) st.SentIds[e.Id] = w;
            st.LastSent = w;
            if (auto) st.LastAutoSent = w;
            foreach (var k in st.SentIds.Where(kv => DateTime.TryParse(kv.Value, null, System.Globalization.DateTimeStyles.RoundtripKind, out var t) && (now - t).TotalDays > 60).Select(kv => kv.Key).ToList()) st.SentIds.Remove(k);
        }
    }
}
