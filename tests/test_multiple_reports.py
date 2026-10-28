import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class MultipleReportsTest(unittest.TestCase):
    def test_same_ticker_has_distinct_urls_and_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            for directory in ('reports', 'sources', 'assets'):
                (site / directory).mkdir()
            shutil.copy(ROOT / 'sync_site.py', site)
            shutil.copy(ROOT / 'index.html', site)
            sample = (ROOT / 'reports' / 'ADEA.html').read_text()
            dates = ['2026-10-01', '2026-11-02']
            names = [f'ADEA_EOIC_{date}.html' for date in dates]
            for date, name in zip(dates, names):
                report = re.sub(r'(<div class="deadline">資訊截止日\s*)[^<]+', r'\g<1>' + date, sample, count=1)
                (site / 'reports' / name).write_text(report)
                (site / 'sources' / f'ADEA_EOIC_{date}.md').write_text(date)
            subprocess.run(['python3', str(site / 'sync_site.py')], check=True, capture_output=True)
            index = (site / 'index.html').read_text()
            feed = (site / 'feed.xml').read_text()
            data = json.loads((site / 'assets' / 'search-index.js').read_text().split(' = ', 1)[1].rstrip(';\n'))
            self.assertEqual({entry['url'] for entry in data}, {f'reports/{n}' for n in names})
            for date, name in zip(dates, names):
                self.assertIn(f'href="reports/{name}"', index)
                self.assertIn(f'sources/ADEA_EOIC_{date}.md', index)
                self.assertIn(f'/reports/{name}', feed)
                report = (site / 'reports' / name).read_text()
                self.assertIn(f'href="../sources/ADEA_EOIC_{date}.md"', report)
                current = re.findall(r'<a class="side-report-link"[^>]*aria-current="page"', report)
                self.assertEqual(len(current), 1)
                self.assertIn(name, current[0])
            self.assertIn(names[1], (site / 'reports' / names[0]).read_text())
            self.assertIn(names[0], (site / 'reports' / names[1]).read_text())

if __name__ == '__main__': unittest.main()
