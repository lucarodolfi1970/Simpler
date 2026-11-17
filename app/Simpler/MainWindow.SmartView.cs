using System;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace Simpler
{
    /// <summary>(1.75.9) «SmartView»: an orange button in the toolbar for setting up a scene without waiting. On, the
    /// engine computes nothing of the view by itself (coast of the sea, shelter from the rain, snow mantle, flakes and
    /// drops, path tracing passes) and the real-time shadows are off; inserting models, moving them, moving the view
    /// and editing materials still work. What is not computed again simply stays as it was. Off: the shadows come
    /// back and what changed meanwhile is made once. Kept from one time to the next.</summary>
    public sealed partial class MainWindow
    {
        Button? _smartButton;

        void BuildSmartButton(DockPanel bar)
        {
            {
                // (1.75.9 first build) SmartView put the shadow level to «off»: back to the one it had
                var st = Settings.Load();
                if (st.SmartPrevShadows != "")
                {
                    if (st.ViewerShadows == "off") st.ViewerShadows = st.SmartPrevShadows;
                    st.SmartPrevShadows = "";
                    st.Save();
                }
            }
            _smartButton = Theme.Button(Theme.IconText(Icons.SmartEye, "SmartView", AdvancedColor, 17), Theme.Kind.Ghost, null);
            _smartButton.VerticalAlignment = VerticalAlignment.Center;
            _smartButton.Padding = new Thickness(10, 0, 10, 0);
            _smartButton.Margin = new Thickness(6, 0, 0, 0);
            _smartButton.Click += async (_, __) => await SetSmartView(!Settings.Load().SmartView);
            DockPanel.SetDock(_smartButton, Dock.Right);
            bar.Children.Add(_smartButton);
            SmartFace();
        }

        void SmartFace()
        {
            if (_smartButton == null) return;
            var on = Settings.Load().SmartView;
            Theme.Style(_smartButton, on ? Theme.Kind.Segment : Theme.Kind.Ghost);
            _smartButton.Padding = new Thickness(10, 0, 10, 0);
            _smartButton.BorderThickness = new Thickness(on ? 1 : 0);
            _smartButton.BorderBrush = Theme.B(AdvancedColor);
            _smartButton.Foreground = Theme.B(on ? AdvancedColor : Theme.TextMuted);
            _smartButton.ToolTip = on
                ? L.T("SmartView attivo: la vista non si ricalcola da sola. Clic per tornare alla vista completa (ombre e ricalcoli)")
                : L.T("SmartView: imposti la scena senza attese. Inserire, spostare e cambiare materiali funziona; ombre spente; pioggia, neve, costa e path tracing non si ricalcolano");
        }

        async Task PushSmartToEngine()
        {
            if (_api == null) return;
            try { await _api.Post("smartview", new { on = Settings.Load().SmartView }); }
            catch (Exception ex) { AppLog.Write("smartview: " + ex.Message); }
        }

        async Task SetSmartView(bool on)
        {
            var s = Settings.Load();
            if (s.SmartView == on) { SmartFace(); return; }
            s.SmartView = on;
            s.Save();
            AppLog.Write("smartview " + (on ? "on" : "off"));
            // (the shadows: the view fades them and stops drawing their maps by itself - the shadow level is not
            // touched, changing it made every shader of the scene again)
            SendToWeb(new { type = "smartView", on });
            if (on && _realistic) await SetRealistic(false);     // (the path tracing is a computation of the engine)
            await PushSmartToEngine();
            SmartFace();
            UpdateQualityDrop();
            RenderLightenBox();
            Status(on ? L.T("SmartView attivo: la vista non si ricalcola da sola")
                      : L.T("SmartView spento: ombre e ricalcoli tornano"));
        }
    }
}
