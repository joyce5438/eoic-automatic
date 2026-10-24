"""Guard shared theme precedence without changing uploaded report content."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sync_site


class SharedThemeTests(unittest.TestCase):
    def test_uploaded_reports_keep_content_and_shared_theme_wins(self):
        root = sync_site.SITE_DIR
        cache = sync_site.load_existing_index_cache(root / 'index.html')
        reports = [sync_site.parse_report(p, cache) for p in sorted((root / 'reports').glob('*.html'))]
        self.assertTrue(reports)
        for report in reports:
            with self.subTest(report=report['code']):
                original = report['path'].read_text(encoding='utf-8')
                sidebar = re.search(r'<aside id="site-sidebar" class="site-sidebar">.*?</aside>', original, re.S).group()
                updated = sync_site.update_report_html(original, report, reports, None, None, sidebar)
                shared_link = '<link rel="stylesheet" href="../assets/site.css">'
                self.assertEqual(updated.count(shared_link), 1)
                self.assertGreater(updated.index(shared_link), updated.rfind('</style>'))
                self.assertLess(updated.index(shared_link), updated.index('</head>'))
                for pattern in [r'<main id="main" class="prose">.*?</main>', r'<h1>.*?</h1>', r'<aside class="hero-verdict">.*?</aside>']:
                    self.assertEqual(re.search(pattern, original, re.S).group(), re.search(pattern, updated, re.S).group())
                self.assertEqual(updated, sync_site.update_report_html(updated, report, reports, None, None, sidebar))


if __name__ == '__main__':
    unittest.main()
