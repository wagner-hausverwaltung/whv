// Wire shape of a single RSS 2.0 <item> from the vermieter1x1.de feed.
//
// Two notes on the choices here:
//
//   1. `pubDate` is parsed from the RFC 822 string the feed emits
//      ("Tue, 28 Oct 2025 08:15:48 +0100"). Foundation's date parsers
//      need a fixed locale + format; see `RSSService.dateFormatter`.
//      Failure to parse falls back to `Date.distantPast` so a single
//      malformed entry doesn't poison the whole list.
//
//   2. The feed's `<description>` field carries the article lede with
//      HTML entities ("&quot;", " "). We strip them in
//      `summary` so the cards don't show `&quot;Bauturbo&quot;`.
//      Full HTML stripping isn't worth the complexity here — entities
//      are the only artefacts in observed feed output.

import Foundation

/// A single feed entry. Decoded from the RSS XML by `RSSService`.
struct RSSItem: Identifiable, Hashable {
    /// Stable ID for SwiftUI ForEach. The feed has no <guid>, so we
    /// use `link` as the identity — it's unique per article on
    /// vermieter1x1.de.
    var id: String { link.absoluteString }

    let title: String
    let summary: String
    let link: URL
    let pubDate: Date
    let category: String?
    /// Optional inline image from <enclosure type="image/...">.
    /// Not every entry has one — only news with a hero photo.
    let imageURL: URL?
}

extension RSSItem {
    /// Strip the HTML entities the feed sometimes embeds in
    /// description. Doesn't try to parse arbitrary HTML — that's
    /// what `WKWebView` is for on the detail page.
    static func cleanSummary(_ raw: String) -> String {
        let replacements: [(String, String)] = [
            (" ", " "),
            ("&quot;", "\""),
            ("&amp;", "&"),
            ("&lt;", "<"),
            ("&gt;", ">"),
            ("&apos;", "'"),
            ("&#39;", "'"),
        ]
        var out = raw
        for (from, to) in replacements {
            out = out.replacingOccurrences(of: from, with: to)
        }
        // Collapse whitespace runs (the feed has stray newlines + tabs).
        let collapsed = out.components(separatedBy: .whitespacesAndNewlines)
            .filter { !$0.isEmpty }
            .joined(separator: " ")
        return collapsed
    }
}
