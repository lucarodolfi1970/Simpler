using System;
using System.Net.Http;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;

namespace Simpler
{
    /// <summary>
    /// (1.78.4, Luca) Checks on rodluc.com whether a newer Simpler exists. It sends only the version and the language,
    /// never downloads nor installs anything; links are opened only when they are https on rodluc.com or github.com.
    /// The automatic check runs at most once every 24 hours and is silent when the site does not answer.
    /// </summary>
    public static class UpdateCheck
    {
        public const string Endpoint = "https://www.rodluc.com/simpler/update/check.php";
        public static readonly TimeSpan Every = TimeSpan.FromHours(24);
        static readonly HttpClient Http = new HttpClient { Timeout = TimeSpan.FromSeconds(6) };

        public sealed class Info
        {
            public string Current = "", Latest = "", Channel = "", Released = "", Title = "", Summary = "", NotesUrl = "", DownloadUrl = "";
            public bool UpdateAvailable, Required;
        }

        /// <summary>Raised (on any thread) when a check finds a newer version: the main window shows its strip.</summary>
        public static event Action<Info, bool>? Found;      // (info, asked by the user with «Controlla ora»)

        public static string BuildUrl(string baseUrl, string version, string lang, string channel)
        {
            var url = $"{baseUrl}?v={Uri.EscapeDataString(version)}&lang={(lang == "en" ? "en" : "it")}";
            return channel == "beta" ? url + "&channel=beta" : url;
        }

        /// <summary>Only https on www.rodluc.com, rodluc.com and github.com; anything else is not opened.</summary>
        public static bool SafeUrl(string? url)
            => Uri.TryCreate(url, UriKind.Absolute, out var u) && u.Scheme == Uri.UriSchemeHttps && u.IsDefaultPort
               && u.Host.ToLowerInvariant() is "www.rodluc.com" or "rodluc.com" or "github.com";

        /// <summary>The answer of the site, or null when it is not a valid one (the check then stays silent).</summary>
        public static Info? Parse(string json)
        {
            try
            {
                if (JsonNode.Parse(json) is not JsonObject o || o["ok"]?.GetValue<bool>() != true) return null;
                static string S(JsonObject o, string k) { try { return o[k]?.GetValue<string>() ?? ""; } catch { return ""; } }
                static bool B(JsonObject o, string k) { try { return o[k]?.GetValue<bool>() == true; } catch { return false; } }
                var i = new Info
                {
                    Current = S(o, "current"), Latest = S(o, "latest"), Channel = S(o, "channel"), Released = S(o, "released"),
                    Title = S(o, "title"), Summary = S(o, "summary"), NotesUrl = S(o, "notes_url"), DownloadUrl = S(o, "download_url"),
                    UpdateAvailable = B(o, "update_available"), Required = B(o, "required"),
                };
                if (!SafeUrl(i.NotesUrl)) i.NotesUrl = "";
                if (!SafeUrl(i.DownloadUrl)) i.DownloadUrl = "";
                return i.Latest == "" ? null : i;
            }
            catch { return null; }
        }

        /// <summary>The automatic check is due: never done, more than 24 hours ago, or a date in the future (clock changed).</summary>
        public static bool Due(string lastUtc, DateTime nowUtc)
            => !DateTime.TryParse(lastUtc, null, System.Globalization.DateTimeStyles.RoundtripKind, out var last)
               || nowUtc - last.ToUniversalTime() >= Every || last.ToUniversalTime() > nowUtc;

        /// <summary>The strip is shown: a newer version for this one, not skipped by the user (a required one always).</summary>
        public static bool ShouldShow(Info? i, string version, string skipped)
            => i != null && i.UpdateAvailable && i.Current == version && (i.Required || i.Latest != skipped);

        /// <summary>Asks the site. Null = no valid answer (offline, error, 6 seconds without answer).</summary>
        public static async Task<Info?> Ask(string baseUrl, string version, string lang, string channel)
        {
            try
            {
                using var req = new HttpRequestMessage(HttpMethod.Get, BuildUrl(baseUrl, version, lang, channel));
                using var resp = await Http.SendAsync(req).ConfigureAwait(false);
                if (!resp.IsSuccessStatusCode) { AppLog.Write($"update check: http {(int)resp.StatusCode}"); return null; }
                var info = Parse(await resp.Content.ReadAsStringAsync().ConfigureAwait(false));
                AppLog.Write(info == null ? "update check: answer not valid" : $"update check: latest {info.Latest}, available {info.UpdateAvailable}, required {info.Required}");
                return info;
            }
            catch (Exception ex) { AppLog.Write("update check: no answer (" + ex.GetType().Name + ")"); return null; }
        }

        /// <summary>A check now (automatic or «Controlla ora»): the answer is kept for the next starts, a newer version raised.</summary>
        public static async Task<Info?> Run(bool manual = false)
        {
            var st = Settings.Load();
            var version = SettingsDialog.Version;
            var info = await Ask(Endpoint, version, L.Lang, st.UpdateChannel).ConfigureAwait(false);
            if (info == null) return null;
            var s = Settings.Load();
            s.UpdateLastCheck = DateTime.UtcNow.ToString("o");
            s.UpdateLast = JsonSerializer.Serialize(new { info.Current, info.Latest, info.Channel, info.Released, info.Title, info.Summary,
                                                          info.NotesUrl, info.DownloadUrl, info.UpdateAvailable, info.Required });
            s.Save();
            if (manual ? info.UpdateAvailable && info.Current == version : ShouldShow(info, version, s.UpdateSkipped)) Found?.Invoke(info, manual);
            return info;
        }

        /// <summary>The answer of the last check, kept in the settings (the strip comes back at the next starts within 24 hours).</summary>
        public static Info? Last(Settings s)
        {
            try
            {
                if (string.IsNullOrEmpty(s.UpdateLast) || JsonNode.Parse(s.UpdateLast) is not JsonObject o) return null;
                var i = new Info
                {
                    Current = (string?)o["Current"] ?? "", Latest = (string?)o["Latest"] ?? "", Channel = (string?)o["Channel"] ?? "",
                    Released = (string?)o["Released"] ?? "", Title = (string?)o["Title"] ?? "", Summary = (string?)o["Summary"] ?? "",
                    NotesUrl = (string?)o["NotesUrl"] ?? "", DownloadUrl = (string?)o["DownloadUrl"] ?? "",
                    UpdateAvailable = (bool?)o["UpdateAvailable"] == true, Required = (bool?)o["Required"] == true,
                };
                if (!SafeUrl(i.NotesUrl)) i.NotesUrl = "";
                if (!SafeUrl(i.DownloadUrl)) i.DownloadUrl = "";
                return i;
            }
            catch { return null; }
        }

        public static void Open(string url)
        {
            if (!SafeUrl(url)) return;
            try { System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(url) { UseShellExecute = true }); } catch { }
        }
    }
}
