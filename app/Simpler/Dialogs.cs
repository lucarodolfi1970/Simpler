using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Effects;
using System.Windows.Shapes;

namespace Simpler
{
    /// <summary>Dialog window in the style of the app: dark rounded panel, own title bar with a small ×, no Windows chrome.</summary>
    public class ThemedDialog : Window
    {
        protected readonly StackPanel Body = new StackPanel { Margin = new Thickness(22, 4, 22, 20) };
        /// <summary>Always at the bottom of the window, outside the part that scrolls (see EnableBodyScroll): the
        /// buttons of a dialog that can grow taller than the screen.</summary>
        protected readonly StackPanel Footer = new StackPanel { Margin = new Thickness(22, 0, 22, 18), Visibility = Visibility.Collapsed };
        readonly DockPanel _root = new DockPanel();

        /// <summary>The body scrolls when the window reaches the height of the screen; the Footer stays in sight.</summary>
        protected void EnableBodyScroll()
        {
            Footer.Visibility = Footer.Children.Count > 0 ? Visibility.Visible : Visibility.Collapsed;
            if (Body.Parent is not DockPanel) return;
            _root.Children.Remove(Body);
            Body.Margin = new Thickness(22, 4, 22, 8);
            _root.Children.Add(new ScrollViewer { Content = Body, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled });
        }

        /// <summary>(1.75.30) Something that stays above the body, outside the part that scrolls (the language buttons of
        /// the license agreement).</summary>
        protected void AddAboveBody(UIElement e)
        {
            DockPanel.SetDock(e, Dock.Top);
            _root.Children.Insert(1, e);          // (after the title bar, before the footer and the body)
        }

        /// <summary>Big dialogs that change size: always in the middle of the screen.</summary>
        protected bool _keepCentred;

        public ThemedDialog(string title, double width)
        {
            // closing an owned window (above all a modeless, always-on-top one) Windows may give the focus to another
            // program: the main window takes it back at once
            Closing += (_, __) => { try { if (Owner is { IsVisible: true } o) o.Activate(); } catch { } };
            Title = title;
            WindowStyle = WindowStyle.None;
            AllowsTransparency = true;
            Background = Brushes.Transparent;
            ResizeMode = ResizeMode.NoResize;
            ShowInTaskbar = false;
            Width = width;
            SizeToContent = SizeToContent.Height;
            WindowStartupLocation = WindowStartupLocation.CenterOwner;
            MaxHeight = SystemParameters.WorkArea.Height;
            // a window that grows (results arriving) or opens taller than the room left below: back inside the screen,
            // in the middle of it - never with its bottom (and its buttons) out of sight
            SizeChanged += (_, __) =>
            {
                var wa = SystemParameters.WorkArea;
                if (Top < wa.Top || Top + ActualHeight > wa.Bottom || Left < wa.Left || Left + ActualWidth > wa.Right || _keepCentred)
                {
                    Left = wa.Left + Math.Max(0, (wa.Width - ActualWidth) / 2);
                    Top = wa.Top + Math.Max(0, (wa.Height - ActualHeight) / 2);
                }
            };
            Foreground = Theme.B(Theme.Text);
            FontFamily = Theme.Sans;
            FontSize = 13;
            UseLayoutRounding = true;
            TextOptions.SetTextFormattingMode(this, TextFormattingMode.Display);

            var root = _root;
            // title bar: logo, title, small × (drag the window from here)
            var bar = new DockPanel { Height = 40, Background = Brushes.Transparent };
            bar.MouseLeftButtonDown += (_, e) => { if (e.ButtonState == MouseButtonState.Pressed) DragMove(); };
            var close = new Button
            {
                Content = Theme.Icon(Geometry.Parse("M6 6l12 12 M18 6 6 18"), Theme.TextMuted, 13, 1.8),
                Width = 28, Height = 28, Margin = new Thickness(0, 0, 8, 0), Cursor = Cursors.Hand,
                ToolTip = L.T("Chiudi"), FocusVisualStyle = null, IsTabStop = false,
            };
            close.Template = RoundTemplate();
            close.Click += (_, __) => OnCloseButton();
            DockPanel.SetDock(close, Dock.Right);
            bar.Children.Add(close);
            var logo = new Grid { Width = 16, Height = 16, Margin = new Thickness(16, 0, 10, 0) };
            logo.Children.Add(new Ellipse { Stroke = Theme.B(Theme.Accent), StrokeThickness = 2 });
            logo.Children.Add(new Ellipse { Fill = Theme.B(Theme.Warm), Width = 6, Height = 6 });
            bar.Children.Add(logo);
            // (1.75.31) the text follows Title, a dialog can change it (the license agreement switching language)
            var titleText = new TextBlock { FontSize = 12.5, Foreground = Theme.B(Theme.TextMuted), VerticalAlignment = VerticalAlignment.Center };
            titleText.SetBinding(TextBlock.TextProperty, new System.Windows.Data.Binding(nameof(Title)) { Source = this });
            bar.Children.Add(titleText);
            DockPanel.SetDock(bar, Dock.Top);
            root.Children.Add(bar);
            DockPanel.SetDock(Footer, Dock.Bottom);
            root.Children.Add(Footer);
            root.Children.Add(Body);

            Content = new Border
            {
                Child = root, Margin = new Thickness(14), CornerRadius = new CornerRadius(12),
                Background = Theme.B(Theme.Panel), BorderBrush = Theme.B(Theme.LineStrong), BorderThickness = new Thickness(1),
                Effect = new DropShadowEffect { BlurRadius = 24, ShadowDepth = 6, Opacity = 0.55, Color = Colors.Black },
            };
            Width = width + 28;
        }

