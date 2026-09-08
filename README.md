# StreamingCommunity Downloader

Un'app macOS per cercare e scaricare film, serie TV e anime da StreamingCommunity e AnimeUnity.
Si apre, si scarica, si chiude: nessun browser, nessun comando da terminale, nessun server da
avviare a mano.

---

## Cosa fa

- Cerca e scarica film, serie TV e anime
- **Ritrova il dominio della fonte da solo** quando cambia: lo cerca, lo verifica e lo propone
- Trama, generi, voto, locandine e trailer sulla pagina del titolo — nessuna chiave API
- Qualità scelta automaticamente (1080p → 720p → 480p → 360p)
- Download dei segmenti HLS in parallelo, con decifratura AES-CBC
- Tracce audio multiple unite con FFmpeg, sottotitoli `.vtt` scaricati e incorporati
- Avanzamento in tempo reale, fase per fase (video → audio → unione)
- **Rilancio dei download falliti** dalla lista, senza rifare la ricerca
- Download programmati
- Gestore file integrato, con streaming video e spazio libero sul volume
- Cartelle di destinazione scegliibili dalle impostazioni, con selettore nativo
- Notifiche del Centro Notifiche a fine download — una sola per una stagione intera
- Webhook post-download, con template del corpo
- Nomi di file e cartelle configurabili

---

## Installazione

Scarica il `.app`, trascinalo in Applicazioni, aprilo.

Al primo avvio va impostato il **dominio della fonte** in **Impostazioni → Sorgente**: non è incluso
nell'app perché cambia ogni poche settimane.

Non essendo firmata con un account sviluppatore Apple, la prima apertura di un'app scaricata da
internet richiede **tasto destro → Apri**. Un `.app` che hai compilato tu si apre normalmente.

### Compilarla

Serve Python ≥ 3.11.

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
./scripts/build-release.sh
```

Lo script lancia i test, compila, verifica che nel bundle ci sia tutto e lascia l'app in
`~/Downloads`. Circa 110 MB, autonoma: si porta dietro Python e un FFmpeg statico, quindi non
richiede nulla di installato sul Mac che la esegue.

Per compilare senza installare né testare: `pyinstaller StreamingCommunity.spec --noconfirm --clean`,
che lascia il risultato in `dist/`.

L'icona sta in `icon/AppIcon.icns` ed è già compilata; si rigenera con `python icon/make_icon.py`.

### Eseguirla dai sorgenti

```bash
pip install -r requirements.txt
python desktop.py
```

`python main.py` serve invece il pannello su `http://127.0.0.1:8000` in un browser normale, senza
finestra — comodo per sviluppare, dove i devtools del browser battono una webview.

---

## Dove finiscono le cose

I file scaricati vanno dove dici tu, in **Impostazioni → Librerie**: una cartella per tipo di
contenuto, scelta col selettore nativo o incollando un percorso. Senza configurazione finiscono in
`~/Movies/StreamingCommunity`.

Le impostazioni dell'app stanno in
`~/Library/Application Support/StreamingCommunity Downloader/`.

La struttura delle cartelle segue la convenzione raccomandata dalla
[documentazione di Jellyfin](https://jellyfin.org/docs/general/server/media/movies/), che è anche
quella che Plex e Infuse riconoscono senza configurazione:

```
<libreria>/
├── Film (2020)/
│   ├── Film (2020).mkv
│   └── Film (2020).en.vtt
└── Serie (2019)/
    └── Season 01/
        ├── Serie S01E01.mkv
        └── Serie S01E02.mkv
```

L'estensione è `.mp4` con una sola traccia audio e `.mkv` quando ce n'è più di una, che è ciò che
serve per portarne diverse in un file solo.

---

## Quando la fonte si sposta

Il dominio cambia ogni poche settimane, e fino a ieri questo fermava tutto senza spiegare perché.
Ora l'app se ne accorge, legge l'indirizzo corrente da una pagina pubblica, controlla che serva
davvero la fonte, e mostra un banner che propone il cambio.

**Propone, non applica.** Quella pagina la scrive gente che non controlliamo, e il dominio decide
dove finiscono tutte le richieste. Vengono presi in considerazione solo domini di secondo livello
con un nome riconoscibile, e solo se rispondono come la fonte attesa. In
**Impostazioni → Sorgente** c'è un interruttore per applicare senza chiedere, spento salvo tua
scelta, e un pulsante "Controlla ora".

---

## Quando lo stream non si risolve

Il video passa dalla pagina embed della fonte, che sta dietro Cloudflare e a volte rifiuta. In quel
caso la pagina del titolo lo dice subito, invece di lasciarti un pulsante che sembra a posto e un
download che fallisce dieci minuti dopo.

---

## Note

Un solo processo, sempre: lo stato dei download vive in memoria. Il server è in ascolto solo su
`127.0.0.1` e non ha login davanti — è una finestra su un processo locale, non un servizio da
esporre in rete.

## Licenza

MIT
