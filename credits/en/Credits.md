# Simpler licenses and credits

This page lists the programs, libraries, services and content by other authors that Simpler uses, with their licenses, and the product names mentioned. It is updated in every version that adds something.

Last update: Simpler 1.78.5, 9 November 2026. The license agreement accepted at the first start can be read again with the «License agreement» button at the top of this window.

## Simpler

- Simpler (the Windows application and the engine running inside Blender): © 2026 Luca Rodolfi, free software under the GNU GPL version 3 or later. The parts by other authors listed below stay under their own licenses.
- Included models and plants and .simplerpack packs: Simpler Content License 1.0, except the content with a different license listed below. The name «Simpler» and the logo are not covered by the GPL.
- The images, renders and projects you make with Simpler are yours.

## Programs and libraries

### Blender and Cycles (render engine)
- Author: Blender Foundation and contributors — https://www.blender.org
- Version used: Blender 5.2.2 LTS, run as a separate program.
- License: GNU GPL version 2 or later; distributed Blender programs fall under GNU GPL version 3 or later. Cycles: Apache License 2.0.
- What you make with Blender (images, .blend files) is yours.

### three.js (real-time view)
- Authors: three.js authors — https://threejs.org
- Version: 0.186.1, with the OrbitControls, TransformControls, GLTFLoader, RoomEnvironment, BufferGeometryUtils, SkeletonUtils addons.
- License: MIT (text in web/lib/LICENSE-three.txt).

### three-mesh-bvh
- Author: Garrett Johnson — https://github.com/gkjohnson/three-mesh-bvh
- Version: 0.9.14. License: MIT (text in web/lib/bvh/LICENSE).

### meshoptimizer (mesh simplification)
- Author: Arseny Kapoulkine — https://github.com/zeux/meshoptimizer
- Version: 1.2.0. License: MIT (text in web/lib/meshopt/LICENSE.md).

### Microsoft WebView2 and .NET
- Microsoft.Web.WebView2 1.0.4129.50 (the panel showing the real-time view): Microsoft license of the WebView2 SDK package; the WebView2 runtime is the one of Windows.
- .NET 8 / WPF: Microsoft, MIT license.

### DeepBump (normal, height maps and upscaling from textures)
- Author: Hugo Tini — https://github.com/HugoTini/DeepBump
- Unmodified copy (commit fad19ba, 17 March 2025), sources and models included in tools/deepbump.
- License: GNU GPL version 3 (text in tools/deepbump/LICENSE). Simpler runs it as a separate program; Simpler's code contains no DeepBump code.
- Libraries installed on first use in %LOCALAPPDATA%\Simpler\deepbump-libs: onnxruntime (Microsoft, MIT), imageio (BSD 2-Clause), numpy (BSD 3-Clause), Pillow (MIT-CMU).

## Online services

### Poly Haven (3D models, materials, HDRIs and backgrounds)
- https://polyhaven.com — CC0 content (public domain): usable for any purpose, commercial too, no attribution required.
- Simpler downloads it on first use through Poly Haven's public API.

### ambientCG (decals and materials)
- https://ambientcg.com — by Lennart Demes, CC0 content (public domain).
- Simpler downloads the decals (Decals ▸ ambientCG menu) through ambientCG's public API.

### NASA Scientific Visualization Studio (night stars and moon)
- Stars: "Deep Star Maps 2020" — https://svs.gsfc.nasa.gov/4851 — visualisation by Ernie Wright (USRA); star data Hipparcos-2, Tycho-2, UCAC3 and Gaia DR2 (ESA/Gaia/DPAC).
- Moon: "CGI Moon Kit" (LROC colour map of the Lunar Reconnaissance Orbiter) — https://svs.gsfc.nasa.gov/4720
- Credit requested by NASA: "NASA's Scientific Visualization Studio"; for the stars also ESA/Gaia/DPAC for the Gaia data. The pages state no explicit licence and refer to NASA's media usage guidelines; NASA images are generally not copyrighted, but may not be used to imply an endorsement by NASA.
- Simpler downloads the two files (about 35 MB) the first time a night needs them.

### OpenAI (AI functions on images)
- https://openai.com — GPT Image models, used only with the user's own key and under OpenAI's terms of use.
- The images sent and received go through OpenAI's servers.

### Krea (AI video)
- https://www.krea.ai — video models, used only with the user's own key and under Krea's terms of use.
- The images sent and the videos received go through Krea's servers.

### rodluc.com (Simpler's website)
- https://www.rodluc.com/simpler/ — at start, at most once a day, Simpler asks whether there is a new version, sending only the version number and the language; the site keeps only the number of checks per day, version and language (no IP address, no identifier). Downloads of packs, models and ecosystems are counted the same way, with no data about who downloads. The check can be switched off in Settings ▸ Updates.
- The pages of what's new and of the download open in the browser only when you ask.
- «Suggest an idea» opens the website's ideas page only when you click it; it receives the version, the language and what you write in the form. The IP address is not saved.

### GitHub (source code and installation)
- https://github.com — Simpler's source code and installation files. Simpler does not connect to GitHub by itself: the page opens in the browser only when you ask.

If a service cannot be reached (for example without a connection), Simpler keeps working; the operations it does by itself in the background, such as the update check, ignore it without error messages.

### Sketchfab (models downloaded by the user)
- https://sketchfab.com — Simpler downloads nothing from Sketchfab by itself: the models you download stay under the license shown on their page.

## Content included in Simpler

