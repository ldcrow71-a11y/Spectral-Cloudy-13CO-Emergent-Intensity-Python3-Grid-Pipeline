# Cloudy 13CO radius and density grid

A Python 3 driver for the G028.320+01.243 Cloudy model. It runs independent models with different inner radii and hydrogen densities, then collects the emergent 13CO J=1–0 emission and H2 column density into a tab-separated text file.

## Requirements

- Python 3; no additional Python packages.
- A working local installation of Cloudy 25. The Cloudy executable and its data files are not included.

## Run the grid

Download this repository using **Code → Download ZIP**, extract it, and open a terminal in the extracted folder. Set the path to your own Cloudy executable:

```sh
python3 run_grid.py --cloudy /full/path/to/cloudy.exe
```

If Cloudy is on your PATH:

```sh
python3 run_grid.py --cloudy cloudy
```

Open `radius_density_results/results.txt` after models complete. Results are flushed after each model, so completed rows can be read while the batch runs. Each model has its own `model_NNN` folder with its input, raw saves, main output, and console log.

## Change the grid

Edit these settings near the top of `run_grid.py`:

```python
INNER_RADII_PC = [0.5, 1.0, 2.0]
LOG_HYDROGEN_DENSITIES = [2.5, 3.0, 3.5, 4.0]
OUTER_RADIUS_LOG_CM = 19.3135
```

The defaults produce 12 sequential models. Density inputs are log10 hydrogen-nuclei densities in cm^-3. The outer radius stays fixed at approximately 6.67 pc; use `19.20357` for approximately 5.18 pc. Each inner radius must be smaller than the outer radius.

The model keeps the specified radiation field, 0.4 metal/dust scale, 104:1 carbon isotope weights, cosmic rays, and spherical geometry. The numerical zone cap is 10000. See the generated `model.in` files for the full inputs.

## Output and normalization

All four result columns contain **linear values**, not logarithms:

| Column | Meaning | Units |
| --- | --- | --- |
| `inner_radius_pc` | Model inner radius | pc |
| `nH_cm^-3` | Total hydrogen-nuclei density, not H2 density | cm^-3 |
| `13CO_emergent_per_inner_area_erg_cm^-2_s^-1` | Emergent line luminosity divided by that model's inner spherical area | erg cm^-2 s^-1 |
| `N_H2_cm^-2` | Model radial H2 column, not a projected disk average | cm^-2 |

For this luminosity-driven model, the selected-line save supplies the absolute emergent luminosity in erg/s. The script calculates:

```text
F_inner = L_13CO / (4 * pi * R_inner_cm**2)
```

This retains Cloudy's inner-area normalization. It is not yet a telescope flux, an intensity per steradian, or an integrated brightness temperature in K km/s. Comparing with observations requires a separate geometry and averaging calculation.

## Prepare, rerun, or recover

Prepare the model inputs without running Cloudy:

```sh
python3 run_grid.py --prepare-only --output prepared_models
```

Run a new batch in a separate folder:

```sh
python3 run_grid.py --cloudy /full/path/to/cloudy.exe --output trial_02
```

Existing batch folders are not overwritten by a new run. Recover results from existing model outputs without rerunning Cloudy:

```sh
python3 run_grid.py --collect-only --output radius_density_results
```

Recovery writes `results_recovered.txt` and `recovery_status.txt`, preserving the original raw files and original result/status tables. It accepts scalar rows prefixed with `iteration N` and selects the final iteration. Missing, unfinished, or known-failed models receive `nan`. Recovery can be repeated after more models finish.

## Check run quality

Inspect `run_status.txt` and each model's `model.out` and `console.log`. Known failures, including the zone limit, are rejected. Review warnings in accepted runs too; a successful exit does not establish a good observational fit.

The driver was checked with simulated Cloudy-format outputs, and the 12-model input preparation was checked without executing Cloudy. A real Cloudy calculation has not been run in the code-preparation environment. Confirm units and convergence using your local runs.

`example_model.in` shows one model with a 1 pc inner radius and log10 nH = 3. The accompanying `13co_lines.dat` contains its selected transition. The driver generates both files automatically for every model.

Generated batch folders and large Cloudy outputs are excluded from Git by `.gitignore`. Preserve research results separately as needed.
