using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;

namespace Simpler
{
    /// <summary>
    /// The user's OpenAI API key, for the AI features of Simpler (ChatGPT image models). Personal and optional. Kept
    /// encrypted with Windows (DPAPI, current user: only this Windows account on this computer can read it) in
    /// %APPDATA%\Simpler\openai.key; never shown again once saved - it can only be deleted and entered again.
    /// </summary>
    public static class AiKey
    {
        static string FilePath => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Simpler", "openai.key");
        static readonly byte[] Entropy = Encoding.UTF8.GetBytes("Simpler.OpenAI.v1");
        static readonly HttpClient Http = new HttpClient { Timeout = TimeSpan.FromSeconds(25) };

        public static bool Exists => File.Exists(FilePath);

        /// <summary>Last test: null = not tested yet.</summary>
        public static bool? Ok { get; private set; }
        public static string Message { get; private set; } = "";
        public static string ImageModel { get; private set; } = "";
        /// <summary>Image models the key can use (newest name first), from the last test.</summary>
        public static System.Collections.Generic.List<string> ImageModels { get; private set; } = new();
        /// <summary>(1.75.40) Every model the key can use, from the last test (for the text helpers).</summary>
        public static System.Collections.Generic.List<string> AllModels { get; private set; } = new();

        public static void Save(string key)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(FilePath)!);
            File.WriteAllBytes(FilePath, Protect(Encoding.UTF8.GetBytes(key.Trim())));
            Ok = null; Message = ""; ImageModel = "";
        }

        public static void Delete()
        {
            try { File.Delete(FilePath); } catch { }
            Ok = null; Message = ""; ImageModel = "";
        }

        /// <summary>The key, for the AI features only (never shown in the interface).</summary>
        internal static string? Read()
        {
            try { return Exists ? Encoding.UTF8.GetString(Unprotect(File.ReadAllBytes(FilePath))) : null; }
            catch { return null; }
        }

        /// <summary>Asks OpenAI for the list of models with the key: answered = the key works; an image model
        /// (gpt-image-…) among them = the ChatGPT image part is active.</summary>
        public static async Task<bool> TestAsync()
        {
            var key = Read();
            if (string.IsNullOrEmpty(key)) { Ok = false; Message = L.T("Nessuna chiave salvata"); return false; }
            try
            {
                using var req = new HttpRequestMessage(HttpMethod.Get, "https://api.openai.com/v1/models");
                req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", key);
                using var res = await Http.SendAsync(req);
                var body = await res.Content.ReadAsStringAsync();
                JsonNode? j = null;
                try { j = JsonNode.Parse(body); } catch { }
                if (!res.IsSuccessStatusCode)
                {
                    Ok = false;
                    Message = $"{(int)res.StatusCode} {res.ReasonPhrase}: " + ((string?)j?["error"]?["message"] ?? body.Trim());
                    return false;
                }
                var ids = (j?["data"] as JsonArray)?.Select(m => (string?)m?["id"] ?? "").ToList() ?? new();
                AllModels = ids;
                var images = ids.Where(id => id.StartsWith("gpt-image", StringComparison.OrdinalIgnoreCase) || id.StartsWith("chatgpt-image", StringComparison.OrdinalIgnoreCase))
                                .OrderByDescending(id => id, StringComparer.OrdinalIgnoreCase).ToList();
                if (images.Count == 0)
                {
                    Ok = false;
                    Message = L.T("La chiave funziona, ma questo account non ha accesso ai modelli di immagini di OpenAI (gpt-image). Controlla su platform.openai.com la verifica dell'organizzazione e i crediti.");
                    return false;
                }
                Ok = true;
                ImageModels = images;
                ImageModel = images[0];
                Message = L.F("OpenAI risponde: modelli di immagini attivi ({0})", string.Join(", ", images.Take(3)));
                return true;
            }
            catch (TaskCanceledException) { Ok = false; Message = L.T("OpenAI non risponde (tempo scaduto): controlla la connessione a internet"); return false; }
            catch (Exception ex) { Ok = false; Message = L.T("Impossibile raggiungere OpenAI: ") + ex.Message; return false; }
        }

        // ---------------------------------------------------------------- Windows DPAPI (no extra package)

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        struct DataBlob { public int cbData; public IntPtr pbData; }

        [DllImport("crypt32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        static extern bool CryptProtectData(ref DataBlob pDataIn, string? szDataDescr, ref DataBlob pOptionalEntropy, IntPtr pvReserved, IntPtr pPromptStruct, int dwFlags, ref DataBlob pDataOut);

        [DllImport("crypt32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        static extern bool CryptUnprotectData(ref DataBlob pDataIn, IntPtr ppszDataDescr, ref DataBlob pOptionalEntropy, IntPtr pvReserved, IntPtr pPromptStruct, int dwFlags, ref DataBlob pDataOut);

        [DllImport("kernel32.dll")]
        static extern IntPtr LocalFree(IntPtr hMem);

        const int CRYPTPROTECT_UI_FORBIDDEN = 0x1;

        static byte[] Protect(byte[] data) => Run(data, true);
        static byte[] Unprotect(byte[] data) => Run(data, false);

        /// <summary>(1.75.32) also for the Krea key (KreaKey), with its own entropy.</summary>
        internal static byte[] Run(byte[] data, bool protect, byte[]? entropy = null)
        {
            var e = entropy ?? Entropy;
            var hIn = GCHandle.Alloc(data, GCHandleType.Pinned);
            var hEnt = GCHandle.Alloc(e, GCHandleType.Pinned);
            try
            {
                var input = new DataBlob { cbData = data.Length, pbData = hIn.AddrOfPinnedObject() };
                var ent = new DataBlob { cbData = e.Length, pbData = hEnt.AddrOfPinnedObject() };
                var output = new DataBlob();
                bool ok = protect
                    ? CryptProtectData(ref input, "Simpler", ref ent, IntPtr.Zero, IntPtr.Zero, CRYPTPROTECT_UI_FORBIDDEN, ref output)
                    : CryptUnprotectData(ref input, IntPtr.Zero, ref ent, IntPtr.Zero, IntPtr.Zero, CRYPTPROTECT_UI_FORBIDDEN, ref output);
                if (!ok) throw new InvalidOperationException("DPAPI " + Marshal.GetLastWin32Error());
                var bytes = new byte[output.cbData];
                Marshal.Copy(output.pbData, bytes, 0, output.cbData);
                LocalFree(output.pbData);
                return bytes;
            }
            finally { hIn.Free(); hEnt.Free(); }
        }
    }

    /// <summary>One image edit with OpenAI (POST /v1/images/edits): the picture, the prompt, optional mask and
    /// reference. Returns the PNG and the tokens used (usage, when OpenAI reports it).</summary>
    public static class AiClient
    {
        static readonly HttpClient Http = new HttpClient { Timeout = TimeSpan.FromMinutes(10) };

        public sealed record Result(byte[] Image, long InputTokens, long OutputTokens);

        /// <summary>A size OpenAI accepts, with the proportions of the picture. gpt-image-2 and later take any
        /// WxH (multiples of 16, ratio up to 3:1, at most 3840x2160): about 1536x1024 pixels with the same ratio
        /// (renderAI compute_matching_size). The others: the closest of the three standard sizes.</summary>
        public static string SizeFor(string model, int w, int h)
        {
            double r = Math.Max(1 / 3.0, Math.Min(3.0, w / (double)Math.Max(1, h)));
            if (model.StartsWith("gpt-image-2", StringComparison.OrdinalIgnoreCase) || model.StartsWith("chatgpt-image", StringComparison.OrdinalIgnoreCase))
            {
                double px = 1536.0 * 1024.0;
                double ww = Math.Sqrt(px * r), hh = px / ww;
                int R16(double v) => (int)Math.Max(320, Math.Round(v / 16) * 16);
                int iw = R16(ww), ih = R16(hh);
                int mx = Math.Max(iw, ih);
                if (mx > 3840) { iw = R16(iw * 3840.0 / mx); ih = R16(ih * 3840.0 / mx); }
                return $"{iw}x{ih}";
            }
            return r > 1.2 ? "1536x1024" : r < 0.83 ? "1024x1536" : "1024x1024";
        }

        /// <summary>input_fidelity "high" keeps faces and fine detail of the input: supported by gpt-image-1 and
        /// 1.5 (not by the mini, nor by gpt-image-2 and later, which must not receive it).</summary>
        static bool Fidelity(string model) =>
            model.Equals("gpt-image-1", StringComparison.OrdinalIgnoreCase) || model.StartsWith("gpt-image-1.5", StringComparison.OrdinalIgnoreCase);

        public static async Task<Result> EditAsync(string model, string quality, string prompt, byte[] image, byte[]? mask, byte[]? reference,
                                                   string size, System.Threading.CancellationToken ct)
        {
            var key = AiKey.Read() ?? throw new InvalidOperationException(L.T("Nessuna chiave salvata"));
            for (int attempt = 0; attempt < 2; attempt++)
            {
                bool fidelity = attempt == 0 && Fidelity(model);
                using var form = new MultipartFormDataContent();
                form.Add(new StringContent(model), "model");
                form.Add(new StringContent(prompt), "prompt");
                form.Add(new StringContent(quality), "quality");
                form.Add(new StringContent(size), "size");
                form.Add(new StringContent("1"), "n");
                if (fidelity) form.Add(new StringContent("high"), "input_fidelity");
                var img = new ByteArrayContent(image); img.Headers.ContentType = new MediaTypeHeaderValue("image/png");
                form.Add(img, "image[]", "image.png");
                if (reference != null)
                {
                    var rf = new ByteArrayContent(reference); rf.Headers.ContentType = new MediaTypeHeaderValue("image/png");
                    form.Add(rf, "image[]", "reference.png");
                }
                if (mask != null)
                {
                    var mk = new ByteArrayContent(mask); mk.Headers.ContentType = new MediaTypeHeaderValue("image/png");
                    form.Add(mk, "mask", "mask.png");
                }
                using var req = new HttpRequestMessage(HttpMethod.Post, "https://api.openai.com/v1/images/edits") { Content = form };
                req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", key);
                using var res = await Http.SendAsync(req, ct);
                var body = await res.Content.ReadAsStringAsync(ct);
                JsonNode? j = null;
                try { j = JsonNode.Parse(body); } catch { }
                if (!res.IsSuccessStatusCode)
                {
                    var msg = (string?)j?["error"]?["message"] ?? body.Trim();
                    // a model that does not know input_fidelity: once more without it (renderAI does the same)
                    if (fidelity && (int)res.StatusCode == 400 && msg.Contains("input_fidelity", StringComparison.OrdinalIgnoreCase)) continue;
                    throw new InvalidOperationException($"OpenAI {(int)res.StatusCode}: {msg}");
                }
                var b64 = (string?)j?["data"]?[0]?["b64_json"];
                if (string.IsNullOrEmpty(b64)) throw new InvalidOperationException(L.T("OpenAI non ha restituito un'immagine"));
                long tin = (long?)j?["usage"]?["input_tokens"] ?? 0, tout = (long?)j?["usage"]?["output_tokens"] ?? 0;
                return new Result(Convert.FromBase64String(b64), tin, tout);
            }
            throw new InvalidOperationException(L.T("OpenAI non ha restituito un'immagine"));
        }
    }

    /// <summary>The AI button's window: what the key is for, where to get it, paste and test it, or delete it.</summary>
    public sealed class AiDialog : ThemedDialog
    {
        readonly Action _changed;

        public AiDialog(Action changed) : base(L.T("Intelligenza artificiale"), 500)
        {
            _changed = changed;
            Build();
        }

        void Build()
        {
            Body.Children.Clear();
            Body.Children.Add(Theme.Label(L.T("AI in Simpler"), 18, Theme.Text, FontWeights.SemiBold));
            Para(L.T("Le funzioni di intelligenza artificiale di Simpler usano i modelli di immagini di ChatGPT (OpenAI) con la tua chiave API personale. La chiave non è obbligatoria: Simpler funziona tutto anche senza, ma senza chiave le funzioni AI restano spente."));
            Para(L.T("Le richieste partono dal tuo computer verso OpenAI e sono addebitate sul tuo account OpenAI, a consumo: i costi sono quelli dei tuoi crediti API, non di Simpler."));
            var how = new TextBlock { TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 0, 0, 12), FontSize = 12.5, Foreground = Theme.B(Theme.TextSoft) };
            how.Inlines.Add(new Run(L.T("Come ottenerla: registrati su ")));
            var link = new Hyperlink(new Run("https://platform.openai.com/")) { NavigateUri = new Uri("https://platform.openai.com/"), Foreground = Theme.B(Theme.Accent) };
            link.RequestNavigate += (_, e) => { try { Process.Start(new ProcessStartInfo(e.Uri.AbsoluteUri) { UseShellExecute = true }); } catch { } };
            how.Inlines.Add(link);
            how.Inlines.Add(new Run(L.T(", acquista dei crediti per le API (Billing) e crea una chiave in «API keys». Per i modelli di immagini OpenAI può chiedere di verificare l'organizzazione.")));
            Body.Children.Add(how);

            if (!AiKey.Exists)
            {
                Body.Children.Add(Theme.Label(L.T("Incolla qui la chiave API (inizia con «sk-»)"), 12, Theme.TextMuted));
                var box = Theme.Input("", true);
                box.Margin = new Thickness(0, 6, 0, 8);
                Body.Children.Add(box);
                var warn = Theme.Label(L.T("Una volta salvata la chiave non si può più vedere: viene conservata cifrata e solo per il tuo utente di Windows. Per cambiarla dovrai eliminarla e inserirla di nuovo."), 11.5, Theme.Warm);
                warn.TextWrapping = TextWrapping.Wrap;
                warn.Margin = new Thickness(0, 0, 0, 14);
                Body.Children.Add(warn);
                var row = Buttons();
                var save = Theme.Button(L.T("Salva e verifica"), Theme.Kind.Primary);
                save.Margin = new Thickness(8, 0, 0, 0);
                save.Click += async (_, __) =>
                {
                    var k = box.Text.Trim();
                    if (k.Length < 20) { Msg.Show(this, L.T("Questa non sembra una chiave API di OpenAI: incollala per intero."), "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning); return; }
                    AiKey.Save(k);
                    box.Text = "";
                    await Test();
                };
                row.Children.Add(save);
                Loaded += (_, __) => box.Focus();
                return;
            }

            // a key is there: its state, test again, delete
            var state = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 4, 0, 6) };
            Body.Children.Add(Theme.Label(L.T("Chiave API salvata: ••••••••••••••••"), 12.5, Theme.TextSoft));
            Body.Children.Add(state);
            if (AiKey.Ok is bool ok)
            {
                var mark = Theme.Icon(ok ? Geometry.Parse("M5 12.5l4.5 4.5L19 7.5") : Geometry.Parse("M6 6l12 12 M18 6 6 18"), ok ? Theme.AxisY : Theme.Danger, 18, 2.4);
                mark.Margin = new Thickness(0, 0, 8, 0);
                mark.VerticalAlignment = VerticalAlignment.Top;
                state.Children.Add(mark);
                var t = Theme.Label(ok ? L.T("Funziona: la parte ChatGPT image è attiva.") + " " + AiKey.Message : AiKey.Message, 12.5, ok ? Theme.AxisY : Theme.Danger);
                t.TextWrapping = TextWrapping.Wrap;
                t.MaxWidth = 440;
                state.Children.Add(t);
            }
            else
                state.Children.Add(Theme.Label(L.T("Non ancora verificata"), 12.5, Theme.TextMuted));
            var b = Buttons();
            var del = Theme.Button(L.T("Elimina chiave"), Theme.Kind.Normal, L.T("Toglie la chiave da questo computer: le funzioni AI si spengono"));
            del.Margin = new Thickness(8, 0, 0, 0);
            del.Click += (_, __) =>
            {
                if (Msg.Show(this, L.T("Eliminare la chiave API da Simpler? Le funzioni AI si spengono finché non ne inserisci una."), "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
                AiKey.Delete();
                _changed();
                Build();
            };
            b.Children.Add(del);
            var again = Theme.Button(L.T("Verifica di nuovo"), Theme.Kind.Primary);
            again.Margin = new Thickness(8, 0, 0, 0);
            again.Click += async (_, __) => await Test();
            b.Children.Add(again);
        }

        void Para(string text)
        {
            var t = Theme.Label(text, 12.5, Theme.TextSoft);
            t.TextWrapping = TextWrapping.Wrap;
            t.Margin = new Thickness(0, 6, 0, 8);
            Body.Children.Add(t);
        }

        StackPanel Buttons()
        {
            var row = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 8, 0, 0) };
            var close = Theme.Button(L.T("Chiudi"), Theme.Kind.Ghost);
            close.Click += (_, __) => Close();
            row.Children.Add(close);
            Body.Children.Add(row);
            return row;
        }

        async Task Test()
        {
            IsEnabled = false;
            var before = System.Windows.Input.Mouse.OverrideCursor;   // (the arrow with the hourglass of a background job comes back)
            System.Windows.Input.Mouse.OverrideCursor = System.Windows.Input.Cursors.Wait;
            try { await AiKey.TestAsync(); }
            finally { System.Windows.Input.Mouse.OverrideCursor = before; IsEnabled = true; }
            _changed();
            Build();
        }
    }

    public sealed partial class MainWindow
    {
        Button _aiButton = null!;

        /// <summary>The classic AI icon: two four-pointed sparkles, filled.</summary>
        static readonly Geometry SparklesIcon = Geometry.Parse("M9.5,6 Q11.37,12.63 18,14.5 Q11.37,16.37 9.5,23 Q7.63,16.37 1,14.5 Q7.63,12.63 9.5,6 Z M18.5,1 Q19.49,4.51 23,5.5 Q19.49,6.49 18.5,10 Q17.51,6.49 14,5.5 Q17.51,4.51 18.5,1 Z");

        /// <summary>(1.76.60, Luca: «una mini macchina fotografica con le stelline della AI in alto a destra … mini ciack
        /// e stelline in alto a sinistra») the icon of an AI function: its picture, outlined, with the two sparkles of
        /// the AI small in a corner.</summary>
        /// (1.76.61, Luca: «i 3 tasti devono avere la stessa larghezza e le icone allineate … alla blu un altro simbolino
        /// che identifichi un render normale in alto a destra») badge: a small outlined symbol in place of the sparkles
        /// (the render: the sun of the light simulation) - the three buttons of the top right one style.
        static FrameworkElement AiIcon(Geometry picture, bool sparklesRight, Color color, Geometry? badge = null)
        {
            var g = new Grid { Width = 24, Height = 20 };
            var ic = Theme.Icon(picture, color, 17);
            ic.HorizontalAlignment = sparklesRight ? HorizontalAlignment.Left : HorizontalAlignment.Right;
            ic.VerticalAlignment = VerticalAlignment.Bottom;
            g.Children.Add(ic);
            FrameworkElement mark = badge != null ? Theme.Icon(badge, color, 10, 1.6)
                : new System.Windows.Shapes.Path { Data = SparklesIcon, Width = 10, Height = 10, Stretch = Stretch.Uniform, Fill = Theme.B(color) };
            mark.HorizontalAlignment = sparklesRight ? HorizontalAlignment.Right : HorizontalAlignment.Left;
            mark.VerticalAlignment = VerticalAlignment.Top;
            mark.Margin = new Thickness(0, -2, 0, 0);
            g.Children.Add(mark);
            return g;
        }

        const double TopButtonWidth = 46;      // (1.76.61) Render finale, AI, Video AI: one width

        /// <summary>The AI button: grey without a working key, orange (the colour of the AI functions) with one.</summary>
        void UpdateAiButton()
        {
            bool on = AiKey.Exists && AiKey.Ok == true;
            Theme.Style(_aiButton, on ? Theme.Kind.Ai : Theme.Kind.Ghost);
            _aiButton.Padding = new Thickness(0);
            _aiButton.Width = TopButtonWidth;
            _aiButton.Content = AiIcon(Icons.Camera, true, on ? Theme.AccentText : Theme.TextSoft);
            _aiButton.ToolTip = !AiKey.Exists ? L.T("AI: inserisci la tua chiave API di OpenAI per attivare le funzioni di intelligenza artificiale")
                : AiKey.Ok == true ? L.T("AI attiva (ChatGPT image)")
                : AiKey.Ok == false ? L.T("AI: la chiave non funziona - ") + AiKey.Message
                : L.T("AI: verifica della chiave in corso…");
        }

        /// <summary>At start: a saved key is tested in the background (the button turns blue when OpenAI answers).</summary>
        async Task TestAiKeyAtStart()
        {
            if (!AiKey.Exists) { UpdateAiButton(); return; }
            UpdateAiButton();
            await AiKey.TestAsync();
            UpdateAiButton();
        }

        void ShowAiDialog()
        {
            var d = new AiDialog(UpdateAiButton) { Owner = this };
            d.ShowDialog();
            UpdateAiButton();
        }
    }
}
