import Darwin
import Foundation

@_silgen_name("launch_activate_socket")
func launchActivateSocket(
    _ name: UnsafePointer<CChar>,
    _ descriptors: UnsafeMutablePointer<UnsafeMutablePointer<Int32>?>,
    _ count: UnsafeMutablePointer<Int>
) -> Int32

struct SupervisorConfig: Decodable {
    let command: [String]
    let host: String
    let port: Int
    let idle_seconds_ac: Int
    let idle_seconds_battery: Int
    let log_path: String
    let events_path: String
}

struct Request: Decodable {
    let operation: String
    let run_id: String?
}

func executable(named name: String) -> String {
    URL(fileURLWithPath: CommandLine.arguments[0]).deletingLastPathComponent()
        .appendingPathComponent(name).path
}

func loadConfig() throws -> SupervisorConfig {
    let task = Process()
    task.executableURL = URL(fileURLWithPath: executable(named: "fresnel"))
    task.arguments = ["internal-supervisor-config"]
    let output = Pipe()
    task.standardOutput = output
    task.standardError = FileHandle.nullDevice
    try task.run()
    task.waitUntilExit()
    guard task.terminationStatus == 0 else { throw NSError(domain: "Fresnel", code: 2) }
    return try JSONDecoder().decode(
        SupervisorConfig.self,
        from: output.fileHandleForReading.readDataToEndOfFile()
    )
}

