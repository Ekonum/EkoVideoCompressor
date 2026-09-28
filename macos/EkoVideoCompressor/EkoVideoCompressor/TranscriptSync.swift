import AppKit
import Foundation
import Security
import SwiftUI

// MARK: - Keychain

/// The device token for transcript.ekonum.fr lives in the login Keychain,
/// never in a file or in UserDefaults: a plain-text token ends up in
/// backups and gets copied around without anyone noticing. Same rule as
/// sync-hub's `enroll.sh`.
enum TranscriptKeychain {
    private static let service = "transcript-ekonum-token"
    private static let account = "EkoVideoCompressor"

    static func read() -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data,
              let token = String(data: data, encoding: .utf8),
              !token.isEmpty
        else { return nil }
        return token
    }

    @discardableResult
    static func save(_ token: String) -> Bool {
        delete()
        let attributes: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecAttrLabel as String: "transcript.ekonum.fr — jeton d'appareil",
            kSecValueData as String: Data(token.utf8),
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlock,
        ]
        return SecItemAdd(attributes as CFDictionary, nil) == errSecSuccess
    }

    static func delete() {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
    }
}

// MARK: - Store

/// Hands the local library over to transcript.ekonum.fr.
///
/// Two moments, and the second one can repeat:
/// 1. **Enrolment** — once per Mac. The engine opens a request, the app
///    shows a short code and opens the approval page in the browser,
///    where Cloudflare Access already knows who the user is. Once
///    approved, the device's own token goes to the Keychain.
/// 2. **Push** — every finished meeting goes through the server's import
///    endpoint. The server de-duplicates, so pushing again later only
///    sends what is new.
///
/// Nothing here ever interrupts work: no modal at launch, a banner that
/// "Plus tard" dismisses for good, and a menu entry for whoever wants
/// it back.
@MainActor
final class TranscriptSyncStore: ObservableObject {
    enum Phase: Equatable {
        case idle
        case starting
        case awaitingApproval(code: String, url: URL)
        case pushing(done: Int, total: Int, label: String)
        case done(pushed: Int, already: Int, failed: Int)
        case failed(String)
    }

    static let serverURL = URL(string: "https://transcript.ekonum.fr")!

    @Published private(set) var phase: Phase = .idle

    /// Persisted by hand rather than with ``@AppStorage``: inside an
    /// ``ObservableObject`` the latter does not publish, so « Plus tard »
    /// would leave the banner on screen until something else redrew it.
    @Published var bannerDismissed: Bool = UserDefaults.standard.bool(
        forKey: TranscriptSyncStore.dismissedKey
    ) {
        didSet {
            UserDefaults.standard.set(bannerDismissed, forKey: TranscriptSyncStore.dismissedKey)
        }
    }
    private static let dismissedKey = "transcriptSyncBannerDismissed"

    private var pollTask: Task<Void, Never>?
    private let pushEngine = EngineProcess()

    var isBusy: Bool {
        switch phase {
        case .starting, .awaitingApproval, .pushing: return true
        default: return false
        }
    }

    /// Banner visibility: shown until dismissed, and always while a
    /// transfer the user started is in flight or has just finished.
    var showsBanner: Bool {
        if case .idle = phase { return !bannerDismissed }
        return true
    }

    func start() {
        guard !isBusy else { return }
        bannerDismissed = false
        if let token = TranscriptKeychain.read() {
            Task { await push(token: token) }
        } else {
            Task { await enrol() }
        }
    }

    func cancel() {
        pollTask?.cancel()
        pollTask = nil
        pushEngine.cancel()
        phase = .idle
    }

    func dismiss() {
        cancel()
        bannerDismissed = true
    }

    // MARK: Enrolment

