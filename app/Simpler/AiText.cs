using System;
using System.Linq;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;

namespace Simpler
{
    /// <summary>
    /// (1.75.40) Small text jobs with the user's OpenAI key (the same as the image functions, no other account): the
    /// cheapest text model the key can use - chosen from the list of models of the key, not written in Simpler: a
    /// «nano» before a «mini», the newest version first; dated snapshots and the audio, realtime, search and
    /// transcription variants are left out.
    /// </summary>
    public static class AiText
    {
        static readonly HttpClient Http = new HttpClient { Timeout = TimeSpan.FromMinutes(2) };
        static readonly Regex Cheap = new Regex(@"^gpt-(\d+(?:\.\d+)?)(?:o)?-(nano|mini)$", RegexOptions.IgnoreCase);

        public static string? CheapestModel()
        {
            var best = AiKey.AllModels
                .Select(id => (id, m: Cheap.Match(id)))
                .Where(x => x.m.Success)
                .OrderBy(x => x.m.Groups[2].Value.Equals("nano", StringComparison.OrdinalIgnoreCase) ? 0 : 1)
                .ThenByDescending(x => double.TryParse(x.m.Groups[1].Value, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var v) ? v : 0)
                .Select(x => x.id).FirstOrDefault();
            return best ?? AiKey.AllModels.FirstOrDefault(id => id == "gpt-4o-mini");
        }

        public sealed record Result(string Text, string Model, long InputTokens, long OutputTokens);

        /// <summary>One answer of the model: instructions, the user's text and optional small pictures (detail low:
        /// the cheapest way to send a picture). Parameters the model does not take are dropped and asked again.</summary>
        public static async Task<Result> AskAsync(string system, string user, string[] imagesJpeg, CancellationToken ct)
        {
            var key = AiKey.Read() ?? throw new InvalidOperationException(L.T("Nessuna chiave salvata"));
            var model = CheapestModel() ?? throw new InvalidOperationException(L.T("La chiave OpenAI non ha accesso a un modello di testo"));
            var content = new JsonArray { new JsonObject { ["type"] = "text", ["text"] = user } };
            foreach (var img in imagesJpeg)
                content.Add(new JsonObject { ["type"] = "image_url", ["image_url"] = new JsonObject { ["url"] = img, ["detail"] = "low" } });
            var body = new JsonObject
            {
                ["model"] = model,
                ["messages"] = new JsonArray
                {
                    new JsonObject { ["role"] = "system", ["content"] = system },
                    new JsonObject { ["role"] = "user", ["content"] = content },
                },
                ["max_completion_tokens"] = 1200,
            };
            // reasoning models: as little thinking as possible (cost); the others refuse the field and it goes away
            if (model.StartsWith("gpt-5", StringComparison.OrdinalIgnoreCase) || model.StartsWith("o", StringComparison.OrdinalIgnoreCase))
                body["reasoning_effort"] = "minimal";
            for (int attempt = 0; ; attempt++)
            {
                using var req = new HttpRequestMessage(HttpMethod.Post, "https://api.openai.com/v1/chat/completions");
                req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", key);
                req.Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json");
                using var res = await Http.SendAsync(req, ct);
                var text = await res.Content.ReadAsStringAsync(ct);
                JsonNode? j = null;
                try { j = JsonNode.Parse(text); } catch { }
                if (res.IsSuccessStatusCode)
                {
                    var answer = ((string?)j?["choices"]?[0]?["message"]?["content"] ?? "").Trim();
                    if (answer == "") throw new InvalidOperationException(L.T("Il modello non ha dato una risposta"));
                    return new Result(answer, model, (long?)j?["usage"]?["prompt_tokens"] ?? 0, (long?)j?["usage"]?["completion_tokens"] ?? 0);
                }
                var msg = (string?)j?["error"]?["message"] ?? text;
                var param = (string?)j?["error"]?["param"] ?? "";
                if ((int)res.StatusCode == 400 && attempt < 3)
                {
                    if (body.ContainsKey("reasoning_effort") && (param == "reasoning_effort" || msg.Contains("reasoning_effort")))
                    {
                        // "minimal" not taken by this model: "low", then without the field
                        if ((string?)body["reasoning_effort"] == "minimal") body["reasoning_effort"] = "low"; else body.Remove("reasoning_effort");
                        continue;
                    }
                    if (param == "max_completion_tokens" || msg.Contains("max_completion_tokens"))
                    {
                        body.Remove("max_completion_tokens"); body["max_tokens"] = 1200; continue;
                    }
                }
                throw new InvalidOperationException($"OpenAI {(int)res.StatusCode}: {msg}");
            }
        }
    }
}