- Interface icons: drawn for Simpler.
- Primitive thumbnails (primitives/*.png): rendered with Simpler.
- «Cosmetic shop» example scene (samples folder): SketchUp CGtips models included with CGtips' permission for non-commercial purposes, such as education and showcasing. They are covered neither by the GPL nor by the Simpler Content License: they may not be sold or redistributed for commercial purposes. Whoever redistributes Simpler commercially must remove the samples folder.
- «Bedroom» example scene (samples folder): the model «Minimalistic Modern Bedroom» by dylanheyes (https://sketchfab.com/3d-models/4f3db3cb57bd4bce886f7b9a13273a2f), licensed under Creative Commons Attribution 4.0 (CC BY 4.0): it may be used, changed and redistributed, also commercially, crediting the author. Changes: converted to the Simpler format, renamed and set in a Simpler scene.
- «Tiles» ground texture, start image, import wizard image, AI function cards and sky reference photos (dawn, cloudy, sunset): checked by the author for use in Simpler.
- Fonts: Windows' Segoe UI and Cascadia Mono (not included in Simpler).

### Kitchen and bathroom models (Simpler library ▸ Furniture ▸ Kitchen and bathroom)
- License: Creative Commons Attribution 4.0 (CC BY 4.0) — https://creativecommons.org/licenses/by/4.0/ — they may be used, changed and redistributed, also commercially, crediting the author. They are not under the Simpler Content License.
- Changes: converted to the Simpler library format and renamed.
- Whoever redistributes these models must keep this list.
- Modern fridge — author: dylanheyes — https://sketchfab.com/3d-models/366f7dfa18744ccf8cee119f26446022
- Retro fridge — author: dylanheyes — https://sketchfab.com/3d-models/3b130f0ba4304966a101c82be2429cc7
- Old fridge — author: dylanheyes — https://sketchfab.com/3d-models/68d173f205344455933f861042b99fe3
- Grey refrigerator — author: glowbox3d — https://sketchfab.com/3d-models/2071bda681b642218b6829b82e4fd93b
- Retro microwave — author: dylanheyes — https://sketchfab.com/3d-models/0cbcd57eef2a47a4b5e3cef9150933bd
- Stove with hood — author: hippostance — https://sketchfab.com/3d-models/ce6f590e7cb848e398c80208ee3b6fdf
- Range hood — author: rickmaolly — https://sketchfab.com/3d-models/4033aa7ba4ef4d4c87ab7f514ac4ae44
- Dishwasher — author: rickmaolly — https://sketchfab.com/3d-models/7a4d8ed6ece248a596ec4dfb5741e7cc
- Coffee maker — author: Ryan_Nein — https://sketchfab.com/3d-models/383923d4412f4b66937d9c1779a9a0a2
- Kitchen sink — author: hippostance — https://sketchfab.com/3d-models/504248ed68e3480a807aced6f002b2d5
- Modular kitchen cabinets — author: sauti — https://sketchfab.com/3d-models/4b765920f7c34676acda91c0bfd87abd
- Modern kitchen — author: dylanheyes — https://sketchfab.com/3d-models/9843a830b96142a9a53f45f25304d93c
- Small modern kitchen — author: dylanheyes — https://sketchfab.com/3d-models/2cc658a96e304a6d9db1813233ed90d1
- Kitchen set — author: EvanPetrov — https://sketchfab.com/3d-models/1bf20d2de7f749d889d69c42207ca669
- Kitchen decor set — author: visthetique — https://sketchfab.com/3d-models/173a93db2b174410ac28093e3ed223fc
- Toilet — author: hippostance — https://sketchfab.com/3d-models/132a8ee2af3a40d39d270fbed3d3666c
- Bathtub — author: roughdominator — https://sketchfab.com/3d-models/3350f81025974c53808a2efd2b31d4fd
- Bathtub with shower — author: hippostance — https://sketchfab.com/3d-models/22e187363dd14bc3a3e1b4611830236a
- Shower cabin — author: Heliona — https://sketchfab.com/3d-models/e2c6a8dd490e4e4398378e1f6c9121a8
- Wooden bathroom vanity — author: visthetique — https://sketchfab.com/3d-models/735646de9c7849159d87df810a6cc59b
- Modern sinks and faucets — author: visthetique — https://sketchfab.com/3d-models/80b5765f34844bcc9b01b43c1a621a25
- Shower room set — author: EvanPetrov — https://sketchfab.com/3d-models/8e13a866ee184bed95bb5b59ddee62cd
- Modern bathroom 1 — author: dylanheyes — https://sketchfab.com/3d-models/9ba7e0a094694335bd8f4656611c0676
- Modern bathroom 2 — author: dylanheyes — https://sketchfab.com/3d-models/f5780e11dfcb456abc1722fa5d069b05
- Towel stack — author: matousekfoto — https://sketchfab.com/3d-models/56ebf3bf8cb445c9a743d3bf31e314bd
- Towel rail — author: maestronoov — https://sketchfab.com/3d-models/4a6f56c65d8645479c2194fbe6a9a5c2

### Living room and furniture models (Simpler library ▸ Furniture: Living room, Sofas and armchairs, Chairs and stools, Tables and desks, Bedroom, Storage and shelves)
- License: Creative Commons Attribution 4.0 (CC BY 4.0) — https://creativecommons.org/licenses/by/4.0/ — they may be used, changed and redistributed, also commercially, crediting the author. They are not under the Simpler Content License.
- Changes: converted to the Simpler library format and renamed.
- Whoever redistributes these models must keep this list.
- Living room ▸ Slim floor lamps — author: hippostance — https://sketchfab.com/3d-models/0143e8771329468aa3a37746bbe7d62a
- Living room ▸ Drum shade floor lamp — author: alpaca. — https://sketchfab.com/3d-models/1aa6739d774348efa691340e3a12b870
- Living room ▸ Modern floor lamp — author: Justin.Foley — https://sketchfab.com/3d-models/083c9408b89949d8b201e8a1bb6ce41c
- Living room ▸ Classic brass table lamp — author: AndreiVNK — https://sketchfab.com/3d-models/1a3292317bb342b4b33431081338a5c3
- Living room ▸ Green desk lamp — author: clon6767 — https://sketchfab.com/3d-models/3ea0dd250740485298f9eff2ba4e97cf
- Living room ▸ Retro table lamp — author: SilkovM — https://sketchfab.com/3d-models/888209bbca0c4709bb24f7bfa01028c1
- Living room ▸ Pendant lights — author: gov3dstudio — https://sketchfab.com/3d-models/5edba31f2fc44062a3c53efae30e8345
- Living room ▸ Flower pendant lamp — author: tijerin_art — https://sketchfab.com/3d-models/018cff2beb324e609446af6f64d059e2
- Living room ▸ Triangle ceiling lamp — author: visthetique — https://sketchfab.com/3d-models/eefd2143d91a410c845619c3caccf20a
- Living room ▸ Flat screen TV — author: hippostance — https://sketchfab.com/3d-models/f90d4fb91dd34b6791e8d66d00f96591
- Living room ▸ Low TV cabinet — author: AleixoAlonso — https://sketchfab.com/3d-models/290cbf357b3045e591ce58e64e66b41c
- Living room ▸ Wooden TV stand — author: slls666 — https://sketchfab.com/3d-models/b03d3365cd604e758b49c41aa652068d
- Living room ▸ Reclaimed wood TV bench — author: grove4069 — https://sketchfab.com/3d-models/63de336ca9bc4fa68863f09be361759a
- Living room ▸ Classic fireplace — author: bcfbox — https://sketchfab.com/3d-models/e9854400c0c1410db01c8db897ef5359
- Living room ▸ Glass vase — author: sousinho — https://sketchfab.com/3d-models/cdc94f959e2f4b5784b60196a98cc354
- Living room ▸ Flowers in vase — author: drmdouglass — https://sketchfab.com/3d-models/b1047276fc7f4421b5f695ad9ff59e72
- Living room ▸ Dracaena in pot — author: asiam — https://sketchfab.com/3d-models/c2207e3e18ba454f8ceb43f208d0927c
- Living room ▸ Potted plant — author: jeffbas — https://sketchfab.com/3d-models/7191a1b935ac452987866573713e4da5
- Living room ▸ Standing mirror — author: dumokanart — https://sketchfab.com/3d-models/a1c6daa19b184e6aa7f02ba68dd1d985
- Living room ▸ Wall mirror — author: rickmaolly — https://sketchfab.com/3d-models/6177cc5abd5746a4b5ff6986b8b81edc
- Living room ▸ Retro wall clock — author: AleixoAlonso — https://sketchfab.com/3d-models/9bd21849d1d04837b4a317d1d5ac6a9e
- Living room ▸ Patchwork rug — author: mfb64 — https://sketchfab.com/3d-models/fa968bf5d57a4265bedb233293870dc2
- Living room ▸ Curtains — author: Heliona — https://sketchfab.com/3d-models/a83e1baf822a4442b0f50ed70d449198
- Living room ▸ Art books — author: mfb64 — https://sketchfab.com/3d-models/3426dbfd26cd4d0395ff137d546d3ec0
- Sofas and armchairs ▸ Dark fabric sofa — author: katjagricishina — https://sketchfab.com/3d-models/03550a3529c24611a12aa158747374e0
- Sofas and armchairs ▸ Beige modern sofa — author: 3dimentionalben — https://sketchfab.com/3d-models/ac92f6e97eaa43c4ad6cb8f7c65ac43f
- Sofas and armchairs ▸ Chesterfield sofa — author: leaguestudio — https://sketchfab.com/3d-models/66ba4225efaa4de59d9a9b7086363199
- Sofas and armchairs ▸ Blue fabric sofa — author: Filipe.Soares — https://sketchfab.com/3d-models/db5d6bbf7f34482ca1be89456fcc4070
- Sofas and armchairs ▸ Leather armchair and sofa — author: knik211 — https://sketchfab.com/3d-models/2e62bad1b0f94bdaa84bb09dd26157b5
- Sofas and armchairs ▸ Lounge armchair — author: knik211 — https://sketchfab.com/3d-models/e9d9d87c32f144e2873765e66814f727
- Sofas and armchairs ▸ Leather armchair — author: rickmaolly — https://sketchfab.com/3d-models/c0755830a1d54d27b86a80c335ccc9c1
- Sofas and armchairs ▸ Antique white armchair — author: klava88 — https://sketchfab.com/3d-models/148a621c978e4c2fb9ecb6c41b852c1d
- Sofas and armchairs ▸ Blue velvet armchair — author: undereality — https://sketchfab.com/3d-models/31570071aa0c4901bc7a1841f1e51844
- Sofas and armchairs ▸ Corner sectional sofa — author: spookyghostboo — https://sketchfab.com/3d-models/1680cc4638ba4902ada718b8b03f6a4b
- Sofas and armchairs ▸ Black leather sofa set — author: YouSaveTime — https://sketchfab.com/3d-models/c2ac7a44144e4b80ab51f21b59c827f8
- Sofas and armchairs ▸ Floral armchair — author: thesidekick — https://sketchfab.com/3d-models/dfea2ba02820403784d99f7d30faeb2a
- Chairs and stools ▸ Dining chair — author: Heliona — https://sketchfab.com/3d-models/3503f197fe8f4e2cb64d10bf44134930
- Chairs and stools ▸ Antique dining chairs — author: soidev — https://sketchfab.com/3d-models/05e815d0f2f64647b646e9b71f8ec9ed
- Chairs and stools ▸ Office chair — author: inven2000 — https://sketchfab.com/3d-models/af2f07d06f6349158c1d24d87f5ceb95
- Chairs and stools ▸ Modern office chair — author: thethieme — https://sketchfab.com/3d-models/675f34f7304e4d92812a41e9750539aa
- Chairs and stools ▸ Chrome bar stool — author: Saandy — https://sketchfab.com/3d-models/aaf556f40f634719bc80a331d2799e4f
- Chairs and stools ▸ Leather bar stool — author: NosTeam — https://sketchfab.com/3d-models/b117e9bb6647471cbba974430dfd3726
- Tables and desks ▸ Glass dining table set — author: topfrank2013 — https://sketchfab.com/3d-models/c41a27d7a1b24dc484bc603e1bc2d0ef
- Tables and desks ▸ Wooden dining set — author: alihoseini13000 — https://sketchfab.com/3d-models/f852064a2ddb40419f7c764b3cfb0d3e
- Tables and desks ▸ Modern dining table set — author: Spectrality_Studios — https://sketchfab.com/3d-models/9135349108174c8285433b3695977158
- Tables and desks ▸ Glass coffee table — author: 3dmaedchen — https://sketchfab.com/3d-models/8f8a3dbd45534152b5771c36cc4742d9
- Tables and desks ▸ Marble coffee table — author: dylanheyes — https://sketchfab.com/3d-models/4bb33512e4964951b3caaa929d08594e
- Tables and desks ▸ Antique round table — author: RimasBe — https://sketchfab.com/3d-models/031dba0a7ef44158b7c3a1186438db64
- Tables and desks ▸ Pedestal side table — author: eucocker — https://sketchfab.com/3d-models/40c5398a67394fe79fc7c74b2ea2bc6c
- Tables and desks ▸ Round side table — author: Alex_V_13 — https://sketchfab.com/3d-models/a39f076101fa4738b01a36e27fa911aa
- Tables and desks ▸ White trestle desk — author: Archivz — https://sketchfab.com/3d-models/c3ac11f22b6542c7a9205d93f38cf683
- Bedroom ▸ Modern bed — author: rickmaolly — https://sketchfab.com/3d-models/b8c16d4b69f64335b46379b119b102b4
- Bedroom ▸ Carved wooden bed — author: Maxmalow — https://sketchfab.com/3d-models/8e77fe0f95e84ca6943e8636bc042570
- Bedroom ▸ Upholstered bed — author: bertosalotti — https://sketchfab.com/3d-models/97e361e8beda4112ac5b1b5bcd388cdf
- Bedroom ▸ Bed with storage — author: bertosalotti — https://sketchfab.com/3d-models/cbe6e0dcc10a414a84acc5cc08171b87
- Bedroom ▸ White wardrobe — author: Mraz3D — https://sketchfab.com/3d-models/47270ac8a40c4af8bb55d076b159122a
- Bedroom ▸ Antique dresser — author: DarrenMcnerney3D — https://sketchfab.com/3d-models/0a46621504c24197b5653608f474f73b
- Bedroom ▸ Wooden dresser — author: Davide.Specchi — https://sketchfab.com/3d-models/040e447fff7f40a7bf08e2506943b342
- Bedroom ▸ Minimalist modern bedroom — author: dylanheyes — https://sketchfab.com/3d-models/4f3db3cb57bd4bce886f7b9a13273a2f
- Storage and shelves ▸ Large bookcase — author: idmental.id — https://sketchfab.com/3d-models/8df6adc634bd4004894a5e70565dc52a
- Storage and shelves ▸ Bookshelf with books — author: n-malmberg — https://sketchfab.com/3d-models/53ba449f3b584d1bbf6724c28e17b3e9
- Storage and shelves ▸ Open bookshelf — author: Heliona — https://sketchfab.com/3d-models/998f0924e8e249719a33ce0fe9976267
- Storage and shelves ▸ Mid-century sideboard — author: calebkung — https://sketchfab.com/3d-models/3028ba44d1f245b886c12eadc934f722
- Storage and shelves ▸ Chest of drawers — author: inven2000 — https://sketchfab.com/3d-models/989876ca437a4effb8911fa52c0adb6a
- Storage and shelves ▸ White dining cabinet — author: D.art — https://sketchfab.com/3d-models/c8717576f2244716b3abf321065f2b9a

### Vehicles (Simpler library ▸ Vehicles: Cars, Trucks and vans, Farm and construction, Aircraft, Boats, Motorcycles and bikes)
- License: Creative Commons Attribution 4.0 (CC BY 4.0) — https://creativecommons.org/licenses/by/4.0/ — they may be used, changed and redistributed, also commercially, crediting the author. They are not under the Simpler Content License.
- Changes: converted to the Simpler library format and given generic names. Some models depict real vehicles: the makers' trademarks and names belong to their owners and Simpler is not affiliated with them.
- Whoever redistributes these models must keep this list.
- Cars ▸ Modern sedan — author: mmcworks — https://sketchfab.com/3d-models/58c33766470d46e7b2aed542650494e5
- Cars ▸ American 70s sedan — author: barbo-autos — https://sketchfab.com/3d-models/78f76d386a4341b0b71745bdc50fd5ab
- Cars ▸ Police car — author: jeandiz — https://sketchfab.com/3d-models/9166b13b6ae341f4bfc093edb71d74f4
- Cars ▸ Yellow taxi — author: haoliu95 — https://sketchfab.com/3d-models/2429a825ff1646568e8e6e1453f9c501
- Trucks and vans ▸ Delivery van — author: evan.hiltz — https://sketchfab.com/3d-models/0b2f1ad95a79419f9a092420024d329c
- Trucks and vans ▸ Vintage pickup truck — author: creosine — https://sketchfab.com/3d-models/d52c6ed3b0ee4d9eb562f875b3c448a4
- Trucks and vans ▸ Modern European truck — author: DevPoly3D — https://sketchfab.com/3d-models/34ce748d9a4b4de7b035cfe5cb97f5d1
- Trucks and vans ▸ American semi truck — author: 3DE_Study — https://sketchfab.com/3d-models/3e8c5275aeab487fa37d227ce0bd1a9a
- Farm and construction ▸ Vintage tractor — author: thesidekick — https://sketchfab.com/3d-models/85720bad20b341ec8508ddbc84f11795
- Farm and construction ▸ Modern tractor — author: heynic — https://sketchfab.com/3d-models/56d7c8e7e2cb4d15a3d80cc42c697c53
- Farm and construction ▸ Classic tractor — author: le0tard — https://sketchfab.com/3d-models/278fc1e0516c401eba358d3aa2e55635
- Farm and construction ▸ Orange excavator — author: thesidekick — https://sketchfab.com/3d-models/3dde2c846cc54a4d9fabcc821c9b9caa
- Farm and construction ▸ Yellow excavator — author: thesidekick — https://sketchfab.com/3d-models/a805e66f565a412682ac8ce45ab9ac3e
- Farm and construction ▸ Orange forklift — author: mohammad6511 — https://sketchfab.com/3d-models/73d21c990e634589b0c130777751be28
- Aircraft ▸ Airliner — author: helijah — https://sketchfab.com/3d-models/28e201042a8441f1bd4403578eda1231
- Aircraft ▸ Twin-prop airplane — author: helijah — https://sketchfab.com/3d-models/8d66cde0c190433e9444a771e6115208
- Aircraft ▸ Helicopter — author: irs1182 — https://sketchfab.com/3d-models/91366449ce6842f784748a914e29d641
- Boats ▸ Old fishing boat — author: aurelien.d — https://sketchfab.com/3d-models/2f894eb760ca49eca14c38c2d49058a1
- Boats ▸ Antique motorboat — author: trivial.cat — https://sketchfab.com/3d-models/21bcd49240a54f2b879dd3f91de4fca3
- Boats ▸ Large yacht — author: sergeif — https://sketchfab.com/3d-models/0dd451f295d049cea20c17d3ffa87ee3
- Boats ▸ Small yacht — author: miguelangelo2k — https://sketchfab.com/3d-models/09a9fc4a0061464fba1bc3ba76848869
- Motorcycles and bikes ▸ Classic motorcycle — author: DeclanLea14 — https://sketchfab.com/3d-models/f246ff1a68d3459892f9420b744a58b6
- Motorcycles and bikes ▸ Vintage bicycle — author: vlad.neko — https://sketchfab.com/3d-models/1795f6e907634afda88fdaf45f67b279
- Motorcycles and bikes ▸ Moped — author: Tomasoo — https://sketchfab.com/3d-models/fe75689a108744b7acf5003d677d4c8e
- Motorcycles and bikes ▸ Retro scooter — author: annaandrei — https://sketchfab.com/3d-models/d2841db11a87440b990a595c3a3f46d1
- Motorcycles and bikes ▸ Electric scooter — author: niilo.poutanen — https://sketchfab.com/3d-models/9479a6d3f1474971afde26b33fe96c55

### Street furniture (Simpler library ▸ Street furniture: Benches and bins, Lighting, Signs and barriers, Bus stops and kiosks, Urban details)
- License: Creative Commons Attribution 4.0 (CC BY 4.0) — https://creativecommons.org/licenses/by/4.0/ — they may be used, changed and redistributed, also commercially, crediting the author. They are not under the Simpler Content License.
- Changes: converted to the Simpler library format and renamed.
- Whoever redistributes these models must keep this list.
- Benches and bins ▸ Cast iron park bench — author: dutrabr98 — https://sketchfab.com/3d-models/84426d6537ac4cdc837d602ccabe7036
- Benches and bins ▸ Wooden street bench — author: donnichols — https://sketchfab.com/3d-models/1ddafec2fda5430697aaf403b3deba96
- Benches and bins ▸ Granite bench — author: sinnervoncrawsz — https://sketchfab.com/3d-models/424c3679dcdd44d380da36a82f5dc382
- Benches and bins ▸ Concrete bench with wood seat — author: sinnervoncrawsz — https://sketchfab.com/3d-models/2eec0b2d47f94db38ea31e8c3d2aab07
- Benches and bins ▸ Steel and wood litter bin — author: luca3d — https://sketchfab.com/3d-models/3057e7f5b6c441fcb67c44e68d77dd38
- Benches and bins ▸ Wheelie bin — author: dk_artist — https://sketchfab.com/3d-models/9044ac8d545747e3959278fbe36fce8b
- Lighting ▸ Victorian street lamp — author: Discovered — https://sketchfab.com/3d-models/b7cebcfb4b1c4d4a97e22072800704ca
- Lighting ▸ Classic street lamp — author: bez_glaza — https://sketchfab.com/3d-models/6881aa1e84b047d79860fa9297e05e22
- Lighting ▸ Modern street light — author: sebastianramirez3d — https://sketchfab.com/3d-models/6cfedb57645b42b4a11d6c06411014b6
- Lighting ▸ Double globe lamp post — author: dasmodal — https://sketchfab.com/3d-models/56f6dcb3865144cd84e049ca6a736fae
- Lighting ▸ Park lamp post — author: sousinho — https://sketchfab.com/3d-models/ff5e3bc99dd146d986cb662813ec988e
- Signs and barriers ▸ Barrier gate — author: sousinho — https://sketchfab.com/3d-models/85b489ac36344ca9af98a78ecffa186f
- Signs and barriers ▸ Concrete barrier with graffiti — author: widthRider — https://sketchfab.com/3d-models/a09622c043724a1b92e7920b22edb6bf
- Signs and barriers ▸ Jersey barrier — author: emran.bayati — https://sketchfab.com/3d-models/b52246c9611a42a99a03b425535a0237
- Signs and barriers ▸ Roadwork cones and signs — author: notanotherapocalypticco — https://sketchfab.com/3d-models/e03b1d2dfdc0416bb8324d15573ea60c
- Bus stops and kiosks ▸ Bus shelter — author: pukkafilms — https://sketchfab.com/3d-models/32cc4c5f6aa147acabdb173e2d2373fa
- Bus stops and kiosks ▸ Small bus shelter — author: Mentailst — https://sketchfab.com/3d-models/f0e7ff79b95d461bb69f5e927b5db062
- Bus stops and kiosks ▸ Phone booth — author: tribhuvantechnoart — https://sketchfab.com/3d-models/d86b8632da384514965b9d920815334e
- Urban details ▸ Fire hydrant — author: jvouillon — https://sketchfab.com/3d-models/7f9164e6018c4ec7a3585bbf6e6d70df
- Urban details ▸ Orange bollard — author: dk_artist — https://sketchfab.com/3d-models/1ccd0c761fc744a3a62e168044a9d2eb
- Urban details ▸ Bike rack — author: Sam54123 — https://sketchfab.com/3d-models/bb71ca627c5c44aba68c610fbfa24cd2
- Urban details ▸ Tree grate — author: LadyLionStudios — https://sketchfab.com/3d-models/49e4e7452a5d4ced92053bcb4facbf31
- Urban details ▸ Parking meter — author: Raffey — https://sketchfab.com/3d-models/cfaf0f457ca244e59c746ebdd6f3ad6c

### Garden, terrace and office (Simpler library ▸ Garden and terrace, Office)
- License: Creative Commons Attribution 4.0 (CC BY 4.0) — https://creativecommons.org/licenses/by/4.0/ — they may be used, changed and redistributed, also commercially, crediting the author. They are not under the Simpler Content License.
- Changes: converted to the Simpler library format and renamed.
- Whoever redistributes these models must keep this list.
- Garden and terrace ▸ Patio set with umbrella — author: zhixson — https://sketchfab.com/3d-models/37c3f6ee451f495ba183427a38a804b4
- Garden and terrace ▸ Modern outdoor lounge set — author: ulugbekdizayn — https://sketchfab.com/3d-models/010bd90929894f32a7caa781c9f8f6a8
- Garden and terrace ▸ White patio umbrella — author: Ngo.Phuoc.Truong — https://sketchfab.com/3d-models/d6c9705a4f8e421ea473196ab9910088
- Garden and terrace ▸ Wooden porch swing — author: Maho_Itz — https://sketchfab.com/3d-models/c88d76ad794b468580b618957a500bd8
- Garden and terrace ▸ Teak lounge set — author: que_3d — https://sketchfab.com/3d-models/6a6c0f882e0e444c9d95dee1b0cadda1
- Garden and terrace ▸ Striped deck chair — author: MaX3Dd — https://sketchfab.com/3d-models/38de6171cbeb41c5bdc49c07df76ede9
- Garden and terrace ▸ Double sun lounger with canopy — author: kirill8666kirill — https://sketchfab.com/3d-models/1eda19e39d1c4580acf56bd981bab8e5
- Garden and terrace ▸ Outdoor dining set with umbrella — author: jennybria — https://sketchfab.com/3d-models/6b0a3a894a664e3d88520ccd905cfd40
- Garden and terrace ▸ Modern outdoor dining table — author: pukkafilms — https://sketchfab.com/3d-models/4043690aacb34d41b9ace951ad623f45
- Garden and terrace ▸ Folding bistro set — author: mohamedhussien — https://sketchfab.com/3d-models/3d7da670439449b9ab14c95fcc6f1918
- Garden and terrace ▸ Wooden outdoor coffee table — author: Gian.Luca — https://sketchfab.com/3d-models/04346631ca1e4c66b93586ada9756110
- Garden and terrace ▸ Outdoor sofa — author: simone_rizzi — https://sketchfab.com/3d-models/f761658fafcc42a78fd42912ef9f57e9
- Garden and terrace ▸ Hanging egg chair — author: klessgyzen — https://sketchfab.com/3d-models/ed88609057db40bf94a5b79ff6485410
- Garden and terrace ▸ Wire lounge chair — author: simone_rizzi — https://sketchfab.com/3d-models/8d50f071d9054909826b23d6bc2e3bd6
- Garden and terrace ▸ Gas barbecue — author: TemurG — https://sketchfab.com/3d-models/d2b1e612f17141f3ae8921167ca91efb
- Garden and terrace ▸ Charcoal barbecue — author: patrakeevasveta — https://sketchfab.com/3d-models/59563705c8a34eefafa177d8d22f35c5
- Garden and terrace ▸ Wooden pergola — author: michalbroz — https://sketchfab.com/3d-models/b728a581a70547418e077d223d2a7828
- Garden and terrace ▸ Pool ladder — author: plaggy — https://sketchfab.com/3d-models/43cbe4e6e68140e1ad202cf8a3e53650
- Garden and terrace ▸ Plastic garden chair — author: kuuttisiitonen — https://sketchfab.com/3d-models/68089dce5fa1461981d690f1cfd657fa
- Office ▸ Ultrawide monitor — author: dylanheyes — https://sketchfab.com/3d-models/f84d24b6df3648d884fd9be9c8007dd4
- Office ▸ Laptop — author: Aullwen — https://sketchfab.com/3d-models/7d870e900889481395b4a575b9fa8c3e
- Office ▸ Keyboard and mouse — author: gorzi90 — https://sketchfab.com/3d-models/c63ee81b71ff45b68a778101b4df3d46
- Office ▸ Office printer — author: nokillnando — https://sketchfab.com/3d-models/d55f6fca7c3d45c883bbff770672970d
- Office ▸ Desk lamp — author: BlueHour — https://sketchfab.com/3d-models/7377ec591df04445a1aae370017aaa13
- Office ▸ Banker's desk lamp — author: Noahouou — https://sketchfab.com/3d-models/b8e13a49528e4231a0512bb5f18f07e5
- Office ▸ Office phone — author: maxdragon — https://sketchfab.com/3d-models/4176a01b6d0b4d13ad165c0df278a6b5
- Office ▸ Whiteboard — author: arlinetjandra — https://sketchfab.com/3d-models/858a2d94034f48ebbbbbd1f07494cea0
- Office ▸ Mesh office chair — author: j.a.m — https://sketchfab.com/3d-models/41973aa1808d4a13b84c24497fc77c63
- Office ▸ Antique wooden desk — author: mkky — https://sketchfab.com/3d-models/536ee7c5cfb94775ae3eff608bd9fecf

### Nature (Simpler library ▸ Nature: Rocks, Ground debris, Logs and stumps, Beach)

- License: Creative Commons Attribution 4.0 (CC BY 4.0) — https://creativecommons.org/licenses/by/4.0/ — they may be used, changed and redistributed, also commercially, crediting the author. They are not under the Simpler Content License.

- Rocks ▸ Grey boulder — author: siesta — https://sketchfab.com/3d-models/b66d5b63deb447299ca3effa904bc789
- Rocks ▸ Speckled rock — author: norgeotloic — https://sketchfab.com/3d-models/462ba9c87ce1445191899a6b74f4203c
- Rocks ▸ Ochre rock — author: norgeotloic — https://sketchfab.com/3d-models/8ffb23ed14824fc29f53dde52398e22b
- Rocks ▸ White river stone — author: norgeotloic — https://sketchfab.com/3d-models/6195afc03d5f4c539273aa24873ef808
- Rocks ▸ Mossy rock pile — author: thesidekick — https://sketchfab.com/3d-models/b7461a9388fc4a6f96726d54df7e641d
- Rocks ▸ Large grey rock — author: 3dhdscan — https://sketchfab.com/3d-models/70b586d54a1e46ab9398f25369a39df3
- Ground debris ▸ Large pile of leaves — author: matousekfoto — https://sketchfab.com/3d-models/48807f86fd03406aa6b813ca026b0ad1
- Ground debris ▸ Scattered leaves — author: matousekfoto — https://sketchfab.com/3d-models/9b7df4b198854ccb885dd7796011796a
- Ground debris ▸ Pine cone — author: nikska — https://sketchfab.com/3d-models/55372cc6491d438db509bd17b016c75c
- Ground debris ▸ Pine cone with scales open — author: JonasSchramme — https://sketchfab.com/3d-models/025f0626a5be48be8e3ec04298d4db39
- Ground debris ▸ Fallen pine branch 1 — author: perz_scans — https://sketchfab.com/3d-models/f5ad948275cd4d13ba3ce2040b72ed47
- Ground debris ▸ Fallen pine branch 2 — author: perz_scans — https://sketchfab.com/3d-models/eca72dd7e85941eb8ecb9907df8aa560
- Ground debris ▸ Dead wood — author: plaggy — https://sketchfab.com/3d-models/898e076697144cffbbf17011bf2e3ac2
- Logs and stumps ▸ Mossy log — author: julianmalik — https://sketchfab.com/3d-models/c65a00ca4a174653beb4c59cb42b9143
- Logs and stumps ▸ Large log — author: julianmalik — https://sketchfab.com/3d-models/5a3b7ba7b639427ea970ccca90553aab
- Logs and stumps ▸ Pile of logs — author: MrUnityCreations — https://sketchfab.com/3d-models/57ebf2b09f7745e2a65da9441e989437
- Logs and stumps ▸ Woodpile — author: apariciosilva3D — https://sketchfab.com/3d-models/fcd5d5993be64ca38ef8ae2926574874
- Logs and stumps ▸ Poplar stump — author: matousekfoto — https://sketchfab.com/3d-models/604a5c25e3b84fa0ae520460112c9f92
- Logs and stumps ▸ Mossy stump — author: nedo — https://sketchfab.com/3d-models/f91647d2969049329a605095febd1c96
- Logs and stumps ▸ Dead oak stump — author: chrisg4919 — https://sketchfab.com/3d-models/c6b6469facad4fc3b77d866bfc2bd913
- Beach ▸ Scallop shell — author: kevinscofield — https://sketchfab.com/3d-models/f61affe06e6b48cb8ba40f60139fa0d1
- Beach ▸ Cockle shell — author: vlands3d — https://sketchfab.com/3d-models/f7c760e4f9e24abea2065964721b2e76
- Beach ▸ Spiky seashell — author: yakaras — https://sketchfab.com/3d-models/b91a711b424c47779c3f39dc1d1b0564
- Beach ▸ Conch shell — author: panoluma — https://sketchfab.com/3d-models/e4d2903fd8c643669c2d3b3ab081e5e7
- Beach ▸ Pine driftwood — author: crufro — https://sketchfab.com/3d-models/95d1087e513e4fb992a27b7b8a05ca9e
- Beach ▸ Driftwood sculpture — author: dbarnum11 — https://sketchfab.com/3d-models/f30401734e6040c0aa5efa0735ee6bc9

### Trash (Simpler library ▸ Trash)

- License: Creative Commons Attribution 4.0 (CC BY 4.0) — https://creativecommons.org/licenses/by/4.0/ — they may be used, changed and redistributed, also commercially, crediting the author. They are not under the Simpler Content License. Changes: scaled to real size, sets split into pieces, converted to the Simpler format.

- Bottle 1 … Bottle 7 — author: viraj chavan (virajsc) — https://sketchfab.com/3d-models/0262aab0829a47d48cae63c21dd6f9bc
- Can sqaure, Can crushed, Can open — author: Sunbox Games (sunboxgames) — https://sketchfab.com/3d-models/5f4c354cf4474c58bad147b346399a5f
- Crumpled papers — author: Sunbox Games (sunboxgames) — https://sketchfab.com/3d-models/7f8b8e5eeb74428f9f326a398baccb5d
- Cigarette butts — author: Sunbox Games (sunboxgames) — https://sketchfab.com/3d-models/52ecf4556be14ffc9226b48eac330feb
- Crumpled egg carton — author: Sunbox Games (sunboxgames) — https://sketchfab.com/3d-models/dad429594e5a4019b9f3cee4e08ad47d
- Burger box — author: -Arthur- (.arthur) — https://sketchfab.com/3d-models/1e051f09b2e24692b683531024cee047
- Crushed can scan — author: Diego (drkolo) — https://sketchfab.com/3d-models/0cd1011264b3437bb5e71cdcca6db243
- Bottle cap — author: Jonas (PactorDK) — https://sketchfab.com/3d-models/a8cc85988d7d44a9875bf3b4f112f162
- Paper bag — author: sixonetwo (evan4129) — https://sketchfab.com/3d-models/9a62b0f87a1a4a2caacbe798f169c414
- Paper cup — author: RoboHoloclone12 — https://sketchfab.com/3d-models/1903f3873e2b44d2b71d37c2fa19f43a
- Discarded mask — author: Marc Sawyer (whitewashstudio) — https://sketchfab.com/3d-models/e778607a19f64f1ca7bd5f405252130f
- Crumpled paper — author: Darxkl05 — https://sketchfab.com/3d-models/f19ea7ce149c4b25a527abecec1da524
- Chips bag — author: ZwiebelGames — https://sketchfab.com/3d-models/cacbcc48c4c8470fb2d77cd7e9e469f4
- Pizza box — author: Scott VanArsdale (vanart) — https://sketchfab.com/3d-models/d589d532b2f64855be79403cfa0bf373

### Interiors rooms (library Materials ▸ Simpler ▸ Interiors)

- 16 rooms made with Simpler (Blender/Cycles) with the models of the Simpler library credited above (same authors and licenses) and Poly Haven textures (CC0).

### Bushes (Vegetation library ▸ Simpler ▸ Bushes)

- bush1, bush2 — made by the author with PlantFactory.

### Rooms of the Interiors type (engine/assets/interiors)

- room_test — made with Simpler (Blender/Cycles) by make_interiors.py, in the same folder.

### Simpler decals (Decals library ▸ Simpler)

- Graffiti, Cracks, Footprints, Tyre tracks, Rust and leaks, Water stains ▸ Rising damp and Ceiling water stain: made by Simpler (public domain, CC0). The graffiti use the typefaces Sedgwick Ave Display and Knewave (SIL Open Font License 1.1) and Permanent Marker (Apache 2.0): pictures made with a typeface are free; the typefaces are not distributed.
- Dirt and grime ▸ Grimy wall patch, Dusty patch, Streaky grime, Soft smudge; Water stains ▸ Heavy water stains, Water run-off stains, Dripping water marks, Weathered water streaks — from Decal 01, 05, 06, 19, 09, 10, 11, 12 by ShareTextures (CC0) — https://www.sharetextures.com/textures/surfaceimperfection
- Dirt and grime ▸ Wall base dirt — from Decals 0001 by TextureCan (CC0) — https://www.texturecan.com/details/333/

## User content

The models, textures and materials you import (for example purchased collections such as Evermotion's Archmodels, or models downloaded from other sites) stay under the license you got them with: Simpler does not change it and does not distribute them.

## Names and trademarks mentioned

Blender and Cycles (Blender Foundation), Poly Haven, ambientCG, OpenAI and GPT Image, Krea, GitHub, Sketchfab, Microsoft, Windows, WebView2 and .NET, Evermotion and Archmodels, ShareTextures and TextureCan are trademarks or names of their owners. They are mentioned only to say where content comes from; Simpler is not affiliated with them.

## Notes for distribution

- All of Simpler's code (application and engine) is distributed under the GNU GPL version 3 or later: the distribution package includes the license text (LICENSE file) and the complete sources are published with every version.
- DeepBump (GPL v3): the distribution package must include its sources and license (already in tools/deepbump).
