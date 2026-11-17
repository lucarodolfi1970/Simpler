using System;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;

namespace Simpler
{
    /// <summary>Sidebar sections that open and close like an accordion (click the title); the state is remembered.</summary>
    public sealed partial class MainWindow
    {
        static readonly Geometry ChevronDown = Geometry.Parse("m6 9 6 6 6-6");

        // open/closed sections and "Avanzate" boxes: only for this session and this scene. Simpler starts, and every
        // new or opened scene starts, with every section closed (1.76.46; before, open) and every "Avanzate" closed (before 1.17.7 they were
        // remembered in the settings, across sessions)
        readonly System.Collections.Generic.HashSet<string> _collapsedSections = new(), _openAdvanced = new();
        // (1.76.46, Luca: «voglio che tutte le schede siano di default chiuse ... per avere maggiore ordine») a section
        // seen for the first time in this scene starts closed; then it stays as it was left
        readonly System.Collections.Generic.HashSet<string> _seenSections = new();

        void ResetPanelState()
        {
            _collapsedSections.Clear();
            _seenSections.Clear();
            _openAdvanced.Clear();
            _foldSaved.Clear();
            _photoResult = null;
            _photoPath = null;
        }

        // «Chiudi tutte le sezioni» (1.73.9): per panel, the sections that were closed before everything was closed -
        // the same button opens them again as they were
        readonly System.Collections.Generic.Dictionary<string, System.Collections.Generic.HashSet<string>> _foldSaved = new();

        static System.Collections.Generic.Dictionary<string, (Geometry, Color)>? _sectionIcons;

