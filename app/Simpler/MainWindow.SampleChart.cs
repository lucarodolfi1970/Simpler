using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Shapes;

namespace Simpler
{
    /// <summary>(1.75.20) While the final render runs, the bottom of the busy screen draws the samples over time: an
    /// area a little lighter than the background, its height the samples reached (0 to the samples of the render), the
    /// whole width the time gone so far. Once a second a new point; the seconds already passed keep the height they
    /// reached and only squeeze to the left, so the shape of the area shows how fast each part of the render went
    /// (loading at the start stays flat, adaptive sampling makes the curve steeper near the end).</summary>
    public sealed partial class MainWindow
    {
        const double ChartHeight = 170;
        Grid _chart = null!;
        // (1.75.21) when the samples reach the end the area turns yellow: the logo's pupil, a little darker
        static readonly Color ChartFill = Theme.C("#111A2C"), ChartLine = Theme.C("#1A2842"),
                              ChartDoneFill = Theme.C("#B8862F"), ChartDoneLine = Theme.Warm;
        readonly SolidColorBrush _chartFillBrush = new SolidColorBrush(ChartFill), _chartLineBrush = new SolidColorBrush(ChartLine);
        readonly Path _chartArea = new Path();
        readonly Polyline _chartEdge = new Polyline { StrokeThickness = 1 };
        bool _chartDone;
        readonly List<int> _chartPts = new List<int>();     // the samples at the end of each second
        int _chartSamples, _chartTotal;
        bool _chartOn;

        UIElement BuildSampleChart()
        {
            _chart = new Grid { Height = ChartHeight, VerticalAlignment = VerticalAlignment.Bottom, ClipToBounds = true,
                                IsHitTestVisible = false, Visibility = Visibility.Collapsed };
            _chartArea.Fill = _chartFillBrush;
            _chartEdge.Stroke = _chartLineBrush;
            _chart.Children.Add(_chartArea);
            _chart.Children.Add(_chartEdge);
            // (1.75.22) a very thin yellow line at the height of the last sample: where the area has to arrive
            _chart.Children.Add(new Rectangle { Height = 1, VerticalAlignment = VerticalAlignment.Top, SnapsToDevicePixels = true,
                                                Fill = new SolidColorBrush(ChartDoneFill) });
            _chart.SizeChanged += (_, __) => ChartDraw();
            return _chart;
        }

        void ChartStart(bool on)
        {
            _chartOn = on;
            _chartPts.Clear();
            _chartSamples = _chartTotal = 0;
            ChartColour(false);
            _chartArea.Data = null;
            _chartEdge.Points = new PointCollection();
            _chart.Visibility = on ? Visibility.Visible : Visibility.Collapsed;
        }

        /// <summary>The latest samples from the engine (every poll of the progress).
        /// <paramref name="end"/>: the engine is past the samples (denoiser, saving), even if the last line it read
        /// was a little below the total.</summary>
        void ChartFeed(int samples, int total, bool end)
        {
            if (!_chartOn) return;
            if (total > 0) _chartTotal = total;
            if (end && _chartTotal > 0) samples = _chartTotal;
            if (samples > _chartSamples) _chartSamples = samples;
            if (!_chartDone && _chartTotal > 0 && _chartSamples >= _chartTotal)
            {
                if (_chartPts.Count > 0) _chartPts[^1] = _chartSamples;      // (the last second up to the top now)
                ChartDraw();
                ChartColour(true);
            }
        }

        void ChartColour(bool done)
        {
            _chartDone = done;
            var d = new Duration(TimeSpan.FromSeconds(done ? 0.6 : 0));
            _chartFillBrush.BeginAnimation(SolidColorBrush.ColorProperty, done ? new ColorAnimation(ChartDoneFill, d) : null);
            _chartLineBrush.BeginAnimation(SolidColorBrush.ColorProperty, done ? new ColorAnimation(ChartDoneLine, d) : null);
            if (!done) { _chartFillBrush.Color = ChartFill; _chartLineBrush.Color = ChartLine; }
        }

        /// <summary>From the busy timer: a new point at every whole second gone.</summary>
        void ChartTick(double secs)
        {
            if (!_chartOn) return;
            var whole = (int)Math.Floor(secs);
            if (whole <= _chartPts.Count) return;
            while (_chartPts.Count < whole) _chartPts.Add(_chartSamples);
            ChartDraw();
        }

        void ChartDraw()
        {
            var w = _chart.ActualWidth;
            var h = _chart.ActualHeight;
            var n = _chartPts.Count;
            if (!_chartOn || n == 0 || w <= 0 || h <= 0) return;
            var total = Math.Max(1, _chartTotal);
            Point P(int k, int s) => new Point(w * k / n, h - (h - 1) * Math.Min(1.0, s / (double)total));
            var edge = new PointCollection(n + 1) { P(0, 0) };
            for (var k = 1; k <= n; k++) edge.Add(P(k, _chartPts[k - 1]));
            var fig = new PathFigure { StartPoint = new Point(0, h), IsClosed = true, IsFilled = true };
            foreach (var p in edge) fig.Segments.Add(new LineSegment(p, false));
            fig.Segments.Add(new LineSegment(new Point(w, h), false));
            var geo = new PathGeometry();
            geo.Figures.Add(fig);
            geo.Freeze();
            _chartArea.Data = geo;
            _chartEdge.Points = edge;
        }
    }
}
