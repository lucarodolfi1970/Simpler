using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Windows;
using System.Windows.Controls;

namespace Simpler
{
    /// <summary>App settings: language, version and release notes.</summary>
    public sealed class SettingsDialog : ThemedDialog
    {
        public static string Version
        {
            get
            {
                var v = Assembly.GetExecutingAssembly().GetName().Version ?? new Version(1, 0, 0);
                return $"{v.Major}.{v.Minor}.{v.Build}";
            }
        }

        public SettingsDialog() : base(L.T("Impostazioni"), 480)
        {

            var sp = new StackPanel { Margin = new Thickness(0, 0, 0, 2) };
            sp.Children.Add(Theme.Label(L.T("Impostazioni"), 18, Theme.Text, FontWeights.SemiBold));

            sp.Children.Add(Spacer(16));
            sp.Children.Add(Theme.Caption(L.T("Lingua")));
            var langs = Theme.Segmented(out var langButtons, ("Italiano", null), ("English", null));
            langs.HorizontalAlignment = HorizontalAlignment.Left;
            langs.Margin = new Thickness(0, 8, 0, 4);
            Theme.SetSegment(langButtons, L.Lang == "en" ? 1 : 0);
            string[] ids = { "it", "en" };
            for (int i = 0; i < langButtons.Count; i++)
            {
                var id = ids[i];
                var idx = i;
                langButtons[i].Click += (_, __) =>
                {
                    Theme.SetSegment(langButtons, idx);
                    var s = Settings.Load();
                    if (s.Language == id || (s.Language == "" && L.Lang == id)) return;
                    s.Language = id;
                    s.Save();
                    Msg.Show(this, id == "en"
                            ? L.T("The language will change the next time you start Simpler.")
                            : L.T("La lingua cambierà al prossimo avvio di Simpler."),
                        "Simpler", MessageBoxButton.OK, MessageBoxImage.Information);
                };
            }
            sp.Children.Add(langs);

            sp.Children.Add(Spacer(16));
            sp.Children.Add(Theme.Caption(L.T("Navigazione")));
            var pad = new Toggle(L.T("Touchpad: due dita spostano la vista"), Settings.Load().TouchpadPan,
                L.T("Due dita su e giù (o di lato) spostano la scena senza ruotarla, come il tasto centrale del mouse; pizzicare avvicina o allontana. Spento: le due dita camminano avanti e indietro come la rotellina"));
            pad.Margin = new Thickness(0, 8, 0, 4);
            pad.Toggled += v => { var s = Settings.Load(); s.TouchpadPan = v; s.Save(); };
            sp.Children.Add(pad);

            sp.Children.Add(Spacer(16));
            sp.Children.Add(Theme.Caption(L.T("Cartelle")));
            var folders = Theme.Button(L.T("Cartelle dei file scaricati e delle librerie…"), Theme.Kind.Normal);
            folders.HorizontalAlignment = HorizontalAlignment.Left;
            folders.Margin = new Thickness(0, 8, 0, 0);
            folders.Click += (_, __) => { OpenFolders = true; Close(); };
            sp.Children.Add(folders);

            sp.Children.Add(Spacer(16));
            sp.Children.Add(Theme.Caption(L.T("Versione")));
            var ver = Theme.Label(L.T("Simpler ") + Version, 14, Theme.Text);
            ver.Margin = new Thickness(0, 8, 0, 8);
            sp.Children.Add(ver);
            var notes = Theme.Button(L.T("Novità di questa versione"), Theme.Kind.Normal);
            notes.HorizontalAlignment = HorizontalAlignment.Left;
            notes.Click += (_, __) => { OpenNotes = true; Close(); };
            sp.Children.Add(notes);

            sp.Children.Add(Spacer(16));
            sp.Children.Add(Theme.Caption(L.T("Motore di render")));
            var blender = Theme.Label(EngineHost.FindBlender() ?? L.T("Blender non trovato"), 12, Theme.TextFaint);
            blender.TextWrapping = TextWrapping.Wrap;
            blender.Margin = new Thickness(0, 8, 0, 0);
            sp.Children.Add(blender);

            var close = Theme.Button(L.T("Chiudi"), Theme.Kind.Primary);
            close.HorizontalAlignment = HorizontalAlignment.Right;
            close.Margin = new Thickness(0, 22, 0, 0);
            close.Click += (_, __) => Close();
            sp.Children.Add(close);
            Body.Children.Add(sp);
        }

        static Border Spacer(double h) => new Border { Height = h };

        public static string? NotesFolderPath() => NotesFolder();

        static string? NotesFolder()
        {
            for (var dir = new DirectoryInfo(AppContext.BaseDirectory); dir != null; dir = dir.Parent)
            {
                var p = Path.Combine(dir.FullName, "release-notes");
                if (Directory.Exists(p)) return p;
            }
            return null;
        }

        /// <summary>release-notes/Simpler-&lt;version&gt;.txt (Italian) or release-notes/en/Simpler-&lt;version&gt;.txt
        /// (English, when the app speaks English and the translation is there), or the most recent one.</summary>
        public static string? NotesFile(string version)
        {
            var folder = NotesFolder();
            if (folder == null) return null;
            string? Pick(string dir)
            {
                var file = Path.Combine(dir, $"Simpler-{version}.txt");
                if (File.Exists(file)) return file;
                return Directory.Exists(dir) ? Directory.GetFiles(dir, "Simpler-*.txt").OrderByDescending(f => VersionKey(f)).FirstOrDefault() : null;
            }
            if (L.Lang == "en")
            {
                var en = Path.Combine(folder, "en", $"Simpler-{version}.txt");
                if (File.Exists(en)) return en;
                if (!File.Exists(Path.Combine(folder, $"Simpler-{version}.txt")) && Pick(Path.Combine(folder, "en")) is string latest) return latest;
            }
            return Pick(folder);
        }

        /// <summary>All versions with notes, newest first.</summary>
        public static List<string> NotesVersions()
        {
            var folder = NotesFolder();
            if (folder == null) return new List<string>();
            return Directory.GetFiles(folder, "Simpler-*.txt").OrderByDescending(f => VersionKey(f))
                .Select(f => Path.GetFileNameWithoutExtension(f).Replace("Simpler-", "")).ToList();
        }

        static System.Version VersionKey(string file)
            => System.Version.TryParse(Path.GetFileNameWithoutExtension(file).Replace("Simpler-", ""), out var v) ? v : new System.Version(0, 0);

        /// <summary>The user asked for the release notes: the main window shows them in its sidebar.</summary>
        public bool OpenNotes { get; private set; }
        public bool OpenFolders { get; private set; }
    }
}