    private func enrol() async {
        phase = .starting
        let result = await EngineProcess.runCommand(
            arguments: EngineProcess.defaultPythonArguments(["transcript-enroll-start"])
        )
        struct Start: Decodable {
            var ok: Bool?
            var error: String?
            var code_appareil: String?
            var code_humain: String?
            var url: String?
        }
        guard let payload = Self.decode(Start.self, from: result.rawOutput) else {
            phase = .failed("Réponse du moteur illisible.")
            return
        }
        guard payload.ok == true,
              let deviceCode = payload.code_appareil,
              let humanCode = payload.code_humain,
              let link = payload.url.flatMap(URL.init(string:))
        else {
            phase = .failed(payload.error ?? "Impossible d'ouvrir la demande d'autorisation.")
            return
        }
        phase = .awaitingApproval(code: humanCode, url: link)
        // The link *is* the approval step: open it for the user rather
        // than asking them to copy it.
        NSWorkspace.shared.open(link)
        pollTask = Task { await poll(deviceCode: deviceCode) }
    }

    private func poll(deviceCode: String) async {
        struct Poll: Decodable {
            var ok: Bool?
            var error: String?
            var statut: String?
            var token: String?
        }
        // The server expires requests after 15 minutes; polling every
        // 3 s keeps the wait short without hammering it.
        let deadline = Date().addingTimeInterval(15 * 60)
        while !Task.isCancelled, Date() < deadline {
            try? await Task.sleep(nanoseconds: 3_000_000_000)
            if Task.isCancelled { return }
            let result = await EngineProcess.runCommand(
                arguments: EngineProcess.defaultPythonArguments(["transcript-enroll-poll"]),
                environment: ["TRANSCRIPT_DEVICE_CODE": deviceCode]
            )
            guard let answer = Self.decode(Poll.self, from: result.rawOutput) else { continue }
            if answer.ok != true {
                // A network blip while waiting is not a failure: keep
                // polling until the deadline.
                continue
            }
            switch answer.statut {
            case "approuve":
                guard let token = answer.token, TranscriptKeychain.save(token) else {
                    phase = .failed("Autorisation reçue, mais le trousseau a refusé le jeton.")
                    return
                }
                await push(token: token)
                return
            case "expire", "consomme":
                phase = .failed("La demande a expiré. Relance le transfert.")
                return
            default:
                continue
            }
        }
        if !Task.isCancelled {
            phase = .failed("La demande a expiré. Relance le transfert.")
        }
    }

    // MARK: Push

    private func push(token: String) async {
        phase = .pushing(done: 0, total: 0, label: "Préparation…")
        let observer = Task { @MainActor [weak self] in
            guard let self else { return }
            while !Task.isCancelled {
                if let event = self.pushEngine.events.last(where: { $0.event == .progress }),
                   let message = event.message {
                    self.phase = Self.progressPhase(from: message)
                }
                try? await Task.sleep(nanoseconds: 250_000_000)
            }
        }
        let status = await pushEngine.runAndWait(
            arguments: EngineProcess.defaultPythonArguments(["transcript-push"]),
            environment: ["TRANSCRIPT_TOKEN": token]
        )
        observer.cancel()

        if status == 0,
           let summary = pushEngine.events.last(where: { $0.event == .done })?.summary {
            func count(_ key: String) -> Int {
                if case .number(let value)? = summary[key] { return Int(value) }
                return 0
            }
            phase = .done(pushed: count("pushed"), already: count("already"), failed: count("failed"))
            return
        }
        let error = pushEngine.events.last(where: { $0.event == .error })
        if error?.code == "transcript_auth" {
            // A revoked or deleted token: forget it, so the next attempt
            // goes through a fresh approval instead of failing forever.
            TranscriptKeychain.delete()
        }
        phase = .failed(error?.message ?? pushEngine.lastError ?? "Le transfert a échoué.")
    }

    /// "12/97 — Acritec - Revue" → pushing(12, 97, "Acritec - Revue").
    private static func progressPhase(from message: String) -> Phase {
        let parts = message.split(separator: "—", maxSplits: 1).map {
            $0.trimmingCharacters(in: .whitespaces)
        }
        let counts = (parts.first ?? "").split(separator: "/").compactMap { Int($0) }
        return .pushing(
            done: counts.first ?? 0,
            total: counts.count > 1 ? counts[1] : 0,
            label: parts.count > 1 ? parts[1] : ""
        )
    }

