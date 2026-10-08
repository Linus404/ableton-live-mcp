autowatch = 1;
inlets = 1;
outlets = 3;

var isRecording = false;
var lastPath = "";
var commandFile = jsarguments.length > 1 ? String(jsarguments[1]) : "agent_audio_tap_command.json";
var lastCommandId = "";
var pollTask = null;
var startTask = null;
var stopTask = null;
var statusFile = jsarguments.length > 2 ? String(jsarguments[2]) : "";
var instanceId = jsarguments.length > 3 ? String(jsarguments[3]) : "";
var runtimeVersion = "audio-tap-2";
var state = "idle";
var stopReason = "";
var takeId = "";
var activeCommandId = "";

function loadbang() {
    start_polling();
}

function start_polling() {
    if (!pollTask) {
        pollTask = new Task(pollCommandFile, this);
        pollTask.interval = 100;
        pollTask.repeat();
    }
}

function pollCommandFile() {
    var file = new File(commandFile, "read");
    if (!file.isopen) {
        return;
    }

    var raw = file.readstring(65536);
    file.close();
    if (!raw) {
        return;
    }

    var command;
    try {
        command = JSON.parse(raw);
    } catch (err) {
        outlet(2, "error", "invalid_command_file", String(err));
        return;
    }

    var id = command.id || raw;
    if (id === lastCommandId) {
        return;
    }
    lastCommandId = id;
    dispatchCommand(command);
}

function dispatchCommand(command) {
    if (!instanceId) {
        handleCommand([command.command, command.path]);
        return;
    }
    if (!command.id || command.instance_id !== instanceId) {
        return;
    }
    activeCommandId = String(command.id);
    var action = command.command;
    if (action === "status") {
        report("status");
        return;
    }
    if (takeId && command.take_id !== takeId && (state === "starting" || isRecording || action === "stop")) {
        report("error", "take_mismatch");
        return;
    }
    if (action === "stop") {
        stopRecording();
        return;
    }
    if (action !== "start" && action !== "open") {
        report("error", "unknown_command");
        return;
    }
    if (state === "starting" || isRecording) {
        report("error", "take_active");
        return;
    }
    if (typeof command.path !== "string" || !command.path) {
        report("error", "missing_path");
        return;
    }
    var duration = Number(command.max_duration_seconds);
    if (action === "start" && (!command.take_id || !isFinite(duration) || duration <= 0 || duration > 86400)) {
        report("error", "invalid_take_or_duration");
        return;
    }
    var now = new Date().getTime();
    var expiry = Number(command.expires_at_unix_ms);
    var stopAt = Number(command.stop_at_unix_ms);
    if (action === "start" && (!isFinite(expiry) || !isFinite(stopAt) || expiry <= now || stopAt <= now || stopAt > now + duration * 1000)) {
        report("error", "expired_or_invalid_start");
        return;
    }
    takeId = command.take_id ? String(command.take_id) : "";
    openPath(command.path, action === "start");
    if (action === "start") {
        state = "starting";
        // This is command acceptance, not sfrecord~ readiness feedback.
        report("start");
        scheduleStartRecording();
        if (!stopTask) {
            stopTask = new Task(function () {
                stopRecording("max_duration");
            }, this);
        }
        stopTask.schedule(stopAt - now);
    }
}

function anything() {
    if (instanceId) { return; }
    var atoms = arrayfromargs(messagename, arguments);
    if (messagename === "/agent_audio_tap") {
        handleCommand(atoms.slice(1));
    } else {
        handle(atoms.join(" "));
    }
}

function list() {
    if (instanceId) { return; }
    handle(arrayfromargs(arguments).join(" "));
}

function msg_string(value) {
    if (instanceId) { return; }
    handle(value);
}

function handle(raw) {
    var command;

    if (raw === "start" || raw === "stop" || raw === "status") {
        handleCommand([raw]);
        return;
    }

    try {
        command = JSON.parse(raw);
    } catch (err) {
        outlet(2, "error", "invalid_json", String(err));
        return;
    }

    handleCommand([command.command, command.path]);
}

function handleCommand(parts) {
    var command = parts[0];
    var path = parts[1];

    if (!command) {
        outlet(2, "error", "missing_command");
        return;
    }

    if (command === "open") {
        openPath(path);
    } else if (command === "start") {
        if (path) {
            openPath(path);
            scheduleStartRecording();
            return;
        }
        startRecording();
    } else if (command === "stop") {
        stopRecording();
    } else if (command === "status") {
        report("status");
    } else {
        outlet(2, "error", "unknown_command", command);
    }
}

function scheduleStartRecording() {
    if (!startTask) {
        startTask = new Task(startRecording, this);
    }
    startTask.schedule(500);
}

function openPath(path, silent) {
    if (!path || typeof path !== "string") {
        outlet(2, "error", "missing_path");
        return;
    }
    lastPath = path;
    state = "open";
    stopReason = "";
    outlet(0, "open", path, "wave");
    if (!silent) { report("open"); }
}

function startRecording() {
    if (!lastPath) {
        outlet(2, "error", "no_output_path");
        return;
    }
    isRecording = true;
    state = "recording";
    outlet(0, 1);
    // Keep the durable command ack intact; status can observe this transition.
    if (!instanceId) { report("start"); }
}

function stopRecording(reason) {
    if (startTask) { startTask.cancel(); }
    if (stopTask) { stopTask.cancel(); }
    isRecording = false;
    state = "stopped";
    stopReason = reason || "stop";
    outlet(0, 0);
    // Watchdog transitions are observed with status, never overwrite a command ack.
    if (reason !== "max_duration") { report("stop"); }
}

function baselineCommandFile() {
    if (!instanceId) { return; }
    // JS reload loses ownership state: stop instead of leaving a prior take running.
    outlet(0, 0);
    var file = new File(commandFile, "read");
    if (!file.isopen) { return; }
    var raw = file.readstring(65536);
    file.close();
    try {
        var command = JSON.parse(raw);
        lastCommandId = command.id || raw;
    } catch (err) {}
}

// Fresh commands must be written after load; reload must not replay a stale start.
baselineCommandFile();

function notifydeleted() {
    if (pollTask) { pollTask.cancel(); }
    if (startTask) { startTask.cancel(); }
    if (stopTask) { stopTask.cancel(); }
    if (instanceId) { outlet(0, 0); }
}

function report(eventName, error) {
    var status = {
        event: eventName,
        recording: isRecording,
        path: lastPath
    };
    if (instanceId) {
        status.command_id = activeCommandId;
        status.instance_id = instanceId;
        status.take_id = takeId;
        status.state = state;
        status.reason = stopReason;
        status.runtime_version = runtimeVersion;
        status.command_only = true;
        if (error) { status.error = error; }
        var file = new File(statusFile, "write");
        if (file.isopen) {
            file.eof = 0;
            file.writestring(JSON.stringify(status));
            file.close();
        }
    } else {
        outlet(1, JSON.stringify(status));
    }
}
