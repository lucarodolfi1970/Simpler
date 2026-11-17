using System;
using System.Globalization;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;

namespace Simpler
{
    /// <summary>
    /// The sky seen from above, turned as the view (1.68.0): the top of the dome is where the camera looks, the bottom
    /// behind it. The sun is dragged where it should be: the distance from the middle is its height (middle = straight
    /// up, the circle = the horizon, the dark band = up to 10° under it), the direction is where its light comes from.
    /// Day and latitude stay: the height gives the hour, the direction the north (of the two hours with that height
    /// the one that moves the north less). A height the sun cannot reach that day stops at its highest (or lowest).
    /// Seen from above, not tilted: in a tilted dome the sun in front of the camera and low (back light, sunsets)
    /// would be hidden behind the sphere and could not be taken.
    /// </summary>
    public sealed class SunDome : FrameworkElement
    {
        // the same formulas as the engine (scene_ops.sun_vector) and the view (sunVector)
        public static (double az, double el) Direction(double hour, double north, double day, double lat)
        {
            double r = Math.PI / 180, phi = lat * r;
            double dec = Decl(day) * r;
            double h = 15 * (hour - 12) * r;
            double east = -Math.Cos(dec) * Math.Sin(h);
            double nrt = Math.Sin(dec) * Math.Cos(phi) - Math.Cos(dec) * Math.Cos(h) * Math.Sin(phi);
            double up = Math.Sin(dec) * Math.Sin(phi) + Math.Cos(dec) * Math.Cos(h) * Math.Cos(phi);
            // azimuth in the scene: degrees clockwise from +Y seen from above (north is at «north», east 90° after it)
            double az = north + Math.Atan2(east, nrt) / r;
            return (Wrap(az), Math.Asin(Math.Clamp(up, -1, 1)) / r);
        }

        public static double Decl(double day) => 23.44 * Math.Sin(2 * Math.PI / 365 * (day - 81));
        public static double MaxElev(double day, double lat) => 90 - Math.Abs(lat - Decl(day));
        public static double MinElev(double day, double lat) => Math.Abs(lat + Decl(day)) - 90;
        static double Wrap(double a) => ((a % 360) + 360) % 360;
        static double Diff(double a, double b) { var d = Wrap(a - b); return d > 180 ? 360 - d : d; }

        /// <summary>Hour and north that put the sun at this azimuth (scene) and height; clamped = the height was out
        /// of reach that day.</summary>
        public static (double hour, double north, bool clamped) Solve(double az, double el, double day, double lat, double northNow)
        {
            double r = Math.PI / 180, phi = lat * r, dec = Decl(day) * r;
            double den = Math.Cos(dec) * Math.Cos(phi);
            double c = den > 1e-9 ? (Math.Sin(el * r) - Math.Sin(dec) * Math.Sin(phi)) / den : 1;
            bool clamped = c > 1 + 1e-9 || c < -1 - 1e-9;
            double h0 = Math.Acos(Math.Clamp(c, -1, 1)) / r;           // hour angle in degrees (0 = noon)
            double best = 12, bestN = northNow, bestD = double.MaxValue;
            foreach (var h in new[] { -h0, h0 })                        // morning, afternoon
            {
                var hour = 12 + h / 15;
                var (trueAz, _) = Direction(hour, 0, day, lat);
                var n = Wrap(az - trueAz);
                var d = Diff(n, northNow);
                if (d < bestD - 1e-9) { bestD = d; best = hour; bestN = n; }
            }
            return (Math.Clamp(best, 0, 24), bestN, clamped);
        }

        double _hour, _north, _day, _lat, _yaw;
        bool _drag, _clamped;
        double _h0, _n0;                         // (at the click: a click without a move changes nothing)
        const double Below = 10;                 // degrees under the horizon on the dome (twilight, night)

        public event Action<double, double>? Moving;      // hour, north (while dragging)
        public event Action<double, double>? Moved;       // hour, north (let go)

        public SunDome(double hour, double north, double day, double lat, double viewYaw)
        {
            _hour = hour; _north = north; _day = day; _lat = lat; _yaw = viewYaw;
            Height = 196;
            Cursor = Cursors.Hand;
            Margin = new Thickness(0, 2, 0, 10);
            Focusable = false;
            UpdateTip();
        }

