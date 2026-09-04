import Foundation

struct Run: Decodable {
    let id: String
    let status: String
    let request: String
}

struct Dashboard: Decodable {
    let healthy: Bool
    let worker: String
    let chip: String
    let memory_free_percent: Int?
    let profile: String
    let personalization: Bool
    let runs: [Run]
}

func paint(_ value: String, _ code: String, enabled: Bool) -> String {
    enabled ? "\u{001B}[\(code)m\(value)\u{001B}[0m" : value
}

func clipped(_ value: String, _ width: Int) -> String {
    if value.count <= width { return value }
    return String(value.prefix(max(1, width - 1))) + "…"
}

let data = FileHandle.standardInput.readDataToEndOfFile()
guard CommandLine.arguments.dropFirst().first == "dashboard",
      let model = try? JSONDecoder().decode(Dashboard.self, from: data) else {
    FileHandle.standardError.write(Data("fresnel-ui: invalid dashboard input\n".utf8))
    exit(2)
}

let environment = ProcessInfo.processInfo.environment
let color = environment["NO_COLOR"] == nil && environment["TERM"] != "dumb"
let columns = max(36, min(100, Int(environment["COLUMNS"] ?? "80") ?? 80))
let inside = columns - 2
let cyan = color ? "\u{001B}[36m" : ""
let reset = color ? "\u{001B}[0m" : ""
print("\(cyan)╭" + String(repeating: "─", count: inside) + "╮\(reset)")
let heading = clipped("  FRESNEL  ·  local implementation control plane", inside)
print("\(cyan)│\(reset)" + heading.padding(toLength: inside, withPad: " ", startingAt: 0) + "\(cyan)│\(reset)")
print("\(cyan)╰" + String(repeating: "─", count: inside) + "╯\(reset)")
let dot = paint("●", model.healthy ? "32" : "31", enabled: color)
let memory = model.memory_free_percent.map { "\($0)% memory free" } ?? "memory unknown"
print("\n  \(dot) " + (model.healthy ? "Healthy" : "Needs attention") + "  ·  worker \(model.worker)")
print("  \(clipped(model.chip, 42))  ·  \(memory)  ·  \(model.profile)")
print("  Personalization  " + (model.personalization ? "local inference on" : "explicit facts only"))
if !model.runs.isEmpty {
    print("\n  RECENT TASKS")
    for run in model.runs {
        let id = String(run.id.prefix(8))
        let status = run.status.padding(toLength: 18, withPad: " ", startingAt: 0)
        print("  \(id)  \(status)  \(clipped(run.request, max(12, columns - 34)))")
    }
}
print("\n  Ask locally     fresnel ask \"Explain this project\"")
print("  Delegate        fresnel run --repo . --plan plan.json")
print("  Diagnose        fresnel doctor\n")
