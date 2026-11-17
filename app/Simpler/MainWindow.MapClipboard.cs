using System;
using System.IO;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace Simpler
{
    /// <summary>
    /// Right click on the map of a material (its thumbnail or its file name): preview, open the folder, copy the map,
    /// paste the map copied before. The paste takes only maps copied in Simpler (a private format on the Windows
    /// clipboard): in the same project the image itself (embedded ones too), in another project or another Simpler its
    /// file on disk. The copy also puts the picture and the file on the clipboard, for Photoshop or Explorer.
    /// </summary>
    public partial class MainWindow
    {
        const string MapClipFormat = "Simpler.MaterialMap";

        ContextMenu MapMenu(string path, string image, JsonObject? info)
        {
            var m = new ContextMenu();
            var file = (string?)info?["path"] ?? "";
            void Item(string text, bool enabled, Func<Task> act)
            {
                var i = new MenuItem { Header = text, IsEnabled = enabled };
                i.Click += async (_, __) => await act();
                m.Items.Add(i);
            }
            Item(L.T("Anteprima"), image != "", async () =>
            {
                if (_host == null) return;
                await TextureViewer.Show(this, TexHttp, _host.Port, image, (string?)info?["file"] ?? image, file,
                                         (int?)info?["width"] ?? 0, (int?)info?["height"] ?? 0, (bool?)info?["packed"] ?? false);
            });
            Item(L.T("Apri la cartella"), image != "" && File.Exists(file), () =>
            {
                try { System.Diagnostics.Process.Start("explorer.exe", "/select,\"" + file + "\""); } catch { }
                return Task.CompletedTask;
            });
            m.Items.Add(new Separator());
            Item(L.T("Copia la mappa"), image != "", async () => await CopyMap(image, info));
            bool canPaste = false;
            try { canPaste = Clipboard.ContainsData(MapClipFormat); } catch { }
            Item(L.T("Incolla la mappa"), canPaste, async () => await PasteMap(path));
            Item(L.T("Incolla immagine dagli appunti"), ClipboardHasPicture(), async () =>
            {
                var f = ClipboardPictureFile();
                if (f == null) { Status(L.T("Negli appunti non c'è un'immagine")); return; }
                await EditMat(path, new JsonObject { ["file"] = f.Value.path, ["pack"] = f.Value.pasted }, true);
                Status(L.F("Immagine incollata come mappa: {0}", Path.GetFileName(f.Value.path)) + (f.Value.pasted ? " · " + L.T("incorporata nel progetto") : ""));
            });
            return m;
        }

        static readonly string[] PictureExt = { ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".hdr", ".bmp", ".tga", ".webp" };

        /// <summary>A picture in the clipboard: a cut-out (Win+Shift+S, a picture copied in a browser or in a graphics
        /// program) or an image file copied in Explorer.</summary>
        static bool ClipboardHasPicture()
        {
            try
            {
                if (Clipboard.ContainsImage() || Clipboard.ContainsData("PNG")) return true;
                if (Clipboard.ContainsFileDropList())
                    foreach (var f in Clipboard.GetFileDropList())
                        if (f != null && PictureExt.Contains(Path.GetExtension(f).ToLowerInvariant())) return true;
            }
            catch { }
            return false;
        }

        /// <summary>The clipboard picture as a file: an image file copied in Explorer as it is; a cut-out saved as PNG
        /// (its transparency kept when the program gives one) in %LOCALAPPDATA%\Simpler\pasted, to be embedded in the
        /// project - so there is no need to save it from a graphics program first.</summary>
        (string path, bool pasted)? ClipboardPictureFile()
        {
            try
            {
                if (Clipboard.ContainsFileDropList())
                    foreach (var f in Clipboard.GetFileDropList())
                        if (f != null && File.Exists(f) && PictureExt.Contains(Path.GetExtension(f).ToLowerInvariant())) return (f, false);
                var pastedRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Simpler", "pasted");
                // (pictures pasted days ago are already inside their projects: their files are not needed any more)
                try { foreach (var old in Directory.Exists(pastedRoot) ? Directory.GetDirectories(pastedRoot) : Array.Empty<string>())
                          if (Directory.GetLastWriteTime(old) < DateTime.Now.AddDays(-7)) try { Directory.Delete(old, true); } catch { } } catch { }
                var dir = Path.Combine(pastedRoot, Guid.NewGuid().ToString("N"));
                var file = Path.Combine(dir, L.T("appunti") + "-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + ".png");
                // the PNG the program put there (with transparency), else the bitmap
                if (Clipboard.ContainsData("PNG") && Clipboard.GetData("PNG") is MemoryStream ms && ms.Length > 0)
                {
                    Directory.CreateDirectory(dir);
                    File.WriteAllBytes(file, ms.ToArray());
                    return (file, true);
                }
                var img = Clipboard.GetImage();
                if (img == null) return null;
                // (the bitmap of the clipboard has no real alpha: drawn opaque, so a cut-out never comes in see-through)
                var opaque = new FormatConvertedBitmap(img, PixelFormats.Bgr24, null, 0);
                var enc = new PngBitmapEncoder();
                enc.Frames.Add(BitmapFrame.Create(opaque));
                Directory.CreateDirectory(dir);
                using (var fs = File.Create(file)) enc.Save(fs);
                return (file, true);
            }
            catch (Exception ex) { AppLog.Write("clipboard picture: " + ex.Message); return null; }
        }

        async Task CopyMap(string image, JsonObject? info)
        {
            var file = (string?)info?["path"] ?? "";
            var clip = new JsonObject
            {
                ["image"] = image, ["path"] = file, ["file"] = (string?)info?["file"] ?? image,
                ["process"] = Environment.ProcessId, ["project"] = _aiProjectGen,
            };
            var data = new DataObject();
            data.SetData(MapClipFormat, clip.ToJsonString());
            // the picture too (other programs): from the file, or from the engine when it is embedded in the project
            try
            {
                byte[]? bytes = File.Exists(file) ? await File.ReadAllBytesAsync(file)
                              : _host != null ? await TexHttp.GetByteArrayAsync($"http://127.0.0.1:{_host.Port}/api/texture?image={Uri.EscapeDataString(image)}&px=4096")
                              : null;
                if (bytes != null)
                {
                    var bmp = new BitmapImage();
                    bmp.BeginInit();
                    bmp.CacheOption = BitmapCacheOption.OnLoad;
                    bmp.StreamSource = new MemoryStream(bytes);
                    bmp.EndInit();
                    bmp.Freeze();
                    data.SetImage(bmp);
                }
            }
            catch (Exception ex) { AppLog.Write("map copy picture: " + ex.Message); }
            if (File.Exists(file)) data.SetFileDropList(new System.Collections.Specialized.StringCollection { file });
            try { Clipboard.SetDataObject(data, true); Status(L.F("Mappa copiata: {0}", (string?)clip["file"] ?? image)); }
            catch (Exception ex) { Status(L.T("Non riesco a copiare negli appunti: ") + ex.Message); }
        }

        async Task PasteMap(string path)
        {
            JsonObject? clip = null;
            try { if (Clipboard.GetData(MapClipFormat) is string s) clip = JsonNode.Parse(s) as JsonObject; } catch { }
            if (clip == null) { Status(L.T("Negli appunti non c'è una mappa copiata in Simpler")); return; }
            var image = (string?)clip["image"] ?? "";
            var file = (string?)clip["path"] ?? "";
            bool sameProject = (int?)clip["process"] == Environment.ProcessId && (int?)clip["project"] == _aiProjectGen;
            JsonObject value;
            if (sameProject && image != "") value = new JsonObject { ["image"] = image };
            else if (File.Exists(file)) value = new JsonObject { ["file"] = file };
            else
            {
                Msg.Show(this, L.T("La mappa copiata era incorporata in un altro progetto e non ha un file sul disco: non posso incollarla qui. Copiala di nuovo da questo progetto, o caricala dal suo file."),
                         "Simpler", MessageBoxButton.OK, MessageBoxImage.Information);
                return;
            }
            await EditMat(path, value, true);
            Status(L.F("Mappa incollata: {0}", (string?)clip["file"] ?? image));
        }
    }
}
