using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;

namespace Simpler
{
    /// <summary>Final render options: size and quality. File format is chosen in the save dialog.</summary>
    public sealed class RenderDialog : ThemedDialog
    {
        protected override void OnCloseButton() => DialogResult = false;

        public int RenderWidth { get; private set; } = 3840;
        public int RenderHeight { get; private set; } = 2160;
        public string Quality { get; private set; }
        public int Textures { get; private set; } = -1;     // -1 auto, 0 original, else max side in pixels
        public int Samples { get; private set; }            // samples of this render (the quality's, or typed)

        static readonly (string label, int w, int h)[] Sizes =
        {
            (L.T("Full HD 1920×1080"), 1920, 1080),
            ("4K 3840×2160", 3840, 2160),
            (L.T("Quadrata 3000×3000"), 3000, 3000),
            (L.T("Verticale 2160×2700"), 2160, 2700),
            (L.T("Stampa A4 300 dpi 3508×2480"), 3508, 2480),
            (L.T("Prova 960×540"), 960, 540),          // a quick check of light and clouds before the big one
        };

        public RenderDialog(string quality, string format = "", double aspect = 0, double viewAspect = 16.0 / 9, int currentSamples = 512)
            : base(L.T("Render finale"), 460)
        {
            var sizeList = Sizes;
            if (aspect > 0)
            {
                // a frame format is set in the Camera panel: offer sizes with exactly those proportions
                (int, int) Fit(int longSide) => aspect >= 1 ? (longSide, (int)Math.Round(longSide / aspect)) : ((int)Math.Round(longSide * aspect), longSide);
                var list = new System.Collections.Generic.List<(string, int, int)>();
                foreach (var (tag, side) in new[] { ("Web", 1920), ("4K", 3840), (L.T("Stampa"), 6000), (L.T("Prova"), 960) })
                {
                    var (fw, fh) = Fit(side);
                    list.Add((L.F("Formato {0}: {1}×{2}", format, fw, fh) + " · " + tag, fw, fh));
                }
                sizeList = list.ToArray();
            }
            Quality = quality;

            var sp = new StackPanel { Margin = new Thickness(0, 0, 0, 2) };
            sp.Children.Add(Theme.Label(L.T("Render finale"), 18, Theme.Text, FontWeights.SemiBold));
            var intro = Theme.Label(L.T("Usa la stessa inquadratura della vista. Il formato del file lo scegli al salvataggio."), 12, Theme.TextFaint);
            intro.TextWrapping = TextWrapping.Wrap;
            intro.Margin = new Thickness(0, 6, 0, 18);
            sp.Children.Add(intro);

            sp.Children.Add(Theme.Caption(L.T("Dimensioni")));
            var sizeButtons = new List<Button>();
            var sizes = new WrapPanel { Margin = new Thickness(0, 8, 0, 18) };
            // a size of your own (x, y), and a thumbnail of the view with the part the image keeps (the largest
            // rectangle with its proportions inside the view: render.fit_camera_to_render)
            var wBox = Theme.Input("", true); wBox.Width = 70;
            var hBox = Theme.Input("", true); hBox.Width = 70;
            wBox.ToolTip = L.T("Larghezza in pixel"); hBox.ToolTip = L.T("Altezza in pixel");
            var thumb = new Canvas { Width = 150, Height = 100, ClipToBounds = true, VerticalAlignment = VerticalAlignment.Center };
            var thumbNote = Theme.Label("", 11, Theme.TextFaint);
            thumbNote.Margin = new Thickness(0, 4, 0, 0);
            bool typing = false, filling = false;   // (filling: Draw writing the boxes - their TextChanged must not read them)
            void Draw()
            {
                thumb.Children.Clear();
                double va = Math.Max(0.1, viewAspect), ra = RenderHeight > 0 ? (double)RenderWidth / RenderHeight : va;
                double vw = va >= 1.5 ? 150 : 100 * va, vh = vw / va;
                thumb.Width = vw; thumb.Height = vh;
                double rw = ra >= va ? vw : vh * ra, rh = rw / ra;
                double x = (vw - rw) / 2, y = (vh - rh) / 2;
                var dim = new SolidColorBrush(Color.FromArgb(0xA0, 0x05, 0x08, 0x10));
                thumb.Children.Add(new Rectangle { Width = vw, Height = vh, Fill = Theme.B(Theme.Inset), Stroke = Theme.B(Theme.Line), StrokeThickness = 1 });
                void Shade(double sx, double sy, double sw, double sh)
                {
                    if (sw <= 0.5 || sh <= 0.5) return;
                    var r = new Rectangle { Width = sw, Height = sh, Fill = dim };
                    Canvas.SetLeft(r, sx); Canvas.SetTop(r, sy); thumb.Children.Add(r);
                }
                Shade(0, 0, x, vh); Shade(x + rw, 0, vw - x - rw, vh); Shade(x, 0, rw, y); Shade(x, y + rh, rw, vh - y - rh);
                var frame = new Rectangle { Width = rw, Height = rh, Stroke = Theme.B(Theme.Accent), StrokeThickness = 1.5 };
                Canvas.SetLeft(frame, x); Canvas.SetTop(frame, y); thumb.Children.Add(frame);
                thumbNote.Text = Math.Abs(ra - va) < 0.01 ? L.T("Tutta la vista")
                    : ra > va ? L.T("Tagliati sopra e sotto") : L.T("Tagliati i lati");
                if (!typing) { filling = true; wBox.Text = RenderWidth.ToString(); hBox.Text = RenderHeight.ToString(); filling = false; }
            }
            for (int i = 0; i < sizeList.Length; i++)
            {
                var (label, w, h) = sizeList[i];
                var b = Theme.Button(label, Theme.Kind.Ghost);
                b.Margin = new Thickness(0, 0, 6, 6);
                int idx = i;
                b.Click += (_, __) => { RenderWidth = w; RenderHeight = h; Theme.SetSegment(sizeButtons, idx); Draw(); };
                sizeButtons.Add(b);
                sizes.Children.Add(b);
            }
            Theme.SetSegment(sizeButtons, 1);
            (RenderWidth, RenderHeight) = (sizeList[1].w, sizeList[1].h);
            sp.Children.Add(sizes);
            void Typed()
            {
                if (filling) return;
                wBox.BorderBrush = Theme.B(Theme.Line); hBox.BorderBrush = Theme.B(Theme.Line);
                if (!int.TryParse(wBox.Text.Trim(), out var tw) || !int.TryParse(hBox.Text.Trim(), out var th)) return;
                if (tw < 16 || th < 16 || tw > 16384 || th > 16384) return;
                RenderWidth = tw; RenderHeight = th;
                int match = Array.FindIndex(sizeList, z => z.w == tw && z.h == th);
                Theme.SetSegment(sizeButtons, match);
                typing = true; Draw(); typing = false;
            }
            wBox.TextChanged += (_, __) => Typed();
            hBox.TextChanged += (_, __) => Typed();
            var custom = new Grid { Margin = new Thickness(0, 0, 0, 18) };
            custom.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            custom.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            custom.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var xy = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            xy.Children.Add(wBox);
            xy.Children.Add(new TextBlock { Text = "×", Foreground = Theme.B(Theme.TextMuted), Margin = new Thickness(6, 0, 6, 0), VerticalAlignment = VerticalAlignment.Center });
            xy.Children.Add(hBox);
            xy.Children.Add(new TextBlock { Text = "px", Foreground = Theme.B(Theme.TextFaint), Margin = new Thickness(6, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center, FontSize = 11.5 });
            var left = new StackPanel { VerticalAlignment = VerticalAlignment.Center };
            left.Children.Add(Theme.Label(L.T("Personalizzata"), 11.5, Theme.TextMuted));
            xy.Margin = new Thickness(0, 4, 0, 0);
            left.Children.Add(xy);
            Grid.SetColumn(left, 0);
            custom.Children.Add(left);
            var right = new StackPanel { HorizontalAlignment = HorizontalAlignment.Right };
            right.Children.Add(thumb);
            thumbNote.HorizontalAlignment = HorizontalAlignment.Center;
            right.Children.Add(thumbNote);
            right.ToolTip = L.T("La vista attuale e la parte che finisce nell'immagine: il resto viene tagliato");
            Grid.SetColumn(right, 2);
            custom.Children.Add(right);
            sp.Children.Add(custom);
            Draw();

            sp.Children.Add(Theme.Caption(L.T("Qualità")));
            var q = Theme.Segmented(out var qButtons, (L.T("Come impostato"), L.T("Usa le impostazioni del pannello Rendering")), (L.T("Bozza"), L.T("Veloce, per controllare")), (L.T("Alta"), L.T("Ottima per il web")), (L.T("Finale"), L.T("Massima qualità, più lento")));
            q.Margin = new Thickness(0, 8, 0, 22);
            q.HorizontalAlignment = HorizontalAlignment.Left;
            string[] ids = { "attuale", "bozza", "alta", "finale" };
            int[] presetSamples = { currentSamples, 64, 512, 2048 };
            var sBox = Theme.Input(currentSamples.ToString(), true); sBox.Width = 80;
            for (int i = 0; i < qButtons.Count; i++)
            {
                int idx = i;
                qButtons[i].Click += (_, __) => { Quality = ids[idx]; Theme.SetSegment(qButtons, idx); sBox.Text = presetSamples[idx].ToString(); };
            }
            Quality = "attuale";
            Samples = currentSamples;
            Theme.SetSegment(qButtons, 0);
            q.Margin = new Thickness(0, 8, 0, 10);
            sp.Children.Add(q);
            // the samples of this image: between the presets (512 -> 2048 is often too much) any number
            var sRow = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 0, 0, 22) };
            var sLab = Theme.Label(L.T("Campioni"), 12, Theme.TextMuted);
            sLab.VerticalAlignment = VerticalAlignment.Center; sLab.Margin = new Thickness(0, 0, 10, 0);
            sRow.Children.Add(sLab);
            sRow.Children.Add(sBox);
            sRow.ToolTip = L.T("Quanti passaggi per pixel, al massimo: più campioni = meno rumore e più tempo. Il denoiser e il campionamento adattivo si fermano prima dove l'immagine è già pulita");
            sBox.TextChanged += (_, __) => { sBox.BorderBrush = Theme.B(Theme.Line); if (int.TryParse(sBox.Text.Trim(), out var n) && n >= 1 && n <= 65536) Samples = n; };
            sp.Children.Add(sRow);

