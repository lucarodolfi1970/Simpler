using System;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Shapes;
using System.Windows.Threading;

namespace Simpler
{
    /// <summary>(1.75.15) While the final render runs, the logo of the busy screen is an eye that looks around: the
    /// yellow dot (the pupil) glances left or right now and then, holds, comes back, sometimes looks twice, a little up
    /// or down, and blinks once in a while. Never the same loop: every pause and every glance is chosen at random.</summary>
    public sealed partial class MainWindow
    {
        Ellipse? _eyePupil;
        readonly TranslateTransform _eyeMove = new TranslateTransform();
        readonly ScaleTransform _eyeBlink = new ScaleTransform(1, 1);
        DispatcherTimer? _eyeTimer;
        readonly Random _eyeRnd = new Random();
        const double EyeReach = 11.0;          // pixels the pupil can travel from the centre (ring 54, pupil 20)

        void EyeStart(bool on)
        {
            EyeStop();
            if (!on || _eyePupil == null) return;
            _eyeTimer = new DispatcherTimer(DispatcherPriority.Background, Dispatcher);
            _eyeTimer.Tick += (_, __) => EyeNext();
            EyeWait(1.2, 2.5);
        }

        void EyeStop()
        {
            _eyeTimer?.Stop();
            _eyeTimer = null;
            EyeTo(0, 0, 0.25);
            _eyeBlink.BeginAnimation(ScaleTransform.ScaleYProperty, null);
            _eyeBlink.ScaleY = 1;
        }

        void EyeWait(double min, double max)
        {
            if (_eyeTimer == null) return;
            _eyeTimer.Stop();
            _eyeTimer.Interval = TimeSpan.FromSeconds(min + _eyeRnd.NextDouble() * (max - min));
            _eyeTimer.Start();
        }

        void EyeTo(double x, double y, double secs)
        {
            var ease = new CubicEase { EasingMode = EasingMode.EaseInOut };
            var d = new Duration(TimeSpan.FromSeconds(secs));
            _eyeMove.BeginAnimation(TranslateTransform.XProperty, new DoubleAnimation(x, d) { EasingFunction = ease });
            _eyeMove.BeginAnimation(TranslateTransform.YProperty, new DoubleAnimation(y, d) { EasingFunction = ease });
        }

        void EyeBlink()
        {
            var a = new DoubleAnimationUsingKeyFrames { Duration = TimeSpan.FromMilliseconds(190) };
            a.KeyFrames.Add(new EasingDoubleKeyFrame(0.08, KeyTime.FromTimeSpan(TimeSpan.FromMilliseconds(80))));
            a.KeyFrames.Add(new EasingDoubleKeyFrame(1.0, KeyTime.FromTimeSpan(TimeSpan.FromMilliseconds(190))));
            _eyeBlink.BeginAnimation(ScaleTransform.ScaleYProperty, a);
        }

        int _eyeStep;            // 0 = looking ahead; >0 = the steps left of a glance
        double _eyeSide = 1;

        void EyeNext()
        {
            if (_eyeTimer == null) return;
            var r = _eyeRnd.NextDouble();
            if (_eyeStep > 0)
            {
                _eyeStep--;
                if (_eyeStep == 1 && _eyeRnd.NextDouble() < 0.35)
                {
                    // a second look, to the other side (as if something moved there)
                    _eyeSide = -_eyeSide;
                    EyeTo(_eyeSide * EyeReach, (_eyeRnd.NextDouble() - 0.5) * 4, 0.32);
                    EyeWait(0.6, 1.4);
                    return;
                }
                EyeTo(0, 0, 0.35 + _eyeRnd.NextDouble() * 0.2);        // back to the centre
                _eyeStep = 0;
                if (_eyeRnd.NextDouble() < 0.25) EyeBlink();
                EyeWait(1.8, 5.0);
                return;
            }
            if (r < 0.12)
            {
                EyeBlink();                                             // only a blink
                EyeWait(1.5, 3.5);
                return;
            }
            if (r < 0.24)
            {
                // a little up or down, slowly (thinking)
                EyeTo((_eyeRnd.NextDouble() - 0.5) * 6, (_eyeRnd.NextDouble() < 0.5 ? -1 : 1) * EyeReach * 0.6, 0.5);
                _eyeStep = 1;
                EyeWait(1.0, 2.2);
                return;
            }
            // a glance to one side: quick out, a pause, then back (sometimes via the other side)
            _eyeSide = _eyeRnd.NextDouble() < 0.5 ? -1 : 1;
            EyeTo(_eyeSide * EyeReach * (0.75 + _eyeRnd.NextDouble() * 0.25), (_eyeRnd.NextDouble() - 0.5) * 3, 0.22 + _eyeRnd.NextDouble() * 0.12);
            _eyeStep = 2;
            EyeWait(0.7, 1.9);
        }
    }
}
