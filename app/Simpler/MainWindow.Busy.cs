using System;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Input;
using System.Windows.Threading;
using Microsoft.Web.WebView2.Core;

namespace Simpler
{
    /// <summary>
    /// Long operations lock the commands that cannot run meanwhile (header, scene tree, library, properties and
    /// editing in the view). Esc stops an export of the view and goes back to the state before.
    /// </summary>
    public sealed partial class MainWindow
    {
        int _busyCount;
        UIElement? _lockHeader, _lockLeft, _lockLib, _lockRight;
        DispatcherTimer? _lockFade;
        bool _recovering;
        DateTime _lastContextReload = DateTime.MinValue;

        bool IsBusy => _busyCount > 0;

        /// <summary>(1.78.4, Luca: «resta il cursore a clessidra anche se ha finito») busy for the hourglass: an open
        /// library window locks the app but is not work - the hourglass went on with the work done in it (the import)
        /// and stayed, because every place that takes it away waited for the lock to end too.</summary>
        bool CursorBusy => CursorLocked || _viewBusy || _working || _engineBusy;
        bool CursorLocked => IsBusy && !(_dialogLock != null && _busyCount == 1);

        /// <summary>(1.78.5, Luca: «molte situazioni in cui si può lavorare anche mentre simpler calcola») two busy
        /// cursors: the full hourglass only when the panels are really locked (a long operation that nothing can run
        /// beside); the arrow with the hourglass when Simpler computes in the background (the engine busy, the view
        /// preparing, a command waiting) and the user can still change panel, look around, read the settings. The
        /// full hourglass there said «stai fermo» when there was no need. Other cursors (a drag) are left alone.</summary>
        void UpdateBusyCursor()
        {
            var cur = Mouse.OverrideCursor;
            if (cur != null && cur != Cursors.Wait && cur != Cursors.AppStarting) return;
            // (the lock dims the panels after 0.35 s: the full hourglass with it, not before - quick commands no flicker)
            var want = CursorLocked && _lockShown ? Cursors.Wait : CursorBusy ? Cursors.AppStarting : null;
            if (cur != want) Mouse.OverrideCursor = want;
        }
        void ReleaseBusyCursor() => UpdateBusyCursor();
        bool _lockShown;
        bool _engineBusy;                  // the view shows «Occupato · attendi» (see busyTick in viewer.js)

        IDisposable BeginBusy()
        {
            if (_busyCount++ == 0) SetLocked(true);
            return new BusyToken(this);
        }

        sealed class BusyToken : IDisposable
        {
            readonly MainWindow _w;
            bool _done;
            public BusyToken(MainWindow w) => _w = w;
            public void Dispose()
            {
                if (_done) return;
                _done = true;
                if (--_w._busyCount <= 0) { _w._busyCount = 0; _w.SetLocked(false); }
            }
        }

        void SetLocked(bool on)
        {
            foreach (var e in new[] { _lockHeader, _lockLeft, _lockLib, _lockRight })
                if (e != null) e.IsEnabled = !on;
            // (a library window open is not work: the view is locked but shows no «Occupato · attendi», and no
            // hourglass - it would show on that window too, which is waiting for clicks)
            SendToWeb(new { type = "lock", on, window = on && _lockingForWindow });
            // dim the panels only if it lasts: quick commands must not flicker
            _lockFade?.Stop();
            if (on)
            {
                _lockFade = new DispatcherTimer(TimeSpan.FromMilliseconds(350), DispatcherPriority.Background, (_, __) =>
                {
                    _lockFade?.Stop();
                    if (!IsBusy) return;
                    foreach (var e in new[] { _lockHeader, _lockLeft, _lockLib, _lockRight }) if (e != null) e.Opacity = 0.55;
                    // (locked only by an open library window: no busy cursor, it would show on that window too)
                    _lockShown = true;
                    UpdateBusyCursor();
                }, Dispatcher);
                _lockFade.Start();
            }
            else
            {
                foreach (var e in new[] { _lockHeader, _lockLeft, _lockLib, _lockRight }) if (e != null) e.Opacity = 1;
                _lockShown = false;
                ReleaseBusyCursor();
            }
        }

        /// <summary>Keys while busy: only Esc (stop the export of the view). True when the key was handled.</summary>
        bool BusyKey(bool escape)
        {
            if (!IsBusy) return false;
            if (escape)
            {
                if (_reloading) _ = CancelReload();
                else if (SkipTerrainTexWait()) { }
                else Status(L.T("Questa operazione non si può interrompere: attendi la fine"));
            }
            return true;
        }

        /// <summary>The web view process crashed (usually out of memory on huge scenes): restart it and show the last view again.</summary>
        void OnViewerFailed(CoreWebView2ProcessFailedKind kind)
        {
            AppLog.Write("viewer process failed: " + kind + (_reloading ? " (while preparing the view)" : ""));
            if (kind == CoreWebView2ProcessFailedKind.RenderProcessUnresponsive)
            {
                // only busy (e.g. loading a big scene while the computer is under load): it usually recovers by
                // itself. Reloading here would throw away the view being loaded and prepare it all over again.
                return;
            }
            if (kind == CoreWebView2ProcessFailedKind.RenderProcessExited || kind == CoreWebView2ProcessFailedKind.FrameRenderProcessExited)
            {
                Status(L.T("Il visualizzatore 3D si è chiuso (memoria esaurita?): lo riavvio…"), true);
                _webReady = false;
                _recovering = true;
                try { _web.CoreWebView2?.Reload(); } catch { }
                return;
            }
            Status(L.T("Il visualizzatore 3D si è chiuso inaspettatamente: ") + kind, true);
        }
    }
}
