from e2e_harness.core import test_substance as ts


def test_javascript_empty_test_is_empty():
    src = "test('renders empty state', () => {})"
    assert ts.analyze(src, "javascript") == [("renders empty state", "empty")]


def test_typescript_vitest_expect_to_equal_is_ok():
    src = "it('adds', () => { expect(add(1, 2)).toEqual(3) })"
    assert ts.analyze(src, "typescript") == [("adds", "ok")]


def test_weak_assertion_stays_suspicious_only_when_strongest_signal():
    weak = "test('exists', () => { expect(value).toBeDefined() })"
    strong = "test('exists', () => { expect(value).toBeDefined(); expect(value).toBe(3) })"

    assert ts.analyze(weak, "typescript") == [("exists", "suspicious")]
    assert ts.analyze(strong, "typescript") == [("exists", "ok")]


def test_react_testing_library_query_semantics():
    src = """
    it('shows empty copy', () => { screen.getByText('No records') })
    it('waits for empty copy', async () => { await screen.findByRole('status') })
    it('bare query is weak', () => { screen.queryByText('No records') })
    it('negative query is strong', () => {
      expect(screen.queryByText('Spinner')).toBeNull()
    })
    """

    assert ts.analyze(src, "typescript") == [
        ("shows empty copy", "ok"),
        ("waits for empty copy", "ok"),
        ("bare query is weak", "empty"),
        ("negative query is strong", "ok"),
    ]


def test_unparseable_supported_javascript_reports_warning_but_legacy_analyze_is_empty():
    src = "test('broken', () => { expect(value).toBe(1)"

    diag = ts.analyze_with_diagnostics(src, "javascript")

    assert ts.analyze(src, "javascript") == []
    assert diag["verdicts"] == []
    assert diag["warnings"][0]["code"] == "analyzer-limitation"
    assert diag["warnings"][0]["line"] == 1