        protected virtual void OnCloseButton() => Close();

        internal static ControlTemplate RoundTemplate()
        {
            var t = new ControlTemplate(typeof(Button));
            var bd = new FrameworkElementFactory(typeof(Border), "Bd");
            bd.SetValue(Border.CornerRadiusProperty, new CornerRadius(14));
            bd.SetValue(Border.BackgroundProperty, Brushes.Transparent);
            var cp = new FrameworkElementFactory(typeof(ContentPresenter));
            cp.SetValue(HorizontalAlignmentProperty, HorizontalAlignment.Center);
            cp.SetValue(VerticalAlignmentProperty, VerticalAlignment.Center);
            bd.AppendChild(cp);
            t.VisualTree = bd;
            var hover = new Trigger { Property = UIElement.IsMouseOverProperty, Value = true };
            hover.Setters.Add(new Setter(Border.BackgroundProperty, Theme.B(Theme.Raised), "Bd"));
            t.Triggers.Add(hover);
            return t;
        }
    }

    /// <summary>Message box in the style of the app; same use as System.Windows.MessageBox.</summary>
    public sealed class Msg : ThemedDialog
    {
        MessageBoxResult _result;
        readonly MessageBoxResult _cancelResult;

        Msg(string text, string title, MessageBoxButton buttons, MessageBoxImage image) : base(title, 460)
        {
            var row = new DockPanel { Margin = new Thickness(0, 6, 0, 22) };
            var (glyph, color) = image switch
            {
                MessageBoxImage.Question => ("?", Theme.Accent),
                MessageBoxImage.Warning => ("!", Theme.Warm),
                MessageBoxImage.Error => ("×", Theme.Danger),
                _ => ("i", Theme.Accent),
            };
            if (image != MessageBoxImage.None)
            {
                var badge = new Grid { Width = 34, Height = 34, Margin = new Thickness(0, 0, 16, 0), VerticalAlignment = VerticalAlignment.Top };
                badge.Children.Add(new Ellipse { Fill = new SolidColorBrush(Color.FromArgb(40, color.R, color.G, color.B)), Stroke = Theme.B(color), StrokeThickness = 1.5 });
                badge.Children.Add(new TextBlock
                {
                    Text = glyph, FontSize = 17, FontWeight = FontWeights.SemiBold, Foreground = Theme.B(color),
                    HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0, -2, 0, 0),
                });
                DockPanel.SetDock(badge, Dock.Left);
                row.Children.Add(badge);
            }
            var msg = new TextBox
            {
                Text = text, IsReadOnly = true, TextWrapping = TextWrapping.Wrap, BorderThickness = new Thickness(0),
                Background = Brushes.Transparent, Foreground = Theme.B(Theme.Text), FontSize = 13.5, Padding = new Thickness(0),
                VerticalAlignment = VerticalAlignment.Center, MaxHeight = 420, VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                Cursor = Cursors.Arrow, IsTabStop = false,
            };
            row.Children.Add(msg);
            Body.Children.Add(row);

