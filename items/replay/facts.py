"""Three-valued display facts: unavailable evidence is unknown, never false."""
PREDICATES = {"capture_contains", "capture_not_contains", "capture_lines_in_order", "size",
              "status_state", "process_running", "child_exit_code", "mode_enabled"}


def validate(facts):
    if not isinstance(facts, list) or len(facts) > 512:
        raise ValueError("invalid_facts")
    for fact in facts:
        if not isinstance(fact, dict) or not isinstance(fact.get("id"), str):
            raise ValueError("invalid_fact")
        keys = set(fact) & PREDICATES
        if len(keys) != 1 or set(fact) - PREDICATES - {"id", "status_id"}:
            raise ValueError("invalid_fact_predicate")
        key = next(iter(keys))
        value = fact[key]
        valid = (isinstance(value, str) if key in {"capture_contains", "capture_not_contains", "status_state", "mode_enabled"}
                 else isinstance(value, bool) if key == "process_running"
                 else type(value) is int if key == "child_exit_code"
                 else isinstance(value, list) and all(isinstance(x, str) for x in value) if key == "capture_lines_in_order"
                 else isinstance(value, dict) and set(value) == {"columns", "rows"} and all(type(x) is int and 1 <= x <= 65535 for x in value.values()))
        if not valid:
            raise ValueError("invalid_fact_value")


def evaluate(facts, observation, size=None, modes=None, exit_code=None):
    validate(facts)
    capture = observation.get("capture", {})
    text = capture.get("content")
    complete = capture.get("complete") is True
    results = []
    for fact in facts:
        key = next(iter(set(fact) & PREDICATES))
        expected = fact[key]
        value = None
        if key == "capture_contains" and isinstance(text, str):
            value = True if expected in text else False if complete else None
        elif key == "capture_not_contains" and isinstance(text, str) and complete:
            value = expected not in text
        elif key == "capture_lines_in_order" and isinstance(text, str):
            offset = 0
            found = True
            for line in expected:
                index = text.find(line, offset)
                if index == -1:
                    found = False
                    break
                offset = index + len(line)
            value = True if found else False if complete else None
        elif key == "size" and size is not None:
            value = all(size.get(k) == v for k, v in expected.items())
        elif key == "status_state":
            records = observation.get("program_status", {}).get("data", {}).get("records", [])
            record = next((r for r in records if r.get("id") == fact.get("status_id")), None)
            if record is not None:
                value = record.get("state") == expected
        elif key == "process_running":
            foreground = observation.get("process", {}).get("data", {}).get("foreground")
            if foreground:
                value = expected is True
            # Missing foreground alone is not proof of exit.
            elif exit_code is not None:
                value = expected is False
        elif key == "child_exit_code" and exit_code is not None:
            value = exit_code == expected
        elif key == "mode_enabled" and modes is not None:
            records = modes.get("modes", [])
            record = next((r for r in records if r.get("name") == expected), None)
            if record is not None:
                value = record.get("set")
        results.append(dict(id=fact["id"], value="unknown" if value is None else value,
                            reason="evidence_unavailable_or_incomplete" if value is None else "predicate_evaluated"))
    return results