        /// <summary>The icon of a section from its title (Italian or translated); a generic one for the others.</summary>
        static (Geometry, Color) SectionIcon(string title)
        {
            if (_sectionIcons == null)
            {
                Color metal = Theme.C("#B8C4D6"), dirt = Theme.C("#C89B6B"), glass = Theme.C("#8FD3F0"), velvet = Theme.C("#E58FB8"),
                      skin = Theme.C("#F0A07A"), fire = Theme.C("#FF8A4C"), green = Theme.AxisY;
                var t = new (string, Geometry, Color)[]
                {
                    ("Materiale", Icons.MatStandard, Theme.Accent), ("Colore", Icons.Palette, Theme.Warm),
                    ("Rugosità", Icons.Rough, Theme.TextSoft), ("Sporco", Icons.Broom, dirt),
                    ("Metallico", Icons.Gem, metal), ("Metallo", Icons.Gem, metal),
                    ("Rilievo", Icons.Relief, Theme.Teal), ("Rilievo vero", Icons.Relief, Theme.Teal), ("Rilievo (normale)", Icons.Relief, Theme.Teal),
                    ("Riflessi e vernice", Icons.Sparkles, Theme.Accent), ("Vetro e trasparenza", Icons.Glass, glass),
                    ("Trasparenza", Icons.Glass, glass), ("Opacità (ritaglio)", Icons.Glass, glass), ("Velluto", Icons.Feather, velvet),
                    ("Sottosuperficie", Icons.WaterDrop, skin), ("Emissione", Icons.Bulb, Theme.Warm), ("Emissione (luce)", Icons.Bulb, Theme.Warm),
                    ("Luce propria (fuoco)", Icons.Flame, fire), ("Tipo di volume", Icons.Cloud, Theme.TextSoft),
                    ("Mappatura texture", Icons.Grid, Theme.Accent), ("Texture per formato", Icons.Grid, Theme.Accent),
                    ("Texture della scena", Icons.Image, Theme.Accent), ("Immagine (colore)", Icons.Image, Theme.Warm),
                    ("Immagine da elaborare", Icons.Image, Theme.Accent), ("Decal", Icons.Image, Theme.Accent), ("Forma", Icons.Mesh, Theme.Teal),
                    ("Trasformazione", Icons.Move, Theme.AxisX), ("Suddivisione", Icons.Mesh, Theme.Teal), ("Spaziatura", Icons.Expand, Theme.TextSoft),
                    ("Aspetto", Icons.Eye, Theme.Accent), ("Luce", Icons.Light, Theme.Warm), ("Area", Icons.Frame, Theme.Warm),
                    ("Funzione", Icons.Gear, Theme.TextSoft), ("Prospettiva", Icons.Frame, Theme.Accent), ("Obiettivo", Icons.Camera, Theme.Accent),
                    ("Profondità di campo", Icons.Aperture, Theme.Teal), ("Colore ed esposizione", Icons.Aperture, Theme.Warm),
                    ("Colore e profondità", Icons.Palette, Theme.Warm), ("Formato dell'immagine", Icons.Frame, Theme.Accent),
                    ("Esposizione", Icons.Aperture, Theme.TextSoft), ("Vista in tempo reale", Icons.Eye, Theme.Accent),
                    ("Path tracing · qualità", Icons.Wand, Theme.Accent), ("Illuminazione globale e rimbalzi", Icons.Light, Theme.Warm),
                    ("Caustiche, riflessi e rifrazioni", Icons.Sparkles, glass), ("Motore", Icons.Gear, Theme.TextSoft),
                    ("Scheda video", Icons.Chip, green), ("Computer", Icons.Monitor, Theme.Accent), ("Consumo", Icons.Drive, Theme.Teal),
                    ("Altro spazio usato da Simpler", Icons.Drive, Theme.TextSoft), ("I modelli più pesanti", Icons.Layers, Theme.Warm),
                    ("Suggerimenti per risparmiare spazio", Icons.Help, Theme.Teal), ("Per cartella", Icons.Folder, Theme.Warm),
                    ("Chiave OpenAI", Icons.Key, Theme.Warm), ("Pennello", Icons.Brush, dirt), ("Oggetti", Icons.Layers, Theme.Accent),
                    ("Modelli da distribuire", Icons.Grass, green), ("Distribuisci", Icons.Grass, green), ("Crea un ecosistema", Icons.Grass, green),
                    ("Ecosistema", Icons.Grass, green), ("Oceano", Waves, SeaColor), ("Superficie e onde", Waves, SeaColor),
                    ("Costa", Icons.Puddle, SeaColor), ("Pioggia e neve", Icons.Rain, RainColor), ("Pioggia", Icons.Rain, RainColor),
                    ("Neve", Icons.Snow, SnowColor), ("Suolo", Icons.Grass, green), ("Sole", Icons.Light, Theme.Warm),
                    ("Cielo", Icons.Horizon, Theme.Accent), ("Nuvole", Icons.Cloud, Theme.TextSoft), ("Foschia e nebbia", Icons.Fog, Theme.Teal),
                    ("Notte", Icons.Moon, NightColor), ("HDRI", Icons.Image, Theme.Accent),
                };
                _sectionIcons = new();
                foreach (var (k, g, c) in t)
                    _sectionIcons[k] = (g, c);
            }
            if (_sectionIcons.TryGetValue(title, out var v)) return v;
            foreach (var kv in _sectionIcons)           // (English: the language can change while Simpler runs)
                if (L.T(kv.Key) == title) return kv.Value;
            return (Icons.Sliders, Theme.TextMuted);
        }

