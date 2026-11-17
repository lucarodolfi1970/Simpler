using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Data;
using System.Windows.Media;

namespace Simpler
{
    /// <summary>Deep-navy theme from the approved mockup, plus small factories for styled controls.</summary>
    public static class Theme
    {
        public static readonly Color Ground = C("#070D18");
        public static readonly Color Window = C("#0A1222");
        public static readonly Color Panel = C("#0D1729");
        public static readonly Color Inset = C("#081020");
        public static readonly Color Raised = C("#12203A");
        public static readonly Color Line = C("#1C2B47");
        public static readonly Color LineStrong = C("#22355A");
        public static readonly Color Selected = C("#16305A");
        public static readonly Color Segment = C("#1D3766");
        public static readonly Color Text = C("#E4EAF4");
        public static readonly Color TextSoft = C("#C9D3E4");
        public static readonly Color TextMuted = C("#9DAAC2");
        public static readonly Color TextFaint = C("#7C8BA6");
        public static readonly Color Accent = C("#4C9DFF");
        public static readonly Color AccentText = C("#061024");
        public static readonly Color Warm = C("#F2B54B");
        public static readonly Color Teal = C("#5FC7B5");
        public static readonly Color AxisX = C("#F06A6A");
        public static readonly Color AxisY = C("#5FD38D");
        public static readonly Color AxisZ = C("#4C9DFF");
        public static readonly Color Danger = C("#FF7A7A");

        public static readonly FontFamily Sans = new FontFamily("Segoe UI Variable Text, Segoe UI");
        public static readonly FontFamily Mono = new FontFamily("Cascadia Mono, Consolas");

        public static Color C(string hex) => (Color)ColorConverter.ConvertFromString(hex);
        public static SolidColorBrush B(Color c) { var b = new SolidColorBrush(c); b.Freeze(); return b; }
        public static SolidColorBrush B(string hex) => B(C(hex));

        // ------------------------------------------------------------- text

        public static TextBlock Label(string text, double size = 13, Color? color = null, FontWeight? weight = null)
            => new TextBlock
            {
                Text = text,
                FontSize = size,
                Foreground = B(color ?? Text),
                FontWeight = weight ?? FontWeights.Normal,
                VerticalAlignment = VerticalAlignment.Center,
                TextTrimming = TextTrimming.CharacterEllipsis,
            };

        /// <summary>The name under a library tile. Long names without spaces (MT_PM_V60_Lolium_perenne_01) break
        /// after _ - . instead of inside a word, stay on two lines and end with … when longer; the whole name shows
        /// when the pointer is on it.</summary>
        public static TextBlock TileText(TextBlock t)
        {
            var full = t.Text ?? "";
            t.Text = System.Text.RegularExpressions.Regex.Replace(full, @"(?<=[_\-.])(?=\S)", "\u200B");
            t.TextTrimming = TextTrimming.CharacterEllipsis;
            t.MaxHeight = 32;
            if (full.Length > 16 && t.ToolTip == null) t.ToolTip = full;
            return t;
        }

        public static TextBlock Caption(string text)
        {
            var t = Label(text.ToUpperInvariant(), 11, TextMuted, FontWeights.SemiBold);
            t.Margin = new Thickness(0, 0, 0, 0);
            return t;
        }

        // ------------------------------------------------------------- buttons

        public enum Kind { Ghost, Normal, Primary, Segment, Ai }
        // (1.76.60, Luca: «fai questi due tasti arancio così li tipizziamo come AI») the buttons of the AI functions
        public static readonly Color AiColor = C("#F08A24");

        static ControlTemplate ButtonTemplate(Brush hover, Brush pressed)
        {
            var t = new ControlTemplate(typeof(ButtonBase));
            var bd = new FrameworkElementFactory(typeof(Border), "bd");
            bd.SetValue(Border.CornerRadiusProperty, new CornerRadius(8));
            bd.SetValue(Border.SnapsToDevicePixelsProperty, true);
            bd.SetBinding(Border.BackgroundProperty, new Binding("Background") { RelativeSource = RelativeSource.TemplatedParent });
            bd.SetBinding(Border.BorderBrushProperty, new Binding("BorderBrush") { RelativeSource = RelativeSource.TemplatedParent });
            bd.SetBinding(Border.BorderThicknessProperty, new Binding("BorderThickness") { RelativeSource = RelativeSource.TemplatedParent });
            var cp = new FrameworkElementFactory(typeof(ContentPresenter));
            cp.SetValue(ContentPresenter.HorizontalAlignmentProperty, HorizontalAlignment.Center);
            // (the button's own vertical alignment: centred by default - see Style -, at the top for library tiles, so
            // a name on two lines never moves the picture of its tile)
            cp.SetBinding(ContentPresenter.VerticalAlignmentProperty, new Binding("VerticalContentAlignment") { RelativeSource = RelativeSource.TemplatedParent });
            cp.SetBinding(ContentPresenter.MarginProperty, new Binding("Padding") { RelativeSource = RelativeSource.TemplatedParent });
            bd.AppendChild(cp);
            t.VisualTree = bd;
            var over = new Trigger { Property = UIElement.IsMouseOverProperty, Value = true };
            over.Setters.Add(new Setter(Border.BackgroundProperty, hover, "bd"));
            t.Triggers.Add(over);
            var press = new Trigger { Property = ButtonBase.IsPressedProperty, Value = true };
            press.Setters.Add(new Setter(Border.BackgroundProperty, pressed, "bd"));
            t.Triggers.Add(press);
            var off = new Trigger { Property = UIElement.IsEnabledProperty, Value = false };
            off.Setters.Add(new Setter(UIElement.OpacityProperty, 0.45));
            t.Triggers.Add(off);
            return t;
        }