            var list = buttons switch
            {
                MessageBoxButton.YesNo => new[] { (MessageBoxResult.No, "No"), (MessageBoxResult.Yes, L.T("Sì")) },
                MessageBoxButton.YesNoCancel => new[] { (MessageBoxResult.Cancel, L.T("Annulla")), (MessageBoxResult.No, "No"), (MessageBoxResult.Yes, L.T("Sì")) },
                MessageBoxButton.OKCancel => new[] { (MessageBoxResult.Cancel, L.T("Annulla")), (MessageBoxResult.OK, "OK") },
                _ => new[] { (MessageBoxResult.OK, "OK") },
            };
            _cancelResult = buttons switch
            {
                MessageBoxButton.YesNo => MessageBoxResult.No,
                MessageBoxButton.OK => MessageBoxResult.OK,
                _ => MessageBoxResult.Cancel,
            };
            _result = _cancelResult;
            var bar = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right };
            Button? primary = null;
            for (int i = 0; i < list.Length; i++)
            {
                var (res, label) = list[i];
                var isPrimary = i == list.Length - 1;
                var b = Theme.Button(label, isPrimary ? Theme.Kind.Primary : Theme.Kind.Ghost);
                b.MinWidth = 88;
                b.Margin = new Thickness(8, 0, 0, 0);
                var r = res;
                b.Click += (_, __) => { _result = r; Close(); };
                bar.Children.Add(b);
                if (isPrimary) primary = b;
            }
            Body.Children.Add(bar);
            PreviewKeyDown += (_, e) =>
            {
                if (e.Key == Key.Escape) { _result = _cancelResult; Close(); e.Handled = true; }
                else if (e.Key == Key.Enter) { _result = list[^1].Item1; Close(); e.Handled = true; }
            };
            Loaded += (_, __) => primary?.Focus();
        }

        public static MessageBoxResult Show(Window? owner, string text, string title = "Simpler",
            MessageBoxButton buttons = MessageBoxButton.OK, MessageBoxImage image = MessageBoxImage.None)
        {
            var d = new Msg(text, title, buttons, image);
            if (owner != null && owner.IsVisible && owner.Left > -20000) d.Owner = owner;
            else d.WindowStartupLocation = WindowStartupLocation.CenterScreen;
            d.Topmost = d.Owner == null;
            d.ShowDialog();
            return d._result;
        }

        public static MessageBoxResult Show(string text, string title = "Simpler",
            MessageBoxButton buttons = MessageBoxButton.OK, MessageBoxImage image = MessageBoxImage.None)
            => Show(Application.Current?.MainWindow, text, title, buttons, image);
    }

    /// <summary>Before importing models into the scene (Importa, Ctrl+I, files dropped on the scene): the files and the
    /// choice «Unisci i pezzi in un solo oggetto», visible and remembered (in the menu Importa it was a tick that did
    /// not show).</summary>
    public sealed class ImportSceneDialog : ThemedDialog
    {
        bool _ok;
        public bool Merge { get; private set; }
        public bool AtView { get; private set; }

        ImportSceneDialog(IReadOnlyList<string> files, bool merge, bool atView) : base(L.T("Importa nella scena"), 440)
        {
            Merge = merge;
            AtView = atView;
            var names = files.Count == 1 ? System.IO.Path.GetFileName(files[0])
                : L.F("{0} modelli: {1}", files.Count, string.Join(", ", System.Linq.Enumerable.Take(System.Linq.Enumerable.Select(files, f => System.IO.Path.GetFileName(f)), 4)) + (files.Count > 4 ? "…" : ""));
            var head = Theme.Label(names, 13.5, Theme.Text, FontWeights.SemiBold);
            head.TextWrapping = TextWrapping.Wrap;
            head.Margin = new Thickness(0, 4, 0, 14);
            Body.Children.Add(head);
            var t = new Toggle(L.T("Unisci i pezzi in un solo oggetto"), merge);
            t.Toggled += on => Merge = on;
            Body.Children.Add(t);
            var hint = Theme.Label(L.T("Tutti i pezzi del modello diventano un solo oggetto, con ogni materiale al suo posto: albero pulito, un clic per selezionarlo. I pezzi ripetuti molte volte (bulloni, sedie) restano copie. Si può unire anche dopo: tasto destro nell'albero, «Unisci in un solo oggetto»."), 11.5, Theme.TextMuted);
            hint.TextWrapping = TextWrapping.Wrap;
            hint.Margin = new Thickness(0, 0, 0, 14);
            Body.Children.Add(hint);
            // (1.75.48) where it goes: the centre of the view (on), or the coordinates written in the file
            var v = new Toggle(L.T("Al centro della vista"), atView);
            v.Toggled += on => AtView = on;
            Body.Children.Add(v);
            var vh = Theme.Label(L.T("Il modello appoggia la base nel punto al centro dello schermo, dove guarda la camera. Più file importati insieme restano allineati tra loro. Spento: il modello resta nelle coordinate del file (per parti dello stesso progetto da far combaciare)."), 11.5, Theme.TextMuted);
            vh.TextWrapping = TextWrapping.Wrap;
            vh.Margin = new Thickness(0, 0, 0, 20);
            Body.Children.Add(vh);
            var bar = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right };
            var cancel = Theme.Button(L.T("Annulla"), Theme.Kind.Ghost);
            cancel.MinWidth = 88;
            cancel.Click += (_, __) => Close();
            var go = Theme.Button(L.T("Importa"), Theme.Kind.Primary);
            go.MinWidth = 88;
            go.Margin = new Thickness(8, 0, 0, 0);
            go.Click += (_, __) => { _ok = true; Close(); };
            bar.Children.Add(cancel);
            bar.Children.Add(go);
            Body.Children.Add(bar);
            PreviewKeyDown += (_, e) =>
            {
                if (e.Key == Key.Escape) { Close(); e.Handled = true; }
                else if (e.Key == Key.Enter) { _ok = true; Close(); e.Handled = true; }
            };
            Loaded += (_, __) => go.Focus();
        }

        /// <summary>null: cancelled; otherwise the choices (merging, at the centre of the view).</summary>
        public static (bool merge, bool atView)? Ask(Window owner, IReadOnlyList<string> files, bool merge, bool atView)
        {
            var d = new ImportSceneDialog(files, merge, atView) { Owner = owner };
            d.ShowDialog();
            return d._ok ? (d.Merge, d.AtView) : null;
        }
    }

    /// <summary>«Aggiorna dalla libreria»: the library models used by what was clicked (or changed in the library since
    /// the project used them), each with what uses it in the project; the chosen ones are made again from the library.</summary>
    public sealed class LibUpdateDialog : ThemedDialog
    {
        bool _ok;
        readonly List<string> _chosen = new List<string>();

        LibUpdateDialog(string title, string intro, IReadOnlyList<System.Text.Json.Nodes.JsonObject> models, string goText) : base(title, 520)
        {
            var head = Theme.Label(intro, 12.5, Theme.Text);
            head.TextWrapping = TextWrapping.Wrap;
            head.Margin = new Thickness(0, 4, 0, 12);
            Body.Children.Add(head);
            var list = new StackPanel();
            foreach (var m in models)
            {
                var id = (string?)m["id"] ?? "";
                var inLib = (bool?)m["inLibrary"] ?? false;
                var parts = new List<string>();
                int nd = (int?)m["distributions"] ?? 0, ne = (int?)m["ecosystems"] ?? 0, np = (int?)m["placed"] ?? 0;
                if (nd > 0) parts.Add(nd == 1 ? L.T("1 distribuzione") : L.F("{0} distribuzioni", nd));
                if (ne > 0) parts.Add(ne == 1 ? L.T("1 ecosistema") : L.F("{0} ecosistemi", ne));
                if (np > 0) parts.Add(np == 1 ? L.T("1 modello piazzato") : L.F("{0} modelli piazzati", np));
                if (!inLib) parts.Add(L.T("non è più nella libreria"));
                else if ((bool?)m["outdated"] == true) parts.Add(L.T("cambiato nella libreria"));
                var on = inLib;
                if (on) _chosen.Add(id);
                var t = new Toggle(((string?)m["name"] ?? id) + "  ·  " + string.Join(", ", parts), on);
                t.Margin = new Thickness(0, 2, 0, 6);
                if (!inLib) { t.IsEnabled = false; t.Opacity = 0.5; }
                t.Toggled += v => { _chosen.Remove(id); if (v) _chosen.Add(id); };
                list.Children.Add(t);
            }
            Body.Children.Add(new ScrollViewer { Content = list, MaxHeight = 320, VerticalScrollBarVisibility = ScrollBarVisibility.Auto });
            if (System.Linq.Enumerable.Any(models, m => !((bool?)m["inLibrary"] ?? false)))
            {
                var miss = Theme.Label(L.T("Un modello che non è più nella libreria non si può aggiornare: se lo hai eliminato e salvato di nuovo, per Simpler è un modello nuovo. Per correggere un modello senza perdere il legame, salvalo con lo stesso nome e scegli di sovrascriverlo."), 11.5, Theme.TextMuted);
                miss.TextWrapping = TextWrapping.Wrap;
                miss.Margin = new Thickness(0, 8, 0, 0);
                Body.Children.Add(miss);
            }
            var hint = Theme.Label(L.T("Ogni modello scelto viene ricaricato dalla libreria in tutto il progetto: i pezzi delle distribuzioni e degli ecosistemi e i modelli piazzati restano dove sono. Le modifiche fatte in questo progetto a quei modelli (un materiale cambiato qui, un pezzo spostato) si perdono: vale la libreria. Si può annullare."), 11.5, Theme.TextMuted);
            hint.TextWrapping = TextWrapping.Wrap;
            hint.Margin = new Thickness(0, 10, 0, 20);
            Body.Children.Add(hint);
            var bar = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right };
            var cancel = Theme.Button(L.T("Non ora"), Theme.Kind.Ghost);
            cancel.MinWidth = 88;
            cancel.Click += (_, __) => Close();
            var go = Theme.Button(goText, Theme.Kind.Primary);
            go.MinWidth = 88;
            go.Margin = new Thickness(8, 0, 0, 0);
            go.Click += (_, __) => { _ok = true; Close(); };
            bar.Children.Add(cancel);
            bar.Children.Add(go);
            Body.Children.Add(bar);
            PreviewKeyDown += (_, e) => { if (e.Key == Key.Escape) { Close(); e.Handled = true; } };
            Loaded += (_, __) => go.Focus();
        }

        /// <summary>null: cancelled; otherwise the ids of the chosen models.</summary>
        public static List<string>? Ask(Window owner, string title, string intro, IReadOnlyList<System.Text.Json.Nodes.JsonObject> models, string goText)
        {
            var d = new LibUpdateDialog(title, intro, models, goText) { Owner = owner };
            d.ShowDialog();
            return d._ok && d._chosen.Count > 0 ? d._chosen : null;
        }
    }
}