    private static func decode<T: Decodable>(_ type: T.Type, from output: String) -> T? {
        // The engine prints one JSON object; anything before it (a stray
        // warning on stderr, merged into the pipe) must not break decoding.
        guard let start = output.firstIndex(of: "{"),
              let data = String(output[start...]).data(using: .utf8)
        else { return nil }
        return try? JSONDecoder().decode(type, from: data)
    }
}

// MARK: - Banner

/// A quiet strip above the library — never a modal. It offers the
/// transfer once, can be put away for good, and reports progress while a
/// transfer runs.
struct TranscriptSyncBanner: View {
    @EnvironmentObject private var sync: TranscriptSyncStore

    var body: some View {
        if sync.showsBanner {
            HStack(alignment: .center, spacing: 12) {
                Image(systemName: icon)
                    .font(.title3)
                    .foregroundStyle(.tint)
                VStack(alignment: .leading, spacing: 2) {
                    content
                }
                Spacer()
                actions
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(Color.accentColor.opacity(0.07))
            .overlay(Divider(), alignment: .bottom)
        }
    }

    private var icon: String {
        switch sync.phase {
        case .done: return "checkmark.icloud"
        case .failed: return "exclamationmark.icloud"
        default: return "icloud.and.arrow.up"
        }
    }

    @ViewBuilder
    private var content: some View {
        switch sync.phase {
        case .idle:
            Text("Tes transcriptions ont maintenant leur place sur transcript.ekonum.fr")
                .font(.headline)
            Text("Transfère ta bibliothèque en un clic : rien n'est effacé ici, et on peut recommencer plus tard pour envoyer les nouvelles.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        case .starting:
            Text("Préparation de l'autorisation…")
                .font(.headline)
        case .awaitingApproval(let code, _):
            Text("Autorise ce Mac dans ton navigateur")
                .font(.headline)
            Text("Vérifie que la page affiche bien le code \(code), puis clique sur « Autoriser ».")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        case .pushing(let done, let total, let label):
            Text(total > 0 ? "Transfert : \(done) / \(total)" : "Transfert en cours…")
                .font(.headline)
            if total > 0 {
                ProgressView(value: Double(done), total: Double(total))
                    .frame(maxWidth: 360)
            }
            if !label.isEmpty {
                Text(label)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        case .done(let pushed, let already, let failed):
            Text(pushed == 0 && failed == 0
                 ? "Tout est déjà sur transcript.ekonum.fr"
                 : "\(pushed) réunion(s) transférée(s)")
                .font(.headline)
            Text(summaryLine(already: already, failed: failed))
                .font(.subheadline)
                .foregroundStyle(.secondary)
        case .failed(let message):
            Text("Le transfert n'a pas abouti")
                .font(.headline)
            Text(message)
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    private var actions: some View {
        switch sync.phase {
        case .idle:
            Button("Plus tard") { sync.dismiss() }
            Button("Transférer ma bibliothèque") { sync.start() }
                .buttonStyle(.borderedProminent)
        case .starting, .pushing:
            Button("Annuler") { sync.cancel() }
        case .awaitingApproval(_, let url):
            Button("Rouvrir la page") { NSWorkspace.shared.open(url) }
            Button("Annuler") { sync.cancel() }
        case .done:
            Button("Fermer") { sync.dismiss() }
            Button("Ouvrir transcript.ekonum.fr") {
                NSWorkspace.shared.open(TranscriptSyncStore.serverURL)
            }
            .buttonStyle(.borderedProminent)
        case .failed:
            Button("Plus tard") { sync.dismiss() }
            Button("Réessayer") { sync.start() }
                .buttonStyle(.borderedProminent)
        }
    }

    private func summaryLine(already: Int, failed: Int) -> String {
        var parts: [String] = []
        if already > 0 { parts.append("\(already) déjà présente(s)") }
        if failed > 0 { parts.append("\(failed) en échec — relance plus tard") }
        parts.append("ta bibliothèque locale reste intacte")
        return parts.joined(separator: " · ")
    }
}