        static readonly ControlTemplate GhostT = ButtonTemplate(B("#16233F"), B("#1B2C4E"));
        static readonly ControlTemplate NormalT = ButtonTemplate(B("#1A2B4C"), B("#20355E"));
        static readonly ControlTemplate PrimaryT = ButtonTemplate(B("#6AAEFF"), B("#3B8BEB"));
        static readonly ControlTemplate SegmentOnT = ButtonTemplate(B("#244276"), B("#244276"));
        static readonly ControlTemplate AiT = ButtonTemplate(B("#FFA650"), B("#D9741A"));

        public static Button Button(object content, Kind kind = Kind.Normal, string? tooltip = null)
        {
            var b = new Button { Content = content, ToolTip = tooltip, Cursor = System.Windows.Input.Cursors.Hand, FocusVisualStyle = null };
            Style(b, kind);
            return b;
        }

        public static void Style(ButtonBase b, Kind kind)
        {
            if (b.ReadLocalValue(Control.VerticalContentAlignmentProperty) == DependencyProperty.UnsetValue)
                b.VerticalContentAlignment = VerticalAlignment.Center;
            b.Padding = new Thickness(12, 0, 12, 0);
            b.MinHeight = 34;
            b.FontSize = 13;
            b.BorderThickness = new Thickness(kind == Kind.Normal ? 1 : 0);
            b.BorderBrush = B(LineStrong);
            switch (kind)
            {
                case Kind.Ghost: b.Template = GhostT; b.Background = Brushes.Transparent; b.Foreground = B(TextMuted); break;
                case Kind.Normal: b.Template = NormalT; b.Background = B(Raised); b.Foreground = B(TextSoft); break;
                case Kind.Primary: b.Template = PrimaryT; b.Background = B(Accent); b.Foreground = B(AccentText); b.FontWeight = FontWeights.SemiBold; break;
                case Kind.Segment: b.Template = SegmentOnT; b.Background = B(Segment); b.Foreground = Brushes.White; break;
                case Kind.Ai: b.Template = AiT; b.Background = B(AiColor); b.Foreground = B(AccentText); b.FontWeight = FontWeights.SemiBold; break;
            }
        }

        public static StackPanel IconText(Geometry icon, string text, Color? iconColor = null, double size = 16)
        {
            var sp = new StackPanel { Orientation = Orientation.Horizontal };
            sp.Children.Add(Icon(icon, iconColor, size));
            if (!string.IsNullOrEmpty(text))
            {
                var tb = new TextBlock { Text = text, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(8, 0, 0, 0) };
                sp.Children.Add(tb);
            }
            return sp;
        }

        public static System.Windows.Shapes.Path Icon(Geometry g, Color? color = null, double size = 16, double stroke = 1.7)
        {
            var p = new System.Windows.Shapes.Path
            {
                Data = g,
                Width = size,
                Height = size,
                Stretch = Stretch.Uniform,
                StrokeThickness = stroke,
                StrokeLineJoin = PenLineJoin.Round,
                StrokeStartLineCap = PenLineCap.Round,
                StrokeEndLineCap = PenLineCap.Round,
                VerticalAlignment = VerticalAlignment.Center,
                SnapsToDevicePixels = true,
            };
            if (color.HasValue) p.Stroke = B(color.Value);
            else p.SetBinding(System.Windows.Shapes.Shape.StrokeProperty, new Binding("Foreground") { RelativeSource = new RelativeSource(RelativeSourceMode.FindAncestor, typeof(Control), 1) });
            return p;
        }

        /// <summary>A row of mutually exclusive buttons (the "segmented control" of the mockup).</summary>
        public static Border Segmented(out System.Collections.Generic.List<Button> buttons, params (object content, string? tooltip)[] items)
        {
            buttons = new System.Collections.Generic.List<Button>();
            var sp = new StackPanel { Orientation = Orientation.Horizontal };
            foreach (var (content, tip) in items)
            {
                var b = Button(content, Kind.Ghost, tip);
                b.MinHeight = 30;
                b.Margin = new Thickness(0, 0, 2, 0);
                buttons.Add(b);
                sp.Children.Add(b);
            }
            return new Border
            {
                Child = sp,
                Background = B(Inset),
                BorderBrush = B(Line),
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(10),
                Padding = new Thickness(3),
            };
        }

        public static void SetSegment(System.Collections.Generic.List<Button> buttons, int selected)
        {
            for (int i = 0; i < buttons.Count; i++)
            {
                Style(buttons[i], i == selected ? Kind.Segment : Kind.Ghost);
                buttons[i].MinHeight = 30;
            }
        }

        // ------------------------------------------------------------- inputs

        /// <summary>A text box of Simpler. (1.75.47) Text boxes (not the number boxes: mono) get a small × at the end that
        /// empties them; <paramref name="clear"/> overrides it.</summary>
        public static TextBox Input(string text = "", bool mono = false, bool? clear = null)
        {
            var tb = InputBox(text, mono);
            if (clear ?? !mono) AddClear(tb);
            return tb;
        }

        static ControlTemplate? _clearTemplate;
        static bool _clearFailed;

