using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;

namespace Simpler
{
    /// <summary>
    /// Label + slider + numeric box. <see cref="Changing"/> fires continuously while dragging (live preview),
    /// <see cref="Committed"/> once when the user releases the mouse or confirms the number.
    /// </summary>
    public sealed class ValueSlider : Grid
    {
        readonly double _min, _max;
        readonly bool _log;
        readonly string _format;
        readonly Border _track, _fill;
        readonly Ellipse _thumb;
        readonly TextBox _box;
        readonly Grid _bar;
        readonly TextBlock _label;
        public string LabelText => _label.Text;          // (1.76.32: the key of a favourite command)
        bool _dragging;
        double _dragFrom, _dragX;          // the value and the mouse when the press started
        bool _onThumb;                     // pressed on the knob itself
        // (1.79.0, Luca: «sposto lo slider sotto e quello sopra cambia e torna a un valore precedente»; «ho portato lo
        // slider ... l'ho lasciato non è successo nulla») a panel made again while a slider was held (the snow mantle
        // computed in the background reloads the panel of the Ambiente) took the slider away from under the mouse: its
        // release never arrived, nothing was sent, and the new panel showed the old value. While a slider is held or
        // its box holds a typed number, the panels wait (MainWindow.RenderProps) and are made when it is let go.
        static int _held;
        /// <summary>A slider is being dragged, or the box with the keyboard holds a number not taken yet.</summary>
        /// (15/11, Luca: «rimasto incastrato nello scatter… non c'è modo di togliere il pannello») this answer holds back EVERY
        /// panel: it must never stay true by mistake. So it is true only for what is really happening now: a slider counted
        /// as held AND the left button really down (a count left over is put back to zero), or a box that is on screen, has
        /// the keyboard and holds something TYPED and not taken yet (before: any difference between the text of the box and
        /// the value as the slider writes it - a slider with its own way of writing the value stayed «pending» for ever).
        public static bool Interacting
        {
            get
            {
                if (_held > 0)
                {
                    if (Mouse.LeftButton == MouseButtonState.Pressed) return true;
                    AppLog.Write($"slider: {_held} counted as held with the mouse button up - put back to zero");
                    _held = 0;
                }
                return Keyboard.FocusedElement is TextBox tb && tb.Tag is ValueSlider vs && vs.Pending
                    && tb.IsVisible && tb.IsKeyboardFocused && PresentationSource.FromVisual(tb) != null;
            }
        }
        /// <summary>Raised when a slider is let go or its box is confirmed / left.</summary>
        public static event Action? InteractionEnded;
        void EndDrag(bool commit)
        {
            if (!_dragging) return;
            _dragging = false;
            _held = Math.Max(0, _held - 1);
            // (sent BEFORE the mouse is freed: freeing it makes WPF send a mouse move at once, and the log said «sent late» for
            // every normal release)
            if (commit) SendIfChanged("let go");
            if (_bar.IsMouseCaptured) _bar.ReleaseMouseCapture();
            InteractionEnded?.Invoke();
        }
        // (14/11, Luca: «il 39 che avevo messo non era stato preso»: the fog at 39,8 on screen, nothing sent to the engine - app.log
        // had no change at all) what the slider SHOWS and what was SENT are now compared, not the start and the end of one drag:
        // a value moved and never sent (a release that never arrived: the mouse let go over the 3D view, a panel locked while
        // held) is sent at the next chance - the mouse moving over the slider with no button, the panel enabled again, the
        // slider leaving the window. And the log says every time a value is sent or held back.
        double _sent = double.NaN;
        string _name = "";
        void SendIfChanged(string why)
        {
            if (double.IsNaN(_sent)) _sent = _dragFrom;
            if (Math.Abs(_value - _sent) < 1e-12) return;
            AppLog.Write($"slider «{_name}» {why}: {_sent.ToString("0.####", System.Globalization.CultureInfo.InvariantCulture)} -> {_value.ToString("0.####", System.Globalization.CultureInfo.InvariantCulture)}" + (Committed == null ? " (nobody listens)" : ""));
            _sent = _value;
            Committed?.Invoke(_value);
        }
        double _value;

        public event Action<double>? Changing;
        public event Action<double>? Committed;

        public double Value => _value;
        /// <summary>Width of the unit column (5 px of gap + the longest unit, «mesh»).</summary>
        public const double UnitWidth = 32;

        /// <summary>Optional: how the value is written in the box (e.g. 10.5 -> "10:30") and read back from it.</summary>
        public Func<double, string>? Display { get; set; }
        public Func<string, double?>? Parse { get; set; }
        /// <summary>Optional: the slider moves in steps of this size (e.g. 5 minutes, 1 degree), within min-max.</summary>
        public double Step { get; set; }
        string Show(double v) => Display != null ? Display(v) : v.ToString(_format, System.Globalization.CultureInfo.CurrentCulture);
        /// <summary>A small coloured icon before the label (the label column grows to make room).</summary>
        public ValueSlider WithIcon(Geometry icon, Color color)
        {
            Children.Remove(_label);
            var row = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            var ic = Theme.Icon(icon, color, 13, 1.6);
            ic.Margin = new Thickness(0, 0, 7, 0);
            row.Children.Add(ic);
            _label.TextTrimming = TextTrimming.CharacterEllipsis;
            _label.MaxWidth = 92;
            row.Children.Add(_label);
            Children.Insert(0, row);
            ColumnDefinitions[0].Width = new GridLength(114);
            return this;
        }

        /// <summary>For narrow places (a model's row in Scatter): the label only as wide as its text and a smaller box,
        /// so the slider keeps the room; stacked: the label on a line of its own above slider and box.</summary>
        public ValueSlider Compact(bool stacked = false)
        {
            ColumnDefinitions[2].Width = new GridLength(50);
            ColumnDefinitions[3].Width = GridLength.Auto;       // (narrow places: the unit only as wide as it is)
            if (!stacked)
            {
                ColumnDefinitions[0].Width = GridLength.Auto;
                _label.Margin = new Thickness(0, 0, 10, 0);
                return this;
            }
            RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            ColumnDefinitions[0].Width = new GridLength(0);
            foreach (UIElement c in Children)
                if (c != _label) Grid.SetRow(c, 1);
            Grid.SetColumnSpan(_label, ColumnDefinitions.Count);
            _label.Margin = new Thickness(0, 0, 0, 2);
            return this;
        }

        /// <summary>True while the box holds a typed value not taken yet.</summary>
        public bool Pending => _boxTyped;
        bool _boxTyped;          // (something typed, erased or pasted in the box since the value was last taken or written)

        /// <summary>Re-writes the box after Display was set.</summary>
        public void Refresh() { _box.Text = Show(_value); _boxTyped = false; }

        /// <param name="log">logarithmic scale (powers, sizes spanning several orders of magnitude)</param>
        /// <param name="format">numeric format for the box, e.g. "0", "0.0"</param>
        /// <param name="trackBrush">optional custom track (e.g. a colour-temperature gradient)</param>
        public ValueSlider(string label, double value, double min, double max, bool log = false, string format = "0.##",
                           string? unit = null, Brush? trackBrush = null, string? tooltip = null)
        {
            _min = min; _max = max; _log = log && min > 0; _format = WithCents(format);
            Margin = new Thickness(0, 0, 0, 10);
            ToolTip = tooltip;
            ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(96) });
            ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(62) });
            // (the unit in a column of fixed width, also when there is none: the boxes of «%», «cm» and «°» sliders
            // one under the other, their edges in line)
            ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(UnitWidth) });

            var l = Theme.Label(label, 12, Theme.TextMuted);
            l.VerticalAlignment = VerticalAlignment.Center;
            _label = l;
            Children.Add(l);

            _bar = new Grid { Height = 22, Margin = new Thickness(0, 0, 10, 0), Background = Brushes.Transparent, Cursor = Cursors.Hand };
            _track = new Border { Height = 4, CornerRadius = new CornerRadius(2), Background = trackBrush ?? Theme.B("#1A2842"), VerticalAlignment = VerticalAlignment.Center };
            _fill = new Border { Height = 4, CornerRadius = new CornerRadius(2), Background = trackBrush == null ? Theme.B(Theme.Accent) : Brushes.Transparent,
                                 HorizontalAlignment = HorizontalAlignment.Left, VerticalAlignment = VerticalAlignment.Center };
            _thumb = new Ellipse { Width = 14, Height = 14, Fill = Theme.B(Theme.Text), Stroke = Theme.B("#0A1222"), StrokeThickness = 2,
                                   HorizontalAlignment = HorizontalAlignment.Left, VerticalAlignment = VerticalAlignment.Center };
            _bar.Children.Add(_track);
            _bar.Children.Add(_fill);
            _bar.Children.Add(_thumb);
            Grid.SetColumn(_bar, 1);
            Children.Add(_bar);

            _box = Theme.Input("", true);
            _box.Padding = new Thickness(6, 3, 6, 3);
            _box.TextAlignment = TextAlignment.Right;
            Grid.SetColumn(_box, 2);
            Children.Add(_box);
            if (unit != null)
            {
                var u = Theme.Label(unit, 11, Theme.TextFaint);
                u.Margin = new Thickness(5, 0, 0, 0);
                u.VerticalAlignment = VerticalAlignment.Center;
                Grid.SetColumn(u, 3);
                Children.Add(u);
            }

            // (Luca: «non puoi fare una verifica preventiva») a press that changes nothing commits nothing: a click on
            // the knob without moving it rounded the value a hair and sent an edit, and every edit makes the engine
            // update the scene (materials, rain, lights) - the busy box for nothing
            _bar.MouseLeftButtonDown += (_, e) =>
            {
                if (!_dragging) _held++;
                _dragging = true; _bar.CaptureMouse();
                _dragFrom = _value; _dragX = e.GetPosition(_bar).X;
                _onThumb = Math.Abs(_dragX - (_thumb.Margin.Left + 7)) <= 8;
                if (!_onThumb) SetFromMouse(_dragX);
                e.Handled = true;
            };
            _bar.MouseMove += (_, e) =>
            {
                // (the button is up but its release never arrived: the drag ends here and the value is sent)
                if (_dragging && e.LeftButton != MouseButtonState.Pressed) { EndDrag(true); return; }
                if (!_dragging) { if (!double.IsNaN(_sent)) SendIfChanged("sent late (mouse over the slider)"); return; }
                var x = e.GetPosition(_bar).X;
                if (_onThumb && Math.Abs(x - _dragX) < 2) return;     // (a still knob: not a move yet)
                _onThumb = false;
                SetFromMouse(x);
            };
            _bar.MouseLeftButtonUp += (_, __) => EndDrag(true);
            // (the mouse taken away while held - another window, the slider out of the panel: what was moved is sent)
            _bar.LostMouseCapture += (_, __) => EndDrag(true);
            IsEnabledChanged += (_, __) => { if (_dragging) EndDrag(true); else if (!double.IsNaN(_sent)) SendIfChanged("sent late (panel enabled again)"); };
            Unloaded += (_, __) => { if (_dragging) EndDrag(true); else if (!double.IsNaN(_sent)) SendIfChanged("sent late (panel made again)"); };
            _bar.SizeChanged += (_, __) => Layout();
            _box.KeyDown += (_, e) =>
            {
                if (e.Key != Key.Enter && e.Key != Key.Return) return;
                CommitBox();                       // Enter takes the typed value at once
                _box.SelectAll();
                InteractionEnded?.Invoke();
                e.Handled = true;
            };
            _box.LostFocus += (_, __) => { CommitBox(); InteractionEnded?.Invoke(); };
            _box.PreviewTextInput += (_, __) => _boxTyped = true;
            _box.PreviewKeyDown += (_, e) =>
            {
                if (e.Key is Key.Back or Key.Delete || (e.Key is Key.V or Key.X && (Keyboard.Modifiers & ModifierKeys.Control) != 0)) _boxTyped = true;
            };
            _box.Tag = this;                       // (the window sends Ctrl+Z to the app undo when nothing is pending)
            SetValue(value, false);
            _name = label; _sent = value;
        }

        /// <summary>Every number can take decimals and hundredths (0.125 m, 2.5 W, 12.75 %): a plain format ("0",
        /// "0.#", "0.0") gets at least two decimal places, shown only when the value has them. Integer settings
        /// (samples, order, blades) are still rounded by their own panel.</summary>
        static string WithCents(string f)
        {
            if (!System.Text.RegularExpressions.Regex.IsMatch(f, @"^0(\.[0#]*)?$")) return f;
            var dot = f.IndexOf('.');
            var dec = dot < 0 ? 0 : f.Length - dot - 1;
            if (dec >= 2) return f;
            return (dot < 0 ? f + "." : f) + new string('#', 2 - dec);
        }

        double ToFraction(double v)
        {
            v = Math.Clamp(v, _min, _max);
            return _log ? Math.Log(v / _min) / Math.Log(_max / _min) : (v - _min) / (_max - _min);
        }

        double FromFraction(double f)
        {
            f = Math.Clamp(f, 0, 1);
            return _log ? _min * Math.Pow(_max / _min, f) : _min + f * (_max - _min);
        }

        void SetFromMouse(double x)
        {
            var w = Math.Max(1, _bar.ActualWidth - 14);
            var v = FromFraction((x - 7) / w);
            SetValue(Step > 0 ? Math.Clamp(Math.Round(v / Step) * Step, _min, _max) : RoundNice(v), true);
        }

        double RoundNice(double v)
        {
            // keep 3 significant digits while dragging: clean numbers in the box
            if (v == 0) return 0;
            var mag = Math.Pow(10, Math.Floor(Math.Log10(Math.Abs(v))) - 2);
            return Math.Round(v / mag) * mag;
        }

        public void SetValue(double v, bool notify)
        {
            _value = v;
            if (!notify && !_dragging) _sent = v;       // (a value given by the panel: nothing to send)
            _box.Text = Show(v);
            _boxTyped = false;
            Layout();
            if (notify) Changing?.Invoke(v);
        }

        void Layout()
        {
            var w = Math.Max(0, _bar.ActualWidth - 14);
            var f = ToFraction(_value);
            _thumb.Margin = new Thickness(f * w, 0, 0, 0);
            _fill.Width = Math.Max(0, f * w + 7);
        }

        void CommitBox()
        {
            _boxTyped = false;          // (taken, or refused and written back: either way nothing typed is waiting)
            if (Parse != null)
            {
                var pv = Parse(_box.Text);
                if (pv == null) { _box.Text = Show(_value); return; }
                var c = Math.Clamp(pv.Value, _min, _max);
                _box.Text = Show(c);
                if (Math.Abs(c - _value) < 1e-12) return;
                _value = c; Layout(); Changing?.Invoke(c); _sent = c; Committed?.Invoke(c);
                return;
            }
            if (!Num.TryParse(_box.Text, out var v)) { _box.Text = _value.ToString(_format); return; }
            // the box may go beyond the slider ends: above the maximum always, below the minimum on logarithmic
            // sliders (down to a thousandth of it) and never below zero on the others
            v = _log ? Math.Max(_min / 1000, v) : Math.Max(_min, v);
            _box.Text = v.ToString(_format, System.Globalization.CultureInfo.CurrentCulture);
            if (_format.StartsWith("0") && !_format.Contains('.') && Math.Abs(v) < 1 && v != 0)
                _box.Text = v.ToString("0.####", System.Globalization.CultureInfo.CurrentCulture);
            if (Math.Abs(v - _value) < 1e-12) return;
            _value = v;
            Layout();
            Changing?.Invoke(v);
            _sent = v;
            Committed?.Invoke(v);
        }
    }

    /// <summary>A small on/off switch with a label.</summary>
    public sealed class Toggle : DockPanel
    {
        readonly Border _knobTrack;
        readonly Ellipse _knob;
        bool _on;
        public event Action<bool>? Toggled;
        public string LabelText { get; } = "";

        public Toggle(string label, bool on, string? tooltip = null)
        {
            Margin = new Thickness(0, 2, 0, 10);
            Cursor = Cursors.Hand;
            Background = Brushes.Transparent;
            ToolTip = tooltip;
            _knobTrack = new Border { Width = 34, Height = 18, CornerRadius = new CornerRadius(9) };
            _knob = new Ellipse { Width = 12, Height = 12, Fill = Theme.B(Theme.Text), HorizontalAlignment = HorizontalAlignment.Left, VerticalAlignment = VerticalAlignment.Center };
            _knobTrack.Child = _knob;
            DockPanel.SetDock(_knobTrack, Dock.Right);
            Children.Add(_knobTrack);
            _multi = Theme.Label(L.T("multi"), 10, Theme.Warm);
            _multi.VerticalAlignment = VerticalAlignment.Center;
            _multi.Margin = new Thickness(0, 0, 6, 0);
            _multi.Visibility = Visibility.Collapsed;
            DockPanel.SetDock(_multi, Dock.Right);
            Children.Add(_multi);
            var l = Theme.Label(label, 12, Theme.TextMuted);
            l.VerticalAlignment = VerticalAlignment.Center;
            Children.Add(l);
            LabelText = label;
            // (mixed: from «multi» a click turns it on for all)
            MouseLeftButtonUp += (_, __) => { Set(_mixed || !_on); Toggled?.Invoke(_on); };
            Set(on);
        }

        readonly TextBlock _multi;
        bool _mixed;

        /// <summary>Several objects selected with different values: the knob in the middle and a small «multi».</summary>
        public Toggle(string label, bool? state, string? tooltip) : this(label, state ?? false, tooltip)
        {
            if (state == null)
            {
                _mixed = true;
                _multi.Visibility = Visibility.Visible;
                _knobTrack.Background = Theme.B(Theme.C("#2A3A58"));
                _knob.Margin = new Thickness(11, 0, 0, 0);
            }
        }

        /// <summary>(1.76.55) Back to a state without Toggled (a choice taken back: «No» to a warning).</summary>
        public void SetQuiet(bool on) => Set(on);

        void Set(bool on)
        {
            _on = on;
            _mixed = false;
            if (_multi != null) _multi.Visibility = Visibility.Collapsed;
            _knobTrack.Background = Theme.B(on ? Theme.Accent : Theme.C("#1A2842"));
            _knob.Margin = new Thickness(on ? 19 : 3, 0, 0, 0);
        }
    }
    /// <summary>
    /// Colour field: label + swatch + hex. Clicking the swatch opens a picker (saturation/brightness square and hue bar).
    /// Values are linear RGB 0-1 (as Blender stores them); the picker and the hex show sRGB like any paint program.
    /// </summary>
    public sealed class ColorField : Grid
    {
        double[] _lin;
        readonly Border _swatch;
        readonly TextBox _hex;
        public event Action<double[]>? Committed;

        public ColorField(string label, double[] linear, string? tooltip = null)
        {
            _lin = new[] { linear.Length > 0 ? linear[0] : 0.8, linear.Length > 1 ? linear[1] : 0.8, linear.Length > 2 ? linear[2] : 0.8 };
            Margin = new Thickness(0, 0, 0, 10);
            ToolTip = tooltip;
            ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(96) });
            ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(40) });
            ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            var l = Theme.Label(label, 12, Theme.TextMuted);
            Children.Add(l);
            _swatch = new Border { Width = 30, Height = 22, CornerRadius = new CornerRadius(5), BorderBrush = Theme.B(Theme.LineStrong),
                                   BorderThickness = new Thickness(1), Cursor = Cursors.Hand, HorizontalAlignment = HorizontalAlignment.Left };
            Grid.SetColumn(_swatch, 1);
            Children.Add(_swatch);
            _hex = Theme.Input("", true);
            _hex.Padding = new Thickness(6, 3, 6, 3);
            Grid.SetColumn(_hex, 2);
            Children.Add(_hex);
            _swatch.MouseLeftButtonUp += (_, __) => OpenPicker();
            _hex.KeyDown += (_, e) => { if (e.Key == Key.Enter) CommitHex(); };
            _hex.LostFocus += (_, __) => CommitHex();
            Show();
        }

        public static double ToSrgb(double c) => c <= 0.0031308 ? 12.92 * c : 1.055 * Math.Pow(c, 1 / 2.4) - 0.055;
        public static double ToLinear(double c) => c <= 0.04045 ? c / 12.92 : Math.Pow((c + 0.055) / 1.055, 2.4);
        static byte B8(double v) => (byte)Math.Round(Math.Clamp(v, 0, 1) * 255);

        Color Srgb() => Color.FromRgb(B8(ToSrgb(_lin[0])), B8(ToSrgb(_lin[1])), B8(ToSrgb(_lin[2])));

        void Show()
        {
            var c = Srgb();
            _swatch.Background = new SolidColorBrush(c);
            _hex.Text = $"#{c.R:X2}{c.G:X2}{c.B:X2}";
        }

        void Set(Color c, bool commit)
        {
            _lin = new[] { ToLinear(c.R / 255.0), ToLinear(c.G / 255.0), ToLinear(c.B / 255.0) };
            Show();
            if (commit) Committed?.Invoke(_lin);
        }

        void CommitHex()
        {
            try
            {
                var t = _hex.Text.Trim();
                if (!t.StartsWith("#")) t = "#" + t;
                var c = (Color)ColorConverter.ConvertFromString(t);
                if (c == Srgb()) return;
                Set(c, true);
            }
            catch { Show(); }
        }

        void OpenPicker()
        {
            var c = Srgb();
            RgbToHsv(c, out var h, out var sat, out var val);
            const double size = 180;
            var root = new StackPanel { Margin = new Thickness(12) };
            var sv = new Grid { Width = size, Height = size, Cursor = Cursors.Cross, ClipToBounds = true };
            var hueFill = new Border();
            var white = new Border { Background = new LinearGradientBrush(Colors.White, Color.FromArgb(0, 255, 255, 255), 0) };
            var black = new Border { Background = new LinearGradientBrush(Color.FromArgb(0, 0, 0, 0), Colors.Black, 90) };
            var dot = new Ellipse { Width = 12, Height = 12, Stroke = Brushes.White, StrokeThickness = 2, HorizontalAlignment = HorizontalAlignment.Left, VerticalAlignment = VerticalAlignment.Top, IsHitTestVisible = false };
            sv.Children.Add(hueFill); sv.Children.Add(white); sv.Children.Add(black); sv.Children.Add(dot);
            var hueBar = new Grid { Width = size, Height = 14, Margin = new Thickness(0, 10, 0, 0), Cursor = Cursors.Hand };
            var rainbow = new LinearGradientBrush { StartPoint = new Point(0, 0), EndPoint = new Point(1, 0) };
            for (int i = 0; i <= 6; i++) rainbow.GradientStops.Add(new GradientStop(HsvToRgb(i * 60, 1, 1), i / 6.0));
            hueBar.Children.Add(new Border { Background = rainbow, CornerRadius = new CornerRadius(3) });
            var hueKnob = new Border { Width = 6, Height = 18, Margin = new Thickness(0, -2, 0, -2), Background = Brushes.White, CornerRadius = new CornerRadius(2),
                                       HorizontalAlignment = HorizontalAlignment.Left, IsHitTestVisible = false };
            hueBar.Children.Add(hueKnob);
            root.Children.Add(sv);
            root.Children.Add(hueBar);
            var preview = new Border { Height = 22, CornerRadius = new CornerRadius(4), Margin = new Thickness(0, 10, 0, 0) };
            root.Children.Add(preview);

            void Refresh(bool commit)
            {
                hueFill.Background = new SolidColorBrush(HsvToRgb(h, 1, 1));
                dot.Margin = new Thickness(sat * size - 6, (1 - val) * size - 6, 0, 0);
                hueKnob.Margin = new Thickness(h / 360 * (size - 6), -2, 0, -2);
                var cc = HsvToRgb(h, sat, val);
                preview.Background = new SolidColorBrush(cc);
                Set(cc, commit);
            }
            bool dragSv = false, dragHue = false;
            sv.MouseLeftButtonDown += (_, e) => { dragSv = true; sv.CaptureMouse(); var p = e.GetPosition(sv); sat = Math.Clamp(p.X / size, 0, 1); val = 1 - Math.Clamp(p.Y / size, 0, 1); Refresh(false); };
            sv.MouseMove += (_, e) => { if (!dragSv) return; var p = e.GetPosition(sv); sat = Math.Clamp(p.X / size, 0, 1); val = 1 - Math.Clamp(p.Y / size, 0, 1); Refresh(false); };
            sv.MouseLeftButtonUp += (_, __) => { if (!dragSv) return; dragSv = false; sv.ReleaseMouseCapture(); Refresh(true); };
            hueBar.MouseLeftButtonDown += (_, e) => { dragHue = true; hueBar.CaptureMouse(); h = Math.Clamp(e.GetPosition(hueBar).X / size, 0, 1) * 360; Refresh(false); };
            hueBar.MouseMove += (_, e) => { if (!dragHue) return; h = Math.Clamp(e.GetPosition(hueBar).X / size, 0, 1) * 360; Refresh(false); };
            hueBar.MouseLeftButtonUp += (_, __) => { if (!dragHue) return; dragHue = false; hueBar.ReleaseMouseCapture(); Refresh(true); };
            var popup = new System.Windows.Controls.Primitives.Popup
            {
                PlacementTarget = _swatch, Placement = System.Windows.Controls.Primitives.PlacementMode.Bottom, StaysOpen = false, AllowsTransparency = true,
                Child = new Border { Child = root, Background = Theme.B(Theme.Raised), BorderBrush = Theme.B(Theme.LineStrong), BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(8) },
            };
            Refresh(false);
            popup.IsOpen = true;
        }

        static void RgbToHsv(Color c, out double h, out double s, out double v)
        {
            double r = c.R / 255.0, g = c.G / 255.0, b = c.B / 255.0;
            double max = Math.Max(r, Math.Max(g, b)), min = Math.Min(r, Math.Min(g, b)), d = max - min;
            v = max; s = max <= 0 ? 0 : d / max;
            if (d <= 0) h = 0;
            else if (max == r) h = 60 * (((g - b) / d) % 6);
            else if (max == g) h = 60 * ((b - r) / d + 2);
            else h = 60 * ((r - g) / d + 4);
            if (h < 0) h += 360;
        }

        public static Color HsvToRgb(double h, double s, double v)
        {
            h = ((h % 360) + 360) % 360;
            double c = v * s, x = c * (1 - Math.Abs(h / 60 % 2 - 1)), m = v - c;
            double r, g, b;
            if (h < 60) (r, g, b) = (c, x, 0); else if (h < 120) (r, g, b) = (x, c, 0); else if (h < 180) (r, g, b) = (0, c, x);
            else if (h < 240) (r, g, b) = (0, x, c); else if (h < 300) (r, g, b) = (x, 0, c); else (r, g, b) = (c, 0, x);
            return Color.FromRgb(B8(r + m), B8(g + m), B8(b + m));
        }
    }
}
