import AppKit
import SwiftUI

struct ContentView: View {
    enum Page: Hashable { case search, downloads, files }
    @State private var page = Page.search
    @Environment(Downloads.self) private var downloads

    var body: some View {
        // The system's own sidebar of tabs, which also keeps each tab's state while another is shown:
        // a search is still there after a look at the downloads.
        TabView(selection: $page) {
            Tab("Cerca", systemImage: "magnifyingglass", value: .search) { NavigationStack { SearchView() } }
            Tab("Download", systemImage: "arrow.down.circle", value: .downloads) { NavigationStack { DownloadsView() } }
                .badge(downloads.activeCount)
            Tab("File", systemImage: "film.stack", value: .files) { NavigationStack { FilesView() } }
        }
        .tabViewStyle(.sidebarAdaptable)
        .tabViewSidebarBottomBar { SidebarFooter() }
        .frame(minWidth: 900, minHeight: 600)
    }
}

/// The source domain, green while it answers and red when it does not — the first thing to look at
/// when searches stop working, since it rotates every few weeks — the replacement when one has been
/// found, and the way into the settings, which open in their own window as the Python panel's did.
struct SidebarFooter: View {
    @AppStorage("domain") private var domain = ""
    @Environment(DomainWatch.self) private var watch

    private var color: Color {
        configuredDomain.isEmpty || watch.answers == false ? .red : watch.answers == true ? .green : .gray
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let candidate = watch.candidate {
                VStack(alignment: .leading, spacing: 6) {
                    Text("La sorgente ha cambiato dominio").font(.caption.weight(.semibold))
                    Text(verbatim: candidate)
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(.orange)
                        .lineLimit(1)
                        .minimumScaleFactor(0.6)
                    HStack {
                        Button("Applica") { Task { await watch.apply(candidate) } }
                        Button("Ignora") { watch.dismiss() }
                    }
                    .controlSize(.small)
                }
                .padding(8)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 8))
            }
            SettingsLink {
                (configuredDomain.isEmpty ? Text("Nessun dominio") : Text(verbatim: configuredDomain))
                    .font(.callout.weight(.semibold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.6)  // the sidebar is narrow, and the whole name is the point
                    .padding(.horizontal, 10)
                    .padding(.vertical, 4)
                    .foregroundStyle(color)
                    .background(color.opacity(0.18), in: Capsule())
            }
            .buttonStyle(.plain)
            .help(watch.answers == false ? Text("Il dominio non risponde: cambialo nelle Impostazioni") : Text(verbatim: ""))
            SettingsLink {
                Label("Impostazioni", systemImage: "gearshape")
                    .labelStyle(.titleAndIcon)  // a bottom bar would otherwise reduce it to the icon
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .buttonStyle(.bordered)
            .controlSize(.large)
        }
        .padding(12)
        .frame(minWidth: 190, alignment: .leading)  // the tab sidebar sizes itself to its labels, too narrow for these
        // Typing a domain restarts this on every keystroke; the wait lets only the last one ask.
        .task(id: domain) {
            guard (try? await Task.sleep(for: .milliseconds(600))) != nil else { return }
            await watch.check()
        }
    }
}

/// The coloured tag the Python panel put on every card, so a grid reads at a glance.
struct Badge: View {
    let text: LocalizedStringKey
    let color: Color

    init(_ text: LocalizedStringKey, _ color: Color) {
        self.text = text
        self.color = color
    }

    var body: some View {
        Text(text)
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .foregroundStyle(color)
            .background(color.opacity(0.18), in: Capsule())
    }
}

extension Title {
    /// The source's own classification — AnimeUnity's Movie, TV, OVA, ONA, Special, or
    /// StreamingCommunity's movie and tv — one colour each.
    var badge: Badge {
        switch animeType ?? kind.rawValue {
        case "Movie", "movie": Badge("Film", .blue)
        case "TV", "tv": Badge("TV", .green)
        case "OVA": Badge("OVA", .purple)
        case "ONA": Badge("ONA", .cyan)
        case "Special": Badge("Speciale", .orange)
        case let other: Badge(LocalizedStringKey(other), .gray)
        }
    }

