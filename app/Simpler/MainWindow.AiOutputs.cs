using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace Simpler
{
    /// <summary>One AI processing of this project: the picture sent (before), the result (after), a thumbnail.</summary>
    sealed class AiOutput
    {
        public string Id = "", Fn = "", Model = "", Quality = "";
        public string Kind = "image";     // (1.75.35) "image" | "video" (the AI video: After = the mp4, no Before)
        public string Name = "";          // (1.75.35) given by the user with Rinomina ("" = the function and the time)
        // (1.75.39) a video: everything that made it (model, resolution, seconds, audio, motion, the two keyframes with
        // the state of the scene) and the pictures of the two keyframes - a click puts them back in the Video AI panel
        public string Params = "", StartImg = "", EndImg = "";
        public DateTime When;
        public long TokensIn, TokensOut;
        public string Before = "", After = "", Thumb = "";       // full paths (session folder or project folder)
        public int Rating;                // (1.75.59) 1 = riuscita (green thumb up), -1 = malriuscita (red thumb down), 0 = none
    }

    /// <summary>
    /// The "Elaborazioni AI" tab of the library: every AI result of the open project, as a thumbnail; a click opens the
    /// before/after window. They belong to the project: saved in the folder "&lt;name&gt; AI" next to the .simpler when the
    /// project is saved (Salva con nome copies them), read back when it is opened, gone with Nuova scena. Until the
    /// project is saved they live in a folder of this session, deleted when Simpler closes: not saved = lost.
    /// </summary>
    public partial class MainWindow
    {
        readonly List<AiOutput> _aiOutputs = new();
        // (1.75.35) the tab has two fixed red folders, «Immagini AI» and «Video AI»: each result goes in its own and
        // stays there (no moving: only Rinomina and Elimina); "" = the two folders
        string _aiOutFolder = "";
        bool _aiOutputsDirty;

        static string AiSessionRoot => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Simpler", "ai-session");
        static readonly string AiSessionDir = Path.Combine(AiSessionRoot, Environment.ProcessId.ToString());

        static string AiProjectDir(string projectPath) =>
            Path.Combine(Path.GetDirectoryName(projectPath) ?? "", Path.GetFileNameWithoutExtension(projectPath) + " AI");

        /// <summary>At start: the session folders of Simpler instances that are no longer running go away.</summary>
        static void CleanAiSessions()
        {
            try
            {
                if (!Directory.Exists(AiSessionRoot)) return;
                foreach (var d in Directory.GetDirectories(AiSessionRoot))
                {
                    bool alive = false;
                    if (int.TryParse(Path.GetFileName(d), out var pid) && pid != Environment.ProcessId)
                        try { using var p = System.Diagnostics.Process.GetProcessById(pid); alive = p.ProcessName.Contains("Simpler", StringComparison.OrdinalIgnoreCase); } catch { }
                    if (!alive) try { Directory.Delete(d, true); } catch { }
                }
            }
            catch (Exception ex) { AppLog.Write("ai sessions: " + ex.Message); }
        }

        static void DeleteAiSessionDir()
        {
            try { if (Directory.Exists(AiSessionDir)) Directory.Delete(AiSessionDir, true); } catch { }
        }

        /// <summary>A new result: written to the session folder, first in the list, shown in the library.</summary>
        void AddAiOutput(BitmapSource before, BitmapSource after, string fn, string model, string quality, long tin, long tout)
        {
            try
            {
                Directory.CreateDirectory(AiSessionDir);
                var id = DateTime.Now.ToString("yyyyMMdd-HHmmss") + "-" + fn;
                var o = new AiOutput
                {
                    Id = id, Fn = fn, Model = model, Quality = quality, When = DateTime.Now, TokensIn = tin, TokensOut = tout,
                    Before = Path.Combine(AiSessionDir, id + "-prima.png"), After = Path.Combine(AiSessionDir, id + "-dopo.png"),
                    Thumb = Path.Combine(AiSessionDir, id + "-mini.jpg"),
                };
                File.WriteAllBytes(o.Before, AiImage.Png(before));
                File.WriteAllBytes(o.After, AiImage.Png(after));
                File.WriteAllBytes(o.Thumb, Thumbnail(after));
                _aiOutputs.Insert(0, o);
                _aiOutputsDirty = true;
                _libraryTab = "aioutputs";
                _aiOutFolder = "images";
                RenderLibrary();
            }
            catch (Exception ex) { AppLog.Write("ai output: " + ex.Message); Status(L.T("Non riesco a conservare l'elaborazione AI: ") + ex.Message); }
        }

        /// <summary>(1.75.35) Where a new AI video is downloaded: the session folder, like the AI images (into the
        /// project folder «nome AI» when the project is saved).</summary>
        static string NewAiVideoPath(out string id)
        {
            Directory.CreateDirectory(AiSessionDir);
            id = DateTime.Now.ToString("yyyyMMdd-HHmmss") + "-video";
            return Path.Combine(AiSessionDir, id + ".mp4");
        }

        /// <summary>(1.75.35) A new AI video: first in the list, in the folder «Video AI». The thumbnail is the start keyframe.</summary>
        void AddAiVideo(string id, string mp4, string? startFrame, string model, string res, int seconds, string? recipeDir = null)
        {
            try
            {
                var o = new AiOutput { Id = id, Kind = "video", Fn = "video", Model = model, Quality = $"{res}, {seconds} s", When = DateTime.Now, After = mp4,
                                       Thumb = Path.Combine(Path.GetDirectoryName(mp4)!, id + "-mini.jpg") };
                // (1.75.39) the recipe of the video, with the pictures of its keyframes, next to it
                if (recipeDir != null && File.Exists(Path.Combine(recipeDir, "recipe.json")))
                {
                    try
                    {
                        var dir = Path.GetDirectoryName(mp4)!;
                        o.Params = File.ReadAllText(Path.Combine(recipeDir, "recipe.json"));
                        foreach (var (src, set) in new (string, Action<string>)[] { ("start.jpg", v => o.StartImg = v), ("end.jpg", v => o.EndImg = v) })
                        {
                            var from = Path.Combine(recipeDir, src);
                            if (!File.Exists(from)) continue;
                            var to = Path.Combine(dir, id + "-" + src);
                            File.Copy(from, to, true);
                            set(to);
                        }
                        if (File.Exists(o.StartImg)) startFrame = o.StartImg;
                        try { Directory.Delete(recipeDir, true); } catch { }
                    }
                    catch (Exception ex) { AppLog.Write("ai video recipe: " + ex.Message); }
                }
                if (startFrame != null && File.Exists(startFrame))
                    try { File.WriteAllBytes(o.Thumb, Thumbnail(AiImage.Decode(File.ReadAllBytes(startFrame), 1280))); } catch { o.Thumb = ""; }
                _aiOutputs.Insert(0, o);
                _aiOutputsDirty = true;
                _libraryTab = "aioutputs";
                _aiOutFolder = "videos";
                RenderLibrary();
            }
            catch (Exception ex) { AppLog.Write("ai video output: " + ex.Message); }
        }

        static byte[] Thumbnail(BitmapSource src)
        {
            double k = Math.Min(1, 320.0 / Math.Max(src.PixelWidth, src.PixelHeight));
            var t = new TransformedBitmap(src, new ScaleTransform(k, k));
            var enc = new JpegBitmapEncoder { QualityLevel = 88 };
            enc.Frames.Add(BitmapFrame.Create(t));
            using var ms = new MemoryStream();
            enc.Save(ms);
            return ms.ToArray();
        }

        /// <summary>Nuova scena: the list empties (the results not saved are lost, as the rest of the scene).</summary>
        void ClearAiOutputs()
        {
            _promptBefore = null;          // (1.75.44) «Annulla» of «Migliora con l'AI» belongs to the project left
            _aiOutputs.Clear();
            _aiOutputsDirty = false;
            DeleteAiSessionDir();
        }

        /// <summary>Opening a project: its results from the folder "&lt;name&gt; AI" (if there is one).</summary>
        void LoadAiOutputs(string projectPath)
        {
            ClearAiOutputs();
            try
            {
                var dir = AiProjectDir(projectPath);
                var index = Path.Combine(dir, "index.json");
                if (!File.Exists(index)) return;
                var arr = JsonNode.Parse(File.ReadAllText(index))?["outputs"] as JsonArray;
                foreach (var n in arr?.OfType<JsonObject>() ?? Enumerable.Empty<JsonObject>())
                {
                    var o = new AiOutput
                    {
                        Id = (string?)n["id"] ?? "", Fn = (string?)n["fn"] ?? "", Kind = (string?)n["kind"] ?? "image", Name = (string?)n["name"] ?? "", Model = (string?)n["model"] ?? "", Quality = (string?)n["quality"] ?? "",
                        TokensIn = (long?)n["in"] ?? 0, TokensOut = (long?)n["out"] ?? 0, Rating = Math.Clamp((int?)n["rating"] ?? 0, -1, 1),
                        Before = (string?)n["before"] is string bf && bf != "" ? Path.Combine(dir, bf) : "", After = Path.Combine(dir, (string?)n["after"] ?? ""),
                        Thumb = (string?)n["thumb"] is string th && th != "" ? Path.Combine(dir, th) : "",
                        Params = (string?)n["params"] ?? "",
                        StartImg = (string?)n["startImg"] is string si && si != "" ? Path.Combine(dir, si) : "",
                        EndImg = (string?)n["endImg"] is string ei && ei != "" ? Path.Combine(dir, ei) : "",
                    };
                    DateTime.TryParse((string?)n["when"], null, System.Globalization.DateTimeStyles.RoundtripKind, out o.When);
                    if (File.Exists(o.After)) _aiOutputs.Add(o);
                }
            }
            catch (Exception ex) { AppLog.Write("ai outputs load: " + ex.Message); }
        }

        /// <summary>Saving the project: the results go to the folder "&lt;name&gt; AI" next to it (copied from the session
        /// or from the folder of the project it was saved from before), the ones deleted from the list leave it.</summary>
        void SaveAiOutputs(string projectPath)
        {
            var dir = AiProjectDir(projectPath);
            try
            {
                if (_aiOutputs.Count == 0)
                {
                    if (Directory.Exists(dir)) RemoveManaged(dir, new HashSet<string>(StringComparer.OrdinalIgnoreCase));
                    _aiOutputsDirty = false;
                    return;
                }
                Directory.CreateDirectory(dir);
                var keep = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                string Bring(string file)
                {
                    if (file == "") return "";
                    var target = Path.Combine(dir, Path.GetFileName(file));
                    if (!string.Equals(Path.GetFullPath(file), Path.GetFullPath(target), StringComparison.OrdinalIgnoreCase) && File.Exists(file))
                        File.Copy(file, target, true);
                    keep.Add(Path.GetFileName(target));
                    return target;
                }
                var arr = new JsonArray();
                foreach (var o in _aiOutputs)
                {
                    o.Before = Bring(o.Before); o.After = Bring(o.After); o.Thumb = Bring(o.Thumb);
                    o.StartImg = Bring(o.StartImg); o.EndImg = Bring(o.EndImg);
                    arr.Add(new JsonObject
                    {
                        ["id"] = o.Id, ["kind"] = o.Kind, ["name"] = o.Name, ["fn"] = o.Fn, ["model"] = o.Model, ["quality"] = o.Quality, ["when"] = o.When.ToString("o"),
                        ["in"] = o.TokensIn, ["out"] = o.TokensOut, ["rating"] = o.Rating,
                        ["before"] = Path.GetFileName(o.Before), ["after"] = Path.GetFileName(o.After), ["thumb"] = Path.GetFileName(o.Thumb),
                        ["params"] = o.Params, ["startImg"] = Path.GetFileName(o.StartImg), ["endImg"] = Path.GetFileName(o.EndImg),
                    });
                }
                File.WriteAllText(Path.Combine(dir, "index.json"), new JsonObject { ["version"] = 1, ["outputs"] = arr }.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
                keep.Add("index.json");
                RemoveManaged(dir, keep);
                _aiOutputsDirty = false;
            }
            catch (Exception ex)
            {
                AppLog.Write("ai outputs save: " + ex.Message);
                Msg.Show(this, L.F("Il progetto è salvato, ma non riesco a salvare le elaborazioni AI nella cartella «{0}»:\n{1}", dir, ex.Message),
                    "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning);
            }
        }

        /// <summary>Deletes from the folder the files Simpler wrote (pictures of results no longer in the list); anything
        /// else the user put there stays, and so does the folder if it is not empty.</summary>
        static void RemoveManaged(string dir, HashSet<string> keep)
        {
            var gone = new List<string>();
            foreach (var f in Directory.GetFiles(dir))
            {
                var name = Path.GetFileName(f);
                bool ours = name.Equals("index.json", StringComparison.OrdinalIgnoreCase)
                            || name.EndsWith("-prima.png", StringComparison.OrdinalIgnoreCase) || name.EndsWith("-dopo.png", StringComparison.OrdinalIgnoreCase)
                            || name.EndsWith("-mini.jpg", StringComparison.OrdinalIgnoreCase) || name.EndsWith("-video.mp4", StringComparison.OrdinalIgnoreCase)
                            || name.EndsWith("-video-start.jpg", StringComparison.OrdinalIgnoreCase) || name.EndsWith("-video-end.jpg", StringComparison.OrdinalIgnoreCase);
                if (ours && !keep.Contains(name)) gone.Add(f);
            }
            RecycleBin.Send(gone);            // (1.76.7) to the Recycle Bin, not deleted: they can be taken back
            RecycleBin.SendIfEmpty(new[] { dir });
        }

        string AiOutputTitle(AiOutput o)
        {
            if (o.Name != "") return o.Name;
            // (1.75.41) with the model that made it: Video · Kling 3.0 · 01/11 10:20, Render AI · GPT Image 2 · …
            var model = o.Model == "" ? "" : " · " + (o.Kind == "video" ? o.Model : ModelInfo(o.Model).name);
            if (o.Kind == "video") return L.T("Video") + model + " · " + o.When.ToString("dd/MM HH:mm");
            var f = AiPrompts.Functions.FirstOrDefault(x => x.Key == o.Fn);
            return (f != null ? L.T(f.Name) : o.Fn) + model + " · " + o.When.ToString("dd/MM HH:mm");
        }

        /// <summary>(1.75.41) A title as a file name: the characters Windows does not take become «-».</summary>
        static string SafeFileName(string t)
        {
            foreach (var c in Path.GetInvalidFileNameChars().Concat(new[] { ':', '/', '\\' })) t = t.Replace(c, '-');
            return t.Replace(" · ", " - ").Trim();
        }

        void OpenAiOutput(AiOutput o)
        {
            if (o.Kind == "video")
            {
                if (o.Params != "") _ = RestoreVideoRecipe(o);      // (1.75.39) its parameters back in the Video AI panel
                if (File.Exists(o.After)) ShowVideo(o.After);
                else Msg.Show(this, L.T("Il file del video non c'è più: ") + o.After, "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }
            try
            {
                var before = File.Exists(o.Before) ? AiImage.Decode(File.ReadAllBytes(o.Before)) : null;
                var after = AiImage.Decode(File.ReadAllBytes(o.After));
                var w = before != null ? new AiImageWindow(this, "Simpler AI · " + AiOutputTitle(o), before, after, SetAiImage, o.After)
                                       : new AiImageWindow(this, "Simpler AI · " + AiOutputTitle(o), after, null, SetAiImage, o.After);
                w.Show();
            }
            catch (Exception ex) { Msg.Show(this, L.T("Non riesco a leggere l'immagine: ") + ex.Message, "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning); }
        }

        /// <summary>The library tab: one tile per result, the newest first.</summary>
        void RenderAiOutputs()
        {
            if (_aiOutFolder is not ("images" or "videos")) _aiOutFolder = "";
            string Label(string f) => f == "videos" ? (L.Lang == "en" ? "AI videos" : "Video AI") : L.T("Immagini AI");
            if (_aiOutFolder == "")
            {
                // the two folders of Simpler: red like its other fixed folders, no menu (not renamed, moved or deleted)
                foreach (var f in new[] { "images", "videos" })
                {
                    int n = _aiOutputs.Count(o => (o.Kind == "video") == (f == "videos"));
                    var sub = f == "videos" ? (n == 1 ? L.T("1 video") : L.F("{0} video", n)) : (n == 1 ? L.T("1 immagine") : L.F("{0} immagini", n));
                    var tile = BigTile(TileIcon(Icons.Folder, Theme.C("#E5534B")), Label(f), sub,
                                       Label(f) + "\n" + (f == "videos" ? L.T("I video fatti con il Video AI in questo progetto") : L.T("Le immagini fatte con l'AI in questo progetto")) + " · " + L.T("Clic per aprire"));
                    var folder = f;
                    tile.Click += (_, __) => { _aiOutFolder = folder; RenderLibrary(); };
                    _libraryTiles.Children.Add(tile);
                }
                return;
            }
            RenderCrumbs(L.T("Elaborazioni AI"), Label(_aiOutFolder), _ => _aiOutFolder = "", null);
            _libraryTiles.Children.Add(UpTile("", _ => _aiOutFolder = "", false));
            var list = _aiOutputs.Where(o => (o.Kind == "video") == (_aiOutFolder == "videos")).ToList();
            if (list.Count == 0)
            {
                var t = new TextBlock
                {
                    Text = _aiOutFolder == "videos" ? L.T("Nessun video AI in questo progetto. Usa il pulsante con il ciak: ogni video compare qui.")
                                                    : L.T("Nessuna elaborazione AI in questo progetto. Usa il pulsante con le stelline: ogni risultato compare qui."),
                    FontSize = 12, Foreground = Theme.B(Theme.TextFaint), TextWrapping = TextWrapping.Wrap, MaxWidth = 420, Margin = new Thickness(8, 12, 8, 0),
                };
                _libraryTiles.Children.Add(t);
                return;
            }
            foreach (var o in list)
            {
                var grid = new Grid { Width = 168, Height = 122 };
                grid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
                grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
                var img = new Image { Stretch = Stretch.Uniform, Margin = new Thickness(0, 0, 0, 4) };
                try
                {
                    var bmp = new BitmapImage();
                    bmp.BeginInit();
                    bmp.CacheOption = BitmapCacheOption.OnLoad;
                    if (!File.Exists(o.Thumb) && o.Kind == "video") throw new FileNotFoundException();
                    bmp.UriSource = new Uri(File.Exists(o.Thumb) ? o.Thumb : o.After);
                    bmp.DecodePixelWidth = 320;
                    bmp.EndInit();
                    bmp.Freeze();
                    img.Source = bmp;
                }
                catch { }
                grid.Children.Add(img);
                if (o.Rating != 0)
                {
                    // (1.75.59) the judgement of the user, small at the top right of the picture
                    var badge = new Border
                    {
                        Width = 24, Height = 24, CornerRadius = new CornerRadius(12), Margin = new Thickness(0, 4, 4, 0),
                        HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Top,
                        Background = Theme.B(o.Rating > 0 ? "#2EA043" : "#E5534B"), BorderBrush = Theme.B("#0A1222"), BorderThickness = new Thickness(1.5),
                        Child = Theme.Icon(o.Rating > 0 ? Icons.ThumbUp : Icons.ThumbDown, Colors.White, 12, 2),
                        ToolTip = o.Rating > 0 ? L.T("Riuscita") : L.T("Malriuscita"),
                    };
                    ((FrameworkElement)badge.Child).HorizontalAlignment = HorizontalAlignment.Center;
                    grid.Children.Add(badge);
                }
                var row = new DockPanel();
                Grid.SetRow(row, 1);
                var more = SmallIconButton(Icons.Dots, o.Kind == "video" ? L.T("Apri, salva, rinomina, elimina") : L.T("Elabora, salva, rinomina, elimina"));
                var cur = o;
                more.Click += (_, e) => { e.Handled = true; AiOutputMenu(more, cur).IsOpen = true; };
                DockPanel.SetDock(more, Dock.Right);
                row.Children.Add(more);
                row.Children.Add(new TextBlock { Text = AiOutputTitle(o), FontSize = 12, Foreground = Theme.B(Theme.TextSoft), VerticalAlignment = VerticalAlignment.Center, TextTrimming = TextTrimming.CharacterEllipsis });
                grid.Children.Add(row);
                var tip = o.Kind == "video" ? L.F("{0} · {1}, {2} · {3}", AiOutputTitle(o), o.Model, o.Quality, o.When.ToString("dd/MM/yyyy HH:mm"))
                        : L.F("{0} · {1}, qualità {2} · {3} token in, {4} out", AiOutputTitle(o), o.Model, o.Quality, o.TokensIn.ToString("N0"), o.TokensOut.ToString("N0"));
                var btn = Theme.Button(grid, Theme.Kind.Normal, tip);
                btn.Padding = new Thickness(5);
                btn.Margin = new Thickness(4);
                btn.Height = 130;
                btn.Click += (_, __) => OpenAiOutput(cur);
                _libraryTiles.Children.Add(btn);
            }
        }

        ContextMenu AiOutputMenu(FrameworkElement anchor, AiOutput o)
        {
            var m = new ContextMenu { PlacementTarget = anchor, Placement = System.Windows.Controls.Primitives.PlacementMode.Bottom };
            void Item(string text, Action act) { var i = new MenuItem { Header = text }; i.Click += (_, __) => act(); m.Items.Add(i); }
            if (o.Kind == "video")
            {
                Item(L.T("Apri il video"), () => OpenAiOutput(o));
                if (o.Params != "") Item(L.T("Carica i parametri nel pannello Video AI"), () => _ = RestoreVideoRecipe(o));
                Item(L.T("Salva video…"), () =>
                {
                    var dlg = new Microsoft.Win32.SaveFileDialog { Filter = "MP4|*.mp4", InitialDirectory = StartFolder("render"), FileName = SafeFileName(AiOutputTitle(o)) + ".mp4" };
                    if (dlg.ShowDialog(this) != true) return;
                    Keep("render", dlg.FileName);
                    try { File.Copy(o.After, dlg.FileName, true); Status(L.F("Video salvato: {0}", dlg.FileName)); }
                    catch (Exception ex) { Msg.Show(this, ex.Message, "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning); }
                });
            }
            else
            {
            Item(L.T("Apri il confronto"), () => OpenAiOutput(o));
            Item(L.T("Elabora con l'AI"), () =>
            {
                try { SetAiImage(AiImage.Decode(File.ReadAllBytes(o.After)), AiOutputTitle(o)); }
                catch (Exception ex) { Msg.Show(this, L.T("Non riesco a leggere l'immagine: ") + ex.Message, "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning); }
            });
            Item(L.T("Salva immagine…"), () =>
            {
                var dlg = new Microsoft.Win32.SaveFileDialog { Filter = L.T("PNG|*.png"), InitialDirectory = StartFolder("render"), FileName = SafeFileName(AiOutputTitle(o)) + ".png" };
                if (dlg.ShowDialog(this) != true) return;
                Keep("render", dlg.FileName);
                try { File.Copy(o.After, dlg.FileName, true); Status(L.T("Immagine salvata: ") + dlg.FileName); }
                catch (Exception ex) { Msg.Show(this, ex.Message, "Simpler", MessageBoxButton.OK, MessageBoxImage.Warning); }
            });
            }
            m.Items.Add(new Separator());
            // (1.75.59) good or failed: a green thumb up or a red thumb down on the thumbnail (click again: off)
            void Rate(string text, int value, Geometry icon, string color)
            {
                var i = new MenuItem { Header = text, Icon = Theme.Icon(icon, Theme.C(color), 14, 1.8), IsCheckable = true, IsChecked = o.Rating == value };
                i.Click += (_, __) => { o.Rating = o.Rating == value ? 0 : value; _aiOutputsDirty = true; RenderLibrary(); };
                m.Items.Add(i);
            }
            Rate(L.T("Riuscita"), 1, Icons.ThumbUp, "#2EA043");
            Rate(L.T("Malriuscita"), -1, Icons.ThumbDown, "#E5534B");
            m.Items.Add(new Separator());
            Item(L.T("Rinomina…"), () =>
            {
                var name = InputDialog.Ask(this, L.T("Rinomina"), L.T("Nuovo nome"), AiOutputTitle(o));
                if (name == null) return;
                o.Name = name.Trim();
                _aiOutputsDirty = true;
                RenderLibrary();
            });
            Item(L.T("Elimina"), () =>
            {
                if (Msg.Show(this, o.Kind == "video" ? L.F("Eliminare il video «{0}»?", AiOutputTitle(o)) : L.F("Eliminare l'elaborazione «{0}»?", AiOutputTitle(o)), "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
                _aiOutputs.Remove(o);
                _aiOutputsDirty = true;
                // a result of this session goes away now; one already in the project folder when the project is saved
                if (o.After.StartsWith(AiSessionDir, StringComparison.OrdinalIgnoreCase))
                    foreach (var f in new[] { o.Before, o.After, o.Thumb, o.StartImg, o.EndImg }) try { File.Delete(f); } catch { }
                RenderLibrary();
            });
            return m;
        }
    }
}