        /// <summary>The view turned: the dome turns with it.</summary>
        public void SetViewYaw(double yaw) { _yaw = yaw; InvalidateVisual(); }

        /// <summary>Hour or north changed from their sliders.</summary>
        public void SetSun(double hour, double north) { if (_drag) return; _hour = hour; _north = north; UpdateTip(); InvalidateVisual(); }

        (Point c, double R) Geo()
        {
            double R = Math.Max(20, Math.Min(ActualWidth, ActualHeight) / 2 - 3);
            return (new Point(ActualWidth / 2, ActualHeight / 2), R);
        }

        double RadiusOf(double el, double R) => (90 - Math.Clamp(el, -Below, 90)) / (90 + Below) * R;

        Point ScreenOf(double az, double el)
        {
            var (c, R) = Geo();
            double a = (az - _yaw) * Math.PI / 180, rr = RadiusOf(el, R);
            return new Point(c.X + rr * Math.Sin(a), c.Y - rr * Math.Cos(a));
        }

        void UpdateTip()
        {
            var (_, el) = Direction(_hour, _north, _day, _lat);
            ToolTip = L.T("Trascina il sole dove lo vuoi: in alto è davanti alla camera, in basso dietro, al centro sopra la testa; il cerchio è l'orizzonte. Ora e Nord seguono (giorno e latitudine restano)")
                      + "\n" + L.F("Il sole sale al massimo a {0}° in questo giorno e a questa latitudine", Math.Max(-90, MaxElev(_day, _lat)).ToString("0"))
                      + (_clamped ? "\n" + L.T("Più in alto (o più in basso) non arriva: per un sole più alto cambia Giorno dell'anno o Latitudine nelle Avanzate") : "")
                      + "\n" + L.F("Altezza attuale: {0}°", el.ToString("0"));
        }

        protected override void OnRender(DrawingContext dc)
        {
            var (c, R) = Geo();
            var warm = Theme.Warm;
            // ground band (under the horizon) and the sky
            dc.DrawEllipse(Theme.B("#0B1424"), new Pen(Theme.B(Theme.Line), 1), c, R, R);
            double rh = RadiusOf(0, R);
            var sky = new RadialGradientBrush(Color.FromRgb(0x2C, 0x4A, 0x7A), Color.FromRgb(0x14, 0x24, 0x42));
            sky.Freeze();
            dc.DrawEllipse(sky, null, c, rh, rh);
            // what the sun cannot reach this day: higher than its noon, lower than its midnight
            var dim = Theme.B(Color.FromArgb(0x99, 0x07, 0x0D, 0x18));
            double maxE = MaxElev(_day, _lat), minE = MinElev(_day, _lat);
            if (maxE < 90 - 0.5)
            {
                var rm = RadiusOf(maxE, R);
                if (maxE > -Below) dc.DrawEllipse(dim, null, c, rm, rm); else dc.DrawEllipse(dim, null, c, R, R);
            }
            if (minE > -Below + 0.5)
            {
                var rn = RadiusOf(minE, R);
                var g = new GeometryGroup { FillRule = FillRule.EvenOdd };
                g.Children.Add(new EllipseGeometry(c, R, R));
                g.Children.Add(new EllipseGeometry(c, rn, rn));
                dc.DrawGeometry(dim, null, g);
            }
            // heights 30° and 60°, the horizon
            var faint = new Pen(Theme.B(Color.FromArgb(0x55, 0x9D, 0xAA, 0xC2)), 1) { DashStyle = new DashStyle(new double[] { 2, 3 }, 0) };
            foreach (var e in new[] { 30.0, 60.0 }) { var re = RadiusOf(e, R); dc.DrawEllipse(null, faint, c, re, re); }
            dc.DrawEllipse(null, new Pen(Theme.B(Theme.TextFaint), 1.2), c, rh, rh);
            // the camera: at the bottom, looking up into the dome
            var cam = new StreamGeometry();
            using (var g = cam.Open())
            {
                var p0 = new Point(c.X, c.Y + rh - 13);
                g.BeginFigure(new Point(c.X - 6, c.Y + rh - 3), true, true);
                g.LineTo(new Point(c.X + 6, c.Y + rh - 3), true, false);
                g.LineTo(p0, true, false);
            }
            cam.Freeze();
            dc.DrawGeometry(Theme.B(Theme.TextMuted), null, cam);
            // north on the horizon band
            {
                double a = (_north - _yaw) * Math.PI / 180, rr = (rh + R) / 2;
                var p = new Point(c.X + rr * Math.Sin(a), c.Y - rr * Math.Cos(a));
                var ft = new FormattedText("N", CultureInfo.CurrentUICulture, FlowDirection.LeftToRight, new Typeface("Segoe UI Semibold"), 9.5, Theme.B(Theme.AxisX), VisualTreeHelper.GetDpi(this).PixelsPerDip);
                dc.DrawText(ft, new Point(p.X - ft.Width / 2, p.Y - ft.Height / 2));
            }
            // the sun, its line from the middle (where it shines from)
            var (az, el) = Direction(_hour, _north, _day, _lat);
            var s = ScreenOf(az, el);
            var up = el >= 0;
            var sunC = up ? warm : Color.FromRgb(0x9D, 0x86, 0x5A);
            dc.DrawLine(new Pen(Theme.B(Color.FromArgb(0xCC, sunC.R, sunC.G, sunC.B)), 1.4), c, s);
            dc.DrawEllipse(Theme.B(Color.FromArgb(0x40, sunC.R, sunC.G, sunC.B)), null, s, 12, 12);
            dc.DrawEllipse(Theme.B(sunC), new Pen(Theme.B("#0A1222"), 1.5), s, 7, 7);
            if (_drag)
            {
                var ft = new FormattedText(el.ToString("0") + "°", CultureInfo.CurrentUICulture, FlowDirection.LeftToRight, new Typeface("Segoe UI Semibold"), 11, Theme.B(Theme.Text), VisualTreeHelper.GetDpi(this).PixelsPerDip);
                var tp = new Point(s.X + 12, s.Y - ft.Height - 4);
                if (tp.X + ft.Width > ActualWidth) tp.X = s.X - 12 - ft.Width;
                if (tp.Y < 0) tp.Y = s.Y + 8;
                dc.DrawRoundedRectangle(Theme.B(Color.FromArgb(0xE6, 0x0A, 0x12, 0x22)), null, new Rect(tp.X - 4, tp.Y - 1, ft.Width + 8, ft.Height + 2), 3, 3);
                dc.DrawText(ft, tp);
            }
        }

