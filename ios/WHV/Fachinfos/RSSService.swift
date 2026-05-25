// Async RSS fetcher + XML parser.
//
// We hand-roll an XMLParser-based parser instead of pulling in a
// dependency (FeedKit, etc.) — keeps the scaffold dep-free and the
// RSS 2.0 surface we need (title, link, description, pubDate,
// category, enclosure) is small. About 60 lines of state machine.

import Foundation

/// Errors surfaced to the UI. Folded into a single enum with a
/// localised description so the SwiftUI error state copy is trivial.
enum RSSError: Error, LocalizedError {
    case network(underlying: Error)
    case http(status: Int)
    case parse

    var errorDescription: String? {
        switch self {
        case .network(let err):
            return "Netzwerkfehler: \(err.localizedDescription)"
        case .http(let status):
            return "Server antwortete mit Status \(status)."
        case .parse:
            return "Feed konnte nicht ausgewertet werden."
        }
    }
}

/// Fetches + parses the vermieter1x1.de RSS feed.
///
/// Stateless by design — every call builds a fresh `URLSession`
/// request. The feed has a 60-min TTL (server-side `<ttl>60</ttl>`)
/// but URLSession's default caching policy already respects the
/// HTTP cache headers, so we don't need our own layer.
struct RSSService {
    /// The canonical Fachinfos feed.
    static let defaultFeedURL = URL(string: "https://www.vermieter1x1.de/Fachinfo/rss/")!

    let feedURL: URL

    init(feedURL: URL = RSSService.defaultFeedURL) {
        self.feedURL = feedURL
    }

    func fetch() async throws -> [RSSItem] {
        var request = URLRequest(url: feedURL)
        // Identify the app in server logs. Some sites also gate
        // RSS access on a recognisable UA; explicit beats default.
        request.setValue(
            "WHV-iOS/0.1 (+ios-scaffold)",
            forHTTPHeaderField: "User-Agent"
        )
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, http.statusCode != 200 {
                throw RSSError.http(status: http.statusCode)
            }
            return try Self.parse(data: data)
        } catch let err as RSSError {
            throw err
        } catch {
            throw RSSError.network(underlying: error)
        }
    }

    // MARK: - XML parsing
    //
    // Single-pass state machine driven by `XMLParserDelegate`. We
    // accumulate the current element's character data into
    // `currentText`, then on `</item>` snapshot a struct from the
    // current scratch fields and reset.

    static func parse(data: Data) throws -> [RSSItem] {
        let delegate = ParserDelegate()
        let parser = XMLParser(data: data)
        parser.delegate = delegate
        guard parser.parse(), delegate.parserError == nil else {
            throw RSSError.parse
        }
        return delegate.items
    }

    static let dateFormatter: DateFormatter = {
        let f = DateFormatter()
        // RFC 822 — what RSS 2.0 mandates. Locale=en_US_POSIX so the
        // weekday/month names parse independent of the device locale
        // (a German user with locale=de_DE would otherwise fail to
        // parse "Tue" / "Oct" etc.).
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "EEE, dd MMM yyyy HH:mm:ss Z"
        return f
    }()

    private final class ParserDelegate: NSObject, XMLParserDelegate {
        var items: [RSSItem] = []
        var parserError: Error?

        // Per-item scratch fields. Reset on <item> open.
        private var title = ""
        private var link = ""
        private var description_ = ""
        private var pubDate = ""
        private var category: String?
        private var imageURL: URL?

        // Tracks the current text-bearing element. Channel-level
        // <title>/<link> also fire these events; `inItem` gates the
        // accumulation to skip them.
        private var currentElement = ""
        private var currentText = ""
        private var inItem = false

        func parser(
            _ parser: XMLParser,
            didStartElement elementName: String,
            namespaceURI: String?,
            qualifiedName qName: String?,
            attributes attributeDict: [String: String] = [:]
        ) {
            currentElement = elementName
            currentText = ""
            if elementName == "item" {
                inItem = true
                title = ""
                link = ""
                description_ = ""
                pubDate = ""
                category = nil
                imageURL = nil
            }
            // <enclosure url="..." type="image/..."/> — only inside <item>.
            if inItem,
               elementName == "enclosure",
               let urlString = attributeDict["url"],
               let url = URL(string: urlString),
               (attributeDict["type"]?.hasPrefix("image/") ?? false)
            {
                imageURL = url
            }
        }

        func parser(_ parser: XMLParser, foundCharacters string: String) {
            currentText += string
        }

        func parser(_ parser: XMLParser, foundCDATA CDATABlock: Data) {
            if let s = String(data: CDATABlock, encoding: .utf8) {
                currentText += s
            }
        }

        func parser(
            _ parser: XMLParser,
            didEndElement elementName: String,
            namespaceURI: String?,
            qualifiedName qName: String?
        ) {
            guard inItem else { return }
            let value = currentText.trimmingCharacters(in: .whitespacesAndNewlines)
            switch elementName {
            case "title":
                title = value
            case "link":
                link = value
            case "description":
                description_ = value
            case "pubDate":
                pubDate = value
            case "category":
                category = value.isEmpty ? nil : value
            case "item":
                if let url = URL(string: link) {
                    let date = RSSService.dateFormatter.date(from: pubDate) ?? .distantPast
                    items.append(
                        RSSItem(
                            title: title,
                            summary: RSSItem.cleanSummary(description_),
                            link: url,
                            pubDate: date,
                            category: category,
                            imageURL: imageURL
                        )
                    )
                }
                inItem = false
            default:
                break
            }
            currentText = ""
        }

        func parser(_ parser: XMLParser, parseErrorOccurred parseError: Error) {
            parserError = parseError
        }
    }
}
