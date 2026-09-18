def test_package_imports():
    import gibhub

    assert gibhub is not None


def test_recorded_fixtures_carry_no_server_credentials():
    """Fixtures are committed, so a gather's address and password must not be."""
    import glob
    import json

    def walk(node, path=""):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("ip", "pw") and value not in (None, "", "REDACTED"):
                    yield "%s.%s = %r" % (path, key, value)
                for found in walk(value, path + "." + key):
                    yield found
        elif isinstance(node, list):
            for item in node:
                for found in walk(item, path + "[]"):
                    yield found

    leaks = []
    for name in glob.glob("tests/fixtures/*.json"):
        leaks += ["%s%s" % (name, f) for f in walk(json.load(open(name)))]
    assert leaks == [], "server credentials in committed fixtures: %s" % leaks
