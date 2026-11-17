"""Simpler · PlantFactory → FBX in serie

Da eseguire DENTRO PlantFactory: Automation ▸ Run Python Script… e scegli questo file.
Apre ogni pianta .tpf di una cartella (e delle sue sottocartelle) e la esporta in FBX con il preset per Blender,
pronta per «Importa vegetazione…» di Simpler. Le immagini vanno accanto a ogni FBX (cartella Maps).

Le cartelle si chiedono all'avvio; se la finestra di scelta non è disponibile (il Python di PlantFactory non ce l'ha)
valgono SOURCE e OUT qui sotto. VERSIONS sceglie le versioni: di norma solo le LD.
Una pianta già esportata (il suo FBX esiste) viene saltata: si può interrompere e riprendere.
Il resoconto è in OUT\\export_log.txt.

SET sceglie cosa esportare:
  "stock"   le piante di serie installate con PlantFactory (C:\\ProgramData\\e-onsoftware\\PlantFactory\\Species): sono
            quelle che si possono distribuire con Simpler come varianti nostre. Ogni pianta esce in VARIANTS varianti, ognuna
            con una forma casuale diversa da quella originale (un altro seme); la cartella «Objects» (secchi, cesti, cancelli)
            è saltata. Per ogni pianta si scrive anche <nome>.txt con i preset della pianta e i poligoni di ogni variante.
  "catalog" le piante del PlantCatalog (solo per uso personale: non si distribuiscono).
"""
import os
import time
import traceback

SET = "stock"                                         # "stock" (piante di serie, distribuibili) | "catalog"
OVERWRITE = False                                     # True: esporta di nuovo anche le piante già esportate
if SET == "stock":
    SOURCE = r"C:\ProgramData\e-onsoftware\PlantFactory\Species"
    OUT = r"M:\3D\meshes\plantfactory\PlantFactory stock"
    VERSIONS = ()                                     # (le piante di serie non hanno versioni LD/HD/RT nel nome)
    SKIP_FOLDERS = ("Objects",)                       # (non sono piante)
    VARIANTS = (1, 2)                                 # semi delle varianti: «<nome> v1.fbx», «<nome> v2.fbx»
else:
    SOURCE = r"M:\software\eonsoftware\plantcatalog"  # dove sono i .tpf (anche nelle sottocartelle)
    OUT = r"M:\3D\meshes\plantfactory"                 # dove vanno gli FBX (stessa struttura di cartelle)
    VERSIONS = ("LD",)                                # versioni da esportare: "LD", "HD", "RT" (vuoto = tutte)
    SKIP_FOLDERS = ()
    VARIANTS = (None,)                                # (la pianta com'è)


def ask_folders():
    global SOURCE, OUT
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        s = filedialog.askdirectory(title="Cartella con le piante .tpf", initialdir=SOURCE if os.path.isdir(SOURCE) else None)
        if not s:
            return False
        o = filedialog.askdirectory(title="Cartella dove salvare gli FBX", initialdir=OUT if os.path.isdir(OUT) else None)
        if not o:
            return False
        SOURCE, OUT = os.path.normpath(s), os.path.normpath(o)
        root.destroy()
    except Exception:
        pass            # (no tkinter here: the folders written above)
    return True


def g(name):
    """A function of PlantFactory's scripting (globals of the console, else the eon module)."""
    import builtins
    f = globals().get(name) or getattr(builtins, name, None)
    if f is None:
        import eon
        f = getattr(eon, name, None)
        if f is None:
            app = getattr(eon, "app", None) or getattr(eon, "Application", None)
            child = app.GetEONChild() if app is not None and hasattr(app, "GetEONChild") else None
            f = getattr(child, name, None) if child is not None else None
    if f is None:
        raise RuntimeError(f"funzione di PlantFactory non trovata: {name}")
    return f


def main():
    if not ask_folders():
        print("Annullato.")
        return
    os.makedirs(OUT, exist_ok=True)
    log_path = os.path.join(OUT, "export_log.txt")
    plants = []
    for d, dirs, files in os.walk(SOURCE):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_FOLDERS and not x.startswith("."))
        for f in sorted(files):
            if f.lower().endswith(".tpf"):
                words = os.path.splitext(f)[0].upper().split()
                if VERSIONS and not any(v.upper() in words for v in VERSIONS):
                    continue                 # (Aesculus pavia HD, … RT: only the versions asked)
                plants.append(os.path.join(d, f))
    print(f"{len(plants)} piante in {SOURCE} (versioni: {', '.join(VERSIONS) or 'tutte'}) → {OUT}")
    try:
        g("EnableMessageBoxes")(False)          # (no dialog may stop the series)
    except Exception:
        pass
    import eon
    done = skipped = failed = 0
    t0 = time.time()
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M')} · {SOURCE} → {OUT} · {len(plants)} piante\n")
        for i, src in enumerate(plants, 1):
            rel = os.path.relpath(os.path.dirname(src), SOURCE)
            name = os.path.splitext(os.path.basename(src))[0].replace("_tpf_170", "").replace("_", " ").strip()
            dst_dir = os.path.normpath(os.path.join(OUT, rel))
            os.makedirs(dst_dir, exist_ok=True)
            info = []
            for seed in VARIANTS:
                vname = name if seed is None else f"{name} v{seed}"
                dst = os.path.join(dst_dir, vname + ".fbx")
                if os.path.isfile(dst) and not OVERWRITE:
                    skipped += 1
                    continue
                t1 = time.time()
                try:
                    if seed is None:
                        g("LoadPlant")(src)
                    else:
                        g("LoadPlant")(src, seed)     # (another random shape: not the plant as it was shipped)
                    try:
                        g("WaitForGeometry")()
                    except Exception:
                        pass
                    if seed is not None and not info:
                        try:                          # (what the plant offers: read once, for the next steps)
                            n = g("GetPresetNumber")()
                            info.append("preset: " + ", ".join(str(g("GetPresetName")(k)) for k in range(n)))
                        except Exception as exc:
                            info.append(f"preset: non letti ({exc})")
                    polys = None
                    try:
                        polys = g("GetNumberOfPolygons")()
                    except Exception:
                        pass
                    g("SetExportPreset")(eon.EExportPreset_EP_Blender)
                    ok = g("ExportAsMesh")(dst, os.path.join(dst_dir, "Maps"))
                    if ok is False or not os.path.isfile(dst):
                        raise RuntimeError("l'esportazione non ha scritto il file")
                    done += 1
                    msg = f"ok    {vname}  ({time.time() - t1:.0f} s, {polys if polys is not None else '?'} poligoni)"
                    info.append(f"{vname}: seme {seed}, {polys if polys is not None else '?'} poligoni")
                except Exception as exc:
                    failed += 1
                    msg = f"ERRORE {vname}: {exc}"
                    log.write(traceback.format_exc())
                print(f"[{i}/{len(plants)}] {msg}")
                log.write(f"{msg}  ← {src}\n")
                log.flush()
            if info and SET == "stock":
                with open(os.path.join(dst_dir, name + ".txt"), "w", encoding="utf-8") as fh:
                    fh.write(f"{name}\norigine: {src}\n" + "\n".join(info) + "\n")
        summary = f"Fatto in {(time.time() - t0) / 60:.1f} min: {done} esportate, {skipped} già presenti, {failed} con errori"
        log.write(summary + "\n")
    print(summary)
    print("Resoconto:", log_path)


main()