    var kindBadge: Badge {
        switch kind {
        case .movie: Badge("Film", .blue)
        case .tv: Badge("TV", .green)
        case .anime: Badge("Anime", .purple)
        }
    }
}

// MARK: Search

struct SearchView: View {
    enum Source: String { case streamingCommunity, animeUnity }
    @AppStorage("domain") private var domain = ""
    @State private var query = ""
    @State private var source = Source.streamingCommunity
    @State private var kind = ""
    @State private var dubbed = false
    @State private var results: [Title] = []
    @State private var searchedFor: String?
    @State private var lastSearch: [String] = []
    @State private var searching = false
    @State private var error: String?
    @State private var shelves: [Shelf] = []
    @State private var shelvesFor = ""
    @State private var shelvesError: String?
    @State private var selected: Title?
    @State private var page = 1
    @State private var pageSize = 0
    @State private var more = false
    @State private var loadingMore = false
    @State private var moreError: String?

    private var searchKey: [String] { [query, source.rawValue, kind, "\(dubbed)", domain] }
    private var showsShelves: Bool { query.trimmingCharacters(in: .whitespaces).count < 3 }

    private var kinds: [(String, LocalizedStringKey)] {
        source == .animeUnity
            ? [("", "Tutti i tipi"), ("Movie", "Film"), ("TV", "Serie TV"), ("OVA", "OVA"), ("ONA", "ONA"), ("Special", "Speciali")]
            : [("", "Film e serie TV"), ("movie", "Solo film"), ("tv", "Solo serie TV")]
    }

