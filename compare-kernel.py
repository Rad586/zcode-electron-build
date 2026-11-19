"""Measure isolated alternating runtime pairs before accepting kernel changes."""
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def summarize(runs):
    names = runs[0]['scenarios']
    result = {}
    for name in names:
        values = [run['scenarios'][name]['wallMs']['median'] for run in runs]
        mid = statistics.median(values)
        within = statistics.median(run['scenarios'][name]['wallMs']['relativeMad'] for run in runs)
        between = statistics.median(abs(value - mid) for value in values) / mid if mid else 0
        result[name] = {'medianMs': mid, 'relativeMad': max(within, between), 'pairMediansMs': values}
    return result


def compare(before, after):
    left, right = summarize(before), summarize(after)
    return {name: {'before': left[name], 'after': right[name],
                   'gain': 1 - right[name]['medianMs'] / left[name]['medianMs'],
                   'noise': max(left[name]['relativeMad'], right[name]['relativeMad'])}
            for name in left}


def accept(comparison, required='svg'):
    if required is not None:
        target = comparison[required]
        if target['gain'] <= max(0.05, 2 * target['noise']):
            raise RuntimeError(required + ' gain does not exceed the acceptance threshold and measured noise')
    for name, row in comparison.items():
        if row['gain'] < -max(0.1, 2 * row['noise']):
            raise RuntimeError('Measured regression: ' + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', default='svg,paint')
    parser.add_argument('--require', default='svg')
    parser.add_argument('--regression-only', action='store_true')
    args = parser.parse_args()
    if not args.regression_only and args.require not in args.cases.split(','):
        parser.error('--require must be included in --cases')
    if args.output.exists():
        raise FileExistsError(args.output)
    runs = {'before': [], 'after': []}
    with tempfile.TemporaryDirectory(prefix='kernel-pairs-', dir=args.output.parent) as work:
        for pair in range(3):
            for label in (('before', 'after') if pair % 2 == 0 else ('after', 'before')):
                prefix = Path(work) / f'{pair}-{label}'
                output = prefix.with_suffix('.json')
                env = dict(os.environ, ZCODE_BENCH_OUTPUT=str(output),
                           ZCODE_BENCH_PROFILE=str(prefix), ZCODE_BENCH_SAMPLES='9',
                           ZCODE_BENCH_CASES=args.cases)
                env.pop('ELECTRON_RUN_AS_NODE', None)
                result = subprocess.run([str(getattr(args, label)), str(HERE / 'benchmark-kernel.cjs')],
                                        env=env, capture_output=True, text=True, encoding='utf-8',
                                        errors='replace', timeout=250,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
                if result.returncode:
                    raise RuntimeError(result.stdout + result.stderr)
                runs[label].append(json.loads(output.read_text(encoding='utf-8')))
        comparison = compare(**runs)
        with args.output.open('x', encoding='utf-8') as output:
            json.dump({'runs': runs, 'comparison': comparison}, output)
    print(json.dumps(comparison), flush=True)
    accept(comparison, None if args.regression_only else args.require)


if __name__ == '__main__':
    main()
