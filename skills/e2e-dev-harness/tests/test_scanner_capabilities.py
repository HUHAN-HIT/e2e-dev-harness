from e2e_harness.adapters.scanner import scan_frontend


def test_frontend_scanner_reports_component_only_capabilities(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.tsx").write_text("export default function App(){return null}")

    scope = scan_frontend(tmp_path)

    assert scope["scanner"] == "typescript-frontend"
    assert scope["capability"] == "component"
    assert scope["capabilities"]["component_scope"] is True
    assert scope["capabilities"]["dependency_graph"] is False
    assert "dependency graph not available" in scope["warnings"][0]