    var body: some View {
        ScrollView {
            if showsShelves {
                // Nothing typed yet: what the source itself puts on its front page.
                LazyVStack(alignment: .leading, spacing: 28) {
                    ForEach(visibleShelves) { shelf in
                        VStack(alignment: .leading, spacing: 10) {
                            Text(LocalizedStringKey(shelf.id)).font(.title2.bold())  // translated where the label is known
                            ScrollView(.horizontal, showsIndicators: false) {
                                LazyHStack(alignment: .top, spacing: 16) {
                                    ForEach(shelf.titles) { title in
                                        Button { selected = title } label: { Card(title: title).frame(width: 150) }
                                            .buttonStyle(.plain)
                                    }
                                }
                            }
                        }
                    }
                }
                .padding()
            } else {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 150), spacing: 16)], spacing: 20) {
                    ForEach(results) { title in
                        Button { selected = title } label: { Card(title: title) }.buttonStyle(.plain)
                    }
                }
                .padding()
                if more {
                    VStack(spacing: 6) {
                        Button { Task { await loadMore() } } label: {
                            if loadingMore { ProgressView().controlSize(.small) } else { Text("Carica altri") }
                        }
                        .disabled(loadingMore)
                        if let moreError { Text(moreError).font(.caption).foregroundStyle(.red) }
                    }
                    .padding(.bottom, 24)
                }
            }
        }
        .overlay { overlay }
        .searchable(text: $query, placement: .toolbar, prompt: source == .animeUnity ? Text("Cerca anime…") : Text("Film, serie TV…"))
        .toolbar {
            Picker("Sorgente", selection: $source) {
                Text("StreamingCommunity").tag(Source.streamingCommunity)
                Text("AnimeUnity").tag(Source.animeUnity)
            }
            .pickerStyle(.segmented)
            Picker("Tipo", selection: $kind) { ForEach(kinds, id: \.0) { Text($0.1).tag($0.0) } }
            if source == .animeUnity { Toggle("Solo doppiati", isOn: $dubbed) }
        }
        // Each source is a search of its own: the other one starts from an empty field.
        .onChange(of: source) { kind = ""; query = ""; dubbed = false }
        // Every keystroke restarts this, cancelling the previous run mid-sleep: that is the whole debounce.
        .task(id: searchKey) { await search() }
        .task(id: source.rawValue + domain) { await loadShelves() }
        .sheet(item: $selected) { TitleSheet(title: $0) }
        .navigationTitle("Cerca")
    }

    @ViewBuilder private var overlay: some View {
        if searching {
            ProgressView()
        } else if source == .streamingCommunity && configuredDomain.isEmpty {
            ContentUnavailableView {
                Label("Nessun dominio", systemImage: "globe")
            } description: {
                Text("Imposta il dominio di StreamingCommunity nelle Impostazioni: cambia ogni poche settimane.")
            }
        } else if showsShelves, let shelvesError {
            ContentUnavailableView("Fonte non raggiungibile", systemImage: "exclamationmark.triangle",
                                   description: Text(shelvesError))
        } else if !showsShelves, let error {
            ContentUnavailableView("Ricerca non riuscita", systemImage: "exclamationmark.triangle", description: Text(error))
        } else if showsShelves && shelves.isEmpty {
            ProgressView()
        } else if showsShelves && visibleShelves.isEmpty {
            ContentUnavailableView("Niente di questo tipo in prima pagina", systemImage: "line.3.horizontal.decrease.circle",
                                   description: Text("Cerca per nome, o allarga il filtro."))
        } else if !showsShelves, results.isEmpty, let searchedFor {
            ContentUnavailableView.search(text: searchedFor)
        }
    }

    /// The front-page lists, narrowed by the same filters the search applies.
    private var visibleShelves: [Shelf] {
        shelves.map { shelf in
            Shelf(id: shelf.id, titles: shelf.titles.filter {
                (kind.isEmpty || ($0.animeType ?? $0.kind.rawValue) == kind) && (!dubbed || $0.dubbed == true)
            })
        }
        .filter { !$0.titles.isEmpty }
    }

    private func search() async {
        let key = searchKey
        guard key != lastSearch else { return }  // back on this tab: what is on screen already answers it
        let text = query.trimmingCharacters(in: .whitespaces)
        guard text.count >= 3 else { results = []; searchedFor = nil; error = nil; more = false; lastSearch = key; return }
        do {
            try await Task.sleep(for: .milliseconds(400))
            searching = true
            defer { searching = false }
            let raw = try await fetchPage(text, 1)
            results = filtered(raw)
            page = 1
            pageSize = raw.count
            more = !raw.isEmpty
            moreError = nil
            searchedFor = text
            error = nil
            lastSearch = key
        } catch {
            if !Task.isCancelled { self.error = error.localizedDescription; results = [] }
        }
    }

    private func fetchPage(_ text: String, _ page: Int) async throws -> [Title] {
        if source == .animeUnity {
            return try await AnimeUnity.search(text, dubbed: dubbed, type: kind.isEmpty ? nil : kind, page: page)
        }
        return try await StreamingCommunity.search(text, domain: configuredDomain, page: page)
    }

    /// StreamingCommunity has no kind filter of its own, so its pages are narrowed here; AnimeUnity's
    /// archive filters by itself.
    private func filtered(_ raw: [Title]) -> [Title] {
        source == .animeUnity || kind.isEmpty ? raw : raw.filter { $0.kind.rawValue == kind }
    }

    /// The next page of the same search. A page shorter than the first is the last there is.
    private func loadMore() async {
        let key = searchKey, text = query.trimmingCharacters(in: .whitespaces)
        loadingMore = true
        defer { loadingMore = false }
        do {
            let raw = try await fetchPage(text, page + 1)
            guard key == searchKey else { return }  // the search changed while this page was on its way
            page += 1
            let known = Set(results.map(\.id))
            results += filtered(raw).filter { !known.contains($0.id) }
            more = !raw.isEmpty && raw.count >= pageSize
            moreError = nil
        } catch {
            moreError = error.localizedDescription
        }
    }

    private func loadShelves() async {
        let key = source.rawValue + configuredDomain
        guard key != shelvesFor else { return }
        shelves = []
        shelvesError = nil
        do {
            shelves = try await source == .animeUnity ? AnimeUnity.home() : StreamingCommunity.home(domain: configuredDomain)
            shelvesFor = key
        } catch {
            if !Task.isCancelled { shelvesError = error.localizedDescription }
        }
    }
}

struct Card: View {
    let title: Title

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Poster(url: title.poster)
            Text(title.name).font(.headline).lineLimit(2)
            HStack(spacing: 4) {
                title.badge
                if let score = title.score { Badge("★ \(score)", .yellow) }
                if let year = title.year { Text(year).font(.caption).foregroundStyle(.secondary) }
            }
        }
        .contentShape(Rectangle())
    }
}

