"""(1.75.23) The samples of the final render read from Cycles' progress lines, with tiles. No Blender here: the
regression replays real Cycles lines through it.

Cycles, when it moves to the next tile, first writes the tile count up with the samples still at the end of the tile
before («Rendered 1/4 Tiles, Sample 512/512»), then starts again («Rendered 1/4 Tiles, Sample 1/512»); after the
last tile it writes «Sample 0/512». Read as they are, the first line jumped a whole tile ahead (half the render with
4 tiles) and the chart of the samples stayed up there. Here such a line counts as the start of the new tile, and the
samples never go back."""
import re

SAMPLE = re.compile(r"Sample (\d+)/(\d+)")
TILES = re.compile(r"Rendered (\d+)/(\d+) Tiles")


class SampleProgress:
    def __init__(self):
        self.done = 0           # samples of the whole image, as if it were one tile (0 .. total)
        self.total = 0
        self._tile = -1

    def feed(self, line):
        """A line of Cycles: True when it carried samples (then .done and .total are up to date)."""
        m = SAMPLE.search(line)
        if not m:
            return False
        s, total = int(m.group(1)), max(1, int(m.group(2)))
        frac = s / total
        t = TILES.search(line)
        if t and int(t.group(2)) > 1:
            tile, tiles = int(t.group(1)), int(t.group(2))
            if tile != self._tile and self._tile >= 0 and s >= total:
                frac = 0.0                      # (the tile count went up, the samples are still those of the last tile)
            self._tile = tile
            frac = (min(tile, tiles) + frac) / tiles
        self.total = total
        self.done = max(self.done, min(total, int(round(frac * total))))
        return True
