// Keeps Premiere Pro off the user's screen while Claude drives it.
//
//   ppro-hide guard     hide Premiere now and keep re-hiding it (every 30 ms) until stdin closes
//   ppro-hide hide      hide once
//   ppro-hide onscreen  print how many Premiere windows are visible on screen right now
//   ppro-hide watch N   sample on-screen windows every 20 ms for N seconds; print max seen
//
// Never activates or focuses anything.
import AppKit
import CoreGraphics

let bundleID = ProcessInfo.processInfo.environment["PCB_PREMIERE_BUNDLE"] ?? "com.adobe.PremierePro.27"

func premiere() -> NSRunningApplication? {
    NSRunningApplication.runningApplications(withBundleIdentifier: bundleID).first
}

// NSRunningApplication.hide() is refused for Premiere, and its isHidden flag goes stale when
// Premiere re-shows its own windows. System Events' "visible" works, so use that, and only
// when a Premiere window is actually on screen.
let hideScript = NSAppleScript(source: """
tell application "System Events" to set visible of process "\(ProcessInfo.processInfo.environment["PCB_PREMIERE_APP"] ?? "Adobe Premiere Pro 2027")" to false
""")!

func hideNow(force: Bool = false) {
    guard premiere() != nil else { return }
    if force || onScreenCount() > 0 {
        var err: NSDictionary?
        hideScript.executeAndReturnError(&err)
    }
}

func onScreenCount() -> Int {
    guard let app = premiere(),
          let info = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]]
    else { return 0 }
    let pid = app.processIdentifier
    return info.filter { w in
        guard (w[kCGWindowOwnerPID as String] as? Int32) == pid,
              (w[kCGWindowLayer as String] as? Int) == 0,
              let b = w[kCGWindowBounds as String] as? [String: CGFloat],
              (b["Width"] ?? 0) > 40, (b["Height"] ?? 0) > 40 else { return false }
        return ((w[kCGWindowAlpha as String] as? Double) ?? 1) > 0
    }.count
}

let args = CommandLine.arguments
switch args.count > 1 ? args[1] : "onscreen" {
case "hide":
    hideNow(force: true)
case "guard":
    // Poll on-screen windows every 15 ms; hide the moment one appears.
    // Exit when the parent closes our stdin, after a short tail (Premiere re-shows windows
    // a beat after a job finishes, e.g. the Home screen after a project closes).
    // Stop signal: the parent creates the stop file (args[2]) or dies.
    let stopFile = args.count > 2 ? args[2] : ""
    let parent = getppid()
    var closing: Date? = nil
    Timer.scheduledTimer(withTimeInterval: 0.015, repeats: true) { _ in
        hideNow()
        if closing == nil && ((!stopFile.isEmpty && FileManager.default.fileExists(atPath: stopFile)) || getppid() != parent) {
            closing = Date()
        }
        if let c = closing, Date().timeIntervalSince(c) > 3.0 {
            hideNow(force: true)
            if !stopFile.isEmpty { try? FileManager.default.removeItem(atPath: stopFile) }
            exit(0)
        }
    }
    hideNow(force: true)
    RunLoop.main.run()
case "watch":
    let secs = Double(args.count > 2 ? args[2] : "10") ?? 10
    var maxSeen = 0, samplesWithWindows = 0, total = 0
    let end = Date().addingTimeInterval(secs)
    while Date() < end {
        let n = onScreenCount(); total += 1
        if n > 0 { samplesWithWindows += 1 }
        maxSeen = max(maxSeen, n)
        usleep(20_000)
    }
    print("samples=\(total) with_premiere_windows=\(samplesWithWindows) max_windows=\(maxSeen)")
case "away":
    // Is the user away? JSON: screen locked, all displays asleep, screensaver, seconds idle.
    let session = (CGSessionCopyCurrentDictionary() as? [String: Any]) ?? [:]
    let locked = (session["CGSSessionScreenIsLocked"] as? Bool) ?? false
    let onConsole = (session[kCGSessionOnConsoleKey as String] as? Bool) ?? true
    var ids = [CGDirectDisplayID](repeating: 0, count: 16); var n: UInt32 = 0
    CGGetOnlineDisplayList(16, &ids, &n)
    let asleep = n == 0 || (0..<Int(n)).allSatisfy { CGDisplayIsAsleep(ids[$0]) != 0 }
    let saver = NSWorkspace.shared.runningApplications.contains {
        ($0.bundleIdentifier ?? "").contains("ScreenSaver") || ($0.localizedName ?? "") == "ScreenSaverEngine"
    }
    let idle = CGEventSource.secondsSinceLastEventType(.hidSystemState, eventType: CGEventType(rawValue: ~0)!)
    print("{\"locked\":\(locked),\"on_console\":\(onConsole),\"displays_asleep\":\(asleep),\"screensaver\":\(saver),\"idle_seconds\":\(Int(idle))}")
default:
    print(onScreenCount())
}