struct Poster: View {
    let url: URL?

    var body: some View {
        Color.secondary.opacity(0.15)
            .aspectRatio(2 / 3, contentMode: .fit)
            .overlay {
                AsyncImage(url: url) { $0.resizable().scaledToFill() } placeholder: {
                    Image(systemName: "film").font(.largeTitle).foregroundStyle(.tertiary)
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

// MARK: One title

struct TitleSheet: View {
    enum Batch { case season, series, all }
    let title: Title
    @Environment(\.dismiss) private var dismiss
    @Environment(Downloads.self) private var downloads
    @State private var details: StreamingCommunity.Details?
    @State private var offered: (audio: [String], subtitles: [String]) = ([], [])
    @State private var audio: Set<String> = []
    @State private var subtitles: Set<String> = []
    @State private var loadingTracks = true
    @State private var season = 1
    @State private var episodes: [Episode] = []
    @State private var loadingEpisodes = false
    @State private var batch: Batch?
    @State private var error: String?

    private var seasons: Int { details?.seasons ?? title.seasons }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .top, spacing: 20) {
                Poster(url: title.poster).frame(width: 150)
                VStack(alignment: .leading, spacing: 8) {
                    Text(title.name).font(.title2.bold())
                    HStack(spacing: 8) {
                        title.badge
                        Text(meta).foregroundStyle(.secondary)
                    }
                    let genres = details?.genres ?? title.genres
                    if !genres.isEmpty { Text(genres.joined(separator: " · ")).font(.callout).foregroundStyle(.secondary) }
                    if let plot = details?.plot ?? title.plot {
                        ScrollView { Text(plot).frame(maxWidth: .infinity, alignment: .leading) }.frame(maxHeight: 110)
                    }
                    if let trailer = details?.trailer { Link("Guarda il trailer", destination: trailer) }
                    if title.kind != .anime { tracks }
                }
            }
            if let error { Text(error).foregroundStyle(.red) }
            if title.kind != .movie { episodeList }
            HStack {
                Spacer()
                Button("Chiudi") { dismiss() }.keyboardShortcut(.cancelAction)
                if title.kind == .movie {
                    Button("Scarica") { downloads.enqueue([request(nil)]); dismiss() }
                        .keyboardShortcut(.defaultAction)
                }
            }
        }
        .padding(20)
        .frame(width: 720, height: title.kind == .movie ? nil : 640)
        .task { await loadDetails() }
        .task(id: season) { await loadEpisodes() }
        .confirmationDialog(batchQuestion, isPresented: Binding { batch != nil } set: { if !$0 { batch = nil } },
                            presenting: batch) { choice in
            Button("Aggiungi alla coda") { Task { await queue(choice) } }
        }
    }

    private var meta: String {
        var parts = [title.year, title.score.map { "★ \($0)" }].compactMap { $0 }
        if title.kind == .tv {
            parts.append(seasons == 1 ? String(localized: "1 stagione") : String(localized: "\(seasons) stagioni"))
        }
        if title.kind == .anime {
            parts.append(title.episodes == 1 ? String(localized: "1 episodio") : String(localized: "\(title.episodes) episodi"))
        }
        return parts.joined(separator: " · ")
    }

    @ViewBuilder private var tracks: some View {
        if loadingTracks {
            ProgressView().controlSize(.small)
        }
        if !offered.audio.isEmpty {
            HStack {
                Text("Audio:").foregroundStyle(.secondary)
                ForEach(offered.audio, id: \.self) { Toggle(languageName($0), isOn: member($0, of: $audio)) }
            }
        }
        if !offered.subtitles.isEmpty {
            HStack {
                Text("Sottotitoli:").foregroundStyle(.secondary)
                ForEach(offered.subtitles, id: \.self) { Toggle(languageName($0), isOn: member($0, of: $subtitles)) }
            }
        }
    }

    @ViewBuilder private var episodeList: some View {
        HStack {
            if title.kind == .tv {
                Picker("Stagione", selection: $season) {
                    ForEach(1...max(seasons, 1), id: \.self) { Text("Stagione \($0)").tag($0) }
                }
                .fixedSize()
            }
            Spacer()
            if title.kind == .tv && seasons > 1 { Button("Tutta la serie") { batch = .series } }
            Button(title.kind == .tv ? LocalizedStringKey("Tutta la stagione") : "Scarica tutti") { batch = title.kind == .tv ? .season : .all }
                .disabled(episodes.isEmpty)
        }
        List(episodes) { episode in
            let request = request(episode, season: season)
            HStack {
                Text(title.kind == .anime ? "E\(episode.number)" : episode.number)
                    .monospacedDigit().foregroundStyle(.secondary).frame(width: 50, alignment: .leading)
                Text(episode.name)
                Spacer()
                if downloads.isQueued(request) {
                    Image(systemName: "checkmark.circle").foregroundStyle(.green)
                } else {
                    Button("Scarica", systemImage: "arrow.down.circle") { downloads.enqueue([request]) }
                        .labelStyle(.iconOnly).buttonStyle(.borderless)
                }
            }
        }
        .overlay { if loadingEpisodes && episodes.isEmpty { ProgressView() } }
    }

    private var batchQuestion: String {
        switch batch {
        case .season: String(localized: "Aggiungere alla coda i \(episodes.count) episodi della stagione \(season)?")
        case .series: String(localized: "Aggiungere alla coda tutte le \(seasons) stagioni?")
        case .all: String(localized: "Aggiungere alla coda tutti i \(episodes.count) episodi?")
        case nil: ""
        }
    }

    private func request(_ episode: Episode?, season: Int? = nil) -> DownloadRequest {
        // Anime chooses no tracks, as in the Python panel: Italian where there is one, the default otherwise.
        title.kind == .anime
            ? DownloadRequest(title: title, episode: episode, audio: ["ita"], subtitles: ["ita", "eng"])
            : DownloadRequest(title: title, episode: episode, season: title.kind == .tv ? season : nil,
                              audio: audio.sorted(), subtitles: subtitles.sorted())
    }

    private func loadDetails() async {
        defer { loadingTracks = false }
        guard title.kind != .anime else { return }
        let domain = configuredDomain
        async let metadata = try? StreamingCommunity.details(title, domain: domain)
        // The track list can fail on a title that downloads fine; the download then takes the default audio.
        async let languages = try? languages(of: title, domain: domain)
        details = await metadata
        if let found = await languages {
            offered = found
            audio = Set(found.audio.filter { $0 == "ita" || found.audio.count == 1 })
            subtitles = Set(found.subtitles.filter { $0 == "ita" || $0 == "eng" })
        }
    }

    private func loadEpisodes() async {
        guard title.kind != .movie else { return }
        loadingEpisodes = true
        defer { loadingEpisodes = false }
        episodes = []
        do {
            episodes = try await title.kind == .anime
                ? AnimeUnity.episodes(title)
                : StreamingCommunity.episodes(title, season: season, domain: configuredDomain)
        } catch {
            if !Task.isCancelled { self.error = error.localizedDescription }
        }
    }

    private func queue(_ batch: Batch) async {
        do {
            var requests = episodes.map { request($0, season: season) }
            if batch == .series {
                requests = []
                for number in 1...max(seasons, 1) {
                    requests += try await StreamingCommunity.episodes(title, season: number, domain: configuredDomain)
                        .map { request($0, season: number) }
                }
            }
            downloads.enqueue(requests)
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }
}

private func member(_ value: String, of set: Binding<Set<String>>) -> Binding<Bool> {
    Binding { set.wrappedValue.contains(value) } set: { isOn in
        if isOn { set.wrappedValue.insert(value) } else { set.wrappedValue.remove(value) }
    }
}

// MARK: Downloads

struct DownloadsView: View {
    @Environment(Downloads.self) private var downloads

    var body: some View {
        List(downloads.jobs.reversed()) { JobRow(job: $0) }
            .overlay {
                if downloads.jobs.isEmpty {
                    ContentUnavailableView("Nessun download", systemImage: "arrow.down.circle",
                                           description: Text("Quello che scarichi compare qui."))
                }
            }
            .toolbar {
                Button("Apri la cartella", systemImage: "folder") {
                    try? FileManager.default.createDirectory(at: libraryFolder, withIntermediateDirectories: true)
                    NSWorkspace.shared.open(libraryFolder)
                }
                Button("Togli i terminati", systemImage: "checklist.checked") { downloads.clearFinished() }
            }
            .navigationTitle("Download")
    }
}

struct JobRow: View {
    let job: Job
    @Environment(Downloads.self) private var downloads

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    job.request.title.kindBadge
                    Text(job.request.label).fontWeight(.medium).lineLimit(1)
                }
                ProgressView(value: job.status == .done ? 1 : job.fraction).tint(tint)
                Text(caption).font(.caption).foregroundStyle(job.status == .failed ? .red : .secondary).lineLimit(2)
            }
            if job.status.isActive {
                Button("Interrompi", systemImage: "stop.circle") { downloads.cancel(job.id) }
            } else {
                if job.status == .failed || job.status == .cancelled {
                    Button("Riprova", systemImage: "arrow.clockwise") { downloads.retry(job.id) }
                }
                if let file = job.output {
                    Button("Mostra nel Finder", systemImage: "magnifyingglass") {
                        NSWorkspace.shared.activateFileViewerSelecting([file])
                    }
                }
                Button("Togli dalla lista", systemImage: "xmark") { downloads.remove(job.id) }
            }
        }
        .labelStyle(.iconOnly)
        .buttonStyle(.borderless)
        .padding(.vertical, 4)
    }

    /// One colour per step, as the Python panel had: downloading, audio, joining, encoding, and how it ended.
    private var tint: Color {
        switch job.status {
        case .done: .green
        case .failed: .red
        case .queued, .cancelled: .gray
        case .encoding: .orange
        case .running: job.phase.hasPrefix("Audio") ? .teal : job.phase == "Unione" ? .purple : .blue
        }
    }

    private var caption: String {
        switch job.status {
        case .queued: String(localized: "In coda")
        // The phase is kept as its Italian key, which the colours read; it is translated only here.
        case .running, .encoding:
            [NSLocalizedString(job.phase, comment: ""), job.detail].filter { !$0.isEmpty }.joined(separator: " · ")
        case .done: job.output?.lastPathComponent ?? String(localized: "Completato")
        case .failed, .cancelled: job.detail
        }
    }
}

