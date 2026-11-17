using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace Simpler
{
    /// <summary>(1.75.34) The AI video without sound: Krea no longer lets the audio be turned off (generate_audio
    /// removed on 30/10/2026), so the sound track is taken out of the MP4 here. The «trak» box of the sound becomes a
    /// «free» box of the same size: nothing moves in the file, the video is not encoded again, every player ignores it.</summary>
    public static class Mp4
    {
        /// <summary>Number of sound tracks taken out (0 = there were none, or the file is not an MP4 Simpler can read).</summary>
        public static int StripAudio(string path)
        {
            var d = File.ReadAllBytes(path);
            int n = 0;
            foreach (var (o, h, sz, t) in Boxes(d, 0, d.LongLength))
            {
                if (t != "moov") continue;
                foreach (var (to, th, tsz, tt) in Boxes(d, o + h, o + sz))
                {
                    if (tt != "trak") continue;
                    var mdia = Find(d, to + th, to + tsz, "mdia");
                    if (mdia == null) continue;
                    var hdlr = Find(d, mdia.Value.o + mdia.Value.h, mdia.Value.o + mdia.Value.sz, "hdlr");
                    if (hdlr == null) continue;
                    long ht = hdlr.Value.o + hdlr.Value.h + 8;        // version/flags (4) + pre_defined (4), then the handler type
                    if (ht + 4 <= d.LongLength && Encoding.ASCII.GetString(d, (int)ht, 4) == "soun")
                    {
                        Encoding.ASCII.GetBytes("free").CopyTo(d, (int)to + 4);
                        n++;
                    }
                }
            }
            if (n > 0)
            {
                var tmp = path + ".tmp";
                File.WriteAllBytes(tmp, d);
                File.Move(tmp, path, true);
            }
            return n;
        }

        static (long o, long h, long sz)? Find(byte[] d, long off, long end, string type)
        {
            foreach (var (o, h, sz, t) in Boxes(d, off, end))
                if (t == type) return (o, h, sz);
            return null;
        }

        static IEnumerable<(long o, long h, long sz, string t)> Boxes(byte[] d, long off, long end)
        {
            while (off + 8 <= end)
            {
                long sz = (long)((uint)d[off] << 24 | (uint)d[off + 1] << 16 | (uint)d[off + 2] << 8 | d[off + 3]);
                var t = Encoding.ASCII.GetString(d, (int)off + 4, 4);
                long h = 8;
                if (sz == 1)
                {
                    if (off + 16 > end) yield break;
                    sz = 0;
                    for (int i = 0; i < 8; i++) sz = sz << 8 | d[off + 8 + i];
                    h = 16;
                }
                else if (sz == 0) sz = end - off;
                if (sz < h || off + sz > end) yield break;
                yield return (off, h, sz, t);
                off += sz;
            }
        }
    }
}
