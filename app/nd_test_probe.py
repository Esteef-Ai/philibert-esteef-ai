"""Run ONE test function and, when it fails, say what the data actually was.

Measured: told its test raised KeyError 'by_format', the model replaced that key
with 'formats' -- another guess -- and failed again. A traceback says which key
was missing. It never says which keys were THERE, so the model has nothing to
read and guesses twice.

This runs the function, and on failure walks back to the deepest frame that
belongs to the test file itself and reports the shape of what it was holding.
Nothing here may raise: a reporter that crashes turns a diagnosable failure into
a silent one.

    python nd_test_probe.py <dir> <module> <function> <test-file-path>

    exit 0  passed
    exit 1  failed (traceback and data shape on stdout)
    exit 3  no such function
"""
import sys
import traceback

MAX_KEYS = 24
MAX_LOCALS = 40
MAX_TEXT = 300


def describe(value):
    """One line about a value's SHAPE. Never raises, never dumps real volume."""
    try:
        if isinstance(value, dict):
            keys = [str(k) for k in list(value.keys())[:MAX_KEYS]]
            more = "" if len(value) <= MAX_KEYS else f" (+{len(value) - MAX_KEYS} more)"
            return "dict with keys " + repr(sorted(keys)) + more
        if isinstance(value, (list, tuple)):
            if value and isinstance(value[0], dict):
                keys = [str(k) for k in list(value[0].keys())[:MAX_KEYS]]
                return (f"{type(value).__name__} of {len(value)}, first item keys "
                        + repr(sorted(keys)))
            return f"{type(value).__name__} of {len(value)}"
        # A TestClient / requests response: the body is the interesting part.
        if hasattr(value, "status_code") and hasattr(value, "json"):
            try:
                body = value.json()
            except Exception:
                return f"response status {value.status_code}, body is not JSON"
            return f"response status {value.status_code}, body " + describe(body)
        if isinstance(value, (str, bytes)):
            return f"{type(value).__name__} {value[:MAX_TEXT]!r}"
        if isinstance(value, (int, float, bool)) or value is None:
            return repr(value)
        return type(value).__name__
    except Exception:
        return "<undescribable>"


def main():
    if len(sys.argv) < 5:
        print("usage: nd_test_probe.py <dir> <module> <function> <file>")
        return 3
    directory, module_name, func_name, test_file = sys.argv[1:5]
    sys.path.insert(0, directory)
    try:
        module = __import__(module_name)
    except BaseException:
        print("IMPORT FAILED")
        traceback.print_exc(file=sys.stdout)
        return 1
    fn = getattr(module, func_name, None)
    if fn is None:
        print(f"NO SUCH FUNCTION: {func_name}")
        return 3
    try:
        fn()
    except BaseException:
        traceback.print_exc(file=sys.stdout)
        try:
            tb = sys.exc_info()[2]
            frames = []
            while tb is not None:
                frames.append(tb.tb_frame)
                tb = tb.tb_next
            # The deepest frame belonging to the test file -- deeper than that is
            # library internals, which are not what the model got wrong.
            mine = [f for f in frames
                    if str(f.f_code.co_filename).lower() == str(test_file).lower()]
            frame = (mine or frames)[-1]
            rows = []
            for name, value in list(frame.f_locals.items())[:MAX_LOCALS]:
                if name.startswith("__"):
                    continue
                rows.append(f"  {name} = {describe(value)}")
            if rows:
                print()
                print("WHAT THE DATA ACTUALLY WAS, at the line that failed:")
                for r in rows:
                    print(r)
        except Exception:
            pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
