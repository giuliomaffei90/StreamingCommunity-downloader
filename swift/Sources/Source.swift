import Foundation

/// Safari's own user agent. URLSession speaks Apple's TLS, and a Chrome agent on top of it is the
/// mismatch a bot check looks for; with this one, vixcloud's embed page and AnimeUnity answer without
/// the cloudscraper session the Python app needed.
let userAgent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"

struct Failure: LocalizedError {
    let errorDescription: String?
    init(_ message: String) { errorDescription = message }
}

struct HTTPStatus: LocalizedError {
    let code: Int
    let host: String
    var errorDescription: String? { "HTTP \(code) da \(host)" }
}

typealias JSON = [String: Any]

/// A JSON scalar as text, whichever type the source chose for it today.
func string(_ value: Any?) -> String? {
    switch value {
    case let text as String: return text.isEmpty ? nil : text
    case let number as NSNumber: return number.stringValue
    default: return nil
    }
}

/// One request, retried while the source is merely unwell — a timeout, a dropped connection, 429 or
/// 5xx. Any other status is a verdict, and repeating it only delays the same answer.
func fetch(_ url: URL, referer: String? = nil, headers: [String: String] = [:], body: Data? = nil) async throws -> Data {
    var request = URLRequest(url: url, timeoutInterval: 30)
    request.setValue(userAgent, forHTTPHeaderField: "User-Agent")
    request.setValue(referer, forHTTPHeaderField: "Referer")
    for (name, value) in headers { request.setValue(value, forHTTPHeaderField: name) }
    if let body { request.httpMethod = "POST"; request.httpBody = body }
    for attempt in 0..<3 {
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            if (200..<300).contains(status) { return data }
            if attempt == 2 || ![429, 500, 502, 503, 504].contains(status) {
                throw HTTPStatus(code: status, host: url.host ?? "?")
            }
        } catch let error as URLError where attempt < 2 && error.code != .cancelled {}
        try await Task.sleep(for: .seconds(1 << attempt))
    }
    throw URLError(.unknown)  // unreachable: the last attempt returns or throws
}

extension String {
    /// One level of HTML escaping undone: numeric entities, then the named ones Laravel writes, `&amp;`
    /// last so "&amp;quot;" stays "&quot;".
    var htmlUnescaped: String {
        let numeric = replacing(#/&#(\d+);/#) { match in
            UInt32(match.1).flatMap { Unicode.Scalar($0) }.map { String($0) } ?? String(match.0)
        }
        return [("&quot;", "\""), ("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&")]
            .reduce(numeric) { $0.replacingOccurrences(of: $1.0, with: $1.1) }
    }
}

struct Title: Identifiable, Hashable, Codable {
    enum Kind: String, Codable { case movie, tv, anime }
    var id: String
    var slug = ""
    var name: String
    var kind: Kind
    var year: String?
    var score: String?
    var poster: URL?
    var seasons = 0
    var episodes = 0
    var animeType: String?  // AnimeUnity's own classification: Movie, TV, OVA, ONA, Special
    var plot: String?       // AnimeUnity sends it with the search
    var genres: [String] = []

    /// AnimeUnity has no seasons: a film, or a title with a single episode, gets a folder of its own.
    var isAnimeMovie: Bool { kind == .anime && (animeType == "Movie" || episodes == 1) }
}

struct Episode: Identifiable, Hashable, Codable {
    var id: String
    var number: String
    var name = ""
}

/// A row of the start page: a list the source itself curates.
struct Shelf: Identifiable {
    let id: String
    let titles: [Title]
}

