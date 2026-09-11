import CommonCrypto
import Foundation
import os

// MARK: Playlists

struct Playlist: Sendable {
    struct Variant: Sendable { let bandwidth: Int; let url: URL }
    struct Media: Sendable { let type: String; let language: String; let isDefault: Bool; let url: URL }

    var variants: [Variant] = []
    var media: [Media] = []
    var segments: [URL] = []
    var duration = 0.0
    var encrypted = false
    var iv: Data?

    init(_ text: String, base: URL) {
        var bandwidth: Int?
        for line in text.split(whereSeparator: \.isNewline).map(String.init) {
            if line.hasPrefix("#EXT-X-STREAM-INF:") {
                bandwidth = Int(attributes(line)["BANDWIDTH"] ?? "") ?? 0
            } else if line.hasPrefix("#EXT-X-MEDIA:") {
                let a = attributes(line)
                if let uri = a["URI"], let url = URL(string: uri, relativeTo: base)?.absoluteURL {
                    media.append(Media(type: a["TYPE"] ?? "", language: a["LANGUAGE"] ?? "und",
                                       isDefault: a["DEFAULT"] == "YES", url: url))
                }
            } else if line.hasPrefix("#EXT-X-KEY:") {
                let a = attributes(line)
                encrypted = a["METHOD"] == "AES-128"
                iv = a["IV"].map { hex in
                    Data(stride(from: 2, to: hex.count, by: 2).compactMap { UInt8(hex.dropFirst($0).prefix(2), radix: 16) })
                }
            } else if line.hasPrefix("#EXTINF:") {
                duration += Double(line.dropFirst(8).prefix { $0 != "," }) ?? 0
            } else if !line.hasPrefix("#"), let url = URL(string: line.trimmingCharacters(in: .whitespaces), relativeTo: base)?.absoluteURL {
                if let rate = bandwidth { variants.append(Variant(bandwidth: rate, url: url)); bandwidth = nil }
                else { segments.append(url) }
            }
        }
    }

    /// vixcloud serves some playlists only with b=1 and others only without it, and which is which changes
    /// from one day to the next — hence without first, and once more with it on a 403.
    static func load(_ url: URL, referer: String) async throws -> Playlist {
        do {
            return Playlist(String(decoding: try await fetch(url, referer: referer), as: UTF8.self), base: url)
        } catch let error as HTTPStatus where error.code == 403 && !(url.query ?? "").contains("b=1") {
            let retry = URL(string: url.absoluteString + (url.query == nil ? "?b=1" : "&b=1"))!
            return Playlist(String(decoding: try await fetch(retry, referer: referer), as: UTF8.self), base: retry)
        }
    }
}

/// `KEY=VALUE,KEY="VALUE, with commas"` as a dictionary.
func attributes(_ line: String) -> [String: String] {
    Dictionary(line.matches(of: #/([A-Z0-9-]+)=("[^"]*"|[^,]*)/#).map {
        (String($0.1), String($0.2).trimmingCharacters(in: CharacterSet(charactersIn: "\"")))
    }, uniquingKeysWith: { first, _ in first })
}

// MARK: Concurrency

/// Concurrency that finds the source's tolerance instead of assuming it: additive increase,
/// multiplicative decrease, the loop TCP uses. One instance serves every download — a ceiling per
/// download, multiplied by three downloads at once, is what produced the Python app's 503 storms.
actor Limiter {
    private var maximum: Int
    private(set) var allowance: Int
    private var inFlight = 0
    private var served = 0
    private var lastPenalty = Date.distantPast
    private var waiting: [CheckedContinuation<Void, Never>] = []

    init(_ maximum: Int) {
        self.maximum = max(1, maximum)
        allowance = self.maximum
    }

    func run<T: Sendable>(_ body: @Sendable () async throws -> T) async rethrows -> T {
        if inFlight < allowance { inFlight += 1 } else { await withCheckedContinuation { waiting.append($0) } }
        defer { inFlight -= 1; wake() }
        return try await body()
    }

    /// The source pushed back: ask for half as much. At most once per two seconds, because a burst of
    /// 503s arrives within milliseconds and describes a single moment.
    func penalise() {
        guard Date().timeIntervalSince(lastPenalty) >= 2 else { return }
        lastPenalty = Date()
        served = 0
        allowance = max(min(2, maximum), allowance / 2)
    }

    /// A segment arrived. One more slot per full allowance served, so a width is earned before it grows.
    func reward() {
        guard allowance < maximum else { return }
        served += 1
        if served >= allowance { served = 0; allowance += 1; wake() }
    }

    /// Follows the setting without forgetting what was learnt: an allowance the source cut stays cut.
    func resize(_ newMaximum: Int) {
        let untouched = allowance >= maximum
        maximum = max(1, newMaximum)
        allowance = untouched ? maximum : min(allowance, maximum)
        wake()
    }

    private func wake() {
        while inFlight < allowance, !waiting.isEmpty { inFlight += 1; waiting.removeFirst().resume() }
    }
}

