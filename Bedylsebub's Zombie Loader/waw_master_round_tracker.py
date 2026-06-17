import json
import os
import time
import pymem
import psutil


PROCESS_NAME = "CoDWaW.exe"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(BASE_DIR, "waw_round_tracker.json")
CURRENT_MAP_FILE = os.path.join(BASE_DIR, "waw_current_map.json")

print(f"Writing rounds to: {OUTPUT_FILE}")


STABLE_ROUND_ADDRESSES = {
    "Nacht der Untoten": 0x0094EC30,
}

DYNAMIC_MAPS = {
    "Shi No Numa",
    "Der Riese",
    "Verruckt",
}


MAP_STRING_SIGNATURES = {
    "Nacht der Untoten": b"nazi_zombie_prototype",
    "Verruckt": b"nazi_zombie_asylum",
    "Shi No Numa": b"nazi_zombie_sumpf",
    "Der Riese": b"nazi_zombie_factory",
}

SCAN_START = 0x03900000
SCAN_END = 0x03B00000

MAP_SCAN_START = 0x00000000
MAP_SCAN_END = 0x7FFFFFFF

CHUNK_SIZE = 0x10000


STARTING_ROUND = 1
MAX_REASONABLE_ROUND = 255

POLL_INTERVAL = 1
LOCK_SCORE_REQUIRED = 12
MIN_ROUND_TO_LOCK = 3
MIN_SECONDS_BETWEEN_ROUND_INCREASES = 20
MIN_STABLE_SECONDS_BEFORE_LOCK = 10
BAD_LOCK_READS_ALLOWED = 5


class Candidate:
    def __init__(self, address, value):
        self.address = address
        self.last_value = value
        self.current_value = value
        self.score = 0
        self.stable_seconds = 0
        self.highest_seen = value
        self.bad = False
        self.increase_count = 0
        self.last_increase_time = None

    def update(self, value):
        if value is None:
            self.score -= 3
            if self.score < -10:
                self.bad = True
            return

        self.last_value = self.current_value
        self.current_value = value

        if not (1 <= value <= MAX_REASONABLE_ROUND):
            self.score -= 8
            self.bad = True
            return

        if value == self.last_value:
            self.stable_seconds += POLL_INTERVAL
            return

        self.stable_seconds = 0

        if value == self.last_value + 1:
            now = time.time()

            if self.last_increase_time is not None:
                seconds_since_last_increase = now - self.last_increase_time

                if seconds_since_last_increase < MIN_SECONDS_BETWEEN_ROUND_INCREASES:
                    self.score -= 10
                    self.bad = True
                    return

            self.last_increase_time = now
            self.score += 6
            self.increase_count += 1
            self.highest_seen = max(self.highest_seen, value)
            return

        self.score -= 8
        self.bad = True


def is_process_running():
    for process in psutil.process_iter(["name"]):
        try:
            if process.info["name"] and process.info["name"].lower() == PROCESS_NAME.lower():
                return True
        except Exception:
            pass

    return False


def wait_for_waw():
    print("Waiting for CoDWaW.exe...")

    while True:
        try:
            pm = pymem.Pymem(PROCESS_NAME)
            print("Attached to CoDWaW.exe")
            return pm
        except Exception:
            time.sleep(1)


def read_int_safe(pm, address):
    try:
        return pm.read_int(address)
    except Exception:
        return None


def load_rounds():
    if not os.path.exists(OUTPUT_FILE):
        return {}

    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        return data if isinstance(data, dict) else {}

    except Exception:
        return {}


def save_rounds(data):
    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4)

        print(f"Saved tracker JSON to: {OUTPUT_FILE}")
        return True

    except Exception as error:
        print(f"Could not save tracker JSON: {error}")
        return False


def save_highest(map_name, round_number):
    if not map_name:
        return

    rounds = load_rounds()
    old_round = int(rounds.get(map_name, 0))

    if round_number > old_round:
        rounds[map_name] = round_number
        save_rounds(rounds)
        print(f"Saved new {map_name} highest round: {round_number}")
    else:
        print(f"{map_name} detected round {round_number}. Saved highest remains {old_round}.")


def count_memory_string(pm, target_bytes):
    count = 0
    address = MAP_SCAN_START

    while address < MAP_SCAN_END:
        try:
            chunk = pm.read_bytes(address, CHUNK_SIZE)
        except Exception:
            address += CHUNK_SIZE
            continue

        index = chunk.find(target_bytes)

        while index != -1:
            count += 1
            index = chunk.find(target_bytes, index + 1)

        address += CHUNK_SIZE

    return count