enum StreamingCommunity {
    static func url(_ domain: String, _ path: String, _ query: [String: String] = [:]) throws -> URL {
        var components = URLComponents(string: "https://\(domain)\(path)")
        if !query.isEmpty { components?.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) } }
        guard !domain.isEmpty, let url = components?.url else {
            throw Failure("Imposta il dominio di StreamingCommunity nelle Impostazioni")
        }
        return url
    }

    /// The props of a server-rendered page: the same JSON the site's XHR API answers, read out of the
    /// `data-page` attribute — so no asset version, no X-Inertia headers and no XSRF token.
    static func props(_ url: URL) async throws -> JSON {
        let html = String(decoding: try await fetch(url), as: UTF8.self)
        guard let match = html.firstMatch(of: #/data-page="([^"]*)"/#),
              let page = try? JSONSerialization.jsonObject(with: Data(String(match.1).htmlUnescaped.utf8)) as? JSON,
              let props = page["props"] as? JSON
        else { throw Failure("Risposta inattesa da \(url.host ?? "?"): il dominio è ancora quello giusto?") }
        return props
    }

    static func search(_ query: String, domain: String) async throws -> [Title] {
        let titles = try await props(url(domain, "/it/search", ["q": query]))["titles"] as? [JSON] ?? []
        return titles.compactMap { title($0, domain: domain) }
    }

    /// The home page's own sliders: what is trending, what was added lately, today's top ten.
    static func home(domain: String) async throws -> [Shelf] {
        let sliders = try await props(url(domain, "/it"))["sliders"] as? [JSON] ?? []
        return sliders.compactMap { slider in
            string(slider["label"]).map { label in
                Shelf(id: label, titles: (slider["titles"] as? [JSON] ?? []).compactMap { title($0, domain: domain) })
            }
        }
    }

    static func title(_ t: JSON, domain: String) -> Title? {
        guard let id = string(t["id"]), let name = string(t["name"]) else { return nil }
        let poster = (t["images"] as? [JSON])?.first { string($0["type"]) == "poster" }.flatMap { string($0["filename"]) }
        return Title(id: id, slug: string(t["slug"]) ?? "", name: name,
                     kind: string(t["type"]) == "movie" ? .movie : .tv,
                     year: (string(t["release_date"]) ?? string(t["last_air_date"])).map { String($0.prefix(4)) },
                     score: string(t["score"]).flatMap(Double.init).map { String(format: "%.1f", $0) },
                     poster: poster.flatMap { URL(string: "https://cdn.\(domain)/images/\($0)") },
                     seasons: t["seasons_count"] as? Int ?? 0)
    }

    struct Details { var plot: String?; var genres: [String]; var trailer: URL?; var seasons: Int }

    static func details(_ title: Title, domain: String) async throws -> Details {
        let t = try await props(url(domain, "/it/titles/\(title.id)-\(title.slug)"))["title"] as? JSON ?? [:]
        let trailer = (t["trailers"] as? [JSON])?.first.flatMap { string($0["youtube_id"]) }
        // The source stores its plots HTML-escaped, inside a page attribute that escapes them again.
        return Details(plot: string(t["plot"])?.htmlUnescaped, genres: (t["genres"] as? [JSON] ?? []).compactMap { string($0["name"]) },
                       trailer: trailer.flatMap { URL(string: "https://www.youtube.com/watch?v=\($0)") },
                       seasons: t["seasons_count"] as? Int ?? title.seasons)
    }

    static func episodes(_ title: Title, season: Int, domain: String) async throws -> [Episode] {
        let props = try await props(url(domain, "/it/titles/\(title.id)-\(title.slug)/season-\(season)"))
        return ((props["loadedSeason"] as? JSON)?["episodes"] as? [JSON] ?? []).compactMap { e in
            string(e["id"]).map { Episode(id: $0, number: string(e["number"]) ?? "?", name: string(e["name"])?.htmlUnescaped ?? "") }
        }
    }

    /// The vixcloud embed page the title's player iframe points at.
    static func embed(_ title: Title, episode: Episode?, domain: String) async throws -> URL {
        let query = episode.map { ["episode_id": $0.id, "next_episode": "1"] } ?? [:]
        let html = String(decoding: try await fetch(url(domain, "/it/iframe/\(title.id)", query)), as: UTF8.self)
        guard let src = html.firstMatch(of: #/<iframe[^>]*src="([^"]+)"/#),
              let embed = URL(string: String(src.1).htmlUnescaped)
        else { throw Failure("Video non disponibile sulla fonte") }
        return embed
    }
}

enum AnimeUnity {
    static let host = "www.animeunity.so"

    /// `/archivio/get-animes` rather than `/livesearch`, which the source caps at eight records: the
    /// archive answers thirty and applies both filters over the whole catalogue.
    static func search(_ query: String, dubbed: Bool, type: String?) async throws -> [Title] {
        let home = String(decoding: try await fetch(URL(string: "https://\(host)/")!), as: UTF8.self)
        let csrf = home.firstMatch(of: #/<meta name="csrf-token" content="([^"]+)"/#).map { String($0.1) } ?? ""
        var payload: JSON = ["title": query, "offset": 0]
        if dubbed { payload["dubbed"] = 1 }
        if let type { payload["type"] = type }
        let data = try await fetch(URL(string: "https://\(host)/archivio/get-animes")!, referer: "https://\(host)/archivio",
                                   headers: ["Content-Type": "application/json", "Accept": "application/json",
                                             "X-Requested-With": "XMLHttpRequest", "X-CSRF-TOKEN": csrf],
                                   body: try JSONSerialization.data(withJSONObject: payload))
        let records = (try JSONSerialization.jsonObject(with: data) as? JSON)?["records"] as? [JSON] ?? []
        return records.compactMap(title)
    }

    /// The home page's own lists: the latest episodes, as the animes they belong to, and the featured
    /// carousel. Both ride in element attributes as escaped JSON.
    static func home() async throws -> [Shelf] {
        let html = String(decoding: try await fetch(URL(string: "https://\(host)/")!), as: UTF8.self)
        func decoded(_ match: Regex<(Substring, Substring)>.Match?) -> Any? {
            match.flatMap { try? JSONSerialization.jsonObject(with: Data(String($0.1).htmlUnescaped.utf8)) }
        }
        var seen = Set<String>()
        let latest = ((decoded(html.firstMatch(of: #/items-json="([^"]*)"/#)) as? JSON)?["data"] as? [JSON] ?? [])
            .compactMap { ($0["anime"] as? JSON).flatMap(title) }
            .filter { seen.insert($0.id).inserted }
        let featured = (decoded(html.firstMatch(of: #/<the-carousel[^>]*animes="([^"]*)"/#)) as? [JSON] ?? []).compactMap(title)
        return [Shelf(id: "Ultimi episodi", titles: latest), Shelf(id: "In evidenza", titles: featured)]
            .filter { !$0.titles.isEmpty }
    }

    static func title(_ r: JSON) -> Title? {
        guard let id = string(r["id"]),
              let name = string(r["title_eng"]) ?? string(r["title"]) ?? string(r["name"]) else { return nil }
        let slug = string(r["slug"]) ?? ""
        return Title(id: slug.isEmpty ? id : "\(id)-\(slug)", slug: slug,
                     name: name.trimmingCharacters(in: .whitespaces), kind: .anime,
                     year: string(r["date"]).map { String($0.prefix(4)) },
                     score: string(r["score"]).flatMap(Double.init).map { String(format: "%.1f", $0) },
                     poster: string(r["imageurl"]).flatMap { URL(string: $0) },
                     episodes: r["episodes_count"] as? Int ?? 0, animeType: string(r["type"]),
                     plot: string(r["plot"])?.htmlUnescaped, genres: (r["genres"] as? [JSON] ?? []).compactMap { string($0["name"]) })
    }

    static func episodes(_ title: Title) async throws -> [Episode] {
        let info = try JSONSerialization.jsonObject(with: try await fetch(URL(string: "https://\(host)/info_api/\(title.id)")!)) as? JSON
        let count = info?["episodes_count"] as? Int ?? 0
        var episodes: [Episode] = []
        // The source hands them out 120 at a time.
        for start in stride(from: 0, to: count + 1, by: 120) {
            var url = URLComponents(string: "https://\(host)/info_api/\(title.id)/0")!
            url.queryItems = [URLQueryItem(name: "start_range", value: "\(start)"),
                              URLQueryItem(name: "end_range", value: "\(min(start + 119, count))")]
            let batch = try JSONSerialization.jsonObject(with: try await fetch(url.url!)) as? JSON
            episodes += (batch?["episodes"] as? [JSON] ?? []).compactMap { e in
                string(e["id"]).map { Episode(id: $0, number: string(e["number"]) ?? "?") }
            }
        }
        return episodes
    }

    static func embed(_ episode: Episode) async throws -> URL {
        let text = String(decoding: try await fetch(URL(string: "https://\(host)/embed-url/\(episode.id)")!), as: UTF8.self)
        guard let url = URL(string: text.trimmingCharacters(in: .whitespacesAndNewlines)), url.scheme == "https"
        else { throw Failure("Risposta inattesa da AnimeUnity") }
        return url
    }
}

/// What a vixcloud embed page hands over: the master playlist, and the referer every later request carries.
struct VideoSource { let master: URL; let referer: String }

func resolve(embed: URL, referer: String) async throws -> VideoSource {
    let html = String(decoding: try await fetch(embed, referer: referer), as: UTF8.self)
    guard let id = html.firstMatch(of: #/window\.video\s*=\s*\{[^}]*?\bid\s*:\s*['"]?(\d+)/#)?.1,
          let token = html.firstMatch(of: #/['"]token['"]\s*:\s*['"]([^'"]*)['"]/#)?.1,
          let expires = html.firstMatch(of: #/['"]expires['"]\s*:\s*['"]([^'"]*)['"]/#)?.1
    else { throw Failure("Video non disponibile: la pagina del player non ha una playlist") }
    let embedQuery = URLComponents(url: embed, resolvingAgainstBaseURL: false)?.queryItems ?? []
    var query = [URLQueryItem(name: "token", value: String(token)), URLQueryItem(name: "expires", value: String(expires))]
    if embedQuery.contains(where: { $0.name == "canPlayFHD" }) { query.append(URLQueryItem(name: "h", value: "1")) }
    if embedQuery.contains(where: { $0.name == "scz" }) { query.append(URLQueryItem(name: "scz", value: "1")) }
    query.append(URLQueryItem(name: "lang", value: embedQuery.first { $0.name == "lang" }?.value ?? "it"))
    var master = URLComponents(string: "https://vixcloud.co/playlist/\(id)")!
    master.queryItems = query
    return VideoSource(master: master.url!, referer: embed.absoluteString)
}

/// The audio and subtitle languages a title offers; a series is sampled on its first episode.
func languages(of title: Title, domain: String) async throws -> (audio: [String], subtitles: [String]) {
    let episode: Episode? = if title.kind == .tv {
        try await StreamingCommunity.episodes(title, season: 1, domain: domain).first
    } else { nil }
    let embed = try await StreamingCommunity.embed(title, episode: episode, domain: domain)
    let source = try await resolve(embed: embed, referer: "https://\(domain)/")
    let media = try await Playlist.load(source.master, referer: source.referer).media
    return (media.filter { $0.type == "AUDIO" }.map(\.language),
            media.filter { $0.type == "SUBTITLES" && $0.language != "auto" }.map(\.language))
}