let segmentLimiter = Limiter(16)
let encoderLimiter = Limiter(1)

// MARK: Segments

let segmentSession: URLSession = {
    let configuration = URLSessionConfiguration.ephemeral
    configuration.urlCache = nil                     // a film's worth of segments is not worth caching
    configuration.httpMaximumConnectionsPerHost = 64 // the Limiter is the ceiling, not this
    configuration.timeoutIntervalForRequest = 30
    return URLSession(configuration: configuration)
}()

/// One segment, retrying what is worth retrying. Any other 4xx is a verdict rather than congestion, and
/// teaches the limiter nothing. Nil once the segment is given up on.
func fetchSegment(_ url: URL, referer: String) async -> Data? {
    let request = {
        var request = URLRequest(url: url)
        request.setValue(userAgent, forHTTPHeaderField: "User-Agent")
        request.setValue(referer, forHTTPHeaderField: "Referer")
        return request
    }()
    for attempt in 0..<3 {
        // Jittered, or every worker comes back at the struggling edge in the same instant.
        var wait = min(pow(2, Double(attempt)), 8) * .random(in: 0.5...1.5)
        do {
            let (data, response) = try await segmentLimiter.run { try await segmentSession.data(for: request) }
            let http = response as? HTTPURLResponse
            if http?.statusCode == 200, !data.isEmpty { await segmentLimiter.reward(); return data }
            guard let status = http?.statusCode, [408, 425, 429, 500, 502, 503, 504].contains(status) else { return nil }
            await segmentLimiter.penalise()
            if let asked = http?.value(forHTTPHeaderField: "Retry-After").flatMap(Double.init) { wait = min(asked, 30) }
        } catch {
            if Task.isCancelled { return nil }
            await segmentLimiter.penalise()  // a refused or timed-out connection says what a 503 says
        }
        if attempt < 2 { try? await Task.sleep(for: .seconds(wait)) }
    }
    return nil
}

/// AES-128-CBC with PKCS7, whose padding check also catches a wrong key: the segment fails instead of
/// joining the film as noise.
func decrypt(_ data: Data, key: Data, iv: Data) -> Data? {
    var output = Data(count: data.count + kCCBlockSizeAES128)
    let capacity = output.count
    var written = 0
    let status = output.withUnsafeMutableBytes { out in
        data.withUnsafeBytes { input in key.withUnsafeBytes { k in iv.withUnsafeBytes { v in
            CCCrypt(CCOperation(kCCDecrypt), CCAlgorithm(kCCAlgorithmAES), CCOptions(kCCOptionPKCS7Padding),
                    k.baseAddress, key.count, v.baseAddress, input.baseAddress, data.count,
                    out.baseAddress, capacity, &written)
        } } }
    }
    return status == CCCryptorStatus(kCCSuccess) ? output.prefix(written) : nil
}