        void MakeAccordions()
        {
            var panel = _rightPanel == "" ? "props" : _rightPanel;
            var applies = new System.Collections.Generic.Dictionary<string, Action<bool>>();
            foreach (var card in _props.Children.OfType<Border>().ToList())
            {
                if (card.Child is not StackPanel sp || sp.Children.Count < 2 || sp.Children[0] is not TextBlock title || (title.Tag as string) != "section")
                    continue;
                var key = (_rightPanel == "" ? "props" : _rightPanel) + ":" + title.Text;
                var body = sp.Children.Cast<UIElement>().Skip(1).Select(el => (el, el.Visibility)).ToList();
                var chevron = Theme.Icon(ChevronDown, Theme.TextMuted, 14, 1.8);
                chevron.RenderTransformOrigin = new Point(0.5, 0.5);
                var header = new DockPanel { Background = Brushes.Transparent, Cursor = Cursors.Hand, Margin = title.Margin };
                header.ToolTip = L.T("Clic per aprire o chiudere la sezione");
                DockPanel.SetDock(chevron, Dock.Right);
                header.Children.Add(chevron);
                sp.Children.RemoveAt(0);
                title.Margin = new Thickness(0);
                // every section with its icon in a small badge (1.74.0): its own (Ambiente, Oceano), else from the title
                var ic = title.DataContext is ValueTuple<Geometry, Color> own ? own : SectionIcon(title.Text);
                {
                    var badge = new Border
                    {
                        Width = 24, Height = 24, CornerRadius = new CornerRadius(7), Margin = new Thickness(0, 0, 9, 0),
                        Background = new SolidColorBrush(Color.FromArgb(38, ic.Item2.R, ic.Item2.G, ic.Item2.B)),
                        Child = Theme.Icon(ic.Item1, ic.Item2, 14, 1.7),
                    };
                    DockPanel.SetDock(badge, Dock.Left);
                    header.Children.Add(badge);
                    title.VerticalAlignment = VerticalAlignment.Center;
                }
                header.Children.Add(title);
                sp.Children.Insert(0, header);

                void Apply(bool collapsed)
                {
                    foreach (var (el, vis) in body) el.Visibility = collapsed ? Visibility.Collapsed : vis;
                    chevron.RenderTransform = new RotateTransform(collapsed ? -90 : 0);
                    header.Margin = new Thickness(0, 0, 0, collapsed ? 0 : 10);
                }
                if (_seenSections.Add(key)) _collapsedSections.Add(key);
                Apply(_collapsedSections.Contains(key));
                applies[key] = Apply;
                header.MouseLeftButtonUp += (_, e) =>
                {
                    bool collapsed = !_collapsedSections.Contains(key);
                    if (collapsed) _collapsedSections.Add(key); else _collapsedSections.Remove(key);
                    Apply(collapsed);
                    FoldFace();
                    e.Handled = true;
                };
            }
            AddFoldAll(panel, applies);          // (the orange arrow of the toolbar: these sections)
        }

        /// <summary>(1.75.3) The panel's sections for the orange double arrow of the toolbar (before the AI button):
        /// it closes every section of the visible panel; pressed again, opens again those that were open. Before, each
        /// panel had its own arrow next to «Chiudi».</summary>
        void AddFoldAll(string panel, System.Collections.Generic.Dictionary<string, Action<bool>> applies)
        {
            _foldPanel = panel;
            _foldApplies = applies;
            FoldFace();
        }

        string? _foldPanel;
        System.Collections.Generic.Dictionary<string, Action<bool>>? _foldApplies;
        Button? _foldButton;

        bool FoldAllClosed() => _foldApplies != null && _foldApplies.Keys.All(k => _collapsedSections.Contains(k));

        void FoldFace()
        {
            if (_foldButton == null) return;
            // only while the visible panel has sections to close (the panel built last is the one shown)
            bool live = _foldApplies != null && _foldApplies.Count >= 2;
            _foldButton.IsEnabled = live;
            _foldButton.Opacity = live ? 1.0 : 0.35;
            bool closed = live && FoldAllClosed();
            _foldButton.Content = Theme.Icon(closed ? Icons.ChevronsDown : Icons.ChevronsUp, AdvancedColor, 17);
            _foldButton.ToolTip = !live ? L.T("Chiudi tutte le sezioni del pannello (nessuna sezione qui)")
                : closed ? L.T("Riapri le sezioni come prima") : L.T("Chiudi tutte le sezioni del pannello");
        }

        void FoldClick()
        {
            var applies = _foldApplies;
            var panel = _foldPanel;
            if (applies == null || panel == null) return;
            if (FoldAllClosed())
            {
                // as they were before (none remembered: all open)
                var saved = _foldSaved.TryGetValue(panel, out var sv) ? sv : new System.Collections.Generic.HashSet<string>();
                foreach (var k in applies.Keys)
                {
                    bool c = saved.Contains(k);
                    if (c) _collapsedSections.Add(k); else _collapsedSections.Remove(k);
                    applies[k](c);
                }
                _foldSaved.Remove(panel);
            }
            else
            {
                _foldSaved[panel] = new System.Collections.Generic.HashSet<string>(applies.Keys.Where(k => _collapsedSections.Contains(k)));
                foreach (var k in applies.Keys) { _collapsedSections.Add(k); applies[k](true); }
            }
            FoldFace();
        }

        static DockPanel? FindDockWith(object? el, string text)
        {
            if (el is DockPanel dp && dp.Children.OfType<Button>().Any(b => b.Content is string s && s == text)) return dp;
            if (el is Panel p)
                foreach (var c in p.Children)
                {
                    var r = FindDockWith(c, text);
                    if (r != null) return r;
                }
            if (el is Decorator d) return FindDockWith(d.Child, text);
            return null;
        }
    }
}