// MARK: Files

/// What this app has downloaded — the Python version it replaced included — as it is on disk now.
/// Only those, not every video in the folder: the library is often a folder like ~/Downloads that
/// holds plenty of other things.
struct FilesView: View {
    @Environment(Downloads.self) private var downloads
    @State private var files: [URL] = []
    @State private var filter = ""
    @State private var selection = Set<URL>()

    private var groups: [(String, [URL])] {
        let shown = filter.isEmpty ? files : files.filter { $0.path.localizedCaseInsensitiveContains(filter) }
        return Dictionary(grouping: shown, by: folderLabel)
            .sorted { $0.key.localizedStandardCompare($1.key) == .orderedAscending }
            .map { ($0.key, $0.value) }
    }

    var body: some View {
        List(selection: $selection) {
            ForEach(groups, id: \.0) { group in
                Section(group.0) {
                    ForEach(group.1, id: \.self) { file in
                        HStack {
                            Image(systemName: "film").foregroundStyle(.secondary)
                            Text(file.lastPathComponent).lineLimit(1).truncationMode(.middle)
                            Spacer()
                            Text(size(of: file)).foregroundStyle(.secondary).monospacedDigit()
                        }
                    }
                }
            }
        }
        .contextMenu(forSelectionType: URL.self) { urls in
            Button("Apri") { urls.forEach { NSWorkspace.shared.open($0) } }
            Button("Mostra nel Finder") { NSWorkspace.shared.activateFileViewerSelecting(Array(urls)) }
            Divider()
            Button("Sposta nel Cestino") { trash(urls) }
        } primaryAction: { urls in
            urls.forEach { NSWorkspace.shared.open($0) }
        }
        .onDeleteCommand { trash(selection) }
        .overlay {
            if files.isEmpty {
                ContentUnavailableView("Nessun file", systemImage: "film.stack",
                                       description: Text("Quello che scarichi compare qui. Doppio clic per aprirlo."))
            }
        }
        .searchable(text: $filter, placement: .toolbar, prompt: "Filtra i file")
        .toolbar {
            Text(freeSpace).foregroundStyle(.secondary)
            Button("Apri la cartella", systemImage: "folder") { NSWorkspace.shared.open(libraryFolder) }
        }
        .task(id: downloads.produced) { reload() }
        .navigationTitle("File")
    }