def get_map_signature_counts(pm):
    counts = {}

    for map_name, signature in MAP_STRING_SIGNATURES.items():
        counts[map_name] = count_memory_string(pm, signature)

    return counts


def detect_current_map_from_memory(pm):
    counts = get_map_signature_counts(pm)

    prototype = counts.get("Nacht der Untoten", 0)
    asylum = counts.get("Verruckt", 0)
    sumpf = counts.get("Shi No Numa", 0)
    factory = counts.get("Der Riese", 0)

    print("\nMap signature counts:")
    print(f"Nacht der Untoten: {prototype}")
    print(f"Verruckt: {asylum}")
    print(f"Shi No Numa: {sumpf}")
    print(f"Der Riese: {factory}")

    if sumpf > 500:
        return "Shi No Numa", counts

    if factory > 200 and sumpf > 200:
        return "Der Riese", counts

    if asylum > 150:
        return "Verruckt", counts

    if prototype > 170:
        return "Nacht der Untoten", counts

    return "", counts


def wait_for_supported_map(pm):
    print("Detecting current WaW map from memory...")

    while True:
        if not is_process_running():
            return ""

        current_map, counts = detect_current_map_from_memory(pm)

        if current_map in STABLE_ROUND_ADDRESSES or current_map in DYNAMIC_MAPS:
            print(f"Detected current WaW map: {current_map}")
            return current_map

        print("Could not confidently detect map yet. Retrying in 5 seconds...")
        time.sleep(5)


def map_changed(pm, expected_map):
    detected_map, counts = detect_current_map_from_memory(pm)

    if not detected_map:
        return False

    return detected_map != expected_map


def scan_for_value(pm, target_value):
    print(f"Scanning memory for value {target_value}...")

    matches = []
    failed_chunks = 0
    readable_chunks = 0
    target_bytes = int(target_value).to_bytes(4, byteorder="little", signed=True)

    address = SCAN_START

    while address < SCAN_END:
        if not is_process_running():
            print("WaW closed during memory scan.")
            return None

        try:
            chunk = pm.read_bytes(address, CHUNK_SIZE)
            readable_chunks += 1
        except Exception:
            failed_chunks += 1
            address += CHUNK_SIZE
            continue

        index = chunk.find(target_bytes)

        while index != -1:
            found_address = address + index

            if found_address % 4 == 0:
                matches.append(found_address)

            index = chunk.find(target_bytes, index + 4)

        address += CHUNK_SIZE

    if readable_chunks == 0:
        print("No readable memory chunks. WaW may have closed or unloaded.")
        return None

    print(f"Initial candidates found: {len(matches)}")
    return matches


def print_top_candidates(candidates):
    alive = [candidate for candidate in candidates.values() if not candidate.bad]
    alive.sort(key=lambda c: c.score, reverse=True)

    print("\nTop candidates:")
    for candidate in alive[:10]:
        print(
            f"0x{candidate.address:08X} | "
            f"value={candidate.current_value} | "
            f"score={candidate.score} | "
            f"increases={candidate.increase_count} | "
            f"stable={candidate.stable_seconds}s | "
            f"highest={candidate.highest_seen}"
        )

    print(f"Alive candidates: {len(alive)}\n")


def calibrate_dynamic_address(pm, map_name):
    print(f"Dynamic calibration started for {map_name}.")
    print("Waiting 8 seconds before scanning for Round 1...")
    time.sleep(8)

    detected_map, counts = detect_current_map_from_memory(pm)

    if detected_map and detected_map != map_name:
        print(f"Map changed during calibration: {map_name} -> {detected_map}")
        return None, 0, "map_changed"

    initial_addresses = scan_for_value(pm, STARTING_ROUND)

    if initial_addresses is None:
        return None, 0, "map_changed"

    candidates = {}

    for address in initial_addresses:
        value = read_int_safe(pm, address)

        if value == STARTING_ROUND:
            candidates[address] = Candidate(address, value)

    print(f"Stable starting candidates: {len(candidates)}")
    print("Play normally. Waiting for reliable 1 -> 2 -> 3 pattern.")

    last_debug_print = time.time()
    last_map_check = time.time()

    while True:
        if not is_process_running():
            return None, 0, "process_closed"

        if time.time() - last_map_check >= 10:
            detected_map, counts = detect_current_map_from_memory(pm)
            last_map_check = time.time()

            if detected_map and detected_map != map_name:
                print(f"Map changed during calibration: {map_name} -> {detected_map}")
                return None, 0, "map_changed"

        for address, candidate in list(candidates.items()):
            value = read_int_safe(pm, address)
            candidate.update(value)

            if candidate.bad:
                continue

            if (
                candidate.score >= LOCK_SCORE_REQUIRED
                and candidate.highest_seen >= MIN_ROUND_TO_LOCK
                and candidate.increase_count >= 2
                and candidate.current_value == candidate.highest_seen
                and candidate.stable_seconds >= MIN_STABLE_SECONDS_BEFORE_LOCK
            ):
                print(f"LOCKED {map_name} address: 0x{candidate.address:08X}")
                return candidate.address, candidate.highest_seen, "locked"

        candidates = {
            address: candidate
            for address, candidate in candidates.items()
            if not candidate.bad
        }

        if time.time() - last_debug_print >= 10:
            print_top_candidates(candidates)
            last_debug_print = time.time()

        if not candidates:
            print("No candidates left. Going back to map detection.")
            return None, 0, "map_changed"

        time.sleep(POLL_INTERVAL)


