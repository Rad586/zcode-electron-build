"""Check noise and regression gates with synthetic measurement distributions."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('comparison', Path(__file__).with_name('compare-kernel.py'))
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)


def runs(svg, paint, mad=0.01):
    return [{'scenarios': {name: {'wallMs': {'median': value, 'relativeMad': mad}}
                           for name, value in [('svg', a), ('paint', b)]}}
            for a, b in zip(svg, paint)]


class ComparisonTests(unittest.TestCase):
    def test_consistent_gain(self):
        result = comparison.compare(runs([100, 102, 98], [200, 204, 196]),
                                    runs([60, 62, 58], [196, 198, 194]))
        self.assertAlmostEqual(result['svg']['gain'], 0.4)
        comparison.accept(result)

    def test_noisy_gain_rejected(self):
        result = comparison.compare(runs([100, 140, 60], [200, 204, 196]),
                                    runs([80, 82, 78], [196, 198, 194]))
        with self.assertRaisesRegex(RuntimeError, 'noise'):
            comparison.accept(result)

    def test_regression_rejected(self):
        result = comparison.compare(runs([100] * 3, [200] * 3),
                                    runs([60] * 3, [240] * 3))
        with self.assertRaisesRegex(RuntimeError, 'regression: paint'):
            comparison.accept(result)

    def test_required_direction(self):
        result = comparison.compare(runs([100] * 3, [200] * 3),
                                    runs([99] * 3, [120] * 3))
        comparison.accept(result, 'paint')
        with self.assertRaisesRegex(RuntimeError, 'threshold'):
            comparison.accept(result)

    def test_existing_patch_only_checks_regressions(self):
        result = comparison.compare(runs([100] * 3, [200] * 3),
                                    runs([99] * 3, [200] * 3))
        comparison.accept(result, None)
        result['paint']['gain'] = -0.2
        with self.assertRaisesRegex(RuntimeError, 'regression: paint'):
            comparison.accept(result, None)

    def test_each_round_must_pass(self):
        result = comparison.compare(runs([100] * 3, [200] * 3),
                                    runs([60, 60, 99], [200] * 3))
        self.assertAlmostEqual(result['svg']['gain'], 0.4)
        with self.assertRaisesRegex(RuntimeError, 'round 3'):
            comparison.accept(result)

    def test_each_round_noise_applies(self):
        before = runs([100] * 3, [200] * 3)
        after = runs([60] * 3, [200] * 3)
        after[2]['scenarios']['svg']['wallMs']['relativeMad'] = 0.3
        result = comparison.compare(before, after)
        self.assertAlmostEqual(result['svg']['noise'], 0.01)
        with self.assertRaisesRegex(RuntimeError, 'round 3'):
            comparison.accept(result)

    def test_each_round_regression_applies(self):
        result = comparison.compare(runs([100] * 3, [200] * 3),
                                    runs([60] * 3, [200, 200, 240]))
        self.assertEqual(result['paint']['gain'], 0)
        with self.assertRaisesRegex(RuntimeError, 'regression: paint round 3'):
            comparison.accept(result)
        with self.assertRaisesRegex(RuntimeError, 'regression: paint round 3'):
            comparison.accept(result, None)

    def test_mismatched_rounds_rejected(self):
        with self.assertRaises(ValueError):
            comparison.compare(runs([100] * 3, [200] * 3), runs([60], [200]))

    def test_small_gain_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'threshold'):
            comparison.accept(comparison.compare(runs([100] * 3, [200] * 3),
                                                 runs([97] * 3, [200] * 3)))


if __name__ == '__main__':
    unittest.main()
