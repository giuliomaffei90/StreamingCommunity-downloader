import Foundation

/// Finding the source again when its domain rotates, every few weeks. A third-party page publishes the
/// current one: this reads it, keeps only hosts that could plausibly be the source, proves one serves it,
/// and proposes it. Proposes — the page is edited by people we do not control, and the domain decides
/// where every search and download goes, so adopting it unseen would hand them that. "Applicalo senza
/// chiedere" opts out, and is off unless someone turns it on.
enum DomainRecovery {
    /// Overridable, because the page is somebody else's and may be deleted or replaced.
    static let page = URL(string: ProcessInfo.processInfo.environment["DOMAIN_SOURCE_URL"]
                          ?? "https://telegra.ph/Link-Aggiornato-StreamingCommunity-09-29")!

    /// Which names may ever be adopted. A constant with an environment override, never a setting: a text
    /// field that relaxes the guard against being redirected would be a loaded gun. A genuine rebrand
    /// fails closed, and a person types the new name in by hand.
    static let names = try! Regex(ProcessInfo.processInfo.environment["DOMAIN_NAME_PATTERN"]
                                  ?? "streaming(community|unity)[a-z0-9-]{0,12}")

    /// The https hosts a page links to, in order, at most five: past that it is not a list of links.
    static func hosts(in html: String) -> [String] {
        var hosts: [String] = []
        for link in html.matches(of: #/<a\b[^>]*\bhref="([^"]+)"/#) {
            guard let url = URL(string: String(link.1).htmlUnescaped), url.scheme == "https",
                  let host = url.host()?.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: ".")),
                  !host.isEmpty, !hosts.contains(host) else { continue }
            hosts.append(host)
        }
        return Array(hosts.prefix(5))
    }

    /// Why `host` may not be adopted, or nil when it may.
    static func rejection(_ host: String) -> String? {
        guard host.wholeMatch(of: #/[a-z0-9.-]{4,253}/#) != nil else { return String(localized: "forma non valida") }
        if host == "localhost" || [".local", ".internal", ".localhost", ".home", ".lan"].contains(where: { host.hasSuffix($0) }) {
            return String(localized: "nome locale")
        }
        if host.wholeMatch(of: #/[0-9.]+/#) != nil { return String(localized: "indirizzo IP") }
        var labels = host.split(separator: ".").map(String.init)
        if labels.count == 3, labels[0] == "www" { labels.removeFirst() }
        // The load-bearing rule. Checking only the first label would accept streamingcommunity.attacker.tld,
        // where the part that decides where the traffic lands is the attacker's.
        guard labels.count == 2 else { return String(localized: "non è un dominio di secondo livello") }
        guard labels[0].wholeMatch(of: names) != nil else { return String(localized: "nome «\(labels[0])» non riconosciuto") }
        return nil
    }

    /// Whether every address `host` resolves to is a public one. Otherwise a candidate could aim the app's
    /// requests at the network it runs inside.
    static func resolvesToPublic(_ host: String) async -> Bool {
        var hints = addrinfo()
        hints.ai_socktype = SOCK_STREAM
        var list: UnsafeMutablePointer<addrinfo>?
        guard getaddrinfo(host, "443", &hints, &list) == 0, let first = list else { return false }
        defer { freeaddrinfo(first) }
        for info in sequence(first: first, next: { $0.pointee.ai_next }) {
            guard let address = info.pointee.ai_addr else { return false }
            let bytes: [UInt8]
            switch Int32(address.pointee.sa_family) {
            case AF_INET:
                bytes = address.withMemoryRebound(to: sockaddr_in.self, capacity: 1) { withUnsafeBytes(of: $0.pointee.sin_addr) { Array($0) } }
            case AF_INET6:
                bytes = address.withMemoryRebound(to: sockaddr_in6.self, capacity: 1) { withUnsafeBytes(of: $0.pointee.sin6_addr) { Array($0) } }
            default:
                return false
            }
            if !isPublic(bytes) { return false }
        }
        return true
    }

    /// Loopback, private, link-local, shared, multicast, reserved and unspecified addresses are not; an
    /// IPv4 address mapped into IPv6 is judged as the IPv4 address it is.
    static func isPublic(_ b: [UInt8]) -> Bool {
        if b.count == 4 {
            return !(b[0] == 0 || b[0] == 10 || b[0] == 127 || b[0] >= 224
                     || (b[0] == 169 && b[1] == 254) || (b[0] == 172 && (16...31).contains(b[1]))
                     || (b[0] == 192 && b[1] == 168) || (b[0] == 100 && (64...127).contains(b[1])))
        }
        if b[0..<10].allSatisfy({ $0 == 0 }) && b[10] == 0xff && b[11] == 0xff { return isPublic(Array(b[12...])) }
        let loopbackOrUnspecified = b[0..<15].allSatisfy { $0 == 0 } && b[15] <= 1
        return !(loopbackOrUnspecified || b[0] == 0xff || (b[0] & 0xfe) == 0xfc || (b[0] == 0xfe && (b[1] & 0xc0) == 0x80))
    }

    /// Whether `host` serves the source: its home page carries the site's page object, with a version.
    /// Stricter than a domain typed in by hand, which is a person deciding; here a web page is deciding.
    static func verify(_ host: String) async -> Bool {
        guard let url = URL(string: "https://\(host)/"),
              let version = (try? await StreamingCommunity.page(url))?["version"] as? String else { return false }
        return !version.isEmpty
    }
}

/// The configured domain's state and the replacement waiting to be applied, for the sidebar and the
/// settings. Checked when the domain changes, every `domainCheckMinutes`, and on "Controlla ora".
@MainActor @Observable final class DomainWatch {
    struct Outcome {
        var answers = false
        var candidate: String?
        var applied = false
        var rejected: [(host: String, reason: String)] = []
    }

    /// Whether the configured domain answered the last time it was asked; nil while asking.
    private(set) var answers: Bool?
    /// The replacement found and waiting for a person. In memory only: the page it came from may change
    /// again, and one frozen across a restart could be applied long after it stopped being right.
    private(set) var candidate: String?
    /// When the page was last read. A dead domain would otherwise have somebody else's page read on
    /// every check.
    @ObservationIgnored private var lastRead = Date.distantPast

    init() {
        Task {
            while true {
                try? await Task.sleep(for: .seconds(max(30, UserDefaults.standard.integer(forKey: "domainCheckMinutes")) * 60))
                await check()
            }
        }
    }

    /// One pass. `force` is "Controlla ora": past the ten-minute floor, and looking further even when the
    /// domain answers, since whoever pressed it wants an answer. Nil when it was cut short.
    @discardableResult
    func check(force: Bool = false) async -> Outcome? {
        var outcome = Outcome()
        let current = configuredDomain
        answers = nil
        outcome.answers = current.isEmpty ? false : await DomainRecovery.verify(current)
        guard !Task.isCancelled, current == configuredDomain else { return nil }
        answers = outcome.answers
        if outcome.answers && !force { candidate = nil; return outcome }
        guard force || (UserDefaults.standard.bool(forKey: "domainAutoCheck") && Date().timeIntervalSince(lastRead) > 600)
        else { return outcome }
        lastRead = Date()

        guard let html = try? await fetch(DomainRecovery.page) else { return outcome }
        for host in DomainRecovery.hosts(in: String(decoding: html, as: UTF8.self)) where host != current {
            var reason = DomainRecovery.rejection(host)
            if reason == nil, !(await DomainRecovery.resolvesToPublic(host)) { reason = String(localized: "risolve a un indirizzo non pubblico") }
            if reason == nil, !(await DomainRecovery.verify(host)) { reason = String(localized: "non verificato") }
            if let reason { outcome.rejected.append((host, reason)); continue }
            outcome.candidate = host
            break
        }
        guard let found = outcome.candidate else { return outcome }

        if UserDefaults.standard.bool(forKey: "domainAutoApply"), await apply(found) {
            outcome.applied = true
            Notifier.shared.post(String(localized: "Dominio sorgente"),
                                 String(localized: "Il dominio della sorgente è cambiato: ora è «\(found)», applicato da solo."),
                                 library: false)
        } else {
            candidate = found
            // Whoever pressed "Controlla ora" is looking at the answer already.
            if !force {
                Notifier.shared.post(String(localized: "Dominio sorgente"),
                                     String(localized: "La sorgente non risponde più su «\(current)». Trovato «\(found)»: apri l'app per applicarlo."),
                                     library: false)
            }
        }
        return outcome
    }

    /// Writes `host` as the domain after checking it again, since a candidate can go stale between being
    /// proposed and being applied. False when it no longer checks out; the proposal goes either way.
    @discardableResult
    func apply(_ host: String) async -> Bool {
        candidate = nil
        guard DomainRecovery.rejection(host) == nil, await DomainRecovery.resolvesToPublic(host),
              await DomainRecovery.verify(host) else { return false }
        UserDefaults.standard.set(host, forKey: "domain")
        answers = true
        return true
    }

    func dismiss() { candidate = nil }
}
