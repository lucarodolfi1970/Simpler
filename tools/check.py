"""The check before a delivery (tools/check.py). Since 1.75.1, as Luca asked: short. Only the build and a quick run of
the engine (opening, self-check, engine at rest, save and reopen) on one small scene; the regressions are checked by
Luca, and the whole check below runs only when he asks for a deep test session (--full).

--full, sized on what changed since the last release:

- only the app (interface, texts, notes): build + a quick run of the engine (opening, self-check, engine at rest,
  save and reopen) on the beach scene - a few minutes;
- the engine changed: the whole regression on the cathedral, the beach and the pool (and the cathedral with its
  water plane when water, light reflected by water or glass changed); the test oceano scene (the
  slowest) too when the change touches the sea, water, rain, snow, clouds or the Ambiente.

    python3 tools/check.py --since <commit of the last release> --scenes DIR --eco DIR --out report.json
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLOW_TOPICS = ("ocean", "seacaustics", "refcaustics", "water", "rain", "snow", "clouds", "ambience", "night", "ice")


def changed(since):
    out = subprocess.run(["git", "diff", "--name-only", since], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    out += subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True).stdout
    return [f for f in out.split() if f]


def static_checks():
    """(1.75.55) Checks on the sources: no window of Simpler on top of every program (Luca: «le vorrei rispetto a
    Simpler, non rispetto a tutto Windows») - an owned window already stays above Simpler. Only the windows shown
    when Simpler has no main window yet may be Topmost (the license at the first start, a message without owner)."""
    import re
    bad = []
    # (1.76.62, Luca: «in molti casi citi nomi di progetti che non hanno senso per un utente») the release notes speak of
    # Simpler only: no test projects, no one's computer or logs, no internal checks, no other rendering programs
    notes_dir = os.path.join(ROOT, "release-notes")
    forbid = re.compile(r"cattedrale|cathedral|test oceano|archmodel|evermotion|Tokio|tokyo_|RTX ?4080|tuo log|your log|"
                        r"tuoi log|your logs|tools/|check\.py|regression\.py|sandbox|^(Provato|Non provato|Tested|Not tested)\b|"
                        r"Twinmotion|\bD5\b|Lumion|Enscape|M:\\\\", re.I | re.M)
    hits = []
    for d_ in (notes_dir, os.path.join(notes_dir, "en")):
        for f_ in sorted(os.listdir(d_)):
            if f_.endswith(".txt") or f_ == "summaries.json":
                m_ = forbid.search(open(os.path.join(d_, f_), encoding="utf-8").read())
                if m_:
                    hits.append(f"{f_}: {m_.group(0)}")
    if hits:
        print(f"FAIL release notes with projects, computers, internal checks or other programs: {hits[:8]}", flush=True)
        bad.append("release notes")
    # (1.76.56, Luca: «questo non ha il tooltip») every slider of the panels says what it does
    tipless = []
    for f_ in sorted(os.listdir(os.path.join(ROOT, "app", "Simpler"))):
        if not f_.endswith(".cs"):
            continue
        cs = open(os.path.join(ROOT, "app", "Simpler", f_), encoding="utf-8").read()
        for m_ in re.finditer(r"(MatSlider|new ValueSlider)\(", cs):
            j_, d_ = m_.end(), 1
            while d_ and j_ < len(cs):
                d_ += {"(": 1, ")": -1}.get(cs[j_], 0)
                j_ += 1
            call = cs[m_.end():j_ - 1]
            if call.startswith("string label"):
                continue                                   # (the definitions)
            args = [a_.strip() for a_ in re.split(r",(?![^()]*\))", call)]
            n_ = 9 if m_.group(1) == "MatSlider" else 8      # (the position of the tooltip)
            if "tip:" not in call and "tooltip:" not in call and (len(args) <= n_ or args[n_] == "null"):
                tipless.append(f"{f_}:{cs[:m_.start()].count(chr(10)) + 1}")
    if tipless:
        print(f"FAIL sliders without a tooltip: {tipless}", flush=True)
        bad.append("slider tooltips")
    # (1.76.56, Luca: «nel box rosso la scritta è in italiano») every name of a command the engine shows in «Busy · please
    # wait» (UNDOABLE, _BUSY_LABELS, the rain/sea idle work) has its English in the engine's i18n
    srv = open(os.path.join(ROOT, "engine", "simpler", "server.py"), encoding="utf-8").read()
    i18 = open(os.path.join(ROOT, "engine", "simpler", "i18n.py"), encoding="utf-8").read()
    rn = open(os.path.join(ROOT, "engine", "simpler", "rain.py"), encoding="utf-8").read()
    bl = srv[srv.find("_BUSY_LABELS"):]
    bl = bl[:bl.find("\n}\n")]
    labels = set(re.findall(r'"(?:POST|GET) /api/[^"]+": \("\w+", "([^"]+)"', srv)) | set(re.findall(r':\s*"([^"]+)"', bl)) \
        | set(re.findall(r'IDLE\["what"\] = "([^"]+)"', rn)) | set(re.findall(r'else "([^"]+)"', "\n".join(l for l in rn.splitlines() if 'IDLE["what"]' in l))) \
        | {"Il motore sta lavorando"}
    miss = sorted(l for l in labels if f'"{l}":' not in i18 and f"'{l}':" not in i18)
    if miss:
        print(f"FAIL «Busy · please wait» without English: {miss}", flush=True)
        bad.append("busy labels")
    app = os.path.join(ROOT, "app", "Simpler")
    for n in sorted(os.listdir(app)):
        if not n.endswith(".cs") or n == "LicenseWindow.cs":
            continue
        for i, line in enumerate(open(os.path.join(app, n), encoding="utf-8"), 1):
            if re.search(r"Topmost\s*=\s*true", line):
                bad.append(f"{n}:{i}")
    if bad:
        print("FAIL topmost windows (above every program): " + ", ".join(bad), flush=True)
    # (1.76.9, Luca) the terrain's textures: «Occupato» from the first moment, and the materials put on also when another
    # command was still running (before: skipped, the terrain stayed plain until it was looked at again)
    src = open(os.path.join(app, "MainWindow.Terrain.cs"), encoding="utf-8").read()
    w = src[src.find("async void WatchTerrainTextures"):src.find("IDisposable? _terrainTexBusy")]
    if "TerrainTexBusy(" not in w or re.search(r"&&\s*!IsBusy\)\s*\n\s*\{\s*\n\s*JsonObject\? r", w):
        print("FAIL terrain textures: no «Occupato» while they download, or skipped when the app is busy", flush=True)
        bad.append("WatchTerrainTextures")
    # (1.76.41, Luca: «guarda quante opzioni! raggruppale con macro voci») the terrain in five sections, each with
    # its own Avanzate, no section holding more than a handful of commands in view
    rc = src[src.find("void RenderTerrainCard()"):src.find("void ShowSplitMenu(")]
    for sec in ("Forma e roccia", "Rilievo 3D", "Scultura", "Zone del terreno", "Colori dal terreno", "Spianata e bordi"):
        if f'Section2(L.T("{sec}")' not in rc:
            print(f"FAIL terrain panel: no section «{sec}»", flush=True)
            bad.append(sec)
    for k in ("terrainShape", "terrainZones", "terrainTone", "terrainFlat", '"terrain")'):
        if k not in rc:
            print(f"FAIL terrain panel: no Avanzate {k}", flush=True)
            bad.append(k)
    # (1.76.53, Luca: «Rilievo 3D» with its pictures) every kind with its picture, its Avanzate, the old slider gone
    rr = src[src.find("void RenderReliefCard("):src.find("async Task LoadTerrainQuiet(")]
    eng_m = open(os.path.join(ROOT, "engine", "simpler", "matedit.py"), encoding="utf-8").read()
    kinds = re.findall(r'\("(\w+)", "[^"]+", "[^"]+"\),', src[src.find("ReliefKinds ="):src.find("void RenderReliefCard(")])
    miss = [k for k in kinds if not os.path.isfile(os.path.join(app, "weather", f"relief_{k}.png")) or f'"{k}"' not in eng_m]
    if len(kinds) < 5 or miss or 'Advanced(card, "terrainRelief")' not in rr or "adv.Done(" not in rr \
            or 'L.T("Rilievo della roccia")' in rc:
        print(f"FAIL «Rilievo 3D»: kinds {kinds}, without picture or not in the engine {miss}", flush=True)
        bad.append("relief card")
    # (1.76.55, Luca: «in avanzate il displacement, spento di default, se acceso messagebox») the toggle in the
    # Avanzate, off by default, the warning before it goes on (and taken back on «No»), the sliders under it
    dz = rr[rr.find('L.T("Displacement vero")'):]
    if 'adv.Body.Children.Add(dsw)' not in rr or '?["rdisp"] ?? false' not in rr or "MessageBoxButton.YesNo" not in dz \
            or "dsw.SetQuiet(false)" not in dz or 'L.T("Ampiezza")' not in dz or 'L.T("Finezza")' not in dz \
            or '"rdisp": False' not in eng_m or "displacement_pass(True, max(" not in open(os.path.join(ROOT, "engine", "simpler", "render.py"), encoding="utf-8").read():
        print("FAIL «Rilievo 3D»: Displacement vero not in the Avanzate, on by default, without its warning or sliders", flush=True)
        bad.append("relief displacement")
    # (1.76.58, Luca: «subito sotto») the relief map of one's own in «Rilievo 3D», the colour map just under it
    i_m, i_c = rr.find('ReliefMapRow(card, L.T("Mappa di rilievo")'), rr.find('ReliefMapRow(card, L.T("Mappa colore")')
    if i_m < 0 or i_c < 0 or not (0 < i_c - i_m < 600) or '"rmap": ""' not in eng_m or "def _relief_tri" not in eng_m:
        print("FAIL «Rilievo 3D»: the relief and colour maps missing or not one under the other", flush=True)
        bad.append("relief maps")
    # (1.77.0, Luca: «inverno dove le foglie spariscono … gradualmente») the type Fogliame: in the editor's list, its
    # season in Cycles and in the view from the same tables, and the leaves gone throw no shadow in the view
    mm = open(os.path.join(app, "MainWindow.Materials.cs"), encoding="utf-8").read()
    vjf = open(os.path.join(app, "web", "viewer.js"), encoding="utf-8").read()
    mats_py = open(os.path.join(ROOT, "engine", "simpler", "materials.py"), encoding="utf-8").read()
    if ('("foliage", "Fogliame"' not in mm or "void FoliageSection()" not in mm or '"foliage.season"' not in mm
            or "def foliage_color" not in eng_m or "FOLIAGE_RAMPS" not in mats_py
            or "if (p.foliage) useFoliage(m, p.foliage)" not in vjf or "foliageShadows();" not in vjf):
        print("FAIL «Fogliame»: the type, its season in Cycles or in the view, or the shadows of the leaves gone missing", flush=True)
        bad.append("foliage")
    # (1.77.1) the type Tessuto: in the editor's list, in Cycles and in the view
    if ('("fabric", "Tessuto"' not in mm or "void FabricSection()" not in mm or "def fabric_color" not in eng_m
            or '"fabric"' not in mats_py or "if (p.fabric) useFabric(" not in vjf):
        print("FAIL «Tessuto»: the type, its Cycles part or its view part missing", flush=True)
        bad.append("fabric")
    # (1.78.0) «Importa vegetazione»: the menu entry, the library «Vegetazione», the conversion and «Foglie e legno…»
    iw = open(os.path.join(app, "MainWindow.ImportWizard.cs"), encoding="utf-8").read()
    vg = open(os.path.join(app, "MainWindow.Vegetation.cs"), encoding="utf-8").read()
    ol = open(os.path.join(app, "MainWindow.ObjectLibrary.cs"), encoding="utf-8").read()
    job = open(os.path.join(ROOT, "engine", "matbulk_job.py"), encoding="utf-8").read()
    if ('"Importa vegetazione nella libreria…"' not in iw or "void RenderVegBrowser(bool simpler)" not in vg or "ShowVegParts(" not in ol
            or "ConvertToVegetation(" not in ol or "def vegetation():" not in job or "!IsVegModel(m)" not in ol):
        print("FAIL «Vegetazione»: the import, the library, the conversion or «Foglie e legno…» missing", flush=True)
        bad.append("vegetation")
    # (1.78.1) the library: a menu per kind with Simpler · I miei · Online, «La storia» in the File menu, search everywhere
    mw = open(os.path.join(app, "MainWindow.cs"), encoding="utf-8").read()
    lm = mw[mw.find("LibraryMenus ="):mw.find("};", mw.find("LibraryMenus ="))]
    if ('("story"' in lm or '("materials", "simplermats", "Simpler")' not in lm or '("models", "primitives", "Simpler")' not in lm
            or "void RenderGlobalSearch()" not in open(os.path.join(app, "MainWindow.LibrarySearch.cs"), encoding="utf-8").read()
            # (1.78.4, Luca) «La storia di Simpler» left the File menu: «Scena di esempio» is its first command
            or 'Item(L.T("Scena di esempio")' not in open(os.path.join(app, "MainWindow.FileMenu.cs"), encoding="utf-8").read()):
        print("FAIL library order: menus by kind with Simpler/I miei/Online, the story in File, the global search", flush=True)
        bad.append("library order")
    if ("SceneToVegetation(" not in open(os.path.join(app, "MainWindow.Tree.cs"), encoding="utf-8").read()
            or "SceneToVegetation(" not in ol or "def scene_vegetation(" not in eng_m
            or not os.path.isfile(os.path.join(app, "import_wizard_veg.jpg")) or '"import_wizard_veg.jpg"' not in iw):
        print("FAIL «Converti in vegetazione» in the scene or the plants' picture of the import window missing", flush=True)
        bad.append("scene vegetation")
    pth = open(os.path.join(ROOT, "engine", "simpler", "paths.py"), encoding="utf-8").read()
    if '"ecosystems", "materials", "decals")' not in pth or 'paths.get("ecosystems")' not in open(os.path.join(ROOT, "engine", "simpler", "ecosystems.py"), encoding="utf-8").read() \
            or "_decalRootPath" not in open(os.path.join(app, "MainWindow.Decals.cs"), encoding="utf-8").read():
        print("FAIL folders: ecosystems and the user's decals must have their own movable folder", flush=True)
        bad.append("folders")
    # (1.78.3) the lights: a button of the header, not a library; Vegetazione and Modelli 3D with Simpler and I miei
    if ('("sky", "lights"' in lm or '("vegetation", "simplerplants", "Simpler")' not in lm or "ShowLightsMenu(lightsBtn!)" not in mw
            or "void RenderSimplerModels()" not in vg):
        print("FAIL lights button in the header, Vegetazione/Modelli 3D ▸ Simpler", flush=True)
        bad.append("lights and simpler")
    # (1.78.3) a material edit that only changes the look does not make the engine look for the coast/shelter again
    sv = open(os.path.join(ROOT, "engine", "simpler", "server.py"), encoding="utf-8").read()
    vj_all = open(os.path.join(app, "web", "viewer.js"), encoding="utf-8").read()
    if "rain.touch(geometry=_changes_geometry(job))" not in sv or "LOOK_ONLY = frozenset(" not in sv:
        print("FAIL a look-only material edit must not count as a change of shapes", flush=True)
        bad.append("look only")
    # (1.78.4) the brush has limits per touch and per distribution (a grass of 8,176 triangles: 120,806 pieces and a
    # frozen view); run on the viewer's own functions when node is there
    import shutil, subprocess
    if shutil.which("node"):
        r_ = subprocess.run(["node", os.path.join(ROOT, "tools", "paint_limits.mjs")], capture_output=True, text=True, timeout=300)
        if r_.returncode != 0:
            print("FAIL brush limits: " + (r_.stdout + r_.stderr).strip()[-400:], flush=True)
            bad.append("brush limits")
    elif "PAINT_DAB_MAX" not in vj_all:
        print("FAIL brush limits missing", flush=True)
        bad.append("brush limits")
    # (1.78.4, Luca: «aggiungi le icone alle luci») the menus draw the Icon of their items; each light its own icon
    tm = open(os.path.join(app, "ThemeMenus.cs"), encoding="utf-8").read()
    ins = open(os.path.join(app, "MainWindow.Insert.cs"), encoding="utf-8").read()
    if "ContentSource='Icon'" not in tm or "Icon = Theme.Icon(LightIcon(k)" not in ins or '"strip" => Icons.LightStrip' not in ins:
        print("FAIL icons of the lights menu", flush=True)
        bad.append("lights icons")
    # (1.78.4, Luca: «recuperiamo spazio nella toolbar») Sagome / Tempo reale / Path tracing in one button with a menu
    if "_viewModeButton.Click += (_, __) => ShowViewModeMenu();" not in mw or "out _modeButtons" in mw:
        print("FAIL the kinds of view: one button with a menu", flush=True)
        bad.append("view mode button")
    # (1.78.4, Luca) the violet pivot: kept in the library, the contact point of the distributions; shown on the only
    # piece of a model
    pt = open(os.path.join(ROOT, "engine", "simpler", "paint.py"), encoding="utf-8").read()
    if ("def contact_point(" not in pt or "def repivot(" not in pt or "models.keep_pivot(ob)" not in open(os.path.join(ROOT, "engine", "simpler", "scene_ops.py"), encoding="utf-8").read()
            or "function pivotOwner(" not in vj_all or "drag.baseStraight.set(0, 0, 0)" not in vj_all or "protoReplace(it.pm)" not in vj_all):
        print("FAIL pivot placed by hand: library, distributions, a model's only piece", flush=True)
        bad.append("pivot")
    # (1.78.4, Luca: «spostali dentro material simpler») the materials of Simpler are the folder «Simpler» of the
    # material library (a real folder, locked with the others); a saved model shows where it was saved
    lf = open(os.path.join(app, "MainWindow.LibraryFolders.cs"), encoding="utf-8").read()
    if ('const string SimplerMats = "Simpler";' not in lf or "static bool InSimplerMats(" not in lf or "def locked_change(" not in open(os.path.join(ROOT, "engine", "simpler", "materials.py"), encoding="utf-8").read()
            or "_libraryTab = ModelTabFor(ans.Value.folder, true);" not in open(os.path.join(app, "MainWindow.ObjectLibrary.cs"), encoding="utf-8").read()):
        print("FAIL Materiali Simpler as a folder / a saved model shown in its tab", flush=True)
        bad.append("simpler materials")
    # (1.78.4, Luca: «i pulsanti sono più larghi del necessario») icon-only header buttons get a narrow padding
    if "void ShowHeaderLabel(FrameworkElement e, bool on)" not in mw or "foreach (var e in step) ShowHeaderLabel(e, false);" not in mw:
        print("FAIL narrow icon-only buttons in the header", flush=True)
        bad.append("header narrow")
    # (1.78.4, Luca: «problema di opacità con plantfactory») a «Transparency» picture is an inverted opacity map (import
    # and «Converti in vegetazione»); tools/transparency_check.py renders it in the regression (transp_map)
    me = open(os.path.join(ROOT, "engine", "simpler", "matedit.py"), encoding="utf-8").read()
    if ("def fix_transparency_map(p, card=False):" not in me or "            fix_transparency_map(p)" not in me
            or "def map_background(image" not in me or 'want = bg == "white"' not in me
            or "fixed = matedit.fix_transparency_map(p, card=True)" not in open(os.path.join(ROOT, "engine", "matbulk_job.py"), encoding="utf-8").read()
            or not os.path.isfile(os.path.join(ROOT, "tools", "transparency_check.py"))):
        print("FAIL «Transparency» maps read as inverted opacity", flush=True)
        bad.append("transparency map")
    # (1.78.4, Luca: flowers yellow in path tracing, violet in the real-time view) pictures by what they are: the
    # source of a name only for the same picture, the view's cache with the rev, GIF masks as PNG (also at the import)
    prx = open(os.path.join(ROOT, "engine", "simpler", "proxies.py"), encoding="utf-8").read()
    vjs = open(os.path.join(ROOT, "app", "Simpler", "web", "viewer.js"), encoding="utf-8").read()
    if ("_SRC_ID.get(im.name) == ident" not in prx or "def _still(path)" not in prx
            or "function loadImage(name, rev, px)" not in vjs or "loadImage(maps.color.image, maps.color.rev)" not in vjs
            or '"rev": _image_rev(d["image"])' not in open(os.path.join(ROOT, "engine", "simpler", "materials.py"), encoding="utf-8").read()
            or "stillgif.to_png(gif, png)" not in open(os.path.join(ROOT, "engine", "preview_job.py"), encoding="utf-8").read()
            or not os.path.isfile(os.path.join(ROOT, "tools", "texname_check.py"))):
        print("FAIL pictures of the view taken by name", flush=True)
        bad.append("texture names")
    # (1.78.4, Luca: «generare video partendo da un solo frame e dal prompt») Video AI «Solo inizio»: no end_image sent
    kr = open(os.path.join(ROOT, "app", "Simpler", "Krea.cs"), encoding="utf-8").read()
    vp = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.VideoPanel.cs"), encoding="utf-8").read()
    if ('if (end != null) body["end_image"] = end;' not in kr or "VideoOneFrame" not in vp or "ImprovePromptOneSystem" not in vp
            or 'var eu = end == null ? null : await KreaClient.UploadAsync(end, ct);' not in vp):
        print("FAIL video from the first frame only", flush=True)
        bad.append("video one frame")
    # (1.78.4, Luca: «non si può avere questa lista più chiara? partire da dove si trova la libreria?») folders of the
    # import as a tree opened on the folder chosen, starting from the library shown, never a locked Simpler folder
    iw = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.ImportWizard.cs"), encoding="utf-8").read()
    if ("void ShowFolderTree(" not in iw or "string StartFolder(bool veg)" not in iw or "bool hidden(string f) => _mw.ReadOnlyFolder(f);" not in iw
            or "new string(' ', 4 * f.Count(c => c == '/'))" in iw):
        print("FAIL import folder tree", flush=True)
        bad.append("import folder tree")
    # (1.78.4, Luca: «switcho su realtime e per molti secondi resta fermo») leaving the path tracing: «Occupato» at once,
    # shaders prepared in the background first, the box until the first frame; slow frames say which shaders
    vjs = open(os.path.join(ROOT, "app", "Simpler", "web", "viewer.js"), encoding="utf-8").read()
    if ("if (_wasPtOn && !ptOn) {" not in vjs or "busyWarn.holdWhat = tr('Passaggio al tempo reale');" not in vjs
            or vjs.count("if (_ptWarm) { _ptWarm = false; busyWarn.holdFrames = 2; }") != 2 or "first frame after the path tracing" not in vjs):
        print("FAIL no «Occupato» when going back to real time", flush=True)
        bad.append("pt to realtime busy")
    # (1.78.4, Luca: «snow brush… parte subito un'elaborazione con questo shelter rain») painting snow/puddles and
    # sculpting snow are not shape changes (regression step snow_paint)
    srv = open(os.path.join(ROOT, "engine", "simpler", "server.py"), encoding="utf-8").read()
    rn = open(os.path.join(ROOT, "engine", "simpler", "rain.py"), encoding="utf-8").read()
    if ('"POST /api/rain/paint", "POST /api/rain/paint/clear", "POST /api/rain/sculpt"' not in srv or rn.count("touch(geometry=False)\n    if layer == \"snow\":") != 2
            or "rain.touch(geometry=False)" not in open(os.path.join(ROOT, "engine", "simpler", "snowsculpt.py"), encoding="utf-8").read()
            or '("snow_paint", "SNOWPAINT"' not in open(os.path.join(ROOT, "tools", "regression.py"), encoding="utf-8").read()):
        print("FAIL painted snow counted as a change of shapes", flush=True)
        bad.append("snow paint geometry")
    # (1.78.4, Luca: «cosa ne dici se lo fa in automatico Simpler?») snow brush on: lighter mantle after a pause, full at
    # the brush off and for final images
    sn = open(os.path.join(ROOT, "engine", "simpler", "snow.py"), encoding="utf-8").read()
    if ("def set_brushing(d):" not in sn or "detail = min(detail, BRUSH_DETAIL)" not in sn or "time.time() - BRUSH[\"last\"] < BRUSH_WAIT" not in sn
            or 'snow.BRUSH["full"] = final' not in rn or '"POST /api/snow/brushing"' not in srv
            or 'Post("snow/brushing"' not in open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Ambience.cs"), encoding="utf-8").read()):
        print("FAIL snow brush without the lighter mantle", flush=True)
        bad.append("snow brush light")
    # (1.78.4, Luca: «il cerchio per dipingere così chiaro sulla neve non si vede») snow brushes in strong colours
    if "const SNOW_BRUSH = 0x1e7bff, SCULPT_BRUSH = 0x8a4dff;" not in vjs or "0xf2f6ff" in vjs:
        print("FAIL snow brush ring too pale", flush=True)
        bad.append("snow brush colour")
    # (1.78.4, Luca: «si può lavorare anche mentre simpler calcola, metti la clessidra con il puntatore») the full
    # hourglass only when the panels are locked; background work shows the arrow with the hourglass
    import glob as _g
    cs = {os.path.basename(f): open(f, encoding="utf-8").read() for f in _g.glob(os.path.join(ROOT, "app", "Simpler", "*.cs"))}
    html = open(os.path.join(ROOT, "app", "Simpler", "web", "viewer.html"), encoding="utf-8").read()
    waits = [n for n, t in cs.items() if "Cursors.Wait" in t and n not in ("MainWindow.Busy.cs", "Ai.cs")]
    if (waits or "CursorLocked && _lockShown ? Cursors.Wait : CursorBusy ? Cursors.AppStarting" not in cs.get("MainWindow.Busy.cs", "")
            or "body.ebusy, body.ebusy * { cursor: progress" not in html or "body.working, body.working * { cursor: progress" not in html
            or "toggle('lockwork', locked && !lockedByWindow)" not in vjs):
        print("FAIL full hourglass while the user can still work " + ",".join(waits), flush=True)
        bad.append("busy cursor kinds")
    # (1.78.4, Luca: «sul bordo del marciapiede tagli squadrati nella neve») the rise of a kerb averaged, not in steps
    if ("KERB_MAX = 0.30" not in sn or "kerb |= j | _shift(j, -dy, -dx, False)" not in sn
            or not os.path.exists(os.path.join(ROOT, "tools", "kerb_check.py"))):
        print("FAIL square cuts in the snow along a kerb", flush=True)
        bad.append("snow kerb")
    # (1.78.4, Luca: «non dovrebbe vedersi così poco dettagliato») the pieces of a distribution lighter only under
    # about 20 fps, never under SCATTER_STILL in a still view, the frames preparing shaders not counted
    if ("const SCATTER_SLOW = 50, SCATTER_FAST = 33, SCATTER_STILL = 8e6;" not in vjs
            or "if (_frameNewShaders || shaderPrep.busy) return;" not in vjs
            or "Math.max(scatter.budget, SCATTER_STILL)" not in vjs or "if (frameMs > 25)" in vjs):
        print("FAIL pieces at the lightest level in a still view that is fast enough", flush=True)
        bad.append("scatter lod")
    # (1.78.4) the hooks for the author's separate tool built from these sources: in Simpler only partial methods
    # without a body (the compiler removes the calls) - never their bodies, never the tool's files
    appdir = os.path.join(ROOT, "app", "Simpler")
    allcs = "".join(open(os.path.join(appdir, f), encoding="utf-8").read() for f in os.listdir(appdir) if f.endswith(".cs"))
    if ("partial void StudioMode(ref bool on);" not in allcs or "partial void StudioMode(ref bool on) =>" in allcs
            or "class StudioProgram" in allcs or 'AppInstance.Prefix + "app.log"' not in allcs):
        print("FAIL the hooks of the separate tool are not empty in Simpler", flush=True)
        bad.append("studio hooks")
    # (1.78.4) packs of models: the installer, its menu entries, its test
    imp = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.ImportWizard.cs"), encoding="utf-8").read()
    if ("await InstallPackAsk()" not in imp or "await ShowInstalledPacks()" not in imp
            or not os.path.exists(os.path.join(ROOT, "tools", "packtest", "PackTest.cs"))
            or "throw new InvalidDataException(\"changed \" + name)" not in allcs or "kept.Contains(id)" not in allcs
            or "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEVGDA911Ejn3" not in allcs):
        print("FAIL packs: installer, menu or test missing", flush=True)
        bad.append("packs")
    # (1.78.4, Luca: «non posso cliccare nulla») the pack window moves only from the picture: the band keeps its clicks
    pw = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Packs.cs"), encoding="utf-8").read()
    if "if (d == band || d is System.Windows.Controls.Primitives.ButtonBase) return;" not in pw:
        print("FAIL the pack window takes the clicks of its band to move", flush=True)
        bad.append("pack window clicks")
    # (1.78.4, Luca: «ho eliminato la cartella con i modelli dentro: i modelli ci sono tutti») delete a folder with its models
    mp = open(os.path.join(ROOT, "engine", "simpler", "models.py"), encoding="utf-8").read()
    lf = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.LibraryFolders.cs"), encoding="utf-8").read()
    if ('if action == "delete" and data.get("items") and path:' not in mp or 'new { action = "delete", path = folder, items }' not in lf
            or not os.path.exists(os.path.join(ROOT, "tools", "folderdelete_check.py"))):
        print("FAIL deleting a folder of models leaves its models", flush=True)
        bad.append("folder delete items")
    # (1.78.4, Luca: «l'utente può fare azioni nelle cartelle rosse di Simpler») the models of the locked Simpler
    # parts: their menu only inserts, scatters and copies; nothing moves or pastes into or out of them
    ol = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.ObjectLibrary.cs"), encoding="utf-8").read()
    ms = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.ModelSelection.cs"), encoding="utf-8").read()
    if ("var ro = ReadOnlyFolder((string?)m[\"folder\"]);" not in ol or "}, ro ? null : async folder =>" not in ol
            or "if (ids.Any(ReadOnlyModel))" not in ms or "if (ReadOnlyFolder(folder) || ids.Any(ReadOnlyModel))" not in ms
            or "ReadOnlyFolder(target)" not in lf or not os.path.exists(os.path.join(ROOT, "tools", "lock_check.py"))):
        print("FAIL the models of the locked Simpler parts can be changed from their menus", flush=True)
        bad.append("simpler read only menus")
    # (1.78.4, Luca) the update check: in the background after the start (never in Studio), only version and language,
    # links only https on rodluc.com / github.com, the switch and «Controlla ora» in the settings, its test
    uc = open(os.path.join(ROOT, "app", "Simpler", "UpdateCheck.cs"), encoding="utf-8").read()
    mwu = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Updates.cs"), encoding="utf-8").read()
    # (the settings are the right panel of MainWindow.FileMenu.cs; SettingsDialog only keeps Version and the notes)
    sd = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.FileMenu.cs"), encoding="utf-8").read()
    mwm = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.cs"), encoding="utf-8").read()
    if ('"www.rodluc.com" or "rodluc.com" or "github.com"' not in uc or "TimeSpan.FromSeconds(6)" not in uc or "TimeSpan.FromHours(24)" not in uc
            or "if (!InStudio) StartUpdateCheck();" not in mwm or "Task.Run(" not in mwu or "Cursor" in mwu.replace("TextTrimming", "")
            or "UpdateCheck.Run(manual: true)" not in sd or "Simpler invia al sito soltanto il numero di versione e la lingua. Si può disattivare." not in sd
            or not os.path.exists(os.path.join(ROOT, "tools", "updatetest", "UpdateTest.cs"))):
        print("FAIL update check not as agreed (background, 6 s, 24 h, links, settings)", flush=True)
        bad.append("update check")
    # (1.78.4, Luca: «nelle info iniziali va scritto che Simpler si collega a … rodluc.com e GitHub») the agreement and the credits say it
    for f, words in ((os.path.join("credits", "Licenza.md"), ("www.rodluc.com", "github.com", "senza messaggi di errore")),
                     (os.path.join("credits", "en", "License.md"), ("www.rodluc.com", "github.com", "without error messages")),
                     (os.path.join("credits", "Crediti.md"), ("rodluc.com", "GitHub", "senza messaggi di errore")),
                     (os.path.join("credits", "en", "Credits.md"), ("rodluc.com", "GitHub", "without error messages"))):
        txt = open(os.path.join(ROOT, f), encoding="utf-8").read()
        if not all(w in txt for w in words):
            print("FAIL " + f + " does not say Simpler connects to rodluc.com and GitHub", flush=True)
            bad.append("connections in the agreement")
    # (1.78.4, Luca) «Perché esiste Simpler»: the link «sito ufficiale di Simpler» to rodluc.com, the example scene on the
    # right (opened from a copy in Documents), the samples shipped next to the exe, the CGtips licence in the credits
    st_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Story.cs"), encoding="utf-8").read()
    if ('SiteUrl = "https://www.rodluc.com/simpler/en/"' not in st_ or 'L.T("sito ufficiale")' not in st_ or "OpenSample(" not in st_
            or 'samples\\**' not in open(os.path.join(ROOT, "app", "Simpler", "Simpler.csproj"), encoding="utf-8").read() or not os.path.exists(os.path.join(ROOT, "samples", "Cosmetic shop", "LICENSE.txt"))
            or "CGtips" not in open(os.path.join(ROOT, "credits", "Crediti.md"), encoding="utf-8").read()):
        print("FAIL the story box: official site link, example scene or its licence missing", flush=True)
        bad.append("story sample")
    # (Luca: «voglio il delta senza sceglierli») Pack Studio: simpler-delta with only what the site does not have
    sc_ = open(os.path.join(ROOT, "Simpler Pack Studio", "StudioContent.cs"), encoding="utf-8").read()
    if ("static void BuildUpload(" not in sc_ or '"1-prima"' not in sc_ or '"2-per-ultimo"' not in sc_ or "da-togliere.txt" not in sc_
            or "try { BuildUpload(outDir," not in sc_ or not os.path.exists(os.path.join(ROOT, "Simpler Pack Studio", "StudioDelta.cs")) or "void OpenContentWizard()" not in sc_ or "class ContentWizard" not in open(os.path.join(ROOT, "Simpler Pack Studio", "StudioDelta.cs"), encoding="utf-8").read() or "bool dryRun = false" not in sc_ or "Directory.Delete(" in sc_ or "3 · Modelli ed ecosistemi nuovi o cambiati" not in open(os.path.join(ROOT, "Simpler Pack Studio", "StudioHelp.cs"), encoding="utf-8").read()):
        print("FAIL Pack Studio: the folder with only the files to upload is missing", flush=True)
        bad.append("upload delta")
    # (1.80.0) Pack Studio: the statistics of the users (diagnostics): a dashboard page in the space of the view, read from the site
    _ps = os.path.join(ROOT, "Simpler Pack Studio")
    _st = open(os.path.join(_ps, "StudioStats.cs"), encoding="utf-8").read() if os.path.exists(os.path.join(_ps, "StudioStats.cs")) else ""
    _hh = open(os.path.join(_ps, "StudioStatsPage.html"), encoding="utf-8").read().replace("\r\n", "\n") if os.path.exists(os.path.join(_ps, "StudioStatsPage.html")) else ""
    _pc = open(os.path.join(_ps, "StudioStatsPage.cs"), encoding="utf-8").read().replace("\r\n", "\n") if os.path.exists(os.path.join(_ps, "StudioStatsPage.cs")) else ""
    if (not _st or not _hh or "void OpenStats()" not in _st or "StatsPageHtml.Html" not in _st or "X-Diag-Key" in _hh or _hh not in _pc
            or '"""' in _hh or "OpenStats()" not in open(os.path.join(_ps, "MainWindow.Studio.cs"), encoding="utf-8").read()
            or "4 · Statistiche degli utenti" not in open(os.path.join(_ps, "StudioHelp.cs"), encoding="utf-8").read()):
        print("FAIL Pack Studio: the statistics of the users (page, or StudioStatsPage.cs out of step: run tools/make_stats_page.py)", flush=True)
        bad.append("pack studio stats")
    # (1.78.5, Luca) the second example scene, «Bedroom»: «Example #1» and «Example #2» in the start box, its licence
    if ('("Bedroom", "bedroom.simpler")' not in st_ or 'L.F("Esempio #{0}", n + 1)' not in st_
            or not os.path.exists(os.path.join(ROOT, "samples", "Bedroom", "LICENSE.txt")) or not os.path.exists(os.path.join(ROOT, "samples", "Bedroom", "thumb.jpg"))
            or "«Bedroom»" not in open(os.path.join(ROOT, "credits", "Crediti.md"), encoding="utf-8").read()):
        print("FAIL the second example scene (Bedroom) or its licence is missing", flush=True)
        bad.append("bedroom sample")
    # (1.78.4, Luca) «Suggerisci un'idea»: the ideas page of rodluc.com in the view, only that page inside, «Torna alla
    # scena»; site not reachable = one plain message and the scene view back (never an error)
    idx = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Ideas.cs"), encoding="utf-8").read()
    if ("IdeasInside(u, page)" not in idx or "IdeasUnreachable(page)" not in idx or "MessageBoxImage.Information" not in idx or "MessageBoxImage.Error" in idx
            or "tiles.Children.Add(IdeasTile());" not in st_ or "CloseIdeas();" not in open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Viewport.cs"), encoding="utf-8").read()
            or not os.path.exists(os.path.join(ROOT, "server", "ideas", "admin.php"))):
        print("FAIL «Suggerisci un'idea» not as agreed (page in the view, unreachable site handled quietly)", flush=True)
        bad.append("ideas")
    # (Luca: «ficus tree 1 e 2 risultano senza materiale») BMP textures: size read from the header (a copy for the
    # view is made), served as an image, and the view asks again while the copy is being made
    px_ = open(os.path.join(ROOT, "engine", "simpler", "proxies.py"), encoding="utf-8").read()
    vj_ = open(os.path.join(ROOT, "app", "Simpler", "web", "viewer.js"), encoding="utf-8").read()
    if ('head[:2] == b"BM"' not in px_ or '".bmp": "image/bmp"' not in open(os.path.join(ROOT, "engine", "simpler", "server.py"), encoding="utf-8").read()
            or "img.src = url + '&try=' + t" not in vj_):
        print("FAIL BMP textures white in the real-time view (no copy for the view, or no new asking)", flush=True)
        bad.append("bmp textures")
    # (Luca) «Modelli gratuiti» next to the ideas (a page of rodluc.com in the view, links in the browser only to the sites
    # it names); «Scena di esempio» in the File menu opens the start box of the library, not the scene
    fm_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.FileMenu.cs"), encoding="utf-8").read()
    if ("tiles.Children.Add(FreeTile());" not in st_ or "OpenOutside(e.Uri, page)" not in idx or "/simpler/free/" not in idx
            or 'Item(L.T("Scena di esempio"), "", () => { _libraryTab = "story"; RenderLibrary();' not in fm_
            or not os.path.exists(os.path.join(ROOT, "server", "free", "index.php"))):
        print("FAIL free models tile or the example scene menu not as agreed", flush=True)
        bad.append("free models")
    # (Luca: «sotto è tagliato») the start box fits in the height of the library (the text gets smaller when needed)
    if "FitStory();" not in st_ or "void FitStory()" not in st_:
        print("FAIL the start box can be cut at the bottom (no fitting to the height of the library)", flush=True)
        bad.append("story fit")
    # (Luca: «serve una scroll bar verticale») the import wizard scrolls, its buttons stay at the bottom
    iw_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.ImportWizard.cs"), encoding="utf-8").read()
    if ("Footer.Children.Add(buttons);" not in iw_ or "EnableBodyScroll();" not in iw_
            or "if (_checkWait is { Task.IsCompleted: false } wait) wait.TrySetResult(false);" not in iw_):
        print("FAIL the import wizard does not scroll (the scale check goes off the screen)", flush=True)
        bad.append("import wizard scroll")
    # (Luca: «i materiali hanno qualche problema», Alter 49 firs from OBJ) the Alpha socket of a picture with no alpha
    # channel is read as the grey of the picture
    me_ = open(os.path.join(ROOT, "engine", "simpler", "matedit.py"), encoding="utf-8").read()
    if 'if m["channel"] == "A" and not _image_has_alpha(m["image"]):' not in me_ or "def _image_has_alpha(name):" not in me_:
        print("FAIL grey cut-out maps of OBJ plants read as alpha (no leaves)", flush=True)
        bad.append("obj plant maps")
    # (Luca: «se prendo il gizmo per appoggiare la pianta al pavimento ruota di 90 gradi») the turn of the file goes into
    # the meshes at the import, and «Correggi gli assi» does it for a model already in the library
    pj_ = open(os.path.join(ROOT, "engine", "preview_job.py"), encoding="utf-8").read()
    if ("_bake_rotation(objs)            # (the file's own turn into the meshes" not in pj_ or 'orient.get("mode") == "bake"' not in pj_
            or '"bake": {"mode": "bake"}' not in open(os.path.join(ROOT, "engine", "simpler", "models.py"), encoding="utf-8").read()
            or 'OItem(L.T("Correggi gli assi")' not in open(os.path.join(ROOT, "app", "Simpler", "MainWindow.ObjectLibrary.cs"), encoding="utf-8").read()):
        print("FAIL a model with a turned up (OBJ with Y up) lies down when rested with the gizmo (no axes fix)", flush=True)
        bad.append("model axes")
    # (Luca: «una voce package a cartelle blu») the packs go in Packages/<title> (Modelli 3D and Vegetazione), their
    # own entry, blue folders, read only (always)
    pk_ = open(os.path.join(ROOT, "app", "Simpler", "PackInstaller.cs"), encoding="utf-8").read()
    vg_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Vegetation.cs"), encoding="utf-8").read()
    if ('public const string PacksFolder = "Packages";' not in pk_ or "public string Destination(string part, string path, string title)" not in pk_
            or "internal bool IsPackFolder(string f)" not in vg_ or "|| IsPackFolder(f ?? \"\");" not in vg_
            or '("models", "packmodels", "Pacchetti")' not in open(os.path.join(ROOT, "app", "Simpler", "MainWindow.cs"), encoding="utf-8").read()
            or '"Packages", veg_root() + "/Packages"' not in open(os.path.join(ROOT, "engine", "simpler", "models.py"), encoding="utf-8").read()):
        print("FAIL packs not in their own blue, read only «Packages» entry", flush=True)
        bad.append("packages entry")
    # (Luca: «vedo simpler ancora e non package») the path of a model in a pack never repeats the pack's title
    pin_ = open(os.path.join(ROOT, "app", "Simpler", "PackInstaller.cs"), encoding="utf-8").read()
    if "path = PackPath(path, title);" not in pin_ or "!string.Equals(x, name, StringComparison.OrdinalIgnoreCase)" not in pin_:
        print("FAIL a pack repeats its title in its folders (Packages/Victorian era/Animals/Victorian era)", flush=True)
        bad.append("pack title folders")
    # (Luca: «c'è ancora delete folder») the folders of the packs are read only whatever «SimplerLocked», in the app and
    # in the engine; the author's own models go back to their folders when the pack goes
    veg_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Vegetation.cs"), encoding="utf-8").read()
    mod_ = open(os.path.join(ROOT, "engine", "simpler", "models.py"), encoding="utf-8").read()
    if ('internal bool ReadOnlyFolder(string? f) => (SimplerLocked && IsSimplerFolder(f ?? "")) || IsPackFolder(f ?? "");' not in veg_
            or 'return _pack_folder(f) or (LOCK["on"] and _locked_folder(f))' not in mod_
            or 'if any(f and is_locked(_clean(f)) for f in folders)' not in mod_ or "GiveBack(id, Before((string?)from?[id], packId, id))" not in pin_):
        print("FAIL the folders of the packs can be changed with «SimplerLocked» 0, or the author's models stay in «Packages»", flush=True)
        bad.append("packs read only")
    # (Luca: «questa resta valida anche con i package?») the packs follow the models library when it is moved
    if "asked every time: the folder of the library can be" not in open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Packs.cs"), encoding="utf-8").read():
        print("FAIL the packs keep the old folder of the models library after it is moved", flush=True)
        bad.append("packs follow library")
    # (audit 1.78.5) the speed of the view: no scale-bar rays while the camera moves, no finishing effects and no safety
    # redraw in SmartView, safety redraw every 10 s; no shelter/mantle/coast checks after lights, names, saved scenes or
    # the sky alone; the automatic save waits for 20 s without input
    vj_ = open(os.path.join(ROOT, "app", "Simpler", "web", "viewer.js"), encoding="utf-8").read()
    sv_ = open(os.path.join(ROOT, "engine", "simpler", "server.py"), encoding="utf-8").read()
    fm_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.FileMenu.cs"), encoding="utf-8").read()
    if ("if (now - _scaleMoveAt < 250) return;" not in vj_ or "if (!fxActive() || _smartOn) return;" not in vj_
            or "if (idle && (_smartOn || now - lastDraw < 10000))" not in vj_
            or '"POST /api/light", "POST /api/rename", "POST /api/views/save", "POST /api/views/update")' not in sv_
            or 'if job.key == "POST /api/ambience":' not in sv_ or "if (InputIdleSeconds() < 20) return;" not in fm_):
        print("FAIL audit 1.78.5 speed fixes missing (scale bar, SmartView effects/redraw, non-geometry commands, autosave)", flush=True)
        bad.append("view speed audit")
    # (1.78.5, Luca: «continua a vedersi il realtime e non il path tracer») the path-traced picture asks a frame when it
    # appears: the canvas turns transparent over it (no more redraw every 2 s of a still view to do it by chance)
    if "if (!cyclesImg.classList.contains('on')) { cyclesImg.classList.add('on'); invalidate(300); }" not in vj_:
        print("FAIL the path-traced picture stays under the last real-time frame", flush=True)
        bad.append("path tracing shown")
    # (1.78.5, Luca: «non chiedere MAI conferma, tanto se uno cancella per sbaglio fa Ctrl+Z») deleting from the view
    # or the tree asks nothing (it asked only for objects with pieces inside: for some imported models yes, others no)
    tr_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Tree.cs"), encoding="utf-8").read()
    ds_ = tr_[tr_.find("async Task DeleteSelected()"):tr_.find("async Task MergeSelected()")]
    if not ds_ or "Msg.Show" in ds_:
        print("FAIL deleting objects asks for a confirmation again", flush=True)
        bad.append("delete without question")
    # (1.78.5, Luca: «continua a essere tagliata la seconda riga di testo») the library tiles are 130 px: picture 84 +
    # two lines of name 32 + padding 10 + border 2 leave no room for a top/bottom margin of the content
    import glob as _g
    for f_ in _g.glob(os.path.join(ROOT, "app", "Simpler", "*.cs")):
        if "var tile = new StackPanel { Width = 92, Margin = new Thickness(4) };" in open(f_, encoding="utf-8").read():
            print("FAIL the second line of the names is cut in the library tiles: " + os.path.basename(f_), flush=True)
            bad.append("tile names cut")
            break
    # (1.78.5, Luca: «cosa è questa approssimazione») the import wizard picture covers its panel (no white bands)
    if "readonly Image _picture = new Image { Stretch = Stretch.UniformToFill, VerticalAlignment = VerticalAlignment.Stretch" not in open(os.path.join(ROOT, "app", "Simpler", "MainWindow.ImportWizard.cs"), encoding="utf-8").read():
        print("FAIL the import wizard picture leaves white bands above and below", flush=True)
        bad.append("wizard picture fill")
    # (1.78.5, Luca: «ho eliminato l'auto … nella viewport si vede») a deleted model drawn from its prototype leaves the view
    if "node.traverse((c) => { if (scatter.nodes.has(c)) scatter.dirty = true; });" not in vj_:
        print("FAIL a deleted library model stays drawn in the view until it is touched", flush=True)
        bad.append("deleted model still drawn")
    # (1.78.5, Luca: «se elimino un folder padre i figli devono essere eliminati») deleting a folder takes its subfolders
    # with it (models, materials, ecosystems), what they contain goes to the folder above
    for f_ in ("models.py", "materials.py", "ecosystems.py"):
        src_ = open(os.path.join(ROOT, "engine", "simpler", f_), encoding="utf-8").read()
        if 'if action == "delete" and (f == path or f.startswith(path + "/")):' not in src_ or '(f == path or f.startswith(path + "/")))]' not in src_:
            print("FAIL deleting a folder leaves its subfolders: " + f_, flush=True)
            bad.append("folder delete subfolders")
            break
    # (1.79, Luca: «falli cosi chiudiamo anche i materiali simpler») the materials added by an update reach a library
    # that already exists, once (a deleted one stays deleted); their names and categories are translated
    mat_ = open(os.path.join(ROOT, "engine", "simpler", "materials.py"), encoding="utf-8").read()
    i18_ = open(os.path.join(ROOT, "engine", "simpler", "i18n.py"), encoding="utf-8").read()
    ns_ = {}
    exec(mat_[mat_.index("PRESETS = {"):mat_.index("PRESET_KEY")], ns_)
    exec(mat_[mat_.index("ADDED_PRESETS = ("):mat_.index("KNOWN_KEY")], ns_)
    miss_ = [w for k in ns_["ADDED_PRESETS"] for w in (ns_["PRESETS"][k][0], ns_["PRESETS"][k][1]) if '"%s":' % w not in i18_]
    if "_add_new_presets(d)" not in mat_ or "d[KNOWN_KEY] = sorted(PRESETS)" not in mat_ or miss_ \
            or any(k not in ns_["PRESETS"] for k in ns_["ADDED_PRESETS"]):
        print("FAIL the new materials of Simpler do not reach the library or are not translated: %s" % miss_[:5], flush=True)
        bad.append("new simpler materials")
    # (1.79, Luca: «aggiungi Vegetation come preferiti cartella Verde dopo 3D models») plants in a green folder
    fv_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Favorites.cs"), encoding="utf-8").read()
    if '("models", "Modelli 3D", Icons.Mesh), ("vegetation", "Vegetazione", Icons.Leaf)' not in fv_ \
            or 'if (IsVegFolder((string?)m?["folder"] ?? "")) return "vegetation";' not in fv_ or "FavGroupOf(f.Kind) ==" in fv_:
        print("FAIL the favourite plants are not in their own Vegetation folder", flush=True)
        bad.append("favourite vegetation")
    # (1.79, Luca: «anche ecosystem devono avere simpler e mine») Ecosistemi ▸ Simpler and I miei, each its own folder
    mw2_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.cs"), encoding="utf-8").read()
    ec_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Ecosystems.cs"), encoding="utf-8").read()
    lb_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Library.cs"), encoding="utf-8").read()
    if '("ecosystems", "simplereco", "Simpler"), ("ecosystems", "ecosystems", "I miei")' not in mw2_ \
            or 'bool Mine(string f) => simpler ? Under(f, SimplerEco) : !Under(f, SimplerEco);' not in ec_ \
            or 'if (_libraryTab is "ecosystems" or "simplereco") { RenderEcosystems(); return; }' not in lb_:
        print("FAIL the ecosystems have no Simpler and I miei", flush=True)
        bad.append("ecosystems simpler mine")
    # (1.79, Luca: «conviene per tutti uno sfondo bianco») the decal tiles on white
    dc_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Decals.cs"), encoding="utf-8").read()
    if "static readonly Brush DecalBack = Brushes.White;" not in dc_ or "DecalChecker" in dc_ or dc_.count("Background = DecalBack") < 2:
        print("FAIL the decal tiles are not on a white background", flush=True)
        bad.append("decal white tiles")
    # (1.79, Luca: «perché new folder è in fondo a destra? controlla che per ogni menu sia sempre a sinistra») in
    # every library view «Nuova cartella» comes before the folders
    for f_, nf_, loop_ in (("MainWindow.Ecosystems.cs", 'NewFolderTile("eco", cur)', "foreach (var f in _ecoFolders.Where(f => ParentFolder(f) == cur"),
                           ("MainWindow.LibraryFolders.cs", 'NewFolderTile("material", _matFolder)', "foreach (var f in all.Where(f => ParentFolder(f) == _matFolder)"),
                           ("MainWindow.ObjectLibrary.cs", 'NewFolderTile("model", _objFolder)', "foreach (var f in _modelFolders.Where(f => ParentFolder(f) == _objFolder"),
                           ("MainWindow.Vegetation.cs", 'NewFolderTile("model", cur)', "foreach (var f in _modelFolders.Where(f => ParentFolder(f) == cur"),
                           ("MainWindow.Decals.cs", 'L.T("Nuova cartella"), ""', "foreach (var sub in Directory.Exists(dir)")):
        src_ = open(os.path.join(ROOT, "app", "Simpler", f_), encoding="utf-8").read()
        a_, b_ = src_.find(nf_), src_.find(loop_)
        if a_ < 0 or b_ < 0 or a_ > b_:
            print("FAIL «Nuova cartella» is not before the folders: " + f_, flush=True)
            bad.append("new folder first")
            break
    # (1.79, Luca: «di nuovo!!! modello eliminato, nella treeview non c'è ma è ancora visibile») every node of an object
    # no longer in the scene leaves the view, also one the view did not have under its id
    vj_ = open(os.path.join(ROOT, "app", "Simpler", "web", "viewer.js"), encoding="utf-8").read()
    if "if (cid && !want.has(cid) && byId.get(cid) !== c && graveyard.get(cid) !== c) stray.push(c);" not in vj_ \
            or "stray nodes of removed objects taken away" not in vj_:
        print("FAIL a deleted model can stay drawn in the view", flush=True)
        bad.append("deleted model stray node")
    # (1.79, Luca: «in path tracing si vedono bene, in tempo reale sono pieni di buchi») a «blended» material whose
    # picture is opaque everywhere is drawn solid in the view (as Cycles sees it)
    if "function solidIfOpaque(m)" not in vj_ or "      solidIfOpaque(m);" not in vj_ or "m.transparent = false; m.depthWrite = true; m.alphaTest = 0;" not in vj_:
        print("FAIL opaque pictures plugged in the alpha make holes in the real-time view", flush=True)
        bad.append("opaque alpha holes")
    # (1.79, Luca: «TMI to Simpler ... solo in Pack Studio, mai in Simpler») the reader of the Twinmotion items and its
    # decompressor stay in the folder of Pack Studio: nothing of them in the app or in the engine of Simpler
    for sub_ in ("app", "engine"):
        for dp_, _dn, fn_ in os.walk(os.path.join(ROOT, sub_)):
            if any(x in dp_ for x in ("bin", "obj", "__pycache__")):
                continue
            for n_ in fn_:
                if not n_.endswith((".cs", ".py", ".js")):
                    continue
                t_ = open(os.path.join(dp_, n_), encoding="utf-8", errors="ignore").read()
                if "tmi2glb" in t_ or "kraken_decompressor" in t_ or "tmi_read" in t_:
                    print("FAIL the TMI reader is in Simpler: " + os.path.join(dp_, n_), flush=True)
                    bad.append("tmi in simpler")
    # (1.79, Luca: «è sparito il materiale asfalto ... e le decal delle righe della strada») opening a saved scene with a
    # sky keeps the ground of the scene (its material, the decals on it): no detour through a studio background
    vw_ = open(os.path.join(ROOT, "engine", "simpler", "views.py"), encoding="utf-8").read()
    if 'if (v.get("ambience") or {}).get("mode") not in ("sky", "hdri"):' not in vw_:
        print("FAIL opening a scene deletes the ground (its material and decals)", flush=True)
        bad.append("view keeps ground")
    # (Luca: «continua a togliere l'asfalto!») an unknown background id (an undo step saved with a photo background)
    # is refused before the sky and its ground are taken away
    so_ = open(os.path.join(ROOT, "engine", "simpler", "scene_ops.py"), encoding="utf-8").read()
    se_ = so_[so_.find("def set_environment("):]
    if se_.find("if env_id not in ENVIRONMENTS:") < 0 or se_.find("if env_id not in ENVIRONMENTS:") > se_.find("ambience._ground(None)"):
        print("FAIL an unknown background takes away the ground before failing", flush=True)
        bad.append("environment checked first")
    # (Luca: «ho trascinato il decal graffiti su un muro ... non lo ha messo») a drop while the view is busy is not
    # thrown away after 2 s without a word
    vp_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Viewport.cs"), encoding="utf-8").read()
    if "using (BeginBusy()) done = await Task.WhenAny(wait.Task, Task.Delay(20000));" not in vp_ or "La vista 3D non ha risposto" not in vp_:
        print("FAIL a drop on the view is lost without a message when the view is busy", flush=True)
        bad.append("view point waits")
    # (Luca: «Not converted: Autumn Leaves 01: not a library item of Twinmotion») the library items of Twinmotion 2023.2
    # and later are a database: read by tmi_db.py, chosen by tmi2glb.py before the reader of the records
    tdir_ = os.path.join(ROOT, "Simpler Pack Studio", "tmi")
    t2g_ = open(os.path.join(tdir_, "tmi2glb.py"), encoding="utf-8").read()
    if not os.path.exists(os.path.join(tdir_, "tmi_db.py")) or "tmi_db.read_item(path) if tmi_db.is_db(path)" not in t2g_:
        print("FAIL the .tmi files of Twinmotion 2023.2 and later (database) are not read", flush=True)
        bad.append("tmi database")
    # (Luca: «possiamo aggiungere un copia incolla? diversi ecosistemi hanno la stessa matrice») «Copia» on every
    # ecosystem (also a locked Simpler one), pasted as a copy by the engine
    ec_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Ecosystems.cs"), encoding="utf-8").read()
    lf_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.LibraryFolders.cs"), encoding="utf-8").read()
    ee_ = open(os.path.join(ROOT, "engine", "simpler", "ecosystems.py"), encoding="utf-8").read()
    if ec_.find('Item(L.T("Copia"), async () => { await Task.Yield(); CopyEco(id, name); });') < 0 \
            or ec_.find("CopyEco(id, name)") > ec_.find("if (ro) { btn.ContextMenu = cm;") \
            or "await PasteEcoCopy(c, target);" not in lf_ or "def copy(d):" not in ee_:
        print("FAIL no copy and paste for the ecosystems", flush=True)
        bad.append("ecosystem copy")
    # (Luca: «facendo click sulla miniatura dell'ecosistema … si apra nel pannello … in una modalità edit») the click opens
    # the ecosystem in the panel; «Modifica sul banco di prova» puts its layers back as scatters with fixed pieces that
    # the brush adds to and erases (paint BASE_KEY, kept by the view first in its pieces); «Salva modifiche» replaces it
    pt_ = open(os.path.join(ROOT, "engine", "simpler", "paint.py"), encoding="utf-8").read()
    vj_ = open(os.path.join(ROOT, "app", "Simpler", "web", "viewer.js"), encoding="utf-8").read()
    pc_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Paint.cs"), encoding="utf-8").read()
    if "btn.Click += async (_, __) => await OpenEcoInPanel(id);" not in ec_ or "def edit(d):" not in ee_ \
            or 'if d.get("replace"):' not in ee_ or "pts[BASE_KEY] = base" not in pt_ or "def base(d):" not in pt_ \
            or "base: alive.filter((it) => it.base).length" not in vj_ \
            or "(paint.strokes.length || paint.baseItems.length) && !paint.painting" not in vj_ or "pickModel(mulberry((paint.seed * 31" not in vj_ \
            or "EcoEditBar();" not in open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Props.cs"), encoding="utf-8").read() or "paintAddBase();\n  paint.strokes.forEach" not in vj_ \
            or 'api.Get("paint/base?group="' not in pc_ or "foreach (var sc in po.Children.Where(c => c.Paint && c.Eco == \"\"))" not in ec_:
        print("FAIL an ecosystem of the library cannot be opened and changed on the bench", flush=True)
        bad.append("ecosystem edit")
    # (Luca: «non dai più avanzamenti di versione … il solito file di News») the version of the app has its notes (it,
    # en) and its summary, and no change in the sources cites a version newer than it (a «(1.80 …» comment while the
    # app is still 1.79.0 = a delivery without a new version)
    csp_ = open(os.path.join(ROOT, "app", "Simpler", "Simpler.csproj"), encoding="utf-8").read()
    mv_ = re.search(r"<Version>(\d+\.\d+\.\d+)</Version>", csp_)
    ver_ = mv_.group(1) if mv_ else "0.0.0"
    vt_ = tuple(int(x) for x in ver_.split("."))
    import json
    summ_ = json.load(open(os.path.join(ROOT, "release-notes", "summaries.json"), encoding="utf-8"))
    miss_ = [f for f in (os.path.join(ROOT, "release-notes", f"Simpler-{ver_}.txt"), os.path.join(ROOT, "release-notes", "en", f"Simpler-{ver_}.txt"))
             if not os.path.isfile(f)]
    newer_ = set()
    srcs_ = [os.path.join(ROOT, "app", "Simpler", f) for f in os.listdir(os.path.join(ROOT, "app", "Simpler")) if f.endswith(".cs")]
    srcs_ += [os.path.join(ROOT, "app", "Simpler", "web", "viewer.js")]
    srcs_ += [os.path.join(ROOT, "engine", "simpler", f) for f in os.listdir(os.path.join(ROOT, "engine", "simpler")) if f.endswith(".py")]
    for f in srcs_:
        for m_ in re.finditer(r"\((1\.\d{2})(?:\.(\d{1,2}))?[,:) ]", open(f, encoding="utf-8").read()):
            v_ = (1, int(m_.group(1).split(".")[1]), int(m_.group(2) or 0))
            if v_ > vt_:
                newer_.add(".".join(map(str, v_)))
    if miss_ or ver_ not in summ_ or newer_:
        print(f"FAIL version {ver_} without its notes or summary, or sources citing a newer version: {miss_} {sorted(newer_)[:5]}", flush=True)
        bad.append("version notes")
    # (Luca: «perché questi materiali, eppure erano a posto») a texture the browser cannot show (TIFF, TGA, EXR) gets a
    # PNG copy for the real-time view, whatever its size: before, small or TIFF ones got nothing (white, solid leaves)
    px_ = open(os.path.join(ROOT, "engine", "simpler", "proxies.py"), encoding="utf-8").read()
    fx_ = px_[px_.find("def file_for("):px_.find("def proxy_map(")]
    if "made = _view_copy(src, px, srgb)" not in fx_ or "def _view_copy(src, px, srgb=False):" not in px_:
        print("FAIL TIFF/TGA textures are not sent to the real-time view", flush=True)
        bad.append("view tiff copy")
    # (Luca: alberi sopra altri alberi) the new distribution being painted (drawn under '' until it has its id) is not a
    # surface for its own brush
    vj_ = open(os.path.join(ROOT, "app", "Simpler", "web", "viewer.js"), encoding="utf-8").read()
    if "function paintingNew()" not in vj_ or "scatter.sets.has('') && !paintingNew()" not in vj_ \
            or "const set = paintingNew() ? null : scatter.sets.get('');" not in vj_:
        print("FAIL the brush puts pieces on the pieces it has just painted (trees on trees)", flush=True)
        bad.append("paint not on itself")
    # (Luca: cespugli con le foglie piene) the alpha cut-out of a glTF «MASK» material (1 - (alpha < cut-off)) is read
    vm_ = open(os.path.join(ROOT, "engine", "simpler", "matedit.py"), encoding="utf-8").read()
    if 't[0].operation == "LESS_THAN" and t[0].inputs[0].is_linked' not in vm_:
        print("FAIL the leaves of glTF models with an alpha mask come out solid", flush=True)
        bad.append("gltf alpha mask")
    # (Luca: «se ne apro un altro devo poterlo vedere, non rimanere intrappolato nel precedente») a click on an ecosystem
    # opens it on the bench (what was there, changed: asked first); «Salva come nuovo» keeps it open; a selected scatter
    # of the bench does not cut the others out of the save
    ec_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Ecosystems.cs"), encoding="utf-8").read()
    ee_ = open(os.path.join(ROOT, "engine", "simpler", "ecosystems.py"), encoding="utf-8").read()
    op_ = ec_[ec_.find("async Task OpenEcoInPanel("):ec_.find("bool _ecoOpening;")]
    if "await LeaveBench(st)" not in op_ or "await EditEcosystem(id, name, true)" not in op_ \
            or "nb.Click += async (_, __) => await NewEcosystem();" not in ec_ \
            or "!(plot != \"\" && _scene.Ancestors(o).Any(a => a.Id == plot))" not in ec_ \
            or "plot[EDIT_KEY] = eid                        # («Salva come nuovo»" not in ee_ \
            or "plot[SIG_KEY] = _bench_sig(plot)" not in ee_ or "changed=bool(sig) and sig !=" not in ee_:
        print("FAIL a click on an ecosystem does not open it on the bench (or the bench is left without asking)", flush=True)
        bad.append("eco open")
    # (Luca: «come salvo questo ecosistema … un'interfaccia chiara»; «salva in libreria mi mostra tutta la libreria tranne
    # gli ecosistemi») the scatters selected (or of the object selected) are saved as an ecosystem from the properties,
    # the Scatter panel and «Salva nella libreria…» of the tree, among the folders of the ecosystems
    pp_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Props.cs"), encoding="utf-8").read()
    ol_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.ObjectLibrary.cs"), encoding="utf-8").read()
    if "EcoSaveBar();" not in pp_ or "void EcoSaveBar()" not in ec_ or "await SaveEcosystemOf(ids, bench ? \"\" : o.Name)" not in ec_ \
            or "await SaveEcosystemOf(ecoIds, ecoBench ? \"\" : o.Name)" not in ol_ \
            or "_ecoFolders.Where(f => !ReadOnlyEco(f)), L.T(\"Ecosistemi (cartella principale)\")" not in ec_:
        print("FAIL the scatters of the scene cannot be saved as an ecosystem from where they are", flush=True)
        bad.append("eco save bar")
    # (Luca: «come esco da qui!!») the bench has a way out: in its blue note and in the panels; the scene comes back
    vj2_ = open(os.path.join(ROOT, "app", "Simpler", "web", "viewer.js"), encoding="utf-8").read()
    vp_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Viewport.cs"), encoding="utf-8").read()
    if "post({ type: 'benchExit' })" not in vj2_ or 'case "benchExit":' not in vp_ or "api.Post(\"ecosystems/close\"" not in ec_ \
            or "def close(_d=None):" not in ee_ or "plot[HIDDEN_KEY] = json.dumps(" not in ee_:
        print("FAIL no way out of the ecosystem bench (the scene stays hidden)", flush=True)
        bad.append("bench exit")
    # (Luca: «se è una vegetazione puoi aggiungere season, così posso fare un mix di colori di foglie») a season per model
    # of the scatter: each piece its own (the same hash in the view and in the engine), read by the leaves in both
    pa_ = open(os.path.join(ROOT, "engine", "simpler", "paint.py"), encoding="utf-8").read()
    me_ = open(os.path.join(ROOT, "engine", "simpler", "matedit.py"), encoding="utf-8").read()
    pc_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Paint.cs"), encoding="utf-8").read()
    if "pts = _points_object(group, coll, xf, mi, sea)" not in pa_ or "_season_materials(coll, sea, mi)" not in pa_ \
            or 'attribute_type="INSTANCER", attribute_name=PIECE_SEASON' not in me_ \
            or "vFoS = foSea - 1.0;" not in vj2_ or "seas[k][fill[k]] = seasonOf(" not in vj2_ or "e.sea[e.n] = seasonOf(" not in vj2_ \
            or "h = (h * 0x45D9F3B) & 0xFFFFFFFF" not in pa_ or "Math.imul(h, 0x45D9F3B)" not in vj2_ \
            or 'Item(L.T("Stagione casuale")' not in pc_ or 'season = Season, seasonRand = SeasonRand' not in pc_:
        print("FAIL the season of each model of a scatter is lost (view, render or panel)", flush=True)
        bad.append("scatter season")
    # (Luca: «parallax room») the material type «Interni»: the same interior mapping in Cycles and in the view, its room
    mm_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Materials.cs"), encoding="utf-8").read()
    if "def interior(self, bsdf, it):" not in me_ or "self.interior(bsdf, itr)" not in me_ or "function useInterior(m, it)" not in vj2_ \
            or "if (p.interior && p.interior.image) useInterior(m, p.interior);" not in vj2_ or 'Bo("interior.enabled")' not in mm_ \
            or not os.path.isfile(os.path.join(ROOT, "engine", "assets", "interiors", "room_test.jpg")):
        print("FAIL the material type Interni is incomplete (Cycles, view, panel or its room picture)", flush=True)
        bad.append("interior")
    # (Luca: «è giusto che si veda cosi in 4 sezioni? serve anche la versione notturna») the rooms start from the lowest corner
    # of the object (not its origin) and the night lights follow the Ambiente, the same in the view and in the render
    dk_ = open(os.path.join(ROOT, "engine", "simpler", "dusk.py"), encoding="utf-8").read()
    rd_ = open(os.path.join(ROOT, "engine", "simpler", "render.py"), encoding="utf-8").read()
    if "def interior_pass(mats=None):" not in me_ or rd_.count("matedit.interior_pass()") < 2 or "INTERIOR_NIGHT_NODE" not in dk_ \
            or "un.inMin.value.copy(_inLo)" not in vj2_ or "uniform vec3 inKel; uniform vec3 inMin;" not in vj2_ \
            or 'MatToggle(sp, L.T("Luci accese"), "interior.lightsOn"' not in mm_:
        print("FAIL the rooms of Interni are not aligned to the object or their night lights are missing", flush=True)
        bad.append("interior night")
    # (Luca: «se light on è spento di notte la stanza NON deve emettere luce mentre in realtà lo fa») the light of the
    # rooms faint when the Ambiente is dark, in the render (node updated by dusk.py) and in the view
    if "def interior_bright(it, dark=None):" not in me_ or "INTERIOR_DARK_ROOM = 0.005" not in me_ or '"interior.bright", 0.4, 0.001, 20, true, "0.###"' not in open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Materials.cs"), encoding="utf-8").read() \
            or "bright.name = INTERIOR_BRIGHT_NODE" not in me_ or "matedit.INTERIOR_BRIGHT_NODE" not in dk_ \
            or '"bright": _me.interior_bright(it)' not in open(os.path.join(ROOT, "engine", "simpler", "materials.py"), encoding="utf-8").read():
        print("FAIL the rooms of Interni still give their daylight at night with the lights off", flush=True)
        bad.append("interior dark room")
    # (Luca: «il gizmo della decal non è rettangolare … su un sacco tondeggiante vorrei un buon risultato») the decal
    # fades by «Angolo massimo» in the render (facing attribute) and in the view (folded into the fade of mesh())
    dc_ = open(os.path.join(ROOT, "engine", "simpler", "decals.py"), encoding="utf-8").read()
    if "def angle_fade(p, facing):" not in dc_ or '"decal_facing"' not in dc_ or '"angle": NEW_ANGLE' not in dc_ \
            or "keep = angle_fade(p, abs(nv.normalized().z))" not in dc_ \
            or 'L.T("Angolo massimo"), V("angle", 90)' not in open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Decals.cs"), encoding="utf-8").read():
        print("FAIL the decals have no «Angolo massimo» fade in the render or the view", flush=True)
        bad.append("decal angle")
    # (Luca: «sul pavimento bagnato non si vedono») a decal whose file changed is not dropped with the old picture
    if "def _load(path):" not in dc_ or "check_existing=False" not in dc_ or "    im = _load(path)" not in dc_:
        print("FAIL a decal of the library changed on disk is still dropped with the picture already in the project", flush=True)
        bad.append("decal reload")
    # (Luca: «quando clicco su un oggetto parte il box rosso di aggiornamento dei materiali») a gizmo click without a
    # move sends no transform (the engine would look again at the rain shelter and the materials)
    if "const moved = items.some((it) => { it.obj.updateMatrixWorld(true); return !it.obj.matrixWorld.equals(it.m0); });" not in vj2_:
        print("FAIL a click on the gizmo without moving still sends a transform", flush=True)
        bad.append("gizmo click")
    # (14/11, Luca: «il 39 che avevo messo non era stato preso») a slider compares what it shows with what it sent and sends
    # late a value whose release never arrived; (log of Luca) the type of the shadows is the one three.js really uses, or
    # every shader of the opening is made twice; in path tracing a change from the app keeps the picture (no real-time
    # shaders made under it, every pass shown); the programs of the outline are made with the others, not at a click
    ct14_ = open(os.path.join(ROOT, "app", "Simpler", "Controls.cs"), encoding="utf-8").read()
    if 'SendIfChanged("sent late (mouse over the slider)")' not in ct14_ or "e.LeftButton != MouseButtonState.Pressed" not in ct14_ \
            or "if (!notify && !_dragging) _sent = v;" not in ct14_:
        print("FAIL a slider can show a value that was never sent", flush=True)
        bad.append("slider sent")
    if "renderer.shadowMap.type = THREE.PCFShadowMap;" not in vj2_ or "PCFSoftShadowMap;" in vj2_:
        print("FAIL the shadow type is not the one three.js uses: every shader is made twice at the opening", flush=True)
        bad.append("shadow type")
    if "const keep = cyclesImg.classList.contains('on') && !interacting" not in vj2_ or "if (_wasPtOn && !ptOn && realistic) {" not in vj2_ \
            or "function warmOutline()" not in vj2_ or "    warmOutline();" not in vj2_:
        print("FAIL path tracing: the picture goes away at a change from the app, or the outline makes its shaders at a click", flush=True)
        bad.append("pt keep")
    # (14/11 sera, measured on Luca's card and found in his log) a thumbnail never hides a light (the spare lights are helpers:
    # hiding them changed the number of lights - «slow frame: 101390 ms, 63 new shaders» at every thumbnail); the lights of the
    # scene file are out of every layer (they were counted in every shader); the mask of the outline sees all the lights of
    # the frame; each light once in lightList; the real-time view knows 12 lights; the cache of shaders of WebView2 is large
    vp14_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Viewport.cs"), encoding="utf-8-sig").read()
    if "!o.userData.glow && !o.isLight) hide(o);" not in vj2_ or "o.layers.disableAll(); }" not in vj2_ \
            or "const lit = lightList()" not in vj2_ or "return [...new Set([key, fill.light, fallbackHemi" not in vj2_ \
            or "cap: { DirectionalLight: 2, DirectionalLights: 2, PointLight: 4, SpotLight: 3, SpotLights: 1 }" not in vj2_ \
            or "const RT_BUDGET = { PointLight: 2, SpotLight: 2 };" not in vj2_ or "--gpu-program-cache-size-kb=" not in vp14_:
        print("FAIL the number of lights of the shaders can change (thumbnail, lights of the scene file, outline) or the budget / the cache of shaders is not the measured one", flush=True)
        bad.append("light state")
    # (15/11, classes of «shader made inside a frame» found in Luca's log) with glass in the scene the shaders of the picture seen
    # through the glass and of the glasses seen from behind are prepared before (tools/glass_check.js reproduces it); the log says
    # why a shader was made inside a frame; the view started again after the video card closed it gets its framing back
    vp15_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Viewport.cs"), encoding="utf-8-sig").read()
    if "function sceneGlass()" not in vj2_ or "for (const m of glass.twoSided) m.side = THREE.BackSide;" not in vj2_ \
            or "function shaderWhy(made, before)" not in vj2_ or "view started again: framing put back" not in vp15_ \
            or not os.path.exists(os.path.join(ROOT, "tools", "glass_check.js")):
        print("FAIL glass: its shaders are made inside a frame again, or the log no longer says why, or a restarted view loses its framing", flush=True)
        bad.append("glass shaders")
    # (15/11, Luca: «l'area azzurra è uscita fuori dal bordo… si sposta e basta») the plane sector of the move gizmo, shown again
    # when the plane is seen almost edge-on, has the size of the gizmo (it came back at size 1: near the camera it covered the
    # arcs and took every press - tools/gizmo_sector_check.js reproduces it); the rotation sector is drawn only while turning
    if "h.scale.setScalar(gizmoScreenFactor(this));" not in vj2_ or "if (gizmo.dragging) drawSector();" not in vj2_ \
            or not os.path.exists(os.path.join(ROOT, "tools", "gizmo_sector_check.js")):
        print("FAIL gizmo: the plane sector seen edge-on has not the size of the gizmo, or the rotation sector is drawn at rest", flush=True)
        bad.append("gizmo sector")
    # (15/11 night, two classes from Luca's log) the marks of the materials «let pass» after 3 empty checks pass only when they come
    # from a material known to mark for nothing and whose shader is still the right one (the rain turned on marked them all and
    # they were made inside a frame: tools/rain_shader_check.js); the view always has its fog, at density 0 with none, so fog on
    # and off make no new shader (104 new shaders and a frame of 57 s: tools/fog_shader_check.js)
    if "function marksPassable()" not in vj2_ or "&& !_shaderNew && marksPassable()) {" not in vj2_ \
            or "_shaderRev++; _marked.add(this);" not in vj2_ or "function noFog()" not in vj2_ or "scene.fog = null;\n      renderer.toneMappingExposure" in vj2_ \
            or "} else scene.fog = null;" in vj2_ or "function shaderOwner(pr)" not in vj2_ \
            or not os.path.exists(os.path.join(ROOT, "tools", "rain_shader_check.js")) or not os.path.exists(os.path.join(ROOT, "tools", "fog_shader_check.js")):
        print("FAIL shaders: a change of the rain or of the fog makes shaders inside a frame again (marks let pass blindly, or the fog taken away from the view)", flush=True)
        bad.append("rain/fog shaders")
    # (15/11, Luca: «ho due montagne… volevo continuare lo scatter lì sopra ma non funziona») a model put in the scene from the
    # library (drawn from its prototype) is a surface for the brush, the area and the cursor (tools/piece_surface_check.js)
    if "function pieceSurfaces(near)" not in vj2_ or "out.push(...pieceSurfaces((sp) => sp.intersectsSphere(sph)));" not in vj2_ \
            or "for (const o of pieceSurfaces(null)) {" not in vj2_ or "function paintMaxItems() { return PAINT_MAX_ITEMS; }" not in vj2_ \
            or not os.path.exists(os.path.join(ROOT, "tools", "piece_surface_check.js")):
        print("FAIL brush: a model from the library is not a surface for it, or the limit of a distribution counts triangles again", flush=True)
        bad.append("brush surfaces")
    # (16/11, the last class at the opening in Luca's log: «(depth, 13 kB) … +instancing») the shaders of the shadows are prepared
    # with the others, one stand-in per kind of thing that casts a shadow (tools/shadow_warm_check.js)
    if "function shadowWarmScene()" not in vj2_ or "p3 = renderer.compileAsync(sh, camera, scene);" not in vj2_ \
            or not os.path.exists(os.path.join(ROOT, "tools", "shadow_warm_check.js")):
        print("FAIL shadows: their shaders are made inside a frame again (no preparation of the shadow shaders)", flush=True)
        bad.append("shadow shaders")
    # (Luca: «non puoi fare una verifica preventiva») the engine does nothing for matrices the objects already have,
    # and a slider pressed and released without a change sends no edit
    sv_ = open(os.path.join(ROOT, "engine", "simpler", "server.py"), encoding="utf-8").read()
    ct_ = open(os.path.join(ROOT, "app", "Simpler", "Controls.cs"), encoding="utf-8").read()
    if "def _same_matrices(d):" not in sv_ or 'and _same_matrices(job.data):' not in sv_ \
            or "if (Math.Abs(_value - _sent) < 1e-12) return;" not in ct_ or 'if (commit) SendIfChanged("let go");' not in ct_:
        print("FAIL an action that changes nothing still makes the engine update the scene", flush=True)
        bad.append("no-op actions")
    # (Luca: «con eyedropper clicco sul pavimento … No material on that surface») the eyedropper looks past decals
    if "isVisible(h.object) && h.object.isMesh && !h.object.userData.decalMesh && !h.object.userData.helper);" not in vj2_:
        print("FAIL the material eyedropper stops on a decal instead of the surface under it", flush=True)
        bad.append("eyedropper decal")
    # (Luca, «test GI»: «non possiamo avere esposizione a zero di default») the exposure opens up on dark framings,
    # in the view, the final render (job included) and the real-time view; new projects with «Contrasto base»
    rd_ = open(os.path.join(ROOT, "engine", "simpler", "render.py"), encoding="utf-8").read()
    rj_ = open(os.path.join(ROOT, "engine", "render_job.py"), encoding="utf-8").read()
    am_ = open(os.path.join(ROOT, "engine", "simpler", "ambience.py"), encoding="utf-8").read()
    mr_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Render.cs"), encoding="utf-8").read()
    if 'scene.view_settings.exposure = c["exposure"] + exposure_auto()' not in rd_ \
            or "_meter_store(meter.measure(scene, STATE.tmp), epoch0)" not in rd_ \
            or "_meter_final(scene, width, height, fresh, own_process)" not in rd_ \
            or 'look="AgX - Base Contrast"' not in rd_ or "meterExposure=True" not in rd_ \
            or '_expose(_m.measure(scene, _dir))' not in rj_ or '"ev": _auto_total(),' not in am_ \
            or 'Switch(L.T("Esposizione sull\'inquadratura"), "meterExposure"' not in mr_:
        print("FAIL the exposure on the framing is not used everywhere (view, final render, real-time view, panel)", flush=True)
        bad.append("meter exposure")
    # (Luca: «ero su scene 4 ho cliccato su scene 2 e la miniatura della 4 si è trasferita sulla due») the path traced
    # thumbnail goes only to the scene that was open when its picture was finished
    lb_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Library.cs"), encoding="utf-8").read()
    if "if (_appliedView != id) { AppLog.Write(\"path traced thumbnail: another scene was opened meanwhile\"); return; }" not in lb_ \
            or 'api.Post("views/ptthumb", new { id, thumb })' not in lb_:
        print("FAIL the path traced thumbnail can go to a scene opened while it waited", flush=True)
        bad.append("ptthumb scene")
    # (Luca: «sposto lo slider sotto e quello sopra cambia e torna a un valore precedente!!») a panel is never made again
    # under a slider held or a number being typed, and a reading of the Ambiente never overwrites a change sent after it
    ct2_ = open(os.path.join(ROOT, "app", "Simpler", "Controls.cs"), encoding="utf-8").read()
    pp_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Props.cs"), encoding="utf-8").read()
    ma_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Ambience.cs"), encoding="utf-8").read()
    if "public static bool Interacting =>" not in ct2_ or "_bar.LostMouseCapture += (_, __) => EndDrag(true);" not in ct2_ \
            or "if (ValueSlider.Interacting)" not in pp_ or "ValueSlider.InteractionEnded += PropsAfterInteraction;" not in pp_ \
            or "if (seq == _ambSeq) _ambience = r;" not in ma_ or "var mine = ++_ambSeq;" not in ma_ \
            or "if (path == \"ambience\") OverlayAmbience(body);" not in ma_ or "CheckAmbienceEcho(body, r);" not in ma_:
        print("FAIL a panel can be made again under a slider held (the value goes back, nothing is sent)", flush=True)
        bad.append("slider held")
    # (Luca: «sculpt neve footprint non va niente!» - the steps under the snow of the grass of an ecosystem) the copies
    # of distributions in a footprint, a tyre track or a dug place are pressed into the snow: path tracing, view, mantle
    sn_ = open(os.path.join(ROOT, "engine", "simpler", "snow.py"), encoding="utf-8").read()
    pa_ = open(os.path.join(ROOT, "engine", "simpler", "paint.py"), encoding="utf-8").read()
    ss_ = open(os.path.join(ROOT, "engine", "simpler", "snowsculpt.py"), encoding="utf-8").read()
    if "def press_update():" not in sn_ or "mi = np.where(pr, -1, mi)" not in sn_ or 'base = str(_signature(st)) + f"/p{PRESS[\'rev\']}"' not in sn_ \
            or "dl.name = PRESS_NODE" not in pa_ or "def press_node(po):" not in pa_ or "pr = snow.pressed_of(pts, n)" not in pa_ \
            or "snow.press_update()          # (1.79.0)" not in ss_ or "inf.pressRev !== WET.pressRev" not in vj2_:
        print("FAIL the copies of distributions are not pressed by the sculpted snow (footprints hidden under the grass)", flush=True)
        bad.append("snow pressed copies")
    # (Luca: «nel pack studio questo è sbagliato! non è vero che vanno in 3d models\\simpler ma vanno nella cartella
    # package … scrivi in blu») the packs made show where their models really go, in the blue of the packs
    sp_ = open(os.path.join(ROOT, "Simpler Pack Studio", "StudioPanel.cs"), encoding="utf-8").read()
    if "PackInstaller.PackPath((string?)x[\"path\"], title)" not in sp_ or "Line(Icons.Folder, d, PackBlue);" not in sp_ \
            or "models.GroupBy(x => MadePackFolder(x, title))" not in sp_ or '" ▸ Simpler" + (((string?)x["path"]' in sp_:
        print("FAIL Pack Studio says the models of a pack go to Simpler instead of Packages", flush=True)
        bad.append("pack destination")
    # (Luca: «un progetto che HA SEMPRE FUNZIONATO mostra questo nel path tracer» - pink ecosystems after opening, put
    # right by «Ricalcola»; «all'apertura forziamo un ricalcolo … degli ecosistemi») the ecosystems made again on opening
    sv3_ = open(os.path.join(ROOT, "engine", "simpler", "server.py"), encoding="utf-8").read()
    if "def _ecosystems_after_open():" not in sv3_ or "    _ecosystems_after_open()\n    return {\"path\": path" not in sv3_:
        print("FAIL the ecosystems are not made again when a project is opened (pink plants in the path tracing)", flush=True)
        bad.append("eco after open")
    # (Luca: «un tasto Roadmap prima di free model … free model deve aprire una pagina che elenca i vari siti») the Roadmap
    # tile in the language of Simpler, and every website of the free models page allowed to open
    id_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Ideas.cs"), encoding="utf-8").read()
    st_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Story.cs"), encoding="utf-8").read()
    fp_ = open(os.path.join(ROOT, "server", "free", "index.php"), encoding="utf-8").read()
    import re as _re
    hosts = set(_re.findall(r"'url' => 'https://([^/']+)", fp_))
    missing = [h for h in hosts if '"' + h + '"' not in id_]
    # (Luca 19/11: the roadmap of Simpler is the copy without links, simpler/inapp/roadmap-en|it.html)
    if '"https://www.rodluc.com/simpler/inapp/roadmap-"' not in id_ or '"/simpler/inapp/"' not in id_ \
            or st_.find("RoadmapTile()") < 0 or st_.find("RoadmapTile()") > st_.find("FreeTile()") or missing:
        print("FAIL the Roadmap tile or the websites of the free models page:", missing, flush=True)
        bad.append("site tiles")
    # (Luca: «in pack studio metti le istruzioni (sia per l'aggiornamento di versione che per i package) … perchè ho
    # l'impressione che me ne dimenticherò») the release steps in Pack Studio: header button, at start, both sections
    sh_ = open(os.path.join(ROOT, "Simpler Pack Studio", "StudioHelp.cs"), encoding="utf-8").read()
    ms_ = open(os.path.join(ROOT, "Simpler Pack Studio", "MainWindow.Studio.cs"), encoding="utf-8").read()
    if 'HeaderButton(Icons.Help, S("Come rilasciare", "How to release")' not in ms_ or "ReleaseHelpAtStart();" not in ms_ \
            or "1 · Nuova versione di Simpler" not in sh_ or "2 · Nuovo pacchetto" not in sh_ or "latest.json" not in sh_ \
            or "Non mostrare all'avvio" not in sh_:
        print("FAIL the release steps (version and pack) are missing from Pack Studio", flush=True)
        bad.append("release help")
    # (Luca: «immaginati fra qualche mese ci sono 5 pacchetti rilasciati e l'utente ne ha installati 3 come lo aiutiamo a
    # fare ordine … si chiama SIMPLER non può essere complicato») one window «Pacchetti…» (installed, new, updates), the
    # blue strip once a day, downloads only by file name from rodluc.com checked by size and SHA-256, and Pack Studio
    # writing the list for the site at every «Segna rilasciato»
    ps_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.PackStore.cs"), encoding="utf-8").read()
    pc_ = open(os.path.join(ROOT, "app", "Simpler", "PackCatalog.cs"), encoding="utf-8").read()
    up_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Updates.cs"), encoding="utf-8").read()
    im2_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.ImportWizard.cs"), encoding="utf-8").read()
    ss_ = open(os.path.join(ROOT, "Simpler Pack Studio", "StudioSite.cs"), encoding="utf-8").read()
    sp2_ = open(os.path.join(ROOT, "Simpler Pack Studio", "StudioPanel.cs"), encoding="utf-8").read()
    if 'L.F("Tutti ({0})"' not in ps_ or 'L.F("Installati ({0})"' not in ps_ or 'L.F("Da installare ({0})"' not in ps_ \
            or "await _mw.InstallPackFrom(this, file)" not in ps_ or "_ = PackNewsCheck();" not in up_ \
            or 'public const string Base = "https://www.rodluc.com/simpler/packs/";' not in pc_ \
            or 'Hash(part) != e.Sha256' not in pc_ or "!SafeName(e.File)" not in pc_ \
            or 'L.T("Pacchetti…")' not in im2_ or 'L.T("Installa un pacchetto da file…")' not in im2_ \
            or "if (SiteDir() != null) _ = PrepareSite(false);" not in sp2_ or 'mimeMap fileExtension="".simplerpack""' not in ss_:
        print("FAIL the window of the packs, its strip, the safe download or the list for the site", flush=True)
        bad.append("pack store")
    # (Luca: «controlla che tutte abbiano l'icona») every first-level folder of the red «Simpler» libraries has an icon
    lf_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.LibraryFolders.cs"), encoding="utf-8").read()
    rules_ = [re.findall(r'"([^"]*)"', m.group(1)) for m in re.finditer(r'\(new\[\] \{([^}]*)\}, Icons\.\w+\)', lf_)]
    simpler_names_ = ["Animals", "Bushes", "Characters", "Cracks", "Dirt and grime", "Fabrics", "Flowers", "Footprints",
                      "Furniture", "Garden and terrace", "Gems", "Glass", "Graffiti", "Grass", "Grasses and plants",
                      "Interiors", "Lights", "Liquids", "Metals", "Nature", "Office", "Paints", "Palms", "Plastics & Rubber",
                      "Primitives", "Rust and leaks", "Sci-fi", "Statues", "Street furniture", "Surfaces", "Trash", "Trees",
                      "Tyre tracks", "Vehicles", "Volumes", "Water stains", "Woods"]
    noicon_ = [n for n in simpler_names_ if not any(any(w.startswith(k) for w in re.split(r"[^a-z]+", n.lower()) if w
                                                      for k in keys) for keys in rules_)]
    if noicon_:
        print("FAIL folders of the Simpler libraries without an icon:", noicon_, flush=True)
        bad.append("folder icons")
    # (Luca: «nel menu si possono togliere materiali dalle cartelle rosse») the red folders allow no change: the menu of
    # a Simpler material has no cut, move, restore or remove; the engine refuses them for the built-in materials and the ecosystems
    ml_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Library.cs"), encoding="utf-8").read()
    mo_ = open(os.path.join(ROOT, "engine", "simpler", "materials.py"), encoding="utf-8").read()
    md_ = open(os.path.join(ROOT, "engine", "simpler", "models.py"), encoding="utf-8").read()
    mm2_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Materials.cs"), encoding="utf-8").read()
    if ("var roMat = SimplerLocked && InSimplerMats(node);" not in ml_ or "if (!roMat) AddMoveMenu(" not in ml_
            or "if (SimplerLocked && InSimplerMats(node)) return m;" not in mm2_ or "bool libRo = SimplerLocked" not in mm2_
            or "InSimplerMatPath(folder))) { Status(" not in lf_
            or 'e = library_entry(mid or "")' not in mo_ or '"POST /api/material/library/reset"' not in mo_
            or "def _eco_lock_check(" not in md_ or not os.path.exists(os.path.join(ROOT, "tools", "lock_check_stub.py"))):
        print("FAIL the red Simpler folders still allow a change (menu of the materials, engine for materials and ecosystems)", flush=True)
        bad.append("red folders read only")
    # (1.80.0) «Prepara i contenuti per il sito»: only the red Simpler folders, a zip per asset, the signed list
    sc_ = open(os.path.join(ROOT, "Simpler Pack Studio", "StudioContent.cs"), encoding="utf-8").read()
    sm_ = open(os.path.join(ROOT, "Simpler Pack Studio", "MainWindow.Studio.cs"), encoding="utf-8").read()
    if ("public static bool IsSimplerFolder(" not in sc_ or 'File.WriteAllText(Path.Combine(outDir, "catalog.sig"), PackKeys.Sign(cbytes)' not in sc_
            or "outside the Simpler folders" not in sc_ or "OpenContentWizard()" not in sm_):
        print("FAIL the content for the site (Simpler folders only, signed catalog, menu of Pack Studio)", flush=True)
        bad.append("site content")
    # (1.80.0) the contents in the cloud, app side: only a signed list is believed, the file is checked (size, SHA-256, safe
    # paths) before it is moved in, a command to the engine downloads what it names first, the library shows cloud and tick
    cs_ = open(os.path.join(ROOT, "app", "Simpler", "ContentStore.cs"), encoding="utf-8").read()
    cw_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Content.cs"), encoding="utf-8").read()
    en_ = open(os.path.join(ROOT, "app", "Simpler", "Engine.cs"), encoding="utf-8").read()
    ol_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.ObjectLibrary.cs"), encoding="utf-8").read()
    ec_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Ecosystems.cs"), encoding="utf-8").read()
    mw_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.cs"), encoding="utf-8").read()
    mc_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Commands.cs"), encoding="utf-8").read()
    wk_ = open(os.path.join(ROOT, "server", "content", "worker.js"), encoding="utf-8").read()
    base_ = re.search(r'DefaultBase = "https://[^"/]+/([A-Za-z0-9]+)/"', cs_)
    if (not base_ or len(base_.group(1)) < 24 or "env.SECRET" not in wk_       # (the secret part is only in the Worker online and in the app)
            or "if (!Verify(data, sig)) throw new ContentException(\"signature\")" not in cs_
            or "if (sha != a.Sha256)" not in cs_ or "!dest.StartsWith(root," not in cs_ or "Range = new System.Net.Http.Headers.RangeHeaderValue(have, null)" not in cs_ and "req.Headers.Range = new System.Net.Http.Headers.RangeHeaderValue(have, null)" not in cs_
            or "if (BeforePost != null) await BeforePost(json, ct)" not in en_
            or "EngineClient.BeforePost = EnsureContentForRequest" not in cw_ or "InitContentAsync()" not in mw_
            or "MergeCloudModels();" not in ol_ or "MergeCloudEcosystems();" not in ec_ or "if (cloud) { await DownloadCloud(id); return; }" not in ol_
            or "AddCloudBadge(" not in ol_ or "AddCloudBadge(" not in ec_ or "RestoreContentTextures(missingTex)" not in mc_
            or "RemoveCloud(id)" not in ol_ or "RemoveCloud(id)" not in ec_ or "SimplerLocked" not in cw_.split("bool ContentOn")[1][:120]):
        print("FAIL the contents in the cloud (signed list, checked download, download before a command, tiles, project open)", flush=True)
        bad.append("cloud content")
    # (1.80.0, Luca: «aggiornare i modelli quando cambia il catalogo») a model of the cloud with a newer rev: the orange arrow beside
    # the tick, «Aggiorna» / «Aggiorna tutti», the new files put over the old ones (the old textures stay: saved projects read them)
    cs2_ = open(os.path.join(ROOT, "app", "Simpler", "ContentStore.cs"), encoding="utf-8-sig").read()
    cw2_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Content.cs"), encoding="utf-8-sig").read()
    ol2_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.ObjectLibrary.cs"), encoding="utf-8-sig").read()
    ec2_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Ecosystems.cs"), encoding="utf-8-sig").read()
    vg2_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Vegetation.cs"), encoding="utf-8-sig").read()
    if ("public static bool NeedsUpdate(" not in cs2_ or "public static string InstalledRev(" not in cs2_ or "var update = Directory.Exists(target)" not in cs2_
            or "File.Move(f, dest, true)" not in cs2_ or "Directory.Delete(target, true);\n                    Directory.Move(folder, target);" not in cs2_.replace("\r\n", "\n")
            or "async Task UpdateContent(" not in cw2_ or "FrameworkElement? UpdateAllTile()" not in cw2_ or "async Task RunInstalls(" not in cw2_
            or "ContentStore.NeedsUpdate(ca, _contentModelsDir)" not in cw2_ or "ContentStore.NeedsUpdate(ca, _contentEcoDir)" not in cw2_
            or "AddCloudBadge(visual, 80, id, cloud, inCat, upd)" not in ol2_ or "AddCloudBadge(picture, 72, id, cloud, inCat, upd)" not in ec2_
            or "UpdateAllTile()" not in vg2_ or "UpdateAllTile()" not in ec2_ or "if (cloud) { await DownloadCloud(id); return; }" not in ol2_):
        print("FAIL the update of the models of the cloud (arrow, update all, files put over the old ones)", flush=True)
        bad.append("cloud update")
    # (Luca: «ogni cambio di slider o valore DEVE mostrare la modifica») the view: a last redraw after every message of the app, the
    # messages not held for ever by a model loading, a setting moved in a distribution panel always made again, the delays in the log
    vj_ = open(os.path.join(ROOT, "app", "Simpler", "web", "viewer.js"), encoding="utf-8").read()
    pt_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Paint.cs"), encoding="utf-8-sig").read()
    if ("function settleRedraw(type)" not in vj_ or "    settleRedraw(msg.type);\n  }\n  if (msg && msg.type === 'addPart')" not in vj_ or "const SETTLE_SKIP = new Set(" not in vj_
            or "a model is loading for more than 25 s" not in vj_ or "viewLog(`update late:" not in vj_
            or "if (msg.regen && msg.group === undefined" not in vj_ or "areaRebuild(true).catch(" not in vj_
            or "SendPaint(true);" not in pt_ or "void SendPaint(bool regen = false)" not in pt_):
        print("FAIL the view always shows a change of the panels (last redraw, messages not held, distribution made again)", flush=True)
        bad.append("view always updates")
    # (Luca: «seleziono l'auto e parte il box rosso sui materiali», «copia light blocca tutto») no shader made by a click: the selected
    # piece stays drawn by its instance (twin invisible) and a reserve of dark lights keeps the number of lights constant
    if ("g.userData.smart = true;" not in vj_ or "new THREE.Mesh(part.geom, SMART_TWIN)" not in vj_ or "function reserveLights()" not in vj_
            or "mat.userData.smartCheap = true;\n  const glow = new THREE.Mesh(geo, mat);" not in vj_ or "const SHADOW_SLOTS_MAX = 6;" not in vj_ or "function lresStep(n)" not in vj_ or "m.userData.realMat = part.mat;" not in vj_ or "hit.object.userData.realMat || hit.object.material" not in vj_ or "setGizmosEnabled(!locked && !selectMode && !paintingNew());" not in vj_ or "if (gizmoAxis()) return;       // (the mouse is on a handle" not in vj_ or "function keepPrograms()" not in vj_ or "pr._kept = true; pr.usedTimes++;" not in vj_ or "try { reserveLights(); }" not in vj_ or "...LRES.all]" not in vj_ or "_warmed.get(P) !== _lightSig) { _shaderRev++" in vj_):
        print("FAIL a click or a copied light must not make the shaders again (selection twin, reserve of lights)", flush=True)
        bad.append("no shaders by click")
    # (diagnostics, with the user's yes) the pieces are all there: collector, sending, the question, the hooks, no window for a missing network
    ap_ = os.path.join(ROOT, "app", "Simpler")
    rd_ = lambda n: open(os.path.join(ap_, n), encoding="utf-8-sig").read()
    if (not os.path.exists(os.path.join(ap_, "Diagnostics.cs")) or "DiagService.Begin();" not in rd_("App.cs") or "DiagService.Schedule(this);" not in rd_("MainWindow.cs")
            or "DiagService.End();" not in rd_("MainWindow.cs") or "new DiagDialog(this, firstTime: false)" not in rd_("MainWindow.FileMenu.cs")
            or "public static string FilePath => PathName;" not in rd_("AppLog.cs") or 'if (st.Consent != "auto") return;' not in rd_("DiagService.cs")
            or 'if (ex.Code == "offline") { Status(' not in rd_("MainWindow.Content.cs")):
        print("FAIL diagnostics (collector, consent, hooks) or a window for a missing network", flush=True)
        bad.append("diagnostics")
    # (Luca: «correggo le auto, devo ricreare gli undici giga?») Pack Studio: only what changed is written again - also a model changed
    # outside Simpler (same rev in the library): a fingerprint of its folder makes a new rev and a new zip, the others stay
    sc_ = open(os.path.join(ROOT, "Simpler Pack Studio", "StudioContent.cs"), encoding="utf-8-sig").read()
    if ("static string Fingerprint(string dir)" not in sc_ or '["srcRev"] = srcRev, ["fp"] = fp' not in sc_
            or 'clean["rev"] = rev;' not in sc_ or "oldFp != null && !same)" not in sc_ or "static bool UnchangedLegacy(" not in sc_ or 'io.Remove("rootRot")' not in sc_):
        print("FAIL Pack Studio: a model changed outside Simpler gets a new rev and zip, the others are not written again", flush=True)
        bad.append("content delta")
    # (Luca, 13/11: «il nome nella treeview è sparito ma il gatto no») the pieces of an object deleted while they were exported are not added to the view
    vp_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Viewport.cs"), encoding="utf-8").read()
    if "were deleted while exported: not added" not in vp_ or "_scene.ById.ContainsKey(i)" not in vp_:
        print("FAIL an object deleted while its pieces were exported stays in the view", flush=True)
        bad.append("deleted while exported")
    # (Luca: «queste sono parallax credo standard ma se le carico il tuo materiale non funziona») a room picture in the
    # 3×3 cross chosen in «Stanza»: its walls, furniture and window frame in Cycles and in the view
    mt_ = open(os.path.join(ROOT, "engine", "simpler", "materials.py"), encoding="utf-8").read()
    if "room = self.interior_atlas(im, t, tx, ty, tz, du, dv, dw, fu, fv, hx, hy, hz)" not in me_ \
            or '(p.get("interior") or {}).get("map") or {}]' not in me_ or '"atlas": atlas is not None' not in mt_ \
            or "vec3 room = inAtlas > 0.5 ? inRoom(h, f, d, tx, ty, tz, t)" not in vj2_ \
            or 'MapRow(sp, L.T("Stanza"), "interior.map"' not in mm_:
        print("FAIL the room picture of Interni (3x3 cross) is not used in the render, the view or the panel", flush=True)
        bad.append("interior atlas")
    # (Luca: «questi sono cubi molto grandi», «su un piano non si vede proprio niente») the rooms in metres of the scene
    # (the scale of the object) and with the floors on the axis of the object that is up in the scene (a plane stood up)
    if "INTERIOR_SC = (" not in me_ or "INTERIOR_UP = (" not in me_ or "px, py, pz = turn(sp)" not in me_ \
            or "R = inTurn(normalize((vInP - vInC) * inScale)), P = inTurn((vInP - inMin) * inScale);" not in vj2_ \
            or "ob.getWorldScale(_inSc)" not in vj2_ or 'MatToggle(sp, L.T("Si adatta al modello"), "interior.stretch"' not in mm_ \
            or "const ref = it.stretch && it.refs" not in vj2_ or "sc = [max(1e-6, float(ob[k])) for k in INTERIOR_REF]" not in me_:
        print("FAIL the rooms of Interni ignore the scale of the object or a plane stood up", flush=True)
        bad.append("interior scale")
    # (Luca: «continuo a non capire dove modifico lo scatter in una scena di un progetto», «A va bene ma solo se lo
    # vincoliamo a quella particolare istanza») the layers of an ecosystem placed in the scene changed only there
    ec_ = open(os.path.join(ROOT, "engine", "simpler", "ecosystems.py"), encoding="utf-8").read()
    ecs_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Ecosystems.cs"), encoding="utf-8").read()
    if "def _effective(e, own):" not in ec_ or "e = _effective(e, own)" not in ec_ or "_keep_def(eid, lib_e)" not in ec_ \
            or "def save_own(d):" not in ec_ or "EcoLayersCard(info);" not in ecs_ \
            or "_ecoAddModel != null && _rightPanel == \"ecosystem\"" not in open(os.path.join(ROOT, "app", "Simpler", "MainWindow.ObjectLibrary.cs"), encoding="utf-8").read():
        print("FAIL the layers of an ecosystem cannot be changed in the project only", flush=True)
        bad.append("eco own")
    # (Luca: «il menu di destra deve tenere conto del tipo oggetto!! se consenti di cliccare optimize polygons secondo te
    # come finisce?») the right-click menus of the tree and of the view: each command only for the objects it applies to
    tr_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Tree.cs"), encoding="utf-8").read()
    ol_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.ObjectLibrary.cs"), encoding="utf-8").read()
    co_ = open(os.path.join(ROOT, "engine", "simpler", "core.py"), encoding="utf-8").read()
    rm_ = tr_[tr_.find("ContextMenu RowMenu(SceneObject o)"):tr_.find("void ShowAddMenu(")]
    if 'out["role"] = role' not in co_ or "readonly struct RowKind" not in tr_ or "if (k.Model && CanDecimate(o))" not in rm_ \
            or 'if (k.Model) Item(L.T("Converti in vegetazione")' not in rm_ or "new RowKind(ro).Model && CanDecimate(ro)" not in ol_ \
            or 'if (k.Model) Item(L.T("Converti in vegetazione")' not in ol_:
        print("FAIL the right-click menus offer commands that do not apply to the object (optimize a scatter...)", flush=True)
        bad.append("menu by kind")
    # (Luca: «tipizza le cartelle con delle icone, una bella icona evocativa nel centro, almeno per quelle della root»)
    lf_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.LibraryFolders.cs"), encoding="utf-8").read()
    if "FirstLevelFolder(folder) ? FolderBadge(FolderName(folder)) : null" not in lf_ or "static Geometry? FolderBadge(string name)" not in lf_ \
            or "FolderBadge(Path.GetFileName(sub))" not in open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Decals.cs"), encoding="utf-8").read():
        print("FAIL the folders of the first level of the libraries lost the icon of their kind", flush=True)
        bad.append("folder icons")
    # (Luca: «se il materiale è di tipo Interni possiamo mettere come miniatura l'anteprima della stanza?»)
    pj_ = open(os.path.join(ROOT, "engine", "preview_job.py"), encoding="utf-8").read()
    if "back = _interior_preview(scene, sphere, mat)" not in pj_ or "{'i' if room else ''}.png" not in open(os.path.join(ROOT, "engine", "simpler", "previews.py"), encoding="utf-8").read():
        print("FAIL the preview of an Interni material is a sphere, not its room", flush=True)
        bad.append("interior preview")
    # (Luca: «Ctrl+C è stato fatto ma non copia») the keys typed in the ideas page are the page's, not the scene's
    mw_ = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.cs"), encoding="utf-8").read()
    ok_ = mw_.find("if (_ideasPanel != null && (InSitePage(e.OriginalSource) || InSitePage(Keyboard.FocusedElement)")
    if ok_ < 0 or ok_ > mw_.find("StudioKey(e);", mw_.find("void OnKey(")):
        print("FAIL the keys typed in the ideas page go to the scene (Ctrl+V pastes objects instead of text)", flush=True)
        bad.append("ideas keys")
    # (1.78.4, Luca: «va bene tutto open source») Simpler is GPL 3 or later: a LICENSE at the root shipped with the
    # app, the agreement v2.0 in both languages without the closed «Applicazione», the content licence kept
    lic_ok = os.path.exists(os.path.join(ROOT, "LICENSE")) and "GNU GENERAL PUBLIC LICENSE" in open(os.path.join(ROOT, "LICENSE"), encoding="utf-8").read()
    it = open(os.path.join(ROOT, "credits", "Licenza.md"), encoding="utf-8").read()
    en = open(os.path.join(ROOT, "credits", "en", "License.md"), encoding="utf-8").read()
    lw = open(os.path.join(ROOT, "app", "Simpler", "LicenseWindow.cs"), encoding="utf-8").read()
    pj = open(os.path.join(ROOT, "app", "Simpler", "Simpler.csproj"), encoding="utf-8").read()
    if (not lic_ok or "Versione 2.0" not in it or "version 2.0" not in en or "Applicazione" in it or "«Application»" in en
            or "Simpler Content License" not in it or "Simpler Content License" not in en or 'Version = "2.0"' not in lw
            or 'Include="..\\..\\LICENSE"' not in pj or "Tutti i diritti riservati" in open(os.path.join(ROOT, "credits", "Crediti.md"), encoding="utf-8").read()):
        print("FAIL Simpler is not released as GPL 3 or later", flush=True)
        bad.append("gpl licence")
    # (1.78.4, Luca: «metti questa parte sopra al menu a sinistra») the folder path on its own row above the menus
    mw = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.cs"), encoding="utf-8").read()
    if "tabs.Children.Add(_libraryCrumbs)" in mw or "panel.Children.Add(crumbRow);" not in mw or mw.find("panel.Children.Add(crumbRow);") > mw.find("panel.Children.Add(tabs);"):
        print("FAIL folder path not on its own row above the library menus", flush=True)
        bad.append("crumbs row")
    # (1.78.4, Luca: «mi serve un tasto elimina per togliere dai piedi questo che ho sbagliato») «Elimina» in the
    # scatter panel: the outline being drawn (in no list) or the distribution
    pnt = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Paint.cs"), encoding="utf-8").read()
    if "async Task DiscardPainting()" not in pnt or "await DiscardPainting()" not in pnt or 'group = "", reset = true });\n            if (_rightPanel == "paint") RenderProps();' not in pnt:
        print("FAIL no «Elimina» for the outline being drawn", flush=True)
        bad.append("scatter delete")
    # (1.78.4, Luca: «metti import vegetation all'inizio») the import tile before the folders
    veg = open(os.path.join(ROOT, "app", "Simpler", "MainWindow.Vegetation.cs"), encoding="utf-8").read()
    body = veg[veg.find("void RenderRootedModels("):veg.find("void RenderVegBrowser(")]
    if not (0 < body.find("if (cur == extraAt) extra?.Invoke();") < body.find("foreach (var f in _modelFolders")):
        print("FAIL import tile not before the folders", flush=True)
        bad.append("import first")
    # (1.78.4, Luca: «se tolgo il focus da Simpler … rallenta tantissimo») the engine, its jobs and the app at full speed
    # with another program in front: every subprocess through fullspeed (power throttling off), the app's processes too
    import glob as _glob
    raw = [f for f in _glob.glob(os.path.join(ROOT, "engine", "simpler", "*.py")) if not f.endswith("fullspeed.py")
           and re.search(r"subprocess\.(Popen|run)\(", open(f, encoding="utf-8").read())]
    eng_cs = open(os.path.join(ROOT, "app", "Simpler", "Engine.cs"), encoding="utf-8").read()
    if (raw or "fullspeed.apply()" not in open(os.path.join(ROOT, "engine", "start_engine.py"), encoding="utf-8").read()
            or "FullSpeed.Apply(_process);" not in eng_cs or "FullSpeed.Apply(Process.GetCurrentProcess());" not in eng_cs
            or "FullSpeed.Apply(p);" not in open(os.path.join(ROOT, "app", "Simpler", "MainWindow.DeepBump.cs"), encoding="utf-8").read()):
        print("FAIL processes not at full speed in the background: " + ", ".join(os.path.basename(f) for f in raw), flush=True)
        bad.append("full speed")
    # (1.78.4, Luca: «cambio lo slider stagione e boom foglie bianche») a black emission is off at the import, and only
    # switching the light on turns a black filter white (tools/emission_check.py, regression step emission_black)
    if ('and "color" not in pe and ("nits" in pe or "on" in pe)' not in me
            or 'p["emission"]["nits"] = 0.0' not in me
            or not os.path.isfile(os.path.join(ROOT, "tools", "emission_check.py"))
            or '"emission_check.py"' not in open(os.path.join(ROOT, "tools", "regression.py"), encoding="utf-8").read()):
        print("FAIL black imported emission turned white by other changes", flush=True)
        bad.append("emission black")
    # (1.78.4, Luca: «in realtime non funziona ma il path tracer sì») a library piece's prototype is drawn with the
    # materials of Simpler as the view makes them; a rename shows in every tab of the models
    if ("out[\"mats\"] = _proto_mats(src)" not in pt or "const own = st.mats || {};" not in vj_all
            or 'or "simplerplants" or "primitives" or "packplants" or "packmodels" or "search") RenderLibrary();' not in open(os.path.join(app, "MainWindow.ObjectLibrary.cs"), encoding="utf-8").read()):
        print("FAIL prototype materials / library refresh after a rename", flush=True)
        bad.append("proto mats")
    # (1.78.4, Luca: «metti Simpler come folder anche nelle decals») Decal ▸ Simpler, lockable like the other parts
    dc = open(os.path.join(app, "MainWindow.Decals.cs"), encoding="utf-8").read()
    if ('("decals", "simplerdecals", "Simpler")' not in mw or "void RenderDecalBrowser(bool simpler = false)" not in dc
            or "var locked = SimplerLocked && InSimplerDecals(DecalRel(file));" not in dc):
        print("FAIL Decal ▸ Simpler", flush=True)
        bad.append("simpler decals")
    # (1.78.4, Luca: «resta il cursore a clessidra anche se ha finito») one rule takes the hourglass away: an open
    # library window (the import) is not work
    import glob as _glob
    srcs = {os.path.basename(f): open(f, encoding="utf-8").read() for f in _glob.glob(os.path.join(app, "*.cs"))}
    loose = [n for n, t in srcs.items() if n not in ("MainWindow.Insert.cs", "Ai.cs") and "Mouse.OverrideCursor = null;" in t.replace("Mouse.OverrideCursor == Cursors.Wait) Mouse.OverrideCursor = null;", "")]
    if "bool CursorBusy =>" not in srcs.get("MainWindow.Busy.cs", "") or loose:
        print(f"FAIL the hourglass must be taken away only by ReleaseBusyCursor: {loose}", flush=True)
        bad.append("busy cursor")
    # (1.78.4, Luca: season in the view, fuchsia leaves, thumbnail, Primitives) the edits of a one-object library piece
    # reach its prototype; the channels follow renumbered pictures; the prototype keeps its export when a picture is
    # not its own; «Ricalcola dalla vista» is no change for the scene's thumbnail; the shapes in Simpler/Primitives
    if ("if (node.userData.paintPiece && !ownMeshes(node).length) { scatterMaterials(it.slots || []); continue; }" not in vj_all
            or 'n["simpler_map"] = name' not in me or "def _maps_are_own(" not in pt
            or 'job.key == "POST /api/camview/refresh" and views.APPLIED["n"] == CHANGES["n"] - 1' not in sv
            or "internal string SimplerPrimitives" not in vg or not os.path.isfile(os.path.join(ROOT, "tools", "heal_check.py"))):
        print("FAIL season/pictures of library pieces in the view, scene thumbnail, Primitives folder", flush=True)
        bad.append("pieces view")
    # (1.78.4) «SimplerLocked» in settings.json: the Simpler parts red and read only, refused by the engine as well
    mdl = open(os.path.join(ROOT, "engine", "simpler", "models.py"), encoding="utf-8").read()
    if ("public int SimplerLocked" not in open(os.path.join(app, "Engine.cs"), encoding="utf-8").read() or "models.lock_check(job.key, job.data)" not in sv
            or "def lock_check(" not in mdl or '"simplermodel"' not in vg or 'Post("models/lock"' not in mw):
        print("FAIL the lock of the Simpler folders (settings, engine, red folders)", flush=True)
        bad.append("simpler lock")
    if rc.count("adv.Body") and "Advanced(shapeCard" in rc and rc.count(".Done(") < 5:
        print("FAIL terrain panel: an Avanzate without its Done", flush=True)
        bad.append("terrain Done")
    # (1.76.44, Luca: «importante che non sia un'interruzione continua ma fatto solo alla fine») «Scultura»: the view
    # sends its strokes only when the tool is left (never per stroke), and the app commits them before the path
    # tracing, the final render and a save
    vj = open(os.path.join(app, "web", "viewer.js"), encoding="utf-8").read()
    te = vj[vj.find("function terrainStrokeEnd()"):vj.find("function terrainUndo()")]
    if "terrainSculptCommit" in te or "type: 'terrainSculptCommit'" not in vj:
        print("FAIL terrain sculpt: the strokes go to the engine at every stroke, or never", flush=True)
        bad.append("terrain sculpt commit")
    for f_, fn in (("MainWindow.Viewport.cs", "async Task SetRealistic("), ("MainWindow.Commands.cs", "async Task FinalRender()"),
                   ("MainWindow.FileMenu.cs", "async Task<bool> SaveProject(")):
        src_ = open(os.path.join(app, f_), encoding="utf-8").read()
        body = src_[src_.find(fn):src_.find(fn) + 600]
        if "FlushTerrainSculpt" not in body:
            print(f"FAIL terrain sculpt: {fn} without the strokes of the view", flush=True)
            bad.append(fn)
    # (1.76.49, Luca: «è importante che non accumuli spazzatura») the caches on disk stay within their limits: too
    # many, too big, too old and half-written files go
    import importlib.util, tempfile as _tf, time as _tm
    spec = importlib.util.spec_from_file_location("diskcache", os.path.join(ROOT, "engine", "simpler", "diskcache.py"))
    dc = importlib.util.module_from_spec(spec); spec.loader.exec_module(dc)
    with _tf.TemporaryDirectory() as tmp:
        old_env = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = tmp
        try:
            d = dc.folder("terrcache"); os.makedirs(d)
            for i in range(30):
                pth = os.path.join(d, f"f{i:02d}.npz")
                with open(pth, "wb") as fh:
                    fh.write(b"x" * 1000)
                os.utime(pth, (_tm.time() - 1000 + i, _tm.time() - 1000 + i))
            for nm, age in (("old.npz", 40 * 86400), ("dead.npz.tmp.npz", 120)):
                with open(os.path.join(d, nm), "wb") as fh:
                    fh.write(b"x")
                os.utime(os.path.join(d, nm), (_tm.time() - age, _tm.time() - age))
            dc.prune("terrcache")
            left = sorted(os.listdir(d))
            mx = dc.LIMITS["terrcache"][1]
            if len(left) != mx or "old.npz" in left or "dead.npz.tmp.npz" in left or left[0] != f"f{30 - mx:02d}.npz":
                print(f"FAIL disk cache not pruned: {left}", flush=True)
                bad.append("diskcache")
            # (1.76.51) the maps of the view left by an earlier engine session go; this session's and fresh ones stay
            rd = dc.folder("rain"); os.makedirs(rd)
            for nm, age in (("mantle_1_3.bin", 3 * 3600), ("dirt_2_9.bin", 3 * 3600), (f"mantle_{os.getpid()}_1.bin", 3 * 3600),
                            ("shelter_3_1.bin", 60)):
                with open(os.path.join(rd, nm), "wb") as fh:
                    fh.write(b"x")
                os.utime(os.path.join(rd, nm), (_tm.time() - age, _tm.time() - age))
            dc.prune_all()
            if sorted(os.listdir(rd)) != sorted([f"mantle_{os.getpid()}_1.bin", "shelter_3_1.bin"]):
                print(f"FAIL view maps of old sessions left on disk: {sorted(os.listdir(rd))}", flush=True)
                bad.append("view files")
            # (1.76.51) the caches of the view within limits: a prototype's .glb and .json go together, files used in
            # the last day stay, a texture the scene shows stays, other files are left alone
            pd = dc.folder("viewcache/proto"); os.makedirs(pd)
            for i in range(4):
                for ext in (".glb", ".json"):
                    pth = os.path.join(pd, f"m{i}{ext}")
                    with open(pth, "wb") as fh:
                        fh.write(b"x" * 100)
                    age = 3 * 86400 - i * 3600 if i < 3 else 60
                    os.utime(pth, (_tm.time() - age, _tm.time() - age))
            with open(os.path.join(pd, "notes.txt"), "w") as fh:
                fh.write("x")
            td = dc.folder("texcache"); os.makedirs(td)
            for nm, age in (("a_1024.png", 5 * 86400), ("b_1024.png", 4 * 86400), ("packed_index.json", 9 * 86400)):
                with open(os.path.join(td, nm), "wb") as fh:
                    fh.write(b"x" * 100)
                os.utime(os.path.join(td, nm), (_tm.time() - age, _tm.time() - age))
            lim = dict(dc.LIMITS)
            try:
                dc.LIMITS["viewcache/proto"] = (250, 100)       # (room for one prototype and a bit)
                dc.LIMITS["texcache"] = (50, 100)
                dc.prune("viewcache/proto")
                dc.prune("texcache", {os.path.normcase(os.path.abspath(os.path.join(td, "a_1024.png")))})
            finally:
                dc.LIMITS.clear(); dc.LIMITS.update(lim)
            lp, lt = sorted(os.listdir(pd)), sorted(os.listdir(td))
            if lp != ["m3.glb", "m3.json", "notes.txt"] or lt != ["a_1024.png", "packed_index.json"]:
                print(f"FAIL view caches not pruned right: {lp} {lt}", flush=True)
                bad.append("view caches")
        finally:
            if old_env is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = old_env
    # (1.76.11, Luca) «Usa la vista attuale» of the video keyframes started the render with one click: asked first
    vp = open(os.path.join(app, "MainWindow.VideoPanel.cs"), encoding="utf-8").read()
    for label in ("Usa la vista attuale", "Stessa inquadratura dell'inizio"):
        line = next((l for l in vp.splitlines() if f'L.T("{label}"), async' in l), "")
        if "ConfirmFrameRender" not in line:
            print(f"FAIL video keyframe «{label}» renders without asking", flush=True)
            bad.append(label)
    # (1.76.13, Luca) the search text of the library belongs to its tab: another tab does not inherit it
    lib = open(os.path.join(app, "MainWindow.Library.cs"), encoding="utf-8").read()
    body = lib[lib.find("void RenderLibrary()"):]
    if "SearchForTab();" not in body[:body.find("foreach (var (menu, b) in _libraryMenuButtons)")]:
        print("FAIL library search: the text is not kept per tab", flush=True)
        bad.append("SearchForTab")
    # (1.76.21, Luca: «guarda che pattern ripetuto ha l'oceano») the maps of the sea laid without repeating, and the
    # foam of the far map where the grid is wide (not the foam of its points: long white streaks)
    vj = open(os.path.join(app, "web", "viewer.js"), encoding="utf-8").read()
    oc = vj[vj.find("function oceanMaterial()"):vj.find("function oceanSet(")]
    if "oTile( oSlope" not in oc or "oTile( oDetail" not in oc or "texture2D( oSlope" in oc or "texture2D( oDetail" in oc:
        print("FAIL sea in the view: a map of the waves laid as a repeating tile", flush=True)
        bad.append("oTile")
    if "float oCut = oFld - ( 2.2 - 4.4 * oD.y * oPatch );" not in oc:
        print("FAIL sea in the view: the foam of the surf as a veil, not a lace cut at a level", flush=True)
        bad.append("surf lace")
    # (1.76.26, Luca) the brush made again (a change of scale) must stand on the library models drawn from their
    # prototype too (a Poly Haven cliff after «Ridisegna la vista»): before, the distribution fell to the ground
    ps = vj[vj.find("function paintSurfaces("):vj.find("function paintApplyStroke(")]
    sh = vj[vj.find("function surfaceHits("):vj.find("function hitNormal(")]
    if "scatter.sets.get('')" not in ps or "setHits(ray, true)" not in sh:
        print("FAIL brush: the library models drawn from their prototype are not surfaces to paint on", flush=True)
        bad.append("paint surfaces")
    # (1.76.27, Luca: «la schiuma della costa è dritta») the coast from its map of square cells where it reaches,
    # not from the points of the grid (straight bands along its long rows)
    if "texture2D( oCMap, oCu ).rgb, smoothstep( oCMapA.w, 2.0 * oCMapA.w, oSpG )" not in oc or "vOD.y" in oc or "vOD.z" in oc or "vOD.w" in oc \
            or "oceanCoastMap(o.coast ? o.coastMap : null)" not in vj:
        print("FAIL sea in the view: the coast from the points of the grid (straight bands), not from its map", flush=True)
        bad.append("coast map")
    # (1.76.30, Luca: moving an object in the water left «ground» where it had been) the idle poll brings the coast's
    # map with the surface
    if "oceanCoastMap(OCEAN.info.coast ? inf.ocean.coastMap : null)" not in vj:
        print("FAIL sea in the view: the coast's map not followed when an object moves", flush=True)
        bad.append("coast map follow")
    # (1.76.32, Luca) favourite commands: the hearts are put before the accordions take the rows, the buttons sit
    # between SmartView and the arrows, the lists of stones and models are content (no heart)
    pr = open(os.path.join(app, "MainWindow.Props.cs"), encoding="utf-8").read()
    rp = pr[pr.find("void RenderProps()"):pr.find("void RenderPropsCore()")]
    mw = open(os.path.join(app, "MainWindow.cs"), encoding="utf-8").read()
    if not (0 < rp.find("MakeFavorites();") < rp.find("MakeAccordions();")) \
            or not (0 < mw.find("BuildFavButtons(bar);") < mw.find("BuildSmartButton(bar);")) \
            or 'row.Tag = "content";' not in open(os.path.join(app, "MainWindow.Scree.cs"), encoding="utf-8").read():
        print("FAIL favourite commands: hearts after the accordions, or the buttons out of place, or list rows with hearts", flush=True)
        bad.append("favourites")
    # (1.76.35, Luca) a favourite is not tied to one instance: the section of an ecosystem has a stable key
    if 'et.Uid = "ecosystem";' not in open(os.path.join(app, "MainWindow.Ecosystems.cs"), encoding="utf-8").read() \
            or "title.Uid" not in open(os.path.join(app, "MainWindow.FavCommands.cs"), encoding="utf-8").read():
        print("FAIL favourite commands: the hearts of an ecosystem tied to its name", flush=True)
        bad.append("favourites per instance")
    if "mix( vOD.x, oFS.z, oFar )" not in oc:
        print("FAIL sea in the view: the foam of the points where the grid is wide (streaks)", flush=True)
        bad.append("far foam")
    # (1.76.50, audit of Luca's logs) the real-time view: a slow frame at the lowest budget does not place every
    # piece again; a model piece that changed count is added again (no full reload); the hemisphere stand-in light
    # stays in the scene (no shader rebuild each time the last light goes)
    vj = open(os.path.join(app, "web", "viewer.js"), encoding="utf-8").read()
    sa = vj[vj.find("function scatterAdapt("):vj.find("function scatterHits(")]
    if "scatter.budget === was" not in sa:
        print("FAIL view: a slow frame places every distribution piece again even at the lowest budget", flush=True)
        bad.append("scatterAdapt")
    if "partRetry" not in vj or "function setFallback" not in vj or "fallback.visible" in vj or "key.intensity = on ? 1.6 : 0" not in vj or "function ensureFill" not in vj:
        print("FAIL view: geometry replace reloads the whole view, or the stand-in light is added and removed", flush=True)
        bad.append("view reloads")
    # (1.76.50) a view loaded again keeps the shaders: the old materials are freed later (the view reuses them)
    cs = vj[vj.find("function clearScene("):vj.find("indexMaterials(root);")]
    if "function matGraveFlush" not in vj or cs.count("disposeTree(root, true)") != 2:
        print("FAIL view: the materials freed at once when the view is loaded again (every shader made again)", flush=True)
        bad.append("shader keep")
    # (1.76.50) SmartView does not walk the whole scene twice a second
    ss = vj[vj.find("function smartShadows("):vj.find("const _standIns")]
    if "SMART.addRev !== _addRev" not in ss:
        print("FAIL SmartView: the whole scene walked every half second for the shadows", flush=True)
        bad.append("smart shadows")
    return not bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True)
    ap.add_argument("--scenes", required=True)
    ap.add_argument("--eco")
    ap.add_argument("--out", required=True)
    ap.add_argument("--full", action="store_true", help="the whole check (only when Luca asks for it)")
    args = ap.parse_args()
    files = changed(args.since)
    engine = [f for f in files if f.startswith("engine/")]
    sc = lambda n: ["--scene", os.path.join(args.scenes, n)]
    cmd = [sys.executable, os.path.join(ROOT, "tools", "regression.py"), "--out", args.out,
           "--base", os.path.join(ROOT, "tools", "regression_base.json")]
    if args.eco:
        cmd += ["--eco", args.eco]
    if not args.full or not engine:
        print("quick check (the whole one only with --full, when Luca asks)", flush=True)
        cmd += sc("spiaggia.simpler") + ["--quick"]
    else:
        slow = any(t in os.path.basename(f) for f in engine for t in SLOW_TOPICS)
        print(f"engine changed ({len(engine)} files): whole check" + (" with test oceano" if slow else ""), flush=True)
        if slow:
            cmd += sc("test_oceano2.simpler")
        cmd += sc("spiaggia.simpler") + sc("cattedrale.simpler") + sc("piscina.simpler")
        if any(t in os.path.basename(f) for f in engine for t in ("water", "refcaustics", "glass")):
            cmd += sc("cattedrale_acqua.simpler")       # (Luca's cathedral with a 139 m water plane: the grid around the camera)
            # (the export of the real-time view of this 75 MB scene goes past the memory of the test computer, 7 GB:
            # the engine is killed - with 1.74.1 too. Left out here, so the steps after it are checked)
            cmd += ["--skip", "cattedrale_acqua.simpler:export_view"]
    ok = static_checks()
    rc = subprocess.run(cmd).returncode
    sys.exit(rc or (0 if ok else 1))


if __name__ == "__main__":
    main()
