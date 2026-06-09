from e2e_harness.adapters.scanner import scan_frontend


def test_frontend_scan_lists_components(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.tsx").write_text("export default function App(){return null}")
    scope = scan_frontend(tmp_path)
    assert scope["schema"].startswith("scanner-scope")
    assert any("App" in c for c in scope["components"])
    assert scope["dependencies"] == []