        /// <summary>(1.75.47) The small × at the end of a text box: shown when there is text (and it can be edited), a
        /// click empties the box and puts the cursor in it (TextChanged runs as when deleting by hand).</summary>
        public static void AddClear(TextBox tb)
        {
            if (_clearFailed) return;
            if (_clearTemplate == null)
            try
            {
            _clearTemplate = (ControlTemplate)System.Windows.Markup.XamlReader.Parse(
                "<ControlTemplate xmlns='http://schemas.microsoft.com/winfx/2006/xaml/presentation' " +
                "xmlns:x='http://schemas.microsoft.com/winfx/2006/xaml' TargetType='TextBox'>" +
                "<Border x:Name='Bd' Background='{TemplateBinding Background}' BorderBrush='{TemplateBinding BorderBrush}' " +
                "BorderThickness='{TemplateBinding BorderThickness}' SnapsToDevicePixels='True'>" +
                "<Grid><ScrollViewer x:Name='PART_ContentHost' Focusable='False' HorizontalScrollBarVisibility='Hidden' VerticalScrollBarVisibility='{TemplateBinding VerticalScrollBarVisibility}'/>" +
                "<Button x:Name='PART_Clear' Width='18' Height='18' HorizontalAlignment='Right' VerticalAlignment='Top' Margin='0,5,4,0' " +
                "Cursor='Hand' Focusable='False' Visibility='Collapsed' ToolTip='×'>" +
                "<Button.Template><ControlTemplate TargetType='Button'><Border x:Name='B' Background='Transparent' CornerRadius='4'>" +
                "<Path Data='M6 6l12 12 M18 6 6 18' Stroke='#9DAAC2' StrokeThickness='1.8' Stretch='Uniform' Width='8' Height='8' " +
                "HorizontalAlignment='Center' VerticalAlignment='Center'/></Border>" +
                "<ControlTemplate.Triggers><Trigger Property='IsMouseOver' Value='True'><Setter TargetName='B' Property='Background' Value='#22355A'/></Trigger></ControlTemplate.Triggers>" +
                "</ControlTemplate></Button.Template></Button></Grid></Border>" +
                "<ControlTemplate.Triggers><Trigger Property='IsKeyboardFocused' Value='True'><Setter TargetName='Bd' Property='BorderBrush' Value='#4C9DFF'/></Trigger></ControlTemplate.Triggers>" +
                "</ControlTemplate>");
            }
            catch (System.Exception ex) { _clearFailed = true; AppLog.Write("clear button template: " + ex.Message); return; }   // (never a crash for a ×)
            tb.Template = _clearTemplate;
            var p = tb.Padding;
            tb.Padding = new Thickness(p.Left, p.Top, System.Math.Max(p.Right, 22), p.Bottom);
            void Sync()
            {
                if (tb.Template?.FindName("PART_Clear", tb) is Button b)
                    b.Visibility = tb.Text.Length > 0 && !tb.IsReadOnly && tb.IsEnabled ? Visibility.Visible : Visibility.Collapsed;
            }
            tb.Loaded += (_, __) =>
            {
                if (tb.Template?.FindName("PART_Clear", tb) is Button b && b.Tag == null)
                {
                    b.Tag = "wired";
                    b.ToolTip = L.T("Cancella il testo");
                    b.Click += (_, __) => { tb.Clear(); tb.Focus(); };
                }
                Sync();
            };
            tb.TextChanged += (_, __) => Sync();
            tb.IsEnabledChanged += (_, __) => Sync();
        }

        static TextBox InputBox(string text, bool mono)
            => new TextBox
            {
                Text = text,
                Background = B(Inset),
                Foreground = B(Text),
                CaretBrush = B(Text),
                SelectionBrush = B(Accent),
                BorderBrush = B(Line),
                BorderThickness = new Thickness(1),
                Padding = new Thickness(6, 4, 6, 4),
                FontFamily = mono ? Mono : Sans,
                FontSize = 12.5,
                VerticalContentAlignment = VerticalAlignment.Center,
                MinHeight = 30,
            };

        public static Border Card(UIElement child, double pad = 14)
            => new Border { Child = child, Padding = new Thickness(pad), BorderBrush = B(Line), BorderThickness = new Thickness(0, 0, 0, 1) };

        public static Border Swatch(string hex, double size)
        {
            var c = C(hex);
            var light = Color.FromRgb((byte)System.Math.Min(255, c.R + 90), (byte)System.Math.Min(255, c.G + 90), (byte)System.Math.Min(255, c.B + 90));
            var dark = Color.FromRgb((byte)(c.R * 0.35), (byte)(c.G * 0.35), (byte)(c.B * 0.35));
            var g = new RadialGradientBrush { GradientOrigin = new Point(0.35, 0.3), Center = new Point(0.45, 0.45), RadiusX = 0.7, RadiusY = 0.7 };
            g.GradientStops.Add(new GradientStop(light, 0));
            g.GradientStops.Add(new GradientStop(c, 0.45));
            g.GradientStops.Add(new GradientStop(dark, 1));
            g.Freeze();
            return new Border
            {
                Width = size,
                Height = size,
                CornerRadius = new CornerRadius(size / 2),
                Background = g,
                Effect = new System.Windows.Media.Effects.DropShadowEffect { BlurRadius = 10, ShadowDepth = 3, Opacity = 0.5, Color = Colors.Black },
            };
        }
    }

