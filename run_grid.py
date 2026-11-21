#!/usr/bin/env python3
"""Run independent Cloudy models and save four linear quantities per model."""
import argparse
import csv
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys

# EDIT THE GRID HERE. All radii in this list are INNER radii, in parsecs.
INNER_RADII_PC = [0.5, 1.0, 2.0]
LOG_HYDROGEN_DENSITIES = [2.5, 3.0, 3.5, 4.0]
# Keep the numerical outer boundary from the user's supplied input.
OUTER_RADIUS_LOG_CM = 19.3135  # 6.67036 pc. Use 19.20357 for 5.18 pc.
PC_CM = 3.085677581491367e18
MAX_ZONES = 10000  # Restored from 1000 to avoid the observed premature stop.

MODEL = '''# Independent radius-density model
title G028.320+01.243 low-metallicity cloud model
radius {rin_log_cm:.9f} {rout_log_cm:.9f}
sphere
CMB
blackbody 33000 K
Q(H) 47.97
hden {log_nh:.8f}
abundances GASS10
metals deplete
grains ISM
grains pah
metals and grains 0.4 linear
element carbon isotopes (12, 104) (13, 1)
atom H2
cosmic rays background
stop temperature off
set nend {max_zones}
iterate to convergence
# With this Q(H)/radius setup, absolute selected-line output is linear erg/s.
save line list "co13_luminosity.txt" "13co_lines.dat" emergent absolute last no hash
# Whole-species H2 column, linear cm^-2; no rotational level selector.
save species column density "h2_column.txt" "H2" last no hash
'''


def model_text(radius_pc, log_nh):
    rin_log = math.log10(radius_pc * PC_CM)
    if not (0 < radius_pc * PC_CM < 10**OUTER_RADIUS_LOG_CM):
        raise ValueError('Every inner radius must be positive and below the outer radius.')
    return MODEL.format(rin_log_cm=rin_log, rout_log_cm=OUTER_RADIUS_LOG_CM,
                        log_nh=log_nh, max_zones=MAX_ZONES)


def read_one_value(path):
    """Read a scalar, allowing Cloudy's 'iteration N' record prefix."""
    rows = []
    for raw in path.read_text(errors='replace').splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line or line.startswith('*'):
            continue
        match = re.match(r'^iteration\s+(\d+)\s+(.+)$', line, re.IGNORECASE)
        iteration = int(match.group(1)) if match else None
        payload = match.group(2) if match else line
        try:
            vals = [float(t.replace('D', 'E').replace('d', 'e')) for t in payload.split()]
        except ValueError:
            raise ValueError(f'Unexpected data in {path.name}: {raw!r}')
        if len(vals) != 1:
            raise ValueError(f'{path.name}: expected one value after any iteration prefix; got {raw!r}')
        rows.append((iteration, vals[0]))
    if not rows:
        raise ValueError(f'{path.name}: no result was found')
    if len(rows) > 1:
        if any(i is None for i, _ in rows):
            raise ValueError(f'{path.name}: ambiguous multiple scalar records')
        # Use the last record of the final iteration.
        final_iteration = max(i for i, _ in rows)
        value = [v for i, v in rows if i == final_iteration][-1]
    else:
        value = rows[0][1]
    if not math.isfinite(value) or value < 0:
        raise ValueError(f'{path.name}: invalid linear value {value!r}')
    return value


def collect_result(folder, radius_pc, returncode):
    out = folder / 'model.out'
    if not out.exists():
        raise ValueError('No model.out was created; check console.log.')
    text = out.read_text(errors='replace')
    # Reject the premature-stop conditions actually seen in the uploaded run.
    bad = re.search(r'NZONE reached|stopped for unintended reasons|something went wrong|DISASTER',
                    text, re.IGNORECASE)
    if returncode != 0 or bad:
        raise ValueError(f'Cloudy exit={returncode}; ' + (bad.group(0) if bad else 'check model.out'))
    luminosity = read_one_value(folder / 'co13_luminosity.txt')
    h2_column = read_one_value(folder / 'h2_column.txt')
    # Use the radius rounded exactly as written to the Cloudy input.
    actual_radius_cm = 10**float(f'{math.log10(radius_pc * PC_CM):.9f}')
    f_inner = luminosity / (4 * math.pi * actual_radius_cm**2)
    return f_inner, h2_column