    private var freeSpace: String {
        let free = (try? libraryFolder.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey]))?
            .volumeAvailableCapacityForImportantUsage
        return free.map { String(localized: "\(ByteCountFormatter.string(fromByteCount: $0, countStyle: .file)) liberi") } ?? ""
    }

    private func size(of file: URL) -> String {
        ByteCountFormatter.string(fromByteCount: Int64((try? file.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0),
                                  countStyle: .file)
    }

    private func reload() {
        try? FileManager.default.createDirectory(at: libraryFolder, withIntermediateDirectories: true)
        // The Python version's ledger, still in the same folder, is how its downloads keep showing.
        let ledger = URL.applicationSupportDirectory.appending(path: "StreamingCommunity Downloader/downloads.json")
        let python = ((try? JSONSerialization.jsonObject(with: Data(contentsOf: ledger))) as? [JSON] ?? [])
            .compactMap { string($0["output_path"]) }
        // The list's finished jobs too, for what was downloaded before `produced` existed.
        let listed = downloads.jobs.compactMap { $0.output?.path }
        files = Set(downloads.produced + listed + python).map { URL(filePath: $0) }
            .filter { FileManager.default.fileExists(atPath: $0.path) }
            .sorted { $0.path.localizedStandardCompare($1.path) == .orderedAscending }
    }

    /// The Trash, not an unlink: a slip of the Delete key is one "Rimetti al suo posto" away.
    private func trash(_ urls: Set<URL>) {
        for url in urls { try? FileManager.default.trashItem(at: url, resultingItemURL: nil) }
        selection.subtract(urls)
        reload()
    }
}