/// Every segment of `playlist` into `folder`, then joined into `file`. Fails rather than leave a gap:
/// TS joined around a missing segment plays, looks complete and is wrong, and nobody knows to redo it.
func downloadRendition(_ playlist: Playlist, key: Data, referer: String, folder: URL, into file: URL,
                       report: @escaping @Sendable (Double, String) -> Void) async throws {
    let count = playlist.segments.count
    guard count > 0 else { throw Failure("Playlist senza segmenti") }
    guard !playlist.encrypted || playlist.iv != nil else { throw Failure("Playlist cifrata senza IV") }
    try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    let width = max(1, UserDefaults.standard.integer(forKey: "maxSegments"))
    await segmentLimiter.resize(width)
    let lastArrival = OSAllocatedUnfairLock(initialState: Date())

    @Sendable func save(_ index: Int) async -> Int {  // bytes written, 0 when given up on
        guard let data = await fetchSegment(playlist.segments[index], referer: referer),
              let plain = playlist.encrypted ? decrypt(data, key: key, iv: playlist.iv!) : data,
              (try? plain.write(to: folder.appending(path: "\(index).ts"))) != nil else { return 0 }
        lastArrival.withLock { $0 = Date() }
        return plain.count
    }

    // The bar counts segments obtained, not attempts made: counting failures would also keep feeding
    // the stall check below, so a source refusing every request would never trip it.
    var failed: [Int] = [], obtained = 0, bytes = 0, streak = 0
    let started = Date()
    var reported = Date.distantPast
    func progress() {
        guard Date().timeIntervalSince(reported) >= 0.5 || obtained == count else { return }
        reported = Date()
        let elapsed = max(Date().timeIntervalSince(started), 0.001)
        let speed = ByteCountFormatter.string(fromByteCount: Int64(Double(bytes) / elapsed), countStyle: .file)
        let eta = Duration.seconds(Double(count - obtained) * elapsed / Double(max(obtained, 1)))
            .formatted(.units(allowed: [.hours, .minutes, .seconds], width: .narrow, maximumUnitCount: 2))
        report(Double(obtained) / Double(count), "\(speed)/s · \(eta)")
    }

    try await withThrowingTaskGroup(of: (Int, Int).self) { group in
        // A source that serves nothing for 30 seconds is not about to start: better an error now than an
        // hour of timeouts.
        group.addTask {
            while Date().timeIntervalSince(lastArrival.withLock { $0 }) < 30 { try await Task.sleep(for: .seconds(1)) }
            throw Failure("Nessun segmento scaricato per 30 secondi: la fonte non risponde, riprova più tardi.")
        }
        var next = 0
        while next < min(width, count) { let index = next; group.addTask { (index, await save(index)) }; next += 1 }
        while let (index, size) = try await group.next() {
            if size > 0 {
                obtained += 1; bytes += size; streak = 0; progress()
            } else {
                failed.append(index); streak += 1
                // Losing some is ordinary, and the second pass below is for them. Two hundred in a row
                // with nothing arriving between them is a source refusing, not throttling.
                if streak >= 200 { throw Failure("Download interrotto: la fonte rifiuta i segmenti. Riprova più tardi.") }
            }
            if next < count { let index = next; group.addTask { (index, await save(index)) }; next += 1 }
            else if obtained + failed.count == count { group.cancelAll(); break }
        }
    }

    // Later and one at a time, which is what a source shedding load was asking for.
    for index in failed {
        try Task.checkCancellation()
        try await Task.sleep(for: .milliseconds(500))
        let size = await save(index)
        if size > 0 { obtained += 1; bytes += size; progress() }
    }
    // The filesystem is the judge, not the bookkeeping above.
    let missing = (0..<count).filter { !FileManager.default.fileExists(atPath: folder.appending(path: "\($0).ts").path) }
    guard missing.isEmpty else {
        throw Failure("Download incompleto: \(missing.count) segmenti su \(count) non scaricati. Il file non è stato creato per non salvarlo corrotto.")
    }

    // TS is a continuous stream, so the join is plain concatenation and ffmpeg's demuxer carries the
    // timestamps across the seams. Each segment goes as soon as it is copied, to keep one copy on disk.
    FileManager.default.createFile(atPath: file.path, contents: nil)
    let output = try FileHandle(forWritingTo: file)
    defer { try? output.close() }
    for index in 0..<count {
        let segment = folder.appending(path: "\(index).ts")
        try output.write(contentsOf: try Data(contentsOf: segment))
        try? FileManager.default.removeItem(at: segment)
    }
}

// MARK: ffmpeg

/// FFMPEG_PATH, then PATH, then Homebrew's usual places: an app opened from the Finder gets a PATH
/// without /opt/homebrew/bin.
let ffmpegURL: URL? = {
    let environment = ProcessInfo.processInfo.environment
    let candidates = [environment["FFMPEG_PATH"]].compactMap { $0 }
        + (environment["PATH"] ?? "").split(separator: ":").map { "\($0)/ffmpeg" }
        + ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"]
    return candidates.first { FileManager.default.isExecutableFile(atPath: $0) }.map { URL(filePath: $0) }
}()

