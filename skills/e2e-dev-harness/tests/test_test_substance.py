"""Test-substance analyzer (Phase 0 link ③, implementation fidelity).

Detects empty-shell tests — the jeepay failure mode of an empty method paired
with a `assertDoesNotThrow`/no-assert test that is green but proves nothing.
Pure: source text in, [(test_name, verdict)] out. verdict ∈ empty|suspicious|ok.
"""
from e2e_harness.core import test_substance as ts


# --- Python -------------------------------------------------------------------

def test_python_no_assertion_is_empty():
    src = "def test_a():\n    do_something()\n"
    assert ts.analyze(src, "python") == [("test_a", "empty")]


def test_python_only_assert_true_is_empty():
    src = "def test_a():\n    assert True\n"
    assert ts.analyze(src, "python") == [("test_a", "empty")]


def test_python_pass_body_is_empty():
    src = "def test_a():\n    pass\n"
    assert ts.analyze(src, "python") == [("test_a", "empty")]


def test_python_real_assert_is_ok():
    src = "def test_a():\n    assert foo() == 3\n"
    assert ts.analyze(src, "python") == [("test_a", "ok")]


def test_python_assertion_method_call_is_ok():
    src = "class T:\n    def test_a(self):\n        self.assertEqual(foo(), 3)\n"
    assert ts.analyze(src, "python") == [("test_a", "ok")]


def test_python_only_is_not_none_is_suspicious():
    src = "def test_a():\n    assert foo() is not None\n"
    assert ts.analyze(src, "python") == [("test_a", "suspicious")]


def test_python_non_test_functions_are_ignored():
    src = "def helper():\n    pass\n\ndef test_a():\n    assert x == 1\n"
    assert ts.analyze(src, "python") == [("test_a", "ok")]


def test_python_unparseable_returns_empty_list():
    assert ts.analyze("def test_a(:\n  oops", "python") == []


def test_empties_helper_lists_only_empty_names():
    src = ("def test_a():\n    assert x == 1\n\n"
           "def test_b():\n    pass\n")
    assert ts.empties(src, "python") == ["test_b"]


# --- Java ---------------------------------------------------------------------

def test_java_assert_does_not_throw_empty_lambda_is_empty():
    src = ("@Test\n void freezes() {\n"
           "   assertDoesNotThrow(() -> {});\n }\n")
    assert ("freezes", "empty") in ts.analyze(src, "java")


def test_java_no_assertion_is_empty():
    src = "@Test\n void runs() {\n   service.call();\n }\n"
    assert ("runs", "empty") in ts.analyze(src, "java")


def test_java_real_assertion_is_ok():
    src = "@Test\n void adds() {\n   assertEquals(3, calc.add(1,2));\n }\n"
    assert ("adds", "ok") in ts.analyze(src, "java")


def test_java_verify_mock_is_ok():
    src = "@Test\n void persists() {\n   verify(repo).save(any());\n }\n"
    assert ("persists", "ok") in ts.analyze(src, "java")