            // texture size: the originals of big models may not fit in the graphics card (then the render is very slow)
            sp.Children.Add(Theme.Caption(L.T("Texture")));
            var tx = Theme.Segmented(out var tButtons,
                (L.T("Auto"), L.T("Le più grandi che stanno nella memoria della scheda video: render veloce anche con modelli enormi")),
                (L.T("Piene"), L.T("Texture originali: massimo dettaglio, ma se non stanno nella memoria video il render diventa lentissimo")),
                ("4K", L.T("Texture ridotte a 4096 pixel")),
                ("2K", L.T("Texture ridotte a 2048 pixel: dettaglio pieno per immagini fino a circa 4K")),
                // (15/11, Luca) the lightest: for the scenes that fill the card (the engine already had it: Auto goes down to it)
                ("1K", L.T("Texture ridotte a 1024 pixel: le più leggere per la scheda video; da vicino i materiali perdono dettaglio")));
            tx.Margin = new Thickness(0, 8, 0, 22);
            tx.HorizontalAlignment = HorizontalAlignment.Left;
            int[] tIds = { -1, 0, 4096, 2048, 1024 };
            for (int i = 0; i < tButtons.Count; i++)
            {
                int idx = i;
                tButtons[i].Click += (_, __) => { Textures = tIds[idx]; Theme.SetSegment(tButtons, idx); };
            }
            Theme.SetSegment(tButtons, 0);
            sp.Children.Add(tx);