/// Runs ffmpeg to completion; cancelling the task terminates it. stderr goes to a file rather than to a
/// pipe nobody drains mid-run: a stream full of bad packets writes more than a pipe holds, and hangs.
func ffmpeg(_ arguments: [String], onOutputLine: (@Sendable (String) -> Void)? = nil) async throws {
    guard let executable = ffmpegURL else { throw Failure("ffmpeg non trovato: installalo con «brew install ffmpeg»") }
    let log = FileManager.default.temporaryDirectory.appending(path: "ffmpeg-\(UUID().uuidString).log")
    FileManager.default.createFile(atPath: log.path, contents: nil)
    defer { try? FileManager.default.removeItem(at: log) }

    let process = Process()
    process.executableURL = executable
    process.arguments = ["-hide_banner", "-nostdin", "-loglevel", "error", "-y"] + arguments
    process.standardError = try FileHandle(forWritingTo: log)
    let output = Pipe()
    process.standardOutput = onOutputLine == nil ? FileHandle.nullDevice : output
    let reader = onOutputLine.map { handle in
        Task.detached { for try await line in output.fileHandleForReading.bytes.lines { handle(line) } }
    }
    defer { reader?.cancel() }

    try await withTaskCancellationHandler {
        try await withCheckedThrowingContinuation { (finished: CheckedContinuation<Void, Error>) in
            process.terminationHandler = { _ in finished.resume() }
            do { try process.run() } catch { finished.resume(throwing: error) }
        }
    } onCancel: {
        if process.isRunning { process.terminate() }
    }
    try Task.checkCancellation()
    guard process.terminationStatus == 0 else {
        let tail = (try? String(contentsOf: log, encoding: .utf8)).map { String($0.suffix(300)) } ?? ""
        throw Failure("ffmpeg: \(tail.trimmingCharacters(in: .whitespacesAndNewlines))")
    }
}

/// "ita" → "Italiano" in the interface's language; vixcloud's "forced-ita" → "Italiano (forzati)".
func languageName(_ code: String, in locale: Locale = .current) -> String {
    let forced = code.hasPrefix("forced-"), base = forced ? String(code.dropFirst(7)) : code
    let name = locale.localizedString(forLanguageCode: base).map { $0.prefix(1).uppercased() + $0.dropFirst() } ?? base.uppercased()
    return forced ? String(localized: "\(name) (forzati)") : name
}

/// One ffmpeg pass: the video, each chosen audio track and the subtitles into a single file. Audio goes
/// to AAC through aresample, which evens out the gaps a stream stitched from segments tends to carry.
func mux(video: URL, audio: [(URL, String)], subtitles: [(URL, String)], into output: URL) async throws {
    let mkv = output.pathExtension == "mkv"
    var arguments = ["-fflags", "+genpts", "-i", video.path]
    for (file, _) in audio { arguments += ["-fflags", "+genpts", "-i", file.path] }
    for (file, _) in subtitles { arguments += ["-i", file.path] }
    arguments += ["-map", "0:v:0"] + (audio.isEmpty ? ["-map", "0:a?"] : audio.indices.flatMap { ["-map", "\($0 + 1):a:0"] })
    arguments += subtitles.indices.flatMap { ["-map", "\(audio.count + 1 + $0):0"] }
    arguments += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-af", "aresample=async=1000",
                  "-c:s", mkv ? "copy" : "mov_text"]
    for (index, (_, language)) in audio.enumerated() { arguments += ["-metadata:s:a:\(index)", "language=\(language)"] }
    for (index, (_, language)) in subtitles.enumerated() {
        // vixcloud writes forced subtitles as "forced-ita": a language plus a disposition, not a code.
        let forced = language.hasPrefix("forced-"), code = forced ? String(language.dropFirst(7)) : language
        // A track title is read by any player, so it is English whatever the interface speaks.
        let title = (Locale(identifier: "en").localizedString(forLanguageCode: code) ?? code.uppercased()) + (forced ? " (Forced)" : "")
        arguments += ["-metadata:s:s:\(index)", "language=\(code)", "-metadata:s:s:\(index)", "title=\(title)",
                      "-disposition:s:\(index)", forced ? "forced" : "0"]
    }
    arguments += ["-avoid_negative_ts", "make_zero"] + (mkv ? [] : ["-movflags", "+faststart"])
    // file: so a colon anywhere in the library path is not taken for a protocol name.
    try await ffmpeg(arguments + ["file:" + output.path])
}