namespace Simpler
{
    /// <summary>(1.76.23) A Poly Haven model with several levels of detail (rock_LOD0 … rock_LOD3, all in its file):
    /// which one goes in the scene - the others stay out (Luca: «si importano mesh in più per niente»).</summary>
    /// <summary>(1.76.34, Luca: «se sono enormi meglio selezionare una parte di pochi km») The part of a big
    /// elevation file to use: its shaded relief, a square to drag on it, its side in km (up to a limit: the terrain
    /// has 512 points a side). Returns [x0, y0, side] as fractions of the file (from the north-west), or null.</summary>
    public sealed class DemCropDialog : ThemedDialog
    {
        bool _ok;
        double _x0, _y0, _side;          // fractions

        DemCropDialog(string name, byte[] png, double fileM, double maxM, double defM) : base(L.T("Quale parte del file"), 560)
        {
            var head = Theme.Label(name, 13.5, Theme.Text, FontWeights.SemiBold);
            head.TextWrapping = TextWrapping.Wrap;
            head.Margin = new Thickness(0, 4, 0, 6);
            Body.Children.Add(head);
            var hint = Theme.Label(L.F("Il file copre {0} km di lato. Trascina il quadrato sulla parte che ti serve e scegli quanto è grande (al massimo {1} km: oltre, il terreno perde dettaglio).",
                (fileM / 1000).ToString("0.#"), (maxM / 1000).ToString("0.#")), 11.5, Theme.TextMuted);
            hint.TextWrapping = TextWrapping.Wrap;
            hint.Margin = new Thickness(0, 0, 0, 10);
            Body.Children.Add(hint);

            const double W = 512;
            var bmp = new System.Windows.Media.Imaging.BitmapImage();
            bmp.BeginInit(); bmp.CacheOption = System.Windows.Media.Imaging.BitmapCacheOption.OnLoad;
            bmp.StreamSource = new System.IO.MemoryStream(png); bmp.EndInit(); bmp.Freeze();
            var canvas = new Canvas { Width = W, Height = W, ClipToBounds = true, Cursor = Cursors.SizeAll, HorizontalAlignment = HorizontalAlignment.Center };
            canvas.Children.Add(new Image { Source = bmp, Width = W, Height = W, Stretch = Stretch.Fill });
            var shade = new Path { Fill = new SolidColorBrush(Color.FromArgb(120, 0, 0, 0)), IsHitTestVisible = false };
            canvas.Children.Add(shade);
            var sq = new Rectangle { Stroke = Theme.B(Theme.Warm), StrokeThickness = 2, Fill = Brushes.Transparent };
            canvas.Children.Add(sq);
            Body.Children.Add(canvas);

            double minM = Math.Min(fileM, Math.Max(500, fileM / 200));
            _side = Math.Min(1.0, defM / fileM);
            _x0 = 0.5 - _side / 2; _y0 = 0.5 - _side / 2;
            var label = Theme.Label("", 12, Theme.TextSoft);
            label.Margin = new Thickness(0, 8, 0, 0);
            void Place()
            {
                _x0 = Math.Max(0, Math.Min(1 - _side, _x0));
                _y0 = Math.Max(0, Math.Min(1 - _side, _y0));
                Canvas.SetLeft(sq, _x0 * W); Canvas.SetTop(sq, _y0 * W);
                sq.Width = sq.Height = Math.Max(4, _side * W);
                shade.Data = new CombinedGeometry(GeometryCombineMode.Exclude, new RectangleGeometry(new Rect(0, 0, W, W)),
                                                  new RectangleGeometry(new Rect(_x0 * W, _y0 * W, _side * W, _side * W)));
                label.Text = L.F("Lato del terreno: {0} km", (_side * fileM / 1000).ToString("0.0#"));
            }
            bool drag = false;
            Point grab = default;
            canvas.MouseLeftButtonDown += (_, e) =>
            {
                var p = e.GetPosition(canvas);
                // (a click outside the square: the square comes there, centred)
                if (p.X < _x0 * W || p.X > (_x0 + _side) * W || p.Y < _y0 * W || p.Y > (_y0 + _side) * W)
                { _x0 = p.X / W - _side / 2; _y0 = p.Y / W - _side / 2; Place(); }
                drag = true; grab = p; canvas.CaptureMouse();
            };
            canvas.MouseMove += (_, e) =>
            {
                if (!drag) return;
                var p = e.GetPosition(canvas);
                _x0 += (p.X - grab.X) / W; _y0 += (p.Y - grab.Y) / W; grab = p;
                Place();
            };
            canvas.MouseLeftButtonUp += (_, __) => { drag = false; canvas.ReleaseMouseCapture(); };
            var slider = new ValueSlider(L.T("Lato"), _side * fileM / 1000, minM / 1000, Math.Max(minM, maxM) / 1000, false, "0.0#", "km", null,
                L.T("Quanti chilometri di lato prendere dal file"));
            slider.Margin = new Thickness(0, 10, 0, 0);
            slider.Committed += v =>
            {
                double cx = _x0 + _side / 2, cy = _y0 + _side / 2;
                _side = Math.Max(minM, Math.Min(maxM, v * 1000)) / fileM;
                _x0 = cx - _side / 2; _y0 = cy - _side / 2;
                Place();
            };
            Body.Children.Add(slider);
            Body.Children.Add(label);
            Place();

            var bar = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 14, 0, 0) };
            var cancel = Theme.Button(L.T("Annulla"), Theme.Kind.Ghost);
            cancel.MinWidth = 88;
            cancel.Click += (_, __) => Close();
            var go = Theme.Button(L.T("Usa questa parte"), Theme.Kind.Primary);
            go.MinWidth = 88;
            go.Margin = new Thickness(8, 0, 0, 0);
            go.Click += (_, __) => { _ok = true; Close(); };
            bar.Children.Add(cancel);
            bar.Children.Add(go);
            Body.Children.Add(bar);
            PreviewKeyDown += (_, e) =>
            {
                if (e.Key == Key.Escape) { Close(); e.Handled = true; }
                else if (e.Key == Key.Enter && e.OriginalSource is not TextBox) { _ok = true; Close(); e.Handled = true; }
            };
        }

        public static double[]? Ask(Window owner, string name, byte[] png, double fileM, double maxM, double defM)
        {
            var d = new DemCropDialog(name, png, fileM, maxM, defM) { Owner = owner };
            d.ShowDialog();
            return d._ok ? new[] { Math.Round(d._x0, 5), Math.Round(d._y0, 5), Math.Round(d._side, 5) } : null;
        }
    }

    public sealed class LodDialog : ThemedDialog
    {
        bool _ok;
        int _level;

        LodDialog(string name, IReadOnlyList<(int level, int tris)> lods, int chosen, bool many) : base(L.T("Livello di dettaglio"), 440)
        {
            _level = chosen;
            var head = Theme.Label(name, 13.5, Theme.Text, FontWeights.SemiBold);
            head.TextWrapping = TextWrapping.Wrap;
            head.Margin = new Thickness(0, 4, 0, 8);
            Body.Children.Add(head);
            var hint = Theme.Label(L.F("Il modello ha {0} livelli di dettaglio, la stessa forma con più o meno triangoli. Ne entra uno solo.", lods.Count) + " " +
                (many ? L.T("Per tante copie (pennello, pietre e detriti) basta un livello leggero: la scena resta veloce.")
                      : L.T("Vicino alla camera serve il più dettagliato; lontano basta un livello più leggero.")), 11.5, Theme.TextMuted);
            hint.TextWrapping = TextWrapping.Wrap;
            hint.Margin = new Thickness(0, 0, 0, 12);
            Body.Children.Add(hint);
            var buttons = new List<Button>();
            foreach (var (level, tris) in lods)
            {
                var lv = level;
                var what = lv == lods[0].level ? L.T("il più dettagliato") : lv == lods[lods.Count - 1].level ? L.T("il più leggero") : "";
                var b = Theme.Button($"LOD{lv}  ·  " + L.F("{0} triangoli", tris.ToString("N0")) + (what != "" ? "  ·  " + what : ""), Theme.Kind.Ghost);
                b.HorizontalContentAlignment = HorizontalAlignment.Left;
                b.Margin = new Thickness(0, 0, 0, 4);
                b.Click += (_, __) => { _level = lv; Mark(); };
                b.MouseDoubleClick += (_, __) => { _level = lv; _ok = true; Close(); };
                buttons.Add(b);
                Body.Children.Add(b);
            }
            void Mark()
            {
                for (int i = 0; i < buttons.Count; i++)
                    buttons[i].BorderBrush = lods[i].level == _level ? Theme.B(Theme.Accent) : Brushes.Transparent;
                for (int i = 0; i < buttons.Count; i++)
                    buttons[i].BorderThickness = new Thickness(lods[i].level == _level ? 2 : 0);
            }
            Mark();
            var bar = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 14, 0, 0) };
            var cancel = Theme.Button(L.T("Annulla"), Theme.Kind.Ghost);
            cancel.MinWidth = 88;
            cancel.Click += (_, __) => Close();
            var go = Theme.Button(L.T("Usa questo"), Theme.Kind.Primary);
            go.MinWidth = 88;
            go.Margin = new Thickness(8, 0, 0, 0);
            go.Click += (_, __) => { _ok = true; Close(); };
            bar.Children.Add(cancel);
            bar.Children.Add(go);
            Body.Children.Add(bar);
            PreviewKeyDown += (_, e) =>
            {
                if (e.Key == Key.Escape) { Close(); e.Handled = true; }
                else if (e.Key == Key.Enter) { _ok = true; Close(); e.Handled = true; }
            };
            Loaded += (_, __) => go.Focus();
        }

        /// <summary>The level chosen, or null (cancelled). many: for a brush or the stones - a light level first.</summary>
        public static int? Ask(Window owner, string name, IReadOnlyList<(int level, int tris)> lods, bool many)
        {
            int chosen = lods[0].level;
            if (many)
            {
                // the first level under 5 000 triangles (stones by the thousand), else the lightest
                var light = lods.FirstOrDefault(l => l.tris <= 5000);
                chosen = light.tris > 0 ? light.level : lods[lods.Count - 1].level;
            }
            var d = new LodDialog(name, lods, chosen, many) { Owner = owner };
            d.ShowDialog();
            return d._ok ? d._level : null;
        }
    }
}
