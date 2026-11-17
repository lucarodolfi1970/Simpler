using System;
using System.Linq;
using System.Windows;
using System.Windows.Threading;

namespace Simpler
{
    public static class Program
    {
        [STAThread]
        public static void Main(string[] args)
        {
            L.Init(Settings.Load().Language);
            DiagService.Begin();          // (the marker of a run not closed well: the next start knows it was a crash)
            var app = new Application { ShutdownMode = ShutdownMode.OnMainWindowClose };
            app.DispatcherUnhandledException += OnUnhandled;
            ThemeMenus.Install(app);
            // (1.75.28) the license agreement at the first start (and when it changes): not accepted, no Simpler
            app.ShutdownMode = ShutdownMode.OnExplicitShutdown;
            if (!LicenseWindow.EnsureAccepted()) { DiagService.End(); return; }
            app.ShutdownMode = ShutdownMode.OnMainWindowClose;
            var splash = new SplashWindow();
            splash.Show();
            // video card check in the background (driver query, a few ms): it never delays the start-up
            System.Threading.Tasks.Task.Run(GpuRating.Detect).ContinueWith(t =>
            {
                if (t.Status == System.Threading.Tasks.TaskStatus.RanToCompletion)
                    splash.Dispatcher.BeginInvoke(() => { try { if (splash.IsVisible) splash.SetGpu(t.Result); } catch { } });
            });
            var window = new MainWindow(args.Length > 0 ? args[0] : null, splash);
            // the splash was the first window created, so WPF made it the main window: closing it would close
            // the whole app. The real main window is this one.
            app.MainWindow = window;
            app.Run(window);
        }

        static void OnUnhandled(object sender, DispatcherUnhandledExceptionEventArgs e)
        {
            AppLog.Write("unhandled exception: " + e.Exception.GetType().Name + ": " + e.Exception.Message);
            // (15/11) where it happened too: without it the log said only «Object reference not set…»
            try { AppLog.Write("   " + string.Join(" < ", (e.Exception.StackTrace ?? "").Split('\n').Select(l => l.Trim()).Where(l => l != "").Take(8))); } catch { }
            Msg.Show(L.T("Si è verificato un errore imprevisto:") + L.T("\n\n") + e.Exception.Message, "Simpler",
                MessageBoxButton.OK, MessageBoxImage.Error);
            e.Handled = true;
        }
    }
}