    /// <summary>Stroke icons (24x24 grid), drawn to match the mockup.</summary>
    public static class Icons
    {
        static Geometry G(string d) { var g = Geometry.Parse(d); g.Freeze(); return g; }
        public static readonly Geometry Undo = G("M9 14 4 9l5-5 M4 9h11a5 5 0 0 1 0 10h-3");
        public static readonly Geometry Ant = G("M12 3.2a1.7 1.7 0 1 0 0.01 0 M12 8.6a1.9 2.1 0 1 0 0.01 0 M12 13.8a3 3.9 0 1 0 0.01 0 M10.9 3.6 9 1.6 M13.1 3.6 15 1.6 M10.3 9.6 6.5 7.5 M13.7 9.6 17.5 7.5 M10.2 11 6 11.5 M13.8 11 18 11.5 M10.4 12.4 7 16 M13.6 12.4 17 16");   // slowest wheel speed
        public static readonly Geometry Walk = G("M13 2.5a1.6 1.6 0 1 0 0.01 0 M9.5 22l2.2-6.5 2.8 2.8V22 M11.7 15.5 11 9.5l4 2.3 2.2 3 M11 9.5 7.8 12v3.2");
        public static readonly Geometry Bike = G("M5.5 14.5a3.5 3.5 0 1 0 0.01 0 M18.5 14.5a3.5 3.5 0 1 0 0.01 0 M5.5 18l4-7.5h6l3 7.5 M9.5 10.5 8.5 7.5H6.5 M15.5 10.5 12.5 18h-7");
        public static readonly Geometry Car = G("M3 16v-3.5L5.2 7h13.6l2.2 5.5V16z M3 12.5h18 M7 16v2.5 M17 16v2.5 M6.5 14.2h1.5 M16 14.2h1.5");
        public static readonly Geometry Gear = G("M12 9a3 3 0 1 0 0.01 0 M12 2.5v2.2 M12 19.3v2.2 M4.6 4.6l1.6 1.6 M17.8 17.8l1.6 1.6 M2.5 12h2.2 M19.3 12h2.2 M4.6 19.4l1.6-1.6 M17.8 6.2l1.6-1.6 M12 5.5a6.5 6.5 0 1 0 0.01 0");
        public static readonly Geometry Aperture = G("M12 3a9 9 0 1 0 0.01 0 M14.3 3.3 8.6 13.2 M20.5 9.5H9.1 M18.3 18.4 12.6 8.5 M9.7 20.7l5.7-9.9 M3.5 14.5h11.4 M5.7 5.6l5.7 9.9");
        public static readonly Geometry Refresh = G("M20 11a8 8 0 1 0-2.3 5.7 M20 4v7h-7");
        public static readonly Geometry Broom = G("M20 3 12.5 10.5 M10 9l5 5 M10 9c-2.5 0.5-4.5 2-5.5 4.5L3 21l7.5-1.5c2.5-1 4-3 4.5-5.5 M6.5 17.5 9 15 M9 19.5l2-2");
        // (1.75.59) good / failed AI results
        public static readonly Geometry ThumbUp = G("M7 10v12 M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z");
        public static readonly Geometry ThumbDown = G("M17 14V2 M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z");
        public static readonly Geometry Dots = G("M5 12h0.01 M12 12h0.01 M19 12h0.01");
        public static readonly Geometry Sliders = G("M4 6h9 M17 6h3 M15 4v4 M4 12h3 M11 12h9 M9 10v4 M4 18h11 M19 18h1 M17 16v4");
        public static readonly Geometry Redo = G("M15 14l5-5-5-5 M20 9H9a5 5 0 0 0 0 10h3");
        public static readonly Geometry Move = G("M12 5v14 M5 12h14 M9.8 7.2L12 5L14.2 7.2 M9.8 16.8L12 19L14.2 16.8 M7.2 9.8L5 12L7.2 14.2 M16.8 9.8L19 12L16.8 14.2 M15.60 3.10A9.6 9.6 0 0 1 20.90 8.40 M18.76 7.11L20.90 8.40L21.54 5.99 M8.40 20.90A9.6 9.6 0 0 1 3.10 15.60 M5.24 16.89L3.10 15.60L2.46 18.01");   // cross arrows + two turning arcs: move and rotate
        public static readonly Geometry Rotate = G("M20 12a8 8 0 1 1-2.3-5.7 M20 4v5h-5");
        public static readonly Geometry Brush = G("M20.5 3.5 11 13 M9.5 11.5l3 3 M10.5 15.5c0 2.8-2.2 5-6.5 5 0.8-1.2 0.5-2.3 0.8-3.8 0.5-2 2.2-3.2 4-2.9");   // a paint brush: Distribuisci
        public static readonly Geometry Close = G("M6 6l12 12 M18 6 6 18");
        public static readonly Geometry Scale = G("M3 11h10v10H3z M14 3h7v7 M21 3l-9 9");
        public static readonly Geometry Import = G("M12 3v12 M7 10l5 5 5-5 M4 17v3h16v-3");
        public static readonly Geometry Search = G("M10.5 4a6.5 6.5 0 1 0 0.01 0 M15.3 15.3 20.5 20.5");     // (1.76.62) the lens
        public static readonly Geometry Camera = G("M4 8h3l2-3h6l2 3h3v11H4z M12 10a3.5 3.5 0 1 0 0.01 0");
        // (1.75.32) the clapperboard of the AI video: the board and its tilted arm with the stripes
        public static readonly Geometry Play = G("M8 5.5v13l10.5-6.5z");
        public static readonly Geometry Clapper = G("M3.5 10.5h17v9.5h-17z M3.3 10.5 2.6 6.8 18.4 4 19.1 7.7z M7.2 6l2.1 3.5 M11.3 5.3l2.1 3.5 M15.4 4.6l2 3.4 M3.5 13.5h17");
        public static readonly Geometry Plus = G("M12 5v14 M5 12h14");
        public static readonly Geometry Chevron = G("m9 6 6 6-6 6");
        public static readonly Geometry ChevronDown = G("m6 9 6 6 6-6");
        public static readonly Geometry ChevronsDown = G("m7 6 5 5 5-5 M7 13l5 5 5-5");   // expand the whole tree
        public static readonly Geometry ChevronsUp = G("m7 11 5-5 5 5 M7 18l5-5 5 5");     // fold the whole tree
        public static readonly Geometry Relief = G("M2 19h20 M3 19l5-8 3 4 4-7 6 11 M8 11l1.5-2.5 M15 8l1.2-2");
        public static readonly Geometry Bolt = G("M13 2 4 14h7l-1 8 9-12h-7z");
        public static readonly Geometry Wrench = G("M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-0.6-0.6-2.4z");
        public static readonly Geometry MatStandard = G("M12 3a9 9 0 1 0 0.01 0 M7.2 10.2a5.2 5.2 0 0 1 3.6-3.6 M3.5 13.5c2.5 1.6 5.5 2.4 8.5 2.4s6-0.8 8.5-2.4");
        public static readonly Geometry Rain = G("M7 14a4.5 4.5 0 0 1-.6-9A6 6 0 0 1 17.8 6.6 3.8 3.8 0 0 1 17.5 14z M8.5 17l-1.2 3.2 M12.5 17l-1.2 3.2 M16.5 17l-1.2 3.2");   // cloud with rain
        public static readonly Geometry Snow = G("M12 2v20 M3.3 7l17.4 10 M3.3 17l17.4-10 M9.5 3.5 12 6l2.5-2.5 M9.5 20.5 12 18l2.5 2.5 M4 10.4l3.4.9-.9 3.3 M20 13.6l-3.4-.9.9-3.3 M4 13.6l3.4-.9-.9-3.3 M20 10.4l-3.4.9.9 3.3");   // snowflake
        public static readonly Geometry Puddle = G("M3 16c0-2.2 4-3.6 9-3.6s9 1.4 9 3.6-4 3.6-9 3.6-9-1.4-9-3.6z M7.5 16c.6-.9 2.4-1.5 4.5-1.5 M12 3.2c1.7 2.1 2.7 3.6 2.7 4.9a2.7 2.7 0 0 1-5.4 0c0-1.3 1-2.8 2.7-4.9z");   // a puddle and a drop
        public static readonly Geometry WaterDrop = G("M12 2.8c3.6 4.6 6.2 7.8 6.2 10.9a6.2 6.2 0 0 1-12.4 0C5.8 10.6 8.4 7.4 12 2.8z M8.8 14.2a3.2 3.2 0 0 0 2.7 3.1");
        public static readonly Geometry File = G("M12 2 3 7v10l9 5 9-5V7z m-9 5 9 5 9-5 M12 12v10");
        public static readonly Geometry Folder = G("M3 6h7l2 2h9v11H3z");
        // (1.79.0, Luca: «tipizza le cartelle con delle icone… una bella icona evocativa nel centro») drawn inside the folders of the libraries
        public static readonly Geometry FPaw = G("M12 13c-3 0-5 3-5 5 0 1.5 1.3 2 2.4 2 1 0 1.6-.6 2.6-.6s1.6.6 2.6.6c1.1 0 2.4-.5 2.4-2 0-2-2-5-5-5z M4.3 10.5a1.7 1.7 0 1 0 3.4 0a1.7 1.7 0 1 0 -3.4 0 M16.3 10.5a1.7 1.7 0 1 0 3.4 0a1.7 1.7 0 1 0 -3.4 0 M7.6 6a1.7 1.7 0 1 0 3.4 0a1.7 1.7 0 1 0 -3.4 0 M13 6a1.7 1.7 0 1 0 3.4 0a1.7 1.7 0 1 0 -3.4 0");
        public static readonly Geometry FPerson = G("M8.5 7.5a3.5 3.5 0 1 0 7 0a3.5 3.5 0 1 0 -7 0 M4.5 21c0-4.2 3.3-7.5 7.5-7.5s7.5 3.3 7.5 7.5");
        public static readonly Geometry FSofa = G("M5 11V8a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v3 M3 11h3v4h12v-4h3v6H3z M5 17v2 M19 17v2");
        public static readonly Geometry FPlantPot = G("M8 14h8l-1.2 6H9.2z M12 14V8.5 M12 11c-3 0-4.5-2-4.5-4.5 3 0 4.5 2 4.5 4.5z M12 9.5c0-3 1.8-4.5 4.5-4.5 0 3-1.8 4.5-4.5 4.5z");
        public static readonly Geometry FBriefcase = G("M3 8h18v11H3z M8.5 8V5h7v3 M3 13h18 M11 13v2h2v-2");
        public static readonly Geometry FCube = G("M12 3 20 7.5v9L12 21 4 16.5v-9z M4 7.5 12 12l8-4.5 M12 12v9");
        public static readonly Geometry FBust = G("M8.8 7a3.2 3.2 0 1 0 6.4 0a3.2 3.2 0 1 0 -6.4 0 M6.5 16c0-3.2 2.4-5.5 5.5-5.5s5.5 2.3 5.5 5.5 M6 16h12v2.2H6z M8.5 18.2h7V21h-7z");
        public static readonly Geometry FStreetLamp = G("M12 21V4h5 M17 4v2.5 M14.8 9h4.4l-2.2-2.5z M9 21h6");
        public static readonly Geometry FFlower = G("M10 9a2 2 0 1 0 4 0a2 2 0 1 0 -4 0 M10.1 4.8a1.9 1.9 0 1 0 3.8 0a1.9 1.9 0 1 0 -3.8 0 M14.3 9a1.9 1.9 0 1 0 3.8 0a1.9 1.9 0 1 0 -3.8 0 M10.1 13.2a1.9 1.9 0 1 0 3.8 0a1.9 1.9 0 1 0 -3.8 0 M5.9 9a1.9 1.9 0 1 0 3.8 0a1.9 1.9 0 1 0 -3.8 0 M12 15.1V21 M12 18.5c-2 0-3.5-1-4-3 2 0 3.5 1 4 3z");
        public static readonly Geometry FShrub = G("M5.5 17.5a3.4 3.4 0 0 1 .8-6.7 4 4 0 0 1 7.3-2.3 3.6 3.6 0 0 1 5.6 3.4 3.2 3.2 0 0 1-1 5.6z M3 20h18 M10 17.5V20 M14.5 17.5V20 M10 14.5l1.5 1.5 M14.5 13.5l-1.2 1.3");
        public static readonly Geometry FTree = G("M12 21v-6 M12 15c-4 0-6.5-2.5-6.5-5.5S8 3.8 12 3c4 .8 6.5 4 6.5 6.5S16 15 12 15z M12 12l-2.5-2 M12 10.5l2.5-2");
        public static readonly Geometry FIngot = G("M3 18 6.5 12h11l3.5 6z M7.5 12l2-4h5l2 4");
        public static readonly Geometry FBottle = G("M10 3h4v3.2l2 3V21H8V9.2l2-3z M8 13h8");
        // (1.79.0, Luca: «alcune ti sono sfuggite») trash, palms, sci-fi; the decals: cracks, dirt and grime, graffiti, rust and leaks
        public static readonly Geometry FTrash = G("M4.5 7h15 M9.5 7V4.5h5V7 M6.5 7l1 13.5h9l1-13.5 M10 10.5v7 M14 10.5v7");
        public static readonly Geometry FPalm = G("M12.5 21c0-4.5.3-8.5 1.2-11.5 M13.7 9.5C12 6.5 8.5 6 5.5 8 M13.7 9.5c.4-3.2 3-5 6-4.3 M13.7 9.5c2.6-1.4 5.5-.6 6.8 2 M13.7 9.5c-2.4-.5-5 .8-6 3.2 M13.7 9.5c-.4-2.6-1.8-4.6-4-5.5");
        public static readonly Geometry FRocket = G("M12 2.8c3.4 2.4 5 5.8 5 9.7l-2.4 3.2H9.4L7 12.5c0-3.9 1.6-7.3 5-9.7z M10.7 10.3a1.3 1.3 0 1 0 2.6 0a1.3 1.3 0 1 0 -2.6 0 M7.3 13.5 5 16.5V19l3.6-2 M16.7 13.5 19 16.5V19l-3.6-2 M10.5 19.5c.5 1.2 1 1.8 1.5 2 .5-.2 1-.8 1.5-2");
        public static readonly Geometry FCrack = G("M12.5 3 10.8 8l3.2 2.2-3.7 4.3 3 2.3L11.5 21 M10.8 8 7 7.2 M14 10.2l3.8 1 M10.3 14.5 6.5 16.5");
        public static readonly Geometry FGrime = G("M5 15a3 3 0 1 0 6 0a3 3 0 1 0 -6 0 M9.5 10.5a3.5 3.5 0 1 0 7 0a3.5 3.5 0 1 0 -7 0 M13 15.5a2.8 2.8 0 1 0 5.6 0a2.8 2.8 0 1 0 -5.6 0 M6 20.5h.01 M12 20h.01 M18 20.5h.01");
        public static readonly Geometry FSpray = G("M8 10h8v11H8z M9.5 10V7h5v3 M11 7V4.5h2V7 M8 14h8 M17.5 5.5h.01 M19.5 3.5h.01 M20 7h.01 M18 8.5h.01 M19.5 10h.01");
        public static readonly Geometry FRust = G("M3 5h14v4H3z M17 6.5h4 M9 12c1.2 1.9 2 3.1 2 4.2a2 2 0 0 1-4 0C7 15.1 7.8 13.9 9 12z M14 16.5h.01 M14 20h.01");
        public static readonly Geometry FWindow = G("M4 3h16v18H4z M12 3v18 M4 12h16");
        public static readonly Geometry FBuilding = G("M4 21V5l8-2v18 M12 8h8v13 M2 21h20 M7 8h2 M7 12h2 M7 16h2 M15 12h2 M15 16h2");
        public static readonly Geometry FDoor = G("M6 21V3h12v18 M4 21h16 M14.5 12h.5");
        public static readonly Geometry FBox = G("M3 7 12 3l9 4v10l-9 4-9-4z M3 7l9 4 9-4 M12 11v10 M7.5 5l9 4");
        public static readonly Geometry FMountain = G("M2 19 9 7l4.5 6.5 2.5-3.5 6 9z M7.4 9.7l1.6 1.3 1.4-1");
        public static readonly Geometry Mesh = G("M12 3 4 7.5v9L12 21l8-4.5v-9z");
        public static readonly Geometry Light = G("M12 8a4 4 0 1 0 0.01 0 M12 2v2 M12 20v2 M4.9 4.9l1.4 1.4 M17.7 17.7l1.4 1.4 M2 12h2 M20 12h2 M4.9 19.1l1.4-1.4 M17.7 6.3l1.4-1.4");
        // (1.75.9) SmartView: an eye with a lightning bolt for the pupil
        public static readonly Geometry SmartEye = G("M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z M12.8 8.2 10 12.4h3.2l-1 3.4 2.8-4.2h-3.2z");
        public static readonly Geometry Eye = G("M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z M12 9a3 3 0 1 0 0.01 0");
        public static readonly Geometry EyeOff = G("M3 3l18 18 M10.6 5.1A10 10 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4.1 M6.6 6.6A17 17 0 0 0 2 12s3.5 7 10 7a9.6 9.6 0 0 0 5.4-1.6");
        public static readonly Geometry Frame = G("M4 9V4h5 M20 9V4h-5 M4 15v5h5 M20 15v5h-5 M12 9a3 3 0 1 0 0.01 0");
        public static readonly Geometry Copy = G("M8 8h12v12H8z M4 16V4h12");
        public static readonly Geometry Wand = G("M4 20 15.5 8.5 M17.5 3v4 M15.5 5h4 M20.5 10v2.4 M19.3 11.2h2.4 M10.5 3.5v2.4 M9.3 4.7h2.4");
        public static readonly Geometry Trash = G("M4 7h16 M9 7V4h6v3 M6 7l1 13h10l1-13");
        public static readonly Geometry Save = G("M5 3h11l3 3v15H5z M8 3v6h8 M8 21v-7h8v7");
        public static readonly Geometry Open = G("M3 6h7l2 2h9v3 M3 6v13h15l3-8H7l-4 8");
        public static readonly Geometry New = G("M6 3h9l4 4v14H6z M14 3v5h5");
        public static readonly Geometry Eyedropper = G("M15.5 3.5a2.1 2.1 0 0 1 3 0l2 2a2.1 2.1 0 0 1 0 3L18 11l-5-5z M13 6l5 5 M14.5 9.5 6 18l-3 1 1-3 8.5-8.5");
        public static readonly Geometry Help = G("M12 3a9 9 0 1 0 0.01 0 M9.3 9.3a2.8 2.8 0 0 1 5.4 1c0 1.9-2.7 2.4-2.7 4 M12 17.6v0.01");
        // ---- Ambiente (sky, sun, clouds, night)
        public static readonly Geometry Clock = G("M12 3a9 9 0 1 0 0.01 0 M12 7v5l3 2");
        public static readonly Geometry Calendar = G("M4 6h16v14H4z M4 10h16 M8 3v4 M16 3v4");
        public static readonly Geometry Compass = G("M12 3a9 9 0 1 0 0.01 0 M15.5 8.5l-2 5-5 2 2-5z");
        public static readonly Geometry SunSize = G("M12 8.5a3.5 3.5 0 1 0 0.01 0 M2.5 12h3 M18.5 12h3 M4 10.5 2.5 12 4 13.5 M20 10.5 21.5 12 20 13.5");
        public static readonly Geometry Wind = G("M3 8h10a3 3 0 1 0-3-3 M3 12h15a3 3 0 1 1-3 3 M3 16h6");
        public static readonly Geometry Haze = G("M4 7h16 M2 11h20 M4 15h16 M7 19h10");
        public static readonly Geometry Ozone = G("M12 3a9 9 0 1 0 0.01 0 M12 7a5 5 0 1 0 0.01 0");
        public static readonly Geometry Horizon = G("M2 17h20 M6 17a6 6 0 0 1 12 0 M12 4v3 M5.2 7.7l1.6 1.6 M18.8 7.7l-1.6 1.6 M7 21h10");
        public static readonly Geometry Sunrise = G("M2 18h20 M6 18a6 6 0 0 1 12 0 M12 3v6 M9.5 5.5 12 3l2.5 2.5 M4.2 11.2l1.4 1.4 M19.8 11.2l-1.4 1.4 M7 22h10");
        public static readonly Geometry Sunset = G("M2 18h20 M6 18a6 6 0 0 1 12 0 M12 3v6 M9.5 6.5 12 9l2.5-2.5 M4.2 11.2l1.4 1.4 M19.8 11.2l-1.4 1.4 M7 22h10");
        public static readonly Geometry GoldenHour = G("M2 18h20 M6 18a6 6 0 0 1 12 0 M12 7v2.5 M5.6 10.6l1.6 1.6 M18.4 10.6l-1.6 1.6 M2.5 14.5h2.2 M19.3 14.5h2.2");
        public static readonly Geometry SunCloud = G("M10 3v1.5 M3.5 9.5H5 M5.4 4.9l1 1 M14.6 4.9l-1 1 M7 11a3.2 3.2 0 0 1 5.7-2.6 M8.5 20a3.5 3.5 0 0 1-.4-7 5 5 0 0 1 9.5 1.3A3 3 0 0 1 17.5 20z");
        public static readonly Geometry Cloud = G("M7 19a4.5 4.5 0 0 1-.6-9A6 6 0 0 1 17.8 11.6 3.8 3.8 0 0 1 17.5 19z");
        public static readonly Geometry Fog = G("M5 9a4 4 0 0 1 7.6-1.6A3.5 3.5 0 0 1 19 10 M3 13h18 M5 17h14 M8 21h8");
        public static readonly Geometry Moon = G("M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5z");
        public static readonly Geometry Star = G("M12 3l2.1 5.2 5.6.5-4.3 3.7 1.3 5.5L12 15l-4.7 2.9 1.3-5.5-4.3-3.7 5.6-.5z");
        public static readonly Geometry Studio = G("M7 4h10v7H7z M17 6l3-1v5l-3-1 M12 11v5 M12 16l-5 5 M12 16l5 5 M12 16v5");
        public static readonly Geometry Cloth = G("M4 6c2.7-2 5.3 2 8 0s5.3-2 8 0v12c-2.7-2-5.3 2-8 0s-5.3-2-8 0z M4 12c2.7-2 5.3 2 8 0s5.3-2 8 0");
        public static readonly Geometry Leaf = G("M5 19C5 10 10 5 20 4c0 10-5 15-15 15z M5 19c3-5 6.5-8.5 11-11");
        public static readonly Geometry Grass = G("M2 20h20 M5 20c0-3 .5-5 2-7 M8 20c0-4 1-6 3-9 M12 20c0-3 1-6 3.5-8 M16 20c0-2.5.5-4 2.5-5.5");
        public static readonly Geometry Expand = G("M4 10V4h6 M20 14v6h-6 M4 4l6 6 M20 20l-6-6");
        public static readonly Geometry Soft = G("M3 12c2.2-3.5 4.3 3.5 6.5 0s4.3 3.5 6.5 0 3.8 3.5 5 1.5");
        public static readonly Geometry Image = G("M3 5h18v14H3z M3 16l5-5 4 4 3-3 6 6 M15.5 8.5a1.5 1.5 0 1 0 0.01 0");
        public static readonly Geometry Globe = G("M12 3a9 9 0 1 0 0.01 0 M3 12h18 M12 3c3 3 3 15 0 18 M12 3c-3 3-3 15 0 18");
        public static readonly Geometry Pivot = G("M12 13V4 M12 13l7.5 4.5 M12 13l-7.5 4.5 M10 4.8 12 2.8 14 4.8 M17.4 18.9l2.6 0.4-0.6-2.6 M6.6 18.9 4 19.3l0.6-2.6 M12 11a2 2 0 1 0 0.01 0");   // mini gizmo: pivot placed by hand
        public static readonly Geometry Layers = G("M12 3 21 7.5 12 12 3 7.5Z M3 12 12 16.5 21 12 M3 16.5 12 21 21 16.5");   // replace in the selection
        // icons of the sections of the panels (1.74.0: every section has its badge, as in Ambiente)
        public static readonly Geometry Palette = G("M12 3a9 9 0 1 0 0 18c1 0 1.5-0.7 1.5-1.5 0-0.4-0.2-0.8-0.4-1.1-0.3-0.3-0.4-0.6-0.4-1 0-0.8 0.7-1.5 1.5-1.5H16a5 5 0 0 0 5-5c0-4.4-4-7.9-9-7.9z M7.5 10.5a1 1 0 1 0 0.01 0 M11 6.5a1 1 0 1 0 0.01 0 M15.5 7.5a1 1 0 1 0 0.01 0");
        public static readonly Geometry Rough = G("M3 15l2-3 2 2 2-4 2 3 2-2 2 3 2-4 2 3 2-2 M3 20h18");
        public static readonly Geometry Gem = G("M6 3h12l4 6-10 12L2 9z M2 9h20 M12 21 8 9l2-6 M12 21l4-12-2-6");
        public static readonly Geometry Sparkles = G("M11 3l1.9 5.1L18 10l-5.1 1.9L11 17l-1.9-5.1L4 10l5.1-1.9z M19 3v4 M17 5h4 M18 16v4 M16 18h4");
        public static readonly Geometry Glass = G("M7 3h10l-0.6 7a4.4 4.4 0 0 1-8.8 0z M12 14.5V21 M8 21h8 M7.4 7h9.2");
        public static readonly Geometry Feather = G("M20.2 12.2a6 6 0 0 0-8.4-8.4L5 10.6V19h8.4z M16 8 2 22 M17.5 15H9");
        public static readonly Geometry Flame = G("M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.4-0.5-2-1-3-1.1-2.1-0.2-4 2-6 0.5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.2 0.4-2.3 1-3.2 0.3 1.6 1.3 2.7 2.5 2.7z");
        public static readonly Geometry Grid = G("M3 3h18v18H3z M3 9h18 M3 15h18 M9 3v18 M15 3v18");
        public static readonly Geometry Chip = G("M5 5h14v14H5z M9 9h6v6H9z M9 2v3 M15 2v3 M9 19v3 M15 19v3 M2 9h3 M2 15h3 M19 9h3 M19 15h3");
        public static readonly Geometry Monitor = G("M3 4h18v12H3z M8 20h8 M12 16v4");
        public static readonly Geometry Drive = G("M22 12H2 M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.1z M6 16h0.01 M10 16h0.01");
        public static readonly Geometry Key = G("M15 4a4.5 4.5 0 1 0 0.01 0 M11.8 11.7 3 20.5 M6 17.5l2 2 M8.5 15l2 2");
        // (1.78.4) the kinds of light, in the menu of the lights button
        public static readonly Geometry LightSpot = G("M9 3h6l3 8H6z M7 14l-2 5 M12 14v6 M17 14l2 5");
        public static readonly Geometry LightArea = G("M4 4h16v8H4z M7 15l-1 5 M12 15v5 M17 15l1 5");
        public static readonly Geometry LightDisk = G("M12 3a5 5 0 1 0 0.01 0 M7 15.5l-1 4.5 M12 15.5v5 M17 15.5l1 4.5");
        public static readonly Geometry LightStrip = G("M2 8h20v3H2z M6 14l-1 5 M12 14v6 M18 14l1 5");
        public static readonly Geometry Bulb = G("M9 18h6 M10 21h4 M12 3a6 6 0 0 0-3.5 10.9c0.6 0.5 1 1.2 1 2V16h5v-0.1c0-0.8 0.4-1.5 1-2A6 6 0 0 0 12 3z");
    }
}