/// "The Office (2005) · Season 01" for an episode, the folder's own name for a film.
private func folderLabel(_ file: URL) -> String {
    let parent = file.deletingLastPathComponent()
    return parent.lastPathComponent.hasPrefix("Season ")
        ? "\(parent.deletingLastPathComponent().lastPathComponent) · \(parent.lastPathComponent)"
        : parent.lastPathComponent
}

// MARK: Settings

struct SettingsView: View {
    @AppStorage("domain") private var domain = ""
    @AppStorage("folder") private var folder = ""
    @AppStorage("maxDownloads") private var maxDownloads = 3
    @AppStorage("maxSegments") private var maxSegments = 16
    @AppStorage("notifications") private var notifications = true
    @AppStorage("transcode") private var transcode = false
    @AppStorage("maxTranscodes") private var maxTranscodes = 1
    @Environment(Downloads.self) private var downloads
    @State private var language = SettingsView.languageAtLaunch
    @AppStorage("domainAutoCheck") private var autoCheck = true
    @AppStorage("domainAutoApply") private var autoApply = false
    @AppStorage("domainCheckMinutes") private var checkMinutes = 360
    @Environment(DomainWatch.self) private var watch
    @State private var report: String?
    @State private var checking = false

    /// The language this run speaks, read once, for a new choice to be compared against.
    private static let languageAtLaunch =
        (UserDefaults.standard.stringArray(forKey: "AppleLanguages")?.first ?? "it").hasPrefix("en") ? "en" : "it"

