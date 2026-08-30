//
//  Polyline.swift
//  WHV
//
//  Google encoded-polyline (precision 1e-5) for the driven route. Compact
//  enough to ship with every trip; the admin map decodes it client-side.
//

import CoreLocation
import Foundation

enum Polyline {
    static func encode(_ coords: [CLLocationCoordinate2D]) -> String {
        var out = ""
        var prevLat = 0
        var prevLng = 0
        for c in coords {
            let lat = Int((c.latitude * 1e5).rounded())
            let lng = Int((c.longitude * 1e5).rounded())
            out += encodeValue(lat - prevLat)
            out += encodeValue(lng - prevLng)
            prevLat = lat
            prevLng = lng
        }
        return out
    }

    private static func encodeValue(_ value: Int) -> String {
        var v = value < 0 ? ~(value << 1) : (value << 1)
        var s = ""
        while v >= 0x20 {
            s.append(Character(UnicodeScalar((0x20 | (v & 0x1f)) + 63)!))
            v >>= 5
        }
        s.append(Character(UnicodeScalar(v + 63)!))
        return s
    }
}

/// Great-circle distance in metres.
func haversineMeters(_ a: CLLocationCoordinate2D, _ b: CLLocationCoordinate2D) -> Double {
    let r = 6_371_000.0
    let dLat = (b.latitude - a.latitude) * .pi / 180
    let dLng = (b.longitude - a.longitude) * .pi / 180
    let la1 = a.latitude * .pi / 180
    let la2 = b.latitude * .pi / 180
    let h = sin(dLat / 2) * sin(dLat / 2) + cos(la1) * cos(la2) * sin(dLng / 2) * sin(dLng / 2)
    return 2 * r * asin(min(1, sqrt(h)))
}