/// HandBrake's "Plex" preset: x265 at CRF 26, capped at 1080p without upscaling, tagged hvc1 so QuickTime
/// and Apple devices play it. Kept only when it comes out smaller — otherwise it is a downgrade in size
/// and quality both.
func transcode(_ file: URL, duration: Double, report: @escaping @Sendable (Double) -> Void) async throws -> URL {
    let encoded = file.deletingLastPathComponent().appending(path: ".encoding-\(UUID().uuidString).mp4")
    defer { try? FileManager.default.removeItem(at: encoded) }
    try await ffmpeg(["-i", "file:" + file.path, "-progress", "pipe:1", "-map", "0",
                      "-c:v", "libx265", "-crf", "26", "-preset", "veryfast",
                      "-x265-params", "strong-intra-smoothing=0:rect=0:aq-mode=1",
                      "-vf", "scale='min(1920,iw)':'min(1080,ih)':force_original_aspect_ratio=decrease",
                      "-tag:v", "hvc1", "-c:a", "copy", "-c:s", "mov_text",
                      "-map_metadata", "0", "-map_chapters", "0", "file:" + encoded.path]) { line in
        if line.hasPrefix("out_time_us="), let micros = Double(line.dropFirst(12)), duration > 0 {
            report(min(micros / 1_000_000 / duration, 1))
        }
    }
    let size = { (url: URL) in (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0 }
    guard size(encoded) < size(file) else { return file }
    let final = file.deletingPathExtension().appendingPathExtension("mp4")
    guard rename(encoded.path, final.path) == 0 else { throw Failure("Impossibile sostituire \(final.lastPathComponent)") }
    if final != file { try? FileManager.default.removeItem(at: file) }
    return final
}

// MARK: A whole download

typealias Report = @Sendable (_ phase: String, _ fraction: Double, _ detail: String) -> Void

/// One film or episode into the library. Returns the file and its running time, which the encoder's
/// progress is measured against.
func download(_ request: DownloadRequest, domain: String, library: URL, temp: URL,
              report: @escaping Report) async throws -> (URL, Double) {
    report("Risoluzione", 0, "")
    let source: VideoSource
    if request.title.kind == .anime, let episode = request.episode {
        source = try await resolve(embed: try await AnimeUnity.embed(episode), referer: "https://\(AnimeUnity.host)/")
    } else {
        let embed = try await StreamingCommunity.embed(request.title, episode: request.episode, domain: domain)
        source = try await resolve(embed: embed, referer: "https://\(domain)/")
    }
    let master = try await Playlist.load(source.master, referer: source.referer)
    // Where vixcloud has always kept it; the playlists' own EXT-X-KEY names the same path.
    let key = try await fetch(URL(string: "https://vixcloud.co/storage/enc.key")!, referer: source.referer)

    let offered = master.media.filter { $0.type == "AUDIO" }
    var audio = offered.filter { request.audio.contains($0.language) }
    // Never a silent file: a title without the chosen language still gets the audio it does have.
    if audio.isEmpty, let fallback = offered.first(where: \.isDefault) ?? offered.first { audio = [fallback] }

    var video = master  // a master without variants is itself the media playlist
    if let best = master.variants.max(by: { $0.bandwidth < $1.bandwidth }) {
        video = try await Playlist.load(best.url, referer: source.referer)
    }
    let videoFile = temp.appending(path: "video.ts")
    try await downloadRendition(video, key: key, referer: source.referer, folder: temp.appending(path: "video"),
                                into: videoFile) { report("Video", $0, $1) }

    var audioFiles: [(URL, String)] = []
    for (index, track) in audio.enumerated() {
        let file = temp.appending(path: "audio\(index).ts")
        let playlist = try await Playlist.load(track.url, referer: source.referer)
        try await downloadRendition(playlist, key: key, referer: source.referer,
                                    folder: temp.appending(path: "audio\(index)"), into: file) {
            report("Audio \(track.language.uppercased())", $0, $1)
        }
        audioFiles.append((file, track.language))
    }

    var subtitleFiles: [(URL, String)] = []
    let subtitles = master.media.filter { $0.type == "SUBTITLES" && request.subtitles.contains($0.language) }
    for (index, track) in subtitles.enumerated() {
        // A subtitle that will not come is not worth failing a film over.
        guard let vtt = (try? await Playlist.load(track.url, referer: source.referer))?.segments.first,
              let data = try? await fetch(vtt, referer: source.referer) else { continue }
        let file = temp.appending(path: "sub\(index).vtt")
        try data.write(to: file)
        subtitleFiles.append((file, track.language))
    }

    report("Unione", 1, "")
    let container = audioFiles.count > 1 || !subtitleFiles.isEmpty ? "mkv" : "mp4"
    let output = destination(request, in: library).appendingPathExtension(container)
    try FileManager.default.createDirectory(at: output.deletingLastPathComponent(), withIntermediateDirectories: true)
    do {
        try await mux(video: videoFile, audio: audioFiles, subtitles: subtitleFiles, into: output)
    } catch {
        try? FileManager.default.removeItem(at: output)
        throw error
    }
    return (output, video.duration)
}