    var body: some View {
        Form {
            Section {
                TextField("Dominio", text: $domain, prompt: Text("streamingcommunity.esempio"))
            } header: {
                Text("Sorgente")
            } footer: {
                Text("Cambia ogni poche settimane: incolla qui quello nuovo, anche l'indirizzo copiato dal browser.")
                    .foregroundStyle(.secondary)
            }
            Section {
                Toggle("Cerca il dominio nuovo quando quello attuale non risponde", isOn: $autoCheck)
                Toggle("Applicalo senza chiedere", isOn: $autoApply).disabled(!autoCheck)
                Stepper("Controllo ogni \(checkMinutes) minuti", value: $checkMinutes, in: 30...1440, step: 30)
                LabeledContent {
                    Button("Controlla ora") {
                        Task {
                            checking = true
                            report = describe(await watch.check(force: true))
                            checking = false
                        }
                    }
                    .disabled(checking)
                } label: {
                    if checking { ProgressView().controlSize(.small) } else { Text(report ?? "") }
                }
            } header: {
                Text("Recupero del dominio")
            } footer: {
                Text("Il dominio nuovo si legge da una pagina esterna che non controlliamo. Si considerano solo domini di secondo livello con un nome riconosciuto, che risolvono a indirizzi pubblici e rispondono davvero come la sorgente; di norma vengono solo proposti, in fondo alla barra laterale.")
                    .foregroundStyle(.secondary)
            }
            Section("Download") {
                LabeledContent("Cartella") {
                    HStack {
                        Text(folder.isEmpty ? libraryFolder.path : folder).lineLimit(1).truncationMode(.middle)
                        Button("Scegli…", action: chooseFolder)
                    }
                }
                Stepper("Download contemporanei: \(maxDownloads)", value: $maxDownloads, in: 1...32)
                Stepper("Segmenti in parallelo: \(maxSegments)", value: $maxSegments, in: 1...128)
                Toggle("Notifica a download finito", isOn: $notifications)
            }
            Section {
                Toggle("Ricodifica in HEVC dopo il download", isOn: $transcode)
                Stepper("Ricodifiche contemporanee: \(maxTranscodes)", value: $maxTranscodes, in: 1...8).disabled(!transcode)
            } header: {
                Text("Ricodifica")
            } footer: {
                Text("Preset «Plex» di HandBrake: circa un terzo di spazio in meno, per un terzo della durata in CPU.")
                    .foregroundStyle(.secondary)
            }
            Section {
                Picker("Lingua dell'interfaccia", selection: $language) {
                    Text(verbatim: "Italiano").tag("it")
                    Text(verbatim: "English").tag("en")
                }
                if language != Self.languageAtLaunch {
                    LabeledContent {
                        Button("Riavvia ora", action: relaunch).disabled(downloads.activeCount > 0)
                    } label: {
                        downloads.activeCount > 0
                            ? Text("Cambia al prossimo avvio. Con dei download in corso, riavvia quando finiscono.")
                            : Text("Cambia al prossimo avvio.")
                    }
                }
            } header: {
                Text("Lingua")
            }
        }
        .formStyle(.grouped)
        .navigationTitle("Impostazioni")
        // The app's own AppleLanguages, which is what System Settings writes for a per-app language.
        .onChange(of: language) { UserDefaults.standard.set([language], forKey: "AppleLanguages") }
    }

    private func describe(_ outcome: DomainWatch.Outcome?) -> String {
        guard let outcome else { return "" }
        if let found = outcome.candidate {
            return outcome.applied ? String(localized: "Applicato «\(found)».")
                                   : String(localized: "Trovato «\(found)»: da applicare, in fondo alla barra laterale.")
        }
        if outcome.answers { return String(localized: "Il dominio attuale risponde.") }
        if outcome.rejected.isEmpty { return String(localized: "Nessun dominio trovato.") }
        // Shown rather than swallowed: a rebranded source and an edited page look alike from here, and
        // only a person can tell them apart.
        let why = outcome.rejected.map { "\($0.host) (\($0.reason))" }.joined(separator: ", ")
        return String(localized: "Nessun dominio adottabile. Scartati: \(why)")
    }

    /// A fresh copy once this one has quit. The path travels as an argument, never inside the script.
    private func relaunch() {
        let shell = Process()
        shell.executableURL = URL(filePath: "/bin/sh")
        shell.arguments = ["-c", "sleep 1; /usr/bin/open \"$0\"", Bundle.main.bundlePath]
        try? shell.run()
        NSApp.terminate(nil)
    }

    private func chooseFolder() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.canCreateDirectories = true
        panel.directoryURL = libraryFolder
        if panel.runModal() == .OK, let url = panel.url { folder = url.path }
    }
}