def recollect(root):
    """Recover existing completed runs; never launch Cloudy or alter raw output."""
    folders = sorted(root.glob('model_[0-9][0-9][0-9]'))
    if not folders:
        raise ValueError(f'No model_NNN folders found in {root}')
    result_path = root / 'results_recovered.txt'
    status_path = root / 'recovery_status.txt'
    failures = 0
    with result_path.open('w', newline='') as rf, status_path.open('w', newline='') as sf:
        results = csv.writer(rf, delimiter='\t')
        status = csv.writer(sf, delimiter='\t')
        results.writerow(['inner_radius_pc', 'nH_cm^-3', '13CO_emergent_per_inner_area_erg_cm^-2_s^-1', 'N_H2_cm^-2'])
        status.writerow(['model', 'status', 'details'])
        for folder in folders:
            radius = nh = float('nan')
            try:
                inp = (folder / 'model.in').read_text()
                radius_match = re.search(r'^\s*radius\s+(\S+)', inp, re.MULTILINE | re.IGNORECASE)
                density_match = re.search(r'^\s*hden\s+(\S+)', inp, re.MULTILINE | re.IGNORECASE)
                if not radius_match or not density_match:
                    raise ValueError('Could not read radius/hden from model.in')
                radius = 10**float(radius_match.group(1)) / PC_CM
                nh = 10**float(density_match.group(1))
                log_text = (folder / 'model.out').read_text(errors='replace')
                # The old driver did not save process return codes. Require a
                # completion footer and reject its known failure messages.
                if not re.search(r'Cloudy (?:ends:|exited OK)', log_text, re.IGNORECASE):
                    raise ValueError('No Cloudy completion footer: still running or incomplete')
                f_inner, column = collect_result(folder, radius, 0)
                results.writerow([f'{radius:.8g}', f'{nh:.8e}', f'{f_inner:.8e}', f'{column:.8e}'])
                status.writerow([folder.name, 'RECOVERED', 'No Cloudy rerun; verify warnings in model.out'])
            except (OSError, ValueError, OverflowError) as error:
                failures += 1
                results.writerow([f'{radius:.8g}', f'{nh:.8e}', 'nan', 'nan'])
                status.writerow([folder.name, 'FAILED_OR_INCOMPLETE', str(error)])
    print(f'Recovered existing files only; Cloudy was NOT run.\nResults: {result_path}\nStatus: {status_path}\nUnrecovered: {failures}/{len(folders)}')
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cloudy', default='cloudy', help='Executable name or full path to cloudy.exe')
    parser.add_argument('--output', type=Path, default=Path('radius_density_results'),
                        help='New output folder (existing folders are not overwritten)')
    parser.add_argument('--prepare-only', action='store_true', help='Write inputs without running Cloudy')
    parser.add_argument('--collect-only', action='store_true', help='Recover existing completed outputs without running Cloudy')
    args = parser.parse_args()
    if args.collect_only:
        if args.prepare_only:
            parser.error('--collect-only and --prepare-only cannot be combined')
        try:
            return recollect(args.output.expanduser().resolve())
        except (OSError, ValueError) as error:
            parser.error(str(error))
    executable = None
    if not args.prepare_only:
        # Resolve before changing each model's working directory.
        executable = shutil.which(str(Path(args.cloudy).expanduser()))
        if not executable:
            parser.error('Cloudy was not found. Supply --cloudy /full/path/to/cloudy.exe')
        executable = str(Path(executable).resolve())
    root = args.output.expanduser().resolve()
    if root.exists():
        parser.error(f'{root} already exists. Choose a new --output folder.')
    # Validate settings before creating any output folders.
    for radius in INNER_RADII_PC:
        for log_nh in LOG_HYDROGEN_DENSITIES:
            model_text(radius, log_nh)
    root.mkdir(parents=True)
    total = len(INNER_RADII_PC) * len(LOG_HYDROGEN_DENSITIES)
    failures = 0
    result_path = root / 'results.txt'
    status_path = root / 'run_status.txt'
    with result_path.open('w', newline='') as result_file, status_path.open('w', newline='') as status_file:
        results = csv.writer(result_file, delimiter='\t')
        status = csv.writer(status_file, delimiter='\t')
        results.writerow(['inner_radius_pc', 'nH_cm^-3', '13CO_emergent_per_inner_area_erg_cm^-2_s^-1', 'N_H2_cm^-2'])
        status.writerow(['model', 'inner_radius_pc', 'log10_nH', 'status', 'details'])
        number = 0
        for radius in INNER_RADII_PC:
            for log_nh in LOG_HYDROGEN_DENSITIES:
                number += 1
                folder = root / f'model_{number:03d}'
                folder.mkdir()
                (folder / 'model.in').write_text(model_text(radius, log_nh))
                (folder / '13co_lines.dat').write_text('"^13CO" 2719.67m\n')
                if args.prepare_only:
                    status.writerow([folder.name, radius, log_nh, 'PREPARED', 'Not executed'])
                    continue
                print(f'[{number}/{total}] inner radius={radius:g} pc, log nH={log_nh:g}', flush=True)
                try:
                    with (folder / 'console.log').open('w') as log:
                        completed = subprocess.run([executable, '-r', 'model'], cwd=folder,
                                                   stdout=log, stderr=subprocess.STDOUT, check=False)
                    f_inner, h2_column = collect_result(folder, radius, completed.returncode)
                    results.writerow([f'{radius:g}', f'{10**log_nh:.8e}', f'{f_inner:.8e}', f'{h2_column:.8e}'])
                    status.writerow([folder.name, radius, log_nh, 'OK', ''])
                except (OSError, ValueError) as error:
                    failures += 1
                    results.writerow([f'{radius:g}', f'{10**log_nh:.8e}', 'nan', 'nan'])
                    status.writerow([folder.name, radius, log_nh, 'FAILED', str(error)])
                    print(f'  Failed: {error}', file=sys.stderr, flush=True)
                result_file.flush()
                status_file.flush()
    if args.prepare_only:
        print(f'Prepared {total} inputs in {root}; results.txt contains its header only.')
    else:
        print(f'Results: {result_path}\nStatus: {status_path}\nFailed models: {failures}/{total}')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
