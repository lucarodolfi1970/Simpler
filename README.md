# Simpler

**Rendering fotorealistico di immagini fisse, semplice da usare, basato su Blender/Cycles.**
*Photorealistic still-image rendering made simple, built on Blender/Cycles.* (English below)

Sito: <https://www.rodluc.com/simpler/> · Autore: Luca Rodolfi · Licenza: GNU GPL versione 3 o successiva

---

## Italiano

Simpler è un'applicazione Windows per ottenere immagini fotorealistiche senza dover imparare un programma 3D
professionale. L'interfaccia (WPF) mostra la scena in tempo reale (three.js in WebView2); il render vero lo fa
Cycles, dentro una copia di Blender usata come motore, senza interfaccia.

### Struttura

| Cartella | Contenuto |
|---|---|
| `app/Simpler/` | L'interfaccia Windows `Simpler.exe` (C#, WPF, .NET 8, WebView2) e la vista 3D (`web/`) |
| `engine/` | Il motore: codice Python che gira dentro Blender 5.2 ed espone un'API locale all'app |
| `tools/` | Prove automatiche e strumenti di sviluppo |
| `Simpler setup/` | Lo script del programma di installazione (Inno Setup) |
| `release-notes/` | Le note di ogni versione |
| `credits/` | Licenza d'uso e crediti (italiano e inglese) |

### Compilare

Servono: Windows 10/11, [.NET 8 SDK](https://dotnet.microsoft.com/download), [Blender 5.2](https://www.blender.org/download/).

1. `Build-App.bat`: compila l'app nella cartella `dist\` e la avvia.
2. Al primo avvio, se Blender non è nel percorso standard, Simpler chiede dove si trova `blender.exe`.
3. Programma di installazione (facoltativo): `Simpler setup\Build-Setup.bat`, con Inno Setup installato
   (vedi `Simpler setup\LEGGIMI.txt`).

### Cosa non c'è in questo repository

- I **contenuti** (modelli 3D, materiali, pacchetti, esempi): non sono codice, hanno licenze proprie
  (vedi `credits/`) e si scaricano dall'app.
- L'**indirizzo dei contenuti nel cloud**: nei sorgenti la parte segreta è sostituita da `SEGRETO-NON-PUBBLICATO`;
  una copia compilata da qui funziona, ma senza il download dei contenuti.
- Gli strumenti privati dell'autore (preparazione dei pacchetti) e il codice dei servizi web del sito.

### Licenza

Il codice di Simpler è © 2026 Luca Rodolfi ed è distribuito con la **GNU General Public License versione 3 o,
a tua scelta, una versione successiva** (file `LICENSE`). I contenuti, il nome e il logo sono regolati da
`credits/Licenza.md`. Blender è GPL ed è usato come programma separato, non modificato; Cycles è Apache 2.0;
le librerie incluse (three.js, meshoptimizer e altre) conservano le loro licenze, nei file accanto a loro.

---

## English

Simpler is a Windows application for photorealistic images without learning a professional 3D package. The
interface (WPF) shows the scene in real time (three.js in WebView2); the final render is done by Cycles, inside a
copy of Blender used as a headless engine.

**Layout:** `app/Simpler/` the Windows app (C#, WPF, .NET 8, WebView2) and the 3D view (`web/`); `engine/` the
engine, Python running inside Blender 5.2 with a local API; `tools/` tests and development tools; `Simpler setup/`
the installer script (Inno Setup); `release-notes/`; `credits/` license and credits.

**Build:** Windows 10/11, .NET 8 SDK, Blender 5.2. Run `Build-App.bat` (builds into `dist\` and starts the app);
the installer is built by `Simpler setup\Build-Setup.bat` with Inno Setup.

**Not in this repository:** the contents (3D models, materials, packs, samples: not code, with their own licenses,
downloaded from the app); the secret part of the cloud contents address (replaced by `SEGRETO-NON-PUBBLICATO`: a
build from these sources works, without content downloads); the author's private tools and the code of the web
services.

**License:** Simpler's code is © 2026 Luca Rodolfi, released under the **GNU General Public License version 3 or,
at your option, any later version** (`LICENSE`). Contents, name and logo: `credits/en/License.md`. Blender is GPL,
used as a separate, unmodified program; Cycles is Apache 2.0; bundled libraries keep their own licenses.
