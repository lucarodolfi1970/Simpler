using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;

namespace Simpler
{
    /// <summary>
    /// Height of the bottom library in whole rows of tiles (1, 2 or 3): dragging its top edge clicks from one row count
    /// to the next, so a row is never cut in half. Double click on the edge: next row count.
    /// </summary>
    public sealed partial class MainWindow
    {
        const double TileRow = 138;          // tile height 130 + margin 4 + 4
        const int MaxLibraryRows = 3;
        Grid? _center;
        int _libraryRows = 1;

        void SetLibraryRows(int rows, bool save = true)
        {
            rows = Math.Clamp(rows, 1, MaxLibraryRows);
            // keep at least 200 px of 3D view on small screens
            if (_center != null && _center.ActualHeight > 0)
                while (rows > 1 && _center.ActualHeight - (rows * TileRow + 128) < 200) rows--;   // (+38: the row of the folder path)
            _libraryRows = rows;
            _libraryTiles.Height = rows * TileRow;
            if (!save) return;
            var s = Settings.Load();
            s.LibraryRows = rows;
            s.Save();
        }

        FrameworkElement LibraryResizer()
        {
            var bar = new Border
            {
                Height = 6, Background = Theme.B(Theme.Line), Cursor = Cursors.SizeNS,
                ToolTip = L.T("Trascina in alto o in basso: la libreria passa a 1, 2 o 3 righe · doppio clic: riga successiva"),
            };
            double startY = 0;
            int startRows = 1;
            bool dragging = false;
            bar.MouseEnter += (_, __) => bar.Background = Theme.B(Theme.Accent);
            bar.MouseLeave += (_, __) => { if (!dragging) bar.Background = Theme.B(Theme.Line); };
            bar.MouseLeftButtonDown += (_, e) =>
            {
                if (e.ClickCount == 2)
                {
                    SetLibraryRows(_libraryRows % MaxLibraryRows + 1);
                    e.Handled = true;
                    return;
                }
                dragging = true;
                startY = e.GetPosition(this).Y;
                startRows = _libraryRows;
                bar.CaptureMouse();
                e.Handled = true;
            };
            bar.MouseMove += (_, e) =>
            {
                if (!dragging) return;
                // up = more rows; the next row clicks in after a third of its height
                var dy = startY - e.GetPosition(this).Y;
                var rows = startRows + (int)Math.Round(dy / TileRow + (dy > 0 ? 0.17 : -0.17));
                rows = Math.Clamp(rows, 1, MaxLibraryRows);
                if (rows != _libraryRows) SetLibraryRows(rows, save: false);
            };
            bar.MouseLeftButtonUp += (_, __) =>
            {
                if (!dragging) return;
                dragging = false;
                bar.ReleaseMouseCapture();
                bar.Background = Theme.B(bar.IsMouseOver ? Theme.Accent : Theme.Line);
                SetLibraryRows(_libraryRows);      // saved
            };
            bar.LostMouseCapture += (_, __) => { if (dragging) { dragging = false; bar.Background = Theme.B(Theme.Line); } };
            return bar;
        }
    }
}
