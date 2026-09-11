import XCTest
@testable import StreamingCommunityDownloader

final class Tests: XCTestCase {
    /// Byte for byte what the Python app writes, or the two would split one library in two.
    func testLibraryLayoutMatchesThePythonApp() {
        func path(_ title: Title, _ episode: Episode? = nil, season: Int? = nil) -> String {
            let request = DownloadRequest(title: title, episode: episode, season: season, audio: [], subtitles: [])
            return destination(request, in: URL(filePath: "/L")).path
        }
        XCTAssertEqual(path(Title(id: "1", name: "Matrix", kind: .movie, year: "1999")), "/L/Matrix (1999)/Matrix (1999)")
        XCTAssertEqual(path(Title(id: "1", name: "Mr. Robot: Pilot", kind: .movie)), "/L/Mr. Robot Pilot/Mr. Robot Pilot")
        XCTAssertEqual(path(Title(id: "2", name: "Law, Order", kind: .tv, year: "1990"), Episode(id: "9", number: "7"), season: 2),
                       "/L/Law, Order (1990)/Season 02/Law, Order S02E07")
        XCTAssertEqual(path(Title(id: "3", name: "Steins;Gate: Movie+", kind: .anime, year: "2013", episodes: 1), Episode(id: "5", number: "1")),
                       "/L/Steins;Gate Movie (2013)/Steins;Gate Movie")
        XCTAssertEqual(path(Title(id: "4", name: "Naruto, Shippuden", kind: .anime, year: "2007", episodes: 500), Episode(id: "6", number: "12.5")),
                       "/L/Naruto Shippuden (2007)/Season 01/Naruto Shippuden S01E12.5")
        XCTAssertEqual(sanitize(" ../.. "), "senza-nome")
        XCTAssertEqual(padded("7"), "07")
        XCTAssertEqual(padded("7.5"), "07.5")
    }

    func testPlaylists() {
        let master = Playlist("""
            #EXTM3U
            #EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Italian",DEFAULT=YES,LANGUAGE="ita",URI="https://vixcloud.co/playlist/1?type=audio&rendition=ita"
            #EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="Italian [Forced]",DEFAULT=NO,LANGUAGE="forced-ita",URI="https://vixcloud.co/playlist/1?type=subtitle"
            #EXT-X-STREAM-INF:BANDWIDTH=1200000,CODECS="avc1.640028,mp4a.40.2",RESOLUTION=854x480,AUDIO="audio"
            https://vixcloud.co/playlist/1?type=video&rendition=480p
            #EXT-X-STREAM-INF:BANDWIDTH=2150000,CODECS="avc1.640028,mp4a.40.2",RESOLUTION=1280x720,AUDIO="audio"
            https://vixcloud.co/playlist/1?type=video&rendition=720p
            """, base: URL(string: "https://vixcloud.co/playlist/1?b=1")!)
        XCTAssertEqual(master.variants.max { $0.bandwidth < $1.bandwidth }?.url.absoluteString,
                       "https://vixcloud.co/playlist/1?type=video&rendition=720p")
        XCTAssertEqual(master.media.map(\.language), ["ita", "forced-ita"])
        XCTAssertEqual(master.media.map(\.isDefault), [true, false])
        XCTAssertTrue(master.segments.isEmpty)

        let media = Playlist("""
            #EXTM3U
            #EXT-X-KEY:METHOD=AES-128,URI="/storage/enc.key",IV=0x43A6D967D5C17290D98322F5C8F6660B
            #EXTINF:4,
            https://cdn.example/0000.ts?token=a
            #EXTINF:2.25,
            1.ts
            #EXT-X-ENDLIST
            """, base: URL(string: "https://vixcloud.co/playlist/1?type=video")!)
        XCTAssertTrue(media.encrypted)
        XCTAssertEqual(media.iv?.count, 16)
        XCTAssertEqual(media.iv?.first, 0x43)
        XCTAssertEqual(media.duration, 6.25)
        XCTAssertEqual(media.segments.map(\.absoluteString), ["https://cdn.example/0000.ts?token=a", "https://vixcloud.co/playlist/1.ts"])
    }

    func testSmallParsers() {
        XCTAssertEqual("{&quot;a&quot;:&quot;x &amp;quot; y&quot;}".htmlUnescaped, "{\"a\":\"x &quot; y\"}")
        // The source stores its plots escaped once more, inside a page that escapes them again.
        XCTAssertEqual("l&amp;#39;hacker".htmlUnescaped.htmlUnescaped, "l'hacker")
        XCTAssertEqual(languageName("forced-ita", in: Locale(identifier: "it")), "Italiano (forzati)")
        XCTAssertEqual(languageName("eng", in: Locale(identifier: "it")), "Inglese")
    }

    func testLimiterBacksOffThenEarnsItsWayBack() async {
        let limiter = Limiter(16)
        await limiter.penalise()
        await limiter.penalise()  // inside the two-second window: the same moment, not a second cut
        var allowance = await limiter.allowance
        XCTAssertEqual(allowance, 8)
        for _ in 0..<8 { await limiter.reward() }
        allowance = await limiter.allowance
        XCTAssertEqual(allowance, 9)
    }
}
