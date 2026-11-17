using System;
using System.Windows;
using System.Windows.Threading;

namespace Simpler
{
    /// <summary>
    /// The library windows (Importa modelli nella libreria, Correggi materiali dei modelli, Statistiche e pulizia) are
    /// not modal - they keep working in the background when hidden - but while one is open, or is still working, the
    /// rest of Simpler is locked: panels, tree, library and view stop (as during any long operation), and a click or a
    /// key there says why and brings the window back.
    /// </summary>
    public sealed partial class MainWindow
    {
        IDisposable? _dialogLock;
        DispatcherTimer? _dialogLockTimer;
        bool _blockedShown;
        bool _lockingForWindow;

        /// <summary>The window that keeps Simpler locked now (visible, or hidden while it works), or null.</summary>
        Window? DialogBlocker()
        {
            if (_importWizard is { } iw && (iw.IsVisible || iw.Running)) return iw;
            if (_matFixWizard is { } mf && (mf.IsVisible || mf.Running)) return mf;
            if (_libStats is { IsVisible: true } ls) return ls;
            return null;
        }

        /// <summary>Called when one of those windows opens: locks now, then checks twice a second until none is left.</summary>
        void WatchDialogLock()
        {
            UpdateDialogLock();
            _dialogLockTimer ??= new DispatcherTimer(TimeSpan.FromMilliseconds(400), DispatcherPriority.Background, (_, __) => UpdateDialogLock(), Dispatcher);
            _dialogLockTimer.Start();
        }

        void UpdateDialogLock()
        {
            var on = DialogBlocker() != null;
            if (on && _dialogLock == null)
            {
                _lockingForWindow = _busyCount == 0;
                _dialogLock = BeginBusy();
                _lockingForWindow = false;
            }
            else if (!on && _dialogLock != null)
            {
                _dialogLock.Dispose();
                _dialogLock = null;
            }
            if (!on && _importWizard == null && _matFixWizard == null && _libStats == null) _dialogLockTimer?.Stop();
        }

        /// <summary>A click or a key on Simpler while a library window keeps it locked.</summary>
        void ShowBlocked()
        {
            if (_blockedShown) return;
            var w = DialogBlocker();
            if (w == null) return;
            _blockedShown = true;
            try
            {
                if (w.IsVisible)
                {
                    Msg.Show(this, L.F("È aperta la finestra «{0}»: finché è aperta il resto di Simpler è fermo.\n\nChiudila (o finisci il lavoro) per tornare alla scena.", w.Title),
                             "Simpler", MessageBoxButton.OK, MessageBoxImage.Information);
                    w.Activate();
                }
                else if (Msg.Show(this, L.F("«{0}» sta lavorando in background: Simpler è occupato finché non ha finito.\n\nVuoi vedere l'avanzamento?", w.Title),
                                  "Simpler", MessageBoxButton.YesNo, MessageBoxImage.Information) == MessageBoxResult.Yes)
                {
                    w.Show();
                    w.Activate();
                }
            }
            finally { _blockedShown = false; }
        }
    }
}
