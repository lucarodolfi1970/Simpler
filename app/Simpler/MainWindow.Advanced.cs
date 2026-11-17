using System;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;

namespace Simpler
{
    /// <summary>"Avanzate": the less used settings of a card, in a box (1.76.25: a bar with «Avanzate» in blue; 1.76.28: azure, not yellow) closed by default, right under the main
    /// controls. Its open/closed state is kept while the scene is open (see ResetPanelState); when closed, an orange dot says that something inside is not at
    /// its default value.</summary>
    public sealed partial class MainWindow
    {
        static readonly Color AdvancedColor = Theme.C("#F08A24");
        // (1.76.25, Luca) the box of «Avanzate» in the colours of the logo: a yellow bar as wide as the panel with
        // «Avanzate» in blue (a deeper blue than the buttons': the light one could not be read on the yellow); inside
        // a list (one per stone, one per model of the brush) the same bar, light: yellow edge, a hint of yellow
        // (1.76.28, Luca: il giallo faceva troppo contrasto) azzurro; (1.76.29, Luca: troppo simile ai pulsanti
        // principali) un blu medio, più scuro dei pulsanti e più chiaro del pannello, con la scritta azzurra quasi
        // bianca: i pulsanti sono chiari con la scritta scura, «Avanzate» il contrario. Negli elenchi la barra
        // sottile con la scritta azzurra chiara
        static readonly Color AdvBar = Theme.C("#24467A");
        static readonly Color AdvBlue = Theme.C("#CFE3FF");
        static readonly Color AdvLight = Theme.C("#9CC8FF");

        sealed class AdvancedBox
        {
            public StackPanel Body = null!;
            public FrameworkElement Root = null!;
            public Ellipse Dot = null!;
            public Panel Parent = null!;
            public StackPanel Footer = null!;
            public Func<bool> IsOpen = null!;

            /// <summary>Call after filling the body: removes the box when empty, shows the dot when something differs
            /// from the default, adds "Valori predefiniti" when a reset is given and something differs.</summary>
            public void Done(bool changed, Func<Task>? reset = null)
            {
                if (Body.Children.Count == 0) { Parent.Children.Remove(Root); return; }
                Dot.Tag = changed;
                Dot.Visibility = changed && !IsOpen() ? Visibility.Visible : Visibility.Collapsed;
                if (changed && reset != null)
                {
                    var b = Theme.Button(L.T("Valori predefiniti"), Theme.Kind.Ghost, L.T("Rimette le impostazioni avanzate di questa sezione ai valori predefiniti"));
                    b.MinHeight = 26; b.FontSize = 12; b.Padding = new Thickness(8, 0, 8, 0);
                    b.HorizontalAlignment = HorizontalAlignment.Left;
                    b.Foreground = new SolidColorBrush(AdvLight);
                    b.Click += async (_, __) => await reset();
                    Footer.Children.Add(b);
                }
            }
        }

        /// <summary>Adds an "Avanzate" box at the end of <paramref name="parent"/> (so: under what is already there).</summary>
        AdvancedBox Advanced(Panel parent, string key)
        {
            var fullKey = (_rightPanel == "" ? "props" : _rightPanel) + ":" + key;
            bool open = _openAdvanced.Contains(fullKey);
            var orange = new SolidColorBrush(AdvancedColor);

            bool light = key.Contains("Item:");
            var root = new StackPanel { Margin = new Thickness(0, 6, 0, 4) };
            var textColor = light ? AdvLight : AdvBlue;
            var chevron = Theme.Icon(ChevronDown, textColor, 13, 2.2);
            chevron.RenderTransformOrigin = new Point(0.5, 0.5);
            chevron.VerticalAlignment = VerticalAlignment.Center;
            var line = new DockPanel { LastChildFill = false };
            var left = new StackPanel { Orientation = Orientation.Horizontal };
            left.Children.Add(chevron);
            var title = Theme.Label(L.T("Avanzate"), 12, textColor);
            title.FontWeight = FontWeights.Bold;
            title.Margin = new Thickness(6, 0, 0, 0);
            title.VerticalAlignment = VerticalAlignment.Center;
            left.Children.Add(title);
            line.Children.Add(left);
            var dot = new Ellipse { Width = 8, Height = 8, Fill = new SolidColorBrush(light ? AdvLight : AdvBlue), Margin = new Thickness(0, 0, 4, 0), VerticalAlignment = VerticalAlignment.Center, Visibility = Visibility.Collapsed };
            dot.ToolTip = L.T("Qualche impostazione avanzata non è al valore predefinito");
            DockPanel.SetDock(dot, Dock.Right);
            line.Children.Add(dot);
            var header = new Border
            {
                Child = line,
                CornerRadius = new CornerRadius(6),
                Padding = light ? new Thickness(8, 3, 8, 3) : new Thickness(10, 6, 10, 6),
                Background = light ? new SolidColorBrush(Color.FromArgb(0x70, AdvBar.R, AdvBar.G, AdvBar.B)) : new SolidColorBrush(AdvBar),
                BorderBrush = new SolidColorBrush(AdvBar),
                BorderThickness = new Thickness(light ? 1 : 0),
                Cursor = Cursors.Hand,
                HorizontalAlignment = HorizontalAlignment.Stretch,
            };
            header.ToolTip = L.T("Impostazioni meno usate: clic per aprire o chiudere");
            root.Children.Add(header);

            var body = new StackPanel();
            var footer = new StackPanel();
            var inner = new StackPanel();
            inner.Children.Add(body);
            inner.Children.Add(footer);
            var frame = new Border
            {
                BorderBrush = new SolidColorBrush(Color.FromArgb(0x70, AdvLight.R, AdvLight.G, AdvLight.B)),
                BorderThickness = new Thickness(2, 0, 0, 0),
                Padding = new Thickness(10, 8, 0, 2),
                Margin = new Thickness(5, 6, 0, 4),
                Child = inner,
            };
            root.Children.Add(frame);

            var box = new AdvancedBox { Body = body, Root = root, Dot = dot, Parent = parent, Footer = footer, IsOpen = () => open };
            root.Tag = body;          // (1.76.32: the favourites walk into an Avanzate through its body)
            void Apply()
            {
                frame.Visibility = open ? Visibility.Visible : Visibility.Collapsed;
                chevron.RenderTransform = new RotateTransform(open ? 0 : -90);
                dot.Visibility = !open && dot.Tag is true ? Visibility.Visible : Visibility.Collapsed;
            }
            Apply();
            header.MouseLeftButtonUp += (_, e) =>
            {
                open = !open;
                if (open) _openAdvanced.Add(fullKey); else _openAdvanced.Remove(fullKey);
                Apply();
                e.Handled = true;
            };
            parent.Children.Add(root);
            return box;
        }

        static bool Diff(double a, double b) => Math.Abs(a - b) > 1e-6 * Math.Max(1, Math.Abs(b));
    }
}
