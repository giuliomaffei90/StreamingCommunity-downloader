import AppKit
import Foundation

struct DownloadRequest: Codable, Hashable {
    var title: Title
    var episode: Episode?
    var season: Int?
    var audio: [String]
    var subtitles: [String]

    var label: String {
        guard let episode else { return title.name }
        if title.kind == .anime { return "\(title.name) E\(episode.number)" }
        return "\(title.name) S\(String(format: "%02d", season ?? 1))E\(padded(episode.number))"
    }
}

// MARK: Settings

/// What the user pasted, reduced to a host: an address copied from the browser works as well as a bare name.
var configuredDomain: String {
    let raw = (UserDefaults.standard.string(forKey: "domain") ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    return URL(string: raw.contains("//") ? raw : "https://" + raw)?.host() ?? raw
}

var libraryFolder: URL {
    let path = UserDefaults.standard.string(forKey: "folder") ?? ""
    return path.isEmpty ? URL.moviesDirectory.appending(path: "StreamingCommunity") : URL(filePath: path)
}

// MARK: Library layout

/// Strips what a file name cannot hold, on every platform alike: titles come from someone else's
/// database, and a "../" in one must not become a traversal.
func scrub(_ name: String) -> String {
    name.replacing(#/[\\\/:*?"<>|\x00-\x1F]/#, with: "")
        .trimmingCharacters(in: .whitespacesAndNewlines)
        .trimmingCharacters(in: CharacterSet(charactersIn: "."))
}

func sanitize(_ name: String) -> String {
    let cleaned = scrub(name)
    return cleaned.isEmpty ? "senza-nome" : String(cleaned.prefix(180))
}

/// "7" → "07", "12.5" → "12.5": the integer part padded to two digits.
func padded(_ number: String) -> String {
    let parts = number.split(separator: ".", maxSplits: 1, omittingEmptySubsequences: false)
    let whole = String(parts.first ?? "")
    return String(repeating: "0", count: max(0, 2 - whole.count)) + whole + (parts.count > 1 ? "." + parts[1] : "")
}

/// Where a download lands, without its extension: the layout the Python app's default templates write,
/// kept exactly so both apps fill one library. Films and anime drop "+" and ","; series keep them, as
/// they always have, or every series folder already on disk would stop matching.
func destination(_ request: DownloadRequest, in library: URL) -> URL {
    let title = request.title
    let year = title.year.map { $0.isEmpty ? "" : " (\($0))" } ?? ""
    let name = title.kind == .tv
        ? sanitize(title.name)
        : sanitize(title.name.replacingOccurrences(of: "+", with: " ").replacingOccurrences(of: ",", with: ""))
    let folder = library.appending(path: scrub(name + year))
    let episode = padded(request.episode?.number ?? "1")
    switch title.kind {
    case .movie:
        return folder.appending(path: scrub(name + year))
    case .tv:
        let season = String(format: "%02d", request.season ?? 1)
        return folder.appending(path: "Season \(season)").appending(path: scrub("\(name) S\(season)E\(episode)"))
    case .anime:
        return title.isAnimeMovie
            ? folder.appending(path: scrub(name))
            : folder.appending(path: "Season 01").appending(path: scrub("\(name) S01E\(episode)"))
    }
}

// MARK: Jobs

struct Job: Identifiable, Codable {
    enum Status: String, Codable {
        case queued, running, encoding, done, failed, cancelled
        var isActive: Bool { self == .queued || self == .running || self == .encoding }
    }
    var id = UUID()
    var request: DownloadRequest
    var batch: UUID?
    var status = Status.queued
    var phase = ""
    var fraction = 0.0
    var detail = ""
    var output: URL?
}

/// The download list: jobs run a few at a time, remembered across restarts. Nothing resumes — a job cut
/// short comes back as failed, and Riprova runs it again from the start.
@MainActor @Observable final class Downloads {
    /// Oldest first, the order they run in; the list shows them newest first.
    private(set) var jobs: [Job] = []
    @ObservationIgnored private var tasks: [UUID: Task<Void, Never>] = [:]
    /// Every file written, kept apart from the list: clearing the list must not lose them from File.
    private(set) var produced = UserDefaults.standard.stringArray(forKey: "produced") ?? []
    private static let ledger = URL.applicationSupportDirectory
        .appending(path: "StreamingCommunity Downloader/swift-downloads.json")

    init() {
        jobs = (try? JSONDecoder().decode([Job].self, from: Data(contentsOf: Self.ledger))) ?? []
        for index in jobs.indices where jobs[index].status.isActive {
            jobs[index].status = .failed
            jobs[index].detail = String(localized: "Interrotto dalla chiusura dell'app")
        }
    }

    var activeCount: Int { jobs.filter(\.status.isActive).count }

    func isQueued(_ request: DownloadRequest) -> Bool {
        jobs.contains { $0.request == request && $0.status.isActive }
    }

    /// Several requests at once are one batch, announced by a single notification when its last job ends.
    func enqueue(_ requests: [DownloadRequest]) {
        let library = libraryFolder
        // Two jobs writing one file leave it corrupt: whatever is already on its way there is not queued twice.
        var busy = Set(jobs.filter(\.status.isActive).map { destination($0.request, in: library) })
        let fresh = requests.filter { busy.insert(destination($0, in: library)).inserted }
        let batch = fresh.count > 1 ? UUID() : nil
        jobs += fresh.map { Job(request: $0, batch: batch) }
        changed()
    }

    func cancel(_ id: UUID) {
        tasks[id]?.cancel()
        update(id) { $0.status = .cancelled; $0.detail = String(localized: "Annullato") }
        changed()
    }

    /// Back to the queue, and out of its batch: that summary has already counted the failure.
    func retry(_ id: UUID) {
        guard tasks[id] == nil else { return }  // still unwinding from its cancellation
        update(id) { $0 = Job(id: $0.id, request: $0.request) }
        changed()
    }

    func remove(_ id: UUID) {
        jobs.removeAll { $0.id == id && !$0.status.isActive }
        changed()
    }

    func clearFinished() {
        jobs.removeAll { !$0.status.isActive }
        changed()
    }

    /// Starts queued jobs while download slots are free. An encoding job has already given its slot back.
    private func pump() {
        var running = jobs.filter { $0.status == .running }.count
        for job in jobs where job.status == .queued && running < UserDefaults.standard.integer(forKey: "maxDownloads") {
            running += 1
            update(job.id) { $0.status = .running; $0.phase = "Avvio" }
            tasks[job.id] = Task { await run(job.id, job.request) }
        }
    }

    private func run(_ id: UUID, _ request: DownloadRequest) async {
        let temp = FileManager.default.temporaryDirectory.appending(path: "StreamingCommunity/\(id.uuidString)")
        defer { try? FileManager.default.removeItem(at: temp) }
        let report: Report = { phase, fraction, detail in
            Task { @MainActor in
                self.update(id) {
                    guard $0.status == .running || $0.status == .encoding else { return }  // a late report
                    $0.phase = phase; $0.fraction = fraction; $0.detail = detail
                }
                self.badge()
            }
        }
        do {
            let (downloaded, duration) = try await download(request, domain: configuredDomain, library: libraryFolder,
                                                            temp: temp, report: report)
            try? FileManager.default.removeItem(at: temp)
            var file = downloaded
            if UserDefaults.standard.bool(forKey: "transcode") {
                update(id) { $0.status = .encoding; $0.phase = "In attesa della ricodifica"; $0.fraction = 0; $0.detail = "" }
                pump()  // bandwidth and CPU are separate budgets: the next download starts while this one encodes
                await encoderLimiter.resize(UserDefaults.standard.integer(forKey: "maxTranscodes"))
                do {
                    file = try await encoderLimiter.run {
                        try await transcode(downloaded, duration: duration) { report("Ricodifica", $0, "") }
                    }
                } catch {
                    if Task.isCancelled { throw error }  // otherwise a failed encode costs a smaller file, never the file
                }
            }
            update(id) { $0.status = .done; $0.output = file; $0.phase = ""; $0.fraction = 1; $0.detail = "" }
            produced.append(file.path)
            UserDefaults.standard.set(produced, forKey: "produced")
        } catch {
            let cancelled = Task.isCancelled
            update(id) {
                $0.status = cancelled ? .cancelled : .failed
                $0.detail = cancelled ? String(localized: "Annullato") : error.localizedDescription
            }
        }
        tasks[id] = nil
        announce(id)
        changed()
    }

    private func update(_ id: UUID, _ change: (inout Job) -> Void) {
        if let index = jobs.firstIndex(where: { $0.id == id }) { change(&jobs[index]) }
    }

    private func changed() {
        pump()
        try? FileManager.default.createDirectory(at: Self.ledger.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? JSONEncoder().encode(Array(jobs.suffix(500))).write(to: Self.ledger)
        badge()
    }

    /// One download shows its percentage; several show how many, since an average matches nothing on screen.
    private func badge() {
        let active = jobs.filter(\.status.isActive)
        NSApp?.dockTile.badgeLabel = active.isEmpty ? nil
            : active.count > 1 ? "\(active.count)" : "\(Int(active[0].fraction * 100))%"
    }

    /// A whole season is one notification when its last episode ends, not twenty-four pings.
    private func announce(_ id: UUID) {
        guard let job = jobs.first(where: { $0.id == id }) else { return }
        guard let batch = job.batch else {
            switch job.status {
            case .done: notify(String(localized: "Download completato"), String(localized: "«\(job.request.label)» è pronto in libreria."))
            case .failed: notify(String(localized: "Download fallito"), "«\(job.request.label)»: \(job.detail)")
            default: break  // cancelling is a decision, not news
            }
            return
        }
        let group = jobs.filter { $0.batch == batch }
        guard !group.contains(where: \.status.isActive) else { return }
        let done = group.filter { $0.status == .done }.count, failed = group.filter { $0.status == .failed }.count
        let name = job.request.title.name, total = group.count
        notify(failed == 0 ? String(localized: "Download completati") : String(localized: "Download completati con errori"),
               failed == 0 ? String(localized: "«\(name)»: \(done) episodi su \(total) scaricati.")
                           : String(localized: "«\(name)»: \(done) episodi su \(total) scaricati, \(failed) falliti."))
    }
}

/// Notification Center through osascript, as the Python app did. The text travels as argv, never inside
/// the script: a title like `Ocean"s Eleven` interpolated into AppleScript stops being data.
func notify(_ title: String, _ message: String) {
    guard UserDefaults.standard.bool(forKey: "notifications") else { return }
    let process = Process()
    process.executableURL = URL(filePath: "/usr/bin/osascript")
    process.arguments = ["-e", "on run argv\ndisplay notification (item 1 of argv) with title (item 2 of argv)\nend run",
                         message, title]
    try? process.run()
}
