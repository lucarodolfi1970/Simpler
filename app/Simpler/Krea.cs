using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;

namespace Simpler
{
    /// <summary>
    /// (1.75.32) The user's Krea API key, for the AI video. Personal and optional, like the OpenAI key (AiKey): kept
    /// encrypted with Windows (DPAPI, current user) in %APPDATA%\Simpler\krea.key, never shown again once saved - it
    /// can only be deleted and entered again.
    /// </summary>
    public static class KreaKey
    {
        static string FilePath => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Simpler", "krea.key");
        static readonly byte[] Entropy = Encoding.UTF8.GetBytes("Simpler.Krea.v1");
        static readonly HttpClient Http = new HttpClient { Timeout = TimeSpan.FromSeconds(25) };

        public static bool Exists => File.Exists(FilePath);
        /// <summary>Last test: null = not tested yet.</summary>
        public static bool? Ok { get; private set; }
        public static string Message { get; private set; } = "";

        public static void Save(string key)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(FilePath)!);
            File.WriteAllBytes(FilePath, AiKey.Run(Encoding.UTF8.GetBytes(key.Trim()), true, Entropy));
            Ok = null; Message = "";
        }

        public static void Delete()
        {
            try { File.Delete(FilePath); } catch { }
            Ok = null; Message = "";
        }

        internal static string? Read()
        {
            try { return Exists ? Encoding.UTF8.GetString(AiKey.Run(File.ReadAllBytes(FilePath), false, Entropy)) : null; }
            catch { return null; }
        }

        /// <summary>A cheap call with the key (the list of the user's assets, one item): answered = the key works.</summary>
        public static async Task<bool> TestAsync()
        {
            var key = Read();
            if (string.IsNullOrEmpty(key)) { Ok = false; Message = L.T("Nessuna chiave salvata"); return false; }
            try
            {
                using var req = new HttpRequestMessage(HttpMethod.Get, KreaClient.Base + "/assets?limit=1");
                req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", key);
                using var res = await Http.SendAsync(req);
                var body = await res.Content.ReadAsStringAsync();
                if (!res.IsSuccessStatusCode)
                {
                    Ok = false;
                    Message = (int)res.StatusCode is 401 or 403 ? L.T("Krea non accetta la chiave: controllala su krea.ai (API tokens)")
                                                              : $"{(int)res.StatusCode} {res.ReasonPhrase}: " + KreaClient.ErrorText(body);
                    return false;
                }
                Ok = true;
                Message = L.T("Krea risponde: la chiave funziona");
                return true;
            }
            catch (TaskCanceledException) { Ok = false; Message = L.T("Krea non risponde (tempo scaduto): controlla la connessione a internet"); return false; }
            catch (Exception ex) { Ok = false; Message = L.T("Impossibile raggiungere Krea: ") + ex.Message; return false; }
        }
    }

    /// <summary>A video model of Krea that takes a first and a last frame. Price in dollars per second of video, per
    /// resolution (0 = not known).</summary>
    public sealed record VideoModel(string Id, string Name, string Path, string Hint, string[] Resolutions,
                                    Dictionary<string, double> PricePerSecond, int MinSeconds, int MaxSeconds, string Kind);

    /// <summary>(1.75.32) The AI video with Krea: which models take a first and a last frame (asked to Krea, with a
    /// table inside Simpler when it does not say), the upload of the two pictures, the job and its result.</summary>
    public static class KreaClient
    {
        public const string Base = "https://api.krea.ai";
        static readonly HttpClient Http = new HttpClient { Timeout = TimeSpan.FromMinutes(5) };

        /// <summary>The models Simpler knows (prices from the Krea API pages, without audio). Kind tells how the
        /// resolution is asked: "kling" with mode std/pro, "resolution" with the resolution field.</summary>
        public static readonly List<VideoModel> Known = new()
        {
            new VideoModel("kling-3.0", "Kling 3.0", "/generate/video/kling/kling-3.0",
                L.T("Il più economico: movimenti di camera puliti tra il primo e l'ultimo fotogramma"),
                new[] { "720p", "1080p" }, new() { ["720p"] = 0.084, ["1080p"] = 0.112 }, 3, 15, "kling"),
            new VideoModel("seedance-2", "Seedance 2.0", "/generate/video/bytedance/seedance-2",
                L.T("ByteDance: buona coerenza dei dettagli; prezzo indicativo (Krea lo dà «a partire da»)"),
                new[] { "720p", "1080p" }, new() { ["720p"] = 0.0809, ["1080p"] = 0 }, 4, 15, "resolution"),
        };

        static List<VideoModel>? _models;
        public static List<VideoModel> Models => _models ?? Known;
        public static string ModelsSource { get; private set; } = "";

        /// <summary>Asks Krea which video models take a start and an end image (its OpenAPI description): the new ones
        /// are added to the list (without a price), the known ones keep the table. Krea not answering = the table.</summary>
        public static async Task<List<VideoModel>> ListModelsAsync()
        {
            if (_models != null) return _models;
            var list = new List<VideoModel>(Known);
            try
            {
                using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(15));
                var json = await Http.GetStringAsync(Base + "/openapi.json", cts.Token);
                var doc = JsonNode.Parse(json) as JsonObject;
                int added = 0;
                if (doc?["paths"] is JsonObject paths)
                    foreach (var (path, item) in paths)
                    {
                        if (!path.StartsWith("/generate/video/", StringComparison.OrdinalIgnoreCase)) continue;
                        if (list.Any(m => string.Equals(m.Path, path, StringComparison.OrdinalIgnoreCase))) continue;
                        var schema = Resolve(doc, item?["post"]?["requestBody"]?["content"]?["application/json"]?["schema"]);
                        if (schema?["properties"] is not JsonObject props || props["start_image"] == null || props["end_image"] == null) continue;
                        var res = (Resolve(doc, props["resolution"])?["enum"] as JsonArray)?.Select(x => (string?)x ?? "").Where(x => x is "720p" or "1080p").ToArray();
                        var kind = res is { Length: > 0 } ? "resolution" : props["mode"] != null ? "kling" : "none";
                        var name = path.Split('/', StringSplitOptions.RemoveEmptyEntries).Last();
                        list.Add(new VideoModel(name, Pretty(name), path, L.T("Modello trovato su Krea: prezzo non noto a Simpler, controllalo su krea.ai"),
                                                res is { Length: > 0 } ? res : new[] { "720p" }, new(), 5, 10, kind));
                        added++;
                    }
                ModelsSource = added > 0 ? L.F("Krea: {0} modelli in più trovati", added) : L.T("Elenco aggiornato da Krea");
                AppLog.Write($"krea: openapi read, {added} more video models with start and end image");
            }
            catch (Exception ex)
            {
                ModelsSource = "";
                AppLog.Write("krea: openapi not read (" + ex.GetType().Name + "), the built-in list");
            }
            _models = list;
            return list;
        }

        static string Pretty(string id) => string.Join(" ", id.Split('-', '_').Select(w => w.Length > 0 ? char.ToUpperInvariant(w[0]) + w[1..] : w));

        static JsonNode? Resolve(JsonObject doc, JsonNode? n)
        {
            for (int i = 0; i < 6 && n?["$ref"] is JsonValue r; i++)
            {
                var parts = ((string?)r ?? "").TrimStart('#', '/').Split('/');
                JsonNode? cur = doc;
                foreach (var p in parts) cur = cur?[p];
                n = cur;
            }
            if (n?["allOf"] is JsonArray all && all.Count > 0) return Resolve(doc, all[0]);
            return n;
        }

        public static string ErrorText(string body)
        {
            try
            {
                var j = JsonNode.Parse(body);
                var m = (string?)j?["error"]?["message"] ?? (string?)j?["message"] ?? (string?)j?["detail"] ?? (string?)j?["error"];
                if (!string.IsNullOrWhiteSpace(m)) return m!;
            }
            catch { }
            body = body.Trim();
            return body.Length > 300 ? body[..300] + "…" : body;
        }

        static HttpRequestMessage Req(HttpMethod m, string path)
        {
            var key = KreaKey.Read() ?? throw new InvalidOperationException(L.T("Nessuna chiave salvata"));
            var r = new HttpRequestMessage(m, path.StartsWith("http") ? path : Base + path);
            r.Headers.Authorization = new AuthenticationHeaderValue("Bearer", key);
            return r;
        }

        static string? FirstUrl(JsonNode? n, string? prefer = null)
        {
            var all = new List<string>();
            void Walk(JsonNode? x)
            {
                switch (x)
                {
                    case JsonValue v when v.TryGetValue<string>(out var s) && s.StartsWith("http", StringComparison.OrdinalIgnoreCase): all.Add(s); break;
                    case JsonArray a: foreach (var e in a) Walk(e); break;
                    case JsonObject o: foreach (var (_, e) in o) Walk(e); break;
                }
            }
            Walk(n);
            return (prefer != null ? all.FirstOrDefault(u => u.Contains(prefer, StringComparison.OrdinalIgnoreCase)) : null) ?? all.FirstOrDefault();
        }

        /// <summary>A picture to Krea (its asset store): the address to give to the job. If the upload does not work, the
        /// picture goes inside the request (data URI, accepted by the video models too).</summary>
        public static async Task<string> UploadAsync(string file, CancellationToken ct)
        {
            var bytes = await File.ReadAllBytesAsync(file, ct);
            var mime = file.EndsWith(".png", StringComparison.OrdinalIgnoreCase) ? "image/png" : "image/jpeg";
            try
            {
                using var req = Req(HttpMethod.Post, "/assets");
                var form = new MultipartFormDataContent();
                var part = new ByteArrayContent(bytes);
                part.Headers.ContentType = new MediaTypeHeaderValue(mime);
                form.Add(part, "file", Path.GetFileName(file));
                req.Content = form;
                using var res = await Http.SendAsync(req, ct);
                var body = await res.Content.ReadAsStringAsync(ct);
                if (res.IsSuccessStatusCode)
                {
                    var j = JsonNode.Parse(body);
                    var url = (string?)j?["image_url"] ?? (string?)j?["url"] ?? FirstUrl(j);
                    if (!string.IsNullOrEmpty(url)) return url!;
                }
                AppLog.Write($"krea: upload {(int)res.StatusCode} {ErrorText(body)}: the picture goes inside the request");
            }
            catch (OperationCanceledException) { throw; }
            catch (Exception ex) { AppLog.Write("krea: upload failed (" + ex.Message + "): the picture goes inside the request"); }
            return $"data:{mime};base64," + Convert.ToBase64String(bytes);
        }

        /// <summary>Starts the video. Returns the job id.</summary>
        public static async Task<string> SubmitAsync(VideoModel m, string res, int seconds, string prompt, string start, string? end, CancellationToken ct)
        {
            var body = new JsonObject
            {
                ["prompt"] = prompt,
                ["start_image"] = start,
                ["duration"] = Math.Clamp(seconds, m.MinSeconds, m.MaxSeconds),
                ["aspect_ratio"] = "16:9",
            };
            // (1.78.4) no last frame: the video starts from the first one and follows the text (end_image is optional
            // for the video models of Krea)
            if (end != null) body["end_image"] = end;
            // (1.75.33) no generate_audio: Krea removed the field on 30/10/2026 and refuses requests that have it
            // (the models make no audio unless asked)
            if (m.Kind == "kling") body["mode"] = res == "1080p" ? "pro" : "std";
            else if (m.Kind == "resolution") body["resolution"] = res;
            string text = "";
            for (int attempt = 0; ; attempt++)
            {
                using var req = Req(HttpMethod.Post, m.Path);
                req.Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json");
                using var r = await Http.SendAsync(req, ct);
                text = await r.Content.ReadAsStringAsync(ct);
                if (r.IsSuccessStatusCode) break;
                // (1.75.33) a field Krea no longer takes ("… was removed … Omit this field"): sent again without it
                var drop = (int)r.StatusCode == 422 && attempt < 3 ? RemovedFields(text).Where(f => body.ContainsKey(f) && f is not ("prompt" or "start_image" or "end_image")).ToList() : new();
                if (drop.Count == 0) throw new InvalidOperationException($"Krea {(int)r.StatusCode}: {ErrorText(text)}");
                foreach (var f in drop) body.Remove(f);
                AppLog.Write("krea: sent again without " + string.Join(", ", drop) + " (" + ErrorText(text) + ")");
            }
            var j = JsonNode.Parse(text);
            var id = (string?)j?["job_id"] ?? (string?)j?["id"] ?? (string?)j?["job"]?["id"];
            if (string.IsNullOrEmpty(id)) throw new InvalidOperationException(L.T("Krea non ha restituito il lavoro: ") + ErrorText(text));
            AppLog.Write($"krea: job {id} started ({m.Id} {res} {seconds}s{(end == null ? ", first frame only" : "")})");
            return id!;
        }

        /// <summary>The fields a 422 of Krea says to leave out (removed, not allowed, unknown).</summary>
        static IEnumerable<string> RemovedFields(string body)
        {
            JsonNode? j = null;
            try { j = JsonNode.Parse(body); } catch { }
            if (j?["details"] is not JsonArray det) yield break;
            foreach (var d in det)
            {
                var f = (string?)d?["field"] ?? "";
                var msg = ((string?)d?["message"] ?? "").ToLowerInvariant();
                if (f != "" && (msg.Contains("omit") || msg.Contains("removed") || msg.Contains("not allowed") || msg.Contains("unrecognized") || msg.Contains("unknown")))
                    yield return f;
            }
        }

        public sealed record JobState(string Status, double Progress, string? VideoUrl, string? Error);

        public static async Task<JobState> PollAsync(string jobId, CancellationToken ct)
        {
            using var req = Req(HttpMethod.Get, "/jobs/" + Uri.EscapeDataString(jobId));
            using var r = await Http.SendAsync(req, ct);
            var text = await r.Content.ReadAsStringAsync(ct);
            if (!r.IsSuccessStatusCode) throw new InvalidOperationException($"Krea {(int)r.StatusCode}: {ErrorText(text)}");
            var j = JsonNode.Parse(text);
            var status = (string?)j?["status"] ?? "";
            double progress = 0;
            try { progress = (double?)j?["progress"] ?? 0; } catch { }
            string? url = status == "completed" ? FirstUrl(j?["result"], ".mp4") ?? FirstUrl(j?["result"]) : null;
            string? err = status is "failed" or "cancelled" ? ((string?)j?["error"]?["message"] ?? (string?)j?["error"] ?? status) : null;
            return new JobState(status, progress, url, err);
        }

        public static async Task DownloadAsync(string url, string file, CancellationToken ct)
        {
            using var res = await Http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, ct);
            res.EnsureSuccessStatusCode();
            Directory.CreateDirectory(Path.GetDirectoryName(file)!);
            var tmp = file + ".part";
            await using (var fs = File.Create(tmp))
                await res.Content.CopyToAsync(fs, ct);
            File.Move(tmp, file, true);
        }
    }
}
