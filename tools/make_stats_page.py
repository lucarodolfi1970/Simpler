#!/usr/bin/env python3
"""Builds «Simpler Pack Studio/StudioStatsPage.cs» from «StudioStatsPage.html» (the dashboard of the user statistics).
Edit the .html, run this, compile. tools/check.py verifies the two are in step."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
D = os.path.join(ROOT, "Simpler Pack Studio")
html = open(os.path.join(D, "StudioStatsPage.html"), encoding="utf-8").read().replace("\r\n", "\n")
assert '"""' not in html, 'the page must not contain three double quotes in a row'
cs = ('namespace Simpler\n{\n    /// <summary>The page of the user statistics (made by tools/make_stats_page.py from StudioStatsPage.html: do not edit here).</summary>\n'
      '    internal static class StatsPageHtml\n    {\n        public const string Html = """\n' + html + '""";\n    }\n}\n')
open(os.path.join(D, "StudioStatsPage.cs"), "w", encoding="utf-8", newline="\r\n").write(cs.replace("\n", "\r\n") if False else cs)
print("ok", len(html))