def locked_value_is_bad(value, last_round, session_highest):
    if value is None:
        return True

    if not (1 <= value <= MAX_REASONABLE_ROUND):
        return True

    if session_highest >= 3 and value < last_round:
        return True

    if value > last_round + 1:
        return True

    return False


def track_dynamic_map(pm, map_name):
    locked_address, starting_round, status = calibrate_dynamic_address(pm, map_name)

    if status != "locked":
        return status

    print(f"Memory-only dynamic tracking started for {map_name}.")

    session_highest = starting_round
    last_round = starting_round
    bad_reads = 0
    last_map_check = time.time()

    if session_highest > 0:
        save_highest(map_name, session_highest)

    while True:
        if not is_process_running():
            return "process_closed"

        if time.time() - last_map_check >= 10:
            detected_map, counts = detect_current_map_from_memory(pm)
            last_map_check = time.time()

            if detected_map and detected_map != map_name:
                print(f"Map changed away from {map_name}: now {detected_map}")
                return "map_changed"

        value = read_int_safe(pm, locked_address)

        if locked_value_is_bad(value, last_round, session_highest):
            bad_reads += 1
            print(f"Bad locked read {bad_reads}/{BAD_LOCK_READS_ALLOWED}: {value}")

            if bad_reads >= BAD_LOCK_READS_ALLOWED:
                print("Match ended or address went stale. Recalibrating.")
                return "recalibrate"

            time.sleep(POLL_INTERVAL)
            continue

        bad_reads = 0

        if value > session_highest:
            session_highest = value
            save_highest(map_name, session_highest)

        last_round = value

        print(f"{map_name} Round: {value} | Session best: {session_highest}")
        time.sleep(POLL_INTERVAL)


def track_stable_map(pm, map_name):
    address = STABLE_ROUND_ADDRESSES[map_name]
    print(f"Stable tracking started for {map_name} at 0x{address:08X}")

    session_highest = 0
    bad_reads = 0
    last_map_check = time.time()

    while True:
        if not is_process_running():
            return "process_closed"

        if time.time() - last_map_check >= 10:
            detected_map, counts = detect_current_map_from_memory(pm)
            last_map_check = time.time()

            if detected_map and detected_map != map_name:
                print(f"Map changed away from {map_name}: now {detected_map}")
                return "map_changed"

        value = read_int_safe(pm, address)

        if value is None or not (1 <= value <= MAX_REASONABLE_ROUND):
            bad_reads += 1
            print(f"Bad stable read {bad_reads}/{BAD_LOCK_READS_ALLOWED}: {value}")

            if bad_reads >= BAD_LOCK_READS_ALLOWED:
                print("Stable map address went stale. Retrying.")
                return "recalibrate"

            time.sleep(POLL_INTERVAL)
            continue

        bad_reads = 0

        if value > session_highest:
            session_highest = value
            save_highest(map_name, session_highest)

        print(f"{map_name} Round: {value} | Session best: {session_highest}")
        time.sleep(POLL_INTERVAL)


def main():
    pm = wait_for_waw()

    while True:
        if not is_process_running():
            print("WaW closed.")
            break

        current_map = wait_for_supported_map(pm)

        if not current_map:
            print("No current map detected.")
            break

        if current_map in STABLE_ROUND_ADDRESSES:
            result = track_stable_map(pm, current_map)

        elif current_map in DYNAMIC_MAPS:
            result = track_dynamic_map(pm, current_map)

        else:
            result = "map_changed"

        if result == "process_closed":
            print("Tracker stopped because WaW closed.")
            break

        if result in ["map_changed", "recalibrate", "failed"]:
            print("Resetting tracker state...")
            time.sleep(3)
            continue


if __name__ == "__main__":
    main()