using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;

namespace Simpler
{
    /// <summary>(1.76.7) Files and folders moved to the Windows Recycle Bin (they can be taken back), not deleted.</summary>
    public static class RecycleBin
    {
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        struct SHFILEOPSTRUCT
        {
            public IntPtr hwnd;
            public uint wFunc;
            public string pFrom;
            public string? pTo;
            public ushort fFlags;
            [MarshalAs(UnmanagedType.Bool)] public bool fAnyOperationsAborted;
            public IntPtr hNameMappings;
            public string? lpszProgressTitle;
        }

        [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
        static extern int SHFileOperation(ref SHFILEOPSTRUCT op);

        const uint FO_DELETE = 3;
        const ushort FOF_SILENT = 0x0004, FOF_NOCONFIRMATION = 0x0010, FOF_ALLOWUNDO = 0x0040, FOF_NOERRORUI = 0x0400;

        /// <summary>The paths that exist go to the Recycle Bin; returns how many were moved.</summary>
        public static int Send(IEnumerable<string> paths)
        {
            var list = paths.Where(p => !string.IsNullOrWhiteSpace(p) && (File.Exists(p) || Directory.Exists(p)))
                            .Select(p => Path.GetFullPath(p)).Distinct(StringComparer.OrdinalIgnoreCase).ToList();
            if (list.Count == 0) return 0;
            var op = new SHFILEOPSTRUCT
            {
                wFunc = FO_DELETE,
                pFrom = string.Join("\0", list) + "\0\0",
                fFlags = (ushort)(FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI),
            };
            try
            {
                int rc = SHFileOperation(ref op);
                if (rc != 0 || op.fAnyOperationsAborted) AppLog.Write($"recycle bin: code {rc} for {list.Count} items");
            }
            catch (Exception ex) { AppLog.Write("recycle bin: " + ex.Message); return 0; }
            var moved = list.Count(p => !File.Exists(p) && !Directory.Exists(p));
            AppLog.Write($"recycle bin: {moved} of {list.Count} moved");
            return moved;
        }

        /// <summary>Folders left empty: moved too (nothing inside to lose).</summary>
        public static void SendIfEmpty(IEnumerable<string> folders)
        {
            foreach (var d in folders.OrderByDescending(f => f.Length))
                try { if (Directory.Exists(d) && !Directory.EnumerateFileSystemEntries(d).Any()) Send(new[] { d }); } catch { }
        }
    }
}
