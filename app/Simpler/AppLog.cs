using System;
using System.IO;
using System.Text;

namespace Simpler
{
    /// <summary>A prefix for the files of this program in %LOCALAPPDATA%\Simpler (logs, data of the 3D view): empty for
    /// Simpler; another tool built from these sources sets its own, so the two can run side by side.</summary>
    public static class AppInstance
    {
        public static string Prefix = "";
    }

    /// <summary>The app's own log (%LOCALAPPDATA%\Simpler\app.log): why the 3D view was prepared again, and similar.</summary>
    public static class AppLog
    {
        static readonly object Lock = new();
        static string PathName => System.IO.Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Simpler", AppInstance.Prefix + "app.log");

        /// <summary>The file of the log (read by the diagnostics).</summary>
        public static string FilePath => PathName;

        public static void Write(string line)
        {
            try
            {
                lock (Lock)
                {
                    Directory.CreateDirectory(System.IO.Path.GetDirectoryName(PathName)!);
                    var fi = new FileInfo(PathName);
                    if (fi.Exists && fi.Length > 1_000_000) File.Delete(PathName);
                    File.AppendAllText(PathName, $"{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff} {line}{Environment.NewLine}", Encoding.UTF8);
                }
            }
            catch { /* logging must never disturb the app */ }
        }
    }
}