            var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right };
            var cancel = Theme.Button(L.T("Annulla"), Theme.Kind.Ghost);
            cancel.Click += (_, __) => DialogResult = false;
            var ok = Theme.Button(L.T("Scegli il file e renderizza"), Theme.Kind.Primary);
            ok.Margin = new Thickness(8, 0, 0, 0);
            // the boxes are read again here: what was typed half-way (51 while writing 512) never goes to the render
            ok.Click += (_, __) =>
            {
                bool bad = false;
                if (!int.TryParse(wBox.Text.Trim(), out var fw) || fw < 16 || fw > 16384) { wBox.BorderBrush = Theme.B(Theme.Danger); bad = true; }
                if (!int.TryParse(hBox.Text.Trim(), out var fh) || fh < 16 || fh > 16384) { hBox.BorderBrush = Theme.B(Theme.Danger); bad = true; }
                if (!int.TryParse(sBox.Text.Trim(), out var fs) || fs < 1 || fs > 65536) { sBox.BorderBrush = Theme.B(Theme.Danger); bad = true; }
                if (bad) return;
                RenderWidth = fw; RenderHeight = fh; Samples = fs;
                DialogResult = true;
            };
            buttons.Children.Add(cancel);
            buttons.Children.Add(ok);
            sp.Children.Add(buttons);
            Body.Children.Add(sp);
        }
    }
}