        void MoveTo(Point p)
        {
            var (c, R) = Geo();
            double dx = p.X - c.X, dy = p.Y - c.Y, rr = Math.Sqrt(dx * dx + dy * dy);
            double el = 90 - Math.Min(rr, R) / R * (90 + Below);
            double az = Wrap(Math.Atan2(dx, -dy) * 180 / Math.PI + _yaw);
            if (rr < 1) az = Direction(_hour, _north, _day, _lat).az;     // (straight up: keep the direction)
            var (hour, north, clamped) = Solve(az, el, _day, _lat, _north);
            _hour = hour; _north = Math.Round(north, 1); _clamped = clamped;
            InvalidateVisual();
            Moving?.Invoke(_hour, _north);
        }

        protected override void OnMouseLeftButtonDown(MouseButtonEventArgs e)
        {
            var (c, R) = Geo();
            var p = e.GetPosition(this);
            if ((p - c).Length > R + 4) return;
            _drag = true;
            _h0 = _hour; _n0 = _north;
            CaptureMouse();
            MoveTo(p);
            e.Handled = true;
        }

        protected override void OnMouseMove(MouseEventArgs e)
        {
            if (_drag) MoveTo(e.GetPosition(this));
        }

        protected override void OnMouseLeftButtonUp(MouseButtonEventArgs e)
        {
            if (!_drag) return;
            _drag = false;
            ReleaseMouseCapture();
            UpdateTip();
            InvalidateVisual();
            if (Math.Abs(_hour - _h0) > 1e-6 || Math.Abs(_north - _n0) > 1e-6) Moved?.Invoke(_hour, _north);
            e.Handled = true;
        }

        protected override void OnLostMouseCapture(MouseEventArgs e)
        {
            if (_drag) { _drag = false; InvalidateVisual(); Moved?.Invoke(_hour, _north); }
        }

        protected override HitTestResult HitTestCore(PointHitTestParameters p) => new PointHitTestResult(this, p.HitPoint);
    }
}
