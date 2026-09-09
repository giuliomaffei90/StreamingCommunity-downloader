// The interface is written in Italian, and Italian is the source: the templates
// and app.js say what they say, and English is a lookup away from it. Keys are
// therefore the Italian strings themselves, not invented identifiers — a string
// nobody translated falls back to what the code already said, which is a page in
// mixed languages rather than a page full of MISSING_KEY.
//
// Two shapes are handled, because the strings come in two shapes:
//
//   * Static text in index.html, translated by walking the DOM once at load.
//     Nothing in the template has to be marked up for this. The exceptions are
//     the few paragraphs that carry inline <code> or <a>, where the sentence is
//     split across several text nodes and no single node is translatable on its
//     own; those carry data-i18n-html and are replaced whole.
//   * Strings app.js builds, wrapped in t(). Anything with a number in it uses
//     a {n} placeholder rather than concatenation, so word order can differ.
//
// Switching language reloads the page (see setLanguage in app.js). Translating
// what is already rendered would mean re-rendering every list and modal from
// whatever state it is in, to save a reload that costs nothing here: the server
// is on localhost and the page holds no unsaved input outside the settings
// modal, which saves as it closes.

const I18N_EN = {
  // ── Chrome, navigation, search ───────────────────────────────────────────
  'Cerca': 'Search',
  'Download': 'Downloads',
  'Connessione...': 'Connecting…',
  'caricamento...': 'loading…',
  'Caricamento...': 'Loading…',
  'Impostazioni': 'Settings',
  'Versione del pannello': 'Panel version',
  'Cancella ricerca': 'Clear search',
  'Film, serie TV...': 'Films, TV series…',
  'Cerca anime...': 'Search anime…',
  'Film e serie TV': 'Films and TV series',
  'Solo film': 'Films only',
  'Solo serie TV': 'TV series only',
  'Solo doppiati in italiano': 'Italian dub only',
  'Tutti i tipi': 'All kinds',
  'Solo OVA': 'OVA only',
  'Solo ONA': 'ONA only',
  'Solo speciali': 'Specials only',
  'Speciale': 'Special',
  'Carica altri': 'Load more',
  'Nessun risultato.': 'No results.',
  'Nessun altro risultato': 'No further results',
  'Nessun risultato per': 'No results for',
  'Ricerca...': 'Searching…',
  'Errore ricerca': 'Search failed',

  // ── The domain banner ────────────────────────────────────────────────────
  'La sorgente ha cambiato dominio.': 'The source has changed domain.',
  'domain-banner-found':
    'Found <code id="domain-banner-host"></code>, verified by the panel.',
  'Applica': 'Apply',
  'Ignora': 'Dismiss',
  'Ignorare il dominio trovato? Il pannello resta sul dominio attuale.':
    'Dismiss the domain found? The panel stays on the current one.',
  'Dominio aggiornato: {domain}': 'Domain updated: {domain}',
  'Impossibile applicare il dominio': 'Could not apply the domain',

  // ── Downloads ────────────────────────────────────────────────────────────
  'Nessun download in corso': 'No downloads running',
  'attivi': 'active',
  'Rimuovi completati': 'Clear finished',
  'Rileggi i download dal server': 'Reload the downloads from the server',
  'In coda': 'Queued',
  'In corso': 'Running',
  'Finalizzazione': 'Finalising',
  'Audio': 'Audio',
  'Unione': 'Merging',
  'Ricodifica': 'Re-encoding',
  'Completato': 'Done',
  'Errore': 'Error',
  'Annullato': 'Cancelled',
  'Riprova': 'Retry',
  'Mostra nel Finder': 'Show in Finder',
  'Interrompere il download?': 'Stop the download?',
  'Impossibile aggiornare i download': 'Could not refresh the downloads',
  'In coda: {label}': 'Queued: {label}',
  'Errore avviando i download': 'Could not start the downloads',
  '{n} episodi in coda': '{n} episodes queued',

  // ── Title detail, episodes ───────────────────────────────────────────────
  'Episodi': 'Episodes',
  'Trailer': 'Trailer',
  'Scarica': 'Download',
  'Scarica tutti': 'Download all',
  'Tutta la serie': 'Whole series',
  'Tutta la stagione': 'Whole season',
  'Caricamento lingue...': 'Loading languages…',
  'Nessun episodio trovato.': 'No episodes found.',
  'Errore caricamento episodi': 'Could not load the episodes',
  'Risposta non valida dal server': 'Invalid response from the server',
  '1 episodio': '1 episode',
  '{n} episodi': '{n} episodes',
  '{n} stagione': '{n} season',
  '{n} stagioni': '{n} seasons',
  'Aggiungere alla coda tutti i {n} episodi della stagione {season}?':
    'Queue all {n} episodes of season {season}?',
  'Aggiungere alla coda tutte le {n} stagioni?': 'Queue all {n} seasons?',
  'Aggiungere alla coda tutti i {n} episodi?': 'Queue all {n} episodes?',

  // ── File manager ─────────────────────────────────────────────────────────
  // 'File' on its own is the naming field, and stays 'File'. The Files page
  // carries a context on its key, the way gettext disambiguates.
  'File|nav': 'Files',
  'File scaricati': 'Downloaded files',
  'Cerca file...': 'Search files…',
  'Trascina per spostare': 'Drag to move',
  'Aggiorna': 'Refresh',
  'Elimina': 'Delete',
  'Sposta': 'Move',
  'Deseleziona': 'Deselect',
  'Nessun file trovato': 'No files found',
  '{n} risultato per "{query}"': '{n} result for “{query}”',
  '{n} risultati per "{query}"': '{n} results for “{query}”',
  'Eliminato: {name}': 'Deleted: {name}',
  '{n} selezionato': '{n} selected',
  '{n} selezionati': '{n} selected',
  'Percorso cartella di destinazione (vuoto = radice):':
    'Destination folder path (empty = root):',
  'Eliminare {n} elementi selezionati?': 'Delete the {n} selected items?',
  'Eliminare la cartella "{name}" e tutto il suo contenuto?':
    'Delete the folder “{name}” and everything in it?',
  'Eliminare il file "{name}"?': 'Delete the file “{name}”?',
  'Spostato: {name}': 'Moved: {name}',
  '{n} file spostati': '{n} files moved',
  '{n} file non spostati': '{n} files not moved',
  '{n} file eliminati': '{n} files deleted',
  '{n} file non eliminati': '{n} files not deleted',
  'Errore spostamento': 'Move failed',
  'Errore eliminazione': 'Delete failed',
  'Errore rinomina': 'Rename failed',
  'Spazio non leggibile': 'Free space unreadable',
  '{free} liberi': '{free} free',
  'su {total}': 'of {total}',
  '(volume più pieno di {n})': '(fullest of {n} volumes)',

  // ── Settings: tabs and source ────────────────────────────────────────────
  'Sorgente': 'Source',
  'Nomi': 'Names',
  'Lingua': 'Language',
  'Italiano': 'Italiano',
  'Inglese': 'English',
  'Chiudi': 'Close',
  'Annulla': 'Cancel',
  'Conferma': 'Confirm',
  'Il dominio da cui il pannello cerca e scarica. Salvando viene verificato.':
    'The domain the panel searches and downloads from. Saving verifies it.',
  'Domain non configurato': 'Domain not configured',
  'Domain salvato': 'Domain saved',
  'Inserisci un domain.': 'Enter a domain.',
  'Verifica in corso...': 'Verifying…',

  // ── Settings: automatic domain recovery ──────────────────────────────────
  'Recupero automatico': 'Automatic recovery',
  'Il dominio della sorgente cambia ogni poche settimane. Il pannello può accorgersene e proporre quello nuovo, dopo averlo verificato.':
    'The source domain changes every few weeks. The panel can notice, and propose the new one once it has verified it.',
  'Controlla se la sorgente non risponde': 'Check when the source stops answering',
  'Applica il dominio trovato senza chiedere': 'Apply the domain found without asking',
  'Intervallo del controllo (minuti)': 'Check interval (minutes)',
  'Controlla ora': 'Check now',
  'Il dominio viene letto da una pagina esterna che non controlliamo. Vengono presi in considerazione solo domini di secondo livello con un nome riconosciuto, e solo se rispondono davvero come la sorgente attesa. Con l’applicazione automatica attiva nessuno rilegge quella scelta prima che abbia effetto.':
    'The domain is read off an external page we do not control. Only second-level domains with a recognised name are considered, and only if they really do answer the way the expected source does. With automatic apply on, nobody reads that choice over before it takes effect.',
  'Con l\'applicazione automatica il pannello adotta il dominio trovato senza chiedere. ':
    'With automatic apply on, the panel adopts the domain it finds without asking. ',
  'Verranno accettati solo domini verificati e con un nome riconosciuto. Continuare?':
    'Only verified domains with a recognised name will be accepted. Continue?',
  'Controllo in corso...': 'Checking…',
  'Controllo fallito.': 'The check failed.',
  'Applicato {domain}.': 'Applied {domain}.',
  'Trovato {domain}: da applicare.': 'Found {domain}: waiting to be applied.',
  'Nessun dominio adottabile. Scartati: {why}': 'No usable domain. Rejected: {why}',
  'Nessun dominio trovato.': 'No domain found.',
  'Il dominio attuale risponde.': 'The current domain answers.',
  'Intervallo tra 30 e 1440 minuti.': 'Interval between 30 and 1440 minutes.',
  'Impostazioni salvate': 'Settings saved',

  // ── Settings: naming ─────────────────────────────────────────────────────
  'Schema dei nomi': 'Naming scheme',
  'naming-placeholders':
    'What folders and files are called. Placeholders available: ' +
    '<code>{title}</code>, <code>{year}</code>, <code>{season}</code>, ' +
    '<code>{season2}</code> (zero-padded), <code>{episode}</code>, ' +
    '<code>{episode2}</code> (zero-padded). What sits inside square brackets appears ' +
    'only when the placeholders within it have a value: <code>[ ({year})]</code> ' +
    'disappears entirely when the year is unknown.',
  'naming-defaults':
    'The values suggested in the fields are the defaults, and follow the structure ' +
    'recommended by the <a href="https://jellyfin.org/docs/general/server/media/movies/" ' +
    'target="_blank" rel="noopener noreferrer">official Jellyfin documentation</a>: ' +
    '<code>Film (2020)/Film (2020).mkv</code> and ' +
    '<code>Serie (2019)/Season 01/Serie S01E01.mkv</code>. Change them only if your ' +
    'library follows a different convention: Jellyfin recognises the one above with ' +
    'no configuration.',
  'I file già scaricati non vengono rinominati. Continuano a essere riconosciuti come presenti, quindi non verranno riscaricati, ma restano con il nome vecchio finché non li rinomini dal gestore file.':
    'Files already downloaded are not renamed. They still count as present, so they will not be downloaded again, but they keep their old name until you rename them from the file manager.',
  'Film': 'Films',
  'Serie TV': 'TV series',
  'Anime': 'Anime',
  'Cartella': 'Folder',
  'Cartella serie': 'Series folder',
  'Cartella stagione': 'Season folder',
  'File episodio': 'Episode file',
  'File film': 'Movie file',
  'Ripristina predefiniti': 'Restore defaults',
  'Ripristinare lo schema dei nomi predefinito?': 'Restore the default naming scheme?',
  'Predefiniti ripristinati: premi Salva per applicarli.':
    'Defaults restored: press Save to apply them.',
  'Schema dei nomi salvato': 'Naming scheme saved',
  'Esempio: {preview}': 'Example: {preview}',

  // ── Settings: destination and performance ────────────────────────────────
  'Cartella di destinazione': 'Destination folder',
  'Dove finiscono i file scaricati. È anche la cartella che mostra il gestore file, quindi quello che scarichi lo ritrovi sempre lì.':
    'Where downloaded files land. It is also the folder the file manager shows, so what you download is always where you are looking.',
  'Lascia vuoto per usare la cartella predefinita.': 'Leave empty to use the default folder.',
  'Sfoglia': 'Browse',
  'Scegli cartella': 'Choose folder',
  'Cartella salvata': 'Folder saved',
  'Impossibile aprire il selettore': 'Could not open the folder chooser',
  'Prestazioni': 'Performance',
  'Download contemporanei': 'Concurrent downloads',
  'Suggerito: 2–4. Valori alti aumentano l\'uso di rete e RAM.':
    'Suggested: 2–4. Higher values use more network and RAM.',
  'Ricodifiche contemporanee': 'Concurrent re-encodes',
  'Contatore separato da quello dei download: un file che aspetta il suo turno per la ricodifica non occupa uno slot di download, così la rete continua a lavorare. Suggerito: 1 — x265 usa già tutti i core, farne partire tre insieme non le fa finire prima, le fa finire tutte dopo.':
    'A counter of its own, separate from the downloads: a file waiting its turn to be re-encoded does not hold a download slot, so the network keeps working. Suggested: 1 — x265 already spreads across every core, and starting three at once does not finish any of them sooner, it finishes all of them later.',
  'Segmenti in parallelo': 'Parallel segments',
  'Tetto massimo complessivo del pannello, non per singolo download. Se la fonte risponde 503 il pannello scende sotto questo valore da solo e risale quando torna a servire. Suggerito: 8–16.':
    'A ceiling for the whole panel, not for one download. If the source answers 503 the panel drops below this on its own, and climbs back when the source starts serving again. Suggested: 8–16.',
  'Ricodifica in HEVC dopo il download': 'Re-encode to HEVC after downloading',
  'x265 · qualità costante 26 · massimo 1080p, senza ingrandire. Riduce i file di circa un terzo e costa circa un terzo della durata del video in CPU — un episodio da 27 minuti impiega circa 9 minuti in più. La sorgente arriva già compressa, quindi ricodificare fa guadagnare spazio ma non qualità: tienilo spento se non ti serve il posto. Se il file ricodificato venisse più grande dell\'originale, viene tenuto l\'originale.':
    'x265 · constant quality 26 · capped at 1080p, never upscaled. Cuts files by about a third and costs about a third of the running time in CPU — a 27-minute episode takes around 9 minutes longer. The source arrives already compressed, so re-encoding wins space and never quality: leave it off unless you need the room. If the re-encoded file comes out larger than the original, the original is kept.',
  'Performance salvate': 'Performance saved',
  'Valori non validi.': 'Invalid values.',

  // ── Saving, and the errors of saving ─────────────────────────────────────
  'Salvataggio...': 'Saving…',
  'Salvato.': 'Saved.',
  'Errore salvataggio.': 'Could not save.',
  'Errore di rete': 'Network error',
  'Errore di rete.': 'Network error.',

  // ── Details the server sends back, shown verbatim in a toast ─────────────
  'Nessun dominio configurato': 'No domain configured',
  'Nessun dominio proposto': 'No domain proposed',
  'Il dominio proposto è cambiato: ricarica la pagina':
    'The proposed domain has changed: reload the page',
  'Cartella di destinazione non esiste': 'The destination folder does not exist',
  'Nessun file selezionato': 'No file selected',
  'Percorso non valido': 'Invalid path',
  'Percorso fuori dalla cartella dei download': 'Path outside the download folder',
  'Il file non esiste più': 'The file no longer exists',
  'Impossibile leggere gli episodi dalla fonte': 'Could not read the episodes from the source',
  'Nessun episodio disponibile sulla fonte': 'No episodes available on the source',
};

