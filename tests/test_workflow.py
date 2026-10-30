"""Deployment entrypoint checks."""
from pathlib import Path
import unittest


class WorkflowTests(unittest.TestCase):
    def test_build_runs_as_module(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/pages.yml").read_text(encoding="utf-8")
        self.assertIn("run: python -m scripts.build", workflow)
        self.assertNotIn("run: python scripts/build.py", workflow)

    def test_cleanup_runs_after_build_and_before_publish(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/pages.yml").read_text(encoding="utf-8")
        build = workflow.split("\n  build:\n", 1)[1].split("\n  cleanup:\n", 1)[0]
        cleanup = workflow.split("\n  cleanup:\n", 1)[1].split("\n  publish:\n", 1)[0]
        publish = workflow.split("\n  publish:\n", 1)[1]
        self.assertIn("needs: build", cleanup)
        self.assertIn("needs: [build, cleanup]", publish)
        self.assertIn("deployments: write", cleanup)
        self.assertNotIn("write-all", cleanup)
        self.assertIn("onlyRemoveDeployments: true", cleanup)
        self.assertIn("environment: github-pages", cleanup)
        self.assertIn("uses: strumwolf/delete-deployment-environment@", cleanup)
        self.assertIn("name: github-pages", publish)
        self.assertIn("pages: write", publish)
        self.assertIn("id-token: write", publish)
        self.assertIn("actions/upload-pages-artifact@", build)
        self.assertIn("actions/deploy-pages@", publish)
        self.assertNotIn("actions/deploy-pages@", build)


if __name__ == "__main__":
    unittest.main()