func memoryFreePercent() -> Int? {
    let task = Process()
    task.executableURL = URL(fileURLWithPath: "/usr/bin/memory_pressure")
    task.arguments = ["-Q"]
    let output = Pipe()
    task.standardOutput = output
    task.standardError = FileHandle.nullDevice
    do { try task.run() } catch { return nil }
    task.waitUntilExit()
    let text = String(data: output.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
    guard let range = text.range(of: #"free percentage:\s*(\d+)"#, options: .regularExpression)
    else { return nil }
    return Int(text[range].split(whereSeparator: { !$0.isNumber }).last ?? "")
}

func onBattery() -> Bool {
    let task = Process()
    task.executableURL = URL(fileURLWithPath: "/usr/bin/pmset")
    task.arguments = ["-g", "batt"]
    let output = Pipe()
    task.standardOutput = output
    task.standardError = FileHandle.nullDevice
    do { try task.run() } catch { return false }
    task.waitUntilExit()
    let text = String(data: output.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
    return text.contains("Battery Power")
}

func constrainedCommand(_ command: [String], eco: Bool) -> [String] {
    guard eco else { return command }
    var result = command
    for (flag, value) in [("--max-tokens", "2048"), ("--prompt-cache-bytes", "1073741824")] {
        if let index = result.firstIndex(of: flag), result.indices.contains(index + 1) {
            result[index + 1] = value
        }
    }
    return result
}

func healthy(_ config: SupervisorConfig) -> Bool {
    guard let url = URL(string: "http://\(config.host):\(config.port)/v1/models") else { return false }
    let semaphore = DispatchSemaphore(value: 0)
    var ok = false
    let task = URLSession.shared.dataTask(with: url) { _, response, _ in
        ok = (response as? HTTPURLResponse)?.statusCode == 200
        semaphore.signal()
    }
    task.resume()
    _ = semaphore.wait(timeout: .now() + 1)
    task.cancel()
    return ok
}

func response(_ value: [String: Any]) -> Data {
    (try? JSONSerialization.data(withJSONObject: value)) ?? Data("{\"ok\":false}\n".utf8)
}

func readRequest(_ descriptor: Int32) -> Request? {
    var data = Data()
    var byte: UInt8 = 0
    while read(descriptor, &byte, 1) == 1 && byte != 10 { data.append(byte) }
    return try? JSONDecoder().decode(Request.self, from: data)
}

func activate() throws -> Int32 {
    var descriptors: UnsafeMutablePointer<Int32>?
    var count = 0
    let error = "Control".withCString { name in
        launchActivateSocket(name, &descriptors, &count)
    }
    guard error == 0, count == 1, let descriptors else {
        throw NSError(domain: "Fresnel", code: Int(error))
    }
    let listener = dup(descriptors[0])
    _ = fcntl(listener, F_SETFL, O_NONBLOCK)
    return listener
}

if CommandLine.arguments.contains("--self-test") {
    let state: [String: Any] = [
        "ok": true,
        "architecture": "arm64",
        "memory_free_percent": memoryFreePercent() as Any,
        "low_power_mode": ProcessInfo.processInfo.isLowPowerModeEnabled,
        "thermal_state": ProcessInfo.processInfo.thermalState.rawValue,
    ]
    FileHandle.standardOutput.write(response(state))
    exit(0)
}

do {
    let config = try loadConfig()
    let listener = try activate()
    var worker: Process?
    var leases = Set<String>()
    var lastRelease = Date()
    var loadedAt: Date?
    var lastSample = Date.distantPast
    var sampledBattery = false
    var sampledFree: Int? = nil

    func record(_ event: [String: Any]) {
        var value = event
        value["timestamp"] = ISO8601DateFormatter().string(from: Date())
        guard var encoded = try? JSONSerialization.data(withJSONObject: value) else { return }
        encoded.append(10)
        let url = URL(fileURLWithPath: config.events_path)
        FileManager.default.createFile(atPath: url.path, contents: nil)
        guard let handle = try? FileHandle(forWritingTo: url) else { return }
        defer { try? handle.close() }
        do { try handle.seekToEnd(); try handle.write(contentsOf: encoded) } catch {}
    }

    func refreshTelemetry(force: Bool = false) {
        guard force || Date().timeIntervalSince(lastSample) >= 2 else { return }
        sampledBattery = onBattery()
        sampledFree = memoryFreePercent()
        lastSample = Date()
    }

    func stopWorker(reason: String) {
        guard let process = worker, process.isRunning else { worker = nil; return }
        let resident = loadedAt.map { Date().timeIntervalSince($0) } ?? 0
        process.terminate()
        let deadline = Date().addingTimeInterval(10)
        while process.isRunning && Date() < deadline { usleep(100_000) }
        if process.isRunning { kill(process.processIdentifier, SIGKILL) }
        worker = nil
        loadedAt = nil
        record([
            "event": "worker_unloaded", "reason": reason,
            "resident_seconds": resident, "memory_free_percent": sampledFree as Any,
        ])
    }

    while true {
        refreshTelemetry()
        let battery = sampledBattery
        let thermal = ProcessInfo.processInfo.thermalState
        let idleLimit = battery
            ? config.idle_seconds_battery : config.idle_seconds_ac
        let free = sampledFree
        if leases.isEmpty && worker != nil && Date().timeIntervalSince(lastRelease) >= Double(idleLimit) {
            stopWorker(reason: "idle_timeout")
        } else if leases.isEmpty && worker != nil && (free ?? 100) < 12 {
            stopWorker(reason: "critical_memory_pressure")
        }
        if leases.isEmpty && worker == nil && Date().timeIntervalSince(lastRelease) >= Double(max(5, idleLimit)) {
            break
        }
        let connection = accept(listener, nil, nil)
        if connection < 0 { usleep(100_000); continue }
        defer { close(connection) }
        guard let request = readRequest(connection) else {
            _ = response(["ok": false, "error": "invalid request"]).withUnsafeBytes {
                write(connection, $0.baseAddress, $0.count)
            }
            continue
        }
        var result: [String: Any]
        switch request.operation {
        case "acquire":
            if thermal == .critical {
                result = [
                    "ok": false,
                    "error": "macOS reports critical thermal pressure",
                    "recommendation": "let the Mac cool before loading Spark",
                ]
            } else if (free ?? 100) < 20 {
                result = [
                    "ok": false,
                    "error": "memory pressure is too high to load Spark",
                    "memory_free_percent": free as Any,
                    "recommendation": "close memory-heavy apps or select the eco profile",
                ]
            } else if let runID = request.run_id {
                var reused = true
                if worker == nil || !(worker?.isRunning ?? false) {
                    reused = false
                    let process = Process()
                    let command = constrainedCommand(config.command, eco: thermal == .serious)
                    process.executableURL = URL(fileURLWithPath: command[0])
                    process.arguments = Array(command.dropFirst())
                    let allowedEnvironment = Set([
                        "PATH", "HOME", "TMPDIR", "LANG", "LC_ALL",
                        "MLX_METAL_CACHE_DIR", "PYTHONUNBUFFERED",
                    ])
                    process.environment = ProcessInfo.processInfo.environment.filter {
                        allowedEnvironment.contains($0.key)
                    }
                    FileManager.default.createFile(atPath: config.log_path, contents: nil)
                    let log = try FileHandle(forWritingTo: URL(fileURLWithPath: config.log_path))
                    log.seekToEndOfFile()
                    process.standardOutput = log
                    process.standardError = log
                    try process.run()
                    worker = process
                    loadedAt = Date()
                    record([
                        "event": "worker_loaded", "effective_profile": thermal == .serious ? "eco" : "configured",
                        "power_source": battery ? "battery" : "ac", "memory_free_percent": free as Any,
                    ])
                    let deadline = Date().addingTimeInterval(180)
                    while Date() < deadline && process.isRunning && !healthy(config) { usleep(250_000) }
                }
                if healthy(config) {
                    leases.insert(runID)
                    record([
                        "event": "lease_acquired", "run_id": runID, "reused": reused,
                        "leases": leases.count,
                    ])
                    result = [
                        "ok": true, "state": "ready", "reused": reused,
                        "load_seconds": loadedAt.map { Date().timeIntervalSince($0) } ?? 0,
                        "leases": leases.count,
                        "effective_profile": thermal == .serious ? "eco" : "configured",
                        "power_source": battery ? "battery" : "ac",
                        "thermal_state": thermal.rawValue,
                        "memory_free_percent": free as Any,
                    ]
                } else {
                    result = ["ok": false, "error": "Spark failed to become healthy"]
                }
            } else { result = ["ok": false, "error": "run_id is required"] }
        case "release":
            if let runID = request.run_id {
                leases.remove(runID)
                record(["event": "lease_released", "run_id": runID, "leases": leases.count])
            }
            lastRelease = Date()
            result = ["ok": true, "leases": leases.count, "idle_seconds": idleLimit]
        case "status":
            result = [
                "ok": true, "state": worker?.isRunning == true ? "ready" : "idle",
                "leases": leases.count, "memory_free_percent": free as Any,
                "low_power_mode": ProcessInfo.processInfo.isLowPowerModeEnabled,
                "power_source": battery ? "battery" : "ac",
                "thermal_state": thermal.rawValue,
            ]
        default: result = ["ok": false, "error": "unknown operation"]
        }
        var encoded = response(result)
        encoded.append(10)
        _ = encoded.withUnsafeBytes { write(connection, $0.baseAddress, $0.count) }
    }
    stopWorker(reason: "supervisor_exit")
} catch {
    FileHandle.standardError.write(Data("fresnel-supervisor: \(error)\n".utf8))
    exit(1)
}
