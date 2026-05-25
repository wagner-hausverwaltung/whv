// Mitteilungen (announcements) — wire shapes mirror the backend's
// AnnouncementResponse / AnnouncementDetailResponse /
// AnnouncementAttachmentResponse / AnnouncementCommentResponse.
//
// The list endpoint returns the summary; the detail endpoint
// returns the full tree (attachments + comments embedded). Same
// split rationale as ETV: list rows can't accidentally rely on
// detail data they don't have.

import Foundation

/// Detail view of a single announcement — attachments + comments
/// included so the detail screen renders without N+1 fetches.
struct AnnouncementDetail: Codable, Identifiable, Hashable {
    let id: String
    let organization_id: String
    let property_id: String
    let created_by_user_id: String
    let title: String
    let body: String
    let audience_eigentuemer: Bool
    let audience_mieter: Bool
    let audience_beirat: Bool
    let created_at: Date
    let updated_at: Date
    let scheduled_publish_at: Date
    let notification_sent_at: Date?
    let property_name: String?
    let creator_email: String?
    let is_edited: Bool
    let attachment_count: Int
    let comment_count: Int
    let attachments: [AnnouncementAttachment]
    let comments: [AnnouncementComment]

    /// Audience labels the detail view chips. Empty when neither
    /// audience flag is set (shouldn't happen — backend enforces at
    /// least one — but kept defensive).
    var audienceLabels: [String] {
        var out: [String] = []
        if audience_eigentuemer { out.append("Eigentümer") }
        if audience_mieter { out.append("Mieter") }
        if audience_beirat { out.append("Beirat") }
        return out
    }
}

struct AnnouncementAttachment: Codable, Identifiable, Hashable {
    let id: String
    let announcement_id: String
    let filename: String
    let mime_type: String?
    let size_bytes: Int
    let uploaded_by_user_id: String?
    let created_at: Date
}

struct AnnouncementComment: Codable, Identifiable, Hashable {
    let id: String
    let announcement_id: String
    let author_user_id: String
    let author_email: String?
    let body: String
    let created_at: Date
    let updated_at: Date
    let edited_at: Date?
}
