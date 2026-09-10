import AppKit
import SwiftUI

struct ContentView: View {
    enum Page { case search, downloads }
    @State private var page: Page? = .search
    @Environment(Downloads.self) private var downloads

    var body: some View {
        NavigationSplitView {
            List(selection: $page) {
                Label("Cerca", systemImage: "magnifyingglass").tag(Page.search)
                Label("Download", systemImage: "arrow.down.circle").tag(Page.downloads).badge(downloads.activeCount)
            }
            .navigationSplitViewColumnWidth(180)
        } detail: {
            if page == .downloads { DownloadsView() } else { SearchView() }
        }
        .frame(minWidth: 900, minHeight: 600)
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
    @State private var searching = false
    @State private var error: String?
    @State private var selected: Title?

    private var kinds: [(String, LocalizedStringKey)] {
        source == .animeUnity
            ? [("", "Tutti i tipi"), ("Movie", "Film"), ("TV", "Serie TV"), ("OVA", "OVA"), ("ONA", "ONA"), ("Special", "Speciali")]
            : [("", "Film e serie TV"), ("movie", "Solo film"), ("tv", "Solo serie TV")]
    }

    var body: some View {
        ScrollView {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 150), spacing: 16)], spacing: 20) {
                ForEach(results) { title in
                    Button { selected = title } label: { Card(title: title) }.buttonStyle(.plain)
                }
            }
            .padding()
        }
        .overlay {
            if searching {
                ProgressView()
            } else if let error {
                ContentUnavailableView("Ricerca non riuscita", systemImage: "exclamationmark.triangle", description: Text(error))
            } else if source == .streamingCommunity && configuredDomain.isEmpty {
                ContentUnavailableView {
                    Label("Nessun dominio", systemImage: "globe")
                } description: {
                    Text("Imposta il dominio di StreamingCommunity nelle Impostazioni: cambia ogni poche settimane.")
                } actions: {
                    SettingsLink { Text("Apri le Impostazioni") }
                }
            } else if results.isEmpty, let searchedFor {
                ContentUnavailableView.search(text: searchedFor)
            }
        }
        .searchable(text: $query, placement: .toolbar, prompt: source == .animeUnity ? "Cerca anime…" : "Film, serie TV…")
        .toolbar {
            Picker("Sorgente", selection: $source) {
                Text("StreamingCommunity").tag(Source.streamingCommunity)
                Text("AnimeUnity").tag(Source.animeUnity)
            }
            .pickerStyle(.segmented)
            Picker("Tipo", selection: $kind) { ForEach(kinds, id: \.0) { Text($0.1).tag($0.0) } }
            if source == .animeUnity { Toggle("Solo doppiati", isOn: $dubbed) }
        }
        .onChange(of: source) { kind = "" }
        // Every keystroke restarts this, cancelling the previous run mid-sleep: that is the whole debounce.
        .task(id: [query, source.rawValue, kind, "\(dubbed)", domain]) { await search() }
        .sheet(item: $selected) { TitleSheet(title: $0) }
        .navigationTitle("Cerca")
    }

    private func search() async {
        let text = query.trimmingCharacters(in: .whitespaces)
        guard text.count >= 3 else { results = []; searchedFor = nil; error = nil; return }
        do {
            try await Task.sleep(for: .milliseconds(400))
            searching = true
            defer { searching = false }
            if source == .animeUnity {
                results = try await AnimeUnity.search(text, dubbed: dubbed, type: kind.isEmpty ? nil : kind)
            } else {
                results = try await StreamingCommunity.search(text, domain: configuredDomain)
                    .filter { kind.isEmpty || $0.kind.rawValue == kind }
            }
            searchedFor = text
            error = nil
        } catch {
            if !Task.isCancelled { self.error = error.localizedDescription; results = [] }
        }
    }
}

extension Title {
    var typeLabel: LocalizedStringKey {
        switch kind {
        case .movie: return "Film"
        case .tv: return "Serie TV"
        case .anime: return animeType == "Movie" ? "Film" : LocalizedStringKey(animeType ?? "Anime")
        }
    }
}

struct Card: View {
    let title: Title

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Poster(url: title.poster)
            Text(title.name).font(.headline).lineLimit(2)
            HStack(spacing: 6) {
                Text(title.typeLabel)
                if let score = title.score { Text("★ \(score)") }
                if let year = title.year { Text(year) }
            }
            .font(.caption)
            .foregroundStyle(.secondary)
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
                    Text(meta).foregroundStyle(.secondary)
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
        if title.kind == .tv { parts.append(seasons == 1 ? "1 stagione" : "\(seasons) stagioni") }
        if title.kind == .anime { parts.append(title.episodes == 1 ? "1 episodio" : "\(title.episodes) episodi") }
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
            Button(title.kind == .tv ? "Tutta la stagione" : "Scarica tutti") { batch = title.kind == .tv ? .season : .all }
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
        case .season: "Aggiungere alla coda i \(episodes.count) episodi della stagione \(season)?"
        case .series: "Aggiungere alla coda tutte le \(seasons) stagioni?"
        case .all: "Aggiungere alla coda tutti i \(episodes.count) episodi?"
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
                Text(job.request.label).fontWeight(.medium).lineLimit(1)
                ProgressView(value: job.status == .done ? 1 : job.fraction)
                    .tint(job.status == .failed ? .red : job.status == .done ? .green : .accentColor)
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

    private var caption: String {
        switch job.status {
        case .queued: "In coda"
        case .running, .encoding: [job.phase, job.detail].filter { !$0.isEmpty }.joined(separator: " · ")
        case .done: job.output?.lastPathComponent ?? "Completato"
        case .failed, .cancelled: job.detail
        }
    }
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
        }
        .formStyle(.grouped)
        .frame(width: 520, height: 620)
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