// Set on <html> by the template, from the stored setting.
const LANG = document.documentElement.lang === 'en' ? 'en' : 'it';

// Italian in, the chosen language out. `vars` fills {placeholders}, which is why
// counted strings are written '{n} episodi' rather than glued together: English
// does not always put the number in the same place.
function t(text, vars) {
  // Everything after '|' is context for the translator, not text: it tells two
  // identical Italian words apart, and falls away when there is no translation.
  let out = (LANG === 'en' && I18N_EN[text]) || text.split('|')[0];
  if (vars) {
    for (const [key, value] of Object.entries(vars)) {
      out = out.split('{' + key + '}').join(value);
    }
  }
  return out;
}

// Walk the static page once and swap what is translatable. Text nodes are
// matched on their trimmed value and rewritten in place, so the surrounding
// whitespace — which is what keeps the HTML readable — survives.
// A sentence wrapped across several lines of template is one string with
// newlines and indentation inside it. The dictionary holds it as it reads, so
// the lookup collapses the whitespace the HTML added.
function key(text) {
  return text.trim().replace(/\s+/g, ' ');
}

function translateDom(root) {
  if (LANG === 'it') return;

  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const tag = node.parentNode && node.parentNode.nodeName;
      if (tag === 'SCRIPT' || tag === 'STYLE') return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const node of nodes) {
    const raw = node.nodeValue;
    const hit = I18N_EN[key(raw)];
    // The surrounding whitespace is what keeps the template readable, so it is
    // put back around the translation rather than collapsed away with it.
    if (hit) node.nodeValue = raw.match(/^\s*/)[0] + hit + raw.match(/\s*$/)[0];
  }

  for (const el of root.querySelectorAll('[placeholder],[title],[aria-label]')) {
    for (const attr of ['placeholder', 'title', 'aria-label']) {
      const value = el.getAttribute(attr);
      if (value && I18N_EN[key(value)]) el.setAttribute(attr, I18N_EN[key(value)]);
    }
  }

  // Sentences with inline markup: no single text node in them is a sentence, so
  // the element is replaced whole.
  for (const el of root.querySelectorAll('[data-i18n-html]')) {
    const html = I18N_EN[el.dataset.i18nHtml];
    if (html) el.innerHTML = html;
  }
}

document.addEventListener('DOMContentLoaded', () => translateDom(document.body));
