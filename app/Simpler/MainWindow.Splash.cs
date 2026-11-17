using System.Threading.Tasks;
using System.Windows;

namespace Simpler
{
    /// <summary>Start-up: everything is prepared behind the splash screen, then the app appears maximized.</summary>
    public sealed partial class MainWindow
    {
        SplashWindow? _splash;
        readonly TaskCompletionSource<bool> _firstLoad = new(TaskCreationOptions.RunContinuationsAsynchronously);

        void SplashStatus(string text, double? fraction = null) => _splash?.SetStatus(text, fraction);

        /// <summary>Shows the main window maximized and closes the splash screen (once).</summary>
        void RevealMain()
        {
            if (_splash == null) return;
            var splash = _splash;
            _splash = null;
            var area = SystemParameters.WorkArea;
            WindowState = WindowState.Normal;
            Left = area.Left + (area.Width - Width) / 2;
            Top = area.Top + (area.Height - Height) / 2;
            ShowInTaskbar = true;
            WindowState = WindowState.Maximized;
            Activate();
            splash.FadeOutAndClose();
        }
    }
}
