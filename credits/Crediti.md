# Licenze e crediti di Simpler

Questa pagina raccoglie i programmi, le librerie, i servizi e i contenuti di altri autori che Simpler usa, con le loro licenze, e i nomi di prodotti citati. Viene aggiornata a ogni versione in cui si aggiunge qualcosa.

Ultimo aggiornamento: Simpler 1.78.5, 9 novembre 2026. Il contratto di licenza accettato al primo avvio si rilegge con il pulsante «Contratto di licenza» in cima a questa finestra.

## Simpler

- Simpler (l'applicazione Windows e il motore che gira dentro Blender): © 2026 Luca Rodolfi, software libero con licenza GNU GPL versione 3 o successiva. Le parti di altri autori elencate qui sotto restano sotto le loro licenze.
- Modelli e piante inclusi e pacchetti .simplerpack: Simpler Content License 1.0, salvo i contenuti con una licenza diversa indicata qui sotto. Il nome «Simpler» e il logo non sono coperti dalla GPL.
- Le immagini, i render e i progetti che crei con Simpler sono tuoi.

## Programmi e librerie

### Blender e Cycles (motore di render)
- Autore: Blender Foundation e collaboratori — https://www.blender.org
- Versione usata: Blender 5.2.2 LTS, eseguito come programma separato.
- Licenza: GNU GPL versione 2 o successiva; i programmi Blender distribuiti ricadono nella GNU GPL versione 3 o successiva. Cycles: Apache License 2.0.
- Ciò che crei con Blender (immagini, file .blend) è tuo.

### three.js (vista in tempo reale)
- Autori: three.js authors — https://threejs.org
- Versione: 0.186.1, con gli addon OrbitControls, TransformControls, GLTFLoader, RoomEnvironment, BufferGeometryUtils, SkeletonUtils.
- Licenza: MIT (testo in web/lib/LICENSE-three.txt).

### three-mesh-bvh
- Autore: Garrett Johnson — https://github.com/gkjohnson/three-mesh-bvh
- Versione: 0.9.14. Licenza: MIT (testo in web/lib/bvh/LICENSE).

### meshoptimizer (semplificazione delle mesh)
- Autore: Arseny Kapoulkine — https://github.com/zeux/meshoptimizer
- Versione: 1.2.0. Licenza: MIT (testo in web/lib/meshopt/LICENSE.md).

### Microsoft WebView2 e .NET
- Microsoft.Web.WebView2 1.0.4129.50 (il pannello che mostra la vista in tempo reale): licenza Microsoft del pacchetto WebView2 SDK; il runtime WebView2 è quello di Windows.
- .NET 8 / WPF: Microsoft, licenza MIT.

### DeepBump (mappe normali, altezza e ingrandimento dalle texture)
- Autore: Hugo Tini — https://github.com/HugoTini/DeepBump
- Copia non modificata (commit fad19ba, 17 marzo 2025), sorgenti e modelli inclusi in tools/deepbump.
- Licenza: GNU GPL versione 3 (testo in tools/deepbump/LICENSE). Simpler lo esegue come programma separato; il codice di Simpler non contiene codice di DeepBump.
- Librerie installate al primo uso in %LOCALAPPDATA%\Simpler\deepbump-libs: onnxruntime (Microsoft, MIT), imageio (BSD 2-Clause), numpy (BSD 3-Clause), Pillow (MIT-CMU).

## Servizi online

### Poly Haven (modelli 3D, materiali, HDRI e sfondi)
- https://polyhaven.com — contenuti CC0 (pubblico dominio): si possono usare per qualsiasi scopo, anche commerciale, senza obbligo di citazione.
- Simpler li scarica al primo uso tramite l'API pubblica di Poly Haven.

### ambientCG (decal e materiali)
- https://ambientcg.com — di Lennart Demes, contenuti CC0 (pubblico dominio).
- Simpler scarica le decal (menu Decal ▸ ambientCG) tramite l'API pubblica di ambientCG.

### NASA Scientific Visualization Studio (stelle e luna della notte)
- Stelle: «Deep Star Maps 2020» — https://svs.gsfc.nasa.gov/4851 — visualizzazione di Ernie Wright (USRA); dati stellari Hipparcos-2, Tycho-2, UCAC3 e Gaia DR2 (ESA/Gaia/DPAC).
- Luna: «CGI Moon Kit» (mappa colori LROC del Lunar Reconnaissance Orbiter) — https://svs.gsfc.nasa.gov/4720
- Credito richiesto da NASA: «NASA's Scientific Visualization Studio»; per le stelle anche ESA/Gaia/DPAC per i dati Gaia. Le pagine non indicano una licenza esplicita e rimandano alle linee guida di riproduzione della NASA; le immagini NASA non sono in genere protette da copyright, ma non possono essere usate per far credere a un'approvazione della NASA.
- Simpler scarica i due file (circa 35 MB) la prima volta che serve una notte.

### OpenAI (funzioni AI sulle immagini)
- https://openai.com — modelli di immagini GPT Image, usati solo con la chiave personale dell'utente e sotto i termini d'uso di OpenAI.
- Le immagini inviate e ricevute passano dai server di OpenAI.

### Krea (video AI)
- https://www.krea.ai — modelli video usati solo con la chiave personale dell'utente e sotto i termini d'uso di Krea.
- Le immagini inviate e i video ricevuti passano dai server di Krea.

### rodluc.com (sito di Simpler)
- https://www.rodluc.com/simpler/ — all'avvio, al massimo una volta al giorno, Simpler chiede se c'è una versione nuova inviando soltanto il numero di versione e la lingua. Si può disattivare in Impostazioni ▸ Aggiornamenti.
- Le pagine delle novità e del download si aprono nel browser solo quando lo chiedi.
- «Suggerisci un'idea» apre la pagina delle idee del sito solo quando ci clicchi; arrivano la versione, la lingua e ciò che scrivi nel modulo. L'indirizzo IP non viene salvato.

### GitHub (codice sorgente e installazione)
- https://github.com — il codice sorgente di Simpler e i file di installazione. Simpler non si collega a GitHub da solo: la pagina si apre nel browser solo quando lo chiedi.

Se un servizio non è raggiungibile (per esempio senza connessione), Simpler continua a funzionare; le operazioni che fa da solo in background, come il controllo degli aggiornamenti, lo ignorano senza messaggi di errore.

### Sketchfab (modelli scaricati dall'utente)
- https://sketchfab.com — Simpler non scarica nulla da Sketchfab da solo: i modelli che scarichi tu restano sotto la licenza indicata sulla loro pagina.

## Contenuti inclusi in Simpler

- Icone dell'interfaccia: disegnate per Simpler.
- Miniature delle primitive (primitives/*.png): renderizzate con Simpler.
- Scena di esempio «Cosmetic shop» (cartella samples): modelli di SketchUp CGtips inclusi con l'autorizzazione di CGtips per scopi non commerciali, come la formazione e la dimostrazione. Non sono coperti dalla GPL né dalla Simpler Content License: non si possono vendere né ridistribuire a fini commerciali. Chi ridistribuisce Simpler a fini commerciali deve togliere la cartella samples.
- Scena di esempio «Bedroom» (cartella samples): il modello «Minimalistic Modern Bedroom» di dylanheyes (https://sketchfab.com/3d-models/4f3db3cb57bd4bce886f7b9a13273a2f), licenza Creative Commons Attribution 4.0 (CC BY 4.0): si può usare, modificare e ridistribuire, anche a fini commerciali, citando l'autore. Modifiche: convertito nel formato di Simpler, rinominato e messo in una scena di Simpler.
- Texture del suolo «piastrelle», immagine di avvio, immagine della procedura di importazione, schede delle funzioni AI e foto di riferimento dei cieli (alba, nuvoloso, tramonto): verificate dal Titolare per l'uso in Simpler.
- Caratteri: Segoe UI e Cascadia Mono di Windows (non inclusi in Simpler).

### Modelli cucina e bagno (libreria Simpler ▸ Furniture ▸ Kitchen and bathroom)
- Licenza: Creative Commons Attribution 4.0 (CC BY 4.0) — https://creativecommons.org/licenses/by/4.0/ — si possono usare, modificare e ridistribuire, anche a fini commerciali, citando l'autore. Non sono sotto la Simpler Content License.
- Modifiche: convertiti nel formato della libreria di Simpler e rinominati.
- Chi ridistribuisce questi modelli deve mantenere questo elenco.
- Modern fridge — autore: dylanheyes — https://sketchfab.com/3d-models/366f7dfa18744ccf8cee119f26446022
- Retro fridge — autore: dylanheyes — https://sketchfab.com/3d-models/3b130f0ba4304966a101c82be2429cc7
- Old fridge — autore: dylanheyes — https://sketchfab.com/3d-models/68d173f205344455933f861042b99fe3
- Grey refrigerator — autore: glowbox3d — https://sketchfab.com/3d-models/2071bda681b642218b6829b82e4fd93b
- Retro microwave — autore: dylanheyes — https://sketchfab.com/3d-models/0cbcd57eef2a47a4b5e3cef9150933bd
- Stove with hood — autore: hippostance — https://sketchfab.com/3d-models/ce6f590e7cb848e398c80208ee3b6fdf
- Range hood — autore: rickmaolly — https://sketchfab.com/3d-models/4033aa7ba4ef4d4c87ab7f514ac4ae44
- Dishwasher — autore: rickmaolly — https://sketchfab.com/3d-models/7a4d8ed6ece248a596ec4dfb5741e7cc
- Coffee maker — autore: Ryan_Nein — https://sketchfab.com/3d-models/383923d4412f4b66937d9c1779a9a0a2
- Kitchen sink — autore: hippostance — https://sketchfab.com/3d-models/504248ed68e3480a807aced6f002b2d5
- Modular kitchen cabinets — autore: sauti — https://sketchfab.com/3d-models/4b765920f7c34676acda91c0bfd87abd
- Modern kitchen — autore: dylanheyes — https://sketchfab.com/3d-models/9843a830b96142a9a53f45f25304d93c
- Small modern kitchen — autore: dylanheyes — https://sketchfab.com/3d-models/2cc658a96e304a6d9db1813233ed90d1
- Kitchen set — autore: EvanPetrov — https://sketchfab.com/3d-models/1bf20d2de7f749d889d69c42207ca669
- Kitchen decor set — autore: visthetique — https://sketchfab.com/3d-models/173a93db2b174410ac28093e3ed223fc
- Toilet — autore: hippostance — https://sketchfab.com/3d-models/132a8ee2af3a40d39d270fbed3d3666c
- Bathtub — autore: roughdominator — https://sketchfab.com/3d-models/3350f81025974c53808a2efd2b31d4fd
- Bathtub with shower — autore: hippostance — https://sketchfab.com/3d-models/22e187363dd14bc3a3e1b4611830236a
- Shower cabin — autore: Heliona — https://sketchfab.com/3d-models/e2c6a8dd490e4e4398378e1f6c9121a8
- Wooden bathroom vanity — autore: visthetique — https://sketchfab.com/3d-models/735646de9c7849159d87df810a6cc59b
- Modern sinks and faucets — autore: visthetique — https://sketchfab.com/3d-models/80b5765f34844bcc9b01b43c1a621a25
- Shower room set — autore: EvanPetrov — https://sketchfab.com/3d-models/8e13a866ee184bed95bb5b59ddee62cd
- Modern bathroom 1 — autore: dylanheyes — https://sketchfab.com/3d-models/9ba7e0a094694335bd8f4656611c0676
- Modern bathroom 2 — autore: dylanheyes — https://sketchfab.com/3d-models/f5780e11dfcb456abc1722fa5d069b05
- Towel stack — autore: matousekfoto — https://sketchfab.com/3d-models/56ebf3bf8cb445c9a743d3bf31e314bd
- Towel rail — autore: maestronoov — https://sketchfab.com/3d-models/4a6f56c65d8645479c2194fbe6a9a5c2

### Modelli soggiorno e arredamento (libreria Simpler ▸ Furniture: Living room, Sofas and armchairs, Chairs and stools, Tables and desks, Bedroom, Storage and shelves)
- Licenza: Creative Commons Attribution 4.0 (CC BY 4.0) — https://creativecommons.org/licenses/by/4.0/ — si possono usare, modificare e ridistribuire, anche a fini commerciali, citando l'autore. Non sono sotto la Simpler Content License.
- Modifiche: convertiti nel formato della libreria di Simpler e rinominati.
- Chi ridistribuisce questi modelli deve mantenere questo elenco.
- Living room ▸ Slim floor lamps — autore: hippostance — https://sketchfab.com/3d-models/0143e8771329468aa3a37746bbe7d62a
- Living room ▸ Drum shade floor lamp — autore: alpaca. — https://sketchfab.com/3d-models/1aa6739d774348efa691340e3a12b870
- Living room ▸ Modern floor lamp — autore: Justin.Foley — https://sketchfab.com/3d-models/083c9408b89949d8b201e8a1bb6ce41c
- Living room ▸ Classic brass table lamp — autore: AndreiVNK — https://sketchfab.com/3d-models/1a3292317bb342b4b33431081338a5c3
- Living room ▸ Green desk lamp — autore: clon6767 — https://sketchfab.com/3d-models/3ea0dd250740485298f9eff2ba4e97cf
- Living room ▸ Retro table lamp — autore: SilkovM — https://sketchfab.com/3d-models/888209bbca0c4709bb24f7bfa01028c1
- Living room ▸ Pendant lights — autore: gov3dstudio — https://sketchfab.com/3d-models/5edba31f2fc44062a3c53efae30e8345
- Living room ▸ Flower pendant lamp — autore: tijerin_art — https://sketchfab.com/3d-models/018cff2beb324e609446af6f64d059e2
- Living room ▸ Triangle ceiling lamp — autore: visthetique — https://sketchfab.com/3d-models/eefd2143d91a410c845619c3caccf20a
- Living room ▸ Flat screen TV — autore: hippostance — https://sketchfab.com/3d-models/f90d4fb91dd34b6791e8d66d00f96591
- Living room ▸ Low TV cabinet — autore: AleixoAlonso — https://sketchfab.com/3d-models/290cbf357b3045e591ce58e64e66b41c
- Living room ▸ Wooden TV stand — autore: slls666 — https://sketchfab.com/3d-models/b03d3365cd604e758b49c41aa652068d
- Living room ▸ Reclaimed wood TV bench — autore: grove4069 — https://sketchfab.com/3d-models/63de336ca9bc4fa68863f09be361759a
- Living room ▸ Classic fireplace — autore: bcfbox — https://sketchfab.com/3d-models/e9854400c0c1410db01c8db897ef5359
- Living room ▸ Glass vase — autore: sousinho — https://sketchfab.com/3d-models/cdc94f959e2f4b5784b60196a98cc354
- Living room ▸ Flowers in vase — autore: drmdouglass — https://sketchfab.com/3d-models/b1047276fc7f4421b5f695ad9ff59e72
- Living room ▸ Dracaena in pot — autore: asiam — https://sketchfab.com/3d-models/c2207e3e18ba454f8ceb43f208d0927c
- Living room ▸ Potted plant — autore: jeffbas — https://sketchfab.com/3d-models/7191a1b935ac452987866573713e4da5
- Living room ▸ Standing mirror — autore: dumokanart — https://sketchfab.com/3d-models/a1c6daa19b184e6aa7f02ba68dd1d985
- Living room ▸ Wall mirror — autore: rickmaolly — https://sketchfab.com/3d-models/6177cc5abd5746a4b5ff6986b8b81edc
- Living room ▸ Retro wall clock — autore: AleixoAlonso — https://sketchfab.com/3d-models/9bd21849d1d04837b4a317d1d5ac6a9e
- Living room ▸ Patchwork rug — autore: mfb64 — https://sketchfab.com/3d-models/fa968bf5d57a4265bedb233293870dc2
- Living room ▸ Curtains — autore: Heliona — https://sketchfab.com/3d-models/a83e1baf822a4442b0f50ed70d449198
- Living room ▸ Art books — autore: mfb64 — https://sketchfab.com/3d-models/3426dbfd26cd4d0395ff137d546d3ec0
- Sofas and armchairs ▸ Dark fabric sofa — autore: katjagricishina — https://sketchfab.com/3d-models/03550a3529c24611a12aa158747374e0
- Sofas and armchairs ▸ Beige modern sofa — autore: 3dimentionalben — https://sketchfab.com/3d-models/ac92f6e97eaa43c4ad6cb8f7c65ac43f
- Sofas and armchairs ▸ Chesterfield sofa — autore: leaguestudio — https://sketchfab.com/3d-models/66ba4225efaa4de59d9a9b7086363199
- Sofas and armchairs ▸ Blue fabric sofa — autore: Filipe.Soares — https://sketchfab.com/3d-models/db5d6bbf7f34482ca1be89456fcc4070
- Sofas and armchairs ▸ Leather armchair and sofa — autore: knik211 — https://sketchfab.com/3d-models/2e62bad1b0f94bdaa84bb09dd26157b5
- Sofas and armchairs ▸ Lounge armchair — autore: knik211 — https://sketchfab.com/3d-models/e9d9d87c32f144e2873765e66814f727
- Sofas and armchairs ▸ Leather armchair — autore: rickmaolly — https://sketchfab.com/3d-models/c0755830a1d54d27b86a80c335ccc9c1
- Sofas and armchairs ▸ Antique white armchair — autore: klava88 — https://sketchfab.com/3d-models/148a621c978e4c2fb9ecb6c41b852c1d
- Sofas and armchairs ▸ Blue velvet armchair — autore: undereality — https://sketchfab.com/3d-models/31570071aa0c4901bc7a1841f1e51844
- Sofas and armchairs ▸ Corner sectional sofa — autore: spookyghostboo — https://sketchfab.com/3d-models/1680cc4638ba4902ada718b8b03f6a4b
- Sofas and armchairs ▸ Black leather sofa set — autore: YouSaveTime — https://sketchfab.com/3d-models/c2ac7a44144e4b80ab51f21b59c827f8
- Sofas and armchairs ▸ Floral armchair — autore: thesidekick — https://sketchfab.com/3d-models/dfea2ba02820403784d99f7d30faeb2a
- Chairs and stools ▸ Dining chair — autore: Heliona — https://sketchfab.com/3d-models/3503f197fe8f4e2cb64d10bf44134930
- Chairs and stools ▸ Antique dining chairs — autore: soidev — https://sketchfab.com/3d-models/05e815d0f2f64647b646e9b71f8ec9ed
- Chairs and stools ▸ Office chair — autore: inven2000 — https://sketchfab.com/3d-models/af2f07d06f6349158c1d24d87f5ceb95
- Chairs and stools ▸ Modern office chair — autore: thethieme — https://sketchfab.com/3d-models/675f34f7304e4d92812a41e9750539aa
- Chairs and stools ▸ Chrome bar stool — autore: Saandy — https://sketchfab.com/3d-models/aaf556f40f634719bc80a331d2799e4f
- Chairs and stools ▸ Leather bar stool — autore: NosTeam — https://sketchfab.com/3d-models/b117e9bb6647471cbba974430dfd3726
- Tables and desks ▸ Glass dining table set — autore: topfrank2013 — https://sketchfab.com/3d-models/c41a27d7a1b24dc484bc603e1bc2d0ef
- Tables and desks ▸ Wooden dining set — autore: alihoseini13000 — https://sketchfab.com/3d-models/f852064a2ddb40419f7c764b3cfb0d3e
- Tables and desks ▸ Modern dining table set — autore: Spectrality_Studios — https://sketchfab.com/3d-models/9135349108174c8285433b3695977158
- Tables and desks ▸ Glass coffee table — autore: 3dmaedchen — https://sketchfab.com/3d-models/8f8a3dbd45534152b5771c36cc4742d9
- Tables and desks ▸ Marble coffee table — autore: dylanheyes — https://sketchfab.com/3d-models/4bb33512e4964951b3caaa929d08594e
- Tables and desks ▸ Antique round table — autore: RimasBe — https://sketchfab.com/3d-models/031dba0a7ef44158b7c3a1186438db64
- Tables and desks ▸ Pedestal side table — autore: eucocker — https://sketchfab.com/3d-models/40c5398a67394fe79fc7c74b2ea2bc6c
- Tables and desks ▸ Round side table — autore: Alex_V_13 — https://sketchfab.com/3d-models/a39f076101fa4738b01a36e27fa911aa
- Tables and desks ▸ White trestle desk — autore: Archivz — https://sketchfab.com/3d-models/c3ac11f22b6542c7a9205d93f38cf683
- Bedroom ▸ Modern bed — autore: rickmaolly — https://sketchfab.com/3d-models/b8c16d4b69f64335b46379b119b102b4
- Bedroom ▸ Carved wooden bed — autore: Maxmalow — https://sketchfab.com/3d-models/8e77fe0f95e84ca6943e8636bc042570
- Bedroom ▸ Upholstered bed — autore: bertosalotti — https://sketchfab.com/3d-models/97e361e8beda4112ac5b1b5bcd388cdf
- Bedroom ▸ Bed with storage — autore: bertosalotti — https://sketchfab.com/3d-models/cbe6e0dcc10a414a84acc5cc08171b87
- Bedroom ▸ White wardrobe — autore: Mraz3D — https://sketchfab.com/3d-models/47270ac8a40c4af8bb55d076b159122a
- Bedroom ▸ Antique dresser — autore: DarrenMcnerney3D — https://sketchfab.com/3d-models/0a46621504c24197b5653608f474f73b
- Bedroom ▸ Wooden dresser — autore: Davide.Specchi — https://sketchfab.com/3d-models/040e447fff7f40a7bf08e2506943b342
- Bedroom ▸ Minimalist modern bedroom — autore: dylanheyes — https://sketchfab.com/3d-models/4f3db3cb57bd4bce886f7b9a13273a2f
- Storage and shelves ▸ Large bookcase — autore: idmental.id — https://sketchfab.com/3d-models/8df6adc634bd4004894a5e70565dc52a
- Storage and shelves ▸ Bookshelf with books — autore: n-malmberg — https://sketchfab.com/3d-models/53ba449f3b584d1bbf6724c28e17b3e9
- Storage and shelves ▸ Open bookshelf — autore: Heliona — https://sketchfab.com/3d-models/998f0924e8e249719a33ce0fe9976267
- Storage and shelves ▸ Mid-century sideboard — autore: calebkung — https://sketchfab.com/3d-models/3028ba44d1f245b886c12eadc934f722
- Storage and shelves ▸ Chest of drawers — autore: inven2000 — https://sketchfab.com/3d-models/989876ca437a4effb8911fa52c0adb6a
- Storage and shelves ▸ White dining cabinet — autore: D.art — https://sketchfab.com/3d-models/c8717576f2244716b3abf321065f2b9a

### Veicoli (libreria Simpler ▸ Vehicles: Cars, Trucks and vans, Farm and construction, Aircraft, Boats, Motorcycles and bikes)
- Licenza: Creative Commons Attribution 4.0 (CC BY 4.0) — https://creativecommons.org/licenses/by/4.0/ — si possono usare, modificare e ridistribuire, anche a fini commerciali, citando l'autore. Non sono sotto la Simpler Content License.
- Modifiche: convertiti nel formato della libreria di Simpler e rinominati con nomi generici. Alcuni modelli riproducono veicoli reali: i marchi e i nomi dei costruttori appartengono ai loro proprietari e Simpler non è affiliato a loro.
- Chi ridistribuisce questi modelli deve mantenere questo elenco.
- Cars ▸ Modern sedan — autore: mmcworks — https://sketchfab.com/3d-models/58c33766470d46e7b2aed542650494e5
- Cars ▸ American 70s sedan — autore: barbo-autos — https://sketchfab.com/3d-models/78f76d386a4341b0b71745bdc50fd5ab
- Cars ▸ Police car — autore: jeandiz — https://sketchfab.com/3d-models/9166b13b6ae341f4bfc093edb71d74f4
- Cars ▸ Yellow taxi — autore: haoliu95 — https://sketchfab.com/3d-models/2429a825ff1646568e8e6e1453f9c501
- Trucks and vans ▸ Delivery van — autore: evan.hiltz — https://sketchfab.com/3d-models/0b2f1ad95a79419f9a092420024d329c
- Trucks and vans ▸ Vintage pickup truck — autore: creosine — https://sketchfab.com/3d-models/d52c6ed3b0ee4d9eb562f875b3c448a4
- Trucks and vans ▸ Modern European truck — autore: DevPoly3D — https://sketchfab.com/3d-models/34ce748d9a4b4de7b035cfe5cb97f5d1
- Trucks and vans ▸ American semi truck — autore: 3DE_Study — https://sketchfab.com/3d-models/3e8c5275aeab487fa37d227ce0bd1a9a
- Farm and construction ▸ Vintage tractor — autore: thesidekick — https://sketchfab.com/3d-models/85720bad20b341ec8508ddbc84f11795
- Farm and construction ▸ Modern tractor — autore: heynic — https://sketchfab.com/3d-models/56d7c8e7e2cb4d15a3d80cc42c697c53
- Farm and construction ▸ Classic tractor — autore: le0tard — https://sketchfab.com/3d-models/278fc1e0516c401eba358d3aa2e55635
- Farm and construction ▸ Orange excavator — autore: thesidekick — https://sketchfab.com/3d-models/3dde2c846cc54a4d9fabcc821c9b9caa
- Farm and construction ▸ Yellow excavator — autore: thesidekick — https://sketchfab.com/3d-models/a805e66f565a412682ac8ce45ab9ac3e
- Farm and construction ▸ Orange forklift — autore: mohammad6511 — https://sketchfab.com/3d-models/73d21c990e634589b0c130777751be28
- Aircraft ▸ Airliner — autore: helijah — https://sketchfab.com/3d-models/28e201042a8441f1bd4403578eda1231
- Aircraft ▸ Twin-prop airplane — autore: helijah — https://sketchfab.com/3d-models/8d66cde0c190433e9444a771e6115208
- Aircraft ▸ Helicopter — autore: irs1182 — https://sketchfab.com/3d-models/91366449ce6842f784748a914e29d641
- Boats ▸ Old fishing boat — autore: aurelien.d — https://sketchfab.com/3d-models/2f894eb760ca49eca14c38c2d49058a1
- Boats ▸ Antique motorboat — autore: trivial.cat — https://sketchfab.com/3d-models/21bcd49240a54f2b879dd3f91de4fca3
- Boats ▸ Large yacht — autore: sergeif — https://sketchfab.com/3d-models/0dd451f295d049cea20c17d3ffa87ee3
- Boats ▸ Small yacht — autore: miguelangelo2k — https://sketchfab.com/3d-models/09a9fc4a0061464fba1bc3ba76848869
- Motorcycles and bikes ▸ Classic motorcycle — autore: DeclanLea14 — https://sketchfab.com/3d-models/f246ff1a68d3459892f9420b744a58b6
- Motorcycles and bikes ▸ Vintage bicycle — autore: vlad.neko — https://sketchfab.com/3d-models/1795f6e907634afda88fdaf45f67b279
- Motorcycles and bikes ▸ Moped — autore: Tomasoo — https://sketchfab.com/3d-models/fe75689a108744b7acf5003d677d4c8e
- Motorcycles and bikes ▸ Retro scooter — autore: annaandrei — https://sketchfab.com/3d-models/d2841db11a87440b990a595c3a3f46d1
- Motorcycles and bikes ▸ Electric scooter — autore: niilo.poutanen — https://sketchfab.com/3d-models/9479a6d3f1474971afde26b33fe96c55

### Arredo urbano (libreria Simpler ▸ Street furniture: Benches and bins, Lighting, Signs and barriers, Bus stops and kiosks, Urban details)
- Licenza: Creative Commons Attribution 4.0 (CC BY 4.0) — https://creativecommons.org/licenses/by/4.0/ — si possono usare, modificare e ridistribuire, anche a fini commerciali, citando l'autore. Non sono sotto la Simpler Content License.
- Modifiche: convertiti nel formato della libreria di Simpler e rinominati.
- Chi ridistribuisce questi modelli deve mantenere questo elenco.
- Benches and bins ▸ Cast iron park bench — autore: dutrabr98 — https://sketchfab.com/3d-models/84426d6537ac4cdc837d602ccabe7036
- Benches and bins ▸ Wooden street bench — autore: donnichols — https://sketchfab.com/3d-models/1ddafec2fda5430697aaf403b3deba96
- Benches and bins ▸ Granite bench — autore: sinnervoncrawsz — https://sketchfab.com/3d-models/424c3679dcdd44d380da36a82f5dc382
- Benches and bins ▸ Concrete bench with wood seat — autore: sinnervoncrawsz — https://sketchfab.com/3d-models/2eec0b2d47f94db38ea31e8c3d2aab07
- Benches and bins ▸ Steel and wood litter bin — autore: luca3d — https://sketchfab.com/3d-models/3057e7f5b6c441fcb67c44e68d77dd38
- Benches and bins ▸ Wheelie bin — autore: dk_artist — https://sketchfab.com/3d-models/9044ac8d545747e3959278fbe36fce8b
- Lighting ▸ Victorian street lamp — autore: Discovered — https://sketchfab.com/3d-models/b7cebcfb4b1c4d4a97e22072800704ca
- Lighting ▸ Classic street lamp — autore: bez_glaza — https://sketchfab.com/3d-models/6881aa1e84b047d79860fa9297e05e22
- Lighting ▸ Modern street light — autore: sebastianramirez3d — https://sketchfab.com/3d-models/6cfedb57645b42b4a11d6c06411014b6
- Lighting ▸ Double globe lamp post — autore: dasmodal — https://sketchfab.com/3d-models/56f6dcb3865144cd84e049ca6a736fae
- Lighting ▸ Park lamp post — autore: sousinho — https://sketchfab.com/3d-models/ff5e3bc99dd146d986cb662813ec988e
- Signs and barriers ▸ Barrier gate — autore: sousinho — https://sketchfab.com/3d-models/85b489ac36344ca9af98a78ecffa186f
- Signs and barriers ▸ Concrete barrier with graffiti — autore: widthRider — https://sketchfab.com/3d-models/a09622c043724a1b92e7920b22edb6bf
- Signs and barriers ▸ Jersey barrier — autore: emran.bayati — https://sketchfab.com/3d-models/b52246c9611a42a99a03b425535a0237
- Signs and barriers ▸ Roadwork cones and signs — autore: notanotherapocalypticco — https://sketchfab.com/3d-models/e03b1d2dfdc0416bb8324d15573ea60c
- Bus stops and kiosks ▸ Bus shelter — autore: pukkafilms — https://sketchfab.com/3d-models/32cc4c5f6aa147acabdb173e2d2373fa
- Bus stops and kiosks ▸ Small bus shelter — autore: Mentailst — https://sketchfab.com/3d-models/f0e7ff79b95d461bb69f5e927b5db062
- Bus stops and kiosks ▸ Phone booth — autore: tribhuvantechnoart — https://sketchfab.com/3d-models/d86b8632da384514965b9d920815334e
- Urban details ▸ Fire hydrant — autore: jvouillon — https://sketchfab.com/3d-models/7f9164e6018c4ec7a3585bbf6e6d70df
- Urban details ▸ Orange bollard — autore: dk_artist — https://sketchfab.com/3d-models/1ccd0c761fc744a3a62e168044a9d2eb
- Urban details ▸ Bike rack — autore: Sam54123 — https://sketchfab.com/3d-models/bb71ca627c5c44aba68c610fbfa24cd2
- Urban details ▸ Tree grate — autore: LadyLionStudios — https://sketchfab.com/3d-models/49e4e7452a5d4ced92053bcb4facbf31
- Urban details ▸ Parking meter — autore: Raffey — https://sketchfab.com/3d-models/cfaf0f457ca244e59c746ebdd6f3ad6c

### Giardino, terrazzo e ufficio (libreria Simpler ▸ Garden and terrace, Office)
- Licenza: Creative Commons Attribution 4.0 (CC BY 4.0) — https://creativecommons.org/licenses/by/4.0/ — si possono usare, modificare e ridistribuire, anche a fini commerciali, citando l'autore. Non sono sotto la Simpler Content License.
- Modifiche: convertiti nel formato della libreria di Simpler e rinominati.
- Chi ridistribuisce questi modelli deve mantenere questo elenco.
- Garden and terrace ▸ Patio set with umbrella — autore: zhixson — https://sketchfab.com/3d-models/37c3f6ee451f495ba183427a38a804b4
- Garden and terrace ▸ Modern outdoor lounge set — autore: ulugbekdizayn — https://sketchfab.com/3d-models/010bd90929894f32a7caa781c9f8f6a8
- Garden and terrace ▸ White patio umbrella — autore: Ngo.Phuoc.Truong — https://sketchfab.com/3d-models/d6c9705a4f8e421ea473196ab9910088
- Garden and terrace ▸ Wooden porch swing — autore: Maho_Itz — https://sketchfab.com/3d-models/c88d76ad794b468580b618957a500bd8
- Garden and terrace ▸ Teak lounge set — autore: que_3d — https://sketchfab.com/3d-models/6a6c0f882e0e444c9d95dee1b0cadda1
- Garden and terrace ▸ Striped deck chair — autore: MaX3Dd — https://sketchfab.com/3d-models/38de6171cbeb41c5bdc49c07df76ede9
- Garden and terrace ▸ Double sun lounger with canopy — autore: kirill8666kirill — https://sketchfab.com/3d-models/1eda19e39d1c4580acf56bd981bab8e5
- Garden and terrace ▸ Outdoor dining set with umbrella — autore: jennybria — https://sketchfab.com/3d-models/6b0a3a894a664e3d88520ccd905cfd40
- Garden and terrace ▸ Modern outdoor dining table — autore: pukkafilms — https://sketchfab.com/3d-models/4043690aacb34d41b9ace951ad623f45
- Garden and terrace ▸ Folding bistro set — autore: mohamedhussien — https://sketchfab.com/3d-models/3d7da670439449b9ab14c95fcc6f1918
- Garden and terrace ▸ Wooden outdoor coffee table — autore: Gian.Luca — https://sketchfab.com/3d-models/04346631ca1e4c66b93586ada9756110
- Garden and terrace ▸ Outdoor sofa — autore: simone_rizzi — https://sketchfab.com/3d-models/f761658fafcc42a78fd42912ef9f57e9
- Garden and terrace ▸ Hanging egg chair — autore: klessgyzen — https://sketchfab.com/3d-models/ed88609057db40bf94a5b79ff6485410
- Garden and terrace ▸ Wire lounge chair — autore: simone_rizzi — https://sketchfab.com/3d-models/8d50f071d9054909826b23d6bc2e3bd6
- Garden and terrace ▸ Gas barbecue — autore: TemurG — https://sketchfab.com/3d-models/d2b1e612f17141f3ae8921167ca91efb
- Garden and terrace ▸ Charcoal barbecue — autore: patrakeevasveta — https://sketchfab.com/3d-models/59563705c8a34eefafa177d8d22f35c5
- Garden and terrace ▸ Wooden pergola — autore: michalbroz — https://sketchfab.com/3d-models/b728a581a70547418e077d223d2a7828
- Garden and terrace ▸ Pool ladder — autore: plaggy — https://sketchfab.com/3d-models/43cbe4e6e68140e1ad202cf8a3e53650
- Garden and terrace ▸ Plastic garden chair — autore: kuuttisiitonen — https://sketchfab.com/3d-models/68089dce5fa1461981d690f1cfd657fa
- Office ▸ Ultrawide monitor — autore: dylanheyes — https://sketchfab.com/3d-models/f84d24b6df3648d884fd9be9c8007dd4
- Office ▸ Laptop — autore: Aullwen — https://sketchfab.com/3d-models/7d870e900889481395b4a575b9fa8c3e
- Office ▸ Keyboard and mouse — autore: gorzi90 — https://sketchfab.com/3d-models/c63ee81b71ff45b68a778101b4df3d46
- Office ▸ Office printer — autore: nokillnando — https://sketchfab.com/3d-models/d55f6fca7c3d45c883bbff770672970d
- Office ▸ Desk lamp — autore: BlueHour — https://sketchfab.com/3d-models/7377ec591df04445a1aae370017aaa13
- Office ▸ Banker's desk lamp — autore: Noahouou — https://sketchfab.com/3d-models/b8e13a49528e4231a0512bb5f18f07e5
- Office ▸ Office phone — autore: maxdragon — https://sketchfab.com/3d-models/4176a01b6d0b4d13ad165c0df278a6b5
- Office ▸ Whiteboard — autore: arlinetjandra — https://sketchfab.com/3d-models/858a2d94034f48ebbbbbd1f07494cea0
- Office ▸ Mesh office chair — autore: j.a.m — https://sketchfab.com/3d-models/41973aa1808d4a13b84c24497fc77c63
- Office ▸ Antique wooden desk — autore: mkky — https://sketchfab.com/3d-models/536ee7c5cfb94775ae3eff608bd9fecf

### Natura (libreria Simpler ▸ Nature: Rocks, Ground debris, Logs and stumps, Beach)

- Licenza: Creative Commons Attribution 4.0 (CC BY 4.0) — https://creativecommons.org/licenses/by/4.0/ — si possono usare, modificare e ridistribuire, anche a fini commerciali, citando l'autore. Non sono sotto la Simpler Content License.

- Rocks ▸ Grey boulder — autore: siesta — https://sketchfab.com/3d-models/b66d5b63deb447299ca3effa904bc789
- Rocks ▸ Speckled rock — autore: norgeotloic — https://sketchfab.com/3d-models/462ba9c87ce1445191899a6b74f4203c
- Rocks ▸ Ochre rock — autore: norgeotloic — https://sketchfab.com/3d-models/8ffb23ed14824fc29f53dde52398e22b
- Rocks ▸ White river stone — autore: norgeotloic — https://sketchfab.com/3d-models/6195afc03d5f4c539273aa24873ef808
- Rocks ▸ Mossy rock pile — autore: thesidekick — https://sketchfab.com/3d-models/b7461a9388fc4a6f96726d54df7e641d
- Rocks ▸ Large grey rock — autore: 3dhdscan — https://sketchfab.com/3d-models/70b586d54a1e46ab9398f25369a39df3
- Ground debris ▸ Large pile of leaves — autore: matousekfoto — https://sketchfab.com/3d-models/48807f86fd03406aa6b813ca026b0ad1
- Ground debris ▸ Scattered leaves — autore: matousekfoto — https://sketchfab.com/3d-models/9b7df4b198854ccb885dd7796011796a
- Ground debris ▸ Pine cone — autore: nikska — https://sketchfab.com/3d-models/55372cc6491d438db509bd17b016c75c
- Ground debris ▸ Pine cone with scales open — autore: JonasSchramme — https://sketchfab.com/3d-models/025f0626a5be48be8e3ec04298d4db39
- Ground debris ▸ Fallen pine branch 1 — autore: perz_scans — https://sketchfab.com/3d-models/f5ad948275cd4d13ba3ce2040b72ed47
- Ground debris ▸ Fallen pine branch 2 — autore: perz_scans — https://sketchfab.com/3d-models/eca72dd7e85941eb8ecb9907df8aa560
- Ground debris ▸ Dead wood — autore: plaggy — https://sketchfab.com/3d-models/898e076697144cffbbf17011bf2e3ac2
- Logs and stumps ▸ Mossy log — autore: julianmalik — https://sketchfab.com/3d-models/c65a00ca4a174653beb4c59cb42b9143
- Logs and stumps ▸ Large log — autore: julianmalik — https://sketchfab.com/3d-models/5a3b7ba7b639427ea970ccca90553aab
- Logs and stumps ▸ Pile of logs — autore: MrUnityCreations — https://sketchfab.com/3d-models/57ebf2b09f7745e2a65da9441e989437
- Logs and stumps ▸ Woodpile — autore: apariciosilva3D — https://sketchfab.com/3d-models/fcd5d5993be64ca38ef8ae2926574874
- Logs and stumps ▸ Poplar stump — autore: matousekfoto — https://sketchfab.com/3d-models/604a5c25e3b84fa0ae520460112c9f92
- Logs and stumps ▸ Mossy stump — autore: nedo — https://sketchfab.com/3d-models/f91647d2969049329a605095febd1c96
- Logs and stumps ▸ Dead oak stump — autore: chrisg4919 — https://sketchfab.com/3d-models/c6b6469facad4fc3b77d866bfc2bd913
- Beach ▸ Scallop shell — autore: kevinscofield — https://sketchfab.com/3d-models/f61affe06e6b48cb8ba40f60139fa0d1
- Beach ▸ Cockle shell — autore: vlands3d — https://sketchfab.com/3d-models/f7c760e4f9e24abea2065964721b2e76
- Beach ▸ Spiky seashell — autore: yakaras — https://sketchfab.com/3d-models/b91a711b424c47779c3f39dc1d1b0564
- Beach ▸ Conch shell — autore: panoluma — https://sketchfab.com/3d-models/e4d2903fd8c643669c2d3b3ab081e5e7
- Beach ▸ Pine driftwood — autore: crufro — https://sketchfab.com/3d-models/95d1087e513e4fb992a27b7b8a05ca9e
- Beach ▸ Driftwood sculpture — autore: dbarnum11 — https://sketchfab.com/3d-models/f30401734e6040c0aa5efa0735ee6bc9

### Rifiuti (libreria Simpler ▸ Trash)

- Licenza: Creative Commons Attribution 4.0 (CC BY 4.0) — https://creativecommons.org/licenses/by/4.0/ — si possono usare, modificare e ridistribuire, anche a fini commerciali, citando l'autore. Non sono sotto la Simpler Content License. Modifiche: scala portata alla misura reale, i set divisi in pezzi, convertiti nel formato di Simpler.

- Bottle 1 … Bottle 7 — autore: viraj chavan (virajsc) — https://sketchfab.com/3d-models/0262aab0829a47d48cae63c21dd6f9bc
- Can sqaure, Can crushed, Can open — autore: Sunbox Games (sunboxgames) — https://sketchfab.com/3d-models/5f4c354cf4474c58bad147b346399a5f
- Crumpled papers — autore: Sunbox Games (sunboxgames) — https://sketchfab.com/3d-models/7f8b8e5eeb74428f9f326a398baccb5d
- Cigarette butts — autore: Sunbox Games (sunboxgames) — https://sketchfab.com/3d-models/52ecf4556be14ffc9226b48eac330feb
- Crumpled egg carton — autore: Sunbox Games (sunboxgames) — https://sketchfab.com/3d-models/dad429594e5a4019b9f3cee4e08ad47d
- Burger box — autore: -Arthur- (.arthur) — https://sketchfab.com/3d-models/1e051f09b2e24692b683531024cee047
- Crushed can scan — autore: Diego (drkolo) — https://sketchfab.com/3d-models/0cd1011264b3437bb5e71cdcca6db243
- Bottle cap — autore: Jonas (PactorDK) — https://sketchfab.com/3d-models/a8cc85988d7d44a9875bf3b4f112f162
- Paper bag — autore: sixonetwo (evan4129) — https://sketchfab.com/3d-models/9a62b0f87a1a4a2caacbe798f169c414
- Paper cup — autore: RoboHoloclone12 — https://sketchfab.com/3d-models/1903f3873e2b44d2b71d37c2fa19f43a
- Discarded mask — autore: Marc Sawyer (whitewashstudio) — https://sketchfab.com/3d-models/e778607a19f64f1ca7bd5f405252130f
- Crumpled paper — autore: Darxkl05 — https://sketchfab.com/3d-models/f19ea7ce149c4b25a527abecec1da524
- Chips bag — autore: ZwiebelGames — https://sketchfab.com/3d-models/cacbcc48c4c8470fb2d77cd7e9e469f4
- Pizza box — autore: Scott VanArsdale (vanart) — https://sketchfab.com/3d-models/d589d532b2f64855be79403cfa0bf373

### Stanze Interni (libreria Materiali ▸ Simpler ▸ Interiors)

- 16 stanze create con Simpler (Blender/Cycles) con i modelli della libreria Simpler citati sopra (stessi autori e licenze) e con texture Poly Haven (CC0).

### Cespugli (libreria Vegetation ▸ Simpler ▸ Bushes)

- bush1, bush2 — creati dal Titolare con PlantFactory.

### Stanze del tipo Interni (engine/assets/interiors)

- room_test — creata con Simpler (Blender/Cycles) da make_interiors.py, nella stessa cartella.

### Decal di Simpler (libreria Decal ▸ Simpler)

- Graffiti, Cracks, Footprints, Tyre tracks, Rust and leaks, Water stains ▸ Rising damp e Ceiling water stain: create da Simpler (dominio pubblico, CC0). I graffiti usano i caratteri Sedgwick Ave Display e Knewave (SIL Open Font License 1.1) e Permanent Marker (Apache 2.0): le immagini fatte con un carattere sono libere; i caratteri non sono distribuiti.
- Dirt and grime ▸ Grimy wall patch, Dusty patch, Streaky grime, Soft smudge; Water stains ▸ Heavy water stains, Water run-off stains, Dripping water marks, Weathered water streaks — dalle Decal 01, 05, 06, 19, 09, 10, 11, 12 di ShareTextures (CC0) — https://www.sharetextures.com/textures/surfaceimperfection
- Dirt and grime ▸ Wall base dirt — da Decals 0001 di TextureCan (CC0) — https://www.texturecan.com/details/333/

## Contenuti dell'utente

I modelli, le texture e i materiali che importi (per esempio collezioni acquistate come Archmodels di Evermotion, o modelli scaricati da altri siti) restano sotto la licenza con cui li hai ottenuti: Simpler non la cambia e non li distribuisce.

## Nomi e marchi citati

Blender e Cycles (Blender Foundation), Poly Haven, ambientCG, OpenAI e GPT Image, Krea, GitHub, Sketchfab, Microsoft, Windows, WebView2 e .NET, Evermotion e Archmodels, ShareTextures e TextureCan sono marchi o nomi dei rispettivi proprietari. Sono citati solo per indicare da dove vengono i contenuti; Simpler non è affiliato a loro.

## Note per la distribuzione

- Tutto il codice di Simpler (applicazione e motore) è distribuito con la GNU GPL versione 3 o successiva: il pacchetto di distribuzione include il testo della licenza (file LICENSE) e i sorgenti completi sono pubblicati insieme a ogni versione.
- DeepBump (GPL v3): il pacchetto di distribuzione deve includerne sorgenti e licenza (già in tools/deepbump).
